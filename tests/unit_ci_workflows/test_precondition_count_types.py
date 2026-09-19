# case_ids: PP-008, AS-004
"""**计数型前置自断言**（`processing_item_count_for_keyword` / `aftersales_ticket_count_for_ticket_no`）的 L0 守卫（issue #4527）。

## 为什么必须有（同族病灶 = `PG-013` / `CU-003` 的归因污染）

PP-008 的写动作是「停用种子加工项 `pi_eval_punch`（名字「纳米圈打孔」）」。它依赖的**真前置**
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
"""

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / ".github") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / ".github"))

from render_cases import load_case_dicts  # noqa: E402

TYPE_NAME = "processing_item_count_for_keyword"


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
        spec = [{"type": TYPE_NAME, "source": "纳米圈打孔", "expect": 1}]
        assert _runner().check_precondition_declared(spec) == []

    def test_unknown_type_still_fail_closed(self):
        """兜底分支不得被放宽：未知 type 必须继续报错。"""
        bad = _runner().check_precondition_declared([{"type": "no_such_type", "source": "x"}])
        assert bad and "没有实现" in bad[0]

    def test_capture_shape_collects_the_source(self):
        """`precondition_capture_shape` 必须收得到本类型的 source（否则运行期不取基线 = 空跑）。"""
        shape = _runner().precondition_capture_shape(
            [{"type": TYPE_NAME, "source": "纳米圈打孔", "expect": 1}])
        assert shape.get(TYPE_NAME) == ["纳米圈打孔"]


class TestProbeCounting:
    """探针读数（纯函数口径）：三种结局都可判，读不出 = 失败关闭。"""

    def _probe_with_items(self, monkeypatch, items, keyword="纳米圈打孔"):
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
            {"name": "纳米圈打孔", "status": "active"},
            {"name": "打孔（纳米圈）加厚", "status": "inactive"},   # 不含完整关键词 ⇒ 不计
        ])
        assert n == 1

    def test_status_is_not_part_of_the_count(self, monkeypatch):
        """**不按 status 计**：停用（inactive）后件数必须**不变** —— 否则本用例的正常写动作
        会被判成「前置漂移」（假红）。判别性：把 `status == active` 加进过滤 ⇒ 本条红。"""
        active = self._probe_with_items(monkeypatch, [{"name": "纳米圈打孔", "status": "active"}])
        inactive = self._probe_with_items(monkeypatch, [{"name": "纳米圈打孔", "status": "inactive"}])
        assert active == inactive == 1

    def test_duplicate_fixture_is_visible(self, monkeypatch):
        """同名副本 >1 ⇒ 读数 >1（`expect: 1` 会判「前置本就不成立」）。"""
        assert self._probe_with_items(monkeypatch, [
            {"name": "纳米圈打孔", "status": "active"},
            {"name": "纳米圈打孔", "status": "active"},
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
        assert asyncio.run(lr._probe_processing_item_count("tok", "纳米圈打孔")) is None


class TestCaseDeclarationStillThere:
    """防「把前置删掉让门禁变绿」：用例侧的声明必须还在（且是那条真前置）。"""

    def test_pp_008_declares_the_precondition(self):
        cases = {c["id"]: c for c in load_case_dicts(REPO_ROOT / ".github" / "cases")}
        case = cases["PP-008"]
        specs = [s for s in (case.get("precondition") or []) if isinstance(s, dict)]
        assert specs, "PP-008 的加工项前置声明消失了（基线格被拆掉 = 判据放宽）"
        spec = specs[0]
        assert spec.get("type") == TYPE_NAME, f"PP-008 的前置类型被换掉：{spec}"
        assert spec.get("source") == "纳米圈打孔", f"PP-008 的前置定位键被改掉：{spec}"
        assert int(spec.get("expect")) == 1, f"PP-008 的基线期望被改掉（放宽）：{spec}"
        # 断言面不得被这次缴费动过（只增前置）
        assert case.get("expectations"), "PP-008 的 expectations 消失"
        assert case.get("must_succeed"), "PP-008 的 must_succeed 消失"
        assert case.get("output_verify"), "PP-008 的 output_verify 消失"


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
        # 断言面不得被这次缴费动过（只增前置）
        assert case.get("expectations"), "AS-004 的 expectations 消失"
        assert case.get("db_verify"), "AS-004 的 db_verify 消失"
        assert case.get("pre_clean"), "AS-004 的 pre_clean 消失"
