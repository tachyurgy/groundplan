import AxeBuilder from '@axe-core/playwright';
import { expect, test as base, type Page, type TestInfo } from '@playwright/test';
import { mkdirSync, writeFileSync, appendFileSync, existsSync, readFileSync } from 'node:fs';
import { randomUUID } from 'node:crypto';
import { dirname, join } from 'node:path';

/**
 * Workspace ids come from a small per-worker pool (e2e/.ws-pool/<target>-<slot>.txt) and are reset
 * through POST /workspace/reset before every test: a freshly seeded sandbox each time, without
 * provisioning a new workspace per test (the APIs allow 30 new workspaces per client IP per day).
 */
export function poolWorkspace(info: TestInfo, slot = 'shared'): string {
  const { target } = info.project.metadata as { target?: string };
  const file = join('e2e', '.ws-pool', `${target ?? 'x'}-${slot}.txt`);
  mkdirSync(dirname(file), { recursive: true });
  if (existsSync(file)) return readFileSync(file, 'utf8').trim();
  const id = randomUUID();
  writeFileSync(file, id);
  return id;
}

/**
 * Read-only journeys share one workspace per target (slot 'shared', never mutated, reset once per run
 * in global setup). Tests that change data pass their own slot and get a reset first.
 */
export async function useWorkspace(page: Page, info: TestInfo, slot = 'shared') {
  const id = poolWorkspace(info, slot);
  const { target, url } = info.project.metadata as { target?: string; url?: string };
  await page.addInitScript((ws) => {
    try {
      localStorage.setItem('gp.workspace', ws);
    } catch {
      /* ignore */
    }
  }, id);
  if (slot !== 'shared' && target && target !== 'mock' && url) {
    const r = await page.request.post(`${url}/api/v1/workspace/reset`, { headers: { 'X-Workspace-Id': id } });
    expect(r.status(), `reset workspace ${id}: ${await r.text().catch(() => '')}`).toBe(200);
  }
  return id;
}

/** Console errors and uncaught exceptions are test failures (network 404s from optional endpoints excepted). */
export const test = base.extend<{ errors: string[]; workspace: string }>({
  workspace: [
    async ({ page }, use, info) => {
      await use(await useWorkspace(page, info));
    },
    { auto: true },
  ],
  errors: async ({ page }, use) => {
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));
    page.on('console', (m) => {
      if (m.type() !== 'error') return;
      const t = m.text();
      if (/Failed to load resource: the server responded with a status of (404|409|422)/.test(t)) return;
      errors.push(`console: ${t}`);
    });
    page.on('response', (r) => {
      if (r.status() >= 500 && r.url().includes('/api/')) errors.push(`HTTP ${r.status()} ${r.url()}`);
    });
    await use(errors);
    expect(errors, 'no console errors, page errors or 5xx').toEqual([]);
  },
});
export { expect };

export const meta = (info: TestInfo) => info.project.metadata as { target: string; viewport: string; url: string };
export const isPhone = (info: TestInfo) => ['iphone', 'android'].includes(meta(info).viewport);

export async function dismissWelcome(page: Page) {
  const b = page.getByRole('button', { name: 'Got it' });
  if (await b.isVisible().catch(() => false)) await b.click();
}

/** Wait until the app shell rendered and no skeletons / pending routes remain. */
export async function settle(page: Page) {
  await page.waitForLoadState('domcontentloaded');
  await expect(page.locator('main#main')).toBeVisible();
  await expect(page.locator('main h1').first()).toBeVisible();
  await expect(page.locator('[role=status][aria-label=Loading]')).toHaveCount(0);
  await page.waitForTimeout(250);
}

export async function noHorizontalScroll(page: Page) {
  const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(over, 'no horizontal page scroll').toBeLessThanOrEqual(0);
}

/** axe: zero serious or critical violations. Results appended to e2e/.results/axe.jsonl for the summary. */
export async function axe(page: Page, info: TestInfo, name: string) {
  const r = await new AxeBuilder({ page: page as never }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
  const bad = r.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
  const file = join('e2e', '.results', 'axe.jsonl');
  mkdirSync(dirname(file), { recursive: true });
  appendFileSync(
    file,
    JSON.stringify({
      project: info.project.name,
      page: name,
      serious: bad.filter((v) => v.impact === 'serious').length,
      critical: bad.filter((v) => v.impact === 'critical').length,
      ids: bad.map((v) => v.id),
    }) + '\n',
  );
  expect(
    bad.map(
      (v) =>
        `${v.id}: ${v.help} (${v.nodes.length}) ${v.nodes
          .slice(0, 2)
          .map((n) => n.target.join(' '))
          .join(' | ')}`,
    ),
  ).toEqual([]);
}

/** Full-page JPEG into e2e/screenshots/<target>/<viewport>/<name>.jpg (gitignored; feeds the contact sheet). */
export async function shot(page: Page, info: TestInfo, name: string) {
  const { target, viewport } = meta(info);
  const path = join('e2e', 'screenshots', target, viewport, `${name}.jpg`);
  mkdirSync(dirname(path), { recursive: true });
  await page.screenshot({ path, fullPage: true, type: 'jpeg', quality: 72, animations: 'disabled' });
  writeFileSync(path + '.json', JSON.stringify({ url: page.url(), title: await page.title() }));
}

/** Numbers on screen must be real: no NaN, undefined, Infinity. */
export async function noBadNumbers(page: Page) {
  const text = await page.locator('main').innerText();
  expect(text).not.toMatch(/\bNaN\b|\bundefined\b|Infinity|\[object Object\]/);
}

/** At least one non-empty SVG path inside the chart figure. */
export async function chartHasMarks(page: Page, testId: string) {
  const fig = page.getByTestId(testId).first();
  await expect(fig).toBeVisible();
  await expect
    .poll(async () =>
      fig.evaluate((el) => {
        const marks = el.querySelectorAll('svg path[d], svg rect[width], [data-testid=tax-layer-bar] > div, [data-testid=heat-cell]');
        return [...marks].filter((m) => {
          const d = m.getAttribute('d');
          if (d !== null) return d.length > 8 && !/NaN/.test(d);
          const w = Number(m.getAttribute('width') ?? (m as HTMLElement).getBoundingClientRect().width);
          return w > 0;
        }).length;
      }),
    )
    .toBeGreaterThan(0);
}

/** From the household list, open the demo household and return its id (ids differ per stack). */
export async function openDemoHousehold(page: Page) {
  await page.goto('/');
  await settle(page);
  await dismissWelcome(page);
  await page
    .getByRole('link', { name: /Okafor-Lindqvist/ })
    .filter({ visible: true })
    .first()
    .click();
  await page.waitForURL(/\/households\/[^/]+$/);
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Okafor-Lindqvist');
  await settle(page);
  return page.url().split('/households/')[1];
}

/** Open a property by nickname from the dashboard; returns its id. */
export async function openProperty(page: Page, nickname: string) {
  await page.getByTestId('property-card').filter({ hasText: nickname }).getByRole('link', { name: nickname }).click();
  await page.waitForURL(/\/properties\/[^/?]+/);
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(nickname);
  await settle(page);
  return new URL(page.url()).pathname.split('/')[2];
}
