"""DART 공시 데이터 매핑 정확성 회귀 테스트.

DART_API_KEY 환경변수가 있을 때만 실행. CI에서는 자동 스킵.
삼성전자·SK하이닉스 등 알려진 공시값과 비교해 매핑 정확성 검증.

수동 실행:
  cd 주식/stockinto && pytest tests/test_dart_mapping.py -v -s
"""
import os
import pytest


# DART_API_KEY 없으면 모듈 전체 스킵
pytestmark = pytest.mark.skipif(
    not os.getenv("DART_API_KEY"),
    reason="DART_API_KEY 환경변수 없음 — 통합 테스트 스킵",
)


@pytest.fixture(scope="module")
def dart():
    from data import dart_client
    if not dart_client.is_available():
        pytest.skip("DART 클라이언트 사용 불가")
    return dart_client


# ────────── 알려진 공시값 (DART 직접 조회 검증된 값) ──────────
# 출처: 금융감독원 전자공시시스템 사업보고서 (2024 결산)
# 주의: 이 값은 공시 시점 기준. 정정공시·분할 등으로 변경 가능 → 변경 시 알림.

KNOWN_VALUES = {
    "005930.KS": {  # 삼성전자
        "name_includes": "삼성",
        "year": 2024,
        # 2024 매출 약 300조, 순이익 약 34조 (검증된 자료)
        "revenue_min": 280_000_000_000_000,  # 280조 이상
        "revenue_max": 320_000_000_000_000,  # 320조 이하
        "net_income_min": 25_000_000_000_000,  # 25조 이상
        "net_income_max": 45_000_000_000_000,  # 45조 이하
    },
    "000660.KS": {  # SK하이닉스
        "name_includes": "SK",
        "year": 2024,
        "revenue_min": 50_000_000_000_000,    # 50조 이상
        "revenue_max": 90_000_000_000_000,    # 90조 이하
    },
}


@pytest.mark.parametrize("ticker, expected", KNOWN_VALUES.items())
def test_dart_revenue_matches_disclosure(dart, ticker, expected):
    """DART에서 가져온 매출이 공시 범위 안에 들어와야."""
    fin = dart.fetch_financials(None, ticker, years=5)
    assert fin is not None, f"{ticker}: DART fetch 실패"
    years = fin.get("years")
    assert years, f"{ticker}: years 비어있음"

    target_year = str(expected["year"])
    if target_year not in years:
        pytest.skip(f"{ticker}: {target_year} 데이터 없음 (years={years})")

    idx = years.index(target_year)
    revenue = (fin.get("revenue") or [None] * len(years))[idx]
    assert revenue is not None, f"{ticker} {target_year}: revenue None"
    assert expected["revenue_min"] <= revenue <= expected["revenue_max"], (
        f"{ticker} {target_year} 매출 {revenue/1e12:.1f}조 — "
        f"공시 범위 [{expected['revenue_min']/1e12:.0f}조, {expected['revenue_max']/1e12:.0f}조] 밖. "
        f"매핑 회귀 또는 공시 정정 의심"
    )


@pytest.mark.parametrize("ticker, expected", [(k, v) for k, v in KNOWN_VALUES.items() if "net_income_min" in v])
def test_dart_net_income_matches_disclosure(dart, ticker, expected):
    """DART에서 가져온 순이익이 공시 범위 안에 들어와야."""
    fin = dart.fetch_financials(None, ticker, years=5)
    assert fin is not None
    years = fin.get("years")
    target_year = str(expected["year"])
    if target_year not in years:
        pytest.skip(f"{ticker}: {target_year} 미존재")
    idx = years.index(target_year)
    ni = (fin.get("net_income") or [None] * len(years))[idx]
    assert ni is not None
    assert expected["net_income_min"] <= ni <= expected["net_income_max"], (
        f"{ticker} {target_year} 순이익 {ni/1e12:.1f}조 — "
        f"공시 범위 [{expected['net_income_min']/1e12:.0f}조, {expected['net_income_max']/1e12:.0f}조] 밖"
    )


def test_dart_corp_map_loaded(dart):
    """기업코드 맵이 로드되고 주요 종목이 들어있어야."""
    m = dart._load_corp_map()
    assert isinstance(m, dict)
    assert len(m) > 1000, f"corp_map 사이즈 비정상 ({len(m)})"
    assert "005930" in m, "삼성전자 매핑 누락"
    assert "000660" in m, "SK하이닉스 매핑 누락"


def test_dart_us_ticker_returns_none(dart):
    """미국 티커는 DART에서 None 반환 (한국 종목만 처리)."""
    fin = dart.fetch_financials(None, "AAPL", years=5)
    assert fin is None or fin.get("years") in (None, []), \
        "미국 티커가 한국 DART에서 데이터를 받으면 안 됨"
