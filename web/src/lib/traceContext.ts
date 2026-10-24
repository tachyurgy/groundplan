import { createContext, useContext } from 'react';
import type { Figure } from '../api/types';
import type { Params } from '../api/hooks';

export interface TraceTarget {
  figure: Figure;
  /** When set, the drawer also fetches GET /properties/{id}/figure/{key} for the full inputs tree. */
  propertyId?: string;
  householdId?: string;
  params?: Params;
}

export interface TraceCtx {
  target: TraceTarget | null;
  open: (t: TraceTarget) => void;
  close: () => void;
}

export const TraceContext = createContext<TraceCtx>({ target: null, open: () => {}, close: () => {} });
export const useTrace = () => useContext(TraceContext);

/** Scope (property + params) that FigureValue picks up so every number on a page traces in context. */
export const TraceScope = createContext<Omit<TraceTarget, 'figure'>>({});
export const useTraceScope = () => useContext(TraceScope);
