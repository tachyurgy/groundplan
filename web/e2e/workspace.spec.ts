import { expect, openDemoHousehold, settle, test } from './helpers';

test('two browsers get separate workspaces; reset restores the demo data', async ({ browser, errors }) => {
  void errors;
  const a = await (await browser.newContext()).newPage();
  const b = await (await browser.newContext()).newPage();
  const hhA = await openDemoHousehold(a);
  await openDemoHousehold(b);
  const idA = await a.evaluate(() => localStorage.getItem('gp.workspace'));
  const idB = await b.evaluate(() => localStorage.getItem('gp.workspace'));
  expect(idA).toMatch(/^[0-9a-f-]{36}$/);
  expect(idA).not.toBe(idB);

  await a.goto(`/households/${hhA}/documents`);
  await settle(a);
  const open = await a.getByTestId('finding').count();
  expect(open).toBeGreaterThan(0);
  await a.getByTestId('finding').first().getByTestId('dismiss').click();
  await expect(a.getByTestId('finding')).toHaveCount(open - 1);

  // B never sees A's change
  const hhB = new URL(b.url()).pathname.split('/')[2];
  await b.goto(`/households/${hhB}/documents`);
  await settle(b);
  await expect(b.getByTestId('finding')).toHaveCount(open);

  // reset A
  await a.getByTestId('reset-open').click();
  await a.getByTestId('reset-confirm').click();
  await a.waitForURL((u) => u.pathname === '/');
  const hhA2 = await openDemoHousehold(a);
  await a.goto(`/households/${hhA2}/documents`);
  await settle(a);
  await expect(a.getByTestId('finding')).toHaveCount(open);
  await a.context().close();
  await b.context().close();
});
