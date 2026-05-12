"""가중 공포/탐욕 지수 — 중복 상관 지표 보정."""

import numpy as np

from analysis.evaluators import safe_get


def _calc_rsi(prices, period=14):
    delta = prices.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta.where(delta < 0, 0.0))
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


WEIGHTS = {
    "RSI (14일)": 0.20,
    "52주 범위 위치": 0.15,
    "50일 이평선 대비": 0.15,
    "200일 이평선 대비": 0.15,
    "거래량 변화 (5일/20일)": 0.15,
    "변동성 (연환산)": 0.20,
}


def evaluate_fear_greed(data: dict) -> dict:
    info = data["info"]
    hist = data.get("hist")
    indicators = []

    # hist 없으면 yfinance Ticker.history()로 직접 받기 시도 (Yahoo 부실 응답 대비)
    if (hist is None or (hasattr(hist, "empty") and hist.empty) or (hist is not None and len(hist) < 20)):
        stock = data.get("stock")
        if stock is not None:
            try:
                import pandas as _pd
                fetched = stock.history(period="1y", interval="1d")
                if fetched is not None and not fetched.empty and len(fetched) >= 20:
                    hist = fetched
            except Exception:
                pass

    if hist is None or hist.empty or len(hist) < 20:
        return {"score": None, "label": "데이터 부족 (가격 시계열 미확보)", "indicators": []}

    close = hist["Close"]
    volume = hist["Volume"]

    # 1) RSI
    rsi = _calc_rsi(close)
    rsi_val = rsi.iloc[-1]
    if not np.isnan(rsi_val):
        label = "과매수 (탐욕)" if rsi_val >= 70 else "과매도 (공포)" if rsi_val <= 30 else "중립"
        indicators.append({
            "name": "RSI (14일)",
            "value": f"{rsi_val:.1f}",
            "score": round(float(rsi_val)),
            "label": label,
            "weight": WEIGHTS["RSI (14일)"],
        })

    # 2) 52주 범위
    price = safe_get(info, "currentPrice") or safe_get(info, "regularMarketPrice")
    high52 = safe_get(info, "fiftyTwoWeekHigh")
    low52 = safe_get(info, "fiftyTwoWeekLow")
    if price and high52 and low52 and high52 != low52:
        pos = (price - low52) / (high52 - low52) * 100
        label = "고점 근처 (탐욕)" if pos >= 80 else "저점 근처 (공포)" if pos <= 20 else "중간"
        indicators.append({
            "name": "52주 범위 위치",
            "value": f"{pos:.0f}%",
            "score": round(pos),
            "label": label,
            "weight": WEIGHTS["52주 범위 위치"],
        })

    # 3) 50일 이평
    if len(close) >= 50:
        ma50 = close.rolling(50).mean().iloc[-1]
        if price and ma50 and ma50 > 0:
            pct = (price - ma50) / ma50 * 100
            score = max(0, min(100, (pct + 20) / 40 * 100))
            label = "이평선 위 (탐욕)" if pct > 5 else "이평선 아래 (공포)" if pct < -5 else "이평선 근처"
            indicators.append({
                "name": "50일 이평선 대비",
                "value": f"{pct:+.1f}%",
                "score": round(score),
                "label": label,
                "weight": WEIGHTS["50일 이평선 대비"],
            })

    # 4) 200일 이평
    if len(close) >= 200:
        ma200 = close.rolling(200).mean().iloc[-1]
        if price and ma200 and ma200 > 0:
            pct = (price - ma200) / ma200 * 100
            score = max(0, min(100, (pct + 30) / 60 * 100))
            label = "장기 상승세 (탐욕)" if pct > 10 else "장기 하락세 (공포)" if pct < -10 else "중립"
            indicators.append({
                "name": "200일 이평선 대비",
                "value": f"{pct:+.1f}%",
                "score": round(score),
                "label": label,
                "weight": WEIGHTS["200일 이평선 대비"],
            })

    # 5) 거래량
    if len(volume) >= 20:
        vol_5 = volume.iloc[-5:].mean()
        vol_20 = volume.iloc[-20:].mean()
        if vol_20 > 0:
            ratio = vol_5 / vol_20
            price_chg_5d = (close.iloc[-1] - close.iloc[-5]) / close.iloc[-5] * 100 if len(close) >= 5 else 0
            if price_chg_5d > 0:
                score = min(100, 50 + (ratio - 1) * 30)
                label = "매수세 증가" if ratio > 1.2 else "보통"
            else:
                score = max(0, 50 - (ratio - 1) * 30)
                label = "매도세 증가" if ratio > 1.2 else "보통"
            indicators.append({
                "name": "거래량 변화 (5일/20일)",
                "value": f"{ratio:.2f}x",
                "score": round(score),
                "label": label,
                "weight": WEIGHTS["거래량 변화 (5일/20일)"],
            })

    # 6) 변동성
    if len(close) >= 20:
        returns = close.pct_change().dropna()
        vol_20d = returns.iloc[-20:].std() * np.sqrt(252) * 100
        score = max(0, min(100, (80 - vol_20d) / 70 * 100))
        label = "극단적 변동 (공포)" if vol_20d > 50 else "높은 변동성" if vol_20d > 30 else "안정적 (탐욕)"
        indicators.append({
            "name": "변동성 (연환산)",
            "value": f"{vol_20d:.1f}%",
            "score": round(score),
            "label": label,
            "weight": WEIGHTS["변동성 (연환산)"],
        })

    if not indicators:
        return {"score": None, "label": "데이터 부족", "indicators": []}

    weighted = sum(ind["score"] * ind["weight"] for ind in indicators)
    total_w = sum(ind["weight"] for ind in indicators)
    total_score = round(weighted / total_w) if total_w > 0 else None

    if total_score is None:
        label = "데이터 부족"
    elif total_score >= 75:
        label = "극단적 탐욕"
    elif total_score >= 55:
        label = "탐욕"
    elif total_score >= 45:
        label = "중립"
    elif total_score >= 25:
        label = "공포"
    else:
        label = "극단적 공포"

    return {"score": total_score, "label": label, "indicators": indicators}
