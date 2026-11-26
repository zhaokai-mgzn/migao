"""persona 身份层文件选择（issue #7292）。

身份层原先是**所有 persona 共用的** `base/identity.md` ⇒ C 端每轮都带
「你是黄金策，商家后台的 AI 管家」开场，而米宝身份只排在 Layer 4 inline。
单一职责：只回答「这个 persona 该读哪个身份文件」，不做读取、不做渲染。
依赖方向：无（纯映射 + 纯函数）；`base_skill` 单向 import 本模块，
本模块**不得**在顶层 import `base_skill`（加载期成环）。

判据：`tests/test_persona_identity_split.py`（身份文件不得点名另一端 + C 端组装面）。
"""

#: persona → 身份层文件（相对 `references/`）。
IDENTITY_FILES = {
    "mibao": "base/identity.md",
    "xiaobu": "base/identity-xiaobu.md",
}


def identity_rel_for(personas) -> str:
    """按 SkillConfig.system_prompts 的键选身份文件。

    绑定面是静态代码事实：B 端各 skill 只声明 `mibao`，C 端只声明 `xiaobu`。
    取不到 / 无法判定时回落到 mibao（与 `_capability_boundary` 的 persona 门控同向）。
    """
    return IDENTITY_FILES["xiaobu"] if set(personas or ()) == {"xiaobu"} else IDENTITY_FILES["mibao"]
