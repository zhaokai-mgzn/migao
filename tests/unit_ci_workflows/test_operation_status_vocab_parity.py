# case_ids: UI-051
"""**工序**状态取值域的跨端一致性守卫（issue #6103）。

## 病根（本单要治的静默失效形态）

工序管理页的「停用」按钮**100% 失效**，而前端测试全绿：UI 写面逐字发 `{status:'inactive'}`，
后端 `ProductionOperationCommandService.STATUSES` 只收 `active|disabled` ⇒ **422**
「status 仅支持 active/disabled」，库里那一行照旧 `status='active'`。

三个原因叠在一起，缺一条都不会这么安静：

| # | 载体 | 形态 |
|---|---|---|
| ① | `frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx` 的停用写面 | 逐字发 `'inactive'` |
| ② | `backend/admin-api/.../ProductionOperationCommandService.java` 的 `STATUSES` | `Set.of("active","disabled")` |
| ③ | `frontend/admin-web/src/types/index.ts` | 写面类型 `status?: string`（**裸 string**）⇒ `tsc` **看不见**错值；`'inactive'` 是**加工项**域 `ProcessingItemStatus` 的词表（抄错了域） |

⇒ 本守卫是**类级元守卫**：让 ①⇄② 的取值域**不一致可机械判红** ——
后端 `STATUSES` 加/删一个值而前端没跟 ⇒ 当场红（不必等哪个页面再抄错一次）。

## 判据（全部**读源**；本文件不 import 任何被测模块）

| # | 判据 | 红证（怎么让它红） |
|---|---|---|
| C1 | 后端 `STATUSES` 的**字面量集合**非空、含 `active`、且能被解析出**一个** `Set.of` 声明（解析失配即红，不静默给空集） | 把声明改名 / 改成变量引用 ⇒ 红 |
| C2 | 前端 `ProductionOperationStatus` 的成员集合与后端**逐值相等**（不是包含） | 后端加 `deleted`、前端没跟 ⇒ 红；前端多写一个后端不认的值 ⇒ 也红 |
| C3 | 前端成员**逐项冻结**为 `{active, disabled}` —— 集合级相等对「两边一起错」无判别力，本条把它钉死 | 两边一起把 `disabled` 改成 `inactive` ⇒ 红 |
| C4 | **写面纵深**：工序管理页里**每一个** `status` 键的字面量都落在后端词表内（今天钉的是停用写面） | 把 `page.tsx` 的值改回 `'inactive'` ⇒ 红（具名报出该字面量） |
| C5 | **判别力自证（反恒真）**：取值实现本身对坏形态判红（含「写面找不到任何 `status` 字面量」这种让人安心但什么都没守的形态），对好形态不报 | 守卫退化成恒真 ⇒ 红 |
| C6 | 前端**没有**第二个没登记的工序状态词表：`types/index.ts` 里除 `ProductionOperationStatus` 外，不得再出现别的「工序 / 操作状态」联合类型（本仓已清白的域只有加工项 `ProcessingItemStatus`） | 复制一份 `OperationStatus = 'active' | 'inactive'` ⇒ 红（保守：判据按**名字形态**点名，见下边界） |

## 边界（照实登记，§19.1）

- 射程只到**这两个源文件**（后端 `ProductionOperationCommandService.STATUSES` ⇄ 前端
  `types/index.ts` 的 `ProductionOperationStatus`）+ 工序管理页这一处写面的 `status` 字面量；
  **不**保证没有别的页面再抄错一次（那由 C4 的同族判据逐个纳入，或由 C2 在词表层面拦住）。
- `ProductionRoutingCommandService.STATUSES`（路线域，同名常量、同一词表）**不在本判据面**：
  它没有对应的前端联合类型可对齐；**不得**据此认为「改了路线域词表也会红」。
- C4 的观测面是**源码字面量**，不是运行期 payload —— 「payload 真的落在词表内」由
  `frontend/admin-web/tests/unit/pages/production-routings.test.tsx` 的「#6103」用例断言（§28.2 的
  行为面由那条承担，本文件只承担**结构面**）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests"))

from unit_ci_workflows._source_parsing import (  # noqa: E402
    java_code,
    java_literals,
)

#: 真值源：**工序**域后端词表（只读比对，本包不改后端实现）
BACKEND_SERVICE = (
    REPO_ROOT
    / "backend/admin-api/src/main/java/com/migao/admin/service/ProductionOperationCommandService.java"
)
#: 前端词表副本
FRONTEND_TYPES = REPO_ROOT / "frontend/admin-web/src/types/index.ts"
#: 工序管理面（停用写面所在）—— issue #6580：功能体搬进 `ProcessConfigBoard`
#: （旧路由 `production/routings/page.tsx` 现在只是渲染它的薄壳，里面没有写面）⇒ 宿主随功能体走。
ROUTINGS_PAGE = (
    REPO_ROOT / "frontend/admin-web/src/components/production-config/ProcessConfigBoard.tsx"
)

#: 前端工序状态联合类型名（与本文件 C2/C3 判据同名 —— 改名即红，是有意的）
TS_STATUS_TYPE = "ProductionOperationStatus"
#: 后端常量名（Java 侧不能按名取值 ⇒ 用下面那条**整体**形态正则定位，见 C1）
#: 一次匹配就吃下 `.of(` 到**它自己的**收尾 `)` —— 声明被改名/换形时**整条**匹配不上 ⇒ 取到空集 ⇒ 判红
JAVA_STATUSES_DECL = re.compile(
    r"Set<String>\s+STATUSES\s*=\s*Set\.of\s*\((?:[^()]|\([^()]*\))*\)"
)
#: 冻结词表：C3 用它把「两边一起错」也判红
FROZEN_OPERATION_STATUSES = ("active", "disabled")
#: 本仓已清白的同类域（C6 用它排除误伤）：加工项域的词表
INNOCENT_STATUS_TYPES = ("ProcessingItemStatus",)
#: 写面取值：`status: 'x'` / `status="x"` / `status: "x"`（入参必须**已剥注释**）
STATUS_LITERAL = re.compile(r"""status\s*[:=]\s*(?:'([^'\n]*)'|"([^"\n]*)")""")
#: 前端联合类型声明（`export type X = 'a' | 'b'`；入参必须**已剥注释**）
TS_UNION_DECL = re.compile(r"""export\s+type\s+PLACEHOLDER\s*=\s*([^\n;]+)""")
#: 联合类型里的单个成员字面量
TS_UNION_MEMBER = re.compile(r"""['"]([^'"]*)['"]""")


def _read(path: Path) -> str:
    assert path.is_file(), f"{path.relative_to(REPO_ROOT)} 不存在 ⇒ 判据失去对象（同步本判据）"
    return path.read_text(encoding="utf-8")


def backend_operation_statuses() -> set[str]:
    """后端 `ProductionOperationCommandService.STATUSES` 的字面量集合（**唯一真值源**）。

    解析失配（声明不在 / 不是 `Set.of(字面量…)`）⇒ **红**，不静默给空集。
    """
    code = java_code(_read(BACKEND_SERVICE))
    segment = JAVA_STATUSES_DECL.search(code)
    literals = (
        [value for _, value in java_literals(segment.group(0))]
        if segment
        else []
    )
    assert literals, (
        "在 backend/admin-api/src/main/java/com/migao/admin/service/"
        "ProductionOperationCommandService.java 里取不到 "
        "`private static final Set<String> STATUSES = Set.of(...)` 的字面量 ⇒ 后端工序状态词表被改名/换形 "
        "⇒ 本判据无法比对（不许静默通过）"
    )
    return set(literals)


def writes_status_literals(code: str) -> set[str]:
    """源码里**每一处** `status` 键的字面量取值（`status: 'x'` / `status="x"` / `status: "x"`）。

    入参必须**已剥注释**（本文件传 `java_code(...)` 的结果）—— 注释里举反例（如「曾经发 `inactive`」）
    不得被判成写面取值。
    """
    return {a or b for a, b in STATUS_LITERAL.findall(code)}


def frontend_operation_statuses() -> set[str]:
    """前端 `ProductionOperationStatus` 的成员集合。

    TypeScript 不能被 `ast` 解析 ⇒ 用「**先剥注释**（`java_code`，引号感知）+ 再取联合字面量」的读法
    （本仓的 TS 侧共享读法；`declared_strings` 只服务 Python）。找不到声明 ⇒ **红**，不静默给空集。
    """
    code = java_code(_read(FRONTEND_TYPES))
    pattern = TS_UNION_DECL.pattern.replace("PLACEHOLDER", TS_STATUS_TYPE)
    matched = re.search(pattern, code)
    members = set(TS_UNION_MEMBER.findall(matched.group(1) if matched else ""))
    assert members, (
        f"{FRONTEND_TYPES.relative_to(REPO_ROOT)} 里取不到 `export type {TS_STATUS_TYPE} = …` 的成员 ⇒ "
        "前端工序状态词表被改名/换形（例如退回裸 string）⇒ 本判据无法比对（不许静默通过）"
    )
    return members


# ══════════════════════════════════════════════════════════════════════════════
# C1 / C2 / C3 —— 词表本身
# ══════════════════════════════════════════════════════════════════════════════


def test_backend_operation_statuses_are_parsed():
    """C1：后端词表可解析、非空、含 `active`（解析失配即红，不静默给空集）。"""
    backend = backend_operation_statuses()
    assert backend, "后端工序状态词表解析出空集 ⇒ 判据被架空（禁止静默通过）"
    assert "active" in backend, f"后端工序状态词表里没有 `active`：{sorted(backend)}"


def test_frontend_operation_statuses_exactly_equal_backend():
    """C2：前端联合类型与后端 `STATUSES` **逐值相等**（后端加/删一个值而前端没跟 ⇒ 红）。"""
    backend = backend_operation_statuses()
    frontend = frontend_operation_statuses()
    assert frontend, (
        f"{FRONTEND_TYPES.relative_to(REPO_ROOT)} 里找不到 `{TS_STATUS_TYPE}` 的成员"
        "（类型被改名 / 被换成裸 string）⇒ 红"
    )
    assert frontend == backend, (
        "前端工序状态取值域与后端 STATUSES 不一致 ⇒ 后端受理的词表与前端写面已分叉：\n"
        f"  后端有、前端没有：{sorted(backend - frontend)}\n"
        f"  前端有、后端没有：{sorted(frontend - backend)}\n"
        "  修法：改前端 `ProductionOperationStatus`（**不要**去放宽后端词表 —— 后端词表与路线域一致）"
    )


def test_frontend_operation_statuses_are_frozen():
    """C3：前端成员**逐项冻结**（集合级相等挡不住「两边一起错」）。"""
    frontend = frontend_operation_statuses()
    assert sorted(frontend) == sorted(FROZEN_OPERATION_STATUSES), (
        f"前端工序状态取值域被改动：现取 {sorted(frontend)} / 冻结 {sorted(FROZEN_OPERATION_STATUSES)}。"
        "两侧一起改同样判红（本仓的工序域停用值就是 `disabled`，改它要先动后端与迁移）"
    )


# ══════════════════════════════════════════════════════════════════════════════
# C4 —— 写面纵深：工序管理页的每一处 status 字面量都在词表内
# ══════════════════════════════════════════════════════════════════════════════


def test_routings_page_status_literals_are_in_backend_vocab():
    """C4：工序管理页里每一个 `status` 键的字面量都落在后端受理词表内（#6103 的实例判据）。"""
    backend = backend_operation_statuses()
    page_code = java_code(_read(ROUTINGS_PAGE))
    literals = writes_status_literals(page_code)
    assert literals, (
        f"{ROUTINGS_PAGE.relative_to(REPO_ROOT)} 里找不到任何 `status:` 字面量 ⇒ "
        "写面被改名/改形（或本判据的正则失效）⇒ 红（禁止「看起来在守、其实什么都没守」）"
    )
    offending = sorted(literals - backend)
    assert not offending, (
        f"工序管理页发出的 status 取值不在后端受理词表内：{offending}（后端受理 {sorted(backend)}）\n"
        "  这正是 issue #6103 的形态：前端逐字发 `'inactive'`（**加工项**域的词表，抄错了域）"
        "⇒ 后端 422「status 仅支持 active/disabled」⇒ 按钮 100% 失效。"
    )


# ══════════════════════════════════════════════════════════════════════════════
# C5 —— 判别力自证（反恒真，在内存语料上跑，不碰仓内文件）
# ══════════════════════════════════════════════════════════════════════════════


def test_guard_has_discriminating_power():
    """C5：取值实现**真的**能判红（好形态不报、四种坏形态各自判红）。"""
    backend = {"active", "disabled"}
    # 好形态：写在写面里的值都在词表内
    assert not (writes_status_literals("x = { status: 'disabled' }") - backend)
    # 坏形态①：抄错域（#6103 本体）
    assert writes_status_literals("x = { status: 'inactive' }") - backend == {"inactive"}
    # 坏形态②：双引号写法同样被抓
    assert writes_status_literals('x = { status: "inactive" }') - backend == {"inactive"}
    # 坏形态③：等号写法同样被抓
    assert writes_status_literals('x = { status="inactive" }') - backend == {"inactive"}
    # 坏形态④：一处都没有 ⇒ 交给调用方的非空断言（这里证明「空集」真的会是空集）
    assert writes_status_literals("x = { other: 'inactive' }") == set()


# ══════════════════════════════════════════════════════════════════════════════
# C6 —— 不许出现第二个没登记的工序状态词表
# ══════════════════════════════════════════════════════════════════════════════


def test_no_second_operation_status_vocabulary():
    """C6：`types/index.ts` 里不得再出现别的「工序状态」联合类型（防抄第二份词表）。"""
    code = _read(FRONTEND_TYPES)
    names = set(re.findall(r"""export type\s+([A-Za-z0-9_]*(?:Operation|OperationStatus)[A-Za-z0-9_]*Status)\s*=""", code))
    unregistered = sorted(names - {TS_STATUS_TYPE} - set(INNOCENT_STATUS_TYPES))
    assert not unregistered, (
        f"发现未登记的工序状态类型：{unregistered} —— 工序状态词表的单一来源是 "
        f"`{TS_STATUS_TYPE}`（本判据 C2/C3 守它）；第二份词表就是 #6103 的复发形态"
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
