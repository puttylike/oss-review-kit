# 프롬프트 자동 최적화 프레임워크 도입 검토: gepa-ai/gepa (2026-11-17)

## 1. 요약
- **조건부**: 프롬프트·코드 등 텍스트를 LLM 반성과 파레토 선택으로 최적화하며 DSPy와는 같은 엔진으로 연동되지만(FAQ 설명 기준), 평가자(evaluator) 코드 격리와 키 관리 기능이 확인되지 않아 통제 조건이 필요합니다.
- 연동은 `dspy.GEPA`, LiteLLM 기반 LLM 호출로 단순하고, README 기준 어댑터(DSPy, RAG, MCP, LangChain 등)가 다양합니다.
- 도입 시 예산 상한(max_metric_calls, max_reflection_cost), run_dir, seed 설정이 필요하고, evaluator 피드백(info)이 외부 LLM에 그대로 전달되므로 info에 민감정보를 넣지 않는 사내 규칙이 전제입니다.

## 2. 핵심 표
| 항목 | 내용 | 직전 리포트 대비 | 출처 |
|---|---|---|---|
| 주제 적합성 | 프롬프트, 코드, 설정, 정책, 에이전트 구조 등 평가 가능한 텍스트를 최적화합니다. 후보를 미니배치로 평가해 trace를 모으고, LLM이 피드백을 반성해 변이를 제안하며 필요하면 병합합니다. 프롬프트 자동 최적화 주제에 직접 부합합니다. | 첫 리포트 | DeepWiki(AI 생성 위키) gepa-ai/gepa "Overview", "Glossary", 조회일 2026-11-17 |
| 목적과 범위 | `optimize`: seed 후보(컴포넌트명→텍스트), 데이터셋, GEPAAdapter를 받는 시스템 통합용 핵심 API. `optimize_anything`: evaluator 기반 선언적 API로 엔진을 고를 수 있고(GEPA는 그중 하나) 단일 텍스트 후보도 받습니다. | 첫 리포트 | DeepWiki(AI 생성 위키) 3.1, 3.2, 조회일 2026-11-17 |
| 주요 구조 | 루프: 파레토 프런티어에서 후보 선택 → 미니배치 평가 → 반성 변이 → 평가 후 풀·프런티어 갱신 → 시스템 인지 병합. 프런티어는 입력·목표별로 강점이 다른 후보를 보존합니다. GEPAAdapter(evaluate, make_reflective_dataset)가 대상 시스템과의 경계이며 GEPAEngine이 어댑터를 보유합니다. | 첫 리포트 | DeepWiki(AI 생성 위키) 4.1, 4.4, 4.8, 5.1, 조회일 2026-11-17 |
| 연동 방식 | `dspy.GEPA`(metric, reflection LM 지정 후 compile)로 DSPy와 연동하며, FAQ는 dspy.GEPA가 같은 엔진을 감싼다고 설명합니다. 어댑터(README 목록): DefaultAdapter, ConfidenceAdapter, DSPy Full Program, Generic RAG, MCP, TerminalBench, AnyMaths, LangChain. 문자열 모델 지정 시 LLM 호출 기본값은 LiteLLM(선택 의존성)이며 callable로 다른 클라이언트도 쓸 수 있습니다. | 첫 리포트 | DeepWiki(AI 생성 위키) README, FAQ, 조회일 2026-11-17 |
| 인증과 보안 기능 | 자격증명은 LiteLLM 제공자 환경변수나 커스텀 LM callable을 씁니다. 사전 점검(preflight)은 있으나 키 보관소·마스킹은 확인되지 않았습니다. evaluator 피드백(info)은 제안용 LLM에 그대로 노출됩니다(이에 대한 문서 경고 문구는 확인 못함). 샌드박스(`OptimizeAnythingConfig.sandbox` 기본 True, 리눅스 bubblewrap·없으면 실행 중단, macOS Seatbelt)는 Claude 서브프로세스에만 적용되고 호스트 네트워크를 공유합니다. evaluator 코드나 GEPA 프로세스 전체는 격리되지 않습니다. | 첫 리포트 | DeepWiki(AI 생성 위키) 3.8, 8.12, 조회일 2026-11-17 |
| 버전 전환 현황 | pyproject.toml 기준 패키지 버전 0.1.4로 1.0 이전 단계입니다. 릴리스는 v* 태그 기반 워크플로로 PyPI에 게시합니다. 핵심 API `optimize()`와 설정 모델 기반 `optimize_anything()`이 공존하며 엔진을 플러그인으로 고를 수 있습니다. 변경이 일어난 버전은 확인되지 않았습니다. | 첫 리포트 | DeepWiki(AI 생성 위키) 9.5, 3.8, 10.1, 조회일 2026-11-17 |
| 운영 시 고려사항 | 비용: 종료 조건이 최소 하나 필요합니다(max_metric_calls, max_reflection_cost). `optimize_anything`의 max_evals 기본값 100은 선택 집합이 크면 낮을 수 있다고 문서가 경고하며, 선택 집합 크기의 약 15~20배를 권장합니다. 로깅: 사용자 로거, W&B, MLflow 동시 사용 가능. 재현성: seed 기본값 0, run_dir 상태 저장·자동 재개, gepa.stop 파일로 정상 종료(외부 모델 결과의 동일성은 보장 안 됨). 병렬: EngineConfig의 parallel 기본값은 True이며, `optimize()` 진입점의 병렬 기본값은 위키 설명이 상충해 확인하지 못했습니다. | 첫 리포트 | DeepWiki(AI 생성 위키) 3.5, 4.2, 8.1, 조회일 2026-11-17 |

## 3. 눈에 띄는 변화와 이유
- **두 API 체계**: 평면 키워드 API `gepa.optimize()`와 함께, 타입이 있는 설정 모델(OptimizeAnythingConfig)로 엔진·예산·run_dir을 관리하는 `optimize_anything()`이 있습니다. 위키는 후자를 확장된 진입점으로 설명하지만 도입 시점(날짜, 버전)은 주지 않습니다. engine_config 처리 방식은 엔진마다 다릅니다. gepa 엔진은 GEPAConfig(**engine_config)로 받아 알 수 없는 키에서 TypeError를 내고, 다른 엔진은 인식한 키만 쓰고 나머지는 경고합니다.
- **엔진 플러그인화**: `OptimizeAnythingConfig.engine`으로 gepa, autoresearch, meta_harness 중 엔진을 고릅니다. 위키가 든 이유는 어떤 옵티마이저도 모든 과제에서 우월하지 않아 과제별로 강점이 다르고, 한 옵티마이저가 정체해도 다른 옵티마이저가 진전할 수 있다는 점입니다. 과제와 evaluator를 그대로 둔 채 엔진을 비교하거나 조합할 수 있습니다. autoresearch는 Claude Code 세션을 서브프로세스로 사용합니다.
- **버전 경계**: 위 변경이 어느 버전에서 일어났는지는 위키로 확인되지 않았습니다.
- 출처: DeepWiki(AI 생성 위키) 3.8, 10.1, 조회일 2026-11-17

## 4. 확인하지 못한 것
- 위키의 생성·갱신 시점과 기준 커밋
- 유지보수 활동(커밋 빈도, 이슈 대응, 릴리스 주기)
- 보안 취약점 이력(CVE, 보안 공지)
- 릴리스별 버전 이력, CHANGELOG, 폐기·마이그레이션 노트 유무, API 변경과 버전 번호의 대응
- 라이선스: pyproject.toml 기준 MIT라는 위키 답변만 있으며 원 저장소로 교차 확인하지 못했고, 의존성 라이선스는 확인하지 못함
- 설치 방식(PyPI `pip install gepa`)과 extras(`gepa[confidence]`, `gepa[langchain]`): 조사 답변 1건에만 나오며 재검토에서 대조하지 못함
- `optimize()` 진입점의 병렬 기본값(위키 설명 상충)
- autoresearch 등 Claude 기반 엔진의 인증 요구사항
- evaluator info 취급에 대한 공식 문서의 경고 여부
- LLM에 전송되는 프롬프트 전체 구성, LLM 제공자의 데이터 보관·학습 정책
- `execute_code` 유틸리티의 실제 격리 수준과 OptimizeAnythingAdapter의 자동 사용 여부
- 위키 8.9 Cost Tracking, 8.10 ComBEE, 8.11 Parallel Proposals, 7.6 Production Use Cases, 11 Comparison with Other Methods 본문
- DeepWiki는 AI 생성 자료이므로 도입 결정 전에 소스 코드와 공식 문서로 교차 검증이 필요합니다

## 5. 검토 결과
**WARN**: 1차 FAIL 지적(근거 없는 문서 경고 문구, 병렬 기본값 불일치 등)은 모두 고쳤고 불일치는 없으나, preflight 존재, v* 태그 릴리스 워크플로, 로깅·gepa.stop·run_dir 자동 재개는 조사 답변에만 근거하고 재검토에서 다시 대조하지 못했습니다.
