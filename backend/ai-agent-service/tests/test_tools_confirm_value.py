# case_ids: CH-010, OR-029, PR-025
"""confirmValue **单点派生**守卫（issue #4054；源头是「关联 #4043」的 S1 条）。

## 被测不变式（一句话）
**顾客看到并点击的卡值**（`interact` 工具 confirm 分支下发、点击后原样回传）与
**门禁侧的基准值**（`confirm_card_fields` + `confirm_value_for_fields` 那条路：
`app/api/chat.py` 补卡 / `execution/finalize_turn.py` 8.3b 补卡 / `_is_card_confirm_value`
的比对基准）必须来自**同一处派生** —— 契约模块 `app/tools/confirm_value.py`。

## 为什么单独立测（§19.1 形状判据）
本缺陷的形态是「**两处独立生成器**」：两侧各自自洽、各有测试，但**谁都不测"两侧相等"**。
任一侧改一行（前缀/分隔符/排序口径）⇒ 客户点了卡仍判「未确认」
（`_is_card_confirm_value` 是**精确**比对）⇒ 确认死循环、写操作落不了库，
而全量单测**全绿**。故本文件每条判据都必须能**真的红**：

  · ① **结构面** —— 全仓只有契约模块一处派生表达式（含"植入第二处生成器"负例）；
  · ② **绑定面** —— `interact` 的卡值在**调用期**取自契约模块（改其一字符 ⇒ 卡值跟着变）；
  · ③ **判据面** —— 只改一侧一个字符 ⇒ 「同源」判据必须报出错位（否则是空判据）；
  · ④ **口径面** —— 与**已删除的旧实现**（逐字抄录于本文件）逐字节同值；`#3406` 语义
    （同 facts 集合、字段顺序不同 ⇒ 同值）成立；合法形态（空 fields / 非 dict 项）不被误伤。

case_ids 选 `CH-010`（choice→form→**confirm** 交互链）/ `OR-029`（**确认卡点击后**写操作
必须真实执行）/ `PR-025`（B 端写操作必须先出确认卡再执行）：三条都是"卡值与门禁判据同源"
的**行为**承载用例 —— 本文件是它们的确定性层守卫（零 LLM）。
"""
import ast
import asyncio
import importlib
from pathlib import Path

import pytest

def _service_dir() -> Path:
    """向上找 `ai-agent-service` 根（含 `app/tools/interact.py` 的那一层）。

    为什么不写死 `parents[N]`：本文件按 qa-growth-gate 对 `app/tools/*.py` 的配套测试名
    约定放在 `tests/`（`tests/test_tools_<name>.py`），而 `tests/unit/` 下的同类守卫用
    `parents[2]` —— 写死层数会在移动文件时**静默扫错目录**（§19.1 形态）。找不到就报错
    （fail-closed），不猜。
    """
    for parent in Path(__file__).resolve().parents:
        if (parent / "app" / "tools" / "interact.py").is_file():
            return parent
    raise AssertionError(f"找不到 ai-agent-service 根目录（fail-closed）：{__file__}")


APP_DIR = _service_dir() / "app"
CONTRACT_PY = APP_DIR / "tools" / "confirm_value.py"
BASE_SKILL_PY = APP_DIR / "graph" / "skills" / "base_skill.py"

# 一批**真实形态**的字段：订单卡（items 归并）/ B 端写参数兜底 / 已含 label 与 value
FIELD_BATCH = [
    [{"label": "商品", "value": "遮光窗帘 米白 3米"}, {"label": "总价", "value": "¥528"}],
    [{"label": "收货人", "value": "张三"}, {"label": "手机号", "value": "13800138000"},
     {"label": "地址", "value": "杭州市余杭区"}],
    [{"label": "商品ID", "value": "p_001"}, {"label": "名称", "value": "遮光窗帘"},
     {"label": "价格", "value": "168.0"}, {"label": "状态", "value": "on_sale"}],
    [{"label": "商品", "value": "窗帘A、窗帘B"}, {"label": "数量", "value": "3、5"}],
    [{"label": "", "value": "无标签值"}],          # 空 label（#3962 归一后的边界形态）
    [{"label": "价格", "value": 168}],              # 非字符串 value
    ["字符串项"],                                    # 非 dict 项（R2 负例分支）
    [],
    None,
]
ARGS = {"product_id": "p_001", "name": "遮光窗帘", "price": "168"}


# ── 旧实现（**本 PR 删掉的那两份**，逐字抄自**拆前基线** `origin/main @2f55a8b3`：
#    `app/tools/interact.py` 第 421-430 行的内联派生，与 `app/graph/skills/base_skill.py`
#    第 2349-2360 行的 `confirm_value_for_fields`；合并后 origin/main 上这两段已不存在）──────
# 留在测试里作**口径锚**：新实现必须与之逐字节同值（口径不得变），
# 同时它也是"第二处生成器"的活标本（下面的漂移负例用它植入）。
def _legacy_confirm_value_for_fields(fields: list) -> str:
    _facts = []
    for _f in fields or []:
        if isinstance(_f, dict):
            _facts.append(f"{_f.get('label') or ''}={_f.get('value') or ''}")
        else:
            _facts.append(str(_f))
    if _facts:
        return "确认：" + "；".join(sorted(_facts))
    return ""


def _contract_module():
    """契约模块（唯一派生源）。"""
    return importlib.import_module("app.tools.confirm_value")


def _card_value(fields, ctx=None) -> str:
    """**卡值**：`interact` 工具 confirm 分支真正下发给顾客的 confirmValue。"""
    from app.tools.interact import InteractTool

    res = asyncio.run(InteractTool().execute(
        context=ctx, component="confirm", title="请确认操作", fields=fields))
    assert res.success, f"interact 发卡失败：{res.error}"
    return res.data["confirmValue"]


def _source_divergence(card_value_fn, gate_value_fn, fields) -> str:
    """「卡值 == 门禁侧基准值」**判据本体**（纯函数 ⇒ 可喂"植入的漂移"做红证）。

    返回 "" = 同源一致；非空 = 漂移描述（调用方 assert 它为空）。
    """
    card, gate = card_value_fn(fields), gate_value_fn(fields)
    if card != gate:
        return f"卡值 {card!r} ≠ 门禁侧基准值 {gate!r}（两处派生已漂移：顾客点了卡也过不了门禁）"
    return ""


def _mutant_of(real):
    """把派生**改一个字符**（前缀 `确认：`→`确认！`）—— 等价于"有人只改了一侧"。

    必须包住**被改之前**的函数对象（`real`）：若在被打补丁的那一侧内部再按名字取一次，
    就会自己递归（这正是"单点"的副作用 —— 名字只有一个，改它就是改全部）。
    """
    return lambda fields: real(fields).replace("确认：", "确认！", 1)


# ── ① 结构面：全仓只有一处派生表达式 ─────────────────────────────────────────
def _derivation_sites(source: str, filename: str = "<src>") -> list:
    """AST 找派生**表达式** `"确认：" + "；".join(...)` 的行号（不是找 "确认：" 字符串）。

    判据等价于命令行版本（issue #4054 判据）：
      `grep -c '确认：" *+ *"；"\\.join' app/tools/interact.py` 必须为 0，且全仓只剩契约模块一处。
    用 AST 而非 grep：`"确认："` 作为**话术前缀**在别处合法（工具描述/提示词），
    只有"前缀 + 分号 join"这个**表达式**才是派生逻辑。
    """
    tree = ast.parse(source, filename=filename)
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Add):
            continue
        left, right = node.left, node.right
        if not (isinstance(left, ast.Constant) and left.value == "确认："):
            continue
        if not (isinstance(right, ast.Call) and isinstance(right.func, ast.Attribute)
                and right.func.attr == "join"
                and isinstance(right.func.value, ast.Constant)
                and right.func.value.value == "；"):
            continue
        hits.append(node.lineno)
    return hits


def _read(path: Path) -> str:
    """读源码；文件缺失即**报错**（fail-closed，不给"扫不到就通过"留口子）。"""
    assert path.is_file(), f"被扫目标不存在：{path}（fail-closed，不静默跳过）"
    return path.read_text(encoding="utf-8")


def _app_derivation_sites(app_dir: Path = APP_DIR) -> dict:
    """`app/**/*.py` 里所有派生表达式站点 {相对路径: [行号]}（fail-closed）。"""
    assert app_dir.is_dir(), f"被扫源码目录不存在：{app_dir}（fail-closed，不静默放行）"
    out = {}
    for path in sorted(app_dir.rglob("*.py")):
        hits = _derivation_sites(_read(path), str(path))
        if hits:
            out[str(path.relative_to(app_dir))] = hits
    return out


class TestOnlyOneDerivationSite:
    """派生逻辑只此一处（否则门禁判据与卡值会各自漂移，且没有任何测试会红）。"""

    def test_derivation_expression_lives_only_in_the_contract_module(self):
        sites = _app_derivation_sites()
        assert list(sites) == ["tools/confirm_value.py"], (
            f"派生表达式 `\"确认：\" + \"；\".join(...)` 出现在 {sites} —— "
            f"应**只有** app/tools/confirm_value.py（多处 = 又会各自漂移）"
        )

    def test_interact_has_no_inline_derivation_left(self):
        """issue #4054 的单点判据：`interact.py` 的命中数必须为 0（旧内联版已删）。"""
        hits = _derivation_sites(_read(APP_DIR / "tools" / "interact.py"))
        assert hits == [], f"app/tools/interact.py 仍有独立派生逻辑（第 {hits} 行）"

    def test_scanner_reports_a_planted_second_generator(self, tmp_path):
        """负例（§19.1）：植入"第二处生成器" ⇒ **同一条扫描判据**必须报出来。

        没有这条，上面那条判据完全可能是"永远绿的空判据"。
        """
        planted = tmp_path / "app" / "tools" / "sneaky.py"
        planted.parent.mkdir(parents=True)
        planted.write_text(
            "_facts = ['a=1']\n"
            "confirmValue = \"确认：\" + \"；\".join(sorted(_facts))\n",
            encoding="utf-8")
        sites = _app_derivation_sites(tmp_path / "app")
        assert sites == {"tools/sneaky.py": [2]}, (
            f"植入第二处生成器后扫描仍报 {sites} —— 这是空判据"
        )


# ── ②③④ 绑定面 / 判据面 / 端到端 ────────────────────────────────────────────
class TestCardValueAndGateShareOneSource:
    """卡值与门禁侧基准值必须同源（顾客点卡 ⇒ 门禁判"已确认"）。"""

    def test_card_value_follows_the_contract_module_at_call_time(
            self, sample_tool_context, monkeypatch):
        """把契约模块的派生**改一个字符** ⇒ 卡值必须跟着变（=`interact` 无第二份派生）。"""
        real = _contract_module().confirm_value_for_fields
        monkeypatch.setattr(_contract_module(), "confirm_value_for_fields", _mutant_of(real))
        fields = _contract_module().confirm_card_fields(ARGS)
        card = _card_value(fields, ctx=sample_tool_context)
        assert card == _mutant_of(real)(fields), (
            f"契约模块改了字符而卡值没跟着变：卡值 {card!r} vs 契约模块 {_mutant_of(real)(fields)!r}"
            f" —— interact 侧仍自带一份派生"
        )
        assert card != real(fields), "卡值没有随契约模块变动，判据是空的"

    def test_gate_side_re_export_is_the_same_function_object(self):
        """`base_skill` 再导出的必须是**同一个函数对象**（不是"抄了一份一样的"）。"""
        base = importlib.import_module("app.graph.skills.base_skill")
        contract = _contract_module()
        for name in ("confirm_card_fields", "confirm_value_for_fields"):
            obj = getattr(base, name, None)
            assert callable(obj), f"{name} 从 base_skill 取不到 / 不可调用（再导出没接上）：{obj!r}"
            assert obj is getattr(contract, name), (
                f"base_skill.{name} 不是契约模块的同一个对象 —— 又出现了第二份实现"
            )

    def test_card_value_passes_the_confirmation_gate(self, sample_tool_context):
        """端到端：卡值 == 门禁侧基准值，且门禁**接受**它；改一个字符则**拒绝**。"""
        base = importlib.import_module("app.graph.skills.base_skill")
        fields = _contract_module().confirm_card_fields(ARGS)
        card = _card_value(fields, ctx=sample_tool_context)
        gate_value = base.confirm_value_for_fields(fields)
        assert _source_divergence(lambda f: card, lambda f: gate_value, fields) == "", (
            f"卡值 {card!r} 与门禁基准值 {gate_value!r} 不等 ⇒ 顾客点了卡也判「未确认」"
        )
        assert base._is_card_confirm_value(card, gate_value) is True, (
            "门禁没有把「顾客点卡回传的原文」判为已确认"
        )
        assert base._is_card_confirm_value(card.replace("确认：", "确认！", 1), gate_value) is False, (
            "门禁是精确比对（改一个字符必须不认）—— 否则这条判据没有判别力"
        )

    def test_divergence_criterion_reports_one_character_drift(
            self, sample_tool_context, monkeypatch):
        """**红证**：只改一侧一个字符 ⇒ 「同源」判据必须报出错位（不是空判据）。

        这正是本缺陷的形态：两处生成器各自自洽，任一侧改一行就漂移。
        上面那条正向用例（漂移为 ""）与本条（漂移非 ""）一绿一红 ⇒ 判据有判别力。
        """
        real = _contract_module().confirm_value_for_fields
        monkeypatch.setattr(_contract_module(), "confirm_value_for_fields", _mutant_of(real))
        fields = _contract_module().confirm_card_fields(ARGS)
        msg = _source_divergence(
            lambda f: _card_value(f, ctx=sample_tool_context), real, fields)
        assert msg != "", "植入一个字符的漂移后判据仍报「无漂移」—— 这是空判据"


# ── ④ 口径面：与旧实现逐字节同值 + #3406 + R2 负例 ───────────────────────────
class TestValueSemanticsUnchanged:
    """搬迁**不得**改口径（issue #4054 硬约束）。"""

    @pytest.mark.parametrize("fields", FIELD_BATCH, ids=range(len(FIELD_BATCH)))
    def test_matches_the_legacy_implementation_byte_for_byte(self, fields):
        new = _contract_module().confirm_value_for_fields(fields)
        old = _legacy_confirm_value_for_fields(fields)
        assert new == old, f"新实现 {new!r} ≠ 旧实现 {old!r}（口径被改了）"
        assert new.encode("utf-8") == old.encode("utf-8"), "逐字节不等（编码层也不许变）"

    def test_field_order_does_not_change_value(self):
        """`#3406` 语义：同 facts 集合、字段顺序不同 ⇒ 同值（否则顾客点击仍会不中）。"""
        a = _contract_module().confirm_value_for_fields(
            [{"label": "商品", "value": "窗帘"}, {"label": "总价", "value": "¥528"}])
        b = _contract_module().confirm_value_for_fields(
            [{"label": "总价", "value": "¥528"}, {"label": "商品", "value": "窗帘"}])
        assert a == b, f"字段顺序变了值就变：{a!r} vs {b!r}"

    def test_empty_fields_yield_empty_string(self):
        """R2 阴性负例：空 fields（含 None）⇒ **空串**（不误伤、不抛错）。"""
        assert _contract_module().confirm_value_for_fields([]) == ""
        assert _contract_module().confirm_value_for_fields(None) == ""

    def test_non_dict_items_fall_back_to_str(self):
        """R2 阴性负例：非 dict 元素走 `str(f)` 分支（合法形态不得被误伤）。"""
        value = _contract_module().confirm_value_for_fields(["字符串项", 42, None])
        assert value == _legacy_confirm_value_for_fields(["字符串项", 42, None]), value
        assert value.startswith("确认："), value
        assert "字符串项" in value, value

    def test_card_fields_fallback_still_shared_with_base_skill(self):
        """`confirm_card_fields` 的通用兜底（issue #3882）随搬迁保持同值。"""
        base = importlib.import_module("app.graph.skills.base_skill")
        args = {"action": "toggle_status", "product_id": "p_001", "name": "遮光窗帘"}
        assert _contract_module().confirm_card_fields(args) == base.confirm_card_fields(args)
        assert _contract_module().confirm_card_fields({"action": "toggle_status"}) == []