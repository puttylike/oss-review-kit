#!/bin/bash
# 사용: mcp-guard.sh <허용할 MCP 서버 이름>...
INPUT=$(cat)
command -v jq >/dev/null || { echo "MCP: 검사기 오류(jq 없음) - 안전을 위해 차단" >&2; exit 2; }
[ $# -ge 1 ] || { echo "MCP: 허용할 서버 이름이 설정에 없음 - 차단" >&2; exit 2; }
TOOL=$(printf '%s' "$INPUT" | jq -er '.tool_name') || { echo "MCP: 입력 해석 실패 - 차단" >&2; exit 2; }

case "$TOOL" in mcp__*) ;; *) exit 0 ;; esac   # MCP 도구가 아니면 관여하지 않는다

for s in "$@"; do
  REST=${TOOL#"mcp__${s}__"}
  [ "$REST" != "$TOOL" ] || continue
  # 허용한 서버라도 쓰기 성격의 도구는 막는다 (도구 이름 기준 예시 패턴)
  if printf '%s' "$REST" | grep -Eiq '(^|_)(create|update|delete|remove|write|edit|move|push|merge|add)(_|$)'; then
    echo "MCP: 쓰기 성격 도구($TOOL)는 차단됩니다" >&2; exit 2
  fi
  exit 0
done
echo "MCP: 허용 목록 밖의 MCP 도구($TOOL). 허용 서버: $*" >&2
exit 2
