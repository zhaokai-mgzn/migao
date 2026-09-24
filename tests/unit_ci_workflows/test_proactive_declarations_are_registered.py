# case_ids: DA-017
"""**声明点的「未登记即红」元守卫**（issue #5389）。

## 病根（一类缺陷，不是一个缺陷）

主动发现的每条规则要**逐条人工登记**两处声明：`judgeable_fields`（行级可判定性 = 「没数据
≠ 没问题」的**行级**版本）与 `enabled_by`（租户级前置 = 「系统有、你没开」）。**漏登记不会有
东西变红** —— 表现是该规则**静默落 `wired`**：

- 行级：某行成本价为空（拿不到值）却照旧按「没命中 = 没问题」读；
- 租户级：租户没开成本核算，规则却报 `wired`（空命中被读成「今天没问题」）。

「**声明了 ≠ 声明全了**」，而「没声明全」在旧口径下**不可见**（issue #5389 的原话：
这是**判断力缺口**，不是能机械兜住的接线缺口）。

## 本元守卫钉的形态（形态学 = `test_guard_parsing_is_comment_aware.py`）

| # | 判据 | 语义 |
|---|---|---|
| 1 | 装配层声明 ≡ 登记册 `row_fields`（**逐字相等**） | 新增一个行字段而没登记 ⇒ 红 |
| 2 | 规则 `requires` 的字段必须**被装配层产出**（或该数组登记在 `unwired_arrays`） | 读一个装配层不产出的字段 = 死绑定 ⇒ 红 |
| 3 | `nullable` 字段被某规则 requires ⇒ 该规则**必须**登记 `judgeable_fields` | **本单的强判据**（漏登记 ⇒ 红） |
| 4 | `judgeable_fields ⊆ requires[1]`、`dimensions ⊆ requires[1]` | 打字错 ⇒ 红（廉价判据那一半） |
| 5 | 装配层下发的事实 ≡ 登记册 `tenant_facts`（逐字相等）；`enabled_by[0]` 必须在册且真下发 | 指向一个装配层根本不发的事实 ⇒ 红 |
| 6 | `tenant_facts[*].gates` 的字段被某规则 requires ⇒ 该规则必须声明 `enabled_by` | 租户级前置漏登记 ⇒ 红 |
| 7 | 条目必须带 `reason` + `issue`；两个豁免台账**今天为空**、只许缩短 | §23 G2 燃尽靶子 |
| 8 | 反空跑读数（规则数 / 行字段数 / 事实数 / nullable 数 / gated 数） | 「扫不到」不许长得像「通过」 |
| 9 | **产出层普查**：谁把字段集放进了快照 `row_fields`（不看源码怎么写） | 现取式腿**看得见**（见「射程」节） |
| 10 | **现取式腿未登记即红** + 台账只许缩短 + 声明与产出同源 | issue #5461 判据 1/3 |
| 11 | 契约判据（`criterion`）必须**真实存在** | 运行期「声明 ≡ 实际产出」不许静默删掉 |
| 12 | 读不出来的产出形态 ⇒ **fail-closed 红** | §23 G5：面外不许永久免检 |

## 射程（issue #5461：「现取式」装配腿不再免检）

**病根（一类缺口，不是一条腿）**：判据 1~8 认的是**源码形态** ——
「`fields.put("<数组>", List.of(…))` 这种**字面量式**装配」。于是**现取式**装配腿
（字段集由 `FieldTruth` 声明在**运行时现取**：`Map.of(array, declaration.declaredFields())`）
**整条落在射程之外** ⇒ 它**不需要登记、不会有东西变红**（§23 G5「判定面之外 = 永久免检」）。
实测形态 = `#5456` / PR `#5458` 的第二快照腿（`CustomerService.profileViewSnapshot`，
见 `backend/admin-api/src/main/java/com/migao/admin/service/CustomerService.java`）——
**当时没出事只是因为恰好还没有主动规则消费那条腿，那是运气不是机制**。

**修法：判产出层，不判源码形态**（普查口径 = 「谁把字段集放进了快照的 `row_fields`」），
契约「**声明的字段集 ≡ 实际产出**」判在**能判的那一层**：

- **字面量式腿** ⇒ 产出集逐字等于 `row_fields` 台账（**现有判据 1~8 一字未动**，判据 2 的「不回退」）；
- **现取式腿** ⇒ ① 产出的数组身份必须现取自 `declaration.table()`；② 产出表达式里**不得**再出现
  字面量（= 第二份清单，两处投影必然分叉）；③ 声明必须已注册、其 `TABLE` 逐字等于台账键里的数组名、
  声明字段集非空；④ **运行期**的「声明 ≡ 实际产出」由台账 `criterion` 点名的**真实存在**的判据判
  —— 真值在 **Java 侧**（`CustomerProfileViewSnapshotTest` 逐字断言行键集 ≡ 声明字段集，§23.7 A3
  「先钉真值在哪一侧」）；本文件判**来源与登记**，不假装能在这里算出运行期产出。
- **读不出来的产出形态** ⇒ **fail-closed 红**（否则「新形态」= 新的永久免检面）。

**输入同刻**（§23 G4）：Python 侧（`proactive.py`）与 Java 侧（`DailyBriefingService.java`）
的源码都在**同一次读数**里取，判据里没有一半快照一半实时。

## 红证（逐条，见文件尾 `TestRedProofs` / `TestFetchedLegRedProofs`；注入先自证 `mutated != src`）

① 删掉规则的 `judgeable_fields=("cost_amount",)` ⇒ 必红（**漏登记**的真形态）；
② 往装配层加一个行字段（未登记）⇒ 必红；③ 往装配层加一个租户事实（未登记）⇒ 必红；
④ 把 `enabled_by` 指向不存在的事实 ⇒ 必红；⑤ 删掉规则的 `enabled_by` ⇒ 必红（gated 字段）；
⑥ 把某字段标成 nullable 而消费规则未登记 ⇒ 必红（判据 3 的判别力）；
⑦ 抹掉一条 reason ⇒ 必红。

**判据 9~12 的红证（#5461，逐条）**：⑧🔴 **造一条现取式腿**（新声明类 + 注册表登记 + 装配层新产出点）
⇒ **未登记即红**（本单的核心红证）；⑨ 同一次注入**连同登记**（fetched_arrays 补一格）⇒ **绿**
（反向对照：⑧ 的红可归因到「没登记」，且登记这个出口**真可行动**）；
⑩ 抹掉那条腿的产出点 ⇒ 台账条目**陈旧 ⇒ 红**（只许缩短）；⑪ 把声明的 `TABLE` 改成别的数组名
⇒ 红（产出的数组身份必须现取自 `declaration.table()`）；⑫ 把 `criterion` 换成不存在的测试名 ⇒ 红
（拦死判据）；⑬ 把产出表达式换成读不出来的形态 ⇒ 红（fail-closed，面外不免检）；
⑭ 同一数组既有字面量腿又有现取式腿 ⇒ 红（两处投影）。

## 真实现场读数（上线当天就抓到一次，不是只有合成注入）

本判据合入后第一次 rebase（把 `#5369`「族 3 包 2 · 具名视图 product_health」并进来）即**当场判红**：
装配层新增了 `skus.sales_count` / `skus.price` / `skus.avg_cost` 与 `product_return_stats.{product_id,
return_tickets, order_lines}` 六个行字段（**未登记**）⇒ 「未登记即红」按设计生效（逐条补登记，
`nullable` 逐一裁定，其中 `skus.avg_cost` 依装配层注释「原样透出 null…不得被 0 冒充成本为零」判**可空**）。
同一次 rebase 还暴露了本判据初版的一处**假红**：`snapshot.put("product_return_stats", …)` 是**行数组**
（在 `SNAPSHOT_ROW_FIELDS` 里），初版把它读成了「租户事实」⇒ 判据口径已修（事实 = 结构键与行数组之外的那些键，
行数组由 `SNAPSHOT_ROW_FIELDS` 现取，不写死清单）。

## 未固化 / 边界（照实登记，别把「登记了」读成「治住了」）

- **`nullable` 是显式裁定，不是从代码派生**：本守卫机械保证「**每新增/改动一个字段都必须显式
  裁定可空性 + 写理由**（未登记即红）」，**不保证裁定正确** —— 除 `orders.cost_amount`（#5348
  已取证）外，其余字段的「不可空」是人工裁定 + 「未逐列核对 DB 约束」如实写法。
  从装配层 builder / DB 约束**派生**可空性 = 下一步（owner = 简报装配层 owner，见 PR body 残余）。
- **`enabled_by` 那一半只做到「登记了才受管」的一半**：判据 6 靠**人**在 `tenant_facts[*].gates`
  里声明「这个事实 gate 了哪些字段」—— 那个映射本身仍是判断（#5389 正文已承认：
  「哪条规则该有租户前置」部分需要人判断）。**未固化项**：没有东西会拦住「新增一条依赖
  租户能力的规则，而没人往 gates 里加字段」。
- 面 = `app/briefing/proactive.py` 的 `RuleSpec` + Java 装配层的一处快照构造。**其它**域
  （其它服务的装配/声明点）不在面内。
- **#5461 的边界（照实登记）**：产出层普查只覆盖 **Java 主源码**（`backend/admin-api/src/main/java/**`）
  里「把字段集放进快照 `row_fields`」的产出点 —— ① 别的语言/RPC 形态的装配腿不在面内；
  ② 「声明字段集」的读数口径 = 声明载体里 `f.put("<字段>", …)` 的字面量键（换别的写法 ⇒ 读到空集
  ⇒ fail-closed 红，不会静默放行）；③ 台账 `criterion` 只判**存在性**（文件在 + 名字在），
  判不了「那个测试到底断没断等价」—— 运行期判据的强度仍由 Java 侧自己保证；
  ④ 本判据**不许**把「产出集 = 声明集」这一条在运行期重算（源级读不出运行期产出）⇒ 有意留给
  台账点名的 Java 判据（真值在那一侧）；**同一个理由也留下一条残余**：产出表达式若是声明的
  **派生**（子集 / 过滤 / `.limit(n)`）而非常量整取，源级判不了 —— 该形态由 criterion 点名的
  运行期判据判（它逐字比较 `row_fields` ≡ 声明字段集、行快照键集 ≡ 声明字段集）；
  **未固化项** = 无人拦着「把来源写错但两处一起改错」。
- 本文件**不改任何门禁的通过条件、不新增豁免**（除两个今天为空的台账，且只许缩短）。

判据 = 本文件；一键复算：
`python3 -m pytest tests/unit_ci_workflows/test_proactive_declarations_are_registered.py -q -s`
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# append（**不是** insert）：只作脚本模式的兜底解析路径，避免遮蔽同名模块（与 conftest 同款理由）。
sys.path.append(str(REPO_ROOT / "tests"))

from unit_ci_workflows._source_parsing import (  # noqa: E402  （#5323 收敛：Java 取值唯一实现）
    java_code,
    java_literals,
)

ENGINE = (REPO_ROOT / "backend" / "ai-agent-service" / "app" / "briefing" / "proactive.py")
ASSEMBLY = (REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "java" / "com" / "migao"
            / "admin" / "service" / "DailyBriefingService.java")
REGISTRY_PATH = Path(__file__).resolve().parent / "proactive_declaration_registry.json"

#: 快照里**结构性**的键（不是「租户级事实」，不被 `enabled_by` 消费）—— 唯一一份排除口径。
#: 行数组（如 `orders` / `skus` / `product_return_stats`）不在这里写死：它们由
#: `SNAPSHOT_ROW_FIELDS` **现取**（新增数组不必回来改这份清单）。
STRUCTURAL_KEYS = frozenset({"metrics", "facts", "row_fields", "row_meta",
                             "orders", "skus", "returns"})


def engine_source() -> str:
    if not ENGINE.is_file():
        raise AssertionError(f"引擎源码不存在：{ENGINE}（fail-closed，不静默跳过）")
    return ENGINE.read_text(encoding="utf8")


def assembly_source() -> str:
    if not ASSEMBLY.is_file():
        raise AssertionError(f"装配层源码不存在：{ASSEMBLY}（fail-closed，不静默跳过）")
    return ASSEMBLY.read_text(encoding="utf8")


# ══════════════════════════════════════════════════════════════════════════════
# 一、两侧声明点的现取读数（纯函数：文本 → 声明；注入式红证 = 换文本重算）
# ══════════════════════════════════════════════════════════════════════════════


def parse_rules(source: str) -> dict[str, dict]:
    """`规则 id → {requires:[数组, 字段…], judgeable_fields, enabled_by, dimensions}`。"""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise AssertionError(f"引擎源码无法解析（{exc}）⇒ 判据失配 ⇒ 红") from exc
    out: dict[str, dict] = {}
    for node in ast.walk(tree):
        # `RULES: Tuple[RuleSpec, ...] = (...)` 是 AnnAssign（不是 Assign）—— 只认 Assign 会
        # 直接空跑（实测踩到：解析出 0 条规则 ⇒ fail-closed 报错，但那已是"判据失配"）
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        else:
            continue
        if getattr(target, "id", None) != "RULES" or not isinstance(value, ast.Tuple):
            continue
        for element in value.elts:
            kwargs = {kw.arg: kw.value for kw in element.keywords}

            def value(name, default=None):
                if name not in kwargs:
                    return default
                try:
                    return ast.literal_eval(kwargs[name])
                except (ValueError, SyntaxError):
                    return default

            rule_id = value("rule_id")
            requires = value("requires") or ("", ())
            out[str(rule_id)] = {
                "array": str(requires[0]),
                "fields": list(requires[1]),
                "judgeable_fields": list(value("judgeable_fields") or ()),
                "enabled_by": value("enabled_by"),
                "dimensions": list(value("dimensions") or ()),
            }
    if not out:
        raise AssertionError("解析不出任何 RULES ⇒ 判据会空跑（fail-closed）")
    return out


def parse_assembly(source: str) -> tuple[dict[str, list[str]], set[str]]:
    """装配层现取读数：`{行数组: [字段…]}` + 下发的**租户级事实**键集。

    **取值靠词法、不靠「按引号扫原文」的正则**（`#5323` 收敛）：字面量由
    `_source_parsing.java_literals` 按**位置**交付（注释里的字面量不算），
    前缀判定用 `原文[:位置].rstrip()`（共享模块 docstring 给出的同款用法），
    并**用注释已抹除的 `java_code` 视角做计数对账**（见末尾 fail-closed 段）。

    ⚠️ 本函数初版是引号定界的正则（`fields\.put\("(\w+)"`）—— 上线当天被类级元守卫
    `test_guard_parsing_is_comment_aware.py` 判红挡下（issue #5338 的机制**当场生效**）。
    这次是**改实现**，不是往台账里加豁免。
    """
    code = java_code(source)                     # 唯一一份 Java 剥注释实现（引号感知）
    literals = java_literals(source)             # ((起点, 值), …) —— 注释里的不算
    row_fields = literal_row_fields(source)      # 字面量式腿的字段集（**唯一取值实现**，见 一·B）
    puts = [value for start, value in literals
            if source[:start].rstrip().endswith("snapshot.put(")]
    # fail-closed：注释里写一句同形的 `fields.put("x", List.of("y"))` 会让上面多认出一个数组 ⇒
    # 与「注释已抹除」的视角**计数不等** ⇒ 当场红（而不是把注释里的东西静默读成声明）。
    if code.count("fields.put(") != len(row_fields):
        raise AssertionError(
            f"行字段解析对账失败：注释外 `fields.put(` 出现 {code.count('fields.put(')} 次，"
            f"而按字面量位置解析出 {len(row_fields)} 个数组 ⇒ 原文口径已不可信（fail-closed）")
    if code.count("snapshot.put(") != len(puts):
        raise AssertionError(
            f"租户事实解析对账失败：注释外 `snapshot.put(` 出现 {code.count('snapshot.put(')} 次，"
            f"而按字面量位置解析出 {len(puts)} 处 ⇒ 原文口径已不可信（fail-closed）")
    # 🔴 「租户事实」= `snapshot.put(<key>, …)` 里**既不是结构键、也不是已声明的行数组**的那些键。
    # 少了 `- set(row_fields)` 这一项，`product_return_stats`（#5369 新增的**行数组**）会被读成
    # 租户事实 ⇒ 假红（实测：本判据上线后第一次 rebase 就撞上）。
    facts = {value for value in puts
             if value not in STRUCTURAL_KEYS and value not in row_fields}
    if len(row_fields) < 3:
        raise AssertionError(f"装配层只解析出 {len(row_fields)} 个行数组 ⇒ 判据会空跑（fail-closed）")
    if not facts:
        raise AssertionError("装配层解析出 0 个租户级事实 ⇒ 判据会空跑（fail-closed）")
    return row_fields, facts


# ══════════════════════════════════════════════════════════════════════════════
# 一·B、**产出层**普查：现取式装配腿（issue #5461 —— 上面那套读数的射程缺口）
# ══════════════════════════════════════════════════════════════════════════════
#
# 病根：`parse_assembly` 认的是**源码形态**（`fields.put("<数组>", List.of(…))` 这种**字面量式**
# 装配）⇒ **现取式**腿（字段集由 `FieldTruth` 声明在运行时现取：`Map.of(array,
# declaration.declaredFields())`）整条落在射程之外：**不需要登记、不会有东西变红**（§23 G5）。
# 判据与出口见模块 docstring 的「射程」节。

ROW_FIELDS_KEY = "row_fields"
JAVA_MAIN = REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "java"
FIELDTRUTH_REL = "backend/admin-api/src/main/java/com/migao/admin/support/fieldtruth"
FIELD_TRUTH_REGISTRY_REL = f"{FIELDTRUTH_REL}/FieldTruthRegistry.java"

#: 产出表达式的字段集来源（第四态 = 判据读不出来 ⇒ **fail-closed 红**：面外不许永久免检）
SOURCE_FETCHED = "fetched"
SOURCE_LITERAL = "literal"
SOURCE_INDIRECT = "indirect"
SOURCE_UNKNOWN = "unknown"

#: **现取式**在产出层的指纹：值不是字面量，而是运行时从声明取。
FETCH_MARKERS = (".declaredFields()", ".payload()")

#: `FieldTruthRegistry` / 声明载体的**结构化**读数（读标识符与类名，**不按引号扫原文**）
_ACCESSOR_RE = re.compile(
    r"FieldTruth\.Declaration\s+(\w+)\s*\(\s*\)\s*\{[^}]*?declarationOf\s*\(\s*(\w+)\s*\.class", re.S)
_REGISTER_RE = re.compile(r"register\s*\(\s*(\w+)\s*\.declaration\s*\(\s*\)")
_ENTITY_RE = re.compile(r"new\s+FieldTruth\.Declaration\s*\(\s*(\w+)\s*\.class")


def literal_row_fields(source: str) -> dict[str, list[str]]:
    """`fields.put("<数组>", List.of("<字段>", …))` 的**字面量**字段集（字面量式腿的**唯一**取值实现）。

    从 `parse_assembly` 里提出来共用：产出层普查也要读它（字面量式腿的产出集 = 这些站点）。
    """
    literals = java_literals(source)
    row_fields: dict[str, list[str]] = {}
    for idx, (start, value) in enumerate(literals):
        if not source[:start].rstrip().endswith("fields.put("):
            continue
        names: list[str] = []
        prev_end = start + len(value) + 2        # 跳过两侧引号
        for pos, later in literals[idx + 1:]:
            if ")" in source[prev_end:pos]:      # `List.of(…)` 收尾 ⇒ 字段名到头
                break
            names.append(later)
            prev_end = pos + len(later) + 2
        row_fields[value] = names
    return row_fields


def _string_spans(code: str) -> list[tuple[int, int]]:
    """**代码视角**（`java_code` 的产出）里 Java 双引号字面量的 `(起, 止)`。

    ⚠️ 入参**必须**是 `java_code` 的产出：`java_code` 会把注释**删掉**（不是抹成等长空格），
    因此「原文坐标」与「代码坐标」不是同一个坐标系 —— 混用会让后面的位置切片错位
    （实测踩到：声明载体被抹掉一整段 ⇒ 读不到 `new FieldTruth.Declaration(...)`）。
    """
    return [(start, start + len(value) + 2) for start, value in java_literals(code)]


def masked_java(text: str) -> str:
    """**代码视角**（剥注释）+ 字符串内容抹成 `x` —— 括号配平与标识符定位的唯一视角。

    不抹字符串的话，字符串里的 `)`（`"a)b"`）会让产出表达式的括号配平**提前收尾**。
    「表达式里有没有字面量」那一类判定读的是**同一个代码视角**的切片，不受本函数影响。
    """
    code = java_code(text)
    chars = list(code)
    for start, end in _string_spans(code):
        for i in range(start, min(end, len(chars))):
            if chars[i] != "\n":
                chars[i] = "x"
    return "".join(chars)


def assigned_literal(text: str, name: str) -> str:
    """`<name> = "字面量"` 的值（靠**位置**取，不按引号扫原文）；找不到 ⇒ fail-closed 抛错。"""
    for start, value in java_literals(text):
        if text[:start].rstrip().endswith(f"{name} ="):
            return value
    raise AssertionError("源码里找不到 `" + name + " = \"…\"`（改名 / 形态漂移 ⇒ 同步本判据）")


def put_keys(text: str) -> list[str]:
    """`<ident>.put("<键>", …)` 的字面量键（按出现顺序；注释里的不算）。"""
    return [value for start, value in java_literals(text)
            if text[:start].rstrip().endswith(".put(")]


def java_main_sources(root: Path | None = None) -> dict[str, str]:
    """Java **主源码**语料：`仓库相对路径 → 原文`（产出层普查只解析含 `row_fields` 的那些文件）。"""
    where = root or JAVA_MAIN
    if not where.is_dir():
        raise AssertionError(f"Java 主源码目录不存在：{where}（fail-closed，不静默跳过）")
    out = {path.relative_to(REPO_ROOT).as_posix(): path.read_text(encoding="utf8")
           for path in sorted(where.rglob("*.java"))}
    if len(out) < 100:
        raise AssertionError(f"Java 主源码只读到 {len(out)} 个文件 ⇒ 普查语料不完整（fail-closed）")
    return out


def produced_row_field_exprs(source: str) -> list[tuple[int, str]]:
    """**产出层**读数：本文件里每一处「把字段集放进快照 `row_fields`」⇒ `(字面量起点, 产出表达式)`。

    全部在**同一个代码视角**里算（`java_code` + 掩码）：切片索引与 `masked` 同坐标系。
    """
    code = java_code(source)
    masked = masked_java(source)
    out: list[tuple[int, str]] = []
    for start, value in java_literals(code):
        if value != ROW_FIELDS_KEY or not code[:start].rstrip().endswith(".put("):
            continue
        comma = masked.find(",", start + len(value) + 2)
        if comma < 0:
            raise AssertionError(
                f"`{ROW_FIELDS_KEY}` 之后找不到实参逗号 ⇒ 产出层形态不认识（fail-closed）："
                f"…{code[max(0, start - 80):start + 20]!r}")
        depth, end = 0, comma
        while end < len(masked):
            char = masked[end]
            if char in "([{":
                depth += 1
            elif char in ")]}":
                if depth == 0:
                    break
                depth -= 1
            end += 1
        expr = code[comma + 1:end].strip()
        if not expr:
            raise AssertionError(f"`{ROW_FIELDS_KEY}` 的产出表达式为空 ⇒ 形态不认识（fail-closed）")
        out.append((start, expr))
    return out


def field_set_source(expr: str) -> str:
    """产出表达式的字段集来源：现取 / 字面量 / 间接（常量·变量）/ 读不出来。"""
    if any(marker in expr for marker in FETCH_MARKERS):
        return SOURCE_FETCHED
    if '"' in expr:
        return SOURCE_LITERAL
    return SOURCE_INDIRECT


def accessor_before(masked: str, pos: int) -> str:
    """`pos` 之前**最近**一次 `FieldTruthRegistry.<访问器>()` 的访问器名（`""` = 读不出来）。"""
    needle, found = "FieldTruthRegistry.", ""
    at = masked.find(needle)
    while 0 <= at < pos:
        end = at + len(needle)
        while end < len(masked) and (masked[end].isalnum() or masked[end] == "_"):
            end += 1
        if masked[end:end + 2] == "()" and end + 2 <= len(masked):
            found = masked[at + len(needle):end]
        at = masked.find(needle, end)
    return found


def declaration_index(sources: dict[str, str]) -> dict[str, dict]:
    """**声明载体**现取读数：`仓库相对路径 → {entity, table, fields}`（`FieldTruth.Declaration` 的载体）。"""
    out: dict[str, dict] = {}
    for rel, text in sorted(sources.items()):
        if not rel.startswith(FIELDTRUTH_REL + "/"):
            continue
        entity = _ENTITY_RE.search(masked_java(text))
        if entity is None:
            continue
        out[rel] = {"entity": entity.group(1),
                    "table": assigned_literal(text, "TABLE"),
                    "fields": put_keys(text)}
    if not out:
        raise AssertionError("`support/fieldtruth/**` 里读不到任何 `FieldTruth.Declaration` 载体 "
                             "⇒ 声明面读数为空（fail-closed）")
    return out


def registry_bindings(registry_source: str) -> tuple[dict[str, str], set[str]]:
    """`FieldTruthRegistry` 现取读数：`访问器 → 实体` + 已注册的声明类名集（读标识符，不读散文）。"""
    masked = masked_java(registry_source)
    registered = set(_REGISTER_RE.findall(masked))
    if not registered:
        raise AssertionError("`FieldTruthRegistry` 里读不到任何 `register(<类>.declaration())` "
                             "⇒ 注册面读数为空（fail-closed）")
    return dict(_ACCESSOR_RE.findall(masked)), registered


def fetched_leg_sites(sources: dict[str, str]) -> list[dict]:
    """**产出层**普查：每条装配腿 = 一处把字段集放进快照 `row_fields` 的产出点（不看怎么写）。"""
    sites: list[dict] = []
    for rel, text in sorted(sources.items()):
        if f'"{ROW_FIELDS_KEY}"' not in text:
            continue
        masked = masked_java(text)
        file_literals = sorted(literal_row_fields(text))
        for pos, expr in produced_row_field_exprs(text):
            sites.append({
                "file": rel, "pos": pos, "expr": expr,
                "source": field_set_source(expr),
                "accessor": accessor_before(masked, pos),
                "masked": masked,
                "file_literal_arrays": file_literals,
                "expr_literal_arrays": sorted({value for start, value in java_literals(expr)
                                               if expr[:start].rstrip().endswith("Map.of(")}),
            })
    if not sites:
        raise AssertionError("产出层普查不到任何 `row_fields` 产出点 ⇒ 判据会空跑（fail-closed）")
    return sites


def effective_kind(site: dict) -> str:
    """产出点的**有效**来源（分类成功但字段集读不出来的两类降级成 `unknown` ⇒ 判红）。"""
    if site["source"] == SOURCE_FETCHED:
        return SOURCE_FETCHED
    if site["source"] == SOURCE_LITERAL:
        return SOURCE_LITERAL if site["expr_literal_arrays"] else SOURCE_UNKNOWN
    return SOURCE_INDIRECT if site["file_literal_arrays"] else SOURCE_UNKNOWN


def literal_arrays_by_site(site: dict) -> list[str]:
    """该产出点**字面量式**产出的数组名（间接形态 = 本文件的 `fields.put(…)` 站点）。"""
    kind = effective_kind(site)
    if kind == SOURCE_LITERAL:
        return list(site["expr_literal_arrays"])
    if kind == SOURCE_INDIRECT:
        return list(site["file_literal_arrays"])
    return []


def load_registry(path: Path | None = None) -> dict:
    where = path or REGISTRY_PATH
    raw = json.loads(where.read_text(encoding="utf8"))
    for section in ("row_fields", "unwired_arrays", "tenant_facts", "fetched_arrays",
                    "judgeable_exemptions", "enabled_by_exemptions"):
        if not isinstance(raw.get(section), (dict, list)):
            raise AssertionError(f"登记册缺 {section} 段（结构损坏）：{where}")
    return raw


def live_fields(row_fields: dict[str, list[str]]) -> set[str]:
    return {f"{array}.{name}" for array, names in row_fields.items() for name in names}


# ══════════════════════════════════════════════════════════════════════════════
# 二、判据（纯函数：输入两侧文本 + 登记册，输出问题清单 —— 空 = 绿）
# ══════════════════════════════════════════════════════════════════════════════


def problems_field_registry(registry: dict, row_fields: dict[str, list[str]]) -> list[str]:
    """① 装配层声明 ≡ 登记册（逐字相等）；② requires 的字段必须被产出或数组已登记未接线。"""
    out: list[str] = []
    live = live_fields(row_fields)
    known = set(registry["row_fields"])
    for field in sorted(live - known):
        out.append(f"装配层新声明了行字段 `{field}`，但**未登记** ⇒ 在 row_fields 里补一格"
                   f"（nullable 裁定 + reason + issue）—— 未登记即红")
    for field in sorted(known - live):
        out.append(f"登记册里的 `{field}` 在装配层**已不存在** ⇒ 陈旧条目必须销账")
    rules = parse_rules(engine_source())
    unwired = set(registry["unwired_arrays"])
    for rule_id, spec in sorted(rules.items()):
        if spec["array"] in unwired:
            continue
        for field in spec["fields"]:
            key = f"{spec['array']}.{field}"
            if key not in live:
                out.append(f"规则 `{rule_id}` 的 requires 读了 `{key}`，但装配层**不产出**它 "
                           f"（也不是登记在册的未接线数组）⇒ 死绑定")
    return out


def problems_judgeable(registry: dict, source: str) -> list[str]:
    """③ nullable 字段被 requires ⇒ 必须登记 judgeable_fields（漏登记 ⇒ 红）；④ 打字错 ⇒ 红。"""
    out: list[str] = []
    rules = parse_rules(source)
    exempt = registry["judgeable_exemptions"]
    for rule_id, spec in sorted(rules.items()):
        for key in (spec["judgeable_fields"] + spec["dimensions"]):
            if key not in spec["fields"]:
                out.append(f"规则 `{rule_id}` 登记了 `{key}`，但它**不在 requires 的字段里** "
                           f"⇒ 打字错/口径漂移（requires={spec['fields']}）")
        for field in spec["fields"]:
            entry = registry["row_fields"].get(f"{spec['array']}.{field}") or {}
            if not entry.get("nullable"):
                continue
            if field in spec["judgeable_fields"] or f"{rule_id}:{field}" in exempt:
                continue
            out.append(f"规则 `{rule_id}` 读了**可空**字段 `{field}`，却没登记 `judgeable_fields` "
                       f"⇒ 该字段为空的行会被读成「没命中 = 没问题」（漏登记即红）")
    return out


def problems_tenant_facts(registry: dict, source: str, facts: set[str], facts_java: set[str]) -> list[str]:
    """⑤ 事实登记册 ≡ 装配层；⑥ gated 字段的规则必须声明 enabled_by。"""
    out: list[str] = []
    known = set(registry["tenant_facts"])
    for fact in sorted(facts_java - known):
        out.append(f"装配层新下发了租户事实 `{fact}`，但**未登记** ⇒ 在 tenant_facts 里补一格"
                   f"（gates 声明 + reason + issue）—— 未登记即红")
    for fact in sorted(known - facts_java):
        out.append(f"登记册里的租户事实 `{fact}` 装配层**已不下发** ⇒ 陈旧条目必须销账")
    rules = parse_rules(source)
    exempt = registry["enabled_by_exemptions"]
    for rule_id, spec in sorted(rules.items()):
        if not spec["enabled_by"]:
            continue
        fact = str(spec["enabled_by"][0])
        if fact not in known:
            out.append(f"规则 `{rule_id}` 的 enabled_by 指向 `{fact}`，但它**不在登记册**里 "
                       f"⇒ 指向一个没人担保存在的事实（静默落 wired）")
        elif fact not in facts_java:
            out.append(f"规则 `{rule_id}` 的 enabled_by 指向 `{fact}`，但装配层**不下发**这个键 "
                       f"⇒ 该规则在未开启租户上静默落 wired")
    for fact, entry in sorted(registry["tenant_facts"].items()):
        for gated in entry.get("gates") or []:
            for rule_id, spec in sorted(rules.items()):
                if gated not in [f"{spec['array']}.{f}" for f in spec["fields"]]:
                    continue
                if spec["enabled_by"] and str(spec["enabled_by"][0]) == fact:
                    continue
                if f"{rule_id}:{fact}" in exempt:
                    continue
                out.append(f"规则 `{rule_id}` 读了被 `{fact}` gate 的 `{gated}`，却没声明 "
                           f"`enabled_by` ⇒ 未开启的租户上会静默落 wired（漏登记即红）")
    return out


def problems_ledger_shape(registry: dict) -> list[str]:
    """⑦ 条目带 reason + issue；豁免台账只许为空（缩短）。"""
    out: list[str] = []
    for section in ("row_fields", "unwired_arrays", "tenant_facts", "fetched_arrays"):
        for key, entry in sorted(registry[section].items()):
            if not isinstance(entry, dict):
                out.append(f"`{section}.{key}` 不是对象 ⇒ 登记条目必须自描述")
                continue
            for field in ("reason", "issue"):
                if not str(entry.get(field) or "").strip():
                    out.append(f"`{section}.{key}` 缺 `{field}`（没有理由/单号的登记等于没人看）")
    for section in ("judgeable_exemptions", "enabled_by_exemptions"):
        for key, reason in sorted(registry[section].items()):
            if not str(reason).strip() or "#" not in str(reason):
                out.append(f"豁免条目 `{section}.{key}` 的理由={reason!r} 不合格 ⇒ "
                           "必须写「为什么可以豁免 + 单号（#NNNN）」")
    return out


def problems_exemptions_are_empty(registry: dict) -> list[str]:
    """燃尽靶子：两个豁免台账**今天必须为空**（只许缩短；加到非空必须在 diff 里看得见）。"""
    out: list[str] = []
    for section in ("judgeable_exemptions", "enabled_by_exemptions"):
        if registry[section]:
            out.append(f"豁免台账 `{section}` 非空（{len(registry[section])} 条）⇒ "
                       "要么修掉对应缺口，要么在本 PR 的 diff 里显式说明为何必须豁免")
    return out


def first_argument(expr: str) -> str:
    """产出表达式的第一个实参（`Map.of(<它>, …)`)—— 判「数组身份现取自 `declaration.table()`」。"""
    open_paren = expr.find("(")
    if open_paren < 0:
        return ""
    comma = expr.find(",", open_paren)
    return expr[open_paren + 1:comma if comma > 0 else len(expr)].strip()


def accessor_name(raw: str) -> str:
    """台账里的访问器写法（`FieldTruthRegistry.customerProfile()` / `customerProfile`）→ 方法名。"""
    return raw.strip().rstrip("()").rsplit(".", 1)[-1]


def _criterion_problems(entry_key: str, criterion: str) -> list[str]:
    """契约判据必须**真实存在**（拦死判据：删掉/改名 ⇒ 红）。"""
    if "::" not in criterion:
        return [f"`{entry_key}` 的 criterion=`{criterion}` 形态不合格 ⇒ "
                f"必须是 `<仓库相对路径>::<测试名>`（与 declaration_gate_registry 同款）"]
    rel, name = criterion.split("::", 1)
    path = REPO_ROOT / rel
    if not path.is_file():
        return [f"`{entry_key}` 的 criterion 指向的文件不存在：`{rel}` ⇒ "
                f"契约「声明 ≡ 实际产出」的**拦死判据**已消失（不许静默删掉）"]
    if not re.search(rf"\b{re.escape(name)}\s*\(", path.read_text(encoding="utf8")):
        return [f"`{entry_key}` 的 criterion `{name}` 在 `{rel}` 里找不到 ⇒ 拦死判据已消失"
                f"（运行期判据才是「声明 ≡ 实际产出」的真值面，§23.7 A3）"]
    return []


def _registration_hint(accessors: dict[str, str], carriers: dict[str, dict], site: dict) -> str:
    """给「未登记即红」一条**真可行动**的出口：键 + 该填什么（§23 G3）。"""
    accessor = site["accessor"]
    if not accessor:
        return ("（`" + site["file"] + "` 里连 `FieldTruthRegistry.<访问器>()` 都读不到 ⇒ "
                "先把这条腿的声明来源写清，再按 `<文件>::<数组名>` 登记）")
    entity = accessors.get(accessor)
    if entity is None:
        return (f"（访问器 `{accessor}` 在 `FieldTruthRegistry` 里读不出实体 ⇒ 先把来源写清，"
                f"再按 `<文件>::<数组名>` 登记）")
    matched = [c for c in carriers.values() if c["entity"] == entity]
    array = matched[0]["table"] if matched else "<数组名>"
    return (f"键 `{site['file']}::{array}`，字段：accessor / declaration / criterion / reason / issue"
            f"（可复制形态 = proactive_declaration_registry.json 的 customer_profiles 条）")


def problems_fetched_legs(registry: dict, sources: dict[str, str],
                          registry_java: str | None = None) -> list[str]:
    """⑨~⑭ **现取式装配腿**：未登记即红 / 陈旧即红 / 声明与产出必须同源 / 面外不许免检（#5461）。"""
    out: list[str] = []
    reg_source = registry_java if registry_java is not None else sources.get(FIELD_TRUTH_REGISTRY_REL)
    if reg_source is None:
        raise AssertionError(f"Java 主源码语料里缺 `{FIELD_TRUTH_REGISTRY_REL}`（fail-closed）")
    accessors, registered = registry_bindings(reg_source)
    carriers = declaration_index(sources)
    entries = registry["fetched_arrays"]
    sites = fetched_leg_sites(sources)

    # ── 产出侧①：读不出来的产出形态 ⇒ 未登记即红（§23 G5：面外不许永久免检）──
    for site in sites:
        if effective_kind(site) != SOURCE_UNKNOWN:
            continue
        out.append(
            f"装配腿 `{site['file']}` 的 `row_fields` 产出表达式 `{site['expr']}` 的字段集来源"
            f"**读不出来**（既不是字面量清单、也不是声明现取、该文件里也没有 `fields.put(…)` 站点）⇒ "
            f"**未登记即红**：① 该腿的字段集确实来自 `FieldTruth` 声明 ⇒ 按现取式在 fetched_arrays 里登记；"
            f"② 是别的形态 ⇒ 把该形态接入本判据（或落回上述两种形态之一）—— 面外不许永久免检")

    # ── 产出侧②：现取式腿逐条归属到登记项 ──
    produced_pairs: set[tuple[str, str]] = set()
    fetched_arrays: dict[str, list[str]] = {}
    for site in sites:
        if effective_kind(site) != SOURCE_FETCHED:
            continue
        produced_pairs.add((site["file"], site["accessor"]))
        if '"' in site["expr"]:
            out.append(f"现取式腿 `{site['file']}` 的产出表达式 `{site['expr']}` 里**出现字面量** ⇒ "
                       f"第二份字段清单（两处投影必然分叉）：产出的字段集必须**整份现取**"
                       f"（`Map.of(array, declaration.declaredFields())`）；真要写字面量清单就登记进 row_fields")
        key_ident = first_argument(site["expr"])
        if not re.fullmatch(r"\w+", key_ident):
            out.append(f"现取式腿 `{site['file']}` 的产出表达式 `{site['expr']}` 的数组名不是变量 ⇒ "
                       f"产出的数组身份必须现取自 `declaration.table()`（否则产出与声明可能不同源）")
        elif not re.search(rf"\b{re.escape(key_ident)}\s*=\s*[\w.]*\.table\s*\(\s*\)", site["masked"]):
            out.append(f"现取式腿 `{site['file']}` 的数组名 `{key_ident}` 在本文件里没有 "
                       f"`= <声明>.table()` 的绑定 ⇒ 产出的数组身份不是现取自声明（同源判据判不了）")
        entry_key = next((k for k in entries
                          if isinstance(entries[k], dict) and "::" in k
                          and k.split("::", 1)[0] == site["file"]
                          and accessor_name(str(entries[k].get("accessor") or "")) == site["accessor"]),
                         None)
        if entry_key is None:
            out.append(f"装配层有一条**现取式**装配腿（`{site['file']}`，字段集由声明运行时现取："
                       f"`FieldTruthRegistry.{site['accessor']}()`），但**未登记** ⇒ 在 fetched_arrays 里"
                       f"补一格：{_registration_hint(accessors, carriers, site)} —— 未登记即红（#5461）")
        else:
            fetched_arrays.setdefault(entry_key.split("::", 1)[1], []).append(site["file"])

    # ── 台账侧：形态 / 同源 / 陈旧（只许缩短）──
    for entry_key, entry in sorted(entries.items()):
        if not isinstance(entry, dict) or "::" not in entry_key:
            out.append(f"fetched_arrays 的键 `{entry_key}` 形态不合格 ⇒ "
                       f"必须是 `<java 仓库相对路径>::<产出的数组名>`")
            continue
        leg_file, array = entry_key.split("::", 1)
        accessor = accessor_name(str(entry.get("accessor") or ""))
        if (leg_file, accessor) not in produced_pairs:
            out.append(f"台账条目 `{entry_key}` 对应的腿在**产出层已不存在**（`{leg_file}` 里读不到 "
                       f"`FieldTruthRegistry.{accessor}()` 的 `row_fields` 产出点）⇒ "
                       f"陈旧条目必须销账（台账只许缩短）")
        decl_rel = str(entry.get("declaration") or "")
        carrier = carriers.get(decl_rel)
        if carrier is None:
            out.append(f"`{entry_key}` 的 declaration=`{decl_rel}` 不是一份 `FieldTruth.Declaration` 载体"
                       f"（`{FIELDTRUTH_REL}/` 下读不到它）⇒ 登记指向了不存在的声明面")
            continue
        entity = accessors.get(accessor)
        if entity is None:
            out.append(f"`{entry_key}` 的 accessor=`{accessor}` 在 `FieldTruthRegistry` 里读不出实体"
                       f"（访问器改名 / 形态漂移 ⇒ 同步本判据与台账）")
        elif entity != carrier["entity"]:
            out.append(f"`{entry_key}` 的 accessor（实体 `{entity}`）与 declaration（实体 "
                       f"`{carrier['entity']}`）**不同源** ⇒ 登记的声明不是这条腿真正现取的那一份")
        if Path(decl_rel).stem not in registered:
            out.append(f"`{entry_key}` 的声明类 `{Path(decl_rel).stem}` 不在 `FieldTruthRegistry` 的 "
                       f"`register(…)` 里 ⇒ 声明未注册（运行期谁也现取不到它）")
        if carrier["table"] != array:
            out.append(f"`{entry_key}` 的数组名与声明的 `TABLE` 不一致（声明 = `{carrier['table']}`）⇒ "
                       f"产出的数组身份必须现取自 `declaration.table()`")
        if not carrier["fields"]:
            out.append(f"`{entry_key}` 的声明 `{decl_rel}` 里读不到任何字段（`f.put(\"<字段>\", …)` 为空）"
                       f"⇒ 声明字段集为空（形态漂移或空声明，fail-closed）")
        criteria = entry.get("criterion")
        if not isinstance(criteria, list) or not criteria:
            out.append(f"`{entry_key}` 缺 `criterion`（运行期「声明 ≡ 实际产出」的**拦死判据**指针，"
                       f"形如 `<测试文件>::<测试名>`）—— 没有它，契约就只剩散文")
            continue
        for criterion in criteria:
            out.extend(_criterion_problems(entry_key, str(criterion)))

    # ── 两处投影：同一数组既有字面量腿又有现取式腿 ⇒ 必然分叉 ──
    for array, files in sorted(fetched_arrays.items()):
        literal_files = sorted({site["file"] for site in sites
                                if array in literal_arrays_by_site(site)})
        if literal_files:
            out.append(f"数组 `{array}` 同时有**字面量式**腿（{literal_files}）与**现取式**腿"
                       f"（{sorted(files)}）⇒ 两份字段集投影必然分叉：只留一条腿（现取式 = 单源）")
    return out


def problems_ledger_census_disagreement(registry: dict, sites: list[dict]) -> list[str]:
    """**关系式**判据：台账声称的现取式腿 ⟺ 产出层普查看得见的现取式腿（两向都要一致）。

    刻意**不**写成「仓库当下必须有一条现取式腿」（那是**自毁式真值主张**：哪天那条腿被合法改写成
    字面量式，判据会挡住正确的改动）。这里判的是两侧**是否互相印证** ——
    台账有而普查看不见 = 普查失效（或条目没销账）；普查看得见而台账没有 = 未登记（另一种判据也会红）。
    """
    fetched = [site for site in sites if effective_kind(site) == SOURCE_FETCHED]
    if bool(registry["fetched_arrays"]) == bool(fetched):
        return []
    return [f"台账与产出层普查**不一致**：台账声称 {len(registry['fetched_arrays'])} 条现取式腿 / "
            f"产出层看得见 {len(fetched)} 条 ⇒ 要么普查失效（看不见真腿）、要么台账陈旧（条目没销账），"
            f"两者都不许（fail-closed）"]


def fetched_legs_reading(registry: dict, sources: dict[str, str]) -> str:
    sites = fetched_leg_sites(sources)
    kinds = [effective_kind(site) for site in sites]
    carriers = declaration_index(sources)
    return (f"读数：装配腿 {len(sites)} 条（现取式 {kinds.count(SOURCE_FETCHED)} / "
            f"字面量式 {kinds.count(SOURCE_LITERAL)} / 间接 {kinds.count(SOURCE_INDIRECT)} / "
            f"读不出来 {kinds.count(SOURCE_UNKNOWN)}）/ 声明载体 {len(carriers)} 份 / "
            f"声明字段 {sum(len(c['fields']) for c in carriers.values())} 个 / "
            f"现取式台账 {len(registry['fetched_arrays'])} 条")


def mechanism_reading(registry: dict, row_fields: dict[str, list[str]], facts: set[str]) -> str:
    rules = parse_rules(engine_source())
    nullable = sum(1 for e in registry["row_fields"].values() if e.get("nullable"))
    gated = sum(len(e.get("gates") or []) for e in registry["tenant_facts"].values())
    return (f"读数：规则 {len(rules)} 条 / 装配层行字段 {len(live_fields(row_fields))} 个"
            f"（{len(row_fields)} 个数组）/ 租户事实 {len(facts)} 个 / nullable 登记 {nullable} 个 / "
            f"gated 字段 {gated} 个 / 豁免 {len(registry['judgeable_exemptions'])} + "
            f"{len(registry['enabled_by_exemptions'])} 条")


# ══════════════════════════════════════════════════════════════════════════════
# 三、判据（真语料）
# ══════════════════════════════════════════════════════════════════════════════


def test_assembly_row_fields_are_registered():
    registry, row_fields, _ = load_registry(), *parse_assembly(assembly_source())
    problems = problems_field_registry(registry, row_fields)
    if problems:
        raise AssertionError("行字段声明与登记册不一致：\n  - " + "\n  - ".join(problems))


def test_nullable_fields_are_judgeable():
    """**本单的强判据**：读了可空字段却没登记 judgeable_fields ⇒ 红（#5389 判据 1）。"""
    problems = problems_judgeable(load_registry(), engine_source())
    if problems:
        raise AssertionError("judgeable_fields 漏登记：\n  - " + "\n  - ".join(problems))


def test_tenant_facts_are_registered_and_gated():
    registry = load_registry()
    _, facts = parse_assembly(assembly_source())
    problems = problems_tenant_facts(registry, engine_source(), facts, facts)
    if problems:
        raise AssertionError("租户事实/enabled_by 声明不一致：\n  - " + "\n  - ".join(problems))


def test_ledger_entries_carry_reason_and_issue():
    problems = problems_ledger_shape(load_registry())
    if problems:
        raise AssertionError("登记条目形态不合格：\n  - " + "\n  - ".join(problems))


def test_exemption_ledgers_are_empty():
    registry = load_registry()
    print(mechanism_reading(registry, *parse_assembly(assembly_source())[:1],
                            parse_assembly(assembly_source())[1]))
    problems = problems_exemptions_are_empty(registry)
    if problems:
        raise AssertionError("\n  - ".join(problems))


def test_mechanism_is_not_vacuous():
    """反空跑：规则 / 行字段 / 事实 / nullable / gated 都必须有正读数（判据不靠「扫不到」通过）。"""
    registry = load_registry()
    row_fields, facts = parse_assembly(assembly_source())
    reading = mechanism_reading(registry, row_fields, facts)
    print(reading)
    rules = parse_rules(engine_source())
    nullable = [k for k, e in registry["row_fields"].items() if e.get("nullable")]
    gated = [g for e in registry["tenant_facts"].values() for g in (e.get("gates") or [])]
    if len(rules) < 3 or len(live_fields(row_fields)) < 10 or len(facts) < 1:
        raise AssertionError(f"{reading} ⇒ 读数过小，判据会空跑（fail-closed）")
    if not nullable or not gated:
        raise AssertionError(f"{reading} ⇒ 没有可空/gated 字段 ⇒ 判据 3/6 无从判别（是空判据）")


def test_fetched_assembly_legs_are_registered():
    """⑨~⑭ **现取式**装配腿：未登记 / 陈旧 / 声明与产出不同源 / 面外形态 ⇒ 红（issue #5461）。"""
    problems = problems_fetched_legs(load_registry(), java_main_sources())
    if problems:
        raise AssertionError("现取式装配腿的登记面不一致：\n  - " + "\n  - ".join(problems))


def test_fetched_leg_census_is_not_vacuous():
    """反空跑：台账与普查必须**一致**（「扫不到」不许长得像「通过」）。

    ⚠️ 判据形态是**关系式**（台账声称的腿数 ⟺ 产出层看得见的腿数），不是「仓库当下必须有一条现取式腿」
    —— 后者是**自毁式真值主张**：哪天那条腿被合法改写成字面量式，判据会挡住正确的改动。
    普查**能不能看见新腿**另由注入式红证证明（`TestFetchedLegRedProofs` 的前提自证），与仓库真值无关。
    """
    registry, sources = load_registry(), java_main_sources()
    reading = fetched_legs_reading(registry, sources)
    print(reading)
    problems = problems_ledger_census_disagreement(registry, fetched_leg_sites(sources))
    if problems:
        raise AssertionError("台账与产出层普查不一致：\n  - " + "\n  - ".join(problems))
    declared = sum(len(c["fields"]) for c in declaration_index(sources).values())
    if declared < 5:
        raise AssertionError(f"{reading} ⇒ 声明字段读数只有 {declared} ⇒ 契约判据无从判别（fail-closed）")


# ══════════════════════════════════════════════════════════════════════════════
# 四、注入式红证（§23 G7：注入先自证生效，再要求判据变红）
# ══════════════════════════════════════════════════════════════════════════════


def _mutate(text: str, old: str, new: str, where: str) -> str:
    if old not in text:
        raise AssertionError(f"注入锚点未命中（注入未生效 ⇒ 该红证是空断言）：{where} 里找不到 {old!r}")
    mutated = text.replace(old, new, 1)
    if mutated == text:
        raise AssertionError(f"注入未生效（mutated == src）：{where}")
    return mutated


def _drop_block(text: str, marker: str) -> str:
    """删掉 `marker` 所在的那**一整条**表达式（多行调用 ⇒ 删到以 `),` 收尾的那一行为止）。

    为什么不用「注释掉首行」：多行实参被注释掉一半会留下**悬空续行** ⇒ 源码语法错、
    判据当场报「无法解析」（实测踩到）—— 那证的不是判别力，是自己的注入写坏了。
    """
    lines = text.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if marker in line), None)
    if start is None:
        raise AssertionError(f"注入锚点未命中（注入未生效 ⇒ 该红证是空断言）：找不到 {marker!r}")
    end = start
    while end < len(lines) and not lines[end].rstrip().endswith("),"):
        end += 1
    if end >= len(lines):
        raise AssertionError(f"注入锚点 {marker!r} 之后找不到表达式收尾（`),`）⇒ 注入未生效")
    mutated = "".join(lines[:start] + lines[end + 1:])
    if mutated == text:
        raise AssertionError(f"注入未生效（mutated == src）：{marker!r}")
    return mutated


def _registry(**overrides) -> dict:
    reg = load_registry()
    for key, value in overrides.items():
        if key not in ("row_fields", "tenant_facts", "judgeable_exemptions",
                       "enabled_by_exemptions", "unwired_arrays", "fetched_arrays"):
            raise AssertionError(f"未知覆盖字段 {key}")
        reg[key] = value
    return reg


def _copy(section: dict) -> dict:
    return {k: (dict(v) if isinstance(v, dict) else v) for k, v in section.items()}


class TestRedProofs:
    """每条判据的判别力：注入 ⇒ 对应的问题清单**必须**非空（不是"一起红"）。"""

    def test_dropping_judgeable_registration_is_red(self):
        """**漏登记**的真形态：删掉规则的 judgeable_fields ⇒ 判据 3 必须红。"""
        mutated = _mutate(engine_source(), 'judgeable_fields=("cost_amount",),', "", "proactive.py")
        if "judgeable_fields" in parse_rules(mutated)["below_cost_price"]["judgeable_fields"]:
            raise AssertionError("注入未生效：judgeable_fields 仍在")
        problems = problems_judgeable(load_registry(), mutated)
        if not any("below_cost_price" in p and "cost_amount" in p for p in problems):
            raise AssertionError(f"漏登记 judgeable_fields 后判据未变红 ⇒ 空断言：{problems}")

    def test_new_assembly_field_unregistered_is_red(self):
        mutated = _mutate(assembly_source(), '"sale_amount", "cost_amount"));',
                          '"sale_amount", "cost_amount", "discount_amount"));',
                          "DailyBriefingService")
        row_fields, _ = parse_assembly(mutated)
        if "orders.discount_amount" not in live_fields(row_fields):
            raise AssertionError("注入未生效：新字段没被解析出来")
        problems = problems_field_registry(load_registry(), row_fields)
        if not any("discount_amount" in p for p in problems):
            raise AssertionError(f"装配层新增字段后判据未变红 ⇒ 空断言：{problems}")

    def test_new_tenant_fact_unregistered_is_red(self):
        mutated = _mutate(assembly_source(),
                          'snapshot.put("cost_accounting", costsAreTracked(tenantId));',
                          'snapshot.put("cost_accounting", costsAreTracked(tenantId));\n'
                          '        snapshot.put("inventory_tracking", costsAreTracked(tenantId));',
                          "DailyBriefingService")
        _, facts = parse_assembly(mutated)
        problems = problems_tenant_facts(load_registry(), engine_source(), facts, facts)
        if not any("inventory_tracking" in p for p in problems):
            raise AssertionError(f"装配层新增事实后判据未变红 ⇒ 空断言：{problems}")

    def test_enabled_by_pointing_nowhere_is_red(self):
        mutated = _mutate(engine_source(), 'enabled_by=("cost_accounting"',
                          'enabled_by=("no_such_fact"', "proactive.py")
        _, facts = parse_assembly(assembly_source())
        problems = problems_tenant_facts(load_registry(), mutated, facts, facts)
        if not any("no_such_fact" in p for p in problems):
            raise AssertionError(f"enabled_by 指向不存在的事实后判据未变红 ⇒ 空断言：{problems}")

    def test_dropping_enabled_by_is_red(self):
        """删掉 enabled_by ⇒ gated 字段失去租户前置 ⇒ 判据 6 红（静默落 wired 的真形态）。"""
        mutated = _drop_block(engine_source(), 'enabled_by=("cost_accounting"')
        if parse_rules(mutated)["below_cost_price"]["enabled_by"]:
            raise AssertionError("注入未生效：enabled_by 仍在")
        _, facts = parse_assembly(assembly_source())
        problems = problems_tenant_facts(load_registry(), mutated, facts, facts)
        if not any("gate" in p and "below_cost_price" in p for p in problems):
            raise AssertionError(f"删掉 enabled_by 后判据未变红 ⇒ 空断言：{problems}")

    def test_marking_a_field_nullable_is_red(self):
        """⑥ 判据 3 的判别力：把某字段标成 nullable 而消费规则未登记 ⇒ 红。"""
        row_fields = _copy(load_registry()["row_fields"])
        row_fields["orders.status"] = {**row_fields["orders.status"], "nullable": True}
        problems = problems_judgeable(_registry(row_fields=row_fields), engine_source())
        if not any("unshipped_overdue" in p and "status" in p for p in problems):
            raise AssertionError(f"把 status 标成可空后判据未变红 ⇒ 空断言：{problems}")

    def test_comment_cannot_feed_the_parser(self):
        """注释里写一句同形的取值文本 ⇒ **喂不动**取值；若真喂动了，对账闸**必红**（fail-closed）。

        这是本文件被类级元守卫 `test_guard_parsing_is_comment_aware.py` 判红后的落地口径：
        取值靠 `java_literals` 的**位置**（注释里的字面量不算），前缀判定再用
        `java_code` 视角的计数对账 —— 两条路都不吃注释。
        """
        # ① 注释里的同形文本：不得被读成声明（注释里的字面量不进 java_literals）
        mutated = _mutate(assembly_source(), 'snapshot.put("cost_accounting"',
                          '// snapshot.put("ghost_fact", costsAreTracked(tenantId));\n'
                          '        snapshot.put("cost_accounting"', "DailyBriefingService")
        _, facts = parse_assembly(mutated)
        if "ghost_fact" in facts:
            raise AssertionError(f"注释里的同形文本被读成了声明（正是 #5323 的病灶）：{facts}")
        # ② 前缀启发式被注释喂中 ⇒ 计数对账必须**当场红**（而不是静默多认一个数组）
        # 锚点选在**不是**数组名的那一行：注释紧贴其后的字面量（`"sale_amount"`）才不会被
        # 真数组名覆盖（选在数组名那一行会因 dict 同键覆盖而"看不出来"，实测踩到）
        poisoned = _mutate(assembly_source(), '"shipped_at", "sale_amount", "cost_amount"));',
                           '"shipped_at",\n                // 这里**不要**再写 fields.put(\n'
                           '                "sale_amount", "cost_amount"));',
                           "DailyBriefingService")
        try:
            parse_assembly(poisoned)
        except AssertionError as exc:
            if "对账失败" not in str(exc):
                raise AssertionError(f"注释喂中后报的不是对账闸：{exc}") from exc
        else:
            raise AssertionError("注释喂中前缀启发式后没有红 ⇒ 对账闸是空判据")

    def test_missing_reason_is_red(self):
        row_fields = _copy(load_registry()["row_fields"])
        row_fields["orders.order_no"] = {**row_fields["orders.order_no"], "reason": ""}
        problems = problems_ledger_shape(_registry(row_fields=row_fields))
        if not any("reason" in p for p in problems):
            raise AssertionError(f"抹掉 reason 后判据未变红 ⇒ 空断言：{problems}")

    def test_exemption_ledger_nonempty_is_red(self):
        problems = problems_exemptions_are_empty(
            _registry(judgeable_exemptions={"below_cost_price:cost_amount": "先豁免（#5389）"}))
        if not problems:
            raise AssertionError("豁免台账非空后判据未变红 ⇒ 空断言")
        shape = problems_ledger_shape(
            _registry(judgeable_exemptions={"below_cost_price:cost_amount": "先豁免"}))
        if not any("不合格" in p for p in shape):
            raise AssertionError(f"豁免条目缺单号后判据未变红 ⇒ 空断言：{shape}")


# ══════════════════════════════════════════════════════════════════════════════
# 五、**现取式装配腿**的注入式红证（issue #5461：造一条现取式腿 ⇒ 未登记即红）
# ══════════════════════════════════════════════════════════════════════════════

CUSTOMER_SERVICE_REL = ("backend/admin-api/src/main/java/com/migao/admin/service"
                        "/CustomerService.java")
CUSTOMER_PROFILE_DECL_REL = f"{FIELDTRUTH_REL}/CustomerProfileFieldTruth.java"
NEW_DECLARATION_REL = f"{FIELDTRUTH_REL}/CustomerTagFieldTruth.java"
CRITERION_REL = ("backend/admin-api/src/test/java/com/migao/admin/service"
                 "/CustomerProfileViewSnapshotTest.java")
CRITERION = f"{CRITERION_REL}::snapshot_shape_and_row_keys_follow_the_declaration"

#: 夹具①（**新声明类**）：新表 ⇒ 新数组 `customer_tags`。
NEW_DECLARATION_SRC = """package com.migao.admin.support.fieldtruth;

import com.migao.admin.entity.CustomerTag;

import java.util.LinkedHashMap;
import java.util.Map;

/** 夹具（#5461 红证）：`customer_tags` 的字段级真值声明。 */
public final class CustomerTagFieldTruth {

    public static final String TABLE = "customer_tags";

    private CustomerTagFieldTruth() {
    }

    public static FieldTruth.Declaration declaration() {
        Map<String, FieldTruth.Entry> f = new LinkedHashMap<>();
        f.put("id", new FieldTruth.Entry(FieldTruth.HAS_TRUTH, "夹具：@TableId 框架生成"));
        f.put("tenantId", new FieldTruth.Entry(FieldTruth.HAS_TRUTH, "夹具：建档时下发"));
        f.put("hitCount", new FieldTruth.Entry(FieldTruth.NO_TRUTH, "夹具：计数列只有列默认值 0"));
        return new FieldTruth.Declaration(CustomerTag.class, TABLE, f);
    }
}
"""

#: 夹具③（**装配层的新产出点**）：字段集**运行时从声明现取** —— 这就是「现取式腿」。
NEW_LEG_SRC = """    // 夹具注入（#5461 红证·第 ③ 步）：一条**现取式**装配腿
    public Map<String, Object> tagSnapshot(Long tenantId, int limit) {
        FieldTruth.Declaration declaration = FieldTruthRegistry.customerTag();
        String array = declaration.table();
        Map<String, Object> snapshot = new LinkedHashMap<>();
        snapshot.put("row_fields", Map.of(array, declaration.declaredFields()));
        snapshot.put(array, new ArrayList<>());
        return snapshot;
    }

"""


def _injected_sources(*, register_declaration: bool = True) -> dict[str, str]:
    """造一条**现取式**装配腿：① 新声明类 ② 注册表登记（+ 访问器） ③ 装配层新产出点。

    每一步都用 `_mutate` 注入（锚点未命中即抛 ⇒ 注入未生效不会被读成「判据不红」= 空断言）。
    """
    sources = java_main_sources()
    sources[CUSTOMER_SERVICE_REL] = _mutate(
        sources[CUSTOMER_SERVICE_REL], "    private static Map<String, Object> profileRow(",
        NEW_LEG_SRC + "    private static Map<String, Object> profileRow(", "CustomerService")
    sources[NEW_DECLARATION_REL] = NEW_DECLARATION_SRC
    if register_declaration:
        registry = _mutate(sources[FIELD_TRUTH_REGISTRY_REL],
                           "        register(CustomerProfileFieldTruth.declaration());",
                           "        register(CustomerProfileFieldTruth.declaration());\n"
                           "        register(CustomerTagFieldTruth.declaration());",
                           "FieldTruthRegistry")
        sources[FIELD_TRUTH_REGISTRY_REL] = _mutate(
            registry, "    /** 便捷入口：客户档案（首个载体）。 */",
            "    /** 夹具：客户标签（#5461 红证）。 */\n"
            "    public static FieldTruth.Declaration customerTag() {\n"
            "        return declarationOf(CustomerTag.class);\n"
            "    }\n\n"
            "    /** 便捷入口：客户档案（首个载体）。 */",
            "FieldTruthRegistry")
    return sources


class TestFetchedLegRedProofs:
    """每条新判据的判别力（#5461）：注入 ⇒ **对应**的问题清单必须非空（不是「一起红」）。"""

    def test_new_fetched_leg_unregistered_is_red(self):
        """🔴 **本单的核心红证**：造一条现取式腿（新声明 + 注册 + 新产出点）⇒ **未登记即红**。

        前提自证（§23 G7）：产出层普查必须**真的看见**这条新腿（否则「判据没红」是注入没生效）。
        """
        sources = _injected_sources()
        seen = [(site["accessor"], site["source"])
                for site in fetched_leg_sites(sources) if site["file"] == CUSTOMER_SERVICE_REL]
        if ("customerTag", SOURCE_FETCHED) not in seen:
            raise AssertionError(f"注入未生效：产出层没看见新腿（读到的产出点：{seen}）")
        problems = problems_fetched_legs(load_registry(), sources)
        if not any("未登记" in problem and "customer_tags" in problem for problem in problems):
            raise AssertionError(f"新造一条现取式腿后判据未变红 ⇒ 空断言：{problems}")

    def test_registered_fetched_leg_stays_green(self):
        """反向对照：同一次注入 **+ 登记到位** ⇒ 不报（红可归因到「没登记」，且出口真可行动）。"""
        sources = _injected_sources()
        entries = dict(load_registry()["fetched_arrays"])
        entries[f"{CUSTOMER_SERVICE_REL}::customer_tags"] = {
            "accessor": "FieldTruthRegistry.customerTag()",
            "declaration": NEW_DECLARATION_REL,
            "criterion": [CRITERION],
            "reason": "夹具：新腿已登记 ⇒ 证明「未登记即红」给的出口真可行动",
            "issue": "#5461",
        }
        problems = problems_fetched_legs(_registry(fetched_arrays=entries), sources)
        if problems:
            raise AssertionError(f"登记到位后仍有判红 ⇒ 出口不可行动（红证不可归因）：{problems}")

    def test_stale_fetched_leg_entry_is_red(self):
        """⑩ 抹掉那条腿的产出点 ⇒ 台账条目**陈旧 ⇒ 红**（台账只许缩短）。"""
        sources = java_main_sources()
        sources[CUSTOMER_SERVICE_REL] = _mutate(
            sources[CUSTOMER_SERVICE_REL],
            '        snapshot.put("row_fields", Map.of(array, declaration.declaredFields()));',
            '        snapshot.put("row_fields", customerRowFields());', "CustomerService")
        problems = problems_fetched_legs(load_registry(), sources)
        if not any("陈旧条目" in problem and "customer_profiles" in problem for problem in problems):
            raise AssertionError(f"腿没了而台账条目还在 ⇒ 未红 ⇒ 空断言：{problems}")

    def test_declaration_table_mismatch_is_red(self):
        """⑪ 把声明的 `TABLE` 改成别的数组名 ⇒ 红（产出的数组身份必须现取自 `declaration.table()`）。"""
        sources = java_main_sources()
        sources[CUSTOMER_PROFILE_DECL_REL] = _mutate(
            sources[CUSTOMER_PROFILE_DECL_REL], 'TABLE = "customer_profiles"',
            'TABLE = "customer_profile_view"', "CustomerProfileFieldTruth")
        problems = problems_fetched_legs(load_registry(), sources)
        if not any("TABLE" in problem and "不一致" in problem for problem in problems):
            raise AssertionError(f"声明 TABLE 与产出的数组名不一致却未红 ⇒ 空断言：{problems}")

    def test_missing_criterion_is_red(self):
        """⑫ 把 `criterion` 换成不存在的测试名 ⇒ 红（拦死判据不许静默消失）。"""
        entries = dict(load_registry()["fetched_arrays"])
        key = sorted(entries)[0]
        entries[key] = {**entries[key], "criterion": [f"{CRITERION_REL}::no_such_test"]}
        problems = problems_fetched_legs(_registry(fetched_arrays=entries), java_main_sources())
        if not any("拦死判据已消失" in problem for problem in problems):
            raise AssertionError(f"criterion 指向不存在的测试却未红 ⇒ 空断言：{problems}")

    def test_unreadable_production_shape_is_red(self):
        """⑬ 产出表达式换成读不出来的形态 ⇒ 红（fail-closed：面外不许永久免检）。"""
        sources = java_main_sources()
        sources[CUSTOMER_SERVICE_REL] = _mutate(
            sources[CUSTOMER_SERVICE_REL],
            'snapshot.put("row_fields", Map.of(array, declaration.declaredFields()));',
            'snapshot.put("row_fields", rowFieldsFromCatalog());', "CustomerService")
        problems = problems_fetched_legs(load_registry(), sources)
        if not any("读不出来" in problem for problem in problems):
            raise AssertionError(f"读不出来的产出形态未红 ⇒ 面外又成了免检区：{problems}")

    def test_ledger_census_disagreement_is_red(self):
        """关系式判据的红证：台账清空（普查仍看得见腿）或普查失效（台账仍有条目）⇒ 必须判红。"""
        sites = fetched_leg_sites(java_main_sources())
        if not [site for site in sites if effective_kind(site) == SOURCE_FETCHED]:
            raise AssertionError("前提不成立：产出层看不见现取式腿 ⇒ 该红证无判别力（注入未生效）")
        if not problems_ledger_census_disagreement(_registry(fetched_arrays={}), sites):
            raise AssertionError("台账清空而普查仍看得见腿 ⇒ 两侧不一致却未判红（关系式是空判据）")
        if not problems_ledger_census_disagreement(load_registry(), []):
            raise AssertionError("普查失效（0 条产出点）而台账仍有条目 ⇒ 未判红（关系式是空判据）")

    def test_literal_and_fetched_legs_for_same_array_is_red(self):
        """⑭ 同一数组既有字面量腿又有现取式腿 ⇒ 红（两份投影必然分叉）。"""
        sources = java_main_sources()
        sources[CUSTOMER_SERVICE_REL] = _mutate(
            sources[CUSTOMER_SERVICE_REL],
            '        snapshot.put("row_fields", Map.of(array, declaration.declaredFields()));',
            '        snapshot.put("row_fields", Map.of(array, declaration.declaredFields()));\n'
            '        snapshot.put("row_fields", Map.of("customer_profiles", List.of("id")));',
            "CustomerService")
        problems = problems_fetched_legs(load_registry(), sources)
        if not any("同时有" in problem and "customer_profiles" in problem for problem in problems):
            raise AssertionError(f"同一数组两条腿（字面量 + 现取）却未红 ⇒ 空断言：{problems}")