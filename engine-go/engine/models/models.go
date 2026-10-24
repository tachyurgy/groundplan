// Package models ports engine/models.py: plain engine input models (no ORM) that the service layer maps rows onto.
package models

import (
	"github.com/tachyurgy/groundplan/engine-go/dec"
	"github.com/tachyurgy/groundplan/engine-go/engine/cashflow"
	"github.com/tachyurgy/groundplan/engine-go/engine/dates"
	"github.com/tachyurgy/groundplan/engine-go/engine/depreciation"
	"github.com/tachyurgy/groundplan/engine-go/engine/figure"
	"github.com/tachyurgy/groundplan/engine-go/engine/loans"
)

// Property is PropertyModel.
type Property struct {
	ID                      string
	Nickname                string
	PropertyType            string
	Units                   int
	PurchaseDate            dates.Date
	PurchasePriceCents      int64
	PlacedInServiceDate     *dates.Date
	LandPct                 *dec.D
	ImprovementsCents       int64
	CostSegStudy            bool
	CurrentValueCents       int64
	ValueSource             string
	ValueAsOf               *dates.Date
	AppreciationRate        *dec.D
	RentGrowthRate          *dec.D
	ExpenseGrowthRate       *dec.D
	VacancyRate             *dec.D
	MgmtFeeRate             *dec.D
	CapexReserveRate        *dec.D
	SellingCostRate         *dec.D
	Status                  string
	FormerResidenceUntil    *dates.Date
	AvgStayDays             *float64
	Loans                   []*loans.Input
	Years                   map[int]*cashflow.YearOperations
	YearOrder               []int // insertion order of Years (Python dict order)
	Ledger                  []depreciation.LedgerRow
	CapitalImprovementsPaid map[int]int64
	BlockedKeys             figure.KeySet
}

// NewProperty returns the dataclass defaults.
func NewProperty() *Property {
	return &Property{ID: "p1", PropertyType: "sfr", Units: 1, PurchaseDate: dates.New(2015, 1, 1), ValueSource: "estimated",
		Status: "active", Years: map[int]*cashflow.YearOperations{}, CapitalImprovementsPaid: map[int]int64{},
		BlockedKeys: figure.KeySet{}}
}

// InService is placed_in_service_date or purchase_date.
func (p *Property) InService() dates.Date {
	if p.PlacedInServiceDate != nil {
		return *p.PlacedInServiceDate
	}
	return p.PurchaseDate
}

// AddYear inserts a year keeping insertion order.
func (p *Property) AddYear(y int, o *cashflow.YearOperations) {
	if _, ok := p.Years[y]; !ok {
		p.YearOrder = append(p.YearOrder, y)
	}
	p.Years[y] = o
}

// Household is HouseholdModel.
type Household struct {
	FilingStatus        string
	State               string
	TaxYear             int
	WagesCents          int64
	OtherIncomeCents    int64
	MagiCents           int64
	ActiveParticipation bool
	REProfessional      bool
	CarryforwardCents   int64
	NetWorthCents       *int64
	Goal                string
}

// NewHousehold returns the dataclass defaults.
func NewHousehold() *Household {
	return &Household{FilingStatus: "mfj", State: "CA", TaxYear: 2025, ActiveParticipation: true}
}

// Defaults is models.DEFAULTS.
var Defaults = map[string]dec.D{
	"appreciation_rate":   dec.S("0.035"),
	"rent_growth_rate":    dec.S("0.03"),
	"expense_growth_rate": dec.S("0.03"),
	"vacancy_rate":        dec.S("0.05"),
	"capex_reserve_rate":  dec.S("0.05"),
	"selling_cost_rate":   dec.S("0.06"),
	"reinvest_rate":       dec.S("0.06"),
	"dst_load_rate":       dec.S("0.085"),
	"dst_yield":           dec.S("0.05"),
}

// RateOrDefault returns (rate, source_type): a nil rate falls back to the default and marks the figure estimated.
func RateOrDefault(value *dec.D, name string) (dec.D, string) {
	if value == nil {
		return Defaults[name], "default"
	}
	return *value, "manual"
}
