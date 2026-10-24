import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';
import type { Figure } from '../api/types';
import type { Params } from '../api/hooks';

export interface TraceTarget {
  figure: Figure;
  /** When set, the drawer also fetches GET /properties/{id}/figure/{key} for the full inputs tree. */
  propertyId?: string;
  householdId?: string;
  params?: Params;
}

interface TraceCtx {
  target: TraceTarget | null;
  open: (t: TraceTarget) => void;
  close: () => void;
}

const Ctx = createContext<TraceCtx>({ target: null, open: () => {}, close: () => {} });

export function TraceProvider({ children }: { children: ReactNode }) {
  const [target, setTarget] = useState<TraceTarget | null>(null);
  const open = useCallback((t: TraceTarget) => setTarget(t), []);
  const close = useCallback(() => setTarget(null), []);
  const v = useMemo(() => ({ target, open, close }), [target, open, close]);
  return <Ctx.Provider value={v}>{children}</Ctx.Provider>;
}

export const useTrace = () => useContext(Ctx);

/** Scope (property + params) that FigureValue picks up so every number on a page traces in context. */
export const TraceScope = createContext<Omit<TraceTarget, 'figure'>>({});
export const useTraceScope = () => useContext(TraceScope);
