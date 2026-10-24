import { chartHasMarks, expect, noBadNumbers, openDemoHousehold, openProperty, settle, shot, test } from './helpers';

test.describe('households → dashboard → property', () => {
  test('dashboard shows real figures and non-empty charts', async ({ page, errors }, info) => {
    void errors;
    await openDemoHousehold(page);
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Okafor-Lindqvist');
    await expect(page.getByTestId('property-card')).toHaveCount(4);
    for (const id of ['chart-equity-debt', 'chart-concentration', 'chart-cashflow']) await chartHasMarks(page, id);
    await expect(page.getByTestId('kpi')).toHaveCount(5);
    await expect(page.getByTestId('sparkline').first()).toBeVisible();
    await noBadNumbers(page);
    // a portfolio with data never shows $0 value or equity
    const value = await page.getByTestId('kpi').first().getByTestId('figure').innerText();
    expect(value).not.toBe('$0');
    await shot(page, info, '02-dashboard');
  });

  test('every analysis tab renders charts with real numbers', async ({ page, errors }, info) => {
    void errors;
    await openDemoHousehold(page);
    await openProperty(page, 'Maple duplex');
    const tabs: [string, string[]][] = [
      ['Cash flow', ['chart-cash-projection']],
      ['Equity', ['capital-stack']],
      ['Appreciation', ['chart-appreciation']],
      ['Depreciation', ['chart-depreciation']],
      ['Exit tax', ['chart-waterfall', 'chart-tax-layers']],
      ['Loans', []],
    ];
    for (const [name, charts] of tabs) {
      await page.getByRole('tab', { name, exact: true }).click();
      await expect(page.getByRole('tab', { name, exact: true })).toHaveAttribute('aria-selected', 'true');
      for (const c of charts) {
        if (c === 'capital-stack') await expect(page.getByTestId(c)).toBeVisible();
        else await chartHasMarks(page, c);
      }
      if (name === 'Depreciation') await expect(page.getByTestId('depreciation-table').getByRole('row').nth(2)).toBeVisible();
      if (name === 'Loans') await expect(page.getByRole('tabpanel')).toContainText(/Lien|free and clear/);
      await noBadNumbers(page);
      await shot(page, info, `04-property-${name.toLowerCase().replace(/\W+/g, '-')}`);
    }
    // the tab is URL state
    expect(new URL(page.url()).searchParams.get('tab')).toBe('loans');
  });

  test('clicking a number opens its calculation; Escape returns focus to it', async ({ page, errors }) => {
    void errors;
    await openDemoHousehold(page);
    await openProperty(page, 'Maple duplex');
    const num = page.getByTestId('kpi').nth(2).getByTestId('figure');
    await num.click();
    const drawer = page.getByTestId('trace-drawer');
    await expect(drawer).toBeVisible();
    await expect(drawer.getByTestId('trace-formula')).not.toHaveText('—');
    await expect(drawer.getByTestId('trace-input').first()).toBeVisible();
    await expect(drawer.getByTestId('trace-value')).toHaveText(/\$/);
    await page.keyboard.press('Escape');
    await expect(drawer).toBeHidden();
    await expect(num).toBeFocused();
  });

  test('an assumption edit recomputes, lands in the URL, and survives a reload', async ({ page, errors }) => {
    void errors;
    await openDemoHousehold(page);
    await openProperty(page, 'Maple duplex');
    const valueKpi = page.getByTestId('kpi').first().getByTestId('figure');
    const equityKpi = page.getByTestId('kpi').nth(1).getByTestId('figure');
    const before = await equityKpi.innerText();
    const input = page.getByLabel('Current value');
    await input.fill('900,000');
    await input.press('Enter');
    await expect(page).toHaveURL(/current_value_cents=90000000/);
    await expect(valueKpi).toHaveText('$900,000');
    await expect(equityKpi).not.toHaveText(before);
    const after = await equityKpi.innerText();
    await page.reload();
    await settle(page);
    await expect(page.getByLabel('Current value')).toHaveValue('900,000');
    await expect(page.getByTestId('kpi').nth(1).getByTestId('figure')).toHaveText(after);
    // back to the stored value: the URL is clean again
    await page.getByRole('button', { name: 'Reset', exact: true }).click();
    await expect(page).not.toHaveURL(/current_value_cents/);
    await expect(page.getByTestId('kpi').nth(1).getByTestId('figure')).toHaveText(before);
  });
});
