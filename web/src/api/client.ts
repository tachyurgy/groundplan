/**
 * The one place the app talks HTTP. Same-origin `/api/v1` in every environment:
 *  - dev: Vite proxies /api to the local API (API_ORIGIN, default :8000)
 *  - production: a Cloudflare Pages Function (functions/api/[[path]].ts) proxies to the stack's API
 *  - mock mode: MSW intercepts /api/v1 in a service worker, so this file does not know mocks exist
 * Every request carries X-Workspace-Id. Errors are RFC 7807 problem+json, surfaced as ApiError.
 * Critical payloads pass a Zod schema; a mismatch throws ContractError naming the bad paths.
 */
import type { z } from 'zod';
import { getWorkspaceId } from '../lib/workspace';

export const API_BASE = '/api/v1';
export const IS_MOCK = import.meta.env.VITE_MOCK === '1' || import.meta.env.VITE_MOCK === 'true';
export const STACK = (import.meta.env.VITE_STACK as 'python' | 'go' | undefined) ?? 'python';

export interface Problem {
  type?: string;
  title?: string;
  status?: number;
  detail?: string;
  instance?: string;
}

export class ApiError extends Error {
  override name = 'ApiError';
  constructor(
    public status: number,
    public problem: Problem | null,
    message: string,
  ) {
    super(message);
  }
  /** Network failure (backend down, offline) rather than an HTTP error. */
  get isNetwork() {
    return this.status === 0;
  }
}

export class ContractError extends Error {
  override name = 'ContractError';
  constructor(
    public endpoint: string,
    public issues: { path: string; message: string }[],
  ) {
    super(`The ${endpoint} response does not match the contract (${issues.length} issue${issues.length === 1 ? '' : 's'}).`);
  }
}

type Body = Record<string, unknown> | FormData | unknown[] | undefined;

export interface RequestOpts<T> {
  body?: Body;
  /** Validate the JSON body; the result type is the schema's output type. */
  schema?: z.ZodType<T>;
  signal?: AbortSignal;
}

export async function api<T = unknown>(method: string, path: string, opts: RequestOpts<T> = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json', 'X-Workspace-Id': getWorkspaceId() };
  const init: RequestInit = { method, headers, signal: opts.signal };
  if (opts.body instanceof FormData) init.body = opts.body;
  else if (opts.body !== undefined) {
    init.body = JSON.stringify(opts.body);
    headers['Content-Type'] = 'application/json';
  }
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, init);
  } catch (e) {
    if ((e as Error)?.name === 'AbortError') throw e;
    throw new ApiError(0, null, 'Could not reach the API. The backend may be restarting or you may be offline.');
  }
  if (!res.ok) {
    let problem: Problem | null = null;
    try {
      problem = (await res.json()) as Problem;
    } catch {
      /* not json (e.g. an HTML 502 from a proxy) */
    }
    const detail = typeof problem?.detail === 'string' ? problem.detail : null;
    throw new ApiError(res.status, problem, detail ?? problem?.title ?? `${res.status} ${res.statusText}`);
  }
  if (res.status === 204) return undefined as T;
  const json: unknown = await res.json();
  if (!opts.schema) return json as T;
  const parsed = opts.schema.safeParse(json);
  if (!parsed.success) {
    const issues = parsed.error.issues.slice(0, 12).map((i) => ({ path: i.path.join('.'), message: i.message }));
    console.error(`[contract] ${method} ${path}`, issues);
    throw new ContractError(`${method} ${path.split('?')[0]}`, issues);
  }
  return parsed.data;
}

export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') u.set(k, String(v));
  const s = u.toString();
  return s ? `?${s}` : '';
}

/**
 * Binary endpoints (report.pdf, CSV). A plain <a href> cannot send X-Workspace-Id, so we fetch with the
 * header and hand the browser a blob URL. Returns the blob so tests can assert the content type.
 */
export async function downloadBinary(path: string, filename: string): Promise<Blob> {
  const res = await fetch(`${API_BASE}${path}`, { headers: { 'X-Workspace-Id': getWorkspaceId() } });
  if (!res.ok) throw new ApiError(res.status, null, `${res.status} ${res.statusText}`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
  return blob;
}
