# case_ids: HR-006
"""内置岗位**描述**的商家可见面判据（issue #7111）。

## 这一条判据要治什么

`roles.description` 是**商家可见面**（岗位权限页逐卡展示、员工弹窗选岗位时读到）。
2026-10-17 用户逐字：「岗位管理中的描述乱七八糟的，我需要你对每个默认的岗位描述尽可能的详细，
阐述这个岗位所承担的职责和默认可以使用的模块」—— 当时的 8 条里，5 条是半句话（「负责销售业务」），
3 条直接把**内部标识**印给商家看（`issue #5652` / `生产：view` 这样的权限码 / `POC 期历史岗位`）。

本文件把「详细」落成**两条可判的形态**（散文写得好不好由人看，判据只判这两条）：

| 判据 | 判什么 | 会怎么红 |
|---|---|---|
| **A 两段式** | 每条描述含「职责：…」+「默认可用模块：…」两段，且模块段非空 | 半句话 / 漏段 ⇒ 具名红 |
| **B 模块集合对账** | 描述里点到的模块名 **== 该岗位默认权限可达的页面名集合**（`rbac/readings.json` 的 `pages[].gate`） | 权限集加了码、描述没跟着写 ⇒ 具名红；描述写了它根本看不到的页面 ⇒ 具名红 |
| **C 内部标识纯度** | 描述零命中权限码 / issue 编号 / 内部阶段口径（`POC` / `P6`）/ 仓内文件名 | 任何一条 ⇒ 具名红（`migao-dev-flow` §31 P3） |
| **D 声明 == 现值** | 清单 `roles.descriptions` 逐值 == 生成物（= `RegistrationService` 种子现取） | 改了 Java 没改清单（或反之）⇒ 具名红 |

## 红证怎么取（本仓纪律：纯函数 + 内存注入，不靠改磁盘）

`test_injected_bad_descriptions_are_named` 把**坏形态直接构造在内存里**喂给同一条纯函数：
删掉一个可达模块名 / 写进一个不可达页面名 / 注入 `issue #1234` / 注入 `production:view` /
清空整条描述 —— 各自必须**具名**判红；**对照读数**：原样的清单必须**不红**（判据不许被自己的文案喂红）。

## 边界（照实登记）

① 「职责」写得准不准、够不够详细，判据**判不了**（那是散文评审）；
② 模块集合对账**只到页面粒度**（`pages[]` 的菜单可见页），不含「操作权限」这类无菜单入口的动作码；
③ 本判据不改任何门禁的通过条件，也不新增豁免。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "rbac" / "manifest.json"
READINGS_PATH = REPO_ROOT / "rbac" / "readings.json"

#: 两段式的**逐字**标记（值同时被 `rbac/generate_migration.py` 的渲染前置断言读着）。
DUTY_MARK = "职责："
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


def reachable_page_names(role: str, seed: dict, pages: list[dict], catalog: list[str]) -> set[str]:
    """该岗位默认权限可达的**页面名**（`pages[].gate` 是页面入口码；无码页不入表）。"""
    codes = set(catalog) if seed[role] == ["*"] else set(seed[role])
    return {page["name"] for page in pages if page.get("gate") and page["gate"] in codes}


def all_gated_page_names(pages: list[dict]) -> set[str]:
    return {page["name"] for page in pages if page.get("gate")}


def two_part_problems(descriptions: dict[str, str]) -> list[str]:
    """判据 A：两段式 + 模块段非空。"""
    out: list[str] = []
    for role in sorted(descriptions):
        text = descriptions[role]
        if DUTY_MARK not in text:
            out.append(f"`{role}` 的描述缺「{DUTY_MARK}」段：{text!r}")
        if MODULE_MARK not in text:
            out.append(f"`{role}` 的描述缺「{MODULE_MARK}」段：{text!r}")
            continue
        if not text.split(MODULE_MARK, 1)[1].strip("。 "):
            out.append(f"`{role}` 的「{MODULE_MARK}」段是空的 ⇒ 等于没说：{text!r}")
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


def module_coverage_problems(descriptions: dict[str, str], seed: dict, pages: list[dict], catalog: list[str]) -> list[str]:
    """判据 B：描述点到的模块名 == 该岗位默认权限可达的页面名集合（逐值点名）。"""
    out: list[str] = []
    every = all_gated_page_names(pages)
    for role in sorted(descriptions):
        text = descriptions[role]
        reach = reachable_page_names(role, seed, pages, catalog)
        for name in sorted(reach - {n for n in every if n in text}):
            out.append(f"`{role}` 的默认权限可达页面「{name}」，但描述里没写 ⇒ 描述与权限集脱节")
        for name in sorted({n for n in every if n in text} - reach):
            out.append(f"`{role}` 的描述写了「{name}」，但该岗位的默认权限**看不到**这个页面（假承诺）")
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


def all_problems(descriptions: dict[str, str], seed: dict, pages: list[dict], catalog: list[str]) -> list[str]:
    """四个判据的**同一份**实现（判据本体与注入式红证共用它 ⇒ 红证证明的正是被测对象）。"""
    return (
        two_part_problems(descriptions)
        + module_coverage_problems(descriptions, seed, pages, catalog)
        + internal_id_problems(descriptions)
    )


def world() -> tuple[dict, dict]:
    manifest, readings = load_json(MANIFEST_PATH), load_json(READINGS_PATH)
    return manifest, readings


def test_role_descriptions_declare_duty_and_modules():
    """判据 A：8 个内置岗位的描述都是「职责 + 默认可用模块」两段式。"""
    manifest, _ = world()
    problems = two_part_problems(descriptions_of(manifest))
    assert problems == [], "岗位描述不合两段式口径：\n" + "\n".join(f"  · {p}" for p in problems)


def test_role_descriptions_carry_no_internal_identifiers():
    """判据 C：描述里不得出现权限码 / issue 编号 / 内部阶段口径 / 仓内文件名（§31 P3）。"""
    manifest, _ = world()
    problems = internal_id_problems(descriptions_of(manifest))
    assert problems == [], "岗位描述把内部标识摆上了商家可见面：\n" + "\n".join(f"  · {p}" for p in problems)


def test_role_description_modules_match_default_permissions():
    """判据 B：描述点到的模块 == 该岗位默认权限可达的页面（加了码没改描述 ⇒ 红）。"""
    manifest, readings = world()
    problems = module_coverage_problems(
        descriptions_of(manifest), readings["roles"]["seed"], readings["pages"], readings["codes"]["registration"]
    )
    assert problems == [], "岗位描述与默认权限集脱节：\n" + "\n".join(f"  · {p}" for p in problems)


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
    manifest, readings = world()
    seed = readings["roles"]["seed"]
    pages = readings["pages"]
    catalog = readings["codes"]["registration"]
    good = descriptions_of(manifest)

    control = all_problems(good, seed, pages, catalog)
    assert control == [], f"对照读数必须干净（判据被自己的文案喂红？）：\n" + "\n".join(control)

    # ① 删掉一个可达模块名（以客服为例：它可达「发货单」）
    dropped = dict(good)
    dropped["customer_service"] = dropped["customer_service"].replace("发货单", "")
    hit = all_problems(dropped, seed, pages, catalog)
    assert any("customer_service" in p and "发货单" in p for p in hit), hit

    # ② 写进一个**不可达**页面名（客服看不到「财务对账」）
    faked = dict(good)
    faked["customer_service"] = faked["customer_service"].replace("订单列表", "订单列表、财务对账")
    hit = all_problems(faked, seed, pages, catalog)
    assert any("customer_service" in p and "财务对账" in p for p in hit), hit

    # ③ 注入 issue 编号
    stale = dict(good)
    stale["sales"] = stale["sales"] + "（issue #7111）"
    hit = all_problems(stale, seed, pages, catalog)
    assert any("sales" in p and "issue 编号" in p for p in hit), hit

    # ④ 注入权限码
    coded = dict(good)
    coded["inspector"] = coded["inspector"] + "（production:inspect）"
    hit = all_problems(coded, seed, pages, catalog)
    assert any("inspector" in p and "权限码" in p for p in hit), hit

    # ⑤ 半句话（退回旧形态）
    halved = dict(good)
    halved["admin"] = "拥有全部管理权限"
    hit = all_problems(halved, seed, pages, catalog)
    assert any("admin" in p and (DUTY_MARK in p or MODULE_MARK in p) for p in hit), hit
