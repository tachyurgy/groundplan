import { axe, dismissWelcome, expect, noBadNumbers, noHorizontalScroll, openDemoHousehold, openProperty, settle, shot, test } from './helpers';

/** Every page: renders, no console errors, no horizontal scroll, axe clean (serious/critical), screenshot. */
test('every page passes axe, has no horizontal scroll and no console errors', async ({ page, errors }, info) => {
  void errors;
  const hh = await openDemoHousehold(page);
  await page.goto('/');
  await settle(page);
  const pages: [string, string][] = [['01-households', '/']];
  await page.goto(`/households/${hh}`);
  await settle(page);
  pages.push(['02-dashboard', `/households/${hh}`]);
  const prop = await openProperty(page, 'Elm SFR');
  pages.push(
    ['03-property', `/properties/${prop}`],
    ['04-property-exit', `/properties/${prop}?tab=exit`],
    ['04-property-loans', `/properties/${prop}?tab=loans`],
    ['05-strategies', `/properties/${prop}/strategies`],
    ['06-documents', `/households/${hh}/documents`],
    ['07-reports', `/households/${hh}/reports`],
    ['08-simulate', '/simulate'],
    ['09-eval', '/eval'],
    ['10-engineering', '/engineering'],
    ['11-not-found', '/no/such/page'],
  );
  for (const [name, path] of pages) {
    await test.step(name, async () => {
      await page.goto(path);
      await settle(page);
      await dismissWelcome(page);
      if (name === '11-not-found') await expect(page.getByRole('heading', { level: 1 })).toContainText('no page');
      else await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
      await noHorizontalScroll(page);
      if (name !== '10-engineering') await noBadNumbers(page); // that page discusses NaN in prose
      await axe(page, info, name);
      await shot(page, info, name);
    });
  }
});

test('dark theme: contrast holds (axe) on the data-heavy pages', async ({ page, errors }, info) => {
  void errors;
  await page.emulateMedia({ colorScheme: 'dark' });
  const hh = await openDemoHousehold(page);
  expect(await page.evaluate(() => document.documentElement.dataset.theme)).toBe('dark');
  const prop = await openProperty(page, 'Maple duplex');
  for (const [name, path] of [
    ['12-dark-dashboard', `/households/${hh}`],
    ['13-dark-property-exit', `/properties/${prop}?tab=exit`],
    ['14-dark-strategies', `/properties/${prop}/strategies`],
  ] as const) {
    await test.step(name, async () => {
      await page.goto(path);
      await settle(page);
      await noHorizontalScroll(page);
      await axe(page, info, name);
      await shot(page, info, name);
    });
  }
});

test('theme toggle overrides the OS setting and persists', async ({ page, errors }) => {
  void errors;
  await page.goto('/');
  await settle(page);
  const html = page.locator('html');
  await expect(html).toHaveAttribute('data-theme', 'light');
  await page.getByRole('button', { name: /^Theme:/ }).click(); // system -> light
  await page.getByRole('button', { name: /^Theme:/ }).click(); // light -> dark
  await expect(html).toHaveAttribute('data-theme', 'dark');
  await page.reload();
  await expect(html).toHaveAttribute('data-theme', 'dark');
});

test('stack badge and twin link', async ({ page, errors }, info) => {
  void errors;
  const hh = await openDemoHousehold(page);
  const badge = page.getByTestId('stack-badge').last();
  await expect(badge).toContainText(/Backend: (Python|Go|Mock)/);
  const target = (info.project.metadata as { target: string }).target;
  if (target === 'python') await expect(badge).toHaveAttribute('data-backend', 'python');
  if (target === 'go') await expect(badge).toHaveAttribute('data-backend', 'go');
  const twin = page.getByTestId('twin-link');
  await twin.hover();
  const href = new URL((await twin.getAttribute('href'))!);
  expect(href.pathname).toBe('/twin');
  expect(href.searchParams.get('to')).toBe(`/households/${hh}`);
  expect(href.searchParams.get('hh')).toMatch(/Okafor-Lindqvist/);
});
