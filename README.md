# oss-review-kit

검토 주제만 주면 공개 오픈소스 후보를 찾아 DeepWiki로 확인하고, 근거 검토를 거쳐 도입 검토 리포트와 도입 기획안까지 만드는 Claude Code 플러그인(my-kit)입니다. FSI Claude Code Deep Dive 워크숍(2026-11) 캡스톤 결과물입니다.

- 소개 페이지: https://puttylike.github.io/oss-review-kit/
- 웹에서 바로 실행: https://dpz3goi98d05t.cloudfront.net (워크숍 기간에만 열려 있습니다)

## 설치

Claude Code에서 실행합니다.

```
/plugin marketplace add puttylike/oss-review-kit
/plugin install my-kit@capstone-local
```

## 사용

```
/my-kit:oss-review 프롬프트 자동 최적화 프레임워크
/my-kit:proposal-draft 사내 문서 추출 프롬프트 자동 최적화 도입
```

- `oss-review`: 주제로 후보 저장소를 찾아 표로 보여 주고, 고른 저장소의 도입 검토 리포트를 `reports/`에 md와 html로 만듭니다. 저장소를 이미 정했다면 주제 뒤에 붙여도 됩니다.
- `proposal-draft`: 리포트를 근거로 기획안을 `proposals/`에 만듭니다. 리포트가 없으면 `oss-review`로 먼저 만듭니다.

## 폴더 구성

- `.claude-plugin/`: 마켓플레이스 정의(capstone-local)
- `plugins/my-kit/`: 플러그인 본체. agents(mcp-researcher, evidence-reviewer), skills(oss-review, proposal-draft), 가드레일 훅, DeepWiki MCP 설정. 자세한 설명은 [plugins/my-kit/README.md](plugins/my-kit/README.md)
- `docs/`: 소개 페이지(GitHub Pages)와 결과 예시
- `showcase/`: 웹 실행 버전 소스. `frontend`(페이지)와 `infra`(AWS CDK: S3, CloudFront, Lambda에서 Bedrock 호출)

## 가드레일

- 훅은 플러그인과 함께 설치되어 허용되지 않은 MCP 서버와 호출 대상을 막습니다.
- 웹 검색 차단(deny)과 MCP 허용 목록은 플러그인에 실리지 않으므로, 사용할 폴더의 `.claude/settings.json`에 따로 둡니다. 예시는 플러그인 README에 있습니다.

## 웹 실행 버전 직접 배포

us-east-1에서 Claude Sonnet 5.5 Bedrock 모델 접근 권한이 있는 계정이 필요합니다.

```
cd showcase/infra
npm ci
npx cdk bootstrap   # 계정·리전에서 처음 한 번
npx cdk deploy
```

## 한계

근거는 DeepWiki의 AI 생성 위키라 원 저장소와 다를 수 있습니다. 리포트에는 출처와 조회일을 남기고, 확인하지 못한 내용은 따로 적습니다.
