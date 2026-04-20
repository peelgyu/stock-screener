"""거래량 TOP 10 — US (Yahoo screener) + KR (FDR KOSPI+KOSDAQ)."""

import urllib.request
import urllib.parse
import json as json_lib

try:
    import FinanceDataReader as fdr
    import pandas as pd
    FDR_AVAILABLE = True
except Exception:
    FDR_AVAILABLE = False


def get_most_active_us(count: int = 10) -> list:
    """Yahoo screener 'most_actives' 엔드포인트로 미국 거래량 TOP."""
    try:
        url = (
            "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
            f"?formatted=false&scrIds=most_actives&count={count}&lang=en-US&region=US"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        data = json_lib.loads(resp.read())
        quotes = data.get("finance", {}).get("result", [{}])[0].get("quotes", [])

        results = []
        for q in quotes[:count]:
            symbol = q.get("symbol", "")
            name = q.get("longName") or q.get("shortName") or symbol
            price = q.get("regularMarketPrice")
            volume = q.get("regularMarketVolume", 0)
            change_pct = q.get("regularMarketChangePercent", 0)
            if symbol and price is not None:
                results.append({
                    "ticker": symbol,
                    "name": (name or "")[:30],
                    "price": round(float(price), 2),
                    "volume": int(volume or 0),
                    "change_pct": round(float(change_pct or 0), 2),
                    "market": "US",
                })
        return results
    except Exception:
        return []


def get_most_active_kr(count: int = 10) -> list:
    """FDR StockListing 사용 — KOSPI + KOSDAQ 통합 후 Volume 정렬."""
    if not FDR_AVAILABLE:
        return []
    try:
        dfs = []
        for market in ["KOSPI", "KOSDAQ"]:
            try:
                df = fdr.StockListing(market)
                df = df.assign(MarketLabel=market)
                dfs.append(df)
            except Exception:
                continue
        if not dfs:
            return []
        all_kr = pd.concat(dfs, ignore_index=True)
        if "Volume" not in all_kr.columns:
            return []
        top = all_kr.sort_values("Volume", ascending=False).head(count)

        results = []
        for _, row in top.iterrows():
            code = str(row.get("Code", ""))
            market = row.get("MarketLabel", "KOSPI")
            suffix = ".KS" if market == "KOSPI" else ".KQ"
            ticker = code + suffix
            name = row.get("Name", code)
            try:
                price = float(row.get("Close", 0))
            except Exception:
                price = 0
            try:
                volume = int(row.get("Volume", 0))
            except Exception:
                volume = 0
            try:
                change_pct = float(row.get("ChagesRatio", 0))
            except Exception:
                change_pct = 0
            results.append({
                "ticker": ticker,
                "display_ticker": code,  # 한국은 종목코드 표시
                "name": str(name)[:20],
                "price": round(price, 0),
                "volume": volume,
                "change_pct": round(change_pct, 2),
                "market": market,
            })
        return results
    except Exception:
        return []


def get_most_active() -> dict:
    return {
        "us": get_most_active_us(10),
        "kr": get_most_active_kr(10),
    }
