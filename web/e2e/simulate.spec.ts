import { chartHasMarks, expect, noBadNumbers, settle, shot, test } from './helpers';

test('simulate: add an event and the fan chart re-renders', async ({ page, errors }, info) => {
  void errors;
  await page.goto('/simulate');
  await settle(page);
  await chartHasMarks(page, 'chart-fan');
  await chartHasMarks(page, 'chart-taxes');
  await chartHasMarks(page, 'chart-equity-debt-sim');
  const rows = await page.getByTestId('event-row').count();
  const median = page.getByTestId('sim-kpi').nth(1);
  await expect(median).toHaveText(/\$/);
  const before = await median.innerText();
  const sim = page.waitForResponse((r) => r.url().includes('/simulate') && r.request().method() === 'POST');
  await page.getByTestId('add-event').click();
  await expect(page.getByTestId('event-row')).toHaveCount(rows + 1);
  expect((await sim).status()).toBe(200);
  await expect(median).not.toHaveText(before); // buying another rental changes the outcome
  await chartHasMarks(page, 'chart-fan');
  await noBadNumbers(page);
  await shot(page, info, '08-simulate');
});
