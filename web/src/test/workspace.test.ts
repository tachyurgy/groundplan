import { describe, expect, it, vi } from 'vitest';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

describe('workspace id (no-login tenancy)', () => {
  it('creates a UUIDv4 once and reuses it from localStorage', async () => {
    vi.resetModules();
    localStorage.clear();
    const ws = await import('../lib/workspace');
    const a = ws.getWorkspaceId();
    expect(a).toMatch(UUID);
    expect(localStorage.getItem('gp.workspace')).toBe(a);
    vi.resetModules();
    const again = await import('../lib/workspace');
    expect(again.getWorkspaceId()).toBe(a);
  });

  it('ignores a garbage stored value', async () => {
    vi.resetModules();
    localStorage.setItem('gp.workspace', 'not-a-uuid');
    const ws = await import('../lib/workspace');
    expect(ws.getWorkspaceId()).toMatch(UUID);
    expect(ws.getWorkspaceId()).not.toBe('not-a-uuid');
  });

  it('falls back to sessionStorage, then memory, when storage throws', async () => {
    vi.resetModules();
    const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError');
    });
    const getSpy = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('SecurityError');
    });
    const ws = await import('../lib/workspace');
    const id = ws.getWorkspaceId();
    expect(id).toMatch(UUID);
    expect(ws.getWorkspaceId()).toBe(id); // stable for the life of the tab
    spy.mockRestore();
    getSpy.mockRestore();
  });

  it('rotate gives a new id', async () => {
    vi.resetModules();
    const ws = await import('../lib/workspace');
    const a = ws.getWorkspaceId();
    expect(ws.rotateWorkspaceId()).not.toBe(a);
  });
});
