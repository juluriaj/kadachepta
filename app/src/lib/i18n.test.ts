// Run with: node --test src/lib/i18n.test.ts
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const source = readFileSync(new URL('./i18n.tsx', import.meta.url), 'utf8');
const block = (start: string, end: string) => source.slice(source.indexOf(start), source.indexOf(end));
const keys = (text: string) => [...text.matchAll(/'([a-z0-9.-]+)':\s*'/gi)].map((m) => m[1]);
const english = keys(block('const en', 'type Key'));
const telugu = new Set(keys(block('const te', 'const dictionaries')));
const BRAND_ONLY = new Set(['app.name']);

test('every UI string has a Telugu translation', () => {
  const missing = english.filter((key) => !telugu.has(key) && !BRAND_ONLY.has(key));
  assert.deepEqual(missing, []);
});

test('placeholders match between languages', () => {
  const placeholders = (dict: string, key: string) => {
    const line = block(dict, dict === 'const en' ? 'type Key' : 'const dictionaries').split('\n').find((l) => l.includes(`'${key}':`)) ?? '';
    return [...line.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort().join(',');
  };
  for (const key of english.filter((k) => telugu.has(k))) {
    assert.equal(placeholders('const te', key), placeholders('const en', key), `placeholders differ for ${key}`);
  }
});
