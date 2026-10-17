# case_ids: PG-078, PG-079, PG-080
"""「作业单两型」的**跨端词表一致 + 接线**类级元守卫（issue #7079）。

## 病根（一类缺陷，不是一个缺陷）

issue #7079 把「单布料售卖」从加工单语义里拆出来：实体上位概念统一为**作业单**，用新列
`processing_orders.order_kind` 分两型（`processing` 加工 / `outbound` 出库），并让**卖布单**
的发货前置「裁剪 + 打包已报工」。这条改动横跨**四张面孔**，而它们**各自都不会因为对方漂移而变红**：

| # | 载体 | 漂移形态（全部静默） |
|---|---|---|
| ① | 迁移 + `db/init/schema.sql` | 取值约束改了而 Java/前端没跟 ⇒ 库里能落下一个谁都认不出的类型 |
| ② | `ProcessingOrderService.ORDER_KIND_*` | 常量改名/换值 ⇒ 生成侧写出的类型与前端读的判据对不上 |
| ③ | `frontend/admin-web/src/types/index.ts` 的 `order_kind` | 前端联合类型加/少一个值 ⇒ UI 把出库单当加工单渲染（或反之） |
| ④ | `OrderShipGuard` / `ProductionTodoService` 的**接线** | 守卫被改回「只判含加工项」⇒ **卖布单又能跳过裁剪/打包直接发货**，而这一条**没有任何东西会红** |

⇒ 本文件是**结构面**的类级守卫：让上面四类漂移**机械可判红**。
**行为面**（「真的拒了 / 真的放行了 / 真的进待办了」）由
`backend/admin-api/src/test/java/com/migao/admin/service/OrderShipGuardTest.java` 与
`ProductionTodoServiceTest.java` 承担 —— 本文件**不**跑它们（§28.2 的分工口径）。

## 判据（每条都会红，且具名）

| # | 判据 | 会怎么红 |
|---|---|---|
| C1 | 后端两个常量 `ORDER_KIND_PROCESSING` / `ORDER_KIND_OUTBOUND` 的**字面量集合**逐值等于冻结词表 | 改名 / 换值 / 少一个 ⇒ 具名报出实际取到的集合 |
| C2 | 迁移里含 `order_kind` 的语句：字面量集合 == 冻结词表，且带 `DEFAULT 'processing'` | 写成 `'outbound'` 默认 / 少一个取值 ⇒ 红 |
| C3 | `db/init/schema.sql`（bootstrap **唯一**建库脚本）里 `order_kind` 那一行带 `DEFAULT 'processing'` | 只改迁移忘了同步 ⇒ 新建库缺列/缺默认 ⇒ 红 |
| C4 | 前端 `order_kind` 联合类型的成员（去掉 `null`）逐值等于冻结词表 | 前端加/少一个值 ⇒ 红 |
| C5 | **词表逐项冻结**：`{processing, outbound}` + 默认 `processing` 写死在本文件 —— 集合级相等对「两边一起错」没有判别力 | 两边一起改成别的词 ⇒ 红 |
| C6 | **接线**：`OrderShipGuard.isProcessingReadyForShip` 必须经由 `needsWork`；`needsWork` 必须同时含 `hasProcessingItems` 与 `hasFabricSaleLine` | 改回只判含加工项 ⇒ 红（具名报出该方法体里找不到 `needsWork`） |
| C7 | **接线纵深（只判过滤点）**：`ProductionTodoService` 里**每个 `for` 循环体**的 `if` 条件都不得出现 `hasProcessingItems(`，且必须有 `for` 循环体引用 `needsWork` | 某一类待办退回旧过滤判据 ⇒ 红。**射程就是「决定某条候选订单是否进待办」的那个决策点** —— `hasProcessingItems(...)` 出现在**证据/文案**里是合法事实（它说的是「这单有没有加工项」），不算第二份判据 |
| C8 | **判别力自证（反恒真）**：上面每个读取器/判定器对**注入的坏形态**各自判红、对好形态不报 | 守卫退化成恒真（读不到东西还给空集通过）⇒ 红 |
| C9 | **反空跑**：任一面「找不到对象」⇒ 红（不许以「没有可比对的东西」为通过） | 删掉整个迁移/常量/类型 ⇒ 红 |

## 边界（照实登记，§19.1）

- 射程 = 上面点名的**五个文件**（迁移目录里含 `order_kind` 的那一份 + `db/init/schema.sql` +
  `ProcessingOrderService.java` + `OrderShipGuard.java` + `ProductionTodoService.java` +
  `frontend/admin-web/src/types/index.ts`）。
- C6 / C7 是**源码文本级**判定（剥注释后按方法体查找）—— 它判不了「那段接线真的跑在真入口上」
  （那由 Java 行为判据承担，见文件头）。**不得**把本文件的绿读成「行为已验证」。
- `order_kind` 的 JSON 键名/读面登记面**不在本文件**：它由
  `tests/unit_ci_workflows/test_read_face_json_key_guard.py` 的台账
  （`read_face_json_key_ledger.json`）承担 —— 两处**不互为副本、也互不重判**。
- 前端**可见面文案**（「作业单」/「加工单」/「出库作业单」的中文标签、机器键不上屏）不在本文件：
  由 `frontend/admin-web/tests/unit/**` 的页面判据 + 既有「JSX 机器键」元守卫承担。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests"))

from unit_ci_workflows._source_parsing import java_code  # noqa: E402
from unit_ci_workflows._sql_schema import strip_sql_comments  # noqa: E402

# ══════════════════════════════════════════════════════════════════════════════
# 冻结词表（C5：集合级相等挡不住「两边一起错」，故在此逐项写死）
# ══════════════════════════════════════════════════════════════════════════════
FROZEN_KINDS = frozenset({"processing", "outbound"})
FROZEN_DEFAULT_KIND = "processing"

MIGRATION_DIR = REPO_ROOT / "backend/admin-api/src/main/resources/db/migration"
INIT_SCRIPT = REPO_ROOT / "backend/admin-api/src/main/resources/db/init/schema.sql"
SERVICE = (
    REPO_ROOT
    / "backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java"
)
SHIP_GUARD = (
    REPO_ROOT / "backend/admin-api/src/main/java/com/migao/admin/service/OrderShipGuard.java"
)
TODO_SERVICE = (
    REPO_ROOT
    / "backend/admin-api/src/main/java/com/migao/admin/service/ProductionTodoService.java"
)
FRONTEND_TYPES = REPO_ROOT / "frontend/admin-web/src/types/index.ts"

COLUMN = "order_kind"
#: 迁移里的取值约束可能写成列内联或独立 `ADD CONSTRAINT` ⇒ 按「含列名的**语句**」取并集
_STATEMENT_SPLIT = re.compile(r";")
#: Java 常量声明（`String ORDER_KIND_X = "…"`；`id` = `public static final` 可有可无）
_JAVA_KIND_CONST = re.compile(r'String\s+(ORDER_KIND_[A-Z0-9_]+)\s*=\s*"([^"]*)"')
#: 前端属性声明（`order_kind?: 'processing' | 'outbound' | null`）
_TS_KIND_DECL = re.compile(rf"{COLUMN}\s*\??\s*:\s*([^\n]+)")
_TS_STRING_MEMBER = re.compile(r"""['"]([^'"]*)['"]""")
#: 剥注释后仍要能在源码里找到的方法名（接线判据 C6 / C7）
_NEEDS_WORK = "needsWork"
_HAS_FABRIC_SALE_LINE = "hasFabricSaleLine"
_HAS_PROCESSING_ITEMS = "hasProcessingItems"
#: `for (...)` 循环的头部（C7 用它把射程收在**过滤点**上）
_FOR_LOOP = re.compile(r"for\s*\([^)]*\)\s*\{")
#: `if (...)` 的**条件文本**（嵌套括号只取到第一个 `)` —— 足够判定「这个条件里引用了哪个谓词」）
_IF_CONDITION = re.compile(r"if\s*\(([^)]*)\)")


def _read(path: Path) -> str:
    assert path.is_file(), (
        f"{path.relative_to(REPO_ROOT).as_posix()} 不存在 ⇒ 判据失去对象"
        "（本判据随 issue #7079 的对象同步，删对象必须同步删本判据）"
    )
    return path.read_text(encoding="utf-8")


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


# ══════════════════════════════════════════════════════════════════════════════
# 读取器（每个都对「取不到」判红，不静默给空集 —— 判据 C9 反空跑）
# ══════════════════════════════════════════════════════════════════════════════


def java_kind_constants(code: str) -> dict[str, str]:
    """`{常量名: 字面量}` —— 取不到任何一条 ⇒ 抛断言（不静默给空 dict）。"""
    found = dict(_JAVA_KIND_CONST.findall(code))
    assert found, (
        f"{_rel(SERVICE)} 里取不到 `String ORDER_KIND_* = \"…\"` 形态的常量声明 ⇒ "
        "作业单类型词表被改名/换形 ⇒ 本判据无法比对（不许静默通过）"
    )
    return found


def kinds_in_order_kind_statements(sql: str) -> tuple[set[str], bool]:
    """迁移/建库脚本里**含 `order_kind` 的语句**中的单引号字面量集合 + 是否带默认值。

    返回 `(字面量集合, 是否含 DEFAULT 'processing')`。语句里一个字面量都没有 ⇒ 返回空集，
    由调用方判红（C2 反空跑）。

    🔴 **先剥 SQL 注释再取值**（顺序不许反）：本单的 V159 迁移头部有大量注释**逐字写着**
    `'processing'` / `'outbound'`（那是说明口径的散文）—— 按原文扫引号会把注释喂成取值，
    「注释里提了某值」就会被读成「约束里真有这个值」。剥注释用仓内**唯一**那份实现
    `_sql_schema.strip_sql_comments`（不另写一份）。判据 = tests/unit_ci_workflows/test_guard_parsing_is_comment_aware.py。
    """
    sql = strip_sql_comments(sql)
    hit = False
    literals: set[str] = set()
    has_default = False
    for raw in _STATEMENT_SPLIT.split(sql):
        if COLUMN not in raw:
            continue
        hit = True
        # 取值集合：先按**结构定界符**取 `order_kind IN ( … )` 的整块（捕获组按右括号定界），
        # 再逐项剥掉包裹的单引号 —— **不写「引号定界捕获组」**那种按原文扫引号的形态
        # （判据 = tests/unit_ci_workflows/test_guard_parsing_is_comment_aware.py 的 RULE_QUOTE：
        #  注释/字符串能喂中 `re.findall(r"'([^']*)'", raw)` 这类写法）。
        for block in re.findall(rf"{COLUMN}\s+IN\s*\(([^)]*)\)", raw, re.I):
            for item in block.split(","):
                item = item.strip()
                if len(item) >= 2 and item.startswith("'") and item.endswith("'"):
                    literals.add(item[1:-1])
        if re.search(rf"DEFAULT\s+'{re.escape(FROZEN_DEFAULT_KIND)}'", raw):
            has_default = True
    assert hit, (
        f"在迁移/{COLUMN} 相关 SQL 里找不到任何含 `{COLUMN}` 的语句 ⇒ "
        "列不存在（或换名）⇒ 本判据无法比对（不许静默通过）"
    )
    return literals, has_default


def migration_order_kind_sql() -> str:
    """迁移目录里**含 `order_kind` 的迁移文件**正文（可能多份 ⇒ 拼接，逐份都验）。"""
    texts = [
        p.read_text(encoding="utf-8")
        for p in sorted(MIGRATION_DIR.glob("*.sql"))
        if COLUMN in p.read_text(encoding="utf-8")
    ]
    assert texts, (
        f"{MIGRATION_DIR.relative_to(REPO_ROOT).as_posix()} 里没有任何含 `{COLUMN}` 的迁移 ⇒ "
        "新列没有落库路径（bootstrap 之外的库拿不到这列）"
    )
    return "\n".join(texts)


def frontend_kind_members(code: str) -> set[str]:
    """前端 `order_kind` 联合类型的成员（**去掉 `null`**）。

    TS 不能被 `ast` 解析 ⇒ 先剥注释（`java_code`，引号感知）再取字面量成员。
    找不到声明 / 取不到成员 ⇒ 抛断言（不静默给空集）。
    """
    matched = _TS_KIND_DECL.search(code)
    members = set(_TS_STRING_MEMBER.findall(matched.group(1) if matched else ""))
    assert members, (
        f"{_rel(FRONTEND_TYPES)} 里取不到 `{COLUMN}` 的联合类型声明 ⇒ "
        "前端作业单类型被改名/退回裸 string ⇒ 本判据无法比对（不许静默通过）"
    )
    return {m for m in members if m not in {"null", "undefined"}}


def java_method_body(code: str, name: str) -> str:
    """按**花括号配平**取 `name(...)` 的方法体（含签名行）。

    取不到 ⇒ 返回 `""`（由调用方判红；不静默当成「已满足」）。
    """
    head = re.search(rf"\b{re.escape(name)}\s*\(", code)
    if not head:
        return ""
    open_brace = code.find("{", head.end())
    if open_brace < 0:
        return ""
    depth = 0
    for idx in range(open_brace, len(code)):
        ch = code[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return code[head.start() : idx + 1]
    return ""


def if_conditions(code: str) -> list[str]:
    """源码里每个 `if (...)` 的**条件文本**（剥注释后）。"""
    return _IF_CONDITION.findall(code)


def for_loop_bodies(code: str) -> list[str]:
    """源码里每个 `for (...)` 循环的**循环体**（花括号配平，含头含尾）。

    C7 的射程就是这些循环体 —— 待办的候选扫描按 `for` 循环写，「某条候选订单是否进待办」
    的决策点必然落在循环体里的 `if` 条件上。
    """
    out: list[str] = []
    for matched in _FOR_LOOP.finditer(code):
        start = matched.end() - 1
        depth = 0
        for idx in range(start, len(code)):
            if code[idx] == "{":
                depth += 1
            elif code[idx] == "}":
                depth -= 1
                if depth == 0:
                    out.append(code[start : idx + 1])
                    break
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 判定器（纯函数；C8 判别力自证对同一份函数注入坏形态）
# ══════════════════════════════════════════════════════════════════════════════


def judge_java_constants(code: str) -> str:
    """C1 ⇒ 返回 `""` 表示通过，否则返回具名失败理由。"""
    constants = java_kind_constants(code)
    values = set(constants.values())
    if values != FROZEN_KINDS:
        return (
            f"{_rel(SERVICE)} 的 ORDER_KIND_* 常量取值集合为 {sorted(values)}，"
            f"冻结词表要求 {sorted(FROZEN_KINDS)}（常量名：{sorted(constants)}）"
        )
    if constants.get("ORDER_KIND_PROCESSING") != "processing":
        return (
            f"{_rel(SERVICE)} 的 ORDER_KIND_PROCESSING = "
            f"{constants.get('ORDER_KIND_PROCESSING')!r}，应为 'processing'"
        )
    if constants.get("ORDER_KIND_OUTBOUND") != "outbound":
        return (
            f"{_rel(SERVICE)} 的 ORDER_KIND_OUTBOUND = "
            f"{constants.get('ORDER_KIND_OUTBOUND')!r}，应为 'outbound'"
        )
    return ""


def judge_migration(sql: str) -> str:
    """C2 ⇒ 通过返回 `""`。"""
    literals, has_default = kinds_in_order_kind_statements(sql)
    missing = FROZEN_KINDS - literals
    if missing:
        return f"迁移里含 `{COLUMN}` 的语句缺少取值 {sorted(missing)}（实际字面量 {sorted(literals)}）"
    if not has_default:
        return f"迁移里含 `{COLUMN}` 的语句没有 `DEFAULT '{FROZEN_DEFAULT_KIND}'`"
    return ""


def judge_init_script(sql: str) -> str:
    """C3 ⇒ 通过返回 `""`。"""
    lines = [ln for ln in sql.splitlines() if COLUMN in ln]
    assert lines, (
        f"{_rel(INIT_SCRIPT)}（bootstrap 唯一建库脚本）里没有 `{COLUMN}` ⇒ 新建库缺列"
    )
    if not any(re.search(rf"DEFAULT\s+'{re.escape(FROZEN_DEFAULT_KIND)}'", ln) for ln in lines):
        return (
            f"{_rel(INIT_SCRIPT)} 的 `{COLUMN}` 行缺 "
            f"`DEFAULT '{FROZEN_DEFAULT_KIND}'`（逐行读数：{lines}）"
        )
    return ""


def judge_frontend(members: set[str]) -> str:
    """C4 ⇒ 通过返回 `""`。"""
    if members != set(FROZEN_KINDS):
        return (
            f"{_rel(FRONTEND_TYPES)} 的 `{COLUMN}` 成员为 {sorted(members)}，"
            f"后端冻结词表为 {sorted(FROZEN_KINDS)}"
        )
    return ""


def judge_ship_guard(code: str) -> str:
    """C6 ⇒ 通过返回 `""`。"""
    ready = java_method_body(code, "isProcessingReadyForShip")
    if not ready:
        return f"{_rel(SHIP_GUARD)} 里找不到 `isProcessingReadyForShip(...)` 方法体"
    if f"{_NEEDS_WORK}(" not in ready:
        return (
            f"{_rel(SHIP_GUARD)} 的 `isProcessingReadyForShip` 没有经由 `{_NEEDS_WORK}(...)` "
            "⇒ 发货前置判据被改回「只判含加工项」⇒ 卖布单又能跳过裁剪/打包直接发货"
        )
    needs = java_method_body(code, _NEEDS_WORK)
    if not needs:
        return f"{_rel(SHIP_GUARD)} 里找不到 `{_NEEDS_WORK}(...)` 方法体"
    for required in (_HAS_PROCESSING_ITEMS, _HAS_FABRIC_SALE_LINE):
        if f"{required}(" not in needs:
            return f"{_rel(SHIP_GUARD)} 的 `{_NEEDS_WORK}` 里没有 `{required}(...)`"
    return ""


def judge_todo_service(code: str) -> str:
    """C7 ⇒ 通过返回 `""`。

    射程 = **过滤点**（`for` 循环体里的 `if` 条件），不是整文件 ——
    `hasProcessingItems(...)` 出现在**证据/文案**里是合法事实（「这单有没有加工项」正是待办要说清的事），
    只有把它**当过滤判据**用才是「第二份判据」。
    """
    loops = for_loop_bodies(code)
    if not loops:
        return (
            f"{_rel(TODO_SERVICE)} 里找不到任何 `for` 循环 ⇒ 判据失去对象"
            "（待办的候选扫描按 `for` 循环写；换形即红，不许静默通过）"
        )
    if not any(f"{_NEEDS_WORK}(" in body for body in loops):
        return (
            f"{_rel(TODO_SERVICE)} 没有任何 `for` 循环体引用 `{_NEEDS_WORK}(...)` ⇒ "
            "生产待办没有改用统一判据（卖布单进不了待排产/待发货）"
        )
    bad = [
        cond
        for body in loops
        for cond in if_conditions(body)
        if f"{_HAS_PROCESSING_ITEMS}(" in cond
    ]
    if bad:
        return (
            f"{_rel(TODO_SERVICE)} 的 `for` 循环 `if` 条件里仍出现 `{_HAS_PROCESSING_ITEMS}(...)` ⇒ "
            f"存在第二份过滤判据（{bad[:2]}）"
        )
    return ""


# ══════════════════════════════════════════════════════════════════════════════
# C1~C7 —— 对**真文件**的判定
# ══════════════════════════════════════════════════════════════════════════════


def test_backend_kind_constants_are_frozen_vocabulary():
    """C1：后端 `ORDER_KIND_*` 常量 == 冻结词表。"""
    reason = judge_java_constants(java_code(_read(SERVICE)))
    assert reason == "", reason


def test_migration_kind_vocabulary_and_default():
    """C2：迁移里 `order_kind` 的取值集合 + 默认值。"""
    reason = judge_migration(migration_order_kind_sql())
    assert reason == "", reason


def test_bootstrap_init_script_has_kind_column_with_default():
    """C3：bootstrap 建库脚本（**唯一**一份）同步了新列与默认值。"""
    reason = judge_init_script(_read(INIT_SCRIPT))
    assert reason == "", reason


def test_frontend_kind_members_match_backend():
    """C4：前端联合类型成员 ⇄ 后端词表**逐值相等**（不是包含）。"""
    reason = judge_frontend(frontend_kind_members(java_code(_read(FRONTEND_TYPES))))
    assert reason == "", reason


def test_ship_guard_wired_through_needs_work():
    """C6：发货前置判据必须经由 `needsWork`（含卖布行），不许退回只判含加工项。"""
    reason = judge_ship_guard(java_code(_read(SHIP_GUARD)))
    assert reason == "", reason


def test_todo_service_has_single_judgement():
    """C7：生产待办只剩 `needsWork`，不得存在第二份判据。"""
    reason = judge_todo_service(java_code(_read(TODO_SERVICE)))
    assert reason == "", reason


# ══════════════════════════════════════════════════════════════════════════════
# C8 —— 判别力自证（**反恒真**）：同一份判定器对坏形态必须判红
# ══════════════════════════════════════════════════════════════════════════════

_JAVA_GOOD = """
    public static final String ORDER_KIND_PROCESSING = "processing";
    public static final String ORDER_KIND_OUTBOUND = "outbound";
"""

#: 迁移的**两种合法写法都要认**：列内联 CHECK，或「加列 + 独立 ADD CONSTRAINT」两条语句
#: （两条语句都含列名 ⇒ `kinds_in_order_kind_statements` 取并集）
_SQL_GOOD = (
    "ALTER TABLE processing_orders ADD COLUMN IF NOT EXISTS order_kind "
    "VARCHAR(16) NOT NULL DEFAULT 'processing';"
    "ALTER TABLE processing_orders ADD CONSTRAINT processing_orders_order_kind_check "
    "CHECK (order_kind IN ('processing', 'outbound'));"
)

_INIT_GOOD = "    order_kind VARCHAR(16) NOT NULL DEFAULT 'processing',"

_TS_GOOD = "  order_kind?: 'processing' | 'outbound' | null\n"

_SHIP_GOOD = """
    public static boolean isProcessingReadyForShip(X x) {
        return !needsWork(x) || completed > 0;
    }
    public static boolean needsWork(X x) {
        return hasProcessingItems(x) || hasFabricSaleLine(x);
    }
"""

_TODO_GOOD = """
    for (Order order : shipCandidates) {
        if (orderService.needsWork(order) && orderService.isProcessingReadyForShip(order)) {
            todos.add(toShipTodo(order));
        }
    }
    for (Order order : scheduleCandidates) {
        if (instanceCountByOrder.getOrDefault(order.getId(), 0) > 0) { continue; }
        if (!orderService.needsWork(order)) { continue; }
        todos.add(toScheduleTodo(order));
    }
    private Map<String, Object> toShipTodo(Order order) {
        evidence.put("has_processing_items", orderService.hasProcessingItems(order));
    }
"""


def test_discriminating_power_good_forms_pass():
    """C8-a：好形态**不报**（否则守卫是在瞎报，会被当成噪音摘掉）。"""
    assert judge_java_constants(_JAVA_GOOD) == ""
    assert judge_migration(_SQL_GOOD) == ""
    assert judge_init_script(_INIT_GOOD) == ""
    assert judge_frontend(frontend_kind_members(_TS_GOOD)) == ""
    assert judge_ship_guard(_SHIP_GOOD) == ""
    assert judge_todo_service(_TODO_GOOD) == ""


def test_discriminating_power_bad_forms_are_named():
    """C8-b：坏形态**各自具名判红**（含「两边一起错」与「接线退回」两种最隐蔽的形态）。"""
    # ① 常量少一个
    assert judge_java_constants('String ORDER_KIND_PROCESSING = "processing";') != ""
    # ② 两边一起改成同一个错词（集合级相等挡不住 ⇒ 由 FROZEN_KINDS 挡）
    assert judge_java_constants(
        'String ORDER_KIND_PROCESSING = "make"; String ORDER_KIND_OUTBOUND = "ship";'
    ) != ""
    assert judge_frontend(frontend_kind_members("order_kind?: 'make' | 'ship'")) != ""
    # ③ 迁移缺默认值
    assert judge_migration(
        "ALTER TABLE processing_orders ADD COLUMN IF NOT EXISTS order_kind VARCHAR(16) "
        "NOT NULL CHECK (order_kind IN ('processing','outbound'));"
    ) != ""
    # ④ bootstrap 忘了同步
    assert judge_init_script("    order_kind VARCHAR(16) NOT NULL,") != ""
    # ⑤ 接线退回「只判含加工项」（本单要防的**头号**回退形态）
    assert (
        judge_ship_guard(
            "boolean isProcessingReadyForShip(X x) { return !hasProcessingItems(x) || done > 0; }"
        )
        != ""
    )
    # ⑥ needsWork 丢了一半判据
    assert (
        judge_ship_guard(
            "boolean isProcessingReadyForShip(X x) { return !needsWork(x); }"
            "boolean needsWork(X x) { return hasProcessingItems(x); }"
        )
        != ""
    )
    # ⑦ 待办里残留第二份**过滤**判据（射程 = for 循环里的 if 条件）
    assert (
        judge_todo_service(
            "for (Order o : xs) { if (orderService.needsWork(o)) { todos.add(a); } }"
            "for (Order o : ys) { if (orderService.hasProcessingItems(o)) { todos.add(b); } }"
        )
        != ""
    )
    # ⑦b 反空跑：一个 for 循环都没有 ⇒ 判据失去对象（不许静默通过）
    assert judge_todo_service("public class X { }") != ""


def test_readers_fail_closed_on_missing_objects():
    """C9：任一面「找不到对象」⇒ 抛断言，**不许**以「没有可比对的东西」为通过。"""
    import pytest

    with pytest.raises(AssertionError):
        java_kind_constants("public class X { }")
    with pytest.raises(AssertionError):
        kinds_in_order_kind_statements("ALTER TABLE orders ADD COLUMN foo INT;")
    with pytest.raises(AssertionError):
        frontend_kind_members("export interface X { id: string }")
    with pytest.raises(AssertionError):
        judge_init_script("CREATE TABLE processing_orders (id VARCHAR(64));")
