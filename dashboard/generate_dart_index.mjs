import fs from 'fs';
import path from 'path';

const DART_API_KEY = process.env.DART_API_KEY;

if (!DART_API_KEY) {
  console.error("❌ DART_API_KEY 환경변수가 설정되지 않았습니다.");
  process.exit(1);
}

const INDEX_PATH = path.join(process.cwd(), 'src', 'data', 'dart_metal_index.json');

async function updateDartIndex() {
  console.log("🚀 Open DART 기업개황 데이터 수집을 시작합니다...");

  if (!fs.existsSync(INDEX_PATH)) {
    console.error(`❌ 파일을 찾을 수 없습니다: ${INDEX_PATH}`);
    return;
  }

  const rawData = fs.readFileSync(INDEX_PATH, 'utf-8');
  const companies = JSON.parse(rawData);
  const updatedCompanies = [];

  console.log(`총 ${companies.length}개 기업 정보 업데이트 시작...`);

  for (let i = 0; i < companies.length; i++) {
    const comp = companies[i];
    const corpCode = comp.corp_code;

    if (!corpCode) {
      updatedCompanies.push(comp);
      continue;
    }

    try {
      const url = `https://opendart.fss.or.kr/api/company.json?crtfc_key=${DART_API_KEY}&corp_code=${corpCode}`;
      const response = await fetch(url);
      const resData = await response.json();

      if (resData.status === '000') {
        updatedCompanies.push({
          ...comp,
          ceo_nm: resData.ceo_nm || '',
          phn_no: resData.phn_no || '',
          fax_no: resData.fax_no || '',
          bizr_no: resData.bizr_no || '',
          hm_url: resData.hm_url || '',
          est_dt: resData.est_dt || '',
          adres: resData.adres || comp.adres || ''
        });
      } else {
        updatedCompanies.push(comp);
      }
    } catch (err) {
      console.error(`[${i + 1}/${companies.length}] ${comp.corp_name} 조회 실패:`, err.message);
      updatedCompanies.push(comp);
    }

    await new Promise((resolve) => setTimeout(resolve, 100));

    if ((i + 1) % 50 === 0 || i === companies.length - 1) {
      console.log(`진행률: ${i + 1} / ${companies.length} 완료`);
    }
  }

  fs.writeFileSync(INDEX_PATH, JSON.stringify(updatedCompanies, null, 2), 'utf-8');
  console.log("✅ 성공적으로 dart_metal_index.json 파일이 갱신되었습니다!");
}

updateDartIndex();
