/**
 * Server state: TanStack Query v5.
 *
 * - `qk` is the query-key factory. Keys are hierarchical (['gp','household',id,...], ['gp','property',id,...])
 *   so one invalidation can target "everything derived from this household" without listing endpoints.
 *   Assumption overrides live INSIDE the key, so an edit is a new query and the old one stays cached
 *   (dragging a slider back is instant).
 * - `*Query(...)` return `queryOptions`, shared by route loaders (ensureQueryData = prefetch before render),
 *   useSuspenseQuery in components, and useQueries for the sensitivity grid.
 * - Mutations do optimistic updates with rollback where the UI should not wait (resolve / dismiss).
 */
import { keepPreviousData, queryOptions, useMutation, useQueryClient, type QueryClient } from '@tanstack/react-query';
import { api, qs } from './client';
import { AnalysisSchema, DashboardSchema, Figure as FigureSchema, MetaSchema, StrategiesSchema, WorkspaceSchema, type FigureT } from './schemas';
import type { DismissIn, PropertyPatch, ResolveIn, ScenarioIn } from './contract';
import type {
  Alert,
  DocumentDetail,
  Document,
  EvalSummary,
  FactSheet,
  FactSheetFormat,
  Finding,
  HouseholdSummary,
  SimulationRequest,
  SimulationResult,
  UploadResponse,
} from './types';

export type Params = Record<string, string | number | boolean | null | undefined>;

/** Drop undefined so {a:1} and {a:1,b:undefined} hit the same cache entry. */
export function cleanParams(p: Params): Params {
  return Object.fromEntries(Object.entries(p).filter(([, v]) => v !== undefined && v !== null && v !== ''));
}

export const qk = {
  all: ['gp'] as const,
  meta: () => ['gp', 'meta'] as const,
  workspace: () => ['gp', 'workspace'] as const,
  households: () => ['gp', 'households'] as const,
  household: (id: string) => ['gp', 'household', id] as const,
  dashboard: (id: string) => [...qk.household(id), 'dashboard'] as const,
  alerts: (id: string) => [...qk.household(id), 'alerts'] as const,
  documents: (id: string) => [...qk.household(id), 'documents'] as const,
  findings: (id: string) => [...qk.household(id), 'findings'] as const,
  property: (id: string) => ['gp', 'property', id] as const,
  analysis: (id: string, p: Params) => [...qk.property(id), 'analysis', cleanParams(p)] as const,
  strategies: (id: string, p: Params) => [...qk.property(id), 'strategies', cleanParams(p)] as const,
  figure: (id: string, key: string, p: Params) => [...qk.property(id), 'figure', key, cleanParams(p)] as const,
  factsheet: (id: string, f: FactSheetFormat) => [...qk.property(id), 'factsheet', f] as const,
  document: (id: string) => ['gp', 'document', id] as const,
  eval: () => ['gp', 'eval'] as const,
  simulate: (req: SimulationRequest) => ['gp', 'simulate', req] as const,
};

export const metaQuery = () =>
  queryOptions({ queryKey: qk.meta(), queryFn: ({ signal }) => api('GET', '/meta', { schema: MetaSchema, signal }), staleTime: 5 * 60_000, retry: 0 });
export const workspaceQuery = () =>
  queryOptions({ queryKey: qk.workspace(), queryFn: ({ signal }) => api('GET', '/workspace', { schema: WorkspaceSchema, signal }), retry: 0 });

export const householdsQuery = () =>
  queryOptions({ queryKey: qk.households(), queryFn: ({ signal }) => api<HouseholdSummary[]>('GET', '/households', { signal }) });
export const dashboardQuery = (id: string) =>
  queryOptions({ queryKey: qk.dashboard(id), queryFn: ({ signal }) => api('GET', `/households/${id}/dashboard`, { schema: DashboardSchema, signal }) });
export const alertsQuery = (id: string) =>
  queryOptions({ queryKey: qk.alerts(id), queryFn: ({ signal }) => api<Alert[]>('GET', `/households/${id}/alerts`, { signal }) });
export const documentsQuery = (id: string) =>
  queryOptions({ queryKey: qk.documents(id), queryFn: ({ signal }) => api<Document[]>('GET', `/households/${id}/documents`, { signal }) });
export const findingsQuery = (id: string) =>
  queryOptions({ queryKey: qk.findings(id), queryFn: ({ signal }) => api<Finding[]>('GET', `/households/${id}/findings`, { signal }) });

export const analysisQuery = (id: string, p: Params) =>
  queryOptions({
    queryKey: qk.analysis(id, p),
    queryFn: ({ signal }) => api('GET', `/properties/${id}/analysis${qs(cleanParams(p))}`, { schema: AnalysisSchema, signal }),
    placeholderData: keepPreviousData,
  });

export const strategiesQuery = (id: string, p: Params) =>
  queryOptions({
    queryKey: qk.strategies(id, p),
    queryFn: ({ signal }) => api('GET', `/properties/${id}/strategies${qs(cleanParams(p))}`, { schema: StrategiesSchema, signal }),
    placeholderData: keepPreviousData,
    staleTime: 5 * 60_000,
  });

export const figureQuery = (propertyId: string, key: string, p: Params) =>
  queryOptions({
    queryKey: qk.figure(propertyId, key, p),
    queryFn: ({ signal }) =>
      api<FigureT>('GET', `/properties/${propertyId}/figure/${encodeURIComponent(key)}${qs(cleanParams(p))}`, { schema: FigureSchema, signal }),
    retry: 0,
  });

export const documentQuery = (id: string) =>
  queryOptions({ queryKey: qk.document(id), queryFn: ({ signal }) => api<DocumentDetail>('GET', `/documents/${id}`, { signal }) });
export const factSheetQuery = (id: string, format: FactSheetFormat) =>
  queryOptions({
    queryKey: qk.factsheet(id, format),
    queryFn: ({ signal }) => api<FactSheet>('GET', `/properties/${id}/factsheet${qs({ format })}`, { signal }),
  });
export const evalQuery = () => queryOptions({ queryKey: qk.eval(), queryFn: ({ signal }) => api<EvalSummary>('GET', '/eval/latest', { signal }), retry: 0 });

/** Simulation is a pure function of the request body, so it is a query (cached, keepPreviousData), not a mutation. */
export const simulateQuery = (req: SimulationRequest) =>
  queryOptions({
    queryKey: qk.simulate(req),
    queryFn: ({ signal }) => api<SimulationResult>('POST', '/simulate', { body: req as unknown as Record<string, unknown>, signal }),
    placeholderData: keepPreviousData,
    staleTime: Infinity,
  });

// ---------------------------------------------------------------------------- mutations

/** Everything a reconciliation change can unblock: the household's queries and every property query. */
function invalidateDerived(qc: QueryClient, householdId: string) {
  return Promise.all([
    qc.invalidateQueries({ queryKey: qk.household(householdId) }),
    qc.invalidateQueries({ queryKey: ['gp', 'property'] }),
    qc.invalidateQueries({ queryKey: qk.households() }),
  ]);
}

type FindingAction = { id: string; householdId: string; value?: unknown; note: string };

function useFindingMutation(kind: 'resolve' | 'dismiss') {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, value, note }: FindingAction) => {
      const body: ResolveIn | DismissIn =
        kind === 'resolve' ? ({ value, note, who: 'advisor' } satisfies ResolveIn) : ({ note, who: 'advisor' } satisfies DismissIn);
      return api<Finding>('POST', `/findings/${id}/${kind}`, { body: body as Record<string, unknown> });
    },
    // Optimistic: the card leaves the open queue immediately; on error it comes back.
    onMutate: async ({ id, householdId, value, note }) => {
      await qc.cancelQueries({ queryKey: qk.findings(householdId) });
      const prev = qc.getQueryData<Finding[]>(qk.findings(householdId));
      qc.setQueryData<Finding[]>(qk.findings(householdId), (old) =>
        old?.map((f) =>
          f.id === id
            ? {
                ...f,
                status: kind === 'resolve' ? 'resolved' : 'dismissed',
                resolution: { value: value ?? null, who: 'advisor', when: new Date().toISOString(), note },
              }
            : f,
        ),
      );
      return { prev };
    },
    onError: (_e, { householdId }, ctx) => {
      if (ctx?.prev) qc.setQueryData(qk.findings(householdId), ctx.prev);
    },
    onSettled: (_d, _e, { householdId }) => invalidateDerived(qc, householdId),
  });
}
export const useResolveFinding = () => useFindingMutation('resolve');
export const useDismissFinding = () => useFindingMutation('dismiss');

export function useUpload(householdId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData();
      fd.append('file', file, file.name);
      return api<UploadResponse>('POST', `/households/${householdId}/documents`, { body: fd });
    },
    onSuccess: () => invalidateDerived(qc, householdId),
  });
}

export function useSaveScenario(propertyId: string) {
  return useMutation({
    mutationFn: (body: ScenarioIn) =>
      api<{ id: string; name: string }>('POST', `/properties/${propertyId}/scenarios`, { body: body as Record<string, unknown> }),
  });
}

export function usePatchProperty(propertyId: string, householdId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: PropertyPatch) => api('PATCH', `/properties/${propertyId}`, { body: body as Record<string, unknown> }),
    onSuccess: () => Promise.all([qc.invalidateQueries({ queryKey: qk.property(propertyId) }), invalidateDerived(qc, householdId)]),
  });
}

export function useResetWorkspace() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api('POST', '/workspace/reset', { schema: WorkspaceSchema }),
    // A reset changes every id; drop the whole cache rather than refetching stale keys.
    onSuccess: () => qc.resetQueries({ queryKey: qk.all }),
  });
}
