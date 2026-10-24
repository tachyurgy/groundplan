import { createContext, useContext } from 'react';
import type { Params } from '../api/queries';

/** Where the numbers on this part of the page come from, so any FigureValue can open the drawer in context. */
export interface TraceScopeValue {
  propertyId?: string;
  householdId?: string;
  params?: Params;
}
export const TraceScope = createContext<TraceScopeValue>({});
export const useTraceScope = () => useContext(TraceScope);
