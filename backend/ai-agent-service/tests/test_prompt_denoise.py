# case_ids: OR-013
"""B 端（黄金策）system prompt 去噪判据。

## 病根（读数，来源 `docs/audit-2026-10/02-mibao-capability-review.md` F7）

每轮 system prompt 5.7~15KB，其中 **53 处** `#NNNN` 形态的内部 issue 号写在**会进 prompt 的
正文**里（`prompts/product.md` 9、`EXAMPLES-product.md` 6、`prompts/order.md` 5 …）。它们对
模型零信息价值、纯占 token，还会把内部编号交到模型手上（可能被复述给商家）。

## 判据（装配面，不是源文件面）

用**既有装配入口** `base_skill._build_system_prompt(skill, inline_prompt=<该 skill 的 mibao
prompt>)` 取**最终** system prompt，断言：

1. `#\\d{4,}` = **0**（`test_prompt_sources_have_no_issue_ref`）；
2. `<!--` 不出现（`test_no_html_comment_marker`）—— 渲染层 `_read_cached()` **不剥离** HTML
   注释（原样读文件、只 `strip()` 首尾空白）⇒ 必须断言「**原文**不含」，而不是「剥离后不含」；
3. 唯一具名残留 `_REGISTRY_DERIVED_RESIDUE`（见下）**只许缩短**。

## 为什么 1 要减去「能力边界」段

该段由 `app/agents/capability_boundary.py` 按工具注册表**现算投影**（段首括注 `issue #7291`），
**不在本包的写面**（该文件由能力边界包独占）。⇒ 判据把 `_capability_boundary()` 的返回值
（逐字相等才替换）从被测文本里摘掉，判**其余全部** prompt 正文；残留另由
`test_issue_ref_residue_is_only_the_known_anchor` 具名兜住 —— 在别处新增 issue 号（含在
能力边界段里）⇒ 红。

## 红证（注入式，逐条命令见 PR body）

| 注入 | 会红的判据 |
|---|---|
| 往 `references/prompts/order.md` 塞回 `（issue #9999）` | `test_prompt_sources_have_no_issue_ref[order]` |
| 往 `app/agents/capability_boundary.py` 段首再加一个 `#9999` | `test_issue_ref_residue_is_only_the_known_anchor`（11 档全红） |
| 往任一域 prompt 塞 `<!-- 内部备注 -->` | `test_no_html_comment_marker`（11 档全红） |
| 检测器退化成空转（正则写错 / 扫描面为空） | `test_detector_has_discrimination_power` |

## 边界（照实登记）

- **C 端（元元 / `xiaobu`）不在本判据射程**：本包只清 B 端 mibao 面的编号（源文件面
  `references/**` 53 → 5 处、Python prompt 常量 31 → 0 处）。C 端仍有同形态编号
  （`prompts/customer_knowledge.md` 2、`prompts/customer_quote.md` 2、
  `EXAMPLES-customer_knowledge.md` 1、`customer_order_skill.py` 12、`customer_quote_skill.py` 1），
  另行收口 —— 本判据**不为它们背书**。
- 判据判的是**装配后的文本**：将来渲染层若补了剥离逻辑，判据仍在装配面成立（不会假绿）。
"""

import re

import pytest

from app.graph.skills.base_skill import (
    _PROMPT_CACHE,
    _build_system_prompt,
    _capability_boundary,
)
from app.graph.skills.skill_registry import get_skill_registry

#: 内部 issue 号形态（4 位以上；与审计 F7 的读数口径逐字一致）。
ISSUE_REF_RE = re.compile(r"#\d{4,}")

#: **唯一具名残留**（只许缩短，不许新增）：能力边界段的段首括注由
#: `app/agents/capability_boundary.py` 现算投影生成，那个文件不在本包写面。
#: 它被清掉时本集合可以一并变空（`<=` 断言不会因此变红）；**新增**任意一条 ⇒ 红。
_REGISTRY_DERIVED_RESIDUE = frozenset({"#7291"})

#: 必须被覆盖的 B 端域（fail-closed：注册表里少一个域 ⇒ 判据不空转）。
EXPECTED_MIBAO_SKILLS = frozenset({
    "product", "order", "aftersales", "customer", "staff",
    "settings", "data", "general", "knowledge", "notification", "reminder",
})


def _mibao_skill_names() -> "list[str]":
    registry = get_skill_registry()
    return sorted(
        cfg.name for cfg in registry.get_all()
        if "mibao" in (cfg.system_prompts or {})
    )


MIBAO_SKILLS = _mibao_skill_names()


def _assembled_prompt(skill: str) -> str:
    """装配后的**最终** system prompt（与 `prepare_turn` 同一入口 + 同一 persona）。"""
    _PROMPT_CACHE.clear()
    cfg = get_skill_registry().get(skill)
    return _build_system_prompt(skill, inline_prompt=cfg.get_prompt("mibao"))


def _prompt_without_registry_projection(skill: str) -> str:
    """装配后 prompt 减去「能力边界」段（注册表投影，见模块 docstring 的说明）。"""
    prompt = _assembled_prompt(skill)
    boundary = _capability_boundary(skill)
    if boundary and boundary in prompt:
        return prompt.replace(boundary, "")
    return prompt


def _issue_refs(text: str) -> "list[str]":
    """检测器本体（判据 1、2 与自证共用**同一份**实现，不复制规则）。"""
    return ISSUE_REF_RE.findall(text or "")


# ============ 覆盖面（判据不许空转） ============

def test_mibao_skill_coverage_is_not_empty():
    """覆盖面必须含全部 11 个 B 端域 —— 注册表改名/漏注册时判据不能安静变绿。"""
    missing = EXPECTED_MIBAO_SKILLS - set(MIBAO_SKILLS)
    assert not missing, f"判据面缺少这些 B 端 skill（注册表变了？）：{sorted(missing)}"
    assert len(MIBAO_SKILLS) >= len(EXPECTED_MIBAO_SKILLS)


# ============ 判据 1：渲染后文本不得含内部 issue 号 ============

@pytest.mark.parametrize("skill", MIBAO_SKILLS)
def test_prompt_sources_have_no_issue_ref(skill):
    """装配后的 prompt 正文（能力边界段除外）**零** `#NNNN`。"""
    refs = _issue_refs(_prompt_without_registry_projection(skill))
    assert not refs, (
        f"{skill}: 装配后的 system prompt 里又有内部 issue 号 {sorted(set(refs))} "
        f"（共 {len(refs)} 处）—— 它们对模型零信息价值、纯占 token，还可能是"
        f"「被复述给商家」的素材。历史说明请写到代码注释 / 文档里，别写进正文"
        f"（判据 = backend/ai-agent-service/tests/test_prompt_denoise.py）"
    )


# ============ 判据 2：HTML 注释原文不得进 prompt ============

@pytest.mark.parametrize("skill", MIBAO_SKILLS)
def test_no_html_comment_marker(skill):
    """装配后的 prompt 不含 `<!--` —— 渲染层（`_read_cached`）不剥离注释，注释会原样进 prompt。"""
    prompt = _assembled_prompt(skill)
    assert "<!--" not in prompt, (
        f"{skill}: 装配后的 prompt 含 `<!--` —— `_read_cached()` 只 `strip()` 首尾空白、"
        f"**不剥离** HTML 注释 ⇒ 注释内容原样进模型上下文（占 token 且可能被复述）"
    )


# ============ 判据 3：残留只许缩短（具名台账） ============

@pytest.mark.parametrize("skill", MIBAO_SKILLS)
def test_issue_ref_residue_is_only_the_known_anchor(skill):
    """**未剥除**的全量 prompt 里，issue 号去重集合必须 ⊆ `_REGISTRY_DERIVED_RESIDUE`。

    ⚠️ 这是 `<=` 不是 `==`：真的把那段投影里的括注清掉时本断言**不会**因此变红
    （残留集合变空是合法的「缩短」）；**新增**一条 ⇒ 红。
    """
    refs = _issue_refs(_assembled_prompt(skill))
    unknown = sorted(set(refs) - _REGISTRY_DERIVED_RESIDUE)
    assert not unknown, (
        f"{skill}: 全量 prompt 里出现**计划外**的内部编号 {unknown}。唯一允许的残留是"
        f"{sorted(_REGISTRY_DERIVED_RESIDUE)}（来自 `app/agents/capability_boundary.py` 的"
        f"注册表投影段首括注，不在本判据的清理写面）。新出现的编号请从 prompt 正文删掉"
        f"（历史写进代码注释 / 文档）"
    )


# ============ 反向判别力自证（判据不是空转） ============

def test_detector_has_discrimination_power():
    """检测函数对**合成噪声**必须判红、对干净文本必须不判红（红/绿双向对照）。"""
    noisy = "规则正文……（issue #1234 用户裁定 2026-09-01）另有 #99999 一处 <!-- 内部备注 -->"
    assert _issue_refs(noisy) == ["#1234", "#99999"], "检测器漏判合成噪声 ⇒ 判据是空转"
    assert "<!--" in noisy
    clean = "规则正文……（商家点「确认」后执行）"
    assert _issue_refs(clean) == [], "检测器把干净文本判红 ⇒ 判据会假红"
    assert "<!--" not in clean


def test_injected_noise_into_real_prompt_turns_red():
    """把噪声**塞回真实 prompt 文本**：判据 1 用的那条扫描必须当场发现（真实载体上的自证）。"""
    real = _prompt_without_registry_projection("order")
    assert _issue_refs(real) == [], "基线不干净：先确认本判据的基线读数"
    injected = real + "\n（issue #9999）\n"
    assert _issue_refs(injected) == ["#9999"], "真实 prompt 上检测器失效 ⇒ 判据 1 没有牙"
