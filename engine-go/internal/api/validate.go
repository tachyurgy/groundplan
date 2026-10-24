package api

import (
	"fmt"
	"math"
	"strconv"
	"strings"
	"time"

	"github.com/tachyurgy/groundplan/engine-go/dec"
	"github.com/tachyurgy/groundplan/engine-go/jsonx"
)

// A small re-implementation of the pydantic v2 (lax mode) rules the request models in api/schemas.py rely on:
// coercion of numeric strings and integral floats to int, int/str to float, the bool string set, ISO dates,
// Literal choices, min/max length and ge/le bounds, extra="forbid". Error objects use pydantic's loc/msg/type.

type kind int

const (
	kStr kind = iota
	kInt
	kFloat
	kBool
	kDate
	kAny
	kObj
)

type spec struct {
	name      string
	k         kind
	required  bool
	nullable  bool
	def       any // default when absent (model_dump includes it)
	choices   []string
	minLen    int
	maxLen    int
	ge, le    *float64
	hasDefNil bool
}

func f(v float64) *float64 { return &v }

type schema struct {
	fields []spec
	forbid bool
}

// parsed is model_dump(): every field (with defaults) plus the set of keys the client sent (exclude_unset).
type parsed struct {
	vals  map[string]any
	order []string
	set   map[string]bool
	extra *jsonx.Obj // extra="allow" members
}

func (p *parsed) has(k string) bool { return p.set[k] }

func (p *parsed) str(k string) string {
	s, _ := p.vals[k].(string)
	return s
}

func (p *parsed) strp(k string) *string {
	if s, ok := p.vals[k].(string); ok {
		return &s
	}
	return nil
}

func (p *parsed) i64(k string) int64 {
	v, _ := p.vals[k].(int64)
	return v
}

func (p *parsed) i64p(k string) *int64 {
	if v, ok := p.vals[k].(int64); ok {
		return &v
	}
	return nil
}

func (p *parsed) fl(k string) float64 {
	v, _ := p.vals[k].(float64)
	return v
}

func (p *parsed) flp(k string) *float64 {
	if v, ok := p.vals[k].(float64); ok {
		return &v
	}
	return nil
}

func (p *parsed) b(k string) bool {
	v, _ := p.vals[k].(bool)
	return v
}

func (p *parsed) datep(k string) *time.Time {
	if v, ok := p.vals[k].(time.Time); ok {
		return &v
	}
	return nil
}

func typeName(v any) string {
	switch v.(type) {
	case nil:
		return "NoneType"
	case string:
		return "str"
	case int64:
		return "int"
	case jsonx.Float:
		return "float"
	case bool:
		return "bool"
	case []any:
		return "list"
	case *jsonx.Obj:
		return "dict"
	}
	return "object"
}

var boolTrue = map[string]bool{"1": true, "on": true, "t": true, "true": true, "y": true, "yes": true}
var boolFalse = map[string]bool{"0": true, "off": true, "f": true, "false": true, "n": true, "no": true}

func coerce(s spec, v any, loc []any) (any, *jsonx.Obj) {
	if v == nil {
		if s.nullable {
			return nil, nil
		}
		switch s.k {
		case kStr:
			return nil, verr(loc, "Input should be a valid string", "string_type")
		case kInt:
			return nil, verr(loc, "Input should be a valid integer", "int_type")
		case kFloat:
			return nil, verr(loc, "Input should be a valid number", "float_type")
		case kBool:
			return nil, verr(loc, "Input should be a valid boolean", "bool_type")
		case kDate:
			return nil, verr(loc, "Input should be a valid date", "date_type")
		case kObj:
			return nil, verr(loc, "Input should be a valid dictionary", "dict_type")
		}
		return nil, nil
	}
	switch s.k {
	case kAny:
		return v, nil
	case kObj:
		if o, ok := v.(*jsonx.Obj); ok {
			return o, nil
		}
		return nil, verr(loc, "Input should be a valid dictionary", "dict_type")
	case kStr:
		x, ok := v.(string)
		if !ok {
			return nil, verr(loc, "Input should be a valid string", "string_type")
		}
		if len(s.choices) > 0 {
			for _, c := range s.choices {
				if c == x {
					return x, nil
				}
			}
			return nil, verr(loc, "Input should be "+choiceText(s.choices), "literal_error")
		}
		n := len([]rune(x))
		if s.minLen > 0 && n < s.minLen {
			return nil, verr(loc, fmt.Sprintf("String should have at least %d character%s", s.minLen, plural(s.minLen)), "string_too_short")
		}
		if s.maxLen > 0 && n > s.maxLen {
			return nil, verr(loc, fmt.Sprintf("String should have at most %d character%s", s.maxLen, plural(s.maxLen)), "string_too_long")
		}
		return x, nil
	case kInt:
		var out int64
		switch x := v.(type) {
		case int64:
			out = x
		case bool:
			if x {
				out = 1
			}
		case jsonx.Float:
			if float64(x) != math.Trunc(float64(x)) || math.IsInf(float64(x), 0) {
				return nil, verr(loc, "Input should be a valid integer, got a number with a fractional part", "int_from_float")
			}
			out = int64(x)
		case string:
			t := strings.TrimSpace(x)
			i, err := strconv.ParseInt(t, 10, 64)
			if err != nil {
				fl, ferr := strconv.ParseFloat(t, 64)
				if ferr != nil || fl != math.Trunc(fl) {
					return nil, verr(loc, "Input should be a valid integer, unable to parse string as an integer", "int_parsing")
				}
				i = int64(fl)
			}
			out = i
		default:
			return nil, verr(loc, "Input should be a valid integer", "int_type")
		}
		if e := bounds(s, float64(out), loc); e != nil {
			return nil, e
		}
		return out, nil
	case kFloat:
		var out float64
		switch x := v.(type) {
		case int64:
			out = float64(x)
		case jsonx.Float:
			out = float64(x)
		case bool:
			if x {
				out = 1
			}
		case string:
			fl, err := strconv.ParseFloat(strings.TrimSpace(x), 64)
			if err != nil {
				return nil, verr(loc, "Input should be a valid number, unable to parse string as a number", "float_parsing")
			}
			out = fl
		default:
			return nil, verr(loc, "Input should be a valid number", "float_type")
		}
		if e := bounds(s, out, loc); e != nil {
			return nil, e
		}
		return out, nil
	case kBool:
		switch x := v.(type) {
		case bool:
			return x, nil
		case int64:
			if x == 0 || x == 1 {
				return x == 1, nil
			}
		case jsonx.Float:
			if x == 0 || x == 1 {
				return x == 1, nil
			}
		case string:
			l := strings.ToLower(strings.TrimSpace(x))
			if boolTrue[l] {
				return true, nil
			}
			if boolFalse[l] {
				return false, nil
			}
			return nil, verr(loc, "Input should be a valid boolean, unable to interpret input", "bool_parsing")
		}
		return nil, verr(loc, "Input should be a valid boolean", "bool_type")
	case kDate:
		x, ok := v.(string)
		if !ok {
			return nil, verr(loc, "Input should be a valid date", "date_type")
		}
		t, err := time.Parse("2006-01-02", x)
		if err != nil {
			if tt, err2 := time.Parse(time.RFC3339, x); err2 == nil && tt.Hour() == 0 && tt.Minute() == 0 && tt.Second() == 0 {
				return time.Date(tt.Year(), tt.Month(), tt.Day(), 0, 0, 0, 0, time.UTC), nil
			}
			return nil, verr(loc, "Input should be a valid date or datetime, invalid character in year", "date_from_datetime_parsing")
		}
		return t, nil
	}
	return v, nil
}

func plural(n int) string {
	if n == 1 {
		return ""
	}
	return "s"
}

func choiceText(cs []string) string {
	q := make([]string, len(cs))
	for i, c := range cs {
		q[i] = "'" + c + "'"
	}
	if len(q) == 1 {
		return q[0]
	}
	return strings.Join(q[:len(q)-1], ", ") + " or " + q[len(q)-1]
}

func bounds(s spec, v float64, loc []any) *jsonx.Obj {
	if s.ge != nil && v < *s.ge {
		return verr(loc, "Input should be greater than or equal to "+numStr(*s.ge), "greater_than_equal")
	}
	if s.le != nil && v > *s.le {
		return verr(loc, "Input should be less than or equal to "+numStr(*s.le), "less_than_equal")
	}
	return nil
}

func numStr(f float64) string {
	if f == math.Trunc(f) {
		return strconv.FormatInt(int64(f), 10)
	}
	return dec.PyFloatRepr(f)
}

// parse validates a decoded JSON body against a schema. loc prefix is ("body", ...).
func (sc schema) parse(v any, prefix []any) (*parsed, []any) {
	o, ok := v.(*jsonx.Obj)
	if !ok {
		return nil, []any{verr(prefix, "Input should be a valid dictionary or object to extract fields from", "model_attributes_type")}
	}
	out := &parsed{vals: map[string]any{}, set: map[string]bool{}, extra: jsonx.O()}
	var errs []any
	known := map[string]bool{}
	for _, s := range sc.fields {
		known[s.name] = true
		out.order = append(out.order, s.name)
		raw, present := o.Get(s.name)
		loc := append(append([]any{}, prefix...), s.name)
		if !present {
			if s.required {
				errs = append(errs, verr(loc, "Field required", "missing"))
				continue
			}
			out.vals[s.name] = s.def
			continue
		}
		val, e := coerce(s, raw, loc)
		if e != nil {
			errs = append(errs, e)
			continue
		}
		out.vals[s.name] = val
		out.set[s.name] = true
	}
	for _, kv := range o.Pairs() {
		if known[kv.K] {
			continue
		}
		if sc.forbid {
			errs = append(errs, verr(append(append([]any{}, prefix...), kv.K), "Extra inputs are not permitted", "extra_forbidden"))
		} else {
			out.extra.Set(kv.K, kv.V)
		}
	}
	return out, errs
}

var (
	filingStatuses = []string{"single", "mfj", "mfs", "hoh"}
	propertyTypes  = []string{"sfr", "multifamily", "vacation_str", "commercial", "land", "self_rental", "other"}
	loanTypes      = []string{"fixed", "arm", "interest_only", "heloc", "balloon"}
	valueSources   = []string{"estimated", "confirmed"}
	propStatuses   = []string{"active", "sold", "converted"}
	simTypes       = []string{"buy", "sell", "exchange", "refi"}
)

var householdIn = schema{fields: []spec{
	{name: "name", k: kStr, required: true},
	{name: "filing_status", k: kStr, def: "mfj", choices: filingStatuses},
	{name: "state", k: kStr, def: "CA", minLen: 2, maxLen: 2},
	{name: "tax_year_latest", k: kInt, def: int64(2025)},
	{name: "wages_cents", k: kInt, def: int64(0)},
	{name: "other_income_cents", k: kInt, def: int64(0)},
	{name: "magi_cents", k: kInt, def: int64(0)},
	{name: "active_participation", k: kBool, def: true},
	{name: "re_professional", k: kBool, def: false},
	{name: "net_worth_cents", k: kInt, nullable: true},
	{name: "goal", k: kStr, def: ""},
	{name: "notes", k: kStr, def: ""},
}}

func patchOf(sc schema, forbid bool) schema {
	out := schema{forbid: forbid}
	for _, s := range sc.fields {
		s.required = false
		s.nullable = true
		s.def = nil
		out.fields = append(out.fields, s)
	}
	return out
}

var householdPatch = patchOf(householdIn, false)

var propertyIn = schema{fields: []spec{
	{name: "nickname", k: kStr, required: true},
	{name: "address_line1", k: kStr, def: ""},
	{name: "city", k: kStr, def: ""},
	{name: "state", k: kStr, def: ""},
	{name: "zip", k: kStr, def: ""},
	{name: "property_type", k: kStr, def: "sfr", choices: propertyTypes},
	{name: "units", k: kInt, def: int64(1)},
	{name: "purchase_date", k: kDate, nullable: true},
	{name: "purchase_price_cents", k: kInt, def: int64(0)},
	{name: "placed_in_service_date", k: kDate, nullable: true},
	{name: "land_pct", k: kFloat, nullable: true, ge: f(0), le: f(1)},
	{name: "improvements_cents", k: kInt, def: int64(0)},
	{name: "cost_seg_study", k: kBool, def: false},
	{name: "current_value_cents", k: kInt, def: int64(0)},
	{name: "value_source", k: kStr, def: "estimated", choices: valueSources},
	{name: "value_as_of", k: kDate, nullable: true},
	{name: "appreciation_rate", k: kFloat, nullable: true},
	{name: "rent_growth_rate", k: kFloat, nullable: true},
	{name: "expense_growth_rate", k: kFloat, nullable: true},
	{name: "vacancy_rate", k: kFloat, nullable: true, ge: f(0), le: f(1)},
	{name: "mgmt_fee_rate", k: kFloat, nullable: true, ge: f(0), le: f(1)},
	{name: "capex_reserve_rate", k: kFloat, nullable: true, ge: f(0), le: f(1)},
	{name: "selling_cost_rate", k: kFloat, nullable: true, ge: f(0), le: f(1)},
	{name: "status", k: kStr, def: "active", choices: propStatuses},
	{name: "former_residence_until", k: kDate, nullable: true},
	{name: "avg_stay_days", k: kFloat, nullable: true},
}}

// PropertyPatch keeps the land_pct bound only (the other rate bounds are not declared on the patch model).
var propertyPatch = func() schema {
	s := patchOf(propertyIn, true)
	for i := range s.fields {
		if s.fields[i].name != "land_pct" {
			s.fields[i].ge, s.fields[i].le = nil, nil
		}
	}
	return s
}()

var loanIn = schema{fields: []spec{
	{name: "lender", k: kStr, def: ""},
	{name: "loan_type", k: kStr, def: "fixed", choices: loanTypes},
	{name: "original_cents", k: kInt, def: int64(0)},
	{name: "balance_cents", k: kInt, def: int64(0)},
	{name: "balance_as_of", k: kDate, required: true},
	{name: "rate", k: kFloat, required: true, ge: f(0), le: f(0.5)},
	{name: "term_months", k: kInt, def: int64(360)},
	{name: "io_months", k: kInt, def: int64(0)},
	{name: "arm_reset_date", k: kDate, nullable: true},
	{name: "arm_index_margin", k: kFloat, nullable: true},
	{name: "monthly_payment_cents", k: kInt, nullable: true},
	{name: "maturity_date", k: kDate, nullable: true},
	{name: "lien_position", k: kInt, def: int64(1)},
	{name: "is_paid_off", k: kBool, def: false},
}}

var loanPatch = func() schema {
	s := patchOf(loanIn, false)
	for i := range s.fields {
		if s.fields[i].name != "rate" {
			s.fields[i].ge, s.fields[i].le = nil, nil
		}
	}
	return s
}()

var yearIn = schema{fields: []spec{
	{name: "gross_rent_cents", k: kInt, def: int64(0)},
	{name: "other_income_cents", k: kInt, def: int64(0)},
	{name: "taxes_cents", k: kInt, def: int64(0)},
	{name: "insurance_cents", k: kInt, def: int64(0)},
	{name: "repairs_cents", k: kInt, def: int64(0)},
	{name: "mgmt_cents", k: kInt, def: int64(0)},
	{name: "utilities_cents", k: kInt, def: int64(0)},
	{name: "hoa_cents", k: kInt, def: int64(0)},
	{name: "other_cents", k: kInt, def: int64(0)},
	{name: "mortgage_interest_cents", k: kInt, def: int64(0)},
	{name: "depreciation_cents", k: kInt, def: int64(0)},
	{name: "depreciation", k: kObj, nullable: true},
}}

var scenarioIn = schema{fields: []spec{
	{name: "name", k: kStr, required: true},
	{name: "horizon_years", k: kInt, def: int64(10), ge: f(1), le: f(40)},
	{name: "assumptions", k: kObj},
}}

var resolveIn = schema{fields: []spec{
	{name: "value", k: kAny, nullable: true},
	{name: "note", k: kStr, def: ""},
	{name: "who", k: kStr, def: "advisor"},
}}

var dismissIn = schema{fields: []spec{
	{name: "note", k: kStr, def: ""},
	{name: "who", k: kStr, def: "advisor"},
}}

var simEvent = schema{fields: []spec{
	{name: "id", k: kStr, nullable: true},
	{name: "year", k: kInt, required: true},
	{name: "type", k: kStr, required: true, choices: simTypes},
	{name: "property_ref", k: kStr, nullable: true},
	{name: "property_id", k: kStr, nullable: true},
	{name: "amount_cents", k: kInt, nullable: true},
	{name: "debt_cents", k: kInt, nullable: true},
	{name: "rate", k: kFloat, nullable: true},
	{name: "note", k: kStr, nullable: true},
}}

var simPropertyIn = schema{fields: []spec{
	{name: "id", k: kStr, nullable: true},
	{name: "nickname", k: kStr, nullable: true},
	{name: "property_type", k: kStr, def: "sfr"},
	{name: "current_value_cents", k: kInt, required: true},
	{name: "debt_cents", k: kInt, def: int64(0)},
	{name: "rate", k: kFloat, def: 0.065},
	{name: "remaining_years", k: kInt, def: int64(30)},
	{name: "noi_cents", k: kInt, nullable: true},
	{name: "gross_rent_cents", k: kInt, nullable: true},
	{name: "expenses_cents", k: kInt, nullable: true},
	{name: "purchase_price_cents", k: kInt, nullable: true},
	{name: "purchase_date", k: kDate, nullable: true},
	{name: "land_pct", k: kFloat, nullable: true},
	{name: "accumulated_depreciation_cents", k: kInt, nullable: true},
}}

var simAssumptions = schema{fields: []spec{
	{name: "appreciation_rate", k: kFloat, def: 0.035},
	{name: "rent_growth", k: kFloat, def: 0.03},
	{name: "expense_growth", k: kFloat, def: 0.03},
	{name: "reinvest_rate", k: kFloat, def: 0.06},
	{name: "cap_rate", k: kFloat, def: 0.055},
	{name: "vacancy_rate", k: kFloat, def: 0.05},
	{name: "filing_status", k: kStr, def: "mfj", choices: filingStatuses},
	{name: "state", k: kStr, def: "CA"},
	{name: "wages_cents", k: kInt, def: int64(0)},
	{name: "other_income_cents", k: kInt, def: int64(0)},
	{name: "magi_cents", k: kInt, def: int64(0)},
	{name: "starting_cash_cents", k: kInt, def: int64(0)},
}}

var monteCarlo = schema{fields: []spec{
	{name: "runs", k: kInt, def: int64(0), ge: f(0), le: f(5000)},
	{name: "appr_sigma", k: kFloat, def: 0.0, ge: f(0), le: f(1)},
	{name: "rent_sigma", k: kFloat, def: 0.0, ge: f(0), le: f(1)},
	{name: "seed", k: kInt, def: int64(7)},
}}
