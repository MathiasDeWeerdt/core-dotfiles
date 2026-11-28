import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { chmodSync, copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, statSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const scripts = fileURLToPath(new URL('../skills/custom/security-tooling/scripts/', import.meta.url));
const hash = value => createHash('sha256').update(value).digest('hex');
function workspace(t) {
  const root = mkdtempSync(join(tmpdir(), 'security-tooling-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  return root;
}
function run(script, args, env = process.env) {
  const r = spawnSync(process.execPath, [script, ...args], { encoding: 'utf8', env, timeout: 10000 });
  assert.ifError(r.error);
  return r;
}

test('refresh preserves prior good captures, verifies the catalog and isolates a scoped lookup', t => {
  const root = workspace(t);
  const skill = join(root, 'skill');
  mkdirSync(join(skill, 'scripts'), { recursive: true });
  const script = join(skill, 'scripts/refresh-help.mjs');
  copyFileSync(join(scripts, 'refresh-help.mjs'), script);
  const bin = join(root, 'bin');
  mkdirSync(bin);
  const env = { HOME: root, XDG_CACHE_HOME: join(root, 'cache'), PATH: bin };
  function fixture(name, body) {
    writeFileSync(join(bin, name), '#!/bin/sh\n' + body + '\n');
    chmodSync(join(bin, name), 0o755);
  }
  const refresh = (...args) => run(script, args, env);
  const refs = join(env.XDG_CACHE_HOME, 'core-dotfiles', 'security-tooling');
  const manifest = join(refs, 'manifest.json');
  assert.equal(refresh('--check').status, 1);
  assert.equal(existsSync(env.XDG_CACHE_HOME), false);
  const alias = join(root, 'cache-link');
  symlinkSync(skill, alias);
  assert.equal(run(script, [], { ...env, XDG_CACHE_HOME: alias }).status, 1);
  assert.equal(existsSync(join(skill, 'core-dotfiles')), false);
  fixture('jq', 'echo "jq fixture"');
  fixture('openssl', 'echo "openssl fixture"');
  fixture('dpkg-query', 'echo "installed jq 1.0"; echo "config-files openssl 3"; exit 1');
  assert.equal(refresh().status, 0);
  assert.equal(statSync(refs).mode & 0o777, 0o700);
  assert.equal(statSync(manifest).mode & 0o777, 0o600);
  writeFileSync(manifest, '{broken');
  assert.equal(refresh('--check').status, 1);
  assert.equal(refresh().status, 0);
  assert.equal(refresh('--check').status, 0);
  assert.deepEqual(JSON.parse(refresh('--check', 'jq').stdout).packages, { jq: '1.0' });
  assert.equal(refresh('--check', 'tshark').status, 1);
  assert.equal(refresh('--check', 'not-a-tool').status, 2);
  const initial = readFileSync(manifest);
  const old = readFileSync(join(refs, 'help/jq-help.txt'));
  fixture('dpkg-query', 'echo "installed jq 1.1"');
  assert.equal(refresh('--check', 'jq').status, 1);
  assert.equal(refresh('--check', 'openssl').status, 0);
  fixture('jq', 'exit 4');
  assert.equal(refresh().status, 1);
  assert.deepEqual(readFileSync(manifest), initial);
  assert.deepEqual(readFileSync(join(refs, 'help/jq-help.txt')), old);
  rmSync(join(bin, 'jq'));
  assert.equal(refresh().status, 0);
  const historical = JSON.parse(refresh('--check', 'jq').stdout).records[0];
  assert.equal(historical.status, 'historical');
  assert.deepEqual(readFileSync(historical.file), old);
  rmSync(join(bin, 'openssl'));
  const partial = readFileSync(manifest);
  assert.equal(refresh().status, 1);
  assert.deepEqual(readFileSync(manifest), partial);
  fixture('openssl', 'echo "openssl fixture"');
  assert.equal(refresh().status, 0);
  const valid = readFileSync(manifest);
  const current = JSON.parse(valid);
  current.entries = current.entries.filter(e => e.id !== 'jq-help');
  writeFileSync(manifest, JSON.stringify(current));
  assert.ok(JSON.parse(refresh('--check').stdout).damaged.includes('jq-help'));
  writeFileSync(manifest, valid);
  writeFileSync(join(refs, 'index.md'), 'damaged');
  assert.ok(JSON.parse(refresh('--check').stdout).damaged.includes('index.md'));
  writeFileSync(join(refs, 'help/openssl-verify-help.txt'), 'corrupt');
  assert.equal(refresh('--check', 'openssl').status, 1);
  assert.equal(refresh().status, 0);
  assert.equal(refresh('--check').status, 0);
});

test('evidence check distinguishes binding drift, changed bytes, unavailable input and invalid registers', t => {
  const root = workspace(t), evidence = join(root, 'evidence');
  mkdirSync(evidence);
  const file = join(evidence, 'cert.txt'), register = join(root, 'register.json');
  const body = 'synthetic certificate metadata\n';
  writeFileSync(file, body);
  const item = { file: 'cert.txt', locator: 'line 1', sha256: hash(body) };
  const finding = { id: 'F1', asset: 'service-A', claim: 'The certificate has expired.', criterion: 'A valid certificate at retest time.', evidence: [item] };
  function check(findings = [finding]) {
    writeFileSync(register, JSON.stringify({ version: 1, findings }));
    return run(join(scripts, 'check-evidence.mjs'), [register, evidence]);
  }
  let result = check();
  assert.equal(result.status, 1);
  finding.reviewedAgainst = JSON.parse(result.stdout).fingerprint;
  assert.equal(check().status, 0);
  const changedClaim = { ...finding, claim: 'The certificate is current.' };
  assert.match(check([changedClaim]).stdout, /predates/);
  item.locator = 'line 2';
  assert.match(check().stdout, /predates/);
  writeFileSync(file, 'changed bytes');
  result = check();
  assert.match(result.stdout, /changed/);
  assert.ok(!result.stdout.includes('fingerprint'));
  rmSync(file);
  assert.match(check().stdout, /unavailable/);
  symlinkSync(register, file);
  assert.match(check().stdout, /unavailable/);
  assert.equal(check([finding, finding]).status, 2);
});
