import { expect, meta, openDemoHousehold, settle, shot, test, useWorkspace } from './helpers';
import type { Page } from '@playwright/test';

const mapleCashFlow = (page: Page) => page.getByTestId('property-card').filter({ hasText: 'Maple duplex' }).locator('[data-testid=figure][data-key="cash_flow.net_annual"]');

/**
 * The demo moment, end to end: upload the 2025 Schedule E sample -> it lands on the existing
 * properties -> Maple duplex goes Blocked on a rent conflict -> resolve it in the queue -> unblocked.
 */
test('upload the 2025 Schedule E: summary, page image, Maple blocked on a rent conflict, resolve, unblocked', async ({ page, errors }, info) => {
  void errors;
  await useWorkspace(page, info, `docs-${meta(info).viewport}`); // this test changes data: its own, freshly reset workspace
  const hh = await openDemoHousehold(page);
  await expect(mapleCashFlow(page)).toBeVisible();
  await expect(mapleCashFlow(page)).not.toHaveAttribute('data-status', 'blocked');

  await page.getByRole('link', { name: 'Documents & reconciliation' }).click();
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Documents and reconciliation');
  await settle(page);
  await expect(page).toHaveURL(new RegExp(`/households/${hh}/documents`));
  // the sample picker runs a shipped PDF through the same upload path as drag and drop
  await page.getByTestId('sample-select').selectOption('2025_schedule_e.pdf');
  await page.getByTestId('sample-upload').click();
  const summary = page.getByTestId('upload-summary');
  await expect(summary).toBeVisible({ timeout: 60_000 });
  await expect(summary).toContainText(/Updated \d+ propert/);
  await expect(summary).toContainText('1 conflict needs review');
  const viewer = page.getByTestId('doc-viewer');
  await expect(viewer).toContainText('2025_schedule_e.pdf');
  await expect(viewer.locator('[data-testid=pdf-page] canvas')).toBeVisible({ timeout: 20_000 });
  await expect(viewer.locator('[data-testid=pdf-page] button').first()).toBeVisible();
  await expect(viewer.getByTestId('extracted-fields').locator('li').first()).toBeVisible();
  await shot(page, info, '06-documents-upload');

  // the dashboard now shows Maple's cash flow Blocked
  await page.getByRole('link', { name: 'Portfolio', exact: true }).click();
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Okafor-Lindqvist');
  await settle(page);
  await expect(mapleCashFlow(page)).toHaveAttribute('data-status', 'blocked');

  // resolve it: pick the value from the uploaded return
  await page.getByRole('link', { name: 'Documents & reconciliation' }).click();
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Documents and reconciliation');
  await settle(page);
  const card = page.getByTestId('finding').filter({ hasText: /Maple duplex 2025 rents disagree/ });
  await expect(card).toHaveAttribute('data-severity', 'block');
  const open = await page.getByTestId('finding').count();
  await card.getByTestId('use-value').first().click();
  await expect(page.getByTestId('finding')).toHaveCount(open - 1);
  await expect(page.getByTestId('closed-finding').filter({ hasText: /rent/ }).first()).toBeVisible();

  await page.getByRole('link', { name: 'Portfolio', exact: true }).click();
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Okafor-Lindqvist');
  await settle(page);
  await expect(mapleCashFlow(page)).not.toHaveAttribute('data-status', 'blocked');
  if (meta(info).target !== 'mock') await expect(mapleCashFlow(page)).toHaveAttribute('data-status', 'confirmed');
});

test('a scanned upload shows progress while OCR runs, then the summary', async ({ page, errors }, info) => {
  void errors;
  test.skip(meta(info).target === 'mock', 'the mock reader is instant; OCR timing only exists on the live stacks');
  test.skip(meta(info).viewport !== 'desktop' && meta(info).viewport !== 'iphone', 'OCR is slow; two viewports are enough');
  await useWorkspace(page, info, `scan-${meta(info).viewport}`);
  const hh = await openDemoHousehold(page);
  await page.goto(`/households/${hh}/documents`);
  await settle(page);
  await page.getByTestId('sample-select').selectOption('stmt_3_2025.scan.pdf');
  await page.getByTestId('sample-upload').click();
  await expect(page.getByRole('progressbar').first()).toBeVisible();
  await expect(page.getByTestId('upload-summary')).toBeVisible({ timeout: 90_000 });
  await expect(page.getByTestId('upload-log')).toContainText(/fields read/);
});
