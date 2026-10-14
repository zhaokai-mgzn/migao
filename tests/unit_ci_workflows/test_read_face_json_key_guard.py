# case_ids: PG-018, PG-030
"""读面 JSON 键的**类级元守卫**（issue #6890；源自 issue #6867 / B3 的实测陷阱）。

## 病根（一类缺陷，不是一个缺陷）

本仓全局 ObjectMapper **没有** `SNAKE_CASE` 命名策略，且 `spring.jackson.default-property-inclusion: non_null`
（`backend/admin-api/src/main/resources/application.yml`）⇒ 一个字段**不显式标注 `@JsonProperty`**
就会静默按 Jackson 默认 bean 命名下发 **camelCase**（`short_code` ⇒ `shortCode`）。
而消费方吃的是**冻结键**（`frontend/admin-web/src/components/orders/ProcessingDoc.tsx` 读 `processingOrder.short_code`）⇒
**错配之后纸面静默退化成「无码」，没有任何东西会红**。B3（PR #6887）这次是靠人读到才钉住的；
它落下的 13 条实例判据只守 `ProcessingOrderResponse` 的**那两个键**，下次换一个 DTO / 换一个键仍然静默。

## 射程（**现取**，不照抄，不写死条数；表达式与依据如下）

**表达式**：`backend/admin-api/src/main/java` 下**承载至少一个显式 `@JsonProperty` 的类**（含嵌套类，按 `Outer.Inner` 记）。

**依据（现取读数）**：显式 `@JsonProperty` 是本仓**唯一**的「冻结键」声明手段 —— 不标注就走 Jackson 默认
camelCase。全仓 `src/main` 里这样的类**恰好 5 个**（`ProcessingOrderResponse` + 其嵌套
`ProcessingOrderItemBrief`、`CategoryCreateRequest` / `CategoryResponse` / `CategoryUpdateRequest`），
共 **13** 个显式键，**全部** snake_case。
反过来的依据同样现取：`com.migao.admin.dto` 下 109 个 DTO 文件里 **96** 个含 camelCase 键 ——
把整个 DTO 包当射程会立刻大范围假红，因为**未冻结**面的既有契约就是 camelCase
（前端按 camelCase 消费 `orderNo` / `isTenant` 这一类键），那不是缺陷。⇒ 射程按「**有没有冻结键声明**」划。

**自扩展**：任何一个**新**类只要写下显式 `@JsonProperty`，就**自动**进入射程 ⇒ 未登记即红（判据 1 的反向）。

**第二类载体（Map，判据 6b）**：冻结键不只在 DTO 字段上 —— 部位读面
（`GET /api/admin/production/orders/{orderId}/operations`，issue #4946 的 `part_short_code` / `scan_url`）
的键是 `ProductionService` 里 `position.put(...)` 的 **Map 条目**。这类键**没有** `@JsonProperty`
⇒ 上面那条射程表达式看不见它，故由台账 `map_view_faces` **逐键给代码锚**（锚须逐字出现且含 `.put(`）：
锚消失（键被删 / 改名 / 搬走）或锚不再证明它是 Map 条目（载体换成 DTO）⇒ 红。

## 判据（每条都会红，且具名）

| # | 判据 | 会怎么红 |
|---|---|---|
| 1 | **射程 ⇄ 台账双向相等**：射程集合必须等于台账 `classes` 的键集合 | 新加一个带冻结键的类没登记 ⇒ 具名报出该类；台账多了个已不存在的类 ⇒ 具名 |
| 2 | **冻结键风格**：射程内每个显式 `@JsonProperty` 的值必须 snake_case（`^[a-z][a-z0-9_]*$`） | 写成 `@JsonProperty("shortCode")` ⇒ `类::字段 ⇒ 实际键名` |
| 3 | **键清单双向相等**：台账 `<字段> -> <键>` 的完整清单 ⇄ 代码实际键 | 摘掉注解 ⇒ 实际键变 `shortCode` ≠ 登记值（具名）；新增字段未登记 / 台账多一条 ⇒ 具名 |
| 4 | **账本侧「代码有、账本无」**：台账点名由 `docs/wiki/CONTRACT-LEDGER.md` 登记的冻结键，必须在锚行里逐字出现 | 从账本锚行删掉 `` `short_code` `` ⇒ 红 |
| 5 | **账本侧「账本有、代码无」**：锚行里 snake 形态的反引号 token 必须 ∈（该类代码键 ∪ 行内白名单词汇） | 往锚行注入一个不存在的 `` `bogus_key` `` ⇒ 红 |
| 6 | **可空键的 null 形态 ⇄ 现取序列化策略**（见下「键恒在」口径） | 把 `application.yml` 的 inclusion 改成 `always`（或给该类加 `@JsonInclude(ALWAYS)`）⇒ 登记的 `absent` 不再成立 ⇒ 红 |
| 6b | **Map 载体读面的键 ⇄ 代码 `put` 锚**（部位读面 `part_short_code` / `scan_url`，issue #4946） | 锚消失（键被删 / 改名 / 搬走）或锚不再含 `.put(`（载体换成 DTO）⇒ 红 |
| 7 | **台账只许缩短 + 反空跑（fail-closed）** | 射程/台账/冻结键集合为空 ⇒ 红；豁免或行内白名单词汇超出**冻结上界**（判据文件里的字面量）⇒ 红；台账里出现写死的整数计数 ⇒ 红（现取，不写死条数） |

## 🔴「键恒在」的口径（判据 6，**与 issue 原文的理想形态不一致，如实登记**）

issue 与 B3 的契约措辞是「**键恒在**：无码 ⇒ 两键都在且为 `null`」。**现取的生产形态不是这样**：
全局 `default-property-inclusion: non_null` + 类/字段均无 `@JsonInclude(ALWAYS)`
⇒ 值为 `null` 时该键**根本不出现在 JSON 里**（`absent`，不是 `key: null`）。
B3 的实例判据用的是 `new ObjectMapper()`（inclusion 默认 `ALWAYS`），**与线上 ObjectMapper 不同源**
⇒ 那条断言在单测里成立、在线上不成立（「看起来在判 ≠ 真的在判」，`docs/testing/test-engineering-standards.md` §9）。
危害面现取为**零**：消费方用 `?? null` + TypeScript `short_code?: string | null`，缺席与 `null` 行为相同。

🔴 **2026-10-14 订正（主会话裁定，本包执行）**：`docs/wiki/CONTRACT-LEDGER.md` 两处「**键恒在**」措辞
（加工单读面 issue #6867 的两键 + 部位读面 issue #4946 的三键）已改为同源表述
「**无码 ⇒ 键缺席或为 `null`**（全局 non_null 下实际缺席；两者语义等价，消费方一律按「没有码」处理）」；
B3 的实例判据已改用**镜像 `application.yml` 的 mapper**（`productionMapper`）断言真实形态 + 正向对照。
裁定依据：`non_null` 是全局策略、仓内 `@JsonInclude` 压倒性是 NON_NULL、消费方 `?? null` ⇒ 产品影响为零
（为「让措辞成真」去加 `@JsonInclude(ALWAYS)` 例外属过度建设）。

⇒ 本判据**不装作它能判「键一定在」**（当前配置下那是不可达形态），它判的是**可推广的那一半**：
「每个可空冻结键的 null 形态，必须与**现取的**序列化策略一致，且逐键显式登记 + 写理由」——
`application.yml` 的 inclusion、类级与字段级 `@JsonInclude` 任一变化 ⇒ 当场红，逼登记面跟着改。
**未登记即红**：射程内每个「冻结 + 引用类型」的键都必须在台账 `nullable_key_forms` 里有一条（双向相等）。
**边界**：真·raw JSON 键集对比（`键在不在`）在 Java 侧，由 B3 的实例判据承担；本判据是静态面，不重跑它。

## 红证（实跑；逐条见 `TestDiscriminatingPower`，另有一轮**真文件**注入读数见 PR body）

| 注入 | 期望 |
|---|---|
| ① `@JsonProperty("short_code")` ⇒ 摘掉 / 改成 `@JsonProperty("shortCode")` | 判据 2 + 3 红，具名 `类::字段 ⇒ 实际键名` |
| ② 台账 `classes[...]["keys"]` 多一条不存在的键 | 判据 3 红（台账有、代码无） |
| ②' 真账本文本锚行注入 `` `bogus_key` `` | 判据 5 红 |
| ③ 台账 `classes[...]["keys"]` 删一条已存在的键 | 判据 3 红（代码有、台账无） |
| ③' 真账本文本锚行删掉 `` `short_code` `` | 判据 4 红 |
| ④ 射程里新加一个**未登记**的类（带 `@JsonProperty`） | 判据 1 红，具名该类 |
| ⑤ `application.yml` 的 inclusion 改成 `always` | 判据 6 红 |
| ⑥ 部位读面的 `position.put("part_short_code", …)` 锚被删 / 锚不再含 `.put(` | 判据 6b 红 |
| 对照：只往源码里加注释 / 只往台账改动**不涉及**键的字段 | **一条都不红**（判别力对照） |

## 未固化 / 边界（照实登记）

① **「作者想写 snake_case 但注解与登记都忘了」判不了**：那类字段的键就是 camelCase，且不在射程内（无显式注解）
—— 射程表达式本身决定了这个残差（要覆盖它就得把整个 DTO 包收进来 ⇒ 96/109 个文件的既有 camelCase 契约变成假红）。
② **账本侧只做「被点名的冻结键」的单向包含 + 锚行 token 的 snake 面**：账本是 113KB 散文、由 B2 独占写面
⇒ 不做全文 token 提取（锚行 13 个反引号 token 里只有 4 个 snake 形态、其中 2 个不是键名 ⇒ 全文提取必然假红）。
③ **判不了**「业务字段该不该下发」（那是权限面，另有既有判据），也判不了消费端是否真的读了某个键。
④ 本判据**不跑** Java 测试、不替代 B3 的 `ProcessingOrderReadFaceShortCodeTest`（行为面仍是它的活）。
⑤ **Map 载体面的键清单是「声明式」的**（`map_view_faces`）：靠代码锚证明键还在，但**不做**「该面所有 `put` 键都登记了吗」的反向穷举 —— 同一个 service 文件里有几十个 `put`（分属多个面），按文件穷举必然假红；缺的方向由「锚消失即红」兜。

判据面复算：
`python3 -m pytest tests/unit_ci_workflows/test_read_face_json_key_guard.py -q -s`
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _source_parsing import java_code, java_literals  # noqa: E402  （判据面唯一共享的 Java 剥注释实现）

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIT_CI_DIR = Path(__file__).resolve().parent
MAIN_JAVA = REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "java"
LEDGER_PATH = UNIT_CI_DIR / "read_face_json_key_ledger.json"
CONTRACT_LEDGER_PATH = REPO_ROOT / "docs" / "wiki" / "CONTRACT-LEDGER.md"
APP_YML_PATH = REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "resources" / "application.yml"

#: 冻结键的风格（issue #6890 判据 2；同一把尺子也是 `short_code` / `scan_url` 的形态）
SNAKE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
#: 字段声明（含其前面的注解块）。**没有引号定界的捕获组**（不触发判据面「原文口径」元守卫）。
FIELD_RE = re.compile(r"((?:@\w+(?:\([^)]*\))?\s*)*)private\s+(?!static)([\w.<>\[\],\s]+?)\s+(\w+)\s*[;=]")
#: 类 / 记录声明 + 花括号（用于把字段归到最内层类）
SCOPE_RE = re.compile(r"[{}]|\b(?:class|record)\s+(\w+)")
PACKAGE_RE = re.compile(r"^package\s+([\w.]+)\s*;", re.M)
BACKTICK_RE = re.compile(r"`([^`]+)`")
INCLUDE_RE = re.compile(r"@JsonInclude\s*\(([^)]*)\)")
#: `@JsonProperty` 字面量的前缀（靠**词法**取值，不靠按引号扫原文的正则）
JP_TOKENS = ("@JsonProperty(", "@JsonProperty(value=")

PRIMITIVES = frozenset({"int", "long", "boolean", "double", "char", "short", "byte", "float"})
KINDS = frozenset({"read-face-response", "read-face-nested", "write-face-request"})
NON_NULL_INCLUSIONS = frozenset({"non_null", "non_empty"})
ALWAYS_INCLUSIONS = frozenset({"always", "always_include"})

#: 台账里「行内白名单词汇」的**冻结上界**（只许缩短；新增一条必须先改这一行 = diff 里看得见）
LEDGER_VOCAB_CEILING = frozenset({"null", "base"})
#: 豁免台账的**冻结上界**（现取：无豁免）。要新增一条豁免必须先改这一行并写理由。
EXEMPTION_CEILING: frozenset[str] = frozenset()


# ══════════════════════════════════════════════════════════════════════════════
# 一、现取：读源码（Java 侧走共享剥注释实现）
# ══════════════════════════════════════════════════════════════════════════════


def _annotation_include(ann_blob: str) -> str | None:
    """注解块里的 `@JsonInclude(...)` 取值（小写归一）；没有 ⇒ None。"""
    m = INCLUDE_RE.search(ann_blob)
    if m is None:
        return None
    token = m.group(1).strip().rsplit(".", 1)[-1].strip().lower()
    return token or None


def parse_classes(code: str) -> dict[str, dict]:
    """把一段 Java 源码**现取**成 `{FQN: {"include": …, "fields": {字段: {...}}}}`。

    字段归属 = **最内层**包围它的类（嵌套类按 `Outer.Inner` 记）。找不到归属的字段**不入账**
    （不静默塞进外层类 —— 那会让清单判据把嵌套类的键记到外层去）。
    """
    package = PACKAGE_RE.search(code)
    package = package.group(1) if package else ""
    literals = java_literals(code)

    scopes: list[tuple[int, int, str, tuple[str, ...]]] = []
    stack: list[list] = []
    depth = 0
    pending: str | None = None
    for m in SCOPE_RE.finditer(code):
        if m.group(1):
            pending = m.group(1)
            continue
        if m.group(0) == "{":
            depth += 1
            stack.append([pending, depth, m.start()])
            pending = None
        else:
            if stack and stack[-1][1] == depth:
                name, _, start = stack.pop()
                scopes.append((start, m.end(), name, tuple(n for n, _, _ in stack)))
            depth -= 1

    out: dict[str, dict] = {}
    for start, end, name, parents in scopes:
        if name is None:
            continue  # 方法 / 初始化块的花括号不是类：它的 parents FQN 与所在类同名，记它会顶掉类级注解
        fqn = ".".join([p for p in (package, *parents, name) if p])
        # 类级注解 = 类关键字之前、上一个 `}` 或 `;` 之后的那一段
        head = code[:start]
        boundary = max(head.rfind("}"), head.rfind(";"))
        out.setdefault(fqn, {"include": _annotation_include(head[boundary + 1:]), "fields": {}})

    for m in FIELD_RE.finditer(code):
        blob, ftype, fname = m.group(1), m.group(2).strip(), m.group(3)
        if "@JsonIgnore" in blob:
            continue  # 显式排除的字段不是「对消费端可见的键」
        key = None
        for pos, value in literals:
            if m.start(1) <= pos < m.end(1) and code[:pos].rstrip().endswith(JP_TOKENS):
                key = value
        enclosing = [(end - start, fqn) for start, end, name, parents in scopes if name is not None
                     for fqn in [".".join([p for p in (package, *parents, name) if p])]
                     if start < m.start() < end]
        if not enclosing:
            continue
        owner = min(enclosing)[1]
        out[owner]["fields"][fname] = {
            "key": key if key is not None else fname,
            "type": ftype,
            "annotated": key is not None,
            "include": _annotation_include(blob),
        }
    return out


def read_sources(root: Path = MAIN_JAVA) -> dict[str, str]:
    """`{仓库相对路径: 源码}` —— **现取**（含子目录），不写死文件清单。"""
    return {
        p.relative_to(REPO_ROOT).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted(root.rglob("*.java"))
    }


def scoped_classes(sources: dict[str, str]) -> dict[str, dict[str, dict]]:
    """射程 = 承载至少一个显式 `@JsonProperty` 的类（含嵌套类）。"""
    scope: dict[str, dict[str, dict]] = {}
    for rel, raw in sources.items():
        if "@JsonProperty" not in raw:
            continue
        for fqn, info in parse_classes(java_code(raw)).items():
            if any(f["annotated"] for f in info["fields"].values()):
                scope[fqn] = {"include": info["include"], "fields": info["fields"], "source": rel}
    return scope


def global_inclusion(yml_text: str) -> str:
    """现取全局 `spring.jackson.default-property-inclusion`（缺省 `always`）。"""
    m = re.search(r"^\s*default-property-inclusion:\s*([\w_]+)\s*$", yml_text, re.M)
    return (m.group(1).strip().lower() if m else "always")


def derive_null_form(class_include: str | None, field_include: str | None, global_inc: str) -> str:
    """由（全局策略 → 类级 → 字段级）现取「值为 null 时键在不在」。"""
    for inc in (field_include, class_include):
        if inc in ALWAYS_INCLUSIONS:
            return "present"
        if inc in NON_NULL_INCLUSIONS:
            return "absent"
    return "absent" if global_inc in NON_NULL_INCLUSIONS else "present"


def _live() -> tuple[dict[str, str], dict[str, dict[str, dict]], dict, str, str]:
    sources = read_sources()
    scope = scoped_classes(sources)
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    return (sources, scope, ledger,
            CONTRACT_LEDGER_PATH.read_text(encoding="utf-8"),
            APP_YML_PATH.read_text(encoding="utf-8"))


# ══════════════════════════════════════════════════════════════════════════════
# 二、判据（纯函数：入参即事实 ⇒ 可在内存里做注入式红证）
# ══════════════════════════════════════════════════════════════════════════════


def scope_violations(scope: dict[str, dict], ledger: dict) -> list[str]:
    """判据 1：射程 ⇄ 台账双向相等（未登记即红；陈旧条目即红）。"""
    out: list[str] = []
    if not scope:
        out.append("射程为空 —— 现取一个带显式 `@JsonProperty` 的类都没有：判据失去被测对象（fail-closed）")
    registered = set(ledger.get("classes", {}))
    for fqn in sorted(set(scope) - registered):
        out.append(f"射程里新出现的 DTO 未登记：{fqn}（拿冻结键的类必须进 "
                   f"{LEDGER_PATH.relative_to(REPO_ROOT).as_posix()} 的 classes；防止新加一个 DTO 就绕过守卫）")
    for fqn in sorted(registered - set(scope)):
        out.append(f"台账登记了射程外的 DTO：{fqn} —— 它已不再承载显式 `@JsonProperty`（陈旧条目，须销账）")
    return out


def style_violations(scope: dict[str, dict]) -> list[str]:
    """判据 2：每个显式 `@JsonProperty` 的值必须 snake_case，红并具名 `类::字段 ⇒ 实际键名`。"""
    out: list[str] = []
    for fqn, info in sorted(scope.items()):
        for field, meta in sorted(info["fields"].items()):
            if meta["annotated"] and not SNAKE_RE.match(meta["key"]):
                out.append(f"{fqn}::{field} ⇒ 实际键名 {meta['key']!r} 不是 snake_case"
                           f"（`^[a-z][a-z0-9_]*$`）—— 不标注 `@JsonProperty` 就静默下发 camelCase，"
                           f"消费方按冻结键取值会静默退化")
    return out


def inventory_violations(scope: dict[str, dict], ledger: dict) -> list[str]:
    """判据 3：台账 `<字段> -> <键>` 完整清单 ⇄ 代码实际键，双向相等。"""
    out: list[str] = []
    for fqn, reg in sorted(ledger.get("classes", {}).items()):
        info = scope.get(fqn)
        if info is None:
            continue  # 由判据 1 具名
        code_snapshot = {f: m["key"] for f, m in info["fields"].items()}
        reg_snapshot = reg.get("keys", {})
        for field in sorted(set(reg_snapshot) - set(code_snapshot)):
            out.append(f"{fqn}::{field} 台账有、代码无（该字段已删/改名 ⇒ 台账须同步销账）")
        for field in sorted(set(code_snapshot) - set(reg_snapshot)):
            out.append(f"{fqn}::{field} ⇒ {code_snapshot[field]!r} 代码有、台账无（新增键必须登记）")
        for field in sorted(set(code_snapshot) & set(reg_snapshot)):
            if code_snapshot[field] != reg_snapshot[field]:
                out.append(f"{fqn}::{field} ⇒ 实际键名 {code_snapshot[field]!r} ≠ 登记键名 "
                           f"{reg_snapshot[field]!r}（摘掉 / 改错 `@JsonProperty` 即此形态："
                           f"全局无 SNAKE_CASE 策略 ⇒ 键名静默变 camelCase）")
        frozen = {v["key"] for f, v in info["fields"].items() if v["annotated"]}
        declared_frozen = set(reg.get("frozen_keys", []))
        for key in sorted(frozen - declared_frozen):
            out.append(f"{fqn}:: 代码里 {key!r} 是显式冻结键，但台账 frozen_keys 未登记")
        for key in sorted(declared_frozen - frozen):
            out.append(f"{fqn}:: 台账 frozen_keys 里的 {key!r} 在代码里已不是显式冻结键（陈旧条目）")
    return out


def contract_ledger_violations(scope: dict[str, dict], ledger: dict, ledger_text: str) -> list[str]:
    """判据 4 / 5：`docs/wiki/CONTRACT-LEDGER.md`（**只读**）⇄ 代码。"""
    out: list[str] = []
    with_anchor = [f for f, r in ledger.get("classes", {}).items() if r.get("contract_ledger_anchor")]
    if not with_anchor:
        out.append("账本侧判定失效：台账里没有任何类声明 `contract_ledger_anchor`（fail-closed）")
    rows = [line for line in ledger_text.splitlines() if line.startswith("|")]
    vocabulary = ledger.get("contract_ledger_row_vocabulary", {})
    for fqn, reg in sorted(ledger.get("classes", {}).items()):
        info = scope.get(fqn)
        if info is None:
            continue
        frozen = {v["key"] for f, v in info["fields"].items() if v["annotated"]}
        named = list(reg.get("contract_ledger_keys", []))
        for key in named:
            if key not in frozen:
                out.append(f"{fqn}:: 台账 `contract_ledger_keys` 里的 {key!r} 不是该类的冻结键（登记面自相矛盾）")
        anchor = reg.get("contract_ledger_anchor")
        if anchor:
            if not named:
                out.append(f"{fqn}:: 声明了账本锚却一个 `contract_ledger_keys` 都没点名（fail-closed）")
            anchor_rows = [r for r in rows if anchor in r]
            if not anchor_rows:
                out.append(f"{fqn}:: 账本锚行消失（找不到含 {anchor!r} 的表格行）—— 账本侧判定失去依据")
                continue
            region = "\n".join(anchor_rows)
            for key in named:
                if f"`{key}`" not in region:
                    out.append(f"{fqn}:: {key!r} 是代码里的冻结键，但账本锚行 {anchor!r} 未登记它"
                               f"（代码有、账本无）")
            for token in sorted(set(BACKTICK_RE.findall(region))):
                if not SNAKE_RE.match(token) or token in frozen:
                    continue
                code_keys = {m["key"] for m in info["fields"].values()}
                if token in code_keys or token in vocabulary:
                    continue
                out.append(f"账本锚行 {anchor!r} 提到 `{token}`，但 {fqn} 的代码里没有这个键"
                           f"（账本有、代码无）—— 要么登记进代码，要么作为非键词汇显式登记（带理由）")
        else:
            if not reg.get("contract_ledger_why"):
                out.append(f"{fqn}:: 没有账本锚，也没写 `contract_ledger_why`（要么给锚，要么具名登记为什么不可达）")
            for key in named:
                if f"`{key}`" not in ledger_text:
                    out.append(f"{fqn}:: {key!r} 是代码里的冻结键，但整个账本都没登记它（代码有、账本无）")
    return out


def _carrier_include(ledger: dict, sources: dict[str, str], face: str) -> str | None:
    """Map 面外层载体类的类级 `@JsonInclude`（台账 `carrier` = `<FQN>::<仓库相对路径>`）。"""
    carrier = ledger.get("map_view_faces", {}).get(face, {}).get("carrier")
    if not carrier:
        return None
    fqn, _, rel = str(carrier).partition("::")
    raw = sources.get(rel)
    if raw is None:
        return None
    return parse_classes(java_code(raw)).get(fqn, {}).get("include")


def map_view_violations(ledger: dict, sources: dict[str, str]) -> list[str]:
    """判据 6b：**Map 载体**读面的键 ⇄ 代码里的 `put` 锚（键-恒在形态对 Map 载体同样成立的前提）。"""
    out: list[str] = []
    faces = ledger.get("map_view_faces", {})
    if not faces:
        out.append("台账 map_view_faces 为空 ⇒ Map 载体面空跑（fail-closed）")
    for face, reg in sorted(faces.items()):
        rel = str(reg.get("source", ""))
        raw = sources.get(rel)
        if raw is None:
            out.append(f"{face}:: 载体源文件不在现取集合里：{rel!r}（路径漂移 ⇒ 该面判定失去依据）")
            continue
        code = java_code(raw)
        keys = reg.get("keys", {})
        if not keys:
            out.append(f"{face}:: keys 为空 ⇒ 该面空跑（fail-closed）")
        if not reg.get("carrier"):
            out.append(f"{face}:: 未声明外层载体 `carrier`（null 形态推导失去依据）")
        elif _carrier_include(ledger, sources, face) is None:
            out.append(f"{face}:: 载体 {reg.get('carrier')!r} 解析不到类级 `@JsonInclude`（路径 / 类名漂移）")
        for key, anchor in sorted(keys.items()):
            if anchor not in code:
                out.append(f"{face}::{key} 的代码锚消失（须逐字出现）：{anchor!r}"
                           f" ⇒ 键被删 / 改名 / 搬走，登记面须同步")
            elif ".put(" not in anchor:
                out.append(f"{face}::{key} 的锚不再证明它是 **Map 条目**（锚里没有 `.put(`）：{anchor!r}"
                           f" ⇒ 载体形态变了，null 形态推导失效，须重新登记")
    return out


def null_form_violations(scope: dict[str, dict], ledger: dict, yml_text: str,
                         sources: dict[str, str]) -> list[str]:
    """判据 6：可空冻结键（DTO 字段 + Map 条目）的 null 形态 ⇄ 现取序列化策略，逐键登记 + 写理由。"""
    out: list[str] = []
    ginc = global_inclusion(yml_text)
    declared = ledger.get("nullable_key_forms", {})

    dto_required: dict[str, tuple[dict, dict]] = {}
    for fqn, info in sorted(scope.items()):
        for _field, meta in sorted(info["fields"].items()):
            if meta["annotated"] and meta["type"] not in PRIMITIVES:
                dto_required[f"{fqn}::{meta['key']}"] = (info, meta)

    map_required: dict[str, str] = {}
    for face, reg in sorted(ledger.get("map_view_faces", {}).items()):
        if reg.get("carrier") and _carrier_include(ledger, sources, face) is None:
            continue  # 载体解析失败已由判据 6b 具名
        for key in reg.get("keys", {}):
            map_required[f"{reg.get('source', '')}::{key}"] = face

    required = set(dto_required) | set(map_required)
    if not required:
        out.append("射程里一个可空冻结键都没有 ⇒ 本判据空跑（fail-closed）")

    for key_id, (info, meta) in sorted(dto_required.items()):
        form = derive_null_form(info["include"], meta["include"], ginc)
        if key_id not in declared:
            out.append(f"{key_id} 未登记 null 形态（可空冻结键必须逐键登记 form + why；现取形态 = {form!r}）")

    for key_id, entry in sorted(declared.items()):
        if key_id not in required:
            out.append(f"{key_id} 是陈旧登记（代码里已无此可空冻结键 / 已变成基本类型 / 该 Map 键已不在登记面）")
            continue
        if key_id in dto_required:
            info, meta = dto_required[key_id]
            form = derive_null_form(info["include"], meta["include"], ginc)
            where = (f"全局 default-property-inclusion={ginc!r}、类级 @JsonInclude={info['include']!r}、"
                     f"字段级 @JsonInclude={meta['include']!r}")
            expect_kind = "dto-key"
        else:
            face = map_required[key_id]
            carrier_inc = _carrier_include(ledger, sources, face)
            form = derive_null_form(carrier_inc, None, ginc)
            where = f"全局 default-property-inclusion={ginc!r}、Map 载体类级 @JsonInclude={carrier_inc!r}"
            expect_kind = "map-entry"
        declared_form = entry.get("form")
        if entry.get("kind") != expect_kind:
            out.append(f"{key_id} 的 kind={entry.get('kind')!r} 与实际载体不符（应为 {expect_kind!r}）")
        if declared_form not in ("present", "absent"):
            out.append(f"{key_id} 的 form={declared_form!r} 非法（只认 'present' / 'absent'）")
        elif declared_form != form:
            out.append(f"{key_id} 登记的 null 形态 = {declared_form!r}，而现取序列化策略推出的是 {form!r}"
                       f"（{where}）⇒ 契约措辞与实现不符，须重登记")
        if not str(entry.get("why", "")).strip():
            out.append(f"{key_id} 的 null 形态登记缺 `why`（每条登记必须写理由）")
    return out


def ledger_shape_violations(ledger: dict) -> list[str]:
    """判据 7：反空跑 + 台账只许缩短 + 不写死条数（现取）。"""
    out: list[str] = []
    classes = ledger.get("classes", {})
    if not classes:
        out.append("台账 classes 为空 ⇒ 判据空跑（fail-closed）")
    for fqn, reg in sorted(classes.items()):
        if not reg.get("frozen_keys"):
            out.append(f"{fqn}:: frozen_keys 为空 ⇒ 该类的风格判据空跑（fail-closed）")
        if not reg.get("keys"):
            out.append(f"{fqn}:: keys 为空 ⇒ 该类的清单判据空跑（fail-closed）")
        if reg.get("kind") not in KINDS:
            out.append(f"{fqn}:: kind={reg.get('kind')!r} 不在 {sorted(KINDS)}")
        source = REPO_ROOT / str(reg.get("source", ""))
        if not source.is_file():
            out.append(f"{fqn}:: source 指向的文件不存在：{reg.get('source')!r}")
        if not set(reg.get("frozen_keys", [])) <= set(reg.get("keys", {}).values()):
            out.append(f"{fqn}:: frozen_keys 不是 keys 取值的子集（模式：注解值与字段名清单不一致）")

    vocabulary = ledger.get("contract_ledger_row_vocabulary", {})
    extra = set(vocabulary) - LEDGER_VOCAB_CEILING
    if extra:
        out.append(f"行内白名单词汇超出冻结上界 {sorted(LEDGER_VOCAB_CEILING)}：{sorted(extra)}"
                   f"（只许缩短；新增一条必须在本判据文件里显式提高上界并写理由）")
    for token, why in sorted(vocabulary.items()):
        if not str(why).strip():
            out.append(f"行内白名单词汇 {token!r} 缺理由")

    exemptions = ledger.get("exemptions", [])
    if not isinstance(exemptions, list):
        out.append("exemptions 必须是列表")
        exemptions = []
    for entry in exemptions:
        if not isinstance(entry, dict) or not str(entry.get("path", "")).strip() or not str(entry.get("why", "")).strip():
            out.append(f"豁免条目必须含 `path` + `why`：{entry!r}")
    granted = {e.get("path") for e in exemptions if isinstance(e, dict)}
    if granted - EXEMPTION_CEILING:
        out.append(f"豁免超出冻结上界 {sorted(EXEMPTION_CEILING)}：{sorted(granted - EXEMPTION_CEILING)}"
                   f"（台账只许缩短）")

    def _ints(node, path="$"):
        if isinstance(node, bool):
            return
        if isinstance(node, int):
            yield path
        elif isinstance(node, dict):
            for k, v in node.items():
                yield from _ints(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                yield from _ints(v, f"{path}[{i}]")

    hardcoded = list(_ints(ledger))
    if hardcoded:
        out.append(f"台账里出现写死的整数（条数必须现取，不写死）：{hardcoded}")
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 三、判据（绿：真语料上全绿；现取读数用 `-s` 打印）
# ══════════════════════════════════════════════════════════════════════════════


def test_scope_is_nonempty_and_equals_registry_both_ways() -> None:
    """判据 1：射程现取、非空，且与台账 classes **双向相等**（未登记即红）。"""
    _, scope, ledger, _, _ = _live()
    print(f"\n[现取] 射程类 = {len(scope)} 个；冻结键 = "
          f"{sum(1 for i in scope.values() for m in i['fields'].values() if m['annotated'])} 个")
    assert scope_violations(scope, ledger) == []


def test_frozen_key_names_are_snake_case() -> None:
    """判据 2：显式 `@JsonProperty` 的值一律 snake_case（camelCase ⇒ 红并具名）。"""
    _, scope, _, _, _ = _live()
    assert style_violations(scope) == []


def test_key_inventory_matches_code_both_ways() -> None:
    """判据 3：台账键清单 ⇄ 代码实际键（含「摘掉注解 ⇒ 实际键名漂移」）。"""
    _, scope, ledger, _, _ = _live()
    assert inventory_violations(scope, ledger) == []


def test_contract_ledger_carries_registered_frozen_keys() -> None:
    """判据 4 / 5：`docs/wiki/CONTRACT-LEDGER.md`（只读）⇄ 代码，两个方向。"""
    _, scope, ledger, ledger_text, _ = _live()
    rows = [line for line in ledger_text.splitlines() if line.startswith("|")]
    print(f"[现取] 账本表格行 = {len(rows)} 行；被点名的冻结键 = "
          f"{sum(len(r.get('contract_ledger_keys', [])) for r in ledger['classes'].values())} 个")
    assert contract_ledger_violations(scope, ledger, ledger_text) == []


def test_nullable_frozen_keys_declare_null_form_matching_live_policy() -> None:
    """判据 6：可空冻结键的 null 形态 ⇄ 现取序列化策略（未登记即红）。"""
    sources, scope, ledger, _, yml_text = _live()
    print(f"[现取] 全局 default-property-inclusion = {global_inclusion(yml_text)!r}；"
          f"登记的可空冻结键 = {len(ledger['nullable_key_forms'])} 个")
    assert null_form_violations(scope, ledger, yml_text, sources) == []


def test_map_view_faces_are_live() -> None:
    """判据 6b：Map 载体读面的键 ⇄ 代码 `put` 锚（部位读面 issue #4946）。"""
    sources, _, ledger, _, _ = _live()
    faces = ledger["map_view_faces"]
    print(f"\n[现取] Map 载体面 = {len(faces)} 个；登记键 = "
          f"{sum(len(f['keys']) for f in faces.values())} 个")
    assert map_view_violations(ledger, sources) == []


def test_ledger_is_fail_closed_and_only_shrinks() -> None:
    """判据 7：反空跑 + 只许缩短 + 不写死条数。"""
    _, _, ledger, _, _ = _live()
    assert ledger_shape_violations(ledger) == []


def test_premises_are_live() -> None:
    """前提自证：本判据赖以成立的两条现取事实仍在（否则整支判据的射程口径失效）。"""
    sources, scope, _, _, yml_text = _live()
    assert len(sources) > 0, "现取不到任何 Java 源文件 —— 射程失去依据（路径漂移）"
    assert len(scope) > 0, "射程为空 —— 见判据 1"
    assert global_inclusion(yml_text) in NON_NULL_INCLUSIONS, (
        "全局 default-property-inclusion 不再是 non_null ⇒ 判据 6 的现取形态变了，须重取读数并重登记"
    )
    strategy_hits = [rel for rel, raw in sources.items() if "PropertyNamingStrateg" in java_code(raw)]
    yml_hits = re.findall(r"property-naming-strategy", yml_text)
    mentions = sum(1 for raw in sources.values() if "SNAKE_CASE" in raw)
    print(f"\n[现取] 代码里的命名策略引用 = {strategy_hits}；yml 的 property-naming-strategy = {len(yml_hits)} 处；"
          f"`SNAKE_CASE` 字样只出现在 {mentions} 个文件的**注释/文档**里"
          f"（那是「没有策略」这条前提的说明，不是配置）")
    assert strategy_hits == [] and not yml_hits, (
        "出现了显式命名策略配置 ⇒ 「不标注就静默 camelCase」这条前提变了，本判据的射程口径须重写"
    )


# ══════════════════════════════════════════════════════════════════════════════
# 四、判别力自证（每条坏形态在**内存里**各自判红；对照：只改注释 ⇒ 不红）
# ══════════════════════════════════════════════════════════════════════════════

DTO_REL = "backend/admin-api/src/main/java/com/migao/admin/dto/ProcessingOrderResponse.java"
DTO_FQN = "com.migao.admin.dto.ProcessingOrderResponse"
ANCHOR = "`GET /api/admin/processing-orders"
SYNTHETIC_REL = "backend/admin-api/src/main/java/com/migao/admin/dto/Synthetic3721View.java"
SYNTHETIC_SRC = (
    "package com.migao.admin.dto;\n\n"
    "import com.fasterxml.jackson.annotation.JsonProperty;\n\n"
    "public class Synthetic3721View {\n"
    "    @JsonProperty(\"some_frozen_key\")\n"
    "    private String someFrozenKey;\n"
    "}\n"
)


def _mutated_source(**replacements: tuple[str, str]) -> dict[str, str]:
    sources = read_sources()
    for rel, (old, new) in replacements.items():
        assert old in sources[rel], f"注入点未命中（先自证坐标再注入）：{rel} :: {old!r}"
        sources[rel] = sources[rel].replace(old, new, 1)
    return sources


def _inject(needle: str, fake: str, fake_key: str, value: object) -> dict:
    """在内存里改台账的一个键（不写盘）。"""
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    if fake == "add":
        ledger["classes"][DTO_FQN]["keys"][fake_key] = value
    elif fake == "del":
        del ledger["classes"][DTO_FQN]["keys"][fake_key]
    else:  # pragma: no cover - 参数错误
        raise AssertionError(fake)
    return ledger


def test_red_proof_1a_annotation_removed_is_red_and_named() -> None:
    """红证 ①-a：摘掉 `@JsonProperty("short_code")` ⇒ 实际键名漂移 ⇒ 红并具名。"""
    sources = _mutated_source(**{DTO_REL: ('    @JsonProperty("short_code")\n', "")})
    scope = scoped_classes(sources)
    violations = inventory_violations(scope, json.loads(LEDGER_PATH.read_text(encoding="utf-8")))
    assert any(f"{DTO_FQN}::shortCode ⇒ 实际键名 'shortCode' ≠ 登记键名 'short_code'" in v for v in violations), violations


def test_red_proof_1b_annotation_camelcased_is_red_and_named() -> None:
    """红证 ①-b：把注解值改成 camelCase ⇒ 风格判据红并具名 `类::字段 ⇒ 实际键名`。"""
    sources = _mutated_source(**{DTO_REL: ('@JsonProperty("short_code")', '@JsonProperty("shortCode")')})
    violations = style_violations(scoped_classes(sources))
    assert any(f"{DTO_FQN}::shortCode ⇒ 实际键名 'shortCode' 不是 snake_case" in v for v in violations), violations


def test_red_proof_2_unique_ledger_key_is_red() -> None:
    """红证 ②：台账里**多**一条不存在的键 ⇒ 红。"""
    ledger = _inject("keys", "add", "ghost_key_3721", "ghostKey3721")
    violations = inventory_violations(scoped_classes(read_sources()), ledger)
    assert any("ghost_key_3721" in v and "台账有、代码无" in v for v in violations), violations


def test_red_proof_2prime_contract_ledger_extra_key_is_red() -> None:
    """红证 ②'：真账本文本锚行注入一个不存在的键 ⇒ 红（账本有、代码无）。"""
    _, scope, ledger, ledger_text, _ = _live()
    row = next(line for line in ledger_text.splitlines() if line.startswith("|") and ANCHOR in line)
    mutated = ledger_text.replace(row, row + " 注入：`bogus_key_3721`", 1)
    assert mutated != ledger_text, "注入未生效（先自证坐标）"
    violations = contract_ledger_violations(scope, ledger, mutated)
    assert any("bogus_key_3721" in v and "账本有、代码无" in v for v in violations), violations


def test_red_proof_3_missing_ledger_key_is_red() -> None:
    """红证 ③：台账里**删**一条已存在的键 ⇒ 红。"""
    ledger = _inject("keys", "del", "shortCode", None)
    violations = inventory_violations(scoped_classes(read_sources()), ledger)
    assert any(f"{DTO_FQN}::shortCode ⇒ 'short_code' 代码有、台账无" in v for v in violations), violations


def test_red_proof_3prime_contract_ledger_dropped_key_is_red() -> None:
    """红证 ③'：真账本文本锚行删掉 `` `short_code` `` ⇒ 红（代码有、账本无）。"""
    row = next(line for line in CONTRACT_LEDGER_PATH.read_text(encoding="utf-8").splitlines()
               if line.startswith("|") and ANCHOR in line)
    mutated_row = row.replace("`short_code`", "`the_short_code`")
    assert mutated_row != row, "注入未生效（先自证坐标）"
    _, scope, ledger, ledger_text, _ = _live()
    violations = contract_ledger_violations(scope, ledger, ledger_text.replace(row, mutated_row, 1))
    assert any(f"{DTO_FQN}:: 'short_code' 是代码里的冻结键，但账本锚行" in v for v in violations), violations


def test_red_proof_4_new_unregistered_dto_is_red() -> None:
    """红证 ④：射程里新加一个**未登记**的 DTO ⇒ 红并具名。"""
    sources = dict(read_sources())
    sources[SYNTHETIC_REL] = SYNTHETIC_SRC
    violations = scope_violations(scoped_classes(sources), json.loads(LEDGER_PATH.read_text(encoding="utf-8")))
    assert any("com.migao.admin.dto.Synthetic3721View" in v for v in violations), violations


def test_red_proof_5_inclusion_flip_is_red() -> None:
    """红证 ⑤：全局 inclusion 改成 `always` ⇒ 登记的 `absent` 不再成立 ⇒ 红。"""
    sources, scope, ledger, _, yml_text = _live()
    flipped = yml_text.replace("default-property-inclusion: non_null", "default-property-inclusion: always", 1)
    assert flipped != yml_text, "注入未生效（先自证坐标）"
    violations = null_form_violations(scope, ledger, flipped, sources)
    assert any("null 形态 = 'absent'，而现取序列化策略推出的是 'present'" in v for v in violations), violations


def test_red_proof_6_map_anchor_removed_or_weakened_is_red() -> None:
    """红证 ⑥：部位读面的 `put` 锚被删 / 锚弱化到不再证明 Map 条目 ⇒ 判据 6b 红。"""
    _, _, ledger, _, _ = _live()
    face = next(iter(ledger["map_view_faces"]))
    rel = ledger["map_view_faces"][face]["source"]
    sources = read_sources()

    removed = dict(sources)
    removed[rel] = "\n".join(line for line in sources[rel].splitlines()
                              if 'position.put("part_short_code"' not in line)
    v1 = map_view_violations(ledger, removed)
    assert any("part_short_code" in v and "代码锚消失" in v for v in v1), v1

    weakened = copy.deepcopy(ledger)
    weakened["map_view_faces"][face]["keys"]["part_short_code"] = "part_short_code"
    v2 = map_view_violations(weakened, sources)
    assert any("Map 条目" in v for v in v2), v2


def test_control_comment_only_change_is_green() -> None:
    """对照：只往源码里加注释 ⇒ **一条都不红**（本判据读的是代码，不是原文口径）。"""
    sources = _mutated_source(**{DTO_REL: (
        "@JsonProperty(\"short_code\")",
        "// 注释里写满 @JsonProperty(\"short_code\") 与 shortCode 也不该被读成声明\n    @JsonProperty(\"short_code\")",
    )})
    scope = scoped_classes(sources)
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    assert style_violations(scope) == []
    assert inventory_violations(scope, ledger) == []
    assert scope_violations(scope, ledger) == []
