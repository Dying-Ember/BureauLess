#!/usr/bin/env node

import fs from 'node:fs';
import path from 'node:path';
import { spawn, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const desktopDir = path.resolve(__dirname, '..');
const repoRoot = path.resolve(desktopDir, '..', '..');

function isExecutable(filePath) {
  try {
    fs.accessSync(filePath, fs.constants.X_OK);
    return true;
  } catch {
    return false;
  }
}

function resolveLocalElectron() {
  const electronDir = path.join(repoRoot, 'node_modules', 'electron');
  const pathFile = path.join(electronDir, 'path.txt');

  if (!fs.existsSync(pathFile)) {
    return null;
  }

  const relativeExecutable = fs.readFileSync(pathFile, 'utf8').trim();
  if (!relativeExecutable) {
    return null;
  }

  const executable = path.join(electronDir, 'dist', relativeExecutable);
  return isExecutable(executable) ? executable : null;
}

function resolvePathBinary(command) {
  const result = spawnSync('which', [command], { encoding: 'utf8' });
  if (result.status !== 0) {
    return null;
  }

  const resolved = result.stdout.trim();
  return resolved && isExecutable(resolved) ? resolved : null;
}

function resolveSystemElectron() {
  const fixedCandidates = [
    '/usr/bin/electron',
    '/usr/bin/electron39',
    '/usr/bin/electron38',
    '/usr/lib/electron/electron',
    '/usr/lib/electron39/electron',
    '/usr/lib/electron38/electron',
  ];

  for (const candidate of fixedCandidates) {
    if (isExecutable(candidate)) {
      return candidate;
    }
  }

  const pathCandidates = ['electron', 'electron39', 'electron38'];
  for (const candidate of pathCandidates) {
    const resolved = resolvePathBinary(candidate);
    if (resolved) {
      return resolved;
    }
  }

  return null;
}

function resolveElectronBinary() {
  if (process.env.BUREAULESS_ELECTRON_BIN && isExecutable(process.env.BUREAULESS_ELECTRON_BIN)) {
    return process.env.BUREAULESS_ELECTRON_BIN;
  }

  return resolveLocalElectron() ?? resolveSystemElectron();
}

const electronBinary = resolveElectronBinary();

if (!electronBinary) {
  console.error('Unable to find a working Electron binary.');
  console.error('Tried the local npm install and common system locations.');
  console.error('Hint: run `npm install --include=dev` or set `BUREAULESS_ELECTRON_BIN=/path/to/electron`.');
  process.exit(1);
}

if (process.argv.includes('--print-bin')) {
  console.log(electronBinary);
  process.exit(0);
}

const entryArg = process.argv[2] ?? 'dist/main.js';
const forwardedArgs = process.argv.slice(3);
const entryFile = path.resolve(desktopDir, entryArg);

const child = spawn(electronBinary, [entryFile, ...forwardedArgs], {
  cwd: desktopDir,
  env: process.env,
  stdio: 'inherit',
});

child.on('exit', (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }

  process.exit(code ?? 0);
});
