# -*- coding: utf-8 -*-
"""
monthly_stats.py

원본 수출입 데이터(68,000+ 행)를 [연월, 시군구명, 금속구분] 기준으로 1차
집계하여 Cloudflare D1의 `monthly_metal_stats` 테이블에 UPSERT하는 로직.

매월 15~20일경 관세청 데이터가 전월/과거 정정 내역까지 일괄 현행화될 때,
`main.py`의 데이터 갱신 흐름(`DataCache._run_refresh`) 마지막 단계에서
`sync_monthly_stats_to_d1(df)`를 호출하면 D1 테이블도 함께 최신화된다.

주의
----
- 원천 API가 시군구코드를 제공하지 않으므로 시군구명을 자연키로 사용한다.
- 원천 API가 중량(kg)을 제공하지 않으므로 weight_kg은 항상 0으로 기록된다.
- D1 접속 정보(CLOUDFLARE_ACCOUNT_ID/CLOUDFLARE_D1_DATABASE_ID/CLOUDFLARE_API_TOKEN)가
  설정되지 않은 환경(예: 로컬 개발)에서는 동기화를 건너뛰고 경고만 남긴다.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

from d1_client import D1Client, D1ConfigError, get_d1_client

logger = logging.getLogger(__name__)

TABLE_NAME = "monthly_metal_stats"

COLUMNS = [
    "year_month",
    "sigungu_code",
    "metal_code",
    "import_amount_usd",
    "import_count",
    "export_amount_usd",
    "export_count",
    "weight_kg",
    "updated_at",
]
CONFLICT_COLUMNS = ["year_month", "sigungu_code", "metal_code"]
UPDATE_COLUMNS = [
    "import_amount_usd",
    "import_count",
    "export_amount_usd",
    "export_count",
    "weight_kg",
    "updated_at",
]


def aggregate_monthly_stats(df: pd.DataFrame) -> pd.DataFrame:
    """원본 df를 [연월, 시군구명, 금속구분] 기준으로 1차 집계한다.

    구버전 캐시(수출 필드 수집 전)와의 호환을 위해 수출 관련 컬럼이 없으면
    0으로 채운다. weight_kg은 원천 API 미제공으로 항상 0이다.
    """
    if df.empty:
        return pd.DataFrame(
            columns=[
                "연월",
                "시군구명",
                "금속구분",
                "수입금액(USD)",
                "수입건수",
                "수출금액(USD)",
                "수출건수",
            ]
        )

    work = df.copy()
    if "수출금액(USD)" not in work.columns:
        work["수출금액(USD)"] = 0.0
    if "수출건수" not in work.columns:
        work["수출건수"] = 0

    grouped = (
        work.groupby(["연월", "시군구명", "금속구분"], as_index=False)
        .agg(
            **{
                "수입금액(USD)": ("수입금액(USD)", "sum"),
                "수입건수": ("수입건수", "sum"),
                "수출금액(USD)": ("수출금액(USD)", "sum"),
                "수출건수": ("수출건수", "sum"),
            }
        )
    )
    return grouped


def _to_upsert_rows(aggregated: pd.DataFrame, updated_at: str) -> List[tuple]:
    rows: List[tuple] = []
    for _, r in aggregated.iterrows():
        rows.append(
            (
                str(r["연월"]),
                str(r["시군구명"]),
                str(r["금속구분"]),
                float(r["수입금액(USD)"]),
                int(r["수입건수"]),
                float(r["수출금액(USD)"]),
                int(r["수출건수"]),
                0.0,  # weight_kg: 원천 API 미제공
                updated_at,
            )
        )
    return rows


def sync_monthly_stats_to_d1(
    df: pd.DataFrame, client: Optional[D1Client] = None
) -> Dict[str, Any]:
    """df를 집계하여 D1 monthly_metal_stats 테이블에 UPSERT한다.

    D1이 설정되지 않은 환경에서는 건너뛰고 status="skipped"를 반환한다
    (기존 서비스 동작에는 영향을 주지 않는다).
    """
    client = client or get_d1_client()
    if not client.is_configured():
        logger.warning(
            "D1 접속 정보가 설정되지 않아 monthly_metal_stats 동기화를 건너뜁니다."
        )
        return {"status": "skipped", "reason": "d1_not_configured"}

    aggregated = aggregate_monthly_stats(df)
    if aggregated.empty:
        return {"status": "skipped", "reason": "no_data", "row_count": 0}

    updated_at = datetime.now(timezone.utc).isoformat()
    rows = _to_upsert_rows(aggregated, updated_at)

    try:
        total = client.upsert_rows(
            table=TABLE_NAME,
            columns=COLUMNS,
            conflict_columns=CONFLICT_COLUMNS,
            update_columns=UPDATE_COLUMNS,
            rows=rows,
        )
    except D1ConfigError as exc:
        logger.warning("D1 설정 오류로 동기화를 건너뜁니다: %s", exc)
        return {"status": "skipped", "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("D1 monthly_metal_stats UPSERT 실패: %s", exc)
        return {"status": "error", "reason": str(exc)}

    logger.info("D1 monthly_metal_stats 동기화 완료: %d행 UPSERT", total)
    return {"status": "ok", "row_count": total, "updated_at": updated_at}


def query_monthly_stats(
    client: Optional[D1Client] = None,
    year_month: Optional[str] = None,
    sigungu_code: Optional[str] = None,
    metal_code: Optional[str] = None,
    limit: int = 5000,
) -> List[Dict[str, Any]]:
    """idx_year_month_sigungu 인덱스를 타도록 (year_month, sigungu_code) 순서로
    필터 조건을 구성하여 조회한다. 조건이 없으면 최신 연월 상위 N행만 반환한다.
    """
    client = client or get_d1_client()
    if not client.is_configured():
        raise D1ConfigError("D1이 설정되지 않았습니다.")

    conditions = []
    params: List[Any] = []
    if year_month:
        conditions.append("year_month = ?")
        params.append(year_month)
    if sigungu_code:
        conditions.append("sigungu_code = ?")
        params.append(sigungu_code)
    if metal_code:
        conditions.append("metal_code = ?")
        params.append(metal_code)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = (
        f"SELECT year_month, sigungu_code, metal_code, import_amount_usd, "
        f"import_count, export_amount_usd, export_count, weight_kg, updated_at "
        f"FROM {TABLE_NAME} {where_clause} "
        f"ORDER BY year_month DESC, sigungu_code, metal_code "
        f"LIMIT ?"
    )
    params.append(limit)

    payload = client.query(sql, params)
    result = payload.get("result", [])
    if not result:
        return []
    return result[0].get("results", [])
