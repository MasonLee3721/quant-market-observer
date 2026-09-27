#!/usr/bin/env node

import { readFile, writeFile } from 'node:fs/promises';

const CHECK_DATE = process.argv[2] ?? '2026-09-24';
const PRICE_FILE = process.argv[3] ?? 'data/spike/normalized/daily_price.csv';
const REPORT_FILE = process.argv[4] ?? 'docs/m0-official-crosscheck.md';

function parseCsv(text) {
  const [header, ...lines] = text.trim().split(/\r?\n/);
  const columns = header.split(',');
  return lines.map((line) => Object.fromEntries(columns.map((column, index) => [column, line.split(',')[index] ?? ''])));
}

function number(value) {
  const cleaned = String(value ?? '').replaceAll(',', '').trim();
  if (cleaned === '' || cleaned === '--') return null;
  const parsed = Number(cleaned);
  return Number.isFinite(parsed) ? parsed : null;
}

function compactDate(date) {
  return date.replaceAll('-', '');
}

function rocDate(date) {
  const [year, month, day] = date.split('-').map(Number);
  return `${year - 1911}/${String(month).padStart(2, '0')}/${String(day).padStart(2, '0')}`;
}

async function fetchJson(url) {
  const response = await fetch(url, { headers: { 'user-agent': 'quant-market-observer-m0/0.1' } });
  if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
  return response.json();
}

async function twse(stockId) {
  const url = new URL('https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY');
  url.searchParams.set('date', compactDate(CHECK_DATE));
  url.searchParams.set('stockNo', stockId);
  url.searchParams.set('response', 'json');
  const body = await fetchJson(url);
  if (body.stat !== 'OK') throw new Error(`TWSE ${stockId}: ${body.stat}`);
  const row = body.data.find((item) => item[0] === rocDate(CHECK_DATE));
  if (!row) throw new Error(`TWSE ${stockId}: date ${CHECK_DATE} not found`);
  return { stock_id: stockId, open: number(row[3]), high: number(row[4]), low: number(row[5]), close: number(row[6]), volume: number(row[1]), trading_money: number(row[2]) };
}

async function tpex(stockId) {
  const url = new URL('https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes');
  url.searchParams.set('date', CHECK_DATE.replaceAll('-', '/'));
  url.searchParams.set('id', stockId);
  url.searchParams.set('response', 'json');
  const body = await fetchJson(url);
  const table = body.tables?.find((item) => item.title === '上櫃股票行情') ?? body.tables?.[0];
  const row = table?.data?.find((item) => item[0] === stockId);
  if (!row) throw new Error(`TPEx ${stockId}: date ${CHECK_DATE} not found`);
  return { stock_id: stockId, open: number(row[4]), high: number(row[5]), low: number(row[6]), close: number(row[2]), volume: number(row[8]), trading_money: number(row[9]) };
}

function compare(source, official) {
  const fields = ['open', 'high', 'low', 'close', 'volume', 'trading_money'];
  const differences = Object.fromEntries(fields.map((field) => [field, Number(source[field]) - Number(official[field])]));
  return { stock_id: official.stock_id, source, official, differences, pass: Object.values(differences).every((value) => value === 0) };
}

async function main() {
  const rows = parseCsv(await readFile(PRICE_FILE, 'utf8'));
  const checks = [];
  for (const [stockId, loader, market] of [['2330', twse, 'TWSE'], ['8069', tpex, 'TPEx']]) {
    const source = rows.find((row) => row.stock_id === stockId && row.trade_date === CHECK_DATE);
    if (!source) throw new Error(`Normalized data missing ${stockId} ${CHECK_DATE}`);
    checks.push({ market, ...compare(source, await loader(stockId)) });
  }
  const status = checks.every((item) => item.pass) ? 'PASS' : 'REVIEW';
  const details = checks.map((item) => `| ${item.market} | ${item.stock_id} | ${item.source.close} | ${item.official.close} | ${item.source.volume} | ${item.official.volume} | ${item.source.trading_money} | ${item.official.trading_money} | ${item.pass ? 'PASS' : 'DIFF'} |`).join('\n');
  const report = `# M0 官方資料抽樣對帳

- 狀態：**${status}**
- 交易日：${CHECK_DATE}
- 對帳範圍：上市 2330、上櫃 8069
- 比較欄位：OHLC、成交股數、成交金額

| 市場 | 股票 | FinMind 收盤 | 官方收盤 | FinMind 成交股數 | 官方成交股數 | FinMind 成交金額 | 官方成交金額 | 結果 |
|---|---|---:|---:|---:|---:|---:|---:|---|
${details}

結果以完全相等為通過條件。此抽樣只證明指定日期與欄位一致，不代表所有歷史資料均已全面核對；M1 將把抽樣對帳做成每日品質檢查。
`;
  await writeFile(REPORT_FILE, report);
  console.log(JSON.stringify({ status, date: CHECK_DATE, checks }, null, 2));
  if (status !== 'PASS') process.exitCode = 2;
}

main().catch((error) => {
  console.error(error.stack ?? error.message);
  process.exitCode = 1;
});
