/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react, { reactCompilerPreset } from '@vitejs/plugin-react';
import babel from '@rolldown/plugin-babel';
import tailwindcss from '@tailwindcss/vite';
import { readFileSync } from 'node:fs';
import type { Plugin } from 'vite';

/** Mock mode only: serve and emit MSW's service-worker script, so production builds never ship it. */
function mswWorker(enabled: boolean): Plugin {
  const src = () => readFileSync('mock-public/mockServiceWorker.js', 'utf8');
  return {
    name: 'gp-msw-worker',
    configureServer(server) {
      if (!enabled) return;
      server.middlewares.use('/mockServiceWorker.js', (_req, res) => {
        res.setHeader('Content-Type', 'text/javascript');
        res.end(src());
      });
    },
    generateBundle() {
      if (enabled) this.emitFile({ type: 'asset', fileName: 'mockServiceWorker.js', source: src() });
    },
  };
}

// `--mode mock` = MSW fixture backend in the browser (VITE_MOCK=1 in .env.mock).
export default defineConfig(({ mode }) => ({
  plugins: [react(), babel({ presets: [reactCompilerPreset()] }), tailwindcss(), mswWorker(mode === 'mock')],
  server: {
    port: 5173,
    strictPort: true,
    proxy: { '/api': { target: process.env.API_ORIGIN ?? 'http://localhost:8000', changeOrigin: true } },
  },
  preview: { port: 4173, strictPort: true, proxy: { '/api': { target: process.env.API_ORIGIN ?? 'http://localhost:8000', changeOrigin: true } } },
  build: {
    sourcemap: false,
    target: 'es2022',
    chunkSizeWarningLimit: 900,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    include: ['src/**/*.test.{ts,tsx}'],
  },
}));
