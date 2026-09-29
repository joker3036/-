#!/bin/bash
# 여행 유튜브 벤치마킹 대시보드 한 번에 설치 (Mac)
#
#   curl -fsSL https://raw.githubusercontent.com/joker3036/-/refs/heads/claude/travel-youtube-ai-content-z73yyg/travel-ai/install.sh | bash
#
# 하는 일: 코드 받기 → Python 준비(uv, 관리자 권한 불필요) → 패키지 설치 → Claude Code 설치·로그인 확인
#          → YouTube API 키 저장 → 바탕화면 실행 아이콘 → 대시보드 열기
# 다시 실행하면 코드만 최신으로 바꾸고, 모은 데이터(data/)와 키(.env)는 그대로 둬요.
set -euo pipefail

BRANCH="${TRAVEL_AI_BRANCH:-claude/travel-youtube-ai-content-z73yyg}"
ZIP_URL="https://github.com/joker3036/-/archive/refs/heads/${BRANCH}.zip"
DEST="${TRAVEL_AI_HOME:-$HOME/travel-ai}"
KEY_PAGE="https://console.cloud.google.com/apis/library/youtube.googleapis.com"

step() { printf '\n\033[1m[%s/6] %s\033[0m\n' "$1" "$2"; }
info() { printf '  %s\n' "$*"; }
ask() {  # 파이프로 실행돼도 키보드 입력을 받도록 /dev/tty에서 읽음
  local answer=""
  if [ -r /dev/tty ]; then IFS= read -r "$@" answer < /dev/tty || answer=""; fi
  printf '%s' "$answer"
}
open_url() { command -v open >/dev/null 2>&1 && open "$1" >/dev/null 2>&1 || true; }

# 1. 코드 받기 -----------------------------------------------------------------
step 1 "코드 내려받는 중 → $DEST"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
curl -fsSL "$ZIP_URL" -o "$tmp/src.zip"
unzip -q "$tmp/src.zip" -d "$tmp/src"
src="$(find "$tmp/src" -maxdepth 2 -type d -name travel-ai | head -n 1)"
if [ -z "$src" ]; then echo "내려받은 파일에서 travel-ai 폴더를 찾지 못했어요."; exit 1; fi
mkdir -p "$DEST"
(cd "$src" && tar cf - .) | (cd "$DEST" && tar xf -)   # data/, .env, .venv 는 건드리지 않음
cd "$DEST"
info "완료"

# 2. Python (uv가 관리자 권한 없이 Python 3.12를 따로 설치) ------------------------
step 2 "Python과 패키지 준비 중 (처음엔 1~3분)"
UV="$(command -v uv || true)"
for cand in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
  [ -z "$UV" ] && [ -x "$cand" ] && UV="$cand"
done
if [ -z "$UV" ]; then
  curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
  for cand in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
    [ -z "$UV" ] && [ -x "$cand" ] && UV="$cand"
  done
fi
if [ -z "$UV" ]; then echo "uv 설치에 실패했어요. 인터넷 연결을 확인하고 다시 실행해 주세요."; exit 1; fi
[ -x .venv/bin/python ] || "$UV" venv --quiet --seed --python 3.12 .venv
"$UV" pip install --quiet --python .venv/bin/python -r requirements.txt
touch .venv/.installed
info "완료"

# 3. Claude Code -------------------------------------------------------------
step 3 "Claude Code 확인 중 (AI 분석용)"
CLAUDE="$(command -v claude || true)"
[ -z "$CLAUDE" ] && [ -x "$HOME/.local/bin/claude" ] && CLAUDE="$HOME/.local/bin/claude"
if [ -z "$CLAUDE" ]; then
  info "Claude Code를 설치해요..."
  curl -fsSL https://claude.ai/install.sh | bash
  CLAUDE="$HOME/.local/bin/claude"
fi
if "$CLAUDE" auth status --json 2>/dev/null | grep -q '"loggedIn": *true'; then
  info "로그인되어 있어요."
elif [ -r /dev/tty ]; then
  info "브라우저가 열리면 Claude 계정(Pro/Max 구독)으로 로그인해 주세요."
  "$CLAUDE" auth login --claudeai < /dev/tty || info "로그인을 건너뛰었어요. 나중에 터미널에서 'claude auth login'을 실행하세요."
else
  info "나중에 터미널에서 'claude auth login'을 실행해 로그인하세요."
fi

# 4. YouTube API 키 ------------------------------------------------------------
step 4 "YouTube API 키"
if [ -f .env ] && grep -q '^YOUTUBE_API_KEY=.' .env; then
  info "저장된 키가 있어요. 바꾸려면 대시보드의 설정 페이지에서 바꾸세요."
else
  info "브라우저에서 Google Cloud Console을 열게요. (처음이면 프로젝트를 만들고)"
  info "'YouTube Data API v3' 사용 → 사용자 인증 정보 → API 키 만들기 → 키 복사"
  open_url "$KEY_PAGE"
  printf '  키를 붙여넣고 엔터 (화면에 안 보여요, 나중에 하려면 그냥 엔터): '
  KEY="$(ask -s)"
  echo
  if [ -n "$KEY" ]; then
    if curl -fsS "https://www.googleapis.com/youtube/v3/channels?part=id&id=UC_x5XG1OV2P6uZZ5FSM9Ttw&key=${KEY}" 2>/dev/null | grep -q '"items"'; then
      info "키 확인 완료"
    else
      info "키 확인에 실패했어요 (API 사용 설정이 막 켜졌다면 몇 분 뒤 괜찮아져요). 일단 저장할게요."
    fi
    umask 077
    printf 'YOUTUBE_API_KEY=%s\n' "$KEY" > .env
  else
    info "건너뛰었어요. 대시보드의 설정 페이지에서 넣을 수 있어요."
  fi
fi

# 5. 바탕화면 실행 아이콘 (이 PC에서 만든 파일이라 더블클릭해도 막히지 않음) ----------
step 5 "바탕화면에 실행 아이콘 만들기"
if [ -d "$HOME/Desktop" ]; then
  launcher="$HOME/Desktop/여행 벤치마킹.command"
  printf '#!/bin/bash\ncd "%s" && exec bash start.command\n' "$DEST" > "$launcher"
  chmod +x "$launcher"
  info "바탕화면의 '여행 벤치마킹'을 더블클릭하면 다음부터 바로 열려요."
else
  info "바탕화면 폴더가 없어서 건너뛰었어요. 다음부터는: cd \"$DEST\" && bash start.command"
fi

# 6. 실행 ---------------------------------------------------------------------
step 6 "대시보드 여는 중 (끝낼 때는 이 창에서 Control + C)"
if [ "${TRAVEL_AI_NO_LAUNCH:-0}" = "1" ]; then
  info "설치만 하고 끝냈어요."
  exit 0
fi
if [ -r /dev/tty ]; then exec bash start.command < /dev/tty; else exec bash start.command; fi
