"""데이터 fetcher — yfinance 우선, 실패 시 FinanceDataReader 등으로 fallback.

Yahoo Finance가 레이트리밋하거나 일시 장애인 경우 한국 주식은 FDR로 자동 전환.
US 주식은 재시도 후 실패하면 명확한 에러 메시지 반환.
"""

import time
import yfinance as yf

try:
    import FinanceDataReader as fdr
    FDR_AVAILABLE = True
except Exception:
    FDR_AVAILABLE = False


def _is_kr_ticker(ticker: str) -> bool:
    t = (ticker or "").upper()
    return t.endswith(".KS") or t.endswith(".KQ")


def _fetch_yfinance(ticker: str, retries: int = 2, delay: float = 2.0):
    """yfinance로 fetch, 실패 시 retry."""
    last_error = None
    for attempt in range(retries):
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            if info and info.get("regularMarketPrice") is not None:
                return {"source": "yfinance", "info": info, "stock": stock}
        except Exception as e:
            last_error = e
        if attempt < retries - 1:
            time.sleep(delay)
    return None


def _fetch_fdr_us(ticker: str):
    """미국 주식 FDR(Stooq) fallback — Yahoo 차단 시 대체."""
    if not FDR_AVAILABLE:
        return None
    try:
        df = fdr.DataReader(ticker, start="2024-01-01")
        if df is None or df.empty:
            return None
        latest = df.iloc[-1]
        close = float(latest["Close"])
        volume = int(latest["Volume"]) if latest.get("Volume") is not None else 0

        info = {
            "regularMarketPrice": close,
            "currentPrice": close,
            "volume": volume,
            "averageVolume": int(df["Volume"].tail(20).mean()) if len(df) >= 20 else volume,
            "fiftyTwoWeekHigh": float(df["Close"].tail(252).max()),
            "fiftyTwoWeekLow": float(df["Close"].tail(252).min()),
            "currency": "USD",
            "symbol": ticker,
            "longName": ticker,
            "_data_warnings": [
                "yfinance 일시 제한 — Stooq 대체 데이터 사용 (재무제표 등 일부 지표 누락)"
            ],
        }
        return {"source": "fdr_us", "info": info, "stock": None, "hist": df}
    except Exception:
        return None


def _fetch_fdr_korean(ticker: str):
    """FinanceDataReader로 한국 주식 fetch. 제한적이지만 yfinance 대체."""
    if not FDR_AVAILABLE:
        return None
    code = ticker.split(".")[0]
    try:
        df = fdr.DataReader(code, start="2024-01-01")
        if df is None or df.empty:
            return None

        # 종목 메타 정보 (섹터, 시총 등)
        meta = None
        for market in ["KOSPI", "KOSDAQ"]:
            try:
                listings = fdr.StockListing(market)
                m = listings[listings["Code"] == code]
                if not m.empty:
                    meta = m.iloc[0]
                    break
            except Exception:
                pass

        latest = df.iloc[-1]
        close = float(latest["Close"])
        volume = int(latest["Volume"]) if latest.get("Volume") is not None else 0

        # 기본 info dict 구성 — yfinance 형식 모방
        info = {
            "regularMarketPrice": close,
            "currentPrice": close,
            "volume": volume,
            "averageVolume": int(df["Volume"].tail(20).mean()) if len(df) >= 20 else volume,
            "fiftyTwoWeekHigh": float(df["Close"].tail(252).max()),
            "fiftyTwoWeekLow": float(df["Close"].tail(252).min()),
            "currency": "KRW",
            "symbol": ticker,
            "_data_warnings": [
                "yfinance 일시 제한 — FinanceDataReader 대체 데이터 사용 (재무제표 등 일부 지표 누락)"
            ],
        }

        if meta is not None:
            info["longName"] = str(meta.get("Name", ticker))
            # Marcap은 마켓 capitalization (원 단위)
            marcap = meta.get("Marcap")
            if marcap is not None and str(marcap).replace(".", "").replace("-", "").isdigit():
                info["marketCap"] = float(marcap)
            stocks = meta.get("Stocks")
            if stocks is not None and str(stocks).replace(".", "").replace("-", "").isdigit():
                info["sharesOutstanding"] = int(stocks)
            sector = meta.get("Sector")
            if sector and str(sector) != "nan":
                # 한국 섹터를 Yahoo 스타일로 매핑 (간단)
                sector_map = {
                    "전기전자": "Technology",
                    "서비스업": "Communication Services",
                    "의약품": "Healthcare",
                    "금융업": "Financial Services",
                    "은행": "Financial Services",
                    "증권": "Financial Services",
                    "보험": "Financial Services",
                    "화학": "Basic Materials",
                    "철강금속": "Basic Materials",
                    "유통업": "Consumer Cyclical",
                    "운수장비": "Consumer Cyclical",
                    "식품": "Consumer Defensive",
                    "전기가스업": "Utilities",
                    "건설업": "Industrials",
                    "기계": "Industrials",
                }
                info["sector"] = sector_map.get(str(sector), str(sector))
                info["industry"] = str(sector)

        return {"source": "fdr", "info": info, "stock": None, "hist": df}
    except Exception as e:
        return None


def fetch_stock_data(ticker: str) -> dict | None:
    """통합 fetcher. 성공 시 {source, info, stock, hist?} 반환, 실패 시 None.

    source 값:
    - "yfinance": Yahoo에서 정상 fetch (full data)
    - "fdr": FinanceDataReader fallback (Korean only, limited data)

    한국 주식은 Yahoo 레이트리밋 빈번하므로 FDR 먼저 시도.
    """
    is_kr = _is_kr_ticker(ticker)

    if is_kr:
        # 한국: FDR 먼저 → 재무는 DART가 app.py에서 덮어씀
        result = _fetch_fdr_korean(ticker)
        if result is not None:
            # yfinance로 info 보강 시도 (실패해도 무시)
            yf_result = _fetch_yfinance(ticker, retries=1, delay=0.5)
            if yf_result is not None:
                # yfinance info를 FDR info 위에 병합 (yfinance가 더 많은 필드)
                merged_info = {**result["info"], **yf_result["info"]}
                # FDR의 필수 필드는 유지
                for k in ("regularMarketPrice", "currentPrice", "volume", "currency"):
                    if yf_result["info"].get(k) is None and result["info"].get(k) is not None:
                        merged_info[k] = result["info"][k]
                result["info"] = merged_info
                result["stock"] = yf_result["stock"]  # stock 객체는 DART/history용
                result["source"] = "fdr+yfinance"
            return result
        # FDR도 실패 → yfinance 시도
        result = _fetch_yfinance(ticker, retries=2, delay=1.5)
        if result is not None:
            return result
    else:
        # 미국·기타: yfinance 먼저
        result = _fetch_yfinance(ticker, retries=2, delay=1.5)
        if result is not None:
            return result
        # Stooq fallback
        result = _fetch_fdr_us(ticker)
        if result is not None:
            return result

    return None


def detect_fetch_error_type(ticker: str) -> str:
    """실패 원인 분류 — 사용자 에러 메시지에 사용."""
    is_kr = _is_kr_ticker(ticker)
    if not FDR_AVAILABLE:
        return "DATA_SOURCE_DOWN"
    if is_kr:
        # 한국이면 FDR도 실패한 것 → 진짜 존재하지 않는 종목일 가능성
        return "TICKER_NOT_FOUND"
    else:
        # US 주식이고 yfinance 실패 → 대부분 레이트리밋
        return "DATA_SOURCE_LIMITED"
