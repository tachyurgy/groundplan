/**
 * Route tree (TanStack Router, code-based).
 *
 * Why TanStack Router: search params are typed and validated per route (validateSearch + Zod), so the
 * assumption set, horizon, tab and DST toggle are first-class, shareable, back/forward-able URL state,
 * and `useSearch({ from })` is typed end to end. Loaders take the QueryClient from router context and
 * call ensureQueryData, so data starts loading in parallel with the lazy route chunk and on link hover
 * (defaultPreload: 'intent'). Every route has its own error boundary and pending skeleton.
 */
import { QueryClient } from '@tanstack/react-query';
import { createRootRouteWithContext, createRoute, createRouter, lazyRouteComponent } from '@tanstack/react-router';
import { AppShell } from './components/AppShell';
import { NotFound, RouteError } from './components/RouteError';
import { PageSkeleton } from './components/Skeletons';
import { analysisQuery, dashboardQuery, documentsQuery, evalQuery, findingsQuery, householdsQuery, strategiesQuery, alertsQuery } from './api/queries';
import { twinSearch, documentsSearch, propertySearch, reportsSearch, simulateSearch, strategiesSearch } from './lib/search';

export interface RouterContext {
  queryClient: QueryClient;
}

const rootRoute = createRootRouteWithContext<RouterContext>()({
  component: AppShell,
  notFoundComponent: NotFound,
  errorComponent: RouteError,
});

const page = (load: () => Promise<Record<string, unknown>>, name: string) => lazyRouteComponent(load as never, name as never);

export const householdsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  loader: ({ context }) => context.queryClient.ensureQueryData(householdsQuery()),
  component: page(() => import('./pages/HouseholdsPage'), 'HouseholdsPage'),
  pendingComponent: () => <PageSkeleton kind="table" />,
  errorComponent: RouteError,
});

export const dashboardRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/households/$householdId',
  loader: ({ context, params }) => {
    void context.queryClient.prefetchQuery(alertsQuery(params.householdId));
    return context.queryClient.ensureQueryData(dashboardQuery(params.householdId));
  },
  component: page(() => import('./pages/DashboardPage'), 'DashboardPage'),
  pendingComponent: () => <PageSkeleton kind="dashboard" />,
  errorComponent: RouteError,
});

export const documentsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/households/$householdId/documents',
  validateSearch: documentsSearch,
  loader: ({ context, params }) =>
    Promise.all([context.queryClient.ensureQueryData(documentsQuery(params.householdId)), context.queryClient.ensureQueryData(findingsQuery(params.householdId))]),
  component: page(() => import('./pages/DocumentsPage'), 'DocumentsPage'),
  pendingComponent: () => <PageSkeleton kind="split" />,
  errorComponent: RouteError,
});

export const reportsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/households/$householdId/reports',
  validateSearch: reportsSearch,
  loader: ({ context, params }) => context.queryClient.ensureQueryData(dashboardQuery(params.householdId)),
  component: page(() => import('./pages/ReportsPage'), 'ReportsPage'),
  pendingComponent: () => <PageSkeleton kind="split" />,
  errorComponent: RouteError,
});

export const propertyRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/properties/$propertyId',
  validateSearch: propertySearch,
  // Only the property's base analysis gates first paint; override queries run in the component with
  // keepPreviousData, so editing an assumption never re-suspends the page.
  loader: ({ context, params }) => context.queryClient.ensureQueryData(analysisQuery(params.propertyId, {})),
  component: page(() => import('./pages/PropertyPage'), 'PropertyPage'),
  pendingComponent: () => <PageSkeleton kind="split" />,
  errorComponent: RouteError,
});

export const strategiesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/properties/$propertyId/strategies',
  validateSearch: strategiesSearch,
  loader: ({ context, params }) =>
    Promise.all([context.queryClient.ensureQueryData(strategiesQuery(params.propertyId, {})), context.queryClient.ensureQueryData(analysisQuery(params.propertyId, {}))]),
  component: page(() => import('./pages/StrategiesPage'), 'StrategiesPage'),
  pendingComponent: () => <PageSkeleton kind="split" />,
  errorComponent: RouteError,
});

export const simulateRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/simulate',
  validateSearch: simulateSearch,
  component: page(() => import('./pages/SimulatePage'), 'SimulatePage'),
  pendingComponent: () => <PageSkeleton kind="split" />,
  errorComponent: RouteError,
});

export const evalRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/eval',
  loader: ({ context }) => context.queryClient.prefetchQuery(evalQuery()),
  component: page(() => import('./pages/EvalPage'), 'EvalPage'),
  pendingComponent: () => <PageSkeleton kind="table" />,
  errorComponent: RouteError,
});

export const engineeringRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/engineering',
  component: page(() => import('./pages/EngineeringPage'), 'EngineeringPage'),
  pendingComponent: () => <PageSkeleton kind="table" />,
  errorComponent: RouteError,
});

export const twinRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/twin',
  validateSearch: twinSearch,
  component: page(() => import('./pages/TwinPage'), 'TwinPage'),
  errorComponent: RouteError,
});

const routeTree = rootRoute.addChildren([twinRoute, householdsRoute, dashboardRoute, documentsRoute, reportsRoute, propertyRoute, strategiesRoute, simulateRoute, evalRoute, engineeringRoute]);

export function makeRouter(queryClient: QueryClient) {
  return createRouter({
    routeTree,
    context: { queryClient },
    defaultPreload: 'intent',
    // Query owns caching; the router should always ask it (ensureQueryData is a no-op when fresh).
    defaultPreloadStaleTime: 0,
    defaultPendingMs: 150,
    defaultPendingMinMs: 300,
    scrollRestoration: true,
  });
}

declare module '@tanstack/react-router' {
  interface Register {
    router: ReturnType<typeof makeRouter>;
  }
}
