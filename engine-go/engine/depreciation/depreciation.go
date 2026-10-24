// Package depreciation ports engine/depreciation.py: MACRS straight-line, mid-month convention (IRS Pub 946
// Tables A-6 / A-7a). Residential rental 27.5 years, nonresidential 39 years. Table mode (default) uses the
// published first-year percentages by month placed in service; the final year is the exact remainder of basis.
// Simple mode = basis / life with the first year prorated by whole months remaining.
// Depreciable basis = (purchase_price + improvements) x (1 - land_pct), land_pct bounded to [0.20, 0.40],
// default 0.30.
package depreciation

import (
	"fmt"
	"sort"

	"github.com/cockroachdb/apd/v3"
	"github.com/tachyurgy/groundplan/engine-go/dec"
	"github.com/tachyurgy/groundplan/engine-go/engine/dates"
	"github.com/tachyurgy/groundplan/engine-go/engine/figure"
	"github.com/tachyurgy/groundplan/engine-go/jsonx"
)

var (
	LandPctMin     = dec.S("0.20")
	LandPctMax     = dec.S("0.40")
	LandPctDefault = dec.S("0.30")
)

var residentialFirstYear = map[int]string{1: "3.485", 2: "3.182", 3: "2.879", 4: "2.576", 5: "2.273", 6: "1.970",
	7: "1.667", 8: "1.364", 9: "1.061", 10: "0.758", 11: "0.455", 12: "0.152"}

const residentialMidYear = "3.636"

var residentialLife = dec.S("27.5")

var nonresidentialFirstYear = map[int]string{1: "2.461", 2: "2.247", 3: "2.033", 4: "1.819", 5: "1.605", 6: "1.391",
	7: "1.177", 8: "0.963", 9: "0.749", 10: "0.535", 11: "0.321", 12: "0.107"}

const nonresidentialMidYear = "2.564"

var nonresidentialLife = dec.S("39")

// ScheduleRow is one calendar year of the schedule.
type ScheduleRow struct {
	Year        int
	AmountCents int64
	Pct         string
}

// ToDict is ScheduleRow.to_dict.
func (r ScheduleRow) ToDict() *jsonx.Obj {
	return jsonx.O("year", r.Year, "amount_cents", r.AmountCents, "pct", r.Pct)
}

// PropertyClass maps a property type onto residential | nonresidential | land.
func PropertyClass(propertyType string) string {
	switch propertyType {
	case "commercial":
		return "nonresidential"
	case "land":
		return "land"
	}
	return "residential"
}

// BoundedLandPct returns (bounded value, notes, source_type).
func BoundedLandPct(landPct *dec.D) (dec.D, []string, string) {
	if landPct == nil {
		return LandPctDefault, []string{fmt.Sprintf("land_pct not provided; default %s applied", LandPctDefault)}, "default"
	}
	lp := *landPct
	if lp.Lt(LandPctMin) {
		return LandPctMin, []string{fmt.Sprintf("land_pct %s below floor; bounded to %s", lp, LandPctMin)}, "manual"
	}
	if lp.Gt(LandPctMax) {
		return LandPctMax, []string{fmt.Sprintf("land_pct %s above ceiling; bounded to %s", lp, LandPctMax)}, "manual"
	}
	return lp, nil, "manual"
}

// DepreciableBasis is depreciable_basis(...).
func DepreciableBasis(purchasePriceCents, improvementsCents int64, landPct *dec.D, sources map[string]*figure.Input) *figure.Figure {
	lp, notes, lpSrc := BoundedLandPct(landPct)
	pp := sources["purchase_price_cents"]
	if pp == nil {
		pp = figure.M("purchase_price_cents", purchasePriceCents)
	}
	im := sources["improvements_cents"]
	if im == nil {
		im = figure.M("improvements_cents", improvementsCents)
	}
	inputs := figure.L(pp, im, figure.Of("land_pct", lp, lpSrc))
	basis := dec.I(purchasePriceCents).Add(dec.I(improvementsCents)).Mul(dec.One.Sub(lp))
	return figure.Money("depreciation.depreciable_basis", basis, inputs, "(purchase_price + improvements) * (1 - land_pct)", notes, nil)
}

// AnnualSchedule is annual_schedule(basis, placed_in_service, class, mode).
func AnnualSchedule(basisCents int64, placedInService dates.Date, propClass, mode string) []ScheduleRow {
	if propClass == "land" || basisCents <= 0 {
		return nil
	}
	first, mid, life := residentialFirstYear, residentialMidYear, residentialLife
	if propClass == "nonresidential" {
		first, mid, life = nonresidentialFirstYear, nonresidentialMidYear, nonresidentialLife
	}
	basis := dec.I(basisCents)
	month := int(placedInService.Month())
	var rows []ScheduleRow
	remaining := basis
	year := placedInService.Year()
	if mode == "simple" {
		annual := basis.Quo(life)
		firstFraction := dec.I(int64(13 - month)).Quo(dec.I(12))
		amt := annual.Mul(firstFraction).Cents()
		rows = append(rows, ScheduleRow{year, amt, pctOf(amt, basis)})
		remaining = remaining.Sub(dec.I(amt))
		year++
		for remaining.Sign() > 0 {
			a := annual.Cents()
			if r := remaining.Int(); r < a {
				a = r
			}
			rows = append(rows, ScheduleRow{year, a, pctOf(a, basis)})
			remaining = remaining.Sub(dec.I(a))
			year++
		}
		return rows
	}
	if mode != "table" {
		panic(fmt.Sprintf("unknown depreciation mode %q", mode))
	}
	firstAmt := basis.Mul(dec.FromPct(first[month])).Cents()
	rows = append(rows, ScheduleRow{year, firstAmt, first[month]})
	remaining = remaining.Sub(dec.I(firstAmt))
	midAmt := basis.Mul(dec.FromPct(mid)).Cents()
	year++
	for remaining.Gt(dec.I(midAmt).Add(dec.One)) {
		rows = append(rows, ScheduleRow{year, midAmt, mid})
		remaining = remaining.Sub(dec.I(midAmt))
		year++
	}
	if remaining.Sign() > 0 {
		r := remaining.Int()
		rows = append(rows, ScheduleRow{year, r, pctOf(r, basis)})
	}
	return rows
}

func pctOf(amount int64, basis dec.D) string {
	if basis.IsZero() {
		return "0.000"
	}
	return dec.I(amount).Quo(basis).Mul(dec.I(100)).Quantize(3, apd.RoundHalfEven).String()
}

// AccumulatedThrough sums the schedule through the END of throughYear.
func AccumulatedThrough(schedule []ScheduleRow, throughYear int) int64 {
	var s int64
	for _, r := range schedule {
		if r.Year <= throughYear {
			s += r.AmountCents
		}
	}
	return s
}

// AmountInYear is the schedule amount in one year.
func AmountInYear(schedule []ScheduleRow, year int) int64 {
	var s int64
	for _, r := range schedule {
		if r.Year == year {
			s += r.AmountCents
		}
	}
	return s
}

// AllowedOrAllowable returns (recapture basis, notes, outlier flag).
func AllowedOrAllowable(allowableCents int64, allowedCents *int64) (int64, []string, bool) {
	if allowedCents == nil {
		return allowableCents, nil, false
	}
	allowed := *allowedCents
	if allowed < allowableCents {
		gap := dec.Zero
		if allowableCents != 0 {
			gap = dec.I(allowableCents - allowed).Quo(dec.I(allowableCents))
		}
		outlier := gap.Gt(dec.S("0.05"))
		return allowableCents, []string{fmt.Sprintf("return claimed %d but allowable is %d; "+
			"allowed-or-allowable rule: recapture uses allowable", allowed, allowableCents)}, outlier
	}
	if allowed > allowableCents {
		return allowed, []string{"return claimed more than table allowable; basis reduced by amount claimed"}, false
	}
	return allowableCents, nil, false
}

// LedgerRow is a DepreciationLedger row {tax_year, allowed_cents, allowable_cents, method}.
type LedgerRow struct {
	TaxYear        int
	AllowedCents   *int64
	AllowableCents *int64
	Method         *string
	// HasMethod/HasAllowed distinguish a missing key from an explicit null in golden inputs.
	keys []string
}

// NewLedgerRow builds a ledger row with the four DB keys (the shape services.portfolio produces).
func NewLedgerRow(year int, allowed, allowable *int64, method string) LedgerRow {
	m := method
	return LedgerRow{TaxYear: year, AllowedCents: allowed, AllowableCents: allowable, Method: &m,
		keys: []string{"tax_year", "allowed_cents", "allowable_cents", "method"}}
}

// LedgerRowFromObj builds a row from a fixture dict, remembering which keys it carried (dict(r) in the trace).
func LedgerRowFromObj(o *jsonx.Obj) LedgerRow {
	r := LedgerRow{keys: o.Keys()}
	if v, ok := o.Get("tax_year"); ok {
		r.TaxYear = int(toInt(v))
	}
	if v, ok := o.Get("allowed_cents"); ok && v != nil {
		x := toInt(v)
		r.AllowedCents = &x
	}
	if v, ok := o.Get("allowable_cents"); ok && v != nil {
		x := toInt(v)
		r.AllowableCents = &x
	}
	if v, ok := o.Get("method"); ok && v != nil {
		s := v.(string)
		r.Method = &s
	}
	return r
}

func toInt(v any) int64 {
	switch x := v.(type) {
	case int64:
		return x
	case int:
		return int64(x)
	case jsonx.Float:
		return int64(x)
	}
	return 0
}

// ToObj renders the row as dict(r).
func (r LedgerRow) ToObj() *jsonx.Obj {
	o := jsonx.O()
	for _, k := range r.keys {
		switch k {
		case "tax_year":
			o.Set(k, int64(r.TaxYear))
		case "allowed_cents":
			o.Set(k, r.AllowedCents)
		case "allowable_cents":
			o.Set(k, r.AllowableCents)
		case "method":
			o.Set(k, r.Method)
		}
	}
	return o
}

func (r LedgerRow) method() string {
	if r.Method == nil {
		return ""
	}
	return *r.Method
}

// Result is DepreciationResult.
type Result struct {
	Basis        *figure.Figure
	Schedule     []ScheduleRow
	Accumulated  *figure.Figure
	CurrentYear  *figure.Figure
	Sec1245Cents int64
	Outlier      bool
	Notes        []string
}

// Compute is compute_depreciation(...).
func Compute(purchasePriceCents, improvementsCents int64, landPct *dec.D, placedInService dates.Date, propertyType string,
	asOfYear int, mode string, ledger []LedgerRow, costSegStudy bool, sources map[string]*figure.Input) *Result {
	basis := DepreciableBasis(purchasePriceCents, improvementsCents, landPct, sources)
	pclass := PropertyClass(propertyType)
	schedule := AnnualSchedule(basis.VC(), placedInService, pclass, mode)
	byYear := map[int]LedgerRow{}
	for _, r := range ledger {
		byYear[r.TaxYear] = r
	}
	var notes []string
	var sec1245 int64
	accelerated := costSegStudy
	for _, r := range ledger {
		if m := r.method(); m == "bonus" || m == "cost_seg" {
			accelerated = true
		}
	}
	outlier := false
	tableThrough := AccumulatedThrough(schedule, asOfYear-1)
	recaptureBasis := tableThrough
	if accelerated {
		var ledgerTotal, slTotal int64
		years := make([]int, 0, len(byYear))
		for y := range byYear {
			years = append(years, y)
		}
		sort.Ints(years)
		for _, yr := range years {
			if yr >= asOfYear {
				continue
			}
			row := byYear[yr]
			var amt int64
			if row.AllowedCents != nil && *row.AllowedCents != 0 {
				amt = *row.AllowedCents
			} else if row.AllowableCents != nil {
				amt = *row.AllowableCents
			}
			ledgerTotal += amt
			slTotal += AmountInYear(schedule, yr)
		}
		sec1245 = max(0, ledgerTotal-slTotal)
		recaptureBasis = max(ledgerTotal, tableThrough)
		notes = append(notes, "cost-seg/bonus ledger overrides the table; excess over straight-line tagged Sec 1245")
	} else {
		var claimedRows []LedgerRow
		for _, r := range ledger {
			if r.TaxYear < asOfYear && r.AllowedCents != nil {
				claimedRows = append(claimedRows, r)
			}
		}
		if len(claimedRows) > 0 {
			var claimed, allowable int64
			for _, r := range claimedRows {
				claimed += *r.AllowedCents
				allowable += AmountInYear(schedule, r.TaxYear)
			}
			rb, n, o := AllowedOrAllowable(allowable, &claimed)
			outlier = o
			notes = append(notes, n...)
			otherYears := tableThrough - allowable
			recaptureBasis = rb + otherYears
			for _, r := range claimedRows {
				tableAmt := AmountInYear(schedule, r.TaxYear)
				diff := *r.AllowedCents - tableAmt
				if diff < 0 {
					diff = -diff
				}
				if tableAmt != 0 && dec.I(diff).Gt(dec.I(tableAmt).Mul(dec.S("0.05"))) {
					notes = append(notes, fmt.Sprintf("%d: return shows %d vs allowable %d (>5%% gap)", r.TaxYear, *r.AllowedCents, tableAmt))
				}
			}
		}
	}
	inputs := figure.L(figure.Fig(basis), figure.M("placed_in_service", placedInService), figure.M("as_of_year", int64(asOfYear)))
	if len(ledger) > 0 {
		rows := make([]any, len(ledger))
		for i, r := range ledger {
			rows[i] = r.ToObj()
		}
		inputs = append(inputs, figure.Of("depreciation_ledger", rows, "document", "Form 4562"))
	}
	rb := recaptureBasis
	accumulated := &figure.Figure{Key: "depreciation.accumulated", ValueCents: &rb, Status: figure.DeriveStatus(inputs, nil),
		Inputs: inputs, Formula: fmt.Sprintf("sum(schedule[year] for year <= %d); allowed-or-allowable", asOfYear-1),
		Notes: append([]string{}, notes...), Unit: "cents"}
	current := figure.Money("depreciation.current_year", dec.I(AmountInYear(schedule, asOfYear)),
		figure.L(figure.Fig(basis), figure.M("as_of_year", int64(asOfYear))),
		fmt.Sprintf("schedule[%d] (%s mode, %s, mid-month convention)", asOfYear, mode, pclass), nil, nil)
	return &Result{basis, schedule, accumulated, current, sec1245, outlier, notes}
}
