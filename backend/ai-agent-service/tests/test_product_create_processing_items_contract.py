# case_ids: PR-014, PR-016
"""建品「分类确认 → 加工项多选卡」链路契约（对真实拼装产物断言，零 LLM）。

病灶（issue #3320，符号级）——建品路径的两条指令被**更后注入的层**反向覆盖：

运行期 System Prompt 由 `base_skill._build_system_prompt()` 五层拼装，
**顺序 = 注入顺序**（`:527-579`）：

    Layer1 identity → Layer2 principles → Layer2.5 PROMPT-rules
    → Layer3 `references/prompts/product.md`        ← `applicable_category_id` 的**唯一**指令源
      （3abaab7a/#2966 加入 `:28/:31`）
    → Layer4 `product_skill.PRODUCT_SYSTEM_PROMPT`  ← **后注入 = 覆盖层**（改前**完全没提**该参数）
    → Layer5 `references/EXAMPLES-product.md`        ← **最后注入，模仿权重最高**
      （改前：建品示例 `processing_item_query()` **零参数**，且放在**分类确认之前**）

⇒ Layer3 的一条长句被 Layer4+Layer5 两层反向覆盖，模型照抄示例 ⇒
① PR-016 判 `required_args[processing_item_query.applicable_category_id]` 缺失；
② PR-014 失效轨迹里模型跳过加工项询问、直接发 confirm 卡
   —— 且 `product_manage.description` 的【铁律】把「创建」与禁用/删除/上下架并列，
   要求「展示操作预览 + 确认卡 → 立即执行」，对多步建品而言就是"尽快到确认卡"的抢跑指令。

本文件把这条链路钉成**可执行契约**：每条断言都对着真实文件 / 真实拼装函数产物，
不是"看起来更清楚了"。前 7 条为**红证**（改前不成立），最后 2 条为**回归锁**。
"""

import re
from pathlib import Path

import pytest

from app.graph.skills.base_skill import _PROMPT_CACHE, _build_system_prompt
from app.graph.skills.product_skill import PRODUCT_SYSTEM_PROMPT

_REF_DIR = Path(__file__).resolve().parents[1] / "app" / "graph" / "skills" / "references"
_EXAMPLES = _REF_DIR / "EXAMPLES-product.md"
_DOMAIN = _REF_DIR / "prompts" / "product.md"

# Layer3 / Layer4 的判别性标记（跨层唯一）
_LAYER3_MARK = "分类/加工项必须用工具返回的真实数据"
_LAYER4_MARK = "## 引用商品用完整名称（卡片引用对齐）"
_LAYER5_MARK = "## Few-shot 参考示例"

# 零参数调用形态：`processing_item_query()` / `processing_item_query(  )`
_NO_ARG_CALL = re.compile(r"processing_item_query\(\s*\)")
# 单行调用形态（示例里的写法都是一行一个调用）
_CALL_LINE = re.compile(r"processing_item_query\(")


@pytest.fixture(autouse=True)
def _clear_prompt_cache():
    """_build_system_prompt 带文件缓存；清掉才读得到本 PR 改后的文件。"""
    _PROMPT_CACHE.clear()
    yield
    _PROMPT_CACHE.clear()


def _examples_text() -> str:
    return _EXAMPLES.read_text(encoding="utf-8")


def _create_example_block(text: str) -> str:
    """示例 1「完整创建流程」正文（到示例 2 为止）。"""
    start = text.index("## 示例 1")
    end = text.index("## 示例 2")
    return text[start:end]


# ── ① Layer5 示例层：加工项查询必须带 applicable_category_id ──

def test_layer5_example_has_no_zero_arg_processing_item_query():
    """红证：示例层不得出现零参数 `processing_item_query()`。

    示例层是 LLM 模仿权重最高的一层（最后注入）——示例里零参数，
    模型就零参数调用，Layer3 的 `applicable_category_id=已选商品分类ID` 形同虚设
    （PR-016 判 `required_args[processing_item_query.applicable_category_id]` 缺失）。
    """
    hits = _NO_ARG_CALL.findall(_examples_text())
    assert hits == [], (
        f"EXAMPLES-product.md 仍有 {len(hits)} 处零参数 processing_item_query() 示例；"
        "示例必须与 Layer3 规则一致地传 applicable_category_id"
    )


def test_layer5_create_example_carries_applicable_category_id():
    """红证：建品示例里每一次 processing_item_query 调用都必须带该参数。"""
    block = _create_example_block(_examples_text())
    call_lines = [ln for ln in block.splitlines() if _CALL_LINE.search(ln)]
    assert call_lines, "建品示例里找不到 processing_item_query 调用（示例被改动过？）"
    missing = [ln.strip() for ln in call_lines if "applicable_category_id" not in ln]
    assert missing == [], (
        "建品示例的 processing_item_query 调用未携带 applicable_category_id：\n"
        + "\n".join(missing)
    )


def test_layer5_page_meta_params_carry_applicable_category_id():
    """红证：示例透传的 pageMeta.params 也要带该筛选（翻页不丢过滤，PR-015 同族）。"""
    block = _create_example_block(_examples_text())
    param_lines = [ln for ln in block.splitlines() if "params:" in ln]
    assert param_lines, "建品示例里找不到透传的 pageMeta.params"
    assert any("applicable_category_id" in ln for ln in param_lines), (
        "pageMeta.params 未携带 applicable_category_id ⇒ 前端翻页后过滤条件丢失：\n"
        + "\n".join(ln.strip() for ln in param_lines)
    )


def test_layer5_create_example_queries_processing_items_after_category_step():
    """红证：加工项查询不得早于分类步骤（分类事实是过滤参数的前提）。

    改前示例把 `processing_item_query()` 放在**轮次 1 基本信息收集**里
    （与 `category_manage` 同轮、分类尚未确认）⇒ 此时无分类事实可传，
    模型只能零参数调用。
    """
    block = _create_example_block(_examples_text())
    first_card = block.index("interact(")
    head = block[:first_card]  # 轮次 1「收集基本信息」段
    assert not _CALL_LINE.search(head), (
        "建品示例在「收集基本信息」轮就预查了加工项（分类尚未确认 ⇒ 无 applicable_category_id 可传）：\n"
        + head
    )
    assert block.index("category_manage(") < block.index("processing_item_query("), (
        "示例里 processing_item_query 出现在 category_manage 之前"
    )


# ── ② Layer4 覆盖层：必须与 Layer3 同口径，不得漏参数、不得抢跑 ──

def test_layer4_overlay_states_applicable_category_id():
    """红证：Layer4（后注入的覆盖层）必须写明 applicable_category_id。

    Layer4 在 Layer3 之后注入 ⇒ 它对「怎么调 processing_item_query」的表述
    天然覆盖 Layer3；它不提该参数，模型就按 Layer4 办。
    """
    assert "applicable_category_id" in PRODUCT_SYSTEM_PROMPT, (
        "product_skill.PRODUCT_SYSTEM_PROMPT（Layer4 覆盖层）未提 applicable_category_id，"
        "会覆盖 Layer3 product.md 的按分类过滤规则"
    )


def test_layer4_overlay_forbids_confirm_card_before_processing_items():
    """红证：Layer4 必须显式禁止「跳过加工项询问直接发汇总确认卡」。

    PR-014 失效轨迹形态：只发 confirm 卡、全程无 `interact(choice, multiSelect=true)`
    —— 双层指令（Layer4 只写"必须询问"、tool 层铁律写"创建也要尽快发确认卡"）
    下，模型合理解读为"直接汇总确认"。
    """
    assert "确认卡" in PRODUCT_SYSTEM_PROMPT
    proc_section = PRODUCT_SYSTEM_PROMPT.split("## 加工项", 1)[-1]
    assert "确认卡" in proc_section, (
        "Layer4 的「加工项」段没有任何「确认卡」字样 ⇒ 未把「加工项询问必须早于汇总确认卡」写成显式顺序契约"
    )


def test_product_manage_iron_rule_excludes_multi_step_create():
    """红证：product_manage 的【铁律】不得把「创建」纳入"尽快发确认卡"清单。

    27ac63d5（2026-09-10，#3204）给 8 个写工具的 description 批量加了统一铁律
    「先查必要信息拿真实 ID → 展示操作预览 + 确认卡 → 确认后立即执行」，
    其中把「**创建**」与禁用/调整/删除/上下架并列。
    建品 create 是**多步引导**（分类确认 → 加工项多选卡 → 货号 → 汇总确认卡），
    该铁律对 create 的合理解读就是"尽快到确认卡" ⇒ 抢跑掉加工项询问。
    """
    from app.tools.product_manage import ProductManageTool

    desc = ProductManageTool.description
    assert "【铁律】" in desc, "product_manage description 结构变了，本契约需同步"
    iron_body = desc.split("【铁律】", 1)[1]
    carve_out_mark = "【create 例外"
    assert carve_out_mark in iron_body, (
        "product_manage【铁律】未把多步引导的 create 摘出 ⇒ 建品会被「尽快发确认卡」抢跑（PR-014 形态）"
    )
    pre_carve = iron_body.split(carve_out_mark, 1)[0]
    assert "创建" not in pre_carve, (
        "【铁律】正文仍把「创建」列在单步写操作清单里：\n" + pre_carve
    )
    create_clause = iron_body.split(carve_out_mark, 1)[1]
    for token in ("加工项", "multiSelect=true", "applicable_category_id"):
        assert token in create_clause, (
            f"create 例外条款缺 `{token}`：\n" + create_clause
        )


# ── ③ 回归锁：层级顺序 + 建品链顺序（改前改后都成立，防回退） ──

def test_assembled_prompt_layer_order_is_overlay_after_domain():
    """回归锁：把「Layer4/Layer5 晚于 Layer3 注入」这一事实钉住。

    这是本 PR 全部结论的前提——若哪天顺序变了（先示例后领域规则），
    上述"覆盖层"分析需重新评估。
    """
    prompt = _build_system_prompt("product", inline_prompt=PRODUCT_SYSTEM_PROMPT)
    i3 = prompt.index(_LAYER3_MARK)
    i4 = prompt.index(_LAYER4_MARK)
    i5 = prompt.index(_LAYER5_MARK)
    assert i3 < i4 < i5, (
        f"Prompt 层级顺序变了（Layer3={i3} Layer4={i4} Layer5={i5}）："
        "覆盖层分析（Layer4/Layer5 反向覆盖 Layer3）需重新评估"
    )


def test_assembled_prompt_asks_processing_items_before_confirm_card():
    """回归锁：真实拼装产物里，建品流程的「加工项询问」必须早于「汇总确认卡」。"""
    prompt = _build_system_prompt("product", inline_prompt=PRODUCT_SYSTEM_PROMPT)
    chain = next(
        (ln for ln in prompt.splitlines() if ln.startswith("- 创建流程：")),
        None,
    )
    assert chain, "product.md 的建品流程链不见了"
    proc_at = chain.index("加工项选择器")
    confirm_at = chain.index("interact(component=confirm)")
    assert proc_at < confirm_at, (
        "建品流程链里汇总确认卡早于加工项询问 ⇒ 顺序契约被破坏\n" + chain
    )
    assert "applicable_category_id" in chain
