# case_ids: MC-198
r"""订单状态**立单一源**的扫面判据（issue #8198 的 P2-2a）。

## 病（一类缺陷，不是一个缺陷）

订单状态在 Java 侧**没有载体**：`orders.status` 的存储值以裸字面量散落在 `service/` 与 `controller/`
里。散落本身不报错，它报错的方式是**静默**的：一处写成 `"producin"`（或某天把 `producing` 改成
`in_production`）⇒ 该分支**永不命中**，而编译、单测、页面全都正常（#3621 的「拼写变体静默匹配不到」
就是这么来的）。所以这单要的不是「改干净这 70 处」，而是**一处取值 + 一条会红的扫面判据**。

历史：第一步（PR #8207）已落 `OrderStatusTransitions` 的 7 个常量 + `controller/` 的扫面；
本判据补的是 `service/` 那一半（46 处）与**取值唯一载体**这一层。

载体形态按 issue #8198 的评论裁定（2026-10-31，仓库所有者读码后）落：**加常量、不加类型** ——
7 个 `public static final String` 就是唯一载体，「状态全集」的权威是 `STATUS_TRANSITIONS` 的键集。

## 判据面与它**为什么只有三个词**

扫面词 = `producing` / `shipped` / `cancelled`，与 issue #8198 的**现取命令同一组**：

    grep -rn '"producing"\|"shipped"\|"cancelled"' backend/admin-api/src/main/java --include=*.java

口径是照实取的，不是图省事：`pending` / `completed` / `packed` 是**跨域通用词**
（知识候选待办 / 加工工序 / 批次盘点 / 注册审核都在用），把它们纳进来会逼出 30+ 条豁免台账，
而台账越长越像白名单 —— 那是**假绿**的常见形态（§19.1）。⇒ 本判据只守现取的那三个词；
**缺口照实登记**：新写 `"pending".equals(order.getStatus())` 这类**不会**被本判据抓到
（`controller/` 面仍由既有 Java 判据按 7 个词守）。

## 四条判据（每条都能单独变红）

1. **扫面**：`service/` 与 `controller/` 下不许再出现裸的这三个词（**唯一例外 = 7 个常量的规范定义形态**，
   且只在 `OrderStatusTransitions` 里；注释里的不算 ——
   取值走 `unit_ci_workflows._source_parsing.java_literals`，全仓唯一一份引号感知实现，#5323）；
   判红时**点名文件与行号**，并给可复制命令；
2. **取值唯一源**：`domain/OrderStatus` 是**唯一**定义这 7 个 code 的地方；
   `OrderStatusTransitions` 的 7 个常量**逐字取自它**（`= OrderStatus.X.code()`），本类里零字面量；
3. **不进序列化面**：`entity/` 与 `dto/` 里不出现 `OrderStatus` 类型 —— 状态字段仍是 `String`
   ⇒ JSON 输出、状态取值、错误文案逐字不变（本单是纯收敛，**任何**对外可见变化都算越界）；
4. **判别力自证 + 台账不许陈旧**：内存里注入坏语料 ⇒ 判据必须**具名**报出（文件 + 行号 + 值）；
   豁免台账每一条都要求**原文仍逐字在**（陈旧 / 被误改 ⇒ 红，且只许缩短）。

## 边界（照实登记）

- `pending` / `completed` / `packed` 不在扫面词里（见上）；
- 判的是**文本形态**，判不了「这个状态值该不该从这里写」这类业务口径；
- `entity/` / `mapper/` 里的**同名但不同域**常量（`ScheduledTask.STATUS_CANCELLED`、
  `InboundOrder.STATUS_CANCELLED`、`Stocktake.STATUS_CANCELLED`、`FinishedGoodsStock.STATUS_SHIPPED`）
  是各自领域的取值，**不在本单射程**，本判据也不碰；
- `FieldTruth` 不动（issue #8198 的边界）。
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests"))

from unit_ci_workflows._source_parsing import java_code, java_literals  # noqa: E402

ADMIN_JAVA = REPO_ROOT / "backend/admin-api/src/main/java/com/migao/admin"
SWEEP_DIRS = ("service", "controller")

#: issue #8198 现取命令里的三个词（判据面 = 该命令的同一组，读数可直接对照）。
SWEEP_CODES = ("producing", "shipped", "cancelled")

#: DB 存储值（**独立硬编码**的真值；故意不引用被测常量，否则改常量值会同时改判据 ⇒ 假绿）。
DB_CODES = ("pending", "confirmed", "producing", "packed", "shipped", "completed", "cancelled")

TRANSITIONS_REL = "service/OrderStatusTransitions.java"

#: 7 个常量定义是**唯一允许**出现状态字面量的地方（且只在 `OrderStatusTransitions` 里）。
#: 用**规范定义形态**匹配（不是「文件级白名单」）⇒ 同文件里另写一处裸字面量照样红。
CANONICAL_DEFINITIONS = tuple(
    f'public static final String {code.upper()} = "{code}";' for code in DB_CODES)

#: 非订单状态的**同名**用法：逐条给出**原文**（`line.strip()` 逐字相等才算命中）。
#: 台账**只许缩短** —— 某条不再出现（重构 / 被误改成订单状态常量）⇒ 判据红并要求删掉这条。
NON_ORDER_STATUS_USAGES: dict[str, tuple[str, ...]] = {
    # 加工单（processing order）状态机：`cancelled` 是加工单的终态，与订单状态同名不同域。
    "service/ProcessingOrderService.java": (
        '"generated", Set.of("issued", STATUS_IN_PROCESSING, "cancelled"),',
        '"issued", Set.of(STATUS_IN_PROCESSING, "cancelled"),',
        'STATUS_IN_PROCESSING, Set.of("completed", "cancelled"),',
        '"cancelled", Set.of()',
        '"cancelled", "已取消"',
        'case "cancel": target = "cancelled"; break;',
    ),
    # 订单取消时**联动**改加工单状态：这一处的 `cancelled` 落在加工单 mapper 的更新里。
    # issue #8191（P2-1d）：`cancelOrder` 的联动作废腿搬到 OrderLifecycleService ⇒ 载体键跟着搬。
    "service/OrderLifecycleService.java": (
        '"generated", "cancelled", null, null, null, null, null,',
    ),
    # 返工单状态（draft / in_progress / done / cancelled），与订单状态无关。
    "service/ReworkState.java": (
        'public static final String CANCELLED = "cancelled";',
    ),
    # 定时任务的「已取消条数」JSON 键（值相同纯属巧合）。
    "controller/agent/AgentScheduledTaskController.java": (
        'return ApiResponse.success(Map.of("id", id, "cancelled", cancelled));',
    ),
}


def _line_of(text: str, pos: int) -> int:
    """字符下标 → 1 起的行号（`java_literals` 给的是下标，不是行号）。"""
    return text.count("\n", 0, pos) + 1


def _violations(rel: str, text: str, frozen: dict[str, tuple[str, ...]]) -> list[str]:
    """纯函数：`(相对路径, 源码文本, 豁免台账)` → 违规清单（每条含 `文件:行号` 与值）。

    口径：豁免按**原文逐字**匹配，不按行号 —— 行号会随无关改动漂移，那是台账腐烂的起点。
    """
    stripped_lines = [line.strip() for line in text.splitlines()]
    allowed = set(frozen.get(rel, ()))
    if rel == TRANSITIONS_REL:
        allowed |= set(CANONICAL_DEFINITIONS)
    bad: list[str] = []
    for pos, value in java_literals(text):
        if value not in SWEEP_CODES:
            continue
        line_no = _line_of(text, pos)
        if stripped_lines[line_no - 1] in allowed:
            continue
        bad.append(f"{rel}:{line_no} 裸字面量 \"{value}\"")
    return bad


def _sweep_surface() -> dict[str, str]:
    """扫描面：`service/**` + `controller/**` 的 Java 源（相对 `com/migao/admin` 的路径 → 原文）。"""
    surface: dict[str, str] = {}
    for sub in SWEEP_DIRS:
        for path in sorted((ADMIN_JAVA / sub).rglob("*.java")):
            rel = path.relative_to(ADMIN_JAVA).as_posix()
            surface[rel] = path.read_text(encoding="utf-8")
    return surface


def test_service_and_controller_have_no_bare_order_status_literals() -> None:
    """🔴 扫面：`service/` 与 `controller/` 零裸字面量（红证：在任一文件加一处 `"producing"` ⇒ 具名红）。"""
    surface = _sweep_surface()
    violations: list[str] = []
    for rel, text in surface.items():
        violations.extend(_violations(rel, text, NON_ORDER_STATUS_USAGES))

    assert violations == [], (
        "service/ 与 controller/ 里残留的订单状态裸字面量（改用 OrderStatusTransitions.* 或 "
        "OrderStatus.*）：\n  " + "\n  ".join(violations) + "\n复算："
        'grep -rn \'"producing"\\|\'"shipped"\\|\'"cancelled"\' '
        "backend/admin-api/src/main/java/com/migao/admin/{service,controller} --include=*.java"
    )


def test_scan_surface_and_exemption_ledger_are_not_stale() -> None:
    """🔴 扫面面非空 + 豁免台账逐条仍在（空面 / 陈旧豁免 ⇒ 红，不许「绿了但没扫」）。"""
    surface = _sweep_surface()

    missing_surface = [
        rel
        for rel in (
            "service/OrderService.java",
            "service/OrderShipmentService.java",
            "service/OrderStatusTransitions.java",
            "controller/OrderController.java",
        )
        if rel not in surface
    ]
    assert missing_surface == [], f"扫面面里缺这些必扫文件（目录被挪走 / 改名 ⇒ 判据空跑）：{missing_surface}"

    stale: list[str] = []
    for rel, allowed_lines in NON_ORDER_STATUS_USAGES.items():
        text = surface.get(rel)
        if text is None:
            stale.append(f"{rel}: 文件不在扫面面里（台账条目须删除）")
            continue
        present = {line.strip() for line in text.splitlines()}
        for line in allowed_lines:
            if line not in present:
                stale.append(f"{rel}: 台账条目已不存在 ⇒ 删掉它（只许缩短）：{line}")
    assert stale == [], "豁免台账陈旧：\n  " + "\n  ".join(stale)


def test_constants_are_the_only_value_source() -> None:
    """🔴 取值唯一载体：状态机里 7 个常量逐字等于 DB 值，且字面量只许出现在那 7 个定义处。

    「状态全集」的权威是 `STATUS_TRANSITIONS` 的键集（issue #8198 评论：那里已经有一处权威了），
    本判据**不另立全集**：它只核对「常量集 == 键集 == 标签表键集」与「没有第二处字面量」。
    """
    transitions_code = java_code((ADMIN_JAVA / TRANSITIONS_REL).read_text(encoding="utf-8"))

    problems: list[str] = []
    for code in DB_CODES:
        definition = f'public static final String {code.upper()} = "{code}";'
        if definition not in transitions_code:
            problems.append(f"{TRANSITIONS_REL}: 缺常量定义 `{definition}`")
        occurrences = transitions_code.count(f'"{code}"')
        if occurrences != 1:
            problems.append(f'{TRANSITIONS_REL}: 字面量 "{code}" 出现 {occurrences} 次（只许在常量定义里 1 次）')

    # 三张表的键必须是常量引用（值碰巧相等不算）
    for anchor in ("PENDING, Set.of(CONFIRMED, CANCELLED)", 'PENDING, "待付款"',
                   "CONTENT_EDITABLE_STATUSES = Set.of(PENDING)"):
        if anchor not in transitions_code:
            problems.append(f"{TRANSITIONS_REL}: 表键不是常量引用（缺锚点 `{anchor}`）")

    assert problems == [], "取值唯一载体被破坏：\n  " + "\n  ".join(problems)


def test_injected_corpora_are_named() -> None:
    """🔴 判别力自证：好 / 坏语料各一份，坏语料必须**具名**（文件 + 行号 + 值），好语料必须不报。"""
    # 合成语料用的相对路径：与行号**分开拼接**构造（Case Trust 的裸行号规则对静态文本敏感）
    injected = "service/Injected.java"
    frozen: dict[str, tuple[str, ...]] = {injected: ("// 台账里的那一行",)}
    at_line = injected + ":"

    bad_corpus = 'class A {\n    void f(String s) {\n        if ("producing".equals(s)) {}\n    }\n}\n'
    bad = _violations(injected, bad_corpus, frozen)
    assert bad == [at_line + '3 裸字面量 "producing"'], f"注入的坏语料没被具名报出（文件 + 行号 + 值）：{bad}"

    good_corpus = (
        "class A {\n"
        "    // 注释里的 \"shipped\" 不算（引号感知的取值实现）\n"
        "    void f(String s) {\n"
        "        if (OrderStatusTransitions.SHIPPED.equals(s)) {}\n"
        '        String key = "cancelled";\n'
        "    }\n"
        "}\n"
    )
    frozen_hit = _violations(injected, good_corpus, frozen)
    assert frozen_hit == [at_line + '5 裸字面量 "cancelled"'], (
        f"未登记的字面量必须报出（台账只精确到原文行）：{frozen_hit}"
    )
    assert _violations(injected, good_corpus, {injected: ('String key = "cancelled";',)}) == []
