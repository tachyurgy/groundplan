package service

import (
	"context"
	"fmt"
	"time"

	"github.com/tachyurgy/groundplan/engine-go/dec"
	"github.com/tachyurgy/groundplan/engine-go/engine/dates"
	"github.com/tachyurgy/groundplan/engine-go/engine/loans"
	"github.com/tachyurgy/groundplan/engine-go/internal/store"
	"github.com/tachyurgy/groundplan/engine-go/jsonx"
)

// Port of backend/scripts/seed.py: the Okafor-Lindqvist demo household (SPEC §4.1), same rows, same values.
// Python computes a few seed values with floats (_usd, round); the literal results are written here and
// TestSeedDerivedValues recomputes them with the same float formulas.

// DemoName is the seeded household name.
const DemoName = "Okafor-Lindqvist household"

func usd(x float64) int64 { return dec.PyRound(x * 100) }

func seedBalance(original float64, rate string, term int, start, asOf dates.Date) int64 {
	s := loans.Build(&loans.Input{LoanType: "fixed", BalanceCents: usd(original), BalanceAsOf: start, Rate: dec.S(rate), TermMonths: term, LienPosition: 1})
	return s.BalanceAt(asOf)
}

// SeedDerived are the float-derived values of the Elm SFR rows (Python: basis3 = 615_000 * 0.70 ...).
func SeedDerived() (allow24 float64, claimed24, dep25 int64) {
	basis3 := 615_000 * 0.70
	allow24 = dec.PyRoundN(basis3*0.01970, 2)
	claimed24 = dec.PyRound(allow24 * 0.88)
	dep25 = dec.PyRound(basis3 * 0.03636)
	return
}

type seeder struct {
	ctx  context.Context
	q    store.Q
	aid  string
	hid  string
	tick time.Time
}

func (s *seeder) exec(sql string, args ...any) error {
	_, err := s.q.Exec(s.ctx, sql, args...)
	return err
}

func d(y, m, dd int) *time.Time { t := dates.New(y, m, dd); return &t }

func ds(v string) *string { return &v }

type propSeed struct {
	nickname, addr, city, state, zip, ptype string
	units                                   int
	purchaseDate                            *time.Time
	price                                   int64
	pis                                     *time.Time
	landPct                                 *string
	improvements                            int64
	value                                   int64
	valueSource                             string
	valueAsOf                               *time.Time
	appr, rg, eg, vac, capex, sell          *string
	avgStay                                 *float64
	key                                     string
}

func (s *seeder) prop(p propSeed) (string, error) {
	id := store.NewID()
	err := s.exec(`INSERT INTO properties (id, advisor_id, household_id, nickname, address_line1, city, state, zip, property_type, units,
		purchase_date, purchase_price_cents, placed_in_service_date, land_pct, improvements_cents, cost_seg_study, current_value_cents,
		value_source, value_as_of, appreciation_rate, rent_growth_rate, expense_growth_rate, vacancy_rate, mgmt_fee_rate,
		capex_reserve_rate, selling_cost_rate, status, former_residence_until, avg_stay_days, property_key)
		VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14::numeric,$15,false,$16,$17,$18,$19::numeric,$20::numeric,$21::numeric,
		$22::numeric,NULL,$23::numeric,$24::numeric,'active',NULL,$25,$26)`,
		id, s.aid, s.hid, p.nickname, p.addr, p.city, p.state, p.zip, p.ptype, p.units, p.purchaseDate, p.price, p.pis, p.landPct,
		p.improvements, p.value, p.valueSource, p.valueAsOf, p.appr, p.rg, p.eg, p.vac, p.capex, p.sell, p.avgStay, p.key)
	return id, err
}

func (s *seeder) loan(pid, lender, ltype string, original, balance int64, asOf time.Time, rate string, term, io int, armReset *time.Time,
	margin *string, payment *int64, maturity *time.Time, lien int, paidOff bool) error {
	return s.exec(`INSERT INTO loans (id, advisor_id, property_id, lender, loan_type, original_cents, balance_cents, balance_as_of, rate,
		term_months, io_months, arm_reset_date, arm_index_margin, monthly_payment_cents, maturity_date, lien_position, is_paid_off)
		VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::numeric,$10,$11,$12,$13::numeric,$14,$15,$16,$17)`,
		store.NewID(), s.aid, pid, lender, ltype, original, balance, asOf, rate, term, io, armReset, margin, payment, maturity, lien, paidOff)
}

type yr struct {
	y                                                                        int
	rent                                                                     float64
	taxes, insurance, repairs, mgmt, utilities, hoa, other, interest, deprec float64
}

func (s *seeder) years(pid string, ys []yr) error {
	for _, y := range ys {
		if err := s.exec(`INSERT INTO rent_rolls (id, advisor_id, property_id, tax_year, gross_rent_cents, other_income_cents) VALUES ($1,$2,$3,$4,$5,0)`,
			store.NewID(), s.aid, pid, y.y, usd(y.rent)); err != nil {
			return err
		}
	}
	for _, y := range ys {
		if err := s.exec(`INSERT INTO expense_years (id, advisor_id, property_id, tax_year, taxes_cents, insurance_cents, repairs_cents,
			mgmt_cents, utilities_cents, hoa_cents, other_cents, mortgage_interest_cents, depreciation_cents) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)`,
			store.NewID(), s.aid, pid, y.y, usd(y.taxes), usd(y.insurance), usd(y.repairs), usd(y.mgmt), usd(y.utilities), usd(y.hoa),
			usd(y.other), usd(y.interest), usd(y.deprec)); err != nil {
			return err
		}
	}
	return nil
}

func (s *seeder) ledger(pid string, y int, allowed float64, allowable *float64, note string) error {
	var al *int64
	if allowable != nil {
		v := usd(*allowable)
		al = &v
	}
	return s.exec(`INSERT INTO depreciation_ledgers (id, advisor_id, property_id, tax_year, allowed_cents, allowable_cents, method, note)
		VALUES ($1,$2,$3,$4,$5,$6,'sl_27_5',$7)`, store.NewID(), s.aid, pid, y, usd(allowed), al, note)
}

func (s *seeder) finding(pid *string, key string, taxYear *int, kind, field, severity, message string, cands []any, status string, resolution any) error {
	s.tick = s.tick.Add(time.Microsecond)
	var res any
	if resolution != nil {
		res = string(jsonx.MustMarshal(resolution))
	}
	return s.exec(`INSERT INTO findings (id, advisor_id, household_id, property_id, key, tax_year, kind, field, severity, message,
		candidates, status, resolution, created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::jsonb,$12,$13::jsonb,$14)`,
		store.NewID(), s.aid, s.hid, pid, key, taxYear, kind, field, severity, message, string(jsonx.MustMarshal(cands)), status, res, s.tick)
}

func cand(source string, value any, page any) *jsonx.Obj {
	return jsonx.O("source", source, "value", value, "document_id", nil, "page", page)
}

func f64(v float64) *float64 { return &v }

// Seed is scripts.seed.seed(s, advisor_id): deletes any previous demo household of the workspace, inserts it again.
func (svc *Service) Seed(ctx context.Context, aid string) (string, error) {
	q := svc.Q(ctx)
	if _, err := q.Exec(ctx, `DELETE FROM households WHERE advisor_id = $1 AND name = $2`, aid, DemoName); err != nil {
		return "", err
	}
	s := &seeder{ctx: ctx, q: q, aid: aid, hid: store.NewID(), tick: time.Now().UTC()}
	if err := s.exec(`INSERT INTO households (id, advisor_id, name, filing_status, state, tax_year_latest, wages_cents, other_income_cents,
		magi_cents, active_participation, re_professional, net_worth_cents, goal, notes, created_at)
		VALUES ($1,$2,$3,'mfj','CA',2025,$4,$5,$6,true,false,$7,$8,$9,$10)`, s.hid, aid, DemoName, usd(171_800), usd(14_600), usd(186_400),
		usd(3_350_000), "retire in 7 years, stop managing property",
		"Both W-2 (hospital pharmacist + school administrator). Self-manage the duplex; Tahoe cabin run by a "+
			"local STR manager. Ages 56 and 54.", time.Now().UTC()); err != nil {
		return "", err
	}
	eoy := dates.New(2025, 12, 31)

	// P1 Maple duplex
	p1, err := s.prop(propSeed{nickname: "Maple duplex", addr: "1420 Maple St", city: "Sacramento", state: "CA", zip: "95816",
		ptype: "multifamily", units: 2, purchaseDate: d(2012, 5, 15), price: usd(310_000), pis: d(2012, 6, 1), landPct: ds("0.30"),
		improvements: usd(28_000), value: usd(785_000), valueSource: "confirmed", valueAsOf: d(2025, 9, 18), appr: ds("0.035"),
		rg: ds("0.03"), eg: ds("0.03"), vac: ds("0.04"), capex: ds("0.05"), sell: ds("0.06"), key: "1420 maple st sacramento ca 95816"})
	if err != nil {
		return "", err
	}
	pay1 := usd(1_166.18)
	if err := s.loan(p1, "Golden 1 Credit Union", "fixed", usd(248_000), seedBalance(248_000, "0.03875", 360, dates.New(2012, 6, 30), eoy), eoy,
		"0.03875", 198, 0, nil, nil, &pay1, d(2042, 6, 1), 1, false); err != nil {
		return "", err
	}
	if err := s.years(p1, []yr{
		{2023, 48_000, 3_780, 1_850, 4_100, 0, 1_720, 0, 540, 7_310, 8_604},
		{2024, 49_800, 3_855, 1_990, 2_950, 0, 1_760, 0, 560, 7_090, 8_604},
		{2025, 51_600, 3_930, 2_240, 3_400, 0, 1_810, 0, 610, 6_860, 8_604}}); err != nil {
		return "", err
	}
	for _, y := range []int{2023, 2024, 2025} {
		if err := s.ledger(p1, y, 8_604, nil, "Form 4562 line 22 (27.5 SL/MM)"); err != nil {
			return "", err
		}
	}

	// P2 Tahoe cabin (STR)
	p2, err := s.prop(propSeed{nickname: "Tahoe cabin", addr: "885 Pine Cone Rd", city: "South Lake Tahoe", state: "CA", zip: "96150",
		ptype: "vacation_str", units: 1, purchaseDate: d(2019, 7, 10), price: usd(640_000), pis: d(2019, 8, 1), landPct: ds("0.40"),
		improvements: usd(35_000), value: usd(805_000), valueSource: "estimated", valueAsOf: d(2025, 11, 1), appr: ds("0.03"),
		vac: ds("0"), capex: ds("0.04"), avgStay: f64(4.0), key: "885 pine cone rd south lake tahoe ca 96150"})
	if err != nil {
		return "", err
	}
	pay2 := usd(2_518.73)
	if err := s.loan(p2, "Chase", "fixed", usd(512_000), seedBalance(512_000, "0.0425", 360, dates.New(2019, 7, 31), eoy), eoy, "0.0425",
		283, 0, nil, nil, &pay2, d(2049, 8, 1), 1, false); err != nil {
		return "", err
	}
	if err := s.years(p2, []yr{
		{2023, 61_400, 7_180, 4_350, 4_900, 14_740, 5_870, 0, 4_620, 20_150, 14_727},
		{2024, 57_900, 7_320, 4_980, 6_300, 13_900, 6_040, 0, 4_390, 19_790, 14_727},
		{2025, 58_300, 7_470, 5_610, 5_200, 13_990, 6_150, 0, 4_480, 19_400, 14_727}}); err != nil {
		return "", err
	}
	for _, y := range []int{2023, 2024, 2025} {
		if err := s.ledger(p2, y, 14_727, nil, ""); err != nil {
			return "", err
		}
	}

	// P3 Elm SFR: IO 7/1 ARM resetting 2027, bought Jun 2024, 2024 depreciation 12% under allowable
	p3, err := s.prop(propSeed{nickname: "Elm SFR", addr: "214 Elm Ct", city: "Roseville", state: "CA", zip: "95678", ptype: "sfr",
		units: 1, purchaseDate: d(2024, 6, 14), price: usd(615_000), pis: d(2024, 6, 20), landPct: ds("0.30"), value: usd(632_000),
		valueSource: "estimated", valueAsOf: d(2025, 10, 1), appr: ds("0.03"), vac: ds("0.05"), capex: ds("0.05"),
		key: "214 elm ct roseville ca 95678"})
	if err != nil {
		return "", err
	}
	pay3 := usd(2_511.25)
	if err := s.loan(p3, "Rocket Mortgage", "arm", usd(492_000), usd(492_000), eoy, "0.06125", 342, 18, d(2027, 7, 1), ds("0.0275"), &pay3,
		d(2054, 7, 1), 1, false); err != nil {
		return "", err
	}
	allow24, claimed24, dep25 := SeedDerived()
	if err := s.years(p3, []yr{
		{2024, 18_300, 3_440, 950, 380, 1_460, 0, 0, 210, 15_068, float64(claimed24)},
		{2025, 36_600, 6_920, 1_940, 1_150, 2_930, 0, 0, 420, 30_135, float64(dep25)}}); err != nil {
		return "", err
	}
	if err := s.ledger(p3, 2024, float64(claimed24), &allow24, "Return claimed 12% below allowable (preparer error)"); err != nil {
		return "", err
	}
	dep25f := float64(dep25)
	if err := s.ledger(p3, 2025, dep25f, &dep25f, ""); err != nil {
		return "", err
	}

	// P4 Oak condo: on 2023 + 2024 returns, ABSENT from 2025; HELOC 2nd, paid-off 1st
	p4, err := s.prop(propSeed{nickname: "Oak condo", addr: "77 Oak Ln Unit 12", city: "Folsom", state: "CA", zip: "95630", ptype: "sfr",
		units: 1, purchaseDate: d(2015, 3, 2), price: usd(285_000), pis: d(2015, 4, 1), landPct: ds("0.25"), value: usd(415_000),
		valueSource: "estimated", valueAsOf: d(2024, 6, 1), appr: ds("0.03"), vac: ds("0.05"), capex: ds("0.03"),
		key: "77 oak ln unit 12 folsom ca 95630"})
	if err != nil {
		return "", err
	}
	if err := s.loan(p4, "Wells Fargo", "fixed", usd(228_000), 0, dates.New(2023, 8, 31), "0.04", 360, 0, nil, nil, nil, d(2045, 4, 1), 1, true); err != nil {
		return "", err
	}
	if err := s.loan(p4, "SAFE Credit Union HELOC", "heloc", usd(60_000), usd(44_800), eoy, "0.0875", 96, 0, nil, nil, nil, d(2033, 12, 1), 2, false); err != nil {
		return "", err
	}
	if err := s.years(p4, []yr{
		{2023, 25_800, 3_210, 640, 1_350, 0, 0, 4_680, 300, 5_120, 7_773},
		{2024, 26_400, 3_275, 690, 900, 0, 0, 4_800, 320, 4_210, 7_773}}); err != nil {
		return "", err
	}
	for _, y := range []int{2023, 2024} {
		if err := s.ledger(p4, y, 7_773, nil, ""); err != nil {
			return "", err
		}
	}

	// Household: Form 8582 carryforwards
	for _, x := range [][2]int64{{2023, 4_900}, {2024, 9_650}, {2025, 14_200}} {
		if err := s.exec(`INSERT INTO suspended_losses (id, advisor_id, household_id, tax_year, carryforward_cents) VALUES ($1,$2,$3,$4,$5)`,
			store.NewID(), aid, s.hid, x[0], usd(float64(x[1]))); err != nil {
			return "", err
		}
	}

	// Findings (what the pipeline raises on this household)
	y24, y25 := 2024, 2025
	if err := s.finding(&p2, "str:p2", nil, "unsupported_structure", "property.property_type", "warn",
		"Tahoe cabin: average stay 4 nights (<= 7): short-term rental rules apply; not modeled. Losses may be "+
			"nonpassive with material participation, or not deductible at all; verify with CPA.",
		[]any{cand("schedule_e 2025 line 2 (fair rental 212 days / personal use 18 days)", int64(4), int64(1))}, "open", nil); err != nil {
		return "", err
	}
	if err := s.finding(&p3, "dep_outlier:p3:2024", &y24, "outlier", "form_4562.depreciation", "warn",
		fmt.Sprintf("Elm SFR: 2024 depreciation claimed $%s is 12%% below the $%s allowable "+
			"(27.5 SL, June placed-in-service). Recapture uses allowable; consider Form 3115.",
			dec.Commas(fmt.Sprint(claimed24)), dec.Commas(dec.PyFixed(allow24, 0))),
		[]any{cand("schedule_e 2024 line 18", usd(float64(claimed24)), int64(1)),
			cand("engine allowable (Pub 946 Table A-6)", usd(allow24), nil)}, "open", nil); err != nil {
		return "", err
	}
	if err := s.finding(&p4, "missing_latest:p4", nil, "missing", "schedule_e.property", "warn",
		"Oak condo appears on the 2023 and 2024 Schedule E but not on 2025: sold? converted to personal use? "+
			"Confirm status before relying on the 2025 numbers.",
		[]any{cand("schedule_e 2023 column C", "77 Oak Ln Unit 12", int64(1)), cand("schedule_e 2024 column C", "77 OAK LANE #12", int64(1)),
			cand("schedule_e 2025", nil, nil)}, "open", nil); err != nil {
		return "", err
	}
	if err := s.finding(&p1, "conflict:p1:rents:2025", &y25, "conflict", "schedule_e.line3.rents", "block",
		"Maple duplex 2025 rents disagree: Schedule E line 3 shows $51,600, the rent roll totals $50,400 "+
			"(unit B vacant in March?). Cash flow for this property is blocked until resolved.",
		[]any{cand("schedule_e 2025 line 3 column A", usd(51_600), int64(1)), cand("rent roll 2025 (advisor upload)", usd(50_400), int64(1))},
		"open", nil); err != nil {
		return "", err
	}
	if err := s.finding(&p1, "address_variants:p1", nil, "conflict", "property.address_line1", "info",
		"Maple duplex address printed three ways across years (1420 Maple St / 1420 MAPLE STREET UNIT A/B / "+
			"1420 Maple St.); matched to one property (confidence 0.93).",
		[]any{cand("schedule_e 2023", "1420 Maple St", int64(1)), cand("schedule_e 2024", "1420 MAPLE STREET UNIT A/B", int64(1)),
			cand("schedule_e 2025", "1420 Maple St.", int64(1))}, "resolved",
		jsonx.O("value", "1420 Maple St", "who", "entity resolution (auto)", "when", "2026-01-15T00:00:00Z",
			"note", "token-set ratio >= 0.85 + property type match")); err != nil {
		return "", err
	}
	return s.hid, nil
}
