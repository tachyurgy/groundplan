import { useQueryClient } from '@tanstack/react-query';
import { getRouteApi, useRouter } from '@tanstack/react-router';
import { useEffect, useState } from 'react';
import { dashboardQuery, householdsQuery } from '../api/queries';
import type { QueryClient } from '@tanstack/react-query';

const route = getRouteApi('/twin');

/**
 * Map a path from the other stack onto this one. Household and property ids are per-backend and
 * per-workspace, so the twin link carries names; we look them up here and keep the search string
 * (all the assumptions) as is.
 */
export async function resolveTwinPath(qc: QueryClient, to: string, hh?: string, prop?: string): Promise<string> {
  const url = new URL(to.startsWith('/') ? to : `/${to}`, 'http://x');
  const path = url.pathname;
  const needsHh = /^\/households\/[^/]+/.test(path);
  const needsProp = /^\/properties\/[^/]+/.test(path);
  if (!needsHh && !needsProp) return path + url.search;
  const households = await qc.fetchQuery(householdsQuery());
  const household = (hh && households.find((h) => h.name.toLowerCase() === hh.toLowerCase())) || households[0];
  if (!household) return '/';
  if (needsHh) return path.replace(/^\/households\/[^/]+/, `/households/${household.id}`) + url.search;
  const candidates = [household, ...households.filter((h) => h.id !== household.id)];
  for (const h of candidates) {
    const d = await qc.fetchQuery(dashboardQuery(h.id));
    const card = d.properties.find((c) => c.property.nickname.toLowerCase() === (prop ?? '').toLowerCase());
    if (card) return path.replace(/^\/properties\/[^/]+/, `/properties/${card.property.id}`) + url.search;
  }
  return `/households/${household.id}`;
}

export function TwinPage() {
  const { to = '/', hh, prop } = route.useSearch();
  const qc = useQueryClient();
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    resolveTwinPath(qc, to, hh, prop)
      .then((p) => live && router.history.replace(p))
      .catch((e: unknown) => live && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      live = false;
    };
  }, [qc, router, to, hh, prop]);
  return (
    <div className="mx-auto my-16 max-w-md text-center text-sm text-ink-700" role="status">
      {error ? (
        <>
          Could not open the matching view on this stack: {error}.{' '}
          <a className="text-brand-600 underline" href="/">
            Go to households
          </a>
        </>
      ) : (
        <>Opening the same view on this stack{prop ? ` (${prop})` : hh ? ` (${hh})` : ''}…</>
      )}
    </div>
  );
}
