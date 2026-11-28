#!/usr/bin/env node
import { createHash } from 'node:crypto';
import { constants } from 'node:fs';
import { open, readFile, realpath } from 'node:fs/promises';
import { isAbsolute, relative, resolve, sep } from 'node:path';

const usage = 'Usage: node check-evidence.mjs REGISTER.json EVIDENCE_DIRECTORY';
const args = process.argv.slice(2);
if (args.length === 1 && args[0] === '--help') {
  console.log(usage + '\nReads local evidence, prints review fingerprints and exits 1 for outstanding reviews.');
  process.exit(0);
}
if (args.length !== 2) { console.error(usage); process.exit(2); }

function within(root, path) {
  const rel = relative(root, path);
  return !!rel && rel !== '..' && !rel.startsWith('..' + sep) && !isAbsolute(rel);
}

async function hashEvidence(root, name) {
  if (typeof name !== 'string' || !name || isAbsolute(name) || !within(root, resolve(root, name))) throw Error('invalid evidence path');
  const path = await realpath(resolve(root, name));
  if (!within(root, path)) throw Error('evidence outside root');
  const file = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    if (!(await file.stat()).isFile()) throw Error('expected regular evidence file');
    const hash = createHash('sha256');
    for await (const chunk of file.createReadStream({ autoClose: false })) hash.update(chunk);
    return hash.digest('hex');
  } finally { await file.close(); }
}

async function main() {
  const root = await realpath(args[1]);
  const register = JSON.parse(await readFile(args[0], 'utf8'));
  if (register.version !== 1 || !Array.isArray(register.findings) || !register.findings.length) throw Error('invalid register');
  const seen = new Set();
  const validId = value => typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/.test(value);
  for (const finding of register.findings) {
    if (!validId(finding?.id) || seen.has(finding.id) || !validId(finding.asset) || !Array.isArray(finding.evidence)) throw Error('invalid finding or duplicate ID');
    if (typeof finding.claim !== 'string' || !finding.claim.trim() || typeof finding.criterion !== 'string' || !finding.criterion.trim()) throw Error('expected a claim and retest criterion');
    seen.add(finding.id);
  }
  const hashes = new Map();
  for (const finding of register.findings) {
    const binding = [], issues = [];
    for (const [index, item] of finding.evidence.entries()) {
      if (typeof item?.locator !== 'string' || !item.locator.trim() || !/^[a-f0-9]{64}$/.test(item.sha256)) throw Error('invalid evidence locator or digest');
      try {
        if (!hashes.has(item.file)) hashes.set(item.file, await hashEvidence(root, item.file));
        if (hashes.get(item.file) !== item.sha256) issues.push(`evidence ${index + 1} changed`);
        binding.push(JSON.stringify([item.file, item.locator, item.sha256]));
      } catch (error) {
        issues.push(`evidence ${index + 1} unavailable (${error.code ?? 'invalid source'})`);
      }
    }
    if (!binding.length && !issues.length) issues.push('no evidence bound');
    const report = { finding: finding.id };
    if (!issues.length) {
      const inputs = JSON.stringify([finding.id, finding.asset, finding.claim, finding.criterion, binding.sort()]);
      report.fingerprint = createHash('sha256').update(inputs).digest('hex');
      if (!finding.reviewedAgainst) issues.push('awaiting review');
      else if (report.fingerprint !== finding.reviewedAgainst) issues.push('review predates claim, criterion or evidence binding');
    }
    report.status = issues.length ? issues : ['review matches evidence binding'];
    console.log(JSON.stringify(report));
    if (issues.length) process.exitCode = 1;
  }
}
try { await main(); }
catch (error) { console.error('Cannot check evidence register (' + (error.code ?? (error instanceof SyntaxError ? 'invalid JSON' : error.message)) + ').'); process.exitCode = 2; }
