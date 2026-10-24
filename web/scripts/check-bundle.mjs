// Bundle budget: sum the gzip size of every script the browser downloads before first render
// (the entry module plus its modulepreloads, read from dist/index.html). Fails over the budget.
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { gzipSync } from 'node:zlib';

const dist = process.argv[2] ?? 'dist';
const budgetKb = Number(process.env.BUNDLE_BUDGET_KB ?? 200);
const html = readFileSync(join(dist, 'index.html'), 'utf8');
const files = [...html.matchAll(/(?:src|href)="\/(assets\/[^"]+\.js)"/g)].map((m) => m[1]);
let total = 0;
for (const f of files) {
  const kb = gzipSync(readFileSync(join(dist, f)), { level: 9 }).length / 1024;
  total += kb;
  console.log(`${kb.toFixed(1).padStart(7)} KB  ${f}`);
}
console.log(`${total.toFixed(1).padStart(7)} KB  initial JS (gzip), budget ${budgetKb} KB`);
if (process.env.BUNDLE_JSON) console.log(JSON.stringify({ initial_gzip_kb: Number(total.toFixed(1)), budget_kb: budgetKb }));
if (total > budgetKb) {
  console.error(`Over budget by ${(total - budgetKb).toFixed(1)} KB`);
  process.exit(1);
}
