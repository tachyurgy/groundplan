import { useMutation, useQuery, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import { api, qs } from './client';
import type {
  Alert,
  Dashboard,
  DocumentDetail,
  Document,
  EvalSummary,
  FactSheet,
  FactSheetFormat,
  Figure,
  Finding,
  HouseholdSummary,
  PropertyAnalysis,
  SimulationRequest,
  SimulationResult,
  StrategyComparison,
  UploadResponse,
} from './types';

export type Params = Record<string, string | number | boolean | null | undefined>;

export const qk = {
  households: ['households'] as const,
  dashboard: (id: string) => ['dashboard', id] as const,
  alerts: (id: string) => ['alerts', id] as const,
  analysis: (id: string, p: Params) => ['analysis', id, p] as const,
  strategies: (id: string, p: Params) => ['strategies', id, p] as const,
  figure: (id: string, key: string, p: Params) => ['figure', id, key, p] as const,
  documents: (hh: string) => ['documents', hh] as const,
  document: (id: string) => ['document', id] as const,
  findings: (hh: string, status?: string) => ['findings', hh, status ?? 'all'] as const,
  factsheet: (id: string, f: FactSheetFormat) => ['factsheet', id, f] as const,
  eval: ['eval'] as const,
};

export const useHouseholds = () => useQuery({ queryKey: qk.households, queryFn: () => api<HouseholdSummary[]>('GET', '/households') });
export const useDashboard = (id: string) => useQuery({ queryKey: qk.dashboard(id), queryFn: () => api<Dashboard>('GET', `/households/${id}/dashboard`) });
export const useAlerts = (id: string) => useQuery({ queryKey: qk.alerts(id), queryFn: () => api<Alert[]>('GET', `/households/${id}/alerts`) });

/** Analysis re-queries on every assumption change; previous data stays on screen while recomputing. */
export const useAnalysis = (id: string, params: Params) =>
  useQuery({ queryKey: qk.analysis(id, params), queryFn: () => api<PropertyAnalysis>('GET', `/properties/${id}/analysis${qs(params)}`), placeholderData: keepPreviousData });

export const useStrategies = (id: string, params: Params) =>
  useQuery({ queryKey: qk.strategies(id, params), queryFn: () => api<StrategyComparison>('GET', `/properties/${id}/strategies${qs(params)}`), placeholderData: keepPreviousData });

export const useFigure = (propertyId: string | null, key: string | null, params: Params) =>
  useQuery({
    queryKey: qk.figure(propertyId ?? '', key ?? '', params),
    queryFn: () => api<Figure>('GET', `/properties/${propertyId}/figure/${encodeURIComponent(key!)}${qs(params)}`),
    enabled: !!propertyId && !!key,
  });

export const useDocuments = (hh: string) => useQuery({ queryKey: qk.documents(hh), queryFn: () => api<Document[]>('GET', `/households/${hh}/documents`) });
export const useDocument = (id: string | null) => useQuery({ queryKey: qk.document(id ?? ''), queryFn: () => api<DocumentDetail>('GET', `/documents/${id}`), enabled: !!id });
export const useFindings = (hh: string, status?: string) =>
  useQuery({ queryKey: qk.findings(hh, status), queryFn: () => api<Finding[]>('GET', `/households/${hh}/findings${qs({ status })}`) });
export const useFactSheet = (id: string | null, format: FactSheetFormat) =>
  useQuery({ queryKey: qk.factsheet(id ?? '', format), queryFn: () => api<FactSheet>('GET', `/properties/${id}/factsheet${qs({ format })}`), enabled: !!id });
export const useEval = () => useQuery({ queryKey: qk.eval, queryFn: () => api<EvalSummary>('GET', '/eval/latest'), retry: false });

/** Anything that changes reconciled data invalidates every derived query (figures may unblock). */
function useInvalidateAll() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries();
}

export function useUpload(hh: string) {
  const inv = useInvalidateAll();
  return useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData();
      fd.append('file', file, file.name);
      return api<UploadResponse>('POST', `/households/${hh}/documents`, fd);
    },
    onSuccess: inv,
  });
}

export function useResolveFinding() {
  const inv = useInvalidateAll();
  return useMutation({ mutationFn: ({ id, value, note }: { id: string; value: unknown; note: string }) => api<Finding>('POST', `/findings/${id}/resolve`, { value, note }), onSuccess: inv });
}

export function useDismissFinding() {
  const inv = useInvalidateAll();
  return useMutation({ mutationFn: ({ id, note }: { id: string; note: string }) => api<Finding>('POST', `/findings/${id}/dismiss`, { note }), onSuccess: inv });
}

export function useSimulate() {
  return useMutation({ mutationFn: (req: SimulationRequest) => api<SimulationResult>('POST', '/simulate', req as unknown as Record<string, unknown>) });
}
