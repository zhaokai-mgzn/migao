# case_ids: AG-014
"""persona 身份层分流（issue #7292）。

病根（2026-10-19 立案，2026-11-25 现取复现）：`base/identity.md` 被**所有 persona 共用**
⇒ `_build_system_prompt("customer_order")` 首段是「你是黄金策…词元通达商家管理后台」，
米宝身份只排在 Layer 4 inline；同一 prompt 里身份互相矛盾，C 端每轮都带 B 端语气铁律。

修法：`identity.md`（mibao）/ `identity-xiaobu.md`（xiaobu）分流，选哪条由 skill 的
`SkillConfig.system_prompts` 决定（`_persona_for_skill`）。
本文件锁两件事：① 两个身份文件各自点名自己、不点名另一端（元判据）；② C 端 6 个 skill
的**组装后** prompt 只带 C 端身份（行为判据，走真实现 `_build_system_prompt`）。
"""
import os

import pytest

from app.graph.skills.base_skill import _build_system_prompt
from app.graph.skills.skill_registry import get_skill_registry

XIAOBU_SKILLS = (
    "customer_order",
    "customer_product",
    "customer_quote",
    "customer_aftersales",
    "customer_knowledge",
    "customer_general",
)

_REF_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "app", "graph", "skills", "references",
)


def _read_identity(name: str) -> str:
    with open(os.path.join(_REF_DIR, "base", name), encoding="utf-8") as f:
        return f.read()


def _assembled(skill: str) -> str:
    """按运行时口径组装（C 端领域规则主要写在 L4 inline prompt 里）。"""
    cfg = get_skill_registry().get_or_raise(skill)
    inline = (cfg.system_prompts or {}).get(cfg.default_persona, "")
    return _build_system_prompt(skill, inline_prompt=inline)


def test_identity_files_do_not_cross_personas():
    """元判据：每个 persona 的身份文件必须点名自己、**不得点名另一端**。

    红证：把 `identity-xiaobu.md` 首行改回「你是黄金策…商家后台」⇒ 本用例必红；
    把 `identity.md` 删掉/改名 ⇒ 组装路径抛 `RequiredPromptMissingError`（fail-loud）。
    """
    mibao = _read_identity("identity.md")
    xiaobu = _read_identity("identity-xiaobu.md")
    assert "黄金策" in mibao, "mibao 身份文件未点名自己"
    assert "米宝" not in mibao, "mibao 身份文件混入了 C 端身份"
    assert "智能客服" in xiaobu, "xiaobu 身份文件缺 C 端身份（智能客服）"
    assert "米宝" not in xiaobu, "C 端身份文件仍自称米宝（2026-11-28 裁定已改称智能客服）"
    assert "黄金策" not in xiaobu, "xiaobu 身份文件仍带 B 端身份（#7292 回归）"
    assert "商家后台" not in xiaobu, "xiaobu 身份文件仍带商家后台口径"


@pytest.mark.parametrize("skill", XIAOBU_SKILLS)
def test_xiaobu_prompt_carries_only_customer_identity(skill):
    """C 端每个 skill 的组装 prompt 只带米宝身份，不带黄金策 / 商家后台。"""
    prompt = _assembled(skill)
    assert "智能客服" in prompt, f"{skill}: 组装 prompt 缺 C 端身份（智能客服）"
    assert "米宝" not in prompt, f"{skill}: 组装 prompt 仍在自称米宝（2026-11-28 裁定）"
    assert "黄金策" not in prompt, f"{skill}: 组装 prompt 仍带 B 端身份"
    assert "商家后台" not in prompt, f"{skill}: 组装 prompt 仍带商家后台口径"
