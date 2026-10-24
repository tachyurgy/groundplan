import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider } from '@tanstack/react-router';
import '@fontsource/ibm-plex-sans/latin-400.css';
import '@fontsource/ibm-plex-sans/latin-500.css';
import '@fontsource/ibm-plex-sans/latin-600.css';
import '@fontsource/ibm-plex-mono/latin-400.css';
import '@fontsource/ibm-plex-mono/latin-500.css';
import './index.css';
import { ApiError } from './api/client';
import { makeRouter } from './router';
import { useConnection } from './lib/connection';
import { startVitals } from './lib/vitals';

function onError(e: unknown) {
  if (e instanceof ApiError && e.isNetwork) useConnection.getState().markDown();
}

const queryClient = new QueryClient({
  queryCache: new QueryCache({ onError, onSuccess: () => useConnection.getState().markUp() }),
  mutationCache: new MutationCache({ onError }),
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      // 4xx (incl. contract drift) never gets better by retrying; network blips do.
      retry: (n, e) => (e instanceof ApiError ? e.isNetwork || e.status >= 500 : false) && n < 2,
    },
  },
});

const router = makeRouter(queryClient);

async function boot() {
  // Literal env check (not the IS_MOCK constant) so a production build drops MSW and the fixtures entirely.
  if (import.meta.env.VITE_MOCK === '1') {
    const { worker } = await import('./api/mock/browser');
    await worker.start({ onUnhandledFrame: 'bypass', quiet: true, serviceWorker: { url: '/mockServiceWorker.js' } });
  }
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </StrictMode>,
  );
  startVitals();
}

void boot();
