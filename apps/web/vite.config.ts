import fs from 'node:fs';
import path from 'node:path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const repoRoot = path.resolve(__dirname, '../..');
const apiUrlFile = path.join(repoRoot, '.bureauless-api-url');
const apiTarget = resolveApiTarget();

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': apiTarget,
    },
  },
});

function resolveApiTarget(): string {
  if (process.env.BUREAULESS_API_URL) {
    return process.env.BUREAULESS_API_URL;
  }
  if (fs.existsSync(apiUrlFile)) {
    const value = fs.readFileSync(apiUrlFile, 'utf8').trim();
    if (value) {
      return value;
    }
  }
  return 'http://127.0.0.1:8000';
}
