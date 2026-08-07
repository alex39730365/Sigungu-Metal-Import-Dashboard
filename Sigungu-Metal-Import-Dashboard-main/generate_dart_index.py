#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
OpenDART에서 전체 기업 목록을 받아 금속/철강 관련 기업만 추려
`dashboard/backend/dart_metal_index.json`을 생성하는 스크립트.

로컬 실행 방법:
    DART_API_KEY="<키>" python generate_dart_index.py

Windows PowerShell:
    $env:DART_API_KEY="<키>"
    python generate_dart_index.py
"""
import os
import sys
from pathlib import Path

# dashboard/backend 내 DartCompanyIndex 모듈 import
_BACKEND_DIR = Path(__file__).resolve().parent / "dashboard" / "backend"
sys.path.insert(0, str(_BACKEND_DIR))

from dart_company_index import DartCompanyIndex


def main() -> int:
    api_key = os.environ.get("DART_API_KEY")
    if not api_key:
        print("오류: DART_API_KEY 환경변수를 설정해주세요.")
        return 1

    print("DART 금속 기업 인덱스 생성 시작...")
    idx = DartCompanyIndex(api_key, cache_dir=_BACKEND_DIR)
    ok = idx.trigger_refresh()
    if not ok:
        print("오류: 인덱스 생성에 실패했습니다. 네트워크/API 키를 확인해주세요.")
        return 1

    print(f"완료: {idx.cache_path} 에 {len(idx.companies)} 건 저장")
    return 0


if __name__ == "__main__":
    sys.exit(main())
