/**
 * Mock engine. A compact, deterministic re-implementation of enough of SPEC §2 to make every page live
 * and reactive to assumption edits while the real FastAPI/Python engine is built. Integer cents out,
 * Figures with provenance, status derived with the §1 rule. This is NOT the engine of record.
 */
import type {
  Figure,
  FigureInput,
  FigureSource,
  Property,
  Loan,
  Household,
  ExpenseYear,
  RentRoll,
  DepreciationLedger,
  Finding,
  PropertyAnalysis,
  CashFlowAnalysis,
  LoanScheduleSummary,
  LoanYearRow,
  DepreciationScheduleRow,
  ExitTaxAnalysis,
  StrategyComparison,
  StrategyPathResult,
  StrategySeriesRow,
  ScenarioAssumptions,
  MatrixMeasure,
  StrategyPath,
  MatrixVerdict,
  Observation,
  SimulationRequest,
  SimulationResult,
  SimulationYear,
  PercentileBand,
  Cents,
  Rate,
  FactSheet,
  FactSheetFormat,
  FactSheetRow,
  FigureStatus,
} from '../types';
import { deriveStatus } from '../../lib/status';

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

const roundCents = (x: number): Cents => Math.round(x + Number.EPSILON);

export interface EngineContext {
  household: Household;
  property: Property;
  loans: Loan[];
  rentRolls: RentRoll[];
  expenseYears: ExpenseYear[];
  ledgers: DepreciationLedger[];
  findings: Finding[];
  suspendedLossCents: Cents;
  /** document refs for provenance, keyed by field */
  docRefs: Record<string, FigureSource>;
}

function blockingKeys(findings: Finding[], propertyId: string): Set<string> {
  return new Set(
    findings
      .filter((f) => f.status === 'open' && f.severity === 'block' && (f.property_id === propertyId || f.property_id === null))
      .map((f) => f.field),
  );
}

export function fig(
  blocking: Set<string>,
  key: string,
  value_cents: Cents,
  inputs: FigureInput[],
  formula: string,
  notes: string[] = [],
  label?: string,
): Figure {
  return { key, value_cents: roundCents(value_cents), status: deriveStatus(inputs, blocking), inputs, formula, notes, label };
}

const inp = (key: string, value: unknown, source: FigureSource, extra: Partial<FigureInput> = {}): FigureInput => ({
  key,
  value,
  source,
  ...extra,
});
const manual = (ref: string): FigureSource => ({ type: 'manual', ref });
const dflt = (ref: string): FigureSource => ({ type: 'default', ref });
const pub = (ref: string): FigureSource => ({ type: 'public_data', ref });
const figIn = (f: Figure): FigureInput => ({ key: f.key, value: f.value_cents, source: { type: 'manual', ref: 'computed' }, figure: f, unit: 'cents', label: f.label });

// ---------------------------------------------------------------------------
// §2.1 depreciation — 27.5-yr residential, mid-month (Pub 946 Table A-6)
// ---------------------------------------------------------------------------

const A6_FIRST_YEAR = [3.485, 3.182, 2.879, 2.576, 2.273, 1.97, 1.667, 1.364, 1.061, 0.758, 0.455, 0.152];
const A39_FIRST_YEAR = [2.461, 2.247, 2.033, 1.819, 1.605, 1.391, 1.177, 0.963, 0.749, 0.535, 0.321, 0.107];

export function depreciationSchedule(p: Property, throughYear: number): { rows: DepreciationScheduleRow[]; basis: Cents; bounded: boolean } {
  const rawLand = p.land_pct;
  const land = Math.min(0.8, Math.max(0.6, rawLand));
  const bounded = land !== rawLand;
  const basis = roundCents((p.purchase_price_cents + p.improvements_cents) * (1 - land));
  const nonres = p.property_type === 'commercial';
  const [y0, m0] = p.placed_in_service_date.split('-').map(Number);
  const first = (nonres ? A39_FIRST_YEAR : A6_FIRST_YEAR)[m0 - 1];
  const mid = nonres ? 2.564 : 3.636;
  const rows: DepreciationScheduleRow[] = [];
  let cum = 0;
  for (let y = y0; y <= throughYear; y++) {
    const idx = y - y0;
    let pct: number;
    if (idx === 0) pct = first;
    else pct = mid;
    const remaining = 100 - cum;
    if (remaining <= 0) break;
    pct = Math.min(pct, remaining);
    const amt = roundCents((basis * pct) / 100);
    rows.push({ year: y, amount_cents: amt, method: nonres ? 'sl_39' : 'sl_27_5', pct });
    cum += pct;
  }
  return { rows, basis, bounded };
}

// ---------------------------------------------------------------------------
// §2.2 loans — annual principal/interest splits from the statement balance forward
// ---------------------------------------------------------------------------

function monthsBetween(a: string, b: string): number {
  const [ay, am] = a.split('-').map(Number);
  const [by, bm] = b.split('-').map(Number);
  return (by - ay) * 12 + (bm - am);
}

function pmt(balance: number, monthlyRate: number, n: number): number {
  if (n <= 0) return balance;
  if (monthlyRate === 0) return balance / n;
  return (balance * monthlyRate) / (1 - Math.pow(1 + monthlyRate, -n));
}

export interface LoanYear {
  year: number;
  principal: number;
  interest: number;
  balanceEnd: number;
  rate: number;
  marker: LoanYearRow['marker'];
}

/** Project a loan year-by-year from `startYear` for `years` years, starting from the statement balance. */
export function projectLoan(loan: Loan, startYear: number, years: number, armIndex = 0.04): LoanYear[] {
  const out: LoanYear[] = [];
  if (loan.is_paid_off || loan.balance_cents <= 0) {
    for (let i = 0; i < years; i++) out.push({ year: startYear + i, principal: 0, interest: 0, balanceEnd: 0, rate: loan.rate, marker: null });
    return out;
  }
  let bal = loan.balance_cents;
  const startMonth = `${startYear}-01`;
  const monthsToMaturity = Math.max(1, monthsBetween(startMonth, loan.maturity_date));
  const originationMonth = monthsBetween(startMonth, loan.maturity_date) - loan.term_months; // negative = months ago
  const ioEndMonthIdx = loan.io_months > 0 ? originationMonth + loan.io_months : -1; // index relative to start
  const armResetIdx = loan.arm_reset_date ? monthsBetween(startMonth, loan.arm_reset_date) : null;
  let rate = loan.rate;
  let payment = loan.monthly_payment_cents;
  const total = years * 12;
  let yearP = 0;
  let yearI = 0;
  let marker: LoanYearRow['marker'] = null;
  for (let m = 0; m < total; m++) {
    const inIO = loan.loan_type === 'heloc' ? true : loan.io_months > 0 && m < ioEndMonthIdx;
    if (armResetIdx !== null && m === armResetIdx) {
      rate = armIndex + (loan.arm_index_margin ?? 0);
      marker = 'arm_reset';
      payment = inIO ? bal * (rate / 12) : pmt(bal, rate / 12, Math.max(1, monthsToMaturity - m));
    }
    if (loan.io_months > 0 && m === ioEndMonthIdx && loan.loan_type !== 'heloc') {
      marker = marker ?? 'io';
      payment = pmt(bal, rate / 12, Math.max(1, monthsToMaturity - m));
    }
    const interest = bal * (rate / 12);
    let principal: number;
    if (inIO) {
      principal = 0;
    } else {
      principal = Math.min(bal, Math.max(0, payment - interest));
      if (payment < interest) principal = 0;
    }
    if (m >= monthsToMaturity - 1 && bal - principal > 0.5) {
      // maturity: balloon or remaining balance due
      principal = bal;
      marker = loan.loan_type === 'balloon' ? 'balloon' : 'maturity';
    }
    bal -= principal;
    yearP += principal;
    yearI += interest;
    if ((m + 1) % 12 === 0) {
      out.push({ year: startYear + Math.floor(m / 12), principal: roundCents(yearP), interest: roundCents(yearI), balanceEnd: roundCents(bal), rate, marker: marker ?? (inIO && loan.loan_type !== 'heloc' ? 'io' : null) });
      yearP = 0;
      yearI = 0;
      marker = null;
    }
    if (bal <= 0) {
      // fill remaining years with zeros
      const doneYears = Math.floor((m + 1) / 12) + ((m + 1) % 12 === 0 ? 0 : 1);
      if ((m + 1) % 12 !== 0) {
        out.push({ year: startYear + Math.floor(m / 12), principal: roundCents(yearP), interest: roundCents(yearI), balanceEnd: 0, rate, marker: marker ?? null });
      }
      for (let y = doneYears; y < years; y++) out.push({ year: startYear + y, principal: 0, interest: 0, balanceEnd: 0, rate, marker: null });
      break;
    }
  }
  return out.slice(0, years);
}

// ---------------------------------------------------------------------------
// §2.6 / §2.7 tax tables (2025)
// ---------------------------------------------------------------------------

type Bracket = [limit: number, rate: number];
const ORD: Record<string, Bracket[]> = {
  single: [[11_925, 0.1], [48_475, 0.12], [103_350, 0.22], [197_300, 0.24], [250_525, 0.32], [626_350, 0.35], [Infinity, 0.37]],
  mfj: [[23_850, 0.1], [96_950, 0.12], [206_700, 0.22], [394_600, 0.24], [501_050, 0.32], [751_600, 0.35], [Infinity, 0.37]],
  hoh: [[17_000, 0.1], [64_850, 0.12], [103_350, 0.22], [197_300, 0.24], [250_500, 0.32], [626_350, 0.35], [Infinity, 0.37]],
  mfs: [[11_925, 0.1], [48_475, 0.12], [103_350, 0.22], [197_300, 0.24], [250_525, 0.32], [375_800, 0.35], [Infinity, 0.37]],
};
const STD: Record<string, number> = { single: 15_750, mfj: 31_500, hoh: 23_625, mfs: 15_750 };
const LTCG: Record<string, [number, number]> = { single: [48_350, 533_400], mfj: [96_700, 600_050], hoh: [64_750, 566_700], mfs: [48_350, 300_025] };
const NIIT_T: Record<string, number> = { single: 200_000, hoh: 200_000, mfj: 250_000, mfs: 125_000 };

const CA_MFJ: Bracket[] = [[21_512, 0.01], [50_998, 0.02], [80_490, 0.04], [111_732, 0.06], [141_212, 0.08], [721_318, 0.093], [865_574, 0.103], [1_442_628, 0.113], [Infinity, 0.123]];
const CA_SINGLE: Bracket[] = [[10_756, 0.01], [25_499, 0.02], [40_245, 0.04], [55_866, 0.06], [70_606, 0.08], [360_659, 0.093], [432_787, 0.103], [721_314, 0.113], [Infinity, 0.123]];
const NO_TAX = new Set(['WA', 'TX', 'FL', 'NV', 'SD', 'WY', 'AK', 'TN', 'NH']);
const FLAT: Record<string, number> = { AZ: 0.025, CO: 0.044, GA: 0.0539, IL: 0.0495, IN: 0.03, KY: 0.04, MI: 0.0425, NC: 0.0425, PA: 0.0307, UT: 0.045, MS: 0.044, ID: 0.05695 };

/** Tax on dollars `from`..`to` under bracket table (dollars). */
function bracketTax(brackets: Bracket[], from: number, to: number, cap?: number): number {
  let tax = 0;
  let lower = 0;
  for (const [limit, rate] of brackets) {
    const lo = Math.max(lower, from);
    const hi = Math.min(limit, to);
    if (hi > lo) tax += (hi - lo) * (cap !== undefined ? Math.min(rate, cap) : rate);
    lower = limit;
    if (limit >= to) break;
  }
  return tax;
}

function stateTaxOnGain(state: string, filing: string, ordinaryTaxable: number, gain: number): { tax: number; note: string } {
  if (NO_TAX.has(state)) return { tax: 0, note: `${state}: no state income tax on real-estate gains (verify).` };
  if (FLAT[state] !== undefined) return { tax: gain * FLAT[state], note: `${state}: flat ${(FLAT[state] * 100).toFixed(2)}% on gain as ordinary income (verify).` };
  if (state === 'CA') {
    const table = filing === 'mfj' ? CA_MFJ : CA_SINGLE;
    const base = Math.max(0, ordinaryTaxable);
    let tax = bracketTax(table, base, base + gain);
    if (base + gain > 1_000_000) tax += (base + gain - Math.max(base, 1_000_000)) * 0.01;
    return { tax, note: 'CA: gain taxed as ordinary income under 2025 CA brackets, stacked on other taxable income; +1% MHS over $1M (verify).' };
  }
  return { tax: 0, note: `${state}: unsupported state in mock tables; state tax shown as 0 (Finding: unsupported state).` };
}

// ---------------------------------------------------------------------------
// Property analysis
// ---------------------------------------------------------------------------

export interface Overrides {
  appreciation_rate?: Rate;
  rent_growth_rate?: Rate;
  expense_growth_rate?: Rate;
  vacancy_rate?: Rate;
  current_value_cents?: Cents;
  land_pct?: Rate;
  arm_index?: Rate;
  selling_cost_rate?: Rate;
  capex_reserve_rate?: Rate;
  reinvest_rate?: Rate;
}

const docSrc = (ctx: EngineContext, field: string, fallbackRef: string): FigureSource => ctx.docRefs[field] ?? manual(fallbackRef);

export function analyzeProperty(ctx: EngineContext, year: number, horizon: number, ov: Overrides = {}): PropertyAnalysis {
  const p: Property = { ...ctx.property, ...stripUndefined(ov) };
  const blocking = blockingKeys(ctx.findings, p.id);
  const loans = ctx.loans.filter((l) => l.property_id === p.id);
  const rr = ctx.rentRolls.find((r) => r.property_id === p.id && r.tax_year === year) ?? latest(ctx.rentRolls.filter((r) => r.property_id === p.id));
  const ey = ctx.expenseYears.find((e) => e.property_id === p.id && e.tax_year === year) ?? latest(ctx.expenseYears.filter((e) => e.property_id === p.id));
  const statusInput = inp('property.status', p.status, manual('property record'), { label: 'Property status' });

  // --- cash flow
  const grossRent = rr?.gross_rent_cents ?? 0;
  const otherInc = rr?.other_income_cents ?? 0;
  const vacancy = roundCents(grossRent * p.vacancy_rate);
  const vacSrc = ov.vacancy_rate !== undefined ? manual('assumptions panel') : dflt(`vacancy_rate ${p.vacancy_rate}`);
  const grossRentFig = fig(blocking, 'cash_flow.gross_rent', grossRent, [inp('rent_roll.gross_rent', grossRent, docSrc(ctx, 'schedule_e.line3.rents', 'rent roll'), { unit: 'cents', label: 'Schedule E line 3 rents' }), statusInput], 'Schedule E line 3', [], 'Gross rent');
  const vacancyFig = fig(blocking, 'cash_flow.vacancy_loss', -vacancy, [figIn(grossRentFig), inp('property.vacancy_rate', p.vacancy_rate, vacSrc, { unit: 'rate', label: 'Vacancy rate' })], 'gross_rent × vacancy_rate', [], 'Vacancy allowance');
  const otherFig = fig(blocking, 'cash_flow.other_income', otherInc, [inp('rent_roll.other_income', otherInc, docSrc(ctx, 'schedule_e.line4.royalties_other', 'rent roll'), { unit: 'cents' }), statusInput], 'Schedule E line 4', [], 'Other income');
  const opexParts = ey
    ? [
        ['taxes', ey.taxes_cents, 'schedule_e.line16.taxes'],
        ['insurance', ey.insurance_cents, 'schedule_e.line9.insurance'],
        ['repairs', ey.repairs_cents, 'schedule_e.line14.repairs'],
        ['mgmt', ey.mgmt_cents, 'schedule_e.line11.management_fees'],
        ['utilities', ey.utilities_cents, 'schedule_e.line17.utilities'],
        ['hoa', ey.hoa_cents, 'schedule_e.line19.other'],
        ['other', ey.other_cents, 'schedule_e.line19.other'],
      ] as const
    : [];
  const opex = opexParts.reduce((s, [, v]) => s + v, 0);
  const opexFig = fig(
    blocking,
    'cash_flow.operating_expenses',
    -opex,
    [...opexParts.map(([k, v, f]) => inp(`expense_year.${k}`, v, docSrc(ctx, f, 'expense entry'), { unit: 'cents', label: k })), statusInput],
    'taxes + insurance + repairs + mgmt + utilities + hoa + other (Schedule E lines 9-19 excl. interest and depreciation)',
    [],
    'Operating expenses',
  );
  const capex = roundCents(grossRent * p.capex_reserve_rate);
  const capexFig = fig(blocking, 'cash_flow.capex_reserve', -capex, [figIn(grossRentFig), inp('property.capex_reserve_rate', p.capex_reserve_rate, ov.capex_reserve_rate !== undefined ? manual('assumptions panel') : dflt(`capex_reserve_rate ${p.capex_reserve_rate}`), { unit: 'rate' })], 'gross_rent × capex_reserve_rate', ['Reserve is a planning assumption, not a Schedule E line.'], 'CapEx reserve');
  const noi = grossRent - vacancy + otherInc - opex - capex;
  const noiFig = fig(blocking, 'cash_flow.noi', noi, [figIn(grossRentFig), figIn(vacancyFig), figIn(otherFig), figIn(opexFig), figIn(capexFig)], 'gross_rent×(1−vacancy) + other_income − operating_expenses − capex_reserve', [], 'NOI');

  const armIndex = ov.arm_index ?? 0.04;
  const loanProj = loans.map((l) => ({ loan: l, years: projectLoan(l, year, Math.max(horizon, 1), armIndex) }));
  const ds = loanProj.reduce((s, lp) => s + (lp.years[0]?.principal ?? 0) + (lp.years[0]?.interest ?? 0), 0);
  const principalY1 = loanProj.reduce((s, lp) => s + (lp.years[0]?.principal ?? 0), 0);
  const dsFig = fig(
    blocking,
    'cash_flow.debt_service',
    -ds,
    loans.map((l) => inp(`loan.${l.id}.annual_payment`, roundCents(l.is_paid_off ? 0 : l.monthly_payment_cents * 12), docSrc(ctx, `mortgage.${l.id}`, `${l.lender} statement`), { unit: 'cents', label: `${l.lender}${l.is_paid_off ? ' (paid off)' : ''}` })),
    'Σ liens (principal + interest) for the year; paid-off liens contribute 0 but stay in the trace',
    loans.some((l) => l.loan_type === 'arm') ? [`ARM index assumption ${(armIndex * 100).toFixed(2)}% + margin after reset.`] : [],
    'Debt service',
  );
  const ncf = noi - ds;
  const ncfFig = fig(blocking, 'cash_flow.net_annual', ncf, [figIn(noiFig), figIn(dsFig)], 'NOI − debt_service', [], 'Net cash flow');

  // Schedule E bridge
  const line21 = ey ? grossRent + otherInc - (opex + ey.mortgage_interest_cents + ey.depreciation_cents) : 0;
  const line21Fig = fig(blocking, 'bridge.line21', line21, [inp('schedule_e.line21', line21, docSrc(ctx, 'schedule_e.line21.income_or_loss', 'Schedule E'), { unit: 'cents' }), statusInput], 'Schedule E line 21 (income or loss)', [], 'Line 21');
  const deprFig = fig(blocking, 'bridge.line18_depreciation', ey?.depreciation_cents ?? 0, [inp('schedule_e.line18', ey?.depreciation_cents ?? 0, docSrc(ctx, 'schedule_e.line18.depreciation', 'Schedule E'), { unit: 'cents' })], 'Schedule E line 18', [], 'Depreciation (add back)');
  const prinFig = fig(blocking, 'bridge.principal_paid', principalY1, loans.map((l) => inp(`loan.${l.id}.principal`, roundCents(loanProj.find((x) => x.loan.id === l.id)?.years[0]?.principal ?? 0), docSrc(ctx, `mortgage.${l.id}`, 'amortization'), { unit: 'cents', label: l.lender })), 'Σ principal paid this year (amortization)', [], 'Principal paid');
  const capImpFig = fig(blocking, 'bridge.capital_improvements_paid', 0, [inp('improvements_paid_this_year', 0, dflt('none recorded'), { unit: 'cents' })], 'capital improvements paid this year', [], 'Capital improvements');
  const cfFromReturn = line21 + (ey?.depreciation_cents ?? 0) - principalY1 - 0;
  const cfFromReturnFig = fig(blocking, 'bridge.cash_flow_from_return', cfFromReturn, [figIn(line21Fig), figIn(deprFig), figIn(prinFig), figIn(capImpFig)], 'line21 + line18_depreciation − principal_paid − capital_improvements_paid', ['Interest is already inside line 21; it is never subtracted twice.'], 'Cash flow from return');
  const deltaFig = fig(blocking, 'bridge.delta_vs_engine', ncf - cfFromReturn, [figIn(ncfFig), figIn(cfFromReturnFig)], 'engine net_cash_flow − cash_flow_from_return', ['Delta is explained by the vacancy allowance and capex reserve (planning assumptions) and any interest difference between the statement projection and line 12.'], 'Delta');

  // projection
  const projection = [];
  for (let i = 0; i < horizon; i++) {
    const g = Math.pow(1 + p.rent_growth_rate, i);
    const e = Math.pow(1 + p.expense_growth_rate, i);
    const noiY = roundCents((grossRent - vacancy + otherInc) * g - (opex + capex) * e);
    const dsY = roundCents(loanProj.reduce((s, lp) => s + (lp.years[i]?.principal ?? 0) + (lp.years[i]?.interest ?? 0), 0));
    projection.push({ year: year + i, noi_cents: noiY, debt_service_cents: dsY, net_cash_flow_cents: noiY - dsY });
  }

  const cash_flow: CashFlowAnalysis = {
    gross_rent: grossRentFig,
    vacancy_loss: vacancyFig,
    other_income: otherFig,
    operating_expenses: opexFig,
    capex_reserve: capexFig,
    noi: noiFig,
    debt_service: dsFig,
    net_cash_flow: ncfFig,
    projection,
    schedule_e_bridge: { line21: line21Fig, line18_depreciation: deprFig, principal_paid: prinFig, capital_improvements_paid: capImpFig, cash_flow_from_return: cfFromReturnFig, delta_vs_engine: deltaFig },
  };

  // --- equity
  const valueSrc: FigureSource = ov.current_value_cents !== undefined ? manual('assumptions panel') : p.value_source === 'confirmed' ? docSrc(ctx, 'appraisal.value', 'appraisal') : pub('AVM estimate');
  const valueFig = fig(blocking, 'equity.value', p.current_value_cents, [inp('property.current_value', p.current_value_cents, valueSrc, { unit: 'cents', label: `Value as of ${p.value_as_of}` }), statusInput], 'current_value', p.value_source === 'estimated' ? ['Value is a public-data estimate; confirm with an appraisal or BPO.'] : [], 'Value');
  const totalDebt = loans.reduce((s, l) => s + (l.is_paid_off ? 0 : l.balance_cents), 0);
  const debtFig = fig(blocking, 'equity.total_debt', totalDebt, loans.map((l) => inp(`loan.${l.id}.balance`, l.is_paid_off ? 0 : l.balance_cents, docSrc(ctx, `mortgage.${l.id}`, `${l.lender} statement`), { unit: 'cents', label: `${l.lender} lien ${l.lien_position}${l.is_paid_off ? ' (paid off)' : ''}` })), 'Σ lien balances', [], 'Total debt');
  const equity = p.current_value_cents - totalDebt;
  const equityFig = fig(blocking, 'equity.equity', equity, [figIn(valueFig), figIn(debtFig)], 'value − Σ balances', [], 'Equity');
  const lendable = Math.max(0, roundCents(p.current_value_cents * 0.7) - totalDebt);
  const lendableFig = fig(blocking, 'equity.lendable_equity', lendable, [figIn(valueFig), figIn(debtFig), inp('ltv_max', 0.7, dflt('70% LTV'), { unit: 'rate' })], 'max(0, value × 0.70 − Σ balances)', [], 'Lendable equity');
  const apprY1 = roundCents(p.current_value_cents * p.appreciation_rate);
  const roeNum = ncf + principalY1 + apprY1;
  const roeRate = equity > 0 ? roeNum / equity : 0;
  const roeFig = fig(blocking, 'equity.roe', roeNum, [figIn(ncfFig), figIn(prinFig), inp('appreciation_this_year', apprY1, ov.appreciation_rate !== undefined ? manual('assumptions panel') : dflt(`appreciation_rate ${p.appreciation_rate}`), { unit: 'cents' }), figIn(equityFig)], '(net_cash_flow + principal_paydown + appreciation_this_year) / equity_begin_of_year', [`ROE = ${(roeRate * 100).toFixed(2)}%`], 'Return on equity (numerator)');

  // --- appreciation
  const yearsHeld = (new Date(`${year}-12-31`).getTime() - new Date(p.purchase_date).getTime()) / (365.25 * 86_400_000);
  const cagr = yearsHeld > 0 ? Math.pow(p.current_value_cents / p.purchase_price_cents, 1 / yearsHeld) - 1 : 0;
  const projected = [];
  for (let i = 0; i <= horizon; i++) {
    const v = roundCents(p.current_value_cents * Math.pow(1 + p.appreciation_rate, i));
    const d = i === 0 ? totalDebt : roundCents(loanProj.reduce((s, lp) => s + (lp.years[i - 1]?.balanceEnd ?? 0), 0));
    projected.push({ year: year + i, value_cents: v, equity_cents: v - d, debt_cents: d });
  }
  const projValFig = fig(blocking, 'appreciation.projected_value_horizon', projected[horizon].value_cents, [figIn(valueFig), inp('property.appreciation_rate', p.appreciation_rate, ov.appreciation_rate !== undefined ? manual('assumptions panel') : dflt(`appreciation_rate ${p.appreciation_rate}`), { unit: 'rate' }), inp('horizon_years', horizon, manual('horizon'))], 'value × (1 + appreciation_rate)^horizon', [], `Projected value, year ${year + horizon}`);

  // --- depreciation
  const dep = depreciationSchedule(p, year);
  const ledgerRows = ctx.ledgers.filter((l) => l.property_id === p.id);
  const accumulated = dep.rows.filter((r) => r.year < year + 1).reduce((s, r) => s + r.amount_cents, 0);
  const thruPrior = dep.rows.filter((r) => r.year <= year - 1).reduce((s, r) => s + r.amount_cents, 0);
  const basisFig = fig(blocking, 'depreciation.depreciable_basis', dep.basis, [inp('property.purchase_price', p.purchase_price_cents, docSrc(ctx, 'closing.purchase_price', 'purchase record'), { unit: 'cents' }), inp('property.improvements', p.improvements_cents, manual('improvements entered'), { unit: 'cents' }), inp('property.land_pct', p.land_pct, ov.land_pct !== undefined ? manual('assumptions panel') : dflt(`land_pct ${p.land_pct}`), { unit: 'rate' })], '(purchase_price + improvements) × (1 − land_pct), land_pct bounded to [0.60, 0.80]', dep.bounded ? ['land_pct was outside [0.60, 0.80] and was bounded.'] : [], 'Depreciable basis');
  const annualAmt = dep.rows.find((r) => r.year === year)?.amount_cents ?? 0;
  const annualFig = fig(blocking, 'depreciation.annual', annualAmt, [figIn(basisFig), inp('table', 'Pub 946 Table A-6 (27.5-yr, mid-month)', dflt('IRS table'))], 'basis × table%(year, month placed in service)', [], `Depreciation ${year}`);
  const accFig = fig(blocking, 'depreciation.accumulated', accumulated, [figIn(basisFig), ...ledgerRows.map((l) => inp(`ledger.${l.tax_year}.allowed`, l.allowed_cents, docSrc(ctx, 'form_4562.part3.line19h.deduction', 'Form 4562'), { unit: 'cents', label: `${l.tax_year} allowed` }))], 'Σ allowable depreciation through end of year (allowed-or-allowable: uses allowable when the return claimed less)', ledgerRows.some((l) => l.allowed_cents < l.allowable_cents) ? ['A ledger year claimed less than allowable; recapture still uses allowable (Finding: outlier).'] : [], 'Accumulated depreciation');

  // --- exit tax (sale in `year`, using accumulated through Y-1 + current year)
  const exit = exitTax(ctx, p, blocking, loans, totalDebt, thruPrior + annualAmt, p.current_value_cents, 'taxable', valueFig, accFig, ov);

  const loanSummaries: LoanScheduleSummary[] = loanProj.map(({ loan, years }) => {
    const y0 = years[0];
    const ads = (y0?.principal ?? 0) + (y0?.interest ?? 0);
    return {
      loan,
      annual: years.map((y) => ({ year: y.year, principal_cents: y.principal, interest_cents: y.interest, balance_end_cents: y.balanceEnd, rate: y.rate, marker: y.marker })),
      dscr: fig(blocking, `loan.${loan.id}.dscr`, ads > 0 ? roundCents((noi / ads) * 100) : 0, [figIn(noiFig), inp('annual_debt_service', ads, docSrc(ctx, `mortgage.${loan.id}`, 'statement'), { unit: 'cents' })], 'NOI / annual debt service (shown ×100 in cents)', [ads > 0 ? `DSCR = ${(noi / ads).toFixed(2)}` : 'No debt service'], 'DSCR'),
      annual_debt_service: fig(blocking, `loan.${loan.id}.annual_debt_service`, ads, [inp('loan.monthly_payment', loan.monthly_payment_cents, docSrc(ctx, `mortgage.${loan.id}`, 'statement'), { unit: 'cents' })], 'Σ monthly payments in year', [], 'Annual debt service'),
      balance_at_year_end: fig(blocking, `loan.${loan.id}.balance_at_year_end`, y0?.balanceEnd ?? 0, [inp('loan.balance', loan.balance_cents, docSrc(ctx, `mortgage.${loan.id}`, 'statement'), { unit: 'cents', label: `Balance as of ${loan.balance_as_of}` })], 'balance_at(Dec 31) from amortization', [], 'Balance at year end'),
    };
  });

  const observations = observe(p, loans, ncf, noi, ds, roeRate, ov.reinvest_rate ?? 0.06, exit.exit_tax_total.value_cents, equity, ctx, year, dep.bounded, ledgerRows);

  return {
    property: p,
    year,
    horizon,
    cash_flow,
    equity: { value: valueFig, total_debt: debtFig, equity: equityFig, lendable_equity: lendableFig, roe: roeFig, roe_rate: roeRate, concentration: null },
    appreciation: { cagr_since_purchase: cagr, projected, projected_value_horizon: projValFig },
    depreciation: { schedule: depreciationSchedule(p, year + horizon).rows, accumulated_cents: accumulated, accumulated: accFig, depreciable_basis: basisFig, annual: annualFig, method: dep.rows[0]?.method ?? 'sl_27_5', land_pct_bounded: dep.bounded },
    exit_tax: exit,
    loans: loanSummaries,
    observations,
  };
}

function latest<T extends { tax_year: number }>(rows: T[]): T | undefined {
  return [...rows].sort((a, b) => b.tax_year - a.tax_year)[0];
}

function stripUndefined<T extends object>(o: T): Partial<T> {
  return Object.fromEntries(Object.entries(o).filter(([, v]) => v !== undefined)) as Partial<T>;
}

// ---------------------------------------------------------------------------
// §2.8 exit tax with bracket stacking
// ---------------------------------------------------------------------------

export function exitTax(
  ctx: EngineContext,
  p: Property,
  blocking: Set<string>,
  loans: Loan[],
  totalDebt: Cents,
  accumulatedDep: Cents,
  salePrice: Cents,
  mode: 'taxable' | 'boot',
  valueFig: Figure,
  accFig: Figure,
  ov: Overrides,
  recognizedOverride?: Cents,
  releaseSuspended = true,
): ExitTaxAnalysis {
  const hh = ctx.household;
  const sellRate = ov.selling_cost_rate ?? p.selling_cost_rate;
  const sellingCosts = roundCents(salePrice * sellRate);
  const netBefore = salePrice - sellingCosts - totalDebt;
  const adjBasis = p.purchase_price_cents + p.improvements_cents - accumulatedDep;
  const amountRealized = salePrice - sellingCosts;
  const totalGain = Math.max(0, amountRealized - adjBasis);
  const gainBase = recognizedOverride !== undefined ? Math.min(recognizedOverride, totalGain) : totalGain;
  const share = totalGain > 0 ? gainBase / totalGain : 0;
  const unrecaptured = roundCents(Math.min(gainBase, accumulatedDep * share));
  const sec1245 = p.cost_seg_study ? roundCents(accumulatedDep * 0.2 * share) : 0; // bonus portion only with a study
  const ltcg = Math.max(0, gainBase - unrecaptured - sec1245);

  const std = STD[hh.filing_status] ?? STD.mfj;
  const released = releaseSuspended && mode === 'taxable' ? ctx.suspendedLossCents : 0;
  const ordinaryTaxable = Math.max(0, (hh.wages_cents + hh.other_income_cents - released) / 100 - std);
  const ord = ORD[hh.filing_status] ?? ORD.mfj;
  const top1245 = ordinaryTaxable + sec1245 / 100;
  const fed1245 = bracketTax(ord, ordinaryTaxable, top1245);
  const top1250 = top1245 + unrecaptured / 100;
  const fed1250 = bracketTax(ord, top1245, top1250, 0.25);
  const [l0, l15] = LTCG[hh.filing_status] ?? LTCG.mfj;
  const ltcgLo = top1250;
  const ltcgHi = top1250 + ltcg / 100;
  const fedLtcg = bracketTax([[l0, 0], [l15, 0.15], [Infinity, 0.2]], ltcgLo, ltcgHi);
  const magi = hh.magi_cents / 100 + gainBase / 100;
  const niitBase = Math.max(0, Math.min(gainBase / 100, magi - (NIIT_T[hh.filing_status] ?? 250_000)));
  const niit = niitBase * 0.038;
  const st = stateTaxOnGain(p.state, hh.filing_status, ordinaryTaxable, gainBase / 100);
  const total = roundCents((fed1250 + fed1245 + fedLtcg + niit + st.tax) * 100);
  const netProceeds = netBefore - total;

  const hhSrc = (k: string) => inp(k, (hh as unknown as Record<string, unknown>)[k], ctx.docRefs['form_1040.line1a.wages'] ?? manual('household record'), { unit: 'cents' });
  const salePriceFig = fig(blocking, 'exit_tax.sale_price', salePrice, [figIn(valueFig)], 'current value (or sale price input)', [], 'Sale price');
  const sellingFig = fig(blocking, 'exit_tax.selling_costs', -sellingCosts, [figIn(salePriceFig), inp('property.selling_cost_rate', sellRate, ov.selling_cost_rate !== undefined ? manual('assumptions panel') : dflt(`selling_cost_rate ${sellRate}`), { unit: 'rate' })], 'sale_price × selling_cost_rate', [], 'Selling costs');
  const payoffFig = fig(blocking, 'exit_tax.loan_payoffs', -totalDebt, loans.map((l) => inp(`loan.${l.id}.balance`, l.is_paid_off ? 0 : l.balance_cents, docSrc(ctx, `mortgage.${l.id}`, `${l.lender} statement`), { unit: 'cents', label: l.lender })), 'Σ lien balances paid at closing', [], 'Loan payoffs');
  const netBeforeFig = fig(blocking, 'exit_tax.net_before_tax', netBefore, [figIn(salePriceFig), figIn(sellingFig), figIn(payoffFig)], 'sale_price − selling_costs − loan_payoffs', [], 'Net before tax');
  const adjBasisFig = fig(blocking, 'exit_tax.adjusted_basis', adjBasis, [inp('property.purchase_price', p.purchase_price_cents, docSrc(ctx, 'closing.purchase_price', 'purchase record'), { unit: 'cents' }), inp('property.improvements', p.improvements_cents, manual('improvements entered'), { unit: 'cents' }), figIn(accFig)], 'purchase + improvements − accumulated_depreciation (allowed or allowable)', [], 'Adjusted basis');
  const gainFig = fig(blocking, 'exit_tax.total_gain', totalGain, [figIn(salePriceFig), figIn(sellingFig), figIn(adjBasisFig)], 'amount_realized − adjusted_basis', recognizedOverride !== undefined ? [`Gain recognized now limited to boot: ${(gainBase / 100).toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })}`] : [], 'Total gain');
  const u1250Fig = fig(blocking, 'exit_tax.unrecaptured_1250', unrecaptured, [figIn(gainFig), figIn(accFig)], 'min(total_gain, accumulated_depreciation_SL)', [], 'Unrecaptured §1250 gain');
  const s1245Fig = fig(blocking, 'exit_tax.sec1245', sec1245, [inp('property.cost_seg_study', p.cost_seg_study, manual('property record'))], 'bonus / cost-seg portion of accumulated depreciation', p.cost_seg_study ? [] : ['No cost-seg study; §1245 recapture is 0.'], '§1245 recapture');
  const ltcgFig = fig(blocking, 'exit_tax.ltcg', ltcg, [figIn(gainFig), figIn(u1250Fig), figIn(s1245Fig)], 'total_gain − §1250 − §1245', [], 'Long-term capital gain');
  const stack = [
    `Ordinary taxable income first: wages ${fmtD(hh.wages_cents / 100)} + other ${fmtD(hh.other_income_cents / 100)} − standard deduction ${fmtD(std)}${released ? ` − released suspended losses ${fmtD(released / 100)}` : ''} = ${fmtD(ordinaryTaxable)}.`,
    `§1245 (${fmtD(sec1245 / 100)}) is ordinary income with no cap, stacked next.`,
    `Unrecaptured §1250 (${fmtD(unrecaptured / 100)}) fills the remaining ordinary brackets at min(bracket, 25%) from ${fmtD(top1245)} to ${fmtD(top1250)}.`,
    `Remaining LTCG (${fmtD(ltcg / 100)}) lands above that at 0 / 15 / 20% by position (0% to ${fmtD(l0)}, 15% to ${fmtD(l15)}).`,
    `NIIT 3.8% on min(gain, MAGI incl. gain − ${fmtD(NIIT_T[hh.filing_status] ?? 250_000)}) = ${fmtD(niit)}.`,
    st.note,
  ];
  const fed1250Fig = fig(blocking, 'exit_tax.fed_1250', roundCents(fed1250 * 100), [figIn(u1250Fig), hhSrc('wages_cents'), hhSrc('other_income_cents'), inp('tax_tables.2025.ordinary', hh.filing_status, dflt('IRS 2025 brackets'))], 'ordinary brackets capped at 25%, stacked on ordinary income', [stack[2]], 'Federal on §1250');
  const fed1245Fig = fig(blocking, 'exit_tax.fed_1245', roundCents(fed1245 * 100), [figIn(s1245Fig)], 'ordinary brackets, no cap', [stack[1]], 'Federal on §1245');
  const fedLtcgFig = fig(blocking, 'exit_tax.fed_ltcg', roundCents(fedLtcg * 100), [figIn(ltcgFig), inp('tax_tables.2025.ltcg', hh.filing_status, dflt('IRS 2025 LTCG thresholds'))], '0/15/20% by where the gain lands above ordinary + §1250', [stack[3]], 'Federal LTCG');
  const niitFig = fig(blocking, 'exit_tax.niit', roundCents(niit * 100), [figIn(gainFig), inp('household.magi', hh.magi_cents, ctx.docRefs['form_1040.line11.agi'] ?? manual('household'), { unit: 'cents' })], '3.8% × min(net investment income, MAGI − threshold)', [stack[4]], 'NIIT');
  const stateFig = fig(blocking, 'exit_tax.state', roundCents(st.tax * 100), [figIn(gainFig), inp('property.state', p.state, manual('property record')), inp('states_table', 'fixtures/engine/states.json', dflt('state table, verify: true'))], 'state table (gain as ordinary income unless table says otherwise)', [st.note], `State (${p.state})`);
  const totalFig = fig(blocking, 'exit_tax.total', total, [figIn(fed1250Fig), figIn(fed1245Fig), figIn(fedLtcgFig), figIn(niitFig), figIn(stateFig)], 'fed_1250 + fed_1245 + fed_ltcg + niit + state', stack, 'Exit tax');
  const netProcFig = fig(blocking, 'exit_tax.net_proceeds', netProceeds, [figIn(netBeforeFig), figIn(totalFig)], 'net_before_tax − exit_tax_total', [], 'Net proceeds');
  return {
    sale_price: salePriceFig,
    selling_costs: sellingFig,
    loan_payoffs: payoffFig,
    net_before_tax: netBeforeFig,
    adjusted_basis: adjBasisFig,
    total_gain: gainFig,
    unrecaptured_1250: u1250Fig,
    sec1245: s1245Fig,
    ltcg: ltcgFig,
    fed_1250: fed1250Fig,
    fed_1245: fed1245Fig,
    fed_ltcg: fedLtcgFig,
    niit: niitFig,
    state: stateFig,
    exit_tax_total: totalFig,
    net_proceeds: netProcFig,
    stacking_notes: stack,
  };
}

const fmtD = (d: number) => d.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });

// ---------------------------------------------------------------------------
// §2.10 observations (rule table)
// ---------------------------------------------------------------------------

export const OBSERVATION_RULES: { id: string; text: string }[] = [
  { id: 'cash_flow_negative', text: 'net cash flow < 0' },
  { id: 'dscr_low', text: 'DSCR < 1.2' },
  { id: 'roe_below_reinvest', text: 'ROE < reinvest_rate' },
  { id: 'recapture_heavy', text: 'exit tax > 15% of equity' },
  { id: 'io_ending', text: 'interest-only period ends within 24 months' },
  { id: 'arm_reset', text: 'ARM resets within 24 months' },
  { id: 'loan_maturity', text: 'loan matures within 36 months' },
  { id: 'land_pct_bounded', text: 'land_pct was bounded to [0.60, 0.80]' },
  { id: 'depreciation_mismatch', text: 'depreciation on return differs from allowable by > 5%' },
  { id: 'value_estimated', text: 'value_source is estimated' },
  { id: 'suspended_losses', text: 'suspended losses present (a taxable sale would release them)' },
  { id: 'magi_phaseout', text: 'MAGI phase-out eating the $25k allowance' },
  { id: 'str_flagged', text: 'short-term rental rules not modeled' },
];

function observe(
  p: Property,
  loans: Loan[],
  ncf: Cents,
  noi: Cents,
  ds: Cents,
  roe: number,
  reinvest: number,
  exitTaxTotal: Cents,
  equity: Cents,
  ctx: EngineContext,
  year: number,
  bounded: boolean,
  ledgers: DepreciationLedger[],
): Observation[] {
  const out: Observation[] = [];
  const add = (rule: string, severity: Observation['severity'], message: string, figures: string[]) => out.push({ id: `${p.id}:${rule}`, rule, severity, message, property_id: p.id, figures });
  if (ncf < 0) add('cash_flow_negative', 'warn', `${p.nickname} net cash flow is negative (${fmtD(ncf / 100)}) for ${year}.`, ['cash_flow.net_annual']);
  if (ds > 0 && noi / ds < 1.2) add('dscr_low', 'warn', `${p.nickname} DSCR is ${(noi / ds).toFixed(2)}, below the 1.2 lender floor.`, ['cash_flow.noi', 'cash_flow.debt_service']);
  if (roe < reinvest) add('roe_below_reinvest', 'info', `${p.nickname} ROE ${(roe * 100).toFixed(1)}% is below the ${(reinvest * 100).toFixed(1)}% reinvestment rate.`, ['equity.roe']);
  if (equity > 0 && exitTaxTotal / equity > 0.15) add('recapture_heavy', 'info', `${p.nickname} exit tax (${fmtD(exitTaxTotal / 100)}) is ${((exitTaxTotal / equity) * 100).toFixed(0)}% of equity and grows every year of depreciation.`, ['exit_tax.total', 'equity.equity']);
  const cutoff24 = `${year + 2}-01-01`;
  const cutoff36 = `${year + 3}-01-01`;
  for (const l of loans) {
    if (l.is_paid_off) continue;
    if (l.arm_reset_date && l.arm_reset_date < cutoff24 && l.arm_reset_date >= `${year}-01-01`) add('arm_reset', 'warn', `${p.nickname}: ${l.lender} ARM resets ${l.arm_reset_date} to index + ${((l.arm_index_margin ?? 0) * 100).toFixed(2)}%.`, [`loan.${l.id}.annual_debt_service`]);
    if (l.io_months > 0 && l.loan_type !== 'heloc') {
      const ioEnd = addMonths(l.maturity_date, -(l.term_months - l.io_months));
      if (ioEnd < cutoff24 && ioEnd >= `${year}-01-01`) add('io_ending', 'warn', `${p.nickname}: interest-only period on the ${l.lender} loan ends ${ioEnd}; payment steps up.`, [`loan.${l.id}.annual_debt_service`]);
    }
    if (l.maturity_date < cutoff36) add('loan_maturity', 'warn', `${p.nickname}: ${l.lender} loan matures ${l.maturity_date}.`, [`loan.${l.id}.balance_at_year_end`]);
  }
  if (bounded) add('land_pct_bounded', 'info', `${p.nickname}: land allocation was bounded to the [60%, 80%] range.`, ['depreciation.depreciable_basis']);
  for (const l of ledgers) {
    if (l.allowable_cents > 0 && Math.abs(l.allowed_cents - l.allowable_cents) / l.allowable_cents > 0.05) add('depreciation_mismatch', 'warn', `${p.nickname}: ${l.tax_year} depreciation claimed (${fmtD(l.allowed_cents / 100)}) differs from allowable (${fmtD(l.allowable_cents / 100)}) by ${(((l.allowable_cents - l.allowed_cents) / l.allowable_cents) * 100).toFixed(1)}%.`, ['depreciation.accumulated']);
  }
  if (p.value_source === 'estimated') add('value_estimated', 'info', `${p.nickname} value is an estimate as of ${p.value_as_of}; every figure built on it is Estimated.`, ['equity.value']);
  if (ctx.suspendedLossCents > 0) add('suspended_losses', 'info', `Household carries ${fmtD(ctx.suspendedLossCents / 100)} of suspended passive losses (Form 8582); a fully taxable sale releases them, a 1031 does not.`, ['exit_tax.total']);
  const magi = ctx.household.magi_cents / 100;
  if (magi > 100_000 && !ctx.household.re_professional) {
    const allowance = Math.max(0, 25_000 - 0.5 * (magi - 100_000));
    add('magi_phaseout', 'info', `MAGI ${fmtD(magi)} reduces the $25,000 active-participation allowance to ${fmtD(allowance)}.`, []);
  }
  if (p.property_type === 'vacation_str') add('str_flagged', 'warn', `${p.nickname} is a short-term rental; §469 7-day / §280A rules apply and are not modeled.`, []);
  return out;
}

function addMonths(iso: string, n: number): string {
  const [y, m] = iso.split('-').map(Number);
  const t = y * 12 + (m - 1) + n;
  const yy = Math.floor(t / 12);
  const mm = (t % 12) + 1;
  return `${yy}-${String(mm).padStart(2, '0')}-01`;
}

// ---------------------------------------------------------------------------
// §2.9 strategies — Hold vs Sell vs 1031 on identical assumptions
// ---------------------------------------------------------------------------

export const DEFAULT_EXCHANGE = (p: Property, totalDebt: Cents) => ({
  replacement_value_cents: p.current_value_cents,
  replacement_debt_cents: totalDebt,
  dst: false,
  load_rate: 0.085,
  dst_yield: 0.05,
  cash_taken_cents: 0,
});

export function strategies(ctx: EngineContext, horizon: number, a: ScenarioAssumptions, armIndex = 0.04): StrategyComparison {
  const p = ctx.property;
  const year = ctx.household.tax_year_latest + 1;
  const ov: Overrides = { appreciation_rate: a.appreciation_rate, rent_growth_rate: a.rent_growth, expense_growth_rate: a.expense_growth, reinvest_rate: a.reinvest_rate, arm_index: armIndex };
  const base = analyzeProperty(ctx, year, horizon + 1, ov);
  const blocking = blockingKeys(ctx.findings, p.id);
  const loans = ctx.loans.filter((l) => l.property_id === p.id);
  const totalDebt = base.equity.total_debt.value_cents;
  const dep = depreciationSchedule({ ...p, ...stripUndefined(ov) }, year + horizon);
  const accThrough = (y: number) => dep.rows.filter((r) => r.year <= y).reduce((s, r) => s + r.amount_cents, 0);
  const r = a.reinvest_rate;

  // ---- HOLD
  const holdSeries: StrategySeriesRow[] = [];
  let cumCF = 0;
  let reinvested = 0;
  let holdDeferred = 0;
  let holdEnding = 0;
  let holdExitAtHorizon: ExitTaxAnalysis | null = null;
  for (let i = 1; i <= horizon; i++) {
    const proj = base.cash_flow.projection[i - 1];
    const cf = proj?.net_cash_flow_cents ?? 0;
    cumCF += cf;
    reinvested = roundCents(reinvested * (1 + r) + cf);
    const value = roundCents(p.current_value_cents * Math.pow(1 + a.appreciation_rate, i));
    const debt = base.appreciation.projected[i]?.debt_cents ?? totalDebt;
    const ex = exitTax(ctx, p, blocking, loans, debt, accThrough(year + i - 1), value, 'taxable', base.equity.value, base.depreciation.accumulated, ov);
    holdDeferred = ex.exit_tax_total.value_cents;
    const equity = value - debt;
    holdEnding = equity;
    holdExitAtHorizon = ex;
    holdSeries.push({ year: year + i, cash_flow_cents: cf, equity_cents: equity, value_cents: value, debt_cents: debt, cumulative_tax_deferred_cents: holdDeferred, wealth_cents: equity - holdDeferred + reinvested });
  }
  const holdTerminal = holdSeries[holdSeries.length - 1];
  const hold: StrategyPathResult = {
    path: 'hold',
    label: 'Hold',
    series: holdSeries,
    terminal: {
      terminal_wealth: fig(blocking, 'strategy.hold.terminal_wealth', holdTerminal.wealth_cents, [inp('ending_equity', holdEnding, manual('projection'), { unit: 'cents' }), inp('exit_tax_at_horizon', holdDeferred, manual('projection'), { unit: 'cents' }), inp('reinvested_cash_flows', reinvested, manual('projection'), { unit: 'cents' }), inp('reinvest_rate', r, manual('assumptions'), { unit: 'rate' })], 'ending_equity − exit_tax_at_horizon + Σ cash_flows reinvested at reinvest_rate', [], 'Terminal after-tax wealth'),
      cumulative_cash_flow: fig(blocking, 'strategy.hold.cumulative_cash_flow', cumCF, [figIn(base.cash_flow.net_cash_flow)], 'Σ yearly net cash flow (grown)', [], 'Cumulative cash flow'),
      tax_paid_now: fig(blocking, 'strategy.hold.tax_paid_now', 0, [], 'no sale today', [], 'Tax paid now'),
      deferred_liability: fig(blocking, 'strategy.hold.deferred_liability', holdDeferred, holdExitAtHorizon ? [figIn(holdExitAtHorizon.exit_tax_total)] : [], 'exit tax if sold at horizon end (grows with depreciation and appreciation)', [], 'Deferred exit tax at horizon'),
      ending_equity: fig(blocking, 'strategy.hold.ending_equity', holdEnding, [figIn(base.appreciation.projected_value_horizon)], 'value_horizon − debt_horizon', [], 'Ending equity'),
    },
    caveats: ['Concentration in one asset and one market stays as is.', 'Recapture grows every year: the deferred liability shown is larger at the horizon than today.', 'Management burden continues for the whole horizon.', loans.some((l) => l.loan_type === 'arm') ? 'ARM reset risk is modeled only at the index assumption.' : 'Cash flow projection assumes steady rent and expense growth.'],
  };

  // ---- SELL NOW
  const sellExit = base.exit_tax;
  const proceeds = sellExit.net_proceeds.value_cents;
  const sellSeries: StrategySeriesRow[] = [];
  for (let i = 1; i <= horizon; i++) {
    sellSeries.push({ year: year + i, cash_flow_cents: roundCents(proceeds * Math.pow(1 + r, i - 1) * r), equity_cents: 0, value_cents: 0, debt_cents: 0, cumulative_tax_deferred_cents: 0, wealth_cents: roundCents(proceeds * Math.pow(1 + r, i)) });
  }
  const sellCum = sellSeries.reduce((s, x) => s + x.cash_flow_cents, 0);
  const sell: StrategyPathResult = {
    path: 'sell',
    label: 'Sell now (taxable)',
    series: sellSeries,
    terminal: {
      terminal_wealth: fig(blocking, 'strategy.sell.terminal_wealth', sellSeries[horizon - 1].wealth_cents, [figIn(sellExit.net_proceeds), inp('reinvest_rate', r, manual('assumptions'), { unit: 'rate' }), inp('horizon_years', horizon, manual('horizon'))], 'net_proceeds × (1 + reinvest_rate)^horizon', ['Suspended losses released against ordinary income in the sale year.'], 'Terminal after-tax wealth'),
      cumulative_cash_flow: fig(blocking, 'strategy.sell.cumulative_cash_flow', sellCum, [figIn(sellExit.net_proceeds)], 'Σ yearly return on the reinvested proceeds', [], 'Cumulative cash flow'),
      tax_paid_now: fig(blocking, 'strategy.sell.tax_paid_now', sellExit.exit_tax_total.value_cents, [figIn(sellExit.exit_tax_total)], 'exit_tax_total today', [], 'Tax paid now'),
      deferred_liability: fig(blocking, 'strategy.sell.deferred_liability', 0, [], 'none after a taxable sale', [], 'Deferred liability'),
      ending_equity: fig(blocking, 'strategy.sell.ending_equity', 0, [], 'no property held', [], 'Ending equity'),
    },
    caveats: ['Tax is paid today; the reinvestment assumption carries the whole outcome.', 'Portfolio return is an assumption, not a contract.', 'Loses the rental income stream and any future appreciation.'],
    proceeds_use: [
      { label: 'Gross sale price', value: sellExit.sale_price },
      { label: 'Selling costs', value: sellExit.selling_costs },
      { label: 'Loan payoffs', value: sellExit.loan_payoffs },
      { label: 'Exit tax', value: sellExit.exit_tax_total },
      { label: 'Invested at reinvest rate', value: sellExit.net_proceeds },
    ],
  };

  // ---- 1031 EXCHANGE (incl. DST)
  const ex = a.exchange;
  const oldDebtPaid = totalDebt;
  const mortgageBoot = Math.max(0, oldDebtPaid - ex.replacement_debt_cents);
  const cashBoot = ex.cash_taken_cents;
  const totalBoot = cashBoot + mortgageBoot;
  const bootExit = exitTax(ctx, p, blocking, loans, totalDebt, accThrough(year - 1), p.current_value_cents, 'boot', base.equity.value, base.depreciation.accumulated, ov, totalBoot, false);
  const totalGain = base.exit_tax.total_gain.value_cents;
  const gainRecognized = Math.min(totalBoot, totalGain);
  const taxOnBoot = totalBoot > 0 ? bootExit.exit_tax_total.value_cents : 0;
  const netBefore = base.exit_tax.net_before_tax.value_cents;
  const equityIn = netBefore - cashBoot - taxOnBoot;
  const load = ex.dst ? roundCents(equityIn * ex.load_rate) : 0;
  const working = equityIn - load;
  const replacementValue = ex.dst ? working + ex.replacement_debt_cents : ex.replacement_value_cents;
  // Equal-or-up rule: if the replacement costs more than working equity + new debt, the client adds cash.
  const addedCash = ex.dst ? 0 : Math.max(0, replacementValue - ex.replacement_debt_cents - working);
  const carryoverBasis = base.exit_tax.adjusted_basis.value_cents + Math.max(0, replacementValue - base.exit_tax.sale_price.value_cents) + gainRecognized;
  const deferredGain = totalGain - gainRecognized;
  const newBasisDepreciable = roundCents(Math.max(0, replacementValue - p.current_value_cents) * 0.7);
  const exSeries: StrategySeriesRow[] = [];
  let exDebt = ex.replacement_debt_cents;
  let exReinv = 0;
  let exCum = 0;
  const capRate = 0.055;
  const replPayment = pmt(exDebt, 0.065 / 12, 360) * 12;
  let exDeferred = 0;
  for (let i = 1; i <= horizon; i++) {
    const value = roundCents(replacementValue * Math.pow(1 + a.appreciation_rate, i));
    let cf: number;
    if (ex.dst) {
      cf = roundCents(working * ex.dst_yield * Math.pow(1 + a.rent_growth * 0.5, i - 1));
    } else {
      const noi = replacementValue * capRate * Math.pow(1 + a.rent_growth, i - 1);
      cf = roundCents(noi - replPayment);
      const interest = exDebt * 0.065;
      exDebt = Math.max(0, roundCents(exDebt - Math.max(0, replPayment - interest)));
    }
    exCum += cf;
    exReinv = roundCents(exReinv * (1 + r) + cf);
    // deferred liability: carried gain + depreciation continuing on carryover basis + new basis
    const accCarry = accThrough(year + i - 1) + roundCents((newBasisDepreciable * 0.03636) * i) + roundCents(base.depreciation.depreciable_basis.value_cents * 0.03636 * i);
    const gainAtHorizon = Math.max(0, value * (1 - p.selling_cost_rate) - (carryoverBasis - (accCarry - accThrough(year - 1))));
    const effRate = totalGain > 0 ? base.exit_tax.exit_tax_total.value_cents / totalGain : 0.3;
    exDeferred = roundCents(Math.max(deferredGain, gainAtHorizon) * Math.max(effRate, 0.2));
    const addedCashOpportunity = roundCents(addedCash * Math.pow(1 + r, i));
    exSeries.push({ year: year + i, cash_flow_cents: cf, equity_cents: value - exDebt, value_cents: value, debt_cents: exDebt, cumulative_tax_deferred_cents: exDeferred, wealth_cents: value - exDebt - exDeferred + exReinv - addedCashOpportunity });
  }
  const exTerm = exSeries[horizon - 1];
  const exchange: StrategyPathResult = {
    path: 'exchange',
    label: ex.dst ? '1031 exchange into DST' : '1031 exchange',
    series: exSeries,
    terminal: {
      terminal_wealth: fig(blocking, 'strategy.exchange.terminal_wealth', exTerm.wealth_cents, [inp('replacement_value', replacementValue, manual('assumptions'), { unit: 'cents' }), inp('replacement_debt', ex.replacement_debt_cents, manual('assumptions'), { unit: 'cents' }), inp('deferred_liability', exDeferred, manual('projection'), { unit: 'cents' }), inp('reinvested_distributions', exReinv, manual('projection'), { unit: 'cents' })], 'replacement equity at horizon − deferred liability (shown, not hidden) + Σ distributions reinvested', ['Suspended losses are NOT released by a 1031 exchange.'], 'Terminal after-tax wealth'),
      cumulative_cash_flow: fig(blocking, 'strategy.exchange.cumulative_cash_flow', exCum, [inp(ex.dst ? 'dst_yield' : 'cap_rate', ex.dst ? ex.dst_yield : capRate, ex.dst ? manual('assumptions') : dflt('cap_rate 5.5%'), { unit: 'rate' })], ex.dst ? 'working_equity × dst_yield, grown' : 'replacement NOI (cap rate) − debt service', [], 'Cumulative cash flow'),
      tax_paid_now: fig(blocking, 'strategy.exchange.tax_paid_now', taxOnBoot, [inp('boot_total', totalBoot, manual('boot calculator'), { unit: 'cents' })], 'exit-tax stack applied to gain recognized = min(boot, total_gain)', [], 'Tax paid now (on boot)'),
      deferred_liability: fig(blocking, 'strategy.exchange.deferred_liability', exDeferred, [inp('deferred_gain', deferredGain, manual('projection'), { unit: 'cents' })], 'deferred gain carried at reduced basis, growing with continued depreciation', [], 'Deferred liability at horizon'),
      ending_equity: fig(blocking, 'strategy.exchange.ending_equity', exTerm.equity_cents, [], 'replacement value_horizon − replacement debt_horizon', [], 'Ending equity'),
    },
    caveats: ex.dst
      ? ['DST interests are illiquid; there is no secondary market to speak of.', 'No control: the sponsor decides on sale, refinance and distributions.', 'Sponsor risk and fee drag (load shown explicitly).', 'Deferred gain is still owed at the eventual taxable sale unless stepped up at death.']
      : ['45-day identification / 180-day close windows must be met.', 'Mortgage boot is taxable now when replacement debt is lower.', 'Deferred liability is shown explicitly and keeps growing.', 'Management burden moves to the replacement property.'],
    boot: {
      cash_boot: fig(blocking, 'strategy.exchange.boot.cash', cashBoot, [inp('exchange.cash_taken', cashBoot, manual('assumptions'), { unit: 'cents' })], 'cash_taken', [], 'Cash boot'),
      mortgage_boot: fig(blocking, 'strategy.exchange.boot.mortgage', mortgageBoot, [inp('old_debt_paid_off', oldDebtPaid, manual('loan balances'), { unit: 'cents' }), inp('exchange.replacement_debt', ex.replacement_debt_cents, manual('assumptions'), { unit: 'cents' })], 'max(0, old_debt_paid_off − replacement_debt)', [], 'Mortgage boot'),
      total_boot: fig(blocking, 'strategy.exchange.boot.total', totalBoot, [], 'cash_boot + mortgage_boot', [], 'Total boot'),
      gain_recognized: fig(blocking, 'strategy.exchange.boot.gain_recognized', gainRecognized, [figIn(base.exit_tax.total_gain)], 'min(boot, total_gain)', [], 'Gain recognized'),
      tax_on_boot: fig(blocking, 'strategy.exchange.boot.tax', taxOnBoot, [figIn(bootExit.exit_tax_total)], 'same exit-tax stack on the recognized gain', [], 'Tax on boot'),
    },
    proceeds_use: [
      { label: 'Net before tax', value: base.exit_tax.net_before_tax },
      { label: 'Cash taken (boot)', value: fig(blocking, 'strategy.exchange.use.cash_taken', -cashBoot, [], 'cash_taken', [], 'Cash taken') },
      { label: 'Tax on boot', value: fig(blocking, 'strategy.exchange.use.tax_on_boot', -taxOnBoot, [], 'tax_on_boot', [], 'Tax on boot') },
      { label: ex.dst ? 'DST load' : 'Load / fees', value: fig(blocking, 'strategy.exchange.use.load', -load, [inp('exchange.load_rate', ex.load_rate, manual('assumptions'), { unit: 'rate' })], 'equity_in × load_rate (DST only)', [], 'Load') },
      { label: 'Working equity into replacement', value: fig(blocking, 'strategy.exchange.use.working_equity', working, [], 'net_before_tax − cash_taken − tax_on_boot − load', [], 'Working equity') },
      { label: 'Added cash needed (equal-or-up)', value: fig(blocking, 'strategy.exchange.use.added_cash', addedCash, [inp('exchange.replacement_value', replacementValue, manual('assumptions'), { unit: 'cents' })], 'max(0, replacement_value − replacement_debt − working_equity); its opportunity cost at reinvest_rate is deducted from wealth', [], 'Added cash') },
    ],
  };

  const paths = [hold, sell, exchange];
  const matrix = buildMatrix(paths, ex.dst);
  return {
    property_id: p.id,
    horizon_years: horizon,
    assumptions: a,
    paths,
    matrix,
    caveats: { hold: hold.caveats, sell: sell.caveats, exchange: exchange.caveats },
  };
}

export function buildMatrix(paths: StrategyPathResult[], dst: boolean): Record<MatrixMeasure, Record<StrategyPath, MatrixVerdict>> {
  const numeric = (measure: 'terminal_wealth' | 'cumulative_cash_flow' | 'tax_paid_now', higherIsBetter: boolean): Record<StrategyPath, MatrixVerdict> => {
    const vals = paths.map((p) => ({ path: p.path, v: p.terminal[measure].value_cents }));
    const sorted = [...vals].sort((a, b) => (higherIsBetter ? b.v - a.v : a.v - b.v));
    const best = sorted[0].v;
    const worst = sorted[sorted.length - 1].v;
    const out = {} as Record<StrategyPath, MatrixVerdict>;
    const spread = Math.abs(best - worst);
    const tol = Math.max(Math.abs(best) * 0.02, 1);
    for (const { path, v } of vals) {
      if (spread <= tol) out[path] = 'neutral';
      else if (v === best) out[path] = 'leads';
      else if (v === worst) out[path] = 'trails';
      else out[path] = 'neutral';
    }
    return out;
  };
  return {
    terminal_wealth: numeric('terminal_wealth', true),
    cumulative_cash_flow: numeric('cumulative_cash_flow', true),
    tax_paid_now: numeric('tax_paid_now', false),
    liquidity: { hold: 'neutral', sell: 'leads', exchange: dst ? 'trails' : 'neutral' },
    management_burden: { hold: 'trails', sell: 'leads', exchange: dst ? 'leads' : 'neutral' },
    concentration: { hold: 'trails', sell: 'leads', exchange: 'neutral' },
  };
}

// ---------------------------------------------------------------------------
// POST /simulate — buy/sell/exchange/refi timeline with Monte Carlo bands
// ---------------------------------------------------------------------------

function mulberry32(seed: number) {
  let t = seed >>> 0;
  return () => {
    t = (t + 0x6d2b79f5) >>> 0;
    let x = t;
    x = Math.imul(x ^ (x >>> 15), x | 1);
    x ^= x + Math.imul(x ^ (x >>> 7), x | 61);
    return ((x ^ (x >>> 14)) >>> 0) / 4294967296;
  };
}
function gauss(rnd: () => number): number {
  const u = Math.max(rnd(), 1e-12);
  const v = rnd();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

export function simulate(req: SimulationRequest): SimulationResult {
  const runs = Math.max(1, Math.min(2000, req.monte_carlo.runs || 200));
  const years = Math.max(1, Math.min(40, req.years));
  const perYear: { nw: number[]; cf: number[]; tax: number[] }[] = Array.from({ length: years }, () => ({ nw: [], cf: [], tax: [] }));
  const eqDebt: { eq: number; debt: number }[] = Array.from({ length: years }, () => ({ eq: 0, debt: 0 }));
  for (let run = 0; run < runs; run++) {
    const rnd = mulberry32(1337 + run * 7919);
    const props = req.properties.map((p) => ({ ...p, value: p.current_value_cents, debt: p.debt_cents, noi: p.noi_cents, basis: roundCents(p.purchase_price_cents * (1 - p.land_pct)), acc: 0, active: true, rate: 0.06 }));
    let cash = 0;
    for (let i = 0; i < years; i++) {
      const year = req.start_year + i;
      const appr = req.assumptions.appreciation_rate + gauss(rnd) * req.monte_carlo.appr_sigma;
      const rg = req.assumptions.rent_growth + gauss(rnd) * req.monte_carlo.rent_sigma;
      let taxes = 0;
      let cf = 0;
      for (const ev of req.events.filter((e) => e.year === year)) {
        if (ev.type === 'buy') {
          props.push({ nickname: ev.property_ref, property_type: 'sfr', current_value_cents: ev.amount_cents ?? 0, debt_cents: ev.debt_cents ?? 0, noi_cents: roundCents((ev.amount_cents ?? 0) * req.assumptions.cap_rate), purchase_price_cents: ev.amount_cents ?? 0, purchase_date: `${year}-01-01`, land_pct: 0.7, value: ev.amount_cents ?? 0, debt: ev.debt_cents ?? 0, noi: roundCents((ev.amount_cents ?? 0) * req.assumptions.cap_rate), basis: roundCents((ev.amount_cents ?? 0) * 0.3), acc: 0, active: true, rate: ev.rate ?? 0.065 });
          cash -= (ev.amount_cents ?? 0) - (ev.debt_cents ?? 0);
        }
        const target = props.find((p) => p.active && p.nickname === ev.property_ref);
        if (!target) continue;
        if (ev.type === 'sell') {
          const gain = Math.max(0, target.value * 0.94 - (target.purchase_price_cents - target.acc));
          const t = roundCents(Math.min(gain, target.acc) * 0.25 + Math.max(0, gain - target.acc) * 0.15 + gain * 0.038 + gain * 0.093);
          taxes += t;
          cash += target.value * 0.94 - target.debt - t;
          target.active = false;
        } else if (ev.type === 'exchange') {
          const newVal = ev.amount_cents ?? target.value;
          const newDebt = ev.debt_cents ?? target.debt;
          const boot = Math.max(0, target.debt - newDebt);
          const t = roundCents(boot * 0.3);
          taxes += t;
          cash -= t;
          target.value = newVal;
          target.debt = newDebt;
          target.noi = roundCents(newVal * req.assumptions.cap_rate);
        } else if (ev.type === 'refi') {
          const newDebt = ev.debt_cents ?? target.debt;
          cash += newDebt - target.debt;
          target.debt = newDebt;
          target.rate = ev.rate ?? target.rate;
        }
      }
      let eq = 0;
      let debt = 0;
      for (const p of props) {
        if (!p.active) continue;
        const ds = p.debt * p.rate + p.debt * 0.012;
        const pcf = p.noi - ds;
        cf += pcf;
        p.debt = Math.max(0, p.debt - p.debt * 0.012);
        p.value = roundCents(p.value * (1 + appr));
        p.noi = roundCents(p.noi * (1 + rg));
        p.acc += roundCents(p.basis * 0.03636);
        eq += p.value - p.debt;
        debt += p.debt;
      }
      cash = roundCents(cash * (1 + req.assumptions.reinvest_rate) + cf);
      const nw = eq + cash;
      perYear[i].nw.push(nw);
      perYear[i].cf.push(cf);
      perYear[i].tax.push(taxes);
      if (run === 0) eqDebt[i] = { eq, debt };
    }
  }
  const band = (xs: number[]): PercentileBand => {
    const s = [...xs].sort((a, b) => a - b);
    const q = (p: number) => s[Math.min(s.length - 1, Math.floor(p * (s.length - 1)))];
    return { p10: roundCents(q(0.1)), p50: roundCents(q(0.5)), p90: roundCents(q(0.9)) };
  };
  const series: SimulationYear[] = perYear.map((y, i) => ({ year: req.start_year + i, net_worth: band(y.nw), cash_flow: band(y.cf), taxes_paid: band(y.tax), equity_cents: roundCents(eqDebt[i].eq), debt_cents: roundCents(eqDebt[i].debt), events: req.events.filter((e) => e.year === req.start_year + i) }));
  const cumTax = perYear[0].tax.map((_, run) => perYear.reduce((s, y) => s + y.tax[run], 0));
  return { series, runs, terminal: { net_worth: series[series.length - 1].net_worth, cumulative_taxes: band(cumTax) } };
}

// ---------------------------------------------------------------------------
// Fact sheets
// ---------------------------------------------------------------------------

const PLATFORM_FIELDS: Record<Exclude<FactSheetFormat, 'json' | 'csv'>, { label: string; map: Record<string, string> }> = {
  emoney: {
    label: 'eMoney',
    map: { value: 'Real Estate Asset › Current Market Value', debt: 'Liability › Mortgage › Current Balance', net_rental_income: 'Income › Rental Income (Net, Annual)', equity: 'Net Worth › Real Estate Equity (derived)', exit_tax: 'Advanced Planning › Embedded Capital Gains Tax', depreciation: 'Tax › Depreciation (Schedule E line 18)' },
  },
  rightcapital: {
    label: 'RightCapital',
    map: { value: 'Net Worth › Property › Current Value', debt: 'Net Worth › Liability › Mortgage Balance', net_rental_income: 'Income › Rental Income › Annual Net Amount', equity: 'Property › Net Equity', exit_tax: 'Tax › Capital Gains on Sale (estimate)', depreciation: 'Tax › Rental Depreciation' },
  },
  mgp: {
    label: 'MoneyGuidePro',
    map: { value: 'Assets › Real Estate › Rental Property › Value', debt: 'Liabilities › Mortgage › Balance', net_rental_income: 'Income › Other Income › Rental Income (annual, net)', equity: 'Assets › Real Estate › Equity (derived)', exit_tax: 'Assets › Real Estate › Cost Basis / Tax on Sale', depreciation: 'Not mapped (MGP has no depreciation field)' },
  },
};

export function factSheet(analysis: PropertyAnalysis, format: FactSheetFormat): FactSheet {
  const rows: FactSheetRow[] = [];
  const src = format === 'json' || format === 'csv' ? PLATFORM_FIELDS.emoney : PLATFORM_FIELDS[format];
  const push = (key: string, f: Figure | null, note: string | null = null) =>
    rows.push({ groundplan_key: key, platform_field: src.map[key] ?? key, value_cents: f ? f.value_cents : null, value_text: null, status: (f?.status ?? 'confirmed') as FigureStatus, note });
  push('value', analysis.equity.value, analysis.property.value_source === 'estimated' ? 'Estimated value; platforms accept it but it is not confirmed.' : null);
  push('debt', analysis.equity.total_debt);
  push('net_rental_income', analysis.cash_flow.net_cash_flow, 'Engine net cash flow (after reserves and debt service).');
  push('equity', analysis.equity.equity);
  push('exit_tax', analysis.exit_tax.exit_tax_total, 'Embedded tax if sold this year.');
  push('depreciation', analysis.depreciation.annual, format === 'mgp' ? 'MGP does not carry depreciation; shown for completeness.' : null);
  return { property_id: analysis.property.id, format, platform_label: format === 'json' || format === 'csv' ? 'Groundplan' : src.label, rows, as_of: `${analysis.year}-12-31` };
}

/** Depth-first search of the analysis tree for a Figure by key (GET /properties/{id}/figure/{key}). */
export function findFigure(root: unknown, key: string, depth = 0): Figure | null {
  if (!root || typeof root !== 'object' || depth > 8) return null;
  if (Array.isArray(root)) {
    for (const x of root) {
      const f = findFigure(x, key, depth + 1);
      if (f) return f;
    }
    return null;
  }
  const o = root as Record<string, unknown>;
  if (typeof o.key === 'string' && o.key === key && Array.isArray(o.inputs) && typeof o.formula === 'string') return o as unknown as Figure;
  for (const v of Object.values(o)) {
    const f = findFigure(v, key, depth + 1);
    if (f) return f;
  }
  return null;
}
