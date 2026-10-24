import { create } from 'zustand';

/** Backend reachability, fed by the QueryCache (network errors) and the browser's online/offline events. */
interface Conn {
  online: boolean;
  apiDown: boolean;
  markDown: () => void;
  markUp: () => void;
}
export const useConnection = create<Conn>((set, get) => ({
  online: typeof navigator === 'undefined' ? true : navigator.onLine,
  apiDown: false,
  markDown: () => !get().apiDown && set({ apiDown: true }),
  markUp: () => get().apiDown && set({ apiDown: false }),
}));
if (typeof window !== 'undefined') {
  window.addEventListener('online', () => useConnection.setState({ online: true }));
  window.addEventListener('offline', () => useConnection.setState({ online: false }));
}
