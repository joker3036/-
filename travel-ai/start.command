#!/bin/bash
# Mac에서 더블클릭하면 대시보드가 열려요. 처음 한 번은 필요한 패키지를 설치하느라 1~2분 걸려요.
# 데모로 보고 싶으면 터미널에서: DEMO=1 ./start.command
cd "$(dirname "$0")" || exit 1

PY=""
for cand in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
    PY="$cand"
    break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.10 이상이 필요해요. https://www.python.org/downloads/ 에서 설치한 뒤 다시 실행하세요."
  read -r -p "엔터를 누르면 닫혀요..."
  exit 1
fi

if [ ! -d .venv ]; then
  echo "처음 실행: 가상환경을 만들고 패키지를 설치해요..."
  "$PY" -m venv .venv || exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate
if [ ! -f .venv/.installed ] || [ requirements.txt -nt .venv/.installed ]; then
  pip install --upgrade pip >/dev/null
  pip install -r requirements.txt && touch .venv/.installed
fi

if ! command -v claude >/dev/null 2>&1; then
  echo "참고: 'claude' 명령이 없어서 AI 분석은 아직 못 해요. README의 'Claude Code 설치' 단계를 따라 주세요."
fi

exec streamlit run app.py
