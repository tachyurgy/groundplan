// Package statetax ports engine/state_tax.py: state income tax on a real-estate gain, table-driven from
// fixtures/engine/states.json (embedded; a test asserts the embedded copy is byte-identical to the fixture).
// Taxing states treat the gain as ordinary income stacked on the household's other income (marginal method).
// Unsupported states return 0, status estimated, plus a Finding; brackets are never invented.
package statetax

import (
	_ "embed"
	"fmt"
	"strings"
	"sync"

	"github.com/tachyurgy/groundplan/engine-go/dec"
	"github.com/tachyurgy/groundplan/engine-go/engine/figure"
	"github.com/tachyurgy/groundplan/engine-go/jsonx"
)

//go:embed states.json
var StatesJSON []byte

var (
	once  sync.Once
	table *jsonx.Obj
)

// Table returns the parsed state table (insertion-ordered like Python's json.load).
func Table() *jsonx.Obj {
	once.Do(func() { table = jsonx.MustDecode(StatesJSON).(*jsonx.Obj) })
	return table
}

func row(state string) *jsonx.Obj {
	st := Table().MustGet("states").(*jsonx.Obj)
	if v, ok := st.Get(strings.ToUpper(state)); ok {
		return v.(*jsonx.Obj)
	}
	return nil
}

func bracketsFor(r *jsonx.Obj, fs string) []any {
	br, _ := r.MustGet("brackets").(*jsonx.Obj)
	if br == nil {
		br = jsonx.O()
	}
	if v, ok := br.Get(fs); ok {
		return v.([]any)
	}
	if fs == "mfs" && br.Has("single") {
		return br.MustGet("single").([]any)
	}
	if fs == "hoh" && br.Has("single") {
		if v, ok := br.Get("hoh"); ok {
			return v.([]any)
		}
		return br.MustGet("single").([]any)
	}
	if v, ok := br.Get("all"); ok && v != nil && len(v.([]any)) > 0 {
		return v.([]any)
	}
	return br.Pairs()[0].V.([]any)
}

func decOf(v any) dec.D {
	switch x := v.(type) {
	case string:
		return dec.S(x)
	case int64:
		return dec.I(x)
	case jsonx.Float:
		return dec.F(float64(x))
	}
	panic(fmt.Sprintf("statetax: not a number %v", v))
}

// TaxOnCents is state_tax_on_cents(taxable, row, filing_status).
func TaxOnCents(taxableCents dec.D, r *jsonx.Obj, fs string) dec.D {
	kind := r.MustGet("kind").(string)
	if kind == "none" {
		return dec.Zero
	}
	taxable := dec.Max(dec.Zero, taxableCents)
	if kind == "flat" {
		return taxable.Mul(decOf(r.MustGet("rate")))
	}
	tax := dec.Zero
	lower := dec.Zero
	for _, b := range bracketsFor(r, fs) {
		pair := b.([]any)
		rate := decOf(pair[0])
		var up *dec.D
		if pair[1] != nil {
			u := decOf(pair[1]).Mul(dec.I(100))
			up = &u
		}
		segHi := taxable
		if up != nil {
			segHi = dec.Min(taxable, *up)
		}
		if segHi.Gt(lower) {
			tax = tax.Add(segHi.Sub(lower).Mul(rate))
		}
		if up == nil || taxable.Le(*up) {
			break
		}
		lower = *up
	}
	if s, ok := r.Get("surtaxes"); ok {
		for _, x := range s.([]any) {
			so := x.(*jsonx.Obj)
			thr := decOf(so.MustGet("over")).Mul(dec.I(100))
			if taxable.Gt(thr) {
				tax = tax.Add(taxable.Sub(thr).Mul(decOf(so.MustGet("rate"))))
			}
		}
	}
	return tax
}

// PyRepr is repr() of a simple string.
func PyRepr(s string) string {
	if strings.Contains(s, "'") && !strings.Contains(s, `"`) {
		return `"` + s + `"`
	}
	return "'" + strings.ReplaceAll(strings.ReplaceAll(s, `\`, `\\`), "'", `\'`) + "'"
}

func strOr(o *jsonx.Obj, k, def string) string {
	if v, ok := o.Get(k); ok {
		if s, ok := v.(string); ok {
			return s
		}
	}
	return def
}

// ExitTax is state_exit_tax(...): the marginal state tax on the gain, plus findings.
func ExitTax(state string, gainCents, otherIncomeCents int64, fs string, replacementState *string) (*figure.Figure, []*jsonx.Obj) {
	r := row(state)
	var findings []*jsonx.Obj
	inputs := figure.L(figure.M("state", state), figure.Of("gain_cents", gainCents, "figure", "exit_tax.total_gain"),
		figure.M("other_income_cents", otherIncomeCents), figure.M("filing_status", fs))
	if r == nil {
		findings = append(findings, jsonx.O("kind", "unsupported_structure", "field", "household.state", "severity", "warn",
			"message", fmt.Sprintf("state %s is not in the state tax table; state tax shown as 0 (unsupported state)", PyRepr(state))))
		zero := int64(0)
		return &figure.Figure{Key: "exit_tax.state", ValueCents: &zero, Status: "estimated",
			Inputs: append(inputs, figure.Of("state_table", "unsupported", "default")), Formula: "0 (unsupported state)",
			Notes: []string{"state not in table; verify with the client's CPA"}, Unit: "cents"}, findings
	}
	var src any
	srcRef := []string{}
	if v, ok := r.Get("source"); ok && v != nil {
		src = v
		srcRef = append(srcRef, v.(string))
	}
	tr := figure.Of("state_table_row", jsonx.O("kind", r.MustGet("kind"), "source", src), "manual", srcRef...)
	inputs = append(inputs, tr)
	notes := []string{fmt.Sprintf("%s: %s", strOr(r, "name", state), strOr(r, "note", r.MustGet("kind").(string))),
		"state standard deduction/exemptions ignored"}
	taxableGain := dec.I(gainCents)
	if v, ok := r.Get("ltcg_exclusion"); ok && truthy(v) {
		excl := decOf(v)
		taxableGain = taxableGain.Mul(dec.One.Sub(excl))
		notes = append(notes, fmt.Sprintf("%s long-term gain exclusion applied", excl.Pct(0)))
	}
	other := dec.I(otherIncomeCents)
	tax := TaxOnCents(other.Add(taxableGain), r, fs).Sub(TaxOnCents(other, r, fs))
	tax = dec.Max(dec.Zero, tax)
	if replacementState != nil && *replacementState != "" && strings.ToUpper(*replacementState) != strings.ToUpper(state) &&
		inClawback(strings.ToUpper(state)) {
		findings = append(findings, jsonx.O("kind", "info", "field", "exchange.replacement_state", "severity", "info",
			"message", fmt.Sprintf("%s is a clawback state: deferred gain on an out-of-state 1031 replacement "+
				"remains reportable to the source state when eventually sold (informational)", strings.ToUpper(state))))
	}
	return figure.Money("exit_tax.state", tax, inputs, "state_tax(other_income + gain) - state_tax(other_income)", notes, nil), findings
}

func inClawback(st string) bool {
	cs, _ := Table().MustGet("clawback_states").([]any)
	for _, c := range cs {
		if c == st {
			return true
		}
	}
	return false
}

// TaxCents is state_tax_cents(state, taxable, filing_status).
func TaxCents(state string, taxableCents int64, fs string) int64 {
	r := row(state)
	if r == nil {
		return 0
	}
	return TaxOnCents(dec.I(taxableCents), r, fs).Cents()
}

// truthy is Python bool(x) for JSON values.
func truthy(v any) bool {
	switch x := v.(type) {
	case nil:
		return false
	case string:
		return x != ""
	case int64:
		return x != 0
	case jsonx.Float:
		return x != 0
	case bool:
		return x
	}
	return true
}
