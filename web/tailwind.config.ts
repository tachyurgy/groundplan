import type { Config } from 'tailwindcss';

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Inter"', 'ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      colors: {
        ink: {
          950: '#0b1220',
          900: '#111a2e',
          700: '#2b3650',
          500: '#5b6478',
          400: '#7c8497',
          300: '#a7adbb',
          200: '#d6d9e0',
          100: '#eceef2',
          50: '#f6f7f9',
        },
        brand: {
          700: '#163a5f',
          600: '#1f4f7f',
          500: '#2a6aa8',
          100: '#e3eef8',
          50: '#f1f6fb',
        },
        pos: { 600: '#157347', 100: '#e4f3ea' },
        neg: { 600: '#b42318', 100: '#fbe9e7' },
        est: { 600: '#9a6700', 100: '#fff4d6' },
        blk: { 600: '#7a1f1f', 100: '#fde2e2' },
      },
      boxShadow: {
        card: '0 1px 2px rgba(11,18,32,0.06), 0 0 0 1px rgba(11,18,32,0.06)',
        drawer: '-12px 0 40px rgba(11,18,32,0.14)',
      },
    },
  },
  plugins: [],
} satisfies Config;
