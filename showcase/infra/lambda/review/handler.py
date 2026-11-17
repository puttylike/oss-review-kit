"""oss-review 웹 실행 Lambda.

하나의 함수가 두 경로로 호출됩니다.
- Function URL(CloudFront /api/*): POST /api/review, GET /api/review/{id}
- S3 이벤트(jobs/{id}/request.json 생성): 조사 -> 초안 -> 근거 검토 파이프라인 실행

지시문은 배포 때 my-kit에서 복사해 온 prompts/ 아래 파일을 그대로 읽습니다.
"""
import base64
import datetime
import json
import os
import re
import time
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

BUCKET = os.environ.get("DATA_BUCKET", "")
MODEL_ID = os.environ.get("MODEL_ID", "")
DAILY_LIMIT = int(os.environ.get("DAILY_LIMIT", "20"))
DEEPWIKI_URL = "https://mcp.deepwiki.com/mcp"
KST = datetime.timezone(datetime.timedelta(hours=9))
PROMPT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")

REPO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
REVIEW_PLACEHOLDER = "{{REVIEW_RESULT}}"
MAX_SOURCE_CHARS = 24000

_s3 = None
_bedrock = None


def s3():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3")
    return _s3


def bedrock():
    global _bedrock
    if _bedrock is None:
        _bedrock = boto3.client(
            "bedrock-runtime",
            config=Config(read_timeout=600, retries={"max_attempts": 4, "mode": "adaptive"}),
        )
    return _bedrock


# ---------------------------------------------------------------- 지시문

def _strip_frontmatter(text):
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4:].lstrip("\n")
    return text


def load_prompt(rel):
    with open(os.path.join(PROMPT_DIR, rel), encoding="utf-8") as f:
        return _strip_frontmatter(f.read())


# ---------------------------------------------------------------- S3 도우미

def _code(err):
    return err.response.get("Error", {}).get("Code", "")


def get_json(key):
    """(dict, etag) 또는 없으면 (None, None)."""
    try:
        obj = s3().get_object(Bucket=BUCKET, Key=key)
    except ClientError as e:
        if _code(e) in ("NoSuchKey", "404"):
            return None, None
        raise
    return json.loads(obj["Body"].read()), obj["ETag"]


def get_text(key):
    try:
        return s3().get_object(Bucket=BUCKET, Key=key)["Body"].read().decode("utf-8")
    except ClientError as e:
        if _code(e) in ("NoSuchKey", "404"):
            return None
        raise


def put_json(key, data, **cond):
    s3().put_object(
        Bucket=BUCKET, Key=key, ContentType="application/json",
        Body=json.dumps(data, ensure_ascii=False).encode("utf-8"), **cond,
    )


def put_text(key, text):
    s3().put_object(Bucket=BUCKET, Key=key, ContentType="text/markdown; charset=utf-8",
                    Body=text.encode("utf-8"))


def is_conflict(err):
    return _code(err) in ("PreconditionFailed", "ConditionalRequestConflict", "412", "409")


def update_status(job_id, **fields):
    key = f"jobs/{job_id}/status.json"
    cur, _ = get_json(key)
    cur = cur or {}
    cur.update(fields)
    cur["updatedAt"] = now_iso()
    put_json(key, cur)
    return cur


def now_iso():
    return datetime.datetime.now(KST).isoformat(timespec="seconds")


def today():
    return datetime.datetime.now(KST).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- 하루 한도, 같은 저장소 재사용

def try_increment_counter(day):
    """한도 안이면 1 올리고 True, 한도에 닿았으면 False. 조건부 쓰기로 동시 요청을 막는다."""
    key = f"counters/{day}.json"
    for _ in range(10):
        cur, etag = get_json(key)
        count = (cur or {}).get("count", 0)
        if count >= DAILY_LIMIT:
            return False
        cond = {"IfMatch": etag} if etag else {"IfNoneMatch": "*"}
        try:
            put_json(key, {"count": count + 1}, **cond)
            return True
        except ClientError as e:
            if is_conflict(e):
                time.sleep(0.05)
                continue
            raise
    raise RuntimeError("counter contention")


def cache_key(day, repo):
    return f"cache/{day}/{repo.lower()}.json"


def claim_repo(day, repo, job_id):
    """오늘 이 저장소의 첫 요청이면 (True, None), 이미 있으면 (False, 기존 job id)."""
    key = cache_key(day, repo)
    for _ in range(5):
        try:
            put_json(key, {"jobId": job_id}, IfNoneMatch="*")
            return True, None
        except ClientError as e:
            if not is_conflict(e):
                raise
        existing, etag = get_json(key)
        if existing is None:
            continue
        status, _ = get_json(f"jobs/{existing['jobId']}/status.json")
        if status and status.get("status") == "failed":
            # 실패한 작업은 재사용하지 않고 새로 돌린다
            try:
                put_json(key, {"jobId": job_id}, IfMatch=etag)
                return True, None
            except ClientError as e:
                if is_conflict(e):
                    continue
                raise
        return False, existing["jobId"]
    raise RuntimeError("cache contention")


# ---------------------------------------------------------------- HTTP API

def resp(status, body):
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json; charset=utf-8", "cache-control": "no-store"},
        "body": json.dumps(body, ensure_ascii=False),
    }


def parse_body(event):
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    try:
        data = json.loads(raw) if raw else {}
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


LIMIT_MSG = "오늘 실행 한도({n}건, 후보 찾기 포함)를 모두 썼습니다. 내일 다시 시도해 주세요."


def read_topic(event):
    """(data, topic, 오류 응답). 오류가 있으면 앞의 둘은 None."""
    data = parse_body(event)
    if data is None:
        return None, None, resp(400, {"error": "요청 본문이 JSON이 아닙니다."})
    topic = re.sub(r"\s+", " ", str(data.get("topic") or "")).strip()
    if not topic or len(topic) > 200:
        return None, None, resp(400, {"error": "검토 주제를 1~200자로 넣어 주세요."})
    return data, topic, None


def start_job(job_id, base):
    put_json(f"jobs/{job_id}/status.json", {**base, "status": "queued", "stage": "대기 중",
                                             "updatedAt": now_iso()})
    # 이 객체가 생기면 S3 이벤트가 이 함수를 비동기로 다시 부른다
    put_json(f"jobs/{job_id}/request.json", base)
    return resp(202, {"jobId": job_id, "kind": base["kind"], "status": "queued", "reused": False})


def api_create(event):
    data, topic, err_resp = read_topic(event)
    if err_resp:
        return err_resp
    repo = str(data.get("repo") or "").strip()
    if not REPO_RE.match(repo):
        return resp(400, {"error": "저장소는 owner/repo 형식으로 넣어 주세요. 비워 두려면 후보 찾기를 쓰세요."})

    day = today()
    job_id = str(uuid.uuid4())
    first, existing = claim_repo(day, repo, job_id)
    if not first:
        status, _ = get_json(f"jobs/{existing}/status.json")
        return resp(200, {"jobId": existing, "kind": "report",
                          "status": (status or {}).get("status", "queued"), "reused": True})

    if not try_increment_counter(day):
        s3().delete_object(Bucket=BUCKET, Key=cache_key(day, repo))
        return resp(429, {"error": LIMIT_MSG.format(n=DAILY_LIMIT)})

    return start_job(job_id, {"jobId": job_id, "kind": "report", "topic": topic, "repo": repo,
                              "day": day, "createdAt": now_iso()})


def api_candidates(event):
    """저장소 없이 주제만 받아 후보 찾기 작업을 만든다. 하루 한도에 함께 센다."""
    _, topic, err_resp = read_topic(event)
    if err_resp:
        return err_resp
    day = today()
    if not try_increment_counter(day):
        return resp(429, {"error": LIMIT_MSG.format(n=DAILY_LIMIT)})
    job_id = str(uuid.uuid4())
    return start_job(job_id, {"jobId": job_id, "kind": "discover", "topic": topic,
                              "day": day, "createdAt": now_iso()})


def api_get(job_id):
    try:
        uuid.UUID(job_id)
    except ValueError:
        return resp(400, {"error": "잘못된 작업 ID입니다."})
    status, _ = get_json(f"jobs/{job_id}/status.json")
    if status is None:
        return resp(404, {"error": "작업을 찾을 수 없습니다."})
    status.setdefault("kind", "report")
    if status.get("status") == "done" and status["kind"] == "report":
        status["report"] = get_text(f"jobs/{job_id}/report.md")
        status["review"] = get_text(f"jobs/{job_id}/review.md")
    return resp(200, status)


def handle_http(event):
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    path = event.get("rawPath", "").rstrip("/")
    if method == "POST" and path == "/api/review":
        return api_create(event)
    if method == "POST" and path == "/api/candidates":
        return api_candidates(event)
    m = re.fullmatch(r"/api/(?:review|candidates)/([^/]+)", path)
    if m and method == "GET":
        return api_get(m.group(1))
    return resp(404, {"error": "없는 경로입니다."})


# ---------------------------------------------------------------- deepwiki MCP (JSON-RPC over HTTP)

class McpError(Exception):
    pass


def mcp_call(tool, arguments, timeout=240):
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": tool, "arguments": arguments}}
    req = urllib.request.Request(
        DEEPWIKI_URL, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream",
                 "User-Agent": "oss-review-kit-showcase/1.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode("utf-8")
        ctype = r.headers.get("Content-Type", "")
    messages = []
    if "text/event-stream" in ctype:
        for line in body.splitlines():
            if line.startswith("data:"):
                try:
                    messages.append(json.loads(line[5:].strip()))
                except ValueError:
                    pass
    else:
        messages.append(json.loads(body))
    msg = next((m for m in messages if m.get("id") == 1), None)
    if msg is None:
        raise McpError("deepwiki 응답을 해석하지 못했습니다.")
    if "error" in msg:
        raise McpError(str(msg["error"].get("message", msg["error"])))
    result = msg.get("result", {})
    text = "\n".join(c.get("text", "") for c in result.get("content", []) if c.get("type") == "text")
    if result.get("isError"):
        raise McpError(text or "deepwiki 도구 오류")
    return text


def survey_questions(topic):
    """SKILL.md 절차 1의 조사 항목을 검토 주제에 비추어 묻는다."""
    return [
        ("주요 구조", f"'{topic}' 관점에서 이 저장소의 전체 구조와 핵심 구성 요소는 무엇인가요?"),
        ("주요 기능", f"'{topic}' 용도로 쓸 때 이 저장소의 주요 기능과 목적, 적용 범위는 무엇인가요?"),
        ("연동 방식", "이 저장소를 다른 시스템, 모델, 프레임워크와 연동하는 방식(API, 어댑터, 플러그인, 설정)은 무엇인가요?"),
        ("인증과 보안 기능", "이 저장소의 인증, 키와 비밀 관리, 코드 실행 격리, 데이터 보호 같은 보안 관련 기능이나 주의점은 무엇인가요?"),
        ("버전 전환 현황", "이 저장소의 주요 버전 전환, 구조 개편, 주요 API 변경 내역과 그 이유는 무엇인가요? 운영할 때 고려할 점도 알려 주세요."),
    ]


def gather(repo, topic, on_stage):
    on_stage("위키 목차 조회")
    structure = mcp_call("read_wiki_structure", {"repoName": repo}, timeout=120)
    qs = survey_questions(topic)
    on_stage(f"위키 질의 {len(qs)}건")

    def ask(item):
        label, q = item
        try:
            return label, q, mcp_call("ask_wiki_question", {"repoName": repo, "question": q})
        except Exception as e:  # 질의 하나가 실패해도 나머지로 진행하고, 실패를 자료에 남긴다
            return label, q, f"(질의 실패: {e})"

    with ThreadPoolExecutor(max_workers=len(qs)) as pool:
        answers = list(pool.map(ask, qs))
    return structure, answers


def format_sources(repo, day, structure, answers):
    parts = [f"## 자료 1. deepwiki read_wiki_structure({repo}) — 조회일 {day}\n\n"
             f"{structure[:MAX_SOURCE_CHARS]}"]
    for i, (label, q, a) in enumerate(answers, start=2):
        parts.append(f"## 자료 {i}. deepwiki ask_wiki_question({repo}) — {label} — 조회일 {day}\n\n"
                     f"질문: {q}\n\n답변:\n{a[:MAX_SOURCE_CHARS]}")
    return "\n\n---\n\n".join(parts)


# ---------------------------------------------------------------- Bedrock Converse

def converse(system_texts, user_text, max_tokens=16000):
    """(텍스트, 잘렸는지) 를 돌려준다."""
    r = bedrock().converse(
        modelId=MODEL_ID,
        system=[{"text": t} for t in system_texts],
        messages=[{"role": "user", "content": [{"text": user_text}]}],
        inferenceConfig={"maxTokens": max_tokens},
    )
    blocks = r["output"]["message"]["content"]
    text = "\n".join(b["text"] for b in blocks if "text" in b).strip()
    return text, r.get("stopReason") == "max_tokens"


VERDICT_LINE = re.compile(r"^[#*>\-\s`|]*(PASS|WARN|FAIL)\b")


def parse_verdict(review, truncated=False):
    """마지막 몇 줄에서 판정 단어로 시작하는 줄만 판정으로 본다. 표 안의 단어는 무시한다."""
    if truncated:
        return "WARN", "WARN — 검토 출력이 길이 제한에서 잘려 최종 판정을 받지 못했습니다."
    tail = [l.strip() for l in review.splitlines() if l.strip()][-3:]
    for line in reversed(tail):
        m = VERDICT_LINE.match(line)
        if m:
            return m.group(1), re.sub(r"^[#*>\-\s`|]*", "", line).strip("*` ")
    return "WARN", "WARN — 검토 결과에서 판정을 읽지 못했습니다."


RUNTIME_NOTE = (
    "이 실행은 웹 서버에서 한 번에 처리됩니다. 사용자에게 되묻거나 파일을 저장할 수 없습니다. "
    "deepwiki MCP 도구는 서버가 이미 호출했고, 그 결과를 아래 '자료'로 붙였습니다. "
    "자료에 없는 사실은 쓰지 말고, 출처는 자료 번호와 도구 이름, 조회일로 적습니다."
)


def run_pipeline(topic, repo, day, previous, on_stage):
    skill = load_prompt("skills/oss-review/SKILL.md")
    researcher = load_prompt("agents/mcp-researcher.md")
    reviewer = load_prompt("agents/evidence-reviewer.md")

    structure, answers = gather(repo, topic, on_stage)
    sources = format_sources(repo, day, structure, answers)
    prev_block = (f"# 직전 리포트 ({previous[0]})\n\n{previous[1][:MAX_SOURCE_CHARS]}"
                  if previous else "# 직전 리포트\n\n없음. '직전 리포트 대비' 칸에는 '첫 검토'라고 적습니다.")

    draft_request = (
        f"{RUNTIME_NOTE}\n\n검토 주제: {topic}\n저장소: {repo}\n조회일: {day}\n\n"
        f"SKILL.md의 '출력 형식' 그대로 마크다운 리포트 초안을 쓰세요. "
        f"5번 '검토 결과' 줄은 내용 대신 {REVIEW_PLACEHOLDER} 라고만 적습니다. "
        f"리포트 밖의 설명은 붙이지 않습니다.\n\n{prev_block}\n\n# 자료\n\n{sources}"
    )
    on_stage("조사 초안 작성")
    draft, draft_cut = converse([skill, researcher], draft_request)

    def review(text):
        return converse([reviewer], (
            f"{RUNTIME_NOTE}\n\n아래 초안의 주장마다 '자료'와 대조해 검토하세요. "
            f"마지막 줄은 'PASS: 한 줄 이유', 'WARN: 한 줄 이유', 'FAIL: 한 줄 이유' 중 하나로 씁니다.\n\n"
            f"# 초안\n\n{text}\n\n# 자료\n\n{sources}"))

    on_stage("근거 검토")
    rv, rv_cut = review(draft)
    verdict, reason = parse_verdict(rv, rv_cut or draft_cut)
    history = [verdict]
    reviews = [f"## 1차 검토: {verdict}\n\n{rv}"]

    if verdict == "FAIL":
        on_stage("지적 반영 후 재검토")
        draft, draft_cut = converse([skill, researcher], (
            f"{draft_request}\n\n# 이전 초안\n\n{draft}\n\n# 검토 지적\n\n{rv}\n\n"
            f"검토 지적을 모두 고친 리포트 전체를 다시 쓰세요. 근거가 없는 주장은 지우거나 "
            f"'확인하지 못한 것'으로 옮깁니다."))
        rv, rv_cut = review(draft)
        verdict, reason = parse_verdict(rv, rv_cut or draft_cut)
        history.append(verdict)
        reviews.append(f"## 2차 검토: {verdict}\n\n{rv}")

    result_line = reason if reason.startswith(verdict) else f"{verdict} — {reason}"
    if REVIEW_PLACEHOLDER in draft:
        report = draft.replace(REVIEW_PLACEHOLDER, result_line)
    else:
        report = f"{draft}\n\n5. 검토 결과: {result_line}"
    return report, "\n\n".join(reviews), verdict, history


# ---------------------------------------------------------------- 후보 찾기 (SKILL.md '저장소 정하기')

MAX_CANDIDATES = 5
MAX_MENTIONS = 8
KNOWLEDGE_PATH = "지식 후보"


def extract_json(text):
    """모델 응답에서 JSON 객체 하나를 꺼낸다. 못 꺼내면 None."""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    raw = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def clean_repo(value):
    """'https://github.com/a/b.git' 같은 표기도 'a/b'로. 형식이 맞지 않으면 None."""
    s = str(value or "").strip().strip("`'\" ")
    s = re.sub(r"^(https?://)?(www\.)?github\.com/", "", s, flags=re.I)
    s = re.sub(r"\.git$", "", s).strip("/")
    return s if REPO_RE.match(s) else None


def clean_repos(values, limit):
    out, seen = [], set()
    for v in values if isinstance(values, list) else []:
        r = clean_repo(v)
        if r and r.lower() not in seen:
            seen.add(r.lower())
            out.append(r)
    return out[:limit]


def json_only(shape):
    return f"아래 JSON만 출력합니다. 다른 설명은 붙이지 않습니다.\n```json\n{shape}\n```"


def run_discovery(topic, day, on_stage):
    """지식 후보 + 허브 탐색 -> 위키 목차로 확인 -> 최대 5개. 찾은 경로는 서버가 기록한다."""
    skill = load_prompt("skills/oss-review/SKILL.md")
    researcher = load_prompt("agents/mcp-researcher.md")

    found = {}  # 소문자 repo -> {"repo": 표기, "paths": [찾은 경로...]}

    def add(repo, how):
        item = found.setdefault(repo.lower(), {"repo": repo, "paths": []})
        if how not in item["paths"]:
            item["paths"].append(how)

    # 1. 지식 후보와 허브 정하기 (SKILL.md: 1번은 직접)
    on_stage("지식 후보 고르기")
    text, _ = converse([skill], (
        f"이 실행은 웹 서버에서 한 번에 처리됩니다. 사용자에게 되묻지 않습니다.\n\n검토 주제: {topic}\n\n"
        f"SKILL.md '저장소 정하기'의 1번(지식 후보 2~3개)과 2번의 허브(주제의 대표 저장소 1~2개)를 "
        f"모델 지식으로 고르세요. 허브는 지식 후보와 겹쳐도 됩니다. "
        + json_only('{"knowledge": ["owner/repo"], "hubs": ["owner/repo"]}')), max_tokens=2000)
    picked = extract_json(text) or {}
    knowledge = clean_repos(picked.get("knowledge"), 3)
    hubs = clean_repos(picked.get("hubs"), 2)
    if not knowledge and not hubs:
        raise RuntimeError("지식 후보를 받지 못했습니다.")
    for r in knowledge:
        add(r, KNOWLEDGE_PATH)
    for h in hubs:
        add(h, f"{KNOWLEDGE_PATH}(허브)")

    # 2. 허브 탐색 (SKILL.md: researcher 담당) — 허브 위키에 관련 저장소를 묻는다
    on_stage(f"허브 탐색 {len(hubs)}곳")
    question = (f"'{topic}'와 관련해 이 저장소가 통합하거나 의존하거나 대안으로 언급하는 "
                f"다른 GitHub 저장소는 무엇인가요? 저장소 이름을 owner/repo 형식으로 알려 주세요.")

    def ask_hub(h):
        try:
            return h, mcp_call("ask_wiki_question", {"repoName": h, "question": question})
        except Exception:
            return h, None

    with ThreadPoolExecutor(max_workers=max(1, len(hubs))) as pool:
        hub_answers = {h: a for h, a in pool.map(ask_hub, hubs) if a}

    if hub_answers:
        material = "\n\n---\n\n".join(
            f"## 자료: deepwiki ask_wiki_question({h}) — 조회일 {day}\n\n질문: {question}\n\n답변:\n"
            f"{a[:MAX_SOURCE_CHARS]}" for h, a in hub_answers.items())
        text, _ = converse([researcher], (
            f"{RUNTIME_NOTE}\n\n아래 허브 위키 답변에 owner/repo 형식으로 적힌 관련 저장소만 뽑으세요. "
            f"허브 자신과 자료에 없는 저장소는 넣지 않습니다. "
            + json_only('{"mentions": [{"repo": "owner/repo", "hub": "허브 owner/repo"}]}')
            + f"\n\n# 자료\n\n{material}"), max_tokens=2000)
        mentions = (extract_json(text) or {}).get("mentions")
        hubs_by_lower = {h.lower(): h for h in hub_answers}
        added = 0
        for m in mentions if isinstance(mentions, list) else []:
            if added >= MAX_MENTIONS or not isinstance(m, dict):
                continue
            repo, hub = clean_repo(m.get("repo")), hubs_by_lower.get(str(m.get("hub", "")).lower())
            # 실제로 그 허브의 답변에 적힌 이름만 받는다 (모델이 지어낸 이름 차단)
            if repo and hub and repo.lower() != hub.lower() and repo.lower() in hub_answers[hub].lower():
                add(repo, f"{hub} 위키에서 언급")
                added += 1

    # 3. 확인 — DeepWiki 목차가 조회되는 것만 남긴다
    on_stage(f"위키 목차로 확인 {len(found)}개")

    def check(key):
        try:
            return key, mcp_call("read_wiki_structure", {"repoName": found[key]["repo"]}, timeout=120)
        except Exception:
            return key, None

    with ThreadPoolExecutor(max_workers=8) as pool:
        structures = {k: s for k, s in pool.map(check, list(found)) if s}
    if not structures:
        return []

    # 4. 제시 — 주제에 맞는 순서로 최대 5개, 한 줄 설명은 목차 근거
    on_stage("후보 정리")
    material = "\n\n---\n\n".join(
        f"## 자료: deepwiki read_wiki_structure({found[k]['repo']}) — 조회일 {day}\n\n"
        f"{s[:4000]}" for k, s in structures.items())
    text, _ = converse([skill, researcher], (
        f"{RUNTIME_NOTE}\n\n검토 주제: {topic}\n\nSKILL.md '저장소 정하기' 4번(제시)을 합니다. "
        f"아래는 DeepWiki 목차 조회로 확인된 후보입니다. 주제에 맞는 순서로 최대 {MAX_CANDIDATES}개를 고르고, "
        f"한 줄 설명은 각 후보의 목차에서 확인되는 내용으로만 씁니다. "
        + json_only('{"candidates": [{"repo": "owner/repo", "description": "한 줄 설명"}]}')
        + f"\n\n# 자료\n\n{material}"), max_tokens=3000)
    picks = (extract_json(text) or {}).get("candidates")

    result, used = [], set()
    for p in picks if isinstance(picks, list) else []:
        key = (clean_repo(p.get("repo")) or "").lower() if isinstance(p, dict) else ""
        if key in structures and key not in used:
            used.add(key)
            desc = re.sub(r"\s+", " ", str(p.get("description") or "")).strip()[:200]
            result.append({"repo": found[key]["repo"], "description": desc or "(설명 없음)",
                           "path": ", ".join(found[key]["paths"])})
    if not result:  # 정리 응답을 못 읽으면 확인된 순서 그대로
        result = [{"repo": found[k]["repo"], "description": "(설명을 만들지 못했습니다)",
                   "path": ", ".join(found[k]["paths"])} for k in structures]
    return result[:MAX_CANDIDATES]


def previous_report(repo, day):
    prefix = f"reports/{repo.lower()}/"
    r = s3().list_objects_v2(Bucket=BUCKET, Prefix=prefix)
    keys = sorted(o["Key"] for o in r.get("Contents", []) if o["Key"] < f"{prefix}{day}.md")
    if not keys:
        return None
    k = keys[-1]
    return k[len(prefix):-3], get_text(k)


def handle_job(job_id):
    key = f"jobs/{job_id}/status.json"
    status, etag = get_json(key)
    if not status or status.get("status") != "queued":
        return  # 중복 이벤트
    status.update(status="running", stage="시작", updatedAt=now_iso())
    try:
        put_json(key, status, IfMatch=etag)  # 이벤트가 두 번 와도 한 번만 실행
    except ClientError as e:
        if is_conflict(e):
            return
        raise

    on_stage = lambda stage: update_status(job_id, stage=stage)  # noqa: E731
    topic, day = status["topic"], status["day"]
    try:
        if status.get("kind") == "discover":
            candidates = run_discovery(topic, day, on_stage)
            update_status(job_id, status="done", stage="완료", candidates=candidates)
            return
        repo = status["repo"]
        report, review_md, verdict, history = run_pipeline(
            topic, repo, day, previous_report(repo, day), on_stage)
        put_text(f"jobs/{job_id}/report.md", report)
        put_text(f"jobs/{job_id}/review.md", review_md)
        put_text(f"reports/{repo.lower()}/{day}.md", report)
        update_status(job_id, status="done", stage="완료", verdict=verdict, verdictHistory=history)
    except McpError as e:
        update_status(job_id, status="failed", error=f"deepwiki: {e}"[:500])
    except Exception as e:
        update_status(job_id, status="failed", error=f"{type(e).__name__}: {e}"[:500])


def handle_s3(event):
    for rec in event.get("Records", []):
        key = urllib.parse.unquote_plus(rec["s3"]["object"]["key"])
        m = re.fullmatch(r"jobs/([0-9a-f-]{36})/request\.json", key)
        if m:
            handle_job(m.group(1))


def handler(event, context):
    if "Records" in event:
        return handle_s3(event)
    return handle_http(event)
