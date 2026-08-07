"""
OpenDART 재무 데이터 최적화 수집 스크립트
- 상호명 정제(clean_name)를 통한 corp_code 매칭
- 연도/보고서/재무제표 종류 fallback
- K-IFRS/K-GAAP 계정명 키워드 매핑
- 속도 최적화 및 API 호출 제한 준수
"""

import json
import os
import re
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from io import BytesIO
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

import requests

# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------
API_KEY = os.environ.get("DART_API_KEY")
if not API_KEY:
    raise SystemExit("DART_API_KEY 환경변수를 설정해주세요.")

INPUT_INDEX = "dashboard/backend/dart_metal_index.json"
OUTPUT_FILE = "dashboard/backend/dart_metal_index_financials.json"
STATE_FILE = "dashboard/backend/dart_metal_index_financials.state.json"

REPORT_CODE = "11011"  # 사업보고서
YEARS = ["2024", "2023", "2022"]  # 연도 fallback
FS_TYPES = [
    ("CFS", "연결"),
    ("OFS", "별도"),
]

REVENUE_KEYWORDS = ["매출액", "수익(매출액)", "매출", "영업수익"]
OP_PROFIT_KEYWORDS = ["영업이익", "영업이익(손실)"]

# 초당/요청간 대기 (ms)
MIN_CALL_INTERVAL = 0.18

# ---------------------------------------------------------------------------
# 이름 정제
# ---------------------------------------------------------------------------
def clean_name(name: str) -> str:
    """법인명에서 괄호, 띄어쓰기, 특수문자, 법인 형태 표기를 제거한다."""
    if not name:
        return ""
    # 1) 공백, 괄호, 특수문자 제거
    name = re.sub(r"[\s\(\)\[\]\{\}.,;:!?~`@#$%^&*\-_=+|\\<>'\"]", "", name)
    # 2) 법인 형태 표기 제거
    for pat in ["(주)", "(유)", "주식회사", "유한회사", "㈜"]:
        name = name.replace(pat, "")
    return name.strip()


# ---------------------------------------------------------------------------
# DART corpCode.xml 다운로드 및 매핑
# ---------------------------------------------------------------------------
def download_dart_corp_codes(api_key: str) -> Dict[str, Tuple[str, str, str]]:
    """
    DART 전체 법인코드 목록을 다운로드 후
    clean_name -> (corp_code, corp_name, stock_code) 매핑 반환
    """
    url = f"https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key={api_key}"
    print("DART corpCode.xml 다운로드 중...")
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()

    with zipfile.ZipFile(BytesIO(resp.content)) as z:
        xml_filename = [n for n in z.namelist() if n.endswith(".xml")][0]
        xml_bytes = z.read(xml_filename)

    # DART XML 인코딩은 보통 UTF-8, 아닐 경우 EUC-KR/CP949 fallback
    for enc in ("utf-8", "euc-kr", "cp949"):
        try:
            xml_str = xml_bytes.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise RuntimeError("XML 인코딩을 파싱할 수 없습니다.")

    root = ET.fromstring(xml_str)
    mapping: Dict[str, Tuple[str, str, str]] = {}

    for item in root.findall("list"):
        corp_code = (item.findtext("corp_code") or "").strip()
        corp_name = (item.findtext("corp_name") or "").strip()
        stock_code = (item.findtext("stock_code") or "").strip()
        if not corp_code or not corp_name:
            continue

        c_name = clean_name(corp_name)
        if not c_name:
            continue
        # 중복 이름은 stock_code 우선 또는 건너뜀
        if c_name not in mapping:
            mapping[c_name] = (corp_code, corp_name, stock_code)
        else:
            # 상장 기업이면 우선 사용
            _, _, existing_stock = mapping[c_name]
            if stock_code and not existing_stock:
                mapping[c_name] = (corp_code, corp_name, stock_code)

    print(f"DART 법인코드 매핑 완료: {len(mapping):,}개")
    return mapping


# ---------------------------------------------------------------------------
# 요청 속도 제어
# ---------------------------------------------------------------------------
class RateLimiter:
    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._last_call = 0.0
        self._lock = Lock()

    def wait(self):
        with self._lock:
            now = time.time()
            elapsed = now - self._last_call
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self._last_call = time.time()


limiter = RateLimiter(MIN_CALL_INTERVAL)


# ---------------------------------------------------------------------------
# API 호출
# ---------------------------------------------------------------------------
def fetch_financial(corp_code: str, year: str, fs_div: str) -> Optional[Dict[str, Any]]:
    """
    fnlttSinglAcntAll API 호출. 성공 시 JSON, 실패/데이터 없음 시 None.
    """
    url = (
        "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
        f"?crtfc_key={API_KEY}"
        f"&corp_code={corp_code}"
        f"&bsns_year={year}"
        f"&reprt_code={REPORT_CODE}"
        f"&fs_div={fs_div}"
    )

    limiter.wait()
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, json.JSONDecodeError):
        return None

    if data.get("status") != "000":
        return None

    items = data.get("list") or []
    if not items:
        return None

    revenue = find_amount(items, REVENUE_KEYWORDS)
    op_profit = find_amount(items, OP_PROFIT_KEYWORDS)

    if revenue is None or op_profit is None:
        return None

    return {
        "revenue": revenue,
        "op_profit": op_profit,
        "base_year": year,
        "fs_div": fs_div,
    }


def find_amount(items: List[Dict[str, Any]], keywords: List[str]) -> Optional[int]:
    """account_nm 키워드 리스트로 thstrm_amount를 찾아 정수 반환."""
    for item in items:
        account = (item.get("account_nm") or "").strip()
        if any(k in account for k in keywords):
            raw = (item.get("thstrm_amount") or "").replace(",", "").strip()
            try:
                val = int(raw)
                if val != 0:
                    return val
            except ValueError:
                continue
    return None


# ---------------------------------------------------------------------------
# 한 기업 처리
# ---------------------------------------------------------------------------
def process_company(
    idx: int,
    company: Dict[str, Any],
    dart_mapping: Dict[str, Tuple[str, str, str]],
    dart_codes: set,
) -> Optional[Tuple[str, Dict[str, Any]]]:
    """한 기업에 대해 year/fs fallback을 시도하고, 성공하면 (key, value) 반환."""
    bizr_no = (company.get("bizr_no") or "").strip()
    stock_code = (company.get("stock_code") or "").strip()
    index_name = company.get("corp_name", "").strip()
    index_code = (company.get("corp_code") or "").strip()

    # 1) clean_name 매칭
    c_name = clean_name(index_name)
    matched = dart_mapping.get(c_name)

    # 2) 매칭 실패 시 stock_code 매칭 시도
    if not matched and stock_code:
        for code, name, st in dart_mapping.values():
            if st == stock_code:
                matched = (code, name, st)
                break

    # 3) 그래도 실패 시 index에 있던 corp_code가 DART 목록에 있으면 사용
    if not matched and index_code in dart_codes:
        matched = (index_code, index_name, stock_code)

    if not matched:
        return None

    corp_code, dart_name, _ = matched

    # year/fs fallback
    for year in YEARS:
        for fs_div, _ in FS_TYPES:
            result = fetch_financial(corp_code, year, fs_div)
            if result:
                key = bizr_no if bizr_no else corp_code
                return key, {
                    "corp_name": dart_name or index_name,
                    "corp_code": corp_code,
                    "base_year": result["base_year"],
                    "fs_div": result["fs_div"],
                    "revenue": result["revenue"],
                    "op_profit": result["op_profit"],
                    "updated_at": datetime.now().isoformat(),
                }
    return None


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------
def main():
    with open(INPUT_INDEX, "r", encoding="utf-8") as f:
        index_data = json.load(f)

    companies = index_data.get("companies", [])
    if not companies:
        raise SystemExit(f"{INPUT_INDEX}에 기업 목록이 없습니다.")

    dart_mapping = download_dart_corp_codes(API_KEY)
    dart_codes = {code for code, _, _ in dart_mapping.values()}

    # 이전 상태( resume ) 복원
    results: Dict[str, Dict[str, Any]] = {}
    processed_names: set = set()
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                results = json.load(f)
            processed_names = {
                v["corp_code"] for v in results.values()
            }  # corp_code로 중복 방지
            print(f"이전 상태 복원: {len(results)}개")
        except json.JSONDecodeError:
            pass

    def should_process(company: Dict[str, Any]) -> bool:
        idx_code = (company.get("corp_code") or "").strip()
        idx_name = (company.get("corp_name") or "").strip()
        if idx_code in processed_names:
            return False
        # 이름 매칭된 기업 중 이미 처리된 코드는 제외
        c_name = clean_name(idx_name)
        matched = dart_mapping.get(c_name)
        if matched and matched[0] in processed_names:
            return False
        return True

    pending = [c for c in companies if should_process(c)]
    total = len(pending)
    print(f"처리 대상 기업: {total}개")

    def worker(args: Tuple[int, Dict[str, Any]]):
        i, company = args
        return i, process_company(i, company, dart_mapping, dart_codes)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {executor.submit(worker, (i, c)): i for i, c in enumerate(pending)}
        done_count = 0

        for future in as_completed(futures):
            try:
                _, out = future.result()
                if out:
                    key, value = out
                    results[key] = value
                done_count += 1

                if done_count % 50 == 0:
                    print(f"{done_count}/{total} 완료, 수집 {len(results)}개")
                    with open(STATE_FILE, "w", encoding="utf-8") as f:
                        json.dump(results, f, ensure_ascii=False, indent=2)

            except Exception as e:
                print(f"작업 중 오류: {e}")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # 임시 상태 파일 정리
    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)

    print(f"\n완료: {len(results)}개 기업 재무 데이터 수집")
    print(f"출력 파일: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
