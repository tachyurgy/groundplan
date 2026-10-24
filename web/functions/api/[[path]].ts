/**
 * Cloudflare Pages Function: same-origin proxy for /api/* to this stack's API.
 *
 * Each Pages project sets API_ORIGIN (gp-python -> https://gp-python-api.levelbrook.com,
 * gp-go -> https://gp-go-api.levelbrook.com). The browser never talks to the API host directly, so
 * there is no CORS preflight and the API host can change without rebuilding the front end.
 *
 * Forwarded: method, query string, body (streamed, so multipart uploads pass through untouched),
 * Content-Type, Accept, X-Workspace-Id, and the visitor IP as X-Forwarded-For (from CF-Connecting-IP)
 * so the API's per-IP limits see the real client. Nothing else from the browser is forwarded
 * (no cookies, no auth headers).
 */
interface Env {
  API_ORIGIN?: string;
  /** shared secret: lets the API trust X-Client-IP from this proxy (Cloudflare rewrites CF-Connecting-IP on subrequests) */
  PROXY_KEY?: string;
}
interface Ctx {
  request: Request;
  env: Env;
}

const FORWARD = ['content-type', 'accept', 'x-workspace-id'];
const PASS_BACK = ['content-type', 'content-disposition', 'cache-control', 'retry-after', 'x-request-id'];

export async function onRequest({ request, env }: Ctx): Promise<Response> {
  const origin = (env.API_ORIGIN ?? '').replace(/\/+$/, '');
  if (!origin) {
    return Response.json({ type: 'about:blank', title: 'API not configured', status: 503, detail: 'API_ORIGIN is not set for this Pages project.' }, { status: 503, headers: { 'content-type': 'application/problem+json' } });
  }
  const url = new URL(request.url);
  const target = `${origin}${url.pathname}${url.search}`;
  const headers = new Headers();
  for (const h of FORWARD) {
    const v = request.headers.get(h);
    if (v) headers.set(h, v);
  }
  // The visitor's IP. CF-Connecting-IP on the subrequest to the API is Cloudflare's egress IP, not the
  // visitor, so the API's per-IP limits need it passed explicitly and authenticated with PROXY_KEY.
  const ip = request.headers.get('cf-connecting-ip');
  if (ip) {
    headers.set('x-forwarded-for', ip);
    headers.set('x-client-ip', ip);
  }
  if (env.PROXY_KEY) headers.set('x-gp-proxy-key', env.PROXY_KEY);
  headers.set('x-forwarded-host', url.host);
  headers.set('x-forwarded-proto', 'https');

  const hasBody = !['GET', 'HEAD'].includes(request.method);
  let upstream: Response;
  try {
    upstream = await fetch(target, { method: request.method, headers, body: hasBody ? request.body : undefined, redirect: 'manual' });
  } catch (e) {
    return Response.json(
      { type: 'about:blank', title: 'API unreachable', status: 502, detail: `The ${new URL(origin).host} backend did not answer (${e instanceof Error ? e.message : 'network error'}).` },
      { status: 502, headers: { 'content-type': 'application/problem+json' } },
    );
  }
  const out = new Headers();
  for (const h of PASS_BACK) {
    const v = upstream.headers.get(h);
    if (v) out.set(h, v);
  }
  if (!out.has('cache-control')) out.set('cache-control', 'no-store');
  out.set('x-proxied-by', 'groundplan-pages-function');
  // Lets a client (and the E2E suite) see which visitor IP the API was told about. It is the caller's own IP.
  if (ip) out.set('x-gp-client-ip', ip);
  return new Response(upstream.body, { status: upstream.status, statusText: upstream.statusText, headers: out });
}
