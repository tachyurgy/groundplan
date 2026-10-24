// Package report ports services/report.py: the client-ready portfolio PDF, generated on the fly per request
// and never stored. Same sections, rows and wording as the reportlab version; the layout is fpdf's own.
package report

import (
	"bytes"
	"fmt"
	"strings"
	"time"

	"github.com/go-pdf/fpdf"
	"github.com/tachyurgy/groundplan/engine-go/dec"
	"github.com/tachyurgy/groundplan/engine-go/jsonx"
)

// PropertyAnalysis is one (property_dict, analysis) pair for the detail pages.
type PropertyAnalysis struct {
	Property *jsonx.Obj
	Analysis *jsonx.Obj
}

type rgb struct{ r, g, b int }

var (
	ink   = rgb{0x1f, 0x29, 0x33}
	muted = rgb{0x61, 0x6e, 0x7c}
	rule  = rgb{0xd9, 0xde, 0xe4}
	chip  = map[string]rgb{"confirmed": {0x2f, 0x6f, 0x4f}, "estimated": {0x8a, 0x6d, 0x1f}, "blocked": {0x9b, 0x2c, 0x2c}}
)

// USD is report.usd: whole dollars with a leading minus.
func USD(c any) string {
	v, ok := cents(c)
	if !ok {
		return "n/a"
	}
	sign := ""
	if v < 0 {
		sign, v = "-", -v
	}
	return sign + "$" + dec.Commas(dec.PyFixed(float64(v)/100, 0))
}

func cents(c any) (int64, bool) {
	switch x := c.(type) {
	case int64:
		return x, true
	case int:
		return int64(x), true
	case *int64:
		if x == nil {
			return 0, false
		}
		return *x, true
	}
	return 0, false
}

func o(v any, path ...string) *jsonx.Obj {
	x, _ := v.(*jsonx.Obj)
	for _, k := range path {
		if x == nil {
			return jsonx.O()
		}
		x, _ = x.MustGet(k).(*jsonx.Obj)
	}
	if x == nil {
		return jsonx.O()
	}
	return x
}

func s(v any) string {
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

func status(fig *jsonx.Obj) string {
	if st, ok := fig.MustGet("status").(string); ok {
		return st
	}
	return "confirmed"
}

type doc struct {
	pdf *fpdf.Fpdf
	tr  func(string) string
}

const (
	left  = 54.0 // 0.75in
	width = 504.0
)

func (d *doc) color(c rgb) { d.pdf.SetTextColor(c.r, c.g, c.b) }

func (d *doc) h1(text string) {
	d.pdf.SetFont("Helvetica", "B", 18)
	d.color(ink)
	d.pdf.MultiCell(width, 22, d.tr(text), "", "L", false)
	d.pdf.Ln(2)
}

func (d *doc) h2(text string) {
	d.pdf.Ln(8)
	d.pdf.SetFont("Helvetica", "B", 12.5)
	d.color(ink)
	d.pdf.MultiCell(width, 16, d.tr(text), "", "L", false)
	d.pdf.Ln(2)
}

func (d *doc) body(text string) {
	d.pdf.SetFont("Helvetica", "", 9.5)
	d.color(ink)
	d.pdf.MultiCell(width, 13, d.tr(text), "", "L", false)
}

func (d *doc) mutedText(text string) {
	d.pdf.SetFont("Helvetica", "", 8)
	d.color(muted)
	d.pdf.MultiCell(width, 10.5, d.tr(text), "", "L", false)
}

// table draws rows; the first row is a header when header is true; status cells are colored.
func (d *doc) table(rows [][]string, widths []float64, header bool, statusCol int) {
	p := d.pdf
	for i, row := range rows {
		isHeader := header && i == 0
		lines := 1
		if len(row) > 1 {
			p.SetFont("Helvetica", "", 8.5)
			lines = len(p.SplitText(d.tr(row[len(row)-1]), widths[len(widths)-1]-4))
			if statusCol >= 0 || len(row) != 2 {
				lines = 1
			}
		}
		h := 13.0 * float64(max(1, lines))
		if p.GetY()+h > 792-60 {
			p.AddPage()
		}
		x, y := left, p.GetY()
		for j, cell := range row {
			p.SetXY(x, y)
			switch {
			case isHeader:
				p.SetFont("Helvetica", "B", 8)
				d.color(muted)
			case j == 0:
				p.SetFont("Helvetica", "", 8.5)
				d.color(ink)
			case j == statusCol:
				p.SetFont("Helvetica", "B", 8)
				c, ok := chip[cell]
				if !ok {
					c = ink
				}
				d.color(c)
			default:
				p.SetFont("Courier", "", 8.5)
				d.color(ink)
			}
			align := "R"
			if j == 0 {
				align = "L"
			}
			if lines > 1 && j == len(row)-1 {
				p.SetFont("Helvetica", "", 8.5)
				p.MultiCell(widths[j], 13, d.tr(cell), "", "L", false)
			} else {
				p.CellFormat(widths[j], h, d.tr(cell), "", 0, align, false, 0, "")
			}
			x += widths[j]
		}
		p.SetY(y + h)
		if isHeader {
			p.SetDrawColor(ink.r, ink.g, ink.b)
			p.SetLineWidth(0.75)
		} else {
			p.SetDrawColor(rule.r, rule.g, rule.b)
			p.SetLineWidth(0.25)
		}
		tot := 0.0
		for _, w := range widths {
			tot += w
		}
		p.Line(left, p.GetY(), left+tot, p.GetY())
	}
}

// obsTable is the observations table: level in bold, the message wrapped.
func (d *doc) obsTable(obs []any) {
	p := d.pdf
	p.SetFont("Helvetica", "B", 8)
	d.color(muted)
	p.CellFormat(50, 13, "", "", 0, "L", false, 0, "")
	p.CellFormat(418, 13, "Observation", "", 1, "L", false, 0, "")
	p.SetDrawColor(ink.r, ink.g, ink.b)
	p.SetLineWidth(0.75)
	p.Line(left, p.GetY(), left+468, p.GetY())
	for _, ov := range obs {
		ob := o(ov)
		msg := d.tr(s(ob.MustGet("message")))
		p.SetFont("Helvetica", "", 9.5)
		lines := p.SplitText(msg, 414)
		h := 13 * float64(max(1, len(lines)))
		if p.GetY()+h > 792-60 {
			p.AddPage()
		}
		y := p.GetY()
		p.SetFont("Helvetica", "B", 7)
		d.color(ink)
		p.SetXY(left, y)
		p.CellFormat(50, 13, strings.ToUpper(s(ob.MustGet("level"))), "", 0, "L", false, 0, "")
		p.SetXY(left+50, y)
		p.SetFont("Helvetica", "", 9.5)
		p.MultiCell(418, 13, msg, "", "L", false)
		p.SetY(y + h)
		p.SetDrawColor(rule.r, rule.g, rule.b)
		p.SetLineWidth(0.25)
		p.Line(left, p.GetY(), left+468, p.GetY())
	}
}

// Render builds the PDF.
func Render(dash *jsonx.Obj, analyses []PropertyAnalysis, firmName string, today time.Time) ([]byte, error) {
	h := o(dash, "household")
	name := s(h.MustGet("name"))
	pdf := fpdf.New("P", "pt", "Letter", "")
	pdf.SetMargins(left, 50, 54)
	pdf.SetAutoPageBreak(true, 54)
	pdf.SetTitle(name+" real estate review", true)
	pdf.SetAuthor(firmName, true)
	pdf.SetCreator("Groundplan", true)
	d := &doc{pdf: pdf, tr: pdf.UnicodeTranslatorFromDescriptor("")}
	pdf.SetFooterFunc(func() {
		pdf.SetY(-36)
		pdf.SetFont("Helvetica", "", 7)
		d.color(muted)
		pdf.SetX(left)
		pdf.CellFormat(300, 10, d.tr(fmt.Sprintf("%s  |  prepared %s  |  Groundplan", name, today.Format("2006-01-02"))), "", 0, "L", false, 0, "")
		pdf.SetX(left + width - 100)
		pdf.CellFormat(100, 10, fmt.Sprintf("page %d", pdf.PageNo()), "", 0, "R", false, 0, "")
	})
	pdf.AddPage()
	goal := s(h.MustGet("goal"))
	if goal == "" {
		goal = "not stated"
	}
	d.h1(name + ": real estate portfolio review")
	d.mutedText(fmt.Sprintf("Tax year %v · %s · filing status %s · goal: %s", h.MustGet("tax_year_latest"), s(h.MustGet("state")),
		strings.ToUpper(s(h.MustGet("filing_status"))), goal))
	pdf.Ln(8)
	met := o(dash, "metrics")
	rows := [][]string{{"Measure", "Amount", "Status"}}
	for _, k := range []string{"total_value", "total_debt", "total_equity", "net_cash_flow", "exit_tax_total", "suspended_losses"} {
		f := o(met, k)
		label := s(f.MustGet("label"))
		if label == "" {
			label = k
		}
		rows = append(rows, []string{label, USD(f.MustGet("value_cents")), status(f)})
	}
	d.h2("Summary")
	d.table(rows, []float64{238, 115, 87}, true, 2)
	d.h2("Summary in plain English")
	nar := o(dash, "narrative")
	for _, para := range strings.Split(s(nar.MustGet("text")), "\n\n") {
		d.body(para)
		pdf.Ln(4)
	}
	d.mutedText(fmt.Sprintf("Narrative source: %s (every number is drawn from the computed figures).", s(nar.MustGet("provider"))))
	if obs, _ := dash.MustGet("observations").([]any); len(obs) > 0 {
		d.h2("Observations")
		d.obsTable(obs)
	}
	prow := [][]string{{"Property", "Value", "Debt", "Equity", "Net cash flow", "Exit tax today"}}
	cards, _ := dash.MustGet("properties").([]any)
	for _, cv := range cards {
		c := o(cv)
		p := o(c, "property")
		val, _ := cents(o(c, "value").MustGet("value_cents"))
		eq, _ := cents(o(c, "equity").MustGet("value_cents"))
		star := ""
		if status(o(c, "net_cash_flow")) != "confirmed" {
			star = "*"
		}
		prow = append(prow, []string{s(p.MustGet("nickname")), USD(val), USD(val - eq), USD(eq),
			USD(o(c, "net_cash_flow").MustGet("value_cents")) + star, USD(o(c, "exit_tax").MustGet("value_cents"))})
	}
	d.h2("Properties")
	d.table(prow, []float64{115, 72, 72, 72, 72, 72}, true, -1)
	pdf.Ln(2)
	d.mutedText("* estimated or blocked: depends on a default assumption, an estimated value, or an unresolved document conflict.")
	for _, pa := range analyses {
		pdf.AddPage()
		p, an := pa.Property, pa.Analysis
		ex, cf, eq := o(an, "exit_tax"), o(an, "cash_flow"), o(an, "equity")
		d.h1(fmt.Sprintf("%s: %s, %s", s(p.MustGet("nickname")), s(p.MustGet("address_line1")), s(p.MustGet("city"))))
		d.mutedText(fmt.Sprintf("%s · %v unit(s) · bought %s for %s · value %s (%s)", s(p.MustGet("property_type")), p.MustGet("units"),
			pyNone(p.MustGet("purchase_date")), USD(p.MustGet("purchase_price_cents")), USD(p.MustGet("current_value_cents")), s(p.MustGet("value_source"))))
		rows := [][]string{{fmt.Sprintf("Cash flow (%v)", an.MustGet("year")), "Amount", "Status"}}
		for _, kl := range [][2]string{{"gross_rent", "Gross rent"}, {"vacancy_loss", "Vacancy"}, {"operating_expenses", "Operating expenses"},
			{"capex_reserve", "Capital reserve"}, {"noi", "Net operating income"}, {"debt_service", "Debt service"}, {"net_cash_flow", "Net cash flow"}} {
			rows = append(rows, []string{kl[1], USD(o(cf, kl[0]).MustGet("value_cents")), status(o(cf, kl[0]))})
		}
		br := o(cf, "schedule_e_bridge")
		rows2 := [][]string{{"Schedule E bridge", "Amount", ""},
			{"Line 21 (income or loss)", USD(o(br, "line21").MustGet("value_cents")), ""},
			{"+ Line 18 depreciation", USD(o(br, "line18_depreciation").MustGet("value_cents")), ""},
			{"- Principal paid", USD(o(br, "principal_paid").MustGet("value_cents")), ""},
			{"- Capital improvements", USD(o(br, "capital_improvements_paid").MustGet("value_cents")), ""},
			{"= Cash flow from the return", USD(o(br, "cash_flow_from_return").MustGet("value_cents")), ""},
			{"Difference vs engine", USD(o(br, "delta_vs_engine").MustGet("value_cents")), ""}}
		d.h2("Cash flow")
		d.table(rows, []float64{238, 115, 87}, true, 2)
		pdf.Ln(6)
		d.table(rows2, []float64{238, 115, 87}, true, -1)
		roe := "n/a"
		if rr, ok := eq.MustGet("roe_rate").(jsonx.Float); ok {
			roe = dec.PyFixed(float64(rr)*100, 1) + "%"
		}
		rows = [][]string{{"Equity", "Amount", "Status"}, {"Value", USD(o(eq, "value").MustGet("value_cents")), status(o(eq, "value"))},
			{"Debt", USD(o(eq, "total_debt").MustGet("value_cents")), status(o(eq, "total_debt"))},
			{"Equity", USD(o(eq, "equity").MustGet("value_cents")), status(o(eq, "equity"))},
			{"Lendable equity (70% LTV)", USD(o(eq, "lendable_equity").MustGet("value_cents")), status(o(eq, "lendable_equity"))},
			{"Return on equity", roe, status(o(eq, "roe"))}}
		d.h2("Equity")
		d.table(rows, []float64{238, 115, 87}, true, 2)
		rows = [][]string{{"If sold at today's value", "Amount", "Status"}}
		for _, kl := range [][2]string{{"sale_price", "Sale price"}, {"selling_costs", "Selling costs"}, {"loan_payoffs", "Loan payoffs"},
			{"net_before_tax", "Net before tax"}, {"adjusted_basis", "Adjusted basis"}, {"total_gain", "Total gain"},
			{"unrecaptured_1250", "Unrecaptured Sec 1250 gain"}, {"ltcg", "Long-term capital gain"},
			{"fed_1250", "Federal tax on 1250 gain (max 25%)"}, {"fed_1245", "Federal tax on 1245 recapture"},
			{"fed_ltcg", "Federal capital gains tax"}, {"niit", "Net investment income tax"}, {"state", "State tax"},
			{"exit_tax_total", "Total exit tax"}, {"net_proceeds", "Net proceeds after tax"}} {
			rows = append(rows, []string{kl[1], USD(o(ex, kl[0]).MustGet("value_cents")), status(o(ex, kl[0]))})
		}
		if pdf.GetY()+16*float64(len(rows))+30 > 792-60 {
			pdf.AddPage()
		}
		d.h2("Exit tax")
		d.table(rows, []float64{238, 115, 87}, true, 2)
		pdf.Ln(2)
		if notes, ok := ex.MustGet("stacking_notes").([]any); ok {
			for _, n := range notes {
				d.mutedText(s(n))
			}
		}
		if obs, ok := an.MustGet("observations").([]any); ok && len(obs) > 0 {
			d.h2("Observations")
			for _, ov := range obs {
				d.body("• " + s(o(ov).MustGet("message")))
			}
		}
	}
	pdf.Ln(14)
	d.mutedText("This report is an analytical illustration for discussion with your advisor. It is not tax or legal advice. Tax figures use " +
		"published federal brackets and a simplified state table and must be verified by a CPA before any transaction. " +
		"Comparisons show trade-offs; no path is recommended by this report.")
	var buf bytes.Buffer
	if err := pdf.Output(&buf); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}

func pyNone(v any) string {
	if v == nil {
		return "None"
	}
	return s(v)
}
