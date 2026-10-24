// Package api is the HTTP layer: stdlib net/http with Go 1.22 pattern routing, mirroring the FastAPI routers
// path for path and dict for dict. Errors are RFC 7807 problem+json shaped exactly like backend/groundplan/api/problems.py.
package api

import (
	"errors"
	"fmt"
	"log/slog"
	"net/http"

	"github.com/tachyurgy/groundplan/engine-go/dec"
	"github.com/tachyurgy/groundplan/engine-go/internal/service"
	"github.com/tachyurgy/groundplan/engine-go/jsonx"
)

// ProblemCT is the problem+json media type.
const ProblemCT = "application/problem+json"

// Problem mirrors problems.Problem: status, title, detail, type and extra members.
type Problem struct {
	Status int
	Title  string
	Detail string
	Type   string
	Extra  []jsonx.KV
}

func (p *Problem) Error() string { return fmt.Sprintf("%d %s: %s", p.Status, p.Title, p.Detail) }

// NewProblem builds a problem with type about:blank.
func NewProblem(status int, title, detail string) *Problem {
	return &Problem{Status: status, Title: title, Detail: detail, Type: "about:blank"}
}

// T sets the type URI.
func (p *Problem) T(t string) *Problem { p.Type = t; return p }

// With adds an extra member.
func (p *Problem) With(k string, v any) *Problem {
	p.Extra = append(p.Extra, jsonx.KV{K: k, V: v})
	return p
}

func notFound(what, id string) *Problem {
	return NewProblem(404, what+" not found", fmt.Sprintf("No %s %s in this workspace", lower(what), pyRepr(id))).
		T("https://groundplan.dev/problems/not-found")
}

func lower(s string) string {
	b := []byte(s)
	for i, c := range b {
		if c >= 'A' && c <= 'Z' {
			b[i] = c + 32
		}
	}
	return string(b)
}

// pyRepr is repr(str) for ids in messages.
func pyRepr(s string) string {
	hasSingle, hasDouble := false, false
	for _, c := range s {
		if c == '\'' {
			hasSingle = true
		}
		if c == '"' {
			hasDouble = true
		}
	}
	if hasSingle && !hasDouble {
		return `"` + s + `"`
	}
	out := []byte{'\''}
	for i := 0; i < len(s); i++ {
		c := s[i]
		switch c {
		case '\\':
			out = append(out, '\\', '\\')
		case '\'':
			out = append(out, '\\', '\'')
		case '\n':
			out = append(out, '\\', 'n')
		case '\t':
			out = append(out, '\\', 't')
		case '\r':
			out = append(out, '\\', 'r')
		default:
			out = append(out, c)
		}
	}
	return string(append(out, '\''))
}

// writeProblem writes problem_response(status, title, detail, instance, type, **extra).
func writeProblem(w http.ResponseWriter, r *http.Request, p *Problem) {
	body := jsonx.O("type", p.Type, "title", p.Title, "status", p.Status, "instance", r.URL.Path)
	if p.Detail != "" {
		body.Set("detail", p.Detail)
	}
	for _, kv := range p.Extra {
		body.Set(kv.K, kv.V)
	}
	b := jsonx.MustMarshal(body)
	w.Header().Set("Content-Type", ProblemCT)
	w.Header().Set("Content-Length", fmt.Sprint(len(b)))
	w.WriteHeader(p.Status)
	_, _ = w.Write(b)
}

// writeErr maps any error onto a problem (Problem, workspace errors, invalid input = 422, else 500).
func writeErr(w http.ResponseWriter, r *http.Request, err error, invalidTitle string) {
	var p *Problem
	var we *service.WorkspaceError
	var ii *service.InvalidInput
	var ae *dec.ArithmeticError
	switch {
	case errors.As(err, &p):
		writeProblem(w, r, p)
	case errors.As(err, &we):
		writeProblem(w, r, NewProblem(we.Status, we.Title, we.Detail).T("https://groundplan.dev/problems/"+we.Kind))
	case errors.As(err, &ii) && invalidTitle != "":
		writeProblem(w, r, NewProblem(422, invalidTitle, ii.Msg))
	case errors.As(err, &ae) && invalidTitle != "":
		writeProblem(w, r, NewProblem(422, invalidTitle, ae.Msg))
	default:
		slog.Error("unhandled_error", "path", r.URL.Path, "err", err.Error(), "request_id", requestID(r.Context()))
		writeProblem(w, r, NewProblem(500, "Internal Server Error", ""))
	}
}

// validationProblem is the RequestValidationError handler's body.
func validationProblem(errs []any) *Problem {
	return NewProblem(422, "Validation failed", fmt.Sprintf("%d invalid field(s)", len(errs))).
		T("https://groundplan.dev/problems/validation").With("errors", errs)
}

// verr builds one pydantic-style error {loc, msg, type}.
func verr(loc []any, msg, typ string) *jsonx.Obj { return jsonx.O("loc", loc, "msg", msg, "type", typ) }
