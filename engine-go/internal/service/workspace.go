package service

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"regexp"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/tachyurgy/groundplan/engine-go/internal/store"
	"github.com/tachyurgy/groundplan/engine-go/jsonx"
)

// Port of services/workspace.py: no-login workspaces (SPEC §8.1). A workspace IS an advisor row.

// TouchEvery is how often last_seen_at is refreshed per workspace.
const TouchEvery = 5 * time.Minute

// WorkspaceError carries the problem+json fields.
type WorkspaceError struct {
	Status              int
	Title, Detail, Kind string
}

func (e *WorkspaceError) Error() string { return e.Detail }

var hexRE = regexp.MustCompile(`^[0-9a-fA-F]{32}$`)

// ParseWorkspaceID is parse_id: Python uuid.UUID accepts hex with or without hyphens/braces/urn prefix.
func ParseWorkspaceID(raw string) (string, error) {
	if raw == "" {
		return "", &WorkspaceError{400, "Missing workspace", "send a random UUIDv4 as the X-Workspace-Id header", "workspace-required"}
	}
	s := strings.TrimSpace(raw)
	s = strings.TrimPrefix(strings.TrimPrefix(s, "urn:"), "uuid:")
	s = strings.Trim(s, "{}")
	s = strings.ReplaceAll(s, "-", "")
	if !hexRE.MatchString(s) {
		return "", &WorkspaceError{400, "Invalid workspace", "X-Workspace-Id must be a UUID (e.g. crypto.randomUUID())", "workspace-invalid"}
	}
	s = strings.ToLower(s)
	return fmt.Sprintf("%s-%s-%s-%s-%s", s[0:8], s[8:12], s[12:16], s[16:20], s[20:32]), nil
}

// ClientIP is client_ip(headers, peer).
func ClientIP(h http.Header, peer string) string {
	ip := h.Get("Cf-Connecting-Ip")
	if ip == "" {
		ip = strings.TrimSpace(strings.Split(h.Get("X-Forwarded-For"), ",")[0])
	}
	if ip == "" {
		ip = peer
	}
	if ip == "" {
		ip = "unknown"
	}
	if len(ip) > 64 {
		ip = ip[:64]
	}
	return ip
}

// EnsureWorkspace provisions + seeds an unknown workspace in one transaction; concurrent first requests race on
// INSERT ... ON CONFLICT DO NOTHING and exactly one seeds.
func (svc *Service) EnsureWorkspace(ctx context.Context, wid, ip string) (created bool, err error) {
	var seen *time.Time
	err = svc.Store.Pool.QueryRow(ctx, `SELECT last_seen_at FROM advisors WHERE id = $1`, wid).Scan(&seen)
	if err == nil {
		if seen == nil || seen.Before(time.Now().Add(-TouchEvery)) {
			_, err = svc.Store.Pool.Exec(ctx, `UPDATE advisors SET last_seen_at = now() WHERE id = $1`, wid)
		}
		return false, err
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return false, err
	}
	tx, err := svc.Store.Pool.Begin(ctx)
	if err != nil {
		return false, err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var count int
	if err := tx.QueryRow(ctx, `INSERT INTO workspace_provisions (ip, day, count) VALUES ($1, (now() AT TIME ZONE 'utc')::date, 1)
		ON CONFLICT (ip, day) DO UPDATE SET count = workspace_provisions.count + 1 RETURNING count`, ip).Scan(&count); err != nil {
		return false, err
	}
	limit := svc.Cfg.MaxWorkspacesPerIPPerDay
	if count > limit {
		return false, &WorkspaceError{429, "Too many new workspaces", fmt.Sprintf("at most %d new workspaces per client IP per day; "+
			"reuse your existing workspace id or try again tomorrow", limit), "workspace-rate-limit"}
	}
	var won string
	err = tx.QueryRow(ctx, `INSERT INTO advisors (id, advisor_id, firm_name, name, email, created_at, last_seen_at, created_ip)
		VALUES ($1, $1, 'Demo workspace', 'Demo advisor', '', now(), now(), $2) ON CONFLICT (id) DO NOTHING RETURNING id`, wid, ip).Scan(&won)
	if errors.Is(err, pgx.ErrNoRows) {
		return false, nil // a concurrent first request created (and committed) it; the rollback undoes our counter bump
	}
	if err != nil {
		return false, err
	}
	if _, err := svc.Seed(context.WithValue(ctx, txKey{}, store.Q(tx)), wid); err != nil {
		return false, err
	}
	if err := tx.Commit(ctx); err != nil {
		return false, err
	}
	slog.Info("workspace_provisioned", "workspace", wid, "ip", ip)
	return true, nil
}

// Counts is (households, documents) of a workspace.
func (svc *Service) Counts(ctx context.Context, wid string) (int, int, error) {
	var hh, docs int
	err := svc.Q(ctx).QueryRow(ctx, `SELECT (SELECT count(*) FROM households WHERE advisor_id = $1), (SELECT count(*) FROM documents WHERE advisor_id = $1)`, wid).Scan(&hh, &docs)
	return hh, docs, err
}

// WorkspaceSummary is workspace.summary.
func (svc *Service) WorkspaceSummary(ctx context.Context, wid string) (*jsonx.Obj, error) {
	var created *time.Time
	err := svc.Q(ctx).QueryRow(ctx, `SELECT created_at FROM advisors WHERE id = $1`, wid).Scan(&created)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return nil, err
	}
	hh, docs, err := svc.Counts(ctx, wid)
	if err != nil {
		return nil, err
	}
	var c any
	if created != nil {
		c = svc.PyISO(*created)
	}
	return jsonx.O("id", wid, "created_at", c, "households", hh, "documents", docs), nil
}

// ResetWorkspace deletes everything the workspace owns and re-seeds the demo household (one transaction).
func (svc *Service) ResetWorkspace(ctx context.Context, wid string) error {
	return svc.WithTx(ctx, func(ctx context.Context) error {
		q := svc.Q(ctx)
		if _, err := q.Exec(ctx, `DELETE FROM households WHERE advisor_id = $1`, wid); err != nil {
			return err
		}
		if _, err := svc.Seed(ctx, wid); err != nil {
			return err
		}
		_, err := q.Exec(ctx, `UPDATE advisors SET last_seen_at = now() WHERE id = $1`, wid)
		return err
	})
}

// Sweep deletes workspaces idle longer than idleDays and old IP counters.
func (svc *Service) Sweep(ctx context.Context, idleDays int) (int, error) {
	cutoff := time.Now().UTC().Add(-time.Duration(idleDays) * 24 * time.Hour)
	tag, err := svc.Store.Pool.Exec(ctx, `DELETE FROM advisors WHERE last_seen_at < $1 AND id <> $2`, cutoff, svc.Cfg.DevAdvisorID)
	if err != nil {
		return 0, err
	}
	if _, err := svc.Store.Pool.Exec(ctx, `DELETE FROM workspace_provisions WHERE day < (now() AT TIME ZONE 'utc')::date - 2`); err != nil {
		return 0, err
	}
	n := int(tag.RowsAffected())
	if n > 0 {
		slog.Info("workspace_sweep", "deleted", n, "idle_days", idleDays)
	}
	return n, nil
}
