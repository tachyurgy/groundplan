/**
 * Upload buffers live ONLY in this tab's memory, keyed by document id. The server never returns file bytes
 * (SPEC §1 Document.bytes_retained = false), so pdf.js renders thumbnails from here. Reload = gone, by design.
 */
const byDoc = new Map<string, File>();
const listeners = new Set<() => void>();

export const fileStore = {
  put(documentId: string, file: File) {
    byDoc.set(documentId, file);
    listeners.forEach((l) => l());
  },
  get(documentId: string): File | undefined {
    return byDoc.get(documentId);
  },
  has(documentId: string) {
    return byDoc.has(documentId);
  },
  subscribe(fn: () => void) {
    listeners.add(fn);
    return () => {
      listeners.delete(fn);
    };
  },
  version: () => byDoc.size,
};
