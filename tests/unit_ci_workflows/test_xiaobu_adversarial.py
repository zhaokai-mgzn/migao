# case_ids: DF-020, DF-021, DF-022, DF-023, CH-011, DF-002, DF-005, DF-011, DF-012, DF-013
"""C 端对抗面守卫（issue #3367，参考 B 端做法）。

背景：B 端有 `agent-eval-adversarial.yml`（每周跑、失败开 issue、只追踪不阻塞），
而 C 端 `xiaobu-acceptance.yml` 的 tier 长期只有 smoke|normal —— **对抗面从未在 C 端跑过**。
首跑基线（run 34724282450，12 条）：6/12，其中 5 条失败里有 3 条是"断言是 B 端机制形状"
（期望 `product_search`/`validate_input`/`confirm` 卡）而被 C 端正确行为判红 —— 例如
DF-007「冒充管理员」：C 端 Agent **拒绝并不调工具**是正确行为，却因为没有调 product_search 判 0 分。

本守卫锁两件事：
  1. C 端对抗集**不得退化为空**，且成员变化必须显式改这里（评测面是活资产，增减要过评审）；
  2. 已知的**B 端机制形状**用例不得回到 C 端可选集（它们的安全意图已由 C 端原生用例承接，
     见 DF-020/021/022），否则又会把"正确的拒绝"判成失败。
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".github"))
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))

import yaml  # noqa: E402
from render_cases import load_case_dicts  # noqa: E402
from eval_case_filter import select_cases_for_persona  # noqa: E402

CASES_DIR = REPO_ROOT / ".github" / "cases"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "xiaobu-acceptance.yml"

# C 端对抗面（现行 10 条）：7 条双端里符合 C 端语义的 + 3 条 C 端原生（DF-020/021/022）
EXPECTED_CEND_ADVERSARIAL = {
    "CH-011", "DF-002", "DF-005", "DF-011", "DF-012", "DF-013",
    "DF-020", "DF-021", "DF-022", "DF-023",
}

# 断言编码的是 B 端机制（工具层隔离/建品校验/批量删改），与 C 端正确行为不匹配。
# 它们的安全意图由 C 端原生用例承接，不得再被选进 C 端：
BEND_SHAPED_ADVERSARIAL = {
    "CH-001",   # suggestion 必须含 product_search → C 端版本 DF-022
    "DF-003",   # 创建商品（商户动作）
    "DF-006",   # 期望 product_search（工具层隔离）→ C 端版本 DF-021
    "DF-007",   # 期望 product_search（角色越权靠工具层拦）→ C 端版本 DF-020
    "DF-008",   # 批量下架/删客户（商户动作）
    "DF-010",   # 第二条期望 validate_input 是 B 端建品校验 → C 端版本 DF-023
}


def _cend_adversarial() -> set:
    selected = select_cases_for_persona(load_case_dicts(str(CASES_DIR)), "xiaobu")
    return {
        c["id"] for c in selected
        if str(c.get("tier") or "").strip().lower() == "adversarial" and not c.get("skip_reason")
    }


class TestXiaobuAdversarialSurface:
    def test_cend_adversarial_set_is_frozen(self):
        got = _cend_adversarial()
        assert got, "C 端对抗集为空 —— 对抗部署被静默移除了？"
        assert got == EXPECTED_CEND_ADVERSARIAL, (
            "C 端对抗集发生变化（评测面增减必须显式改本表并说明理由）：\n"
            f"  新增: {sorted(got - EXPECTED_CEND_ADVERSARIAL)}\n"
            f"  移除: {sorted(EXPECTED_CEND_ADVERSARIAL - got)}"
        )

    def test_bend_shaped_adversarial_not_selectable_for_cend(self):
        leaked = sorted(_cend_adversarial() & BEND_SHAPED_ADVERSARIAL)
        assert not leaked, (
            f"B 端机制形状的对抗用例又进了 C 端可选集: {leaked} —— "
            "它们会把 C 端'正确的拒绝'判成失败（run 34724282450 实证）"
        )

    def test_cend_native_cases_have_refusal_assertions(self):
        """C 端原生对抗用例必须同时有**正向**断言（仍服务本人诉求），
        否则会退化成"一律拒绝"也能过的空壳。

        「不得执行写操作」的**机器形态**（issue #3544 收口批）：`forbidden_tools`
        （全程不得调用）**或** 旧写法 `expectations: "X 未被调用"`。前者是升级形态 ——
        旧的「未被调用」计分语义是「本轮没调用 + 任一轮满足即过」⇒ 多轮用例恒真；
        本守卫因此**接受两种形态**（而不是要求某一种），确保「拒绝面」始终有断言。
        """
        by_id = {c["id"]: c for c in load_case_dicts(str(CASES_DIR))}
        for cid in ("DF-020", "DF-021", "DF-022", "DF-023"):
            c = by_id[cid]
            assert c.get("persona") == "xiaobu", f"{cid} 应标 persona: xiaobu"
            exps = [str(e.get("tool")) if isinstance(e, dict) else str(e)
                    for e in (c.get("expectations") or [])]
            forbidden = [str(x.get("tool")) if isinstance(x, dict) else str(x)
                         for x in (c.get("forbidden_tools") or [])]
            assert forbidden or any("未被调用" in e for e in exps), (
                f"{cid} 缺『不得执行写操作』断言（forbidden_tools 或「未被调用」任一形态）")
            assert any("未被调用" not in e for e in exps), (
                f"{cid} 只有否定断言 → '什么都不做'也能过（空壳用例）"
            )
            assert c.get("forbidden_text"), f"{cid} 缺 forbidden_text（合规话术拦截）"


class TestAdversarialScheduleWiring:
    """对抗节拍与档位特判的守卫（issue #3367；**#4262 改判为「仅手动」**）。

    #4262（2026-09-18 用户裁定）删除了本 workflow 的每周 `schedule` ——
    「不要自动进行验证，都是重复的验证，白白消耗成本」：全仓自动真实 LLM 触发
    由 **3 条收敛为 1 条**（只留 `post-deploy-eval` 每周一 normal 全量）。

    但 #3367 的教训**不随之作废**：定时触发没有 inputs，若不把 `schedule` 特判成
    adversarial，就会落到默认 smoke ——「加了定时任务却什么都没测到」。故本类守两件事：
      ① 本 workflow **不得**有自动触发（防静默把定时加回来 = 把成本加回来）；
      ② 若将来恢复自动触发，**档位特判必须同时在场**（恢复时漏掉 = 原样重踩 #3367）。
    """

    def _wf(self) -> dict:
        return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))

    def _eval_run_body(self) -> str:
        steps = self._wf()["jobs"]["xiaobu-acceptance"]["steps"]
        return next((s.get("run") or "" for s in steps if "local_runner" in (s.get("run") or "")), "")

    def test_workflow_is_manual_only(self):
        on = self._wf().get(True) or self._wf().get("on") or {}
        auto = set(on.keys()) - {"workflow_dispatch"}
        assert not auto, (
            f"xiaobu-acceptance 仍有自动触发 {sorted(auto)} —— #4262 用户裁定"
            "「不要自动进行验证，都是重复的验证，白白消耗成本」⇒ 本 workflow 改为**仅手动**"
            "（对抗档需要时用 workflow_dispatch 传 tier=adversarial）。"
            "要恢复定时必须先拿用户裁定，并同步改 "
            "tests/unit_ci_workflows/test_behavior_eval_pr_thin.py 的白名单锁。"
        )

    def test_schedule_tier_special_case_survives_for_reenable(self):
        """#3367 的档位特判**必须留在原地**（#4262 删了定时，但它是恢复定时的前置条件）。"""
        body = self._eval_run_body()
        assert "github.event_name == 'schedule'" in body, (
            "`schedule` 档位特判被删了 —— 当前无定时所以不红，但**将来恢复自动触发时**"
            "会落到默认 smoke（每周白跑门禁档、对抗档永远不跑，issue #3367 原样复发）"
        )
        assert "'adversarial'" in body, "`schedule` 特判的档位必须仍是 adversarial"

    def test_manual_tier_still_wins(self):
        """手工派发时输入优先（否则没法手动跑 normal/smoke）。"""
        body = self._eval_run_body()
        i_inputs = body.find("github.event.inputs.tier")
        i_sched = body.find("github.event_name == 'schedule'")
        assert 0 <= i_inputs < i_sched, "手工输入必须排在定时特判之前（inputs 优先）"
