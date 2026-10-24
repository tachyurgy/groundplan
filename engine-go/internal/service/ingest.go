package service

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/cockroachdb/apd/v3"
	"github.com/tachyurgy/groundplan/engine-go/dec"
	"github.com/tachyurgy/groundplan/engine-go/engine/dates"
	"github.com/tachyurgy/groundplan/engine-go/internal/store"
	"github.com/tachyurgy/groundplan/engine-go/jsonx"
)

// Port of services/ingest.py: import a ReconciledHousehold and persist upload results. Idempotent upsert:
// properties match on property_key then nickname; loans on lien_position; years / ledger / suspended losses on
// tax_year; documents on sha256 (else filename); findings on their stable key. File bytes never reach this code.

func pget(o *jsonx.Obj, k string) any {
	if o == nil {
		return nil
	}
	return o.MustGet(k)
}

// truthy is Python bool() for JSON values.
func truthy(v any) bool {
	switch x := v.(type) {
	case nil:
		return false
	case string:
		return x != ""
	case int64:
		return x != 0
	case jsonx.Float:
		return x != 0
	case bool:
		return x
	case []any:
		return len(x) > 0
	case *jsonx.Obj:
		return x.Len() > 0
	}
	return true
}

func asStr(v any) (string, bool) {
	if v == nil {
		return "", false
	}
	if s, ok := v.(string); ok {
		return s, true
	}
	return fmt.Sprint(v), true
}

func asInt(v any) (int64, bool) {
	switch x := v.(type) {
	case int64:
		return x, true
	case jsonx.Float:
		return int64(x), true
	case bool:
		if x {
			return 1, true
		}
		return 0, true
	case string:
		i, err := strconv.ParseInt(strings.TrimSpace(x), 10, 64)
		return i, err == nil
	}
	return 0, false
}

func asBool(v any) (bool, bool) {
	if b, ok := v.(bool); ok {
		return b, true
	}
	if v == nil {
		return false, false
	}
	return truthy(v), true
}

// pyDate is ingest._d: falsy -> None, else date.fromisoformat(str(x)[:10]).
func pyDate(v any) *time.Time {
	if !truthy(v) {
		return nil
	}
	s, _ := asStr(v)
	d, err := dates.Parse(s)
	if err != nil {
		panic(&InvalidInput{Msg: fmt.Sprintf("Invalid isoformat string: %s", pyRepr(s))})
	}
	return &d
}

// pyDec is ingest._dec: Decimal(str(x)).
func pyDec(v any) *dec.D {
	if v == nil {
		return nil
	}
	var s string
	switch x := v.(type) {
	case jsonx.Float:
		s = dec.PyFloatRepr(float64(x))
	case float64:
		s = dec.PyFloatRepr(x)
	default:
		s, _ = asStr(v)
	}
	d, err := dec.Parse(s)
	if err != nil {
		panic(&InvalidInput{Msg: err.Error()})
	}
	return &d
}

func objList(v any) []*jsonx.Obj {
	arr, _ := v.([]any)
	var out []*jsonx.Obj
	for _, x := range arr {
		if o, ok := x.(*jsonx.Obj); ok {
			out = append(out, o)
		}
	}
	return out
}

func setS(dst *string, v any) {
	if s, ok := asStr(v); ok {
		*dst = s
	}
}

func setI64(dst *int64, v any) {
	if i, ok := asInt(v); ok {
		*dst = i
	}
}

func setInt(dst *int, v any) {
	if i, ok := asInt(v); ok {
		*dst = int(i)
	}
}

func setB(dst *bool, v any) {
	if b, ok := asBool(v); ok {
		*dst = b
	}
}

func intStat(stats *jsonx.Obj, k string) {
	cur, _ := stats.MustGet(k).(int)
	stats.Set(k, cur+1)
}

// ImportReconciled is ingest.import_reconciled(s, h, payload).
func (svc *Service) ImportReconciled(ctx context.Context, h *store.Household, payload *jsonx.Obj) (stats *jsonx.Obj, err error) {
	defer recoverInvalid(&err)
	q := svc.Q(ctx)
	aid := h.AdvisorID
	stats = jsonx.O("properties_created", 0, "properties_updated", 0, "loans", 0, "years", 0, "ledger", 0, "suspended_losses", 0,
		"documents", 0, "extracted_fields", 0, "findings_created", 0, "findings_updated", 0)
	hh, _ := pget(payload, "household").(*jsonx.Obj)
	before := store.Snapshot(h)
	setS(&h.FilingStatus, pget(hh, "filing_status"))
	setS(&h.State, pget(hh, "state"))
	setInt(&h.TaxYearLatest, pget(hh, "tax_year_latest"))
	setI64(&h.WagesCents, pget(hh, "wages_cents"))
	setI64(&h.OtherIncomeCents, pget(hh, "other_income_cents"))
	setI64(&h.MagiCents, pget(hh, "magi_cents"))
	setB(&h.ActiveParticipation, pget(hh, "active_participation"))
	setB(&h.REProfessional, pget(hh, "re_professional"))
	if truthy(pget(hh, "goal")) {
		setS(&h.Goal, pget(hh, "goal"))
	}
	if h.Name == "" && truthy(pget(hh, "name")) {
		setS(&h.Name, pget(hh, "name"))
	}
	if store.Snapshot(h) != before {
		if err := store.SaveHousehold(ctx, q, h); err != nil {
			return nil, err
		}
	}
	byKey := map[string]*store.Property{}
	byNick := map[string]*store.Property{}
	for _, p := range h.Properties {
		if p.PropertyKey != nil && *p.PropertyKey != "" {
			byKey[*p.PropertyKey] = p
		}
		byNick[strings.ToLower(p.Nickname)] = p
	}
	keyToID := map[string]string{}
	var conflicts []*jsonx.Obj
	for _, po := range objList(pget(payload, "properties")) {
		key, _ := asStr(pget(po, "key"))
		nick, _ := asStr(pget(po, "nickname"))
		var p *store.Property
		if k, ok := asStr(pget(po, "key")); ok {
			p = byKey[k]
		}
		if p == nil {
			p = byNick[strings.ToLower(nick)]
		}
		isNew := p == nil
		before := ""
		if !isNew {
			// a document never renames an existing property or downgrades a confirmed value it did not carry
			po = po.Copy()
			for _, k := range []string{"nickname", "address_line1", "city", "state", "zip"} {
				po.Delete(k)
			}
			if pget(po, "current_value_cents") == nil {
				po.Delete("value_source")
			}
		}
		if isNew {
			name := nick
			if !truthy(pget(po, "nickname")) {
				if a := pget(po, "address_line1"); truthy(a) {
					name, _ = asStr(a)
				} else {
					name = key
				}
			}
			p = &store.Property{ID: store.NewID(), AdvisorID: aid, HouseholdID: h.ID, Nickname: name, PropertyType: "sfr", Units: 1,
				ValueSource: "estimated", Status: "active", Household: h}
			h.Properties = append(h.Properties, p)
			intStat(stats, "properties_created")
		} else {
			before = store.Snapshot(p)
			intStat(stats, "properties_updated")
		}
		land := pget(po, "land_pct")
		if land == nil && truthy(pget(po, "depreciable_basis_cents")) && truthy(pget(po, "purchase_price_cents")) {
			pp, _ := asInt(pget(po, "purchase_price_cents"))
			imp, _ := asInt(pget(po, "improvements_cents"))
			basis, _ := asInt(pget(po, "depreciable_basis_cents"))
			cost := pp + imp
			land = jsonx.Float(dec.PyRoundN(1-float64(basis)/float64(cost), 6))
		}
		setS(&p.Nickname, pget(po, "nickname"))
		setS(&p.AddressLine1, pget(po, "address_line1"))
		setS(&p.City, pget(po, "city"))
		setS(&p.State, pget(po, "state"))
		setS(&p.Zip, pget(po, "zip"))
		setS(&p.PropertyType, pget(po, "property_type"))
		setInt(&p.Units, pget(po, "units"))
		if d := pyDate(pget(po, "purchase_date")); d != nil {
			p.PurchaseDate = d
		}
		setI64(&p.PurchasePriceCents, pget(po, "purchase_price_cents"))
		if d := pyDate(pget(po, "placed_in_service_date")); d != nil {
			p.PlacedInServiceDate = d
		}
		if x := pyDec(land); x != nil {
			p.LandPct = roundScale6(x)
		}
		setI64(&p.ImprovementsCents, pget(po, "improvements_cents"))
		setB(&p.CostSegStudy, pget(po, "cost_seg_study"))
		setI64(&p.CurrentValueCents, pget(po, "current_value_cents"))
		setS(&p.ValueSource, pget(po, "value_source"))
		if d := pyDate(pget(po, "value_as_of")); d != nil {
			p.ValueAsOf = d
		}
		setS(&p.Status, pget(po, "status"))
		if k, ok := asStr(pget(po, "key")); ok {
			p.PropertyKey = &k
		}
		if v := pget(po, "avg_stay_days"); v != nil {
			f := toF(v)
			p.AvgStayDays = &f
		}
		if isNew {
			if err := store.InsertProperty(ctx, q, p); err != nil {
				return nil, err
			}
		} else if store.Snapshot(p) != before {
			if err := store.UpdateProperty(ctx, q, p); err != nil {
				return nil, err
			}
		}
		keyToID[key] = p.ID
		loansByPos := map[int]*store.Loan{}
		for _, ln := range p.Loans {
			loansByPos[ln.LienPosition] = ln
		}
		for _, lo := range objList(pget(po, "loans")) {
			pos := int64(1)
			if v, ok := lo.Get("lien_position"); ok {
				pos, _ = asInt(v)
			}
			ln := loansByPos[int(pos)]
			lnew := ln == nil
			lbefore := ""
			if lnew {
				bao := pyDate(pget(lo, "balance_as_of"))
				r := pyDec(pget(lo, "rate"))
				ln = &store.Loan{ID: store.NewID(), AdvisorID: aid, PropertyID: p.ID, LoanType: "fixed", TermMonths: 360, LienPosition: 1}
				if bao != nil {
					ln.BalanceAsOf = *bao
				}
				if r != nil {
					ln.Rate = *r
				}
				p.Loans = append(p.Loans, ln)
			} else {
				lbefore = store.Snapshot(ln)
			}
			ioMonths, _ := asInt(pget(lo, "io_months"))
			if ioMonths == 0 && truthy(pget(lo, "io_end_date")) {
				end, start := pyDate(pget(lo, "io_end_date")), pyDate(pget(lo, "balance_as_of"))
				ioMonths = int64(max(0, (end.Year()-start.Year())*12+int(end.Month())-int(start.Month())))
			}
			setS(&ln.Lender, pget(lo, "lender"))
			setS(&ln.LoanType, pget(lo, "loan_type"))
			setI64(&ln.OriginalCents, pget(lo, "original_cents"))
			setI64(&ln.BalanceCents, pget(lo, "balance_cents"))
			if d := pyDate(pget(lo, "balance_as_of")); d != nil {
				ln.BalanceAsOf = *d
			}
			if r := pyDec(pget(lo, "rate")); r != nil {
				ln.Rate = *roundScale6(r)
			}
			setInt(&ln.TermMonths, pget(lo, "term_months"))
			ln.IOMonths = int(ioMonths)
			if d := pyDate(pget(lo, "arm_reset_date")); d != nil {
				ln.ArmResetDate = d
			}
			if m := pyDec(pget(lo, "arm_index_margin")); m != nil {
				ln.ArmIndexMargin = roundScale6(m)
			}
			if v, ok := asInt(pget(lo, "monthly_payment_cents")); ok {
				ln.MonthlyPaymentCents = &v
			}
			if d := pyDate(pget(lo, "maturity_date")); d != nil {
				ln.MaturityDate = d
			}
			setInt(&ln.LienPosition, pget(lo, "lien_position"))
			setB(&ln.IsPaidOff, pget(lo, "is_paid_off"))
			if !truthy(pget(lo, "term_months")) && ln.MaturityDate != nil {
				ln.TermMonths = max(1, (ln.MaturityDate.Year()-ln.BalanceAsOf.Year())*12+int(ln.MaturityDate.Month())-int(ln.BalanceAsOf.Month()))
			}
			if lnew {
				if err := store.InsertLoan(ctx, q, ln); err != nil {
					return nil, err
				}
			} else if store.Snapshot(ln) != lbefore {
				if err := store.UpdateLoan(ctx, q, ln); err != nil {
					return nil, err
				}
			}
			intStat(stats, "loans")
		}
		rr := map[int]*store.RentRoll{}
		for _, r := range p.RentRolls {
			rr[r.TaxYear] = r
		}
		for _, ro := range objList(pget(po, "rent_rolls")) {
			ty, _ := asInt(pget(ro, "tax_year"))
			r := rr[int(ty)]
			if r == nil {
				r = &store.RentRoll{ID: store.NewID(), AdvisorID: aid, PropertyID: p.ID, TaxYear: int(ty)}
				p.RentRolls = append(p.RentRolls, r)
				setI64(&r.GrossRentCents, pget(ro, "gross_rent_cents"))
				setI64(&r.OtherIncomeCents, pget(ro, "other_income_cents"))
				if err := store.SaveRentRoll(ctx, q, r, true); err != nil {
					return nil, err
				}
			} else {
				b := store.Snapshot(r)
				cols := map[string]*int64{"gross_rent_cents": &r.GrossRentCents, "other_income_cents": &r.OtherIncomeCents}
				conflicts = mergeYear(h, p, r.TaxYear, ro, []string{"gross_rent_cents", "other_income_cents"}, cols, "rent roll", conflicts)
				if store.Snapshot(r) != b {
					if err := store.SaveRentRoll(ctx, q, r, false); err != nil {
						return nil, err
					}
				}
			}
			intStat(stats, "years")
		}
		ex := map[int]*store.ExpenseYear{}
		for _, e := range p.ExpenseYears {
			ex[e.TaxYear] = e
		}
		for _, eo := range objList(pget(po, "expense_years")) {
			ty, _ := asInt(pget(eo, "tax_year"))
			e := ex[int(ty)]
			if e == nil {
				e = &store.ExpenseYear{ID: store.NewID(), AdvisorID: aid, PropertyID: p.ID, TaxYear: int(ty), Cents: map[string]int64{}}
				for _, k := range store.ExpenseKeys {
					e.Cents[k] = 0
					if v, ok := asInt(pget(eo, k)); ok {
						e.Cents[k] = v
					}
				}
				p.ExpenseYears = append(p.ExpenseYears, e)
				if err := store.SaveExpenseYear(ctx, q, e, true); err != nil {
					return nil, err
				}
			} else {
				b := store.Snapshot(e)
				cols := map[string]*int64{}
				for _, k := range store.ExpenseKeys {
					v := e.Cents[k]
					cols[k] = &v
				}
				conflicts = mergeYear(h, p, e.TaxYear, eo, expenseMergeCols, cols, "expense year", conflicts)
				for k, v := range cols {
					e.Cents[k] = *v
				}
				if store.Snapshot(e) != b {
					if err := store.SaveExpenseYear(ctx, q, e, false); err != nil {
						return nil, err
					}
				}
			}
		}
		led := map[int]*store.Ledger{}
		for _, d := range p.Ledger {
			led[d.TaxYear] = d
		}
		for _, do := range objList(pget(po, "depreciation_ledger")) {
			ty, _ := asInt(pget(do, "tax_year"))
			d := led[int(ty)]
			isNew := d == nil
			b := ""
			if isNew {
				d = &store.Ledger{ID: store.NewID(), AdvisorID: aid, PropertyID: p.ID, TaxYear: int(ty), Method: "sl_27_5"}
				p.Ledger = append(p.Ledger, d)
			} else {
				b = store.Snapshot(d)
			}
			setI64(&d.AllowedCents, pget(do, "allowed_cents"))
			if v, ok := asInt(pget(do, "allowable_cents")); ok {
				d.AllowableCents = &v
			}
			setS(&d.Method, pget(do, "method"))
			setS(&d.Note, pget(do, "note"))
			if isNew || store.Snapshot(d) != b {
				if err := store.SaveLedger(ctx, q, d, isNew); err != nil {
					return nil, err
				}
			}
			intStat(stats, "ledger")
		}
	}
	sl := map[int]*store.SuspendedLoss{}
	for _, x := range h.SuspendedLosses {
		sl[x.TaxYear] = x
	}
	for _, so := range objList(pget(payload, "suspended_losses")) {
		ty, _ := asInt(pget(so, "tax_year"))
		x := sl[int(ty)]
		isNew := x == nil
		b := ""
		if isNew {
			x = &store.SuspendedLoss{ID: store.NewID(), AdvisorID: aid, HouseholdID: h.ID, TaxYear: int(ty)}
			h.SuspendedLosses = append(h.SuspendedLosses, x)
		} else {
			b = store.Snapshot(x)
		}
		x.CarryforwardCents, _ = asInt(pget(so, "carryforward_cents"))
		if isNew || store.Snapshot(x) != b {
			if err := store.SaveSuspendedLoss(ctx, q, x, isNew); err != nil {
				return nil, err
			}
		}
		intStat(stats, "suspended_losses")
	}
	docIDs, err := svc.PersistDocuments(ctx, h, objList(pget(payload, "documents")), objList(pget(payload, "extracted_fields")), stats)
	if err != nil {
		return nil, err
	}
	docs := objList(pget(payload, "documents"))
	if len(docs) == 1 { // a single upload: point the document-side candidate at it (the page viewer opens it)
		dk := pget(docs[0], "key")
		if !truthy(dk) {
			dk = pget(docs[0], "filename")
		}
		for _, c := range conflicts {
			c.MustGet("candidates").([]any)[0].(*jsonx.Obj).Set("document_key", dk)
		}
	}
	all := append(objList(pget(payload, "findings")), conflicts...)
	if _, err := svc.UpsertFindings(ctx, h, all, keyToID, docIDs, stats); err != nil {
		return nil, err
	}
	stats.Set("conflicts_raised", len(conflicts))
	keys := make([]any, len(conflicts))
	for i, c := range conflicts {
		keys[i] = c.MustGet("key")
	}
	stats.Set("conflict_keys", keys)
	return stats, nil
}

// roundScale6 mirrors Numeric(9,6): the value as it reads back from the database.
func roundScale6(x *dec.D) *dec.D {
	r := x.Quantize(6, apd.RoundHalfUp)
	return &r
}

func toF(v any) float64 {
	switch x := v.(type) {
	case jsonx.Float:
		return float64(x)
	case int64:
		return float64(x)
	case string:
		f, _ := strconv.ParseFloat(x, 64)
		return f
	}
	return 0
}

// PersistDocuments is ingest.persist_documents(s, h, docs, fields, stats).
func (svc *Service) PersistDocuments(ctx context.Context, h *store.Household, docs, fields []*jsonx.Obj, stats *jsonx.Obj) (map[string]string, error) {
	q := svc.Q(ctx)
	aid := h.AdvisorID
	bySha := map[string]*store.Document{}
	byName := map[string]*store.Document{}
	for _, d := range h.Documents {
		bySha[d.Sha256] = d
		byName[d.Filename] = d
	}
	keyToDoc := map[string]string{}
	for _, do := range docs {
		sha, _ := asStr(pget(do, "sha256"))
		if sha == "" {
			fn, _ := asStr(pget(do, "filename"))
			sum := sha256.Sum256([]byte(fn))
			sha = hex.EncodeToString(sum[:])
		}
		d := bySha[sha]
		if d == nil {
			if fn, ok := asStr(pget(do, "filename")); ok {
				d = byName[fn]
			}
		}
		isNew := d == nil
		b := ""
		if isNew {
			name, _ := asStr(pget(do, "filename"))
			if name == "" {
				name, _ = asStr(pget(do, "key"))
			}
			d = &store.Document{ID: store.NewID(), AdvisorID: aid, HouseholdID: h.ID, Kind: "other", Filename: name, Sha256: sha,
				UploadedAt: time.Now().UTC(), Status: "queued"}
			h.Documents = append(h.Documents, d)
			stats.Set("documents", statInt(stats, "documents")+1)
		} else {
			b = store.Snapshot(d)
		}
		setS(&d.Kind, pget(do, "kind"))
		if v, ok := asInt(pget(do, "tax_year")); ok {
			t := int(v)
			d.TaxYear = &t
		}
		setInt(&d.PageCount, pget(do, "page_count"))
		if s, ok := asStr(pget(do, "status")); ok && s != "" {
			d.Status = s
		} else {
			d.Status = "reconciled"
		}
		d.BytesRetained = false
		if isNew || store.Snapshot(d) != b {
			if err := store.SaveDocument(ctx, q, d, isNew); err != nil {
				return nil, err
			}
		}
		k, _ := asStr(pget(do, "key"))
		if k == "" {
			k = d.Filename
		}
		keyToDoc[k] = d.ID
		keyToDoc[d.Filename] = d.ID
	}
	var order []string
	byDoc := map[string][]*jsonx.Obj{}
	for _, fo := range fields {
		dk, _ := asStr(pget(fo, "document_key"))
		docID := keyToDoc[dk]
		if docID == "" {
			docID, _ = asStr(pget(fo, "document_id"))
		}
		if docID != "" {
			if _, ok := byDoc[docID]; !ok {
				order = append(order, docID)
			}
			byDoc[docID] = append(byDoc[docID], fo)
		}
	}
	for _, docID := range order {
		var d *store.Document
		for _, x := range h.Documents {
			if x.ID == docID {
				d = x
			}
		}
		if d == nil {
			return nil, fmt.Errorf("StopIteration: document %s not in household", docID)
		}
		var nf []*store.Field
		for _, fo := range byDoc[docID] {
			hint, _ := asStr(pget(fo, "entity_hint"))
			if hint != "household" && hint != "property" {
				hint = "property"
			}
			f := &store.Field{ID: store.NewID(), AdvisorID: aid, DocumentID: docID, EntityHint: hint, Value: pget(fo, "value"),
				Unit: "text", Page: 1, Extractor: "rules"}
			if pk, ok := asStr(pget(fo, "property_key")); ok {
				f.PropertyKey = &pk
			}
			f.Field, _ = asStr(pget(fo, "field"))
			if s, ok := asStr(pget(fo, "unit")); ok && s != "" {
				f.Unit = s
			}
			if v, ok := asInt(pget(fo, "page")); ok && v != 0 {
				f.Page = int(v)
			}
			if truthy(pget(fo, "bbox")) {
				f.BBox = pget(fo, "bbox")
			} else {
				f.BBox = []any{int64(0), int64(0), int64(0), int64(0)}
			}
			if truthy(pget(fo, "confidence")) {
				f.Confidence = toF(pget(fo, "confidence"))
			}
			if s, ok := asStr(pget(fo, "extractor")); ok && s != "" {
				f.Extractor = s
			}
			if s, ok := asStr(pget(fo, "raw_text")); ok {
				f.RawText = s
			}
			nf = append(nf, f)
			stats.Set("extracted_fields", statInt(stats, "extracted_fields")+1)
		}
		if err := store.ReplaceFields(ctx, q, d, nf); err != nil {
			return nil, err
		}
	}
	return keyToDoc, nil
}

func statInt(stats *jsonx.Obj, k string) int {
	v, _ := stats.MustGet(k).(int)
	return v
}

// UpsertFindings is ingest.upsert_findings(s, h, findings, key_to_prop, key_to_doc, stats).
func (svc *Service) UpsertFindings(ctx context.Context, h *store.Household, findings []*jsonx.Obj, keyToProp, keyToDoc map[string]string,
	stats *jsonx.Obj) ([]*store.Finding, error) {
	q := svc.Q(ctx)
	existing := map[string]*store.Finding{}
	for _, f := range h.Findings {
		if f.Key != nil && *f.Key != "" {
			existing[*f.Key] = f
		}
	}
	propByKey := map[string]string{}
	for _, p := range h.Properties {
		if p.PropertyKey != nil && *p.PropertyKey != "" {
			propByKey[*p.PropertyKey] = p.ID
		}
	}
	var out []*store.Finding
	for _, fo := range findings {
		var cands []any
		for _, c := range objList(pget(fo, "candidates")) {
			c = c.Copy()
			dk := c.Delete("document_key")
			if !c.Has("document_id") {
				if truthy(dk) {
					s, _ := asStr(dk)
					if id, ok := keyToDoc[s]; ok {
						c.Set("document_id", id)
					} else {
						c.Set("document_id", nil)
					}
				} else {
					c.Set("document_id", c.MustGet("document_id"))
				}
			}
			c.SetDefault("page", nil)
			cands = append(cands, c)
		}
		if cands == nil {
			cands = []any{}
		}
		pk, _ := asStr(pget(fo, "property_key"))
		pid := keyToProp[pk]
		if pid == "" {
			pid = propByKey[pk]
		}
		var pidp *string
		if pid != "" {
			pidp = &pid
		} else if s, ok := asStr(pget(fo, "property_id")); ok {
			pidp = &s
		}
		key, hasKey := asStr(pget(fo, "key"))
		var f *store.Finding
		if hasKey && key != "" {
			f = existing[key]
		}
		isNew := f == nil
		b := ""
		if isNew {
			kind, _ := asStr(pget(fo, "kind"))
			f = &store.Finding{ID: store.NewID(), AdvisorID: h.AdvisorID, HouseholdID: h.ID, Kind: kind, Severity: "warn", Status: "open",
				CreatedAt: time.Now().UTC()}
			if hasKey {
				k := key
				f.Key = &k
			}
			h.Findings = append(h.Findings, f)
			stats.Set("findings_created", statInt(stats, "findings_created")+1)
		} else {
			b = store.Snapshot(f)
			stats.Set("findings_updated", statInt(stats, "findings_updated")+1)
			if f.Status != "open" {
				f.Candidates = cands
				if store.Snapshot(f) != b {
					if err := store.SaveFinding(ctx, q, f, false); err != nil {
						return nil, err
					}
				}
				out = append(out, f)
				continue
			}
		}
		if pidp != nil {
			f.PropertyID = pidp
		}
		setS(&f.Kind, pget(fo, "kind"))
		if s, ok := asStr(pget(fo, "field")); ok && s != "" {
			f.Field = s
		} else {
			f.Field = ""
		}
		setS(&f.Severity, pget(fo, "severity"))
		setS(&f.Message, pget(fo, "message"))
		if v, ok := asInt(pget(fo, "tax_year")); ok {
			t := int(v)
			f.TaxYear = &t
		}
		if s, ok := asStr(pget(fo, "status")); ok && s != "" {
			f.Status = s
		} else {
			f.Status = "open"
		}
		if r := pget(fo, "resolution"); r != nil {
			f.Resolution = r
		}
		f.Candidates = cands
		if isNew || store.Snapshot(f) != b {
			if err := store.SaveFinding(ctx, q, f, isNew); err != nil {
				return nil, err
			}
		}
		out = append(out, f)
	}
	return out, nil
}

// ApplyResolution writes the advisor's chosen value back to the underlying row.
func (svc *Service) ApplyResolution(ctx context.Context, h *store.Household, f *store.Finding, value any) (*string, error) {
	if value == nil || f.PropertyID == nil {
		return nil, nil
	}
	p := store.FindProperty(h, *f.PropertyID)
	if p == nil || p.AdvisorID != f.AdvisorID {
		return nil, nil
	}
	q := svc.Q(ctx)
	key := InputKeyForField(f.Field)
	str := func(s string) *string { return &s }
	iv := func() (int64, error) {
		if i, ok := asInt(value); ok {
			return i, nil
		}
		if s, ok := value.(string); ok {
			return PyInt(s)
		}
		return 0, &InvalidInput{Msg: fmt.Sprintf("int() argument must be a string or a number, not %T", value)}
	}
	if (key == "gross_rent_cents" || key == "other_income_cents") && f.TaxYear != nil {
		year := *f.TaxYear
		var r *store.RentRoll
		for _, x := range p.RentRolls {
			if x.TaxYear == year {
				r = x
			}
		}
		isNew := r == nil
		if isNew {
			r = &store.RentRoll{ID: store.NewID(), AdvisorID: p.AdvisorID, PropertyID: p.ID, TaxYear: year}
			p.RentRolls = append(p.RentRolls, r)
		}
		v, err := iv()
		if err != nil {
			return nil, err
		}
		b := store.Snapshot(r)
		if key == "gross_rent_cents" {
			r.GrossRentCents = v
		} else {
			r.OtherIncomeCents = v
		}
		if isNew || store.Snapshot(r) != b {
			if err := store.SaveRentRoll(ctx, q, r, isNew); err != nil {
				return nil, err
			}
		}
		return str(fmt.Sprintf("rent_rolls[%d].%s", year, key)), nil
	}
	if strings.HasSuffix(key, "_cents") && key != "current_value_cents" && key != "purchase_price_cents" && f.TaxYear != nil {
		year := *f.TaxYear
		for _, e := range p.ExpenseYears {
			if e.TaxYear != year {
				continue
			}
			if _, ok := e.Cents[key]; !ok {
				break
			}
			v, err := iv()
			if err != nil {
				return nil, err
			}
			if e.Cents[key] != v {
				e.Cents[key] = v
				if err := store.SaveExpenseYear(ctx, q, e, false); err != nil {
					return nil, err
				}
			}
			return str(fmt.Sprintf("expense_years[%d].%s", year, key)), nil
		}
	}
	if key == "current_value_cents" || key == "purchase_price_cents" {
		v, err := iv()
		if err != nil {
			return nil, err
		}
		b := store.Snapshot(p)
		if key == "current_value_cents" {
			p.CurrentValueCents = v
			p.ValueSource = "confirmed"
		} else {
			p.PurchasePriceCents = v
		}
		if store.Snapshot(p) != b {
			if err := store.UpdateProperty(ctx, q, p); err != nil {
				return nil, err
			}
		}
		return str("property." + key), nil
	}
	return nil, nil
}

// Resolve is ingest.resolve(s, f, value, note, who, status).
func (svc *Service) Resolve(ctx context.Context, h *store.Household, f *store.Finding, value any, note, who, status string) error {
	var applied *string
	if status == "resolved" {
		var err error
		if applied, err = svc.ApplyResolution(ctx, h, f, value); err != nil {
			return err
		}
	}
	f.Status = status
	f.Resolution = jsonx.O("value", value, "who", who, "when", time.Now().UTC().Format("2006-01-02T15:04:05+00:00"), "note", note,
		"applied_to", applied)
	return store.SaveFinding(ctx, svc.Q(ctx), f, false)
}

func recoverInvalid(err *error) {
	if r := recover(); r != nil {
		if ii, ok := r.(*InvalidInput); ok {
			*err = ii
			return
		}
		panic(r)
	}
}

// columnField is the Schedule E line each stored column comes from (InputKeyForField maps it back on resolve).
var columnField = map[string]string{"gross_rent_cents": "schedule_e.line3.rents", "other_income_cents": "schedule_e.line4.royalties",
	"taxes_cents": "schedule_e.line16.taxes", "insurance_cents": "schedule_e.line9.insurance",
	"repairs_cents": "schedule_e.line14.repairs", "mgmt_cents": "schedule_e.line11.management_fees",
	"utilities_cents": "schedule_e.line17.utilities", "other_cents": "schedule_e.line19.other",
	"mortgage_interest_cents": "schedule_e.line12.mortgage_interest",
	"depreciation_cents":      "schedule_e.line18.depreciation", "hoa_cents": "expense_year.hoa"}

var columnLabel = map[string]string{"gross_rent_cents": "rents", "other_income_cents": "other income", "mortgage_interest_cents": "mortgage interest"}

// expenseMergeCols is the expense column order of ingest._merge_year.
var expenseMergeCols = []string{"taxes_cents", "insurance_cents", "repairs_cents", "mgmt_cents", "utilities_cents", "hoa_cents",
	"other_cents", "mortgage_interest_cents", "depreciation_cents"}

func dollars(c int64) string { return dec.Commas(dec.PyFixed(float64(c)/100, 0)) }

// mergeYear is ingest._merge_year: a document value that differs from a stored non-zero value is never written;
// it becomes a blocking conflict with both candidates. A decided (resolved/dismissed) conflict never reopens.
func mergeYear(h *store.Household, p *store.Property, year int, incoming *jsonx.Obj, cols []string, vals map[string]*int64, what string,
	conflicts []*jsonx.Obj) []*jsonx.Obj {
	decided := map[string]bool{}
	for _, f := range h.Findings {
		if f.Key != nil && *f.Key != "" && f.Status != "open" {
			decided[*f.Key] = true
		}
	}
	pk := p.ID
	if p.PropertyKey != nil && *p.PropertyKey != "" {
		pk = *p.PropertyKey
	}
	for _, col := range cols {
		nv, ok := asInt(pget(incoming, col))
		if !ok {
			continue
		}
		old := *vals[col]
		if nv == old {
			continue
		}
		short := strings.TrimSuffix(col, "_cents")
		key := fmt.Sprintf("conflict:%s:%s:%d", pk, short, year)
		if old == 0 {
			*vals[col] = nv
			continue
		}
		if decided[key] {
			continue
		}
		name, ok := columnLabel[col]
		if !ok {
			name = strings.ReplaceAll(short, "_", " ")
		}
		field, ok := columnField[col]
		if !ok {
			field = col
		}
		var pkv any
		if p.PropertyKey != nil {
			pkv = *p.PropertyKey
		}
		conflicts = append(conflicts, jsonx.O("key", key, "kind", "conflict", "field", field, "severity", "block", "tax_year", int64(year),
			"property_key", pkv, "property_id", p.ID,
			"message", fmt.Sprintf("%s %d %s disagree: the uploaded document shows $%s, the %s on file says $%s. Figures using it are "+
				"blocked until you pick one (never averaged).", p.Nickname, year, name, dollars(nv), what, dollars(old)),
			"candidates", []any{jsonx.O("source", fmt.Sprintf("uploaded document %d (%s)", year, field), "value", nv),
				jsonx.O("source", fmt.Sprintf("%s on file %d", what, year), "value", old)}))
	}
	return conflicts
}
