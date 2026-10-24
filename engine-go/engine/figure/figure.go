// Package figure ports backend/groundplan/engine/figure.py: the API shape for any computed number, with
// provenance. A Figure is confirmed only if every input came from a document or manual entry, estimated if any
// input is public_data or default, and blocked if an open blocking Finding touches an input. Child Figures
// propagate the worst status upward.
package figure

import (
	"fmt"
	"time"

	"github.com/tachyurgy/groundplan/engine-go/dec"
	"github.com/tachyurgy/groundplan/engine-go/jsonx"
)

// Status order.
var statusOrder = map[string]int{"confirmed": 0, "estimated": 1, "blocked": 2}

// StatusRank exposes the order (confirmed < estimated < blocked).
func StatusRank(s string) int { return statusOrder[s] }

// Worst returns the worse of two statuses (first wins ties).
func Worst(a, b string) string {
	if statusOrder[a] >= statusOrder[b] {
		return a
	}
	return b
}

// WorstOf is max(statuses, key=order) with a default of confirmed.
func WorstOf(ss ...string) string {
	if len(ss) == 0 {
		return "confirmed"
	}
	w := ss[0]
	for _, s := range ss[1:] {
		if statusOrder[s] > statusOrder[w] {
			w = s
		}
	}
	return w
}

// Source of an input.
type Source struct {
	Type       string // document | manual | public_data | default | figure
	Ref        *string
	Page       *int
	DocumentID *string
	BBox       []any
}

// Input of a Figure.
type Input struct {
	Key    string
	Value  any
	Source Source
	Status *string
	Child  *Figure
	Label  string
}

// Figure is a computed number with its provenance.
type Figure struct {
	Key        string
	ValueCents *int64
	Status     string
	Inputs     []*Input
	Formula    string
	Notes      []string
	Value      *string // non-money figures as a decimal string
	Unit       string  // cents | rate | ratio | years | count
}

// Str returns a pointer to s (nil for "").
func Str(s string) *string { return &s }

// Int64 returns a pointer to v.
func Int64(v int64) *int64 { return &v }

// Of is Input.of(key, value, src, ref, page).
func Of(key string, value any, src string, ref ...string) *Input {
	in := &Input{Key: key, Value: Jsonable(value), Source: Source{Type: checkSrc(src)}}
	if len(ref) > 0 {
		r := ref[0]
		in.Source.Ref = &r
	}
	return in
}

// M is Input.of with the default "manual" source.
func M(key string, value any) *Input { return Of(key, value, "manual") }

// OfPage is Input.of with a page.
func OfPage(key string, value any, src, ref string, page int) *Input {
	in := Of(key, value, src, ref)
	in.Source.Page = &page
	return in
}

func checkSrc(s string) string {
	switch s {
	case "document", "manual", "public_data", "default", "figure":
		return s
	}
	panic(fmt.Sprintf("unknown source type %q", s))
}

// Fig is Input.figure(fig).
func Fig(f *Figure) *Input {
	var val any
	if f.ValueCents != nil {
		val = *f.ValueCents
	} else if f.Value != nil {
		val = *f.Value
	}
	st := f.Status
	k := f.Key
	return &Input{Key: f.Key, Value: val, Source: Source{Type: "figure", Ref: &k}, Status: &st, Child: f}
}

// Jsonable mirrors figure._jsonable: Decimals become strings, dates become ISO strings.
func Jsonable(v any) any {
	switch x := v.(type) {
	case dec.D:
		return x.String()
	case time.Time:
		return x.Format("2006-01-02")
	case *time.Time:
		if x == nil {
			return nil
		}
		return x.Format("2006-01-02")
	case int:
		return int64(x)
	case *int64:
		if x == nil {
			return nil
		}
		return *x
	case *string:
		if x == nil {
			return nil
		}
		return *x
	case *dec.D:
		if x == nil {
			return nil
		}
		return x.String()
	}
	return v
}

// ToDict is Input.to_dict(depth).
func (i *Input) ToDict(depth int) *jsonx.Obj {
	src := jsonx.O("type", i.Source.Type, "ref", i.Source.Ref, "page", i.Source.Page)
	if i.Source.DocumentID != nil && *i.Source.DocumentID != "" {
		src.Set("document_id", *i.Source.DocumentID)
	}
	if len(i.Source.BBox) > 0 {
		src.Set("bbox", i.Source.BBox)
	}
	d := jsonx.O("key", i.Key, "value", i.Value, "source", src)
	if i.Status != nil {
		d.Set("status", *i.Status)
	}
	if i.Label != "" {
		d.Set("label", i.Label)
	}
	if i.Child != nil && depth > 0 {
		d.Set("figure", i.Child.ToDict(depth-1))
	}
	return d
}

// ToDict is Figure.to_dict(depth) with the default depth 1.
func (f *Figure) ToDict(depth ...int) *jsonx.Obj {
	dp := 1
	if len(depth) > 0 {
		dp = depth[0]
	}
	ins := make([]any, len(f.Inputs))
	for k, in := range f.Inputs {
		ins[k] = in.ToDict(dp)
	}
	notes := make([]any, len(f.Notes))
	for k, n := range f.Notes {
		notes[k] = n
	}
	d := jsonx.O("key", f.Key, "value_cents", f.ValueCents, "status", f.Status, "inputs", ins, "formula", f.Formula,
		"notes", notes, "unit", f.Unit)
	if f.Unit != "cents" {
		d.Set("value", f.Value)
	}
	return d
}

// Dec is the Figure's value as a decimal (cents for money figures).
func (f *Figure) Dec() dec.D {
	if f.ValueCents != nil {
		return dec.I(*f.ValueCents)
	}
	if f.Value != nil {
		return dec.S(*f.Value)
	}
	return dec.Zero
}

// VC returns value_cents or 0 (Python `fig.value_cents or 0`).
func (f *Figure) VC() int64 {
	if f.ValueCents == nil {
		return 0
	}
	return *f.ValueCents
}

// Walk yields this Figure and every descendant (depth-first).
func (f *Figure) Walk(fn func(*Figure) bool) bool {
	if fn(f) {
		return true
	}
	for _, in := range f.Inputs {
		if in.Child != nil && in.Child.Walk(fn) {
			return true
		}
	}
	return false
}

// KeySet is a set of input keys touched by open blocking Findings.
type KeySet map[string]bool

// DeriveStatus is derive_status(inputs, blocked_keys).
func DeriveStatus(inputs []*Input, blocked KeySet) string {
	worst := "confirmed"
	for _, in := range inputs {
		s := "confirmed"
		if len(blocked) > 0 && blocked[in.Key] {
			s = "blocked"
		} else if in.Source.Type == "figure" {
			if in.Status != nil {
				s = *in.Status
			}
		} else if in.Source.Type == "public_data" || in.Source.Type == "default" {
			s = "estimated"
		}
		if statusOrder[s] > statusOrder[worst] {
			worst = s
		}
	}
	return worst
}

// Money is money(key, amount, inputs, formula, notes, blocked_keys): rounds once, derives status.
func Money(key string, amount dec.D, inputs []*Input, formula string, notes []string, blocked KeySet) *Figure {
	c := amount.Cents()
	return &Figure{Key: key, ValueCents: &c, Status: DeriveStatus(inputs, blocked), Inputs: inputs, Formula: formula,
		Notes: copyNotes(notes), Unit: "cents"}
}

// MoneyI is Money for an integer amount.
func MoneyI(key string, amount int64, inputs []*Input, formula string, notes []string, blocked KeySet) *Figure {
	return Money(key, dec.I(amount), inputs, formula, notes, blocked)
}

// Ratio is ratio(key, value, inputs, formula, unit, notes, places).
func Ratio(key string, value *dec.D, inputs []*Input, formula, unit string, notes []string, places int) *Figure {
	var v *string
	if value != nil {
		s := value.RateStr(places)
		v = &s
	}
	return &Figure{Key: key, Status: DeriveStatus(inputs, nil), Inputs: inputs, Formula: formula, Notes: copyNotes(notes),
		Value: v, Unit: unit}
}

func copyNotes(n []string) []string {
	out := make([]string, len(n))
	copy(out, n)
	return out
}

// Ins concatenates input lists into a fresh slice (Python `a + b` on lists).
func Ins(parts ...[]*Input) []*Input {
	n := 0
	for _, p := range parts {
		n += len(p)
	}
	out := make([]*Input, 0, n)
	for _, p := range parts {
		out = append(out, p...)
	}
	return out
}

// L builds an input list.
func L(xs ...*Input) []*Input { return xs }
