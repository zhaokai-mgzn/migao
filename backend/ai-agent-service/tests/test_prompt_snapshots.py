"""
防线 2: Prompt 黄金快照测试

验证 _build_system_prompt() 的组装结果：
- 每个 Skill 至少包含身份 + 原则
- 长度在合理范围
- 关键规则都存在
- 无意外交叉污染（product 的规则不应出现在 order 中）

改动 references/ 下的 Prompt 文件后运行此测试即可发现意外变更。
"""
# case_ids: MC-003, MC-010, CH-003, CH-018

import pytest

from app.graph.skills.base_skill import _build_system_prompt, _PROMPT_CACHE


def _clear_cache():
    """清除缓存，确保每次测试重新读取"""
    _PROMPT_CACHE.clear()


@pytest.fixture(autouse=True)
def clear_before_each():
    _clear_cache()
    yield
    _clear_cache()


# ============ 所有 Skill 通用检查 ============

MIBAO_SKILLS = ["product", "order", "aftersales", "customer", "staff", "settings", "data", "general"]

# 每个 Skill 必须包含的关键文本
REQUIRED_IDENTITY = "词元通达商家管理后台"
REQUIRED_PRINCIPLES = "不编造数据"


@pytest.mark.parametrize("skill", MIBAO_SKILLS)
def test_skill_has_identity(skill):
    """每个 Skill 的 Prompt 必须包含公共身份"""
    prompt = _build_system_prompt(skill)
    assert REQUIRED_IDENTITY in prompt, f"{skill}: 缺少身份描述"


@pytest.mark.parametrize("skill", MIBAO_SKILLS)
def test_skill_has_principles(skill):
    """每个 Skill 的 Prompt 必须包含公共行为准则"""
    prompt = _build_system_prompt(skill)
    assert REQUIRED_PRINCIPLES in prompt, f"{skill}: 缺少行为准则"


@pytest.mark.parametrize("skill", MIBAO_SKILLS)
def test_skill_prompt_length_reasonable(skill):
    """Prompt 长度在合理范围（200-10500 字符）

    2026-09-03 上限 9500→10500：product 累积澄清话术（#2784）+ 承诺边界（#2785）
    达 9586，9500 误报；10500 仍防失控膨胀（正常增量 ~几百字符/PR）。
    """
    prompt = _build_system_prompt(skill)
    assert 200 < len(prompt) < 10500, f"{skill}: prompt 长度异常 ({len(prompt)} chars)"


# ============ 领域隔离检查 ============

def test_product_prompt_no_order_contamination():
    """product 的 Prompt 不应包含 order 的专属规则"""
    prompt = _build_system_prompt("product")
    # order-only rules
    assert "售后工单的创建、查询、流转" not in prompt
    assert "转人工提示" not in prompt


def test_order_prompt_no_product_contamination():
    """order 的 Prompt 不应包含 product 特有的工具和规则"""
    prompt = _build_system_prompt("order")
    # product-only tools（公共 principles 中可能提及通用概念但不包含具体用法）
    assert "inventory_manage" not in prompt
    assert "category_manage" not in prompt
    # product-only 领域规则
    assert "展示加工项：名称、分类" not in prompt


def test_aftersales_has_critical_rules():
    """售后 Prompt 必须包含转人工规则"""
    prompt = _build_system_prompt("aftersales")
    assert "转人工" in prompt or "人工介入" in prompt


def test_order_prompt_requires_interact_for_sku_selection():
    """生产回归 OR-010 flaky：多 SKU 选择必须用 interact(choice) 组件。

    旧 prompt 要求"展示表格让用户选"→ LLM 输出纯文本选项，pending_skill 未设置，
    后续"选1"短消息被误路由 → 回复"没有订单创建权限"。
    """
    prompt = _build_system_prompt("order")
    assert 'interact(component="choice")' in prompt


def test_general_is_fallback_friendly():
    """兜底节点必须引导用户说出具体需求"""
    prompt = _build_system_prompt("general")
    assert "创建商品" in prompt or "写操作" in prompt  # 必须有写操作引导


def test_cross_domain_write_no_permission_blame():
    """生产回归（sess_9cfeb2c8b3df4a8f）：跨域写操作失败禁止甩锅"权限/工具缺失"。

    商品创建确认轮被误路由到订单技能时，LLM 曾声称"没有可用的创建商品执行工具/
    联系管理员开通权限"——错误归因误导用户。共享原则必须规定：模块不符时如实
    说明并引导用户重新表达意图，而非归因权限。
    """
    for skill in ("order", "product", "general"):
        prompt = _build_system_prompt(skill)
        assert "不得甩锅权限" in prompt, f"{skill}: 缺少跨域失败归因规则"
        assert "重新表达" in prompt or "重新说出" in prompt, f"{skill}: 规则未要求引导用户重新表达意图"


def test_product_image_create_wording_unified():
    """G7 仲裁（issue #2777）：图片建品话术三方统一，杜绝"呈现 vs 预填"矛盾漂移。

    旧矛盾：product_skill.py 内联要求"图片识别后的第一步是向用户呈现识别结果…
    让用户确认"，而 EXAMPLES-product.md 写"识别结果直接预填，不做二次确认"——
    同一流程两种指令，模型行为漂移。统一仲裁口径：
    「识别结果以预填 form 呈现（呈现即一次确认入口）；已识别字段不重复反问，
    缺失字段引导补充；禁止跳过呈现直接建品」。
    """
    prompt = _build_system_prompt("product")
    # 统一口径关键词必须在（覆盖 prompts/product.md + EXAMPLES-product.md + 内联）
    assert "预填" in prompt, "product prompt 缺少『预填』统一口径"
    assert "一次确认" in prompt or "确认或修改" in prompt, "product prompt 缺少『一次确认』语义"
    # 已识别字段不得反问（呈现预填的价值所在）
    assert "不重复反问" in prompt or "重复反问" in prompt or "不要重复输入" in prompt, (
        "product prompt 缺少『已识别字段不重复反问』约束"
    )
    # 旧矛盾措辞不得复活
    assert "不做二次确认" not in prompt, "product prompt 出现旧矛盾措辞『不做二次确认』"


# ============ Prompt 增量快照 ============

def test_snapshot_all_skills():
    """全量快照：任意 Prompt 变更都会在此体现

    测试失败时的判断：
    - 故意改动 → 更新下方 expected 中的对应值
    - 意外改动 → 检查 references/ 文件是否被误改
    """
    # 最小长度快照（如果 references/ 被不小心清空，这里会失败）
    expected_min = {
        "product": 2000,     # 有 EXAMPLES
        "order": 1500,       # 有 EXAMPLES
        "aftersales": 1200,  # 有 EXAMPLES
        "customer": 1200,    # 有 EXAMPLES
        "staff": 500,
        "settings": 600,
        "data": 500,
        "general": 700,
    }
    for skill, min_len in expected_min.items():
        prompt = _build_system_prompt(skill)
        assert len(prompt) >= min_len, (
            f"{skill}: prompt 长度 {len(prompt)} < 预期 {min_len}。"
            f"检查 references/ 文件是否被清空或截断。"
        )

    # 最大长度快照（防止无限制膨胀）
    expected_max = {
        "product": 10500,  # +400: 澄清话术(#2784)+承诺边界(#2785) + 加工项主动询问增强（issue #2892，达 9985）
        "order": 8000,    # +1400: 加工项下单铁律（数据来源/金额计算/数量确认/示例）+ 中止铁律+跨域归因铁律+禁英文枚举全局规则
        "aftersales": 5200,  # +700: 禁英文枚举全局规则 + 售后工单枚举中文对照（本轮新增）
        "customer": 5000,  # +500: 禁英文枚举全局规则（共享原则增长）
        "staff": 4900,    # +400: 禁英文枚举全局规则（共享原则增长）
        "settings": 4900, # +400: 禁英文枚举全局规则（共享原则增长）
        "data": 4500,
        "general": 5800,  # +600: Phase 2 (#2789) 澄清卡引导（choice 候选示例）达 5465
    }
    for skill, max_len in expected_max.items():
        prompt = _build_system_prompt(skill)
        assert len(prompt) <= expected_max[skill], (
            f"{skill}: prompt 长度 {len(prompt)} > 上限 {expected_max[skill]}。"
            f"检查是否重复拼接了内容。"
        )
        # 90% 预警：接近上限时输出 WARNING，便于提前发现膨胀趋势
        if len(prompt) > max_len * 0.9:
            import warnings
            warnings.warn(
                f"⚠️  {skill}: prompt 长度 {len(prompt)}/{max_len} "
                f"({len(prompt)*100//max_len}%) — 接近上限，新内容需精简"
            )


# ============ 小布 C 端售后 few-shot 引导 ============

def test_customer_aftersales_fewshot_guides_aftersale_create():
    """小布售后必须注入 C 端 few-shot：明确换货/退货诉求 → aftersale_create，
    而非误走 human_handoff（真实闭环回归：两次新会话 AI 均转人工建 complaint 工单）。"""
    prompt = _build_system_prompt("customer_aftersales")
    # few-shot 已注入
    assert "Few-shot 参考示例" in prompt, "customer_aftersales 缺少 few-shot 注入"
    # 核心引导：换货/退货应 aftersale_create
    assert "aftersale_create" in prompt, "few-shot 未包含 aftersale_create 引导"
    # 转人工边界明确（禁止把换货/退货转人工）
    assert "转人工" in prompt and "换货" in prompt
    # 反例存在（错误示例指明换货走 human_handoff 是错误）
    assert "human_handoff" in prompt
    # 已发货订单可售后（状态门禁：confirmed/producing/shipped/completed 均可建退换货）
    # —— 真实闭环回归：AI 看到"已发货"误判不能售后而转人工
    assert "已发货" in prompt, "few-shot 未说明已发货订单可申请售后"
    assert "尺寸买大了" in prompt, "few-shot 缺少已发货换货示例"


def test_customer_aftersales_prompt_loaded_with_identity():
    """小布售后 prompt 组装包含公共身份与原则（无意外污染）"""
    prompt = _build_system_prompt("customer_aftersales")
    assert "词元通达商家管理后台" in prompt, "缺少公共身份"
    assert "不编造数据" in prompt, "缺少公共原则"


# ============ Phase 2 澄清卡契约（issue #2789） ============

def test_general_prompt_guides_choice_clarify():
    """B 端 general 兜底（低置信/图片澄清主战场）prompt 必须引导澄清卡。

    旧引导只有"用文字列出可能的操作方向"（prompts/general.md），无 interact 承载；
    Phase 2 升级为 interact(choice) 候选卡 + 文字兜底（低学历可点选）。
    """
    prompt = _build_system_prompt("general")
    assert "interact" in prompt, "general prompt 缺少 interact 澄清卡引导"
    assert "候选" in prompt, "general prompt 缺少候选方向语义"


def test_general_inline_prompt_guides_choice_clarify():
    """general_agent.py 内联 SYSTEM_PROMPT 的回复格式必须与 references 一致。

    _build_system_prompt 组装的是 references/ 层；general 的"回复格式"引导在
    内联 prompt（general_agent.py GENERAL_SYSTEM_PROMPT），须同样要求 choice 卡优先。
    """
    from app.graph.skills.general_agent import GENERAL_SYSTEM_PROMPT
    assert "interact(component=choice)" in GENERAL_SYSTEM_PROMPT, (
        "general 内联 prompt 缺少 interact choice 澄清卡引导（Phase 2 回归）"
    )


def test_customer_product_image_clarify_not_default_search():
    """C 端 customer_product 图片段：意图不明时先澄清候选，不默认直接搜相似。

    回归背景：小布 C 端顾客随手发图时，旧 prompt"识别后主动搜相似"会把
    "想量尺寸/想问价/想做售后"一律当"找同款"处理（G1 缺口）。
    """
    from app.graph.skills.customer_product_skill import CUSTOMER_PRODUCT_SYSTEM_PROMPT
    assert "候选意图卡" in CUSTOMER_PRODUCT_SYSTEM_PROMPT, (
        "customer_product 图片段缺少候选意图澄清卡引导"
    )
    assert "不要默认直接搜相似" in CUSTOMER_PRODUCT_SYSTEM_PROMPT, (
        "customer_product 图片段仍默认直接搜相似（应意图明确才搜）"
    )


def test_customer_general_image_clarify_not_default_search():
    """C 端 customer_general 图片段：意图不明时先澄清候选，不默认直接搜相似。"""
    from app.graph.skills.customer_general_skill import CUSTOMER_GENERAL_SYSTEM_PROMPT
    assert "候选意图卡" in CUSTOMER_GENERAL_SYSTEM_PROMPT, (
        "customer_general 图片段缺少候选意图澄清卡引导"
    )
    assert "不要默认直接搜相似" in CUSTOMER_GENERAL_SYSTEM_PROMPT, (
        "customer_general 图片段仍默认直接搜相似（应意图明确才搜）"
    )
