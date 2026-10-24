package service

import (
	"bytes"
	"os"
	"testing"
)

// The embedded seed must be byte-identical to fixtures/seed/okafor-lindqvist.json (the file scripts/seed.py loads).
func TestSeedFileIsTheFixture(t *testing.T) {
	raw, err := os.ReadFile("../../../fixtures/seed/okafor-lindqvist.json")
	if err != nil {
		t.Skip("fixture not present:", err)
	}
	if !bytes.Equal(raw, SeedJSON) {
		t.Fatal("internal/service/seeddata/okafor-lindqvist.json differs from fixtures/seed: copy it again (make -C engine-go sync)")
	}
	if _, err := loadSeed(); err != nil {
		t.Fatal(err)
	}
}
