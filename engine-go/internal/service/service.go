package service

import (
	"context"
	"errors"
	"fmt"
	"strings"

	"github.com/tachyurgy/groundplan/engine-go/dec"
	"github.com/tachyurgy/groundplan/engine-go/engine/models"
	"github.com/tachyurgy/groundplan/engine-go/engine/strategies"
	"github.com/tachyurgy/groundplan/engine-go/internal/store"
	"github.com/tachyurgy/groundplan/engine-go/jsonx"
)

// Config is the subset of settings the services need.
type Config struct {
	MaxWorkspacesPerIPPerDay  int
	MaxHouseholdsPerWorkspace int
	MaxDocumentsPerWorkspace  int
	WorkspaceIdleDays         int
	DevAdvisorID              string
	PipelineURL               string
}

// Service holds the store and settings.
type Service struct {
	Store *store.Store
	Cfg   Config
}

type txKey struct{}

// Q returns the transaction in ctx, or the pool.
func (svc *Service) Q(ctx context.Context) store.Q {
	if tx, ok := ctx.Value(txKey{}).(store.Q); ok {
		return tx
	}
	return svc.Store.Pool
}

// WithTx runs fn with a transaction bound to the context.
func (svc *Service) WithTx(ctx context.Context, fn func(ctx context.Context) error) error {
	if _, ok := ctx.Value(txKey{}).(store.Q); ok {
		return fn(ctx)
	}
	tx, err := svc.Store.Pool.Begin(ctx)
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if err := fn(context.WithValue(ctx, txKey{}, store.Q(tx))); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

func recoverArith(err *error) {
	if r := recover(); r != nil {
		var ae *dec.ArithmeticError
		if e, ok := r.(error); ok && errors.As(e, &ae) {
			*err = &InvalidInput{Msg: ae.Msg}
			return
		}
		panic(r)
	}
}

// StrategyOverrides are the query params /strategies accepts.
var StrategyOverrides = []string{"appreciation_rate", "rent_growth", "expense_growth", "reinvest_rate", "arm_index",
	"replacement_value_cents", "replacement_debt_cents", "cash_taken_cents", "dst", "load_rate", "dst_yield", "replacement_state"}

func pyFloatStr(s string) (float64, error) {
	d, err := dec.Parse(s)
	if err != nil {
		return 0, &InvalidInput{Msg: fmt.Sprintf("could not convert string to float: %s", pyRepr(s))}
	}
	return d.Float64(), nil
}

// Strategies is services.portfolio.strategies(s, p, advisor_id, horizon, params).
func (svc *Service) Strategies(ctx context.Context, p *store.Property, aid string, horizon int, params map[string]string) (out *jsonx.Obj, err error) {
	defer recoverArith(&err)
	pr := map[string]string{}
	for k, v := range params {
		if v != "" {
			pr[k] = v
		}
	}
	an, err := svc.Analyze(ctx, p, aid, 0, 1, []Override{{"arm_index", pr["arm_index"]}})
	if err != nil {
		return nil, err
	}
	o := an.Out()
	statuses := []string{st(obj(o, "cash_flow", "net_cash_flow")), st(obj(o, "equity", "equity")), st(obj(o, "exit_tax", "exit_tax_total"))}
	base := figureStatus(statuses...)
	var reason *string
	if base != "confirmed" {
		var culprits []string
		for i, n := range []string{"cash flow", "equity", "exit tax"} {
			if statuses[i] == base {
				culprits = append(culprits, n)
			}
		}
		r := fmt.Sprintf("base analysis %s: %s", base, strings.Join(culprits, ", "))
		reason = &r
	}
	x := strategies.Exchange{CashTakenCents: 0}
	if v, ok := pr["replacement_value_cents"]; ok {
		i, err := PyInt(v)
		if err != nil {
			return nil, err
		}
		x.ReplacementValueCents = &i
	}
	if v, ok := pr["replacement_debt_cents"]; ok {
		i, err := PyInt(v)
		if err != nil {
			return nil, err
		}
		x.ReplacementDebtCents = &i
	}
	dst := "false"
	if v, ok := pr["dst"]; ok {
		dst = v
	}
	switch strings.ToLower(dst) {
	case "1", "true", "yes", "on":
		x.DST = true
	}
	loadS := models.Defaults["dst_load_rate"].String()
	if v, ok := pr["load_rate"]; ok {
		loadS = v
	}
	yieldS := models.Defaults["dst_yield"].String()
	if v, ok := pr["dst_yield"]; ok {
		yieldS = v
	}
	if x.LoadRate, err = parseDecimal(loadS); err != nil {
		return nil, err
	}
	if x.DSTYield, err = parseDecimal(yieldS); err != nil {
		return nil, err
	}
	if v, ok := pr["cash_taken_cents"]; ok {
		if x.CashTakenCents, err = PyInt(v); err != nil {
			return nil, err
		}
	}
	if v, ok := pr["replacement_state"]; ok {
		s := v
		x.ReplacementState = &s
	}
	a := strategies.NewAssumptions()
	a.HorizonYears = horizon
	optRate := func(k string) (*dec.D, error) {
		v, ok := pr[k]
		if !ok {
			return nil, nil
		}
		d, err := parseDecimal(v)
		if err != nil {
			return nil, err
		}
		return &d, nil
	}
	if a.AppreciationRate, err = optRate("appreciation_rate"); err != nil {
		return nil, err
	}
	if a.RentGrowth, err = optRate("rent_growth"); err != nil {
		return nil, err
	}
	if a.ExpenseGrowth, err = optRate("expense_growth"); err != nil {
		return nil, err
	}
	rrS := models.Defaults["reinvest_rate"].String()
	if v, ok := pr["reinvest_rate"]; ok {
		rrS = v
	}
	if a.ReinvestRate, err = parseDecimal(rrS); err != nil {
		return nil, err
	}
	a.Exchange = x
	r := strategies.Present(strategies.Compare(an.PM, an.HM, a), base, reason)
	assum := r.MustGet("assumptions").(*jsonx.Obj)
	exTerm := r.MustGet("paths").([]any)[2].(*jsonx.Obj).MustGet("terminal").(*jsonx.Obj)
	lf, err := pyFloatStr(loadS)
	if err != nil {
		return nil, err
	}
	yf, err := pyFloatStr(yieldS)
	if err != nil {
		return nil, err
	}
	assum.Set("exchange", jsonx.O("replacement_value_cents", exTerm.MustGet("replacement_value_cents"),
		"replacement_debt_cents", exTerm.MustGet("replacement_debt_cents"), "dst", x.DST, "load_rate", jsonx.Float(lf),
		"dst_yield", jsonx.Float(yf), "cash_taken_cents", x.CashTakenCents))
	for _, k := range []string{"appreciation_rate", "rent_growth", "expense_growth", "reinvest_rate"} {
		assum.Set(k, jsonx.Float(dec.S(assum.MustGet(k).(string)).Float64()))
	}
	assum.Set("sale_year", assum.MustGet("start_year"))
	return r, nil
}
