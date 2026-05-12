"""데이터 정확도 검증 — 우리 API vs 공식 자료 비교.

scripts/ 하위 실행: stockinto 루트에서 `python -m scripts.data_accuracy_check`
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import app
from data.cache import cache; cache.clear()
import json

CASES = [
    # (ticker, 공식 자료 참고치, 출처)
    ('AAPL', {
        'longName': 'Apple',
        '2024 revenue ($B)': 391,
        '2024 net income ($B)': 94,
        'trailing EPS ($)': 7.5,
        'ROE (%)': '150%+ (자사주매입 효과)',
        '출처': 'Apple 10-K (Oct 2024), SEC'
    }),
    ('005930.KS', {
        'longName': '삼성전자',
        '2024 revenue (조원)': 300,
        '2024 net income (조원)': 34,
        'ROE (%)': '약 9~10%',
        '출처': 'DART 사업보고서 2024'
    }),
    ('MSFT', {
        'longName': 'Microsoft',
        'FY2025 revenue ($B)': 282,
        'FY2025 net income ($B)': 102,
        'trailing EPS ($)': 13.5,
        '출처': 'MSFT 10-K (July 2025)'
    }),
    ('GOOGL', {
        'longName': 'Alphabet',
        '2024 revenue ($B)': 350,
        '2024 net income ($B)': 100,
        '출처': 'Alphabet 10-K 2024'
    }),
]

def fmt_num(v):
    if v is None: return 'None'
    if abs(v) >= 1e9: return f'{v/1e9:.2f}B'
    if abs(v) >= 1e6: return f'{v/1e6:.1f}M'
    if abs(v) >= 1e3: return f'{v/1e3:.1f}K'
    return f'{v:.2f}'

with app.test_client() as c:
    for ticker, expected in CASES:
        print('=' * 70)
        print(f'[{ticker}] 기대값:')
        for k, v in expected.items():
            print(f'  {k}: {v}')
        print()

        r = c.post('/api/analyze', json={'ticker': ticker})
        if r.status_code != 200:
            print(f'  API 실패: {r.status_code}')
            continue
        d = r.get_json()

        # 원본 info 가져오기 위해 yfinance 직접
        import yfinance as yf
        t = yf.Ticker(ticker)
        info = t.info

        print(f'>>> 우리 API / yfinance 원본:')
        print(f'  longName: {info.get("longName", "?")}')
        print(f'  currentPrice: {info.get("currentPrice") or info.get("regularMarketPrice")}')
        print(f'  marketCap: {fmt_num(info.get("marketCap"))}')
        print(f'  sector / industry: {info.get("sector")} / {info.get("industry")}')
        print()
        print(f'  trailingEps: {info.get("trailingEps")}')
        print(f'  forwardEps: {info.get("forwardEps")}')
        print(f'  trailingPE: {info.get("trailingPE")}')
        print(f'  forwardPE: {info.get("forwardPE")}')
        print()
        print(f'  returnOnEquity: {info.get("returnOnEquity")} (raw)')
        print(f'  debtToEquity: {info.get("debtToEquity")}')
        print(f'  operatingMargins: {info.get("operatingMargins")}')
        print(f'  profitMargins: {info.get("profitMargins")}')
        print(f'  revenueGrowth (YoY): {info.get("revenueGrowth")}')
        print(f'  earningsGrowth (YoY): {info.get("earningsGrowth")}')
        print()
        print(f'  freeCashflow: {fmt_num(info.get("freeCashflow"))}')
        print(f'  totalRevenue: {fmt_num(info.get("totalRevenue"))}')
        print(f'  totalCash: {fmt_num(info.get("totalCash"))}')
        print(f'  totalDebt: {fmt_num(info.get("totalDebt"))}')
        print()
        print(f'  targetMeanPrice: {info.get("targetMeanPrice")}')
        print(f'  numberOfAnalystOpinions: {info.get("numberOfAnalystOpinions")}')
        print()

        # 다년도 재무 (연간)
        print(f'  >>> 연간 재무제표 (최근 4년):')
        try:
            inc = t.income_stmt
            if inc is not None and not inc.empty:
                for col in inc.columns[:4]:
                    year = col.year if hasattr(col, 'year') else str(col)[:7]
                    rev = inc.loc['Total Revenue'].get(col) if 'Total Revenue' in inc.index else None
                    ni = inc.loc['Net Income'].get(col) if 'Net Income' in inc.index else None
                    print(f'    {year}: Revenue={fmt_num(rev)}, NetIncome={fmt_num(ni)}')
        except Exception as e:
            print(f'    재무제표 로드 실패: {e}')
        print()

        # 히스토리
        hist = d.get('history', {})
        if hist.get('available'):
            print(f'  >>> 우리 history 모듈 출력 (연도, EPS, ROE):')
            for i, yr in enumerate(hist.get('years', [])):
                eps = hist.get('eps', [])[i] if i < len(hist.get('eps', [])) else None
                roe = hist.get('roe', [])[i] if i < len(hist.get('roe', [])) else None
                rev = hist.get('revenue', [])[i] if i < len(hist.get('revenue', [])) else None
                print(f'    {yr}: EPS={eps}, ROE={roe}, Revenue={fmt_num(rev)}')
        print()
