/**
 * Runtime validation at the API boundary (Zod 4) for the payloads every chart and headline figure reads:
 * dashboard, property analysis, strategy comparison (+ meta and workspace, which the shell needs).
 *
 * Why: the FastAPI OpenAPI document declares these responses as `{}` (untyped dicts), and two backends
 * (Python and Go) serve the same contract. A field rename on either side should produce a clear
 * "contract drift" error naming the path, not NaN or $0 on screen. The schemas are deliberately LOOSE
 * (`z.looseObject`): unknown extra fields pass through untouched, only what the UI reads is checked.
 * Decimal rates arrive from Python as strings ("0.060000"), so rate fields coerce to number here, once.
 */
import { z } from 'zod';

const cents = z.number().int();
const rate = z.coerce.number();
const status = z.enum(['confirmed', 'estimated', 'blocked']);

export interface FigureT {
  key: string;
  value_cents: number;
  status: 'confirmed' | 'estimated' | 'blocked';
  inputs: FigureInputT[];
  formula: string;
  notes: string[];
  label?: string | null;
  unit?: string | null;
  /** set for unit 'ratio' figures (DSCR): the API sends value_cents null and the ratio in `value` */
  ratio?: number | null;
}
export interface FigureInputT {
  key: string;
  value: unknown;
  source: { type: string; ref?: string | null; page?: number | null; document_id?: string | null; bbox?: number[] | null };
  figure?: FigureT;
  unit?: string | null;
  label?: string | null;
  status?: string | null;
}

export const FigureInput: z.ZodType<FigureInputT> = z.lazy(() =>
  z.looseObject({
    key: z.string(),
    value: z.unknown(),
    source: z.looseObject({
      type: z.string(),
      ref: z.string().nullish(),
      page: z.number().nullish(),
      document_id: z.string().nullish(),
      bbox: z.array(z.number()).nullish(),
    }),
    figure: Figure.optional(),
    unit: z.string().nullish(),
    label: z.string().nullish(),
    status: z.string().nullish(),
  }),
);

/**
 * Ratio figures (DSCR) carry `value_cents: null` and the ratio as a Decimal string in `value`.
 * Normalize once here: `ratio` holds the number and value_cents holds ratio × 100 so sorting and
 * charts keep working; anything else with a null value_cents is still a contract error.
 */
const ratioFix = (raw: unknown) => {
  if (raw && typeof raw === 'object' && (raw as { value_cents?: unknown }).value_cents === null && (raw as { unit?: unknown }).unit === 'ratio') {
    const r = Number((raw as { value?: unknown }).value);
    if (Number.isFinite(r)) return { ...(raw as object), value_cents: Math.round(r * 100), ratio: r };
  }
  return raw;
};

export const Figure: z.ZodType<FigureT> = z.lazy(() =>
  z.preprocess(ratioFix, z.looseObject({
    key: z.string(),
    value_cents: cents,
    status,
    inputs: z.array(FigureInput).default([]),
    formula: z.string().default(''),
    notes: z.array(z.string()).default([]),
    label: z.string().nullish(),
    unit: z.string().nullish(),
    ratio: z.number().nullish(),
  })),
);

const Property = z.looseObject({
  id: z.string(),
  household_id: z.string(),
  nickname: z.string(),
  address_line1: z.string(),
  city: z.string(),
  state: z.string(),
  zip: z.string(),
  property_type: z.string(),
  units: z.number(),
  purchase_date: z.string(),
  purchase_price_cents: cents,
  current_value_cents: cents,
  value_source: z.string(),
  value_as_of: z.string().nullish(),
  land_pct: rate,
  appreciation_rate: rate,
  rent_growth_rate: rate,
  expense_growth_rate: rate,
  vacancy_rate: rate,
  capex_reserve_rate: rate,
  selling_cost_rate: rate,
  status: z.string(),
});

const Observation = z.looseObject({
  id: z.string(),
  severity: z.enum(['info', 'warn', 'block']),
  rule: z.string(),
  message: z.string(),
  property_id: z.string().nullish(),
  figures: z.array(z.string()).default([]),
});

export const PropertyCardSchema = z.looseObject({
  property: Property,
  value: Figure,
  equity: Figure,
  net_cash_flow: Figure,
  exit_tax: Figure,
  roe: Figure,
  roe_rate: rate,
  status_chips: z.array(status),
  open_findings: z.number().int(),
});

export const DashboardSchema = z.looseObject({
  household: z.looseObject({
    id: z.string(),
    name: z.string(),
    filing_status: z.enum(['single', 'mfj', 'mfs', 'hoh']),
    state: z.string(),
    tax_year_latest: z.number().int(),
    wages_cents: cents,
    other_income_cents: cents,
    magi_cents: cents,
    active_participation: z.boolean(),
    re_professional: z.boolean(),
    goal: z.string().default(''),
  }),
  metrics: z.looseObject({
    total_value: Figure,
    total_equity: Figure,
    net_cash_flow: Figure,
    exit_tax_total: Figure,
    total_debt: Figure.optional(),
    suspended_losses: Figure.optional(),
  }),
  observations: z.array(Observation),
  properties: z.array(PropertyCardSchema),
  findings_open: z.number().int(),
  narrative: z.looseObject({ text: z.string(), provider: z.string(), generated_at: z.string().nullish() }),
});

const TaxLayer = z.looseObject({ rate, lower_cents: cents, upper_cents: cents, amount_cents: cents, tax_cents: cents });

const LoanMonth = z.looseObject({
  index: z.number().int(),
  year: z.number().int(),
  month: z.number().int(),
  rate,
  payment_cents: cents,
  interest_cents: cents,
  principal_cents: cents,
  balance_cents: cents,
  phase: z.string().nullish(),
});

export const AnalysisSchema = z.looseObject({
  property: Property,
  year: z.number().int(),
  horizon: z.number().int(),
  cash_flow: z.looseObject({
    gross_rent: Figure,
    vacancy_loss: Figure,
    other_income: Figure,
    operating_expenses: Figure,
    capex_reserve: Figure,
    noi: Figure,
    debt_service: Figure,
    net_cash_flow: Figure,
    projection: z.array(z.looseObject({ year: z.number().int(), noi_cents: cents, debt_service_cents: cents, net_cash_flow_cents: cents })),
    schedule_e_bridge: z.looseObject({
      line21: Figure,
      line18_depreciation: Figure,
      principal_paid: Figure,
      capital_improvements_paid: Figure,
      cash_flow_from_return: Figure,
      delta_vs_engine: Figure,
    }),
  }),
  equity: z.looseObject({ value: Figure, total_debt: Figure, equity: Figure, lendable_equity: Figure, roe: Figure, roe_rate: rate }),
  appreciation: z.looseObject({
    cagr_since_purchase: rate.nullish(),
    projected: z.array(z.looseObject({ year: z.number().int(), value_cents: cents, equity_cents: cents, debt_cents: cents })),
    projected_value_horizon: Figure,
  }),
  depreciation: z.looseObject({
    schedule: z.array(z.looseObject({ year: z.number().int(), amount_cents: cents, method: z.string().nullish(), pct: rate.nullish() })),
    accumulated: Figure,
    depreciable_basis: Figure,
    annual: Figure,
    method: z.string(),
    land_pct_bounded: z.boolean(),
  }),
  exit_tax: z.looseObject({
    sale_price: Figure,
    selling_costs: Figure,
    loan_payoffs: Figure,
    net_before_tax: Figure,
    adjusted_basis: Figure,
    total_gain: Figure,
    unrecaptured_1250: Figure,
    sec1245: Figure,
    ltcg: Figure,
    fed_1250: Figure,
    fed_1245: Figure,
    fed_ltcg: Figure,
    niit: Figure,
    state: Figure,
    exit_tax_total: Figure,
    net_proceeds: Figure,
    stacking_notes: z.array(z.string()),
    ordinary_taxable_other: z.union([Figure, cents]).optional(),
    layers_1245: z.array(TaxLayer).optional(),
    layers_1250: z.array(TaxLayer).optional(),
    layers_ltcg: z.array(TaxLayer).optional(),
  }),
  loans: z.array(
    z.looseObject({
      loan: z.looseObject({
        id: z.string(),
        lender: z.string(),
        loan_type: z.string(),
        balance_cents: cents,
        rate,
        lien_position: z.number().int(),
        is_paid_off: z.boolean(),
        maturity_date: z.string().nullish(),
        arm_reset_date: z.string().nullish(),
        io_months: z.number().int().nullish(),
      }),
      annual: z.array(
        z.looseObject({ year: z.number().int(), principal_cents: cents, interest_cents: cents, balance_end_cents: cents, rate, marker: z.string().nullish() }),
      ),
      months: z.array(LoanMonth).default([]),
      dscr: Figure,
      annual_debt_service: Figure,
      balance_at_year_end: Figure,
    }),
  ),
  observations: z.array(Observation),
});

const SeriesRow = z.looseObject({
  year: z.number().int(),
  cash_flow_cents: cents,
  equity_cents: cents,
  value_cents: cents,
  debt_cents: cents,
  cumulative_tax_deferred_cents: cents,
  wealth_cents: cents,
});
const pathEnum = z.enum(['hold', 'sell', 'exchange']);
const verdict = z.enum(['leads', 'trails', 'neutral']);

export const StrategiesSchema = z.looseObject({
  property_id: z.string(),
  horizon_years: z.number().int(),
  assumptions: z.looseObject({
    appreciation_rate: rate,
    rent_growth: rate,
    expense_growth: rate,
    reinvest_rate: rate,
    exchange: z.looseObject({
      replacement_value_cents: cents,
      replacement_debt_cents: cents,
      dst: z.boolean(),
      load_rate: rate,
      dst_yield: rate,
      cash_taken_cents: cents,
    }),
  }),
  paths: z.array(
    z.looseObject({
      path: pathEnum,
      label: z.string(),
      series: z.array(SeriesRow),
      terminal: z.looseObject({ terminal_wealth: Figure, cumulative_cash_flow: Figure, tax_paid_now: Figure, deferred_liability: Figure, ending_equity: Figure }),
      caveats: z.array(z.string()),
      boot: z.looseObject({ cash_boot: Figure, mortgage_boot: Figure, total_boot: Figure, gain_recognized: Figure, tax_on_boot: Figure }).nullish(),
      proceeds_use: z.array(z.looseObject({ label: z.string(), value: Figure })).nullish(),
    }),
  ),
  matrix: z.record(z.string(), z.record(z.string(), verdict)),
});

export const MetaSchema = z.looseObject({
  backend: z.string(),
  version: z.string().nullish(),
  engine: z.string().nullish(),
  runtime: z.string().nullish(),
  started_at: z.string().nullish(),
  db: z.string().nullish(),
});

export const WorkspaceSchema = z.looseObject({ id: z.string(), created_at: z.string().nullish(), households: z.number().nullish(), documents: z.number().nullish() });

export type DashboardT = z.infer<typeof DashboardSchema>;
export type AnalysisT = z.infer<typeof AnalysisSchema>;
export type StrategiesT = z.infer<typeof StrategiesSchema>;
export type StrategyPathT = StrategiesT['paths'][number];
export type PropertyCardT = z.infer<typeof PropertyCardSchema>;
export type MetaT = z.infer<typeof MetaSchema>;
export type TaxLayerT = z.infer<typeof TaxLayer>;
export type LoanSummaryT = AnalysisT['loans'][number];
export type LoanMonthT = z.infer<typeof LoanMonth>;
