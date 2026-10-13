# case_ids: MC-097
"""**已移除页面名的旧指针改指「企业基础设置 → <域 label>」** 的实例判据（issue #6839 = #6826 的 B1 包）。

## 与 `test_removed_page_copy_guard.py`（MC-096）的分工（**不是第二份守卫**）

- **MC-096** = **类级元守卫**：任何 Java 字面量里出现 `REMOVED_PAGE_NAMES` 而未登记进台账 ⇒ 红。
  它判的是「**有没有漏网的旧页名**」——**判不了**「那个新指针指向的域对不对」。
- **本文件** = **实例判据**：判「① 本包那 6 个文件**确实**改指了**正确**的域」（正控，逐域断言）
  与「② 台账被清到**只剩能力名**那 3 条」（清零的**真读数**，不是嘴说）。

⇒ 合起来才有意义：只跑 MC-096，把旧指针**删掉**（或改指另一个错域）它一样绿。

## 判据（逐条会红；红证见 `test_injection_*`）

| # | 判什么 |
|---|---|
| 1 | 6 个承包文件的服务端字面量里**零** `REMOVED_PAGE_NAMES`（改前红：逐条具名报出） |
| 2 | **逐域正控**：4 个目标域 label 各被对应的服务读到（「企业基础设置 → 加工费组合 / 加工项与分类 / 工艺路线 / 工序与部位单价」） |
| 3 | **两处假出口**改写后**不再含**该页名、且给出的是**真边界**（工艺词的写面不存在 ⇒ 不许出现新的页面坐标） |
| 4 | 台账 = **3 条 / 3 处**（只剩能力名）且 `FROZEN_MAX_*` 与台账**逐值一致**（常量与台账不许各说一套） |
| 5 | 域 label 真值源现取非空（fail-closed；域被改名 ⇒ 红而不是静默空集） |

## 边界（照实登记，`migao-dev-flow` §19.1）

① 判**文本**不判**上屏**（真机截图那一半要 §15.7）；② 判不了「假出口真的不可达」——
那需要遍历商家面写能力的**语义**判断，本文件只判「不再给出那个不存在的坐标」；
③ 能力名 3 处（`PermissionService` / `RegistrationService`）**有意不改** ⇒ 不在正控里，也不进判据 1 的必改集。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(REPO_ROOT / "tests"))
from unit_ci_workflows._source_parsing import java_literals  # noqa: E402

LEDGER_PATH = REPO_ROOT / "tests" / "unit_ci_workflows" / "removed_page_copy_ledger.json"
GUARD_PATH = REPO_ROOT / "tests" / "unit_ci_workflows" / "test_removed_page_copy_guard.py"
DOMAINS_TS = REPO_ROOT / "frontend" / "admin-web" / "src" / "lib" / "config-center-domains.ts"
SERVICE_REL = "backend/admin-api/src/main/java/com/migao/admin/service"

#: 已移除页面名（与 MC-096 的 `REMOVED_PAGE_NAMES` **同一份集合语义**，取法 = 现读守卫，见判据 5）。
REMOVED_NAMES = ("参数总览", "工艺配置", "加工项管理", "加工费管理")

#: 本包承包的**必改**文件（页名指针）。
MUST_FIX_FILES = (
    "ProcessingFeeCalculator.java",
    "ProcessingFeeCombinationCommandService.java",
    "ProductionRoutingCommandService.java",
    "ProcessingOrderService.java",
    "ProductionInstanceRepricingService.java",
    "ProductionService.java",
)

#: 能力名（权限/岗位显示名）—— **有意不改**，判据 1 不为它们红。
CAPABILITY_FILES = ("PermissionService.java", "RegistrationService.java")

#: 逐域正控：目标域 label 必须被对应的服务读到（域真值源 = `config-center-domains.ts`）。
DOMAIN_POSITIVE_CONTROLS = {
    "ProcessingFeeCalculator.java": "企业基础设置 → 加工费组合",
    "ProcessingFeeCombinationCommandService.java": "企业基础设置 → 加工项与分类",
    "ProductionRoutingCommandService.java": "企业基础设置 → 加工项与分类",
    "ProcessingOrderService.java": "企业基础设置 → 工艺路线",
    "ProductionInstanceRepricingService.java": "企业基础设置 → 工序与部位单价",
    "ProductionService.java": "企业基础设置 → 工序与部位单价",
}

#: 台账清到只剩能力名（3 条 / 3 处）。
EXPECTED_LEDGER_ENTRIES = 3
EXPECTED_LEDGER_HITS = 3


def sources() -> dict[str, str]:
    out: dict[str, str] = {}
    for name in MUST_FIX_FILES + CAPABILITY_FILES:
        path = REPO_ROOT / SERVICE_REL / name
        assert path.is_file(), f"承包文件不存在（路径漂了）：{path}"
        out[name] = path.read_text(encoding="utf8")
    return out


def literals_of(source: str) -> list[str]:
    """该源码里的**字符串字面量**（注释不算 —— 与 MC-096 同一把尺子）。"""
    return [text for _pos, text in java_literals(source)]


def removed_name_literals(source: str) -> list[tuple[str, str]]:
    """返回 `(已移除页面名, 字面量)` 命中清单。"""
    out: list[tuple[str, str]] = []
    for literal in literals_of(source):
        for name in REMOVED_NAMES:
            if name in literal:
                out.append((name, literal))
    return out


# ── 判据 1 ────────────────────────────────────────────────────────────────────


def test_contract_files_carry_no_removed_page_name():
    """判据 1（**改前红**）：6 个承包文件的服务端字面量里零已移除页面名。"""
    problems: list[str] = []
    for name, source in sources().items():
        if name in CAPABILITY_FILES:
            continue
        for removed, literal in removed_name_literals(source):
            problems.append(f"{SERVICE_REL}/{name} 的字面量仍含已移除页面名「{removed}」⇒ {literal!r}")
    assert problems == [], "陈旧导航指针未改净：\n" + "\n".join(problems)


# ── 判据 2：逐域正控 ───────────────────────────────────────────────────────────


def test_each_domain_pointer_is_the_current_domain_label():
    """判据 2：四个目标域 label 各被对应的服务**逐字**读到（改指错域 ⇒ 红）。"""
    problems: list[str] = []
    for name, expected in DOMAIN_POSITIVE_CONTROLS.items():
        literals = literals_of(sources()[name])
        if not any(expected in text for text in literals):
            problems.append(f"{SERVICE_REL}/{name} 的字面量里读不到新指针 {expected!r}（域指错 / 没改）")
    assert problems == [], "域指针正控失败：\n" + "\n".join(problems)


# ── 判据 3：两处假出口 ─────────────────────────────────────────────────────────


def test_false_exits_no_longer_name_a_nonexistent_coordinate():
    """判据 3：工艺词表 / 默认工艺两处**假出口**改写后不得再出现那个坐标，也不得**新编**页面名。

    - `ProductionRoutingCommandService`：craft 触发值那条**不许**再写「工艺词表」（商家面无该页、无写能力）；
      改写后必须说清**真边界**（触发值只能取自本店**已有的活跃工艺**）。
    - `ProcessingOrderService`：默认工艺那条**不许**再写「工艺配置」；仍保留真出路（下单时给出工艺）。
    """
    routing = literals_of(sources()["ProductionRoutingCommandService.java"])
    craft_hints = [t for t in routing if "触发键查不到" in t or "请先" in t]
    assert craft_hints, "`ProductionRoutingCommandService` 的 craft 触发值提示不见了（判据失去对象 ⇒ fail-closed）"
    assert all("工艺词表" not in t for t in craft_hints), (
        "假出口未改写：「工艺词表」在商家面无页面、无写能力（只经 `GET /route-rule-options` 供下拉取值）"
    )
    assert any("已有的活跃工艺" in t or "已有的工艺" in t for t in routing), (
        "改写后必须说清**真边界**（触发值只能取自本店已有的活跃工艺 / 换一个已有的 / 联系服务方新增）"
    )

    order = literals_of(sources()["ProcessingOrderService.java"])
    default_hints = [t for t in order if "默认工艺" in t]
    assert default_hints, "`ProcessingOrderService` 的默认工艺提示不见了（判据失去对象 ⇒ fail-closed）"
    assert all("工艺配置" not in t for t in default_hints), "默认工艺那条仍是陈旧页名坐标"
    assert any("下单时给出工艺" in t for t in order), "改写不得把**真出路**（下单时给出工艺）一起删掉"


# ── 判据 4：台账清零的真读数 ───────────────────────────────────────────────────


def test_ledger_shrunk_to_capability_names_only():
    """判据 4：台账 = 3 条 / 3 处（只剩能力名），且 `FROZEN_MAX_*` 与台账**逐值一致**。"""
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf8"))
    entries = list(ledger.get("entries", []))
    total = sum(int(e.get("hits", 0)) for e in entries)
    assert (len(entries), total) == (EXPECTED_LEDGER_ENTRIES, EXPECTED_LEDGER_HITS), (
        f"台账应为 {EXPECTED_LEDGER_ENTRIES} 条 / {EXPECTED_LEDGER_HITS} 处（只剩能力名），"
        f"现取 {len(entries)} 条 / {total} 处"
    )
    for entry in entries:
        assert entry.get("name") in REMOVED_NAMES, f"台账条目名字不在集合里：{entry!r}"
        assert "能力" in entry.get("reason", ""), (
            f"剩下的条目必须具名说清它是**能力名（不是坐标）**⇒ {entry.get('path')} 的 reason 未说明"
        )
    guard = GUARD_PATH.read_text(encoding="utf8")
    frozen = {
        key: int(m.group(1))
        for key in ("FROZEN_MAX_ENTRIES", "FROZEN_MAX_HITS")
        if (m := re.search(rf"^{key} = (\d+)$", guard, re.M))
    }
    assert frozen.get("FROZEN_MAX_ENTRIES") == EXPECTED_LEDGER_ENTRIES, (
        f"守卫的 FROZEN_MAX_ENTRIES={frozen.get('FROZEN_MAX_ENTRIES')} 与台账条数 "
        f"{EXPECTED_LEDGER_ENTRIES} 不一致（常量与台账不许各说一套）"
    )
    assert frozen.get("FROZEN_MAX_HITS") == EXPECTED_LEDGER_HITS, (
        f"守卫的 FROZEN_MAX_HITS={frozen.get('FROZEN_MAX_HITS')} 与台账命中数 "
        f"{EXPECTED_LEDGER_HITS} 不一致"
    )


def test_capability_names_stay_out_of_the_pointer_rewrite():
    """判据 4b（**负控**）：能力名那 2 个文件**不许**被改成页面坐标（改了就是语义错误）。"""
    problems: list[str] = []
    for name in CAPABILITY_FILES:
        for literal in literals_of(sources()[name]):
            if "企业基础设置 →" in literal:
                problems.append(f"{SERVICE_REL}/{name} 的能力名被误改成页面坐标 ⇒ {literal!r}")
    assert problems == [], "能力名误改为坐标：\n" + "\n".join(problems)


# ── 判据 5 + 判别力自证 ────────────────────────────────────────────────────────


def test_domain_truth_source_is_live():
    """判据 5（fail-closed）：域 label 真值源必须现取到那四个域（域改名 / 文件漂 ⇒ 红）。"""
    assert DOMAINS_TS.is_file(), f"域真值源不存在：{DOMAINS_TS}"
    text = DOMAINS_TS.read_text(encoding="utf8")
    labels = re.findall(r"label: '([^']+)'", text)
    assert len(labels) >= 8, f"域 label 只读出 {len(labels)} 个 —— 解析器被改坏 / 域塌了 ⇒ 红（不是「无需判」）"
    for expected in ("加工费组合", "加工项与分类", "工艺路线", "工序与部位单价"):
        assert expected in labels, f"域 label 真值源里没有「{expected}」⇒ 新指针指向了一个不存在的域"


def test_injection_detects_a_reverted_pointer():
    """判别力自证：把真语料里的新指针**改回旧指针** ⇒ 判据 1 当场红（不是恒绿）。"""
    name = "ProductionService.java"
    source = sources()[name]
    mutated = source.replace("企业基础设置 → 工序与部位单价", "工艺配置 → 工艺路线")
    assert mutated != source, "变异没生效（正控锚在新源码里找不到）⇒ 判据会假绿"
    hits = removed_name_literals(mutated)
    assert hits and any(n == "工艺配置" for n, _ in hits), f"注入失效：变异后未检出旧页名 ⇒ {hits}"


def test_injection_comment_only_change_is_not_red():
    """对照读数：**只加注释**（含旧页名）⇒ 判据 1 不红（沿革注释合法）。"""
    source = sources()["ProcessingFeeCalculator.java"]
    commented = source + "\n// 沿革：这里曾指向「加工费管理」（issue #6839 已改指「企业基础设置 → 加工费组合」）\n"
    assert removed_name_literals(commented) == [], "只改注释却被判红（与 MC-096 的对照读数应一致）"
