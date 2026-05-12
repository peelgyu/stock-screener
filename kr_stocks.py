"""한국·미국 주식 한국어 별명·설명 매핑 (JSON 외부화).

원본 데이터(384개 entry)는 data/kr_stocks_data.json에 분리 저장.
이 파일은 로딩 + 검색·조회 함수만 담당.
"""
import json
import os

_DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "kr_stocks_data.json")

with open(_DATA_PATH, encoding="utf-8") as _f:
    _DATA = json.load(_f)

# JSON은 tuple을 못 쓰니 list로 저장됨 → 기존 API 호환 위해 tuple로 복원.
KR_STOCKS = {k: tuple(v) for k, v in _DATA["KR_STOCKS"].items()}
US_STOCKS_KR = _DATA["US_STOCKS_KR"]
KR_DESCRIPTIONS = _DATA["KR_DESCRIPTIONS"]
US_DESCRIPTIONS = _DATA["US_DESCRIPTIONS"]
SECTOR_KR = _DATA["SECTOR_KR"]


def search_kr_stocks(query: str) -> list[dict]:
    """한국어 검색어로 종목 검색."""
    query = query.strip()
    results = []

    for name, (ticker, eng_name) in KR_STOCKS.items():
        if query in name:
            results.append({
                "symbol": ticker,
                "name": name,
                "engName": eng_name,
                "exchange": "KOSDAQ" if ".KQ" in ticker else "KOSPI",
            })

    for kr_name, ticker in US_STOCKS_KR.items():
        if query in kr_name:
            results.append({
                "symbol": ticker,
                "name": kr_name,
                "engName": kr_name,
                "exchange": "US",
            })

    seen = set()
    unique = []
    for r in results:
        if r["symbol"] not in seen:
            seen.add(r["symbol"])
            unique.append(r)

    return unique[:8]


def get_kr_description(ticker: str) -> str | None:
    """티커에서 한국어 사업 설명을 반환. .KS/.KQ 접미사 제거 후 매핑 조회."""
    if not ticker:
        return None
    code = ticker.split(".")[0]
    return KR_DESCRIPTIONS.get(code)


def get_us_description(ticker: str) -> str | None:
    """미국 티커 → 한국어 사업 설명. 없으면 None."""
    if not ticker:
        return None
    t = ticker.upper().split(".")[0]
    return US_DESCRIPTIONS.get(t)


def sector_kr(sector_en: str) -> str:
    """yfinance 영문 sector → 한국어. 매핑 없으면 원문 그대로."""
    if not sector_en:
        return sector_en or ""
    return SECTOR_KR.get(sector_en, sector_en)
