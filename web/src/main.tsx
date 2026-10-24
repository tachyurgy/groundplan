import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App } from './App';
import { TraceProvider } from './components/trace';
import './index.css';

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, refetchOnWindowFocus: false, retry: 1 } },
});

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <TraceProvider>
          <App />
        </TraceProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
