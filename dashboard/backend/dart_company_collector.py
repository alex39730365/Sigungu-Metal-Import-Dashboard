# -*- coding: utf-8 -*-
"""
DART 기업개황 정보를 수집하여 시군구별 본사/등록 사업장 주소 매핑을 만드는 스크립트.

관세청 '시군구별 품목별 수출입실적' API는 수입을 '납세의무자 주소지' 기준으로 집계하므로,
DART에 등록된 기업 주소를 같은 시군구 단위로 묶어 대시보드에서 연계 조회할 수 있게 합니다.

출력: dashboard/backend/dart_company_map.json
      { "서울특별시 강남구": [ { "corp_code", "corp_name", "stock_code", "adres", "induty_code" }, ... ], ... }

사용 예:
    set DART_API_KEY=<키>        (Windows cmd)
    python dart_company_collector.py

환경 변수:
    DART_API_KEY          (필수) DART OpenAPI 인증키
    DART_ONLY_LISTED      1 이면 상장기업(stock_code 존재)만 수집, 기본 0 (전체)
    DART_FILTER_INDUSTRY  1 이면 금속·화학·제조·무역 관련 업종만 필터, 기본 1
    DART_MAX_WORKERS      병렬 요청 수, 기본 8
"""
from __future__ import annotations

import io
import json
import os
import re
import time
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Set

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import xml.etree.ElementTree as ET

# ------------------------------------------------------------------------------
# 설정
# ------------------------------------------------------------------------------
API_KEY = os.environ.get("DART_API_KEY")
ONLY_LISTED = os.environ.get("DART_ONLY_LISTED", "0").strip() in ("1", "true", "True", "yes")
FILTER_INDUSTRY = os.environ.get("DART_FILTER_INDUSTRY", "1").strip() in ("1", "true", "True", "yes")
MAX_WORKERS = int(os.environ.get("DART_MAX_WORKERS", "6"))

CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"
COMPANY_URL = "https://opendart.fss.or.kr/api/company.json"


def _create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, application/xml, */*",
    })
    retries = Retry(
        total=5,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retries, pool_connections=MAX_WORKERS, pool_maxsize=MAX_WORKERS * 2)
    session.mount("https://", adapter)
    return session


_SESSION = _create_session()

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
OUTPUT_PATH = SCRIPT_DIR / "dart_company_map.json"

# 관세청 data_cache.json 의 시군구명을 기준 지역명으로 사용
CACHE_PATH = PROJECT_ROOT / "data_cache.json"

# 시도 명칭 정규화 (과거/줄임 표기 → 현재 공식 명칭)
SIDO_NAME_MAP = {
    "강원": "강원특별자치도",
    "강원도": "강원특별자치도",
    "전라북도": "전북특별자치도",
    "전북": "전북특별자치도",
    "전라남도": "전라남도",
    "경상북도": "경상북도",
    "경상남도": "경상남도",
    "충청북도": "충청북도",
    "충청남도": "충청남도",
    "경기": "경기도",
    "경기도": "경기도",
    "제주": "제주특별자치도",
    "제주도": "제주특별자치도",
    "세종": "세종특별자치시",
    "세종시": "세종특별자치시",
}

# 본 기능에서 우선 보여줄 업종(표준산업분류 기준)
# 금속광물 도매업, 1차 금속제품 도매업, 비철금속 도매업, 철강제품 도매업 등
# '1차 금속제품 및 금속광물 도매업' 군(4672)에 해당하는 코드로 제한
RELEVANT_INDUSTRY_PREFIXES = ("4672",)


def load_valid_regions() -> Set[str]:
    """data_cache.json 의 시군구명을 유효 지역 집합으로 반환."""
    if not CACHE_PATH.exists():
        return set()
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        rows = data.get("rows", data if isinstance(data, list) else [])
        return {str(r.get("시군구명", "")).strip() for r in rows if r.get("시군구명")}
    except Exception as e:
        print(f"[경고] data_cache.json 로드 실패: {e}")
        return set()


def normalize_sido(token: str) -> str:
    return SIDO_NAME_MAP.get(token, token)


def extract_sigungu(address: str) -> Optional[str]:
    """DART 기업 주소에서 '시도명 시군구명' 형태로 추출."""
    if not address:
        return None

    # 괄호 내용 제거, 공백 정리
    cleaned = re.sub(r"\([^)]*\)", "", address)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # 세종특별자치시는 단독 지역
    if cleaned.startswith("세종"):
        return "세종특별자치시"

    sido_pattern = (
        r"(서울특별시|부산광역시|대구광역시|인천광역시|광주광역시|"
        r"대전광역시|울산광역시|세종특별자치시|세종시|제주특별자치도|제주도|"
        r"강원특별자치도|강원도|경기도|경상북도|경상남도|전라남도|"
        r"전북특별자치도|전라북도|전북|충청북도|충청남도)"
    )
    # 첫 번째 시/군/구 토큰만 취함 (예: "경기도 성남시 분당구" → "경기도 성남시")
    pattern = re.compile(rf"{sido_pattern}\s+([^\s]+(?:시|군|구))")
    match = pattern.search(cleaned)
    if not match:
        return None

    sido = normalize_sido(match.group(1))
    sigungu = match.group(2)
    return f"{sido} {sigungu}"


def is_relevant_industry(induty_code: Optional[str]) -> bool:
    """업종코드가 '1차 금속제품 및 금속광물 도매업' 군(4672)에 속하면 True."""
    if not induty_code:
        return False  # 코드가 없으면 제외
    return any(induty_code.startswith(p) for p in RELEVANT_INDUSTRY_PREFIXES)


def fetch_corp_codes() -> List[Dict[str, str]]:
    """DART 고유번호 목록(zip+xml)을 다운로드하고 파싱."""
    print("DART 고유번호 목록 다운로드 중...")
    resp = _SESSION.get(CORP_CODE_URL, params={"crtfc_key": API_KEY}, timeout=120)
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        xml_name = next((n for n in z.namelist() if n.lower().endswith(".xml")), None)
        if not xml_name:
            raise RuntimeError("CORPCODE xml 파일을 찾을 수 없습니다.")
        with z.open(xml_name) as xml_file:
            tree = ET.parse(xml_file)

    root = tree.getroot()
    corps = []
    for node in root.findall("list"):
        corp_code = (node.findtext("corp_code") or "").strip()
        corp_name = (node.findtext("corp_name") or "").strip()
        stock_code = (node.findtext("stock_code") or "").strip()
        if not corp_code:
            continue
        if ONLY_LISTED and not stock_code:
            continue
        corps.append({"corp_code": corp_code, "corp_name": corp_name, "stock_code": stock_code})
    print(f"수집 대상 기업 수: {len(corps):,}")
    return corps


def fetch_company_info(corp_code: str, corp_name: str) -> Optional[Dict]:
    """DART 기업개황 API를 호출하여 주소 등 정보를 반환."""
    try:
        resp = _SESSION.get(
            COMPANY_URL,
            params={"crtfc_key": API_KEY, "corp_code": corp_code},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None

    if data.get("status") != "000":
        return None

    adres = (data.get("adres") or "").strip()
    if not adres:
        return None

    induty_code = (data.get("induty_code") or "").strip()
    if FILTER_INDUSTRY and not is_relevant_industry(induty_code):
        return None

    return {
        "corp_code": corp_code,
        "corp_name": (data.get("corp_name") or corp_name).strip(),
        "stock_code": (data.get("stock_code") or "").strip(),
        "adres": adres,
        "induty_code": induty_code,
    }


def collect_companies(corps: List[Dict[str, str]], valid_regions: Set[str]) -> Dict[str, List[Dict]]:
    """병렬로 기업개황을 수집하고 시군구별로 그룹화."""
    region_map: Dict[str, List[Dict]] = defaultdict(list)
    skipped = 0
    success = 0

    print(f"기업개황 병렬 수집 시작 (workers={MAX_WORKERS})...")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_corp = {
            executor.submit(fetch_company_info, c["corp_code"], c["corp_name"]): c
            for c in corps
        }
        for i, future in enumerate(as_completed(future_to_corp)):
            info = future.result()
            if info is None:
                skipped += 1
                continue

            region = extract_sigungu(info["adres"])
            if not region or region not in valid_regions:
                skipped += 1
                continue

            region_map[region].append(info)
            success += 1

            if (i + 1) % 500 == 0:
                print(f"  ... {i + 1:,}/{len(corps):,} 처리, 성공 {success:,}, 스킵 {skipped:,}")

            # 서버 부하 방지용 짧은 대기
            if (i + 1) % MAX_WORKERS == 0:
                time.sleep(0.05)

    # 각 지역 내 회사명 가나다순 정렬
    for region in region_map:
        region_map[region].sort(key=lambda x: x["corp_name"])

    return dict(region_map)


def main() -> None:
    if not API_KEY:
        raise RuntimeError("DART_API_KEY 환경변수를 설정해주세요.")

    valid_regions = load_valid_regions()
    if not valid_regions:
        raise RuntimeError("data_cache.json 에서 유효한 시군구명을 찾을 수 없습니다.")
    print(f"유효한 시군구 수: {len(valid_regions):,}")

    corps = fetch_corp_codes()
    if not corps:
        raise RuntimeError("수집할 기업이 없습니다.")

    region_map = collect_companies(corps, valid_regions)
    total = sum(len(v) for v in region_map.values())
    print(f"매핑 완료: 지역 {len(region_map):,}개, 기업 {total:,}개")

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(region_map, f, ensure_ascii=False, indent=2)
    print(f"저장 완료: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
