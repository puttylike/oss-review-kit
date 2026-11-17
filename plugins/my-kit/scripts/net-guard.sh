#!/bin/bash
# 사용: net-guard.sh <허용할 호스트>...   (인자가 없으면 URL이 든 호출을 모두 막는다. 예시, www.alphavantage.co)
INPUT=$(cat)
command -v jq >/dev/null || { echo "NET: 검사기 오류(jq 없음) - 안전을 위해 차단" >&2; exit 2; }
TEXT=$(printf '%s' "$INPUT" | jq -r '.tool_input | [.. | strings] | join("\n")') \
  || { echo "NET: 입력 해석 실패 - 차단" >&2; exit 2; }

ALLOW=" $* "
HOSTS=$(printf '%s\n' "$TEXT" | grep -oiE "https?://[^/[:space:]\"'<>]+" | sed -E 's#^[A-Za-z]+://##; s#^[^@]*@##; s#:[0-9]+$##' | tr 'A-Z' 'a-z' | sort -u)
for h in $HOSTS; do
  case "$ALLOW" in
    *" $h "*) ;;
    *) echo "NET: 허용되지 않은 호출 대상($h). 허용: ${*:-없음}" >&2; exit 2 ;;
  esac
done
exit 0
