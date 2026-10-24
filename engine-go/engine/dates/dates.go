// Package dates is the tiny subset of Python's datetime.date the engine uses (calendar dates, UTC midnight).
package dates

import "time"

// Date is a calendar date.
type Date = time.Time

// New is date(y, m, d).
func New(y, m, d int) Date { return time.Date(y, time.Month(m), d, 0, 0, 0, 0, time.UTC) }

// Parse is date.fromisoformat (the first 10 characters).
func Parse(s string) (Date, error) {
	if len(s) > 10 {
		s = s[:10]
	}
	return time.Parse("2006-01-02", s)
}

// MustParse panics on a bad date.
func MustParse(s string) Date {
	d, err := Parse(s)
	if err != nil {
		panic(err)
	}
	return d
}

// ISO is date.isoformat().
func ISO(d Date) string { return d.Format("2006-01-02") }

// Days is (a - b).days.
func Days(a, b Date) int { return int(a.Sub(b).Hours() / 24) }

// Ptr returns a pointer to d.
func Ptr(d Date) *Date { return &d }

// ISOPtr formats an optional date (nil -> nil).
func ISOPtr(d *Date) any {
	if d == nil {
		return nil
	}
	return ISO(*d)
}

// Before reports (a.year, a.month) < (b.year, b.month) etc.
func YM(d Date) int { return d.Year()*12 + int(d.Month()) - 1 }
