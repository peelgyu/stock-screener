"""
유명 투자자 기준 주식 스크리너
- 워렌 버핏, 벤저민 그레이엄, 피터 린치, 윌리엄 오닐, 필립 피셔 기준으로 종목 평가
- 티커 또는 종목명 입력 시 각 기준별 YES/NO 판정
"""

import yfinance as yf
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
import sys
import io

# Windows cp949 인코딩 문제 해결
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

console = Console(force_terminal=True)


def get_stock_data(ticker: str) -> dict | None:
    """yfinance로 주식 데이터 수집"""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info

        if not info or info.get("regularMarketPrice") is None:
            return None

        # 재무제표 가져오기
        financials = stock.financials
        balance = stock.balance_sheet
        cashflow = stock.cashflow

        # 분기 실적
        quarterly_financials = stock.quarterly_financials
        quarterly_earnings = stock.quarterly_earnings

        data = {
            "info": info,
            "financials": financials,
            "balance": balance,
            "cashflow": cashflow,
            "quarterly_financials": quarterly_financials,
            "quarterly_earnings": quarterly_earnings,
            "stock": stock,
        }
        return data
    except Exception as e:
        console.print(f"[red]데이터 수집 오류: {e}[/red]")
        return None


def safe_get(info: dict, key: str, default=None):
    """info에서 안전하게 값 가져오기 (None, 0 처리)"""
    val = info.get(key, default)
    return val if val is not None else default


# ──────────────────────────────────────────────
# 워렌 버핏 기준
# ──────────────────────────────────────────────
def evaluate_buffett(data: dict) -> list[tuple[str, bool | None, str]]:
    info = data["info"]
    results = []

    # 1) ROE >= 15%
    roe = safe_get(info, "returnOnEquity")
    if roe is not None:
        passed = roe >= 0.15
        results.append(("ROE >= 15%", passed, f"{roe*100:.1f}%"))
    else:
        results.append(("ROE >= 15%", None, "데이터 없음"))

    # 2) 부채비율 (Debt/Equity) <= 0.5
    debt_equity = safe_get(info, "debtToEquity")
    if debt_equity is not None:
        passed = debt_equity <= 50  # yfinance는 %로 제공
        results.append(("부채비율 <= 50%", passed, f"{debt_equity:.1f}%"))
    else:
        results.append(("부채비율 <= 50%", None, "데이터 없음"))

    # 3) 영업이익률 >= 15%
    op_margin = safe_get(info, "operatingMargins")
    if op_margin is not None:
        passed = op_margin >= 0.15
        results.append(("영업이익률 >= 15%", passed, f"{op_margin*100:.1f}%"))
    else:
        results.append(("영업이익률 >= 15%", None, "데이터 없음"))

    # 4) 5년 매출 성장률 > 0 (꾸준한 성장)
    rev_growth = safe_get(info, "revenueGrowth")
    if rev_growth is not None:
        passed = rev_growth > 0
        results.append(("매출 성장 중", passed, f"{rev_growth*100:.1f}%"))
    else:
        results.append(("매출 성장 중", None, "데이터 없음"))

    # 5) FCF > 0 (잉여현금흐름 양수)
    fcf = safe_get(info, "freeCashflow")
    if fcf is not None:
        passed = fcf > 0
        fcf_b = fcf / 1e9
        results.append(("FCF 양수", passed, f"${fcf_b:.2f}B"))
    else:
        results.append(("FCF 양수", None, "데이터 없음"))

    return results


# ──────────────────────────────────────────────
# 벤저민 그레이엄 기준
# ──────────────────────────────────────────────
def evaluate_graham(data: dict) -> list[tuple[str, bool | None, str]]:
    info = data["info"]
    results = []

    # 1) PER <= 15
    per = safe_get(info, "trailingPE")
    if per is not None:
        passed = 0 < per <= 15
        results.append(("PER <= 15", passed, f"{per:.1f}"))
    else:
        results.append(("PER <= 15", None, "데이터 없음"))

    # 2) PBR <= 1.5
    pbr = safe_get(info, "priceToBook")
    if pbr is not None:
        passed = 0 < pbr <= 1.5
        results.append(("PBR <= 1.5", passed, f"{pbr:.2f}"))
    else:
        results.append(("PBR <= 1.5", None, "데이터 없음"))

    # 3) PER x PBR < 22.5
    if per is not None and pbr is not None and per > 0 and pbr > 0:
        product = per * pbr
        passed = product < 22.5
        results.append(("PER × PBR < 22.5", passed, f"{product:.1f}"))
    else:
        results.append(("PER × PBR < 22.5", None, "데이터 없음"))

    # 4) 유동비율 >= 200%
    current_ratio = safe_get(info, "currentRatio")
    if current_ratio is not None:
        passed = current_ratio >= 2.0
        results.append(("유동비율 >= 200%", passed, f"{current_ratio*100:.0f}%"))
    else:
        results.append(("유동비율 >= 200%", None, "데이터 없음"))

    # 5) 배당 지급 여부
    div_yield = safe_get(info, "dividendYield")
    if div_yield is not None:
        passed = div_yield > 0
        results.append(("배당 지급", passed, f"{div_yield*100:.2f}%"))
    else:
        results.append(("배당 지급", None, "데이터 없음"))

    return results


# ──────────────────────────────────────────────
# 피터 린치 기준
# ──────────────────────────────────────────────
def evaluate_lynch(data: dict) -> list[tuple[str, bool | None, str]]:
    info = data["info"]
    results = []

    # 1) PEG < 1
    peg = safe_get(info, "pegRatio")
    if peg is not None:
        passed = 0 < peg < 1
        results.append(("PEG < 1", passed, f"{peg:.2f}"))
    else:
        results.append(("PEG < 1", None, "데이터 없음"))

    # 2) 매출 성장률 > 10%
    rev_growth = safe_get(info, "revenueGrowth")
    if rev_growth is not None:
        passed = rev_growth > 0.10
        results.append(("매출 성장률 > 10%", passed, f"{rev_growth*100:.1f}%"))
    else:
        results.append(("매출 성장률 > 10%", None, "데이터 없음"))

    # 3) EPS 성장률 > 15%
    earnings_growth = safe_get(info, "earningsGrowth")
    if earnings_growth is not None:
        passed = earnings_growth > 0.15
        results.append(("EPS 성장률 > 15%", passed, f"{earnings_growth*100:.1f}%"))
    else:
        results.append(("EPS 성장률 > 15%", None, "데이터 없음"))

    # 4) 부채비율 낮음 (Debt/Equity <= 80%)
    debt_equity = safe_get(info, "debtToEquity")
    if debt_equity is not None:
        passed = debt_equity <= 80
        results.append(("부채비율 <= 80%", passed, f"{debt_equity:.1f}%"))
    else:
        results.append(("부채비율 <= 80%", None, "데이터 없음"))

    # 5) 기관 보유 비율 < 60% (아직 덜 주목받는 종목)
    inst = safe_get(info, "heldPercentInstitutions")
    if inst is not None:
        passed = inst < 0.60
        results.append(("기관 보유 < 60%", passed, f"{inst*100:.1f}%"))
    else:
        results.append(("기관 보유 < 60%", None, "데이터 없음"))

    return results


# ──────────────────────────────────────────────
# 윌리엄 오닐 CAN SLIM 기준
# ──────────────────────────────────────────────
def evaluate_oneil(data: dict) -> list[tuple[str, bool | None, str]]:
    info = data["info"]
    results = []

    # C - 최근 분기 EPS 성장 >= 25%
    earnings_growth = safe_get(info, "earningsQuarterlyGrowth")
    if earnings_growth is not None:
        passed = earnings_growth >= 0.25
        results.append(("C: 분기 EPS 성장 >= 25%", passed, f"{earnings_growth*100:.1f}%"))
    else:
        results.append(("C: 분기 EPS 성장 >= 25%", None, "데이터 없음"))

    # A - 연간 EPS 성장
    annual_growth = safe_get(info, "earningsGrowth")
    if annual_growth is not None:
        passed = annual_growth > 0
        results.append(("A: 연간 EPS 성장 중", passed, f"{annual_growth*100:.1f}%"))
    else:
        results.append(("A: 연간 EPS 성장 중", None, "데이터 없음"))

    # N - 52주 신고가 근처 (현재가가 52주 고가의 90% 이상)
    price = safe_get(info, "currentPrice") or safe_get(info, "regularMarketPrice")
    high52 = safe_get(info, "fiftyTwoWeekHigh")
    if price is not None and high52 is not None and high52 > 0:
        ratio = price / high52
        passed = ratio >= 0.90
        results.append(("N: 52주 고가 근처(90%+)", passed, f"{ratio*100:.1f}%"))
    else:
        results.append(("N: 52주 고가 근처(90%+)", None, "데이터 없음"))

    # S - 거래량 증가 (평균 거래량 대비)
    avg_vol = safe_get(info, "averageVolume")
    vol = safe_get(info, "volume")
    if avg_vol is not None and vol is not None and avg_vol > 0:
        vol_ratio = vol / avg_vol
        passed = vol_ratio >= 1.0
        results.append(("S: 거래량 >= 평균", passed, f"{vol_ratio:.2f}x"))
    else:
        results.append(("S: 거래량 >= 평균", None, "데이터 없음"))

    # L - 업종 선도주 (ROE 상위)
    roe = safe_get(info, "returnOnEquity")
    if roe is not None:
        passed = roe >= 0.17
        results.append(("L: ROE >= 17% (선도주)", passed, f"{roe*100:.1f}%"))
    else:
        results.append(("L: ROE >= 17% (선도주)", None, "데이터 없음"))

    # I - 기관 매수 증가
    inst = safe_get(info, "heldPercentInstitutions")
    if inst is not None:
        passed = inst >= 0.20
        results.append(("I: 기관 보유 >= 20%", passed, f"{inst*100:.1f}%"))
    else:
        results.append(("I: 기관 보유 >= 20%", None, "데이터 없음"))

    return results


# ──────────────────────────────────────────────
# 필립 피셔 기준
# ──────────────────────────────────────────────
def evaluate_fisher(data: dict) -> list[tuple[str, bool | None, str]]:
    info = data["info"]
    results = []

    # 1) 매출 성장률 > 10%
    rev_growth = safe_get(info, "revenueGrowth")
    if rev_growth is not None:
        passed = rev_growth > 0.10
        results.append(("매출 성장률 > 10%", passed, f"{rev_growth*100:.1f}%"))
    else:
        results.append(("매출 성장률 > 10%", None, "데이터 없음"))

    # 2) 영업이익률 업계 평균 이상 (>= 15%)
    op_margin = safe_get(info, "operatingMargins")
    if op_margin is not None:
        passed = op_margin >= 0.15
        results.append(("영업이익률 >= 15%", passed, f"{op_margin*100:.1f}%"))
    else:
        results.append(("영업이익률 >= 15%", None, "데이터 없음"))

    # 3) R&D 투자 (매출 대비 R&D 비율 추정 - grossMargins으로 대체)
    gross_margin = safe_get(info, "grossMargins")
    if gross_margin is not None:
        passed = gross_margin >= 0.40  # 높은 매출총이익률 = R&D 투자 여력
        results.append(("매출총이익률 >= 40% (R&D 여력)", passed, f"{gross_margin*100:.1f}%"))
    else:
        results.append(("매출총이익률 >= 40% (R&D 여력)", None, "데이터 없음"))

    # 4) 순이익률 > 10%
    profit_margin = safe_get(info, "profitMargins")
    if profit_margin is not None:
        passed = profit_margin > 0.10
        results.append(("순이익률 > 10%", passed, f"{profit_margin*100:.1f}%"))
    else:
        results.append(("순이익률 > 10%", None, "데이터 없음"))

    # 5) 장기 성장 전망 (애널리스트 목표가 > 현재가)
    price = safe_get(info, "currentPrice") or safe_get(info, "regularMarketPrice")
    target = safe_get(info, "targetMeanPrice")
    if price is not None and target is not None and price > 0:
        upside = (target - price) / price
        passed = upside > 0.10
        results.append(("애널리스트 목표가 10%+ 상승여력", passed, f"{upside*100:.1f}%"))
    else:
        results.append(("애널리스트 목표가 10%+ 상승여력", None, "데이터 없음"))

    return results


# ──────────────────────────────────────────────
# 종합 평가 출력
# ──────────────────────────────────────────────
def format_result(passed: bool | None) -> str:
    if passed is True:
        return "[bold green]YES[/bold green]"
    elif passed is False:
        return "[bold red]NO[/bold red]"
    else:
        return "[dim]N/A[/dim]"


def print_investor_table(title: str, emoji: str, results: list[tuple[str, bool | None, str]]):
    table = Table(title=f"{emoji} {title}", show_header=True, header_style="bold cyan", expand=True)
    table.add_column("기준", style="white", ratio=3)
    table.add_column("판정", justify="center", ratio=1)
    table.add_column("실제 값", justify="right", ratio=2)

    yes_count = 0
    total = len(results)

    for criterion, passed, value in results:
        table.add_row(criterion, format_result(passed), value)
        if passed is True:
            yes_count += 1

    console.print(table)

    # 통과율
    if total > 0:
        rate = yes_count / total * 100
        if rate >= 80:
            color = "green"
        elif rate >= 50:
            color = "yellow"
        else:
            color = "red"
        console.print(f"  통과: [{color}]{yes_count}/{total} ({rate:.0f}%)[/{color}]\n")


def print_stock_info(data: dict):
    info = data["info"]
    name = safe_get(info, "longName", "N/A")
    sector = safe_get(info, "sector", "N/A")
    industry = safe_get(info, "industry", "N/A")
    price = safe_get(info, "currentPrice") or safe_get(info, "regularMarketPrice", 0)
    market_cap = safe_get(info, "marketCap", 0)
    currency = safe_get(info, "currency", "USD")

    cap_str = f"${market_cap/1e9:.1f}B" if market_cap >= 1e9 else f"${market_cap/1e6:.0f}M"

    console.print()
    console.print(Panel(
        f"[bold white]{name}[/bold white]\n"
        f"섹터: {sector} | 산업: {industry}\n"
        f"현재가: {currency} {price:,.2f} | 시가총액: {cap_str}",
        title="[bold cyan]종목 정보[/bold cyan]",
        border_style="cyan"
    ))
    console.print()


def run_screener(ticker: str):
    console.print(f"\n[bold cyan]'{ticker}' 데이터 수집 중...[/bold cyan]")

    data = get_stock_data(ticker)
    if data is None:
        console.print(f"[bold red]'{ticker}' 종목을 찾을 수 없습니다. 티커를 확인해주세요.[/bold red]")
        return

    print_stock_info(data)

    # 각 투자자 기준 평가
    investors = [
        ("워렌 버핏 (가치투자)", "🏛️", evaluate_buffett),
        ("벤저민 그레이엄 (안전마진)", "📊", evaluate_graham),
        ("피터 린치 (성장주)", "🚀", evaluate_lynch),
        ("윌리엄 오닐 (CAN SLIM)", "📈", evaluate_oneil),
        ("필립 피셔 (장기성장)", "🔬", evaluate_fisher),
    ]

    total_yes = 0
    total_criteria = 0

    for name, emoji, eval_func in investors:
        results = eval_func(data)
        print_investor_table(name, emoji, results)
        for _, passed, _ in results:
            if passed is not None:
                total_criteria += 1
                if passed:
                    total_yes += 1

    # 종합 점수
    if total_criteria > 0:
        overall = total_yes / total_criteria * 100
        if overall >= 70:
            grade = "[bold green]A (매우 우수)[/bold green]"
        elif overall >= 55:
            grade = "[bold green]B (우수)[/bold green]"
        elif overall >= 40:
            grade = "[bold yellow]C (보통)[/bold yellow]"
        elif overall >= 25:
            grade = "[bold red]D (미흡)[/bold red]"
        else:
            grade = "[bold red]F (부적합)[/bold red]"

        console.print(Panel(
            f"총 통과: [bold]{total_yes}/{total_criteria}[/bold] ({overall:.0f}%)\n"
            f"종합 등급: {grade}",
            title="[bold cyan]종합 평가[/bold cyan]",
            border_style="bright_magenta"
        ))
    console.print()


def main():
    console.print(Panel(
        "[bold white]유명 투자자 기준 주식 스크리너[/bold white]\n"
        "워렌 버핏 | 벤저민 그레이엄 | 피터 린치 | 윌리엄 오닐 | 필립 피셔\n\n"
        "[dim]티커(예: AAPL, MSFT, TSLA) 입력 | 'q' 입력 시 종료[/dim]",
        border_style="bright_cyan"
    ))

    while True:
        console.print()
        ticker = console.input("[bold cyan]종목 티커 입력 > [/bold cyan]").strip().upper()

        if ticker in ("Q", "QUIT", "EXIT", ""):
            console.print("[dim]프로그램을 종료합니다.[/dim]")
            break

        run_screener(ticker)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        for t in sys.argv[1:]:
            run_screener(t.upper())
    else:
        main()
