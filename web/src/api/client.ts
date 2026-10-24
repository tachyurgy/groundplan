/**
 * API client. Live mode (default) calls `/api/v1/*` (Vite proxies /api to http://localhost:8000).
 * Mock mode (`VITE_MOCK=1`) routes the same paths into the in-memory fixture service.
 */
import type { Problem } from './types';

export const API_BASE = '/api/v1';
export const IS_MOCK = import.meta.env.VITE_MOCK === '1' || import.meta.env.VITE_MOCK === 'true';

export class ApiError extends Error {
  constructor(public status: number, public problem: Problem | null, message: string) {
    super(message);
  }
}

type Body = Record<string, unknown> | FormData | unknown[] | undefined;

export async function api<T>(method: string, path: string, body?: Body): Promise<T> {
  if (IS_MOCK) {
    const { mockFetch, MockHttpError } = await import('./mock/router');
    try {
      // structuredClone so callers can never mutate the mock store through a response
      const res = await mockFetch(method, `${API_BASE}${path}`, body);
      return (res === undefined || res === null ? res : JSON.parse(JSON.stringify(res))) as T;
    } catch (e) {
      if (e instanceof MockHttpError) throw new ApiError(e.status, e.problem as Problem, e.problem.detail ?? e.problem.title);
      throw e;
    }
  }
  const init: RequestInit = { method, headers: { Accept: 'application/json' } };
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) {
    init.body = JSON.stringify(body);
    (init.headers as Record<string, string>)['Content-Type'] = 'application/json';
  }
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) {
    let problem: Problem | null = null;
    try {
      problem = (await res.json()) as Problem;
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, problem, problem?.detail ?? problem?.title ?? `${res.status} ${res.statusText}`);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') u.set(k, String(v));
  const s = u.toString();
  return s ? `?${s}` : '';
}

/** URL for binary endpoints (report.pdf, factsheet csv). In mock mode there is no server, so callers stub. */
export function rawUrl(path: string): string {
  return `${API_BASE}${path}`;
}
