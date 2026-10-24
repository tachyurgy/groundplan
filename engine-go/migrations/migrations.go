// Package migrations embeds the schema. Alembic (backend/alembic) is the single source of truth: alembic_head.sql
// is `alembic upgrade head --sql` output committed by the Python side as backend/migrations.sql, copied here
// verbatim (a test fails if the two drift). The Go service applies it to an empty database and refuses to start
// against any other revision.
package migrations

import (
	_ "embed"
	"regexp"
)

//go:embed alembic_head.sql
var SQL string

// Head is the Alembic revision the embedded SQL ends at.
var Head = func() string {
	re := regexp.MustCompile(`(?:VALUES \('|SET version_num=')([0-9A-Za-z_]+)'`)
	m := re.FindAllStringSubmatch(SQL, -1)
	if len(m) == 0 {
		return ""
	}
	return m[len(m)-1][1]
}()
