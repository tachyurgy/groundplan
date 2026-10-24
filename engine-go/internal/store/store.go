// Package store is the Postgres layer: the embedded Alembic SQL, the version guard, and tenant-scoped loads and
// writes for the SPEC §1 tables. Every query filters by advisor_id (the workspace); there is no unscoped read of
// tenant data anywhere in this package.
package store

import (
	"context"
	"crypto/rand"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/tachyurgy/groundplan/engine-go/migrations"
)

var (
	migrationSQL = migrations.SQL
	// HeadRevision is the Alembic revision the embedded SQL ends at.
	HeadRevision = migrations.Head
)

// Store wraps the pool.
type Store struct {
	Pool *pgxpool.Pool
	TZ   *time.Location // the session TimeZone (Python renders timestamps in it)
}

// Open connects and runs the schema guard.
func Open(ctx context.Context, url string, maxConns int32) (*Store, error) {
	cfg, err := pgxpool.ParseConfig(url)
	if err != nil {
		return nil, err
	}
	if maxConns > 0 {
		cfg.MaxConns = maxConns
	}
	cfg.MaxConnIdleTime = 5 * time.Minute
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return nil, err
	}
	s := &Store{Pool: pool, TZ: time.UTC}
	var tz string
	if err := pool.QueryRow(ctx, "SHOW TimeZone").Scan(&tz); err == nil {
		if loc, err := time.LoadLocation(tz); err == nil {
			s.TZ = loc
		}
	}
	return s, nil
}

// ErrSchemaMismatch is returned when the database is at a different Alembic revision than the embedded SQL.
var ErrSchemaMismatch = errors.New("schema mismatch")

// Migrate applies the embedded Alembic SQL to an empty database and refuses a database at another revision.
func (s *Store) Migrate(ctx context.Context) (applied bool, err error) {
	var exists bool
	if err := s.Pool.QueryRow(ctx, "SELECT to_regclass('public.alembic_version') IS NOT NULL").Scan(&exists); err != nil {
		return false, err
	}
	if !exists {
		var n int
		if err := s.Pool.QueryRow(ctx, "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'").Scan(&n); err != nil {
			return false, err
		}
		if n > 0 {
			return false, fmt.Errorf("%w: database has %d tables but no alembic_version; refusing to touch it", ErrSchemaMismatch, n)
		}
		conn, err := s.Pool.Acquire(ctx)
		if err != nil {
			return false, err
		}
		defer conn.Release()
		// The Alembic offline SQL carries its own BEGIN/COMMIT; run it as one simple-protocol batch. A concurrent
		// starter loses on the CREATE TABLE alembic_version and then passes the version check below.
		if _, err := conn.Conn().PgConn().Exec(ctx, migrationSQL).ReadAll(); err != nil {
			var pe *pgconn.PgError
			if !(errors.As(err, &pe) && pe.Code == "42P07") {
				return false, fmt.Errorf("apply embedded migrations: %w", err)
			}
		} else {
			applied = true
		}
	}
	var ver string
	if err := s.Pool.QueryRow(ctx, "SELECT version_num FROM alembic_version").Scan(&ver); err != nil {
		return applied, fmt.Errorf("%w: read alembic_version: %v", ErrSchemaMismatch, err)
	}
	if ver != HeadRevision {
		return applied, fmt.Errorf("%w: database is at alembic revision %q, this binary embeds %q", ErrSchemaMismatch, ver, HeadRevision)
	}
	return applied, nil
}

// NewID is uuid4 as a string.
func NewID() string {
	var b [16]byte
	_, _ = rand.Read(b[:])
	b[6] = (b[6] & 0x0f) | 0x40
	b[8] = (b[8] & 0x3f) | 0x80
	return fmt.Sprintf("%x-%x-%x-%x-%x", b[0:4], b[4:6], b[6:8], b[8:10], b[10:16])
}

// Tx runs fn in a transaction.
func (s *Store) Tx(ctx context.Context, fn func(tx pgx.Tx) error) error {
	return pgx.BeginFunc(ctx, s.Pool, fn)
}

// Q is the common subset of pool and tx.
type Q interface {
	Exec(ctx context.Context, sql string, args ...any) (pgconn.CommandTag, error)
	Query(ctx context.Context, sql string, args ...any) (pgx.Rows, error)
	QueryRow(ctx context.Context, sql string, args ...any) pgx.Row
}
