#!/usr/bin/env node

import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';

const API_URL = 'https://api.finmindtrade.com/api/v4/data';
const SCHEMA_VERSION = 'schema-v0.1';
const DATASETS = {
  price: 'TaiwanStockPrice',
  institutional: 'TaiwanStockInstitutionalInvestorsBuySell',
  margin: 'TaiwanStockMarginPurchaseShortSale',
};

function parseArgs(argv) {
  const options = {
    universe: 'config/universe_spike.csv',
    out: 'data/spike',
    report: 'docs/m0-spike-result.md',
    start: '2024-09-27',
    end: '2026-09-25',
    concurrency: 3,
    refresh: false,
  };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--refresh') options.refresh = true;
    else if (arg.startsWith('--')) {
      const key = arg.slice(2);
      if (!(key in options)) throw new Error(`Unknown option: ${arg}`);
      options[key] = argv[++i];
    }
  }
  options.concurrency = Number(options.concurrency);
  if (!Number.isInteger(options.concurrency) || options.concurrency < 1) {
    throw new Error('--concurrency must be a positive integer');
  }
  return options;
}

function parseCsv(text) {
  const lines = text.trim().split(/\r?\n/);
  const headers = lines.shift().split(',');
  return lines.filter(Boolean).map((line) => {
    const values = line.split(',');
    return Object.fromEntries(headers.map((header, index) => [header, values[index] ?? '']));
  });
}

function csvCell(value) {
  if (value === null || value === undefined) return '';
  const text = String(value);
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function toCsv(rows, columns) {
  return `${columns.join(',')}\n${rows.map((row) => columns.map((key) => csvCell(row[key])).join(',')).join('\n')}\n`;
}

async function fileExists(file) {
  try {
    await readFile(file);
    return true;
  } catch (error) {
    if (error.code === 'ENOENT') return false;
    throw error;
  }
}

async function fetchJson(url, attempts = 4) {
  let lastError;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      const response = await fetch(url, { headers: { 'user-agent': 'quant-market-observer-m0/0.1' } });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const body = await response.json();
      if (body.status !== 200 || body.msg !== 'success') {
        throw new Error(`API ${body.status}: ${body.msg}`);
      }
      return body;
    } catch (error) {
      lastError = error;
      if (attempt < attempts) await new Promise((resolve) => setTimeout(resolve, attempt * 750));
    }
  }
  throw lastError;
}

async function loadDataset({ dataset, stockId, start, end, rawDir, refresh }) {
  const file = path.join(rawDir, dataset, `${stockId}.json`);
  if (!refresh && await fileExists(file)) return JSON.parse(await readFile(file, 'utf8'));
  const url = new URL(API_URL);
  url.searchParams.set('dataset', dataset);
  url.searchParams.set('data_id', stockId);
  url.searchParams.set('start_date', start);
  url.searchParams.set('end_date', end);
  const body = await fetchJson(url);
  await mkdir(path.dirname(file), { recursive: true });
  await writeFile(file, `${JSON.stringify(body)}\n`);
  return body;
}

async function mapLimit(items, limit, worker) {
  const results = new Array(items.length);
  let cursor = 0;
  async function run() {
    while (cursor < items.length) {
      const index = cursor++;
      results[index] = await worker(items[index], index);
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, run));
  return results;
}

function normalizePrice(rows, meta, retrievedAt) {
  return rows.map((row) => {
    const noTrade = Number(row.Trading_Volume) === 0 && Number(row.Trading_money) === 0;
    return {
      trade_date: row.date,
      stock_id: row.stock_id,
      market: meta.market,
      open: noTrade ? null : row.open,
      high: noTrade ? null : row.max,
      low: noTrade ? null : row.min,
      close: noTrade ? null : row.close,
      volume: row.Trading_Volume,
      trading_money: row.Trading_money,
      trades: row.Trading_turnover,
      spread: noTrade ? null : row.spread,
      quality_flags: noTrade ? "no_trade" : "",
      source: `FinMind:${DATASETS.price}`,
      retrieved_at: retrievedAt,
      schema_version: SCHEMA_VERSION,
    };
  });
}

function normalizeInstitutional(rows, meta, retrievedAt) {
  const dates = new Map();
  for (const row of rows) {
    const current = dates.get(row.date) ?? {
      trade_date: row.date,
      stock_id: row.stock_id,
      market: meta.market,
      foreign_net: 0,
      trust_net: 0,
      dealer_net: 0,
      total_net: 0,
      categories: new Set(),
    };
    const net = Number(row.buy) - Number(row.sell);
    current.categories.add(row.name);
    if (row.name === 'Foreign_Investor' || row.name === 'Foreign_Dealer_Self') current.foreign_net += net;
    else if (row.name === 'Investment_Trust') current.trust_net += net;
    else if (row.name.startsWith('Dealer_')) current.dealer_net += net;
    current.total_net += net;
    dates.set(row.date, current);
  }
  return [...dates.values()].map((row) => ({
    ...row,
    categories: [...row.categories].sort().join('|'),
    source: `FinMind:${DATASETS.institutional}`,
    retrieved_at: retrievedAt,
    schema_version: SCHEMA_VERSION,
  }));
}

function normalizeMargin(rows, meta, retrievedAt) {
  return rows.map((row) => ({
    trade_date: row.date,
    stock_id: row.stock_id,
    market: meta.market,
    margin_buy: row.MarginPurchaseBuy,
    margin_sell: row.MarginPurchaseSell,
    margin_cash_repayment: row.MarginPurchaseCashRepayment,
    margin_balance: row.MarginPurchaseTodayBalance,
    margin_previous_balance: row.MarginPurchaseYesterdayBalance,
    short_buy: row.ShortSaleBuy,
    short_sell: row.ShortSaleSell,
    short_cash_repayment: row.ShortSaleCashRepayment,
    short_balance: row.ShortSaleTodayBalance,
    short_previous_balance: row.ShortSaleYesterdayBalance,
    offset: row.OffsetLoanAndShort,
    note: row.Note?.trim() ?? '',
    source: `FinMind:${DATASETS.margin}`,
    retrieved_at: retrievedAt,
    schema_version: SCHEMA_VERSION,
  }));
}

function duplicateCount(rows) {
  const seen = new Set();
  let duplicates = 0;
  for (const row of rows) {
    const key = `${row.trade_date}|${row.stock_id}`;
    if (seen.has(key)) duplicates += 1;
    seen.add(key);
  }
  return duplicates;
}

function summarize(rows, universe) {
  const byStock = new Map();
  for (const row of rows) {
    const item = byStock.get(row.stock_id) ?? { count: 0, min: row.trade_date, max: row.trade_date };
    item.count += 1;
    if (row.trade_date < item.min) item.min = row.trade_date;
    if (row.trade_date > item.max) item.max = row.trade_date;
    byStock.set(row.stock_id, item);
  }
  const missingStocks = universe.filter((stock) => !byStock.has(stock.stock_id)).map((stock) => stock.stock_id);
  return {
    rows: rows.length,
    stocks: byStock.size,
    missingStocks,
    duplicates: duplicateCount(rows),
    minDate: rows.reduce((min, row) => !min || row.trade_date < min ? row.trade_date : min, ''),
    maxDate: rows.reduce((max, row) => !max || row.trade_date > max ? row.trade_date : max, ''),
    minRowsPerStock: byStock.size ? Math.min(...[...byStock.values()].map((item) => item.count)) : 0,
    maxRowsPerStock: byStock.size ? Math.max(...[...byStock.values()].map((item) => item.count)) : 0,
  };
}

function buildReport({ options, universe, price, institutional, margin, retrievedAt }) {
  const summaries = {
    price: summarize(price, universe),
    institutional: summarize(institutional, universe),
    margin: summarize(margin, universe),
  };
  const noTradeRows = price.filter((row) => row.quality_flags === "no_trade").length;
  const invalidPriceRows = price.filter((row) => row.close !== null && (!Number.isFinite(Number(row.close)) || Number(row.close) <= 0)).length;
  const joined = new Set(institutional.map((row) => `${row.trade_date}|${row.stock_id}`));
  const marginJoined = new Set(margin.map((row) => `${row.trade_date}|${row.stock_id}`));
  const completePriceRows = price.filter((row) => joined.has(`${row.trade_date}|${row.stock_id}`) && marginJoined.has(`${row.trade_date}|${row.stock_id}`)).length;
  const report = {
    generated_at: retrievedAt,
    requested_start: options.start,
    requested_end: options.end,
    universe_size: universe.length,
    theme_count: new Set(universe.map((row) => row.theme)).size,
    summaries,
    invalid_price_rows: invalidPriceRows,
    no_trade_rows: noTradeRows,
    complete_join_rows: completePriceRows,
    complete_join_ratio: price.length ? completePriceRows / price.length : 0,
  };
  const status = Object.values(summaries).every((item) => item.stocks === universe.length && item.duplicates === 0)
    && invalidPriceRows === 0 ? 'PASS' : 'REVIEW';
  const table = Object.entries(summaries).map(([name, item]) =>
    `| ${name} | ${item.rows} | ${item.stocks}/${universe.length} | ${item.minDate} | ${item.maxDate} | ${item.minRowsPerStock}–${item.maxRowsPerStock} | ${item.duplicates} | ${item.missingStocks.join(', ') || '—'} |`
  ).join('\n');
  const markdown = `# M0 50 檔／2 年資料 Spike 結果

- 狀態：**${status}**
- 執行時間（UTC）：${retrievedAt}
- 請求區間：${options.start} ～ ${options.end}
- 股票數：${universe.length}
- 代表主題數：${report.theme_count}
- schema：${SCHEMA_VERSION}

## 覆蓋與品質

| dataset | rows | 股票覆蓋 | 起始日期 | 結束日期 | 每檔筆數 | 重複主鍵 | 缺少股票 |
|---|---:|---:|---|---|---:|---:|---|
${table}

- 無效收盤價筆數：${invalidPriceRows}
- 無成交／停牌語意列（價格轉為 null）：${noTradeRows}
- 價量、法人、融資同日可完整 join：${completePriceRows}/${price.length}（${(report.complete_join_ratio * 100).toFixed(2)}%）
- 零值與缺值未互換；未取得融資資料的日期不以零補齊。

## 判讀

此 spike 驗證 FinMind 可按股票取得最近兩年的價量、法人與融資資料，並標準化為一致主鍵。\`complete_join_ratio\` 不預期為 100%，因部分股票或交易日可能沒有融資資格／資料，法人表也可能依來源規則缺少紀錄；正式模型必須保留缺值語意。

## 尚未宣告完成的項目

- 本結果使用未還原價格，不可直接作跨除權息的正式績效結論。
- 價量已完成 TWSE／TPEx 官方抽樣對帳；法人與融資值留待 M1 擴充官方核對。
- 歷史股票池、下市股票與資料修訂版本仍待 M1 處理。
- 大量原始資料位於 gitignored 的 \`data/\`，不提交至公開 repository。
`;
  return { report, markdown };
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const universe = parseCsv(await readFile(options.universe, 'utf8'));
  if (universe.length !== 50) throw new Error(`M0 universe must contain 50 stocks; found ${universe.length}`);
  const ids = new Set(universe.map((row) => row.stock_id));
  if (ids.size !== universe.length) throw new Error('Duplicate stock_id in universe');

  const retrievedAt = new Date().toISOString();
  const rawDir = path.join(options.out, 'raw');
  const normalizedDir = path.join(options.out, 'normalized');
  await mkdir(normalizedDir, { recursive: true });

  const results = await mapLimit(universe, options.concurrency, async (stock, index) => {
    process.stderr.write(`[${index + 1}/${universe.length}] ${stock.stock_id} ${stock.name}\n`);
    const [price, institutional, margin] = await Promise.all(Object.values(DATASETS).map((dataset) =>
      loadDataset({ dataset, stockId: stock.stock_id, start: options.start, end: options.end, rawDir, refresh: options.refresh })
    ));
    return {
      price: normalizePrice(price.data, stock, retrievedAt),
      institutional: normalizeInstitutional(institutional.data, stock, retrievedAt),
      margin: normalizeMargin(margin.data, stock, retrievedAt),
    };
  });

  const price = results.flatMap((item) => item.price).sort((a, b) => `${a.trade_date}${a.stock_id}`.localeCompare(`${b.trade_date}${b.stock_id}`));
  const institutional = results.flatMap((item) => item.institutional).sort((a, b) => `${a.trade_date}${a.stock_id}`.localeCompare(`${b.trade_date}${b.stock_id}`));
  const margin = results.flatMap((item) => item.margin).sort((a, b) => `${a.trade_date}${a.stock_id}`.localeCompare(`${b.trade_date}${b.stock_id}`));

  await writeFile(path.join(normalizedDir, 'daily_price.csv'), toCsv(price, Object.keys(price[0] ?? {})));
  await writeFile(path.join(normalizedDir, 'institutional_flow.csv'), toCsv(institutional, Object.keys(institutional[0] ?? {})));
  await writeFile(path.join(normalizedDir, 'margin.csv'), toCsv(margin, Object.keys(margin[0] ?? {})));

  const { report, markdown } = buildReport({ options, universe, price, institutional, margin, retrievedAt });
  await writeFile(path.join(options.out, 'validation-summary.json'), `${JSON.stringify(report, null, 2)}\n`);
  await writeFile(options.report, markdown);
  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
}

main().catch((error) => {
  console.error(error.stack ?? error.message);
  process.exitCode = 1;
});
