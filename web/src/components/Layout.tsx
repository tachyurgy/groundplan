import { NavLink, Outlet, useMatch } from 'react-router-dom';
import { IS_MOCK } from '../api/client';
import { TraceDrawer } from './TraceDrawer';

const link = ({ isActive }: { isActive: boolean }) => `rounded px-2.5 py-1.5 text-sm font-medium transition-colors ${isActive ? 'bg-white/10 text-white' : 'text-ink-300 hover:text-white'}`;

export function Layout() {
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 bg-ink-950">
        <div className="mx-auto flex h-12 max-w-[1320px] items-center gap-4 px-4">
          <NavLink to="/" className="flex items-center gap-2 text-white">
            <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden>
              <rect x="1" y="9" width="16" height="8" rx="1" fill="#2a6aa8" />
              <path d="M2 9 L9 2 L16 9" fill="none" stroke="#a7adbb" strokeWidth="1.6" />
            </svg>
            <span className="text-[15px] font-semibold tracking-tight">Groundplan</span>
          </NavLink>
          <nav className="flex items-center gap-1 overflow-x-auto">
            <NavLink to="/" end className={link}>
              Households
            </NavLink>
            <NavLink to="/simulate" className={link}>
              Simulate
            </NavLink>
            <NavLink to="/eval" className={link}>
              Pipeline eval
            </NavLink>
          </nav>
          <div className="ml-auto flex items-center gap-2">
            {IS_MOCK ? (
              <span className="rounded bg-est-100 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-est-600" title="VITE_MOCK=1: in-memory fixture service, no API calls">
                Mock data
              </span>
            ) : (
              <span className="hidden text-[11px] text-ink-400 sm:inline">API /api/v1 → :8000</span>
            )}
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-[1320px] px-4 py-6">
        <Outlet />
      </main>
      <TraceDrawer />
    </div>
  );
}

export function HouseholdNav({ id }: { id: string }) {
  const onDash = useMatch('/households/:id');
  const sub = ({ isActive }: { isActive: boolean }) => `-mb-px border-b-2 px-3 py-2 text-sm font-medium ${isActive ? 'border-brand-600 text-ink-950' : 'border-transparent text-ink-500 hover:text-ink-900'}`;
  return (
    <nav className="mb-5 flex gap-1 overflow-x-auto border-b border-ink-200">
      <NavLink to={`/households/${id}`} end className={() => sub({ isActive: !!onDash })}>
        Portfolio
      </NavLink>
      <NavLink to={`/households/${id}/documents`} className={sub}>
        Documents & reconciliation
      </NavLink>
      <NavLink to={`/households/${id}/reports`} className={sub}>
        Reports & fact sheets
      </NavLink>
    </nav>
  );
}
