// Package loans ports engine/loans.py: monthly schedules for fixed, interest-only, ARM, HELOC and balloon loans.
//
// The schedule starts the month AFTER balance_as_of from balance_cents and runs to maturity (or term_months).
// Monthly interest = round_half_up(balance x rate / 12); principal = payment - interest; the final payment clears
// the remaining balance exactly. Payment = annuity formula on the remaining term rounded half-up once, unless the
// statement's monthly_payment_cents is supplied.
package loans

import (
	"fmt"

	"github.com/tachyurgy/groundplan/engine-go/dec"
	"github.com/tachyurgy/groundplan/engine-go/engine/dates"
	"github.com/tachyurgy/groundplan/engine-go/engine/figure"
	"github.com/tachyurgy/groundplan/engine-go/jsonx"
)

// ArmIndexDefault is the forward index assumption when none is supplied.
var ArmIndexDefault = dec.S("0.045")

// Input is LoanInput.
type Input struct {
	LoanType            string
	BalanceCents        int64
	BalanceAsOf         dates.Date
	Rate                dec.D
	TermMonths          int
	IOMonths            int
	ArmResetDate        *dates.Date
	ArmIndexMargin      *dec.D
	ArmIndex            *dec.D
	MonthlyPaymentCents *int64
	MaturityDate        *dates.Date
	LienPosition        int
	IsPaidOff           bool
	Lender              string
	ID                  *string
}

// Validate mirrors LoanInput.__post_init__.
func (l *Input) Validate() error {
	switch l.LoanType {
	case "fixed", "arm", "interest_only", "heloc", "balloon":
		return nil
	}
	return fmt.Errorf("unknown loan_type %q", l.LoanType)
}

// MonthRow is one month of the schedule.
type MonthRow struct {
	Index          int
	Year           int
	Month          int
	Rate           string
	PaymentCents   int64
	InterestCents  int64
	PrincipalCents int64
	BalanceCents   int64
	Phase          string
}

// ToDict is MonthRow.to_dict.
func (r MonthRow) ToDict() *jsonx.Obj {
	return jsonx.O("index", r.Index, "year", r.Year, "month", r.Month, "rate", r.Rate, "payment_cents", r.PaymentCents,
		"interest_cents", r.InterestCents, "principal_cents", r.PrincipalCents, "balance_cents", r.BalanceCents, "phase", r.Phase)
}

// Schedule is LoanSchedule.
type Schedule struct {
	Loan  *Input
	Rows  []MonthRow
	Notes []string
}

func (s *Schedule) PrincipalPaidInYear(year int) int64 {
	var t int64
	for _, r := range s.Rows {
		if r.Year == year && r.Phase != "balloon_due" {
			t += r.PrincipalCents
		}
	}
	return t
}

func (s *Schedule) InterestPaidInYear(year int) int64 {
	var t int64
	for _, r := range s.Rows {
		if r.Year == year {
			t += r.InterestCents
		}
	}
	return t
}

func (s *Schedule) DebtServiceInYear(year int) int64 {
	var t int64
	for _, r := range s.Rows {
		if r.Year == year && r.Phase != "balloon_due" {
			t += r.PaymentCents
		}
	}
	return t
}

func (s *Schedule) BalloonInYear(year int) int64 {
	var t int64
	for _, r := range s.Rows {
		if r.Year == year && r.Phase == "balloon_due" {
			t += r.PrincipalCents
		}
	}
	return t
}

// BalanceAt is the balance at the end of the month containing `on`.
func (s *Schedule) BalanceAt(on dates.Date) int64 {
	onYM := on.Year()*12 + int(on.Month())
	if len(s.Rows) == 0 || onYM < s.Rows[0].Year*12+s.Rows[0].Month {
		if s.Loan.IsPaidOff {
			return 0
		}
		return s.Loan.BalanceCents
	}
	bal := s.Loan.BalanceCents
	for _, r := range s.Rows {
		if r.Year*12+r.Month > onYM {
			break
		}
		bal = r.BalanceCents
	}
	return bal
}

func (s *Schedule) BalanceEndOfYear(year int) int64 { return s.BalanceAt(dates.New(year, 12, 31)) }

// Annual is the annual_summary dict.
type Annual struct {
	Year             int
	PrincipalCents   int64
	InterestCents    int64
	DebtServiceCents int64
	BalloonCents     int64
	BalanceEndCents  int64
}

// ToDict renders annual_summary.
func (a Annual) ToDict() *jsonx.Obj {
	return jsonx.O("year", a.Year, "principal_cents", a.PrincipalCents, "interest_cents", a.InterestCents,
		"debt_service_cents", a.DebtServiceCents, "balloon_cents", a.BalloonCents, "balance_end_cents", a.BalanceEndCents)
}

func (s *Schedule) AnnualSummary(year int) Annual {
	return Annual{year, s.PrincipalPaidInYear(year), s.InterestPaidInYear(year), s.DebtServiceInYear(year),
		s.BalloonInYear(year), s.BalanceEndOfYear(year)}
}

func addMonths(y, m, n int) (int, int) {
	idx := y*12 + (m - 1) + n
	return floorDiv(idx, 12), floorMod(idx, 12) + 1
}

func floorDiv(a, b int) int {
	q := a / b
	if (a%b != 0) && ((a < 0) != (b < 0)) {
		q--
	}
	return q
}

func floorMod(a, b int) int { return a - floorDiv(a, b)*b }

// MonthsBetween is (b.year - a.year)*12 + (b.month - a.month).
func MonthsBetween(a, b dates.Date) int {
	return (b.Year()-a.Year())*12 + (int(b.Month()) - int(a.Month()))
}

// AnnuityPayment is the level monthly payment rounded half-up once.
func AnnuityPayment(balance, annualRate dec.D, nMonths int) int64 {
	if nMonths <= 0 {
		return balance.Cents()
	}
	r := annualRate.Quo(dec.I(12))
	if r.IsZero() {
		return balance.Quo(dec.I(int64(nMonths))).Cents()
	}
	factor := dec.One.Add(r).PowInt(nMonths)
	return balance.Mul(r).Mul(factor).Quo(factor.Sub(dec.One)).Cents()
}

// Build is build_schedule(loan).
func Build(loan *Input) *Schedule {
	sched := &Schedule{Loan: loan}
	if loan.IsPaidOff || loan.BalanceCents <= 0 {
		sched.Notes = append(sched.Notes, "lien is paid off; contributes 0 to debt service but is kept in the trace")
		return sched
	}
	rate := loan.Rate
	totalMonths := loan.TermMonths
	if loan.MaturityDate != nil {
		totalMonths = MonthsBetween(loan.BalanceAsOf, *loan.MaturityDate)
	}
	totalMonths = max(1, totalMonths)
	amortMonths := totalMonths
	if loan.LoanType == "balloon" {
		amortMonths = loan.TermMonths
	}
	y0, m0 := loan.BalanceAsOf.Year(), int(loan.BalanceAsOf.Month())
	balance := dec.I(loan.BalanceCents)
	resetIdx := -1
	if loan.LoanType == "arm" && loan.ArmResetDate != nil {
		resetIdx = MonthsBetween(loan.BalanceAsOf, *loan.ArmResetDate)
		if resetIdx < 1 {
			resetIdx = 1
		}
	}
	var resetRate *dec.D
	if loan.LoanType == "arm" {
		idx := ArmIndexDefault
		if loan.ArmIndex != nil {
			idx = *loan.ArmIndex
		}
		margin := dec.S("0.0225")
		if loan.ArmIndexMargin != nil {
			margin = *loan.ArmIndexMargin
		}
		rr := idx.Add(margin)
		resetRate = &rr
		if loan.ArmIndex == nil {
			sched.Notes = append(sched.Notes, fmt.Sprintf("ARM reset rate assumes index %s + margin %s (assumption)", ArmIndexDefault, margin))
		}
	}
	ioMonths := 0
	if loan.LoanType == "interest_only" || loan.LoanType == "arm" || loan.LoanType == "fixed" {
		ioMonths = loan.IOMonths
	}
	if loan.LoanType == "heloc" {
		ioMonths = totalMonths
		sched.Notes = append(sched.Notes, "HELOC modeled as interest-only revolving at the stated rate on the current balance")
	}
	var payment *int64
	curRate := rate
	for i := 1; i <= totalMonths; i++ {
		yr, mo := addMonths(y0, m0, i)
		phase := "amortizing"
		if resetIdx >= 0 && i == resetIdx && resetRate != nil {
			curRate = *resetRate
			payment = nil
		}
		interest := balance.Mul(curRate).Quo(dec.I(12)).Cents()
		var principal, pay int64
		if i <= ioMonths {
			principal = 0
			pay = interest
			if loan.LoanType == "heloc" {
				phase = "heloc"
			} else {
				phase = "interest_only"
			}
		} else {
			if payment == nil {
				remainingAmort := totalMonths - i + 1
				if loan.LoanType == "balloon" {
					remainingAmort = amortMonths - i + 1
				}
				useStatement := loan.MonthlyPaymentCents != nil && i == ioMonths+1 && curRate.Eq(rate)
				var p int64
				if useStatement && *loan.MonthlyPaymentCents != 0 {
					p = *loan.MonthlyPaymentCents
				} else {
					p = AnnuityPayment(balance, curRate, remainingAmort)
				}
				payment = &p
			}
			pay = *payment
			principal = pay - interest
			if resetIdx >= 0 && i >= resetIdx {
				phase = "arm_reset"
			}
			if dec.I(principal).Gt(balance) || i == totalMonths {
				if loan.LoanType != "balloon" || i == totalMonths {
					principal = balance.Int()
				}
				if loan.LoanType == "balloon" && i == totalMonths {
					regPrincipal := min(pay-interest, balance.Int())
					balance = balance.Sub(dec.I(regPrincipal))
					sched.Rows = append(sched.Rows, MonthRow{i, yr, mo, curRate.String(), pay, interest, regPrincipal, balance.Int(), "amortizing"})
					if balance.Sign() > 0 {
						b := balance.Int()
						sched.Rows = append(sched.Rows, MonthRow{i, yr, mo, curRate.String(), b, 0, b, 0, "balloon_due"})
						balance = dec.Zero
					}
					break
				}
				pay = principal + interest
			}
		}
		balance = balance.Sub(dec.I(principal))
		sched.Rows = append(sched.Rows, MonthRow{i, yr, mo, curRate.String(), pay, interest, principal, balance.Int(), phase})
		if balance.Sign() <= 0 && loan.LoanType != "heloc" {
			break
		}
	}
	if loan.LoanType == "heloc" && balance.Sign() > 0 {
		sched.Notes = append(sched.Notes, "HELOC balance outstanding at end of draw/maturity: assumed refinanced or repaid from equity")
	}
	return sched
}

// CombinedAnnual sums annual summaries across liens.
func CombinedAnnual(scheds []*Schedule, year int) Annual {
	out := Annual{Year: year}
	for _, s := range scheds {
		a := s.AnnualSummary(year)
		out.PrincipalCents += a.PrincipalCents
		out.InterestCents += a.InterestCents
		out.DebtServiceCents += a.DebtServiceCents
		out.BalloonCents += a.BalloonCents
		out.BalanceEndCents += a.BalanceEndCents
	}
	return out
}

// TotalBalanceAt sums balances.
func TotalBalanceAt(scheds []*Schedule, on dates.Date) int64 {
	var t int64
	for _, s := range scheds {
		t += s.BalanceAt(on)
	}
	return t
}

// DSCR is NOI / annual debt service.
func DSCR(noiCents, annualDebtServiceCents int64, inputs []*figure.Input) *figure.Figure {
	var val *dec.D
	var notes []string
	if annualDebtServiceCents > 0 {
		v := dec.I(noiCents).Quo(dec.I(annualDebtServiceCents))
		val = &v
	} else {
		notes = []string{"no debt service: DSCR undefined"}
	}
	if inputs == nil {
		inputs = figure.L(figure.M("noi_cents", noiCents), figure.M("annual_debt_service_cents", annualDebtServiceCents))
	}
	return figure.Ratio("loans.dscr", val, inputs, "NOI / annual debt service", "ratio", notes, 4)
}
