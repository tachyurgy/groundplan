import type { AnalysisT, FigureT } from '../api/schemas';
import { BracketFill } from '../charts/BracketFill';
import { C, ChartFrame } from '../charts/kit';
import { Waterfall, type WaterfallStep } from '../charts/Waterfall';
import { formatCents, formatRate } from '../lib/money';

type Exit = AnalysisT['exit_tax'];
const mag = (f: FigureT) => Math.abs(f.value_cents);

export const TAX_PARTS = [
  { k: 'fed_1250', label: '§1250 recapture (≤25%)', short: '§1250', color: C.s1 },
  { k: 'fed_1245', label: '§1245 recapture', short: '§1245', color: C.s2 },
  { k: 'fed_ltcg', label: 'Federal LTCG', short: 'LTCG', color: C.s3 },
  { k: 'niit', label: 'NIIT 3.8%', short: 'NIIT', color: C.s4 },
  { k: 'state', label: 'State', short: 'State', color: C.s5 },
] as const;

/** price → selling costs → loan payoff → §1250 → §1245 → LTCG → NIIT → state → net proceeds */
export function SaleWaterfall({ x, title = 'Where the sale price goes' }: { x: Exit; title?: string }) {
  const steps: WaterfallStep[] = [
    { label: 'Sale price', value: mag(x.sale_price), kind: 'total', figure: x.sale_price },
    { label: 'Selling costs', value: -mag(x.selling_costs), kind: 'step', color: C.muted, figure: x.selling_costs },
    { label: 'Loan payoff', value: -mag(x.loan_payoffs), kind: 'step', color: C.muted, figure: x.loan_payoffs },
    ...TAX_PARTS.filter((p) => x[p.k].value_cents !== 0).map((p) => ({ label: p.short === 'State' ? (x.state.label?.replace(/^State/, 'State tax') ?? 'State tax') : p.short, value: -mag(x[p.k]), kind: 'step' as const, color: p.color, figure: x[p.k] })),
    { label: 'Net proceeds', value: x.net_proceeds.value_cents, kind: 'total', figure: x.net_proceeds },
  ];
  const keep = x.sale_price.value_cents > 0 ? x.net_proceeds.value_cents / x.sale_price.value_cents : 0;
  return (
    <ChartFrame
      testId="chart-waterfall"
      title={title}
      summary={`Of a ${formatCents(mag(x.sale_price))} sale, ${formatCents(x.net_proceeds.value_cents)} (${formatRate(keep, 0)}) reaches the client after costs, the loan payoff and ${formatCents(mag(x.exit_tax_total))} of tax.`}
      height={steps.length * 30 + 4}
      table={{ columns: [{ key: 'label', label: 'Step' }, { key: 'value', label: 'Amount', money: true }], rows: steps.map((s) => ({ label: s.label, value: s.value })) }}
    >
      <Waterfall steps={steps} />
    </ChartFrame>
  );
}

export function TaxLayersBar({ x }: { x: Exit }) {
  const total = Math.max(1, TAX_PARTS.reduce((s, p) => s + mag(x[p.k]), 0));
  const parts = TAX_PARTS.map((p) => ({ ...p, v: mag(x[p.k]) })).filter((p) => p.v > 0);
  return (
    <ChartFrame
      testId="chart-tax-layers"
      title="Exit tax by layer"
      summary={`${formatCents(mag(x.exit_tax_total))} in total; the largest layer is ${[...parts].sort((a, b) => b.v - a.v)[0]?.label ?? 'none'}.`}
      legend={parts.map((p) => ({ label: p.label, color: p.color, value: formatCents(p.v) }))}
      height={40}
      table={{ columns: [{ key: 'label', label: 'Layer' }, { key: 'v', label: 'Tax', money: true }], rows: parts.map((p) => ({ label: p.label, v: p.v })) }}
    >
      <div className="flex h-[30px] gap-[2px] overflow-hidden rounded" data-testid="tax-layer-bar">
        {parts.map((p) => (
          <div key={p.k} title={`${p.label}: ${formatCents(p.v)}`} className="h-full first:rounded-l last:rounded-r" style={{ width: `${(p.v / total) * 100}%`, background: p.color }} />
        ))}
      </div>
    </ChartFrame>
  );
}

export function StackingExplainer({ x }: { x: Exit }) {
  const ordinary = typeof x.ordinary_taxable_other === 'number' ? x.ordinary_taxable_other : (x.ordinary_taxable_other?.value_cents ?? null);
  const hasLayers = ordinary !== null && ((x.layers_1250?.length ?? 0) > 0 || (x.layers_ltcg?.length ?? 0) > 0);
  return (
    <div className="space-y-4">
      {hasLayers && (
        <ChartFrame
          testId="chart-bracket-fill"
          title="How the gain fills the brackets"
          summary="Ordinary income fills the brackets first; §1250 gain stacks on top at the bracket rate capped at 25%; long-term gain lands last at 0, 15 or 20% depending on where it starts."
          height={84}
          table={{
            columns: [
              { key: 'layer', label: 'Layer' },
              { key: 'rate', label: 'Rate', align: 'right' },
              { key: 'amount', label: 'Income', money: true },
              { key: 'tax', label: 'Tax', money: true },
            ],
            rows: [
              { layer: 'Other ordinary income', rate: '—', amount: ordinary!, tax: '' },
              ...(x.layers_1245 ?? []).map((l) => ({ layer: '§1245', rate: formatRate(l.rate, 0), amount: l.amount_cents, tax: l.tax_cents })),
              ...(x.layers_1250 ?? []).map((l) => ({ layer: '§1250', rate: formatRate(l.rate, 0), amount: l.amount_cents, tax: l.tax_cents })),
              ...(x.layers_ltcg ?? []).map((l) => ({ layer: 'LTCG', rate: formatRate(l.rate, 0), amount: l.amount_cents, tax: l.tax_cents })),
            ],
          }}
        >
          <BracketFill ordinary={ordinary!} l1245={x.layers_1245 ?? []} l1250={x.layers_1250 ?? []} ltcg={x.layers_ltcg ?? []} />
        </ChartFrame>
      )}
      <div>
        <h3 className="mb-2">The stacking, step by step</h3>
        <ol className="space-y-2 text-xs leading-relaxed text-ink-700">
          {x.stacking_notes.map((n, i) => (
            <li key={i} className="flex gap-2.5">
              <span className="num mt-px h-5 w-5 shrink-0 rounded-full bg-ink-100 text-center text-[11px] leading-5 text-ink-700">{i + 1}</span>
              <span className="min-w-0 break-words">{n}</span>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}
