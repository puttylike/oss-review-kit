"""handler.py API 로직 테스트 (가짜 S3, 네트워크 없음). 실행: python3 -I tests/test_handler.py"""
import io
import json
import os
import sys
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor

from botocore.exceptions import ClientError

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lambda", "review"))
os.environ.update(DATA_BUCKET="b", MODEL_ID="m", DAILY_LIMIT="3")
import handler  # noqa: E402


def err(code):
    return ClientError({"Error": {"Code": code}}, "op")


class FakeS3:
    """IfMatch / IfNoneMatch를 지원하는 최소한의 S3."""

    def __init__(self):
        self.objs, self.lock, self.n = {}, threading.Lock(), 0

    def get_object(self, Bucket, Key):
        with self.lock:
            if Key not in self.objs:
                raise err("NoSuchKey")
            body, etag = self.objs[Key]
            return {"Body": io.BytesIO(body), "ETag": etag}

    def put_object(self, Bucket, Key, Body, ContentType=None, IfMatch=None, IfNoneMatch=None):
        with self.lock:
            cur = self.objs.get(Key)
            if IfNoneMatch == "*" and cur is not None:
                raise err("PreconditionFailed")
            if IfMatch is not None and (cur is None or cur[1] != IfMatch):
                raise err("PreconditionFailed")
            self.n += 1
            self.objs[Key] = (Body, f'"{self.n}"')
            self.last_put = Key

    def delete_object(self, Bucket, Key):
        with self.lock:
            self.objs.pop(Key, None)

    def list_objects_v2(self, Bucket, Prefix):
        return {"Contents": [{"Key": k} for k in sorted(self.objs) if k.startswith(Prefix)]}


def post_to(path, body):
    return handler.handler({"requestContext": {"http": {"method": "POST"}}, "rawPath": path,
                            "body": json.dumps(body)}, None)


def post(body):
    return post_to("/api/review", body)


def get_from(prefix, job_id):
    return handler.handler({"requestContext": {"http": {"method": "GET"}},
                            "rawPath": f"{prefix}/{job_id}"}, None)


def get(job_id):
    return get_from("/api/review", job_id)


def body(r):
    return json.loads(r["body"])


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.s3 = FakeS3()
        handler._s3 = self.s3

    def ok(self, repo, topic="주제"):
        return post({"topic": topic, "repo": repo})

    def test_validation(self):
        self.assertEqual(self.ok("not-a-repo")["statusCode"], 400)
        self.assertEqual(self.ok("a/b", topic="")["statusCode"], 400)
        self.assertEqual(self.ok("a/b/../c")["statusCode"], 400)
        bad_json = handler.handler({"requestContext": {"http": {"method": "POST"}},
                                    "rawPath": "/api/review", "body": "{"}, None)
        self.assertEqual(bad_json["statusCode"], 400)
        self.assertEqual(self.s3.objs, {})  # 거절된 요청은 아무것도 쓰지 않는다
        self.assertEqual(self.ok("a/b", topic="")["statusCode"], 400)
        self.assertEqual(self.ok("a/b/../c")["statusCode"], 400)

    def test_create_writes_request_and_status(self):
        r = self.ok("gepa-ai/gepa")
        self.assertEqual(r["statusCode"], 202)
        jid = body(r)["jobId"]
        self.assertIn(f"jobs/{jid}/request.json", self.s3.objs)
        g = body(get(jid))
        self.assertEqual((g["status"], g["repo"]), ("queued", "gepa-ai/gepa"))

    def test_same_repo_same_day_reuses_and_does_not_count(self):
        a = body(self.ok("Gepa-AI/gepa"))
        b = self.ok("gepa-ai/GEPA", topic="다른 주제")
        self.assertEqual(b["statusCode"], 200)
        self.assertEqual(body(b)["jobId"], a["jobId"])
        self.assertTrue(body(b)["reused"])
        cnt = json.loads(self.s3.objs[f"counters/{handler.today()}.json"][0])["count"]
        self.assertEqual(cnt, 1)

    def test_failed_job_is_not_reused(self):
        a = body(self.ok("a/b"))["jobId"]
        handler.update_status(a, status="failed")
        b = self.ok("a/b")
        self.assertEqual(b["statusCode"], 202)
        self.assertNotEqual(body(b)["jobId"], a)

    def test_daily_limit(self):
        for i in range(3):
            self.assertEqual(self.ok(f"o/r{i}")["statusCode"], 202)
        r = self.ok("o/r9")
        self.assertEqual(r["statusCode"], 429)
        # 한도 초과 요청은 캐시 표시를 남기지 않는다
        self.assertNotIn(handler.cache_key(handler.today(), "o/r9"), self.s3.objs)

    def test_limit_holds_under_concurrency(self):
        with ThreadPoolExecutor(12) as pool:
            codes = list(pool.map(lambda i: self.ok(f"c/r{i}")["statusCode"], range(12)))
        self.assertEqual(codes.count(202), 3)
        self.assertEqual(codes.count(429), 9)

    def test_get_bad_and_missing_id(self):
        self.assertEqual(get("x")["statusCode"], 400)
        self.assertEqual(get(str(uuid.uuid4()))["statusCode"], 404)

    def test_duplicate_s3_event_runs_once(self):
        jid = body(self.ok("a/b"))["jobId"]
        calls = []
        orig = handler.run_pipeline
        handler.run_pipeline = lambda *a: calls.append(1) or ("# r", "rv", "PASS", ["PASS"])
        try:
            ev = {"Records": [{"s3": {"object": {"key": f"jobs/{jid}/request.json"}}}]}
            handler.handler(ev, None)
            handler.handler(ev, None)
        finally:
            handler.run_pipeline = orig
        self.assertEqual(len(calls), 1)
        g = body(get(jid))
        self.assertEqual((g["status"], g["verdict"], g["report"]), ("done", "PASS", "# r"))

    def test_pipeline_error_marks_failed(self):
        jid = body(self.ok("a/b"))["jobId"]
        orig = handler.run_pipeline

        def boom(*a):
            raise handler.McpError("Repository not found")
        handler.run_pipeline = boom
        try:
            handler.handler({"Records": [{"s3": {"object": {"key": f"jobs/{jid}/request.json"}}}]}, None)
        finally:
            handler.run_pipeline = orig
        g = body(get(jid))
        self.assertEqual(g["status"], "failed")
        self.assertIn("Repository not found", g["error"])

    # ---- 후보 찾기 API

    def find(self, topic="주제"):
        return post_to("/api/candidates", {"topic": topic})

    def test_report_still_requires_repo(self):
        self.assertEqual(self.ok("")["statusCode"], 400)

    def test_candidates_validation_writes_nothing(self):
        self.assertEqual(self.find("")["statusCode"], 400)
        self.assertEqual(self.find("x" * 201)["statusCode"], 400)
        self.assertEqual(self.s3.objs, {})

    def test_candidates_create_discover_job(self):
        r = self.find("프롬프트 최적화")
        self.assertEqual(r["statusCode"], 202)
        jid = body(r)["jobId"]
        self.assertEqual(body(r)["kind"], "discover")
        req = json.loads(self.s3.objs[f"jobs/{jid}/request.json"][0])
        self.assertEqual((req["kind"], req["topic"]), ("discover", "프롬프트 최적화"))
        self.assertNotIn("repo", req)
        g = body(get_from("/api/candidates", jid))
        self.assertEqual((g["kind"], g["status"]), ("discover", "queued"))

    def test_candidates_count_toward_daily_limit_and_are_not_reused(self):
        a, b = self.find(), self.find()  # 같은 주제라도 매번 새 작업, 매번 한 건
        self.assertNotEqual(body(a)["jobId"], body(b)["jobId"])
        self.assertEqual(self.ok("o/r")["statusCode"], 202)  # 한도 3 = 후보 2 + 리포트 1
        self.assertEqual(self.find()["statusCode"], 429)
        self.assertEqual(self.ok("o/r2")["statusCode"], 429)
        self.assertEqual(self.ok("o/r")["statusCode"], 200)  # 이미 만든 저장소 재사용은 한도와 무관

    def test_discover_job_stores_candidates(self):
        jid = body(self.find())["jobId"]
        cands = [{"repo": "a/b", "description": "d", "path": "지식 후보"}]
        orig = handler.run_discovery
        handler.run_discovery = lambda topic, day, on_stage: cands
        try:
            handler.handler({"Records": [{"s3": {"object": {"key": f"jobs/{jid}/request.json"}}}]}, None)
        finally:
            handler.run_discovery = orig
        g = body(get_from("/api/candidates", jid))
        self.assertEqual((g["status"], g["candidates"]), ("done", cands))
        self.assertNotIn("report", g)

    def test_parse_verdict(self):
        self.assertEqual(handler.parse_verdict("표...\n\n**WARN: 일부 출처 없음**")[0], "WARN")
        self.assertEqual(handler.parse_verdict("a\nFAIL: 불일치\n")[0], "FAIL")
        self.assertEqual(handler.parse_verdict("판정 없음")[0], "WARN")
        # 표 안에 든 단어는 판정이 아니다
        v, why = handler.parse_verdict("| 1 | FAIL 처리 방식 | 확인 |\n| 2 | x | 확인 |\n| 3 | y | 확인 |\n| 4 | z |")
        self.assertIn("읽지 못했습니다", why)
        self.assertEqual(handler.parse_verdict("...\nPASS: 모두 확인", truncated=True)[0], "WARN")
        self.assertEqual(handler.parse_verdict("표\n\n**PASS: 모두 확인**")[1], "PASS: 모두 확인")


class DiscoveryTest(unittest.TestCase):
    """run_discovery를 가짜 deepwiki/Bedrock으로 돌린다."""

    HUB_ANSWER = ("DSPy integrates with gepa-ai/gepa as an optimizer engine. "
                  "See also https://github.com/zou-group/textgrad for an alternative.")
    ON_WIKI = {"stanfordnlp/dspy", "gepa-ai/gepa", "zou-group/textgrad",
               "microsoft/promptwizard", "k1/a", "k2/b", "k3/c"}

    def setUp(self):
        self.saved = (handler.converse, handler.mcp_call, handler.load_prompt)
        self.calls = []
        self.final_picks = None
        handler.load_prompt = lambda rel: f"[{rel}]"
        handler.mcp_call = self.fake_mcp
        handler.converse = self.fake_converse

    def tearDown(self):
        handler.converse, handler.mcp_call, handler.load_prompt = self.saved

    def fake_mcp(self, tool, args, timeout=0):
        self.calls.append((tool, args["repoName"]))
        if tool == "ask_wiki_question":
            return self.HUB_ANSWER
        if args["repoName"].lower() in self.ON_WIKI:
            return f"Available pages for {args['repoName']}:\n- 1 Overview"
        raise handler.McpError("Repository not found")

    def fake_converse(self, systems, text, max_tokens=0):
        if "지식 후보 2~3개" in text:
            self.assertEqual(systems, ["[skills/oss-review/SKILL.md]"])
            return ('```json\n{"knowledge": ["stanfordnlp/dspy", "https://github.com/microsoft/PromptWizard.git",'
                    ' "ghost/not-on-wiki"], "hubs": ["stanfordnlp/dspy"]}\n```', False)
        if "허브 위키 답변" in text:
            self.assertEqual(systems, ["[agents/mcp-researcher.md]"])
            return (json.dumps({"mentions": [
                {"repo": "gepa-ai/gepa", "hub": "stanfordnlp/dspy"},
                {"repo": "zou-group/textgrad", "hub": "stanfordnlp/dspy"},
                {"repo": "invented/by-model", "hub": "stanfordnlp/dspy"},  # 답변에 없는 이름
                {"repo": "stanfordnlp/dspy", "hub": "stanfordnlp/dspy"},   # 허브 자신
            ]}), False)
        if "4번(제시)" in text:
            self.assertEqual(systems, ["[skills/oss-review/SKILL.md]", "[agents/mcp-researcher.md]"])
            picks = self.final_picks or [
                {"repo": "gepa-ai/gepa", "description": "반사적 프롬프트 진화"},
                {"repo": "ghost/not-on-wiki", "description": "확인 안 된 후보"},
                {"repo": "stanfordnlp/dspy", "description": "LM 프로그램 프레임워크"},
                {"repo": "gepa-ai/gepa", "description": "중복"},
            ]
            return "설명\n" + json.dumps({"candidates": picks}), False
        raise AssertionError(text[:80])

    def run_it(self):
        return handler.run_discovery("프롬프트 최적화", "2026-11-17", lambda s: None)

    def test_only_wiki_verified_candidates_with_server_paths(self):
        res = self.run_it()
        self.assertEqual([c["repo"] for c in res], ["gepa-ai/gepa", "stanfordnlp/dspy"])
        self.assertEqual(res[0]["path"], "stanfordnlp/dspy 위키에서 언급")
        self.assertEqual(res[1]["path"], "지식 후보, 지식 후보(허브)")
        self.assertEqual(res[0]["description"], "반사적 프롬프트 진화")
        checked = {r for t, r in self.calls if t == "read_wiki_structure"}
        self.assertNotIn("invented/by-model", checked)  # 지어낸 이름은 목차 조회조차 안 한다
        self.assertIn("ghost/not-on-wiki", checked)      # 조회했지만 없어서 탈락
        self.assertIn("microsoft/PromptWizard", checked)  # URL 표기를 owner/repo로 정리

    def test_at_most_five(self):
        self.final_picks = [{"repo": r, "description": r} for r in
                            ["stanfordnlp/dspy", "gepa-ai/gepa", "zou-group/textgrad", "microsoft/PromptWizard"]]
        res = self.run_it()
        self.assertLessEqual(len(res), handler.MAX_CANDIDATES)
        self.assertEqual(len(res), 4)

    def test_unreadable_final_answer_falls_back_to_verified(self):
        self.final_picks = [{"repo": "nope/x"}]
        res = self.run_it()
        self.assertTrue(res)
        self.assertTrue(all(c["repo"].lower() in self.ON_WIKI for c in res))

    def test_nothing_verified_returns_empty(self):
        self.ON_WIKI = set()
        self.assertEqual(self.run_it(), [])

    def test_helpers(self):
        self.assertEqual(handler.clean_repo("https://github.com/a/b.git"), "a/b")
        self.assertIsNone(handler.clean_repo("src/gepa/api.py"))
        self.assertEqual(handler.extract_json('앞말 {"a": 1} 뒷말'), {"a": 1})
        self.assertIsNone(handler.extract_json("JSON 없음"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
