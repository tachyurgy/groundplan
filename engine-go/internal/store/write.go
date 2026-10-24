package store

import (
	"context"
	"encoding/json"

	"github.com/tachyurgy/groundplan/engine-go/dec"
	"github.com/tachyurgy/groundplan/engine-go/jsonx"
)

// Writes mirror the ORM's unit of work: a row is INSERTed when new and UPDATEd only when one of its columns
// changed (Snapshot before, compare after), so the physical row order evolves like the Python side's.

// Snapshot renders a row's columns for change detection.
func Snapshot(v any) string {
	b, _ := json.Marshal(v)
	return string(b)
}

func decArg(d *dec.D) any {
	if d == nil {
		return nil
	}
	return d.String()
}

func jsonArg(v any) any {
	if v == nil {
		return "null" // SQLAlchemy's JSON type stores Python None as JSON null
	}
	return string(jsonx.MustMarshal(v))
}

func jsonArgNullable(v any) any {
	if v == nil {
		return nil
	}
	return string(jsonx.MustMarshal(v))
}

// SaveHousehold updates the household's scalar columns.
func SaveHousehold(ctx context.Context, q Q, h *Household) error {
	_, err := q.Exec(ctx, `UPDATE households SET name=$3, filing_status=$4, state=$5, tax_year_latest=$6, wages_cents=$7,
		other_income_cents=$8, magi_cents=$9, active_participation=$10, re_professional=$11, net_worth_cents=$12, goal=$13, notes=$14
		WHERE id=$1 AND advisor_id=$2`, h.ID, h.AdvisorID, h.Name, h.FilingStatus, h.State, h.TaxYearLatest, h.WagesCents,
		h.OtherIncomeCents, h.MagiCents, h.ActiveParticipation, h.REProfessional, h.NetWorthCents, h.Goal, h.Notes)
	return err
}

// InsertHousehold inserts a household.
func InsertHousehold(ctx context.Context, q Q, h *Household) error {
	_, err := q.Exec(ctx, `INSERT INTO households (id, advisor_id, name, filing_status, state, tax_year_latest, wages_cents,
		other_income_cents, magi_cents, active_participation, re_professional, net_worth_cents, goal, notes, created_at)
		VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)`, h.ID, h.AdvisorID, h.Name, h.FilingStatus, h.State, h.TaxYearLatest,
		h.WagesCents, h.OtherIncomeCents, h.MagiCents, h.ActiveParticipation, h.REProfessional, h.NetWorthCents, h.Goal, h.Notes, h.CreatedAt)
	return err
}

func propArgs(p *Property) []any {
	return []any{p.ID, p.AdvisorID, p.HouseholdID, p.Nickname, p.AddressLine1, p.City, p.State, p.Zip, p.PropertyType, p.Units,
		p.PurchaseDate, p.PurchasePriceCents, p.PlacedInServiceDate, decArg(p.LandPct), p.ImprovementsCents, p.CostSegStudy,
		p.CurrentValueCents, p.ValueSource, p.ValueAsOf, decArg(p.AppreciationRate), decArg(p.RentGrowthRate),
		decArg(p.ExpenseGrowthRate), decArg(p.VacancyRate), decArg(p.MgmtFeeRate), decArg(p.CapexReserveRate),
		decArg(p.SellingCostRate), p.Status, p.FormerResidenceUntil, p.AvgStayDays, p.PropertyKey}
}

// InsertProperty inserts a property.
func InsertProperty(ctx context.Context, q Q, p *Property) error {
	_, err := q.Exec(ctx, `INSERT INTO properties (id, advisor_id, household_id, nickname, address_line1, city, state, zip, property_type,
		units, purchase_date, purchase_price_cents, placed_in_service_date, land_pct, improvements_cents, cost_seg_study,
		current_value_cents, value_source, value_as_of, appreciation_rate, rent_growth_rate, expense_growth_rate, vacancy_rate,
		mgmt_fee_rate, capex_reserve_rate, selling_cost_rate, status, former_residence_until, avg_stay_days, property_key)
		VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14::numeric,$15,$16,$17,$18,$19,$20::numeric,$21::numeric,$22::numeric,
		$23::numeric,$24::numeric,$25::numeric,$26::numeric,$27,$28,$29,$30)`, propArgs(p)...)
	return err
}

// UpdateProperty writes every column of a property.
func UpdateProperty(ctx context.Context, q Q, p *Property) error {
	_, err := q.Exec(ctx, `UPDATE properties SET household_id=$3, nickname=$4, address_line1=$5, city=$6, state=$7, zip=$8,
		property_type=$9, units=$10, purchase_date=$11, purchase_price_cents=$12, placed_in_service_date=$13, land_pct=$14::numeric,
		improvements_cents=$15, cost_seg_study=$16, current_value_cents=$17, value_source=$18, value_as_of=$19,
		appreciation_rate=$20::numeric, rent_growth_rate=$21::numeric, expense_growth_rate=$22::numeric, vacancy_rate=$23::numeric,
		mgmt_fee_rate=$24::numeric, capex_reserve_rate=$25::numeric, selling_cost_rate=$26::numeric, status=$27,
		former_residence_until=$28, avg_stay_days=$29, property_key=$30 WHERE id=$1 AND advisor_id=$2`, propArgs(p)...)
	return err
}

func loanArgs(l *Loan) []any {
	return []any{l.ID, l.AdvisorID, l.PropertyID, l.Lender, l.LoanType, l.OriginalCents, l.BalanceCents, l.BalanceAsOf, l.Rate.String(),
		l.TermMonths, l.IOMonths, l.ArmResetDate, decArg(l.ArmIndexMargin), l.MonthlyPaymentCents, l.MaturityDate, l.LienPosition, l.IsPaidOff}
}

// InsertLoan inserts a loan.
func InsertLoan(ctx context.Context, q Q, l *Loan) error {
	_, err := q.Exec(ctx, `INSERT INTO loans (id, advisor_id, property_id, lender, loan_type, original_cents, balance_cents, balance_as_of,
		rate, term_months, io_months, arm_reset_date, arm_index_margin, monthly_payment_cents, maturity_date, lien_position, is_paid_off)
		VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::numeric,$10,$11,$12,$13::numeric,$14,$15,$16,$17)`, loanArgs(l)...)
	return err
}

// UpdateLoan writes every column of a loan.
func UpdateLoan(ctx context.Context, q Q, l *Loan) error {
	_, err := q.Exec(ctx, `UPDATE loans SET property_id=$3, lender=$4, loan_type=$5, original_cents=$6, balance_cents=$7, balance_as_of=$8,
		rate=$9::numeric, term_months=$10, io_months=$11, arm_reset_date=$12, arm_index_margin=$13::numeric, monthly_payment_cents=$14,
		maturity_date=$15, lien_position=$16, is_paid_off=$17 WHERE id=$1 AND advisor_id=$2`, loanArgs(l)...)
	return err
}

// SaveRentRoll inserts or updates a rent roll.
func SaveRentRoll(ctx context.Context, q Q, r *RentRoll, isNew bool) error {
	if isNew {
		_, err := q.Exec(ctx, `INSERT INTO rent_rolls (id, advisor_id, property_id, tax_year, gross_rent_cents, other_income_cents)
			VALUES ($1,$2,$3,$4,$5,$6)`, r.ID, r.AdvisorID, r.PropertyID, r.TaxYear, r.GrossRentCents, r.OtherIncomeCents)
		return err
	}
	_, err := q.Exec(ctx, `UPDATE rent_rolls SET gross_rent_cents=$3, other_income_cents=$4 WHERE id=$1 AND advisor_id=$2`,
		r.ID, r.AdvisorID, r.GrossRentCents, r.OtherIncomeCents)
	return err
}

// SaveExpenseYear inserts or updates an expense year.
func SaveExpenseYear(ctx context.Context, q Q, e *ExpenseYear, isNew bool) error {
	c := e.Cents
	if isNew {
		_, err := q.Exec(ctx, `INSERT INTO expense_years (id, advisor_id, property_id, tax_year, taxes_cents, insurance_cents, repairs_cents,
			mgmt_cents, utilities_cents, hoa_cents, other_cents, mortgage_interest_cents, depreciation_cents)
			VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)`, e.ID, e.AdvisorID, e.PropertyID, e.TaxYear, c["taxes_cents"],
			c["insurance_cents"], c["repairs_cents"], c["mgmt_cents"], c["utilities_cents"], c["hoa_cents"], c["other_cents"],
			c["mortgage_interest_cents"], c["depreciation_cents"])
		return err
	}
	_, err := q.Exec(ctx, `UPDATE expense_years SET taxes_cents=$3, insurance_cents=$4, repairs_cents=$5, mgmt_cents=$6, utilities_cents=$7,
		hoa_cents=$8, other_cents=$9, mortgage_interest_cents=$10, depreciation_cents=$11 WHERE id=$1 AND advisor_id=$2`, e.ID, e.AdvisorID,
		c["taxes_cents"], c["insurance_cents"], c["repairs_cents"], c["mgmt_cents"], c["utilities_cents"], c["hoa_cents"], c["other_cents"],
		c["mortgage_interest_cents"], c["depreciation_cents"])
	return err
}

// SaveLedger inserts or updates a ledger row.
func SaveLedger(ctx context.Context, q Q, d *Ledger, isNew bool) error {
	if isNew {
		_, err := q.Exec(ctx, `INSERT INTO depreciation_ledgers (id, advisor_id, property_id, tax_year, allowed_cents, allowable_cents, method, note)
			VALUES ($1,$2,$3,$4,$5,$6,$7,$8)`, d.ID, d.AdvisorID, d.PropertyID, d.TaxYear, d.AllowedCents, d.AllowableCents, d.Method, d.Note)
		return err
	}
	_, err := q.Exec(ctx, `UPDATE depreciation_ledgers SET allowed_cents=$3, allowable_cents=$4, method=$5, note=$6 WHERE id=$1 AND advisor_id=$2`,
		d.ID, d.AdvisorID, d.AllowedCents, d.AllowableCents, d.Method, d.Note)
	return err
}

// SaveSuspendedLoss inserts or updates a suspended loss.
func SaveSuspendedLoss(ctx context.Context, q Q, x *SuspendedLoss, isNew bool) error {
	if isNew {
		_, err := q.Exec(ctx, `INSERT INTO suspended_losses (id, advisor_id, household_id, tax_year, carryforward_cents) VALUES ($1,$2,$3,$4,$5)`,
			x.ID, x.AdvisorID, x.HouseholdID, x.TaxYear, x.CarryforwardCents)
		return err
	}
	_, err := q.Exec(ctx, `UPDATE suspended_losses SET carryforward_cents=$3 WHERE id=$1 AND advisor_id=$2`, x.ID, x.AdvisorID, x.CarryforwardCents)
	return err
}

// SaveDocument inserts or updates a document.
func SaveDocument(ctx context.Context, q Q, d *Document, isNew bool) error {
	if isNew {
		_, err := q.Exec(ctx, `INSERT INTO documents (id, advisor_id, household_id, kind, tax_year, filename, sha256, page_count, uploaded_at,
			status, bytes_retained) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,false)`, d.ID, d.AdvisorID, d.HouseholdID, d.Kind, d.TaxYear,
			d.Filename, d.Sha256, d.PageCount, d.UploadedAt, d.Status)
		return err
	}
	_, err := q.Exec(ctx, `UPDATE documents SET kind=$3, tax_year=$4, filename=$5, sha256=$6, page_count=$7, status=$8, bytes_retained=false
		WHERE id=$1 AND advisor_id=$2`, d.ID, d.AdvisorID, d.Kind, d.TaxYear, d.Filename, d.Sha256, d.PageCount, d.Status)
	return err
}

// ReplaceFields deletes a document's fields and inserts the new list (d.fields.clear() + append).
func ReplaceFields(ctx context.Context, q Q, d *Document, fields []*Field) error {
	if _, err := q.Exec(ctx, `DELETE FROM extracted_fields WHERE document_id = $1 AND advisor_id = $2`, d.ID, d.AdvisorID); err != nil {
		return err
	}
	for _, f := range fields {
		if _, err := q.Exec(ctx, `INSERT INTO extracted_fields (id, advisor_id, document_id, entity_hint, property_key, field, value, unit,
			page, bbox, confidence, extractor, raw_text) VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9,$10::jsonb,$11,$12,$13)`, f.ID, f.AdvisorID,
			f.DocumentID, f.EntityHint, f.PropertyKey, f.Field, jsonArg(f.Value), f.Unit, f.Page, jsonArg(f.BBox), f.Confidence, f.Extractor,
			f.RawText); err != nil {
			return err
		}
	}
	d.Fields = fields
	return nil
}

// SaveFinding inserts or updates a finding.
func SaveFinding(ctx context.Context, q Q, f *Finding, isNew bool) error {
	if isNew {
		_, err := q.Exec(ctx, `INSERT INTO findings (id, advisor_id, household_id, property_id, key, tax_year, kind, field, severity, message,
			candidates, status, resolution, created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::jsonb,$12,$13::jsonb,$14)`, f.ID, f.AdvisorID,
			f.HouseholdID, f.PropertyID, f.Key, f.TaxYear, f.Kind, f.Field, f.Severity, f.Message, jsonArg(f.Candidates), f.Status,
			jsonArgNullable(f.Resolution), f.CreatedAt)
		return err
	}
	_, err := q.Exec(ctx, `UPDATE findings SET property_id=$3, key=$4, tax_year=$5, kind=$6, field=$7, severity=$8, message=$9,
		candidates=$10::jsonb, status=$11, resolution=$12::jsonb WHERE id=$1 AND advisor_id=$2`, f.ID, f.AdvisorID, f.PropertyID, f.Key,
		f.TaxYear, f.Kind, f.Field, f.Severity, f.Message, jsonArg(f.Candidates), f.Status, jsonArgNullable(f.Resolution))
	return err
}
