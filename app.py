"""
유명 투자자 기준 주식 스크리너 - Flask 웹앱
"""

from flask import Flask, render_template, request, jsonify
import yfinance as yf
import numpy as np
import urllib.request
import urllib.parse
import json as json_lib
from kr_stocks import search_kr_stocks, KR_STOCKS, US_STOCKS_KR

app = Flask(__name__)


def safe_get(info: dict, key: str, default=None):
    val = info.get(key, default)
    return val if val is not None else default


def get_stock_data(ticker: str) -> dict | None:
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        if not info or info.get("regularMarketPrice") is None:
            return None

        # 재무제표에서 직접 계산 (info에 None인 항목 보완)
        try:
            bs = stock.balance_sheet
            inc = stock.income_stmt
            if bs is not None and not bs.empty and inc is not None and not inc.empty:
                latest_bs = bs.iloc[:, 0]
                latest_inc = inc.iloc[:, 0]

                # ROE 직접 계산: 순이익 / 자기자본
                if info.get("returnOnEquity") is None:
                    net_income = latest_inc.get("Net Income") or latest_inc.get("Net Income Common Stockholders")
                    equity = latest_bs.get("Stockholders Equity") or latest_bs.get("Total Stockholders Equity") or latest_bs.get("Common Stock Equity")
                    if net_income is not None and equity is not None and equity != 0:
                        info["returnOnEquity"] = float(net_income / equity)
                        info["_roe_note"] = "자본잠식" if equity < 0 else ""

                # 부채비율 직접 계산: 총부채 / 자기자본
                if info.get("debtToEquity") is None:
                    total_debt = latest_bs.get("Total Debt") or latest_bs.get("Total Liabilities Net Minority Interest")
                    equity = latest_bs.get("Stockholders Equity") or latest_bs.get("Total Stockholders Equity") or latest_bs.get("Common Stock Equity")
                    if total_debt is not None and equity is not None and equity != 0:
                        info["debtToEquity"] = float(total_debt / equity * 100)
                        info["_de_note"] = "자본잠식" if equity < 0 else ""

                # EPS 성장률 직접 계산
                if info.get("earningsGrowth") is None and inc.shape[1] >= 2:
                    ni_curr = inc.iloc[:, 0].get("Net Income") or inc.iloc[:, 0].get("Net Income Common Stockholders")
                    ni_prev = inc.iloc[:, 1].get("Net Income") or inc.iloc[:, 1].get("Net Income Common Stockholders")
                    if ni_curr is not None and ni_prev is not None and ni_prev != 0:
                        info["earningsGrowth"] = float((ni_curr - ni_prev) / abs(ni_prev))
        except Exception:
            pass

        # 분기 실적에서 earningsQuarterlyGrowth 보완
        try:
            q_inc = stock.quarterly_income_stmt
            if info.get("earningsQuarterlyGrowth") is None and q_inc is not None and not q_inc.empty and q_inc.shape[1] >= 5:
                ni_curr = q_inc.iloc[:, 0].get("Net Income") or q_inc.iloc[:, 0].get("Net Income Common Stockholders")
                ni_yoy = q_inc.iloc[:, 4].get("Net Income") or q_inc.iloc[:, 4].get("Net Income Common Stockholders")
                if ni_curr is not None and ni_yoy is not None and ni_yoy != 0:
                    info["earningsQuarterlyGrowth"] = float((ni_curr - ni_yoy) / abs(ni_yoy))
        except Exception:
            pass

        # 주가 히스토리 (공포/탐욕 계산용)
        hist = stock.history(period="1y")

        return {"info": info, "hist": hist, "stock": stock}
    except Exception:
        return None


# ──────────────────────────────────────────────
# 공포/탐욕 지수 계산
# ──────────────────────────────────────────────
def calc_rsi(prices, period=14):
    """RSI 계산"""
    delta = prices.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta.where(delta < 0, 0.0))
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def evaluate_fear_greed(data: dict) -> dict:
    """종목별 공포/탐욕 지수 계산 (0=극단적 공포, 100=극단적 탐욕)"""
    info = data["info"]
    hist = data.get("hist")
    indicators = []

    if hist is None or hist.empty or len(hist) < 20:
        return {"score": None, "label": "데이터 부족", "indicators": []}

    close = hist["Close"]
    volume = hist["Volume"]

    # 1) RSI (0~100 그대로 사용)
    rsi = calc_rsi(close)
    rsi_val = rsi.iloc[-1]
    if not np.isnan(rsi_val):
        rsi_score = float(rsi_val)  # RSI 자체가 0~100
        if rsi_val >= 70:
            rsi_label = "과매수 (탐욕)"
        elif rsi_val <= 30:
            rsi_label = "과매도 (공포)"
        else:
            rsi_label = "중립"
        indicators.append({
            "name": "RSI (14일)",
            "value": f"{rsi_val:.1f}",
            "score": round(rsi_score),
            "label": rsi_label,
        })

    # 2) 52주 범위 내 위치
    price = safe_get(info, "currentPrice") or safe_get(info, "regularMarketPrice")
    high52 = safe_get(info, "fiftyTwoWeekHigh")
    low52 = safe_get(info, "fiftyTwoWeekLow")
    if price and high52 and low52 and high52 != low52:
        pos = (price - low52) / (high52 - low52) * 100
        if pos >= 80:
            pos_label = "고점 근처 (탐욕)"
        elif pos <= 20:
            pos_label = "저점 근처 (공포)"
        else:
            pos_label = "중간"
        indicators.append({
            "name": "52주 범위 위치",
            "value": f"{pos:.0f}%",
            "score": round(pos),
            "label": pos_label,
        })

    # 3) 50일 이동평균 대비
    if len(close) >= 50:
        ma50 = close.rolling(50).mean().iloc[-1]
        if price and ma50 and ma50 > 0:
            ma50_pct = (price - ma50) / ma50 * 100
            # -20% 이하 = 0점, +20% 이상 = 100점
            ma50_score = max(0, min(100, (ma50_pct + 20) / 40 * 100))
            if ma50_pct > 5:
                ma50_label = "이평선 위 (탐욕)"
            elif ma50_pct < -5:
                ma50_label = "이평선 아래 (공포)"
            else:
                ma50_label = "이평선 근처"
            indicators.append({
                "name": "50일 이평선 대비",
                "value": f"{ma50_pct:+.1f}%",
                "score": round(ma50_score),
                "label": ma50_label,
            })

    # 4) 200일 이동평균 대비
    if len(close) >= 200:
        ma200 = close.rolling(200).mean().iloc[-1]
        if price and ma200 and ma200 > 0:
            ma200_pct = (price - ma200) / ma200 * 100
            ma200_score = max(0, min(100, (ma200_pct + 30) / 60 * 100))
            if ma200_pct > 10:
                ma200_label = "장기 상승세 (탐욕)"
            elif ma200_pct < -10:
                ma200_label = "장기 하락세 (공포)"
            else:
                ma200_label = "중립"
            indicators.append({
                "name": "200일 이평선 대비",
                "value": f"{ma200_pct:+.1f}%",
                "score": round(ma200_score),
                "label": ma200_label,
            })

    # 5) 거래량 변화 (최근 5일 평균 vs 20일 평균)
    if len(volume) >= 20:
        vol_5 = volume.iloc[-5:].mean()
        vol_20 = volume.iloc[-20:].mean()
        if vol_20 > 0:
            vol_ratio = vol_5 / vol_20
            # 거래량 급증은 극단적 심리 (공포든 탐욕이든)
            # 주가 방향과 결합: 주가 상승 + 거래량 증가 = 탐욕, 주가 하락 + 거래량 증가 = 공포
            price_change_5d = (close.iloc[-1] - close.iloc[-5]) / close.iloc[-5] * 100 if len(close) >= 5 else 0
            if price_change_5d > 0:
                vol_score = min(100, 50 + (vol_ratio - 1) * 30)
                vol_label = "매수세 증가" if vol_ratio > 1.2 else "보통"
            else:
                vol_score = max(0, 50 - (vol_ratio - 1) * 30)
                vol_label = "매도세 증가" if vol_ratio > 1.2 else "보통"
            indicators.append({
                "name": "거래량 변화 (5일/20일)",
                "value": f"{vol_ratio:.2f}x",
                "score": round(vol_score),
                "label": vol_label,
            })

    # 6) 변동성 (20일 수익률 표준편차)
    if len(close) >= 20:
        returns = close.pct_change().dropna()
        vol_20d = returns.iloc[-20:].std() * np.sqrt(252) * 100  # 연환산 변동성
        # 변동성 높을수록 공포: 80%+ = 0점, 10% = 100점
        vol_score = max(0, min(100, (80 - vol_20d) / 70 * 100))
        if vol_20d > 50:
            vol_label = "극단적 변동 (공포)"
        elif vol_20d > 30:
            vol_label = "높은 변동성"
        else:
            vol_label = "안정적 (탐욕)"
        indicators.append({
            "name": "변동성 (연환산)",
            "value": f"{vol_20d:.1f}%",
            "score": round(vol_score),
            "label": vol_label,
        })

    # 종합 점수 계산 (가중 평균)
    if indicators:
        total_score = sum(ind["score"] for ind in indicators) / len(indicators)
        total_score = round(total_score)

        if total_score >= 75:
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

    return {"score": None, "label": "데이터 부족", "indicators": []}


# ──────────────────────────────────────────────
# 숏/롱 포지션 데이터
# ──────────────────────────────────────────────
def evaluate_positions(data: dict) -> dict:
    info = data["info"]

    short_data = []
    long_data = []

    # 공매도 데이터
    shares_short = safe_get(info, "sharesShort")
    if shares_short is not None:
        if shares_short >= 1e9:
            val = f"{shares_short/1e9:.2f}B"
        elif shares_short >= 1e6:
            val = f"{shares_short/1e6:.1f}M"
        else:
            val = f"{shares_short/1e3:.0f}K"
        short_data.append({"name": "공매도 수량", "value": val})

    short_pct = safe_get(info, "shortPercentOfFloat")
    if short_pct is not None:
        level = ""
        if short_pct >= 0.20:
            level = " (매우 높음 - 숏스퀴즈 주의)"
        elif short_pct >= 0.10:
            level = " (높음)"
        elif short_pct >= 0.05:
            level = " (보통)"
        else:
            level = " (낮음)"
        short_data.append({"name": "공매도 비율 (유통주식 대비)", "value": f"{short_pct*100:.1f}%{level}"})

    short_ratio = safe_get(info, "shortRatio")
    if short_ratio is not None:
        level = ""
        if short_ratio >= 10:
            level = " (숏커버 어려움)"
        elif short_ratio >= 5:
            level = " (높음)"
        else:
            level = " (보통)"
        short_data.append({"name": "숏 커버 일수 (Days to Cover)", "value": f"{short_ratio:.1f}일{level}"})

    shares_short_prev = safe_get(info, "sharesShortPriorMonth")
    if shares_short is not None and shares_short_prev is not None and shares_short_prev > 0:
        change = (shares_short - shares_short_prev) / shares_short_prev * 100
        direction = "증가" if change > 0 else "감소"
        short_data.append({"name": "전월 대비 공매도 변화", "value": f"{change:+.1f}% ({direction})"})

    # 롱 포지션 데이터
    inst_pct = safe_get(info, "heldPercentInstitutions")
    if inst_pct is not None:
        long_data.append({"name": "기관 보유 비율", "value": f"{inst_pct*100:.1f}%"})

    insider_pct = safe_get(info, "heldPercentInsiders")
    if insider_pct is not None:
        long_data.append({"name": "내부자 보유 비율", "value": f"{insider_pct*100:.1f}%"})

    float_shares = safe_get(info, "floatShares")
    if float_shares is not None:
        if float_shares >= 1e9:
            val = f"{float_shares/1e9:.2f}B"
        elif float_shares >= 1e6:
            val = f"{float_shares/1e6:.0f}M"
        else:
            val = f"{float_shares/1e3:.0f}K"
        long_data.append({"name": "유통 주식수", "value": val})

    shares_outstanding = safe_get(info, "sharesOutstanding")
    if shares_outstanding is not None:
        if shares_outstanding >= 1e9:
            val = f"{shares_outstanding/1e9:.2f}B"
        elif shares_outstanding >= 1e6:
            val = f"{shares_outstanding/1e6:.0f}M"
        else:
            val = f"{shares_outstanding/1e3:.0f}K"
        long_data.append({"name": "총 발행 주식수", "value": val})

    # 숏 심리 판단
    sentiment = "중립"
    sentiment_detail = ""
    if short_pct is not None:
        if short_pct >= 0.20:
            sentiment = "강한 약세 베팅"
            sentiment_detail = "공매도 비율이 매우 높아 숏스퀴즈 가능성 있음"
        elif short_pct >= 0.10:
            sentiment = "약세 베팅 우세"
            sentiment_detail = "공매도가 상당히 잡혀있어 하락 압력 존재"
        elif short_pct >= 0.05:
            sentiment = "소폭 약세"
            sentiment_detail = "적당한 수준의 공매도"
        else:
            sentiment = "강세 우세"
            sentiment_detail = "공매도가 적어 시장이 낙관적"

    return {
        "short": short_data,
        "long": long_data,
        "sentiment": sentiment,
        "sentimentDetail": sentiment_detail,
    }


def evaluate_buffett(info: dict) -> list[dict]:
    results = []

    roe = safe_get(info, "returnOnEquity")
    if roe is not None:
        note = info.get("_roe_note", "")
        val_str = f"{roe*100:.1f}%"
        if note:
            val_str += f" ({note})"
        # 자본잠식(음수 자기자본)이면 ROE가 음수로 나옴 -> NO
        results.append({"name": "ROE >= 15%", "passed": roe >= 0.15 and note != "자본잠식", "value": val_str})
    else:
        results.append({"name": "ROE >= 15%", "passed": None, "value": "데이터 없음"})

    de = safe_get(info, "debtToEquity")
    if de is not None:
        note = info.get("_de_note", "")
        val_str = f"{de:.1f}%"
        if note:
            val_str += f" ({note})"
        # 자본잠식이면 부채비율 의미 없음 -> NO
        results.append({"name": "부채비율 <= 50%", "passed": de <= 50 and de > 0 and note != "자본잠식", "value": val_str})
    else:
        results.append({"name": "부채비율 <= 50%", "passed": None, "value": "데이터 없음"})

    om = safe_get(info, "operatingMargins")
    if om is not None:
        results.append({"name": "영업이익률 >= 15%", "passed": om >= 0.15, "value": f"{om*100:.1f}%"})
    else:
        results.append({"name": "영업이익률 >= 15%", "passed": None, "value": "데이터 없음"})

    rg = safe_get(info, "revenueGrowth")
    if rg is not None:
        results.append({"name": "매출 성장 중", "passed": rg > 0, "value": f"{rg*100:.1f}%"})
    else:
        results.append({"name": "매출 성장 중", "passed": None, "value": "데이터 없음"})

    fcf = safe_get(info, "freeCashflow")
    if fcf is not None:
        results.append({"name": "FCF 양수", "passed": fcf > 0, "value": f"${fcf/1e9:.2f}B"})
    else:
        results.append({"name": "FCF 양수", "passed": None, "value": "데이터 없음"})

    return results


def evaluate_graham(info: dict) -> list[dict]:
    results = []

    per = safe_get(info, "trailingPE")
    if per is not None:
        results.append({"name": "PER <= 15", "passed": 0 < per <= 15, "value": f"{per:.1f}"})
    else:
        results.append({"name": "PER <= 15", "passed": None, "value": "데이터 없음"})

    pbr = safe_get(info, "priceToBook")
    if pbr is not None:
        results.append({"name": "PBR <= 1.5", "passed": 0 < pbr <= 1.5, "value": f"{pbr:.2f}"})
    else:
        results.append({"name": "PBR <= 1.5", "passed": None, "value": "데이터 없음"})

    if per and pbr and per > 0 and pbr > 0:
        p = per * pbr
        results.append({"name": "PER x PBR < 22.5", "passed": p < 22.5, "value": f"{p:.1f}"})
    else:
        results.append({"name": "PER x PBR < 22.5", "passed": None, "value": "데이터 없음"})

    cr = safe_get(info, "currentRatio")
    if cr is not None:
        results.append({"name": "유동비율 >= 200%", "passed": cr >= 2.0, "value": f"{cr*100:.0f}%"})
    else:
        results.append({"name": "유동비율 >= 200%", "passed": None, "value": "데이터 없음"})

    dy = safe_get(info, "dividendYield")
    if dy is not None:
        results.append({"name": "배당 지급", "passed": dy > 0, "value": f"{dy*100:.2f}%"})
    else:
        results.append({"name": "배당 지급", "passed": None, "value": "데이터 없음"})

    return results


def evaluate_lynch(info: dict) -> list[dict]:
    results = []

    peg = safe_get(info, "pegRatio")
    if peg is not None:
        results.append({"name": "PEG < 1", "passed": 0 < peg < 1, "value": f"{peg:.2f}"})
    else:
        results.append({"name": "PEG < 1", "passed": None, "value": "데이터 없음"})

    rg = safe_get(info, "revenueGrowth")
    if rg is not None:
        results.append({"name": "매출 성장률 > 10%", "passed": rg > 0.10, "value": f"{rg*100:.1f}%"})
    else:
        results.append({"name": "매출 성장률 > 10%", "passed": None, "value": "데이터 없음"})

    eg = safe_get(info, "earningsGrowth")
    if eg is not None:
        results.append({"name": "EPS 성장률 > 15%", "passed": eg > 0.15, "value": f"{eg*100:.1f}%"})
    else:
        results.append({"name": "EPS 성장률 > 15%", "passed": None, "value": "데이터 없음"})

    de = safe_get(info, "debtToEquity")
    if de is not None:
        results.append({"name": "부채비율 <= 80%", "passed": de <= 80, "value": f"{de:.1f}%"})
    else:
        results.append({"name": "부채비율 <= 80%", "passed": None, "value": "데이터 없음"})

    inst = safe_get(info, "heldPercentInstitutions")
    if inst is not None:
        results.append({"name": "기관 보유 < 60%", "passed": inst < 0.60, "value": f"{inst*100:.1f}%"})
    else:
        results.append({"name": "기관 보유 < 60%", "passed": None, "value": "데이터 없음"})

    return results


def evaluate_oneil(info: dict) -> list[dict]:
    results = []

    eq = safe_get(info, "earningsQuarterlyGrowth")
    if eq is not None:
        results.append({"name": "C: 분기 EPS 성장 >= 25%", "passed": eq >= 0.25, "value": f"{eq*100:.1f}%"})
    else:
        results.append({"name": "C: 분기 EPS 성장 >= 25%", "passed": None, "value": "데이터 없음"})

    eg = safe_get(info, "earningsGrowth")
    if eg is not None:
        results.append({"name": "A: 연간 EPS 성장 중", "passed": eg > 0, "value": f"{eg*100:.1f}%"})
    else:
        results.append({"name": "A: 연간 EPS 성장 중", "passed": None, "value": "데이터 없음"})

    price = safe_get(info, "currentPrice") or safe_get(info, "regularMarketPrice")
    high52 = safe_get(info, "fiftyTwoWeekHigh")
    if price and high52 and high52 > 0:
        r = price / high52
        results.append({"name": "N: 52주 고가 근처(90%+)", "passed": r >= 0.90, "value": f"{r*100:.1f}%"})
    else:
        results.append({"name": "N: 52주 고가 근처(90%+)", "passed": None, "value": "데이터 없음"})

    avg_vol = safe_get(info, "averageVolume")
    vol = safe_get(info, "volume")
    if avg_vol and vol and avg_vol > 0:
        vr = vol / avg_vol
        results.append({"name": "S: 거래량 >= 평균", "passed": vr >= 1.0, "value": f"{vr:.2f}x"})
    else:
        results.append({"name": "S: 거래량 >= 평균", "passed": None, "value": "데이터 없음"})

    roe = safe_get(info, "returnOnEquity")
    if roe is not None:
        results.append({"name": "L: ROE >= 17% (선도주)", "passed": roe >= 0.17, "value": f"{roe*100:.1f}%"})
    else:
        results.append({"name": "L: ROE >= 17% (선도주)", "passed": None, "value": "데이터 없음"})

    inst = safe_get(info, "heldPercentInstitutions")
    if inst is not None:
        results.append({"name": "I: 기관 보유 >= 20%", "passed": inst >= 0.20, "value": f"{inst*100:.1f}%"})
    else:
        results.append({"name": "I: 기관 보유 >= 20%", "passed": None, "value": "데이터 없음"})

    return results


def evaluate_fisher(info: dict) -> list[dict]:
    results = []

    rg = safe_get(info, "revenueGrowth")
    if rg is not None:
        results.append({"name": "매출 성장률 > 10%", "passed": rg > 0.10, "value": f"{rg*100:.1f}%"})
    else:
        results.append({"name": "매출 성장률 > 10%", "passed": None, "value": "데이터 없음"})

    om = safe_get(info, "operatingMargins")
    if om is not None:
        results.append({"name": "영업이익률 >= 15%", "passed": om >= 0.15, "value": f"{om*100:.1f}%"})
    else:
        results.append({"name": "영업이익률 >= 15%", "passed": None, "value": "데이터 없음"})

    gm = safe_get(info, "grossMargins")
    if gm is not None:
        results.append({"name": "매출총이익률 >= 40% (R&D 여력)", "passed": gm >= 0.40, "value": f"{gm*100:.1f}%"})
    else:
        results.append({"name": "매출총이익률 >= 40% (R&D 여력)", "passed": None, "value": "데이터 없음"})

    pm = safe_get(info, "profitMargins")
    if pm is not None:
        results.append({"name": "순이익률 > 10%", "passed": pm > 0.10, "value": f"{pm*100:.1f}%"})
    else:
        results.append({"name": "순이익률 > 10%", "passed": None, "value": "데이터 없음"})

    price = safe_get(info, "currentPrice") or safe_get(info, "regularMarketPrice")
    target = safe_get(info, "targetMeanPrice")
    if price and target and price > 0:
        upside = (target - price) / price
        results.append({"name": "애널리스트 목표가 10%+ 상승여력", "passed": upside > 0.10, "value": f"{upside*100:.1f}%"})
    else:
        results.append({"name": "애널리스트 목표가 10%+ 상승여력", "passed": None, "value": "데이터 없음"})

    return results


# ──────────────────────────────────────────────
# 옵션 체인 분석
# ──────────────────────────────────────────────
def evaluate_options(data: dict) -> dict:
    """옵션 체인에서 풋/콜 포지션 분석"""
    info = data["info"]
    stock = data.get("stock")
    price = safe_get(info, "currentPrice") or safe_get(info, "regularMarketPrice")

    if stock is None or price is None:
        return {"available": False}

    try:
        expirations = stock.options
        if not expirations:
            return {"available": False}

        # 가장 가까운 만기일 사용
        exp_date = expirations[0]
        opt = stock.option_chain(exp_date)
        calls = opt.calls
        puts = opt.puts

        if calls.empty and puts.empty:
            return {"available": False}

        # 풋/콜 비율
        total_call_vol = int(calls["volume"].sum()) if "volume" in calls.columns else 0
        total_put_vol = int(puts["volume"].sum()) if "volume" in puts.columns else 0
        total_call_oi = int(calls["openInterest"].sum()) if "openInterest" in calls.columns else 0
        total_put_oi = int(puts["openInterest"].sum()) if "openInterest" in puts.columns else 0

        pcr_vol = round(total_put_vol / total_call_vol, 2) if total_call_vol > 0 else None
        pcr_oi = round(total_put_oi / total_call_oi, 2) if total_call_oi > 0 else None

        # 풋/콜 비율 해석
        if pcr_oi is not None:
            if pcr_oi >= 1.5:
                pcr_label = "극단적 약세 (하락 베팅 압도적)"
            elif pcr_oi >= 1.0:
                pcr_label = "약세 우세 (하락 베팅 > 상승 베팅)"
            elif pcr_oi >= 0.7:
                pcr_label = "중립"
            elif pcr_oi >= 0.5:
                pcr_label = "강세 우세 (상승 베팅 > 하락 베팅)"
            else:
                pcr_label = "극단적 강세 (상승 베팅 압도적)"
        else:
            pcr_label = "데이터 없음"

        # 가격대별 미결제약정 TOP 5 (풋)
        put_oi_top = []
        if not puts.empty and "openInterest" in puts.columns:
            top_puts = puts.nlargest(5, "openInterest")
            for _, row in top_puts.iterrows():
                strike = float(row["strike"])
                oi = int(row["openInterest"])
                diff_pct = (strike - price) / price * 100
                if strike < price:
                    desc = f"현재가 대비 {abs(diff_pct):.1f}% 아래 - 이 가격까지 하락 베팅"
                elif strike > price:
                    desc = f"현재가 대비 {abs(diff_pct):.1f}% 위 - 하락 헤지 포지션"
                else:
                    desc = "현재가 수준 - 하락 방어선"
                put_oi_top.append({
                    "strike": strike,
                    "oi": oi,
                    "diffPct": round(diff_pct, 1),
                    "desc": desc,
                })

        # 가격대별 미결제약정 TOP 5 (콜)
        call_oi_top = []
        if not calls.empty and "openInterest" in calls.columns:
            top_calls = calls.nlargest(5, "openInterest")
            for _, row in top_calls.iterrows():
                strike = float(row["strike"])
                oi = int(row["openInterest"])
                diff_pct = (strike - price) / price * 100
                if strike > price:
                    desc = f"현재가 대비 {abs(diff_pct):.1f}% 위 - 이 가격까지 상승 베팅"
                elif strike < price:
                    desc = f"현재가 대비 {abs(diff_pct):.1f}% 아래 - ITM 콜 (이미 수익)"
                else:
                    desc = "현재가 수준 - 상승 출발점"
                call_oi_top.append({
                    "strike": strike,
                    "oi": oi,
                    "diffPct": round(diff_pct, 1),
                    "desc": desc,
                })

        # 맥스페인 (Max Pain) - 옵션 매도자가 가장 유리한 가격
        all_strikes = sorted(set(calls["strike"].tolist() + puts["strike"].tolist()))
        min_pain = float("inf")
        max_pain_strike = price
        for s in all_strikes:
            pain = 0
            for _, row in calls.iterrows():
                if s > row["strike"]:
                    pain += (s - row["strike"]) * row.get("openInterest", 0)
            for _, row in puts.iterrows():
                if s < row["strike"]:
                    pain += (row["strike"] - s) * row.get("openInterest", 0)
            if pain < min_pain:
                min_pain = pain
                max_pain_strike = s

        max_pain_diff = (max_pain_strike - price) / price * 100
        if max_pain_diff > 2:
            max_pain_desc = f"현재가보다 {max_pain_diff:.1f}% 위 - 주가 상승 압력"
        elif max_pain_diff < -2:
            max_pain_desc = f"현재가보다 {abs(max_pain_diff):.1f}% 아래 - 주가 하락 압력"
        else:
            max_pain_desc = "현재가 근처 - 큰 변동 없을 가능성"

        return {
            "available": True,
            "expDate": exp_date,
            "currentPrice": round(price, 2),
            "pcrVolume": pcr_vol,
            "pcrOI": pcr_oi,
            "pcrLabel": pcr_label,
            "totalCallVol": total_call_vol,
            "totalPutVol": total_put_vol,
            "totalCallOI": total_call_oi,
            "totalPutOI": total_put_oi,
            "putOITop": put_oi_top,
            "callOITop": call_oi_top,
            "maxPain": round(max_pain_strike, 2),
            "maxPainDiff": round(max_pain_diff, 1),
            "maxPainDesc": max_pain_desc,
        }
    except Exception:
        return {"available": False}


# ──────────────────────────────────────────────
# 종목 검색 API
# ──────────────────────────────────────────────
def resolve_ticker(query: str) -> str | None:
    """검색어를 티커로 변환"""
    q = query.strip()

    # 이미 티커 형식이면 그대로 반환 (ASCII 영문만)
    if q.isascii() and q.upper() == q and q.replace("-", "").replace(".", "").isalpha() and len(q) <= 6:
        return q.upper()

    # 한국 주식 숫자코드 (예: 005930)
    if q.isdigit() and len(q) == 6:
        return q + ".KS"

    # 한국어 매핑 검색
    if q in KR_STOCKS:
        return KR_STOCKS[q][0]
    if q in US_STOCKS_KR:
        return US_STOCKS_KR[q]

    # 부분 매칭
    for name, (ticker, _) in KR_STOCKS.items():
        if q in name:
            return ticker
    for kr_name, ticker in US_STOCKS_KR.items():
        if q in kr_name:
            return ticker

    # Yahoo Finance 검색 API
    try:
        encoded = urllib.parse.quote(q)
        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={encoded}&quotesCount=1&newsCount=0&listsCount=0"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=5)
        data = json_lib.loads(resp.read())
        quotes = data.get("quotes", [])
        if quotes:
            return quotes[0]["symbol"]
    except Exception:
        pass

    return None


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/search", methods=["GET"])
def search_stocks():
    """종목 검색 자동완성 API"""
    q = request.args.get("q", "").strip()
    if len(q) < 1:
        return jsonify([])

    results = []

    # 1) 한국어 로컬 검색
    kr_results = search_kr_stocks(q)
    results.extend(kr_results)

    # 2) Yahoo Finance 검색 (영문 또는 티커)
    try:
        encoded = urllib.parse.quote(q)
        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={encoded}&quotesCount=6&newsCount=0&listsCount=0"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=5)
        data = json_lib.loads(resp.read())
        for item in data.get("quotes", []):
            symbol = item.get("symbol", "")
            # 이미 로컬 결과에 있으면 스킵
            if any(r["symbol"] == symbol for r in results):
                continue
            results.append({
                "symbol": symbol,
                "name": item.get("shortname", "") or item.get("longname", ""),
                "engName": item.get("longname", ""),
                "exchange": item.get("exchDisp", ""),
            })
    except Exception:
        pass

    return jsonify(results[:8])


@app.route("/api/analyze", methods=["POST"])
def analyze():
    raw_query = request.json.get("ticker", "").strip()
    if not raw_query:
        return jsonify({"error": "종목명 또는 티커를 입력해주세요."}), 400

    # 티커 변환 (이름 -> 티커)
    ticker = resolve_ticker(raw_query)
    if ticker is None:
        ticker = raw_query.upper()

    data = get_stock_data(ticker)
    if data is None:
        return jsonify({"error": f"'{raw_query}' 종목을 찾을 수 없습니다. 티커 또는 종목명을 확인해주세요."}), 404

    info = data["info"]

    # 종목 기본 정보
    price = safe_get(info, "currentPrice") or safe_get(info, "regularMarketPrice", 0)
    market_cap = safe_get(info, "marketCap", 0)
    cap_str = f"${market_cap/1e9:.1f}B" if market_cap >= 1e9 else f"${market_cap/1e6:.0f}M"

    stock_info = {
        "name": safe_get(info, "longName", ticker),
        "sector": safe_get(info, "sector", "N/A"),
        "industry": safe_get(info, "industry", "N/A"),
        "price": f"{safe_get(info, 'currency', 'USD')} {price:,.2f}",
        "marketCap": cap_str,
        "logo": safe_get(info, "logo_url", ""),
    }

    # 각 투자자별 평가
    investors = [
        {"name": "워렌 버핏", "sub": "가치투자", "icon": "buffett", "criteria": evaluate_buffett(info)},
        {"name": "벤저민 그레이엄", "sub": "안전마진", "icon": "graham", "criteria": evaluate_graham(info)},
        {"name": "피터 린치", "sub": "성장주", "icon": "lynch", "criteria": evaluate_lynch(info)},
        {"name": "윌리엄 오닐", "sub": "CAN SLIM", "icon": "oneil", "criteria": evaluate_oneil(info)},
        {"name": "필립 피셔", "sub": "장기성장", "icon": "fisher", "criteria": evaluate_fisher(info)},
    ]

    # 각 투자자별 통과율 계산
    total_yes = 0
    total_count = 0
    for inv in investors:
        yes = sum(1 for c in inv["criteria"] if c["passed"] is True)
        count = sum(1 for c in inv["criteria"] if c["passed"] is not None)
        inv["yes"] = yes
        inv["total"] = count
        inv["rate"] = round(yes / count * 100) if count > 0 else 0
        total_yes += yes
        total_count += count

    overall_rate = round(total_yes / total_count * 100) if total_count > 0 else 0
    if overall_rate >= 70:
        grade = "A"
        grade_text = "매우 우수"
    elif overall_rate >= 55:
        grade = "B"
        grade_text = "우수"
    elif overall_rate >= 40:
        grade = "C"
        grade_text = "보통"
    elif overall_rate >= 25:
        grade = "D"
        grade_text = "미흡"
    else:
        grade = "F"
        grade_text = "부적합"

    # 공포/탐욕 지수
    fear_greed = evaluate_fear_greed(data)

    # 숏/롱 포지션
    positions = evaluate_positions(data)

    # 옵션 체인 분석
    options = evaluate_options(data)

    return jsonify({
        "stock": stock_info,
        "ticker": ticker,
        "fearGreed": fear_greed,
        "positions": positions,
        "options": options,
        "investors": investors,
        "overall": {
            "yes": total_yes,
            "total": total_count,
            "rate": overall_rate,
            "grade": grade,
            "gradeText": grade_text,
        }
    })


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
