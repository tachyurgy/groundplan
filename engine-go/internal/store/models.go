package store

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/tachyurgy/groundplan/engine-go/dec"
	"github.com/tachyurgy/groundplan/engine-go/jsonx"
)

// Rows mirror backend/groundplan/db/models.py. Numeric(9,6) rates are carried as decimals parsed from the
// database text (so "0.300000" keeps its scale exactly like SQLAlchemy's Decimal), JSONB as ordered jsonx values.

type Advisor struct {
	ID, FirmName, Name, Email string
	CreatedAt, LastSeenAt     time.Time
	CreatedIP                 *string
}

type Household struct {
	ID, AdvisorID, Name, FilingStatus, State string
	TaxYearLatest                            int
	WagesCents, OtherIncomeCents, MagiCents  int64
	ActiveParticipation, REProfessional      bool
	NetWorthCents                            *int64
	Goal, Notes                              string
	CreatedAt                                time.Time

	Properties      []*Property      `json:"-"`
	SuspendedLosses []*SuspendedLoss `json:"-"`
	Documents       []*Document      `json:"-"`
	Findings        []*Finding       `json:"-"`
}

type Property struct {
	ID, AdvisorID, HouseholdID, Nickname, AddressLine1, City, State, Zip, PropertyType string
	Units                                                                              int
	PurchaseDate                                                                       *time.Time
	PurchasePriceCents                                                                 int64
	PlacedInServiceDate                                                                *time.Time
	LandPct                                                                            *dec.D
	ImprovementsCents                                                                  int64
	CostSegStudy                                                                       bool
	CurrentValueCents                                                                  int64
	ValueSource                                                                        string
	ValueAsOf                                                                          *time.Time
	AppreciationRate, RentGrowthRate, ExpenseGrowthRate, VacancyRate, MgmtFeeRate      *dec.D
	CapexReserveRate, SellingCostRate                                                  *dec.D
	Status                                                                             string
	FormerResidenceUntil                                                               *time.Time
	AvgStayDays                                                                        *float64
	PropertyKey                                                                        *string

	Household    *Household     `json:"-"`
	Loans        []*Loan        `json:"-"`
	RentRolls    []*RentRoll    `json:"-"`
	ExpenseYears []*ExpenseYear `json:"-"`
	Ledger       []*Ledger      `json:"-"`
	Scenarios    []*Scenario    `json:"-"`
}

// Rate returns a property rate field by its Python name.
func (p *Property) Rate(name string) *dec.D {
	switch name {
	case "land_pct":
		return p.LandPct
	case "appreciation_rate":
		return p.AppreciationRate
	case "rent_growth_rate":
		return p.RentGrowthRate
	case "expense_growth_rate":
		return p.ExpenseGrowthRate
	case "vacancy_rate":
		return p.VacancyRate
	case "mgmt_fee_rate":
		return p.MgmtFeeRate
	case "capex_reserve_rate":
		return p.CapexReserveRate
	case "selling_cost_rate":
		return p.SellingCostRate
	}
	panic("unknown rate " + name)
}

type Loan struct {
	ID, AdvisorID, PropertyID, Lender, LoanType string
	OriginalCents, BalanceCents                 int64
	BalanceAsOf                                 time.Time
	Rate                                        dec.D
	TermMonths, IOMonths                        int
	ArmResetDate                                *time.Time
	ArmIndexMargin                              *dec.D
	MonthlyPaymentCents                         *int64
	MaturityDate                                *time.Time
	LienPosition                                int
	IsPaidOff                                   bool
}

type RentRoll struct {
	ID, AdvisorID, PropertyID        string
	TaxYear                          int
	GrossRentCents, OtherIncomeCents int64
}

type ExpenseYear struct {
	ID, AdvisorID, PropertyID string
	TaxYear                   int
	Cents                     map[string]int64 // taxes_cents ... depreciation_cents
}

// ExpenseKeys are the expense_years money columns in model order.
var ExpenseKeys = []string{"taxes_cents", "insurance_cents", "repairs_cents", "mgmt_cents", "utilities_cents", "hoa_cents",
	"other_cents", "mortgage_interest_cents", "depreciation_cents"}

type Ledger struct {
	ID, AdvisorID, PropertyID string
	TaxYear                   int
	AllowedCents              int64
	AllowableCents            *int64
	Method, Note              string
}

type SuspendedLoss struct {
	ID, AdvisorID, HouseholdID string
	TaxYear                    int
	CarryforwardCents          int64
}

type Document struct {
	ID, AdvisorID, HouseholdID, Kind string
	TaxYear                          *int
	Filename, Sha256                 string
	PageCount                        int
	UploadedAt                       time.Time
	Status                           string
	BytesRetained                    bool
	Fields                           []*Field `json:"-"`
}

type Field struct {
	ID, AdvisorID, DocumentID, EntityHint string
	PropertyKey                           *string
	Field                                 string
	Value                                 any // decoded JSONB
	Unit                                  string
	Page                                  int
	BBox                                  any
	Confidence                            float64
	Extractor, RawText                    string
}

type Finding struct {
	ID, AdvisorID, HouseholdID string
	PropertyID, Key            *string
	TaxYear                    *int
	Kind, Field, Severity      string
	Message                    string
	Candidates                 any
	Status                     string
	Resolution                 any
	CreatedAt                  time.Time
}

type Scenario struct {
	ID, AdvisorID, PropertyID, Name string
	HorizonYears                    int
	Assumptions, Results            any
	CreatedAt                       time.Time
}

// --- scanning helpers --------------------------------------------------------------------------------------

func decPtr(s *string) *dec.D {
	if s == nil {
		return nil
	}
	d := dec.S(*s)
	return &d
}

func jsonVal(b []byte) any {
	if b == nil {
		return nil
	}
	return jsonx.MustDecode(b)
}

const householdCols = `id, advisor_id, name, filing_status, state, tax_year_latest, wages_cents, other_income_cents, magi_cents,
	active_participation, re_professional, net_worth_cents, goal, notes, created_at`

func scanHousehold(r pgx.Row) (*Household, error) {
	h := &Household{}
	err := r.Scan(&h.ID, &h.AdvisorID, &h.Name, &h.FilingStatus, &h.State, &h.TaxYearLatest, &h.WagesCents, &h.OtherIncomeCents,
		&h.MagiCents, &h.ActiveParticipation, &h.REProfessional, &h.NetWorthCents, &h.Goal, &h.Notes, &h.CreatedAt)
	return h, err
}

const propertyCols = `id, advisor_id, household_id, nickname, address_line1, city, state, zip, property_type, units, purchase_date,
	purchase_price_cents, placed_in_service_date, land_pct::text, improvements_cents, cost_seg_study, current_value_cents,
	value_source, value_as_of, appreciation_rate::text, rent_growth_rate::text, expense_growth_rate::text, vacancy_rate::text,
	mgmt_fee_rate::text, capex_reserve_rate::text, selling_cost_rate::text, status, former_residence_until, avg_stay_days, property_key`

func scanProperty(r pgx.Row) (*Property, error) {
	p := &Property{}
	var land, appr, rg, eg, vac, mgmt, capex, sell *string
	err := r.Scan(&p.ID, &p.AdvisorID, &p.HouseholdID, &p.Nickname, &p.AddressLine1, &p.City, &p.State, &p.Zip, &p.PropertyType,
		&p.Units, &p.PurchaseDate, &p.PurchasePriceCents, &p.PlacedInServiceDate, &land, &p.ImprovementsCents, &p.CostSegStudy,
		&p.CurrentValueCents, &p.ValueSource, &p.ValueAsOf, &appr, &rg, &eg, &vac, &mgmt, &capex, &sell, &p.Status,
		&p.FormerResidenceUntil, &p.AvgStayDays, &p.PropertyKey)
	p.LandPct, p.AppreciationRate, p.RentGrowthRate, p.ExpenseGrowthRate = decPtr(land), decPtr(appr), decPtr(rg), decPtr(eg)
	p.VacancyRate, p.MgmtFeeRate, p.CapexReserveRate, p.SellingCostRate = decPtr(vac), decPtr(mgmt), decPtr(capex), decPtr(sell)
	return p, err
}

const loanCols = `id, advisor_id, property_id, lender, loan_type, original_cents, balance_cents, balance_as_of, rate::text, term_months,
	io_months, arm_reset_date, arm_index_margin::text, monthly_payment_cents, maturity_date, lien_position, is_paid_off`

func scanLoan(r pgx.Row) (*Loan, error) {
	l := &Loan{}
	var rate string
	var margin *string
	err := r.Scan(&l.ID, &l.AdvisorID, &l.PropertyID, &l.Lender, &l.LoanType, &l.OriginalCents, &l.BalanceCents, &l.BalanceAsOf, &rate,
		&l.TermMonths, &l.IOMonths, &l.ArmResetDate, &margin, &l.MonthlyPaymentCents, &l.MaturityDate, &l.LienPosition, &l.IsPaidOff)
	if err == nil {
		l.Rate = dec.S(rate)
		l.ArmIndexMargin = decPtr(margin)
	}
	return l, err
}

const findingCols = `id, advisor_id, household_id, property_id, key, tax_year, kind, field, severity, message, candidates, status,
	resolution, created_at`

func scanFinding(r pgx.Row) (*Finding, error) {
	f := &Finding{}
	var cand, res []byte
	err := r.Scan(&f.ID, &f.AdvisorID, &f.HouseholdID, &f.PropertyID, &f.Key, &f.TaxYear, &f.Kind, &f.Field, &f.Severity, &f.Message,
		&cand, &f.Status, &res, &f.CreatedAt)
	if err == nil {
		f.Candidates = jsonVal(cand)
		f.Resolution = jsonVal(res)
	}
	return f, err
}

const documentCols = `id, advisor_id, household_id, kind, tax_year, filename, sha256, page_count, uploaded_at, status, bytes_retained`

func scanDocument(r pgx.Row) (*Document, error) {
	d := &Document{}
	err := r.Scan(&d.ID, &d.AdvisorID, &d.HouseholdID, &d.Kind, &d.TaxYear, &d.Filename, &d.Sha256, &d.PageCount, &d.UploadedAt,
		&d.Status, &d.BytesRetained)
	return d, err
}

const fieldCols = `id, advisor_id, document_id, entity_hint, property_key, field, value, unit, page, bbox, confidence, extractor, raw_text`

func scanField(r pgx.Row) (*Field, error) {
	f := &Field{}
	var val, bbox []byte
	err := r.Scan(&f.ID, &f.AdvisorID, &f.DocumentID, &f.EntityHint, &f.PropertyKey, &f.Field, &val, &f.Unit, &f.Page, &bbox,
		&f.Confidence, &f.Extractor, &f.RawText)
	if err == nil {
		f.Value = jsonVal(val)
		f.BBox = jsonVal(bbox)
	}
	return f, err
}

const scenarioCols = `id, advisor_id, property_id, name, horizon_years, assumptions, results, created_at`

func scanScenario(r pgx.Row) (*Scenario, error) {
	s := &Scenario{}
	var a, res []byte
	err := r.Scan(&s.ID, &s.AdvisorID, &s.PropertyID, &s.Name, &s.HorizonYears, &a, &res, &s.CreatedAt)
	if err == nil {
		s.Assumptions = jsonVal(a)
		s.Results = jsonVal(res)
	}
	return s, err
}

func collect[T any](rows pgx.Rows, scan func(pgx.Row) (T, error)) ([]T, error) {
	defer rows.Close()
	var out []T
	for rows.Next() {
		v, err := scan(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, v)
	}
	return out, rows.Err()
}

func queryAll[T any](ctx context.Context, q Q, scan func(pgx.Row) (T, error), sql string, args ...any) ([]T, error) {
	rows, err := q.Query(ctx, sql, args...)
	if err != nil {
		return nil, fmt.Errorf("%s: %w", firstLine(sql), err)
	}
	return collect(rows, scan)
}

func firstLine(s string) string {
	for i, c := range s {
		if c == '\n' {
			return s[:i]
		}
	}
	return s
}
