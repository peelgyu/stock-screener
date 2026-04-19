"""종합 한 줄 판정 — 매수/관망/회피."""


def generate_verdict(overall: dict, rs_data: dict | None, market_data: dict | None,
                     fair_value: dict | None, quality: dict | None,
                     fear_greed: dict | None) -> dict:
    score = 0
    reasons = []
    warnings = []

    # 1) 투자자 기준 통과율
    rate = overall.get("rate", 0)
    if rate >= 60:
        score += 2
        reasons.append(f"투자자 기준 통과율 {rate}% ({overall.get('yes',0)}/{overall.get('total',0)})")
    elif rate >= 40:
        score += 1
    else:
        warnings.append(f"투자자 기준 통과율 낮음 ({rate}%)")

    # 2) RS
    if rs_data and rs_data.get("available"):
        rc = rs_data.get("rs_composite", 0) or 0
        if rc >= 80:
            score += 2
            reasons.append(f"RS Rating {rc} (선도주)")
        elif rc >= 60:
            score += 1
            reasons.append(f"RS Rating {rc} (시장 상회)")
        elif rc < 40:
            warnings.append(f"RS Rating {rc} (시장 대비 부진)")

    # 3) 시장 방향
    if market_data and market_data.get("available"):
        if market_data.get("passed_canslim_m"):
            score += 1
            reasons.append(f"시장 {market_data.get('benchmark_name','')} 상승장")
        elif "하락장" in (market_data.get("direction","") or ""):
            score -= 2
            warnings.append(f"시장 하락장 — 신규 매수 비권장")
        elif "조정" in (market_data.get("direction","") or ""):
            score -= 1
            warnings.append(f"시장 조정 중")

    # 4) 적정주가
    if fair_value and fair_value.get("available"):
        upside = fair_value.get("upside_pct", 0) or 0
        if upside >= 20:
            score += 2
            reasons.append(f"적정가 대비 {upside:+.0f}% 저평가")
        elif upside >= 10:
            score += 1
            reasons.append(f"적정가 대비 {upside:+.0f}%")
        elif upside <= -20:
            score -= 2
            warnings.append(f"적정가 대비 {upside:+.0f}% 고평가")
        elif upside <= -10:
            score -= 1
            warnings.append(f"적정가 대비 {upside:+.0f}% 고평가")

    # 5) 재무 품질
    if quality and quality.get("available"):
        qs = quality.get("quality_score", 50) or 50
        if qs >= 80:
            score += 1
            reasons.append(f"재무품질 양호 ({qs}/100)")
        elif qs <= 40:
            score -= 1
            warnings.append(f"재무품질 우려 ({qs}/100)")

    # 6) 공포/탐욕
    if fear_greed and fear_greed.get("score") is not None:
        fg = fear_greed["score"]
        if fg <= 25:
            score += 1
            reasons.append(f"극단적 공포 ({fg}) — 역발상 매수 기회")
        elif fg >= 80:
            score -= 1
            warnings.append(f"극단적 탐욕 ({fg}) — 단기 과열")

    # 판정
    if score >= 4:
        decision, color, confidence = "매수", "green", "high"
    elif score >= 2:
        decision, color, confidence = "관심 (선별 매수)", "green", "medium"
    elif score >= 0:
        decision, color, confidence = "관망", "yellow", "medium"
    elif score >= -2:
        decision, color, confidence = "회피 (리스크)", "red", "medium"
    else:
        decision, color, confidence = "회피", "red", "high"

    if not reasons:
        reasons = ["특이점 없음"]

    return {
        "decision": decision,
        "color": color,
        "score": score,
        "reasons": reasons[:4],
        "warnings": warnings[:4],
        "confidence": confidence,
    }
