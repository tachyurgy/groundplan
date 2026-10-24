import { Link } from '@tanstack/react-router';

const cls = 'flex h-11 shrink-0 items-center border-b-2 px-3 text-sm font-medium whitespace-nowrap transition-colors sm:h-10';
const active = { className: `${cls} border-brand-600 text-ink-950` };
const inactive = { className: `${cls} border-transparent text-ink-500 hover:text-ink-900` };

export function HouseholdNav({ householdId }: { householdId: string }) {
  return (
    <nav aria-label="Household sections" className="-mx-4 mb-5 flex overflow-x-auto border-b border-ink-100 px-3 [scrollbar-width:none] sm:mx-0 sm:px-0">
      <Link to="/households/$householdId" params={{ householdId }} activeOptions={{ exact: true }} activeProps={active} inactiveProps={inactive}>
        Portfolio
      </Link>
      <Link to="/households/$householdId/documents" params={{ householdId }} activeProps={active} inactiveProps={inactive}>
        Documents & reconciliation
      </Link>
      <Link to="/households/$householdId/reports" params={{ householdId }} activeProps={active} inactiveProps={inactive}>
        Reports & fact sheets
      </Link>
    </nav>
  );
}
