
# -*- coding: utf-8 -*-
"""
sigungu_metal_import_collector.py

대한민국 공공데이터포털(data.go.kr) 관세청 API를 이용해
귀금속을 제외한 주요 산업용 비귀금속(철강·구리·알루미늄·니켈·아연·납·주석·마그네슘·코발트·몰리브덴·텅스텐·티타늄·기타희유금속·리튬화합물 등)의
지역별(시도/시군구) 수입 데이터를 수집, 가공, 분석, 저장하는 스크립트.

사용 API
--------
관세청_시군구별 품목별 수출입실적 (실측으로 확인된 실제 스펙)
- 공공데이터포털 상세페이지: https://www.data.go.kr/data/15134343/openapi.do
- 요청주소: https://apis.data.go.kr/1220000/sigunguperprlstperacrs/getSigunguPerPrlstPerAcrs
- 요청 파라미터: serviceKey, strtYymm(시작년월 YYYYMM), endYymm(종료년월 YYYYMM,
  strtYymm~endYymm 최대 1년 이내), HsSgn(HS Code, 반드시 6자리), sidoCd(시도코드 2자리)
- 응답 필드: hsSgn, korePrlstNm(품목명), priodTitle(기간, "YYYY.MM"),
  sggNm(지역명 - 광역시는 "○○광역시 ○○구", 도는 "○○도 ○○시/군" 형태),
  expCnt/expUsdAmt(수출건수/금액), impCnt/impUsdAmt(수입건수/금액), cmtrBlncAmt(무역수지)

!! 중요 제약사항 !!
- 이 API는 지역 필터링에 "시군구코드"가 아닌 "시도코드(sidoCd)"만 사용합니다.
  응답의 sggNm 필드에 시군구명까지 포함되어 나오지만, 특정 시군구만 콕 집어
  조회하는 것은 불가능하며 시도 단위로 조회 후 결과에서 원하는 시군구명으로
  필터링해야 합니다.
- 이 API는 수입중량(kg)을 제공하지 않습니다. 제공되는 수치는 수입건수(impCnt)와
  수입금액(impUsdAmt)뿐입니다. 따라서 본 스크립트의 Top3 분석은
  요구사항의 "수입중량(kg)" 대신 "수입금액(USD)" 기준으로 수행합니다.
- impUsdAmt/expUsdAmt는 "천 달러" 단위입니다. 본 스크립트는 USD_AMOUNT_UNIT을 곱해
  실제 달러 금액으로 환산한 뒤 "수입금액(USD)" 컬럼에 저장합니다.
- HsSgn은 반드시 6자리여야 합니다(4자리 입력 시 "품목코드는 6자리로 입력해야
  합니다" 오류 발생). 이에 따라 7201/7204/7208/7209/7403/7601/7502 같은 4자리
  HS Code는 WCO HS 표준의 하위 6자리 세번으로 확장하여 조회합니다.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd
import requests
from requests.adapters import HTTPAdapter, Retry

# ------------------------------------------------------------------------------
# 1. 설정(CONFIG)
# ------------------------------------------------------------------------------

# 공공데이터포털에서 발급받은 서비스키 (Decoding 키 권장)
SERVICE_KEY = "21c3a7130b45aa44a1f4c71804810b183e48a420fbb8a26721466ad626a0c6ea"

# 관세청_시군구별 품목별 수출입실적 API 요청주소 (실측으로 정상 동작 확인됨)
END_POINT = "https://apis.data.go.kr/1220000/sigunguperprlstperacrs/getSigunguPerPrlstPerAcrs"

# API의 수출입금액(expUsdAmt/impUsdAmt)은 천 달러 단위이므로 실제 달러로 환산할 때 곱하는 값
USD_AMOUNT_UNIT = 1000

REQUEST_TIMEOUT = 15  # seconds
# 이 API는 초당 호출 횟수가 엄격하게 제한되어 있어, 워커(쓰리딜)별로 개별 sleep을 둔는 대신
# 모든 워커가 같이 준수하는 전역(global) 최소 호출 간격을 강제한다 (_throttle 함수 참조).
GLOBAL_MIN_INTERVAL_SEC = float(os.environ.get("METAL_API_MIN_INTERVAL_SEC", "1.0"))
NUM_OF_ROWS = 500

# ------------------------------------------------------------------------------
# 2. 대상 HS Code(6자리) 및 금속 카테고리 매핑
# ------------------------------------------------------------------------------
# 이 API는 HsSgn 파라미터가 반드시 6자리여야 하므로, 요구사항의 4자리 HS Code는
# WCO HS 2022 기준 하위 6자리 세번(subheading) 전체로 확장했습니다.
# 실제 세관 통계 기준 필요 여부에 따라 목록을 조정하세요.

# 4자리(또는 이미 6자리인) 원본 HS Code -> (금속 카테고리, 품목명)
HS_HEADING_INFO: Dict[str, Dict[str, str]] = {
    "282520": {
        "metal": "리튬화합물",
        "name": "수산화리튬"
    },
    "283691": {
        "metal": "리튬화합물",
        "name": "탄산리튬"
    },
    "7201": {
        "metal": "철강",
        "name": "Pig iron and spiegeleisen in pigs, blocks or other primary forms"
    },
    "7202": {
        "metal": "철강",
        "name": "Ferro-alloys"
    },
    "7203": {
        "metal": "철강",
        "name": "Ferrous products obtained by direct reduction of iron ore and other spongy ferrous products, in lumps, pellets or the like; iron having a minimum purity of 99.9"
    },
    "7204": {
        "metal": "철강",
        "name": "Ferrous waste and scrap; remelting scrap ingots of iron or steel"
    },
    "7205": {
        "metal": "철강",
        "name": "Granules and powders, of pig iron, spiegeleisen, iron or steel"
    },
    "7206": {
        "metal": "철강",
        "name": "Iron and non-alloy steel in ingots or other primary forms (excluding iron of heading no. 7203)"
    },
    "7207": {
        "metal": "철강",
        "name": "Iron or non-alloy steel; semi-finished products thereof"
    },
    "7208": {
        "metal": "철강",
        "name": "Iron or non-alloy steel; flat-rolled products of a width of 600mm or more, hot-rolled, not clad, plated or coated"
    },
    "7209": {
        "metal": "철강",
        "name": "Iron or non-alloy steel; flat-rolled products, width 600mm or more, cold-rolled (cold-reduced), not clad, plated or coated"
    },
    "7210": {
        "metal": "철강",
        "name": "Iron or non-alloy steel; flat-rolled products, width 600mm or more, clad, plated or coated"
    },
    "7211": {
        "metal": "철강",
        "name": "Iron or non-alloy steel; flat-rolled products, width less than 600mm, not clad, plated or coated"
    },
    "7212": {
        "metal": "철강",
        "name": "Iron or non-alloy steel; flat-rolled products, width less than 600mm, clad, plated or coated"
    },
    "7213": {
        "metal": "철강",
        "name": "Iron or non-alloy steel; bars and rods, hot-rolled, in irregularly wound coils"
    },
    "7214": {
        "metal": "철강",
        "name": "Iron or non-alloy steel; bars and rods, not further worked than forged, hot-rolled, hot drawn or hot-extruded, but including those twisted after rolling"
    },
    "7215": {
        "metal": "철강",
        "name": "Iron or non-alloy steel; bars and rods, n.e.c. in chapter 72"
    },
    "7216": {
        "metal": "철강",
        "name": "Iron or non-alloy steel, angles, shapes and sections"
    },
    "7217": {
        "metal": "철강",
        "name": "Wire of iron or non-alloy steel"
    },
    "7218": {
        "metal": "철강",
        "name": "Stainless steel in ingots or other primary forms; semi-finished products of stainless steel"
    },
    "7219": {
        "metal": "철강",
        "name": "Stainless steel; flat-rolled products of width of 600mm or more"
    },
    "7220": {
        "metal": "철강",
        "name": "Stainless steel; flat-rolled products of width less than 600mm"
    },
    "7221": {
        "metal": "철강",
        "name": "Stainless steel bars and rods, hot-rolled, in irregularly wound coils"
    },
    "7222": {
        "metal": "철강",
        "name": "Stainless steel bars and rods, angles, shapes and sections"
    },
    "7223": {
        "metal": "철강",
        "name": "Stainless steel wire"
    },
    "7224": {
        "metal": "철강",
        "name": "Alloy steel in ingots or other primary forms, semi-finished products of other alloy steel"
    },
    "7225": {
        "metal": "철강",
        "name": "Alloy steel flat-rolled products, of a width 600mm or more"
    },
    "7226": {
        "metal": "철강",
        "name": "Alloy steel flat-rolled products, of a width of less than 600mm"
    },
    "7227": {
        "metal": "철강",
        "name": "Steel, alloy; bars and rods, hot-rolled, in irregularly wound coils"
    },
    "7228": {
        "metal": "철강",
        "name": "Alloy steel bars, rods, shapes and sections; hollow drill bars and rods, of alloy or non-alloy steel"
    },
    "7229": {
        "metal": "철강",
        "name": "Wire of other alloy steel"
    },
    "7401": {
        "metal": "구리",
        "name": "Copper mattes; cement copper (precipitated copper)"
    },
    "7402": {
        "metal": "구리",
        "name": "Copper; unrefined, copper anodes for electrolytic refining"
    },
    "7403": {
        "metal": "구리",
        "name": "Copper; refined and copper alloys, unwrought"
    },
    "7404": {
        "metal": "구리",
        "name": "Copper; waste and scrap"
    },
    "7405": {
        "metal": "구리",
        "name": "Copper; master alloys"
    },
    "7406": {
        "metal": "구리",
        "name": "Copper; powders and flakes"
    },
    "7407": {
        "metal": "구리",
        "name": "Copper; bars, rods and profiles"
    },
    "7408": {
        "metal": "구리",
        "name": "Copper wire"
    },
    "7409": {
        "metal": "구리",
        "name": "Copper plates, sheets and strip; of a thickness exceeding 0.15mm"
    },
    "7410": {
        "metal": "구리",
        "name": "Copper foil (whether or not printed or backed with paper, paperboard, plastics or similar backing materials) of a thickness (excluding any backing) not exceedin"
    },
    "7411": {
        "metal": "구리",
        "name": "Copper tubes and pipes"
    },
    "7412": {
        "metal": "구리",
        "name": "Copper; tube or pipe fittings (e.g. couplings, elbows, sleeves)"
    },
    "7413": {
        "metal": "구리",
        "name": "Copper; stranded wire, cables, plaited bands and the like, not electrically insulated"
    },
    "7415": {
        "metal": "구리",
        "name": "Copper, nails, tacks, drawing pins, staples (not those of heading no. 8305) and the like, of copper or iron or steel with heads of copper; screws bolts, nuts, s"
    },
    "7418": {
        "metal": "구리",
        "name": "Copper; table, kitchen or other household articles and parts thereof; pot scourers, scouring, polishing pads, gloves and the like; sanitary ware and parts there"
    },
    "7419": {
        "metal": "구리",
        "name": "Copper; articles thereof n.e.c. in chapter 74"
    },
    "7501": {
        "metal": "니켈",
        "name": "Nickel mattes; nickel oxide sinters and other intermediate products of nickel metallurgy"
    },
    "7502": {
        "metal": "니켈",
        "name": "Nickel; unwrought"
    },
    "7503": {
        "metal": "니켈",
        "name": "Nickel; waste and scrap"
    },
    "7504": {
        "metal": "니켈",
        "name": "Nickel; powders and flakes"
    },
    "7505": {
        "metal": "니켈",
        "name": "Nickel; bars, rods, profiles and wire"
    },
    "7506": {
        "metal": "니켈",
        "name": "Nickel; plates, sheets, strip and foil"
    },
    "7507": {
        "metal": "니켈",
        "name": "Nickel; tubes, pipes and tube or pipe fittings (e.g. couplings, elbows, sleeves)"
    },
    "7508": {
        "metal": "니켈",
        "name": "Nickel; articles thereof n.e.c. in chapter 75"
    },
    "7601": {
        "metal": "알루미늄",
        "name": "Aluminium; unwrought"
    },
    "7602": {
        "metal": "알루미늄",
        "name": "Aluminium; waste and scrap"
    },
    "7603": {
        "metal": "알루미늄",
        "name": "Aluminium; powders and flakes"
    },
    "7604": {
        "metal": "알루미늄",
        "name": "Aluminium; bars, rods and profiles"
    },
    "7605": {
        "metal": "알루미늄",
        "name": "Aluminium wire"
    },
    "7606": {
        "metal": "알루미늄",
        "name": "Aluminium; plates, sheets and strip, thickness exceeding 0.2mm"
    },
    "7607": {
        "metal": "알루미늄",
        "name": "Aluminium foil (whether or not printed or backed with paper, paperboard, plastics or similar backing materials) of a thickness (excluding any backing) not excee"
    },
    "7608": {
        "metal": "알루미늄",
        "name": "Aluminium; tubes and pipes"
    },
    "7609": {
        "metal": "알루미늄",
        "name": "Aluminium; tube or pipe fittings (e.g. couplings, elbows, sleeves)"
    },
    "7610": {
        "metal": "알루미늄",
        "name": "Aluminium; structures (excluding prefabricated buildings of heading no. 9406) and parts (e.g. bridges and sections, towers, lattice masts, etc) plates, rods, pr"
    },
    "7611": {
        "metal": "알루미늄",
        "name": "Aluminium; reservoirs, tanks, vats and the like for material (not compressed or liquefied gas) of capacity over 300l, whether or not lined, heat-insulated, not "
    },
    "7612": {
        "metal": "알루미늄",
        "name": "Aluminium casks, drums, cans, boxes etc (including rigid, collapsible tubular containers), for materials other than compressed, liquefied gas, 300l capacity or "
    },
    "7613": {
        "metal": "알루미늄",
        "name": "Aluminium; containers for compressed or liquefied gas"
    },
    "7614": {
        "metal": "알루미늄",
        "name": "Aluminium; stranded wire, cables, plaited bands and the like, (not electrically insulated)"
    },
    "7615": {
        "metal": "알루미늄",
        "name": "Aluminium; table, kitchen or other household articles and parts thereof, pot scourers and scouring or polishing pads, gloves and the like, sanitary ware and par"
    },
    "7616": {
        "metal": "알루미늄",
        "name": "Aluminium; articles n.e.c. in chapter 76"
    },
    "7801": {
        "metal": "납",
        "name": "Lead; unwrought"
    },
    "7802": {
        "metal": "납",
        "name": "Lead; waste and scrap"
    },
    "7804": {
        "metal": "납",
        "name": "Lead; plates, sheets, strip and foil, lead powders and flakes"
    },
    "7806": {
        "metal": "납",
        "name": "Lead; articles n.e.c. in chapter 78"
    },
    "7901": {
        "metal": "아연",
        "name": "Zinc; unwrought"
    },
    "7902": {
        "metal": "아연",
        "name": "Zinc; waste and scrap"
    },
    "7903": {
        "metal": "아연",
        "name": "Zinc; dust, powders and flakes"
    },
    "7904": {
        "metal": "아연",
        "name": "Zinc; bars, rods, profiles and wire"
    },
    "7905": {
        "metal": "아연",
        "name": "Zinc; plates, sheets, strip and foil"
    },
    "7907": {
        "metal": "아연",
        "name": "Zinc; articles n.e.c. in chapter 79"
    },
    "8001": {
        "metal": "주석",
        "name": "Tin; unwrought"
    },
    "8002": {
        "metal": "주석",
        "name": "Tin; waste and scrap"
    },
    "8003": {
        "metal": "주석",
        "name": "Tin; bars, rods, profiles and wire"
    },
    "8007": {
        "metal": "주석",
        "name": "Tin; articles n.e.c. in chapter 80"
    },
    "8101": {
        "metal": "텅스텐",
        "name": "Tungsten (wolfram); articles thereof, including waste and scrap"
    },
    "8102": {
        "metal": "몰리브덴",
        "name": "Molybdenum; articles thereof, including waste and scrap"
    },
    "8103": {
        "metal": "탄탈륨",
        "name": "Tantalum; articles thereof, including waste and scrap"
    },
    "8104": {
        "metal": "마그네슘",
        "name": "Magnesium; articles thereof, including waste and scrap"
    },
    "8105": {
        "metal": "코발트",
        "name": "Cobalt; mattes and other intermediate products of cobalt metallurgy, cobalt and articles thereof, including waste and scrap"
    },
    "8106": {
        "metal": "비스무트",
        "name": "Bismuth; articles thereof, including waste and scrap"
    },
    "8108": {
        "metal": "티타늄",
        "name": "Titanium; articles thereof, including waste and scrap"
    },
    "8109": {
        "metal": "지르코늄",
        "name": "Zirconium; articles thereof, including waste and scrap"
    },
    "8110": {
        "metal": "안티모니",
        "name": "Antimony; articles thereof, including waste and scrap"
    },
    "8111": {
        "metal": "망간",
        "name": "Manganese; articles thereof, including waste and scrap"
    },
    "8112": {
        "metal": "기타희유금속",
        "name": "Beryllium, chromium, hafnium, rhenium, thallium, cadmium, germanium, vanadium, gallium, indium and niobium (columbium), articles of these metals, including wast"
    }
}

# 4자리 HS Code -> 하위 6자리 세번(subheading) 목록 (WCO HS 2022 기준)
HS4_TO_HS6_SUBCODES: Dict[str, List[str]] = {
    "7201": [
        "720110",
        "720120",
        "720150"
    ],
    "7202": [
        "720211",
        "720219",
        "720221",
        "720229",
        "720230",
        "720241",
        "720249",
        "720250",
        "720260",
        "720270",
        "720280",
        "720291",
        "720292",
        "720293",
        "720299"
    ],
    "7203": [
        "720310",
        "720390"
    ],
    "7204": [
        "720410",
        "720421",
        "720429",
        "720430",
        "720441",
        "720449",
        "720450"
    ],
    "7205": [
        "720510",
        "720521",
        "720529"
    ],
    "7206": [
        "720610",
        "720690"
    ],
    "7207": [
        "720711",
        "720712",
        "720719",
        "720720"
    ],
    "7208": [
        "720810",
        "720825",
        "720826",
        "720827",
        "720836",
        "720837",
        "720838",
        "720839",
        "720840",
        "720851",
        "720852",
        "720853",
        "720854",
        "720890"
    ],
    "7209": [
        "720915",
        "720916",
        "720917",
        "720918",
        "720925",
        "720926",
        "720927",
        "720928",
        "720990"
    ],
    "7210": [
        "721011",
        "721012",
        "721020",
        "721030",
        "721041",
        "721049",
        "721050",
        "721061",
        "721069",
        "721070",
        "721090"
    ],
    "7211": [
        "721113",
        "721114",
        "721119",
        "721123",
        "721129",
        "721190"
    ],
    "7212": [
        "721210",
        "721220",
        "721230",
        "721240",
        "721250",
        "721260"
    ],
    "7213": [
        "721310",
        "721320",
        "721391",
        "721399"
    ],
    "7214": [
        "721410",
        "721420",
        "721430",
        "721491",
        "721499"
    ],
    "7215": [
        "721510",
        "721550",
        "721590"
    ],
    "7216": [
        "721610",
        "721621",
        "721622",
        "721631",
        "721632",
        "721633",
        "721640",
        "721650",
        "721661",
        "721669",
        "721691",
        "721699"
    ],
    "7217": [
        "721710",
        "721720",
        "721730",
        "721790"
    ],
    "7218": [
        "721810",
        "721891",
        "721899"
    ],
    "7219": [
        "721911",
        "721912",
        "721913",
        "721914",
        "721921",
        "721922",
        "721923",
        "721924",
        "721931",
        "721932",
        "721933",
        "721934",
        "721935",
        "721990"
    ],
    "7220": [
        "722011",
        "722012",
        "722020",
        "722090"
    ],
    "7221": [
        "722100"
    ],
    "7222": [
        "722211",
        "722219",
        "722220",
        "722230",
        "722240"
    ],
    "7223": [
        "722300"
    ],
    "7224": [
        "722410",
        "722490"
    ],
    "7225": [
        "722511",
        "722519",
        "722530",
        "722540",
        "722550",
        "722591",
        "722592",
        "722599"
    ],
    "7226": [
        "722611",
        "722619",
        "722620",
        "722691",
        "722692",
        "722699"
    ],
    "7227": [
        "722710",
        "722720",
        "722790"
    ],
    "7228": [
        "722810",
        "722820",
        "722830",
        "722840",
        "722850",
        "722860",
        "722870",
        "722880"
    ],
    "7229": [
        "722920",
        "722990"
    ],
    "7401": [
        "740100"
    ],
    "7402": [
        "740200"
    ],
    "7403": [
        "740311",
        "740312",
        "740313",
        "740319",
        "740321",
        "740322",
        "740329"
    ],
    "7404": [
        "740400"
    ],
    "7405": [
        "740500"
    ],
    "7406": [
        "740610",
        "740620"
    ],
    "7407": [
        "740710",
        "740721",
        "740729"
    ],
    "7408": [
        "740811",
        "740819",
        "740821",
        "740822",
        "740829"
    ],
    "7409": [
        "740911",
        "740919",
        "740921",
        "740929",
        "740931",
        "740939",
        "740940",
        "740990"
    ],
    "7410": [
        "741011",
        "741012",
        "741021",
        "741022"
    ],
    "7411": [
        "741110",
        "741121",
        "741122",
        "741129"
    ],
    "7412": [
        "741210",
        "741220"
    ],
    "7413": [
        "741300"
    ],
    "7415": [
        "741510",
        "741521",
        "741529",
        "741533",
        "741539"
    ],
    "7418": [
        "741810",
        "741820"
    ],
    "7419": [
        "741920",
        "741980"
    ],
    "7501": [
        "750110",
        "750120"
    ],
    "7502": [
        "750210",
        "750220"
    ],
    "7503": [
        "750300"
    ],
    "7504": [
        "750400"
    ],
    "7505": [
        "750511",
        "750512",
        "750521",
        "750522"
    ],
    "7506": [
        "750610",
        "750620"
    ],
    "7507": [
        "750711",
        "750712",
        "750720"
    ],
    "7508": [
        "750810",
        "750890"
    ],
    "7601": [
        "760110",
        "760120"
    ],
    "7602": [
        "760200"
    ],
    "7603": [
        "760310",
        "760320"
    ],
    "7604": [
        "760410",
        "760421",
        "760429"
    ],
    "7605": [
        "760511",
        "760519",
        "760521",
        "760529"
    ],
    "7606": [
        "760611",
        "760612",
        "760691",
        "760692"
    ],
    "7607": [
        "760711",
        "760719",
        "760720"
    ],
    "7608": [
        "760810",
        "760820"
    ],
    "7609": [
        "760900"
    ],
    "7610": [
        "761010",
        "761090"
    ],
    "7611": [
        "761100"
    ],
    "7612": [
        "761210",
        "761290"
    ],
    "7613": [
        "761300"
    ],
    "7614": [
        "761410",
        "761490"
    ],
    "7615": [
        "761510",
        "761520"
    ],
    "7616": [
        "761610",
        "761691",
        "761699"
    ],
    "7801": [
        "780110",
        "780191",
        "780199"
    ],
    "7802": [
        "780200"
    ],
    "7804": [
        "780411",
        "780419",
        "780420"
    ],
    "7806": [
        "780600"
    ],
    "7901": [
        "790111",
        "790112",
        "790120"
    ],
    "7902": [
        "790200"
    ],
    "7903": [
        "790310",
        "790390"
    ],
    "7904": [
        "790400"
    ],
    "7905": [
        "790500"
    ],
    "7907": [
        "790700"
    ],
    "8001": [
        "800110",
        "800120"
    ],
    "8002": [
        "800200"
    ],
    "8003": [
        "800300"
    ],
    "8007": [
        "800700"
    ],
    "8101": [
        "810110",
        "810194",
        "810196",
        "810197",
        "810199"
    ],
    "8102": [
        "810210",
        "810294",
        "810295",
        "810296",
        "810297",
        "810299"
    ],
    "8103": [
        "810320",
        "810330",
        "810391",
        "810399"
    ],
    "8104": [
        "810411",
        "810419",
        "810420",
        "810430",
        "810490"
    ],
    "8105": [
        "810520",
        "810530",
        "810590"
    ],
    "8106": [
        "810610",
        "810690"
    ],
    "8108": [
        "810820",
        "810830",
        "810890"
    ],
    "8109": [
        "810921",
        "810929",
        "810931",
        "810939",
        "810991",
        "810999"
    ],
    "8110": [
        "811010",
        "811020",
        "811090"
    ],
    "8111": [
        "811100"
    ],
    "8112": [
        "811212",
        "811213",
        "811219",
        "811221",
        "811222",
        "811229",
        "811231",
        "811239",
        "811241",
        "811249",
        "811251",
        "811252",
        "811259",
        "811261",
        "811269",
        "811292",
        "811299"
    ]
}


# 6자리 HS Code -> (금속 카테고리, 품목명) : 위 4자리 정보를 6자리 단위로 펼친 매핑
HS6_CODE_METAL_MAP: Dict[str, str] = {}
HS6_CODE_NAME_MAP: Dict[str, str] = {}
HS6_TO_HS4: Dict[str, str] = {}

for _hs_code, _info in HS_HEADING_INFO.items():
    if _hs_code in HS4_TO_HS6_SUBCODES:
        for _hs6 in HS4_TO_HS6_SUBCODES[_hs_code]:
            HS6_CODE_METAL_MAP[_hs6] = _info["metal"]
            HS6_CODE_NAME_MAP[_hs6] = _info["name"]
            HS6_TO_HS4[_hs6] = _hs_code
    else:
        # 이미 6자리인 HS Code(리튬화합물)는 그대로 사용
        HS6_CODE_METAL_MAP[_hs_code] = _info["metal"]
        HS6_CODE_NAME_MAP[_hs_code] = _info["name"]
        HS6_TO_HS4[_hs_code] = _hs_code

TARGET_HS6_CODES: List[str] = list(HS6_CODE_METAL_MAP.keys())

# ------------------------------------------------------------------------------
# 3. 대상 시도 코드 (행정표준코드 2자리)
#    이 API는 시군구 단위가 아닌 "시도 단위"로만 지역을 필터링할 수 있습니다.
#    관심 시군구가 속한 시도를 조회한 뒤, 응답의 sggNm 필드로 시군구를 필터링합니다.
# ------------------------------------------------------------------------------

TARGET_SIDO_MAP: Dict[str, str] = {
    "11": "서울특별시",
    "26": "부산광역시",
    "27": "대구광역시",
    "28": "인천광역시",
    "29": "광주광역시",
    "30": "대전광역시",
    "31": "울산광역시",
    "36": "세종특별자치시",
    "41": "경기도",
    "51": "강원특별자치도",
    "43": "충청북도",
    "44": "충청남도",
    "52": "전북특별자치도",
    "46": "전라남도",
    "47": "경상북도",
    "48": "경상남도",
    "50": "제주특별자치도",
}

# 결과 필터링 시 관심 시군구 키워드(응답 sggNm 문자열에 포함 여부로 매칭)
# 필요 시 자유롭게 추가/수정 가능. 비워두면(빈 리스트) 시도 전체 시군구를 포함.
TARGET_SIGUNGU_KEYWORDS: List[str] = []

# ------------------------------------------------------------------------------
# 4. 응답 필드 정의 (실측으로 확인된 실제 응답 스키마)
# ------------------------------------------------------------------------------
# 예시 응답 item:
# <cmtrBlncAmt>-60</cmtrBlncAmt><expCnt>0</expCnt><expUsdAmt>0</expUsdAmt>
# <hsSgn>720449</hsSgn><impCnt>2</impCnt><impUsdAmt>60</impUsdAmt>
# <korePrlstNm>기타</korePrlstNm><priodTitle>2024.01</priodTitle>
# <sggNm>경상북도 포항시</sggNm>

RESPONSE_FIELD_CANDIDATES: Dict[str, List[str]] = {
    "year_month": ["priodTitle"],
    "region_nm": ["sggNm"],
    "hs_cd": ["hsSgn"],
    "item_nm": ["korePrlstNm"],
    "imp_cnt": ["impCnt"],
    "imp_dlr": ["impUsdAmt"],
    "exp_cnt": ["expCnt"],
    "exp_dlr": ["expUsdAmt"],
    "trade_balance": ["cmtrBlncAmt"],
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ------------------------------------------------------------------------------
# 5. HTTP 세션 (재시도 포함)
# ------------------------------------------------------------------------------

def _build_session() -> requests.Session:
    session = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=2.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET"]),
        respect_retry_after_header=True,
    )
    session.mount("http://", HTTPAdapter(max_retries=retries))
    session.mount("https://", HTTPAdapter(max_retries=retries))
    return session


SESSION = _build_session()

_THREAD_LOCAL = threading.local()


def _get_thread_session() -> requests.Session:
    if not getattr(_THREAD_LOCAL, "session", None):
        _THREAD_LOCAL.session = _build_session()
    return _THREAD_LOCAL.session


# 여러 워커 스레드가 함께 지키는 전역 레이트 리밋을 위한 락(lock)과 마지막 요청 시각
_RATE_LIMIT_LOCK = threading.Lock()
_last_request_ts = 0.0


def _throttle() -> None:
    """모든 워커 스레드가 공유하는 전역 기준으로, 적어도 GLOBAL_MIN_INTERVAL_SEC만큼의
    간격을 둔 다음에 실제 HTTP 요청을 보낸다. ThreadPoolExecutor의 병렬 워커 수와
    무관하게 실제 관세청 API 호출 속도가 이 간격을 넘지 않도록 강제하여 429(Too Many
    Requests) 폭주를 원천적으로 방지한다."""
    global _last_request_ts
    with _RATE_LIMIT_LOCK:
        now = time.monotonic()
        wait = GLOBAL_MIN_INTERVAL_SEC - (now - _last_request_ts)
        if wait > 0:
            time.sleep(wait)
        _last_request_ts = time.monotonic()


# ------------------------------------------------------------------------------
# 6. 응답 파싱 유틸
# ------------------------------------------------------------------------------

def _first_present(item: Dict[str, Any], candidates: List[str]) -> Optional[str]:
    """item 딕셔너리에서 candidates 중 처음으로 존재하는 키의 값을 반환."""
    for key in candidates:
        if key in item and item[key] not in (None, ""):
            return str(item[key]).strip()
    return None


def _parse_xml_items(xml_text: str) -> List[Dict[str, Any]]:
    """공공데이터포털 표준 XML 응답(response/body/items/item)을 파싱."""
    root = ET.fromstring(xml_text)

    # 오류 응답 처리: <OpenAPI_ServiceResponse> 형태로 오는 경우가 있음
    err_msg = root.find(".//errMsg")
    if err_msg is not None:
        auth_msg = root.findtext(".//returnAuthMsg", default="")
        raise RuntimeError(f"OpenAPI 오류 응답: {err_msg.text} ({auth_msg})")

    result_code = root.findtext(".//resultCode")
    result_msg = root.findtext(".//resultMsg")
    if result_code is not None and result_code not in ("00", "0"):
        raise RuntimeError(f"API 오류: resultCode={result_code}, resultMsg={result_msg}")

    items = []
    for item_el in root.findall(".//items/item"):
        row = {child.tag: (child.text or "").strip() for child in item_el}
        items.append(row)
    return items


def _parse_json_items(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """공공데이터포털 표준 JSON 응답(response.body.items)을 파싱."""
    response = payload.get("response", payload)
    header = response.get("header", {})
    result_code = str(header.get("resultCode", "00"))
    if result_code not in ("00", "0"):
        raise RuntimeError(
            f"API 오류: resultCode={result_code}, resultMsg={header.get('resultMsg')}"
        )

    body = response.get("body", {})
    items = body.get("items", [])
    if isinstance(items, dict):
        items = items.get("item", [])
    if isinstance(items, dict):
        items = [items]
    return items or []


def parse_response(raw_text: str, content_type: str = "") -> List[Dict[str, Any]]:
    """XML 또는 JSON 응답을 자동 감지하여 파싱. 실패 시 예외를 발생시킴."""
    stripped = raw_text.strip()
    try:
        if stripped.startswith("{") or "json" in content_type.lower():
            import json

            return _parse_json_items(json.loads(stripped))
        return _parse_xml_items(stripped)
    except ET.ParseError as exc:
        raise RuntimeError(f"XML 파싱 실패: {exc}\n원본 응답 일부: {stripped[:300]}") from exc


# ------------------------------------------------------------------------------
# 7. API 호출
# ------------------------------------------------------------------------------

@dataclass
class ImportRecord:
    year_month: str
    sido_cd: str
    region_nm: str
    hs_cd: str
    item_nm: str
    imp_cnt: int
    imp_amt_usd: float
    metal_category: str
    exp_cnt: int = 0
    exp_amt_usd: float = 0.0


def fetch_import_data(
    hs6_code: str,
    sido_cd: str,
    strt_yymm: str,
    end_yymm: str,
    page_no: int = 1,
    num_of_rows: int = NUM_OF_ROWS,
    session: Optional[requests.Session] = None,
) -> List[Dict[str, Any]]:
    """단일 6자리 HS Code / 시도 / 조회기간(strt_yymm~end_yymm, 최대 1년)에 대한
    시군구별 수출입 실적을 조회한다."""
    params = {
        "serviceKey": SERVICE_KEY,
        "strtYymm": strt_yymm,
        "endYymm": end_yymm,
        "HsSgn": hs6_code,
        "sidoCd": sido_cd,
        "pageNo": page_no,
        "numOfRows": num_of_rows,
    }

    sess = session or SESSION
    _throttle()
    try:
        resp = sess.get(END_POINT, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.exceptions.RequestException as exc:
        logger.error(
            "요청 실패 (hs=%s, sido=%s, %s~%s): %s", hs6_code, sido_cd, strt_yymm, end_yymm, exc
        )
        return []

    try:
        items = parse_response(resp.text, resp.headers.get("Content-Type", ""))
    except RuntimeError as exc:
        logger.warning(
            "응답 파싱/오류 (hs=%s, sido=%s, %s~%s): %s", hs6_code, sido_cd, strt_yymm, end_yymm, exc
        )
        return []

    return items


def normalize_items(
    raw_items: Iterable[Dict[str, Any]],
    fallback_hs6_code: str,
    fallback_sido_cd: str,
) -> List[ImportRecord]:
    """원본 API 응답 딕셔너리 목록을 ImportRecord 목록으로 정규화."""
    records: List[ImportRecord] = []

    for raw in raw_items:
        hs_cd = _first_present(raw, RESPONSE_FIELD_CANDIDATES["hs_cd"]) or fallback_hs6_code
        region_nm = _first_present(raw, RESPONSE_FIELD_CANDIDATES["region_nm"]) or ""
        year_month_raw = _first_present(raw, RESPONSE_FIELD_CANDIDATES["year_month"]) or ""
        year_month = year_month_raw.replace(".", "-")
        item_nm = _first_present(raw, RESPONSE_FIELD_CANDIDATES["item_nm"]) or HS6_CODE_NAME_MAP.get(
            fallback_hs6_code, ""
        )

        imp_cnt_raw = _first_present(raw, RESPONSE_FIELD_CANDIDATES["imp_cnt"])
        imp_dlr_raw = _first_present(raw, RESPONSE_FIELD_CANDIDATES["imp_dlr"])
        exp_cnt_raw = _first_present(raw, RESPONSE_FIELD_CANDIDATES["exp_cnt"])
        exp_dlr_raw = _first_present(raw, RESPONSE_FIELD_CANDIDATES["exp_dlr"])

        try:
            imp_cnt = int(float(imp_cnt_raw)) if imp_cnt_raw not in (None, "") else 0
        except ValueError:
            imp_cnt = 0
        try:
            imp_dlr = (
                float(imp_dlr_raw.replace(",", "")) if imp_dlr_raw not in (None, "") else 0.0
            )
        except ValueError:
            imp_dlr = 0.0
        try:
            exp_cnt = int(float(exp_cnt_raw)) if exp_cnt_raw not in (None, "") else 0
        except ValueError:
            exp_cnt = 0
        try:
            exp_dlr = (
                float(exp_dlr_raw.replace(",", "")) if exp_dlr_raw not in (None, "") else 0.0
            )
        except ValueError:
            exp_dlr = 0.0

        metal_category = HS6_CODE_METAL_MAP.get(fallback_hs6_code, "기타")

        records.append(
            ImportRecord(
                year_month=year_month,
                sido_cd=fallback_sido_cd,
                region_nm=region_nm,
                hs_cd=hs_cd,
                item_nm=item_nm,
                imp_cnt=imp_cnt,
                imp_amt_usd=imp_dlr * USD_AMOUNT_UNIT,
                metal_category=metal_category,
                exp_cnt=exp_cnt,
                exp_amt_usd=exp_dlr * USD_AMOUNT_UNIT,
            )
        )

    return records


# ------------------------------------------------------------------------------
# 8. 전체 수집 루프
# ------------------------------------------------------------------------------

def _split_yymm_ranges(strt_yymm: str, end_yymm: str) -> List[tuple]:
    """strtYymm~endYymm 구간을 API 제약(최대 1년)에 맞춰 1년 단위로 분할한다."""
    strt_y, strt_m = int(strt_yymm[:4]), int(strt_yymm[4:])
    end_y, end_m = int(end_yymm[:4]), int(end_yymm[4:])

    ranges = []
    cur_y, cur_m = strt_y, strt_m
    while (cur_y, cur_m) <= (end_y, end_m):
        if cur_m == 1:
            chunk_end_y, chunk_end_m = cur_y, 12
        else:
            chunk_end_y, chunk_end_m = cur_y + 1, cur_m - 1
        if (chunk_end_y, chunk_end_m) > (end_y, end_m):
            chunk_end_y, chunk_end_m = end_y, end_m

        ranges.append((f"{cur_y:04d}{cur_m:02d}", f"{chunk_end_y:04d}{chunk_end_m:02d}"))

        if chunk_end_m == 12:
            cur_y, cur_m = chunk_end_y + 1, 1
        else:
            cur_y, cur_m = chunk_end_y, chunk_end_m + 1

    return ranges


BASE_DIR = Path(__file__).resolve().parent
PROGRESS_PATH = BASE_DIR / "sigungu_metal_imports_progress.json"
OUTPUT_PATH = BASE_DIR / "sigungu_metal_imports.csv"
CHECKPOINT_EVERY = 100  # 이 개수만큼 호출할 때마다 CSV+진행률을 중간 저장
MAX_WORKERS = 6  # 병렬 API 호출 수 (API 부하/차단 주의)


def _load_progress() -> int:
    """이전에 완료된 target 인덱스(0-based, 없으면 0)를 반환."""
    if Path(PROGRESS_PATH).exists():
        try:
            with open(PROGRESS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return int(data.get("completed_index", 0))
        except Exception:  # noqa: BLE001
            return 0
    return 0


def _save_progress(completed_index: int) -> None:
    with open(PROGRESS_PATH, "w", encoding="utf-8") as f:
        json.dump({"completed_index": completed_index}, f, ensure_ascii=False)


def _records_to_df(records: List["ImportRecord"]) -> pd.DataFrame:
    columns = [
        "연월",
        "시도코드",
        "시군구명",
        "HS코드",
        "품목명",
        "금속구분",
        "수입건수",
        "수입금액(USD)",
        "수출건수",
        "수출금액(USD)",
    ]
    if not records:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(
        [
            {
                "연월": r.year_month,
                "시도코드": r.sido_cd,
                "시군구명": r.region_nm,
                "HS코드": r.hs_cd,
                "품목명": r.item_nm,
                "금속구분": r.metal_category,
                "수입건수": r.imp_cnt,
                "수입금액(USD)": r.imp_amt_usd,
                "수출건수": r.exp_cnt,
                "수출금액(USD)": r.exp_amt_usd,
            }
            for r in records
        ]
    )


def _append_and_save_csv(output_path: str, new_records: List["ImportRecord"], sigungu_keywords: Optional[List[str]]) -> None:
    """새 레코드를 기존 CSV에 병합하고 중복 제거 후 저장."""
    new_df = _records_to_df(new_records)
    if sigungu_keywords:
        pattern = "|".join(re.escape(k) for k in sigungu_keywords)
        new_df = new_df[new_df["시군구명"].str.contains(pattern, regex=True, na=False)].reset_index(drop=True)

    if Path(output_path).exists():
        try:
            existing_df = pd.read_csv(output_path, encoding="utf-8-sig")
        except Exception:  # noqa: BLE001
            existing_df = pd.DataFrame()
    else:
        existing_df = pd.DataFrame()

    if not existing_df.empty:
        combined = pd.concat([existing_df, new_df], ignore_index=True).drop_duplicates().reset_index(drop=True)
    else:
        combined = new_df

    combined.to_csv(output_path, index=False, encoding="utf-8-sig")


def _fetch_target(idx: int, total_calls: int, target: tuple, output_path: str) -> tuple:
    """단일 target에 대해 API 호출/정규화를 수행. (병렬 worker용)"""
    range_strt, range_end, hs6_code, sido_cd, sido_nm = target
    logger.info(
        "[%d/%d] 조회 중: %s~%s HS=%s 시도=%s(%s)",
        idx,
        total_calls,
        range_strt,
        range_end,
        hs6_code,
        sido_nm,
        sido_cd,
    )

    try:
        session = _get_thread_session()
        raw_items = fetch_import_data(
            hs6_code=hs6_code,
            sido_cd=sido_cd,
            strt_yymm=range_strt,
            end_yymm=range_end,
            session=session,
        )
        records = normalize_items(
            raw_items,
            fallback_hs6_code=hs6_code,
            fallback_sido_cd=sido_cd,
        )
    except Exception as exc:  # noqa: BLE001 - 수집 루프는 계속 진행되어야 함
        logger.exception(
            "예상치 못한 오류 (hs=%s, sido=%s, %s~%s): %s",
            hs6_code,
            sido_cd,
            range_strt,
            range_end,
            exc,
        )
        records = []
    finally:
        time.sleep(REQUEST_INTERVAL_SEC)

    return idx, records


def collect_all_import_data(
    strt_yymm: str,
    end_yymm: str,
    hs6_codes: Optional[List[str]] = None,
    sido_map: Optional[Dict[str, str]] = None,
    sigungu_keywords: Optional[List[str]] = None,
    output_path: str = str(OUTPUT_PATH),
    resume: bool = True,
) -> pd.DataFrame:
    """대상 조회기간 x HS코드(6자리) x 시도 전체 조합에 대해 수입 데이터를 수집하고,
    필요 시 관심 시군구 키워드로 결과를 필터링한다.
    CHECKPOINT_EVERY 호출마다 중간 결과를 CSV에 저장하고 진행률을 기록해,
    중단 후 재실행하면 마지막 체크포인트부터 자동으로 이어서 진행된다.
    병렬 처리를 위해 ThreadPoolExecutor를 사용한다."""
    hs6_codes = hs6_codes or TARGET_HS6_CODES
    sido_map = sido_map or TARGET_SIDO_MAP
    sigungu_keywords = TARGET_SIGUNGU_KEYWORDS if sigungu_keywords is None else sigungu_keywords

    yymm_ranges = _split_yymm_ranges(strt_yymm, end_yymm)

    all_targets = [
        (range_strt, range_end, hs6_code, sido_cd, sido_nm)
        for range_strt, range_end in yymm_ranges
        for hs6_code in hs6_codes
        for sido_cd, sido_nm in sido_map.items()
    ]
    total_calls = len(all_targets)

    start_index = _load_progress() if resume else 0
    if start_index > 0:
        logger.info("체크포인트 발견: %d번째부터 이어서 진행합니다.", start_index + 1)
    if start_index >= total_calls:
        logger.info("모든 항목이 이미 수집 완료되었습니다.")
        if Path(output_path).exists():
            try:
                return pd.read_csv(output_path, encoding="utf-8-sig")
            except Exception:  # noqa: BLE001
                pass
        return pd.DataFrame()

    pending_targets = all_targets[start_index:]
    pending_iter = iter(enumerate(pending_targets, start=start_index + 1))

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        while True:
            # CHECKPOINT_EVERY개씩 묶어 병렬 처리 후 저장 (중간에 중단되도 안전)
            chunk = []
            for _ in range(CHECKPOINT_EVERY):
                try:
                    idx, target = next(pending_iter)
                except StopIteration:
                    break
                future = executor.submit(_fetch_target, idx, total_calls, target, output_path)
                chunk.append((idx, target, future))

            if not chunk:
                break

            pending_records: List[ImportRecord] = []
            chunk_max_idx = start_index
            for idx, target, future in chunk:
                try:
                    _, records = future.result()
                    pending_records.extend(records)
                    chunk_max_idx = idx
                except Exception as exc:  # noqa: BLE001
                    range_strt, range_end, hs6_code, sido_cd, _ = target
                    logger.exception(
                        "worker 결과 처리 중 오류 (hs=%s, sido=%s, %s~%s): %s",
                        hs6_code,
                        sido_cd,
                        range_strt,
                        range_end,
                        exc,
                    )

            if pending_records:
                _append_and_save_csv(output_path, pending_records, sigungu_keywords)
            _save_progress(chunk_max_idx)
            logger.info("체크포인트 저장: %d/%d 까지 완료, CSV 중간 저장됨", chunk_max_idx, total_calls)

    if Path(output_path).exists():
        try:
            return pd.read_csv(output_path, encoding="utf-8-sig")
        except Exception:  # noqa: BLE001
            pass
    return pd.DataFrame()


# ------------------------------------------------------------------------------
# 9. 시군구별 Top3 금속 분석
# ------------------------------------------------------------------------------

def analyze_top3_metals_by_sigungu(
    df: pd.DataFrame, value_col: str = "수입금액(USD)"
) -> pd.DataFrame:
    """시군구별로 수입량이 가장 높은 금속(금속구분 그룹) Top 3를 반환.

    이 API는 수입중량(kg)을 제공하지 않으므로 기본 순위 기준은 "수입금액(USD)"이며,
    "수입건수" 컬럼으로도 동일하게 분석할 수 있습니다.

    Parameters
    ----------
    df : 수집된 원본 DataFrame (필요 컬럼: 시군구명, 금속구분, value_col)
    value_col : 순위 산정 기준 컬럼. "수입금액(USD)" 또는 "수입건수".

    Returns
    -------
    시군구명, 순위, 금속구분, 합계값 컬럼을 갖는 DataFrame
    """
    if df.empty:
        return pd.DataFrame(columns=["시군구명", "순위", "금속구분", value_col])

    grouped = (
        df.groupby(["시군구명", "금속구분"], as_index=False)[value_col]
        .sum()
        .sort_values(["시군구명", value_col], ascending=[True, False])
    )

    grouped["순위"] = grouped.groupby("시군구명")[value_col].rank(
        method="first", ascending=False
    ).astype(int)

    top3 = grouped[grouped["순위"] <= 3].sort_values(["시군구명", "순위"])
    return top3[["시군구명", "순위", "금속구분", value_col]].reset_index(drop=True)


# ------------------------------------------------------------------------------
# 10. 메인 실행부
# ------------------------------------------------------------------------------

def main() -> None:
    strt_yymm = "202401"
    end_yymm = "202412"

    logger.info("데이터 수집을 시작합니다... (%s ~ %s)", strt_yymm, end_yymm)
    # collect_all_import_data 가 체크포인트 기반으로 CSV를 직접 누적 저장하며,
    # 중단 후 재실행 시 마지막 체크포인트부터 자동으로 이어서 진행한다.
    df = collect_all_import_data(strt_yymm=strt_yymm, end_yymm=end_yymm)
    logger.info("원본 데이터를 %s 에 저장했습니다. (행 수: %d)", str(OUTPUT_PATH), len(df))

    top3_df = analyze_top3_metals_by_sigungu(df, value_col="수입금액(USD)")
    top3_output_path = "sigungu_metal_imports_top3.csv"
    top3_df.to_csv(top3_output_path, index=False, encoding="utf-8-sig")
    logger.info("시군구별 Top3 금속 분석 결과를 %s 에 저장했습니다.", top3_output_path)

    if not top3_df.empty:
        print("\n=== 시군구별 수입금액(USD) 기준 Top 3 금속 ===")
        print(top3_df.to_string(index=False))


if __name__ == "__main__":
    main()
