"""Flask 라우트 통합 테스트 — 분석 깨짐 회귀 방지.

이전 사고: app.py 분리 시 get_stock_data 함수가 같이 잘려나갔는데,
호출부는 그대로 남아 NameError. 평가자 유닛테스트로는 못 잡음.
이 파일이 그 격차를 메운다 — 라우트를 실제 호출해서 import + 함수 정의 검증.

외부 호출(yfinance·DART)은 monkeypatch로 stub 처리 → 빠르고 결정론적.
"""
import os
import sys
import json
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture
def client(monkeypatch):
    """Flask test client + 외부 호출을 stub으로 대체."""
    # fetch_stock_data를 stub으로 — Yahoo 호출 X, 미국 종목 가짜 응답
    fake_info = {
        "currentPrice": 270.0,
        "regularMarketPrice": 270.0,
        "marketCap": 3_500_000_000_000,
        "sector": "Technology",
        "industry": "Consumer Electronics",
        "longName": "Apple Inc.",
        "currency": "USD",
        "trailingPE": 28.0,
        "forwardPE": 24.0,
        "trailingEps": 6.5,
        "forwardEps": 7.5,
        "priceToBook": 5.0,
        "bookValue": 5.4,
        "currentRatio": 1.5,
        "pegRatio": 1.5,
        "returnOnEquity": 0.30,
        "debtToEquity": 60,
        "operatingMargins": 0.30,
        "grossMargins": 0.45,
        "profitMargins": 0.25,
        "revenueGrowth": 0.15,
        "earningsGrowth": 0.18,
        "freeCashflow": 100_000_000_000,
        "totalRevenue": 400_000_000_000,
        "sharesOutstanding": 14_700_000_000,
        "totalDebt": 1.1e11,
        "interestExpense": 4e9,
        "beta": 1.2,
        "dividendYield": 0.005,
        "heldPercentInstitutions": 0.65,
        "targetMeanPrice": 300,
        "numberOfAnalystOpinions": 40,
    }

    class FakeStock:
        ticker = "AAPL"
        info = fake_info
        income_stmt = None
        cashflow = None
        balance_sheet = None
        quarterly_income_stmt = None

    def fake_fetch(ticker):
        return {"source": "yfinance", "info": dict(fake_info), "stock": FakeStock(), "hist": None}

    import data.fetcher as fetcher
    monkeypatch.setattr(fetcher, "fetch_stock_data", fake_fetch)

    import app as app_module
    # cache 우회 — get_stock_data가 캐시되니 stub 적용 위해 캐시 비움
    from data.cache import cache as _cache
    _cache.clear() if hasattr(_cache, "clear") else None
    # app.py에 import된 fetch_stock_data 심볼도 패치
    monkeypatch.setattr(app_module, "fetch_stock_data", fake_fetch)

    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def _post(client, path, body):
    return client.post(
        path,
        data=json.dumps(body),
        content_type="application/json",
        headers={"Origin": "https://stockinto.com"},
    )


# ────────────────── 진짜 회귀 방지 테스트 ──────────────────

def test_api_analyze_does_not_raise_nameerror_on_get_stock_data(client):
    """이전 사고 재발 방지 — get_stock_data 같은 핵심 함수 누락 시 즉시 빨간불."""
    res = _post(client, "/api/analyze", {"ticker": "AAPL"})
    # 500 에러여도 NameError가 아닌 다른 이유여야 함 (Yahoo·DART는 stub됨)
    if res.status_code == 500:
        body = res.get_data(as_text=True)
        assert "NameError" not in body, f"NameError 발생 — 분리 회귀!\n{body}"
        assert "is not defined" not in body, f"이름 미정의 — 분리 회귀!\n{body}"


def test_api_analyze_returns_2xx_with_stub(client):
    """stub fetch가 들어가면 분석 라우트는 무조건 200 OK 반환해야."""
    res = _post(client, "/api/analyze", {"ticker": "AAPL"})
    body = res.get_data(as_text=True)
    assert res.status_code == 200, f"분석 라우트 실패: HTTP {res.status_code}\n{body[:500]}"


def test_api_analyze_response_has_required_keys(client):
    """분석 응답에 프론트가 의존하는 핵심 필드 모두 있어야."""
    res = _post(client, "/api/analyze", {"ticker": "AAPL"})
    assert res.status_code == 200
    data = res.get_json()
    required = ["stock", "ticker", "investors", "overall", "fairValue", "history"]
    missing = [k for k in required if k not in data]
    assert not missing, f"응답에 누락된 키: {missing}"


def test_api_analyze_investors_has_5_evaluators(client):
    """5인 평가자 모두 응답에 들어와야 — 병렬화 회귀 방지."""
    res = _post(client, "/api/analyze", {"ticker": "AAPL"})
    assert res.status_code == 200
    investors = res.get_json().get("investors", [])
    names = {inv.get("name") for inv in investors}
    assert "워렌 버핏" in names
    assert "벤저민 그레이엄" in names
    assert "피터 린치" in names
    assert "윌리엄 오닐" in names
    assert "필립 피셔" in names


def test_api_search_returns_results(client):
    """검색 라우트도 깨지면 안 됨."""
    res = client.get("/api/search?q=apple", headers={"Origin": "https://stockinto.com"})
    assert res.status_code == 200


def test_api_cache_stats_alive(client):
    """헬스체크 — 앱 자체 살아있는지."""
    res = client.get("/api/cache/stats")
    assert res.status_code == 200
    assert "hits" in res.get_json()


def test_api_analyze_rejects_invalid_query(client):
    """입력 검증 — XSS/SSRF 차단 회귀 방지."""
    res = _post(client, "/api/analyze", {"ticker": "<script>"})
    assert res.status_code in (400, 403, 404)


def test_api_analyze_handles_empty_ticker(client):
    """빈 ticker — 400 응답 + 명확한 에러 메시지."""
    res = _post(client, "/api/analyze", {"ticker": ""})
    assert res.status_code == 400
