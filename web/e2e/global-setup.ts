import { mkdirSync, existsSync, readFileSync, writeFileSync } from 'node:fs';
import { randomUUID } from 'node:crypto';

/** Reset each live target's shared read-only workspace once per run, so every journey starts from the current seed. */
export default async function globalSetup() {
  const targets = [
    ['python', process.env.E2E_PYTHON_URL],
    ['go', process.env.E2E_GO_URL],
    [process.env.E2E_TARGET_NAME ?? 'live', process.env.E2E_BASE_URL],
  ].filter(([, u]) => !!u) as [string, string][];
  mkdirSync('e2e/.ws-pool', { recursive: true });
  for (const [name, url] of targets) {
    const file = `e2e/.ws-pool/${name}-shared.txt`;
    if (!existsSync(file)) writeFileSync(file, randomUUID());
    const id = readFileSync(file, 'utf8').trim();
    const r = await fetch(`${url}/api/v1/workspace/reset`, { method: 'POST', headers: { 'X-Workspace-Id': id } });
    if (!r.ok) throw new Error(`global setup: resetting ${name} shared workspace failed: ${r.status} ${await r.text()}`);
  }
}
