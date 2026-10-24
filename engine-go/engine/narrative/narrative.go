// Package narrative ports engine/narrative.py: AI may write the prose, it never touches the math.
//
// TemplateNarrative is the default (offline) provider and produces text byte-identical to Python's. The Go
// service has no LLM provider wired in: GP_LLM_PROVIDER is ignored and the template is always used, which is the
// Python default too. NumberGuard is ported so an LLM provider could be added behind the same check.
package narrative

import (
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/tachyurgy/groundplan/engine-go/jsonx"
)

var (
	moneyRE = regexp.MustCompile(`-?\$\s?\d[\d,]*(?:\.\d+)?(?:\s?[kKmM]\b)?`)
	pctRE   = regexp.MustCompile(`\d+(?:\.\d+)?%`)
)

// Facts is the narrative_facts dict.
type Facts struct {
	HouseholdName string
	Goal          string
	PropertyCount int
	TotalValue    string
	TotalDebt     string
	TotalEquity   string
	NetCashFlow   string
	ExitTaxTotal  string
	Carryforward  *string
	Observations  []string // messages of alert/warn observations
	Strategy      *StrategyFacts
}

// StrategyFacts is the optional strategy_matrix block.
type StrategyFacts struct {
	Property, Horizon, Hold, Sell, Exchange string
}

// Template is TemplateNarrative.generate.
func Template(f *Facts) string {
	var paras []string
	goal := f.Goal
	if goal == "" {
		goal = "their long-term plan"
	}
	paras = append(paras, f.HouseholdName+" holds "+itoa(f.PropertyCount)+" rental properties worth "+f.TotalValue+" with "+
		f.TotalDebt+" of debt, for "+f.TotalEquity+" of equity. Together they produce "+
		f.NetCashFlow+" a year of net cash flow after debt service. The stated goal is to "+strings.TrimRight(goal, ".")+".")
	if len(f.Observations) > 0 {
		top := f.Observations
		if len(top) > 4 {
			top = top[:4]
		}
		paras = append(paras, "What stands out: "+strings.Join(top, " "))
	}
	if f.ExitTaxTotal != "" {
		p := "Selling everything today would trigger about " + f.ExitTaxTotal + " of combined federal, NIIT and " +
			"state tax, which is why the timing and structure of any exit matters as much as the price. "
		if f.Carryforward != nil && *f.Carryforward != "" {
			p += "The household also carries " + *f.Carryforward + " of suspended passive losses that a fully " +
				"taxable sale would release; a 1031 exchange would carry them forward instead."
		}
		paras = append(paras, p)
	}
	if s := f.Strategy; s != nil {
		paras = append(paras, "For "+s.Property+", over "+s.Horizon+" years on identical assumptions: holding "+
			s.Hold+" terminal wealth, selling now "+s.Sell+", a 1031 "+
			"exchange "+s.Exchange+". Holding leads or trails on wealth as the matrix shows, "+
			"selling leads on liquidity and management burden, and the exchange defers tax rather than eliminating it. "+
			"No path is presented as the answer; the trade-offs belong in the conversation.")
	}
	return strings.Join(paras, "\n\n")
}

func itoa(n int) string { return strconv.Itoa(n) }

// Generate is generate_narrative(facts) with the template provider.
func Generate(f *Facts) *jsonx.Obj {
	now := time.Now().UTC().Format("2006-01-02T15:04:05+00:00")
	return jsonx.O("text", Template(f), "provider", "template", "generated_at", now, "guard", "n/a")
}

// NumberGuard returns the dollar amounts / percentages in text that are not in the allowed blob.
func NumberGuard(text, factsBlob string) []string {
	ok := map[string]bool{}
	for _, m := range moneyRE.FindAllString(factsBlob, -1) {
		ok[strings.ReplaceAll(m, " ", "")] = true
	}
	for _, m := range pctRE.FindAllString(factsBlob, -1) {
		ok[m] = true
	}
	var bad []string
	for _, m := range moneyRE.FindAllString(text, -1) {
		if !ok[strings.ReplaceAll(m, " ", "")] {
			bad = append(bad, m)
		}
	}
	for _, m := range pctRE.FindAllString(text, -1) {
		if !ok[m] {
			bad = append(bad, m)
		}
	}
	return bad
}
