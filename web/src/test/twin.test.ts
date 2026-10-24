import { describe, expect, it } from 'vitest';
import { QueryClient } from '@tanstack/react-query';
import { resolveTwinPath } from '../pages/TwinPage';
import { twinHref } from '../components/AppShell';
import { analysisQuery, householdsQuery } from '../api/queries';

describe('twin-stack link', () => {
  it('carries names, not ids, plus the full search string', async () => {
    const qc = new QueryClient();
    await qc.fetchQuery(householdsQuery());
    await qc.fetchQuery(analysisQuery('p3_elm', {}));
    const href = new URL(twinHref(qc, '/properties/p3_elm/strategies', '?horizon=15&dst=true'));
    expect(href.pathname).toBe('/twin');
    expect(href.searchParams.get('to')).toBe('/properties/p3_elm/strategies?horizon=15&dst=true');
    expect(href.searchParams.get('prop')).toBe('Elm SFR');
    expect(href.searchParams.get('hh')).toBe('Okafor-Lindqvist');
  });

  it('maps the names back to this stack’s ids and keeps the assumptions', async () => {
    const qc = new QueryClient();
    expect(await resolveTwinPath(qc, '/properties/SOME-OTHER-ID/strategies?horizon=15&dst=true', 'Okafor-Lindqvist', 'Elm SFR')).toBe(
      '/properties/p3_elm/strategies?horizon=15&dst=true',
    );
    expect(await resolveTwinPath(qc, '/households/OTHER/documents?doc=x', 'okafor-lindqvist')).toBe('/households/hh_okafor_lindqvist/documents?doc=x');
    expect(await resolveTwinPath(qc, '/simulate?years=20')).toBe('/simulate?years=20');
  });
});
