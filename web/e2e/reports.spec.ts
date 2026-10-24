import { readFileSync } from 'node:fs';
import { expect, openDemoHousehold, settle, shot, test } from './helpers';

test('report PDF, fact-sheet tabs and CSV/JSON export', async ({ page, errors }, info) => {
  void errors;
  const hh = await openDemoHousehold(page);
  await page.goto(`/households/${hh}/reports`);
  await settle(page);
  await expect(page.getByTestId('report-preview')).toContainText('Okafor-Lindqvist');

  const [pdfResp, pdf] = await Promise.all([page.waitForResponse((r) => r.url().includes('/report.pdf')), page.waitForEvent('download'), page.getByTestId('report-pdf').click()]);
  expect(pdfResp.status()).toBe(200);
  expect(pdfResp.headers()['content-type']).toContain('application/pdf');
  expect(readFileSync((await pdf.path())!).subarray(0, 5).toString()).toBe('%PDF-');

  await expect(page.getByTestId('factsheet').locator('li').first()).toBeVisible();
  await page.getByRole('tab', { name: 'RightCapital' }).click();
  await expect(page).toHaveURL(/platform=rightcapital/);
  await expect(page.getByTestId('factsheet').filter({ visible: true }).locator('li').first()).toBeVisible();

  const [csvResp, csv] = await Promise.all([page.waitForResponse((r) => r.url().includes('format=csv')), page.waitForEvent('download'), page.getByTestId('export-csv').click()]);
  expect(csvResp.headers()['content-type']).toContain('text/csv');
  const text = readFileSync((await csv.path())!, 'utf8');
  expect(text.split('\n').length).toBeGreaterThan(3);
  expect(text).toMatch(/,/);

  const [json] = await Promise.all([page.waitForEvent('download'), page.getByTestId('export-json').click()]);
  expect(JSON.parse(readFileSync((await json.path())!, 'utf8')).rows.length).toBeGreaterThan(2);
  await shot(page, info, '07-reports');
});
