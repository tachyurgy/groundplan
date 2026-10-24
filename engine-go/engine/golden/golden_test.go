package golden

import (
	"bytes"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"

	"github.com/tachyurgy/groundplan/engine-go/engine/statetax"
	"github.com/tachyurgy/groundplan/engine-go/jsonx"
)

const fixtures = "../../../fixtures/engine"

// TestGoldenFixtures runs every case in fixtures/engine/*.json (the same files the Python suite runs) and requires
// byte-equal cents / strings for every expected key.
func TestGoldenFixtures(t *testing.T) {
	files, err := filepath.Glob(filepath.Join(fixtures, "*.json"))
	if err != nil || len(files) == 0 {
		t.Fatalf("no fixtures found under %s: %v", fixtures, err)
	}
	sort.Strings(files)
	n := 0
	for _, f := range files {
		if strings.HasSuffix(f, "states.json") {
			continue
		}
		raw, err := os.ReadFile(f)
		if err != nil {
			t.Fatal(err)
		}
		doc := jsonx.MustDecode(raw).(*jsonx.Obj)
		for _, c := range doc.MustGet("cases").([]any) {
			cs := c.(*jsonx.Obj)
			name := strings.TrimSuffix(filepath.Base(f), ".json") + "/" + cs.MustGet("name").(string)
			n++
			t.Run(name, func(t *testing.T) {
				defer func() {
					if r := recover(); r != nil {
						t.Fatalf("panic: %v", r)
					}
				}()
				got := RunCase(cs)
				if d := Compare(cs.MustGet("expected").(*jsonx.Obj), got); len(d) > 0 {
					t.Errorf("%s", strings.Join(d, "\n"))
				}
			})
		}
	}
	t.Logf("%d golden cases", n)
}

// TestStatesTableIsTheFixture guards the embedded copy of fixtures/engine/states.json.
func TestStatesTableIsTheFixture(t *testing.T) {
	raw, err := os.ReadFile(filepath.Join(fixtures, "states.json"))
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(raw, statetax.StatesJSON) {
		t.Fatal("engine/statetax/states.json differs from fixtures/engine/states.json: copy it again (make -C engine-go sync)")
	}
}
