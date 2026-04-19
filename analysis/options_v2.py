"""벡터화된 옵션 체인 분석 — Max Pain NumPy 브로드캐스트."""

import numpy as np


def _safe(info, key, default=None):
    v = info.get(key, default)
    return v if v is not None else default


def evaluate_options(data: dict) -> dict:
    info = data["info"]
    stock = data.get("stock")
    price = _safe(info, "currentPrice") or _safe(info, "regularMarketPrice")

    if stock is None or price is None:
        return {"available": False}

    try:
        expirations = stock.options
        if not expirations:
            return {"available": False}
        exp_date = expirations[0]
        opt = stock.option_chain(exp_date)
        calls = opt.calls
        puts = opt.puts
        if calls.empty and puts.empty:
            return {"available": False}
    except Exception:
        return {"available": False}

    total_call_vol = int(calls["volume"].fillna(0).sum()) if "volume" in calls.columns else 0
    total_put_vol = int(puts["volume"].fillna(0).sum()) if "volume" in puts.columns else 0
    total_call_oi = int(calls["openInterest"].fillna(0).sum()) if "openInterest" in calls.columns else 0
    total_put_oi = int(puts["openInterest"].fillna(0).sum()) if "openInterest" in puts.columns else 0

    pcr_vol = round(total_put_vol / total_call_vol, 2) if total_call_vol > 0 else None
    pcr_oi = round(total_put_oi / total_call_oi, 2) if total_call_oi > 0 else None

    if pcr_oi is None:
        pcr_label = "데이터 없음"
    elif pcr_oi >= 1.5:
        pcr_label = "극단적 약세 (하락 베팅 압도적)"
    elif pcr_oi >= 1.0:
        pcr_label = "약세 우세 (하락 베팅 > 상승 베팅)"
    elif pcr_oi >= 0.7:
        pcr_label = "중립"
    elif pcr_oi >= 0.5:
        pcr_label = "강세 우세 (상승 베팅 > 하락 베팅)"
    else:
        pcr_label = "극단적 강세 (상승 베팅 압도적)"

    # 풋 OI TOP 5
    put_oi_top = []
    if not puts.empty and "openInterest" in puts.columns:
        top_puts = puts.nlargest(5, "openInterest")
        for _, row in top_puts.iterrows():
            strike = float(row["strike"])
            oi = int(row["openInterest"]) if row["openInterest"] == row["openInterest"] else 0
            diff_pct = (strike - price) / price * 100
            if strike < price:
                desc = f"현재가 대비 {abs(diff_pct):.1f}% 아래 - 이 가격까지 하락 베팅"
            elif strike > price:
                desc = f"현재가 대비 {abs(diff_pct):.1f}% 위 - 하락 헤지 포지션"
            else:
                desc = "현재가 수준 - 하락 방어선"
            put_oi_top.append({"strike": strike, "oi": oi, "diffPct": round(diff_pct, 1), "desc": desc})

    # 콜 OI TOP 5
    call_oi_top = []
    if not calls.empty and "openInterest" in calls.columns:
        top_calls = calls.nlargest(5, "openInterest")
        for _, row in top_calls.iterrows():
            strike = float(row["strike"])
            oi = int(row["openInterest"]) if row["openInterest"] == row["openInterest"] else 0
            diff_pct = (strike - price) / price * 100
            if strike > price:
                desc = f"현재가 대비 {abs(diff_pct):.1f}% 위 - 이 가격까지 상승 베팅"
            elif strike < price:
                desc = f"현재가 대비 {abs(diff_pct):.1f}% 아래 - ITM 콜 (이미 수익)"
            else:
                desc = "현재가 수준 - 상승 출발점"
            call_oi_top.append({"strike": strike, "oi": oi, "diffPct": round(diff_pct, 1), "desc": desc})

    # Max Pain 벡터화
    try:
        call_strikes = calls["strike"].values.astype(float) if not calls.empty else np.array([])
        call_oi_arr = calls["openInterest"].fillna(0).values.astype(float) if not calls.empty else np.array([])
        put_strikes = puts["strike"].values.astype(float) if not puts.empty else np.array([])
        put_oi_arr = puts["openInterest"].fillna(0).values.astype(float) if not puts.empty else np.array([])

        all_strikes_set = set()
        if len(call_strikes) > 0:
            all_strikes_set.update(call_strikes.tolist())
        if len(put_strikes) > 0:
            all_strikes_set.update(put_strikes.tolist())
        test_strikes = np.array(sorted(all_strikes_set))

        if len(test_strikes) == 0:
            max_pain_strike = price
        else:
            pain_calls = np.zeros(len(test_strikes))
            pain_puts = np.zeros(len(test_strikes))
            if len(call_strikes) > 0:
                diff_c = np.maximum(test_strikes[:, None] - call_strikes[None, :], 0)
                pain_calls = diff_c @ call_oi_arr
            if len(put_strikes) > 0:
                diff_p = np.maximum(put_strikes[None, :] - test_strikes[:, None], 0)
                pain_puts = diff_p @ put_oi_arr
            total_pain = pain_calls + pain_puts
            max_pain_strike = float(test_strikes[int(total_pain.argmin())])
    except Exception:
        max_pain_strike = price

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
