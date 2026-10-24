// Command gp-api is the Go twin of the FastAPI app: same /api/v1 paths, same JSON, same cents.
//
// Environment (GP_ prefix like the Python settings; DATABASE_URL also accepted):
//
//	DATABASE_URL / GP_DATABASE_URL   postgres://... (required)
//	GP_ADDR                          listen address (default :8080)
//	GP_PIPELINE_URL                  http://gp-pipeline:8090 (document uploads; unset = 503 on upload)
//	GP_CORS_ORIGINS                  comma list (default: the two twin front ends + localhost dev ports)
//	GP_EVAL_PATH                     eval-latest.json for /eval/latest
//	GP_SWEEP_ENABLED=false           disable the 14-day idle-workspace sweep
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"regexp"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/tachyurgy/groundplan/engine-go/internal/api"
	"github.com/tachyurgy/groundplan/engine-go/internal/service"
	"github.com/tachyurgy/groundplan/engine-go/internal/store"
)

var version = "dev"

func env(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

func envInt(k string, def int) int {
	if v, err := strconv.Atoi(os.Getenv(k)); err == nil {
		return v
	}
	return def
}

func main() {
	healthcheck := flag.Bool("healthcheck", false, "GET /health on GP_ADDR and exit 0/1 (for docker HEALTHCHECK in a scratch image)")
	flag.Parse()
	slog.SetDefault(slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo})).With("service", "gp-go-api", "version", version))
	addr := env("GP_ADDR", ":8080")
	if *healthcheck {
		host := addr
		if strings.HasPrefix(host, ":") {
			host = "127.0.0.1" + host
		}
		c := http.Client{Timeout: 3 * time.Second}
		resp, err := c.Get("http://" + host + "/health")
		if err != nil || resp.StatusCode != 200 {
			os.Exit(1)
		}
		os.Exit(0)
	}
	if err := run(addr); err != nil {
		slog.Error("fatal", "err", err.Error())
		os.Exit(1)
	}
}

func run(addr string) error {
	dbURL := env("DATABASE_URL", env("GP_DATABASE_URL", "postgres:///groundplan_go_test?host=/tmp"))
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	st, err := store.Open(ctx, dbURL, int32(envInt("GP_DB_MAX_CONNS", 8)))
	if err != nil {
		return fmt.Errorf("connect: %w", err)
	}
	defer st.Pool.Close()
	applied, err := st.Migrate(ctx)
	if err != nil {
		return err // refuses to start on a schema mismatch
	}
	slog.Info("schema", "alembic_head", store.HeadRevision, "applied_now", applied)
	svc := &service.Service{Store: st, Cfg: service.Config{
		MaxWorkspacesPerIPPerDay:  envInt("GP_MAX_WORKSPACES_PER_IP_PER_DAY", 30),
		MaxHouseholdsPerWorkspace: envInt("GP_MAX_HOUSEHOLDS_PER_WORKSPACE", 20),
		MaxDocumentsPerWorkspace:  envInt("GP_MAX_DOCUMENTS_PER_WORKSPACE", 50),
		WorkspaceIdleDays:         envInt("GP_WORKSPACE_IDLE_DAYS", 14),
		DevAdvisorID:              env("GP_DEV_ADVISOR_ID", "00000000-0000-4000-8000-000000000001"),
		PipelineURL:               os.Getenv("GP_PIPELINE_URL"),
	}}
	origins := []string{"https://gp-python.levelbrook.com", "https://gp-go.levelbrook.com", "http://localhost:5173",
		"http://localhost:4173", "http://127.0.0.1:5173"}
	if v := os.Getenv("GP_CORS_ORIGINS"); v != "" {
		origins = strings.Split(v, ",")
	}
	cfg := api.Config{
		Version: version, StartedAt: time.Now().UTC(), CORSOrigins: origins,
		CORSOriginRegex: regexp.MustCompile(`^` + env("GP_CORS_ORIGIN_REGEX", `https://([a-z0-9-]+\.)?gp-(python|go)\.pages\.dev`) + `$`),
		MaxBodyMB:       envInt("GP_MAX_BODY_MB", 20), MaxUploadMB: envInt("GP_MAX_UPLOAD_MB", 15),
		EvalPath:        env("GP_EVAL_PATH", "../fixtures/documents/eval-latest.json"),
		RequestTimeout:  time.Duration(envInt("GP_REQUEST_TIMEOUT_S", 30)) * time.Second,
		PipelineTimeout: time.Duration(envInt("GP_PIPELINE_TIMEOUT_S", 120)) * time.Second,
		PipelineURL:     os.Getenv("GP_PIPELINE_URL"),
	}
	srv := &http.Server{Addr: addr, Handler: api.New(svc, cfg), ReadHeaderTimeout: 10 * time.Second, ReadTimeout: 60 * time.Second,
		WriteTimeout: cfg.PipelineTimeout + 60*time.Second, IdleTimeout: 120 * time.Second, MaxHeaderBytes: 64 << 10}
	if env("GP_SWEEP_ENABLED", "true") != "false" {
		go func() {
			t := time.NewTicker(6 * time.Hour)
			defer t.Stop()
			for {
				if _, err := svc.Sweep(ctx, svc.Cfg.WorkspaceIdleDays); err != nil {
					slog.Error("workspace_sweep_failed", "err", err.Error())
				}
				select {
				case <-ctx.Done():
					return
				case <-t.C:
				}
			}
		}()
	}
	errc := make(chan error, 1)
	go func() {
		slog.Info("listening", "addr", addr, "pipeline", cfg.PipelineURL)
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			errc <- err
		}
		close(errc)
	}()
	select {
	case err := <-errc:
		return err
	case <-ctx.Done():
	}
	slog.Info("shutting_down")
	sctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	return srv.Shutdown(sctx)
}
