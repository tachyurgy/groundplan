import { join } from 'node:path';
import { expect, openDemoHousehold, settle, shot, test } from './helpers';

const FIXTURES = join(import.meta.dirname, '..', '..', 'fixtures', 'documents');

test('upload a return: fields, page image with boxes, then resolve a finding and the figure unblocks', async ({ page, errors }, info) => {
  void errors;
  const hh = await openDemoHousehold(page);
  await expect(page.locator('[data-testid=figure][data-status=blocked]').first()).toBeVisible();
  const blockedBefore = await page.locator('[data-testid=figure][data-status=blocked]').count();

  await page.goto(`/households/${hh}/documents`);
  await settle(page);
  await page.getByTestId('file-input').setInputFiles(join(FIXTURES, '2025_schedule_e.pdf'));
  await expect(page.getByTestId('upload-log')).toContainText(/\d+ fields/, { timeout: 45_000 });
  const viewer = page.getByTestId('doc-viewer');
  await expect(viewer).toContainText('2025_schedule_e.pdf');
  // the page image comes from the copy in this tab (pdf.js), with extraction boxes over it
  await expect(viewer.locator('[data-testid=pdf-page] canvas')).toBeVisible({ timeout: 20_000 });
  await expect(viewer.locator('[data-testid=pdf-page] button').first()).toBeVisible();
  await expect(viewer.getByTestId('extracted-fields').locator('li').first()).toBeVisible();
  await shot(page, info, '06-documents-upload');

  // resolve the first blocking finding that offers a value
  const card = page.getByTestId('finding').filter({ has: page.getByTestId('use-value') }).and(page.locator('[data-severity=block]')).first();
  await expect(card).toBeVisible();
  const openBefore = await page.getByTestId('finding').count();
  await card.getByTestId('use-value').first().click();
  await expect(page.getByTestId('finding')).toHaveCount(openBefore - 1);
  await expect(page.getByTestId('closed-finding').first()).toBeVisible();

  await page.getByRole('link', { name: 'Portfolio', exact: true }).click();
  await settle(page);
  await expect.poll(() => page.locator('[data-testid=figure][data-status=blocked]').count()).toBeLessThan(blockedBefore);
});
