# case_ids: MC-012
"""统一评测入口 / 结论复用 / 空跑守卫（issue #3769，用户本轮裁定）。

## 用户裁定（本轮起生效）

> 「不要空跑消耗我的 token 成本了，务必优化研发模式和评测方式，尽量统一评测。」

三条落成**代码**（不靠文档约定 —— 文档约定拦不住派发）：

| 规则 | 判据 | 落点 |
|---|---|---|
| **A 统一入口** | `case_ids` 非空 **且** `purpose=determination` ⇒ **直接 fail** | `post-deploy-eval.yml` 的「派发合规守卫」步骤 → `.github/scripts/eval_dispatch_guard.sh MODE=ci` |
| **B 结论复用** | 键 `(sha, tier, case_ids, 用例库指纹, 跑批策略版本)` 命中 ⇒ **不跑**，引用旧 run | 同一脚本 `MODE=dispatch`；键由 `local_runner` 写进 summary 的 `run_key` |
| **C 空跑守卫** | 评测相关路径变更集为空 ⇒ **不派发**，打印 `⏭️ … 未跑（引用 <run_id>）` | 同一脚本 `MODE=dispatch` |

## 为什么"策略版本"必须机器可算

键里含"跑批策略版本"是为了让**放行口径/分类实现**一变就自动失去复用资格；若用手工 bump 的
常量，迟更/漏更本身就是假绿来源（拿旧结论当新策略的结论）。故 `policy_version` 由
`_COMPLETION_RELEASED_CLASSES` / `_classify_attempts` / `_failure_signature` 三者的**源码片段**
哈希而来（`tests/agent_eval/eval_policy_version.py`，stdlib-only，派发侧与 runner 共用同一实现）。

## 红证

· 策略版本：确定性（两次同值）+ 敏感性（改放行档 ⇒ 变值）；
· 复用：键命中 ⇒ 退出码 2 且给引用 run id；**策略版本不同 ⇒ 不命中**（不许复用过期结论）；
· 空跑：只改文档 ⇒ 退出码 2 且给引用 run id；有评测相关变更 ⇒ 退出码 0；
· 统一入口：判定用途 + 收窄 ⇒ 退出码 1（fail，不是 skip）。
"""
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD = REPO_ROOT / ".github" / "scripts" / "eval_dispatch_guard.sh"
POLICY = REPO_ROOT / "tests" / "agent_eval" / "eval_policy_version.py"
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))


def _load_runner():
    """导入 `local_runner`（缺 httpx 时注入最小替身，与 test_eval_summary_attribution 同形）。"""
    try:
        import httpx  # noqa: F401
    except ImportError:                      # pragma: no cover - 本地 venv 有 httpx
        stub = types.ModuleType("httpx")

        class _AsyncClient:
            def __init__(self, *a, **k):
                raise RuntimeError("httpx 替身：本文件的单测不得真实发起 HTTP")

        stub.AsyncClient = _AsyncClient
        sys.modules.setdefault("httpx", stub)
    import local_runner
    return local_runner


lr = _load_runner()


def _head_sha() -> str:
    out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
                         capture_output=True, text=True)
    return out.stdout.strip()


def _policy_version(path=None) -> str:
    out = subprocess.run([sys.executable, str(POLICY)] + (["--path", str(path)] if path else []),
                         capture_output=True, text=True, cwd=REPO_ROOT)
    return out.stdout.strip()


def _run_guard(env_extra: dict, timeout: int = 60):
    env = dict(os.environ)
    env.update({"REPO": "o/r", "PURPOSE": "determination", "EVAL_TIER": "normal"})
    env.update(env_extra)
    return subprocess.run(["bash", str(GUARD)], capture_output=True, text=True,
                          env=env, cwd=REPO_ROOT, timeout=timeout)


# ── ① 跑批策略版本：机器可算、确定、对策略改动敏感 ──────────────────────────

class TestPolicyVersion:
    def test_is_deterministic(self):
        assert _policy_version() == _policy_version() != ""

    def test_changes_when_release_policy_changes(self, tmp_path):
        """红证：把放行档从 {llm-noise} 改成 {llm-noise, unstable} ⇒ 版本必变。

        不变 = 键不会换 ⇒ 新旧策略的结论被当成等价的（**假绿**）。
        """
        src = (REPO_ROOT / "tests" / "agent_eval" / "local_runner.py").read_text(encoding="utf-8")
        anchor = '_COMPLETION_RELEASED_CLASSES = frozenset({"llm-noise"})'
        assert anchor in src, "锚点不存在 → 本红证是空断言"
        mutated = tmp_path / "local_runner_mutated.py"
        mutated.write_text(src.replace(anchor, '_COMPLETION_RELEASED_CLASSES = frozenset({"llm-noise", "unstable"})'),
                           encoding="utf-8")
        assert _policy_version(mutated) != _policy_version(), \
            "改了放行口径而策略版本没变 —— verdict ledger 会复用过期结论"

    def test_runner_uses_the_shared_helper(self):
        """单一实现：runner 必须 import 共用的 helper（否则两侧算法漂移）。"""
        src = (REPO_ROOT / "tests" / "agent_eval" / "local_runner.py").read_text(encoding="utf-8")
        assert "from eval_policy_version import policy_version" in src, \
            "runner 没复用 eval_policy_version.py —— 派发侧会算出不同的值（复用永远不命中或误命中）"


# ── ② summary 的 run_key：键的语义（收窄跑 ≠ 判定结论） ─────────────────────

class TestRunKeySemantics:
    def _write(self, tmp_path, *, case_ids_env=""):
        old = os.environ.get("GITHUB_SHA")
        os.environ["GITHUB_SHA"] = _head_sha()
        os.environ["EVAL_CASE_IDS_INPUT"] = case_ids_env
        try:
            out = tmp_path / "s.json"
            lr.write_summary_json(str(out), "normal", "",
                                  [{"case_id": "OR-016", "score": 1.0, "classification": "pass",
                                    "duration_s": 12.0}], elapsed_s=99.0)
            return json.loads(out.read_text(encoding="utf-8"))
        finally:
            if old is None:
                os.environ.pop("GITHUB_SHA", None)
            else:
                os.environ["GITHUB_SHA"] = old
            os.environ.pop("EVAL_CASE_IDS_INPUT", None)

    def test_key_carries_all_ledger_dimensions(self, tmp_path):
        k = self._write(tmp_path)["run_key"]
        for dim in ("sha", "tier", "case_ids", "cases_fingerprint", "policy_version", "persona"):
            assert dim in k, f"run_key 缺维度 {dim} —— 键不完整会让复用变成误命中"
        assert k["tier"] == "normal" and k["case_ids"] == ""
        assert k["policy_version"] == _policy_version(), "summary 里的策略版本与 helper 不一致"

    def test_narrowed_run_has_a_different_key(self, tmp_path):
        """红证：加 `--case-ids` 收窄 ⇒ 键必须不同（收窄跑不得顶替全库判定结论）。"""
        full = self._write(tmp_path)["run_key"]
        narrowed = self._write(tmp_path, case_ids_env="OR-016")["run_key"]
        assert full["case_ids"] == "" and narrowed["case_ids"] == "OR-016"
        assert full != narrowed, "收窄跑的键与全库跑相同 —— 定点小跑会被当成判定结论复用"

    def test_run_mode_records_purpose(self, tmp_path):
        """遥测要能把「判定用途真跑」与「定点小跑」分开计数。"""
        os.environ["EVAL_PURPOSE"] = "debug"
        try:
            k = self._write(tmp_path)["run_key"]
        finally:
            os.environ.pop("EVAL_PURPOSE", None)
        assert k["run_mode"] == "debug"
        assert self._write(tmp_path)["run_key"]["run_mode"] == "determination"


# ── ③ 派发守卫脚本：A/B/C 三条规则的真实行为（bash 真跑） ────────────────────

def _hooks(diff_files: str, candidates: str = "", artifacts: str = "",
           latest: str = "printf 424242"):
    return {
        "DIFF_CMD": f"printf '{diff_files}'",
        "RUNS_CMD": f"printf '{candidates}'",
        "ARTIFACT_CMD": artifacts or "false",
        "LATEST_CMD": latest,
    }


class TestDispatchGuardUnifiedEntry:
    """A：判定用途不得收窄（用户裁定：直接 fail）。"""

    def test_narrowed_determination_run_is_refused(self):
        r = _run_guard({"MODE": "ci", "CASE_IDS": "OR-016"})
        assert r.returncode == 1, f"A 违规未 fail（rc={r.returncode}）\n{r.stdout}"
        assert "派发不合规" in r.stdout and "全库" in r.stdout

    def test_full_run_passes_ci_mode(self):
        r = _run_guard({"MODE": "ci", "CASE_IDS": "", "EVAL_SHA": _head_sha()})
        assert r.returncode == 0, r.stdout

    def test_narrowed_debug_run_is_allowed(self):
        """debug 用途（定点复现）允许收窄 —— 规则拦的是"拿小跑当判定"，不是拦调试。"""
        r = _run_guard({"MODE": "ci", "CASE_IDS": "OR-016", "PURPOSE": "debug"})
        assert r.returncode == 0, r.stdout


class TestDispatchGuardEmptyRunGuard:
    """C：评测相关路径无变更 ⇒ 不派发，且必须给出可引用 run id。"""

    def test_docs_only_change_is_refused_with_citation(self):
        r = _run_guard({"EVAL_SHA": _head_sha(),
                        **_hooks("README.md\ndocs/wiki/CI-CD.md\n")})
        assert r.returncode == 2, f"只改文档却放行派发（rc={r.returncode}）\n{r.stdout}"
        assert "⏭️" in r.stdout and "未跑" in r.stdout, "「没跑」没有明确看起来像没跑"
        assert "424242" in r.stdout, "拒绝派发但没给出可引用的 run id（调用方无从复用）"

    def test_eval_relevant_change_is_allowed(self):
        r = _run_guard({"EVAL_SHA": _head_sha(),
                        **_hooks("tests/agent_eval/local_runner.py\n")})
        assert r.returncode == 0, f"评测相关改动被误拦（rc={r.returncode}）\n{r.stdout}"

    def test_unknown_diff_fails_open_as_unjudgeable(self):
        r = _run_guard({"EVAL_SHA": _head_sha(), "DIFF_CMD": "false"})
        assert r.returncode == 3, f"算不出变更集却当成'可以派发'（rc={r.returncode}）"


class TestDispatchGuardVerdictReuse:
    """B：同一 SHA 已有判定结论 ⇒ 不重复跑（真省钱点）。"""

    def _artifact_cmd(self, tmp_path, fixture_dir: Path) -> str:
        """把 fixture summary 放到守卫**默认的下载目录**里（与 `gh run download -D` 同路径）。

        这样测试锁的是"守卫能在 artifact 落盘后读到 run_key 并比对"，而不是某个临时路径约定。
        """
        return (f"mkdir -p /tmp/eval-ledger-%s-PERSONA && "
                f"cp {fixture_dir}/eval-summary-PERSONA.json /tmp/eval-ledger-%s-PERSONA/")

    def _make_fixtures(self, tmp_path, monkeypatch, *, case_ids_env=""):
        """用**真实的** `write_summary_json` 产出两个 persona 的汇总（不是手写桩）。"""
        monkeypatch.setenv("GITHUB_SHA", _head_sha())
        monkeypatch.setenv("EVAL_CASE_IDS_INPUT", case_ids_env)
        fixture = tmp_path / "fixture"
        fixture.mkdir(exist_ok=True)
        for persona in ("mibao", "xiaobu"):
            monkeypatch.setattr(lr, "PERSONA", persona)
            lr.write_summary_json(str(fixture / f"eval-summary-{persona}.json"), "normal", "",
                                  [{"case_id": "OR-016", "score": 1.0,
                                    "classification": "pass", "duration_s": 5.0}])
        return fixture

    def test_key_hit_refuses_and_cites_run(self, tmp_path, monkeypatch):
        fixture = self._make_fixtures(tmp_path, monkeypatch)
        r = _run_guard({"EVAL_SHA": _head_sha(),
                        **_hooks("tests/agent_eval/local_runner.py\n", candidates="7770001",
                                 artifacts=self._artifact_cmd(tmp_path, fixture))})
        assert r.returncode == 2, f"键命中却仍派发（rc={r.returncode}）\n{r.stdout}"
        assert "不重复跑" in r.stdout and "7770001" in r.stdout

    def test_narrowed_prior_run_does_not_satisfy_determination(self, tmp_path, monkeypatch):
        """红证：旧 run 是**收窄跑** ⇒ 不得被当作判定结论（键里 case_ids 非空）。"""
        fixture = self._make_fixtures(tmp_path, monkeypatch, case_ids_env="OR-016")
        r = _run_guard({"EVAL_SHA": _head_sha(),
                        **_hooks("tests/agent_eval/local_runner.py\n", candidates="7770002",
                                 artifacts=self._artifact_cmd(tmp_path, fixture))})
        assert r.returncode == 0, f"收窄跑的结论被当成判定结论复用（rc={r.returncode}）\n{r.stdout}"

    def test_stale_policy_version_does_not_satisfy_reuse(self, tmp_path, monkeypatch):
        """红证：策略版本不同 ⇒ 不命中（不许拿旧策略的结论顶新策略）。"""
        fixture = self._make_fixtures(tmp_path, monkeypatch)
        for persona in ("mibao", "xiaobu"):
            f = fixture / f"eval-summary-{persona}.json"
            d = json.loads(f.read_text(encoding="utf-8"))
            d["run_key"]["policy_version"] = "deadbeefdeadbeef"
            f.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        r = _run_guard({"EVAL_SHA": _head_sha(),
                        **_hooks("tests/agent_eval/local_runner.py\n", candidates="7770003",
                                 artifacts=self._artifact_cmd(tmp_path, fixture))})
        assert r.returncode == 0, f"策略版本不同却命中了复用（rc={r.returncode}）\n{r.stdout}"

    def test_failing_prior_run_does_not_satisfy_reuse(self, tmp_path, monkeypatch):
        """红证：旧 run 的 `completion.ok` 非 true ⇒ 不命中（不许拿"上次是红的"当结论）。"""
        fixture = self._make_fixtures(tmp_path, monkeypatch)
        for persona in ("mibao", "xiaobu"):
            f = fixture / f"eval-summary-{persona}.json"
            d = json.loads(f.read_text(encoding="utf-8"))
            d["completion"]["ok"] = False
            f.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        r = _run_guard({"EVAL_SHA": _head_sha(),
                        **_hooks("tests/agent_eval/local_runner.py\n", candidates="7770004",
                                 artifacts=self._artifact_cmd(tmp_path, fixture))})
        assert r.returncode == 0, f"上一次判定是红的却被当成可复用的结论（rc={r.returncode}）"


# ── ④ 接线：workflow 必须真的调用它（否则规则只在脚本里，没人执行） ──────────

class TestWorkflowWiring:
    def _wf(self):
        import yaml
        return yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "post-deploy-eval.yml")
                              .read_text(encoding="utf-8"))

    def test_purpose_input_declared(self):
        doc = self._wf()
        on = doc.get("on") or doc.get(True)
        inputs = on["workflow_dispatch"]["inputs"]
        assert "purpose" in inputs, "缺少 purpose 声明 —— 调用方无法声明「判定用途 vs 调试」"
        assert inputs["purpose"].get("default") == "determination", \
            "purpose 默认值不是 determination —— 默认路径必须是判定用途（全库跑）"

    def test_guard_step_runs_ci_mode_before_any_cost(self):
        steps = self._wf()["jobs"]["eval"]["steps"]
        idx = [i for i, s in enumerate(steps) if "派发合规守卫" in (s.get("name") or "")]
        assert len(idx) == 1, "「派发合规守卫」步骤不唯一"
        guard = steps[idx[0]]
        assert "eval_dispatch_guard.sh" in (guard.get("run") or ""), "守卫步骤没调用守卫脚本"
        assert (guard.get("env") or {}).get("MODE") == "ci", "守卫未以 MODE=ci 执行（会误跑派发侧的 B/C）"
        for cost_kw in ("Start local stack", "Install eval runner deps", "真实 LLM"):
            cost = [i for i, s in enumerate(steps) if cost_kw in (s.get("name") or "")]
            assert cost and idx[0] < cost[0], f"守卫排在成本步骤 {cost_kw!r} 之后 —— 拦不住浪费"

    def test_runner_receives_purpose_and_case_ids_input(self):
        """遥测/键要拿到用途与收窄输入（否则 run_key.run_mode 恒为默认值，计数分不开）。"""
        steps = self._wf()["jobs"]["eval"]["steps"]
        run_step = [s for s in steps if "真实 LLM" in (s.get("name") or "")][0]
        env = run_step.get("env") or {}
        assert "EVAL_PURPOSE" in env, "runner 未收到用途 —— run_key.run_mode 无法区分判定/调试"
        assert "EVAL_CASE_IDS_INPUT" in env, "runner 未收到收窄输入 —— run_key.case_ids 恒空（复用会误命中）"
