"""시장 방향(M) — CAN SLIM의 Market Direction."""

import yfinance as yf


def get_market_regime(is_kr: bool = False) -> dict:
    benchmark = "^KS11" if is_kr else "^GSPC"
    benchmark_name = "KOSPI" if is_kr else "S&P 500"

    try:
        hist = yf.Ticker(benchmark).history(period="2y")
        if hist is None or hist.empty or len(hist) < 210:
            return {"available": False, "benchmark": benchmark, "benchmark_name": benchmark_name}
        close = hist["Close"]
    except Exception:
        return {"available": False, "benchmark": benchmark, "benchmark_name": benchmark_name}

    current = float(close.iloc[-1])
    ma50 = float(close.rolling(50).mean().iloc[-1])
    ma200 = float(close.rolling(200).mean().iloc[-1])

    # 20일 전 MA200으로 기울기 판단
    try:
        ma200_20d_ago = float(close.rolling(200).mean().iloc[-21])
    except Exception:
        ma200_20d_ago = ma200

    ma50_pct = (current - ma50) / ma50 * 100 if ma50 > 0 else 0
    ma200_pct = (current - ma200) / ma200 * 100 if ma200 > 0 else 0
    ma200_slope_up = ma200 > ma200_20d_ago

    above_200 = current > ma200
    above_50 = current > ma50

    if above_200 and above_50 and ma200_slope_up and ma50_pct > 1:
        direction = "상승장 (Confirmed Uptrend)"
        recommend = "신규 매수에 유리한 환경"
        passed_m = True
        trend_200d = "up"
        trend_50d = "up"
    elif above_200 and ma200_slope_up:
        direction = "약한 상승"
        recommend = "선별적 매수"
        passed_m = False
        trend_200d = "up"
        trend_50d = "up" if above_50 else "down"
    elif abs(ma50_pct) < 3 and abs(ma200_pct) < 5:
        direction = "횡보"
        recommend = "관망 또는 스윙 단타"
        passed_m = False
        trend_200d = "flat"
        trend_50d = "flat"
    elif above_200 and not above_50:
        direction = "조정 (장기추세 유효)"
        recommend = "매수 신중, 이평선 회복 대기"
        passed_m = False
        trend_200d = "up"
        trend_50d = "down"
    else:
        direction = "하락장"
        recommend = "매수 자제 (현금 비중 확대)"
        passed_m = False
        trend_200d = "down"
        trend_50d = "down"

    return {
        "benchmark": benchmark,
        "benchmark_name": benchmark_name,
        "current": round(current, 2),
        "ma50": round(ma50, 2),
        "ma200": round(ma200, 2),
        "ma50_pct": round(ma50_pct, 2),
        "ma200_pct": round(ma200_pct, 2),
        "trend_200d": trend_200d,
        "trend_50d": trend_50d,
        "direction": direction,
        "recommend": recommend,
        "passed_canslim_m": passed_m,
        "available": True,
    }
