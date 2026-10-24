import { setupServer } from 'msw/node';
import { handlers } from '../api/mock/handlers';

/** The same MSW handlers the in-browser mock mode uses, on Node for Vitest. */
export const server = setupServer(...handlers);
