import { useQueryErrorResetBoundary } from '@tanstack/react-query';
import { Link, useRouter, type ErrorComponentProps } from '@tanstack/react-router';
import { ApiError, ContractError } from '../api/client';

/** Per-route error boundary: says what failed in plain words, renders problem+json, and retries in place. */
export function RouteError({ error, reset }: ErrorComponentProps) {
  const router = useRouter();
  const qReset = useQueryErrorResetBoundary();
  const retry = () => {
    qReset.reset();
    reset();
    void router.invalidate();
  };
  let title = 'This view could not load';
  let body: React.ReactNode = error instanceof Error ? error.message : String(error);
  if (error instanceof ApiError) {
    if (error.isNetwork) {
      title = 'The API is not answering';
      body = 'The backend may be restarting. Your data is safe; try again in a few seconds.';
    } else if (error.status === 404) {
      title = 'Not found in this workspace';
      body = (
        <>
          {error.message} This link may point at another browser's sandbox; each browser gets its own demo data. <Link to="/" className="font-medium text-brand-600 underline">Go to your households</Link>.
        </>
      );
    } else {
      title = error.problem?.title ?? `Request failed (${error.status})`;
      body = error.problem?.detail ?? error.message;
    }
  } else if (error instanceof ContractError) {
    title = 'The API returned data this screen does not understand';
    body = (
      <>
        <p>
          {error.message} Nothing is shown rather than showing wrong numbers. Fields: <span className="font-mono text-xs">{error.issues.map((i) => i.path || '(root)').join(', ')}</span>
        </p>
      </>
    );
  }
  return (
    <div role="alert" className="card mx-auto my-10 max-w-xl px-5 py-5">
      <h2 className="text-lg">{title}</h2>
      <div className="mt-2 text-sm leading-relaxed text-ink-700">{body}</div>
      <div className="mt-4 flex gap-2">
        <button type="button" className="btn btn-primary" onClick={retry}>
          Try again
        </button>
        <Link to="/" className="btn">
          Households
        </Link>
      </div>
    </div>
  );
}

export function NotFound() {
  return (
    <div className="mx-auto my-16 max-w-md text-center">
      <p className="num text-5xl font-medium text-ink-500">404</p>
      <h1 className="mt-3 text-xl">There is no page at this address</h1>
      <p className="mt-2 text-sm text-ink-500">Check the link, or start from the household list.</p>
      <Link to="/" className="btn btn-primary mt-5">
        Go to households
      </Link>
    </div>
  );
}
