"""스크리너 데이터 빌더 — 인기 종목 메트릭 정적 JSON 생성.

사용법:
    python scripts/build_screener_data.py

출력: static/screener-data.json (5분 정도 소요, 네트워크 의존)

매주 1~2회 수동 실행 또는 GitHub Actions cron으로 자동화 가능.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta

# 루트 경로 추가 (data 모듈 임포트용)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.fetcher import fetch_stock_data

# ----- 종목 유니버스 -----
US_TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA", "AMD", "INTC", "NFLX",
    "JPM", "BAC", "V", "MA", "DIS", "KO", "PEP", "WMT", "COST", "HD",
    "NKE", "SBUX", "MCD", "PG", "JNJ", "UNH", "XOM", "CVX", "BA", "CAT",
    "GE", "T", "VZ", "CRM", "ORCL", "ADBE", "CSCO", "IBM", "QCOM", "TXN",
    "BRK-B", "BLK", "GS", "MS", "C", "WFC", "PYPL",
]

# 한국: 시가총액 상위 + 인지도 높은 종목
KR_TICKERS = [
    "005930.KS",  # 삼성전자
    "000660.KS",  # SK하이닉스
    "035420.KS",  # NAVER
    "035720.KS",  # 카카오
    "005380.KS",  # 현대차
    "000270.KS",  # 기아
    "207940.KS",  # 삼성바이오로직스
    "373220.KS",  # LG에너지솔루션
    "068270.KS",  # 셀트리온
    "051910.KS",  # LG화학
    "006400.KS",  # 삼성SDI
    "105560.KS",  # KB금융
    "055550.KS",  # 신한지주
    "086790.KS",  # 하나금융지주
    "017670.KS",  # SK텔레콤
    "030200.KS",  # KT
    "032830.KS",  # 삼성생명
    "003550.KS",  # LG
    "066570.KS",  # LG전자
    "012330.KS",  # 현대모비스
    "015760.KS",  # 한국전력
    "009150.KS",  # 삼성전기
    "010130.KS",  # 고려아연
    "024110.KS",  # 기업은행
    "316140.KS",  # 우리금융지주
    "377300.KS",  # 카카오페이
    "035900.KQ",  # JYP Ent.
    "041510.KQ",  # SM
    "112040.KQ",  # 위메이드
    "247540.KQ",  # 에코프로비엠
]


def safe_float(v, default=None):
    """안전한 float 변환."""
    try:
        if v is None:
            return default
        f = float(v)
        if f != f or f == float("inf") or f == -float("inf"):  # NaN/Inf 차단
            return default
        return f
    except (TypeError, ValueError):
        return default


def extract_metrics(ticker: str, data: dict) -> dict:
    """fetch_stock_data 결과에서 스크리너용 메트릭 추출."""
    info = data.get("info", {}) if data else {}
    is_kr = ".KS" in ticker or ".KQ" in ticker

    # 이름
    name = (
        info.get("longName")
        or info.get("shortName")
        or info.get("displayName")
        or ticker
    )

    # 기본 메트릭
    return {
        "ticker": ticker,
        "name": name,
        "country": "KR" if is_kr else "US",
        "sector": info.get("sector") or "—",
        "industry": info.get("industry") or "—",
        "price": safe_float(info.get("currentPrice") or info.get("regularMarketPrice")),
        "currency": info.get("currency") or ("KRW" if is_kr else "USD"),
        "marketCap": safe_float(info.get("marketCap")),
        # 밸류에이션
        "per": safe_float(info.get("trailingPE")),
        "pbr": safe_float(info.get("priceToBook")),
        "psr": safe_float(info.get("priceToSalesTrailing12Months")),
        # 수익성
        "roe": safe_float(info.get("returnOnEquity")),  # 0.20 = 20%
        "operatingMargin": safe_float(info.get("operatingMargins")),
        # 재무 건전성
        "debtToEquity": safe_float(info.get("debtToEquity")),  # 100 = 100%
        # 배당
        "dividendYield": safe_float(info.get("dividendYield")),  # 0.02 = 2%
        # 성장
        "earningsGrowth": safe_float(info.get("earningsGrowth")),
        "revenueGrowth": safe_float(info.get("revenueGrowth")),
        # 베타
        "beta": safe_float(info.get("beta")),
    }


def main():
    all_tickers = US_TICKERS + KR_TICKERS
    print(f"총 {len(all_tickers)}개 종목 처리 시작...")

    results = []
    failures = []
    start = time.time()

    for i, ticker in enumerate(all_tickers, 1):
        try:
            data = fetch_stock_data(ticker)
            if data is None:
                failures.append(ticker)
                print(f"  [{i}/{len(all_tickers)}] {ticker} — 실패 (데이터 없음)")
                continue
            metrics = extract_metrics(ticker, data)
            results.append(metrics)
            elapsed = time.time() - start
            avg = elapsed / i
            remaining = avg * (len(all_tickers) - i)
            print(f"  [{i}/{len(all_tickers)}] {ticker} — {metrics['name'][:30]} (남은 시간 ~{remaining:.0f}초)")
        except Exception as e:
            failures.append(ticker)
            print(f"  [{i}/{len(all_tickers)}] {ticker} — 예외: {e}")

        # 레이트 리밋 회피
        time.sleep(0.5)

    # 메타데이터
    kst = timezone(timedelta(hours=9))
    output = {
        "version": 1,
        "generated_at": datetime.now(kst).isoformat(),
        "generated_at_kst": datetime.now(kst).strftime("%Y-%m-%d %H:%M KST"),
        "count": len(results),
        "failures": failures,
        "stocks": results,
    }

    # 저장
    out_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "static",
        "screener-data.json",
    )
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✓ 완료: {len(results)}/{len(all_tickers)}개 저장")
    print(f"  파일: {out_path}")
    if failures:
        print(f"  실패: {failures}")
    print(f"  총 소요: {(time.time() - start):.1f}초")


if __name__ == "__main__":
    main()
