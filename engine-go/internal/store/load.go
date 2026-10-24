package store

import (
	"context"
	"errors"

	"github.com/jackc/pgx/v5"
)

// ErrNotFound means the row does not exist in this workspace.
var ErrNotFound = errors.New("not found")

// Relationship loads use the same ORDER BY as the SQLAlchemy relationships; relationships without an order_by
// are read in physical (ctid) order, which is what Postgres returns for the ORM's unordered lazy loads.

// ListHouseholds returns the workspace's households ordered by name (shallow).
func ListHouseholds(ctx context.Context, q Q, aid string) ([]*Household, error) {
	return queryAll(ctx, q, scanHousehold, `SELECT `+householdCols+` FROM households WHERE advisor_id = $1 ORDER BY name`, aid)
}

// HouseholdIDForProperty etc. resolve owned ids.
func ownedOne(ctx context.Context, q Q, sql, aid, id string) (string, error) {
	var out string
	err := q.QueryRow(ctx, sql, aid, id).Scan(&out)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", ErrNotFound
	}
	return out, err
}

// PropertyHousehold returns the household id of an owned property.
func PropertyHousehold(ctx context.Context, q Q, aid, pid string) (string, error) {
	return ownedOne(ctx, q, `SELECT household_id FROM properties WHERE advisor_id = $1 AND id = $2`, aid, pid)
}

// LoanProperty returns the property id of an owned loan.
func LoanProperty(ctx context.Context, q Q, aid, id string) (string, error) {
	return ownedOne(ctx, q, `SELECT property_id FROM loans WHERE advisor_id = $1 AND id = $2`, aid, id)
}

// DocumentHousehold returns the household of an owned document.
func DocumentHousehold(ctx context.Context, q Q, aid, id string) (string, error) {
	return ownedOne(ctx, q, `SELECT household_id FROM documents WHERE advisor_id = $1 AND id = $2`, aid, id)
}

// FindingHousehold returns the household of an owned finding.
func FindingHousehold(ctx context.Context, q Q, aid, id string) (string, error) {
	return ownedOne(ctx, q, `SELECT household_id FROM findings WHERE advisor_id = $1 AND id = $2`, aid, id)
}

// ScenarioByID loads an owned scenario.
func ScenarioByID(ctx context.Context, q Q, aid, id string) (*Scenario, error) {
	s, err := scanScenario(q.QueryRow(ctx, `SELECT `+scenarioCols+` FROM scenarios WHERE advisor_id = $1 AND id = $2`, aid, id))
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, ErrNotFound
	}
	return s, err
}

// LoadHousehold loads one owned household with its whole tree.
func LoadHousehold(ctx context.Context, q Q, aid, hid string) (*Household, error) {
	h, err := scanHousehold(q.QueryRow(ctx, `SELECT `+householdCols+` FROM households WHERE advisor_id = $1 AND id = $2`, aid, hid))
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	if err := fillHousehold(ctx, q, h); err != nil {
		return nil, err
	}
	return h, nil
}

func fillHousehold(ctx context.Context, q Q, h *Household) error {
	var err error
	if h.Properties, err = queryAll(ctx, q, scanProperty, `SELECT `+propertyCols+` FROM properties WHERE household_id = $1 AND advisor_id = $2 ORDER BY nickname`, h.ID, h.AdvisorID); err != nil {
		return err
	}
	byID := map[string]*Property{}
	ids := make([]string, 0, len(h.Properties))
	for _, p := range h.Properties {
		p.Household = h
		byID[p.ID] = p
		ids = append(ids, p.ID)
	}
	if len(ids) > 0 {
		lns, err := queryAll(ctx, q, scanLoan, `SELECT `+loanCols+` FROM loans WHERE property_id = ANY($1) AND advisor_id = $2 ORDER BY lien_position, ctid`, ids, h.AdvisorID)
		if err != nil {
			return err
		}
		for _, l := range lns {
			byID[l.PropertyID].Loans = append(byID[l.PropertyID].Loans, l)
		}
		rrs, err := queryAll(ctx, q, func(r pgx.Row) (*RentRoll, error) {
			x := &RentRoll{}
			return x, r.Scan(&x.ID, &x.AdvisorID, &x.PropertyID, &x.TaxYear, &x.GrossRentCents, &x.OtherIncomeCents)
		}, `SELECT id, advisor_id, property_id, tax_year, gross_rent_cents, other_income_cents FROM rent_rolls
			WHERE property_id = ANY($1) AND advisor_id = $2 ORDER BY tax_year`, ids, h.AdvisorID)
		if err != nil {
			return err
		}
		for _, x := range rrs {
			byID[x.PropertyID].RentRolls = append(byID[x.PropertyID].RentRolls, x)
		}
		eys, err := queryAll(ctx, q, func(r pgx.Row) (*ExpenseYear, error) {
			x := &ExpenseYear{Cents: map[string]int64{}}
			v := make([]int64, len(ExpenseKeys))
			dst := []any{&x.ID, &x.AdvisorID, &x.PropertyID, &x.TaxYear}
			for i := range v {
				dst = append(dst, &v[i])
			}
			if err := r.Scan(dst...); err != nil {
				return nil, err
			}
			for i, k := range ExpenseKeys {
				x.Cents[k] = v[i]
			}
			return x, nil
		}, `SELECT id, advisor_id, property_id, tax_year, taxes_cents, insurance_cents, repairs_cents, mgmt_cents, utilities_cents,
			hoa_cents, other_cents, mortgage_interest_cents, depreciation_cents FROM expense_years
			WHERE property_id = ANY($1) AND advisor_id = $2 ORDER BY tax_year`, ids, h.AdvisorID)
		if err != nil {
			return err
		}
		for _, x := range eys {
			byID[x.PropertyID].ExpenseYears = append(byID[x.PropertyID].ExpenseYears, x)
		}
		lds, err := queryAll(ctx, q, func(r pgx.Row) (*Ledger, error) {
			x := &Ledger{}
			return x, r.Scan(&x.ID, &x.AdvisorID, &x.PropertyID, &x.TaxYear, &x.AllowedCents, &x.AllowableCents, &x.Method, &x.Note)
		}, `SELECT id, advisor_id, property_id, tax_year, allowed_cents, allowable_cents, method, note FROM depreciation_ledgers
			WHERE property_id = ANY($1) AND advisor_id = $2 ORDER BY tax_year`, ids, h.AdvisorID)
		if err != nil {
			return err
		}
		for _, x := range lds {
			byID[x.PropertyID].Ledger = append(byID[x.PropertyID].Ledger, x)
		}
		scs, err := queryAll(ctx, q, scanScenario, `SELECT `+scenarioCols+` FROM scenarios WHERE property_id = ANY($1) AND advisor_id = $2 ORDER BY ctid`, ids, h.AdvisorID)
		if err != nil {
			return err
		}
		for _, x := range scs {
			byID[x.PropertyID].Scenarios = append(byID[x.PropertyID].Scenarios, x)
		}
	}
	if h.SuspendedLosses, err = queryAll(ctx, q, func(r pgx.Row) (*SuspendedLoss, error) {
		x := &SuspendedLoss{}
		return x, r.Scan(&x.ID, &x.AdvisorID, &x.HouseholdID, &x.TaxYear, &x.CarryforwardCents)
	}, `SELECT id, advisor_id, household_id, tax_year, carryforward_cents FROM suspended_losses WHERE household_id = $1 AND advisor_id = $2 ORDER BY ctid`, h.ID, h.AdvisorID); err != nil {
		return err
	}
	if h.Documents, err = queryAll(ctx, q, scanDocument, `SELECT `+documentCols+` FROM documents WHERE household_id = $1 AND advisor_id = $2 ORDER BY ctid`, h.ID, h.AdvisorID); err != nil {
		return err
	}
	if len(h.Documents) > 0 {
		dids := make([]string, len(h.Documents))
		dby := map[string]*Document{}
		for i, d := range h.Documents {
			dids[i] = d.ID
			dby[d.ID] = d
		}
		fs, err := queryAll(ctx, q, scanField, `SELECT `+fieldCols+` FROM extracted_fields WHERE document_id = ANY($1) AND advisor_id = $2 ORDER BY ctid`, dids, h.AdvisorID)
		if err != nil {
			return err
		}
		for _, f := range fs {
			dby[f.DocumentID].Fields = append(dby[f.DocumentID].Fields, f)
		}
	}
	if h.Findings, err = queryAll(ctx, q, scanFinding, `SELECT `+findingCols+` FROM findings WHERE household_id = $1 AND advisor_id = $2 ORDER BY `+FindingsOrderBy, h.ID, h.AdvisorID); err != nil {
		return err
	}
	return nil
}

// FieldSource is one extracted field joined to its document (portfolio._field_sources).
type FieldSource struct {
	Field *Field
	Doc   *Document
}

// FieldSources mirrors the join in services.portfolio._field_sources.
func FieldSources(ctx context.Context, q Q, aid, householdID, propertyKey string) ([]FieldSource, error) {
	rows, err := q.Query(ctx, `SELECT f.id, f.advisor_id, f.document_id, f.entity_hint, f.property_key, f.field, f.value, f.unit, f.page,
		f.bbox, f.confidence, f.extractor, f.raw_text,
		d.id, d.advisor_id, d.household_id, d.kind, d.tax_year, d.filename, d.sha256, d.page_count, d.uploaded_at, d.status, d.bytes_retained
		FROM extracted_fields f JOIN documents d ON d.id = f.document_id
		WHERE f.advisor_id = $1 AND d.advisor_id = $1 AND d.household_id = $2 AND f.property_key = $3`, aid, householdID, propertyKey)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []FieldSource
	for rows.Next() {
		f := &Field{}
		d := &Document{}
		var val, bbox []byte
		if err := rows.Scan(&f.ID, &f.AdvisorID, &f.DocumentID, &f.EntityHint, &f.PropertyKey, &f.Field, &val, &f.Unit, &f.Page, &bbox,
			&f.Confidence, &f.Extractor, &f.RawText, &d.ID, &d.AdvisorID, &d.HouseholdID, &d.Kind, &d.TaxYear, &d.Filename, &d.Sha256,
			&d.PageCount, &d.UploadedAt, &d.Status, &d.BytesRetained); err != nil {
			return nil, err
		}
		f.Value, f.BBox = jsonVal(val), jsonVal(bbox)
		out = append(out, FieldSource{f, d})
	}
	return out, rows.Err()
}

// FindProperty returns the property (with its household tree) by id.
func FindProperty(h *Household, pid string) *Property {
	for _, p := range h.Properties {
		if p.ID == pid {
			return p
		}
	}
	return nil
}
