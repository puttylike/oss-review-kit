# oss-review-kit

검토 주제만 주면 공개 오픈소스 후보를 찾아 DeepWiki로 확인하고, 근거 검토를 거쳐 도입 검토 리포트와 도입 기획안까지 만드는 Claude Code 플러그인(my-kit)입니다. FSI Claude Code Deep Dive 워크숍(2026-11) 캡스톤 결과물입니다.

- 소개 페이지: https://puttylike.github.io/oss-review-kit/
- 웹에서 바로 실행: https://dpz3goi98d05t.cloudfront.net (워크숍 기간에만 열려 있습니다. 닫힌 뒤에는 [테스트 증적](#웹-실행-버전-테스트-증적-2026-11-18)으로 동작을 확인할 수 있습니다)

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
- `showcase/`: 웹 실행 버전 소스. `frontend`(페이지)와 `infra`(AWS CDK: S3, CloudFront, Lambda에서 Bedrock 호출), `evidence`(웹 실행 버전 테스트 캡처와 영상)

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

## 웹 실행 버전 테스트 증적 (2026-11-18)

CloudFront 웹 실행 버전이 닫히기 전에 화면의 모든 기능을 액션 단위로 눌러 보고 캡처했습니다. 캡처와 영상은 [`showcase/evidence/2026-11-18/`](showcase/evidence/2026-11-18/)에 있습니다.

| 항목 | 내용 |
|---|---|
| 대상 | https://dpz3goi98d05t.cloudfront.net |
| 일시 | 2026-11-18 01:19~01:27 (KST) |
| 브라우저 | Claude 데스크톱 앱 내장 브라우저 (Chromium 156, Windows), PC 가로 화면 1024×640 |
| 범위 | 4개 영역, 36개 액션 |

### 실행 결과

| 실행 | 입력 | 결과 | 걸린 시간 |
|---|---|---|---|
| 후보 찾기 | 주제 `k8s 기반 사내 GPU LLM 서빙 엔진`, 저장소 비움 | 후보 5개: llm-d/llm-d, kserve/kserve, vllm-project/vllm, sgl-project/sglang, InftyAI/llmaz | 34초 (01:20:52 → 01:21:26) |
| 리포트 | 후보 중 `vllm-project/vllm` 선택 | 1차 근거 검토 WARN, 도입 권고는 조건부 | 1분 32초 (01:21:52 → 01:23:24) |
| 같은 저장소 다시 실행 | `vllm-project/vllm` | 같은 jobId를 재사용(`reused: true`)해 바로 완료 | 즉시 |
| 빈 주제로 실행 | 주제 비움 | 필수 입력 안내가 뜨고 요청은 나가지 않음 | - |

### 영상

전체 36개 액션을 순서대로 이은 영상입니다. ([MP4로 보기](showcase/evidence/2026-11-18/walkthrough.mp4))

![테스트 전체 흐름](showcase/evidence/2026-11-18/walkthrough.gif)

<details>
<summary>웹에서 바로 실행만 짧게 보기 (후보 찾기 → 리포트 → 재사용)</summary>

![웹 실행 흐름](showcase/evidence/2026-11-18/web-run.gif)

</details>

### 액션별 캡처

<details>
<summary><b>A. 페이지 둘러보기</b> (5개)</summary>

**A-01** 첫 화면: 히어로와 터미널 데모가 열림

![A-01](showcase/evidence/2026-11-18/screens/a-01-landing.jpg)

**A-02** 터미널 데모가 워크숍 실행 로그(capstone-try)를 끝까지 재생

![A-02](showcase/evidence/2026-11-18/screens/a-02-terminal-demo.jpg)

**A-03** '다시 보기' 클릭 → 데모를 처음부터 다시 재생

![A-03](showcase/evidence/2026-11-18/screens/a-03-terminal-replay.jpg)

**A-04** 메뉴 '동작 방식' → 5단계 흐름 섹션으로 이동

![A-04](showcase/evidence/2026-11-18/screens/a-04-nav-how-it-works.jpg)

**A-05** 히어로 '결과 예시 보기' → 결과 섹션으로 이동

![A-05](showcase/evidence/2026-11-18/screens/a-05-hero-results-button.jpg)

</details>

<details>
<summary><b>B. 명령 만들기</b> (4개)</summary>

**B-06** 메뉴 '명령 만들기': 기본 주제로 oss-review 명령 표시

![B-06](showcase/evidence/2026-11-18/screens/b-06-builder-default.jpg)

**B-07** 'GPU LLM 서빙' 칩 클릭 → 주제와 명령이 함께 바뀜

![B-07](showcase/evidence/2026-11-18/screens/b-07-builder-chip.jpg)

**B-08** 저장소 입력(vllm-project/vllm) → 명령 끝에 저장소가 붙음

![B-08](showcase/evidence/2026-11-18/screens/b-08-builder-repo.jpg)

**B-09** 기획안 주제 입력 → proposal-draft 명령이 추가로 나타남

![B-09](showcase/evidence/2026-11-18/screens/b-09-builder-proposal.jpg)

</details>

<details>
<summary><b>C. 웹에서 바로 실행</b> (18개)</summary>

**C-10** 메뉴 '바로 실행': 위에서 넣은 주제와 저장소가 실행 폼에 채워짐

![C-10](showcase/evidence/2026-11-18/screens/c-10-run-prefilled.jpg)

**C-11** 주제를 비우고 실행 → 필수 입력 안내가 뜨고 요청은 나가지 않음

![C-11](showcase/evidence/2026-11-18/screens/c-11-run-validation.jpg)

**C-12** 저장소를 비워 후보 찾기 모드로 실행 준비

![C-12](showcase/evidence/2026-11-18/screens/c-12-discover-ready.jpg)

**C-13** 실행 → 후보 찾기 단계 표시 시작(접수)

![C-13](showcase/evidence/2026-11-18/screens/c-13-discover-started.jpg)

**C-14** 지식 후보 고르기 완료, 허브 탐색 진행 중

![C-14](showcase/evidence/2026-11-18/screens/c-14-discover-progress.jpg)

**C-15** 후보 찾기 완료(34초): 후보 5개

![C-15](showcase/evidence/2026-11-18/screens/c-15-discover-done.jpg)

**C-16** DeepWiki에서 확인된 후보 5개와 찾은 경로

![C-16](showcase/evidence/2026-11-18/screens/c-16-candidates.jpg)

**C-17** vllm-project/vllm 선택 → 리포트 실행 시작

![C-17](showcase/evidence/2026-11-18/screens/c-17-candidate-select.jpg)

**C-18** 리포트 진행: 위키 목차와 질의

![C-18](showcase/evidence/2026-11-18/screens/c-18-report-wiki.jpg)

**C-19** 리포트 진행: 조사 초안 작성

![C-19](showcase/evidence/2026-11-18/screens/c-19-report-draft.jpg)

**C-20** 리포트 진행: 근거 검토

![C-20](showcase/evidence/2026-11-18/screens/c-20-report-review.jpg)

**C-21** 리포트 완료(1분 32초): 2026-11-18 생성

![C-21](showcase/evidence/2026-11-18/screens/c-21-report-done.jpg)

**C-22** 결과 리포트: WARN 배지와 요약(조건부 권고)

![C-22](showcase/evidence/2026-11-18/screens/c-22-result-top.jpg)

**C-23** 핵심 표: 항목별 내용과 출처(DeepWiki, 조회일)

![C-23](showcase/evidence/2026-11-18/screens/c-23-result-table.jpg)

**C-24** 리포트 끝: 확인하지 못한 것과 검토 결과(WARN 사유)

![C-24](showcase/evidence/2026-11-18/screens/c-24-result-end.jpg)

**C-25** '근거 검토 내역 보기' 펼침 → 주장별 판정 표

![C-25](showcase/evidence/2026-11-18/screens/c-25-evidence-review.jpg)

**C-26** '마크다운 복사' 클릭 → 리포트 원문(5,226자)이 클립보드 API로 전달됨

![C-26](showcase/evidence/2026-11-18/screens/c-26-md-copy.jpg)

**C-27** 같은 저장소 재실행 → 당일 결과 재사용(reused: true), 즉시 완료

![C-27](showcase/evidence/2026-11-18/screens/c-27-same-repo-reused.jpg)

</details>

<details>
<summary><b>D. 결과 예시와 설치</b> (9개)</summary>

**D-28** 메뉴 '결과 예시': 워크숍 실행 결과 2건(리포트, 기획안)

![D-28](showcase/evidence/2026-11-18/screens/d-28-results.jpg)

**D-29** 리포트 링크와 주제만 넣었을 때 찾은 후보

![D-29](showcase/evidence/2026-11-18/screens/d-29-results-links.jpg)

**D-30** '웹 리포트 열기' → examples/gepa-report.html

![D-30](showcase/evidence/2026-11-18/screens/d-30-example-web-report.jpg)

**D-31** 'md 원본' → GitHub의 gepa-report.md

![D-31](showcase/evidence/2026-11-18/screens/d-31-example-md.jpg)

**D-32** '기획안 읽기' → GitHub의 기획안 md

![D-32](showcase/evidence/2026-11-18/screens/d-32-example-proposal.jpg)

**D-33** 메뉴 '설치': 플러그인 설치 두 줄과 구성 요소

![D-33](showcase/evidence/2026-11-18/screens/d-33-install.jpg)

**D-34** 업무 폴더 .claude/settings.json 예시

![D-34](showcase/evidence/2026-11-18/screens/d-34-install-settings.jpg)

**D-35** 가드레일(막는 것, 알아둘 한계)과 푸터

![D-35](showcase/evidence/2026-11-18/screens/d-35-guardrails.jpg)

**D-36** GitHub 버튼 → 저장소 페이지

![D-36](showcase/evidence/2026-11-18/screens/d-36-github-link.jpg)

</details>

### 참고

- 복사 버튼(명령 만들기의 `복사`, 결과 리포트의 `마크다운 복사`)은 테스트 브라우저가 클립보드 쓰기 권한을 막아 `복사됨` 표시까지는 확인하지 못했습니다. 대신 페이지가 올바른 문자열(명령, 리포트 원문 5,226자)을 `navigator.clipboard.writeText`로 넘기는 것까지 확인했습니다. 권한이 있는 브라우저에서는 코드상 `복사됨`이 1.4초 표시됩니다.
- 후보 찾기와 리포트 모두 페이지 안내(1~3분, 5~10분)보다 빨리 끝났습니다.
- 캡처는 1024×640 화면을 800px 폭으로 줄여 저장했습니다.

## 한계

근거는 DeepWiki의 AI 생성 위키라 원 저장소와 다를 수 있습니다. 리포트에는 출처와 조회일을 남기고, 확인하지 못한 내용은 따로 적습니다.
