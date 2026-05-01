"""SEC EDGAR 클라이언트 — 미국 상장사 공시 재무제표 조회.

근거: 미국 증권거래위원회(https://www.sec.gov/edgar) 공식 데이터
라이선스: 17 U.S.C. § 105 — 미국 정부 저작물 = Public Domain (상업 이용 무제한)
호출 한도: 초당 10 요청 (User-Agent 헤더 필수)

yfinance가 부실 응답 줄 때 미국 종목 재무 데이터의 1차 소스로 사용.
DART(한국)와 동일한 인터페이스로 설계 → app.py가 같은 패턴으로 병합 가능.

API 문서: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
XBRL taxonomy: https://www.sec.gov/info/edgar/xbrlfinancialreporting.htm
"""
from __future__ import annotations

import os
import re
import time
import threading
from typing import Optional

import requests

from .cache import cache


# SEC 공식 엔드포인트
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_FACTS_BASE = "https://data.sec.gov/api/xbrl/companyfacts"

# Rate limit + 매너 — User-Agent 필수
_USER_AGENT = os.getenv(
    "SEC_USER_AGENT",
    "StockInto stockintokr@gmail.com",  # 운영자 연락처 (SEC 가이드 따름)
)
_MIN_INTERVAL = 0.12  # 초당 8회 정도로 보수적 (SEC 한도 10/s)
_LAST_CALL = 0.0
_RATE_LOCK = threading.Lock()

# 티커 → CIK 매핑 (10자리 zero-padded)
_TICKER_TO_CIK: dict[str, str] = {}
_TICKER_LOCK = threading.Lock()
_TICKER_LOADED_AT: float = 0.0
_TICKER_TTL = 7 * 24 * 3600  # 7일


def is_available() -> bool:
    """SEC EDGAR는 공개라 항상 사용 가능 (네트워크 OK 가정)."""
    return True


def _throttle():
    global _LAST_CALL
    with _RATE_LOCK:
        now = time.time()
        wait = _MIN_INTERVAL - (now - _LAST_CALL)
        if wait > 0:
            time.sleep(wait)
        _LAST_CALL = time.time()


def _headers() -> dict:
    """SEC가 요구하는 User-Agent 헤더."""
    return {"User-Agent": _USER_AGENT, "Accept-Encoding": "gzip, deflate"}


def _normalize_ticker(ticker: str) -> Optional[str]:
    """미국 티커만 처리 — 한국 종목(.KS/.KQ)은 None."""
    if not ticker:
        return None
    t = ticker.strip().upper()
    # 한국 티커 차단
    if t.endswith(".KS") or t.endswith(".KQ"):
        return None
    # 거래소 접미사 제거 (예: BRK-B → BRK-B 그대로, AAPL.US → AAPL)
    if "." in t and not t.startswith("."):
        t = t.split(".")[0]
    # SEC는 일반적으로 영문/숫자/하이픈만
    if not re.fullmatch(r"[A-Z0-9\-]{1,10}", t):
        return None
    return t


def _load_ticker_map() -> dict[str, str]:
    """SEC company_tickers.json 받아서 ticker → CIK(10자리) 맵 구성. 7일 캐시.

    응답 구조:
        {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...}
    """
    global _TICKER_LOADED_AT
    with _TICKER_LOCK:
        if _TICKER_TO_CIK and (time.time() - _TICKER_LOADED_AT) < _TICKER_TTL:
            return _TICKER_TO_CIK

        try:
            _throttle()
            r = requests.get(SEC_TICKERS_URL, headers=_headers(), timeout=15)
            r.raise_for_status()
            data = r.json()

            new_map: dict[str, str] = {}
            for entry in data.values():
                ticker = (entry.get("ticker") or "").upper().strip()
                cik = entry.get("cik_str")
                if ticker and isinstance(cik, int):
                    # CIK 10자리 zero-pad (SEC 표준)
                    new_map[ticker] = f"{cik:010d}"
            _TICKER_TO_CIK.clear()
            _TICKER_TO_CIK.update(new_map)
            _TICKER_LOADED_AT = time.time()
            return _TICKER_TO_CIK
        except Exception:
            return _TICKER_TO_CIK  # 실패하면 기존 맵 (있으면)


def _get_cik(ticker: str) -> Optional[str]:
    """티커 → 10자리 CIK. 없으면 None."""
    t = _normalize_ticker(ticker)
    if not t:
        return None
    m = _load_ticker_map()
    return m.get(t)


# us-gaap XBRL 태그 후보 (회사마다 사용 태그 다름 — 우선순위 순서로 시도)
_FIELD_CONCEPTS = {
    "revenue": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
    ],
    "cost_of_revenue": [
        "CostOfRevenue",
        "CostOfGoodsAndServicesSold",
        "CostOfGoodsSold",
    ],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": [
        "NetIncomeLoss",
        "ProfitLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
    ],
    "rd_expense": ["ResearchAndDevelopmentExpense"],
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "total_equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "current_assets": ["AssetsCurrent"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "operating_cf": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "shares_outstanding": [
        "CommonStockSharesOutstanding",
        "EntityCommonStockSharesOutstanding",
    ],
    "eps_basic": ["EarningsPerShareBasic"],
    "eps_diluted": ["EarningsPerShareDiluted"],
}


def _fetch_company_facts(cik: str) -> Optional[dict]:
    """SEC companyfacts JSON — 한 회사의 모든 XBRL 데이터를 한 번에.

    주의: 응답 1~5MB라 메모리 캐시 X (메모리 폭주 방지).
    fetch_financials가 즉시 파싱·작은 결과만 24h 캐시함.
    음성(실패)만 1시간 캐시 — 재호출 폭주 차단.
    """
    neg_key = f"sec_facts_fail:{cik}"
    if cache.get(neg_key):
        return None

    try:
        _throttle()
        r = requests.get(
            f"{SEC_FACTS_BASE}/CIK{cik}.json",
            headers=_headers(),
            timeout=20,
        )
        if r.status_code != 200:
            cache.set(neg_key, True, ttl=3600)  # 실패만 1시간 캐시
            return None
        # 원본 JSON은 캐시하지 않고 즉시 반환 (호출자가 파싱 후 폐기)
        return r.json()
    except Exception:
        cache.set(neg_key, True, ttl=3600)
        return None


def _extract_annual_value(facts: dict, concept: str, year: int) -> Optional[float]:
    """특정 연도 (FY)의 연간 값 추출. 10-K 우선, 없으면 큰 unit 합계."""
    try:
        node = facts.get("facts", {}).get("us-gaap", {}).get(concept)
        if not node:
            return None
        units = node.get("units", {})
        # USD 우선, 그 다음 일반 unit
        unit_keys = list(units.keys())
        if not unit_keys:
            return None
        # USD 또는 USD/shares 우선
        primary = "USD" if "USD" in unit_keys else unit_keys[0]
        entries = units.get(primary, [])
        # FY 그리고 연도 매칭, 10-K 우선
        candidates = []
        for e in entries:
            fy = e.get("fy")
            fp = e.get("fp")  # FY = 연간, Q1~Q4 = 분기
            form = e.get("form", "")
            if fy == year and fp == "FY":
                priority = 1 if form.startswith("10-K") else 2
                candidates.append((priority, e.get("val")))
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0])
        v = candidates[0][1]
        return float(v) if v is not None else None
    except Exception:
        return None


def _pick_concept(facts: dict, concept_list: list[str], year: int) -> Optional[float]:
    """후보 concept 중 첫 번째 가용 값."""
    for c in concept_list:
        v = _extract_annual_value(facts, c, year)
        if v is not None:
            return v
    return None


def fetch_financials(ticker: str, years: int = 5) -> Optional[dict]:
    """SEC EDGAR에서 최근 N년 연간 연결재무제표 조회.

    DART 클라이언트와 동일 인터페이스 — app.py가 같은 패턴으로 병합 가능.

    Returns:
        {years, revenue, net_income, operating_income, gross_profit,
         rd_expense, equity, total_assets, total_liabilities,
         current_assets, current_liabilities, operating_cf, capex, fcf, source}
        실패/비대상이면 None.
    """
    cik = _get_cik(ticker)
    if not cik:
        return None

    cache_key = f"sec_fin_v1:{cik}:{years}"
    hit = cache.get(cache_key)
    if hit is not None:
        return hit if hit else None

    facts = _fetch_company_facts(cik)
    if not facts:
        cache.set(cache_key, False, ttl=3600)
        return None

    import datetime
    now_year = datetime.datetime.now().year
    year_list = list(range(now_year - 1, now_year - 1 - years, -1))
    year_list.sort()  # 오름차순 (오래된 것부터)

    by_year: dict[int, dict[str, float]] = {}
    for y in year_list:
        year_data: dict[str, float] = {}
        for field, concepts in _FIELD_CONCEPTS.items():
            v = _pick_concept(facts, concepts, y)
            if v is not None:
                year_data[field] = v
        # 매출 또는 순이익 하나라도 있으면 유효 연도
        if year_data.get("revenue") is not None or year_data.get("net_income") is not None:
            by_year[y] = year_data

    if not by_year:
        cache.set(cache_key, False, ttl=3600)
        return None

    sorted_years = sorted(by_year.keys())

    def col(field):
        return [by_year[y].get(field) for y in sorted_years]

    # gross_profit fallback: 없으면 revenue - cost_of_revenue
    gp_col = col("gross_profit")
    if all(v is None for v in gp_col):
        gp_col = []
        for y in sorted_years:
            d = by_year[y]
            r, c = d.get("revenue"), d.get("cost_of_revenue")
            gp_col.append(r - c if (r is not None and c is not None) else None)

    # FCF 계산: operating_cf - capex (SEC capex는 양수로 들어옴, 지출이라 빼기)
    fcf_col = []
    for y in sorted_years:
        d = by_year[y]
        ocf, cx = d.get("operating_cf"), d.get("capex")
        if ocf is None:
            fcf_col.append(None)
        else:
            fcf_col.append(ocf - (cx or 0))

    result = {
        "years": [str(y) for y in sorted_years],
        "revenue": col("revenue"),
        "net_income": col("net_income"),
        "operating_income": col("operating_income"),
        "gross_profit": gp_col,
        "rd_expense": col("rd_expense"),
        "equity": col("total_equity"),
        "total_assets": col("total_assets"),
        "total_liabilities": col("total_liabilities"),
        "current_assets": col("current_assets"),
        "current_liabilities": col("current_liabilities"),
        "operating_cf": col("operating_cf"),
        "capex": col("capex"),
        "fcf": fcf_col,
        "shares_outstanding": col("shares_outstanding"),
        "eps_diluted": col("eps_diluted"),
        "eps_basic": col("eps_basic"),
        "source": "sec_edgar",
    }
    # 명시적 메모리 해제 — 원본 facts(1~5MB) 폐기
    facts = None
    by_year = None
    cache.set(cache_key, result, ttl=24 * 3600)
    return result


def fetch_company_meta(ticker: str) -> Optional[dict]:
    """회사 메타 정보 (이름·sector 등) — companyfacts에서 추출."""
    cik = _get_cik(ticker)
    if not cik:
        return None
    facts = _fetch_company_facts(cik)
    if not facts:
        return None
    return {
        "cik": cik,
        "entity_name": facts.get("entityName"),
    }
