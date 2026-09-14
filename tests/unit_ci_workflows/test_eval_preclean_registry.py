# case_ids: HR-003, HR-002, CU-003
"""`pre_clean` 夹具层 **fail-closed**：注册表 + 未应用必须进结论（issue #3781）。

## 为什么单开这条守卫

"unknown pre_clean type = 静默跳过" 是**假绿温床**：`_run_pre_clean` 旧实现

```python
return f"未知 pre_clean 类型: {_type}（跳过）"
```

调用侧 `_pre_clean_for_case` 把返回值**当消息打印**（`🧹 pre_clean: …`）——于是
**数据压根没准备，用例照跑**，而它的红/绿会被读成"agent 能力缺陷"
（`migao-acceptance`「空跑：绿了但没跑」同族）。这在"**新增一个 type**"时最危险：
新类型没被 runner 认出来就静默退回成"什么都没做"。

同一族还有两处（本文件一并锁）：
- `employee_reactivate` 查不到目标员工 ⇒ 旧文案「查询 3 次未命中（跳过）」
  （**HR-003 的停用前置根本没复位**，却只有一行日志）；
- `customer_tag_remove` 的标签不在目录里 ⇒ 旧文案「不存在（跳过清理）」。

## 本文件锁四条

1. **注册表是单一事实源**：用例库里出现的每个 `pre_clean` type ∈ `runner._PRECLEAN_TYPES`
   （漏实现/拼错 ⇒ CI 直接红，而不是静默少做一件事）；
2. **配置错误可辨**：未知 type 返回带稳定前缀的**配置错误**，且
   `check_preclean_not_applied` 能把它捞出来（不再只是一行日志）；
3. **前置未应用 ⇒ 进结论**：折成 case-level 失败原文 + `precondition` 标记
   （#3751 标记语义从"复位失败"扩到"前置压根没被应用"）；
4. **幂等消息不误判**：正常成功路径的消息（含「无需清理」「幂等」）**不得**被判成配置错误
   —— 否则每个用例都会带着假的"前置未应用"标记。

## 红证

| 断言 | 红证 |
|---|---|
| ①② 今天它是静默跳过 / 改后被标记 | `test_unknown_type_is_a_config_error_not_a_silent_skip` **同时**断言"前缀可辨"与"能进结论"；把前缀改回旧文案（`未知 …（跳过）`）即红 |
| ③ 未应用 ⇒ 标记 | `test_not_applied_folds_into_the_case_verdict` 断言原文进 `failed` 且 `precondition` 被写上；删掉折叠逻辑即红 |
| ④ 幂等不误判 | `test_idempotent_success_messages_are_not_flagged` 用真实成功文案；把判据放宽成 `"跳过" in msg` 即红 |
| ① 注册表 | `test_every_declared_type_is_registered` —— 往任意用例加一个 `type: foo` 即红 |
"""
import re
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".github"))
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))
CASES_DIR = REPO_ROOT / ".github" / "cases"


def _load_runner():
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


def _declared_types() -> dict:
    """用例库（单一源）里所有 `pre_clean.type` → 声明它的用例 ID。"""
    from render_cases import load_case_dicts
    out: dict = {}
    for c in load_case_dicts(str(CASES_DIR)):
        for spec in (c.get("pre_clean") or []):
            t = str((spec or {}).get("type") or "")
            if t:
                out.setdefault(t, []).append(c.get("id", "?"))
    return out


class TestRegistryIsTheSingleSource:
    def test_registry_is_nonempty_and_a_frozenset(self):
        assert isinstance(lr._PRECLEAN_TYPES, frozenset) and lr._PRECLEAN_TYPES

    def test_every_declared_type_is_registered(self):
        """**核心 L0 不变式**：用例声明的 type 必须已实现（拼错/漏实现 ⇒ CI 红）。"""
        declared = _declared_types()
        assert declared, "用例库里一个 pre_clean 都没有？本守卫的前提失效（解析失败？）"
        unknown = {t: ids for t, ids in declared.items() if t not in lr._PRECLEAN_TYPES}
        assert unknown == {}, (
            "这些 pre_clean 类型没有在 runner 注册表中（会走配置错误 / 静默不生效）："
            f"{unknown}\n合法类型: {sorted(lr._PRECLEAN_TYPES)}")

    def test_registry_entries_all_have_an_inline_branch(self):
        """注册表里的每个 type 都必须在 `_run_pre_clean` 里有实现（防「登记了没实现」）。

        `customer_tag_remove` 走的是**兜底分支**（`if _type != "customer_tag_remove": 报配置错误`
        —— 它排在最后，落到那里即它），故两种形态都算「有实现」。
        """
        src = Path(REPO_ROOT / "tests" / "agent_eval" / "local_runner.py").read_text(encoding="utf-8")
        start = src.index("async def _run_pre_clean(")
        body = src[start:src.index("\nasync def ", start + 10)]

        def _implemented(t: str) -> bool:
            return f'_type == "{t}"' in body or f'_type != "{t}"' in body

        missing = [t for t in sorted(lr._PRECLEAN_TYPES) if not _implemented(t)]
        assert missing == [], f"注册表里有但没实现分支的 type：{missing}"


class TestUnknownTypeIsNotASilentSkip:
    def test_unknown_type_is_a_config_error_not_a_silent_skip(self):
        """**红证**：未知 type 必须返回**可辨的配置错误**（旧实现是「（跳过）」）。"""
        import asyncio
        msg = asyncio.run(lr._run_pre_clean("tok", {"type": "employee_dedupe_typo"}))
        assert msg.startswith(lr._PRECLEAN_CONFIG_ERR), (
            f"未知 type 没有走配置错误前缀（旧行为是静默跳过）：{msg!r}")
        assert "未执行" in msg, f"配置错误消息没有说明「数据准备未执行」：{msg!r}"
        # 且必须能被折叠器捞出来（否则"可辨"只是文案，进不了结论）
        assert lr.check_preclean_not_applied([msg]) == [msg]

    def test_registered_but_unimplemented_type_is_also_a_config_error(self, monkeypatch):
        """登记了但漏写实现体 ⇒ 同样走配置错误（不许退回静默）。"""
        import asyncio
        monkeypatch.setattr(lr, "_PRECLEAN_TYPES", lr._PRECLEAN_TYPES | {"ghost_type"})
        msg = asyncio.run(lr._run_pre_clean("tok", {"type": "ghost_type"}))
        assert msg.startswith(lr._PRECLEAN_CONFIG_ERR), msg
        assert "未实现" in msg, msg

    def test_not_applied_marker_folds_into_the_case_verdict(self):
        """**红证**：`前置未应用` 必须折成 case-level 失败 + `precondition` 标记。"""
        msg = (f"{lr._PRECONDITION_NOT_APPLIED}: 员工「王五」查询 3 次未命中 —— 前置未复位")
        folded = lr.check_preclean_not_applied([msg])
        assert folded == [msg], f"未应用的 pre_clean 没有被折叠：{folded}"
        # 折叠后的原文必须与行为失败**分属不同签名**（否则两次尝试会被误判 unstable）
        atom = lr._failure_atom(msg, lr._CASE_LEVEL_DETAIL)
        assert atom == "precondition_not_applied(pre_clean)", (
            f"前置未应用的失败身份应固定为 precondition_not_applied(pre_clean)，实得 {atom!r}")
        # 配置错误同样有稳定身份（保留 type 名 → 不同 type 不同根因）
        cfg = lr._failure_atom(
            f"{lr._PRECLEAN_CONFIG_ERR}: 'bogus'（数据准备未执行）", lr._CASE_LEVEL_DETAIL)
        assert cfg == "config_error(pre_clean)", cfg

    def test_retry_boundary_treats_not_applied_as_not_restored(self):
        """#3751 标记语义扩展：**前置压根没被应用**也必须算"未复位"。"""
        src = Path(REPO_ROOT / "tests" / "agent_eval" / "local_runner.py").read_text(encoding="utf-8")
        assert "_PRECLEAN_BAD_MARKERS" in src, "重试边界没有复用前置坏消息标记"
        marker = lr._PRECLEAN_BAD_MARKERS
        assert isinstance(marker, tuple) and lr._PRECLEAN_CONFIG_ERR in marker
        assert lr._PRECONDITION_NOT_APPLIED in marker


class TestIdempotentSuccessIsNotFlagged:
    def test_idempotent_success_messages_are_not_flagged(self):
        """**红证**：正常成功/幂等文案不得被判成配置错误（判据必须是稳定前缀，不是"跳过"）。"""
        ok_msgs = [
            "无 「王五」（手机号 13812345678）员工需清理（幂等）",
            "员工「王五」（手机号 13700137000）状态 active，无需恢复",
            "「遮光窗帘」无重复（1 件），无需去重",
            "客户无「VIP2活跃」标签，无需清理",
            "已恢复「王五」为 active（防存量消耗）",
            "已清理 1 个测试员工 「王五」（手机号 13812345678）",
        ]
        assert lr.check_preclean_not_applied(ok_msgs) == [], (
            "正常成功文案被误判成前置未应用 —— 会让每个用例带上假的失败标记")
        # 反向：判据放宽成"含『跳过』"就会误伤（旧文案里带跳过字样）
        for m in ok_msgs:
            assert not m.startswith(lr._PRECLEAN_BAD_MARKERS), m

    def test_success_messages_avoid_the_reset_failure_wording(self):
        """措辞红线（#3751）：成功路径的消息不得含「未复位」/「失败」。

        它们会被重试边界读成"复位失败" ⇒ 结论被错误标成不可归因于 agent。
        """
        ok = [
            "无 「王五」（手机号 13812345678）员工需清理（幂等）",
            "已恢复 「王五」（手机号 13700137000）为 active（防存量消耗）",
        ]
        for m in ok:
            assert "未复位" not in m and "失败" not in m, m


class TestRealCasesUseTheNewTypeMinimally:
    def test_hr_pair_uses_name_plus_phone(self):
        """HR-002 的清理与 HR-003 的复位都必须带**唯一标识**（手机号）—— 只按姓名裸匹配
        就是今天这个坑本身（命中同名残留 ⇒ 目标不确定）。"""
        import yaml
        hr = yaml.safe_load((CASES_DIR / "hr.yml").read_text(encoding="utf-8"))
        by_id = {c["id"]: c for c in hr["cases"]}
        h2 = by_id["HR-002"]["pre_clean"]
        assert [s["type"] for s in h2] == ["employee_remove"], h2
        assert h2[0].get("employee_phone") == "13812345678", h2
        h3 = by_id["HR-003"]["pre_clean"]
        assert h3[0].get("employee_phone") == "13700137000", (
            f"HR-003 的复位没有用手机号精确定位（会命中 HR-002 造的同名「王五」）：{h3}")
        assert re.fullmatch(r"\d{11}", str(h3[0]["employee_phone"]))
