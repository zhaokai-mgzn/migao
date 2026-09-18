# case_ids: PG-012, PR-013, PR-024, KN-001, KN-002, OR-013
"""
防线 2: Prompt 黄金快照测试

验证 _build_system_prompt() 的组装结果：
- 每个 Skill 至少包含身份 + 原则
- 长度在合理范围
- 关键规则都存在
- 无意外交叉污染（product 的规则不应出现在 order 中）

改动 references/ 下的 Prompt 文件后运行此测试即可发现意外变更。
"""

import os as _os
import re

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
def test_global_rules_forbid_english_in_user_facing_replies(skill):
    """全局规则必须要求「面向用户一律中文」，且覆盖**技术术语（SKU/ID）**而不只是英文枚举。

    为什么锁这条：用户（顾客尤其低学历用户、以及商家员工）看不懂英文单词。
    规则原先只禁「英文枚举」（pending/refund），实测仍漏出 `SKU`（小布 1 次 / 米宝 3 次）
    与 `ID`（米宝 1 次）——见 2026-09-14 结论档 run 34841029062 的回复文本。
    ⚠️ 本断言同时防「把规则改回只禁枚举」的回退：只留 ① 会让 ② 类泄漏重新发生。
    """
    prompt = _build_system_prompt(skill)
    assert "面向用户一律中文" in prompt, f"{skill}: 缺少「面向用户一律中文」语言铁律"
    # ② 类（技术术语）必须被点名，否则模型不知道 SKU/ID 也算「英文」
    assert "SKU" in prompt, f"{skill}: 语言规则未点名 SKU（技术术语会漏给用户）"
    assert "UUID" in prompt, f"{skill}: 语言规则未点名 UUID/ID 一类标识"
    # ① 类（英文枚举）不得被删掉
    assert "pending" in prompt or "refund" in prompt, f"{skill}: 英文枚举禁令被删除"


@pytest.mark.parametrize("skill", MIBAO_SKILLS)
def test_skill_prompt_length_reasonable(skill):
    """Prompt 长度在合理范围（200-11200 字符）

    2026-09-03 上限 9500→10500：product 累积澄清话术（#2784）+ 承诺边界（#2785）
    达 9586，9500 误报；10500 仍防失控膨胀（正常增量 ~几百字符/PR）。
    2026-09-08 上限 10500→10800：product 建品规格落库 + 加工项价格配置规则（#3027），达 10732。
    2026-09-08 上限 10800→11200：product 确认卡片必须发出、禁止只发文字提示（#3045），达 11131。
    """
    prompt = _build_system_prompt(skill)
    # 2026-09-15 上限 12000→13000：order 单价铁律补「系统会拦截并回填」+ EXAMPLES-order.md 反例4（OR-014 判定跑 34923425338 收口，达 12595）
    # 2026-09-18（issue #4196）：加工单章节反转 #3917、恢复操作指引后 order 实测 **12991 < 13000**
    # ⇒ **本硬上限不动**（先 trim 再谈抬：删 #3921 的过期处方「问加工单不调用任何工具」（= 反转后
    #    的假真值）、去掉模型不需要的跨层口径括注与冗余措辞、防混淆守则压到 3 行）；
    #    order 的 per-skill 预算 12800→13000 同步上调（账本条目见 test_snapshot_all_skills）。
    assert 200 < len(prompt) < 13000, f"{skill}: prompt 长度异常 ({len(prompt)} chars)"


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
    """售后 Prompt 必须包含**复杂投诉的能力边界规则**（退场后不再有转人工出口）。

    变更沿革（用户裁定 2026-09-19）：「不应该存在 human_handoff 这种东西，以后全是
    AI 来判断」—— 原断言要求售后 prompt 出现「转人工 / 人工介入」，那是**指向一个
    已退场出口**的指令（米宝侧本来也没有该工具）。替代规则：超权限/复杂投诉时
    如实说明能力边界 + 把能落地的落地（落成工单/记录），不得推给人工了事。
    """
    prompt = _build_system_prompt("aftersales")
    assert "不得" in prompt and "人工" in prompt, (
        "售后 prompt 缺少「不得把用户推给人工了事」的能力边界规则"
    )
    assert "落成工单" in prompt or "记录" in prompt, (
        "售后 prompt 缺少「把能落地的部分落地」的可执行下一步"
    )
    # 退场面：不得再出现"主动建议转人工"这类指向已退场出口的处方
    for forbidden in ("主动建议转人工", "转人工处理", "联系人工客服"):
        assert forbidden not in prompt, (
            f"售后 prompt 又出现「{forbidden}」—— 转人工能力已退场，这是给模型一个按不动的出口"
        )


def test_order_prompt_requires_interact_for_sku_selection():
    """生产回归 OR-010 flaky：多 SKU 选择必须用 interact(choice) 组件。

    旧 prompt 要求"展示表格让用户选"→ LLM 输出纯文本选项，pending_skill 未设置，
    后续"选1"短消息被误路由 → 回复"没有订单创建权限"。
    """
    prompt = _build_system_prompt("order")
    assert 'interact(component="choice")' in prompt


def test_order_prompt_requires_proactive_processing_item():
    """issue #3033：创建订单 confirm 前必须主动询问加工项，禁止直接弹确认卡。

    旧 prompt 是「用户要求加工时禁止遗漏」（被动式）→ sess_7f27137647e14b1e 实证
    confirm 卡在加工项询问前弹出、金额不含加工费，用户质问后才补。
    """
    prompt = _build_system_prompt("order")
    assert "必须主动询问" in prompt, "order prompt 缺少『主动询问加工项』强制词"
    assert "确认卡之前" in prompt or "确认订单卡之前" in prompt, (
        "order prompt 未约束加工项询问必须先于 confirm 卡"
    )


def test_aftersales_prompt_requires_exchange_processing_item():
    """issue #3033：换货/维修选目标商品后必须确认加工项。

    旧 prompt 完全无加工项概念 → sess_50ff3e3c824c4a70 实证换货选 2699 面料
    （有 5 个加工项）全程未提加工项，工单 description 无加工信息。
    """
    prompt = _build_system_prompt("aftersales")
    assert "加工项" in prompt, "aftersales prompt 缺少换货加工项规则"


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


def test_product_create_carries_inferred_specifications():
    """图片建品：推理属性必须随 create 传入 specifications（sess_c1fce183dae24f22 复盘）。

    旧缺陷：prompt 要求预填表单展示推理属性（材质/克重等），但未要求 create 时
    把这些推理属性经 specifications 落库 → 商品规格（product_attributes）为空，
    用户需事后补一次「给这个商品生成商品属性」。
    """
    prompt = _build_system_prompt("product")
    # 图片建品的推理属性必须带入 create 的 specifications
    assert "specifications" in prompt, "product prompt 未提及 specifications 参数"
    assert "推理" in prompt, "product prompt 未要求携带图片推理属性"


def test_product_create_carries_processing_item_configs():
    """建品：加工项必须经 processing_item_configs 传入（含价格），禁止只传名称列表（sess_c1fce183dae24f22 复盘）。

    旧缺陷：prompt 要求 create 时只传 processing_item_ids=[名称] → 商品加工项
    custom_price 全 NULL → 详情页展示 ¥0.00。加工项选择器已展示价格，必须一并落库。
    """
    prompt = _build_system_prompt("product")
    assert "processing_item_configs" in prompt, "product prompt 未要求创建时携带加工项价格配置"
    # 价格需从查询结果取真实 unit_price，禁止编造
    assert "unit_price" in prompt or "unitPrice" in prompt, "product prompt 未要求取加工项真实默认单价"


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
        "knowledge": 3000,   # 有 EXAMPLES（issue #3569 补：knowledge 域此前不在任何厚度门禁里）
    }
    for skill, min_len in expected_min.items():
        prompt = _build_system_prompt(skill)
        assert len(prompt) >= min_len, (
            f"{skill}: prompt 长度 {len(prompt)} < 预期 {min_len}。"
            f"检查 references/ 文件是否被清空或截断。"
        )

    # 最大长度快照（防止无限制膨胀）
    expected_max = {
        "product": 12700,  # +800: 澄清话术(#2784)+承诺边界(#2785) + 加工项主动询问增强（issue #2892，达 9985）+ 建品规格/加工项价格规则（#3027，达 10732）+ 确认卡片必须发出（issue #3045，达 11131）+ 库存工具分工铁律（Round 37，达 11318）+ 120（issue #3930/#3931）：product_update 描述补「主图/详情图走 product_manage」反例 + product.md 主图/详情图映射行（达 12019）+ 379（issue #3936）：product.md 补「禁止以工具不支持/没有能力为由拒绝写操作」通用铁律（达 12398）；+300（issue #4107 F7）：共享层 `base/principles.md` 的权限归因规则补后半——「系统**确实**报权限拒绝时必须如实说明缺哪项能力 + 不得重试 + 给开通路径」（+168 字符，达 12562）
        "order": 13000,  # +800: 加工项数量自动推导（issue #2986）+ confirm 前必须主动询问加工项（issue #3033，达 8836）+ 共享规则确认卡片铁律（issue #3045，达 9133）+ 规格ID≠商品ID 铁律（Round 39，达 9396）+ 加工单域（#3340，达 10005）；+1200（issue #3799）：订单→物流链收口（prompts/order.md 链规则 + EXAMPLES-order.md「同一轮 order_query→logistics_track」正/反例，达 11364）；+600（issue #3873）：单价铁律——报价/确认/落单单价必须来自商品库，禁止编造分色价（达 11967）；+400（OR-014 判定跑 34923425338 收口）：单价铁律补「系统会拦截并回填」+ EXAMPLES-order.md 反例4「库价 168 却写米白 150」（达 12595）；-233（issue #3917，达 12362）：加工单章节由「工具操作指引」（生成/查询/发加工/start/complete/cancel）整体替换为「加工项 vs 加工单概念区分 + 不接入声明」；+76（issue #3921，达 12438）：补「问加工单不调用任何工具（含订单查询/加工项查询）」；+200（issue #4107 F7）：共享层 `base/principles.md` 权限归因规则补后半（达 12602）；+389（issue #4196，达 **12991**）：**反转 -233 与 +76 两笔过期处方**——加工单章节恢复操作指引（frontmatter 工具行 + 工具使用表 3 行 + 生成/查询/发加工/状态机/发货守卫），概念区分以**一条防混淆守则**保留（加工项≠加工单、不得用 processing_item_query 冒充、不得编造加工单号/状态）；#3921 那条「不调用任何工具」已成假真值故删除（留着会把模型往错处推）。先 trim 再评估抬上限：删过期处方 + 去跨层口径括注与冗余措辞 + 守则压 3 行后**实测 12991 < 硬上限 13000**，故本次只上调本 per-skill 预算（12800→13000），**硬上限不动**（命令自证：本文件即判据）
        "aftersales": 8000,  # +1300: 禁英文枚举 + 退货库存规则（issue #2991）+ 换货加工项确认（issue #3033，达 6269）+ 共享规则确认卡片铁律（issue #3045，达 6566）+ 创建/关闭工单执行引导（Round 43，达 7068）
        "customer": 8600,  # +3500: 领域 prompt 补齐打标签流程（CU-003 场景）+ EXAMPLES 补标签示例（Round 33）；+100（用户裁定 2026-09-19 转人工退场）：共享层 `base/principles.md` 核心原则③ 由「遇问题转人工」改写为「自己解决到底（不得推给人工/管理员）」——该层每个 skill 都注入，customer 原本只剩 19 字符余量（达 8555），按本 dict 既有惯例显式上调并说明理由（不精简业务内容：退场后"不得假承诺转人工"是**新增**的必需规则）
        "staff": 8000,    # +3100: 领域 prompt 补齐创建角色流程（HR-005 场景）+ EXAMPLES 补角色创建示例（Round 32）
        "settings": 6500, # +1600: 领域 prompt 补齐配置/通知流程（Round 34）
        "data": 6800,     # +1700: 领域 prompt 补齐看板/会话流程（Round 34）；+300（issue #4107 F7）：共享层 `base/principles.md` 权限归因规则补后半（达 6660）
        "general": 6600,  # +600: Phase 2 (#2789) 澄清卡引导（choice 候选示例）达 5465；+200: 兜底库存查询改真实工具（issue #3569，达 5827）；+200: 面向用户一律中文（扩到 SKU/ID 等技术术语，达 6079）；+207（issue #3921）：加工单≠加工项兜底口径——问加工单不调 processing_item_query、解释概念并引导后台（达 6286）；+200（issue #4107 F7）：同上共享层权限归因规则补后半（达 6450）
        "knowledge": 7000,  # issue #3569：knowledge 域（B 端知识问答）补入厚度门禁，达 5032
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
    **且不得再指向已退场的转人工出口**（真实闭环回归：两次新会话 AI 均转人工建 complaint 工单）。

    变更沿革（用户裁定 2026-09-19）：「不应该存在 human_handoff 这种东西，以后全是
    AI 来判断」—— 原断言要求 prompt 里出现 `human_handoff`（"反例存在"）与「转人工」。
    退场后这两条**必须反过来**：工具名出现在 prompt 里 = 模型被告知一个按不动的出口
    （L0 判据见 tests/unit_ci_workflows/test_human_handoff_retired.py）。
    反例的教学价值以**不带工具名**的形式保留：反例1/2 改成「推给人工（应 aftersale_create）」。
    """
    prompt = _build_system_prompt("customer_aftersales")
    # few-shot 已注入
    assert "Few-shot 参考示例" in prompt, "customer_aftersales 缺少 few-shot 注入"
    # 核心引导：换货/退货应 aftersale_create
    assert "aftersale_create" in prompt, "few-shot 未包含 aftersale_create 引导"
    # 换货场景仍在（下行断言依赖它）
    assert "换货" in prompt, "few-shot 缺少换货场景"
    # 反例仍在（教学价值不得因退场而丢）：推给人工被明确标为错误
    assert "错误" in prompt and "需要人工客服处理哦" in prompt, (
        "few-shot 丢了「推给人工 = 错误」的反例 —— 退场后这仍是高频失败形态"
    )
    # 退场面：prompt 里**不得**出现退场工具名（否则模型会承诺"已为您转接"）
    assert "human_handoff" not in prompt, (
        "customer_aftersales prompt 里出现了已退场工具名 —— 模型会被导向一个按不动的出口"
    )
    # 假承诺禁令在（退场后新增的必需规则）
    assert "禁止" in prompt and "已为您转接人工客服" in prompt, (
        "prompt 缺少「禁止假承诺转接」的显式禁令"
    )
    # 已发货订单可售后（状态门禁：confirmed/producing/shipped/completed 均可建退换货）
    # —— 真实闭环回归：AI 看到"已发货"误判不能售后而推给人工
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


# ============ C 端（小布）Prompt 厚度门禁（issue #3569） ============
#
# 为什么 C 端需要单独一套门禁：
# 1) 上面 `test_snapshot_all_skills` 只列 8 个 B 端 skill，且调用
#    `_build_system_prompt(skill)` **不传 inline_prompt**；而 C 端 6 个域
#    （customer_order/customer_product/customer_quote/customer_aftersales/
#    customer_knowledge/customer_general）的领域规则**大量写在
#    `{SKILL}_SYSTEM_PROMPT`（L4 内联）里**、`references/prompts/{skill}.md`（L3）多为空
#    → 只测 references 层等于对 C 端结构性不可见，C 端可无限变薄而 CI 全绿。
# 2) `_read_cached`（base_skill.py:512-524）在文件缺失时**静默返回 ""** → 删掉一个
#    `EXAMPLES-{skill}.md` 不会有任何报错，只是 prompt 悄悄变薄（"无声变薄"的机制根源）。
#    故这里额外显式断言 EXAMPLES 文件存在且非空、且组装结果里真的有 few-shot 段。
#
# 快照值取自 2026-09-14 实测（issue #3569）。每项 4 个数字，分别守不同的"变薄"路径：
#   (EXAMPLES 最小字符, 内联 prompt 最小字符, 组装后最小字符, 组装后最大字符)
#   - EXAMPLES 最小 → 文件被删/清空/截成残片（L5 无声消失）
#   - 内联最小     → `{SKILL}_SYSTEM_PROMPT` 被删空/大幅删减（C 端规则主载体在 L4）
#   - 组装后最小   → L3（prompts/{skill}.md）或上两层被削
#   - 组装后最大   → 重复拼接、失控膨胀
# 只抓"整层消失/大幅删减"；单条规则的丢失由本文件的关键词断言（如"候选意图卡"）兜住。
# 失败时判断：故意增删内容 → 更新对应数字；意外变更 → 查 references/ 与 skill 内联是否被误改。
CUSTOMER_SKILL_LENGTH_SNAPSHOT = {
    # 域                    EXAMPLES≥  内联≥   组装≥     组装≤
    "customer_order":      (1000,     3200,   7500,     10500),
    "customer_product":    (800,       800,   4900,     7000),
    "customer_quote":      (1500,      900,   7500,     11000),
    "customer_aftersales": (1400,     1400,   5700,     9000),
    "customer_knowledge":  (1000,      700,   6400,     8800),
    "customer_general":    (600,       900,   4900,     7000),
}

_EXAMPLES_DIR = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                              "app", "graph", "skills", "references")


def _customer_inline_prompt(skill: str) -> str:
    """该 skill 运行时真正注入的内联 prompt（L4 = `SkillConfig.system_prompts[persona]`）。

    运行时调用点 base_skill.py:2663 即 `_build_system_prompt(skill_name, inline_prompt=system_prompt)`。
    """
    from app.graph.skills.skill_registry import get_skill_registry

    cfg = get_skill_registry().get_or_raise(skill)
    inline = (cfg.system_prompts or {}).get(cfg.default_persona, "")
    assert inline, f"{skill}: SkillConfig.system_prompts[{cfg.default_persona}] 为空（C 端规则主要在这层）"
    return inline


def _customer_prompt(skill: str) -> str:
    """按**运行时口径**组装 C 端 prompt：显式传入内联 prompt（L4）。

    这一点是关键：`test_snapshot_all_skills` 调 `_build_system_prompt(skill)` 不传内联，
    对"规则主要写在内联里"的 C 端结构性不可见。
    """
    return _build_system_prompt(skill, inline_prompt=_customer_inline_prompt(skill))


@pytest.mark.parametrize("skill", sorted(CUSTOMER_SKILL_LENGTH_SNAPSHOT))
def test_customer_prompt_has_fewshot_examples(skill):
    """C 端每个域必须有非空 `EXAMPLES-{skill}.md`（L5），且真的拼进了 prompt。

    L5 位于 prompt 最末（衰减最小、行为影响最大）。文件缺失时 `_read_cached`
    （base_skill.py:512-524）静默返回 ""，连"## Few-shot 参考示例"标题都不会出现，
    却没有任何红灯 —— 这是"无声变薄"的机制根源。
    """
    path = _os.path.join(_EXAMPLES_DIR, "EXAMPLES-" + skill + ".md")
    assert _os.path.exists(path), (
        f"{skill}: 缺少 {path} —— C 端 few-shot 是行为影响最大的一层，不允许缺（issue #3569）"
    )
    with open(path, "r", encoding="utf-8") as f:
        content = f.read().strip()
    min_chars = CUSTOMER_SKILL_LENGTH_SNAPSHOT[skill][0]
    assert len(content) >= min_chars, (
        f"{skill}: EXAMPLES 只有 {len(content)} 字符 < {min_chars} —— 被清空/截断？"
    )
    assert "## Few-shot 参考示例" in _customer_prompt(skill), (
        f"{skill}: 组装后的 prompt 没有 few-shot 段 —— EXAMPLES 未被加载"
    )


@pytest.mark.parametrize("skill", sorted(CUSTOMER_SKILL_LENGTH_SNAPSHOT))
def test_customer_inline_prompt_thickness(skill):
    """C 端内联 prompt（L4）不得被删减 —— C 端 6 个域都没有 L3，规则 100% 压在这层。"""
    inline = _customer_inline_prompt(skill)
    min_chars = CUSTOMER_SKILL_LENGTH_SNAPSHOT[skill][1]
    assert len(inline) >= min_chars, (
        f"{skill}: 内联 prompt 只有 {len(inline)} 字符 < {min_chars} —— "
        f"C 端领域规则主要在这层，被删减等于能力静默降级"
    )


@pytest.mark.parametrize("skill", sorted(CUSTOMER_SKILL_LENGTH_SNAPSHOT))
def test_customer_prompt_length_snapshot(skill):
    """C 端组装后长度（含内联 prompt）必须在区间内 —— 防无声变薄与失控膨胀。"""
    _, _, min_len, max_len = CUSTOMER_SKILL_LENGTH_SNAPSHOT[skill]
    prompt = _customer_prompt(skill)
    assert len(prompt) >= min_len, (
        f"{skill}: C 端 prompt 长度 {len(prompt)} < {min_len}。"
        f"检查 prompts/{skill}.md（L3）/ EXAMPLES-{skill}.md（L5）/ 内联 prompt 是否被削。"
    )
    assert len(prompt) <= max_len, (
        f"{skill}: C 端 prompt 长度 {len(prompt)} > {max_len}（可能重复拼接），"
        f"确认后更新 CUSTOMER_SKILL_LENGTH_SNAPSHOT。"
    )
    # 90% 预警（与 B 端快照同口径）：别一加就顶格
    if len(prompt) > max_len * 0.9:
        import warnings
        warnings.warn(
            f"⚠️  {skill}: C 端 prompt 长度 {len(prompt)}/{max_len} "
            f"({len(prompt)*100//max_len}%) — 接近上限，新内容需精简"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 报价协商口径「不再打架」（issue #4118 ⑥-B）
#
# 病根：**同一段 system prompt** 里两句相反指令 ——
#   L3（`references/prompts/customer_quote.md`）：「顾客问『还能便宜点吗』→ 传
#       craft_tier=economy 重算一档，给省 X 米布、省 ¥Y 的对比」；
#   L4（`customer_quote_skill.py` 的 `CUSTOMER_QUOTE_SYSTEM_PROMPT`）：「问能不能便宜/有优惠
#       → 引导活动页或到店确认，**不要承诺**」。
# L4 拼在**后**（调用点 `_build_system_prompt(skill_name, inline_prompt=system_prompt)`）
# ⇒ 实际行为取决于 L4；而笼统的「不要」会把 #3990 已交付的**工艺省料方案对比**一起禁掉。
# 治法（B：保留能力 + 消除矛盾）：两侧收口 —— 明确区分「**工艺省料方案对比**（要做）」
# 与「**价格优惠承诺**（不做）」，使两层的动作集**互不重叠**。
# ══════════════════════════════════════════════════════════════════════════════

def _bullets_with(text: str, marker: str):
    """返回含 `marker` 的**整行**（逐行 bullet 粒度；找不到返回空表）。"""
    return [ln.strip() for ln in text.splitlines() if marker in ln]


class TestQuoteNegotiationPromptNotConflicting:
    """省料对比要做、价格优惠承诺不做 —— L3 与 L4 对**同一动作**不得给出相反指令。"""

    #: L3 要求做的动作（工艺省料方案对比）的关键词
    SAVING_ACTION = ("重算", "省料", "省米", "工艺对比")
    #: L4 禁止的动作（价格优惠承诺）的关键词
    DISCOUNT_ACTION = ("价格优惠", "折扣")

    def _layers(self):
        """按**运行时口径**取三层：L3（md 原文）、L4（SkillConfig 内联）、组装结果。"""
        from app.graph.skills.customer_quote_skill import CUSTOMER_QUOTE_SYSTEM_PROMPT as L4

        with open(_os.path.join(_EXAMPLES_DIR, "prompts", "customer_quote.md"),
                  encoding="utf-8") as f:
            l3 = f.read()
        composed = _build_system_prompt("customer_quote", inline_prompt=L4)
        return l3, L4, composed

    def _l3_saving_bullet(self, l3: str) -> str:
        hits = _bullets_with(l3, "craft_tier=economy")
        assert len(hits) == 1, f"L3 的省料对比条目应恰好 1 条，实际 {len(hits)} 条：{hits}"
        return hits[0]

    def _l4_scope_of_prohibition(self, l4: str) -> str:
        """L4「不要承诺」的**宾语**（禁令作用域）—— 冲突与否全看这一段。"""
        hits = _bullets_with(l4, "不要承诺")
        assert len(hits) == 1, f"L4 的「不要承诺」条目应恰好 1 条，实际 {len(hits)} 条：{hits}"
        m = re.search(r"不要承诺([^。；\n]*)", hits[0])
        assert m, f"L4 的禁令句式变了，无法解析作用域：{hits[0]!r}"
        return m.group(1)

    def test_l3_keeps_saving_comparison_and_declares_it_not_a_discount(self):
        """L3：省料对比能力**保留**（#3990 已交付，删掉 = 删功能），且明说**不是**价格优惠承诺。"""
        l3, _, composed = self._layers()
        bullet = self._l3_saving_bullet(l3)
        assert "重算" in bullet and "省" in bullet, (
            f"L3 丢了「economy 重算给省 X 米布对比」能力 —— 这是 #3990 已交付的功能：{bullet!r}"
        )
        assert re.search(r"(不是|非)[^。；\n]{0,8}价格优惠", bullet), (
            f"L3 必须明说这是**工艺省料方案**的对比、**不是**价格优惠承诺（否则与 L4 打架）：{bullet!r}"
        )
        assert bullet in composed, "L3 的这条指导没进组装后的 system prompt"

    def test_l4_prohibition_is_scoped_to_price_discount_only(self):
        """L4：「不要承诺」的作用域**只限价格优惠**，且显式豁免省料对比（不再笼统禁）。"""
        _, l4, composed = self._layers()
        scope = self._l4_scope_of_prohibition(l4)
        assert any(k in scope for k in self.DISCOUNT_ACTION), (
            f"L4 的禁令宾语未限定为「价格优惠/折扣」，实际作用域={scope!r}"
        )
        leaked = [k for k in self.SAVING_ACTION if k in scope]
        assert not leaked, (
            f"L4 的禁令把省料对比一起禁掉了（命中 {leaked}）⇒ 与 L3 相反指令，"
            f"作用域={scope!r}"
        )
        assert any(k in l4 for k in ("省料", "工艺对比", "省米")), (
            "L4 必须显式豁免工艺省料对比（否则模型会连省料对比一起拒掉）"
        )
        assert "允许" in l4 or "可以" in l4, "L4 的豁免须是**允许式**表述，不是又一句禁令"

    def test_two_layers_address_disjoint_actions(self):
        """结构化判据：省料对比 = L3 要做 ∩ L4 不禁；价格优惠承诺 = L3 不要求 ∩ L4 禁。"""
        l3, l4, _ = self._layers()
        saving_bullet = self._l3_saving_bullet(l3)
        scope = self._l4_scope_of_prohibition(l4)

        # ① 省料对比：L3 要求做（正向指令），L4 的禁令作用域**不覆盖**它
        assert any(k in saving_bullet for k in self.SAVING_ACTION), saving_bullet
        assert not any(k in scope for k in self.SAVING_ACTION), (
            f"省料对比同时被 L3 要求、被 L4 禁止 ⇒ 两句打架：scope={scope!r}"
        )
        # ② 价格优惠承诺：L4 禁止，而 L3 的省料条目**不**对它下相反指令
        assert any(k in scope for k in self.DISCOUNT_ACTION), scope
        assert "不要承诺" not in saving_bullet, (
            f"L3 的省料条目里出现禁令句式 ⇒ 与 L4 的作用域再次交叠：{saving_bullet!r}"
        )
        # ③ 组装结果里两层都在（同一次调用的同一段 prompt）
        assert saving_bullet in _build_system_prompt(
            "customer_quote",
            inline_prompt=l4,
        )


# ══════════════════════════════════════════════════════════════════════════════
# 基础规则层 fail-loud（issue #4057 S5）
# ══════════════════════════════════════════════════════════════════════════════


class TestRequiredReferenceFilesFailLoud:
    """`identity.md` / `principles.md` / `PROMPT-rules.md` 缺失 ⇒ **不得静默返回 ""**。

    改前：`_read_cached` 对缺失/读失败一律 `_PROMPT_CACHE[path] = ""` 并返回 "" ⇒
    三个**基础规则层**文件缺失时整层公共规则静默消失（System Prompt 少一整层、
    模型行为漂移），而没有任何东西变红。
    改后：必需文件（`required=True`）缺失/为空 ⇒ error 级日志 + 抛
    `RequiredPromptMissingError`（fail-loud）；可选域文件（`prompts/<skill>.md` /
    `EXAMPLES-*.md`）仍返回 ""（这些层可缺席是合法形态）。

    静态侧（文件在磁盘上存在）由 L0 用例
    `tests/unit_ci_workflows/test_ai_agent_prompt_reference_guard.py` 锁。
    """

    def test_missing_required_file_raises_instead_of_returning_empty(self, tmp_path):
        """红证：必需文件不存在 ⇒ 抛错（改前返回 ""，本用例必红）。"""
        from app.graph.skills.base_skill import _read_cached, RequiredPromptMissingError

        missing = tmp_path / "base" / "identity.md"
        with pytest.raises(RequiredPromptMissingError):
            _read_cached(str(missing), required=True)

    def test_empty_required_file_also_raises(self, tmp_path):
        """必需文件存在但为空 ⇒ 内容上仍是「整层消失」，同样不得静默。"""
        from app.graph.skills.base_skill import _read_cached, RequiredPromptMissingError

        empty = tmp_path / "PROMPT-rules.md"
        empty.write_text("   \n", encoding="utf-8")
        with pytest.raises(RequiredPromptMissingError):
            _read_cached(str(empty), required=True)

    def test_required_path_cached_as_optional_is_still_loud(self, tmp_path):
        """负例边界：先按可选读到 ""（进缓存），再按必需读 ⇒ 仍必须响亮失败。

        否则「谁先读」会决定判据是否生效 —— 这正是静默形态本身。
        """
        from app.graph.skills.base_skill import _read_cached, RequiredPromptMissingError

        missing = tmp_path / "base" / "principles.md"
        assert _read_cached(str(missing)) == ""          # 可选通道：合法形态
        with pytest.raises(RequiredPromptMissingError):
            _read_cached(str(missing), required=True)

    def test_optional_domain_files_still_return_empty(self, tmp_path):
        """可选层（`prompts/<skill>.md`）缺席是**合法形态** —— 不得被 fail-loud 误伤。"""
        from app.graph.skills.base_skill import _read_cached

        assert _read_cached(str(tmp_path / "prompts" / "no_such_skill.md")) == ""

    def test_build_system_prompt_raises_when_a_base_layer_is_gone(self, tmp_path, monkeypatch):
        """端到端：基础层文件缺失 ⇒ `_build_system_prompt` 响亮失败（不产出"少一层"的 prompt）。"""
        import app.graph.skills.base_skill as base_skill

        (tmp_path / "base").mkdir()
        (tmp_path / "base" / "identity.md").write_text("身份", encoding="utf-8")
        # principles.md / PROMPT-rules.md 故意不给
        monkeypatch.setattr(base_skill, "_ref_dir", str(tmp_path))
        _PROMPT_CACHE.clear()
        with pytest.raises(base_skill.RequiredPromptMissingError):
            _build_system_prompt("order")

    def test_build_system_prompt_succeeds_when_all_base_layers_exist(self, tmp_path, monkeypatch):
        """负例（防恒红）：三层齐备 ⇒ 必须正常组装且真的拼进了三层内容。"""
        import app.graph.skills.base_skill as base_skill

        (tmp_path / "base").mkdir()
        (tmp_path / "base" / "identity.md").write_text("身份层内容", encoding="utf-8")
        (tmp_path / "base" / "principles.md").write_text("准则层内容", encoding="utf-8")
        (tmp_path / "PROMPT-rules.md").write_text("共享规则层内容", encoding="utf-8")
        monkeypatch.setattr(base_skill, "_ref_dir", str(tmp_path))
        _PROMPT_CACHE.clear()
        prompt = _build_system_prompt("order")   # 域文件缺席 ⇒ 可选层跳过，不报错
        for layer in ("身份层内容", "准则层内容", "共享规则层内容"):
            assert layer in prompt, f"基础层 {layer} 未被拼进 prompt"
