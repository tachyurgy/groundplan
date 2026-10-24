// Package jsonx is an insertion-ordered JSON object plus an encoder that writes what Starlette's JSONResponse
// writes for the same Python value: compact separators, UTF-8 (ensure_ascii=False), Python float repr, keys in
// insertion order. Responses from both backends are therefore byte-comparable, not just structurally equal.
package jsonx

import (
	"bytes"
	"encoding/json"
	"fmt"
	"math"
	"reflect"
	"sort"
	"strconv"
	"unicode/utf8"

	"github.com/tachyurgy/groundplan/engine-go/dec"
)

// KV is one member of an ordered object.
type KV struct {
	K string
	V any
}

// Obj is an insertion-ordered JSON object (Python dict semantics: setting an existing key keeps its position).
type Obj struct {
	kv  []KV
	idx map[string]int
}

// O builds an object from alternating key, value arguments.
func O(pairs ...any) *Obj {
	o := &Obj{idx: make(map[string]int, len(pairs)/2)}
	for i := 0; i+1 < len(pairs); i += 2 {
		o.Set(pairs[i].(string), pairs[i+1])
	}
	return o
}

// Set inserts or replaces a key.
func (o *Obj) Set(k string, v any) *Obj {
	if o.idx == nil {
		o.idx = map[string]int{}
	}
	if i, ok := o.idx[k]; ok {
		o.kv[i].V = v
		return o
	}
	o.idx[k] = len(o.kv)
	o.kv = append(o.kv, KV{k, v})
	return o
}

// SetDefault is dict.setdefault.
func (o *Obj) SetDefault(k string, v any) any {
	if x, ok := o.Get(k); ok {
		return x
	}
	o.Set(k, v)
	return v
}

// Get returns a value.
func (o *Obj) Get(k string) (any, bool) {
	if o == nil || o.idx == nil {
		return nil, false
	}
	i, ok := o.idx[k]
	if !ok {
		return nil, false
	}
	return o.kv[i].V, true
}

// MustGet returns a value or nil.
func (o *Obj) MustGet(k string) any { v, _ := o.Get(k); return v }

// Has reports key presence.
func (o *Obj) Has(k string) bool { _, ok := o.Get(k); return ok }

// Delete removes a key (dict.pop).
func (o *Obj) Delete(k string) any {
	i, ok := o.idx[k]
	if !ok {
		return nil
	}
	v := o.kv[i].V
	o.kv = append(o.kv[:i], o.kv[i+1:]...)
	delete(o.idx, k)
	for j := i; j < len(o.kv); j++ {
		o.idx[o.kv[j].K] = j
	}
	return v
}

// Keys returns the keys in order.
func (o *Obj) Keys() []string {
	out := make([]string, len(o.kv))
	for i, kv := range o.kv {
		out[i] = kv.K
	}
	return out
}

// Pairs returns the members in order.
func (o *Obj) Pairs() []KV { return o.kv }

// Len is the number of members.
func (o *Obj) Len() int {
	if o == nil {
		return 0
	}
	return len(o.kv)
}

// Copy is a shallow copy (dict(x)).
func (o *Obj) Copy() *Obj {
	n := &Obj{idx: make(map[string]int, len(o.kv))}
	for _, kv := range o.kv {
		n.Set(kv.K, kv.V)
	}
	return n
}

// MarshalJSON lets an Obj be used with encoding/json too.
func (o *Obj) MarshalJSON() ([]byte, error) { return Marshal(o) }

// Float marks a float value that must be written with Python's repr (use for every float in a response).
type Float float64

// Raw is pre-encoded JSON written as-is.
type Raw []byte

// Marshal writes v compactly.
func Marshal(v any) ([]byte, error) {
	var b bytes.Buffer
	if err := write(&b, v); err != nil {
		return nil, err
	}
	return b.Bytes(), nil
}

// MustMarshal panics on error.
func MustMarshal(v any) []byte {
	b, err := Marshal(v)
	if err != nil {
		panic(err)
	}
	return b
}

func write(b *bytes.Buffer, v any) error {
	switch x := v.(type) {
	case nil:
		b.WriteString("null")
	case *Obj:
		if x == nil {
			b.WriteString("null")
			return nil
		}
		b.WriteByte('{')
		for i, kv := range x.kv {
			if i > 0 {
				b.WriteByte(',')
			}
			writeString(b, kv.K)
			b.WriteByte(':')
			if err := write(b, kv.V); err != nil {
				return err
			}
		}
		b.WriteByte('}')
	case Raw:
		b.Write(x)
	case json.RawMessage:
		b.Write(x)
	case string:
		writeString(b, x)
	case bool:
		if x {
			b.WriteString("true")
		} else {
			b.WriteString("false")
		}
	case int:
		b.WriteString(strconv.Itoa(x))
	case int32:
		b.WriteString(strconv.FormatInt(int64(x), 10))
	case int64:
		b.WriteString(strconv.FormatInt(x, 10))
	case *int64:
		if x == nil {
			b.WriteString("null")
		} else {
			b.WriteString(strconv.FormatInt(*x, 10))
		}
	case *int:
		if x == nil {
			b.WriteString("null")
		} else {
			b.WriteString(strconv.Itoa(*x))
		}
	case *string:
		if x == nil {
			b.WriteString("null")
		} else {
			writeString(b, *x)
		}
	case *float64:
		if x == nil {
			b.WriteString("null")
		} else {
			return writeFloat(b, *x)
		}
	case Float:
		return writeFloat(b, float64(x))
	case float64:
		return writeFloat(b, x)
	case dec.D:
		writeString(b, x.String()) // engine Inputs carry Decimals as strings (figure._jsonable)
	case json.Number:
		b.WriteString(string(x))
	case []any:
		b.WriteByte('[')
		for i, e := range x {
			if i > 0 {
				b.WriteByte(',')
			}
			if err := write(b, e); err != nil {
				return err
			}
		}
		b.WriteByte(']')
	case []*Obj:
		b.WriteByte('[')
		for i, e := range x {
			if i > 0 {
				b.WriteByte(',')
			}
			if err := write(b, e); err != nil {
				return err
			}
		}
		b.WriteByte(']')
	case []string:
		b.WriteByte('[')
		for i, e := range x {
			if i > 0 {
				b.WriteByte(',')
			}
			writeString(b, e)
		}
		b.WriteByte(']')
	case map[string]any:
		keys := make([]string, 0, len(x))
		for k := range x {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		o := &Obj{}
		for _, k := range keys {
			o.Set(k, x[k])
		}
		return write(b, o)
	case interface{ JSONValue() any }:
		return write(b, x.JSONValue())
	default:
		rv := reflect.ValueOf(v)
		if rv.Kind() == reflect.Slice {
			b.WriteByte('[')
			for i := 0; i < rv.Len(); i++ {
				if i > 0 {
					b.WriteByte(',')
				}
				if err := write(b, rv.Index(i).Interface()); err != nil {
					return err
				}
			}
			b.WriteByte(']')
			return nil
		}
		if rv.Kind() == reflect.Pointer && rv.IsNil() {
			b.WriteString("null")
			return nil
		}
		raw, err := json.Marshal(v)
		if err != nil {
			return fmt.Errorf("jsonx: cannot encode %T: %w", v, err)
		}
		b.Write(raw)
	}
	return nil
}

func writeFloat(b *bytes.Buffer, f float64) error {
	if math.IsInf(f, 0) || math.IsNaN(f) {
		return fmt.Errorf("jsonx: out of range float %v", f) // Starlette uses allow_nan=False
	}
	b.WriteString(dec.PyFloatRepr(f))
	return nil
}

const hexd = "0123456789abcdef"

// writeString escapes like json.dumps(ensure_ascii=False): ", \\, control chars; everything else raw UTF-8.
func writeString(b *bytes.Buffer, s string) {
	b.WriteByte('"')
	for i := 0; i < len(s); {
		c := s[i]
		if c < utf8.RuneSelf {
			switch c {
			case '"':
				b.WriteString(`\"`)
			case '\\':
				b.WriteString(`\\`)
			case '\n':
				b.WriteString(`\n`)
			case '\r':
				b.WriteString(`\r`)
			case '\t':
				b.WriteString(`\t`)
			case '\b':
				b.WriteString(`\b`)
			case '\f':
				b.WriteString(`\f`)
			default:
				if c < 0x20 || c == 0x7f && false {
					b.WriteString(`\u00`)
					b.WriteByte(hexd[c>>4])
					b.WriteByte(hexd[c&0xf])
				} else {
					b.WriteByte(c)
				}
			}
			i++
			continue
		}
		r, size := utf8.DecodeRuneInString(s[i:])
		if r == utf8.RuneError && size == 1 {
			b.WriteString(`�`)
		} else {
			b.WriteString(s[i : i+size])
		}
		i += size
	}
	b.WriteByte('"')
}

// Decode parses JSON preserving object key order (objects become *Obj, numbers become int64 or Float like
// Python's json.loads: integers stay integers, anything with a fraction or exponent is a float).
func Decode(data []byte) (any, error) {
	d := json.NewDecoder(bytes.NewReader(data))
	d.UseNumber()
	v, err := decodeValue(d)
	if err != nil {
		return nil, err
	}
	return v, nil
}

func decodeValue(d *json.Decoder) (any, error) {
	t, err := d.Token()
	if err != nil {
		return nil, err
	}
	return fromToken(d, t)
}

func fromToken(d *json.Decoder, t json.Token) (any, error) {
	switch x := t.(type) {
	case json.Delim:
		switch x {
		case '{':
			o := O()
			for d.More() {
				kt, err := d.Token()
				if err != nil {
					return nil, err
				}
				k, _ := kt.(string)
				v, err := decodeValue(d)
				if err != nil {
					return nil, err
				}
				o.Set(k, v)
			}
			if _, err := d.Token(); err != nil {
				return nil, err
			}
			return o, nil
		case '[':
			arr := []any{}
			for d.More() {
				v, err := decodeValue(d)
				if err != nil {
					return nil, err
				}
				arr = append(arr, v)
			}
			if _, err := d.Token(); err != nil {
				return nil, err
			}
			return arr, nil
		}
	case json.Number:
		s := string(x)
		if i, err := strconv.ParseInt(s, 10, 64); err == nil {
			return i, nil
		}
		for _, c := range s {
			if c == '.' || c == 'e' || c == 'E' {
				f, err := strconv.ParseFloat(s, 64)
				if err != nil {
					return nil, err
				}
				return Float(f), nil
			}
		}
		return x, nil // big integer: keep the literal
	default:
		return x, nil
	}
	return nil, fmt.Errorf("jsonx: unexpected token %v", t)
}

// MustDecode panics on error.
func MustDecode(data []byte) any {
	v, err := Decode(data)
	if err != nil {
		panic(err)
	}
	return v
}

// Equal compares two decoded JSON values structurally (object order ignored; 1 == 1.0 like Python).
func Equal(a, b any) bool {
	return reflect.DeepEqual(Normalize(a), Normalize(b))
}

// Normalize converts to plain Go values for comparison (maps, slices, float64 numbers).
func Normalize(v any) any {
	switch x := v.(type) {
	case *Obj:
		m := map[string]any{}
		for _, kv := range x.kv {
			m[kv.K] = Normalize(kv.V)
		}
		return m
	case []any:
		out := make([]any, len(x))
		for i, e := range x {
			out[i] = Normalize(e)
		}
		return out
	case int64:
		return float64(x)
	case int:
		return float64(x)
	case Float:
		return float64(x)
	default:
		return v
	}
}
