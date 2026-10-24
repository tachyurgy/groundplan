/**
 * Groundplan API types — mirror SPEC §1 (domain model) and §3 (API shapes) exactly.
 *
 * Conventions (SPEC §1):
 *  - All money is integer CENTS (`number`, integral). Rendered as dollars only in the UI.
 *  - Rates are decimals (0.035 = 3.5%).
 *  - Dates are ISO `YYYY-MM-DD` strings.
 *  - Every analytic number is a `Figure` carrying provenance.
 */

export type Cents = number; // integer cents
export type Rate = number; // decimal, 0.035 = 3.5%
export type ISODate = string; // YYYY-MM-DD
export type ISODateTime = string;

// ---------------------------------------------------------------------------
// §1 Domain model
// ---------------------------------------------------------------------------

export type FilingStatus = 'single' | 'mfj' | 'mfs' | 'hoh';

export interface Advisor {
  id: string;
  firm_name: string;
  name: string;
  email: string;
}

export interface Household {
  id: string;
  advisor_id: string;
  name: string;
  filing_status: FilingStatus;
  state: string; // 2-letter
  tax_year_latest: number;
  wages_cents: Cents;
  other_income_cents: Cents;
  magi_cents: Cents;
  active_participation: boolean;
  re_professional: boolean;
  goal: string;
  notes: string;
}

export type PropertyType = 'sfr' | 'multifamily' | 'vacation_str' | 'commercial' | 'land' | 'self_rental' | 'other';

export type ValueSource = 'estimated' | 'confirmed';
export type PropertyStatus = 'active' | 'sold' | 'converted';

export interface Property {
  id: string;
  household_id: string;
  nickname: string;
  address_line1: string;
  city: string;
  state: string;
  zip: string;
  property_type: PropertyType;
  units: number;
  purchase_date: ISODate;
  purchase_price_cents: Cents;
  placed_in_service_date: ISODate;
  land_pct: Rate; // LAND share 0.20..0.40 (improvements 60-80%), default 0.30
  improvements_cents: Cents;
  cost_seg_study: boolean;
  current_value_cents: Cents;
  value_source: ValueSource;
  value_as_of: ISODate;
  appreciation_rate: Rate;
  rent_growth_rate: Rate;
  expense_growth_rate: Rate;
  vacancy_rate: Rate;
  mgmt_fee_rate: Rate;
  capex_reserve_rate: Rate;
  selling_cost_rate: Rate; // default 0.06
  status: PropertyStatus;
}

export type LoanType = 'fixed' | 'arm' | 'interest_only' | 'heloc' | 'balloon';

export interface Loan {
  id: string;
  property_id: string;
  lender: string;
  loan_type: LoanType;
  original_cents: Cents;
  balance_cents: Cents;
  balance_as_of: ISODate;
  rate: Rate;
  term_months: number;
  io_months: number; // 0 if none
  arm_reset_date: ISODate | null;
  arm_index_margin: Rate | null;
  monthly_payment_cents: Cents;
  maturity_date: ISODate;
  lien_position: number; // 1..n
  is_paid_off: boolean;
}

export interface RentRoll {
  id: string;
  property_id: string;
  tax_year: number;
  gross_rent_cents: Cents;
  other_income_cents: Cents;
}

/** Schedule E lines for one property-year. */
export interface ExpenseYear {
  id: string;
  property_id: string;
  tax_year: number;
  taxes_cents: Cents;
  insurance_cents: Cents;
  repairs_cents: Cents;
  mgmt_cents: Cents;
  utilities_cents: Cents;
  hoa_cents: Cents;
  other_cents: Cents;
  mortgage_interest_cents: Cents;
  depreciation_cents: Cents;
}

export type DepreciationMethod = 'sl_27_5' | 'sl_39' | 'cost_seg' | 'bonus';

export interface DepreciationLedger {
  id: string;
  property_id: string;
  tax_year: number;
  allowed_cents: Cents;
  allowable_cents: Cents;
  method: DepreciationMethod;
  note: string;
}

/** Form 8582 carryforward. */
export interface SuspendedLoss {
  id: string;
  household_id: string;
  tax_year: number;
  carryforward_cents: Cents;
}

export type DocumentKind =
  'form_1040' | 'schedule_e' | 'form_4562' | 'form_8582' | 'mortgage_statement' | 'closing_statement' | 'lease' | 'appraisal' | 'other';

export type DocumentStatus = 'queued' | 'extracted' | 'reconciled' | 'discarded';

export interface Document {
  id: string;
  household_id: string;
  kind: DocumentKind;
  tax_year: number | null;
  filename: string;
  sha256: string;
  page_count: number;
  uploaded_at: ISODateTime;
  status: DocumentStatus;
  /** Always false: the file is processed in memory and dropped; only sha256 + fields persist. */
  bytes_retained: false;
}

export type FieldUnit = 'cents' | 'date' | 'text' | 'bool' | 'rate' | 'ratio';
export type ExtractorKind = 'rules' | 'ocr' | 'llm';
export type EntityHint = 'household' | 'property';

/** [x0, y0, x1, y1] in PDF points (origin bottom-left, as pdfplumber/pdf.js report). */
export type BBox = [number, number, number, number];

export interface ExtractedField {
  id: string;
  document_id: string;
  entity_hint: EntityHint;
  property_key: string | null; // normalized address or column id
  field: string; // e.g. "schedule_e.line3.rents"
  value: unknown; // json
  unit: FieldUnit;
  page: number; // 1-based
  bbox: BBox;
  confidence: number; // 0..1
  extractor: ExtractorKind;
  raw_text: string;
}

export type FindingKind = 'conflict' | 'missing' | 'outlier' | 'stale' | 'unsupported_structure';
export type Severity = 'info' | 'warn' | 'block';
export type FindingStatus = 'open' | 'resolved' | 'dismissed';

export interface FindingCandidate {
  source: string;
  value: unknown;
  document_id: string | null;
  page: number | null;
}

export interface FindingResolution {
  value: unknown;
  who: string;
  when: ISODateTime;
  note: string;
}

export interface Finding {
  id: string;
  household_id: string;
  property_id: string | null;
  kind: FindingKind;
  field: string;
  severity: Severity;
  message: string;
  candidates: FindingCandidate[];
  status: FindingStatus;
  resolution: FindingResolution | null;
}

// --- Figure: the API shape for any computed number (not a table) ---------------

export type FigureStatus = 'confirmed' | 'estimated' | 'blocked';
export type SourceType = 'document' | 'manual' | 'public_data' | 'default';

export interface FigureSource {
  type: SourceType;
  ref: string;
  page?: number | null;
  document_id?: string | null;
  bbox?: BBox | null;
}

export interface FigureInput {
  key: string;
  value: unknown;
  source: FigureSource;
  /** Optional nested Figure when an input is itself computed (the full inputs tree). */
  figure?: Figure;
  unit?: FieldUnit;
  label?: string;
}

export interface Figure {
  key: string; // e.g. "cash_flow.net_annual"
  value_cents: Cents;
  status: FigureStatus;
  inputs: FigureInput[];
  formula: string;
  notes: string[];
  label?: string;
  unit?: FieldUnit;
  ratio?: number;
}

export interface ExchangeAssumptions {
  replacement_value_cents: Cents;
  replacement_debt_cents: Cents;
  dst: boolean;
  load_rate: Rate; // default 0.085 for DST
  dst_yield: Rate; // default 0.05
  cash_taken_cents: Cents;
}

export interface ScenarioAssumptions {
  appreciation_rate: Rate;
  rent_growth: Rate;
  expense_growth: Rate;
  reinvest_rate: Rate; // default 0.06
  sale_year: number;
  exchange: ExchangeAssumptions;
}

export interface Scenario {
  id: string;
  property_id: string;
  name: string;
  horizon_years: number; // default 10
  assumptions: ScenarioAssumptions;
  results: StrategyComparison | null; // json cache
}

export type AlertKind = 'arm_reset' | 'io_period_ending' | 'cash_flow_negative' | 'value_drift' | 'loan_maturity' | 'roe_below_threshold';

export interface Alert {
  id: string;
  household_id: string;
  property_id: string | null;
  kind: AlertKind;
  due_date: ISODate;
  message: string;
  status: 'open' | 'acknowledged' | 'resolved';
}

// ---------------------------------------------------------------------------
// §3 API shapes
// ---------------------------------------------------------------------------

export interface HouseholdSummary {
  id: string;
  name: string;
  state: string;
  filing_status: FilingStatus;
  property_count: number;
  net_cash_flow_cents: Cents;
  total_equity_cents: Cents;
  open_findings: number;
  status: FigureStatus;
}

export interface Observation {
  id: string;
  severity: Severity;
  rule: string; // rule id from the observations table
  message: string;
  property_id: string | null;
  figures: string[]; // figure keys cited
}

export interface PropertyCard {
  property: Property;
  value: Figure;
  equity: Figure;
  net_cash_flow: Figure;
  exit_tax: Figure;
  /** ROE as a Figure whose value_cents is the numerator (cash flow + paydown + appreciation); rate in roe_rate. */
  roe: Figure;
  roe_rate: Rate;
  status_chips: FigureStatus[];
  open_findings: number;
}

export interface Narrative {
  text: string;
  provider: 'template' | 'llm';
  generated_at: ISODateTime;
}

export interface Dashboard {
  household: Household;
  metrics: Record<string, Figure>;
  observations: Observation[];
  properties: PropertyCard[];
  findings_open: number;
  narrative: Narrative;
}

export interface DepreciationScheduleRow {
  year: number;
  amount_cents: Cents;
  method: DepreciationMethod;
  pct: number | null;
}

export interface LoanYearRow {
  year: number;
  principal_cents: Cents;
  interest_cents: Cents;
  balance_end_cents: Cents;
  rate: Rate;
  marker: 'io' | 'arm_reset' | 'balloon' | 'maturity' | null;
}

export interface LoanMonthRow {
  index: number;
  year: number;
  month: number;
  rate: Rate;
  payment_cents: Cents;
  interest_cents: Cents;
  principal_cents: Cents;
  balance_cents: Cents;
  phase: string;
}

export interface LoanScheduleSummary {
  loan: Loan;
  annual: LoanYearRow[];
  months?: LoanMonthRow[];
  months_total?: number;
  dscr: Figure;
  annual_debt_service: Figure;
  balance_at_year_end: Figure;
}

export interface ScheduleEBridge {
  line21: Figure;
  line18_depreciation: Figure;
  principal_paid: Figure;
  capital_improvements_paid: Figure;
  cash_flow_from_return: Figure;
  delta_vs_engine: Figure;
}

export interface CashFlowAnalysis {
  gross_rent: Figure;
  vacancy_loss: Figure;
  other_income: Figure;
  operating_expenses: Figure;
  capex_reserve: Figure;
  noi: Figure;
  debt_service: Figure;
  net_cash_flow: Figure;
  projection: { year: number; noi_cents: Cents; debt_service_cents: Cents; net_cash_flow_cents: Cents }[];
  schedule_e_bridge: ScheduleEBridge;
}

export interface EquityAnalysis {
  value: Figure;
  total_debt: Figure;
  equity: Figure;
  lendable_equity: Figure;
  roe: Figure;
  roe_rate: Rate;
  concentration: Figure | null;
}

export interface AppreciationAnalysis {
  cagr_since_purchase: Rate;
  projected: { year: number; value_cents: Cents; equity_cents: Cents; debt_cents: Cents }[];
  projected_value_horizon: Figure;
}

export interface DepreciationAnalysis {
  schedule: DepreciationScheduleRow[];
  accumulated_cents: Cents;
  accumulated: Figure;
  depreciable_basis: Figure;
  annual: Figure;
  method: DepreciationMethod;
  land_pct_bounded: boolean;
}

export interface ExitTaxAnalysis {
  sale_price: Figure;
  selling_costs: Figure;
  loan_payoffs: Figure;
  net_before_tax: Figure;
  adjusted_basis: Figure;
  total_gain: Figure;
  unrecaptured_1250: Figure;
  sec1245: Figure;
  ltcg: Figure;
  fed_1250: Figure;
  fed_1245: Figure;
  fed_ltcg: Figure;
  niit: Figure;
  state: Figure;
  exit_tax_total: Figure;
  net_proceeds: Figure;
  stacking_notes: string[];
  ordinary_taxable_other?: Figure;
  layers_1245?: TaxLayer[];
  layers_1250?: TaxLayer[];
  layers_ltcg?: TaxLayer[];
}

export interface TaxLayer {
  rate: number;
  lower_cents: Cents;
  upper_cents: Cents;
  amount_cents: Cents;
  tax_cents: Cents;
}

export interface PropertyAnalysis {
  property: Property;
  year: number;
  horizon: number;
  cash_flow: CashFlowAnalysis;
  equity: EquityAnalysis;
  appreciation: AppreciationAnalysis;
  depreciation: DepreciationAnalysis;
  exit_tax: ExitTaxAnalysis;
  loans: LoanScheduleSummary[];
  observations: Observation[];
}

export type StrategyPath = 'hold' | 'sell' | 'exchange';
export type MatrixVerdict = 'leads' | 'trails' | 'neutral';
export type MatrixMeasure = 'terminal_wealth' | 'cumulative_cash_flow' | 'tax_paid_now' | 'liquidity' | 'management_burden' | 'concentration';

export interface StrategySeriesRow {
  year: number;
  cash_flow_cents: Cents;
  equity_cents: Cents;
  value_cents: Cents;
  debt_cents: Cents;
  cumulative_tax_deferred_cents: Cents;
  wealth_cents: Cents;
}

export interface StrategyPathResult {
  path: StrategyPath;
  label: string;
  series: StrategySeriesRow[];
  terminal: {
    terminal_wealth: Figure;
    cumulative_cash_flow: Figure;
    tax_paid_now: Figure;
    deferred_liability: Figure;
    ending_equity: Figure;
  };
  caveats: string[];
  /** 1031 only */
  boot?: {
    cash_boot: Figure;
    mortgage_boot: Figure;
    total_boot: Figure;
    gain_recognized: Figure;
    tax_on_boot: Figure;
  };
  /** what the proceeds do */
  proceeds_use?: { label: string; value: Figure }[];
}

export interface StrategyComparison {
  property_id: string;
  horizon_years: number;
  assumptions: ScenarioAssumptions;
  paths: StrategyPathResult[];
  matrix: Record<MatrixMeasure, Record<StrategyPath, MatrixVerdict>>;
  caveats: Record<StrategyPath, string[]>;
}

export interface UploadResponse {
  document: Document;
  extracted_fields: ExtractedField[];
  findings: Finding[];
  properties_touched: string[];
  /** what the upload changed in the household (live APIs since the documents-driven seed) */
  import?: { properties_created: number; properties_updated: number; conflicts_raised: number };
}

export interface DocumentDetail {
  document: Document;
  fields: ExtractedField[];
}

export type FactSheetFormat = 'emoney' | 'rightcapital' | 'mgp' | 'json' | 'csv';

export interface FactSheetRow {
  groundplan_key: string;
  platform_field: string;
  value_cents: Cents | null;
  value_text: string | null;
  status: FigureStatus;
  note: string | null;
}

export interface FactSheet {
  property_id: string;
  format: FactSheetFormat;
  platform_label: string;
  rows: FactSheetRow[];
  as_of: ISODate;
}

export type SimulationEventType = 'buy' | 'sell' | 'exchange' | 'refi';

export interface SimulationEvent {
  id: string;
  year: number;
  type: SimulationEventType;
  property_ref: string; // nickname or id
  amount_cents?: Cents;
  debt_cents?: Cents;
  rate?: Rate;
  note?: string;
}

export interface SimulationAssumptions {
  appreciation_rate: Rate;
  rent_growth: Rate;
  expense_growth: Rate;
  reinvest_rate: Rate;
  cap_rate: Rate;
}

export interface SimulationProperty {
  nickname: string;
  property_type: PropertyType;
  current_value_cents: Cents;
  debt_cents: Cents;
  noi_cents: Cents;
  purchase_price_cents: Cents;
  purchase_date: ISODate;
  land_pct: Rate;
}

export interface SimulationRequest {
  start_year: number;
  years: number;
  properties: SimulationProperty[];
  events: SimulationEvent[];
  assumptions: SimulationAssumptions;
  monte_carlo: { runs: number; appr_sigma: number; rent_sigma: number };
}

export interface PercentileBand {
  p10: Cents;
  p50: Cents;
  p90: Cents;
}

export interface SimulationYear {
  year: number;
  net_worth: PercentileBand;
  cash_flow: PercentileBand;
  taxes_paid: PercentileBand;
  equity_cents: Cents;
  debt_cents: Cents;
  events: SimulationEvent[];
}

export interface SimulationResult {
  series: SimulationYear[];
  runs: number;
  terminal: { net_worth: PercentileBand; cumulative_taxes: PercentileBand };
}

export interface EvalFieldRow {
  form: string;
  field: string;
  variant: 'text' | 'scan';
  precision: number;
  recall: number;
  exact_match: number;
  n: number;
}

export interface EvalSummary {
  generated_at: ISODateTime;
  docs_dir: string;
  noise: { dpi: number; rotation_deg: number; jpeg_q: number } | null;
  overall: { variant: 'text' | 'scan'; precision: number; recall: number; exact_match: number; n: number }[];
  per_form: { form: string; variant: 'text' | 'scan'; precision: number; recall: number; exact_match: number; n: number }[];
  per_field: EvalFieldRow[];
  entity_resolution: { accuracy: number; n: number; mismatches: { gold: string; predicted: string }[] };
  finding_recall: { planted: number; raised: number; missed: string[] };
  confusion: { labels: string[]; matrix: number[][] };
}

/** RFC 7807 problem+json */
export interface Problem {
  type: string;
  title: string;
  status: number;
  detail?: string;
  instance?: string;
}
