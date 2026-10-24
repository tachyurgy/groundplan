package api

import (
	"context"
	"crypto/rand"
	"crypto/subtle"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/netip"
	"regexp"
	"runtime"
	"runtime/debug"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/tachyurgy/groundplan/engine-go/internal/service"
	"github.com/tachyurgy/groundplan/engine-go/jsonx"
)

// Config is the server configuration (env-driven, see cmd/gp-api).
type Config struct {
	Version         string
	StartedAt       time.Time
	CORSOrigins     []string
	CORSOriginRegex *regexp.Regexp
	MaxBodyMB       int
	MaxUploadMB     int
	EvalPath        string
	RequestTimeout  time.Duration
	PipelineTimeout time.Duration
	PipelineURL     string
	PagesProxyKey   string // GP_PAGES_PROXY_KEY: shared secret of the Cloudflare Pages Function proxy
}

// Server wires the services into an http.Handler.
type Server struct {
	Svc *service.Service
	Cfg Config
	mux *http.ServeMux

	pgMu    sync.Mutex
	pgLabel string
}

// New builds the server and its routes.
func New(svc *service.Service, cfg Config) *Server {
	s := &Server{Svc: svc, Cfg: cfg, mux: http.NewServeMux()}
	s.routes()
	return s
}

type ctxKey int

const (
	keyRequestID ctxKey = iota
	keyWorkspace
)

func requestID(ctx context.Context) string { v, _ := ctx.Value(keyRequestID).(string); return v }

func workspaceID(ctx context.Context) string { v, _ := ctx.Value(keyWorkspace).(string); return v }

type recorder struct {
	http.ResponseWriter
	status int
	bytes  int
}

func (r *recorder) WriteHeader(code int) { r.status = code; r.ResponseWriter.WriteHeader(code) }

func (r *recorder) Write(b []byte) (int, error) {
	if r.status == 0 {
		r.status = 200
	}
	n, err := r.ResponseWriter.Write(b)
	r.bytes += n
	return n, err
}

// ServeHTTP is the middleware chain: request id -> recover -> access log -> CORS -> body limit -> timeout -> mux.
func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	start := time.Now()
	rid := r.Header.Get("X-Request-Id")
	if rid == "" || len(rid) > 64 {
		var b [8]byte
		_, _ = rand.Read(b[:])
		rid = hex.EncodeToString(b[:])
	}
	w.Header().Set("X-Request-Id", rid)
	ctx := context.WithValue(r.Context(), keyRequestID, rid)
	r = r.WithContext(ctx)
	rec := &recorder{ResponseWriter: w}
	defer func() {
		if p := recover(); p != nil {
			if p == http.ErrAbortHandler {
				panic(p)
			}
			slog.Error("panic", "request_id", rid, "path", r.URL.Path, "panic", fmt.Sprint(p), "stack", string(debug.Stack()))
			if rec.status == 0 {
				writeProblem(rec, r, NewProblem(500, "Internal Server Error", ""))
			}
		}
		lvl := slog.LevelInfo
		if rec.status >= 500 {
			lvl = slog.LevelError
		}
		if r.URL.Path != "/health" && r.URL.Path != "/api/v1/health" || rec.status >= 400 {
			slog.Log(r.Context(), lvl, "request", "request_id", rid, "method", r.Method, "path", r.URL.Path, "status", rec.status,
				"bytes", rec.bytes, "ms", float64(time.Since(start).Microseconds())/1000, "workspace", r.Header.Get("X-Workspace-Id"))
		}
	}()
	if s.cors(rec, r) {
		return
	}
	limit := int64(s.Cfg.MaxBodyMB) * 1024 * 1024
	if cl := r.Header.Get("Content-Length"); cl != "" {
		if n, err := strconv.ParseInt(cl, 10, 64); err == nil && n > limit {
			writeProblem(rec, r, NewProblem(413, "Request body too large", fmt.Sprintf("max %d MB", s.Cfg.MaxBodyMB)).
				T("https://groundplan.dev/problems/body-too-large"))
			return
		}
	}
	r.Body = http.MaxBytesReader(rec, r.Body, limit)
	timeout := s.Cfg.RequestTimeout
	if strings.HasSuffix(r.URL.Path, "/documents") && r.Method == http.MethodPost {
		timeout = s.Cfg.PipelineTimeout + 30*time.Second
	}
	ctx, cancel := context.WithTimeout(r.Context(), timeout)
	defer cancel()
	s.mux.ServeHTTP(rec, r.WithContext(ctx))
}

// cors implements the CORSMiddleware settings of api/app.py; returns true when it answered a preflight.
func (s *Server) cors(w http.ResponseWriter, r *http.Request) bool {
	origin := r.Header.Get("Origin")
	allowed := false
	if origin != "" {
		for _, o := range s.Cfg.CORSOrigins {
			if o == origin {
				allowed = true
			}
		}
		if !allowed && s.Cfg.CORSOriginRegex != nil && s.Cfg.CORSOriginRegex.MatchString(origin) {
			allowed = true
		}
	}
	if r.Method == http.MethodOptions && r.Header.Get("Access-Control-Request-Method") != "" {
		h := w.Header()
		h.Add("Vary", "Origin")
		if !allowed {
			w.WriteHeader(400)
			_, _ = io.WriteString(w, "Disallowed CORS origin")
			return true
		}
		h.Set("Access-Control-Allow-Origin", origin)
		h.Set("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
		h.Set("Access-Control-Allow-Headers", "Content-Type, X-Workspace-Id")
		h.Set("Access-Control-Max-Age", "600")
		w.WriteHeader(200)
		_, _ = io.WriteString(w, "OK")
		return true
	}
	if allowed {
		w.Header().Set("Access-Control-Allow-Origin", origin)
		w.Header().Set("Access-Control-Expose-Headers", "Content-Disposition")
		w.Header().Add("Vary", "Origin")
	}
	return false
}

// writeJSON writes a 200/201 JSON response like Starlette's JSONResponse.
func writeJSON(w http.ResponseWriter, status int, v any) {
	b, err := jsonx.Marshal(v)
	if err != nil {
		slog.Error("encode", "err", err.Error())
		w.WriteHeader(500)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Content-Length", strconv.Itoa(len(b)))
	w.WriteHeader(status)
	_, _ = w.Write(b)
}

// Handler is a handler returning a value (written as JSON) or an error (written as problem+json).
type Handler func(w http.ResponseWriter, r *http.Request) (any, error)

type opt struct {
	status       int
	workspace    bool
	invalidTitle string
}

func (s *Server) handle(pattern string, h Handler, o opt) {
	if o.status == 0 {
		o.status = 200
	}
	s.mux.HandleFunc(pattern, func(w http.ResponseWriter, r *http.Request) {
		if o.workspace {
			wid, err := s.ensureWorkspace(r)
			if err != nil {
				writeErr(w, r, err, "")
				return
			}
			r = r.WithContext(context.WithValue(r.Context(), keyWorkspace, wid))
		}
		v, err := h(w, r)
		if err != nil {
			if errors.Is(err, context.DeadlineExceeded) {
				writeProblem(w, r, NewProblem(504, "Request timed out", ""))
				return
			}
			writeErr(w, r, err, o.invalidTitle)
			return
		}
		switch x := v.(type) {
		case nil:
			w.WriteHeader(204)
		case rawResponse:
			for k, vv := range x.headers {
				w.Header().Set(k, vv)
			}
			w.Header().Set("Content-Type", x.ct)
			w.Header().Set("Content-Length", strconv.Itoa(len(x.body)))
			w.WriteHeader(o.status)
			_, _ = w.Write(x.body)
		default:
			writeJSON(w, o.status, v)
		}
	})
}

type rawResponse struct {
	ct      string
	body    []byte
	headers map[string]string
}

func (s *Server) ensureWorkspace(r *http.Request) (string, error) {
	wid, err := service.ParseWorkspaceID(r.Header.Get("X-Workspace-Id"))
	if err != nil {
		return "", err
	}
	peer := r.RemoteAddr
	if i := strings.LastIndexByte(peer, ':'); i > 0 {
		peer = peer[:i]
	}
	peer = strings.Trim(peer, "[]")
	if _, err := s.Svc.EnsureWorkspace(r.Context(), wid, s.clientIP(r, peer)); err != nil {
		return "", err
	}
	return wid, nil
}

// runtimeLabel is "go1.26.5".
func runtimeLabel() string { return runtime.Version() }

// clientIP is the per-IP abuse key. Behind the Pages Function proxy every request carries the Worker's egress IP in
// CF-Connecting-IP, so the proxy forwards the visitor's address as X-Client-IP together with X-GP-Proxy-Key.
// X-Client-IP is trusted ONLY when the key matches GP_PAGES_PROXY_KEY (constant-time) and the value parses as an IP;
// otherwise the usual CF-Connecting-IP / X-Forwarded-For / peer order applies.
func (s *Server) clientIP(r *http.Request, peer string) string {
	if key := s.Cfg.PagesProxyKey; key != "" {
		got := r.Header.Get("X-GP-Proxy-Key")
		if got != "" && subtle.ConstantTimeCompare([]byte(got), []byte(key)) == 1 {
			if addr, err := netip.ParseAddr(strings.TrimSpace(r.Header.Get("X-Client-IP"))); err == nil {
				return addr.Unmap().String()
			}
		}
	}
	return service.ClientIP(r.Header, peer)
}
