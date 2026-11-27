# case_ids: KF-031, KF-032, KF-033, KF-034, KF-035
"""微信客服（kf）判定面的判据 + 红证（新能力面：`.github/cases/kf.yml` 的后 5 条 live 用例）。

## 这个文件锁什么

C 端 mini-app 已删（2026-11-26）⇒ 微信客服（kf）是 C 端**唯一主入口**，而它的判定链
（`KfDecisionService.decide` → `KfJudgeClient.judge` → `POST /api/internal/kf/judge` →
`app/api/kf_judge.py::judge_text`）在用例库里**零 LLM 级覆盖**（30 条全是 `[backend-contract]` 单测）。
本文件锁的是「**喂顾客消息 → 断言判定 JSON**」这一层（面本体 = `tests/agent_eval/kf_judge_face.py`）：

| # | 判据 | 会红的形态 |
|---|---|---|
| 1 | **形态单实现**：`.github/render_cases.py::exp_to_str` 与面**同一份**规范串；解析可逆 | 渲染器把 `kf_judge` 当工具名 / 吞掉 → 断言永不满足（且静默） |
| 2 | **接线到真实现**：面传输的路径 == ai-agent 真路由（`API_PREFIX` + `/internal/kf` + `/judge`），且该路由 handler 调 `judge_text` | 面接成 mock / 常量 / 死路径 |
| 3 | **输出随输入变化**：两条语义相反的输入（要人工 / 问价）⇒ `escalate` 必须不同 | 面被换成常量 `False`（= 空断言） |
| 4 | **失败关闭**：端点 `success=false` / 空 data / 不可达 / 空输入 ⇒ **判红并具名**，绝不静默 pass | 把「未评估」当通过 |
| 5 | **5 条新用例 live 且进 C 端集合**（`eval_case_filter` 的选择口径现取） | 用例被 skip / 挂错端 / 期望被吞 |
| 6 | **runner 真的在计分区间里走面**（源码区间判据） | 接线被拆掉 ⇒ 面期望回落到 chat 面匹配（恒红/空断言） |

## 红证（每条都先自证「变异已落下」，再证明判据会红）

见 `TestRedProofs`：注入走 `unit_ci_workflows.injection.inject`（锚点漂移/命中数不符 ⇒ 当场抛错，
不会静默空跑），每条注入后**先读回变异**（`mutated != src` + 具体锚点），再跑**同一个**判据本体。

## 边界（照实登记）

- 判据 3/4 的注入点是 **HTTP seam**（`transport=`），不是判定逻辑 —— 判定逻辑一行都没复制
  （复制即第二实现，会与产品实现漂移）；面**默认**传输是真的 `_http_transport`（判据 2 钉住）。
- **真 LLM 面**（模型对某句话到底给 `upset` 还是 `angry`）本文件判不了，也不派发：
  用户裁定 #4262「不自动验证、手动集中跑一次」⇒ 5 条用例只登记，等人工集中跑。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".github"))          # render_cases（用例单一源装载器）
sys.path.append(str(REPO_ROOT / "tests" / "agent_eval"))  # kf_judge_face / eval_case_filter

import kf_judge_face as face  # noqa: E402
import render_cases  # noqa: E402
from eval_case_filter import select_cases_for_persona  # noqa: E402
from unit_ci_workflows.injection import inject  # noqa: E402

FACE_PATH = REPO_ROOT / "tests" / "agent_eval" / "kf_judge_face.py"
RUNNER_PATH = REPO_ROOT / "tests" / "agent_eval" / "local_runner.py"
KF_CASES = REPO_ROOT / ".github" / "cases" / "kf.yml"

NEW_CASE_IDS = ("KF-031", "KF-032", "KF-033", "KF-034", "KF-035")


# ══════════════════════════════════════════════════════════════════════════════
# 夹具：从**给定源码**装载一个面模块（红证用；不改动工作树里的真文件）
# ══════════════════════════════════════════════════════════════════════════════
def load_face_from_source(tmp_path, src: str, name: str = "_kf_face_under_test"):
    path = tmp_path / (name + ".py")
    path.write_text(src, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: 真响应契约的两条**语义相反**样本（形状逐字取自 `make_response`）。
HUMAN_RAW = {"success": True, "data": {"intent": "human_request", "risk": "low",
                                       "emotion": "upset", "confidence": 0.9, "escalate": True}}
PRICE_RAW = {"success": True, "data": {"intent": "price", "risk": "none",
                                       "emotion": "calm", "confidence": 0.8, "escalate": False}}


def judge_with_raw(module, text: str, raw: dict) -> dict:
    """用**HTTP seam 双件**跑一次判定（判据 3/4 的被测对象 = 面的归一化 + 断言层）。"""
    return module.judge_message(text, base_url="http://judge.invalid", service_token="t",
                                transport=lambda _t, **_kw: raw)


# ══════════════════════════════════════════════════════════════════════════════
# 判据本体（纯函数；红证驱动**同一份**本体，不另写一份）
# ══════════════════════════════════════════════════════════════════════════════
def wiring_gaps(module) -> list:
    """判据 2：面传输的路径 == ai-agent 真路由，且该路由的 handler 调 `judge_text`。"""
    gaps = []
    judge_path = getattr(module, "JUDGE_PATH", None)
    if judge_path != "/api/internal/kf/judge":
        gaps.append("JUDGE_PATH != /api/internal/kf/judge（实得 %r）" % (judge_path,))
    api_dir = REPO_ROOT / "backend" / "ai-agent-service" / "app" / "api"
    router_src = (api_dir / "kf_judge.py").read_text(encoding="utf-8")
    if '@router.post("/judge")' not in router_src:
        gaps.append("app/api/kf_judge.py 里没有 @router.post(\"/judge\") —— 面指的端点不存在")
    if "judge_text(" not in router_src:
        gaps.append("app/api/kf_judge.py 的 handler 没调 judge_text —— 端点后面不是真实现")
    routes_src = (api_dir / "routes.py").read_text(encoding="utf-8")
    if "kf_judge_router" not in routes_src or 'prefix="/internal/kf"' not in routes_src:
        gaps.append("app/api/routes.py 没有把 kf_judge_router 挂到 /internal/kf")
    config_src = (REPO_ROOT / "backend" / "ai-agent-service" / "app" / "config.py").read_text(
        encoding="utf-8")
    if 'API_PREFIX: str = "/api"' not in config_src:
        gaps.append("app/config.py 的 API_PREFIX 不是 /api —— 面的绝对路径会偏")
    return gaps


def escalation_varies(module) -> tuple:
    """判据 3：两条语义相反的输入 ⇒ `escalate` 必须不同（否则面 = 常量）。

    ⚠️ 两条文本必须**真的相反**且都命中现实现口径：要人工（escalate true）/ 问价（false）。
    """
    human = judge_with_raw(module, "我要人工，叫你们老板来", HUMAN_RAW)
    price = judge_with_raw(module, "这个雪尼尔多少钱一米", PRICE_RAW)
    if not (human.get("available") and price.get("available")):
        return False, "判定面未产出（human=%r price=%r）" % (
            human.get("skip_reason"), price.get("skip_reason"))
    a = human["judgment"]["escalate"]
    b = price["judgment"]["escalate"]
    if a == b:
        return False, ("两条语义相反的输入得到同一个 escalate=%s ⇒ 面把输入吞了"
                       "（等价于常量，断言永不失败）" % (a,))
    return True, "escalate 随输入变化：要人工=%s / 问价=%s" % (a, b)


def fail_closed_ok(module) -> tuple:
    """判据 4：端点 `success=false` ⇒ 面「未评估」，断言**不许**通过（不静默 pass）。"""
    unavailable_raw = {"success": False,
                       "data": None,
                       "error": {"code": "KF_JUDGE_UNAVAILABLE", "message": "语义判定不可用，请按规则回退"}}
    outcome = judge_with_raw(module, "你们这什么破质量，气死我了", unavailable_raw)
    if outcome.get("available"):
        return False, "端点 success=false 却被读成 available=True（把「判定没跑」当成了判定结果）"
    if "KF_JUDGE_UNAVAILABLE" not in str(outcome.get("skip_reason") or ""):
        return False, "skip_reason 没有带出端点错误码：%r" % (outcome.get("skip_reason"),)
    ok, detail = module.check({"escalate": False}, outcome)
    if ok:
        return False, "端点失败时 escalate=false 的期望被判通过 ⇒ 静默 pass（最坏形态）"
    if "kf_judge_unavailable" not in detail:
        return False, "判红但没具名（detail=%r）" % (detail,)
    # 空输入同样必须「未评估」，不能当成一条合法的判定
    empty = module.judge_case_inputs([])
    if empty.get("available"):
        return False, "空输入被当成判定跑了（available=True）"
    return True, "端点失败/空输入 ⇒ 未评估且判红，具名 kf_judge_unavailable"


def scoring_region(src: str) -> str:
    """runner 的**计分区间**（`scoring_checks` 构造 → `total_exp` 计算）；锚点漂移 ⇒ 判「无法判定」。"""
    start = src.find("scoring_checks = list(case.expectations or [])")
    end = src.find("total_exp = len(scoring_checks)", start)
    if start < 0 or end <= start:
        return ""
    return src[start:end]


def runner_wiring_gaps(src: str) -> list:
    """判据 6：kf 判定面的四个调用点必须**落在计分区间内**（不是注释/死代码）。"""
    region = scoring_region(src)
    if not region:
        return ["runner 的计分区间定位失败（锚点漂移 ⇒ 判据无法判定，按红处理）"]
    required = (
        "kf_judge_face.is_face_expectation(exp)",
        "kf_judge_face.parse_expectation(exp)",
        "kf_judge_face.check(",
        "await kf_judge_face.judge_case_inputs_async(",
    )
    return [tok for tok in required if tok not in region]


def new_cases_by_id() -> dict:
    return {str(c.get("id")): c for c in render_cases.load_case_dicts(str(KF_CASES.parent))}


# ══════════════════════════════════════════════════════════════════════════════
# 判据 1：形态单实现
# ══════════════════════════════════════════════════════════════════════════════
class TestExpectationShape:
    def test_renderer_shares_the_face_formatter(self):
        spec = {"escalate": False, "intent": "price"}
        rendered = render_cases.exp_to_str({"kf_judge": spec})
        assert rendered == face.render_expectation(spec), (
            "渲染器与面各写一份格式 ⇒ 两处必然漂移（渲染 / 装载 / runner 必须同一份）")
        assert rendered.startswith("kf_judge(")
        assert face.parse_expectation(rendered) == spec

    def test_renderer_keeps_tool_expectations_untouched(self):
        assert render_cases.exp_to_str({"tool": "direct_reply"}) == "direct_reply"
        assert render_cases.exp_to_str({"tool": "product_search", "args": {"q": "布"}}) == (
            "product_search(q=布)")
        assert face.parse_expectation("direct_reply") is None
        assert face.parse_expectation({"tool": "product_search"}) is None

    def test_empty_spec_is_red_not_silent(self):
        ok, detail = face.check({}, {"available": True, "judgment": {"escalate": False}})
        assert ok is False
        assert "空断言" in detail

    def test_unsupported_field_is_named(self):
        ok, detail = face.check({"escalatee": True}, {"available": True,
                                                     "judgment": {"escalate": True}})
        assert ok is False
        assert "escalatee" in detail

    def test_field_level_assertion_names_every_gap(self):
        outcome = {"available": True, "judgment": {"escalate": True, "intent": "after_sales",
                                                  "risk": "high", "emotion": "angry",
                                                  "confidence": 0.4}}
        ok, detail = face.check({"escalate": False, "intent": "price", "emotion": ["calm"],
                                 "confidence_min": 0.5}, outcome)
        assert ok is False
        for token in ("escalate 期望 False 实得 True", "intent 期望 'price' 实得 'after_sales'",
                      "emotion 期望", "confidence=0.4 < 0.5"):
            assert token in detail, "判红没具名：%r 缺 %r" % (detail, token)

    def test_one_of_emotion_accepts_both_negative_values(self):
        for emotion in ("upset", "angry"):
            ok, detail = face.check({"emotion": ["upset", "angry"]},
                                    {"available": True, "judgment": {"emotion": emotion}})
            assert ok is True, detail

    def test_message_text_takes_the_last_customer_turn(self):
        assert face.message_text(["第一句", "最后一句"]) == "最后一句"
        assert face.message_text([{"text": "带图的最后一句", "images": ["u"]}]) == "带图的最后一句"
        assert face.message_text([]) == ""


# ══════════════════════════════════════════════════════════════════════════════
# 判据 2：接线到真实现（不是 mock / 常量 / 死路径）
# ══════════════════════════════════════════════════════════════════════════════
class TestRealImplementationWiring:
    def test_face_points_at_the_real_judge_route(self):
        assert wiring_gaps(face) == []

    def test_default_transport_is_http_not_a_constant(self):
        import inspect
        src = inspect.getsource(face)
        assert "urllib.request" in src
        assert "transport or _http_transport" in src, (
            "默认传输必须真的是 HTTP；缺省走常量/空实现 = 面不接真实现")
        assert "SERVICE_TOKEN" in src


# ══════════════════════════════════════════════════════════════════════════════
# 判据 3 / 4：判别力 + 失败关闭（正例）
# ══════════════════════════════════════════════════════════════════════════════
class TestDiscriminatesAndFailsClosed:
    def test_escalation_varies_with_input(self):
        ok, detail = escalation_varies(face)
        assert ok is True, detail

    def test_failure_never_passes(self):
        ok, detail = fail_closed_ok(face)
        assert ok is True, detail


# ══════════════════════════════════════════════════════════════════════════════
# 判据 5：5 条新用例 live 且进 C 端集合
# ══════════════════════════════════════════════════════════════════════════════
class TestNewCases:
    def test_all_new_cases_exist(self):
        cases = new_cases_by_id()
        missing = [cid for cid in NEW_CASE_IDS if cid not in cases]
        assert missing == [], "新用例号没落进 .github/cases/kf.yml：%s" % missing

    def test_new_cases_are_live_llm_assertions(self):
        cases = new_cases_by_id()
        for cid in NEW_CASE_IDS:
            c = cases[cid]
            assert str(c.get("skip_reason") or "") == "", (
                "%s 必须 live（skip_reason 非空 ⇒ 不进 agent-eval = 仍然是零覆盖）" % cid)
            assert str(c.get("persona") or "") == "xiaobu", (
                "%s 是 C 端（米宝）主入口用例，persona 必须显式声明（缺省=双端会被 B 端腿跑）" % cid)
            assert str(c.get("tier") or "") == "normal"
            specs = [face.parse_expectation(e) for e in (c.get("expectations") or [])]
            specs = [s for s in specs if isinstance(s, dict)]
            assert specs, "%s 没有任何 kf_judge 判定面期望（= 空断言）" % cid
            for spec in specs:
                assert spec, "%s 有一条空 kf_judge 期望（空断言）" % cid
            # 用例的机器证据链必须指向本文件（真会跑、真会被收集）
            traces = (c.get("traces") or {}).get("tests") or []
            assert "tests/unit_ci_workflows/test_kf_judge_face.py" in traces, (
                "%s 的 traces.tests 没接本判据文件：%s" % (cid, traces))

    def test_new_cases_are_selected_for_the_c_end_leg(self):
        cases = list(new_cases_by_id().values())
        selected = {str(c.get("id")) for c in select_cases_for_persona(cases, "xiaobu")}
        assert set(NEW_CASE_IDS) <= selected, (
            "新用例没进 C 端集合（harness 永远不会跑它们）：缺 %s" % sorted(set(NEW_CASE_IDS) - selected))


# ══════════════════════════════════════════════════════════════════════════════
# 判据 6：runner 计分区间内真的走面
# ══════════════════════════════════════════════════════════════════════════════
class TestRunnerWiring:
    def test_runner_scores_face_expectations(self):
        src = RUNNER_PATH.read_text(encoding="utf-8")
        assert runner_wiring_gaps(src) == []


# ══════════════════════════════════════════════════════════════════════════════
# 红证（每条：注入 → 自证变异落下 → 同一判据本体必须红且具名）
# ══════════════════════════════════════════════════════════════════════════════
class TestRedProofs:
    def test_constant_false_escalate_turns_the_criterion_red(self, tmp_path):
        """面被换成**常量 escalate=False** ⇒ 判据 3 具名红（= 空断言会被抓住）。"""
        src = FACE_PATH.read_text(encoding="utf-8")
        mutated = inject(
            src,
            '        "escalate": bool(data.get("escalate")),',
            '        "escalate": False,  # 变异：面被换成常量 False',
            where="tests/agent_eval/kf_judge_face.py",
        )
        assert mutated != src, "变异没落下（注入等于没做）"
        assert "变异：面被换成常量 False" in mutated
        broken = load_face_from_source(tmp_path, mutated)
        ok, detail = escalation_varies(broken)
        assert ok is False, "面被换成常量 False 后判据仍绿 ⇒ 判据没有牙"
        assert "escalate" in detail, "判红没具名 escalate：%r" % (detail,)

    def test_silent_pass_mutation_turns_the_fail_closed_criterion_red(self, tmp_path):
        """把「未评估」改成「常量通过」⇒ 判据 4 具名红（最坏形态：没跑却算过）。"""
        src = FACE_PATH.read_text(encoding="utf-8")
        mutated = inject(
            src,
            '    return {"available": False, "skip_reason": "%s: %s" % (UNAVAILABLE_PREFIX, reason)}',
            '    return {"available": True, "judgment": {"escalate": False, "intent": "other",\n'
            '                                              "risk": "none", "emotion": "calm",\n'
            '                                              "confidence": 1.0}}  # 变异：静默 pass',
            where="tests/agent_eval/kf_judge_face.py",
        )
        assert mutated != src, "变异没落下（注入等于没做）"
        assert "变异：静默 pass" in mutated
        broken = load_face_from_source(tmp_path, mutated)
        ok, detail = fail_closed_ok(broken)
        assert ok is False, "「未评估」被改成通过后判据仍绿 ⇒ 失败关闭是空话"
        assert "静默 pass" in detail or "success=false" in detail, "判红没具名：%r" % (detail,)

    def test_dead_route_mutation_turns_the_wiring_criterion_red(self, tmp_path):
        """面的路径改成不存在的端点 ⇒ 判据 2 具名红。"""
        src = FACE_PATH.read_text(encoding="utf-8")
        mutated = inject(
            src,
            'JUDGE_PATH = "/api/internal/kf/judge"',
            'JUDGE_PATH = "/api/internal/kf/judge-mock"  # 变异：死路径',
            where="tests/agent_eval/kf_judge_face.py",
        )
        assert mutated != src, "变异没落下（注入等于没做）"
        broken = load_face_from_source(tmp_path, mutated)
        gaps = wiring_gaps(broken)
        assert gaps, "路径被改成死路径后判据仍绿 ⇒ 接线判据没有牙"
        assert "judge-mock" in gaps[0], "判红没具名死路径：%r" % (gaps,)

    def test_runner_wiring_removal_turns_the_criterion_red(self):
        """把 runner 的 kf 面分支拆掉 ⇒ 判据 6 具名红（面期望会回落到 chat 面匹配）。"""
        src = RUNNER_PATH.read_text(encoding="utf-8")
        mutated = inject(
            src,
            "        if kf_judge_face.is_face_expectation(exp):",
            "        if False:  # 变异：拆掉 kf 判定面接线",
            count=2,  # 计分区间 + `_assertions_fired_summary` 各一处（两处都必须按面归口）
            where="tests/agent_eval/local_runner.py",
        )
        assert mutated != src, "变异没落下（注入等于没做）"
        gaps = runner_wiring_gaps(mutated)
        assert gaps, "接线被拆掉后判据仍绿 ⇒ runner 接线判据没有牙"
        assert "kf_judge_face.is_face_expectation(exp)" in gaps, "判红没具名拆除点：%r" % (gaps,)