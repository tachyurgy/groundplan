/** Loading states with the same footprint as the content they stand in for, so nothing shifts on arrival (CLS 0). */
export function Sk({ className = '' }: { className?: string }) {
  return <div aria-hidden className={`skeleton ${className}`} />;
}

export function PageSkeleton({ kind }: { kind: 'table' | 'dashboard' | 'split' }) {
  return (
    <div role="status" aria-label="Loading" className="space-y-5">
      <div className="space-y-2">
        <Sk className="h-4 w-28" />
        <Sk className="h-8 w-72 max-w-full" />
        <Sk className="h-4 w-96 max-w-full" />
      </div>
      {kind === 'table' && <Sk className="h-[420px] w-full rounded-lg" />}
      {kind === 'dashboard' && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {[0, 1, 2, 3].map((i) => (
              <Sk key={i} className="h-[104px] rounded-lg" />
            ))}
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Sk className="h-[300px] rounded-lg" />
            <Sk className="h-[300px] rounded-lg" />
          </div>
        </>
      )}
      {kind === 'split' && (
        <div className="grid gap-5 lg:grid-cols-[300px_1fr]">
          <Sk className="h-[460px] rounded-lg" />
          <Sk className="h-[460px] rounded-lg" />
        </div>
      )}
    </div>
  );
}

export function ChartSkeleton({ height }: { height: number }) {
  return <div aria-hidden className="skeleton w-full rounded-md" style={{ height }} />;
}
