# case_ids: MC-391
"""「环境前置缺失」判定类（issue #9280）—— 红→绿判据。

## 症状（值级证据，run 46002922920 @16cdb5bcc，2026-11-27 21:0x +08）

```
mibao: ❌ PR-135 score=0.0
  must_succeed: product_image_generate 共 1 次调用**无一成功**（R1:IMAGE_GEN_UNAVAILABLE）
```

上一轮同一用例是 `IMAGE_SOURCE_MISSING`（种子主图没配），补上主图后**变成
`IMAGE_GEN_UNAVAILABLE`** ⇒ 链路前半段已通，卡点是**评测栈没配图生成凭证**。
该码语义逐字（`backend/ai-agent-service/app/tools/product_image_generate.py` 的模块 docstring）：
「`ImageGenerationUnavailable`（**未配置 Key / 开关关闭** / 模型接不了这类图生图请求）」。
⇒ 它是**环境前置**，既不是产品缺陷、也不是用例缺陷，但每轮都被记进
`deterministic_failures`（"必须处理的失败"），把判定结论污染成"agent 又坏了一条"。

## 本单落的判据（每条都能单独变红）

| # | 判据 | 红证（本文件里可执行） |
|---|---|---|
| ① | **声明 + 环境码** ⇒ 具名 `ENV_PREREQUISITE_MISSING`（含用例 id / 前置名 / 错误码），进 `completion.env_missing`，**不进** `deterministic_failures` | 改前 `completion_verdict` 无该键 ⇒ `KeyError` |
| ② | **未声明 + 同一环境码** ⇒ **仍判产品红**（落 `deterministic_failures`） | `test_red_proof_only_declared_cases_enjoy_the_class`：只放开「声明」这一个变量，同一条失败原文就从红变成环境缺失 |
| ③ | **声明了但换成非环境码**（`VALIDATION_ERROR`）⇒ 仍判红 | 单测直接喂非环境码 |
| ④ | **声明了、环境码在场，但另有**别的失败 ⇒ 仍判红（不许把无关产品缺陷洗成环境） | 单测喂 `other_issues` |
| ⑤ | 声明 + 环境码 + **跨 run 复发** ⇒ 仍是 `env_missing`，**不进** `systemic_recurrence`（否则下一轮又假红 —— 正是 PR-135 的形状） | 单测喂 `cross_run_recurrence` |
| ⑥ | **结论口径**：全部失败都是环境缺失 ⇒ `completion.ok` **可为 true**，但 `reason` **必须**显式写出「环境前置缺失 N 条…未验证」；`ok=false` 时也必须单列一节 —— 不许静默吞掉、不许从 `total` 里消失 | 单测断言 `reason` 原文 + `total/passed` |
| ⑦ | **消费侧**：`env_missing` 是**非阻塞**键（`scripts/eval_closeout.py`），但在 closeout 输出里有独立一行、逐条状态是「环境缺失（未验证）」（不是"已收口"） | 单测断言 render 原文 |
| ⑧ | **声明面接线**：`requires_env` 经 CI 的 YAML 装载路径（`load_cases_from_yaml`）与生成物渲染器（`_case_literal_lines`）都要活下来 —— 漏映射 = 声明形同虚设、用例照旧判产品红 | 漏映射 ⇒ 装载后为空 |
| ⑨ | **PR-135 真的用上了**：`.github/cases/product.yml` 的 PR-135 声明 `requires_env`，且**原 `must_succeed` 断言一字不动**（有凭证时仍必须真成功 —— 本类只改归因，不改门槛） | 删声明 ⇒ 本判据红；删 `must_succeed` ⇒ 本判据红 |

## 为什么用单测

`env_prerequisite_missing` / `completion_verdict` / `write_summary_json` 都是**纯函数**
（吃结果列表 / 断言原文），零 LLM / 零网络 / 零栈（`migao-dev-flow` §16.1：能下层不上层）。
⚠️ `local_runner` 有模块级 `import httpx`，而本目录 CI 只装 `pytest` + `pytest-xdist` + `pyyaml`
⇒ 用最小替身（与 `test_eval_blocked_vs_failed.py` 同形）。
"""
import json
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))
sys.path.append(str(REPO_ROOT / "scripts"))

import eval_closeout as ec  # noqa: E402


def _load_runner():
    """导入 `local_runner`（缺 httpx 时注入最小替身；一旦被调用即抛错）。"""
    try:
        import httpx  # noqa: F401
    except ImportError:                      # pragma: no cover - 本地 venv 有 httpx
        stub = types.ModuleType("httpx")

        class _AsyncClient:
            def __init__(self, *a, **k):
                raise RuntimeError("httpx 替身：本文件的单测不得真实发起 HTTP")

        stub.AsyncClient = _AsyncClient
        sys.modules.setdefault("httpx", stub)
    import local_runner as lr
    return lr


lr = _load_runner()

#: PR-135 的真实失败原文（run 46002922920 的逐字形态；`R1:` 前缀来自 `check_must_succeed` 的 detail 拼装）
FAIL_LINE = ("must_succeed: product_image_generate 共 1 次调用**无一成功**"
             "（R1:IMAGE_GEN_UNAVAILABLE）—— 调了 ≠ 成了")
ENV = "IMAGE_GEN_API_KEY"


def _issues(code: str) -> list:
    return [f"must_succeed: product_image_generate 共 1 次调用**无一成功**"
            f"（R1:{code}）—— 调了 ≠ 成了"]


# ══════════════════════════════════════════════════════════════════════════════
# ①~⑤ 判定本体（纯函数）
# ══════════════════════════════════════════════════════════════════════════════

class TestDetection:
    def test_declared_case_with_env_code_is_named_env_missing(self):
        """① 声明 + 环境码 ⇒ 具名（用例 id / 前置名 / 错误码三者都在串里）。"""
        msg = lr.env_prerequisite_missing("PR-135", [ENV], _issues("IMAGE_GEN_UNAVAILABLE"), [])
        assert msg.startswith("ENV_PREREQUISITE_MISSING: PR-135 依赖 IMAGE_GEN_API_KEY"), msg
        assert "IMAGE_GEN_UNAVAILABLE" in msg, msg
        assert "未验证" in msg, msg

    def test_undeclared_case_is_never_classified(self):
        """② 未声明 ⇒ 一条都不归此族（防「一切失败都赖环境」）。"""
        assert lr.env_prerequisite_missing("PG-999", [], _issues("IMAGE_GEN_UNAVAILABLE"), []) == ""
        assert lr.env_prerequisite_missing("PG-999", None, _issues("IMAGE_GEN_UNAVAILABLE"), []) == ""

    def test_red_proof_only_declared_cases_enjoy_the_class(self):
        """②（红证）只放开「有没有声明」这一个变量 ⇒ 同一条失败原文分流。

        这条就是「去掉『只认已声明用例』」的注入式红证：不动失败原文、不动错误码注册表，
        只把 `requires_env` 从 `[]` 改成 `[ENV]` ⇒ 归类结果从「无」变成「具名环境缺失」。
        """
        issues = _issues("IMAGE_GEN_UNAVAILABLE")
        undeclared = lr.env_prerequisite_missing("PG-999", [], issues, [])
        if_gate_removed = lr.env_prerequisite_missing("PG-999", [ENV], issues, [])
        assert undeclared == "", undeclared
        assert if_gate_removed.startswith(
            "ENV_PREREQUISITE_MISSING: PG-999 依赖 IMAGE_GEN_API_KEY"), if_gate_removed
        # 落到判定层：未声明的同码失败必须仍是**产品红**
        verdict = lr.completion_verdict([{
            "case_id": "PG-999", "score": 0.0, "classification": "reproducible",
            "env_prerequisite_missing": undeclared,
            "failed": [(issues[0], "case-level check")],
        }])
        assert verdict["deterministic_failures"] == ["PG-999"], verdict
        assert verdict["env_missing"] == [], verdict
        assert verdict["ok"] is False, verdict

    def test_declared_but_non_env_code_still_red(self):
        """③ 声明了但错误码不在该前置的已知环境码集合里 ⇒ 仍判红。"""
        assert lr.env_prerequisite_missing("PR-135", [ENV], _issues("VALIDATION_ERROR"), []) == ""

    def test_env_code_without_a_recognisable_code_stays_red(self):
        """配置错 / 从未调用（原文里没有错误码）不许洗成环境缺失（fail-closed）。"""
        assert lr.env_prerequisite_missing(
            "PR-135", [ENV], ["must_succeed: product_image_generate 从未被调用 → 没有发生任何写操作"], []) == ""
        assert lr.env_prerequisite_missing(
            "PR-135", [ENV], ["must_succeed: 配置缺 tool: {'x': 1}"], []) == ""

    def test_other_failures_block_the_env_classification(self):
        """④ 环境码在场、但还有**别的**失败 ⇒ 仍判红（不许连带洗白无关缺陷）。"""
        msg = lr.env_prerequisite_missing(
            "PR-135", [ENV], _issues("IMAGE_GEN_UNAVAILABLE"),
            ["forbidden_text: 回复含反模式词「做不到」"])
        assert msg == "", msg

    def test_unregistered_requirement_name_does_not_classify(self):
        """没登记进 `ENV_PREREQUISITE_CODES` 的前置名 ⇒ 没有已知环境码 ⇒ 不归类（不猜）。"""
        assert lr.env_prerequisite_missing(
            "PR-135", ["SOME_UNKNOWN_KEY"], _issues("IMAGE_GEN_UNAVAILABLE"), []) == ""

    def test_registry_codes_are_the_tool_docstrings_verbatim(self):
        """注册表不是自由文本：`IMAGE_GEN_API_KEY` 的码必须与工具实现里的对外码逐字一致。"""
        assert lr.ENV_PREREQUISITE_CODES[ENV] == ("IMAGE_GEN_UNAVAILABLE",)
        tool = (REPO_ROOT / "backend" / "ai-agent-service" / "app" / "tools"
                / "product_image_generate.py").read_text(encoding="utf-8")
        assert f'"{lr.ENV_PREREQUISITE_CODES[ENV][0]}"' in tool, "工具实现里取不到该错误码"


# ══════════════════════════════════════════════════════════════════════════════
# ⑥ 判定层：桶 / ok / reason（结论口径）
# ══════════════════════════════════════════════════════════════════════════════

def _env_result(cid="PR-135", **extra):
    r = {"case_id": cid, "score": 0.0, "classification": "reproducible",
         "env_prerequisite_missing": (f"ENV_PREREQUISITE_MISSING: {cid} 依赖 {ENV}，本栈未配置"
                                      f"（工具错误码 IMAGE_GEN_UNAVAILABLE）—— 该用例本轮**未验证**"),
         "failed": [(FAIL_LINE, "case-level check")]}
    r.update(extra)
    return r


class TestVerdict:
    def test_env_missing_is_not_a_must_fix_failure(self):
        """①⑥ 全部失败都是环境缺失 ⇒ ok=true、确定性失败为空，但 reason 里必须点名。"""
        v = lr.completion_verdict([_env_result()])
        assert v["deterministic_failures"] == [], v
        assert v["env_missing"] == ["PR-135"], v
        assert v["ok"] is True, v
        assert "环境前置缺失 1 条" in v["reason"], v["reason"]
        assert "PR-135" in v["reason"], v["reason"]
        assert "未验证" in v["reason"], v["reason"]
        # 不许从 total / passed 里悄悄消失（它确实跑了、也确实没通过）
        assert (v["total"], v["passed"]) == (1, 0), v

    def test_env_missing_survives_cross_run_recurrence(self):
        """⑤ 跨 run 复发仍落 env_missing（否则每轮都复发成 systemic ⇒ 又变成假红）。"""
        v = lr.completion_verdict([_env_result(
            cross_run_recurrence={"prior_count": 3, "prior_runs": ["1", "2", "3"]})])
        assert v["env_missing"] == ["PR-135"], v
        assert v["systemic_recurrence"] == [], v
        assert v["ok"] is True, v

    def test_env_missing_does_not_hide_a_real_failure(self):
        """④⑥ 同批里有一条真失败 ⇒ ok=false、真失败照旧落 deterministic，环境条目仍单列。"""
        v = lr.completion_verdict([
            _env_result(),
            {"case_id": "PG-013", "score": 0.0, "classification": "reproducible"},
        ])
        assert v["deterministic_failures"] == ["PG-013"], v
        assert v["env_missing"] == ["PR-135"], v
        assert v["ok"] is False, v
        assert "环境前置缺失 1 条" in v["reason"], v["reason"]

    def test_empty_results_return_point_declares_the_bucket(self):
        """两处 return 点键集同口径（早退分支漏一个桶 = 那条结论永远不出现）。"""
        early = lr.completion_verdict([])
        assert early["env_missing"] == [], early
        assert early["ok"] is False, early

    def test_env_key_is_not_a_blocking_bucket(self):
        """⑦ 与消费侧同源：`env_missing` 属非阻塞键（不进 `_BLOCKING_VERDICT_KEYS`）。"""
        assert "env_missing" not in lr._BLOCKING_VERDICT_KEYS
        assert "env_missing" in ec.NON_BLOCKING_VERDICT_KEYS


# ══════════════════════════════════════════════════════════════════════════════
# ⑦ 结论档：summary 独立一节 + closeout 不吞掉
# ══════════════════════════════════════════════════════════════════════════════

def _summary(results):
    path = REPO_ROOT / ".eval-test-artifacts" / "env-prerequisite-summary.json"
    path.parent.mkdir(exist_ok=True)
    lr.write_summary_json(str(path), "normal", "", results, elapsed_s=0.0)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    finally:
        path.unlink(missing_ok=True)


def _leg_summary(results, label="mibao"):
    cases = [{"id": r["case_id"], "score": r["score"], "classification": "reproducible",
              "pre_clean": []} for r in results]
    verdict = lr.completion_verdict(results)
    return {"label": label, "shard": "", "total": len(cases),
            "passed": sum(1 for c in cases if c["score"] >= 1.0),
            "failed": sum(1 for c in cases if c["score"] < 1.0),
            "avg_score": 0.0, "order_write_cases": 0, "write_cases_ok": 0,
            "cases": cases, "completion": verdict,
            "run_key": {"sha": "16cdb5bcc" + "0" * 31, "tier": "normal", "persona": label}}


def test_summary_json_carries_a_named_env_section():
    """⑥ summary 的 `completion.env_missing` 是独立键，且 `failure_reasons` 里是具名原文。"""
    s = _summary([_env_result()])
    completion = s["completion"]
    assert completion["env_missing"] == ["PR-135"], completion
    assert completion["ok"] is True, completion
    assert "环境前置缺失 1 条" in completion["reason"], completion["reason"]
    reason = completion["failure_reasons"]["PR-135"]
    assert reason.startswith("ENV_PREREQUISITE_MISSING: PR-135 依赖 IMAGE_GEN_API_KEY"), reason
    # 逐条条目也留痕（读的人不必回日志里翻）
    case = next(c for c in s["cases"] if c["id"] == "PR-135")
    assert case["env_prerequisite_missing"].startswith(
        "ENV_PREREQUISITE_MISSING: PR-135 依赖 IMAGE_GEN_API_KEY"), case


def test_closeout_is_not_blocking_but_never_silent():
    """⑦ closeout：不计阻塞、不算"已收口"，但输出里有独立一行 + 逐条状态。"""
    s = _leg_summary([_env_result()])
    # `case_ids` 显式给出（真实用法 = 派发侧的用例清单）：默认清单是「阻塞桶并集」，
    # 而本类**不是**阻塞桶 —— 那正是它必须另有一条可见通道的原因。
    res = ec.closeout([s], _green_run_steps(), [], ["PR-135"])
    leg = res["legs"]["mibao"]
    assert leg["env_missing"] == ["PR-135"], leg
    assert "PR-135" not in leg["blocking"], leg
    assert leg["ok"] is True, leg
    row = next(r for r in res["case_rows"] if r["case_id"] == "PR-135")
    assert row["verdict"] == "环境缺失（未验证）", row
    out = ec.render(res)
    assert "env_missing=1" in out, out
    assert "环境缺失（未验证）" in out, out
    assert res["exit_code"] == 0, res


def _green_run_steps():
    """一条已评测腿的步骤形状（名字逐字取自真实 run；只留被测实现消费的部分）。"""
    def leg(persona):
        return {"name": f"{persona} 行为回归（独立栈 + 真实 LLM）", "conclusion": "success",
                "status": "completed", "steps": [
                    {"name": "Set up job", "conclusion": "success", "status": "completed"},
                    {"name": "Checkout", "conclusion": "success", "status": "completed"},
                    {"name": "抑制判定", "conclusion": "success", "status": "completed"},
                    {"name": "Start local stack", "conclusion": "success", "status": "completed"},
                    {"name": f"Run {persona} normal（真实 LLM）", "conclusion": "success",
                     "status": "completed"},
                    {"name": "汇总打印", "conclusion": "success", "status": "completed"},
                    {"name": "判定（completion_verdict）", "conclusion": "success",
                     "status": "completed"},
                    {"name": "被抑制记录", "conclusion": "skipped", "status": "completed"},
                    {"name": "被取消记录", "conclusion": "skipped", "status": "completed"},
                ]}

    report = {"name": "部署后回归结论", "conclusion": "success", "status": "completed", "steps": [
        {"name": "结论打印", "conclusion": "success", "status": "completed"},
        {"name": "被抑制留档", "conclusion": "skipped", "status": "completed"},
        {"name": "被取消留档", "conclusion": "skipped", "status": "completed"},
    ]}
    return {"conclusion": "success", "status": "completed",
            "headSha": "16cdb5bcc" + "0" * 31, "event": "workflow_dispatch",
            "jobs": [leg("mibao"), report]}


# ══════════════════════════════════════════════════════════════════════════════
# ⑧⑨ 声明面接线 + PR-135 真的用上了
# ══════════════════════════════════════════════════════════════════════════════

def _write_case_yaml(tmp_path, extra: str) -> Path:
    d = tmp_path / "cases"
    d.mkdir()
    (d / "x.yml").write_text(
        "cases:\n"
        "  - id: TMP-1\n"
        "    title: t\n"
        "    tier: normal\n"
        "    user_inputs:\n"
        "      - \"你好\"\n" + extra,
        encoding="utf-8")
    return d


def test_yaml_loader_maps_requires_env(tmp_path):
    """⑧ CI 走的是 YAML 装载路径（`--cases .github/cases`）—— 漏映射 = 声明形同虚设。"""
    d = _write_case_yaml(tmp_path, '    requires_env:\n      - "IMAGE_GEN_API_KEY"\n')
    case = lr.load_cases_from_yaml(str(d))[0]
    assert list(getattr(case, "requires_env", []) or []) == ["IMAGE_GEN_API_KEY"], case


def test_renderer_emits_requires_env(tmp_path):
    """⑧ 生成物渲染器也要映射（本地读生成物路径看不出问题 = #3391/#3417 同款假绿）。"""
    sys.path.insert(0, str(REPO_ROOT / ".github"))
    import render_cases as rc

    cases = rc.load_case_dicts(str(_write_case_yaml(
        tmp_path, '    requires_env:\n      - "IMAGE_GEN_API_KEY"\n')))
    lines = "\n".join(rc._case_literal_lines(cases[0]))
    assert "requires_env=['IMAGE_GEN_API_KEY']" in lines, lines
    assert "requires_env: List[str]" in rc._schema_text(), "生成的 EvalCase 缺 requires_env 字段"


def test_run_case_hook_is_wired_and_lands_on_the_result():
    """接线判据：`run_case` 必须真的调判定、并把结论落进结果 dict（删任一环 ⇒ 本判据红）。

    为什么用静态面：`run_case` 要真 HTTP + 真栈才跑得起来（本目录零网络），而"判定函数写得对、
    却没人调用"正是本仓反复踩的**声明无消费**（#3836/#3391 同族）。三条断言分别钉住
    调用点的三个来源（用例字段 / 判定函数 / 结果键），任一处漂移即具名红。
    """
    src = (REPO_ROOT / "tests" / "agent_eval" / "local_runner.py").read_text(encoding="utf-8")
    assert "_env_missing = env_prerequisite_missing(" in src, "run_case 里没有调用判定（声明无消费）"
    assert 'getattr(case, "requires_env", None)' in src, "调用点没有读用例声明的 requires_env"
    assert '"env_prerequisite_missing": _env_missing,' in src, "结论没有落到结果 dict（判定层拿不到）"


def test_pr135_declares_requires_env_and_keeps_its_must_succeed():
    """⑨ 真实用例：PR-135 声明环境前置，**且原 `must_succeed` 断言一字不动**。"""
    sys.path.insert(0, str(REPO_ROOT / ".github"))
    import render_cases as rc

    cases = {c["id"]: c for c in rc.load_case_dicts(str(REPO_ROOT / ".github" / "cases"))}
    pr135 = cases["PR-135"]
    assert list(pr135.get("requires_env") or []) == ["IMAGE_GEN_API_KEY"], pr135.get("requires_env")
    assert pr135.get("must_succeed") == [{"tool": "product_image_generate"}], pr135.get("must_succeed")
    # 反向：这道门只该开给**声明了**环境前置的用例 —— 全库范围读数（不是恒定小量）
    declared = sorted(cid for cid, c in cases.items() if c.get("requires_env"))
    assert declared == ["PR-135"], declared
