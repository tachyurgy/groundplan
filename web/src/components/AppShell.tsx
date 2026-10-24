import { useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';
import { Link, Outlet, useLocation, useRouterState } from '@tanstack/react-router';
import { AlertDialog } from 'radix-ui';
import { lazy, Suspense, useEffect, useState, type ReactNode } from 'react';
import { IS_MOCK, STACK } from '../api/client';
import { metaQuery, useResetWorkspace } from '../api/queries';
import type { AnalysisT, DashboardT } from '../api/schemas';
import type { HouseholdSummary } from '../api/types';
import { useConnection } from '../lib/connection';
import { useUi, type ThemePref } from '../lib/theme';
import { hasSeenWelcome, markWelcomeSeen } from '../lib/workspace';
import { Banner } from './ui';

const TraceDrawer = lazy(() => import('./TraceDrawer'));

export const TWIN = {
  python: { origin: 'https://gp-python.levelbrook.com', label: 'Python' },
  go: { origin: 'https://gp-go.levelbrook.com', label: 'Go' },
} as const;
const twinOf = STACK === 'go' ? TWIN.python : TWIN.go;

const BACKEND_LABEL: Record<string, string> = { python: 'Python (FastAPI)', go: 'Go (net/http)', mock: 'Mock (MSW, in-browser)' };

function Icon({ d, className = 'h-[18px] w-[18px]' }: { d: string; className?: string }) {
  return (
    <svg viewBox="0 0 20 20" aria-hidden className={className} fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round">
      <path d={d} />
    </svg>
  );
}
const ICONS = {
  households: 'M3 9.5 10 4l7 5.5V16a1 1 0 0 1-1 1h-3.5v-4.5h-5V17H4a1 1 0 0 1-1-1V9.5Z',
  simulate: 'M3 16h14M4.5 13l3.5-4 3 2.5L16 5',
  eval: 'M4 16V9m4 7V5m4 11v-5m4 5V7',
  engineering: 'M7 6 3 10l4 4m6-8 4 4-4 4M11 4 9 16',
};

const NAV = [
  { to: '/', label: 'Households', short: 'Clients', icon: ICONS.households, exact: false, match: (p: string) => p === '/' || p.startsWith('/households') || p.startsWith('/properties') },
  { to: '/simulate', label: 'Simulate', short: 'Simulate', icon: ICONS.simulate, match: (p: string) => p.startsWith('/simulate') },
  { to: '/eval', label: 'Pipeline eval', short: 'Eval', icon: ICONS.eval, match: (p: string) => p.startsWith('/eval') },
  { to: '/engineering', label: 'Engineering notes', short: 'Notes', icon: ICONS.engineering, match: (p: string) => p.startsWith('/engineering') },
] as const;

const TITLES: [RegExp, string][] = [
  [/^\/$/, 'Households'],
  [/^\/households\/[^/]+\/documents/, 'Documents'],
  [/^\/households\/[^/]+\/reports/, 'Reports'],
  [/^\/households\//, 'Portfolio'],
  [/^\/properties\/[^/]+\/strategies/, 'Hold, sell or exchange'],
  [/^\/properties\//, 'Property analysis'],
  [/^\/simulate/, 'Simulate'],
  [/^\/eval/, 'Pipeline eval'],
  [/^\/engineering/, 'Engineering notes'],
];

/** Build the twin-stack URL for the current view. Ids differ per backend and per workspace, so we pass names; /twin on the other side maps them back. */
export function twinHref(qc: QueryClient, pathname: string, searchStr: string): string {
  const u = new URL('/twin', twinOf.origin);
  u.searchParams.set('to', pathname + searchStr);
  const prop = pathname.match(/^\/properties\/([^/]+)/)?.[1];
  const hh = pathname.match(/^\/households\/([^/]+)/)?.[1];
  const households = qc.getQueryData<HouseholdSummary[]>(['gp', 'households']);
  if (prop) {
    const a = qc.getQueryData<AnalysisT>(['gp', 'property', prop, 'analysis', {}]);
    if (a) {
      u.searchParams.set('prop', a.property.nickname);
      const name = households?.find((h) => h.id === a.property.household_id)?.name ?? qc.getQueryData<DashboardT>(['gp', 'household', a.property.household_id, 'dashboard'])?.household.name;
      if (name) u.searchParams.set('hh', name);
    }
  } else if (hh) {
    const name = households?.find((h) => h.id === hh)?.name ?? qc.getQueryData<DashboardT>(['gp', 'household', hh, 'dashboard'])?.household.name;
    if (name) u.searchParams.set('hh', name);
  }
  return u.toString();
}

function ThemeToggle() {
  const theme = useUi((s) => s.theme);
  const setTheme = useUi((s) => s.setTheme);
  const next: Record<ThemePref, ThemePref> = { system: 'light', light: 'dark', dark: 'system' };
  const label = { system: 'System', light: 'Light', dark: 'Dark' }[theme];
  return (
    <button type="button" className="btn btn-ghost h-9 w-9 px-0 text-ink-700 sm:h-8 sm:w-auto sm:px-2" onClick={() => setTheme(next[theme])} aria-label={`Theme: ${label}. Switch to ${next[theme]}`} title={`Theme: ${label}`}>
      <svg viewBox="0 0 20 20" aria-hidden className="h-[18px] w-[18px]" fill="none" stroke="currentColor" strokeWidth={1.6}>
        <circle cx="10" cy="10" r="6.5" />
        <path d="M10 3.5a6.5 6.5 0 0 1 0 13Z" fill="currentColor" />
      </svg>
      <span className="hidden text-xs sm:inline">{label}</span>
    </button>
  );
}

function StackBadge({ compact = false }: { compact?: boolean }) {
  const meta = useQuery(metaQuery());
  const backend = meta.data?.backend ?? (IS_MOCK ? 'mock' : STACK);
  const sha = meta.data?.version ? String(meta.data.version).slice(0, 7) : null;
  const dot = meta.isError ? 'bg-neg-600' : meta.data ? 'bg-pos-600' : 'bg-ink-300';
  return (
    <span data-testid="stack-badge" data-backend={backend} className="inline-flex items-center gap-1.5 text-xs text-ink-500" title={meta.data?.runtime ? `${meta.data.runtime} · ${meta.data.db ?? ''}` : undefined}>
      <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${dot}`} />
      {compact ? (BACKEND_LABEL[backend] ?? backend).split(' ')[0] : <>Backend: {BACKEND_LABEL[backend] ?? backend}</>}
      {sha && !compact && <span className="num text-ink-400">· {sha}</span>}
    </span>
  );
}

function TwinLink({ className = '', children }: { className?: string; children?: ReactNode }) {
  const qc = useQueryClient();
  const loc = useLocation();
  const searchStr = useRouterState({ select: (s) => s.location.searchStr });
  const [href, setHref] = useState(`${twinOf.origin}/`);
  const refresh = () => setHref(twinHref(qc, loc.pathname, searchStr));
  return (
    <a href={href} onPointerEnter={refresh} onFocus={refresh} onClick={(e) => (e.currentTarget.href = twinHref(qc, loc.pathname, searchStr))} data-testid="twin-link" className={className}>
      {children ?? <>Same app on the {twinOf.label} stack →</>}
    </a>
  );
}

function ResetButton() {
  const reset = useResetWorkspace();
  const [open, setOpen] = useState(false);
  return (
    <AlertDialog.Root open={open} onOpenChange={setOpen}>
      <AlertDialog.Trigger asChild>
        <button type="button" className="text-xs font-medium text-ink-500 underline-offset-2 hover:text-ink-900 hover:underline" data-testid="reset-open">
          Reset demo data
        </button>
      </AlertDialog.Trigger>
      <AlertDialog.Portal>
        <AlertDialog.Overlay className="fixed inset-0 z-50 bg-black/30" />
        <AlertDialog.Content className="fixed top-1/2 left-1/2 z-50 w-[min(420px,calc(100vw-32px))] -translate-x-1/2 -translate-y-1/2 rounded-lg bg-surface p-5 shadow-pop">
          <AlertDialog.Title className="text-base font-semibold text-ink-950">Reset this sandbox?</AlertDialog.Title>
          <AlertDialog.Description className="mt-2 text-sm text-ink-700">Uploads, resolved findings and edits in this browser are deleted, and the demo household is seeded again.</AlertDialog.Description>
          <div className="mt-5 flex justify-end gap-2">
            <AlertDialog.Cancel asChild>
              <button type="button" className="btn">
                Keep my data
              </button>
            </AlertDialog.Cancel>
            <button
              type="button"
              className="btn btn-primary"
              data-testid="reset-confirm"
              disabled={reset.isPending}
              onClick={() =>
                reset.mutate(undefined, {
                  onSuccess: () => {
                    setOpen(false);
                    window.location.assign('/');
                  },
                })
              }
            >
              {reset.isPending ? 'Resetting…' : 'Reset demo data'}
            </button>
          </div>
          {reset.isError && <p className="mt-3 text-sm text-neg-600">{reset.error.message}</p>}
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}

function Welcome() {
  const [show, setShow] = useState(() => !hasSeenWelcome());
  if (!show) return null;
  return (
    <div className="mb-4">
      <Banner
        action={
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => {
              markWelcomeSeen();
              setShow(false);
            }}
          >
            Got it
          </button>
        }
      >
        <strong className="font-semibold">Your own sandbox.</strong> No sign-in: this browser gets a private workspace seeded with a demo household. Data is stored for this browser for 14 days; edits and uploads are yours alone.
      </Banner>
    </div>
  );
}

function ConnectionBanner() {
  const { online, apiDown } = useConnection();
  if (online && !apiDown) return null;
  return (
    <div className="mb-4" data-testid="connection-banner">
      <Banner tone="warn">{!online ? 'You are offline. Figures on screen are the last ones loaded.' : 'The API is not answering right now. Figures on screen are the last ones loaded; retrying in the background.'}</Banner>
    </div>
  );
}

export function AppShell() {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  useEffect(() => {
    const t = TITLES.find(([re]) => re.test(pathname))?.[1];
    document.title = t ? `${t} · Groundplan` : 'Groundplan';
  }, [pathname]);
  const trace = useUi((s) => s.trace);
  return (
    <div className="flex min-h-dvh flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[60] focus:rounded focus:bg-surface focus:px-3 focus:py-2 focus:shadow-pop">
        Skip to content
      </a>
      <header className="sticky top-0 z-30 border-b border-ink-100 bg-surface/90 backdrop-blur supports-[backdrop-filter]:bg-surface/80">
        <div className="mx-auto flex h-14 max-w-[1360px] items-center gap-5 px-4 sm:h-12">
          <Link to="/" className="flex shrink-0 items-center gap-2 text-ink-950" aria-label="Groundplan, home">
            <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden>
              <rect width="32" height="32" rx="7" fill="var(--brand-700)" />
              <path d="M7 23V13l9-6 9 6v10" fill="none" stroke="var(--brand-100)" strokeWidth="2.2" strokeLinejoin="round" />
              <path d="M7 23h18M13 23v-6h6v6" fill="none" stroke="var(--brand-500)" strokeWidth="2.2" strokeLinejoin="round" />
            </svg>
            <span className="text-[15px] font-semibold tracking-tight">Groundplan</span>
          </Link>
          <nav aria-label="Main" className="hidden items-center gap-0.5 md:flex">
            {NAV.map((n) => {
              const active = n.match(pathname);
              return (
                <Link key={n.to} to={n.to} aria-current={active ? 'page' : undefined} className={`rounded-md px-2.5 py-1.5 text-sm font-medium transition-colors ${active ? 'bg-ink-100 text-ink-950' : 'text-ink-500 hover:text-ink-950'}`}>
                  {n.label}
                </Link>
              );
            })}
          </nav>
          <div className="ml-auto flex items-center gap-3">
            <span className="hidden lg:inline-flex">
              <StackBadge />
            </span>
            <span className="inline-flex lg:hidden">
              <StackBadge compact />
            </span>
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main id="main" tabIndex={-1} className="mx-auto w-full max-w-[1360px] flex-1 px-4 pt-5 pb-28 outline-none md:pt-6 md:pb-10">
        <ConnectionBanner />
        <Welcome />
        <Outlet />
      </main>

      <footer className="border-t border-ink-100 bg-surface pb-[calc(env(safe-area-inset-bottom)+72px)] md:pb-0">
        <div className="mx-auto flex max-w-[1360px] flex-wrap items-center gap-x-5 gap-y-2 px-4 py-4 text-xs text-ink-500">
          <StackBadge />
          <TwinLink className="font-medium text-brand-600 hover:underline" />
          <Link to="/engineering" className="hover:text-ink-900 hover:underline">
            Engineering notes
          </Link>
          <ResetButton />
          <span className="ml-auto">Demo data only. Not tax or legal advice.</span>
        </div>
      </footer>

      {/* phone navigation: a bottom tab bar within thumb reach */}
      <nav aria-label="Main" className="fixed inset-x-0 bottom-0 z-30 border-t border-ink-100 bg-surface/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden">
        <ul className="grid grid-cols-4">
          {NAV.map((n) => {
            const active = n.match(pathname);
            return (
              <li key={n.to}>
                <Link to={n.to} aria-current={active ? 'page' : undefined} className={`flex h-14 flex-col items-center justify-center gap-0.5 text-[11px] font-medium ${active ? 'text-brand-600' : 'text-ink-500'}`}>
                  <Icon d={n.icon} />
                  {n.short}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      {trace && (
        <Suspense fallback={null}>
          <TraceDrawer />
        </Suspense>
      )}
    </div>
  );
}
