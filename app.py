"""
유명 투자자 기준 주식 스크리너 - Flask 웹앱
"""

from flask import Flask, render_template, request, jsonify
import yfinance as yf

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

        return {"info": info}
    except Exception:
        return None


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


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/analyze", methods=["POST"])
def analyze():
    ticker = request.json.get("ticker", "").strip().upper()
    if not ticker:
        return jsonify({"error": "티커를 입력해주세요."}), 400

    data = get_stock_data(ticker)
    if data is None:
        return jsonify({"error": f"'{ticker}' 종목을 찾을 수 없습니다."}), 404

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

    return jsonify({
        "stock": stock_info,
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
