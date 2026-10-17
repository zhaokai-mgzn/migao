# case_ids: HR-006, UI-117
"""内置岗位**描述**的商家可见面判据（issue #7111 起；issue #7146 改判为「职责-only + 派生化」）。

## 这一条判据要治什么

`roles.description` 是**商家可见面**（岗位权限页逐卡展示）。

- 2026-10-17 `#7111`：用户逐字「岗位管理中的描述乱七八糟的，我需要你对每个默认的岗位描述尽可能的详细，
  阐述这个岗位所承担的职责和默认可以使用的模块」⇒ 当时把「职责 + **默认可用模块**」两段**都写进了散文**。
- 🔴 同一个下午的 `#7146`：用户逐字「手机端可见面要不要作为『默认岗位默认菜单』的一部分，当然需要，
  **把 PC 和手机端当一个整体**」⇒ 模块清单**必须派生**（一份权限码 → 后台 + 手机端两面投影），
  不能再是散文 —— 散文只抄了后台菜单，且会漂（`#7087` 撤掉「每日简报」菜单后 7/8 条描述仍点名它，见 #7139）。

⇒ 现在的口径：**描述只承载「职责」**（散文，写得准不准由人看）；
**默认菜单 = 派生**（`frontend/admin-web/src/lib/role-default-menu.ts`，后台名取 `@/config/menu`、
手机端名只透传服务端 `mobileTitles`）。描述里再出现「默认可用模块：」= 把会漂的第二份真值写回来了 ⇒ **判红**。

## 判据（每条都会红）

| 判据 | 判什么 | 怎么红 |
|---|---|---|
| **A 职责-only** | 每条描述以「职责：」开头、正文非空，且**不含**「默认可用模块：」 | 半句话 / 把模块清单写回散文 ⇒ 具名红 |
| **C 内部标识纯度** | 描述零命中权限码 / issue 编号 / 内部阶段口径（`POC` / `P6`）/ 仓内文件名 | 任何一条 ⇒ 具名红（`migao-dev-flow` §31 P3） |
| **D 声明 == 现值** | 清单 `roles.descriptions` 逐值 == 生成物（= `RegistrationService` 种子现取） | 改了 Java 没改清单（或反之）⇒ 具名红 |

## 派生的那一半在哪判

「后台 + 手机端同一张卡」是**前端行为**：判据 =
`frontend/admin-web/tests/unit/lib/role-default-menu.test.ts`（纯函数：一份码集两面投影、
面名只透传服务端）与 `frontend/admin-web/tests/unit/pages/roles.test.tsx`（同一张卡渲染、
服务端改名 ⇒ 页面跟着改、0 入口、工人只读卡）。本文件**只**守「散文不再抄清单」这一半。

## 红证怎么取（本仓纪律：纯函数 + 内存注入，不靠改磁盘）

`test_injected_bad_descriptions_are_named` 把坏形态直接构造在内存里：
把「默认可用模块：…」写回任一条 / 注入 `issue #1234` / 注入 `production:view` /
清空整条描述 / 退回半句话 —— 各自必须**具名**判红；**对照读数**：原样的清单必须**不红**。

## 边界（照实登记）

① 「职责」写得准不准、够不够详细，判据**判不了**（那是散文评审）；
② 判据**不**检查「描述里有没有模块名」的语义（如「知识库」同时是菜单项与业务名词）——
   它只认**机制性标记**（「默认可用模块：」），因为那正是「清单回归散文」的承载体；
③ 本判据不改任何门禁的通过条件，也不新增豁免。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "rbac" / "manifest.json"
READINGS_PATH = REPO_ROOT / "rbac" / "readings.json"

#: 职责段的**逐字**开头（`rbac/generate_migration.py` 的渲染前置断言读同一串）。
DUTY_MARK = "职责："

#: 🔴 **已经退役**的散文段标记（issue #7146）：模块清单改为派生 ⇒ 它再出现就是「第二份会漂的真值」。
MODULE_MARK = "默认可用模块："

#: 内部标识形态（每条 = `(正则, 人话名字)`）。命中即「商家看不懂也无从行动」的东西上了可见面。
INTERNAL_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"[a-z][a-z_]*(?::[a-z][a-z_]*)+", "权限码"),
    (r"issue\s*#?\s*\d+", "issue 编号"),
    (r"#\d{3,}", "issue 编号"),
    (r"POC|P6(?![0-9])|\bP[0-9]+\b", "内部阶段口径"),
    (r"\.(?:java|sql|py|ts|tsx)\b", "仓内文件名"),
)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def descriptions_of(manifest: dict) -> dict[str, str]:
    """清单声明的岗位描述（**声明面**；缺失即 fail-closed）。"""
    descriptions = manifest["roles"].get("descriptions")
    assert isinstance(descriptions, dict) and descriptions, (
        "清单缺 `roles.descriptions` ⇒ 本判据会空跑（fail-closed）"
    )
    return descriptions


def duty_only_problems(descriptions: dict[str, str]) -> list[str]:
    """判据 A：描述 = 「职责：…」单段，且**不得**含已退役的模块清单标记。"""
    out: list[str] = []
    for role in sorted(descriptions):
        text = descriptions[role]
        if not text.startswith(DUTY_MARK):
            out.append(f"`{role}` 的描述缺「{DUTY_MARK}」开头：{text!r}")
            continue
        if not text[len(DUTY_MARK):].strip("。 "):
            out.append(f"`{role}` 的职责段是空的 ⇒ 等于没说：{text!r}")
        if MODULE_MARK in text:
            out.append(
                f"`{role}` 的描述把「{MODULE_MARK}」写回了散文 —— 模块清单必须派生"
                f"（一份权限码 → 后台 + 手机端；issue #7146）：{text!r}"
            )
    return out


def internal_id_problems(descriptions: dict[str, str]) -> list[str]:
    """判据 C：商家可见面上不得出现内部标识。"""
    out: list[str] = []
    for role in sorted(descriptions):
        text = descriptions[role]
        for pattern, label in INTERNAL_PATTERNS:
            for hit in re.findall(pattern, text):
                out.append(
                    f"`{role}` 的描述含{label} {hit!r}（商家看不懂也无从行动，§31 P3）：{text!r}"
                )
    return out


def declaration_problems(manifest: dict, readings: dict) -> list[str]:
    """判据 D：清单（声明）== 生成物（= `RegistrationService` 现取）。"""
    declared = descriptions_of(manifest)
    present = readings["roles"].get("descriptions")
    if not isinstance(present, dict) or not present:
        return ["生成物缺 `roles.descriptions` ⇒ 声明无人对账（fail-closed）"]
    out: list[str] = []
    for role in sorted(set(declared) | set(present)):
        if declared.get(role) != present.get(role):
            out.append(
                f"`{role}`：清单={declared.get(role)!r} / 现值={present.get(role)!r}"
                " —— 改了 `RegistrationService` 就要改清单并重渲染生成物（或反之）"
            )
    return out


def all_problems(descriptions: dict[str, str]) -> list[str]:
    """判据 A + C 的**同一份**实现（判据本体与注入式红证共用它 ⇒ 红证证明的正是被测对象）。"""
    return duty_only_problems(descriptions) + internal_id_problems(descriptions)


def world() -> tuple[dict, dict]:
    manifest, readings = load_json(MANIFEST_PATH), load_json(READINGS_PATH)
    return manifest, readings


def test_role_descriptions_are_duty_only():
    """判据 A：8 个内置岗位的描述 = 「职责：…」单段；模块清单已退役（必须派生）。"""
    manifest, _ = world()
    problems = duty_only_problems(descriptions_of(manifest))
    assert problems == [], "岗位描述不合「职责-only」口径：\n" + "\n".join(f"  · {p}" for p in problems)


def test_role_descriptions_carry_no_internal_identifiers():
    """判据 C：描述里不得出现权限码 / issue 编号 / 内部阶段口径 / 仓内文件名（§31 P3）。"""
    manifest, _ = world()
    problems = internal_id_problems(descriptions_of(manifest))
    assert problems == [], "岗位描述把内部标识摆上了商家可见面：\n" + "\n".join(f"  · {p}" for p in problems)


def test_role_descriptions_are_reconciled_with_the_seed():
    """判据 D：清单声明 == 生成物现值（`RegistrationService` 种子）。"""
    manifest, readings = world()
    problems = declaration_problems(manifest, readings)
    assert problems == [], "岗位描述的声明与现值不等：\n" + "\n".join(f"  · {p}" for p in problems)


def test_injected_bad_descriptions_are_named():
    """判别力自证：五种坏形态各自**具名**判红 + 一条对照读数（原样 ⇒ 不红）。

    注入**在内存里**发生（不改磁盘）：本仓实测过「改磁盘的变异可能不被读到 ⇒ 那种红证在 CI 上
    可能永远绿 = 空断言」（见同目录 `test_rbac_single_source_manifest.py` 的机具纪律）。
    """
    good = descriptions_of(world()[0])

    control = all_problems(good)
    assert control == [], f"对照读数必须干净（判据被自己的文案喂红？）：\n" + "\n".join(control)

    # ① 把已退役的「默认可用模块：」写回散文（#7146 的病灶形态）
    relapsed = dict(good)
    relapsed["sales"] = relapsed["sales"] + "默认可用模块：商品管理、生产看板。"
    hit = all_problems(relapsed)
    assert any("sales" in p and "默认可用模块" in p for p in hit), hit

    # ② 注入 issue 编号
    stale = dict(good)
    stale["sales"] = stale["sales"] + "（issue #7146）"
    hit = all_problems(stale)
    assert any("sales" in p and "issue 编号" in p for p in hit), hit

    # ③ 注入权限码
    coded = dict(good)
    coded["inspector"] = coded["inspector"] + "（production:inspect）"
    hit = all_problems(coded)
    assert any("inspector" in p and "权限码" in p for p in hit), hit

    # ④ 半句话（退回 #7111 之前的旧形态）
    halved = dict(good)
    halved["admin"] = "拥有全部管理权限"
    hit = all_problems(halved)
    assert any("admin" in p and DUTY_MARK in p for p in hit), hit

    # ⑤ 空职责段
    emptied = dict(good)
    emptied["finance"] = "职责："
    hit = all_problems(emptied)
    assert any("finance" in p and "空的" in p for p in hit), hit
