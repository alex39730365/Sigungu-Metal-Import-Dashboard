# -*- coding: utf-8 -*-
"""
supabase_client.py

Supabase PostgreSQL 연결 클라이언트 (psycopg2-binary 사용).
- DATABASE_URL 또는 SUPABASE_DB_URL 환경변수로 연결한다.
- 수집된 수출입 원시 데이터(raw_metal_imports)를 upsert한다.
- 수집 진행률(collection_progress)을 저장/복원한다.
- FastAPI DataCache 가 서버 재시작 후에도 DB에서 마지막 데이터를 로드할 수 있게 한다.
"""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Any, List, Optional

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

logger = logging.getLogger(__name__)

RAW_TABLE = "raw_metal_imports"
PROGRESS_TABLE = "collection_progress"

# DB 컬럼(영문) -> 수집/대시보드용 한글 컬럼
COLUMN_KOREAN = {
    "year_month": "연월",
    "sido_cd": "시도코드",
    "sigungu_name": "시군구명",
    "hs_code": "HS코드",
    "item_name": "품목명",
    "metal_category": "금속구분",
    "import_count": "수입건수",
    "import_amount_usd": "수입금액(USD)",
    "export_count": "수출건수",
    "export_amount_usd": "수출금액(USD)",
}

DIMENSION_COLUMNS = list(COLUMN_KOREAN.keys())
# target_key: 6개 차원 컬럼을 SHA256 해싱한 값으로, 긴 텍스트 PK 문제를 피함
RAW_COLUMNS = ["target_key"] + DIMENSION_COLUMNS + ["updated_at"]
CONFLICT_COLUMNS = ["target_key"]
UPDATE_COLUMNS = [
    "import_count",
    "import_amount_usd",
    "export_count",
    "export_amount_usd",
    "updated_at",
]

UPSERT_CHUNK = 1000


def _make_target_key(
    year_month: str,
    sido_cd: str,
    sigungu_name: str,
    hs_code: str,
    item_name: str,
    metal_category: str,
) -> str:
    """6개 차원 값으로 고유 target_key를 생성한다."""
    raw = f"{year_month}|{sido_cd}|{sigungu_name}|{hs_code}|{item_name}|{metal_category}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class SupabaseClient:
    def __init__(self, dsn: Optional[str] = None) -> None:
        self.dsn = dsn or os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL")

    def is_configured(self) -> bool:
        return bool(self.dsn)

    def _connect(self):
        if not self.dsn:
            raise RuntimeError(
                "Supabase 연결을 위해 DATABASE_URL 또는 SUPABASE_DB_URL 환경변수가 필요합니다."
            )
        return psycopg2.connect(self.dsn)

    def ensure_tables(self) -> None:
        """필요한 테이블이 없으면 생성한다."""
        if not self.is_configured():
            logger.warning("Supabase DSN이 설정되지 않아 ensure_tables를 건너뜁니다.")
            return

        raw_table_sql = f"""
        CREATE TABLE IF NOT EXISTS {RAW_TABLE} (
            target_key TEXT PRIMARY KEY,
            year_month TEXT NOT NULL,
            sido_cd TEXT NOT NULL,
            sigungu_name TEXT NOT NULL,
            hs_code TEXT NOT NULL,
            item_name TEXT NOT NULL,
            metal_category TEXT NOT NULL,
            import_count INTEGER NOT NULL DEFAULT 0,
            import_amount_usd NUMERIC(20, 2) NOT NULL DEFAULT 0,
            export_count INTEGER NOT NULL DEFAULT 0,
            export_amount_usd NUMERIC(20, 2) NOT NULL DEFAULT 0,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """

        progress_table_sql = f"""
        CREATE TABLE IF NOT EXISTS {PROGRESS_TABLE} (
            task_name TEXT PRIMARY KEY,
            completed_index INTEGER NOT NULL DEFAULT 0,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(raw_table_sql)
                cur.execute(progress_table_sql)

    def save_progress(self, completed_index: int, task_name: str = "metal_imports") -> None:
        if not self.is_configured():
            return

        sql = f"""
        INSERT INTO {PROGRESS_TABLE} (task_name, completed_index, updated_at)
        VALUES (%s, %s, NOW())
        ON CONFLICT (task_name) DO UPDATE SET
            completed_index = EXCLUDED.completed_index,
            updated_at = EXCLUDED.updated_at
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (task_name, completed_index))

    def load_progress(self, task_name: str = "metal_imports") -> int:
        if not self.is_configured():
            return 0

        sql = f"SELECT completed_index FROM {PROGRESS_TABLE} WHERE task_name = %s"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (task_name,))
                row = cur.fetchone()
                return int(row[0]) if row else 0

    def get_last_progress_updated(self, task_name: str = "metal_imports") -> Optional[datetime]:
        if not self.is_configured():
            return None

        sql = f"SELECT updated_at FROM {PROGRESS_TABLE} WHERE task_name = %s"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (task_name,))
                row = cur.fetchone()
                return row[0] if row else None

    def upsert_raw_records(self, records: List[Any], updated_at: Optional[datetime] = None) -> int:
        """ImportRecord 객체(또는 동일 속성을 가진 객체) 목록을 upsert한다."""
        if not self.is_configured():
            logger.warning("Supabase DSN이 설정되지 않아 DB 저장을 건너뜁니다.")
            return 0
        if not records:
            return 0

        if updated_at is None:
            updated_at = datetime.now(timezone.utc)

        rows: List[tuple] = []
        for r in records:
            year_month = getattr(r, "year_month", "")
            sido_cd = getattr(r, "sido_cd", "")
            sigungu_name = getattr(r, "region_nm", "")
            hs_code = getattr(r, "hs_cd", "")
            item_name = getattr(r, "item_nm", "")
            metal_category = getattr(r, "metal_category", "")
            target_key = _make_target_key(
                year_month, sido_cd, sigungu_name, hs_code, item_name, metal_category
            )
            rows.append(
                (
                    target_key,
                    year_month,
                    sido_cd,
                    sigungu_name,
                    hs_code,
                    item_name,
                    metal_category,
                    getattr(r, "imp_cnt", 0),
                    getattr(r, "imp_amt_usd", 0.0),
                    getattr(r, "exp_cnt", 0),
                    getattr(r, "exp_amt_usd", 0.0),
                    updated_at,
                )
            )

        col_list = ", ".join(RAW_COLUMNS)
        conflict_list = ", ".join(CONFLICT_COLUMNS)
        update_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in UPDATE_COLUMNS)

        sql = (
            f"INSERT INTO {RAW_TABLE} ({col_list}) VALUES %s "
            f"ON CONFLICT ({conflict_list}) DO UPDATE SET {update_clause}"
        )

        with self._connect() as conn:
            with conn.cursor() as cur:
                execute_values(cur, sql, rows, page_size=UPSERT_CHUNK)

        return len(rows)

    def load_raw_records(self) -> pd.DataFrame:
        """DB에 저장된 원본 데이터를 수집/대시보드용 한글 컬럼 DataFrame으로 반환한다."""
        if not self.is_configured():
            return pd.DataFrame(columns=list(COLUMN_KOREAN.values()))

        select_cols = ", ".join(RAW_COLUMNS[1:-1])  # target_key, updated_at 제외
        sql = f"SELECT {select_cols} FROM {RAW_TABLE}"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchall()
                cols = [desc[0] for desc in cur.description]

        df = pd.DataFrame(rows, columns=cols)
        df = df.rename(columns=COLUMN_KOREAN)

        for c in ("수입건수", "수출건수"):
            if c in df.columns:
                df[c] = df[c].astype(int)
        for c in ("수입금액(USD)", "수출금액(USD)"):
            if c in df.columns:
                df[c] = df[c].astype(float)

        return df

    def raw_record_count(self) -> int:
        if not self.is_configured():
            return 0

        sql = f"SELECT COUNT(*) FROM {RAW_TABLE}"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                row = cur.fetchone()
                return int(row[0]) if row else 0


def get_supabase_client() -> SupabaseClient:
    return SupabaseClient()
