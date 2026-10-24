/**
 * UI state that is genuinely client-only lives in one small Zustand store: theme preference and the
 * traceability drawer target. Server data never goes here (TanStack Query owns it) and shareable view
 * state never goes here (it lives in the URL search params).
 */
import { create } from 'zustand';
import type { FigureT } from '../api/schemas';
import type { Params } from '../api/queries';

export type ThemePref = 'system' | 'light' | 'dark';

function readPref(): ThemePref {
  try {
    const v = localStorage.getItem('gp.theme');
    return v === 'light' || v === 'dark' ? v : 'system';
  } catch {
    return 'system';
  }
}

const mq = typeof window !== 'undefined' && window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

export function resolveTheme(p: ThemePref): 'light' | 'dark' {
  return p === 'system' ? (mq?.matches ? 'dark' : 'light') : p;
}

function apply(p: ThemePref) {
  if (typeof document !== 'undefined') document.documentElement.dataset.theme = resolveTheme(p);
}

export interface TraceTarget {
  figure: FigureT;
  /** When set, the drawer also fetches GET /properties/{id}/figure/{key} for the full inputs tree. */
  propertyId?: string;
  householdId?: string;
  params?: Params;
  /** element to return focus to when the drawer closes */
  returnFocus?: HTMLElement | null;
}

interface UiState {
  theme: ThemePref;
  resolved: 'light' | 'dark';
  setTheme: (t: ThemePref) => void;
  trace: TraceTarget | null;
  openTrace: (t: TraceTarget) => void;
  closeTrace: () => void;
}

export const useUi = create<UiState>((set, get) => ({
  theme: readPref(),
  resolved: resolveTheme(readPref()),
  setTheme: (theme) => {
    try {
      if (theme === 'system') localStorage.removeItem('gp.theme');
      else localStorage.setItem('gp.theme', theme);
    } catch {
      /* storage blocked: preference lasts for this tab only */
    }
    apply(theme);
    set({ theme, resolved: resolveTheme(theme) });
  },
  trace: null,
  openTrace: (trace) => set({ trace }),
  closeTrace: () => {
    // Return focus to the number that opened the drawer (keyboard users land where they were).
    const back = get().trace?.returnFocus;
    set({ trace: null });
    if (back) requestAnimationFrame(() => back.isConnected && back.focus());
  },
}));

mq?.addEventListener('change', () => {
  const { theme } = useUi.getState();
  if (theme === 'system') {
    apply('system');
    useUi.setState({ resolved: resolveTheme('system') });
  }
});
