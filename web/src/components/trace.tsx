import { useCallback, useMemo, useState, type ReactNode } from 'react';
import { TraceContext, type TraceTarget } from '../lib/traceContext';

export function TraceProvider({ children }: { children: ReactNode }) {
  const [target, setTarget] = useState<TraceTarget | null>(null);
  const open = useCallback((t: TraceTarget) => setTarget(t), []);
  const close = useCallback(() => setTarget(null), []);
  const v = useMemo(() => ({ target, open, close }), [target, open, close]);
  return <TraceContext.Provider value={v}>{children}</TraceContext.Provider>;
}
