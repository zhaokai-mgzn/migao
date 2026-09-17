"""
LLM 熔断器作用域隔离（issue #3270）。

背景（2026-09-11 实证，本地 DEBUG 栈 + 真实 LLM）：
`app/graph/skills/base_skill.py` 用一个**全局常量**做熔断器名：

    LLM_BREAKER = "llm_minimax"          # 遗留名，与实际模型无关
    llm_breaker = get_breaker(LLM_BREAKER)   # 所有 skill 共用同一个实例

后果：任一 skill 的 LLM 连续 3 次超时（60s 阈值）→ 该**全局**熔断器 OPEN →
**全部** skill 的 LLM 调用被拒 → 用户侧统一看到 "抱歉，AI 服务暂时不可用，请稍后重试。"

实测日志：
    [circuit-breaker:llm_minimax] OPEN → HALF_OPEN | reason=recovery_timeout(30.0s)
    [circuit-breaker:llm_minimax] HALF_OPEN → OPEN | reason=probe failed: TimeoutError failures=4
    [customer_order][SLS] LLM circuit_breaker_open
    → assistant: 抱歉，AI 服务暂时不可用，请稍后重试。

C 端场景影响：查订单 / 下单 / 问知识 全部返回同一句兜底文案 —— 单点超时拖垮整机。
"""
# case_ids: DF-011, DF-012
import asyncio
import inspect
from pathlib import Path

import pytest

from app.core.circuit_breaker import (
    CircuitBreakerState,
    get_breaker,
    reset_breakers,
)

# ── 跟随式扫描：LLM 调用面的**搬迁家族**（issue #4049）──────────────────────────
# `base_skill.execute_skill` 的 1699 行按职责搬进了 `app/graph/skills/execution/`，
# 其中就包含 LLM 调用与熔断器取名的现场。任何"只扫 `base_skill.py`"的文本判据
# 都会在搬迁后**变成空跑但仍全绿**（§19.1「判据自己选择沉默」）⇒ 判据改为扫家族。
_SKILLS_DIR = Path(__file__).resolve().parents[2] / "app" / "graph" / "skills"
_BASE_SKILL_PY = _SKILLS_DIR / "base_skill.py"
_EXECUTION_DIR = _SKILLS_DIR / "execution"


def _skill_family_sources(execution_dir: Path = _EXECUTION_DIR) -> dict:
    """`base_skill.py` + `execution/*.py` 的源码（键=路径，值=全文）。

    fail-closed：文件/目录缺失、或家族里的实现文件不足 3 个（三段实现），一律**报错** ——
    不允许"扫不到就通过"（那正是本函数要消灭的空判据形态）。
    """
    if not _BASE_SKILL_PY.is_file():
        raise AssertionError(f"被扫目标不存在：{_BASE_SKILL_PY}（fail-closed，不静默跳过）")
    if not execution_dir.is_dir():
        raise AssertionError(f"拆分后的实现目录不存在：{execution_dir}（fail-closed）")
    exec_files = sorted(execution_dir.glob("*.py"))
    if len(exec_files) < 3:
        raise AssertionError(
            f"{execution_dir} 下的实现文件不足 3 个（实得 {[p.name for p in exec_files]}）"
            f"—— 家族扫描会静默漏掉搬走的 LLM 调用现场"
        )
    sources = {str(_BASE_SKILL_PY): _BASE_SKILL_PY.read_text(encoding="utf-8")}
    for path in exec_files:
        sources[str(path)] = path.read_text(encoding="utf-8")
    return sources


def _forbidden_literal_hits(literal: str, sources: dict) -> list:
    """家族里含 `literal` 的文件清单（空 = 判据通过）。抽成纯函数是为了能喂负例。"""
    return sorted(path for path, src in sources.items() if literal in src)


@pytest.fixture(autouse=True)
def _reset_registry():
    reset_breakers()
    yield
    reset_breakers()


class TestLLMBreakerScope:
    """每个 skill 必须拥有独立熔断器（防单点超时拖垮整机）"""

    def test_llm_breaker_name_is_per_skill(self):
        """llm_breaker_name(skill) 对不同 skill 返回不同名字"""
        from app.graph.skills.base_skill import llm_breaker_name

        names = {llm_breaker_name(s) for s in
                 ("customer_order", "customer_product", "customer_knowledge")}
        assert len(names) == 3, f"不同 skill 必须得到不同熔断器名，实得 {names}"

    def test_llm_breaker_name_stable_for_same_skill(self):
        """同一 skill 多次取名字必须稳定（否则熔断器每次都新建，熔断失效）"""
        from app.graph.skills.base_skill import llm_breaker_name

        assert llm_breaker_name("customer_order") == llm_breaker_name("customer_order")

    def test_llm_breaker_name_prefix_identifies_llm(self):
        """名字带统一前缀，便于日志/监控按 llm 维度聚合"""
        from app.graph.skills.base_skill import llm_breaker_name

        assert llm_breaker_name("customer_order").startswith("llm:")

    def test_legacy_global_name_no_longer_used(self):
        """遗留的全局常量 LLM_BREAKER 不得再被用作熔断器名（防回归）。

        ⚠️ 扫**搬迁家族**（`base_skill.py` + `execution/*.py`）而不是单文件：取熔断器的
        现场（`get_breaker(llm_breaker_name(...))`）已随第 7 节搬进 `execution/react_turn.py`，
        只扫 `base_skill.py` 会让这条判据变成**永远绿的空判据**（issue #4049）。
        """
        # 若保留该常量，必须不再参与 get_breaker 调用
        hits = _forbidden_literal_hits("get_breaker(LLM_BREAKER)", _skill_family_sources())
        assert hits == [], (
            f"仍有 get_breaker(LLM_BREAKER) 调用 —— 全局单一熔断器回归：{hits}"
        )

    @pytest.mark.asyncio
    async def test_one_skill_failure_does_not_open_other_skill_breaker(self):
        """核心契约：skill A 的 LLM 连续失败 → skill B 的熔断器仍 CLOSED"""
        from app.graph.skills.base_skill import llm_breaker_name

        async def boom():
            raise TimeoutError("llm slow")

        a = get_breaker(llm_breaker_name("customer_order"))
        for _ in range(3):
            with pytest.raises(TimeoutError):
                await a.call(boom)
        assert a.state == CircuitBreakerState.OPEN, "A 连续失败应 OPEN"

        b = get_breaker(llm_breaker_name("customer_product"))
        assert b.state == CircuitBreakerState.CLOSED, (
            "skill A 熔断不得影响 skill B —— 这正是 #3270 的整机降级根因"
        )

    @pytest.mark.asyncio
    async def test_other_skill_still_usable_after_first_opens(self):
        """skill A 熔断后，skill B 的 LLM 调用仍能成功（用户可见契约）"""
        from app.graph.skills.base_skill import llm_breaker_name

        async def boom():
            raise TimeoutError("llm slow")

        async def ok():
            return "fine"

        a = get_breaker(llm_breaker_name("customer_order"))
        for _ in range(3):
            with pytest.raises(TimeoutError):
                await a.call(boom)

        b = get_breaker(llm_breaker_name("customer_knowledge"))
        assert await b.call(ok) == "fine", "skill B 应仍可用"


class TestLLMTimeoutConfigurable:
    """LLM 调用超时不得硬编码 60s（慢模型/长 prompt 下必然误熔断）"""

    def test_timeout_is_module_level_constant(self):
        """超时应是模块级常量（可单测、可配置），不再散落两处字面量"""
        import app.graph.skills.base_skill as bs

        assert hasattr(bs, "LLM_CALL_TIMEOUT_S"), "缺 LLM_CALL_TIMEOUT_S 常量"
        assert isinstance(bs.LLM_CALL_TIMEOUT_S, (int, float))
        assert bs.LLM_CALL_TIMEOUT_S >= 60.0, (
            "LLM 超时阈值应 >= 60s（低于此值在 reasoning 模型 + 多工具 prompt 下误熔断）"
        )

    def test_no_hardcoded_timeout_literal(self):
        """源码中不得再出现 wait_for(..., timeout=60.0) 字面量。

        ⚠️ 扫**搬迁家族**：`asyncio.wait_for(..., timeout=LLM_CALL_TIMEOUT_S)` 的现场已随
        0~6 节（Vision 调用）与第 7 节（循环内调用）搬进 `execution/`，只扫 `base_skill.py`
        会让这条判据变成**永远绿的空判据**（issue #4049）—— 而它防的正是"把超时写死回去"。
        """
        hits = _forbidden_literal_hits("timeout=60.0", _skill_family_sources())
        assert hits == [], (
            f"仍有硬编码 timeout=60.0 —— 应改用 LLM_CALL_TIMEOUT_S：{hits}"
        )


class TestFamilyScanIsNotVacuous:
    """负例（§19.1）：跟随式扫描**真的会红**，不是"永远绿"的空判据。

    本包把 1699 行搬进 `execution/` 后，"只扫 `base_skill.py`"的判据会静默变成空跑 ——
    故这里钉住三件事：① 家族真的覆盖到搬走的实现文件；② 判据在**植入违规**时必报；
    ③ 家族扫描缺文件时 fail-closed 报错（而不是"扫不到就通过"）。
    """

    def test_family_covers_the_split_regions(self):
        sources = _skill_family_sources()
        exec_paths = sorted(p for p in sources if "execution" in p)
        assert len(exec_paths) >= 3, (
            f"家族扫描没覆盖拆出去的实现文件（实得 {exec_paths}）⇒ 判据会空跑"
        )

    def test_predicate_goes_red_on_a_planted_violation(self, tmp_path):
        """把含 `timeout=60.0` 的**临时文件**塞进被扫目录 ⇒ 判据必报（真负例）。"""
        fake_exec = tmp_path / "execution"
        fake_exec.mkdir()
        (fake_exec / "react_turn.py").write_text("x = 1\n", encoding="utf-8")
        (fake_exec / "prepare_turn.py").write_text("y = 2\n", encoding="utf-8")
        (fake_exec / "finalize_turn.py").write_text("z = 3\n", encoding="utf-8")
        planted = fake_exec / "react_turn.py"
        planted.write_text(
            "async def f():\n    return await asyncio.wait_for(g(), timeout=60.0)\n",
            encoding="utf-8")
        hits = _forbidden_literal_hits("timeout=60.0", _skill_family_sources(fake_exec))
        assert hits == [str(planted)], (
            f"植入违规后判据仍不报 —— 这是空判据：{hits}"
        )

    def test_family_scan_fails_closed_on_missing_regions(self, tmp_path):
        """实现文件不足 3 个 ⇒ 报错（不允许"扫不到就通过"）。"""
        fake_exec = tmp_path / "execution"
        fake_exec.mkdir()
        (fake_exec / "prepare_turn.py").write_text("x = 1\n", encoding="utf-8")
        with pytest.raises(AssertionError, match="不足 3 个"):
            _skill_family_sources(fake_exec)


class TestRegisteredSkillsGetDistinctBreakers:
    """集成级契约：真实注册的所有 skill 必须各自拥有独立熔断器"""

    def test_all_registered_skills_map_to_distinct_breakers(self):
        """遍历 skill_registry 注册的真实 skill，验证熔断器名两两不同。

        防止将来新增 skill 时误传固定名（如把 config.name 换成字面量）
        → 又退回「全局单一熔断器」。
        """
        from app.graph.skills.skill_registry import get_skill_registry
        from app.graph.skills.base_skill import llm_breaker_name

        registry = get_skill_registry()
        names = registry.get_names()
        assert len(names) >= 10, f"注册 skill 过少，疑似取错对象：{names}"

        breaker_names = [llm_breaker_name(n) for n in names]
        assert len(set(breaker_names)) == len(breaker_names), (
            f"存在共享熔断器名的 skill：{breaker_names}"
        )
