/**
 * StockInto 용어 사전 인라인 툴팁 데이터.
 * - key: 본문에 등장하는 용어 (대소문자/한영 구분)
 * - definition: 한 줄 설명 (50~120자 권장)
 * - more: /glossary 페이지에서 해시 점프 가능한 앵커 (선택)
 */
window.STOCKINTO_TERMS = {
  // 가치평가 지표
  "PER": {
    def: "주가수익비율 (P/E). 주가 ÷ 주당순이익(EPS). 회사가 1원 벌 때 시장이 몇 원 평가하는지. 낮을수록 저평가, 단 섹터별 적정 PER이 다름 (Tech ~30, 금융 ~12).",
    more: "per"
  },
  "P/E": { alias: "PER" },
  "PBR": {
    def: "주가순자산비율 (P/B). 주가 ÷ 주당순자산(BPS). 회사 청산가치 대비 시장가. 1 미만이면 청산가치보다 저평가. 자산집약 산업(은행·제조)에 적합.",
    more: "pbr"
  },
  "PEG": {
    def: "PER ÷ 연 이익성장률(%). 피터 린치가 애용. 1.0 미만이면 성장 대비 저평가, 0.5 미만이면 텐베거 후보. 성장주 평가 핵심.",
    more: "peg"
  },
  "EPS": {
    def: "주당순이익. 순이익 ÷ 발행주식수. PER·PEG 계산의 기반. 5년 EPS CAGR이 꾸준히 양수면 안정 성장 신호.",
    more: "eps"
  },
  "ROE": {
    def: "자기자본이익률. 순이익 ÷ 자기자본 × 100. 버핏이 가장 중시하는 지표. 15% 이상 꾸준히 유지하면 우량 기업, 20%+면 코카콜라급.",
    more: "roe"
  },
  "ROIC": {
    def: "투하자본이익률. 사업에 투입된 자본 대비 영업수익률. ROE보다 부채 효과를 배제해 본질적 수익성 측정. 15%+ 우수.",
    more: "roic"
  },
  "ROA": {
    def: "총자산이익률. 순이익 ÷ 총자산 × 100. 자산 효율성. 5%+ 양호, 제조업 기준.",
    more: "roa"
  },
  "FCF": {
    def: "잉여현금흐름 (Free Cash Flow). 영업활동현금흐름 - 자본적지출(CapEx). 회사가 실제 쓸 수 있는 현금. 양수가 지속되면 건강한 기업.",
    more: "fcf"
  },
  "DCF": {
    def: "현금흐름할인법. 미래 FCF를 현재가치로 환산해 적정주가 추정. 할인율 8%, 영구성장률 4% 가정. 안정적 기업에 적합.",
    more: "dcf"
  },
  "Graham": {
    def: "벤저민 그레이엄 공식. √(22.5 × EPS × BPS). 자산집약 가치주 적정주가 추정. 자본잠식 기업엔 무효.",
    more: "graham"
  },
  "P/S": {
    def: "주가매출비율. 주가 ÷ 주당매출. 적자 성장주(테슬라·NVAX 등) 평가에 사용. PER이 의미 없을 때 대안.",
    more: "ps"
  },

  // 수익성·재무건전성
  "영업이익률": {
    def: "영업이익 ÷ 매출 × 100. 본업 수익성. 10%+ 양호, 20%+ 우수. 섹터별 차이 큼 (소매 ~5%, 소프트웨어 ~30%).",
    more: "operating-margin"
  },
  "매출총이익률": {
    def: "Gross Margin. (매출 - 매출원가) ÷ 매출. 제품 자체 수익력. 40%+ 강력한 경제적 해자(moat) 신호.",
    more: "gross-margin"
  },
  "부채비율": {
    def: "총부채 ÷ 자기자본 × 100. 100% 이하면 보수적, 200%+ 위험. 단 금융업·유틸리티는 본질적으로 높음.",
    more: "debt-ratio"
  },
  "유동비율": {
    def: "유동자산 ÷ 유동부채. 1년 내 채무 상환 능력. 200%+ 그레이엄 기준, 150%+ 양호.",
    more: "current-ratio"
  },
  "안전마진": {
    def: "Margin of Safety. (적정주가 - 현재가) ÷ 적정주가. 그레이엄·버핏 핵심. 30%+ 확보 시 매수 고려.",
    more: "margin-of-safety"
  },

  // 성장·기술적
  "CAGR": {
    def: "연평균성장률. (말기 ÷ 초기)^(1/년수) - 1. 매출·EPS의 5년 CAGR로 성장 일관성 측정.",
    more: "cagr"
  },
  "RS": {
    def: "Relative Strength Rating. 같은 기간 시장 대비 주가 상승률 백분위. 80+ 선도주, 40 미만 부진주. 윌리엄 오닐 핵심 지표.",
    more: "rs-rating"
  },
  "RSI": {
    def: "상대강도지수. 14일 평균 상승폭 ÷ (상승+하락폭). 70+ 과매수, 30 이하 과매도. 단기 매매 보조.",
    more: "rsi"
  },
  "CAN SLIM": {
    def: "윌리엄 오닐의 7요소 종목 선정법. C(분기실적) A(연실적) N(신고가/신제품) S(수급) L(선도주) I(기관매집) M(시장방향).",
    more: "can-slim"
  },

  // 시장·심리
  "시가총액": {
    def: "주가 × 발행주식수. 회사 시장가치. 라지캡 $10B+, 미드캡 $2~10B, 스몰캡 $300M~2B 등 분류.",
    more: "market-cap"
  },
  "배당수익률": {
    def: "연간 주당배당금 ÷ 주가 × 100. 4%+ 고배당주. 단 배당성향 80%+면 지속가능성 점검 필요.",
    more: "dividend-yield"
  },
  "공포탐욕지수": {
    def: "Fear & Greed Index. 6개 시장지표 가중평균. 0~25 극단적 공포(역발상 매수 구간), 75~100 극단적 탐욕(과열).",
    more: "fear-greed"
  },
  "Max Pain": {
    def: "옵션 만기 시 콜+풋 매수자 손실 최대 지점. 시장 메이커가 이 가격으로 수렴시키려 한다는 가설.",
    more: "max-pain"
  },

  // 종목 카테고리
  "DISTRESSED": {
    def: "재무 위기 종목. 5년 중 4년 적자 + FCF 음수. 펀더멘털 평가 부정확, 애널리스트 목표가만 참고.",
    more: "distressed"
  },
  "BUYBACK_HEAVY": {
    def: "공격적 자사주매입 종목. 자기자본 잠식 위험. PBR/Graham 무효 → DCF·PER 위주 평가.",
    more: "buyback-heavy"
  },
  "STABLE": {
    def: "안정 흑자 종목. 3년 이상 흑자 + FCF 양수. 5가지 평가법(DCF/PER/Graham/애널/P/S) 모두 적용.",
    more: "stable"
  },
};

/**
 * 별칭 자동 해소: alias가 있으면 원본 키로 매핑.
 */
(function resolveAliases() {
  const T = window.STOCKINTO_TERMS;
  Object.keys(T).forEach(k => {
    if (T[k].alias && T[T[k].alias]) {
      T[k] = T[T[k].alias];
    }
  });
})();
