# Stock Screener - 유명 투자자 기준 주식 분석기

## 기능

| 기능 | 설명 |
|------|------|
| 투자자 기준 분석 | 버핏, 그레이엄, 린치, 오닐, 피셔 기준 YES/NO 판정 |
| 공포/탐욕 지수 | RSI, 이평선, 변동성 등 종목별 0~100 점수 |
| 숏/롱 포지션 | 공매도 비율, 커버일수, 기관/내부자 보유 |
| 옵션 체인 분석 | Put/Call 비율, Max Pain, 가격대별 미결제약정 |
| 종목명 검색 | "애플", "삼성전자" 등 한국어/영어 이름으로 검색 |
| 자동완성 | 입력 시 관련 종목 드롭다운 |
| 한국 주식 | 코스피/코스닥 주요 종목 지원 |

## 파일 구조

```
STOCK SCREENER/
├── app.py                      # Flask 웹앱 백엔드 (메인)
├── kr_stocks.py                # 한국 주식 매핑 DB
├── templates/
│   └── index.html              # 웹앱 프론트엔드 (UI)
├── requirements.txt            # Python 의존성
├── render.yaml                 # Render.com 배포 설정
├── stock_screener_terminal.py  # 터미널 버전 (CLI)
└── README.md                   # 이 파일
```

## 실행 방법

### 웹앱 (로컬)
```bash
pip install flask yfinance numpy
python app.py
# 브라우저에서 http://localhost:5000 접속
```

### 터미널 버전
```bash
pip install yfinance rich
python stock_screener_terminal.py AAPL
```

## 배포

- GitHub: https://github.com/peelgyu/stock-screener
- Render.com에서 위 레포 연결 → 자동 배포
- git push 시 자동 재배포 (Auto-Deploy)
