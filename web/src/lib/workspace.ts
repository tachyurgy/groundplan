/**
 * Per-visitor workspace (SPEC §8.1). No logins: a random UUIDv4 kept in localStorage["gp.workspace"]
 * IS the tenant; the API scopes every query by it. Storage can throw (Safari private mode, blocked
 * site data), so we fall back to sessionStorage, then to memory for the life of the tab.
 */
const KEY = 'gp.workspace';
const SEEN_KEY = 'gp.welcomed';
let memory: string | null = null;

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function uuidv4(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  const b = crypto.getRandomValues(new Uint8Array(16));
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = [...b].map((x) => x.toString(16).padStart(2, '0')).join('');
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

function read(store: () => Storage): string | null {
  try {
    return store().getItem(KEY);
  } catch {
    return null;
  }
}
function write(store: () => Storage, v: string): boolean {
  try {
    store().setItem(KEY, v);
    return store().getItem(KEY) === v;
  } catch {
    return false;
  }
}

export function getWorkspaceId(): string {
  if (memory) return memory;
  const existing = read(() => localStorage) ?? read(() => sessionStorage);
  if (existing && UUID_RE.test(existing)) return (memory = existing);
  const id = uuidv4();
  if (!write(() => localStorage, id)) write(() => sessionStorage, id);
  return (memory = id);
}

/** Start over with a brand-new workspace id (the old one is abandoned and swept after 14 idle days). */
export function rotateWorkspaceId(): string {
  memory = null;
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
  return getWorkspaceId();
}

export function hasSeenWelcome(): boolean {
  try {
    return localStorage.getItem(SEEN_KEY) === '1';
  } catch {
    return false;
  }
}
export function markWelcomeSeen() {
  try {
    localStorage.setItem(SEEN_KEY, '1');
  } catch {
    /* ignore */
  }
}
