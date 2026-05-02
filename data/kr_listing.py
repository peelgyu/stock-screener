"""KRX 전체 상장 종목 리스트 — KOSPI + KOSDAQ 약 2,500개.

FinanceDataReader로 받아서 24시간 메모리 캐시.
검색 시 정식 종목명·코드 매칭에 사용.
kr_stocks.KR_STOCKS의 친근 별명(89개)과 보완 관계.
"""
from __future__ import annotations

import threading
import time
from typing import Optional

try:
    import FinanceDataReader as fdr  # type: ignore
    _FDR_AVAILABLE = True
except Exception:
    fdr = None
    _FDR_AVAILABLE = False


# 메모리 캐시 (앱 시작 후 24h 유지)
_LISTINGS: list[dict] = []  # [{"symbol": "005930.KS", "name": "삼성전자", "engName": "...", "exchange": "KOSPI"}, ...]
_LOADED_AT: float = 0.0
_TTL = 24 * 3600
_LOCK = threading.Lock()


def _build_listings() -> list[dict]:
    """KRX KOSPI + KOSDAQ 전체 종목 가져와서 dict 리스트로 변환."""
    if not _FDR_AVAILABLE:
        return []
    out: list[dict] = []
    seen: set[str] = set()

    for market, suffix, exch_name in [("KOSPI", ".KS", "KOSPI"), ("KOSDAQ", ".KQ", "KOSDAQ")]:
        try:
            df = fdr.StockListing(market)
        except Exception:
            continue
        if df is None or df.empty:
            continue

        # 컬럼명 호환 — fdr 버전마다 살짝 다름
        code_col = next((c for c in ("Code", "Symbol", "code") if c in df.columns), None)
        name_col = next((c for c in ("Name", "name", "Korean Name") if c in df.columns), None)
        eng_col = next((c for c in ("EngName", "EnglishName", "eng_name") if c in df.columns), None)
        if not code_col or not name_col:
            continue

        for _, row in df.iterrows():
            try:
                code = str(row[code_col]).strip().zfill(6)
                if not code or code in seen or len(code) != 6 or not code.isdigit():
                    continue
                name = str(row[name_col]).strip()
                if not name:
                    continue
                eng = str(row[eng_col]).strip() if eng_col else ""
                seen.add(code)
                out.append({
                    "symbol": code + suffix,
                    "name": name,
                    "engName": eng,
                    "exchange": exch_name,
                })
            except Exception:
                continue

    return out


def get_all_listings() -> list[dict]:
    """전체 KRX 종목 리스트 — 24h 캐시."""
    global _LOADED_AT
    with _LOCK:
        if _LISTINGS and (time.time() - _LOADED_AT) < _TTL:
            return _LISTINGS
        new = _build_listings()
        if new:
            _LISTINGS.clear()
            _LISTINGS.extend(new)
            _LOADED_AT = time.time()
        return _LISTINGS


def search_listings(query: str, limit: int = 8) -> list[dict]:
    """전체 KRX 종목에서 검색 — 종목명 부분 일치, 코드 일치, 영문명 일치."""
    if not query:
        return []
    q = query.strip()
    if not q:
        return []
    listings = get_all_listings()
    if not listings:
        return []

    q_lower = q.lower()
    is_digit = q.isdigit()

    # 1) 정확 일치 우선
    exact: list[dict] = []
    starts: list[dict] = []
    contains: list[dict] = []

    for item in listings:
        name = item["name"]
        code = item["symbol"].split(".")[0]
        eng = (item.get("engName") or "").lower()

        # 종목코드 일치
        if is_digit and (code == q or code.startswith(q)):
            exact.append(item)
            continue

        # 종목명 정확 일치
        if name == q:
            exact.append(item)
            continue

        # 종목명 시작 일치
        if name.startswith(q):
            starts.append(item)
            continue

        # 종목명 부분 일치
        if q in name:
            contains.append(item)
            continue

        # 영문명 부분 일치
        if eng and q_lower in eng:
            contains.append(item)

    result = exact + starts + contains
    return result[:limit]


def find_by_name(name: str) -> Optional[str]:
    """종목명 → 티커 변환 (정확/시작 일치). 없으면 None."""
    results = search_listings(name, limit=1)
    return results[0]["symbol"] if results else None
