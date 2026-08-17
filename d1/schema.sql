-- Cloudflare D1 스키마: 월단위 시군구별 금속 수출입 통계 스냅샷
--
-- 목적
-- ----
-- 원천 데이터(관세청 시군구별 품목별 수출입실적, 68,000+ 행)를
-- [연월(YYYY-MM), 시군구명, 금속구분] 기준으로 1차 집계한 결과만 저장하여
-- 저장 용량을 최소화하고, 매월 15~20일경 전월/과거 정정 데이터가
-- 일괄 갱신될 때 전체 재적재 대신 UPSERT로 최신화한다.
--
-- 주의사항 (원천 API 제약)
-- ----------------------
-- - 관세청 API는 "시군구코드"를 제공하지 않는다. 응답에는 시군구명(sggNm)
--   문자열만 존재하므로, sigungu_code 컬럼에는 시군구명 문자열을 그대로
--   사용한다 (자연키). 예: "경상북도 포항시".
-- - 관세청 API는 수입/수출 중량(kg)을 제공하지 않는다. weight_kg 컬럼은
--   스키마 호환을 위해 존재하지만 원천 데이터가 없으므로 항상 0으로
--   기록된다. 추후 중량 제공 API가 확보되면 갱신 로직만 채우면 된다.

DROP TABLE IF EXISTS monthly_metal_stats;

CREATE TABLE monthly_metal_stats (
    year_month        TEXT    NOT NULL,  -- 'YYYY-MM'
    sigungu_code      TEXT    NOT NULL,  -- 시군구명 (예: '경상북도 포항시'). 공식 코드 미제공으로 자연키 사용
    metal_code         TEXT    NOT NULL,  -- 금속구분 (예: '철강', '구리', '알루미늄' 등)

    import_amount_usd REAL    NOT NULL DEFAULT 0,  -- 수입금액(USD) 합계
    import_count      INTEGER NOT NULL DEFAULT 0,  -- 수입건수 합계
    export_amount_usd REAL    NOT NULL DEFAULT 0,  -- 수출금액(USD) 합계
    export_count      INTEGER NOT NULL DEFAULT 0,  -- 수출건수 합계
    weight_kg         REAL    NOT NULL DEFAULT 0,  -- 중량(kg) 합계. 원천 API 미제공으로 항상 0

    updated_at        TEXT    NOT NULL,  -- 이 행이 마지막으로 UPSERT된 시각 (ISO 8601)

    PRIMARY KEY (year_month, sigungu_code, metal_code)
);

-- 대시보드에서 연월 + 시군구 필터로 조회할 때 이 인덱스를 타서 빠르게 반환된다.
-- (PRIMARY KEY 자체도 동일 컬럼 순서의 복합 인덱스이지만, 조회 패턴을 명시하기 위해
--  별도 인덱스로도 선언한다. SQLite/D1은 중복 인덱스를 만들어도 안전하다.)
CREATE INDEX IF NOT EXISTS idx_year_month_sigungu
    ON monthly_metal_stats (year_month, sigungu_code);

-- 금속구분 단독 필터(예: 특정 금속의 전국 월별 추이)를 위한 보조 인덱스
CREATE INDEX IF NOT EXISTS idx_year_month_metal
    ON monthly_metal_stats (year_month, metal_code);
