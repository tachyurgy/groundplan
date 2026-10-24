import { describe, expect, it } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f);
    return statSync(p).isDirectory() ? (f === 'test' ? [] : walk(p)) : /\.(tsx?|css)$/.test(f) ? [p] : [];
  });
}

describe('product rules in the source', () => {
  it('the UI never says "recommended" (the comparison describes; it does not pick)', () => {
    const hits = walk(join(__dirname, '..')).filter((p) => /\brecommend(ed|ation|s)?\b/i.test(readFileSync(p, 'utf8')));
    expect(hits).toEqual([]);
  });
});
