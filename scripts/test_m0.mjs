#!/usr/bin/env node

import { readFile } from 'node:fs/promises';

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function parseCsv(text) {
  const [header, ...lines] = text.trim().split(/\r?\n/);
  const columns = header.split(',');
  return lines.map((line) => Object.fromEntries(columns.map((column, index) => [column, line.split(',')[index] ?? ''])));
}

const universe = parseCsv(await readFile('config/universe_spike.csv', 'utf8'));
assert(universe.length === 50, `expected 50 stocks, got ${universe.length}`);
assert(new Set(universe.map((row) => row.stock_id)).size === 50, 'stock_id must be unique');
assert(new Set(universe.map((row) => row.theme)).size >= 20, 'spike must represent at least 20 themes');

const price = parseCsv(await readFile('data/spike/normalized/daily_price.csv', 'utf8'));
assert(price.length > 20_000, `expected >20,000 price rows, got ${price.length}`);
assert(price.every((row) => row.source === 'FinMind:TaiwanStockPrice'), 'price source metadata is incomplete');
assert(price.every((row) => row.schema_version === 'schema-v0.1'), 'unexpected price schema version');

const validation = JSON.parse(await readFile('data/spike/validation-summary.json', 'utf8'));
for (const [name, summary] of Object.entries(validation.summaries)) {
  assert(summary.stocks === 50, `${name}: expected 50 stocks, got ${summary.stocks}`);
  assert(summary.duplicates === 0, `${name}: duplicate primary keys found`);
}
assert(validation.invalid_price_rows === 0, 'invalid price rows found');
assert(validation.complete_join_ratio >= 0.99, 'three-table join ratio is below 99%');

const official = await readFile('docs/m0-official-crosscheck.md', 'utf8');
assert(official.includes('狀態：**PASS**'), 'official cross-check did not pass');

console.log(JSON.stringify({
  status: 'PASS',
  stocks: universe.length,
  themes: new Set(universe.map((row) => row.theme)).size,
  price_rows: price.length,
  complete_join_ratio: validation.complete_join_ratio,
}, null, 2));
