/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react, { reactCompilerPreset } from '@vitejs/plugin-react';
import babel from '@rolldown/plugin-babel';
import tailwindcss from '@tailwindcss/vite';

// `--mode mock` = MSW fixture backend in the browser (VITE_MOCK=1 in .env.mock).
// The service-worker script lives in mock-public/ so production builds never ship it.
export default defineConfig(({ mode }) => ({
  plugins: [react(), babel({ presets: [reactCompilerPreset()] }), tailwindcss()],
  publicDir: mode === 'mock' ? 'mock-public' : 'public',
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
