import fs from 'fs';

const API_KEY = process.env.DART_API_KEY;
if (!API_KEY) {
  console.error('DART_API_KEY 환경변수를 설정해주세요.');
  process.exit(1);
}

const INPUT = 'dashboard/backend/dart_metal_index.json';
const BAK = 'dashboard/backend/dart_metal_index.json.bak';
const TEMP = 'dashboard/backend/dart_metal_index.json.financials.tmp';
const OUTPUT = 'dashboard/backend/dart_metal_index.json';

fs.copyFileSync(INPUT, BAK);

let data;
if (fs.existsSync(TEMP)) {
  console.log('이전 임시 파일에서 재시도');
  data = JSON.parse(fs.readFileSync(TEMP, 'utf8'));
} else {
  data = JSON.parse(fs.readFileSync(INPUT, 'utf8'));
}

const companies = data.companies;
if (!Array.isArray(companies) || companies.length === 0) {
  console.error('기업 목록이 비어 있습니다.');
  process.exit(1);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const YEARS = ['2025', '2024'];
const FS_TYPES = [
  { code: 'CFS', name: '연결' },
  { code: 'OFS', name: '별도' },
];

const REVENUE_KEYS = ['매출액', '수익(매출액)', '영업수익', '매출'];
const OP_PROFIT_KEYS = ['영업이익', '영업이익(손실)', '영업손실'];

function findAmount(list, keywords) {
  for (const item of list) {
    const account = (item.account_nm || '').trim();
    if (keywords.some((k) => account.includes(k))) {
      const raw = (item.thstrm_amount || '').toString().replace(/,/g, '').trim();
      const v = Number(raw);
      if (raw && !Number.isNaN(v) && v !== 0) return v;
    }
  }
  return null;
}

async function fetchFinancial(corpCode, year, fsCode) {
  const url = `https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json?crtfc_key=${API_KEY}&corp_code=${corpCode}&bsns_year=${year}&reprt_code=11011&fs_div=${fsCode}`;
  const res = await fetch(url, {
    headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36' },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const d = await res.json();
  if (d.status !== '000' || !Array.isArray(d.list) || d.list.length === 0) return null;
  const revenue = findAmount(d.list, REVENUE_KEYS);
  const opProfit = findAmount(d.list, OP_PROFIT_KEYS);
  if (revenue === null || opProfit === null) return null;
  return {
    revenue: String(revenue),
    op_profit: String(opProfit),
    fin_year: year,
    fs_type: fsCode === 'CFS' ? '연결' : '별도',
  };
}

async function fillCompany(c) {
  for (const year of YEARS) {
    for (const fs of FS_TYPES) {
      try {
        const result = await fetchFinancial(c.corp_code, year, fs.code);
        if (result) {
          Object.assign(c, result);
          return;
        }
      } catch (e) {
        console.warn(`${c.corp_code} ${year}/${fs.code} 오류:`, e.message);
      }
      await sleep(180);
    }
  }
  c.revenue = '';
  c.op_profit = '';
  c.fin_year = '';
  c.fs_type = '';
}

async function run() {
  const total = companies.length;
  const start = companies.findIndex((c) => c.fin_year === undefined);
  const begin = start === -1 ? total : start;
  console.log(`총 ${total}건, ${begin}번째부터 시작`);

  for (let i = begin; i < total; i++) {
    await fillCompany(companies[i]);

    if ((i + 1) % 100 === 0 || i === total - 1) {
      fs.writeFileSync(TEMP, JSON.stringify({ ...data, companies }, null, 2));
      console.log(`${i + 1}/${total} 완료`);
    }

    if (i < total - 1) await sleep(180);
  }

  fs.writeFileSync(TEMP, JSON.stringify({ ...data, companies }, null, 2));
  fs.renameSync(TEMP, OUTPUT);
  try { fs.unlinkSync(BAK); } catch {}
  console.log('모든 재무 데이터 수집 완료');
}

run().catch((e) => {
  console.error('실행 오류:', e);
  process.exit(1);
});
