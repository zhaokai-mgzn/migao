# case_ids: CU-010
"""具名跨域视图 `customer_profile`（客户画像）—— 视图语义测试（issue #5456，族 3 · 包 3）

判据来源：issue #5456 的六条（逐字段三态 / 无真值字段不得以真值形态出现 / 「未知」与「0」可分 /
口径同源 / 确定性 + 租户隔离 + 有界行数 / 与 #5362 的声明表对账）。

## 本单最容易做错的一条：**不得整表一刀切**

`customer_profiles` 的字段**分两侧**（#5362 逐字段核实：一侧有真值、一侧无真值）⇒ 视图必须
**逐字段区分**：有真值照实返回、无真值一律 `null`（未知）—— **既不许给默认值 / 0，也不许把有真值的
字段抹成 null**。两侧的红证都是注入式的（见 `TestRedProofs`）。

## 口径同源（本文件最承重的机械判据）

真值判断**不写在视图里**：装配层把 #5362 的 `FieldTruthRegistry` 声明**现取**成
`snapshot["field_truth"]["customer_profiles"]`（迁移运输），视图只按运输来的声明逐字段分类。
⇒ 判据 = ① 视图模块是**声明无关**的（不出现任何被声明字段的名字，`TestFieldLedgerIsNotOwnedByTheView`；
同类形态由**类级元守卫**覆盖 `app/briefing/**` 全部模块：自带字段台账 ⇒ 未登记即红，台账只许缩短）；
② 把运输来的声明改掉，视图的分类**必须跟着变**。

## 红证（§23 G7：注入先自证生效，再要求同一断言变红）

零回填 / 整表一刀切 / 自带字段台账（容器形态与散落形态）/ 单个通用词不误报 —— 五条注入式红证。

case_ids 说明（照实登记）：`CU-010` = 本视图的**专属**用例条目（**issue #5462 用例面补录**）——
本文件就是它的视图语义判据（逐字段三态 / 「未知」≠「0」/ 口径同源 / 五条注入式红证）；
装配腿与声明对账的判据见该条目的 `traces.tests`。
沿革：本单（#5456 / PR #5458）交付时按切包约束**未碰** `.github/cases/**` ⇒ 当时只声明了相邻面的
`DA-016` / `DA-017` / `DA-018`（快照装配 / 逐项可分 / 如实披露三条纪律的相邻载体）；
#5462 补录专属条目后改指 `CU-010`，不再借相邻面的用例记账。
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

import pytest

from app.briefing import customer_profile as view_module
# 三态词表与内核读取器**同一份**（视图与判据都不另写词表 —— 改词表时两侧一起红）
from app.briefing.proactive import INCOMPLETE, NOT_WIRED, WIRED

REPO_ROOT = Path(__file__).resolve().parents[3]
# append（**不是** insert）：只作脚本模式的兜底解析路径，避免遮蔽同名模块（与 conftest 同款理由）。
sys.path.append(str(REPO_ROOT / "tests"))

from unit_ci_workflows._source_parsing import (  # noqa: E402  （#5323：Java 剥注释/取字面量唯一实现）
    java_code,
    java_literals,
)

VIEW_SRC = Path(view_module.__file__)
KERNEL_DIR = VIEW_SRC.parent
FIELD_TRUTH_JAVA = (REPO_ROOT / "backend/admin-api/src/main/java/com/migao/admin/support/fieldtruth"
                    / "CustomerProfileFieldTruth.java")
SERVICE_JAVA = (REPO_ROOT / "backend/admin-api/src/main/java/com/migao/admin/service/CustomerService.java")
BRIEFING_JAVA = (REPO_ROOT / "backend/admin-api/src/main/java/com/migao/admin/service/DailyBriefingService.java")
CONTROLLER_JAVA = (REPO_ROOT / "backend/admin-api/src/main/java/com/migao/admin/controller/CustomerController.java")

#: 端点路径（与工具调用点的字面量、控制器的 `@GetMapping` 三处同源；工具侧另有判据）
ENDPOINT_PATH = "/api/admin/customers/profile-view"

ARRAY = view_module.ARRAY
TRUTH_KEY = view_module.TRUTH_KEY
HAS_TRUTH = view_module.HAS_TRUTH
NO_TRUTH = view_module.NO_TRUTH


#: **字段台账豁免**（§23 G2 燃尽靶子）：`app/briefing/**` 任一模块自带「哪些字段没有真值」这类
#: 台账 ⇒ 必须逐条登记。现状 = **空**（现取 0 处命中）⇒ 任何新增即红，且**悬空登记也红**
#: （命中数涨跌都红 ⇒ 只许缩短）。
FIELD_LEDGER_EXEMPTIONS: dict[str, str] = {}

#: 夹具前提（**红证前提自证**，§23 G7）：这两个字段必须真在 #5362 的**有真值**侧 ——
#: 「真 0 与未知可分」的对照物取它们（JSON 类字段，值里可以合法地出现 `0`）。
#: 声明一旦改判，前提断言先红（而不是让对照判据静默退化成恒真）。
ZERO_BEARING_FIELDS = ("craftProfile", "customFields")

#: **租户列**名（测试夹具用：行里放**别的**租户的号 ⇒ 视图必须回显调用方的租户）。
TENANT_COLUMN = "tenantId"

#: 无真值字段可能被「泄漏」过来的值形态：DB 列默认值（`DEFAULT 0` / `DEFAULT 30`）与建档种子常量
#: （`"new"` / `false`）—— 视图必须**一个都不放行**。
LEAKED_DB_DEFAULTS = (0, 0.0, "new", 30, False)


# ══════════════════════════════════════════════════════════════════════════════
# 一、现取（**不写死字段名**）：从 #5362 的声明源与装配层源码里读
# ══════════════════════════════════════════════════════════════════════════════


def java_source(path: Path) -> str:
    if not path.is_file():
        raise AssertionError(f"被判据引用的文件不存在：{path}（路径漂移 ⇒ 红，不得静默跳过）")
    return path.read_text(encoding="utf8")


def declaration_from_java(source: str | None = None) -> dict[str, str]:
    """现取 #5362 的逐字段声明（`字段 -> has_truth / no_truth`）。

    取值靠**词法位置**（共享机具 `java_literals`，注释里的字面量不算），不靠按引号扫原文的正则
    （`#5323` 的病灶）—— 因此「在注释里写一句同形声明」喂不动本判据。
    """
    text = java_source(FIELD_TRUTH_JAVA) if source is None else source
    literals = java_literals(text)
    out: dict[str, str] = {}
    for index, (pos, value) in enumerate(literals):
        if not text[:pos].rstrip().endswith("f.put("):
            continue
        nxt = literals[index + 1][0] if index + 1 < len(literals) else len(text)
        between = text[pos + len(value) + 2:nxt]
        if ", none(" in between:
            out[value] = NO_TRUTH
        elif ", has(" in between:
            out[value] = HAS_TRUTH
        else:
            raise AssertionError(f"声明条目 {value!r} 的真值侧读不出来（形态漂移 ⇒ fail-closed）")
    if len(out) < 30 or set(out.values()) != {HAS_TRUTH, NO_TRUTH}:
        raise AssertionError(
            f"声明解析读数异常：{len(out)} 个字段 / 两侧 = {sorted(set(out.values()))} ⇒ 判据会空跑")
    return out


def java_field_name_literals(text: str) -> set[str]:
    """Java 源码里**作为字符串字面量出现**的被声明字段名（注释里的不算 ⇒ 注释喂不动）。"""
    names = set(declaration_from_java())
    return {value for _pos, value in java_literals(text) if value in names}


def leg_body(text: str, signature: str) -> str:
    """取装配腿**方法体**的源码（剥注释后按花括号配平）。

    fail-closed：签名找不到、或配平结果过短 ⇒ 直接报错（否则「扫描面为空」会变成恒绿）。
    """
    code = java_code(text)
    start = code.find(signature)
    if start < 0:
        raise AssertionError(f"装配腿签名找不到：{signature!r}（路径/方法改名 ⇒ 判据失配 ⇒ 红）")
    open_at = code.find("{", start)
    if open_at < 0:
        raise AssertionError(f"装配腿 {signature!r} 之后找不到方法体起始花括号")
    depth = 0
    for index in range(open_at, len(code)):
        if code[index] == "{":
            depth += 1
        elif code[index] == "}":
            depth -= 1
            if depth == 0:
                body = code[open_at:index + 1]
                if len(body) < 200:
                    raise AssertionError(f"装配腿方法体过短（{len(body)} 字符）⇒ 判据会空跑")
                return body
    raise AssertionError(f"装配腿 {signature!r} 的花括号没配平 ⇒ 判据失配（fail-closed）")


def python_ledger_forms(text: str) -> tuple[set[str], set[str]]:
    """Python 源码里字段名的两种引用形态（用于类级元守卫）：

    ① `container` —— 字段名作为**容器字面量的直接成员 / 键**（`{"某字段", ...}` / `{"某字段": …}`
       / `["某字段"]`）⇒ 这就是「自带一份字段台账」的形态，**命中一个即红**；
    ② `scattered` —— 字段名作为裸字符串常量散落在模块里：单个通用词（如 `id`）不足以构成台账，
       ≥2 个不同字段名才算（拆成散落常量也逃不掉）。
    """
    names = set(declaration_from_java())
    tree = ast.parse(text)
    container: set[str] = set()
    scattered: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Set, ast.List, ast.Tuple)):
            for element in node.elts:
                if isinstance(element, ast.Constant) and isinstance(element.value, str) \
                        and element.value in names:
                    container.add(element.value)
        elif isinstance(node, ast.Dict):
            for key in node.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str) \
                        and key.value in names:
                    container.add(key.value)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in names:
            scattered.add(node.value)
    return container, scattered


def offenders_in(text: str) -> set[str]:
    """一个模块是否**自带字段台账**：形态 ① 命中，或形态 ② ≥2 个不同字段名。"""
    container, scattered = python_ledger_forms(text)
    return container if container else (scattered if len(scattered) > 1 else set())


# ══════════════════════════════════════════════════════════════════════════════
# 二、夹具：装配层运输给视图的快照（形态 = `CustomerService` 的客户画像装配腿）
# ══════════════════════════════════════════════════════════════════════════════


def leg_snapshot(*, truth: dict[str, str] | None = None, rows: list | None = None,
                 declared: list | None = None, omitted_array: bool = False,
                 omitted_field: str | None = None, truncated: bool = False,
                 limit: int = 51) -> dict:
    """装配层的产出形态：`row_fields` / `row_meta` / `field_truth` / `customer_profiles`。

    行值与真值侧一一对应：**有真值 ⇒ 现场造一个值**（`v:<字段>:<tag>`）、**无真值 ⇒ `None`**
    （= 已被 `CustomerProfileTruthMask` 遮蔽的形态）。
    """
    truth = truth or declaration_from_java()
    declared = sorted(truth) if declared is None else declared
    if rows is None:
        rows = [sample_row(truth, tag="a"), sample_row(truth, tag="b")]
    snapshot: dict = {
        "row_fields": {ARRAY: declared},
        "row_meta": {ARRAY: {"limit": limit, "count": len(rows), "truncated": truncated}},
        TRUTH_KEY: {ARRAY: {name: {"truth": side, "reason": f"#{name} 的证据化原因"}
                            for name, side in truth.items()}},
        ARRAY: rows,
    }
    if omitted_array:
        # 未接线 = 装配层**自描述里也没有**这个数组（与 product_health 的同款夹具同口径）
        del snapshot[ARRAY]
        del snapshot["row_fields"][ARRAY]
    if omitted_field:
        snapshot["row_fields"][ARRAY] = [f for f in declared if f != omitted_field]
    return snapshot


def sample_row(truth: dict[str, str], *, tag: str = "a", leaked: object | None = None) -> dict:
    """一行客户档案：有真值字段给一个**通用**值，无真值字段给 `None`。

    `leaked` 非 None 时，无真值字段一律给该「泄漏值」（模拟 DB 列默认值 / 建档种子常量绕过遮蔽）。
    """
    return {
        name: (leaked if leaked is not None else None) if side == NO_TRUTH else f"v:{name}:{tag}"
        for name, side in sorted(truth.items())
    }


def rows_by_tag(view: dict, tag: str) -> list:
    """按夹具的值标记取行（**不依赖任何具体字段名**）：有真值字段的值以 `:<tag>` 收尾。"""
    suffix = f":{tag}"
    return [row for row in view["rows"]
            if any(isinstance(value, str) and value.endswith(suffix) for value in row.values())]


def status_of(view: dict, field: str) -> str:
    return view["fields"][field]["status"]


def assert_no_truth_field_carries_a_value(view: dict) -> None:
    """判据 2 的断言函数（**与注入式红证共用**）：无真值字段不得以任何真值形态出现。"""
    no_truth = view["no_truth_fields"]
    if not no_truth:
        raise AssertionError("视图没给出无真值字段 ⇒ 本断言恒真（是空断言）")
    for row in view["rows"]:
        for field in no_truth:
            if row[field] is not None:
                raise AssertionError(
                    f"无真值字段 {field} 以真值形态出现了：{row[field]!r} —— "
                    "「未知」被冒充成 0 / 默认值 / 建档种子（口径 = NULL 即未知，不猜 0）")
    for field in no_truth:
        entry = view["fields"][field]
        if entry["truth"] != NO_TRUTH or entry["status"] != NOT_WIRED or not entry["reason"]:
            raise AssertionError(f"无真值字段 {field} 的接线状态没如实说明：{entry}")


def assert_has_truth_fields_are_preserved(view: dict, tagged_rows: dict) -> None:
    """判据 6 的断言函数（**与注入式红证共用**）：有真值的字段一个都不许被抹掉 / 改写。"""
    for tag, original in tagged_rows.items():
        found = rows_by_tag(view, tag)
        if len(found) != 1:
            raise AssertionError(
                f"标记 {tag!r} 的行找不到了（{len(found)} 行）—— 有真值的字段被整表抹掉了？")
        for field, value in original.items():
            if found[0][field] != value:
                raise AssertionError(
                    f"有真值字段 {field} 被改写/抹掉：期望 {value!r}，实得 {found[0][field]!r}")


# ══════════════════════════════════════════════════════════════════════════════
# 三、判据 1：逐字段三态
# ══════════════════════════════════════════════════════════════════════════════


class TestFieldStatusIsTriState:
    """判据 1：逐字段 `wired` / `not_wired` / `incomplete` + `reason`，不变式 `reason is None ⟺ wired`"""

    def test_every_declared_field_gets_exactly_one_state(self):
        truth = declaration_from_java()
        view = view_module.customer_profile(leg_snapshot(truth=truth), tenant_id=7)

        assert set(view["fields"]) == set(truth), "视图必须逐字段覆盖 #5362 的整张声明表"
        assert view["has_truth_fields"] == sorted(f for f, s in truth.items() if s == HAS_TRUTH)
        assert view["no_truth_fields"] == sorted(f for f, s in truth.items() if s == NO_TRUTH)
        has_side = {s: status_of(view, s) for s, side in truth.items() if side == HAS_TRUTH}
        no_side = {s: status_of(view, s) for s, side in truth.items() if side == NO_TRUTH}
        assert set(has_side.values()) == {WIRED}, f"完整快照下：有真值的字段都该 wired，实得 {has_side}"
        assert set(no_side.values()) == {NOT_WIRED}, (
            f"无真值的字段都该 not_wired（不是「值为 0 的正常字段」），实得 {no_side}")

    def test_invariant_reason_none_iff_wired(self):
        """不变式：`reason is None` ⟺ `wired`（全字段 × 4 种快照形态逐条核对）"""
        truth = declaration_from_java()
        variants = {
            "complete": leg_snapshot(truth=truth),
            "truncated": leg_snapshot(truth=truth, truncated=True),
            "array_missing": leg_snapshot(truth=truth, omitted_array=True),
            "field_missing": leg_snapshot(truth=truth, omitted_field=sorted(truth)[3]),
            "declaration_missing": {k: v for k, v in leg_snapshot(truth=truth).items()
                                    if k != TRUTH_KEY},
        }
        checked = 0
        for label, snapshot in variants.items():
            view = view_module.customer_profile(snapshot, tenant_id=7)
            for field, entry in view["fields"].items():
                assert (entry["reason"] is None) == (entry["status"] == WIRED), (
                    f"[{label}] {field} 违反不变式：status={entry['status']} reason={entry['reason']!r}")
                checked += 1
        assert checked >= 4 * len(truth), f"核对面过小（{checked}）⇒ 判据空跑"

    def test_partial_wiring_is_per_field(self):
        """**部分接线**（本判据的关键场景）：一个字段缺了，不该把整张表读成未接线"""
        truth = declaration_from_java()
        victim = sorted(f for f, side in truth.items() if side == HAS_TRUTH)[0]
        view = view_module.customer_profile(
            leg_snapshot(truth=truth, omitted_field=victim), tenant_id=7)

        assert status_of(view, victim) == NOT_WIRED
        assert view["fields"][victim]["missing"] == [victim]
        assert victim in view["fields"][victim]["reason"], view["fields"][victim]["reason"]
        others = [f for f, side in truth.items() if side == HAS_TRUTH and f != victim]
        assert {status_of(view, f) for f in others} == {WIRED}, "只有缺的那个字段该落 not_wired"

    def test_missing_array_is_not_wired_with_reason(self):
        truth = declaration_from_java()
        view = view_module.customer_profile(
            leg_snapshot(truth=truth, omitted_array=True), tenant_id=7)

        for field, side in truth.items():
            entry = view["fields"][field]
            assert entry["status"] == NOT_WIRED, f"{field} 应为 not_wired，实得 {entry['status']}"
            assert entry["reason"], f"{field} 的 not_wired 必须带原因（两种「没有」要可分）"
        sample = sorted(f for f, s in truth.items() if s == HAS_TRUTH)[0]
        assert ARRAY in view["fields"][sample]["reason"], view["fields"][sample]["reason"]
        assert view["count"] == 0

    def test_truncated_array_is_incomplete_on_has_truth_fields_only(self):
        """有界不许变成静默少报：行被上限截断 ⇒ 有真值的字段结论不完整；无真值的字段仍 `not_wired`"""
        truth = declaration_from_java()
        view = view_module.customer_profile(
            leg_snapshot(truth=truth, truncated=True, limit=1), tenant_id=7)

        for field, side in truth.items():
            entry = view["fields"][field]
            if side == NO_TRUTH:
                assert entry["status"] == NOT_WIRED, "无真值字段永远不产出 ⇒ 不因截断变 incomplete"
                continue
            assert entry["status"] == INCOMPLETE, f"{field} 应为 incomplete，实得 {entry['status']}"
            assert "截断" in entry["reason"], entry["reason"]

    def test_row_missing_a_declared_key_is_incomplete(self):
        """行里整个缺一个**已声明有真值**的键（装配/序列化漂移）⇒ 该字段不完整（不静默补 null）"""
        truth = declaration_from_java()
        victim = sorted(f for f, side in truth.items() if side == HAS_TRUTH)[0]
        snapshot = leg_snapshot(truth=truth)
        for row in snapshot[ARRAY]:
            del row[victim]

        view = view_module.customer_profile(snapshot, tenant_id=7)

        entry = view["fields"][victim]
        assert entry["status"] == INCOMPLETE, entry["status"]
        assert victim in entry["reason"] and "2" in entry["reason"], entry["reason"]

    def test_declaration_missing_is_fail_closed(self):
        """快照没带 #5362 的声明 ⇒ **不产出任何字段**（不猜哪些字段可信），并如实说明"""
        snapshot = leg_snapshot()
        del snapshot[TRUTH_KEY]

        view = view_module.customer_profile(snapshot, tenant_id=7)

        assert view["declaration"]["status"] == NOT_WIRED
        assert TRUTH_KEY in view["declaration"]["reason"], view["declaration"]["reason"]
        assert view["fields"] == {} and view["rows"] == [] and view["count"] == 0
        assert view["no_truth_fields"] == [] and view["has_truth_fields"] == []


# ══════════════════════════════════════════════════════════════════════════════
# 四、判据 2 + 3 + 6：无真值不得以真值形态出现 / 未知与 0 可分 / 与声明表对账
# ══════════════════════════════════════════════════════════════════════════════


class TestUnknownIsNotZero:
    """判据 2 + 3：无真值 ⇒ `null`（未知），**绝不是 0 / 默认值**；真 0 与未知在输出上可分"""

    def test_no_truth_fields_are_null_in_a_clean_snapshot(self):
        view = view_module.customer_profile(leg_snapshot(), tenant_id=7)
        assert_no_truth_field_carries_a_value(view)

    @pytest.mark.parametrize("leaked", LEAKED_DB_DEFAULTS)
    def test_leaked_db_defaults_never_reach_the_output(self, leaked):
        """🔴 判据 2 的**输入侧**红证：快照里带着 DB 默认值（0 / 30 / "new" / false）也一律不放行"""
        truth = declaration_from_java()
        snapshot = leg_snapshot(truth=truth, rows=[sample_row(truth, tag="a", leaked=leaked)])

        view = view_module.customer_profile(snapshot, tenant_id=7)

        assert_no_truth_field_carries_a_value(view)
        assert {row[f] for row in view["rows"] for f in view["no_truth_fields"]} == {None}, (
            f"泄漏值 {leaked!r} 出现在了无真值列上")

    def test_zero_inside_a_has_truth_field_survives_verbatim(self):
        """🔴 判据 3 的另一半：**真 0 保留**（未知 = null ⟹ 值域里的 0 不再是「未知」的同义词）"""
        truth = declaration_from_java()
        assert set(ZERO_BEARING_FIELDS) <= set(truth), "对照字段不在声明表里（夹具前提失效 ⇒ 必红）"
        assert {truth[name] for name in ZERO_BEARING_FIELDS} == {HAS_TRUTH}, (
            "对照字段必须真在**有真值**侧（否则本判据退化：拿无真值字段证明「真值保留」是自证）")

        snapshot = leg_snapshot()
        for row in snapshot[ARRAY]:
            row[ZERO_BEARING_FIELDS[0]] = {"rollCount": 0, "extra": None}
            row[ZERO_BEARING_FIELDS[1]] = {"refundAmount": 0}
        view = view_module.customer_profile(snapshot, tenant_id=7)

        for row in view["rows"]:
            assert row[ZERO_BEARING_FIELDS[0]] == {"rollCount": 0, "extra": None}
            assert row[ZERO_BEARING_FIELDS[1]] == {"refundAmount": 0}
        assert {status_of(view, name) for name in ZERO_BEARING_FIELDS} == {WIRED}
        # 同一行里「真 0（保留）」与「未知（null）」并存 ⇒ 两者可分
        assert_no_truth_field_carries_a_value(view)

    def test_truth_side_of_every_field_is_visible_in_the_envelope(self):
        """可分性不靠猜：每个字段的**真值侧**进 `fields`（`no_truth` + `not_wired` + 声明给的原因）"""
        truth = declaration_from_java()
        view = view_module.customer_profile(leg_snapshot(truth=truth), tenant_id=7)

        for field, side in truth.items():
            assert view["fields"][field]["truth"] == side, (
                f"{field} 的真值侧与 #5362 声明不一致 —— 有真值的字段不许被误判为「无真值」")
            if side == NO_TRUTH:
                assert f"#{field}" in view["fields"][field]["reason"], (
                    f"{field} 的无真值原因必须来自运输来的声明（证据化），实得 "
                    f"{view['fields'][field]['reason']!r}")


# ══════════════════════════════════════════════════════════════════════════════
# 五、判据 4：口径同源（视图不持有第二份真值判断）
# ══════════════════════════════════════════════════════════════════════════════


class TestFieldLedgerIsNotOwnedByTheView:
    """判据 4：真值判断**只有一份**（#5362 的注册表）—— 视图与内核都不许自带字段台账"""

    def test_view_module_lists_no_declared_field_name(self):
        """视图模块**声明无关**：不出现任何被声明字段的名字（含 docstring —— 那也是字符串常量）"""
        container, scattered = python_ledger_forms(VIEW_SRC.read_text(encoding="utf8"))

        assert (sorted(container), sorted(scattered)) == ([], []), (
            f"视图模块自带字段名：容器形态 {sorted(container)} / 散落形态 {sorted(scattered)}"
            " —— 真值判断必须只来自运输来的声明（#5362 注册表）"
            "（复算：python3 -m pytest tests/test_briefing_customer_profile.py -q -k lists_no_declared）"
        )

    def test_class_level_meta_guard_against_a_second_field_ledger(self):
        """🔴 **类级元守卫**（§23 G1/G2）：`app/briefing/**` 任一模块自带字段台账 ⇒ 未登记即红。

        为什么是**类级**而不是只钉本视图：族 3 的视图会继续长（下一个表按「声明 + 判据」两步复用），
        「视图自己维护一份字段台账」这一类缺陷只要落在本目录里就自动走这条闸 —— 不靠人记得写判据。
        判据形态：未登记即红；**悬空登记也红**（命中数涨跌都红 ⇒ 台账只许缩短）。
        """
        scanned = sorted(KERNEL_DIR.glob("*.py"))
        assert scanned, f"扫描面为空（{KERNEL_DIR}）⇒ 判据空转（fail-closed）"
        offenders = {path.name for path in scanned
                     if offenders_in(path.read_text(encoding="utf8"))}

        assert sorted(offenders) == sorted(FIELD_LEDGER_EXEMPTIONS), (
            "内核目录里出现「自带字段台账」的模块（= 真值判断的第二份来源）——"
            f"未登记：{sorted(set(offenders) - set(FIELD_LEDGER_EXEMPTIONS))}；"
            f"悬空登记（修好后请销账）：{sorted(set(FIELD_LEDGER_EXEMPTIONS) - set(offenders))}；"
            f"扫描 {len(scanned)} 个模块、字段名现取 {len(declaration_from_java())} 个、"
            f"豁免台账现取 {len(FIELD_LEDGER_EXEMPTIONS)} 条"
            "（复算：python3 -m pytest tests/test_briefing_customer_profile.py -q -k meta_guard）"
        )

    def test_classification_follows_the_transported_declaration(self):
        """🔴 口径同源的**行为**判据：把运输来的声明改判，视图的分类必须跟着变

        视图若自带一份台账，本判据必红（它跟着自己的表走，不跟着 `snapshot[field_truth]` 走）。
        """
        truth = declaration_from_java()
        flipped = dict(truth)
        to_has = sorted(f for f, side in truth.items() if side == NO_TRUTH)[0]
        to_none = sorted(f for f, side in truth.items() if side == HAS_TRUTH)[0]
        flipped[to_has], flipped[to_none] = HAS_TRUTH, NO_TRUTH

        base = leg_snapshot(truth=truth)
        mutated = leg_snapshot(truth=flipped)
        for row in mutated[ARRAY]:
            row[to_has] = "v:flipped"

        view = view_module.customer_profile(mutated, tenant_id=7)
        base_view = view_module.customer_profile(base, tenant_id=7)

        assert status_of(view, to_has) == WIRED, "声明改判为有真值 ⇒ 视图必须跟着当有真值"
        assert view["rows"][0][to_has] == "v:flipped"
        assert status_of(view, to_none) == NOT_WIRED, "声明改判为无真值 ⇒ 视图必须跟着遮蔽"
        assert {row[to_none] for row in view["rows"]} == {None}
        untouched = [f for f in truth if f not in (to_has, to_none)]
        assert [view["fields"][f]["truth"] for f in untouched] == \
            [flipped[f] for f in untouched], "其余字段不该跟着一起翻转（逐字段区分）"
        assert view["rows"] != base_view["rows"], "改判前后输出逐字相同 ⇒ 视图没跟着声明走（判据无判别力）"

    def test_array_key_and_endpoint_default_match_the_declared_contract(self):
        """契约键同源（跨端两处一份口径，机械钉住）：

        ① 视图的行数组名 == #5362 声明里的**表名**（视图消费的键就是声明运输的键）；
        ② 端点默认的行数上限 == 视图的 `MAX_VIEW_ROWS`（工具另会显式传同一个值 —— 两处都钉）。
        """
        declaration_src = java_source(FIELD_TRUTH_JAVA)
        table = re.search(r'TABLE\s*=\s*"([^"]+)"', declaration_src)
        assert table, "声明源里找不到表名常量 ⇒ 判据失配（fail-closed）"
        assert view_module.ARRAY == table.group(1), (
            f"视图的行数组名 {view_module.ARRAY!r} 与声明的表名 {table.group(1)!r} 不一致")

        controller = java_source(CONTROLLER_JAVA)
        anchor = f'@GetMapping("{ENDPOINT_PATH}")'
        start = controller.find(anchor)
        assert start > 0, f"控制器里找不到 {anchor} ⇒ 端点/判据失配（fail-closed）"
        default = re.search(r'defaultValue\s*=\s*"(\d+)"', controller[start:start + 600])
        assert default, "端点没有声明默认行数上限 ⇒ 契约缺一半"
        assert int(default.group(1)) == view_module.MAX_VIEW_ROWS, (
            f"端点默认上限 {default.group(1)} != 视图上限 {view_module.MAX_VIEW_ROWS}"
            " —— 两处一份口径，必须由判据钉住")

    def test_assembler_renders_the_declaration_from_the_registry(self):
        """装配腿侧的同源判据：声明**现取**自 #5362 的注册表；读面遮蔽复用既有 Mask；腿内不写字段名"""
        service = java_source(SERVICE_JAVA)
        body = leg_body(service, "profileViewSnapshot")

        assert "FieldTruthRegistry" in body, (
            "客户画像视图的装配腿必须从 #5362 的注册表现取声明（不许在装配层另写一份）")
        assert "CustomerProfileTruthMask.apply" in body, (
            "读面遮蔽必须复用既有 Mask（值的单点来源）—— 视图不承担第二份遮蔽实现")
        assert java_field_name_literals(body) == set(), (
            f"装配腿里出现了被声明字段的名字（= 手写清单）：{sorted(java_field_name_literals(body))}")

    def test_dashboard_snapshot_stays_free_of_customer_rows(self):
        """🔴 权限面不变量：客户档案行**不得**进 `dashboard:view` 的简报表快照（PII 不得越过 `customer:view`）

        工具码 ≡ 端点码 ≡ 菜单节点码这条线由既有守卫机械强制
        （`tests/unit_ci_workflows/test_agent_permission_parity.py`：工具声明的码必须等于它调用的
        每个已注解端点的生效码）—— 本判据只补它管不到的那一半：**行数组别越界**。
        """
        briefing = java_source(BRIEFING_JAVA)

        assert ARRAY not in briefing, (
            "简报表快照（`/api/admin/briefing/snapshot`，权限码 `dashboard:view`）里出现了客户档案行数组 "
            "—— 客户 PII 必须留在 `customer:view` 那一侧（Agent 能力 ≡ 页面权限，issue #5246）")


# ══════════════════════════════════════════════════════════════════════════════
# 六、判据 5：确定性 + 租户隔离 + 有界行数
# ══════════════════════════════════════════════════════════════════════════════


class TestDeterminismIsolationAndBound:

    def test_same_snapshot_same_output(self):
        snapshot = leg_snapshot()
        first = view_module.customer_profile(snapshot, tenant_id=7)
        second = view_module.customer_profile(json.loads(json.dumps(snapshot)), tenant_id=7)

        assert json.dumps(first, ensure_ascii=False, sort_keys=True) == \
            json.dumps(second, ensure_ascii=False, sort_keys=True)

    def test_field_status_and_counts_do_not_depend_on_row_order(self):
        """行序不改变**结论**（行序本身是装配层 SQL 的口径：新建倒序，视图不改行序）"""
        truth = declaration_from_java()
        rows = [sample_row(truth, tag="a"), sample_row(truth, tag="b"), sample_row(truth, tag="c")]
        forward = view_module.customer_profile(leg_snapshot(truth=truth, rows=rows), tenant_id=7)
        backward = view_module.customer_profile(
            leg_snapshot(truth=truth, rows=list(reversed(rows))), tenant_id=7)

        assert forward["fields"] == backward["fields"]
        assert forward["count"] == backward["count"] == 3
        assert forward["no_truth_fields"] == backward["no_truth_fields"]
        assert forward["basis"] == backward["basis"]
        probe = sorted(truth)[0]
        assert [r[probe] for r in forward["rows"]] != [r[probe] for r in backward["rows"]], \
            "夹具自证：两次输入的行序确实不同"

    def test_module_reads_no_clock_and_no_randomness(self):
        tree = ast.parse(VIEW_SRC.read_text(encoding="utf8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add("relative" if node.level else (node.module or "").split(".")[0])
        assert not ({"time", "datetime", "random", "uuid", "os"} & imported), sorted(imported)

    def test_tenant_is_echoed_and_not_guessed_from_rows(self):
        truth = declaration_from_java()
        assert TENANT_COLUMN in truth, f"夹具前提：{TENANT_COLUMN} 必须在声明表里（否则本判据空跑）"
        snapshot = leg_snapshot(truth=truth)
        for row in snapshot[ARRAY]:
            row[TENANT_COLUMN] = 999999          # 行里是**别的**租户

        view = view_module.customer_profile(snapshot, tenant_id=7)

        assert view["tenant_id"] == 7, "租户由调用方传入并原样回显（隔离关口在装配层，不由行反推）"

    def test_rows_are_bounded_by_default_and_truncation_is_explicit(self):
        truth = declaration_from_java()
        rows = [sample_row(truth, tag=f"t{index:03d}")
                for index in range(view_module.MAX_VIEW_ROWS + 5)]

        view = view_module.customer_profile(leg_snapshot(truth=truth, rows=rows), tenant_id=7)

        assert view["count"] == view_module.MAX_VIEW_ROWS
        assert view["rows_total"] == view_module.MAX_VIEW_ROWS + 5
        assert view["truncated"] is True
        assert {entry["status"] for entry in view["fields"].values()
                if entry["truth"] == HAS_TRUTH} == {INCOMPLETE}, "被截断时结论必须标不完整"

    def test_limit_is_validated(self):
        truth = declaration_from_java()
        rows = [sample_row(truth, tag="a"), sample_row(truth, tag="b")]
        snapshot = leg_snapshot(truth=truth, rows=rows)

        assert view_module.customer_profile(snapshot, tenant_id=7, limit=1)["count"] == 1
        assert view_module.customer_profile(snapshot, tenant_id=7, limit=2)["truncated"] is False
        for bad in (0, -1, True, "2", None):
            with pytest.raises(ValueError):
                view_module.customer_profile(snapshot, tenant_id=7, limit=bad)

    def test_non_dict_snapshot_is_fail_closed_not_crash(self):
        view = view_module.customer_profile(None, tenant_id=7)

        assert view["declaration"]["status"] == NOT_WIRED
        assert view["count"] == 0 and view["rows"] == [] and view["fields"] == {}
        assert view["no_truth_fields"] == []

    def test_all_values_are_json_native(self):
        view = view_module.customer_profile(leg_snapshot(), tenant_id=7)
        assert json.loads(json.dumps(view, ensure_ascii=False))["view"] == view_module.VIEW_ID

    def test_view_id_and_basis_are_stable(self):
        view = view_module.customer_profile(leg_snapshot(), tenant_id=7)

        assert view_module.VIEW_ID == "customer_profile"
        assert view["view"] == "customer_profile"
        assert view["basis"]["array"] == ARRAY
        assert TRUTH_KEY in view["basis"]["truth_source"]
        assert "装配层" in view["basis"]["row_order"]


# ══════════════════════════════════════════════════════════════════════════════
# 七、注入式红证（§23 G7：先自证注入生效，再要求同一断言变红）
# ══════════════════════════════════════════════════════════════════════════════


class TestRedProofs:

    def test_zero_filling_injection_turns_the_unknown_assertion_red(self):
        """🔴 红证 ①：把「无真值 ⇒ null」改成「无真值 ⇒ 0」⇒ 判据 2/3 的断言必须变红"""
        original = view_module._cell
        view_module._cell = lambda field, entry, raw: (
            0 if entry["truth"] == NO_TRUTH else raw.get(field))
        try:
            injected = view_module.customer_profile(leg_snapshot(), tenant_id=7)
            victim = injected["no_truth_fields"][0]
            assert {row[victim] for row in injected["rows"]} == {0}, "注入未生效"
            with pytest.raises(AssertionError):
                assert_no_truth_field_carries_a_value(injected)
        finally:
            view_module._cell = original

        assert_no_truth_field_carries_a_value(
            view_module.customer_profile(leg_snapshot(), tenant_id=7))

    def test_blanket_nulling_injection_turns_the_preservation_assertion_red(self):
        """🔴 红证 ②（「不得整表一刀切」）：把**有真值**的字段也抹成 null ⇒ 判据 6 的断言必须变红"""
        truth = declaration_from_java()
        expected = {tag: sample_row(truth, tag=tag) for tag in ("a", "b")}
        original = view_module._cell
        view_module._cell = lambda field, entry, raw: None
        try:
            injected = view_module.customer_profile(leg_snapshot(), tenant_id=7)
            assert set(injected["rows"][0].values()) == {None}, "注入未生效（还有值没被抹掉）"
            with pytest.raises(AssertionError):
                assert_has_truth_fields_are_preserved(injected, expected)
        finally:
            view_module._cell = original

        assert_has_truth_fields_are_preserved(
            view_module.customer_profile(leg_snapshot(), tenant_id=7), expected)

    def test_injected_field_ledger_turns_the_meta_guard_red(self):
        """🔴 红证 ③：视图自带一份字段台账（容器形态）⇒ 元守卫的形态判据必须认出来"""
        truth = declaration_from_java()
        victim = sorted(f for f, side in truth.items() if side == NO_TRUTH)[0]
        source = VIEW_SRC.read_text(encoding="utf8")
        injected = source + f'\nNO_TRUTH_FIELDS = {{"{victim}"}}\n'
        assert injected != source, "注入未生效"

        assert offenders_in(injected) == {victim}, "注入的台账没被形态 ① 认出来"

    def test_injected_scattered_field_names_turn_the_meta_guard_red(self):
        """🔴 红证 ④：把台账拆成散落的裸字符串常量（形态 ②）也逃不掉"""
        truth = declaration_from_java()
        victims = sorted(f for f, side in truth.items() if side == NO_TRUTH)[:2]
        source = VIEW_SRC.read_text(encoding="utf8")
        injected = source + "".join(
            f'\n_SORT_{index} = "{name}"\n' for index, name in enumerate(victims))
        assert injected != source, "注入未生效"

        assert offenders_in(injected) == set(victims), "散落形态没被认出来"

    def test_single_generic_name_is_not_treated_as_a_ledger(self):
        """判别力边界（**自证不误报**）：单个通用词（`id` 这类任意模块都可能出现的名字）不算台账"""
        truth = declaration_from_java()
        one = sorted(truth)[0]
        source = VIEW_SRC.read_text(encoding="utf8")
        injected = source + f'\nROW_KEY = "{one}"\n'

        assert offenders_in(injected) == set(), f"单个 {one!r} 被误判成台账 ⇒ 判据会假红"