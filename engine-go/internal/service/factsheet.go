package service

import (
	"bytes"
	"encoding/csv"
	"fmt"
	"sort"

	"github.com/tachyurgy/groundplan/engine-go/dec"
	"github.com/tachyurgy/groundplan/engine-go/jsonx"
)

// Port of services/factsheet.py: best-effort field mappings for planning platforms (not official integrations).

var platforms = map[string]string{
	"emoney":       "eMoney Advisor (best-effort mapping)",
	"rightcapital": "RightCapital (best-effort mapping)",
	"mgp":          "MoneyGuidePro (best-effort mapping)",
	"json":         "Groundplan native (JSON)",
	"csv":          "Groundplan native (CSV)",
}

var mappings = map[string][][2]string{
	"emoney": {
		{"property.nickname", "Real Estate Asset: Description"},
		{"property.property_type", "Real Estate Asset: Type"},
		{"equity.value", "Real Estate Asset: Market Value"},
		{"exit_tax.adjusted_basis", "Real Estate Asset: Cost Basis"},
		{"equity.total_debt", "Real Estate Asset: Mortgage Liability"},
		{"loan.rate", "Mortgage Liability: Interest Rate"},
		{"loan.monthly_payment", "Mortgage Liability: Monthly Payment"},
		{"cash_flow.noi", "Real Estate Asset: Net Rental Income"},
		{"cash_flow.net_annual", "Real Estate Asset: Net Cash Flow (after debt service)"},
		{"equity.net", "Real Estate Asset: Net Equity"},
		{"appreciation.rate", "Real Estate Asset: Growth Rate"},
	},
	"rightcapital": {
		{"property.nickname", "Property: Name"},
		{"property.property_type", "Property: Type"},
		{"equity.value", "Property: Current Value"},
		{"exit_tax.adjusted_basis", "Property: Cost Basis"},
		{"cash_flow.gross_rent", "Property: Annual Rental Income"},
		{"cash_flow.operating_expenses", "Property: Annual Expenses"},
		{"equity.total_debt", "Property: Mortgage"},
		{"loan.rate", "Mortgage: Interest Rate"},
		{"loan.monthly_payment", "Mortgage: Monthly Payment"},
		{"appreciation.rate", "Property: Appreciation Rate"},
		{"equity.net", "Property: Equity"},
	},
	"mgp": {
		{"property.nickname", "Asset Type: Real Estate - Description"},
		{"equity.value", "Asset Type: Real Estate - Value"},
		{"equity.total_debt", "Asset Type: Real Estate - Debt"},
		{"cash_flow.noi", "Asset Type: Real Estate - Income"},
		{"cash_flow.operating_expenses", "Asset Type: Real Estate - Expenses"},
		{"exit_tax.adjusted_basis", "Asset Type: Real Estate - Cost Basis"},
		{"appreciation.rate", "Asset Type: Real Estate - Growth Rate"},
		{"equity.net", "Asset Type: Real Estate - Net Equity"},
	},
}

func native() [][2]string {
	var out [][2]string
	for _, kv := range mappings["emoney"] {
		out = append(out, [2]string{kv[0], kv[0]})
	}
	for _, k := range []string{"cash_flow.gross_rent", "cash_flow.operating_expenses", "exit_tax.total", "exit_tax.net_proceeds", "equity.lendable"} {
		out = append(out, [2]string{k, k})
	}
	return out
}

type fsVal struct {
	cents  any // *int64 or nil
	text   any // string or nil
	status string
	note   any
}

func figVal(o *jsonx.Obj) (any, string) { return o.MustGet("value_cents"), st(o) }

// Factsheet is factsheet.build(prop, an, loans, fmt).
func Factsheet(prop *jsonx.Obj, an *jsonx.Obj, loans []*jsonx.Obj, format string) *jsonx.Obj {
	cf, eq, ex := obj(an, "cash_flow"), obj(an, "equity"), obj(an, "exit_tax")
	var active []*jsonx.Obj
	for _, ln := range loans {
		if !ln.MustGet("is_paid_off").(bool) {
			active = append(active, ln)
		}
	}
	var first *jsonx.Obj
	if len(active) > 0 {
		s := append([]*jsonx.Obj{}, active...)
		sort.SliceStable(s, func(i, j int) bool { return s[i].MustGet("lien_position").(int) < s[j].MustGet("lien_position").(int) })
		first = s[0]
	}
	var pay int64
	for _, ln := range active {
		if v, ok := ln.MustGet("monthly_payment_cents").(*int64); ok && v != nil {
			pay += *v
		}
	}
	fv := func(o *jsonx.Obj, note any) fsVal { c, s := figVal(o); return fsVal{c, nil, s, note} }
	v := map[string]fsVal{}
	v["property.nickname"] = fsVal{nil, prop.MustGet("nickname"), "confirmed", prop.MustGet("address_line1")}
	v["property.property_type"] = fsVal{nil, prop.MustGet("property_type"), "confirmed", nil}
	v["equity.value"] = fv(obj(eq, "value"), fmt.Sprintf("value source: %s", prop.MustGet("value_source")))
	var debtNote any
	if len(active) > 1 {
		debtNote = fmt.Sprintf("%d active lien(s) summed", len(active))
	}
	v["equity.total_debt"] = fv(obj(eq, "total_debt"), debtNote)
	v["equity.net"] = fv(obj(eq, "equity"), nil)
	v["equity.lendable"] = fv(obj(eq, "lendable_equity"), "70% LTV")
	v["exit_tax.adjusted_basis"] = fv(obj(ex, "adjusted_basis"), "adjusted basis after depreciation (allowed or allowable)")
	v["exit_tax.total"] = fv(obj(ex, "exit_tax_total"), nil)
	v["exit_tax.net_proceeds"] = fv(obj(ex, "net_proceeds"), nil)
	v["cash_flow.gross_rent"] = fv(obj(cf, "gross_rent"), nil)
	v["cash_flow.operating_expenses"] = fv(obj(cf, "operating_expenses"), "excludes mortgage interest and depreciation")
	v["cash_flow.noi"] = fv(obj(cf, "noi"), "NOI before debt service")
	v["cash_flow.net_annual"] = fv(obj(cf, "net_cash_flow"), nil)
	if first != nil {
		r := float64(first.MustGet("rate").(jsonx.Float))
		v["loan.rate"] = fsVal{nil, dec.PyFixed(r*100, 3) + "%", "confirmed", fmt.Sprintf("first lien (%s)", first.MustGet("lender"))}
	} else {
		v["loan.rate"] = fsVal{nil, nil, "confirmed", "no active loan"}
	}
	if pay != 0 {
		v["loan.monthly_payment"] = fsVal{pay, nil, "confirmed", "sum of statement payments"}
	} else {
		v["loan.monthly_payment"] = fsVal{nil, nil, "confirmed", "no payment on file"}
	}
	ap := obj(an, "appreciation")
	rate := float64(ap.MustGet("rate").(jsonx.Float))
	status := "confirmed"
	if ap.MustGet("rate_source") == "default" {
		status = "estimated"
	}
	v["appreciation.rate"] = fsVal{nil, dec.PyFixed(rate*100, 2) + "%", status, "assumption"}
	pairs, ok := mappings[format]
	if !ok {
		pairs = native()
	}
	var rows []any
	for _, kl := range pairs {
		x := v[kl[0]]
		rows = append(rows, jsonx.O("groundplan_key", kl[0], "platform_field", kl[1], "value_cents", x.cents, "value_text", x.text,
			"status", x.status, "note", x.note))
	}
	return jsonx.O("property_id", prop.MustGet("id"), "format", format, "platform_label", platforms[format], "rows", rows,
		"as_of", fmt.Sprintf("%v-12-31", an.MustGet("year")),
		"disclaimer", "Best-effort field mapping by Groundplan; not an official integration. Verify against the platform's "+
			"current import template.")
}

func centsOf(v any) (int64, bool) {
	switch x := v.(type) {
	case *int64:
		if x == nil {
			return 0, false
		}
		return *x, true
	case int64:
		return x, true
	}
	return 0, false
}

func strOrEmpty(v any) string {
	switch x := v.(type) {
	case nil:
		return ""
	case string:
		return x
	case *string:
		if x == nil {
			return ""
		}
		return *x
	}
	return fmt.Sprint(v)
}

// FactsheetCSV is factsheet.to_csv(sheet): Python's csv module (excel dialect, \r\n line endings).
func FactsheetCSV(sheet *jsonx.Obj) string {
	var b bytes.Buffer
	w := csv.NewWriter(&b)
	w.UseCRLF = true
	_ = w.Write([]string{"groundplan_key", "platform_field", "value_dollars", "value_text", "status", "note"})
	for _, rv := range sheet.MustGet("rows").([]any) {
		r := rv.(*jsonx.Obj)
		dollars := ""
		if c, ok := centsOf(r.MustGet("value_cents")); ok {
			dollars = dec.PyFixed(float64(c)/100, 2)
		}
		_ = w.Write([]string{r.MustGet("groundplan_key").(string), r.MustGet("platform_field").(string), dollars,
			strOrEmpty(r.MustGet("value_text")), r.MustGet("status").(string), strOrEmpty(r.MustGet("note"))})
	}
	w.Flush()
	return b.String()
}
