# case_ids: MC-097, MC-098, MC-128
"""**已移除页面名的旧指针改指「企业基础设置 → <域 label>」** 的实例判据（issue #6839 = #6826 的 B1 包）。

## 与 `test_removed_page_copy_guard.py`（MC-096）的分工（**不是第二份守卫**）

- **MC-096** = **类级元守卫**：任何 Java 字面量里出现 `REMOVED_PAGE_NAMES` 而未登记进台账 ⇒ 红。
  它判的是「**有没有漏网的旧页名**」——**判不了**「那个新指针指向的域对不对」。
- **本文件** = **实例判据**：判「① 本包那 6 个文件**确实**改指了**正确**的域」（正控，逐域断言）
  与「② 台账被清到**只剩能力名**那 3 条」（清零的**真读数**，不是嘴说）。
- 另含**内部端点泄漏**那一族（§31 P3）的**类级**判据 + 只许缩短台账
  （`restricted_literal_leaks_ledger.json`；跟踪单 = issue #6841）。

⇒ 合起来才有意义：只跑 MC-096，把旧指针**删掉**（或改指另一个错域）它一样绿。

## 判据（逐条会红；红证见 `test_injection_*`）

| # | 判什么 |
|---|---|
| 1 | 6 个承包文件的服务端字面量里**零** `REMOVED_PAGE_NAMES`（改前红：逐条具名报出） |
| 2 | **逐域正控**：4 个目标域 label 各被对应的服务读到（「企业基础设置 → 加工费组合 / 加工项与分类 / 工艺路线 / 工序与部位单价」） |
| 3 | **两处假出口**改写后**不再含**该页名、且给出的是**真边界**（工艺词的写面不存在 ⇒ 不许出现新的页面坐标） |
| 4 | 台账 = **2 条 / 2 处**（只剩能力名，issue #7111 起）且 `FROZEN_MAX_*` 与台账**逐值一致**（常量与台账不许各说一套） |
| 5 | 域 label 真值源现取非空（fail-closed；域被改名 ⇒ 红而不是静默空集） |
| 6 | **§31 P3 类级**：admin-api 字面量里「商家答复型提示 + 内部端点」的命中必须逐条在 `restricted_literal_leaks_ledger.json` 里（未登记即红 / 幽灵条目即红 / 条数 ≤ 冻结基线） |
| 6b | **键不许含行号**（issue #6977 的类级元守卫）：台账键 = `文件::字面量::#出现序号`，纯数字段即红；只插空行（行号漂移）⇒ 判据 6 仍绿，真删已登记端点 ⇒ 判据 6 红 |
| 7 | `REMOVED_NAMES` 与 MC-096 守卫的 `REMOVED_PAGE_NAMES` **逐值相等**（本文件是镜像 ⇒ 镜像漂了要红，不许静默用旧集合） |
| 8 | **跨包指针消费者 ⇄ 后端下发面**双向核对（issue #6853）：登记的消费者文件代码区里必须逐字带着后端下发的域指针，且该指针**仍在下发**（删任一侧 ⇒ 在**本 Python 腿**就红，不必等前端腿） |

## 边界（照实登记，`migao-dev-flow` §19.1）

① 判**文本**不判**上屏**（真机截图那一半要 §15.7）；② 判不了「假出口真的不可达」——
那需要遍历商家面写能力的**语义**判断，本文件只判「不再给出那个不存在的坐标」；
③ 能力名 3 处（`PermissionService` / `RegistrationService`）**有意不改** ⇒ 不在正控里，也不进判据 1 的必改集；
④ 判据 6 的判据面是「**商家答复型**提示里的端点」（`GET/POST/PUT/DELETE/PATCH /api/...` 或「查看入口 / 读面 + 路径」）——
**不是**「所有字面量里的端点」（端点注释 / 开发者面 / 无操作动词的裸路径**不在面内**），
故它**判不了**「某个 hit 到底会不会上屏给商家」；⑤ 台账里剩的条目是**跨单债务**（跟踪 issue #6841），本文件不为它们背书。
"""

from __future__ import annotations

import ast
import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(REPO_ROOT / "tests"))
from unit_ci_workflows._source_parsing import java_literals  # noqa: E402

LEDGER_PATH = REPO_ROOT / "tests" / "unit_ci_workflows" / "removed_page_copy_ledger.json"
LEAK_LEDGER_PATH = REPO_ROOT / "tests" / "unit_ci_workflows" / "restricted_literal_leaks_ledger.json"
GUARD_PATH = REPO_ROOT / "tests" / "unit_ci_workflows" / "test_removed_page_copy_guard.py"
DOMAINS_TS = REPO_ROOT / "frontend" / "admin-web" / "src" / "lib" / "config-center-domains.ts"
SERVICE_REL = "backend/admin-api/src/main/java/com/migao/admin/service"

#: 🔴 **本文件里的已移除页面名是镜像** —— 真值源 = MC-096 守卫的 `REMOVED_PAGE_NAMES`，
#: 由判据 `test_removed_names_mirror_mc096_guard` **逐值核**（漂了要红，见该判据的 docstring）。
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

#: 台账清到只剩能力名（2 条 / 2 处）。
#: 🔻 2026-10-17（issue #7111）：岗位描述改成「职责 + 默认可用模块」后，`RegistrationService` 的
#: **加工项管理**那条能力名（旧商品管理员描述整句）在扫描面上不再存在 ⇒ 按「只许缩短」销账
#: （3 条 / 3 处 ⇒ 2 条 / 2 处）；本常量与 `test_removed_page_copy_guard` 的 `FROZEN_MAX_*` 同步收窄。
EXPECTED_LEDGER_ENTRIES = 2
EXPECTED_LEDGER_HITS = 2

#: 内部端点泄漏台账的冻结基线（**只许缩短**；跟踪单 issue #6841）。
LEAK_LEDGER_BASELINE = 9

#: §31 P3 判据面（**收紧**，见文件头「边界 ④」）：字面量里出现「HTTP 动词 + `/api/` 路径」**且**含中文字符
#: —— 即**人话提示里夹着端点**。端点常量 / worker 端点文档串 / 路由声明字面量**有意不在面内**
#: （台账 `_doc` 里具名登记了这三类）。
API_CALL_RE = re.compile(r"\b(GET|POST|PUT|DELETE|PATCH)\s+/api/")
CJK_RE = re.compile(r"[\u4e00-\u9fff]")


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
    """判据 4：台账 = 2 条 / 2 处（只剩能力名，issue #7111 起），且 `FROZEN_MAX_*` 与台账**逐值一致**。"""
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


# ── 判据 6：§31 P3 类级（内部端点泄漏 + 只许缩短台账）────────────────────────────


#: 端点泄漏台账的**键形态**（issue #6977）：`仓库相对路径::字面量原文::#出现序号`。
#: 🔴 **不含行号** —— 行号是可变分量：它一漂，该文件里**所有**已登记条目会同时变成
#: 「未登记（新行号）」+「陈旧（旧行号）」**双向假红**（红的是排版，不是泄漏）。
LEAK_KEY_RE = re.compile(r"^(?P<path>[^:]+)::(?P<literal>.+)::#(?P<index>\d+)$")


def leak_scan_face() -> dict[str, str]:
    """扫描面语料：`backend/admin-api/src/main/java/**/*.java` 的 `仓库相对路径 → 原文`。"""
    root = REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "java"
    files = sorted(root.rglob("*.java"))
    assert files, f"扫描面为空：{root} —— 射程塌了 ⇒ 红（fail-closed）"
    return {path.relative_to(REPO_ROOT).as_posix(): path.read_text(encoding="utf8") for path in files}


def scan_endpoint_leaks(sources: Mapping[str, str]) -> list[dict]:
    """在给定语料上现取「商家答复型提示 + 内部端点」的命中（纯函数 ⇒ 可注入式自证）。

    `line` **只用于报错定位**，不进台账键（issue #6977）；键的身份 = `路径 + 字面量 + 出现序号`。
    """
    out: list[dict] = []
    for rel, source in sorted(sources.items()):
        seen: dict[str, int] = {}
        for pos, literal in java_literals(source):
            if not (API_CALL_RE.search(literal) and CJK_RE.search(literal)):
                continue
            seen[literal] = seen.get(literal, 0) + 1
            out.append({
                "path": rel,
                "line": source[:pos].count("\n") + 1,
                "literal": literal,
                "index": seen[literal],
            })
    return out


def leak_hits() -> list[dict]:
    return scan_endpoint_leaks(leak_scan_face())


def leak_key(hit: dict) -> str:
    """台账键 = `文件::字面量原文::#出现序号`（**不含行号**，issue #6977）。

    - **为什么不能带行号**：行号是**可变分量**。任何人在被监视文件里增删一行（与泄漏毫不相干的改动）
      都会让该文件里**所有**已登记条目**同时**变成「未登记（新行号）」+「陈旧（旧行号）」**双向假红**
      —— 红的是排版，不是泄漏；作者唯一的出路是把每条 `line` 手工重锚，而债务内容一字未变
      （PR #6973 的实测形态：同一批改动报出「未登记 5 处」与「台账未被兑现 3 处」）。
    - **为什么仍要出现序号**：`AgentBatchService` 有**两条字面量完全相同**的提示
      （「用 GET /api/admin/agent/batches/」×2）—— 只用 `文件::字面量` 会把两条合并成一条，
      于是「未登记 / 台账未被兑现」两侧都可能对不上（一条登记、另一条被判幽灵）。
    - **序号的稳定性**：序号 = 同文件、**同字面量**的出现顺序 ⇒ 插空行 / 移方法 / 整体重排都不变；
      两条同串互换先后时键集合不变 ⇒ 仍绿（身份是**字面量本身**，不是它落在哪一行）。
    """
    return f"{hit['path']}::{hit['literal']}::#{int(hit['index'])}"


def leak_ledger() -> dict:
    """读泄漏台账；**旧形态（键含行号）⇒ 红并给出重新生成入口**（不静默接受）。"""
    assert LEAK_LEDGER_PATH.is_file(), f"泄漏台账不存在：{LEAK_LEDGER_PATH} —— fail-closed"
    ledger = json.loads(LEAK_LEDGER_PATH.read_text(encoding="utf8"))
    legacy = [e for e in ledger.get("entries", []) if "index" not in e or "line" in e]
    assert not legacy, (
        "泄漏台账是**旧形态**（键含行号）⇒ 请重新生成（幂等：第二次跑零 diff）：\n"
        f"  python3 {Path(__file__).resolve().relative_to(REPO_ROOT).as_posix()} --migrate-leak-ledger\n"
        f"旧形态条目：{[(e.get('path'), e.get('line')) for e in legacy]}"
    )
    return ledger


def leak_key_problems(entries: list[dict], hits: list[dict]) -> list[str]:
    """纯函数判定：**未登记即红** + **台账未被兑现即红**（**不比行号**）。"""
    detected = {leak_key(h): h for h in hits}
    registered = {leak_key(e): e for e in entries}
    problems: list[str] = []
    for key, hit in sorted(detected.items()):
        if key not in registered:
            problems.append(
                f"未登记：{hit['path']}:{hit['line']} 的商家答复型字面量含内部端点 ⇒ {hit['literal']!r}"
                f"（键 = {key}；请删掉端点从句**不指路**，或按只许缩短登记进台账 + 跟踪单 #6841）"
            )
    for key, entry in sorted(registered.items()):
        if key not in detected:
            problems.append(
                f"台账未被兑现：{entry['path']} 的 {entry['literal']!r}（第 {entry['index']} 次出现）"
                "在扫描面上**已不存在** ⇒ 该条陈旧（销账即删，台账只许缩短）"
            )
    return problems


def key_shape_problems(key: str) -> list[str]:
    """纯函数判定（**元级**）：键本身不许把行号当身份（issue #6977 的类级元守卫）。"""
    problems: list[str] = []
    numeric = [seg for seg in key.split("::") if seg.isdigit()]
    if numeric:
        problems.append(
            f"台账键含**纯数字段** {numeric}（= 旧形态 `文件::行::字面量`）⇒ 重排即双向假红：{key}"
        )
    match = LEAK_KEY_RE.match(key)
    if match is None:
        problems.append(f"台账键不符合 `路径::字面量::#出现序号`：{key}")
        return problems
    path = REPO_ROOT / match.group("path")
    if not path.is_file():
        problems.append(f"台账键的路径不存在：{match.group('path')}")
    elif match.group("literal") not in [text for _pos, text in java_literals(path.read_text(encoding="utf8"))]:
        problems.append(f"台账键的字面量在该文件的字面量里找不到（锚已悬空）：{key}")
    if int(match.group("index")) < 1:
        problems.append(f"台账键的出现序号必须 ≥ 1：{key}")
    return problems


def leak_key_shape_problems(entries: list[dict]) -> list[str]:
    """逐条判键形态（元守卫入口；`index` 缺失 / 仍留 `line` 都算旧形态）+ 重复键判红。"""
    problems: list[str] = []
    for entry in entries:
        if "index" not in entry or "line" in entry:
            problems.append(
                f"台账条目仍是旧形态（`line` 当锚 / 缺 `index`）：{entry.get('path')} "
                f"{entry.get('literal')!r} line={entry.get('line')}"
            )
            continue
        problems.extend(key_shape_problems(leak_key(entry)))
    keys = [leak_key(entry) for entry in entries if "index" in entry]
    for key in sorted({k for k in keys if keys.count(k) > 1}):
        problems.append(f"台账键重复（两条登记抢同一个键 ⇒ 一条会被静默吞掉）：{key}")
    return problems


def migrate_legacy_ledger(path: Path = LEAK_LEDGER_PATH) -> bool:
    """一次性迁移：旧键 `文件::行::字面量` ⇒ 新键 `文件::字面量::#出现序号`（issue #6977）。

    **幂等**：已是新形态 ⇒ **零写入**（返回 `False`）；同一输入第二次跑必须逐字节零 diff。
    **自证**：每条旧条目的旧行号必须能在**现取扫描**里解析到同一条命中（行号 → 序号），
    解析不到 ⇒ 直接报错（fail-closed，不做「猜一个序号」）。
    """
    ledger = json.loads(path.read_text(encoding="utf8"))
    entries = list(ledger.get("entries", []))

    def is_new(entry: dict) -> bool:
        return "index" in entry and "line" not in entry

    if all(is_new(entry) for entry in entries):
        return False
    if any(is_new(entry) for entry in entries):
        raise SystemExit("台账是**混合形态**（部分已迁）⇒ 先人工核对；本迁移只接受「全旧」或「全新」")

    hits = leak_hits()
    by_path: dict[str, list[dict]] = {}
    for entry in entries:
        by_path.setdefault(entry["path"], []).append(entry)
    for rel, group in by_path.items():
        line_to_index = {hit["line"]: hit["index"] for hit in hits if hit["path"] == rel}
        for entry in group:
            ordinal = line_to_index.get(int(entry["line"]))
            if ordinal is None:
                raise SystemExit(
                    f"迁移无法自证：{rel} 的旧行号 {entry['line']} 在现取扫描面上不存在 ⇒ 先对账再迁移"
                )
            entry.pop("line")
            entry["index"] = ordinal
    ledger["entries"] = entries
    unresolved = leak_key_problems(entries, hits)
    if unresolved:
        raise SystemExit("迁移无法自证（迁移后台账与现取命中对不上）：\n" + "\n".join(unresolved))
    path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    return True


def test_merchant_hint_endpoint_leaks_are_all_registered():
    """判据 6：未登记即红 + 幽灵条目即红 + 条数 ≤ 冻结基线（**只许缩短**）。

    键 = `文件::字面量::#出现序号`（**不含行号**，issue #6977）⇒ 只重排文件（插空行 / 移方法）
    不会红；真加 / 真删泄漏照旧红（判别力由 ::test_injection_* 逐条自证）。

    改前实测（本包修 6 处**之前**）命中 16 处；修掉 `ProductionOrderService` 4 处 +
    `ProductionRoutingCommandService` 5 处 + `ProcessingFeeCombinationCommandService` 1 处后，
    仍剩本台账登记的条目（跟踪 issue #6841）。
    """
    hits = leak_hits()
    entries = list(leak_ledger().get("entries", []))
    assert len(entries) == LEAK_LEDGER_BASELINE, (
        f"泄漏台账条数 {len(entries)} ≠ 冻结基线 {LEAK_LEDGER_BASELINE}（**只许缩短**；"
        "加条目必须同 PR 改大基线并在 PR body 说明为什么它是跨单债务）"
    )
    problems = leak_key_problems(entries, hits)
    assert problems == [], "内部端点泄漏台账对不上：\n" + "\n".join(problems)
    for entry in entries:
        assert entry.get("issue", "").strip(), f"泄漏台账条目缺跟踪单：{entry!r}"
        assert entry.get("reason", "").strip(), f"泄漏台账条目缺 reason：{entry!r}"


def test_leak_ledger_keys_carry_no_line_number():
    """判据 6b（**类级元守卫**）：台账键不许把行号当身份（issue #6977）。

    否则同类缺陷会以「下次某人又把 `line` 写回键里」的形态原样复发 —— 这条就是让那一步**进不来**。
    """
    entries = list(leak_ledger().get("entries", []))
    problems = leak_key_shape_problems(entries)
    assert problems == [], "泄漏台账键形态不合规：\n" + "\n".join(problems)


def test_injection_line_numbered_key_is_red():
    """判别力自证（判据 6b）：把键退回旧形态 `文件::行::字面量` ⇒ **元守卫必须红**。"""
    entries = list(leak_ledger().get("entries", []))
    assert entries, "台账为空 ⇒ 注入失去对象（fail-closed）"
    legacy_key = entries[0]["path"] + "::252::" + entries[0]["literal"]
    assert key_shape_problems(legacy_key) != [], f"旧形态键没被判红 ⇒ 元守卫退化成空断言：{legacy_key}"
    # 对照组：合规键（含出现序号）必须**不**红 —— 否则「不许纯数字段」被写成了「不许有任何数字」。
    assert key_shape_problems(leak_key(entries[0])) == [], "合规键被判红 ⇒ 元守卫口径写错"
    legacy_entries = [
        {"path": entry["path"], "literal": entry["literal"], "line": 252} for entry in entries[:1]
    ]
    assert leak_key_shape_problems(legacy_entries) != [], "条目级旧形态（`line` 当锚）没被判红"


def test_injection_blank_line_shift_keeps_endpoint_ledger_green():
    """判据 6c（**本单验收判据①**）：只在被监视文件里插空行（行号整体漂移）⇒ 判据 6 **仍绿**。

    修前形态（issue #6977 的实测红证，PR #6973）：键含行号 ⇒ 同一批改动同时报
    「未登记 5 处」+「台账未被兑现 3 处」。这条把那个形态钉死。
    """
    rel = f"{SERVICE_REL}/AgentBatchService.java"
    source = (REPO_ROOT / rel).read_text(encoding="utf8")
    shifted = source.replace("\n", "\n\n\n")  # 每个换行后再插两个空行 ⇒ 行号整体放大
    assert shifted.count("\n") > source.count("\n") * 2, "注入没生效（行号没漂）⇒ 这条自证会假绿"
    before = [hit for hit in leak_hits() if hit["path"] == rel]
    after = scan_endpoint_leaks({rel: shifted})
    entries = [entry for entry in leak_ledger().get("entries", []) if entry["path"] == rel]
    assert entries, f"台账里没有 {rel} 的条目 ⇒ 这条自证失去对象（fail-closed）"
    assert leak_key_problems(entries, before) == [], "修前就先红 ⇒ 台账与语料已漂，先对账"
    assert [hit["line"] for hit in before] != [hit["line"] for hit in after], "行号没漂 ⇒ 注入无效"
    assert leak_key_problems(entries, after) == [], (
        "插入空行后判据 6 变红 ⇒ 键仍按行锚（issue #6977 未修净）："
        f"{leak_key_problems(entries, after)}"
    )


def test_injection_deleting_a_registered_endpoint_turns_red():
    """判据 6d（**本单验收判据②**）：真的删掉一处已登记端点 ⇒ 判据 6 **必红**（陈旧条目）。"""
    rel = f"{SERVICE_REL}/ProductionOperationCommandService.java"
    source = (REPO_ROOT / rel).read_text(encoding="utf8")
    entries = [entry for entry in leak_ledger().get("entries", []) if entry["path"] == rel]
    assert len(entries) == 1, f"台账里 {rel} 应恰有 1 条（现取 {len(entries)}）⇒ 自证对象漂了，先对账"
    entry = entries[0]
    assert entry["literal"] in source, "台账字面量在源码里找不到 ⇒ 台账已陈旧，先对账"
    stripped = API_CALL_RE.sub("", entry["literal"]).strip()
    mutated = source.replace(entry["literal"], stripped)
    assert mutated != source, "变异没生效（正控锚找不到）⇒ 判据会假绿"
    problems = leak_key_problems(entries, scan_endpoint_leaks({rel: mutated}))
    assert problems and all("台账未被兑现" in problem for problem in problems), (
        f"删掉已登记端点后判据 6 没红 ⇒ 判据被改宽成永远绿：{problems}"
    )


def test_legacy_ledger_reader_fails_closed_with_regenerate_hint(tmp_path, monkeypatch):
    """读取侧兜底：旧形态台账 ⇒ **红**并给出重新生成入口（不静默接受旧键）。"""
    legacy = {"entries": [{"path": "x.java", "literal": "y", "line": 3, "issue": "#1", "reason": "r"}]}
    target = tmp_path / "ledger.json"
    target.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf8")
    monkeypatch.setattr(sys.modules[__name__], "LEAK_LEDGER_PATH", target)
    with pytest.raises(AssertionError, match="--migrate-leak-ledger"):
        leak_ledger()


def test_legacy_ledger_migration_is_idempotent_and_semantics_preserving(tmp_path):
    """一次性迁移的**幂等 + 语义等价**判据（issue #6977）。

    - 幂等：第二次跑 = **零写入**，台账逐字节不变；
    - 等价：迁移后的 `(路径, 字面量, 出现序号)` 与现取台账**逐值相等**（债务认定一字未改，
      只把锚从「行号」换成「字面量 + 出现序号」）。
    """
    ledger = json.loads(LEAK_LEDGER_PATH.read_text(encoding="utf8"))
    by_key = {leak_key(hit): hit for hit in leak_hits()}
    legacy_entries = [
        {
            "path": entry["path"],
            "literal": entry["literal"],
            "line": by_key[leak_key(entry)]["line"],
            "hits": entry["hits"],
            "issue": entry["issue"],
            "kind": entry["kind"],
            "reason": entry["reason"],
        }
        for entry in ledger["entries"]
    ]
    target = tmp_path / "ledger.json"
    target.write_text(
        json.dumps({**ledger, "entries": legacy_entries}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf8",
    )
    assert migrate_legacy_ledger(target) is True, "旧形态没有迁移（迁移器失效）"
    first = target.read_bytes()
    assert migrate_legacy_ledger(target) is False, "第二次迁移仍写盘 ⇒ 不幂等"
    assert target.read_bytes() == first, "第二次迁移不是逐字节零 diff ⇒ 不幂等"
    migrated = json.loads(first)["entries"]
    assert [(e["path"], e["literal"], e["index"]) for e in migrated] == [
        (e["path"], e["literal"], e["index"]) for e in ledger["entries"]
    ], "迁移结果与现取台账不逐值相等（语义漂了）"
    assert leak_key_problems(migrated, leak_hits()) == [], "迁移后台账与现取命中对不上"


# ── 判据 7：镜像一致性（本文件 vs MC-096 守卫）────────────────────────────────────


def test_removed_names_mirror_mc096_guard():
    """判据 7：`REMOVED_NAMES` 必须与 MC-096 守卫的 `REMOVED_PAGE_NAMES` **逐值相等**。

    ⚠️ 为什么必须有这条（本仓点名的「注释漂移」形态）：本文件的名字集合是**本地镜像** ——
    守卫那边加/删一个页名而这里没跟，本判据会**静默**用旧集合 ⇒ **假绿**。
    取法 = **`ast` 读语法单元**（`Module.body` 里的 `Assign` ⇒ `ast.literal_eval`）——
    **不是**「按引号扫原文」（那种口径被 `test_guard_parsing_is_comment_aware.py` 的元守卫拦，
    issue #5325：注释 / docstring 里的同形文本会喂中它）；
    同时**不 import 守卫**，避免把它的模块级副作用带进来。
    """
    tree = ast.parse(GUARD_PATH.read_text(encoding="utf8"), filename=str(GUARD_PATH))
    value = next(
        (
            ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "REMOVED_PAGE_NAMES" for t in node.targets)
        ),
        None,
    )
    # 判红可归因（且**不是**裸存在性弱断言）：把「没读到 / 读到的不是字符串元组 / 读到空集」三态各自报出来。
    assert isinstance(value, tuple), (
        f"守卫里读不到 `REMOVED_PAGE_NAMES` 的字符串元组（AST 里没有该赋值，或它已不是元组字面量）：{value!r}"
        " ⇒ 红（fail-closed，不是「无对象可判」）"
    )
    assert value, f"守卫的 `REMOVED_PAGE_NAMES` 是空元组：{value!r}（集合塌了 ⇒ 红，不是「无需判」）"
    assert all(isinstance(x, str) for x in value), f"`REMOVED_PAGE_NAMES` 成员不全是字符串：{value!r}"
    guard_names = tuple(value)
    assert guard_names, f"守卫的 `REMOVED_PAGE_NAMES` 解析出空集：{value!r}"
    assert REMOVED_NAMES == guard_names, (
        f"本文件的 REMOVED_NAMES={REMOVED_NAMES} 与守卫的 REMOVED_PAGE_NAMES={guard_names} 不一致 —— "
        "镜像是本地硬编码的，漂了这条判据才是唯一会响的东西"
    )


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


def test_injection_leak_endpoint_is_detected():
    """判别力自证（判据 6 那一族）：把端点从句**写回**一个字面量 ⇒ 判据 6 当场判「未登记」。"""
    literal = "请在工序库补上 韩褶（或改这条路线不再引用它们）；工序库目录查看入口 GET /api/admin/production/operations-catalog"
    assert API_CALL_RE.search(literal), "判据 6 的判据面读不到端点 ⇒ 判据会假绿"
    injected = {"path": f"{SERVICE_REL}/X.java", "line": 1, "literal": literal, "index": 1}
    problems = leak_key_problems([], [injected])  # 只判「未登记」这一侧（不给台账条目）
    assert problems and all("未登记" in problem for problem in problems), (
        f"新增未登记泄漏却没有判红 ⇒ 判据被改宽成永远绿：{problems}"
    )


# ── 判据 8：跨包指针消费者（issue #6853）──────────────────────────────────────────

#: 🔴 **跨包锚点登记**（issue #6853）：后端下发的「企业基础设置 → <域>」指针的**跨包消费者**。
#: 为什么必须在**前端腿之外**另守一层：B1（#6839）删掉后端常量 `PRICING_ENTRY` 时，
#: `frontend/admin-web/tests/unit/pages/orders-new-fee-preview.test.tsx` 仍在抽它 ⇒ **admin-web 腿**必红，
#: 而 main 的 push 腿**看不见** admin-web 腿（核过 `de7ccd6f5` 的 check-runs）⇒ 合并后才炸、还卡住在飞的 PR。
#: ⇒ 「已无消费者」这种判断必须**由机器**代答，不能靠包作者的 grep。
#: 键 = (消费者文件, 该文件**代码区**里必须逐字出现的指针串)。
CROSS_PACKAGE_POINTER_CONSUMERS = (
    ("frontend/admin-web/tests/unit/pages/orders-new-fee-preview.test.tsx", "企业基础设置 → 加工费组合"),
    ("frontend/admin-web/src/app/(dashboard)/orders/new/page.tsx", "企业基础设置 → 加工费组合"),
)

_TS_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_TS_LINE_COMMENT = re.compile(r"(?m)//.*$")
_DOMAIN_POINTER_RE = re.compile(r"「(企业基础设置 → [^」]+)」")


def _ts_code_only(text: str) -> str:
    """TS/TSX 的**非注释**区（先剥块注释、再剥行注释）。

    边界（照实登记）：不做字符串字面量级解析 ⇒ 字符串里的 `//`（如 URL）也会被当注释切掉 ——
    对本判据无影响（域指针串里没有 `//`）。这么做是为了让「只在注释里提到指针」**不算**消费者仍带着它。
    """
    return _TS_LINE_COMMENT.sub("", _TS_BLOCK_COMMENT.sub("", text))


def emitted_domain_pointers() -> set[str]:
    """后端 `service/` 目录**字面量**里下发的全部域指针（现取，不写死清单）。"""
    out: set[str] = set()
    for path in sorted((REPO_ROOT / SERVICE_REL).glob("*.java")):
        for _pos, literal in java_literals(path.read_text(encoding="utf8")):
            out.update(_DOMAIN_POINTER_RE.findall(literal))
    return out


def _read_consumer_code(rel: str) -> str | None:
    path = REPO_ROOT / rel
    if not path.is_file():
        return None
    return _ts_code_only(path.read_text(encoding="utf8"))


def cross_package_pointer_problems(consumers, emitted, read_code) -> list[str]:
    """纯函数判定（便于注入式自证）：消费者 ⇄ 后端下发面**双向**核对。"""
    problems: list[str] = []
    for rel, pointer in consumers:
        code = read_code(rel)
        if code is None:
            problems.append(f"{rel}：文件不存在（改名 / 删除 ⇒ 红；别只改台账）")
            continue
        if pointer not in code:
            problems.append(f"{rel}：代码区里不再带着后端下发的指针「{pointer}」")
        if pointer not in emitted:
            problems.append(
                f"{rel}：后端**已不再下发**指针「{pointer}」（现取 = {sorted(emitted)}）⇒ 消费者悬空"
            )
    return problems


def test_cross_package_pointer_consumers_still_exist():
    """判据 8：**跨包指针消费者**必须与后端下发面同时成立（issue #6853 的类级固化）。"""
    emitted = emitted_domain_pointers()
    assert emitted, (
        "后端 service 目录里读不到任何「企业基础设置 → <域>」指针 ⇒ 红（fail-closed，不是「无对象可判」）"
        " —— 本判据的判据面塌了"
    )
    problems = cross_package_pointer_problems(
        CROSS_PACKAGE_POINTER_CONSUMERS, emitted, _read_consumer_code
    )
    assert problems == [], "跨包指针消费者对不上：\n" + "\n".join(problems)


def test_injection_cross_package_pointer_guard_discriminates():
    """判别力自证（判据 8）：三种坏形态各自判红 + 一条对照读数。"""
    consumers = (("x.tsx", "企业基础设置 → 加工费组合"),)
    ok_code = "… 企业基础设置 → 加工费组合 …"
    ok_emitted = {"企业基础设置 → 加工费组合"}
    assert cross_package_pointer_problems(consumers, ok_emitted, lambda _r: ok_code) == []
    # ① 消费者换了坐标（真注入实测：把链接文案改成「工艺配置 → 工艺路线」⇒ admin-web 腿 2 failed）
    assert cross_package_pointer_problems(consumers, ok_emitted, lambda _r: "工艺配置 → 工艺路线") != []
    # ② 后端不再下发该指针（= B1 删锚点那一半）
    assert cross_package_pointer_problems(consumers, set(), lambda _r: ok_code) != []
    # ③ 消费者文件被删 / 改名
    assert cross_package_pointer_problems(consumers, ok_emitted, lambda _r: None) != []
    # ④ 对照读数：**只在注释里**出现 ≠ 消费者仍带着它（否则这条判据就是空断言）
    assert "企业基础设置 → 加工费组合" not in _ts_code_only("// 企业基础设置 → 加工费组合\n")


if __name__ == "__main__":  # pragma: no cover —— 一次性迁移入口（幂等；本文件其余部分是 pytest 判据）
    import argparse

    _parser = argparse.ArgumentParser(description="内部端点泄漏台账的键迁移（issue #6977）")
    _parser.add_argument(
        "--migrate-leak-ledger",
        action="store_true",
        help="把旧键 `文件::行::字面量` 迁到 `文件::字面量::#出现序号`（幂等：已是新形态则零写入）",
    )
    _args = _parser.parse_args()
    if _args.migrate_leak_ledger:
        print("✅ 已迁移到新键（请提交台账）" if migrate_legacy_ledger() else "✅ 已是新形态（幂等：零写入）")
        raise SystemExit(0)
    raise SystemExit("本文件是 pytest 判据；唯一的脚本用法 = --migrate-leak-ledger")
