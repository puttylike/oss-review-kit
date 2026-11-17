# my-kit

캡스톤 트랙 C에서 만든 plugin입니다. 공개 GitHub 오픈소스를 DeepWiki MCP로 조사해 사내 도입 검토 리포트(oss-review)와 도입 기획안(proposal-draft)을 만듭니다. 조사 agent와 근거 검토 agent가 일을 나눠 맡고, 가드레일 훅이 deepwiki 외의 MCP 도구, 쓰기 성격 도구, 외부 호스트 호출을 막습니다.

## 들어 있는 것
- agents: evidence-reviewer mcp-researcher 
- skills: oss-review proposal-draft 
- 가드레일 훅: mcp-guard.sh net-guard.sh 

## 설치 (Claude 세션 안에서)
/plugin marketplace add ~/claude-lab/capstone/marketplace
/plugin install my-kit@capstone-local

## 사용 예
- 주제만 주고 후보 찾기: /my-kit:oss-review 프롬프트 자동 최적화 프레임워크
- 저장소를 정해서 검토: /my-kit:oss-review 프롬프트 자동 최적화 프레임워크 gepa-ai/gepa
- 리포트로 기획안 쓰기: /my-kit:proposal-draft reports/(리포트 파일) 사내 문서 추출 프롬프트 자동 최적화 도입 기획안

## 필요한 설정
- 키나 토큰은 필요 없습니다. DeepWiki는 인증 없는 공개 MCP 서버입니다. 이 저장소에는 키를 넣지 않습니다.
- 업무 폴더에 필요한 것: 없음. reports/와 proposals/ 폴더는 skill이 만듭니다.
- plugin에 넣을 수 없는 설정(권한 deny, MCP 허용 목록)은 업무 폴더의 .claude/settings.json 에 둡니다. MCP 허용 목록은 deepwiki(https://mcp.deepwiki.com/mcp), 호출 허용 호스트는 mcp.deepwiki.com 하나입니다.
- 버전: 0.1.0 (고치면 .claude-plugin/plugin.json 의 version 과 함께 올립니다)

## 한계
- DeepWiki 위키는 AI가 생성한 문서이고 생성 시점을 알 수 없습니다. 실제 코드와 다를 수 있어 리포트의 확인하지 못한 것 항목에 남깁니다.
- DeepWiki에는 저장소 검색이 없습니다. 주제만 주면 모델 지식과 대표 저장소 위키로 후보를 찾고, DeepWiki에 등록된 공개 저장소만 씁니다.
