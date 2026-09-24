# case_ids: PP-008, AS-004
"""**计数型前置自断言**（`processing_item_count_for_keyword` / `aftersales_ticket_count_for_ticket_no`）的 L0 守卫（issue #4527）。

## 为什么必须有（同族病灶 = `PG-013` / `CU-003` 的归因污染）

PP-008 的写动作是「停用种子加工项 `pi_eval_punch`（名字「打孔」）」。它依赖的**真前置**
是「那个共享夹具真的在、且只有一份」：

- **不在** ⇒ 红的表现是 `unmatched expectation` —— 看起来像「agent 不会停用加工项」，归因全错；
- **有同名副本** ⇒ 停用的可能不是种子那一件（后续用例读到被改坏的状态）。

本类型把这条前置变成**可判定自断言**（`precondition[processing_item_count_for_keyword]`）。

## 判据（每条都能红）

1. **类型有实现**：声明了没人实现的 type ⇒ `check_precondition_declared` 报 config_error
   （用例带一个不生效的守卫跑）—— 红证 = 从 `_PRECONDITION_TYPES` 删掉本类型；
2. **静态检查放行**：本类型的声明必须 `== []`（否则用例在运行期被判 config_error）；
3. **未知类型仍 fail-closed**：兜底分支不得被放宽（防「新类型顺手开个大口子」）；
4. **计数口径**：`_probe_processing_item_count` 按**名字子串**计数，**不按 status**
   （本用例的写动作就是改状态；把 status 计入口径 ⇒ 正常行为被判成「前置漂移」= 假红）；
   读数取不到 ⇒ `None`（**不**当成 0 —— 0 会被读成「夹具没了」，是另一种误判）；
5. **用例侧声明仍在**（防有人把前置删掉让门禁变绿）：PP-008 必须声明本类型 + `expect: 1`。

## #5247 改判（2026-09-23 用户裁定「B 端米宝只读化」）：断言面为什么变了

PP-008 的写 action（`processing_item_manage(action=toggle_item_status)`）与 AS-004 的写 action
（`after_sales_manage(action=update_status)`）**已从源码删除**、对应工具从 B 端全部 skill 解绑
⇒ 两条用例按新机制改判到**只读**路径（`processing_item_query` / `after_sales_manage(action=list)`），
原来的写声明（`must_succeed` / `required_args` / `output_verify` / `db_verify`）随之清空 ——
那是**被判据要求**的结果（写声明悬空 ⇒ 指向不存在的 action ⇒ 会被 CI 的 action 绑定判据阻塞），
**不是放宽**。本文件的两条"用例侧声明仍在"判据据此改判：`precondition`（类型 / 定位键 /
基线期望）**一字不动**；断言面的要求换成**等效/更强**形态 —— `expectations` 仍必须非空，
且机器可判字段里**不得残留任何退役写面**（详见 `TestCaseDeclarationStillThere` 与
`TestAftersalesTicketType` 的注释）。
"""

import asyncio
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / ".github") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / ".github"))

import assertion_taxonomy  # noqa: E402  —— 本仓"写"判定的唯一源（证明改判后的 action 是读）
from render_cases import load_case_dicts  # noqa: E402

TYPE_NAME = "processing_item_count_for_keyword"

#: #5247 **退役的 B 端写面**（留档）：8 个工具收窄为只读（写 action 已从源码删除）+
#: 8 个工具从 B 端全部 skill 解绑（工具类仍在、C 端绑定未动，但两侧工具集都不可达）。
#: 这里只收**不可能合法出现**的名字：已解绑的写工具 + 已删除的、专属于某工具的写 action
#: （不收 `create` 这类通用词 —— 它们可能是别的工具的合法 action，会造成假红）。
RETIRED_WRITE_SURFACE: frozenset = frozenset({
    # 已解绑（B 端全部 skill 不绑定、C 端也没有它们）
    "order_manage", "product_manage", "product_update", "sku_update",
    "processing_item_manage", "processing_order_generate", "processing_order_update",
    "product_processing_item_manage",          # 更早（#4371 商品↔加工项解耦）退场
    # 已从源码删除的写 action（只可能由写路径产生）
    "toggle_item_status", "toggle_status", "update_status", "adjust", "add_tag", "remove_tag",
})

#: `db_verify` 里只可能由已删除写 action（`after_sales_manage(action=update_status)`）产生的 token。
RETIRED_DB_VERIFY_TOKENS: tuple = ("closedAt", "closeReason", '"closed"')

#: "机器可判字段" = 这几格里出现的东西都会被 runner 真的拿去判（断言面本体）。
MACHINE_FIELDS: tuple = ("expectations", "must_succeed", "required_args", "output_verify", "db_verify")


def _declared_machine_tools(case: dict) -> set:
    """机器可判字段里声明/引用的**工具名**（含 `tool or tool2` 与字符串形态）。"""
    out: set = set()
    for field in MACHINE_FIELDS:
        for spec in (case.get(field) or []):
            src = spec.get("tool") if isinstance(spec, dict) else spec
            for part in re.split(r"\s+or\s+", str(src or "")):
                m = re.match(r"\s*([a-z][a-z0-9_]*)", part)
                if m:
                    out.add(m.group(1))
    return out


def _declared_machine_actions(case: dict) -> set:
    """机器可判字段里声明的 **action**（dict 的 `args.action` 与 spec 级 `action`、字符串形态）。"""
    raw = json.dumps([case.get(f) for f in MACHINE_FIELDS], ensure_ascii=False)
    out = set(re.findall(r'"(?:action|actions)"\s*:\s*"([^"]+)"', raw))
    for field in MACHINE_FIELDS:
        for spec in (case.get(field) or []):
            if isinstance(spec, str):
                out.update(re.findall(r"action=([A-Za-z_][A-Za-z0-9_]*)", spec))
    return out


def _retired_write_leaks(case: dict) -> list:
    """机器可判字段里残留的**退役写面**（#5247）—— 工具名 / 已删写 action，残留即红。"""
    return sorted((_declared_machine_tools(case) | _declared_machine_actions(case))
                  & RETIRED_WRITE_SURFACE)


def _retired_db_verify_tokens(case: dict) -> list:
    """`db_verify` 里残留的、只可能由已删除写 action 产生的断言 token（#5247）。"""
    text = json.dumps(case.get("db_verify") or [], ensure_ascii=False)
    return sorted(t for t in RETIRED_DB_VERIFY_TOKENS if t in text)


def _runner():
    """加载 runner（同 `test_eval_debug_permissions_precondition.py` 的做法）。"""
    path = REPO_ROOT / "tests" / "agent_eval" / "local_runner.py"
    spec = importlib.util.spec_from_file_location("local_runner_precond_pitem", path)
    assert spec and spec.loader, f"无法加载 runner: {path}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestTypeIsImplemented:

    def test_type_is_registered(self):
        assert TYPE_NAME in _runner()._PRECONDITION_TYPES, (
            f"`{TYPE_NAME}` 不在 runner 的 `_PRECONDITION_TYPES` ⇒ 声明了没人实现的 type，"
            "`check_precondition_declared` 会报 config_error（用例带一个不生效的守卫跑）"
        )

    def test_declared_type_passes_static_check(self):
        spec = [{"type": TYPE_NAME, "source": "打孔", "expect": 1}]
        assert _runner().check_precondition_declared(spec) == []

    def test_unknown_type_still_fail_closed(self):
        """兜底分支不得被放宽：未知 type 必须继续报错。"""
        bad = _runner().check_precondition_declared([{"type": "no_such_type", "source": "x"}])
        assert bad and "没有实现" in bad[0]

    def test_capture_shape_collects_the_source(self):
        """`precondition_capture_shape` 必须收得到本类型的 source（否则运行期不取基线 = 空跑）。"""
        shape = _runner().precondition_capture_shape(
            [{"type": TYPE_NAME, "source": "打孔", "expect": 1}])
        assert shape.get(TYPE_NAME) == ["打孔"]


class TestProbeCounting:
    """探针读数（纯函数口径）：三种结局都可判，读不出 = 失败关闭。"""

    def _probe_with_items(self, monkeypatch, items, keyword="打孔"):
        lr = _runner()

        class _Resp:
            def __init__(self, body):
                self._body = body

            def json(self):
                return self._body

        class _Client:
            def __init__(self, *a, **kw):
                return None

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, **kw):
                assert "processing-items" in url, f"探针必须打加工项端点，实际 {url}"
                assert kw.get("params", {}).get("keyword") == keyword, (
                    f"探针必须按关键词检索，实际 params={kw.get('params')}")
                return _Resp({"data": {"items": items}})

        monkeypatch.setattr(lr.httpx, "AsyncClient", _Client)
        monkeypatch.setattr(lr, "_admin_headers", lambda token: {})
        monkeypatch.setattr(lr, "_safe_json", lambda r, default: r.json())
        return asyncio.run(lr._probe_processing_item_count("tok", keyword))

    def test_counts_only_name_substring_hits(self, monkeypatch):
        """服务端是模糊匹配 ⇒ 客户端必须只留**名字真的含关键词**的项（口径同商品版）。"""
        n = self._probe_with_items(monkeypatch, [
            {"name": "打孔", "status": "active"},
            {"name": "纳米圈加厚", "status": "inactive"},   # 不含关键词「打孔」⇒ 不计
            # ⚠️ #4572：关键词由「纳米圈打孔」改名「打孔」后，旧诱饵「打孔（纳米圈）加厚」
            #    变成**真的含**关键词 ⇒ 判别性失效（诱饵必须真的不含关键词才算诱饵）
        ])
        assert n == 1

    def test_status_is_not_part_of_the_count(self, monkeypatch):
        """**不按 status 计**：停用（inactive）后件数必须**不变** —— 否则本用例的正常写动作
        会被判成「前置漂移」（假红）。判别性：把 `status == active` 加进过滤 ⇒ 本条红。"""
        active = self._probe_with_items(monkeypatch, [{"name": "打孔", "status": "active"}])
        inactive = self._probe_with_items(monkeypatch, [{"name": "打孔", "status": "inactive"}])
        assert active == inactive == 1

    def test_duplicate_fixture_is_visible(self, monkeypatch):
        """同名副本 >1 ⇒ 读数 >1（`expect: 1` 会判「前置本就不成立」）。"""
        assert self._probe_with_items(monkeypatch, [
            {"name": "打孔", "status": "active"},
            {"name": "打孔", "status": "active"},
        ]) == 2

    def test_empty_keyword_is_none_not_zero(self):
        """空关键词 ⇒ `None`（fail-closed：不取真值**不得**退化成 0 —— 0 会被读成「夹具没了」）。"""
        assert asyncio.run(_runner()._probe_processing_item_count("tok", "")) is None

    def test_request_failure_is_none_not_zero(self, monkeypatch):
        """请求异常 ⇒ `None`（同上：环境层问题不得伪装成「前置不成立」）。"""
        lr = _runner()

        class _Boom:
            def __init__(self, *a, **kw):
                return None

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, *a, **kw):
                raise RuntimeError("connection refused")

        monkeypatch.setattr(lr.httpx, "AsyncClient", _Boom)
        monkeypatch.setattr(lr, "_admin_headers", lambda token: {})
        assert asyncio.run(lr._probe_processing_item_count("tok", "打孔")) is None


class TestCaseDeclarationStillThere:
    """防「把前置删掉让门禁变绿」：用例侧的声明必须还在（且是那条真前置）。"""

    def test_pp_008_declares_the_precondition(self):
        cases = {c["id"]: c for c in load_case_dicts(REPO_ROOT / ".github" / "cases")}
        case = cases["PP-008"]
        specs = [s for s in (case.get("precondition") or []) if isinstance(s, dict)]
        assert specs, "PP-008 的加工项前置声明消失了（基线格被拆掉 = 判据放宽）"
        spec = specs[0]
        assert spec.get("type") == TYPE_NAME, f"PP-008 的前置类型被换掉：{spec}"
        assert spec.get("source") == "打孔", f"PP-008 的前置定位键被改掉：{spec}"
        assert int(spec.get("expect")) == 1, f"PP-008 的基线期望被改掉（放宽）：{spec}"
        # ── 断言面：**原口径**「不得被这次缴费动过（只增前置）」= expectations / must_succeed /
        #    output_verify 三条都必须非空。**为什么前提被 #5247 证伪**：PP-008 的写 action
        #    `toggle_item_status` 已随「B 端只读化」从源码删除（`processing_item_manage` 从 B 端
        #    全部 skill 解绑）⇒ 用例按新机制改判到**只读**路径 `processing_item_query`；原来的
        #    `must_succeed(action=toggle_item_status)` / `required_args(item_id,status)` /
        #    `output_verify(status=inactive)` 三条写声明**悬空**（指向不存在的 action），
        #    而 CI 的 action 绑定判据会把悬空声明判为阻塞 ⇒ 它们**被判据要求清空**：
        #    清空是改判的**结果**，不是放宽。
        # 新口径（等效/更强，两条都在）：
        #   ① `expectations` 仍必须非空（改判到只读路径，不得退化成"什么都不断言"）；
        #   ② 机器可判字段里**不得残留任何退役写面**（已解绑写工具 / 已删写 action）——
        #      把"把退役当放宽、留着写声明蒙混"这条路径关掉。
        assert case.get("expectations"), "PP-008 的 expectations 消失（改判不得退化成不断言）"
        tools = _declared_machine_tools(case)
        assert "processing_item_query" in tools, (
            f"PP-008 没改判到存活的只读路径 processing_item_query：{sorted(tools)}")
        leaks = _retired_write_leaks(case)
        assert leaks == [], (
            f"PP-008 的机器可判字段里残留了退役写面 {leaks} ⇒ 写声明悬空"
            "（#5247 已删除该 action；悬空声明会被 CI 的 action 绑定判据阻塞）")

    def test_retired_write_leak_check_is_not_vacuous(self):
        """**判别力自证**（防空断言）：合成一条仍带着 #5247 退役写面的用例 ⇒ 检查器必红。

        为什么要有这一条：上面两句在**当前用例库**上都是"空集 == 空集"式的通过，
        少了它，检查器哪天失效（正则写坏 / 字段名漂移）不会有任何东西变红。
        """
        fake = {"id": "FAKE-LEAK",
                "expectations": [{"tool": "processing_item_query"}],
                "must_succeed": [{"tool": "processing_item_manage",
                                  "action": "toggle_item_status"}],
                "db_verify": [{"tool": "after_sales_ticket", "expect_status": "closed",
                               "expect": {"closedAt": "__nonnull__", "closeReason": "客户要求"}}]}
        leaks = _retired_write_leaks(fake)
        assert {"processing_item_manage", "toggle_item_status"} <= set(leaks), leaks
        assert _retired_db_verify_tokens(fake), (
            "`db_verify` 里 `status=closed` / `closedAt` / `closeReason` 这类"
            "「只可能由已删除写 action 产生」的断言没被认出来")


class TestAftersalesTicketType:
    """售后工单存在性前置（AS-004）：按**工单号**计数，**只读**，取不到 = fail-closed。"""

    TYPE = "aftersales_ticket_count_for_ticket_no"

    def test_type_is_registered(self):
        assert self.TYPE in _runner()._PRECONDITION_TYPES, (
            f"`{self.TYPE}` 不在 runner 的 `_PRECONDITION_TYPES` ⇒ 声明了没人实现的 type")

    def test_declared_type_passes_static_check(self):
        spec = [{"type": self.TYPE, "source": "AS-20260914-9001", "expect": 1}]
        assert _runner().check_precondition_declared(spec) == []

    def test_capture_shape_collects_the_source(self):
        shape = _runner().precondition_capture_shape(
            [{"type": self.TYPE, "source": "AS-20260914-9001"}])
        assert shape.get(self.TYPE) == ["AS-20260914-9001"]

    def test_empty_ticket_no_is_none(self):
        """空工单号 ⇒ `None`（不取真值不得退化成 0）。"""
        assert asyncio.run(_runner()._probe_aftersales_ticket_count("")) is None

    def test_missing_asyncpg_is_none_not_zero(self, monkeypatch):
        """`asyncpg` 不可用（CI 的 ci-workflow-tests job 就不装）⇒ `None`，**不得**当成 0。"""
        import builtins
        real_import = builtins.__import__

        def _boom(name, *a, **kw):
            if name == "asyncpg":
                raise ImportError("no asyncpg in this job")
            return real_import(name, *a, **kw)

        monkeypatch.setattr(builtins, "__import__", _boom)
        assert asyncio.run(_runner()._probe_aftersales_ticket_count("AS-20260914-9001")) is None

    def test_as_004_declares_the_precondition(self):
        cases = {c["id"]: c for c in load_case_dicts(REPO_ROOT / ".github" / "cases")}
        case = cases["AS-004"]
        specs = [s for s in (case.get("precondition") or []) if isinstance(s, dict)]
        assert specs, "AS-004 的工单前置声明消失了（基线格被拆掉 = 判据放宽）"
        spec = specs[0]
        assert spec.get("type") == self.TYPE, f"AS-004 的前置类型被换掉：{spec}"
        assert spec.get("source") == "AS-20260914-9001", f"AS-004 的定位键被改掉：{spec}"
        assert int(spec.get("expect")) == 1, f"AS-004 的基线期望被改掉（放宽）：{spec}"
        # `expectations` / `pre_clean` 非空：**原样保留**（只读改判不等于"什么都不断言"）。
        assert case.get("expectations"), "AS-004 的 expectations 消失"
        assert case.get("pre_clean"), "AS-004 的 pre_clean 消失"
        # ── `db_verify`：**原口径**「db_verify 不得消失」（非空）。**为什么前提被 #5247 证伪**：
        #    AS-004 已改判为**只读** `after_sales_manage(action=list)`（写 action `update_status`
        #    已从源码删除）⇒ 原 `db_verify[after_sales_ticket, expect_status=closed]`
        #    （`status=closed` / `closedAt` / `closeReason`）只可能由那条写 action 产生，
        #    保留它 = **每次跑都固定的假红**：核对器只认带 `ticket_id` 的**成功载荷**，
        #    而 `list` 的载荷是 `{items, total}` ⇒ fail-closed 会恒报「找不到成功调用」。
        #    所以"整条退役"是改判的**结果**，不是放宽。
        # 新口径（更强）：`db_verify` **不得**再声明已删除的写面 —— 残留才红。
        assert _retired_db_verify_tokens(case) == [], (
            f"AS-004 的 db_verify 仍声明着已删除的写面（只读改判后它恒为假红）："
            f"{json.dumps(case.get('db_verify'), ensure_ascii=False)}")
        leaks = _retired_write_leaks(case)
        assert leaks == [], f"AS-004 的机器可判字段里残留了退役写面：{leaks}"
        # ── **新增正向断言**：「改判到存活只读路径」这件事本身要有机钉住（防止有人把它悄悄
        #    改成别的）；并用 taxonomy（本仓"写"判定的唯一源）证明该 action 确实是**读**。
        got = [(str(s.get("tool") or ""), str((s.get("args") or {}).get("action") or ""))
               for s in (case.get("expectations") or []) if isinstance(s, dict)]
        assert got == [("after_sales_manage", "list")], (
            f"AS-004 的 expectations 不再是只读 `after_sales_manage(action=list)`：{got}")
        assert not assertion_taxonomy.is_write_expectation("after_sales_manage", {"action": "list"}), (
            "`after_sales_manage(action=list)` 被判成写期望了 —— 「改判到只读路径」的前提不成立")
