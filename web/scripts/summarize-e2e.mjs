// Collect the latest test evidence into src/generated/e2e-summary.json (shown on /engineering):
// Playwright JSON reports (e2e/.results/*.json), axe logs (e2e/.results/axe*.jsonl), the Vitest JSON
// report (e2e/.results/vitest.json) and the bundle budget check.
import { existsSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';

const dir = 'e2e/.results';
const runs = [];
const files = process.argv.slice(2).length ? process.argv.slice(2) : readdirSync(dir).filter((f) => /^(mock|live).*\.json$/.test(f)).map((f) => `${dir}/${f}`);
for (const file of files) {
  const rep = JSON.parse(readFileSync(file, 'utf8'));
  const urlOf = Object.fromEntries((rep.config?.projects ?? []).map((p) => [p.name, p.metadata?.url ?? (p.name === 'parity' ? 'python vs go' : '')]));
  const by = {};
  const walk = (suite) => {
    for (const s of suite.suites ?? []) walk(s);
    for (const spec of suite.specs ?? [])
      for (const t of spec.tests ?? []) {
        const r = (by[t.projectName] ??= { project: t.projectName, target: urlOf[t.projectName] ?? '', passed: 0, failed: 0, skipped: 0, flaky: 0 });
        if (t.status === 'skipped') r.skipped++;
        else if (t.status === 'expected') r.passed++;
        else if (t.status === 'flaky') r.flaky++;
        else r.failed++;
      }
  };
  for (const s of rep.suites ?? []) walk(s);
  runs.push(...Object.values(by));
}
runs.sort((a, b) => a.project.localeCompare(b.project));

let axe = null;
const axeFiles = readdirSync(dir).filter((f) => f.startsWith('axe') && f.endsWith('.jsonl'));
if (axeFiles.length) {
  const rows = axeFiles.flatMap((f) => readFileSync(`${dir}/${f}`, 'utf8').trim().split('\n').filter(Boolean).map((l) => JSON.parse(l)));
  axe = { pages: rows.length, serious: rows.reduce((a, r) => a + r.serious, 0), critical: rows.reduce((a, r) => a + r.critical, 0) };
}

let unit = null;
if (existsSync(`${dir}/vitest.json`)) {
  const v = JSON.parse(readFileSync(`${dir}/vitest.json`, 'utf8'));
  unit = { files: v.numTotalTestSuites ?? v.testResults?.length ?? 0, tests: v.numTotalTests, passed: v.numPassedTests };
  if (v.testResults) unit.files = v.testResults.length;
}

let bundle = null;
if (existsSync('dist/index.html')) {
  const out = execFileSync('node', ['scripts/check-bundle.mjs', 'dist'], { env: { ...process.env, BUNDLE_JSON: '1' } }).toString();
  bundle = JSON.parse(out.trim().split('\n').pop());
}

const summary = { generated_at: new Date().toISOString(), unit, runs, axe, bundle };
writeFileSync('src/generated/e2e-summary.json', JSON.stringify(summary, null, 2) + '\n');
console.log(JSON.stringify(summary, null, 2));
