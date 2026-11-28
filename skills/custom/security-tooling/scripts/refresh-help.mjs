#!/usr/bin/env node
import { spawnSync } from 'node:child_process';
import { accessSync, constants, existsSync, mkdirSync, mkdtempSync, openSync, closeSync, readFileSync, realpathSync, renameSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { delimiter, dirname, isAbsolute, join, relative, resolve } from 'node:path';
import { homedir } from 'node:os';
import { stripVTControlCharacters } from 'node:util';
import { createHash } from 'node:crypto';

process.umask(0o077);
const cache = process.env.XDG_CACHE_HOME;
const references = join(cache && isAbsolute(cache) ? cache : join(homedir(), '.cache'), 'core-dotfiles', 'security-tooling');
const manifestPath = join(references, 'manifest.json');
function locate(names) {
  for (const name of names) {
    for (const dir of (process.env.PATH ?? '').split(delimiter)) {
      if (!isAbsolute(dir)) continue;
      const candidate = resolve(dir, name);
      try {
        accessSync(candidate, constants.X_OK);
        if (statSync(candidate).isFile()) return candidate;
      } catch {}
    }
  }
  return null;
}

function fingerprint(path) {
  if (!path) return null;
  const stat = statSync(path);
  return { path, size: stat.size, mtimeMs: stat.mtimeMs };
}

function run(path, argv) {
  const result = spawnSync(path, argv, {
    encoding: 'utf8', timeout: 15000, killSignal: 'SIGKILL', maxBuffer: 4 * 1024 * 1024,
    stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, SEMGREP_SEND_METRICS: 'off', SEMGREP_ENABLE_VERSION_CHECK: '0', SYFT_CHECK_FOR_APP_UPDATE: 'false', NO_COLOR: '1', TERM: 'dumb', COLUMNS: '120', PAGER: 'cat' },
  });
  return {
    exitCode: result.status,
    stdout: result.stdout ?? '',
    error: result.error?.message ?? null,
    output: stripVTControlCharacters([result.stdout, result.stderr].filter(Boolean).join('\n')).trimEnd() + '\n',
  };
}

// Each entry has fixed arguments and reads help or version information only.
const jobs = [
  ['capinfos-help', 'capinfos', ['-h']],
  ['tshark-help', 'tshark', ['-h']],
  ['nmap-version', 'nmap', ['--version']],
  ['openssl-x509-help', 'openssl', ['x509', '-help']],
  ['openssl-verify-help', 'openssl', ['verify', '-help']],
  ['jq-help', 'jq', ['--help']],
  ['curl-version', 'curl', ['--version']],
  ['xmllint-version', 'xmllint', ['--version']],
  ['syft-help', 'syft', ['scan', '--help']],
  ['trivy-sbom-help', 'trivy', ['sbom', '--help']],
  ['oscap-info-help', 'oscap', ['info', '--help']],
  ['semgrep-scan-help', 'semgrep', ['scan', '--help']],
];

const usage = 'Usage: node refresh-help.mjs [--check [tool-or-reference] | --help]';
const [action, selection, ...extra] = process.argv.slice(2);
if (action === '--help' && !selection && !extra.length) {
  console.log(usage + '\nNo arguments refreshes local help. --check reads the pack. No target input.');
  process.exit(0);
}
const selectedJobs = jobs.filter(([id, tool]) => !selection || selection === id || selection === tool);
if ((action !== undefined && action !== '--check') || extra.length || !selectedJobs.length || selection === '') {
  console.error(usage);
  process.exit(2);
}

const digest = value => createHash('sha256').update(value).digest('hex');
const same = (left, right) => JSON.stringify(left) === JSON.stringify(right);
const fileFor = id => `help/${id}.txt`;
function read(path) {
  try { return readFileSync(path, 'utf8'); }
  catch (error) { if (error.code !== 'ENOENT') throw error; return null; }
}

function packageNames(tool, debian) {
  if (tool === 'capinfos') return [debian ? 'wireshark-common' : 'wireshark-cli'];
  if (tool === 'tshark') return [debian ? 'tshark' : 'wireshark-cli'];
  if (tool === 'xmllint') return [debian ? 'libxml2-utils' : 'libxml2'];
  if (tool === 'oscap') return [debian ? 'openscap-scanner' : 'openscap'];
  if (tool === 'semgrep' && !debian) return ['semgrep-bin'];
  return [tool];
}

// Consult only the local package database. A binary can also come from outside it.
function inventory(scope) {
  const preferDpkg = existsSync('/etc/debian_version') && !existsSync('/etc/arch-release');
  const manager = locate(preferDpkg ? ['dpkg-query', 'pacman'] : ['pacman', 'dpkg-query']);
  const debian = manager ? manager.endsWith('/dpkg-query') : preferDpkg;
  const packages = [...new Set(scope.flatMap(tool => packageNames(tool, debian)))].sort();
  const versions = {};
  if (manager) {
    const argv = debian ? ['-W', '-f=${db:Status-Status} ${Package} ${Version}\n', ...packages] : ['-Q', ...packages];
    const result = run(manager, argv);
    // Both managers can return 1 with valid rows when an optional package is absent.
    if (result.error || ![0, 1].includes(result.exitCode)) throw Error('Local package inventory failed.');
    for (const line of result.stdout.split('\n')) {
      const fields = line.trim().split(/\s+/);
      if (debian && fields.shift() !== 'installed') continue;
      const [name, version] = fields;
      if (packages.includes(name) && version) versions[name] = version;
    }
  }
  return { versions, installed: Object.fromEntries(scope.map(tool => [tool, fingerprint(locate([tool]))])), debian };
}

function renderIndex(manifest) {
  const lines = [
    '# Local command reference index', '', `Checked on the capture host at ${manifest.capturedAt}.`, '',
    'Use the installed skill’s refresh-help.mjs with --check ID before reading a snapshot. Historical rows retain the last good output for a tool that is now absent. Missing rows have no verified syntax.', '',
    '## Local package inventory', '', '```text', manifest.packageVersions, '```', '',
    '| Reference | Capture status | Command at capture |', '| --- | --- | --- |',
    ...manifest.entries.map(e => `| [${e.id}](${e.file}) | ${e.status} | \`${[e.path ?? e.tool, ...e.argv].join(' ')}\` |`),
    '', 'The local package database, executable metadata and file digests cover common changes. Check the actual host for different plugins, configurations or binaries.', '',
  ];
  return lines.join('\n');
}

function validEntry(entry, [id, tool, argv]) {
  return entry?.id === id && entry.tool === tool && same(entry.argv, argv) &&
    entry.file === fileFor(id) && ['ok', 'missing', 'historical'].includes(entry.status) &&
    (entry.status === 'missing' ? entry.path === null : typeof entry.path === 'string') &&
    /^[a-f0-9]{64}$/.test(entry.sha256) && typeof entry.capturedAt === 'string';
}

function check(manifest, host) {
  if (manifest?.schema !== 2 || !Array.isArray(manifest.entries) || !manifest.installed || !manifest.packages) {
    throw Error('Reference manifest is incomplete or uses an older format. Run the local refresh.');
  }
  const changed = [], damaged = [], incomplete = [], records = [];
  for (const tool of Object.keys(host.installed)) {
    if (!same(host.installed[tool], manifest.installed[tool]) ||
        packageNames(tool, host.debian).some(name => host.versions[name] !== manifest.packages[name])) changed.push(tool);
  }
  for (const job of selectedJobs) {
    const [id, tool] = job;
    const matches = manifest.entries.filter(e => e?.id === id);
    const entry = matches[0];
    if (matches.length !== 1 || !validEntry(entry, job)) { damaged.push(id); continue; }
    const content = read(join(references, fileFor(id)));
    if (content === null || digest(content) !== entry.sha256 ||
        (entry.status === 'ok' ? entry.path !== manifest.installed[tool]?.path : !!manifest.installed[tool])) damaged.push(id);
    if (entry.status !== 'ok') incomplete.push(`${id}: ${entry.status}`);
    records.push({ id, status: entry.status, file: join(references, entry.file), capturedAt: entry.capturedAt, path: entry.path });
  }
  if (!selection) {
    const validLayout = manifest.entries.length === jobs.length && jobs.every((job, i) => validEntry(manifest.entries[i], job));
    if (!validLayout) damaged.push('manifest inventory');
    const index = read(join(references, 'index.md'));
    if (index === null || (validLayout && index !== renderIndex(manifest))) damaged.push('index.md');
  }
  const ok = records.filter(record => record.status === 'ok').length;
  const result = { capturedAt: manifest.capturedAt, ok, changed, damaged, incomplete };
  if (selection) Object.assign(result, { packages: host.versions, records });
  console.log(JSON.stringify(result, null, 2));
  if (!ok || changed.length || damaged.length || (selection && incomplete.length)) process.exitCode = 1;
}

function refresh(previous, host) {
  const capturedAt = new Date().toISOString();
  const entries = [], updates = new Map(), errors = [];
  for (const [id, tool, argv] of jobs) {
    const file = fileFor(id), path = host.installed[tool]?.path ?? null;
    const old = previous?.entries?.find(e => e?.id === id && e.file === file && e.tool === tool && same(e.argv, argv));
    const existing = read(join(references, file));
    const intact = old && existing !== null && digest(existing) === old.sha256;
    const oldTime = old?.capturedAt ?? previous?.capturedAt;
    if (!path && intact && ['ok', 'historical'].includes(old.status)) {
      entries.push({ ...old, status: 'historical', capturedAt: oldTime });
      continue;
    }
    const result = path ? run(path, argv) : null;
    if (result && (result.error || result.exitCode !== 0 || !result.output.trim())) {
      errors.push(id);
      continue;
    }
    const status = path ? 'ok' : 'missing';
    const command = [path ?? tool, ...argv].join(' ');
    const body = [`Command: ${command}`, `Status: ${status}`, `Exit code: ${result?.exitCode ?? 'none'}`, '', '',
      result?.output ?? `Executable not found in PATH. Checked: ${tool}. No local syntax validated.\n`].join('\n');
    // A missing manifest can be rebuilt from available tools and known empty notices.
    // Never replace an orphaned real capture with an availability notice.
    const emptyNotice = existing?.startsWith('Captured: ') && existing.slice(existing.indexOf('\n') + 1) === body;
    if (!path && !intact && ((existing !== null && !emptyNotice) || ['ok', 'historical'].includes(old?.status))) {
      errors.push(id + ' (restore the prior manifest or a trusted copy of this unavailable capture)');
      continue;
    }
    const reuse = intact && oldTime && existing === `Captured: ${oldTime}\n${body}`;
    const time = reuse ? oldTime : capturedAt;
    const content = `Captured: ${time}\n${body}`;
    if (!reuse) updates.set(file, content);
    entries.push({ id, tool, argv, path, status, exitCode: result?.exitCode ?? null, file, sha256: digest(content), capturedAt: time });
  }
  if (errors.length) throw Error('Refresh stopped before writing. Failed captures: ' + errors.join(', '));
  const ok = entries.filter(e => e.status === 'ok').length;
  if (!ok) throw Error('No usable local help found. Previous references preserved.');
  const packageVersions = Object.entries(host.versions).map(([k, v]) => `${k} ${v}`).join('\n') || 'Local package versions unavailable.';
  const manifest = { schema: 2, capturedAt, installed: host.installed, packages: host.versions, packageVersions, entries };
  updates.set('index.md', renderIndex(manifest));
  updates.set('manifest.json', JSON.stringify(manifest, null, 2) + '\n');
  const stage = mkdtempSync(join(references, '.refresh-'));
  try {
    mkdirSync(join(stage, 'help'));
    mkdirSync(join(references, 'help'), { recursive: true });
    for (const [file, content] of updates) writeFileSync(join(stage, file), content);
    // Readers using --check share this directory lock. Write the manifest last.
    for (const file of updates.keys()) renameSync(join(stage, file), join(references, file));
  } finally { rmSync(stage, { recursive: true, force: true }); }
  console.log(JSON.stringify({ capturedAt, ok, missing: entries.filter(e => e.status === 'missing').map(e => e.id),
    historical: entries.filter(e => e.status === 'historical').map(e => e.id), index: join(references, 'index.md') }, null, 2));
}

function main() {
  if (action === '--check' && !existsSync(manifestPath)) throw Error('No local help cache. Run refresh-help.mjs first.');
  if (action !== '--check') {
    // Resolve existing ancestors before creating anything, including through a cache symlink.
    let ancestor = references;
    while (!existsSync(ancestor)) ancestor = dirname(ancestor);
    const destination = join(realpathSync(ancestor), relative(ancestor, references));
    const skill = realpathSync(new URL('..', import.meta.url));
    for (let dir = destination; dir !== dirname(dir); dir = dirname(dir)) {
      if (dir === skill || existsSync(join(dir, '.git'))) throw Error('Choose a private cache outside the skill and Git checkout.');
    }
    mkdirSync(references, { recursive: true, mode: 0o700 });
  }
  // flock on the inherited directory descriptor is released by the OS on exit.
  const fd = openSync(references, 'r');
  try {
    const lock = spawnSync('/usr/bin/flock', [action === '--check' ? '-s' : '-x', '-n', '3'], { stdio: ['ignore', 'ignore', 'inherit', fd] });
    if (lock.error) throw Error('Cannot lock references. Linux util-linux flock is required.');
    if (lock.status !== 0) throw Error('Reference pack is busy. Retry after the other operation finishes.');
    const raw = read(manifestPath);
    let previous;
    try { previous = raw === null ? null : JSON.parse(raw); }
    catch {
      if (action === '--check') throw Error('Reference manifest is invalid JSON. Run the local refresh.');
    }
    if (!Array.isArray(previous?.entries) && action !== '--check') previous = null;
    const host = inventory([...new Set(selectedJobs.map(([, tool]) => tool))]);
    if (action === '--check') check(previous, host);
    else refresh(previous, host);
  } finally { closeSync(fd); }
}
try { main(); }
catch (error) { console.error(error.message); process.exitCode = 1; }
