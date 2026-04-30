"""5인 투자 거장 채점 로직 — 순수 함수, 외부 의존성 없음.

원래 app.py 안에 있던 evaluate_* 함수들을 분리.
입력은 yfinance/DART에서 가져온 info dict, 섹터 기준값, 다년도 history.
출력은 [{name, passed, value}, ...] 형태의 채점 결과.

테스트: tests/test_evaluators.py — 21개 회귀 테스트 통과 보장
"""
from __future__ import annotations


def safe_get(info: dict, key: str, default=None):
    """info dict에서 안전하게 값 가져오기 — None이면 default 반환."""
    val = info.get(key, default)
    return val if val is not None else default


def fmt_money(amount: float, info: dict = None) -> str:
    """금액을 통화·규모에 맞게 포맷. KRW는 조/억, USD는 B/M."""
    if amount is None:
        return "데이터 없음"
    cur = (info or {}).get("currency") or "USD"
    if cur == "KRW":
        a = abs(amount)
        if a >= 1e12:
            return f"₩{amount/1e12:.1f}조"
        if a >= 1e8:
            return f"₩{amount/1e8:.0f}억"
        if a >= 1e4:
            return f"₩{amount/1e4:.0f}만"
        return f"₩{amount:,.0f}"
    # USD 기본
    a = abs(amount)
    if a >= 1e9:
        return f"${amount/1e9:.2f}B"
    if a >= 1e6:
        return f"${amount/1e6:.0f}M"
    return f"${amount:,.0f}"


def evaluate_positions(data: dict) -> dict:
    """공매도·기관 보유 등 시장 포지션 정보를 short/long으로 정리."""
    info = data.get("info") or {}
    short_data, long_data = [], []

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

    inst_pct = safe_get(info, "heldPercentInstitutions")
    if inst_pct is not None:
        long_data.append({"name": "기관 보유 비율", "value": f"{inst_pct*100:.1f}%"})

    insider_pct = safe_get(info, "heldPercentInsiders")
    if insider_pct is not None:
        long_data.append({"name": "내부자 보유 비율", "value": f"{insider_pct*100:.1f}%"})

    for key, name in [("floatShares", "유통 주식수"), ("sharesOutstanding", "총 발행 주식수")]:
        v = safe_get(info, key)
        if v is not None:
            if v >= 1e9:
                val = f"{v/1e9:.2f}B"
            elif v >= 1e6:
                val = f"{v/1e6:.0f}M"
            else:
                val = f"{v/1e3:.0f}K"
            long_data.append({"name": name, "value": val})

    sentiment = "중립"
    sentiment_detail = ""
    if short_pct is not None:
        if short_pct >= 0.20:
            sentiment, sentiment_detail = "강한 약세 베팅", "공매도 비율이 매우 높아 숏스퀴즈 가능성 있음"
        elif short_pct >= 0.10:
            sentiment, sentiment_detail = "약세 베팅 우세", "공매도가 상당히 잡혀있어 하락 압력 존재"
        elif short_pct >= 0.05:
            sentiment, sentiment_detail = "소폭 약세", "적당한 수준의 공매도"
        else:
            sentiment, sentiment_detail = "강세 우세", "공매도가 적어 시장이 낙관적"

    return {"short": short_data, "long": long_data, "sentiment": sentiment, "sentimentDetail": sentiment_detail}


def evaluate_buffett(info: dict, sector_t: dict, history_data: dict | None = None, fair_value: dict | None = None) -> list[dict]:
    """버핏 9대 기준 — 원조 5개 + 개선 4개 (다년도 ROE·해자·안전마진)."""
    results = []

    # ===== 원조 5개 =====

    # 1. ROE (섹터 기준)
    roe = safe_get(info, "returnOnEquity")
    if roe is not None:
        note = info.get("_roe_note", "")
        val_str = f"{roe*100:.1f}%" + (f" ({note})" if note else "")
        results.append({"name": f"ROE >= {sector_t['roe_min']*100:.0f}% (섹터 기준)",
                        "passed": roe >= sector_t['roe_min'] and note != "자본잠식",
                        "value": val_str})
    else:
        results.append({"name": "ROE (섹터 기준)", "passed": None, "value": "데이터 없음"})

    # 2. 부채비율
    de = safe_get(info, "debtToEquity")
    if de is not None:
        note = info.get("_de_note", "")
        val_str = f"{de:.1f}%" + (f" ({note})" if note else "")
        results.append({"name": f"부채비율 <= {sector_t['de_max']}% (섹터 기준)",
                        "passed": de <= sector_t['de_max'] and de > 0 and note != "자본잠식",
                        "value": val_str})
    else:
        results.append({"name": "부채비율 (섹터 기준)", "passed": None, "value": "데이터 없음"})

    # 3. 영업이익률
    om = safe_get(info, "operatingMargins")
    if om is not None:
        results.append({"name": f"영업이익률 >= {sector_t['om_min']*100:.0f}% (섹터 기준)",
                        "passed": om >= sector_t['om_min'], "value": f"{om*100:.1f}%"})
    else:
        results.append({"name": "영업이익률 (섹터 기준)", "passed": None, "value": "데이터 없음"})

    # 4. 매출 성장
    rg = safe_get(info, "revenueGrowth")
    if rg is not None:
        results.append({"name": "매출 성장 중", "passed": rg > 0, "value": f"{rg*100:.1f}%"})
    else:
        results.append({"name": "매출 성장 중", "passed": None, "value": "데이터 없음"})

    # 5. FCF 양수
    fcf = safe_get(info, "freeCashflow")
    if fcf is not None:
        results.append({"name": "FCF 양수", "passed": fcf > 0, "value": fmt_money(fcf, info)})
    else:
        results.append({"name": "FCF 양수", "passed": None, "value": "데이터 없음"})

    # ===== 개선 4개 (실제 버핏 철학 반영) =====

    # 6. ROE 꾸준함 (여러 해 연속 15%+)
    if history_data and history_data.get("available") and history_data.get("roe_consistency"):
        rc = history_data["roe_consistency"]
        years_above = rc.get("years_above_15pct", 0)
        total = rc.get("total_measured", 0)
        passed = total >= 3 and years_above >= max(3, int(total * 0.6))
        results.append({
            "name": "ROE 꾸준함 (다년도 15%+)",
            "passed": passed if total >= 3 else None,
            "value": f"{years_above}/{total}년" if total > 0 else "데이터 없음"
        })
    else:
        results.append({"name": "ROE 꾸준함 (다년도 15%+)", "passed": None, "value": "데이터 없음"})

    # 7. Gross Margin 안정성 (편차 5%p 이하)
    if history_data and history_data.get("gross_margin_analysis"):
        gma = history_data["gross_margin_analysis"]
        std = gma.get("std")
        avg = gma.get("avg")
        measured = gma.get("measured", 0)
        if std is not None and avg is not None and measured >= 3:
            results.append({
                "name": "Gross Margin 안정 (편차 ≤5%p)",
                "passed": std <= 0.05,
                "value": f"평균 {avg*100:.1f}% · 편차 {std*100:.1f}%p"
            })
        else:
            results.append({"name": "Gross Margin 안정", "passed": None, "value": "데이터 부족"})
    else:
        results.append({"name": "Gross Margin 안정", "passed": None, "value": "데이터 없음"})

    # 8. R&D 투자 적극성 (섹터별 기준)
    if history_data and history_data.get("rd_analysis"):
        rda = history_data["rd_analysis"]
        rd = rda.get("latest")
        sector = info.get("sector", "")
        rd_threshold = {
            "Technology": 0.05,
            "Healthcare": 0.08,
            "Communication Services": 0.05,
        }.get(sector, 0.01)
        if rd is not None:
            results.append({
                "name": f"R&D 투자 (매출 대비 {rd_threshold*100:.0f}%+)",
                "passed": rd >= rd_threshold,
                "value": f"{rd*100:.1f}%"
            })
        else:
            if sector in ("Financial Services", "Utilities", "Real Estate", "Energy"):
                results.append({
                    "name": "R&D 투자 (섹터 특성)",
                    "passed": True,
                    "value": f"{sector} — 해당 없음"
                })
            else:
                results.append({"name": "R&D 투자", "passed": None, "value": "데이터 없음"})
    else:
        results.append({"name": "R&D 투자", "passed": None, "value": "데이터 없음"})

    # 9. 안전마진 30%+ (저평가)
    if fair_value and fair_value.get("available"):
        upside = fair_value.get("upside_pct", 0) or 0
        results.append({
            "name": "안전마진 30%+ (저평가)",
            "passed": upside >= 30,
            "value": f"{upside:+.1f}% (기준 +30%)"
        })
    else:
        results.append({"name": "안전마진 30%+ (저평가)", "passed": None, "value": "데이터 없음"})

    # 10. ROE 20%+ (버핏 선호 — 코카콜라·시즈캔디 수준)
    if roe is not None:
        results.append({
            "name": "ROE 20%+ (버핏 최선호)",
            "passed": roe >= 0.20,
            "value": f"{roe*100:.1f}% (기준 20%)"
        })
    else:
        results.append({"name": "ROE 20%+ (버핏 최선호)", "passed": None, "value": "데이터 없음"})

    return results


def buffett_strict_grade(yes: int, total: int) -> dict:
    """버핏 전용 점수 등급 (10기준 통과 수). 정량 점수만 표시 — 매수·매도 권유 아님."""
    if total == 0:
        return {"grade": "N/A", "text": "데이터 부족", "color": "gray", "score": "—/10"}
    pct = yes / total * 100
    score_str = f"{yes}/{total}"
    if pct >= 90:
        return {"grade": "A+", "text": f"버핏 기준 {score_str} 충족 (90%+)", "color": "green", "score": score_str}
    if pct >= 80:
        return {"grade": "A", "text": f"버핏 기준 {score_str} 충족", "color": "green", "score": score_str}
    if pct >= 70:
        return {"grade": "B", "text": f"버핏 기준 {score_str} 충족", "color": "green", "score": score_str}
    if pct >= 50:
        return {"grade": "C", "text": f"버핏 기준 {score_str} 부분 충족", "color": "yellow", "score": score_str}
    if pct >= 30:
        return {"grade": "D", "text": f"버핏 기준 {score_str} 충족 — 미달 항목 다수", "color": "red", "score": score_str}
    return {"grade": "F", "text": f"버핏 기준 {score_str} 충족 — 대부분 미충족", "color": "red", "score": score_str}


def evaluate_graham(info: dict, sector_t: dict, history_data: dict | None = None) -> list[dict]:
    """그레이엄 7기준 — 원전 'The Intelligent Investor' Defensive Investor 기준."""
    results = []
    per = safe_get(info, "trailingPE")
    per_max = min(15, sector_t["per_max"])
    if per is not None:
        results.append({"name": f"PER <= {per_max}", "passed": 0 < per <= per_max, "value": f"{per:.1f}"})
    else:
        results.append({"name": f"PER <= {per_max}", "passed": None, "value": "데이터 없음"})

    pbr = safe_get(info, "priceToBook")
    pbr_max = min(1.5, sector_t["pbr_max"])
    if pbr is not None:
        results.append({"name": f"PBR <= {pbr_max}", "passed": 0 < pbr <= pbr_max, "value": f"{pbr:.2f}"})
    else:
        results.append({"name": f"PBR <= {pbr_max}", "passed": None, "value": "데이터 없음"})

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

    # #5: 5년 연속 흑자
    if history_data and history_data.get("available"):
        ni_list = history_data.get("net_income") or []
        valid_ni = [v for v in ni_list if v is not None]
        if len(valid_ni) >= 3:
            positive_years = sum(1 for v in valid_ni if v > 0)
            results.append({
                "name": "수익 안정성 (5년 연속 흑자)",
                "passed": positive_years == len(valid_ni),
                "value": f"{positive_years}/{len(valid_ni)}년 흑자"
            })
        else:
            results.append({"name": "수익 안정성 (5년 연속 흑자)", "passed": None, "value": "데이터 부족"})
    else:
        results.append({"name": "수익 안정성 (5년 연속 흑자)", "passed": None, "value": "데이터 없음"})

    # #6: 배당 + 배당 수익률 1%+
    dy = safe_get(info, "dividendYield")
    if dy is not None:
        results.append({
            "name": "배당 1%+ (인플레 헤지)",
            "passed": dy >= 0.01,
            "value": f"{dy*100:.2f}%"
        })
    else:
        results.append({"name": "배당 1%+ (인플레 헤지)", "passed": None, "value": "데이터 없음"})

    # #7: 매출 성장 (인플레 이상)
    if history_data and history_data.get("revenue_cagr") is not None:
        cagr = history_data["revenue_cagr"]
        results.append({
            "name": "매출 CAGR >= 3% (장기 인플레 이상)",
            "passed": cagr >= 0.03,
            "value": f"{cagr*100:.1f}%/년"
        })
    else:
        results.append({"name": "매출 CAGR >= 3%", "passed": None, "value": "데이터 없음"})

    return results


def lynch_category(info: dict, history_data: dict | None = None) -> dict:
    """피터 린치 6 카테고리 자동 분류 — 'One Up On Wall Street' (1989).

    카테고리: SLOW_GROWER / STALWART / FAST_GROWER / CYCLICAL / TURNAROUND / ASSET_PLAY
    """
    rg = safe_get(info, "revenueGrowth")
    eg = safe_get(info, "earningsGrowth")
    sector = info.get("sector", "") or ""
    pbr = safe_get(info, "priceToBook")
    de = safe_get(info, "debtToEquity")

    cyclical_sectors = ("Consumer Cyclical", "Energy", "Basic Materials", "Industrials", "Financial Services")

    is_volatile = False
    if history_data and history_data.get("available"):
        ni = [v for v in (history_data.get("net_income") or []) if v is not None]
        if len(ni) >= 3:
            avg_ni = sum(ni) / len(ni)
            if avg_ni != 0:
                ni_cv = (sum((v - avg_ni)**2 for v in ni) / len(ni)) ** 0.5 / abs(avg_ni)
                is_volatile = ni_cv > 0.5

    if pbr is not None and 0 < pbr < 1.0:
        return {"code": "ASSET_PLAY", "label": "자산주 (Asset Play)",
                "desc": "장부가 미만 거래 — 숨은 자산가치 노림"}

    if de is not None and de > 200 and eg is not None and eg > 0.5:
        return {"code": "TURNAROUND", "label": "회생주 (Turnaround)",
                "desc": "고부채 + 급격한 이익 회복 — 위험·고수익"}

    if sector in cyclical_sectors and is_volatile:
        return {"code": "CYCLICAL", "label": "경기 순환주 (Cyclical)",
                "desc": "경기 사이클에 따라 매출·이익 큰 변동"}

    if rg is not None and rg > 0.20 and eg is not None and eg > 0.25:
        return {"code": "FAST_GROWER", "label": "고성장주 (Fast Grower)",
                "desc": "매출·이익 모두 20%+ 성장 — 텐베거 후보"}

    if rg is not None and 0.05 <= rg <= 0.20:
        return {"code": "STALWART", "label": "우량 안정주 (Stalwart)",
                "desc": "꾸준한 성장 + 큰 시가총액 — 30~50% 수익 노림"}

    if rg is not None and 0 <= rg < 0.05:
        return {"code": "SLOW_GROWER", "label": "저성장주 (Slow Grower)",
                "desc": "성숙기업 — 배당 위주, 자본 차익 기대 낮음"}

    return {"code": "UNCLASSIFIED", "label": "분류 불가",
            "desc": "데이터 부족으로 카테고리 판정 어려움"}


def evaluate_lynch(info: dict, sector_t: dict, history_data: dict | None = None) -> list[dict]:
    """피터 린치 5기준 — 'One Up On Wall Street' (1989)."""
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
        results.append({"name": "기관 보유 < 60% (아직 안 알려진 종목)", "passed": inst < 0.60, "value": f"{inst*100:.1f}%"})
    else:
        results.append({"name": "기관 보유 < 60%", "passed": None, "value": "데이터 없음"})

    return results


def evaluate_fisher(info: dict, sector_t: dict, history_data: dict | None = None) -> list[dict]:
    """필립 피셔 6기준 — 'Common Stocks and Uncommon Profits' (1958).

    원전 15-Point 중 정량 가능한 항목 + Scuttlebutt 정신 (애널리스트 컨센서스 무시).
    """
    results = []

    rg = safe_get(info, "revenueGrowth")
    if rg is not None:
        results.append({"name": "매출 성장률 > 10%", "passed": rg > 0.10, "value": f"{rg*100:.1f}%"})
    else:
        results.append({"name": "매출 성장률 > 10%", "passed": None, "value": "데이터 없음"})

    om = safe_get(info, "operatingMargins")
    if om is not None:
        results.append({"name": f"영업이익률 >= {sector_t['om_min']*100:.0f}% (섹터 기준)",
                        "passed": om >= sector_t['om_min'], "value": f"{om*100:.1f}%"})
    else:
        results.append({"name": "영업이익률 (섹터 기준)", "passed": None, "value": "데이터 없음"})

    gm = safe_get(info, "grossMargins")
    if gm is not None:
        results.append({"name": f"매출총이익률 >= {sector_t['gm_min']*100:.0f}% (R&D 여력)",
                        "passed": gm >= sector_t['gm_min'], "value": f"{gm*100:.1f}%"})
    else:
        results.append({"name": "매출총이익률 (섹터 기준)", "passed": None, "value": "데이터 없음"})

    pm = safe_get(info, "profitMargins")
    if pm is not None:
        results.append({"name": f"순이익률 >= {sector_t['pm_min']*100:.0f}% (섹터 기준)",
                        "passed": pm >= sector_t['pm_min'], "value": f"{pm*100:.1f}%"})
    else:
        results.append({"name": "순이익률 (섹터 기준)", "passed": None, "value": "데이터 없음"})

    if history_data and history_data.get("revenue_cagr") is not None:
        cagr = history_data["revenue_cagr"]
        results.append({
            "name": "매출 CAGR >= 7% (장기 성장)",
            "passed": cagr >= 0.07,
            "value": f"{cagr*100:.1f}%/년"
        })
    else:
        results.append({"name": "매출 CAGR >= 7% (장기 성장)", "passed": None, "value": "데이터 없음"})

    if history_data and history_data.get("eps_cagr") is not None:
        eps_cagr = history_data["eps_cagr"]
        results.append({
            "name": "EPS CAGR >= 10% (5년 복리)",
            "passed": eps_cagr >= 0.10,
            "value": f"{eps_cagr*100:.1f}%/년"
        })
    else:
        results.append({"name": "EPS CAGR >= 10% (5년 복리)", "passed": None, "value": "데이터 없음"})

    return results
