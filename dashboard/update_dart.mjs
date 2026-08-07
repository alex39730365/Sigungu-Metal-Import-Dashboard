import fs from 'fs';
import path from 'path';

const backendDir = path.join(process.cwd(), 'backend');
const targetPath = path.join(backendDir, 'dart_metal_index.json');

const apiKey = process.env.DART_API_KEY || '33abaef529ba07d36d8e3953ba00b8aa45229b1a';

function loadValidData() {
  // 1. 현재 파일 읽기
  if (fs.existsSync(targetPath)) {
    try {
      const data = JSON.parse(fs.readFileSync(targetPath, 'utf-8'));
      const list = Array.isArray(data) ? data : (data.companies || data.items || []);
      if (list.length > 0) return { list, targetPath };
    } catch (e) {}
  }

  // 2. 백업 파일 또는 backend 내 다른 json 검사
  const files = fs.readdirSync(backendDir);
  for (const file of files) {
    if (file.endsWith('.json') && file !== 'package.json') {
      const filePath = path.join(backendDir, file);
      try {
        const data = JSON.parse(fs.readFileSync(filePath, 'utf-8'));
        const list = Array.isArray(data) ? data : (data.companies || data.items || []);
        if (list.length > 0) {
          console.log(`💡 '${file}' 파일에서 원본 데이터 ${list.length}개를 찾았습니다!`);
          return { list, targetPath };
        }
      } catch (e) {}
    }
  }

  // 3. src/data 폴더 검사
  const srcDataDir = path.join(process.cwd(), 'src', 'data');
  if (fs.existsSync(srcDataDir)) {
    const srcFiles = fs.readdirSync(srcDataDir);
    for (const file of srcFiles) {
      if (file.endsWith('.json')) {
        const filePath = path.join(srcDataDir, file);
        try {
          const data = JSON.parse(fs.readFileSync(filePath, 'utf-8'));
          const list = Array.isArray(data) ? data : (data.companies || data.items || []);
          if (list.length > 0) {
            console.log(`💡 'src/data/${file}' 파일에서 원본 데이터 ${list.length}개를 찾았습니다!`);
            return { list, targetPath };
          }
        } catch (e) {}
      }
    }
  }

  return { list: [], targetPath };
}

const { list: companies } = loadValidData();

if (companies.length === 0) {
  console.error("❌ 모든 위치에서 기업 목록 데이터를 찾을 수 없습니다.");
  console.error("💡 Git에서 원본 파일을 복구(git checkout backend/dart_metal_index.json)하거나 원본 json 파일이 필요합니다.");
  process.exit(1);
}

(async () => {
  console.log(`🚀 Open DART 데이터 수집 시작 (총 ${companies.length}개 기업)...`);
  
  const updated = [];
  for (let i = 0; i < companies.length; i++) {
    const comp = companies[i];
    
    if (!comp || !comp.corp_code) { 
      updated.push(comp); 
      continue; 
    }
    
    try {
      const res = await fetch(`https://opendart.fss.or.kr/api/company.json?crtfc_key=${apiKey}&corp_code=${comp.corp_code}`);
      const data = await res.json();
      
      if (data.status === '000') {
        updated.push({
          ...comp,
          ceo_nm: data.ceo_nm || comp.ceo_nm || '',
          phn_no: data.phn_no || comp.phn_no || '',
          fax_no: data.fax_no || comp.fax_no || '',
          bizr_no: data.bizr_no || comp.bizr_no || '',
          hm_url: data.hm_url || comp.hm_url || '',
          est_dt: data.est_dt || comp.est_dt || '',
          adres: data.adres || comp.adres || ''
        });
      } else { 
        updated.push(comp); 
      }
    } catch (e) { 
      updated.push(comp); 
    }
    
    await new Promise(r => setTimeout(r, 100));
    
    if ((i + 1) % 50 === 0 || i === companies.length - 1) {
      console.log(`진행률: ${i + 1} / ${companies.length} 완료`);
    }
  }

  fs.writeFileSync(targetPath, JSON.stringify(updated, null, 2), 'utf-8');
  console.log('✅ backend/dart_metal_index.json 파일 갱신이 완벽하게 완료되었습니다!');
})();