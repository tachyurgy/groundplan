import { defineConfig, devices } from '@playwright/test';

/**
 * Targets: the mock build (always; Vite preview of dist-mock on :4173, MSW in a service worker) and,
 * when their URLs are given, the live stacks: E2E_PYTHON_URL / E2E_GO_URL (or E2E_BASE_URL for one).
 * Every target runs at four viewports. Phones are Desktop Chrome with a phone viewport + touch, so the
 * same Chromium build runs everything (only the cached headless shell is installed on this machine).
 */
const VIEWPORTS = {
  iphone: { width: 390, height: 844, mobile: true },
  android: { width: 360, height: 800, mobile: true },
  tablet: { width: 768, height: 1024, mobile: true },
  desktop: { width: 1440, height: 900, mobile: false },
} as const;

const targets: { name: string; url: string }[] = [];
if (!process.env.E2E_LIVE_ONLY) targets.push({ name: 'mock', url: 'http://localhost:4173' });
if (process.env.E2E_BASE_URL) targets.push({ name: process.env.E2E_TARGET_NAME ?? 'live', url: process.env.E2E_BASE_URL });
if (process.env.E2E_PYTHON_URL) targets.push({ name: 'python', url: process.env.E2E_PYTHON_URL });
if (process.env.E2E_GO_URL) targets.push({ name: 'go', url: process.env.E2E_GO_URL });

const onlyVp = process.env.E2E_VIEWPORTS?.split(',');

export default defineConfig({
  testDir: './e2e',
  globalSetup: './e2e/global-setup.ts',
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: true,
  workers: process.env.CI ? 2 : 4,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list'], ['json', { outputFile: 'e2e/.results/results.json' }]],
  use: { trace: 'retain-on-failure', screenshot: 'only-on-failure', actionTimeout: 15_000, navigationTimeout: 30_000 },
  projects: [
    ...targets.flatMap((t) =>
      Object.entries(VIEWPORTS)
        .filter(([vp]) => !onlyVp || onlyVp.includes(vp))
        .map(([vp, v]) => ({
          name: `${t.name}-${vp}`,
          testIgnore: /parity\.spec\.ts/,
          use: {
            ...devices['Desktop Chrome'],
            baseURL: t.url,
            viewport: { width: v.width, height: v.height },
            hasTouch: v.mobile,
            isMobile: false,
            deviceScaleFactor: 1,
          },
          metadata: { target: t.name, viewport: vp, url: t.url },
        })),
    ),
    ...(process.env.E2E_PYTHON_URL && process.env.E2E_GO_URL ? [{ name: 'parity', testMatch: /parity\.spec\.ts/, use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } }] : []),
  ],
  webServer: process.env.E2E_LIVE_ONLY
    ? undefined
    : { command: 'npm run build:mock && npm run preview:mock', url: 'http://localhost:4173', reuseExistingServer: !process.env.CI, timeout: 180_000 },
});
