package migrations

import (
	"os"
	"testing"
)

func TestEmbeddedSQLIsAlembicOutput(t *testing.T) {
	raw, err := os.ReadFile("../../backend/migrations.sql")
	if err != nil {
		t.Skip("backend/migrations.sql not present:", err)
	}
	if string(raw) != SQL {
		t.Fatal("migrations/alembic_head.sql differs from backend/migrations.sql: re-copy it (make -C engine-go sync)")
	}
	if Head == "" {
		t.Fatal("could not find the head revision in the embedded SQL")
	}
}
