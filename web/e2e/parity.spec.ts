import { expect, test } from '@playwright/test';
import { dismissWelcome, poolWorkspace, settle } from './helpers';

const PY = process.env.E2E_PYTHON_URL!;
const GO = process.env.E2E_GO_URL!;

async function headline(page: import('@playwright/test').Page) {
  const kpis = page.getByTestId('kpi');
  await expect(kpis).toHaveCount(5);
  return Object.fromEntries(
    await Promise.all([0, 1, 2, 3, 4].map(async (i) => [await kpis.nth(i).locator('.label').innerText(), await kpis.nth(i).getByTestId('figure').innerText()])),
  );
}

test('the same property shows identical headline figures on the Python and Go stacks (via the twin link)', async ({ page }, info) => {
  // one pooled workspace id, freshly reset on both stacks (separate databases, same seed)
  const ws = poolWorkspace(info, 'parity');
  await page.addInitScript((id) => localStorage.setItem('gp.workspace', id), ws);
  for (const base of [PY, GO]) expect((await page.request.post(`${base}/api/v1/workspace/reset`, { headers: { 'X-Workspace-Id': ws } })).status()).toBe(200);
  await page.goto(`${PY}/`);
  await settle(page);
  await dismissWelcome(page);
  await page
    .getByRole('link', { name: /Okafor-Lindqvist/ })
    .first()
    .click();
  await settle(page);
  for (const nick of ['Maple duplex', 'Elm SFR', 'Tahoe cabin', 'Oak condo']) {
    await test.step(nick, async () => {
      await page.goto(`${PY}/`);
      await settle(page);
      await page
        .getByRole('link', { name: /Okafor-Lindqvist/ })
        .first()
        .click();
      await settle(page);
      await page.getByTestId('property-card').filter({ hasText: nick }).getByRole('link', { name: nick }).click();
      await settle(page);
      const py = await headline(page);
      expect(page.url()).toContain(new URL(PY).host);
      const twin = page.getByTestId('twin-link');
      await twin.hover();
      const href = (await twin.getAttribute('href'))!.replace(/^https:\/\/gp-go\.levelbrook\.com/, GO.replace(/\/$/, ''));
      await page.goto(href);
      await page.waitForURL(/\/properties\/[^/]+$/);
      await settle(page);
      await expect(page.getByRole('heading', { level: 1 })).toHaveText(nick);
      const go = await headline(page);
      expect(go, `${nick}: Go headline figures equal Python's`).toEqual(py);
    });
  }
});
