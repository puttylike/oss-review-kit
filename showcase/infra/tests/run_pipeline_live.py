"""실제 deepwiki + Bedrock으로 파이프라인 한 번 실행 (S3 미사용).
실행: python -I tests/run_pipeline_live.py <my-kit 경로> <topic> <owner/repo> <출력 폴더>
"""
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
my_kit, topic, repo, out_dir = sys.argv[1:5]

# Lambda 번들과 같은 배치(handler.py + prompts/)를 임시 폴더에 만든다
work = tempfile.mkdtemp()
shutil.copy(os.path.join(HERE, "..", "lambda", "review", "handler.py"), work)
os.makedirs(os.path.join(work, "prompts", "skills", "oss-review"))
os.makedirs(os.path.join(work, "prompts", "agents"))
shutil.copy(os.path.join(my_kit, "skills/oss-review/SKILL.md"), os.path.join(work, "prompts/skills/oss-review"))
for f in ("mcp-researcher.md", "evidence-reviewer.md"):
    shutil.copy(os.path.join(my_kit, "agents", f), os.path.join(work, "prompts/agents"))
sys.path.insert(0, work)
os.environ.setdefault("MODEL_ID", "us.anthropic.claude-sonnet-5-5")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
import handler  # noqa: E402

t0 = time.time()
report, review, verdict, history = handler.run_pipeline(
    topic, repo, handler.today(), None,
    lambda s: print(f"[{time.time() - t0:6.1f}s] {s}", flush=True))
os.makedirs(out_dir, exist_ok=True)
open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8").write(report)
open(os.path.join(out_dir, "review.md"), "w", encoding="utf-8").write(review)
print(f"[{time.time() - t0:6.1f}s] done verdict={verdict} history={history}")
