# -*- coding: utf-8 -*-
"""
setup_supabase_schema.py

Supabase(PostgreSQL)에 수집/대시보드에 필요한 테이블을 생성한다.
- raw_metal_imports: 관세청 원본 수출입 데이터
- collection_progress: 수집 체크포인트(마지막 완료 인덱스)

사용법:
    DATABASE_URL="postgresql://..." python scripts/setup_supabase_schema.py
"""

from __future__ import annotations

import logging
import os
import sys

# 프로젝트 루트에 있는 supabase_client.py 를 import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase_client import get_supabase_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    client = get_supabase_client()
    if not client.is_configured():
        logger.error(
            "DATABASE_URL 또는 SUPABASE_DB_URL 환경변수가 설정되지 않았습니다. "
            "Supabase Dashboard > Project Settings > Database 에서 Connection string 을 복사해주세요."
        )
        sys.exit(1)

    client.ensure_tables()
    logger.info("Supabase 테이블 생성/확인 완료: raw_metal_imports, collection_progress")
    logger.info("현재 저장된 raw 행 수: %d", client.raw_record_count())
    logger.info("현재 체크포인트: %d", client.load_progress())


if __name__ == "__main__":
    main()
