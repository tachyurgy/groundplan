package api

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"net/url"
	"os"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode"

	"github.com/tachyurgy/groundplan/engine-go/dec"
	"github.com/tachyurgy/groundplan/engine-go/engine/figure"
	"github.com/tachyurgy/groundplan/engine-go/engine/observations"
	"github.com/tachyurgy/groundplan/engine-go/internal/report"
	"github.com/tachyurgy/groundplan/engine-go/internal/service"
	"github.com/tachyurgy/groundplan/engine-go/internal/store"
	"github.com/tachyurgy/groundplan/engine-go/jsonx"
)

const prefix = "/api/v1"

func (s *Server) routes() {
	ws := opt{workspace: true}
	created := opt{workspace: true, status: 201}
	noContent := opt{workspace: true, status: 204}
	paths := map[string]bool{}
	reg := func(method, path string, h Handler, o opt) {
		paths[path] = true
		s.handle(method+" "+path, h, o)
	}
	p := func(x string) string { return prefix + x }

	// system (no workspace)
	reg("GET", p("/health"), s.health, opt{})
	reg("GET", "/health", s.health, opt{})
	reg("GET", p("/meta"), s.meta, opt{})
	reg("GET", p("/eval/latest"), s.evalLatest, opt{})
	reg("GET", p("/rules"), func(w http.ResponseWriter, r *http.Request) (any, error) { return observations.RuleTable(), nil }, opt{})
	// workspace
	reg("GET", p("/workspace"), s.getWorkspace, ws)
	reg("POST", p("/workspace/reset"), s.resetWorkspace, ws)
	reg("POST", p("/simulate"), s.simulate, ws)
	// households
	reg("GET", p("/households"), s.listHouseholds, ws)
	reg("POST", p("/households"), s.createHousehold, created)
	reg("GET", p("/households/{household_id}"), s.getHousehold, ws)
	reg("PATCH", p("/households/{household_id}"), s.patchHousehold, ws)
	reg("DELETE", p("/households/{household_id}"), s.deleteHousehold, noContent)
	reg("GET", p("/households/{household_id}/dashboard"), s.dashboard, ws)
	reg("GET", p("/households/{household_id}/alerts"), s.alerts, ws)
	reg("GET", p("/households/{household_id}/findings"), s.findings, ws)
	reg("POST", p("/households/{household_id}/import-reconciled"), s.importReconciled, ws)
	reg("GET", p("/households/{household_id}/report.pdf"), s.reportPDF, ws)
	// properties
	reg("POST", p("/households/{household_id}/properties"), s.createProperty, created)
	reg("GET", p("/properties/{property_id}"), s.getProperty, ws)
	reg("PATCH", p("/properties/{property_id}"), s.patchProperty, ws)
	reg("DELETE", p("/properties/{property_id}"), s.deleteProperty, noContent)
	reg("GET", p("/properties/{property_id}/analysis"), s.analysis, opt{workspace: true, invalidTitle: "Invalid assumption override"})
	reg("GET", p("/properties/{property_id}/figure/{key...}"), s.figure, opt{workspace: true, invalidTitle: "Invalid assumption override"})
	reg("GET", p("/properties/{property_id}/strategies"), s.strategies, opt{workspace: true, invalidTitle: "Invalid strategy assumption"})
	reg("POST", p("/properties/{property_id}/loans"), s.createLoan, created)
	reg("PATCH", p("/loans/{loan_id}"), s.patchLoan, ws)
	reg("DELETE", p("/loans/{loan_id}"), s.deleteLoan, noContent)
	reg("PUT", p("/properties/{property_id}/years/{tax_year}"), s.putYear, ws)
	reg("POST", p("/properties/{property_id}/scenarios"), s.createScenario, created)
	reg("GET", p("/properties/{property_id}/scenarios"), s.listScenarios, ws)
	reg("GET", p("/scenarios/{scenario_id}"), s.getScenario, ws)
	reg("GET", p("/properties/{property_id}/factsheet"), s.factsheet, ws)
	// documents & findings
	reg("POST", p("/households/{household_id}/documents"), s.uploadDocument, created)
	reg("GET", p("/households/{household_id}/documents"), s.listDocuments, ws)
	reg("GET", p("/documents/{document_id}"), s.getDocument, ws)
	reg("DELETE", p("/documents/{document_id}"), s.deleteDocument, noContent)
	reg("POST", p("/findings/{finding_id}/resolve"), s.resolveFinding, ws)
	reg("POST", p("/findings/{finding_id}/dismiss"), s.dismissFinding, ws)
	// internal engine endpoints (strangler pattern: the Python API proxies engine math here behind GP_ENGINE=go)
	for _, base := range []string{"", prefix} {
		reg("POST", base+"/engine/analyze", s.engineAnalyze, opt{invalidTitle: "Invalid engine input"})
		reg("POST", base+"/engine/strategies", s.engineStrategies, opt{invalidTitle: "Invalid engine input"})
	}
	for path := range paths {
		s.mux.HandleFunc(path, func(w http.ResponseWriter, r *http.Request) {
			writeProblem(w, r, NewProblem(405, "Method Not Allowed", ""))
		})
	}
	s.mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		writeProblem(w, r, NewProblem(404, "Not Found", ""))
	})
}

// ---------------------------------------------------------------- helpers

func (s *Server) q(r *http.Request) store.Q { return s.Svc.Q(r.Context()) }

func (s *Server) household(r *http.Request, id string) (*store.Household, error) {
	h, err := store.LoadHousehold(r.Context(), s.q(r), workspaceID(r.Context()), id)
	if errors.Is(err, store.ErrNotFound) {
		return nil, notFound("Household", id)
	}
	return h, err
}

func (s *Server) property(r *http.Request, id string) (*store.Property, error) {
	hid, err := store.PropertyHousehold(r.Context(), s.q(r), workspaceID(r.Context()), id)
	if errors.Is(err, store.ErrNotFound) {
		return nil, notFound("Property", id)
	}
	if err != nil {
		return nil, err
	}
	h, err := s.household(r, hid)
	if err != nil {
		return nil, err
	}
	if p := store.FindProperty(h, id); p != nil {
		return p, nil
	}
	return nil, notFound("Property", id)
}

// readJSON reads and decodes the body; a missing/invalid body is the FastAPI validation error.
func readJSON(r *http.Request, required bool) (any, *Problem) {
	raw, err := io.ReadAll(r.Body)
	if err != nil {
		var mbe *http.MaxBytesError
		if errors.As(err, &mbe) {
			return nil, NewProblem(413, "Request body too large", "").T("https://groundplan.dev/problems/body-too-large")
		}
		return nil, NewProblem(400, "Bad Request", err.Error())
	}
	if len(bytes.TrimSpace(raw)) == 0 {
		if required {
			return nil, validationProblem([]any{verr([]any{"body"}, "Field required", "missing")})
		}
		return nil, nil
	}
	v, err := jsonx.Decode(raw)
	if err != nil {
		return nil, validationProblem([]any{verr([]any{"body", 0}, "JSON decode error", "json_invalid")})
	}
	return v, nil
}

func body(r *http.Request, sc schema) (*parsed, error) {
	v, p := readJSON(r, true)
	if p != nil {
		return nil, p
	}
	out, errs := sc.parse(v, []any{"body"})
	if len(errs) > 0 {
		return nil, validationProblem(errs)
	}
	return out, nil
}

func queryInt(r *http.Request, name string, def int, lo, hi *int) (int, error) {
	v := r.URL.Query().Get(name)
	if !r.URL.Query().Has(name) {
		return def, nil
	}
	n, err := strconv.Atoi(strings.TrimSpace(v))
	if err != nil {
		return 0, validationProblem([]any{verr([]any{"query", name}, "Input should be a valid integer, unable to parse string as an integer", "int_parsing")})
	}
	if lo != nil && n < *lo {
		return 0, validationProblem([]any{verr([]any{"query", name}, fmt.Sprintf("Input should be greater than or equal to %d", *lo), "greater_than_equal")})
	}
	if hi != nil && n > *hi {
		return 0, validationProblem([]any{verr([]any{"query", name}, fmt.Sprintf("Input should be less than or equal to %d", *hi), "less_than_equal")})
	}
	return n, nil
}

func ip(v int) *int { return &v }

func anyList[T any](xs []T, f func(T) any) []any {
	out := make([]any, len(xs))
	for i, x := range xs {
		out[i] = f(x)
	}
	return out
}

// ---------------------------------------------------------------- system

func (s *Server) health(w http.ResponseWriter, r *http.Request) (any, error) {
	var one int
	if err := s.Svc.Store.Pool.QueryRow(r.Context(), "select 1").Scan(&one); err != nil {
		return nil, err
	}
	return jsonx.O("status", "ok", "version", s.Cfg.Version, "db", "ok", "engine", "go", "narrative_provider", "template",
		"retain_uploads_seconds", 0), nil
}

func (s *Server) meta(w http.ResponseWriter, r *http.Request) (any, error) {
	s.pgMu.Lock()
	if s.pgLabel == "" {
		var num string
		if err := s.Svc.Store.Pool.QueryRow(r.Context(), "show server_version_num").Scan(&num); err == nil {
			n, _ := strconv.Atoi(num)
			s.pgLabel = fmt.Sprintf("postgres %d", n/10000)
		}
	}
	label := s.pgLabel
	s.pgMu.Unlock()
	if label == "" {
		label = "postgres" // meta must answer even if the DB is down
	}
	return jsonx.O("backend", "go", "version", s.Cfg.Version, "engine", "go", "runtime", runtimeLabel(),
		"started_at", s.Cfg.StartedAt.UTC().Format("2006-01-02T15:04:05Z"), "db", label), nil
}

func (s *Server) evalLatest(w http.ResponseWriter, r *http.Request) (any, error) {
	raw, err := os.ReadFile(s.Cfg.EvalPath)
	if err != nil {
		return nil, NewProblem(404, "No eval yet", "run `make pipeline-eval` to produce fixtures/documents/eval-latest.json")
	}
	v, err := jsonx.Decode(raw)
	if err != nil {
		return nil, err
	}
	return v, nil
}

func (s *Server) getWorkspace(w http.ResponseWriter, r *http.Request) (any, error) {
	return s.Svc.WorkspaceSummary(r.Context(), workspaceID(r.Context()))
}

func (s *Server) resetWorkspace(w http.ResponseWriter, r *http.Request) (any, error) {
	wid := workspaceID(r.Context())
	if err := s.Svc.ResetWorkspace(r.Context(), wid); err != nil {
		return nil, err
	}
	return s.Svc.WorkspaceSummary(r.Context(), wid)
}

// ---------------------------------------------------------------- households

func (s *Server) listHouseholds(w http.ResponseWriter, r *http.Request) (any, error) {
	rows, err := store.ListHouseholds(r.Context(), s.q(r), workspaceID(r.Context()))
	if err != nil {
		return nil, err
	}
	out := []any{}
	for _, h0 := range rows {
		h, err := s.household(r, h0.ID)
		if err != nil {
			return nil, err
		}
		sm, err := s.Svc.Summary(r.Context(), h, h.AdvisorID)
		if err != nil {
			return nil, err
		}
		out = append(out, sm)
	}
	return out, nil
}

func (s *Server) createHousehold(w http.ResponseWriter, r *http.Request) (any, error) {
	wid := workspaceID(r.Context())
	b, err := body(r, householdIn)
	if err != nil {
		return nil, err
	}
	hh, _, err := s.Svc.Counts(r.Context(), wid)
	if err != nil {
		return nil, err
	}
	if cap := s.Svc.Cfg.MaxHouseholdsPerWorkspace; hh >= cap {
		return nil, NewProblem(429, "Household limit reached", fmt.Sprintf("a workspace holds at most %d households; delete one or reset "+
			"the workspace", cap)).T("https://groundplan.dev/problems/household-limit")
	}
	h := &store.Household{ID: store.NewID(), AdvisorID: wid, CreatedAt: time.Now().UTC()}
	applyHousehold(h, b, false)
	if err := store.InsertHousehold(r.Context(), s.q(r), h); err != nil {
		return nil, err
	}
	return service.HouseholdDict(h), nil
}

func applyHousehold(h *store.Household, b *parsed, onlySet bool) {
	use := func(k string) bool { return !onlySet || b.has(k) }
	if use("name") {
		h.Name = b.str("name")
	}
	if use("filing_status") {
		h.FilingStatus = b.str("filing_status")
	}
	if use("state") {
		h.State = b.str("state")
	}
	if use("tax_year_latest") {
		h.TaxYearLatest = int(b.i64("tax_year_latest"))
	}
	if use("wages_cents") {
		h.WagesCents = b.i64("wages_cents")
	}
	if use("other_income_cents") {
		h.OtherIncomeCents = b.i64("other_income_cents")
	}
	if use("magi_cents") {
		h.MagiCents = b.i64("magi_cents")
	}
	if use("active_participation") {
		h.ActiveParticipation = b.b("active_participation")
	}
	if use("re_professional") {
		h.REProfessional = b.b("re_professional")
	}
	if use("net_worth_cents") {
		h.NetWorthCents = b.i64p("net_worth_cents")
	}
	if use("goal") {
		h.Goal = b.str("goal")
	}
	if use("notes") {
		h.Notes = b.str("notes")
	}
}

func (s *Server) getHousehold(w http.ResponseWriter, r *http.Request) (any, error) {
	h, err := s.household(r, r.PathValue("household_id"))
	if err != nil {
		return nil, err
	}
	d := service.HouseholdDict(h)
	d.Set("properties", anyList(h.Properties, func(p *store.Property) any { return service.PropertyDict(p) }))
	return d, nil
}

func (s *Server) patchHousehold(w http.ResponseWriter, r *http.Request) (any, error) {
	h, err := s.household(r, r.PathValue("household_id"))
	if err != nil {
		return nil, err
	}
	b, err := body(r, householdPatch)
	if err != nil {
		return nil, err
	}
	for _, k := range []string{"name", "filing_status", "state", "tax_year_latest", "wages_cents", "other_income_cents", "magi_cents",
		"active_participation", "re_professional", "goal", "notes"} {
		if b.has(k) && b.vals[k] == nil {
			return nil, fmt.Errorf("IntegrityError: null value in column %q of relation \"households\"", k)
		}
	}
	applyHousehold(h, b, true)
	if err := store.SaveHousehold(r.Context(), s.q(r), h); err != nil {
		return nil, err
	}
	return service.HouseholdDict(h), nil
}

func (s *Server) deleteHousehold(w http.ResponseWriter, r *http.Request) (any, error) {
	h, err := s.household(r, r.PathValue("household_id"))
	if err != nil {
		return nil, err
	}
	_, err = s.q(r).Exec(r.Context(), `DELETE FROM households WHERE id = $1 AND advisor_id = $2`, h.ID, h.AdvisorID)
	return nil, err
}

func (s *Server) dashboard(w http.ResponseWriter, r *http.Request) (any, error) {
	h, err := s.household(r, r.PathValue("household_id"))
	if err != nil {
		return nil, err
	}
	d, _, err := s.Svc.Dashboard(r.Context(), h, h.AdvisorID)
	return d, err
}

func (s *Server) alerts(w http.ResponseWriter, r *http.Request) (any, error) {
	h, err := s.household(r, r.PathValue("household_id"))
	if err != nil {
		return nil, err
	}
	return s.Svc.Alerts(r.Context(), h, h.AdvisorID)
}

var statusRE = regexp.MustCompile(`^(open|resolved|dismissed)$`)

func (s *Server) findings(w http.ResponseWriter, r *http.Request) (any, error) {
	h, err := s.household(r, r.PathValue("household_id"))
	if err != nil {
		return nil, err
	}
	status := r.URL.Query().Get("status")
	if r.URL.Query().Has("status") && !statusRE.MatchString(status) {
		return nil, validationProblem([]any{verr([]any{"query", "status"}, "String should match pattern '^(open|resolved|dismissed)$'", "string_pattern_mismatch")})
	}
	rows := service.SortFindings(h, h.Findings)
	var sel []*store.Finding
	for _, f := range rows {
		if status == "" || f.Status == status {
			sel = append(sel, f)
		}
	}
	return anyList(sel, func(f *store.Finding) any { return service.FindingDict(f) }), nil
}

func (s *Server) importReconciled(w http.ResponseWriter, r *http.Request) (any, error) {
	h, err := s.household(r, r.PathValue("household_id"))
	if err != nil {
		return nil, err
	}
	v, p := readJSON(r, true)
	if p != nil {
		return nil, p
	}
	payload, ok := v.(*jsonx.Obj)
	if !ok {
		return nil, validationProblem([]any{verr([]any{"body"}, "Input should be a valid dictionary", "dict_type")})
	}
	if !payload.Has("household") || !payload.Has("properties") {
		return nil, NewProblem(422, "Not a ReconciledHousehold", "payload must carry `household` and `properties`")
	}
	var out *jsonx.Obj
	err = s.Svc.WithTx(r.Context(), func(ctx context.Context) error {
		stats, err := s.Svc.ImportReconciled(ctx, h, payload)
		if err != nil {
			return err
		}
		out = jsonx.O("household_id", h.ID, "stats", stats,
			"properties", anyList(h.Properties, func(p *store.Property) any { return service.PropertyDict(p) }),
			"findings_open", len(service.OpenFindings(h)))
		return nil
	})
	if err != nil {
		var ii *service.InvalidInput
		if errors.As(err, &ii) {
			return nil, NewProblem(422, "Invalid ReconciledHousehold", ii.Msg)
		}
		return nil, err
	}
	return out, nil
}

func (s *Server) reportPDF(w http.ResponseWriter, r *http.Request) (any, error) {
	h, err := s.household(r, r.PathValue("household_id"))
	if err != nil {
		return nil, err
	}
	dash, figs, err := s.Svc.Dashboard(r.Context(), h, h.AdvisorID)
	if err != nil {
		return nil, err
	}
	_ = figs
	var analyses []report.PropertyAnalysis
	for _, p := range h.Properties {
		if p.Status != "active" {
			continue
		}
		an, err := s.Svc.Analyze(r.Context(), p, h.AdvisorID, 0, 10, nil)
		if err != nil {
			return nil, err
		}
		analyses = append(analyses, report.PropertyAnalysis{Property: service.PropertyDict(p), Analysis: an.Out()})
	}
	var firm string
	_ = s.q(r).QueryRow(r.Context(), `SELECT firm_name FROM advisors WHERE id = $1`, h.AdvisorID).Scan(&firm)
	pdf, err := report.Render(dash, analyses, firm, time.Now())
	if err != nil {
		return nil, err
	}
	var safe strings.Builder
	for _, c := range h.Name {
		if isAlnum(c) {
			safe.WriteRune(c)
		} else {
			safe.WriteByte('-')
		}
	}
	name := strings.ToLower(strings.Trim(safe.String(), "-"))
	return rawResponse{ct: "application/pdf", body: pdf, headers: map[string]string{
		"Content-Disposition": fmt.Sprintf(`inline; filename="%s-report.pdf"`, name), "Cache-Control": "no-store"}}, nil
}

// isAlnum is str.isalnum for one character.
func isAlnum(c rune) bool { return unicode.IsLetter(c) || unicode.IsNumber(c) }

// ---------------------------------------------------------------- properties

func (s *Server) createProperty(w http.ResponseWriter, r *http.Request) (any, error) {
	h, err := s.household(r, r.PathValue("household_id"))
	if err != nil {
		return nil, err
	}
	b, err := body(r, propertyIn)
	if err != nil {
		return nil, err
	}
	p := &store.Property{ID: store.NewID(), AdvisorID: h.AdvisorID, HouseholdID: h.ID, Household: h}
	applyProperty(p, b, false)
	if err := store.InsertProperty(r.Context(), s.q(r), p); err != nil {
		return nil, err
	}
	return service.PropertyDict(p), nil
}

func rateDec(v any) *dec.D {
	f, ok := v.(float64)
	if !ok {
		return nil
	}
	d := dec.F(f) // Decimal(str(float))
	return &d
}

func applyProperty(p *store.Property, b *parsed, onlySet bool) {
	use := func(k string) bool { return !onlySet || b.has(k) }
	strs := map[string]*string{"nickname": &p.Nickname, "address_line1": &p.AddressLine1, "city": &p.City, "state": &p.State,
		"zip": &p.Zip, "property_type": &p.PropertyType, "value_source": &p.ValueSource, "status": &p.Status}
	for _, k := range b.order {
		if !use(k) {
			continue
		}
		v := b.vals[k]
		if dst, ok := strs[k]; ok {
			if s, ok := v.(string); ok {
				*dst = s
			}
			continue
		}
		switch k {
		case "units":
			p.Units = int(b.i64(k))
		case "purchase_date":
			p.PurchaseDate = b.datep(k)
		case "purchase_price_cents":
			p.PurchasePriceCents = b.i64(k)
		case "placed_in_service_date":
			p.PlacedInServiceDate = b.datep(k)
		case "land_pct":
			p.LandPct = rateDec(v)
		case "improvements_cents":
			p.ImprovementsCents = b.i64(k)
		case "cost_seg_study":
			p.CostSegStudy = b.b(k)
		case "current_value_cents":
			p.CurrentValueCents = b.i64(k)
		case "value_as_of":
			p.ValueAsOf = b.datep(k)
		case "appreciation_rate":
			p.AppreciationRate = rateDec(v)
		case "rent_growth_rate":
			p.RentGrowthRate = rateDec(v)
		case "expense_growth_rate":
			p.ExpenseGrowthRate = rateDec(v)
		case "vacancy_rate":
			p.VacancyRate = rateDec(v)
		case "mgmt_fee_rate":
			p.MgmtFeeRate = rateDec(v)
		case "capex_reserve_rate":
			p.CapexReserveRate = rateDec(v)
		case "selling_cost_rate":
			p.SellingCostRate = rateDec(v)
		case "former_residence_until":
			p.FormerResidenceUntil = b.datep(k)
		case "avg_stay_days":
			p.AvgStayDays = b.flp(k)
		}
	}
}

func (s *Server) getProperty(w http.ResponseWriter, r *http.Request) (any, error) {
	p, err := s.property(r, r.PathValue("property_id"))
	if err != nil {
		return nil, err
	}
	d := service.PropertyDict(p)
	d.Set("loans", anyList(p.Loans, func(l *store.Loan) any { return service.LoanDict(l) }))
	d.Set("years", years(p))
	return d, nil
}

func years(p *store.Property) []any {
	rr := map[int]*store.RentRoll{}
	ex := map[int]*store.ExpenseYear{}
	led := map[int]*store.Ledger{}
	set := map[int]bool{}
	for _, x := range p.RentRolls {
		rr[x.TaxYear] = x
		set[x.TaxYear] = true
	}
	for _, x := range p.ExpenseYears {
		ex[x.TaxYear] = x
		set[x.TaxYear] = true
	}
	for _, x := range p.Ledger {
		led[x.TaxYear] = x
		set[x.TaxYear] = true
	}
	var ys []int
	for y := range set {
		ys = append(ys, y)
	}
	sort.Ints(ys)
	out := []any{}
	for _, y := range ys {
		row := jsonx.O("tax_year", y)
		if r := rr[y]; r != nil {
			row.Set("gross_rent_cents", r.GrossRentCents).Set("other_income_cents", r.OtherIncomeCents)
		} else {
			row.Set("gross_rent_cents", 0).Set("other_income_cents", 0)
		}
		for _, k := range store.ExpenseKeys {
			if e := ex[y]; e != nil {
				row.Set(k, e.Cents[k])
			} else {
				row.Set(k, 0)
			}
		}
		if d := led[y]; d != nil {
			row.Set("depreciation_ledger", jsonx.O("id", d.ID, "allowed_cents", d.AllowedCents, "allowable_cents", d.AllowableCents,
				"method", d.Method, "note", d.Note))
		} else {
			row.Set("depreciation_ledger", nil)
		}
		out = append(out, row)
	}
	return out
}

func (s *Server) patchProperty(w http.ResponseWriter, r *http.Request) (any, error) {
	p, err := s.property(r, r.PathValue("property_id"))
	if err != nil {
		return nil, err
	}
	b, err := body(r, propertyPatch)
	if err != nil {
		return nil, err
	}
	applyProperty(p, b, true)
	if err := store.UpdateProperty(r.Context(), s.q(r), p); err != nil {
		return nil, err
	}
	return service.PropertyDict(p), nil
}

func (s *Server) deleteProperty(w http.ResponseWriter, r *http.Request) (any, error) {
	p, err := s.property(r, r.PathValue("property_id"))
	if err != nil {
		return nil, err
	}
	_, err = s.q(r).Exec(r.Context(), `DELETE FROM properties WHERE id = $1 AND advisor_id = $2`, p.ID, p.AdvisorID)
	return nil, err
}

func overrides(q url.Values) []service.Override {
	var out []service.Override
	for _, k := range service.AnalysisOverrides {
		if v := q.Get(k); v != "" {
			out = append(out, service.Override{K: k, V: v})
		}
	}
	return out
}

func (s *Server) analysisOf(r *http.Request) (*store.Property, *service.Analyzed, error) {
	var year int
	if r.URL.Query().Has("year") {
		y, err := queryInt(r, "year", 0, ip(1990), ip(2100))
		if err != nil {
			return nil, nil, err
		}
		year = y
	}
	horizon, err := queryInt(r, "horizon", 10, ip(1), ip(40))
	if err != nil {
		return nil, nil, err
	}
	p, err := s.property(r, r.PathValue("property_id"))
	if err != nil {
		return nil, nil, err
	}
	an, err := s.Svc.Analyze(r.Context(), p, p.AdvisorID, year, horizon, overrides(r.URL.Query()))
	if err != nil {
		return nil, nil, err
	}
	return p, an, nil
}

func (s *Server) analysis(w http.ResponseWriter, r *http.Request) (any, error) {
	p, an, err := s.analysisOf(r)
	if err != nil {
		return nil, err
	}
	out := an.Out()
	out.Set("property", service.PropertyDict(p))
	loans := map[string]*jsonx.Obj{}
	for _, l := range p.Loans {
		loans[l.ID] = service.LoanDict(l)
	}
	for _, rv := range out.MustGet("loans").([]any) {
		row := rv.(*jsonx.Obj)
		id, _ := row.MustGet("loan_id").(string)
		if l, ok := loans[id]; ok {
			row.Set("loan", l)
		} else {
			row.Set("loan", nil)
		}
	}
	var fs []any
	for _, f := range service.SortFindings(p.Household, p.Household.Findings) {
		if f.PropertyID != nil && *f.PropertyID == p.ID && f.Status == "open" {
			fs = append(fs, service.FindingDict(f))
		}
	}
	if fs == nil {
		fs = []any{}
	}
	out.Set("findings", fs)
	return out, nil
}

func (s *Server) figure(w http.ResponseWriter, r *http.Request) (any, error) {
	key := r.PathValue("key")
	depth, err := queryInt(r, "depth", 12, ip(0), ip(40))
	if err != nil {
		return nil, err
	}
	// Python declares year without bounds on this route
	if r.URL.Query().Has("year") {
		if _, err := queryInt(r, "year", 0, nil, nil); err != nil {
			return nil, err
		}
	}
	var year int
	if r.URL.Query().Has("year") {
		year, _ = queryInt(r, "year", 0, nil, nil)
	}
	horizon, err := queryInt(r, "horizon", 10, ip(1), ip(40))
	if err != nil {
		return nil, err
	}
	p, err := s.property(r, r.PathValue("property_id"))
	if err != nil {
		return nil, err
	}
	an, err := s.Svc.Analyze(r.Context(), p, p.AdvisorID, year, horizon, overrides(r.URL.Query()))
	if err != nil {
		return nil, err
	}
	figs := an.R.Figs
	fig := figs[key]
	if fig == nil {
		for _, k := range an.R.FigOrder {
			figs[k].Walk(func(x *figure.Figure) bool {
				if x.Key == key {
					fig = x
					return true
				}
				return false
			})
			if fig != nil {
				break
			}
		}
	}
	if fig == nil {
		keys := append([]string{}, an.R.FigOrder...)
		sort.Strings(keys)
		return nil, NewProblem(404, "Figure not found", fmt.Sprintf("no figure %s; known keys: %s", pyRepr(key), strings.Join(keys, ", ")))
	}
	d := fig.ToDict(depth)
	d.Set("year", an.R.Year)
	return d, nil
}

func (s *Server) strategies(w http.ResponseWriter, r *http.Request) (any, error) {
	horizon, err := queryInt(r, "horizon", 10, ip(1), ip(40))
	if err != nil {
		return nil, err
	}
	p, err := s.property(r, r.PathValue("property_id"))
	if err != nil {
		return nil, err
	}
	params := map[string]string{}
	for _, k := range service.StrategyOverrides {
		if r.URL.Query().Has(k) {
			params[k] = r.URL.Query().Get(k)
		}
	}
	return s.Svc.Strategies(r.Context(), p, p.AdvisorID, horizon, params)
}

func (s *Server) createLoan(w http.ResponseWriter, r *http.Request) (any, error) {
	p, err := s.property(r, r.PathValue("property_id"))
	if err != nil {
		return nil, err
	}
	b, err := body(r, loanIn)
	if err != nil {
		return nil, err
	}
	l := &store.Loan{ID: store.NewID(), AdvisorID: p.AdvisorID, PropertyID: p.ID}
	applyLoan(l, b, false)
	if err := store.InsertLoan(r.Context(), s.q(r), l); err != nil {
		return nil, err
	}
	return service.LoanDict(l), nil
}

func applyLoan(l *store.Loan, b *parsed, onlySet bool) {
	use := func(k string) bool { return !onlySet || b.has(k) }
	for _, k := range b.order {
		if !use(k) {
			continue
		}
		v := b.vals[k]
		switch k {
		case "lender":
			l.Lender = b.str(k)
		case "loan_type":
			l.LoanType = b.str(k)
		case "original_cents":
			l.OriginalCents = b.i64(k)
		case "balance_cents":
			l.BalanceCents = b.i64(k)
		case "balance_as_of":
			if d := b.datep(k); d != nil {
				l.BalanceAsOf = *d
			}
		case "rate":
			if d := rateDec(v); d != nil {
				l.Rate = *d
			}
		case "term_months":
			l.TermMonths = int(b.i64(k))
		case "io_months":
			l.IOMonths = int(b.i64(k))
		case "arm_reset_date":
			l.ArmResetDate = b.datep(k)
		case "arm_index_margin":
			l.ArmIndexMargin = rateDec(v)
		case "monthly_payment_cents":
			l.MonthlyPaymentCents = b.i64p(k)
		case "maturity_date":
			l.MaturityDate = b.datep(k)
		case "lien_position":
			l.LienPosition = int(b.i64(k))
		case "is_paid_off":
			l.IsPaidOff = b.b(k)
		}
	}
}

func (s *Server) loan(r *http.Request, id string) (*store.Loan, error) {
	pid, err := store.LoanProperty(r.Context(), s.q(r), workspaceID(r.Context()), id)
	if errors.Is(err, store.ErrNotFound) {
		return nil, notFound("Loan", id)
	}
	if err != nil {
		return nil, err
	}
	p, err := s.property(r, pid)
	if err != nil {
		return nil, err
	}
	for _, l := range p.Loans {
		if l.ID == id {
			return l, nil
		}
	}
	return nil, notFound("Loan", id)
}

func (s *Server) patchLoan(w http.ResponseWriter, r *http.Request) (any, error) {
	l, err := s.loan(r, r.PathValue("loan_id"))
	if err != nil {
		return nil, err
	}
	b, err := body(r, loanPatch)
	if err != nil {
		return nil, err
	}
	applyLoan(l, b, true)
	if err := store.UpdateLoan(r.Context(), s.q(r), l); err != nil {
		return nil, err
	}
	return service.LoanDict(l), nil
}

func (s *Server) deleteLoan(w http.ResponseWriter, r *http.Request) (any, error) {
	l, err := s.loan(r, r.PathValue("loan_id"))
	if err != nil {
		return nil, err
	}
	_, err = s.q(r).Exec(r.Context(), `DELETE FROM loans WHERE id = $1 AND advisor_id = $2`, l.ID, l.AdvisorID)
	return nil, err
}

func (s *Server) putYear(w http.ResponseWriter, r *http.Request) (any, error) {
	ty, err := strconv.Atoi(r.PathValue("tax_year"))
	if err != nil {
		return nil, validationProblem([]any{verr([]any{"path", "tax_year"}, "Input should be a valid integer, unable to parse string as an integer", "int_parsing")})
	}
	p, err := s.property(r, r.PathValue("property_id"))
	if err != nil {
		return nil, err
	}
	b, err := body(r, yearIn)
	if err != nil {
		return nil, err
	}
	ctx := r.Context()
	err = s.Svc.WithTx(ctx, func(ctx context.Context) error {
		q := s.Svc.Q(ctx)
		var rr *store.RentRoll
		for _, x := range p.RentRolls {
			if x.TaxYear == ty {
				rr = x
			}
		}
		newRR := rr == nil
		if newRR {
			rr = &store.RentRoll{ID: store.NewID(), AdvisorID: p.AdvisorID, PropertyID: p.ID, TaxYear: ty}
			p.RentRolls = append(p.RentRolls, rr)
		}
		before := store.Snapshot(rr)
		rr.GrossRentCents, rr.OtherIncomeCents = b.i64("gross_rent_cents"), b.i64("other_income_cents")
		if newRR || store.Snapshot(rr) != before {
			if err := store.SaveRentRoll(ctx, q, rr, newRR); err != nil {
				return err
			}
		}
		var e *store.ExpenseYear
		for _, x := range p.ExpenseYears {
			if x.TaxYear == ty {
				e = x
			}
		}
		newE := e == nil
		if newE {
			e = &store.ExpenseYear{ID: store.NewID(), AdvisorID: p.AdvisorID, PropertyID: p.ID, TaxYear: ty, Cents: map[string]int64{}}
			p.ExpenseYears = append(p.ExpenseYears, e)
		}
		before = store.Snapshot(e)
		for _, k := range store.ExpenseKeys {
			e.Cents[k] = b.i64(k)
		}
		if newE || store.Snapshot(e) != before {
			if err := store.SaveExpenseYear(ctx, q, e, newE); err != nil {
				return err
			}
		}
		if led, ok := b.vals["depreciation"].(*jsonx.Obj); ok && led != nil {
			var d *store.Ledger
			for _, x := range p.Ledger {
				if x.TaxYear == ty {
					d = x
				}
			}
			newD := d == nil
			if newD {
				d = &store.Ledger{ID: store.NewID(), AdvisorID: p.AdvisorID, PropertyID: p.ID, TaxYear: ty, Method: "sl_27_5"}
				p.Ledger = append(p.Ledger, d)
			}
			before = store.Snapshot(d)
			if v, ok := led.Get("allowed_cents"); ok {
				n, ok := toInt64(v)
				if !ok {
					return fmt.Errorf("allowed_cents: not an integer")
				}
				d.AllowedCents = n
			}
			if v, ok := led.Get("allowable_cents"); ok {
				if v == nil {
					d.AllowableCents = nil
				} else if n, ok := toInt64(v); ok {
					d.AllowableCents = &n
				}
			}
			if v, ok := led.Get("method"); ok {
				d.Method, _ = v.(string)
			}
			if v, ok := led.Get("note"); ok {
				d.Note, _ = v.(string)
			}
			if newD || store.Snapshot(d) != before {
				if err := store.SaveLedger(ctx, q, d, newD); err != nil {
					return err
				}
			}
			sort.SliceStable(p.Ledger, func(i, j int) bool { return p.Ledger[i].TaxYear < p.Ledger[j].TaxYear })
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	for _, y := range years(p) {
		if y.(*jsonx.Obj).MustGet("tax_year") == ty {
			return y, nil
		}
	}
	return nil, fmt.Errorf("year %d vanished", ty)
}

func toInt64(v any) (int64, bool) {
	switch x := v.(type) {
	case int64:
		return x, true
	case jsonx.Float:
		return int64(x), true
	}
	return 0, false
}

func (s *Server) createScenario(w http.ResponseWriter, r *http.Request) (any, error) {
	p, err := s.property(r, r.PathValue("property_id"))
	if err != nil {
		return nil, err
	}
	b, err := body(r, scenarioIn)
	if err != nil {
		return nil, err
	}
	assum, _ := b.vals["assumptions"].(*jsonx.Obj)
	if assum == nil {
		assum = jsonx.O()
	}
	params := map[string]string{}
	allowed := map[string]bool{}
	for _, k := range service.StrategyOverrides {
		allowed[k] = true
	}
	for _, kv := range assum.Pairs() {
		if allowed[kv.K] {
			params[kv.K] = pyStr(kv.V)
		}
	}
	if ex, ok := assum.MustGet("exchange").(*jsonx.Obj); ok && ex != nil {
		for _, kv := range ex.Pairs() {
			if allowed[kv.K] {
				params[kv.K] = pyStr(kv.V)
			}
		}
	}
	horizon := int(b.i64("horizon_years"))
	results, err := s.Svc.Strategies(r.Context(), p, p.AdvisorID, horizon, params)
	if err != nil {
		return nil, err
	}
	sc := &store.Scenario{ID: store.NewID(), AdvisorID: p.AdvisorID, PropertyID: p.ID, Name: b.str("name"), HorizonYears: horizon,
		Assumptions: assum, Results: results, CreatedAt: time.Now().UTC()}
	if _, err := s.q(r).Exec(r.Context(), `INSERT INTO scenarios (id, advisor_id, property_id, name, horizon_years, assumptions, results, created_at)
		VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb,$8)`, sc.ID, sc.AdvisorID, sc.PropertyID, sc.Name, sc.HorizonYears,
		string(jsonx.MustMarshal(assum)), string(jsonx.MustMarshal(results)), sc.CreatedAt); err != nil {
		return nil, err
	}
	return s.scenarioDict(sc, true), nil
}

// pyStr renders a JSON value the way Python's str() does for the strategy param parser (str(v) of the dumped value).
func pyStr(v any) string {
	switch x := v.(type) {
	case string:
		return x
	case int64:
		return strconv.FormatInt(x, 10)
	case jsonx.Float:
		return dec.PyFloatRepr(float64(x))
	case bool:
		if x {
			return "True"
		}
		return "False"
	case nil:
		return ""
	}
	return string(jsonx.MustMarshal(v))
}

func (s *Server) scenarioDict(sc *store.Scenario, results bool) *jsonx.Obj {
	var res any
	if results {
		res = sc.Results
	}
	return jsonx.O("id", sc.ID, "property_id", sc.PropertyID, "name", sc.Name, "horizon_years", sc.HorizonYears,
		"assumptions", sc.Assumptions, "results", res, "created_at", s.Svc.PyISO(sc.CreatedAt))
}

func (s *Server) listScenarios(w http.ResponseWriter, r *http.Request) (any, error) {
	p, err := s.property(r, r.PathValue("property_id"))
	if err != nil {
		return nil, err
	}
	return anyList(p.Scenarios, func(sc *store.Scenario) any { return s.scenarioDict(sc, false) }), nil
}

func (s *Server) getScenario(w http.ResponseWriter, r *http.Request) (any, error) {
	id := r.PathValue("scenario_id")
	sc, err := store.ScenarioByID(r.Context(), s.q(r), workspaceID(r.Context()), id)
	if errors.Is(err, store.ErrNotFound) {
		return nil, notFound("Scenario", id)
	}
	if err != nil {
		return nil, err
	}
	return s.scenarioDict(sc, true), nil
}

var formatRE = regexp.MustCompile(`^(emoney|rightcapital|mgp|json|csv)$`)

func (s *Server) factsheet(w http.ResponseWriter, r *http.Request) (any, error) {
	format := "json"
	if r.URL.Query().Has("format") {
		format = r.URL.Query().Get("format")
		if !formatRE.MatchString(format) {
			return nil, validationProblem([]any{verr([]any{"query", "format"}, "String should match pattern '^(emoney|rightcapital|mgp|json|csv)$'", "string_pattern_mismatch")})
		}
	}
	p, err := s.property(r, r.PathValue("property_id"))
	if err != nil {
		return nil, err
	}
	an, err := s.Svc.Analyze(r.Context(), p, p.AdvisorID, 0, 1, nil)
	if err != nil {
		return nil, err
	}
	var loans []*jsonx.Obj
	for _, l := range p.Loans {
		loans = append(loans, service.LoanDict(l))
	}
	sheet := service.Factsheet(service.PropertyDict(p), an.Out(), loans, format)
	if format == "csv" {
		name := strings.ToLower(strings.ReplaceAll(p.Nickname, " ", "-"))
		return rawResponse{ct: "text/csv; charset=utf-8", body: []byte(service.FactsheetCSV(sheet)),
			headers: map[string]string{"Content-Disposition": fmt.Sprintf(`attachment; filename="%s-factsheet.csv"`, name)}}, nil
	}
	return sheet, nil
}

// ---------------------------------------------------------------- documents & findings

func (s *Server) uploadDocument(w http.ResponseWriter, r *http.Request) (any, error) {
	h, err := s.household(r, r.PathValue("household_id"))
	if err != nil {
		return nil, err
	}
	_, docs, err := s.Svc.Counts(r.Context(), h.AdvisorID)
	if err != nil {
		return nil, err
	}
	if cap := s.Svc.Cfg.MaxDocumentsPerWorkspace; docs >= cap {
		return nil, NewProblem(429, "Document limit reached", fmt.Sprintf("a workspace holds at most %d documents; delete some or reset the "+
			"workspace", cap)).T("https://groundplan.dev/problems/document-limit")
	}
	mr, err := r.MultipartReader()
	if err != nil {
		return nil, validationProblem([]any{verr([]any{"body", "file"}, "Field required", "missing")})
	}
	limit := int64(s.Cfg.MaxUploadMB) * 1024 * 1024
	var data []byte
	filename := ""
	found := false
	for {
		part, err := mr.NextPart()
		if err == io.EOF {
			break
		}
		if err != nil {
			var mbe *http.MaxBytesError
			if errors.As(err, &mbe) {
				return nil, NewProblem(413, "Request body too large", "").T("https://groundplan.dev/problems/body-too-large")
			}
			return nil, validationProblem([]any{verr([]any{"body", "file"}, "Field required", "missing")})
		}
		if part.FormName() != "file" || found {
			_, _ = io.Copy(io.Discard, part)
			continue
		}
		found = true
		filename = part.FileName()
		data, err = io.ReadAll(io.LimitReader(part, limit+1))
		if err != nil {
			var mbe *http.MaxBytesError
			if errors.As(err, &mbe) {
				return nil, NewProblem(413, "Request body too large", "").T("https://groundplan.dev/problems/body-too-large")
			}
			return nil, err
		}
	}
	if !found {
		return nil, validationProblem([]any{verr([]any{"body", "file"}, "Field required", "missing")})
	}
	if int64(len(data)) > limit {
		return nil, NewProblem(413, "Upload too large", fmt.Sprintf("max %d MB", s.Cfg.MaxUploadMB)).T("https://groundplan.dev/problems/upload-too-large")
	}
	sum := sha256.Sum256(data)
	sha := hex.EncodeToString(sum[:])
	if filename == "" {
		filename = "upload.pdf"
	}
	if s.Cfg.PipelineURL == "" {
		size := len(data)
		data = nil
		return nil, NewProblem(503, "Document pipeline unavailable", "Upload accepted and hashed, but GP_PIPELINE_URL is not set. Set GP_PIPELINE_URL to the "+
			"gp-pipeline service.").T("https://groundplan.dev/problems/pipeline-not-installed").With("sha256", sha).With("filename", filename).
			With("size_bytes", size).With("bytes_retained", false)
	}
	var keys []any
	for _, p := range h.Properties {
		if p.PropertyKey != nil && *p.PropertyKey != "" {
			keys = append(keys, *p.PropertyKey)
		}
	}
	if keys == nil {
		keys = []any{}
	}
	hint := jsonx.O("household_id", h.ID, "state", h.State, "tax_year_latest", h.TaxYearLatest, "property_keys", keys)
	result, perr := s.callPipeline(r.Context(), data, filename, hint)
	data = nil // nothing is retained: the bytes only ever lived in this request's memory
	if perr != nil {
		return nil, perr.With("sha256", sha).With("filename", filename)
	}
	docOut := jsonx.O()
	if d, ok := result.MustGet("document").(*jsonx.Obj); ok && d != nil {
		docOut = d.Copy()
	}
	docOut.Set("sha256", sha)
	if fn, _ := docOut.MustGet("filename").(string); fn == "" {
		docOut.Set("filename", filename)
	}
	var findings []*store.Finding
	var doc *store.Document
	imp := jsonx.O()
	err = s.Svc.WithTx(r.Context(), func(ctx context.Context) error {
		stats := jsonx.O()
		if rec, ok := result.MustGet("reconciled").(*jsonx.Obj); ok && rec != nil && rec.Len() > 0 {
			st, err := s.Svc.ImportReconciled(ctx, h, rec)
			if err != nil {
				return err
			}
			imp = st
		}
		keymap, err := s.Svc.PersistDocuments(ctx, h, []*jsonx.Obj{docOut}, objList(result.MustGet("extracted_fields")), stats)
		if err != nil {
			return err
		}
		findings, err = s.Svc.UpsertFindings(ctx, h, objList(result.MustGet("findings")), map[string]string{}, keymap, stats)
		if err != nil {
			return err
		}
		// conflicts the import raised are part of this upload's findings too
		raised := map[string]bool{}
		if ks, ok := imp.MustGet("conflict_keys").([]any); ok {
			for _, k := range ks {
				raised[k.(string)] = true
			}
		}
		have := map[*store.Finding]bool{}
		for _, f := range findings {
			have[f] = true
		}
		for _, f := range h.Findings {
			if f.Key != nil && raised[*f.Key] && !have[f] {
				findings = append(findings, f)
				have[f] = true
			}
		}
		for _, d := range h.Documents {
			if d.Sha256 == sha {
				doc = d
				break
			}
		}
		return nil
	})
	if err != nil {
		var ii *service.InvalidInput
		if errors.As(err, &ii) {
			return nil, NewProblem(422, "Document rejected", ii.Msg).T("https://groundplan.dev/problems/document-rejected").
				With("sha256", sha).With("filename", filename)
		}
		return nil, err
	}
	if doc == nil {
		return nil, fmt.Errorf("StopIteration: uploaded document not persisted")
	}
	keySet := map[string]bool{}
	for _, f := range doc.Fields {
		if f.PropertyKey != nil {
			keySet[*f.PropertyKey] = true
		}
	}
	// properties_touched in property order (nickname, then property key) so both stacks list them identically
	var tp []*store.Property
	for _, p := range h.Properties {
		if p.PropertyKey != nil && keySet[*p.PropertyKey] {
			tp = append(tp, p)
		}
	}
	sort.SliceStable(tp, func(i, j int) bool {
		if tp[i].Nickname != tp[j].Nickname {
			return tp[i].Nickname < tp[j].Nickname
		}
		return *tp[i].PropertyKey < *tp[j].PropertyKey
	})
	touchedAny := anyList(tp, func(p *store.Property) any { return p.ID })
	impN := func(k string) any {
		if v, ok := imp.MustGet(k).(int); ok {
			return v
		}
		return 0
	}
	importOut := jsonx.O("properties_created", impN("properties_created"), "properties_updated", impN("properties_updated"),
		"conflicts_raised", impN("conflicts_raised"))
	return jsonx.O("document", s.Svc.DocumentDict(doc), "extracted_fields", anyList(doc.Fields, func(f *store.Field) any { return service.FieldDict(f) }),
		"findings", anyList(service.SortFindings(h, findings), func(f *store.Finding) any { return service.FindingDict(f) }), "properties_touched", touchedAny,
		"import", importOut), nil
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

// callPipeline POSTs the bytes to {GP_PIPELINE_URL}/extract over the private docker network (multipart `file`,
// form `household_hint`). 4xx = rejected (422, or 413), unreachable / 5xx = 503, like pipeline_adapter._remote.
func (s *Server) callPipeline(ctx context.Context, data []byte, filename string, hint *jsonx.Obj) (*jsonx.Obj, *Problem) {
	var buf bytes.Buffer
	mw := multipart.NewWriter(&buf)
	h := make(map[string][]string)
	h["Content-Disposition"] = []string{fmt.Sprintf(`form-data; name="file"; filename="%s"`, strings.ReplaceAll(filename, `"`, `\"`))}
	h["Content-Type"] = []string{"application/pdf"}
	pw, _ := mw.CreatePart(h)
	_, _ = pw.Write(data)
	_ = mw.WriteField("household_hint", string(jsonx.MustMarshal(hint)))
	_ = mw.Close()
	url := strings.TrimRight(s.Cfg.PipelineURL, "/") + "/extract"
	cctx, cancel := context.WithTimeout(ctx, s.Cfg.PipelineTimeout)
	defer cancel()
	req, _ := http.NewRequestWithContext(cctx, http.MethodPost, url, &buf)
	req.Header.Set("Content-Type", mw.FormDataContentType())
	resp, err := http.DefaultClient.Do(req)
	buf.Reset()
	if err != nil {
		return nil, NewProblem(503, "Document pipeline unavailable", fmt.Sprintf("the pipeline service at %s is unreachable (%T)", s.Cfg.PipelineURL, err)).
			T("https://groundplan.dev/problems/pipeline-not-installed").With("bytes_retained", false)
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 64<<20))
	if resp.StatusCode >= 400 && resp.StatusCode < 500 {
		detail := string(raw)
		if v, err := jsonx.Decode(raw); err == nil {
			if o, ok := v.(*jsonx.Obj); ok {
				if d, ok := o.Get("detail"); ok {
					detail = pyStr(d)
				}
			}
		}
		status := 422
		if resp.StatusCode == 413 {
			status = 413
		}
		return nil, NewProblem(status, "Document rejected", detail).T("https://groundplan.dev/problems/document-rejected")
	}
	if resp.StatusCode >= 500 {
		return nil, NewProblem(503, "Document pipeline unavailable", fmt.Sprintf("the pipeline service returned %d", resp.StatusCode)).
			T("https://groundplan.dev/problems/pipeline-not-installed").With("bytes_retained", false)
	}
	v, err := jsonx.Decode(raw)
	o, ok := v.(*jsonx.Obj)
	if err != nil || !ok {
		return nil, NewProblem(503, "Document pipeline unavailable", "the pipeline service returned invalid JSON").
			T("https://groundplan.dev/problems/pipeline-not-installed").With("bytes_retained", false)
	}
	return o, nil
}

func (s *Server) listDocuments(w http.ResponseWriter, r *http.Request) (any, error) {
	h, err := s.household(r, r.PathValue("household_id"))
	if err != nil {
		return nil, err
	}
	docs := append([]*store.Document{}, h.Documents...)
	sort.SliceStable(docs, func(i, j int) bool {
		a, b := docs[i], docs[j]
		if (a.TaxYear == nil) != (b.TaxYear == nil) {
			return b.TaxYear == nil // NULLS LAST, like Postgres ORDER BY tax_year
		}
		if a.TaxYear != nil && *a.TaxYear != *b.TaxYear {
			return *a.TaxYear < *b.TaxYear
		}
		return a.Filename < b.Filename
	})
	return anyList(docs, func(d *store.Document) any {
		return s.Svc.DocumentDict(d).Set("field_count", len(d.Fields))
	}), nil
}

func (s *Server) document(r *http.Request, id string) (*store.Household, *store.Document, error) {
	hid, err := store.DocumentHousehold(r.Context(), s.q(r), workspaceID(r.Context()), id)
	if errors.Is(err, store.ErrNotFound) {
		return nil, nil, notFound("Document", id)
	}
	if err != nil {
		return nil, nil, err
	}
	h, err := s.household(r, hid)
	if err != nil {
		return nil, nil, err
	}
	for _, d := range h.Documents {
		if d.ID == id {
			return h, d, nil
		}
	}
	return nil, nil, notFound("Document", id)
}

func (s *Server) getDocument(w http.ResponseWriter, r *http.Request) (any, error) {
	_, d, err := s.document(r, r.PathValue("document_id"))
	if err != nil {
		return nil, err
	}
	fields := append([]*store.Field{}, d.Fields...)
	sort.SliceStable(fields, func(i, j int) bool {
		if fields[i].Page != fields[j].Page {
			return fields[i].Page < fields[j].Page
		}
		return fields[i].Field < fields[j].Field
	})
	return jsonx.O("document", s.Svc.DocumentDict(d), "fields", anyList(fields, func(f *store.Field) any { return service.FieldDict(f) })), nil
}

func (s *Server) deleteDocument(w http.ResponseWriter, r *http.Request) (any, error) {
	_, d, err := s.document(r, r.PathValue("document_id"))
	if err != nil {
		return nil, err
	}
	_, err = s.q(r).Exec(r.Context(), `DELETE FROM documents WHERE id = $1 AND advisor_id = $2`, d.ID, d.AdvisorID)
	return nil, err
}

func (s *Server) finding(r *http.Request, id string) (*store.Household, *store.Finding, error) {
	hid, err := store.FindingHousehold(r.Context(), s.q(r), workspaceID(r.Context()), id)
	if errors.Is(err, store.ErrNotFound) {
		return nil, nil, notFound("Finding", id)
	}
	if err != nil {
		return nil, nil, err
	}
	h, err := s.household(r, hid)
	if err != nil {
		return nil, nil, err
	}
	for _, f := range h.Findings {
		if f.ID == id {
			return h, f, nil
		}
	}
	return nil, nil, notFound("Finding", id)
}

func (s *Server) resolveFinding(w http.ResponseWriter, r *http.Request) (any, error) {
	h, f, err := s.finding(r, r.PathValue("finding_id"))
	if err != nil {
		return nil, err
	}
	b, err := body(r, resolveIn)
	if err != nil {
		return nil, err
	}
	err = s.Svc.WithTx(r.Context(), func(ctx context.Context) error {
		return s.Svc.Resolve(ctx, h, f, b.vals["value"], b.str("note"), b.str("who"), "resolved")
	})
	if err != nil {
		var ii *service.InvalidInput
		if errors.As(err, &ii) {
			return nil, NewProblem(422, "Invalid resolution value", ii.Msg)
		}
		return nil, err
	}
	return service.FindingDict(f), nil
}

func (s *Server) dismissFinding(w http.ResponseWriter, r *http.Request) (any, error) {
	h, f, err := s.finding(r, r.PathValue("finding_id"))
	if err != nil {
		return nil, err
	}
	v, p := readJSON(r, false)
	if p != nil {
		return nil, p
	}
	note, who := "", "advisor"
	if v != nil {
		b, errs := dismissIn.parse(v, []any{"body"})
		if len(errs) > 0 {
			return nil, validationProblem(errs)
		}
		note, who = b.str("note"), b.str("who")
	}
	if err := s.Svc.WithTx(r.Context(), func(ctx context.Context) error {
		return s.Svc.Resolve(ctx, h, f, nil, note, who, "dismissed")
	}); err != nil {
		return nil, err
	}
	return service.FindingDict(f), nil
}
