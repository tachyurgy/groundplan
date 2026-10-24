package service

import (
	"context"
	_ "embed"
	"fmt"
	"os"
	"sync"
	"time"

	"github.com/tachyurgy/groundplan/engine-go/dec"
	"github.com/tachyurgy/groundplan/engine-go/engine/dates"
	"github.com/tachyurgy/groundplan/engine-go/internal/store"
	"github.com/tachyurgy/groundplan/engine-go/jsonx"
)

// Port of backend/scripts/seed.py: the Okafor-Lindqvist demo household loaded from fixtures/seed/okafor-lindqvist.json
// (generated from the same facts as the synthetic PDFs). One seed file, two backends: the JSON is embedded here
// verbatim (TestSeedFileIsTheFixture guards drift); GP_SEED_PATH overrides it like on the Python side.

// DemoName is the seeded household name.
const DemoName = "Okafor-Lindqvist household"

//go:embed seeddata/okafor-lindqvist.json
var SeedJSON []byte

var (
	seedOnce sync.Once
	seedData *jsonx.Obj
	seedErr  error
)

func loadSeed() (*jsonx.Obj, error) {
	seedOnce.Do(func() {
		raw := SeedJSON
		if p := os.Getenv("GP_SEED_PATH"); p != "" {
			if raw, seedErr = os.ReadFile(p); seedErr != nil {
				return
			}
		}
		v, err := jsonx.Decode(raw)
		if err != nil {
			seedErr = err
			return
		}
		seedData, _ = v.(*jsonx.Obj)
		if seedData == nil {
			seedErr = fmt.Errorf("seed file is not an object")
		}
	})
	return seedData, seedErr
}

func jDate(v any) *time.Time {
	s, ok := v.(string)
	if !ok || s == "" {
		return nil
	}
	d := dates.MustParse(s)
	return &d
}

func jDec(v any) *dec.D {
	if v == nil {
		return nil
	}
	return pyDec(v)
}

func jI(o *jsonx.Obj, k string, def int64) int64 {
	if v, ok := asInt(o.MustGet(k)); ok {
		return v
	}
	return def
}

func jS(o *jsonx.Obj, k, def string) string {
	if s, ok := o.MustGet(k).(string); ok {
		return s
	}
	return def
}

func jB(o *jsonx.Obj, k string, def bool) bool {
	if b, ok := o.MustGet(k).(bool); ok {
		return b
	}
	return def
}

func jIP(o *jsonx.Obj, k string) *int64 {
	if v, ok := asInt(o.MustGet(k)); ok {
		return &v
	}
	return nil
}

func jSP(o *jsonx.Obj, k string) *string {
	if s, ok := o.MustGet(k).(string); ok {
		return &s
	}
	return nil
}

// Seed is scripts.seed.seed(s, advisor_id): deletes any previous demo household of the workspace, inserts it again.
func (svc *Service) Seed(ctx context.Context, aid string) (string, error) {
	data, err := loadSeed()
	if err != nil {
		return "", err
	}
	q := svc.Q(ctx)
	if _, err := q.Exec(ctx, `DELETE FROM households WHERE advisor_id = $1 AND name = $2`, aid, DemoName); err != nil {
		return "", err
	}
	hd := data.MustGet("household").(*jsonx.Obj)
	h := &store.Household{ID: store.NewID(), AdvisorID: aid, Name: jS(hd, "name", DemoName), FilingStatus: jS(hd, "filing_status", "mfj"),
		State: jS(hd, "state", "CA"), TaxYearLatest: int(jI(hd, "tax_year_latest", 2025)), WagesCents: jI(hd, "wages_cents", 0),
		OtherIncomeCents: jI(hd, "other_income_cents", 0), MagiCents: jI(hd, "magi_cents", 0),
		ActiveParticipation: jB(hd, "active_participation", true), REProfessional: jB(hd, "re_professional", false),
		NetWorthCents: jIP(hd, "net_worth_cents"), Goal: jS(hd, "goal", ""), Notes: jS(hd, "notes", ""), CreatedAt: time.Now().UTC()}
	if err := store.InsertHousehold(ctx, q, h); err != nil {
		return "", err
	}
	byRef := map[string]string{}
	for _, pd := range objList(data.MustGet("properties")) {
		p := &store.Property{ID: store.NewID(), AdvisorID: aid, HouseholdID: h.ID, Nickname: jS(pd, "nickname", ""),
			AddressLine1: jS(pd, "address_line1", ""), City: jS(pd, "city", ""), State: jS(pd, "state", ""), Zip: jS(pd, "zip", ""),
			PropertyType: jS(pd, "property_type", "sfr"), Units: int(jI(pd, "units", 1)), PurchaseDate: jDate(pd.MustGet("purchase_date")),
			PurchasePriceCents: jI(pd, "purchase_price_cents", 0), PlacedInServiceDate: jDate(pd.MustGet("placed_in_service_date")),
			LandPct: jDec(pd.MustGet("land_pct")), ImprovementsCents: jI(pd, "improvements_cents", 0), CostSegStudy: jB(pd, "cost_seg_study", false),
			CurrentValueCents: jI(pd, "current_value_cents", 0), ValueSource: jS(pd, "value_source", "estimated"),
			ValueAsOf: jDate(pd.MustGet("value_as_of")), AppreciationRate: jDec(pd.MustGet("appreciation_rate")),
			RentGrowthRate: jDec(pd.MustGet("rent_growth_rate")), ExpenseGrowthRate: jDec(pd.MustGet("expense_growth_rate")),
			VacancyRate: jDec(pd.MustGet("vacancy_rate")), MgmtFeeRate: jDec(pd.MustGet("mgmt_fee_rate")),
			CapexReserveRate: jDec(pd.MustGet("capex_reserve_rate")), SellingCostRate: jDec(pd.MustGet("selling_cost_rate")),
			Status: jS(pd, "status", "active"), FormerResidenceUntil: jDate(pd.MustGet("former_residence_until")), PropertyKey: jSP(pd, "property_key")}
		if v := pd.MustGet("avg_stay_days"); v != nil {
			f := toF(v)
			p.AvgStayDays = &f
		}
		if err := store.InsertProperty(ctx, q, p); err != nil {
			return "", err
		}
		byRef[jS(pd, "ref", "")] = p.ID
		for _, lo := range objList(pd.MustGet("loans")) {
			l := &store.Loan{ID: store.NewID(), AdvisorID: aid, PropertyID: p.ID, Lender: jS(lo, "lender", ""), LoanType: jS(lo, "loan_type", "fixed"),
				OriginalCents: jI(lo, "original_cents", 0), BalanceCents: jI(lo, "balance_cents", 0), Rate: *jDec(lo.MustGet("rate")),
				TermMonths: int(jI(lo, "term_months", 360)), IOMonths: int(jI(lo, "io_months", 0)), ArmResetDate: jDate(lo.MustGet("arm_reset_date")),
				ArmIndexMargin: jDec(lo.MustGet("arm_index_margin")), MonthlyPaymentCents: jIP(lo, "monthly_payment_cents"),
				MaturityDate: jDate(lo.MustGet("maturity_date")), LienPosition: int(jI(lo, "lien_position", 1)), IsPaidOff: jB(lo, "is_paid_off", false)}
			l.BalanceAsOf = *jDate(lo.MustGet("balance_as_of"))
			if err := store.InsertLoan(ctx, q, l); err != nil {
				return "", err
			}
		}
		for _, r := range objList(pd.MustGet("rent_rolls")) {
			rr := &store.RentRoll{ID: store.NewID(), AdvisorID: aid, PropertyID: p.ID, TaxYear: int(jI(r, "tax_year", 0)),
				GrossRentCents: jI(r, "gross_rent_cents", 0), OtherIncomeCents: jI(r, "other_income_cents", 0)}
			if err := store.SaveRentRoll(ctx, q, rr, true); err != nil {
				return "", err
			}
		}
		for _, e := range objList(pd.MustGet("expense_years")) {
			ey := &store.ExpenseYear{ID: store.NewID(), AdvisorID: aid, PropertyID: p.ID, TaxYear: int(jI(e, "tax_year", 0)), Cents: map[string]int64{}}
			for _, k := range store.ExpenseKeys {
				ey.Cents[k] = jI(e, k, 0)
			}
			if err := store.SaveExpenseYear(ctx, q, ey, true); err != nil {
				return "", err
			}
		}
		for _, d := range objList(pd.MustGet("depreciation_ledger")) {
			ld := &store.Ledger{ID: store.NewID(), AdvisorID: aid, PropertyID: p.ID, TaxYear: int(jI(d, "tax_year", 0)),
				AllowedCents: jI(d, "allowed_cents", 0), AllowableCents: jIP(d, "allowable_cents"), Method: jS(d, "method", "sl_27_5"), Note: jS(d, "note", "")}
			if err := store.SaveLedger(ctx, q, ld, true); err != nil {
				return "", err
			}
		}
	}
	for _, sl := range objList(data.MustGet("suspended_losses")) {
		x := &store.SuspendedLoss{ID: store.NewID(), AdvisorID: aid, HouseholdID: h.ID, TaxYear: int(jI(sl, "tax_year", 0)),
			CarryforwardCents: jI(sl, "carryforward_cents", 0)}
		if err := store.SaveSuspendedLoss(ctx, q, x, true); err != nil {
			return "", err
		}
	}
	tick := time.Now().UTC()
	for _, fd := range objList(data.MustGet("findings")) {
		tick = tick.Add(time.Microsecond) // created_at keeps the file order (the findings list sorts on it)
		f := &store.Finding{ID: store.NewID(), AdvisorID: aid, HouseholdID: h.ID, Key: jSP(fd, "key"), Kind: jS(fd, "kind", ""),
			Field: jS(fd, "field", ""), Severity: jS(fd, "severity", "warn"), Message: jS(fd, "message", ""), Status: jS(fd, "status", "open"),
			Resolution: fd.MustGet("resolution"), CreatedAt: tick}
		if ref, ok := fd.MustGet("property").(string); ok && ref != "" {
			pid := byRef[ref]
			f.PropertyID = &pid
		}
		if v, ok := asInt(fd.MustGet("tax_year")); ok {
			t := int(v)
			f.TaxYear = &t
		}
		f.Candidates = fd.MustGet("candidates")
		if f.Candidates == nil {
			f.Candidates = []any{}
		}
		if err := store.SaveFinding(ctx, q, f, true); err != nil {
			return "", err
		}
	}
	return h.ID, nil
}
