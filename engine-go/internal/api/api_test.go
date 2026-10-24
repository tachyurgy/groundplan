package api

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/tachyurgy/groundplan/engine-go/internal/service"
	"github.com/tachyurgy/groundplan/engine-go/internal/store"
)

// Handler tests that need no database: routing, problem+json shape, workspace header validation.

func bareServer() *Server {
	return New(&service.Service{}, Config{MaxBodyMB: 20, MaxUploadMB: 15, RequestTimeout: 5 * time.Second, PipelineTimeout: time.Second,
		CORSOrigins: []string{"https://gp-go.levelbrook.com"}})
}

func do(t *testing.T, h http.Handler, method, path, ws string, body string) (*http.Response, map[string]any) {
	t.Helper()
	req := httptest.NewRequest(method, path, strings.NewReader(body))
	if ws != "" {
		req.Header.Set("X-Workspace-Id", ws)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Forwarded-For", "203.0.113.9")
	rr := httptest.NewRecorder()
	h.ServeHTTP(rr, req)
	res := rr.Result()
	raw, _ := io.ReadAll(res.Body)
	var out map[string]any
	_ = json.Unmarshal(raw, &out)
	return res, out
}

func TestProblemShapes(t *testing.T) {
	s := bareServer()
	res, body := do(t, s, "GET", "/api/v1/households", "", "")
	if res.StatusCode != 400 || res.Header.Get("Content-Type") != ProblemCT {
		t.Fatalf("missing workspace: %d %s", res.StatusCode, res.Header.Get("Content-Type"))
	}
	want := map[string]any{"type": "https://groundplan.dev/problems/workspace-required", "title": "Missing workspace", "status": 400.0,
		"instance": "/api/v1/households", "detail": "send a random UUIDv4 as the X-Workspace-Id header"}
	for k, v := range want {
		if body[k] != v {
			t.Errorf("%s = %v want %v", k, body[k], v)
		}
	}
	if res, body = do(t, s, "GET", "/api/v1/households", "not-a-uuid", ""); res.StatusCode != 400 || body["title"] != "Invalid workspace" {
		t.Errorf("invalid workspace: %d %v", res.StatusCode, body)
	}
	if res, body = do(t, s, "GET", "/api/v1/nope", "", ""); res.StatusCode != 404 || body["title"] != "Not Found" {
		t.Errorf("unknown route: %d %v", res.StatusCode, body)
	}
	if res, body = do(t, s, "PUT", "/api/v1/households", "", ""); res.StatusCode != 405 || body["title"] != "Method Not Allowed" {
		t.Errorf("wrong method: %d %v", res.StatusCode, body)
	}
	req := httptest.NewRequest("POST", "/api/v1/simulate", strings.NewReader("{}"))
	req.Header.Set("Content-Length", fmt.Sprint(21*1024*1024))
	rr := httptest.NewRecorder()
	s.ServeHTTP(rr, req)
	if rr.Code != 413 {
		t.Errorf("oversize body: %d", rr.Code)
	}
}

func TestCORSPreflight(t *testing.T) {
	s := bareServer()
	req := httptest.NewRequest("OPTIONS", "/api/v1/households", nil)
	req.Header.Set("Origin", "https://gp-go.levelbrook.com")
	req.Header.Set("Access-Control-Request-Method", "GET")
	rr := httptest.NewRecorder()
	s.ServeHTTP(rr, req)
	if rr.Code != 200 || rr.Header().Get("Access-Control-Allow-Origin") != "https://gp-go.levelbrook.com" ||
		!strings.Contains(rr.Header().Get("Access-Control-Allow-Headers"), "X-Workspace-Id") {
		t.Fatalf("preflight: %d %v", rr.Code, rr.Header())
	}
	req.Header.Set("Origin", "https://evil.example")
	rr = httptest.NewRecorder()
	s.ServeHTTP(rr, req)
	if rr.Code != 400 {
		t.Fatalf("disallowed origin: %d", rr.Code)
	}
}

func TestParseWorkspaceID(t *testing.T) {
	for in, want := range map[string]string{
		"0F0E0D0C-0B0A-4908-8706-050403020100":          "0f0e0d0c-0b0a-4908-8706-050403020100",
		"{0f0e0d0c0b0a49088706050403020100}":            "0f0e0d0c-0b0a-4908-8706-050403020100",
		"urn:uuid:0f0e0d0c-0b0a-4908-8706-050403020100": "0f0e0d0c-0b0a-4908-8706-050403020100",
	} {
		got, err := service.ParseWorkspaceID(in)
		if err != nil || got != want {
			t.Errorf("%s -> %s %v", in, got, err)
		}
	}
}

// --- integration: a real local Postgres (db groundplan_go_test on the /tmp socket); skipped when unavailable ---

func integrationServer(t *testing.T) *Server {
	t.Helper()
	url := os.Getenv("GP_TEST_DATABASE_URL")
	if url == "" {
		url = "postgres:///groundplan_go_test?host=/tmp"
	}
	ctx := context.Background()
	st, err := store.Open(ctx, url, 16)
	if err == nil {
		err = st.Pool.Ping(ctx)
	}
	if err != nil {
		t.Skipf("no test database (%v)", err)
	}
	var db string
	_ = st.Pool.QueryRow(ctx, "select current_database()").Scan(&db)
	if db != "groundplan_go_test" && os.Getenv("GP_TEST_DATABASE_URL") == "" {
		t.Fatalf("refusing to reset %q", db)
	}
	if _, err := st.Pool.Exec(ctx, "DROP SCHEMA public CASCADE; CREATE SCHEMA public"); err != nil {
		t.Fatal(err)
	}
	if _, err := st.Migrate(ctx); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(st.Pool.Close)
	svc := &service.Service{Store: st, Cfg: service.Config{MaxWorkspacesPerIPPerDay: 1000, MaxHouseholdsPerWorkspace: 20,
		MaxDocumentsPerWorkspace: 50, WorkspaceIdleDays: 14, DevAdvisorID: "00000000-0000-4000-8000-000000000001"}}
	return New(svc, Config{MaxBodyMB: 20, MaxUploadMB: 15, RequestTimeout: 30 * time.Second, PipelineTimeout: time.Second})
}

func getJSON(t *testing.T, h http.Handler, method, path, ws, body string) (int, any) {
	t.Helper()
	req := httptest.NewRequest(method, path, strings.NewReader(body))
	req.Header.Set("X-Workspace-Id", ws)
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()
	h.ServeHTTP(rr, req)
	var out any
	_ = json.Unmarshal(rr.Body.Bytes(), &out)
	return rr.Code, out
}

func walkKeys(v any, fn func(string)) {
	switch x := v.(type) {
	case map[string]any:
		for k, e := range x {
			fn(k)
			walkKeys(e, fn)
		}
	case []any:
		for _, e := range x {
			walkKeys(e, fn)
		}
	}
}

func TestIntegration(t *testing.T) {
	s := integrationServer(t)
	wsA := "11111111-1111-4111-8111-111111111111"
	wsB := "22222222-2222-4222-8222-222222222222"

	t.Run("concurrent first requests provision exactly once", func(t *testing.T) {
		var wg sync.WaitGroup
		codes := make([]int, 16)
		for i := range codes {
			wg.Add(1)
			go func(i int) {
				defer wg.Done()
				codes[i], _ = getJSON(t, s, "GET", "/api/v1/households", wsA, "")
			}(i)
		}
		wg.Wait()
		for _, c := range codes {
			if c != 200 {
				t.Fatalf("codes %v", codes)
			}
		}
		_, hh := getJSON(t, s, "GET", "/api/v1/households", wsA, "")
		if n := len(hh.([]any)); n != 1 {
			t.Fatalf("%d households after concurrent provisioning", n)
		}
		var provisions int
		_ = s.Svc.Store.Pool.QueryRow(context.Background(), "select coalesce(sum(count),0) from workspace_provisions").Scan(&provisions)
		if provisions != 1 {
			t.Fatalf("provision counter %d, want 1 (losers roll back)", provisions)
		}
	})

	_, hh := getJSON(t, s, "GET", "/api/v1/households", wsA, "")
	hid := hh.([]any)[0].(map[string]any)["id"].(string)
	_, h := getJSON(t, s, "GET", "/api/v1/households/"+hid, wsA, "")
	var maple string
	var pids []string
	for _, p := range h.(map[string]any)["properties"].([]any) {
		pm := p.(map[string]any)
		pids = append(pids, pm["id"].(string))
		if pm["nickname"] == "Maple duplex" {
			maple = pm["id"].(string)
		}
	}

	t.Run("workspace isolation", func(t *testing.T) {
		_, other := getJSON(t, s, "GET", "/api/v1/households", wsB, "")
		for _, o := range other.([]any) {
			if o.(map[string]any)["id"] == hid {
				t.Fatal("workspace B sees workspace A's household")
			}
		}
		for _, u := range []string{"/households/" + hid, "/households/" + hid + "/dashboard", "/properties/" + maple,
			"/properties/" + maple + "/analysis", "/properties/" + maple + "/strategies", "/households/" + hid + "/report.pdf"} {
			if c, _ := getJSON(t, s, "GET", "/api/v1"+u, wsB, ""); c != 404 {
				t.Errorf("%s from another workspace: %d", u, c)
			}
		}
		if c, _ := getJSON(t, s, "DELETE", "/api/v1/properties/"+maple, wsB, ""); c != 404 {
			t.Errorf("cross-workspace delete: %d", c)
		}
	})

	t.Run("resolve moves the figure from blocked to confirmed", func(t *testing.T) {
		_, an := getJSON(t, s, "GET", "/api/v1/properties/"+maple+"/analysis", wsA, "")
		if st := an.(map[string]any)["cash_flow"].(map[string]any)["net_cash_flow"].(map[string]any)["status"]; st != "blocked" {
			t.Fatalf("before: %v", st)
		}
		_, fs := getJSON(t, s, "GET", "/api/v1/households/"+hid+"/findings?status=open", wsA, "")
		var fid string
		for _, f := range fs.([]any) {
			if f.(map[string]any)["severity"] == "block" {
				fid = f.(map[string]any)["id"].(string)
			}
		}
		c, r := getJSON(t, s, "POST", "/api/v1/findings/"+fid+"/resolve", wsA, `{"value": 5040000, "note": "rent roll"}`)
		if c != 200 || r.(map[string]any)["resolution"].(map[string]any)["applied_to"] != "rent_rolls[2025].gross_rent_cents" {
			t.Fatalf("resolve: %d %v", c, r)
		}
		_, an = getJSON(t, s, "GET", "/api/v1/properties/"+maple+"/analysis", wsA, "")
		cf := an.(map[string]any)["cash_flow"].(map[string]any)
		if st := cf["net_cash_flow"].(map[string]any)["status"]; st != "confirmed" {
			t.Fatalf("after: %v", st)
		}
		if v := cf["gross_rent"].(map[string]any)["value_cents"]; v != 5040000.0 {
			t.Fatalf("resolved value not written back: %v", v)
		}
	})

	t.Run("no recommended key anywhere", func(t *testing.T) {
		urls := []string{"/households", "/households/" + hid, "/households/" + hid + "/dashboard", "/households/" + hid + "/alerts",
			"/households/" + hid + "/findings", "/households/" + hid + "/documents", "/workspace", "/rules"}
		for _, p := range pids {
			urls = append(urls, "/properties/"+p, "/properties/"+p+"/analysis", "/properties/"+p+"/strategies",
				"/properties/"+p+"/strategies?dst=true&cash_taken_cents=500000&replacement_debt_cents=0",
				"/properties/"+p+"/figure/exit_tax.total", "/properties/"+p+"/factsheet?format=emoney")
		}
		for _, u := range urls {
			c, b := getJSON(t, s, "GET", "/api/v1"+u, wsA, "")
			if c != 200 {
				t.Errorf("%s: %d", u, c)
			}
			walkKeys(b, func(k string) {
				if k == "recommended" {
					t.Errorf("%s carries a recommended key", u)
				}
			})
		}
		c, b := getJSON(t, s, "POST", "/api/v1/simulate", wsA, `{"household_id": "`+hid+`", "years": 5, "monte_carlo": {"runs": 30, "appr_sigma": 0.05}}`)
		if c != 200 {
			t.Fatalf("simulate %d", c)
		}
		walkKeys(b, func(k string) {
			if k == "recommended" {
				t.Error("simulate carries a recommended key")
			}
		})
	})

	t.Run("report pdf and reset", func(t *testing.T) {
		req := httptest.NewRequest("GET", "/api/v1/households/"+hid+"/report.pdf", nil)
		req.Header.Set("X-Workspace-Id", wsA)
		rr := httptest.NewRecorder()
		s.ServeHTTP(rr, req)
		if rr.Code != 200 || rr.Header().Get("Content-Type") != "application/pdf" || !strings.HasPrefix(rr.Body.String(), "%PDF-") || rr.Body.Len() < 5000 {
			t.Fatalf("pdf: %d %s %d", rr.Code, rr.Header().Get("Content-Type"), rr.Body.Len())
		}
		c, w := getJSON(t, s, "POST", "/api/v1/workspace/reset", wsA, "")
		if c != 200 || w.(map[string]any)["households"] != 1.0 {
			t.Fatalf("reset: %d %v", c, w)
		}
	})
}
