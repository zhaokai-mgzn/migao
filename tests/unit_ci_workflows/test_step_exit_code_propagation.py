"""
CI workflow 步骤的退出码传播守卫（issue #3270）。

背景（2026-09-11 实证）：
`xiaobu-acceptance.yml` 的「Start local stack」步骤写成：

    docker compose ... up --wait ... 2>&1 | tail -20

bash 默认返回**管道最后一个命令**的退出码。`tail` 永远成功 → 即使 compose
因为 postgres `exited (3)` 而失败，该步骤仍报 **success**：

    step 4 "Start local stack ..." -> success      ← 假绿
    step 5 "Diagnose ..."          -> skipped      ← if: failure() 永不触发，拿不到日志
    step 7 "Run xiaobu local_runner" -> failure    ← 只剩「评测连不上」的表象

后果：真因（栈没起来）被掩盖成「评测失败」，自 2026-08-31 起 9/9 全 failure
却长期无法定位。

本测试锁定：带管道的关键步骤必须 `set -o pipefail`，且其后必须有可触发的失败诊断步骤。
"""
# case_ids: MC-012, DF-011
import re
from pathlib import Path

import yaml

WORKFLOWS_DIR = Path(__file__).parent.parent.parent / ".github" / "workflows"


def _steps(workflow: str):
    d = yaml.safe_load((WORKFLOWS_DIR / workflow).read_text(encoding="utf-8")) or {}
    out = []
    for job in (d.get("jobs") or {}).values():
        out.extend(job.get("steps") or [])
    return out


def _find_step(workflow: str, name_contains: str):
    for s in _steps(workflow):
        if name_contains in (s.get("name") or ""):
            return s
    return None


def _effective_run_lines(run: str):
    """剔除 bash 注释行后的有效命令（防「注释里提到 pipefail」造成假通过）。"""
    out = []
    for line in (run or "").splitlines():
        if line.lstrip().startswith("#"):
            continue
        out.append(line)
    return "\n".join(out)


def _sets_pipefail(run: str) -> bool:
    return bool(re.search(r"set\s+-[a-z]*o\s+pipefail|set\s+-[a-z]*euo\s+pipefail",
                          _effective_run_lines(run)))


class TestXiaobuStackExitCodePropagation:
    """xiaobu-acceptance 起栈步骤必须真实传播 compose 失败"""

    WORKFLOW = "xiaobu-acceptance.yml"

    def test_stack_step_exists_and_pipes(self):
        """前提：起栈步骤确实把 compose 输出管给 tail（因此需要 pipefail）"""
        step = _find_step(self.WORKFLOW, "Start local stack")
        assert step is not None, "未找到 Start local stack 步骤（测试前提失效）"
        run = step.get("run") or ""
        assert "docker compose" in run
        assert "|" in run, "起栈步骤不再有管道 —— 本守卫前提变化，需同步修订"

    def test_stack_step_sets_pipefail(self):
        """核心契约：管道存在时必须有 set -o pipefail，否则 compose 失败被吞"""
        step = _find_step(self.WORKFLOW, "Start local stack")
        run = step.get("run") or ""
        assert _sets_pipefail(run), (
            "起栈步骤有管道但无 pipefail —— compose 失败会变成 step success，"
            "真因被掩盖（issue #3270 实证：postgres exited 3 却报 success）。"
            "注意：断言只看非注释行（注释里写 pipefail 不算数）"
        )

    def test_diagnose_step_triggers_on_failure(self):
        """失败诊断步骤必须能在起栈失败时触发"""
        step = _find_step(self.WORKFLOW, "Diagnose stack startup")
        assert step is not None, "缺少失败诊断步骤"
        assert (step.get("if") or "").strip() == "failure()", (
            f"诊断步骤 if 应为 failure()，实为 {step.get('if')!r} —— "
            "否则起栈失败时不会 dump 容器日志（真因无法定位）"
        )

    def test_diagnose_provides_required_compose_env(self):
        """诊断步骤必须给 DEV_SERVICE_TOKEN 值，否则 compose 插值失败拿不到日志"""
        step = _find_step(self.WORKFLOW, "Diagnose stack startup")
        env = (step.get("env") or {})
        assert "DEV_SERVICE_TOKEN" in env, (
            "诊断步骤缺 DEV_SERVICE_TOKEN —— deploy/docker-compose.yml 将其声明为 "
            "required（${DEV_SERVICE_TOKEN:?...}），缺它连 compose ps/logs 都会插值失败"
        )


class TestPipefailPatternInventory:
    """管道退出码吞失败是**系统性**模式，非单点（记录规模，防扩大）"""

    # 2026-09-11 基线：28 个 step 有管道但无 pipefail。
    # 不逐条修（部分管道的非零退出是预期行为，如 grep 无匹配 → 直接加 pipefail 会
    # 制造新的假失败），故本测试只做**规模告警**：数量增长需人工复核新引入的步骤。
    BASELINE = 28
    TOLERANCE = 10

    def _pipe_without_pipefail(self):
        hits = []
        for f in sorted(WORKFLOWS_DIR.glob("*.yml")):
            try:
                d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            except Exception:
                continue
            for job in (d.get("jobs") or {}).values():
                for s in (job.get("steps") or []):
                    run = s.get("run") or ""
                    if "|" in run and "pipefail" not in run:
                        hits.append((f.name, s.get("name")))
        return hits

    def test_pipe_without_pipefail_not_growing(self):
        hits = self._pipe_without_pipefail()
        recent = hits[-8:]
        assert len(hits) <= self.BASELINE + self.TOLERANCE, (
            f"「有管道但无 pipefail」的步骤增至 {len(hits)} 个（基线 {self.BASELINE}）—— "
            "新步骤若用管道吞掉了退出码，请显式加 set -o pipefail，"
            f"或在本测试注释中说明该步骤的失败为何可忽略。尾部样本：{recent}"
        )
