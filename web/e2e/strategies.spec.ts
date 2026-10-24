import { chartHasMarks, expect, noBadNumbers, openDemoHousehold, openProperty, settle, shot, test } from './helpers';

test('hold vs sell vs 1031: horizon, DST, waterfall, heatmap, no "recommended"', async ({ page, errors }, info) => {
  void errors;
  await openDemoHousehold(page);
  await openProperty(page, 'Maple duplex');
  await page.getByRole('link', { name: 'Hold, sell or 1031' }).click();
  await page.waitForURL(/\/strategies/);
  await settle(page);
  for (const p of ['hold', 'sell', 'exchange']) await expect(page.getByTestId(`path-${p}`)).toBeVisible();
  for (const c of ['chart-wealth', 'chart-deferred', 'chart-waterfall']) await chartHasMarks(page, c);
  await expect(page.getByTestId('strategy-matrix')).toBeVisible();
  const holdWealth = page.getByTestId('path-hold').getByTestId('figure').first();
  const w10 = await holdWealth.innerText();

  // horizon slider: keyboard operable; writes the URL on commit; all three paths change
  await page.getByTestId('horizon-slider').focus();
  for (let i = 0; i < 5; i++) await page.keyboard.press('ArrowRight');
  await expect(page.getByTestId('horizon-value')).toHaveText('15 yrs');
  await expect(page).toHaveURL(/horizon=15/);
  await expect(holdWealth).not.toHaveText(w10);

  // DST toggle: URL state, extra inputs appear, the 1031 path recomputes
  const exWealth = page.getByTestId('path-exchange').getByTestId('figure').first();
  const exBefore = await exWealth.innerText();
  await page.getByLabel('Exchange into a DST').check();
  await expect(page).toHaveURL(/dst=true/);
  await expect(page.getByLabel('DST load (fees)')).toBeVisible();
  await expect(exWealth).not.toHaveText(exBefore);

  // sensitivity grid: 25 strategy runs
  await page.getByTestId('run-sensitivity').click();
  await expect(page.getByTestId('heat-cell')).toHaveCount(25, { timeout: 45_000 });
  await chartHasMarks(page, 'chart-heatmap');
  await noBadNumbers(page);
  expect(await page.locator('body').innerText()).not.toMatch(/recommend/i);
  await shot(page, info, '05-strategies');

  // the whole view is a shareable URL
  const url = page.url();
  await page.goto(url);
  await settle(page);
  await expect(page.getByTestId('horizon-value')).toHaveText('15 yrs');
  await expect(page.getByLabel('Exchange into a DST')).toBeChecked();
});
