# 시군구별 금속 수입 대시보드

관세청_시군구별 품목별 수출입실적 API로 수집한 데이터(`sigungu_metal_imports.csv`)를
지도(버블맵)/바 차트/금속 비율 파이차트로 시각화하는 풀스택 대시보드입니다.

## 아키텍처

```
dashboard/
├── backend/                 # FastAPI (데이터 API 서버) - Render 등에 배포
│   ├── main.py               # /api/regions, /api/regions/{name}/breakdown, /timeseries, /api/export/excel
│   └── requirements.txt
└── frontend/                 # React + TypeScript + Tailwind + Recharts - Cloudflare Pages 등에 배포
    ├── src/
    │   ├── api/metalImports.ts       # 백엔드 API 클라이언트
    │   ├── components/
    │   │   ├── KoreaBubbleMap.tsx     # 지도 레이어 (좌표 기반 버블맵)
    │   │   ├── RegionBarChart.tsx     # 시군구별 수입금액 바 차트
    │   │   ├── MetalBreakdownPanel.tsx# 클릭한 시군구의 금속별 비율 파이차트
    │   │   └── ExportPanel.tsx        # 엑셀(.xlsx) 내보내기 패널
    │   ├── App.tsx                    # 상태 관리 및 컴포넌트 조합
    │   └── types.ts
    └── package.json
```

### 데이터 흐름
1. `sigungu_metal_import_collector.py` (프로젝트 루트) 실행 → `sigungu_metal_imports.csv` 생성
2. FastAPI 백엔드가 CSV를 읽어 지역별/금속별로 집계한 REST API 제공
3. React 프론트엔드가 API를 호출해 지도/차트/리스트를 렌더링
4. 지도의 버블 또는 바 차트, 시군구 목록 중 하나를 클릭하면 `selectedRegion` 상태가
   바뀌고 `MetalBreakdownPanel`이 해당 시군구의 금속별 비율(파이차트)을 갱신

### 컴포넌트 상호작용 로직
- `App.tsx`가 `selectedRegion` state를 소유
- `KoreaBubbleMap`, `RegionBarChart`, 시군구 목록 모두 `onSelectRegion` 콜백을 공유
- `MetalBreakdownPanel`은 `regionName` prop이 바뀔 때마다
  `GET /api/regions/{region}/breakdown` 을 호출해 최신 비율을 로드

### 엑셀 내보내기
- `ExportPanel`에서 "전체 데이터 엑셀 다운로드" 또는 "선택 지역 상세 엑셀" 버튼 클릭
- 백엔드 `GET /api/export/excel`이 .xlsx 워크북을 반환
  - `region_name` 미지정: 시군구별 요약, 금속별 요약, 시군구×금속 금액 매트릭스, 원본 데이터
  - `region_name` 지정: 요약 + 선택 시군구 금속별 비중/추이 + 해당 지역 원본 데이터

## 실행 방법

### 1) 백엔드
```bash
cd dashboard/backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```
기본적으로 프로젝트 루트의 `../../sigungu_metal_imports.csv` 를 읽습니다.
다른 경로를 쓰려면 환경변수 `METAL_IMPORTS_CSV` 를 지정하세요.

### 2) 프론트엔드
```bash
cd dashboard/frontend
npm install
npm run dev
```
`http://localhost:5173` 접속 (Vite 프록시가 `/api` 요청을 `http://localhost:8000` 으로 전달)

### 3) Cloudflare Pages 배포
프론트엔드는 Cloudflare Pages에 정적 사이트로 배포할 수 있습니다.

#### GitHub Actions 자동 배포
1. Cloudflare Dashboard에서 `sigungu-metal-dashboard` Pages 프로젝트를 생성합니다.
2. GitHub 저장소 Secrets에 다음을 추가합니다.
   - `CLOUDFLARE_API_TOKEN`: Cloudflare API 토큰 (`Cloudflare Pages:Edit`, `Account:Read` 권한)
   - `CLOUDFLARE_ACCOUNT_ID`: Cloudflare 계정 ID
   - `VITE_API_BASE_URL`: Render 등에 배포된 백엔드 URL (예: `https://sigungu-metal-dashboard-api.onrender.com`)
3. `main` 브랜치에 `dashboard/frontend/**` 변경 사항을 push하면 자동으로 배포됩니다.

#### 수동 배포
```bash
cd dashboard/frontend
npm install
VITE_API_BASE_URL=https://<your-backend-url> npm run build
npx wrangler pages project create sigungu-metal-dashboard
npx wrangler pages deploy dist
```

## 알려진 제약 및 확장 포인트

- **지도**: 현재는 5개 대상 시군구의 위경도 좌표를 `backend/main.py`의
  `REGION_COORDINATES` 에 하드코딩하고, 프론트엔드에서 단순 좌표 투영으로
  버블맵을 그립니다. 실제 시군구 경계(Choropleth)가 필요하면
  `react-simple-maps` + 통계청/VWorld 행정구역 TopoJSON으로 `KoreaBubbleMap.tsx`를
  교체하세요.
- **수입중량(ton) 미제공**: 사용 중인 API(`getSigunguPerPrlstPerAcrs`)는 중량을
  제공하지 않아 수입금액(USD)/건수 기준으로 시각화합니다. 중량 데이터가 필요하면
  관세청_품목별 수출입실적(GW·전국 단위)의 HS코드별 중량/금액 비율로 근사하거나,
  중량을 제공하는 별도 API를 추가 연동해야 합니다.
- **데이터 갱신**: `POST /api/refresh` 호출 시 CSV 캐시를 다시 로드합니다.
  수집 스크립트를 크론으로 주기 실행 후 이 엔드포인트를 호출하면 자동 갱신됩니다.
- **신규 시군구 추가**: `TARGET_SIGUNGU_KEYWORDS`(수집 스크립트)와
  `REGION_COORDINATES`(백엔드)에 항목만 추가하면 됩니다.
