"""상대강도(RS) Rating — 벤치마크 대비 수익률."""

import yfinance as yf


def _benchmark_for(ticker: str) -> str:
    t = (ticker or "").upper()
    if t.endswith(".KS") or t.endswith(".KQ"):
        return "^KS11"
    return "^GSPC"


def _return_over_days(close_series, days: int):
    if close_series is None or len(close_series) < days + 1:
        return None
    try:
        start = float(close_series.iloc[-days - 1])
        end = float(close_series.iloc[-1])
        if start <= 0:
            return None
        return (end - start) / start
    except Exception:
        return None


def _rs_score(stock_ret, bench_ret):
    if stock_ret is None or bench_ret is None:
        return None
    score = 50 + (stock_ret - bench_ret) * 500
    return max(0, min(100, int(round(score))))


def calculate_rs_rating(ticker: str, hist=None) -> dict:
    benchmark = _benchmark_for(ticker)

    try:
        if hist is None:
            hist = yf.Ticker(ticker).history(period="1y")
        if hist is None or hist.empty:
            return {"available": False, "benchmark": benchmark}
        stock_close = hist["Close"]
    except Exception:
        return {"available": False, "benchmark": benchmark}

    try:
        bench_hist = yf.Ticker(benchmark).history(period="1y")
        bench_close = bench_hist["Close"] if bench_hist is not None and not bench_hist.empty else None
    except Exception:
        bench_close = None

    if bench_close is None or len(bench_close) < 30:
        return {"available": False, "benchmark": benchmark}

    periods = {"rs_1m": 21, "rs_3m": 63, "rs_6m": 126, "rs_12m": 252}
    scores = {}
    for k, d in periods.items():
        sr = _return_over_days(stock_close, d)
        br = _return_over_days(bench_close, d)
        scores[k] = _rs_score(sr, br)

    weights = {"rs_1m": 0.2, "rs_3m": 0.2, "rs_6m": 0.2, "rs_12m": 0.4}
    weighted, total_w = 0.0, 0.0
    for k, w in weights.items():
        if scores.get(k) is not None:
            weighted += scores[k] * w
            total_w += w
    composite = int(round(weighted / total_w)) if total_w > 0 else None

    stock_12m = _return_over_days(stock_close, 252)
    bench_12m = _return_over_days(bench_close, 252)

    if composite is None:
        label = "데이터 부족"
    elif composite >= 80:
        label = "선도주 (상위 20%)"
    elif composite >= 60:
        label = "시장 상회"
    elif composite >= 40:
        label = "시장 동행"
    else:
        label = "시장 대비 부진"

    return {
        **scores,
        "rs_composite": composite,
        "stock_12m_return_pct": round(stock_12m * 100, 1) if stock_12m is not None else None,
        "benchmark_12m_return_pct": round(bench_12m * 100, 1) if bench_12m is not None else None,
        "benchmark": benchmark,
        "label": label,
        "passed_oneil": composite is not None and composite >= 80,
        "available": composite is not None,
    }
