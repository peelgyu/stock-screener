#!/bin/bash
# stock-screener 레포로 자동 동기화 (Railway 배포 트리거)
#
# 배경:
#   - 개발 레포: peelgyu/peelgyu-inventory (이 레포, 모든 코드)
#   - 배포 레포: peelgyu/stock-screener (Railway가 감시 중)
#   - 한글 경로(주식/stockinto) 때문에 git subtree push 사용 불가
#   - → clone + 복사 + push 방식
#
# 사용:
#   bash 주식/stockinto/sync_to_deploy.sh "커밋 메시지"
#
# 자동 실행 조건:
#   주식/stockinto/ 하위에서 push 후 항상 호출
#
set -e

MEMO="${1:-sync from peelgyu-inventory}"
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
TMP_DIR="/tmp/stock-screener-sync-$$"
DEPLOY_REPO="https://github.com/peelgyu/stock-screener.git"

# 원본 레포의 git 정체 그대로 사용 (전역 fallback 포함)
GIT_EMAIL="$(git -C "$SRC_DIR" config user.email 2>/dev/null || true)"
GIT_NAME="$(git -C "$SRC_DIR" config user.name 2>/dev/null || true)"
if [ -z "$GIT_EMAIL" ] || [ -z "$GIT_NAME" ]; then
  echo "❌ git user.email / user.name 미설정 — 'git config --global user.email/name' 먼저 설정해 주세요" >&2
  exit 1
fi

echo "==> 1/4 stock-screener 클론"
git clone --depth=1 "$DEPLOY_REPO" "$TMP_DIR" 2>&1 | tail -2

echo "==> 2/4 기존 콘텐츠 청소 (.git 제외)"
cd "$TMP_DIR"
ls | xargs -I {} rm -rf {} 2>/dev/null || true

echo "==> 3/4 stockinto 콘텐츠 복사 (백업·캐시·.env 제외)"
cp -a "$SRC_DIR/." "$TMP_DIR/"
rm -rf "$TMP_DIR/백업" "$TMP_DIR/.pytest_cache" "$TMP_DIR/.env" 2>/dev/null || true
find "$TMP_DIR" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find "$TMP_DIR" -name "*.pyc" -delete 2>/dev/null || true

echo "==> 4/4 commit + push"
cd "$TMP_DIR"
git config user.email "$GIT_EMAIL"
git config user.name "$GIT_NAME"
git add -A

if git diff --cached --quiet; then
  echo "변경 없음 — push 스킵"
else
  git commit -m "🔄 sync: $MEMO

자동 동기화 — peelgyu-inventory/주식/stockinto/ → stock-screener
Railway 배포 트리거용. CLAUDE.md 규칙대로 실행됨.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
  git push origin master
  echo "✅ 완료 — Railway가 1~2분 안에 재배포 시작"
fi

# 청소
cd /tmp
rm -rf "$TMP_DIR"
