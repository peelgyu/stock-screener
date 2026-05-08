"""공유 헬퍼 함수 — Blueprint들이 공통으로 import하는 진실 소스.

app.py 분리 작업 중 만들어짐. 순환 import 방지 목적.
- routes/api_market.py, routes/api_stock.py 등이 여기서 import
- app.py도 여기서 import (역방향 의존 없음)
"""
from __future__ import annotations

import json as json_lib
import logging
import re
import urllib.parse
import urllib.request

from data.cache import cached
from data.fetcher import fetch_stock_data
from data import kr_listing
from kr_stocks import KR_STOCKS, US_STOCKS_KR

logger = logging.getLogger(__name__)


# ============================================================
# 입력 검증 — SSRF·Injection 차단
# ============================================================
# 허용: 영문, 숫자, 한글, 공백, 점, 하이픈. 길이 1~30
_SAFE_QUERY_RE = re.compile(r"^[\w가-힣\.\-\s]{1,30}$", re.UNICODE)


def is_safe_query(query: str) -> bool:
    """검색어/티커 입력 검증 — 위험 문자 차단."""
    if not query or len(query) > 30:
        return False
    return bool(_SAFE_QUERY_RE.match(query))


# ============================================================
# 종목 데이터 fetch (캐시 적용)
# ============================================================
@cached(ttl=7200)  # 2시간 캐시 — "시세 15분 지연" UI 표기와 일치, Yahoo 호출 4배 절감
def get_stock_data(ticker: str) -> dict | None:
    """yfinance·FDR 통합 fetch + 2시간 캐시. 분석 핵심 진입점."""
    fetched = fetch_stock_data(ticker)
    if fetched is None:
        return None
    return fetched


# ============================================================
# 티커 해석 — 사용자 입력을 표준 ticker 코드로 변환
# ============================================================
def resolve_ticker(query: str) -> str | None:
    """검색어를 표준 ticker 코드로 변환.

    우선순위:
    1. 영문 대문자 1~6자 (이미 ticker 형식) → passthrough
    2. 6자리 숫자 → KRX 매칭 → .KS 또는 .KQ
    3. 친근 별명 (KR_STOCKS·US_STOCKS_KR 매핑)
    4. KRX 전체 종목명 매칭
    5. Yahoo 검색 fallback
    """
    q = query.strip()
    if q.isascii() and q.upper() == q and q.replace("-", "").replace(".", "").isalpha() and len(q) <= 6:
        return q.upper()
    if q.isdigit() and len(q) == 6:
        # 6자리 숫자만 입력 시 KOSPI 우선 → 없으면 KOSDAQ
        full_kospi = q + ".KS"
        full_kosdaq = q + ".KQ"
        # KRX 전체 리스트에서 정확한 거래소 확인
        for item in kr_listing.get_all_listings():
            if item["symbol"] == full_kospi:
                return full_kospi
            if item["symbol"] == full_kosdaq:
                return full_kosdaq
        return full_kospi  # 폴백
    # 1) 친근 별명 매핑 (89개)
    if q in KR_STOCKS:
        return KR_STOCKS[q][0]
    if q in US_STOCKS_KR:
        return US_STOCKS_KR[q]
    for name, (ticker, _) in KR_STOCKS.items():
        if q in name:
            return ticker
    for kr_name, ticker in US_STOCKS_KR.items():
        if q in kr_name:
            return ticker
    # 2) KRX 전체 리스트 (~2,500개) 정식 종목명 매칭
    kr_match = kr_listing.find_by_name(q)
    if kr_match:
        return kr_match
    # 3) Yahoo 검색 fallback (미국 종목·해외 ETF 등)
    try:
        encoded = urllib.parse.quote(q)
        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={encoded}&quotesCount=1&newsCount=0&listsCount=0"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=5)
        data = json_lib.loads(resp.read())
        quotes = data.get("quotes", [])
        if quotes:
            return quotes[0]["symbol"]
    except Exception as e:
        logger.debug("Yahoo search resolve failed for '%s': %s", q, type(e).__name__)
    return None
