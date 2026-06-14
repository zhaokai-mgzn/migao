"""
防线 2: Prompt 黄金快照测试

验证 _build_system_prompt() 的组装结果：
- 每个 Skill 至少包含身份 + 原则
- 长度在合理范围
- 关键规则都存在
- 无意外交叉污染（product 的规则不应出现在 order 中）

改动 references/ 下的 Prompt 文件后运行此测试即可发现意外变更。
"""

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
    """Prompt 长度在合理范围（200-6000 字符）"""
    prompt = _build_system_prompt(skill)
    assert 200 < len(prompt) < 6000, f"{skill}: prompt 长度异常 ({len(prompt)} chars)"


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


def test_general_is_fallback_friendly():
    """兜底节点必须引导用户说出具体需求"""
    prompt = _build_system_prompt("general")
    assert "创建商品" in prompt or "写操作" in prompt  # 必须有写操作引导


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
        "product": 5000,
        "order": 4000,
        "aftersales": 3600,
        "customer": 3500,
        "staff": 3500,
        "settings": 3500,
        "data": 3500,
        "general": 4000,
    }
    for skill, max_len in expected_max.items():
        prompt = _build_system_prompt(skill)
        assert len(prompt) <= expected_max[skill], (
            f"{skill}: prompt 长度 {len(prompt)} > 上限 {expected_max[skill]}。"
            f"检查是否重复拼接了内容。"
        )
