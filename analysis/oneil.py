"""CAN SLIM 개선판 — M과 RS 추가."""


def _safe(info, key, default=None):
    v = info.get(key, default)
    return v if v is not None else default


def evaluate_oneil(info: dict, ticker: str = "",
                   hist=None, rs_data: dict | None = None,
                   market_data: dict | None = None) -> list[dict]:
    results = []

    # C: 분기 EPS 성장 >= 25%
    eq = _safe(info, "earningsQuarterlyGrowth")
    if eq is not None:
        results.append({"name": "C: 분기 EPS 성장 >= 25%", "passed": eq >= 0.25, "value": f"{eq*100:.1f}%"})
    else:
        results.append({"name": "C: 분기 EPS 성장 >= 25%", "passed": None, "value": "데이터 없음"})

    # A: 연간 EPS 성장 >= 25%
    eg = _safe(info, "earningsGrowth")
    if eg is not None:
        results.append({"name": "A: 연간 EPS 성장 >= 25%", "passed": eg >= 0.25, "value": f"{eg*100:.1f}%"})
    else:
        results.append({"name": "A: 연간 EPS 성장 >= 25%", "passed": None, "value": "데이터 없음"})

    # N: 52주 고가 85%+
    price = _safe(info, "currentPrice") or _safe(info, "regularMarketPrice")
    high52 = _safe(info, "fiftyTwoWeekHigh")
    if price and high52 and high52 > 0:
        r = price / high52
        results.append({"name": "N: 52주 고가 근처(85%+)", "passed": r >= 0.85, "value": f"{r*100:.1f}%"})
    else:
        results.append({"name": "N: 52주 고가 근처(85%+)", "passed": None, "value": "데이터 없음"})

    # S: 거래량 >= 1.5x 평균
    avg_vol = _safe(info, "averageVolume")
    vol = _safe(info, "volume")
    if avg_vol and vol and avg_vol > 0:
        vr = vol / avg_vol
        results.append({"name": "S: 거래량 >= 1.5x 평균", "passed": vr >= 1.5, "value": f"{vr:.2f}x"})
    else:
        results.append({"name": "S: 거래량 >= 1.5x 평균", "passed": None, "value": "데이터 없음"})

    # L: RS Rating >= 80
    if rs_data and rs_data.get("available"):
        rc = rs_data.get("rs_composite")
        if rc is not None:
            results.append({"name": "L: RS Rating >= 80 (선도주)", "passed": rc >= 80, "value": f"{rc}"})
        else:
            results.append({"name": "L: RS Rating >= 80 (선도주)", "passed": None, "value": "데이터 없음"})
    else:
        results.append({"name": "L: RS Rating >= 80 (선도주)", "passed": None, "value": "데이터 없음"})

    # I: 기관 보유 >= 20%
    inst = _safe(info, "heldPercentInstitutions")
    if inst is not None:
        results.append({"name": "I: 기관 보유 >= 20%", "passed": inst >= 0.20, "value": f"{inst*100:.1f}%"})
    else:
        results.append({"name": "I: 기관 보유 >= 20%", "passed": None, "value": "데이터 없음"})

    # M: 시장 방향 상승장
    if market_data and market_data.get("available"):
        passed_m = market_data.get("passed_canslim_m")
        val = market_data.get("direction", "데이터 없음")
        results.append({"name": "M: 시장 방향 = 상승장", "passed": bool(passed_m), "value": val})
    else:
        results.append({"name": "M: 시장 방향 = 상승장", "passed": None, "value": "데이터 없음"})

    return results
