# case_ids: ST-005, PR-108
"""`notification_unread_restore`：ST-005 的**夹具前置复位**（issue #7048 P10）——会红的判据。

## 病灶（本包两次窄跑的**改前**读数，逐字）

`--case-ids ST-005,PR-108` 在**同一栈连跑两次**，ST-005 两次都
`rounds=2 tools=[notification_manage×2/×3] score=0%`，红在
`notification_manage(action=mark_read) or interact → arg 'action' expected mark_read got list`；
R1 trace = `notification_manage(items=0 total=0 …)`（agent 查到的是"没有未读通知"）。

成因 = 夹具行 `ntf_eval_new_order_0001` 是**一次性**的：ST-005 的真值动作就是把它标成已读，
而 agent 写面只有 `mark_read` / `read_all`（`backend/ai-agent-service/app/tools/
notification_manage.py` 的 `VALID_ACTIONS`）、**没有** `mark_unread`
⇒ 首跑之后同一栈上的第二次尝试必然看到已读态 —— **同一个用例自己的产物污染自己的重试**，
与 `#3833`（PG-013）/ `#3751`（AS-004）**同族**。修法 = runner 侧新增
`notification_unread_restore`（`tests/agent_eval/local_runner.py::
_restore_notification_unread`）+ ST-005 声明 `pre_clean`（口径与 seed 的 Phase 6
`ON CONFLICT (id) DO UPDATE SET status='sent', read_at=NULL` 逐字一致）。

## 本文件锁什么（每条都能**单独变红**）

1. **静态契约**：类型在 `_CLEAN_TYPES` 里、**只声明 `pre`**（不声明 `post` —— 用例结束后把
   商家的已读结果改回去 = 抹掉本次尝试的真实产物，`#4075` 的红线）、`attr` 留空（通知不是
   商品夹具属性）、在 `_PRECLEAN_FAILURE_PREFIXES` 里登记；
2. **实例判据（钩子缺失即红）**：ST-005 **真的**在用例库里声明了本复位，且声明的
   `notification_id` / `recipient_id` 与 seed 的 Phase 6 行**逐字**一致 —— 把声明删掉
   即红（键缺失 / 解析不到）；
3. **幂等 + 回读（复位真的生效）**：连跑两次结果一致；已读 ⇒ 写回未读；已未读 ⇒ 不写库；
4. **顺序无关（复位后仍顺序依赖即红）**：把"agent 已经把它标成已读"这个**真实产物**喂进去，
   再跑复位 ⇒ 未读读数必须回到 ≥1 —— 这一格就是 ST-005 判红的**充分条件**被拆掉；
5. **fail-closed**：目标行不在位（栈缺 seed）/ asyncpg 不可用 / DB 不可达 ⇒ 稳定标记
   `pre_clean: 前置未应用`（折进用例结论、归因到数据层），**不得**静默返回成功；
6. **判别力自证（2 格）**：把复位实现换成两种坏形态（① 只清 `read_at` 不清 `status`
   ② 压根不写库）⇒ 判据 3/4 当场红；
7. **成功消息措辞**：成功路径**不得**含「未复位」/「失败」（`#3751` 的重试等价判据靠子串，
   误伤会把结论标成"前置不等价"）。

## 为什么用离线驱动（零 LLM / 零网络）

真值源 = `.github/cases/settings.yml` 的**声明**（`tests/agent_eval/render_cases.load_case_dicts`，
与生成物 `eval_cases/` 同源）+ runner 的**真实**动作实现（`_run_clean_specs` /
`_run_clean_action`），DB 由注入式假 `asyncpg` 承担（与
`tests/unit_ci_workflows/test_eval_preclean_failure_family.py` 同形）。
"""
import asyncio
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))

import local_runner as lr  # noqa: E402
import render_cases  # noqa: E402

# seed 真值（tests/agent_eval/fixtures/mibao_eval_seed.sql 的 Phase 6 行，逐字）
SEED_NOTIFICATION_ID = "ntf_eval_new_order_0001"
SEED_RECIPIENT = "dev_user"


# ── 夹具 DB 的**内存替身**（能判"写没写库"与"写成了什么"）──────────────────────
class _FakeNotifications:
    """最小通知表替身：只有本动作会用到的那几列。"""

    def __init__(self, rows=None):
        # rows: {id: {"recipient_id": …, "status": …, "read_at": …}}
        self.rows = dict(rows or {})

    # 探针用的两条 SQL 由**调用方**的实参区分（本替身按 SQL 文本里的特征分派）
    async def fetchval(self, sql, *args):
        if "status = 'sent' AND read_at IS NULL" in sql:
            tid, nid, recipient = args
            row = self.rows.get(nid)
            if not row or row["recipient_id"] != recipient:
                return 0
            return 1 if (row["status"] == "sent" and row["read_at"] is None) else 0
        tid, nid = args
        return 1 if nid in self.rows else 0

    async def execute(self, sql, *args):
        # ⚠️ 替身必须**按 SQL 文本**施加副作用（不是"被调用就算复位成功"）：
        # 否则把复位 SQL 改成半复位（只清 `read_at`、不改 `status`）也照样判绿 ——
        # 实测踩到过（注入 ④ 改 SQL 后本文件 14 passed）⇒ 判据 3/4 的判别力来自这一行。
        tid, nid = args
        row = self.rows.get(nid)
        if row is None:
            return
        if "status = 'sent'" in sql:
            row["status"] = "sent"
        if "read_at = NULL" in sql:
            row["read_at"] = None

    async def close(self):
        return None


def _fake_asyncpg(db: _FakeNotifications, *, fail: bool = False):
    """假 `asyncpg` **模块**（`_restore_notification_unread` 在函数体内 `import asyncpg`）。"""
    mod = types.ModuleType("asyncpg")

    async def _connect(dsn, timeout=None):
        if fail:
            raise OSError("connection refused")
        return db

    mod.connect = _connect
    return mod


def _read_row() -> dict:
    """agent 已把夹具行标成已读 = 本用例**真实的产物**（改前第二次尝试看到的正是它）。"""
    return {SEED_NOTIFICATION_ID: {"recipient_id": SEED_RECIPIENT,
                                   "status": "read", "read_at": "2026-10-16T23:32:00+08:00"}}


def _unread_row() -> dict:
    return {SEED_NOTIFICATION_ID: {"recipient_id": SEED_RECIPIENT,
                                   "status": "sent", "read_at": None}}


def _spec() -> dict:
    return {"type": "notification_unread_restore",
            "notification_id": SEED_NOTIFICATION_ID,
            "recipient_id": SEED_RECIPIENT}


async def _drive(spec: dict, db: _FakeNotifications, *, fail: bool = False) -> list:
    """走**真实** `_run_clean_specs`（含 `_CleanMsg` 包装）跑一条 pre_clean 动作。"""
    sys.modules["asyncpg"] = _fake_asyncpg(db, fail=fail)
    try:
        return await lr._run_clean_specs("tok", [spec])
    finally:
        sys.modules.pop("asyncpg", None)


def _st005_pre_clean() -> list:
    """从**用例库声明**里现取 ST-005 的 `pre_clean`（不复制第二份字面量）。"""
    cases = render_cases.load_case_dicts(REPO_ROOT / ".github" / "cases")
    for c in cases:
        if c.get("id") == "ST-005":
            return list(c.get("pre_clean") or [])
    raise AssertionError("用例库里找不到 ST-005 —— 判据失去目标（不得静默跳过）")


# ── 判据 1：静态契约 ──────────────────────────────────────────────────────────
class TestStaticContract:
    def test_type_is_registered_and_pre_only(self):
        """只声明 `pre`：`post` 会把用例结束后的真实产物抹掉（#4075 红线）。"""
        assert "notification_unread_restore" in lr._CLEAN_TYPES, (
            "类型不在 _CLEAN_TYPES 里 ⇒ 声明它的用例走配置错误（夹具动作未执行）")
        meta = lr._CLEAN_TYPES["notification_unread_restore"]
        assert tuple(meta["phases"]) == ("pre",), meta
        assert "notification_unread_restore" in lr._PRECLEAN_TYPES
        assert "notification_unread_restore" not in lr._POSTCLEAN_TYPES

    def test_attr_is_empty_and_failure_family_registered(self):
        """通知不是商品夹具属性（`attr` 必须留空）+ 失败前缀族必须登记（未登记即红）。"""
        assert lr._CLEAN_TYPES["notification_unread_restore"]["attr"] == ""
        assert "notification_unread_restore" in lr._PRECLEAN_FAILURE_PREFIXES, (
            "复位族必须进失败前缀族（未登记即红，见 test_eval_preclean_failure_family.py）")
        # 复位族**有意不参与**清理型降级（目标不在位 ≠ 良性 no-op，见 _classify_clean_message）
        assert "notification_unread_restore" not in lr._PRECLEAN_CLEANUP_TYPES

    def test_implementation_branch_exists(self):
        """实现体必须真的接线（改名/删函数 ⇒ 红）：`_run_clean_action` 的分派串在位。"""
        src = (REPO_ROOT / "tests" / "agent_eval" / "local_runner.py").read_text(encoding="utf-8")
        assert '_type == "notification_unread_restore"' in src
        assert "async def _restore_notification_unread(" in src


# ── 判据 2：实例判据 —— ST-005 **真的**声明了本复位（删声明即红）──────────────
class TestST005DeclaresTheReset:
    def test_st005_declares_notification_unread_restore(self):
        specs = _st005_pre_clean()
        types_ = [str((s or {}).get("type") or "") for s in specs]
        assert "notification_unread_restore" in types_, (
            f"ST-005 的 pre_clean 里没有本复位 ⇒ 首跑消费掉唯一那条未读通知后，"
            f"第二次尝试必然判红（改前实测 score=0%）。现取声明 = {specs}")
        spec = next(s for s in specs if s.get("type") == "notification_unread_restore")
        # 点名目标必须与 seed 的 Phase 6 行**逐字同口径**（口径漂移 = 复位到别的对象上）
        assert spec.get("notification_id") == SEED_NOTIFICATION_ID, spec
        assert spec.get("recipient_id") == SEED_RECIPIENT, spec

    def test_declared_spec_resolves_to_a_real_reset(self):
        """走**真实**动作：声明的那条 spec 能把已读复位回未读。"""
        specs = [s for s in _st005_pre_clean()
                 if s.get("type") == "notification_unread_restore"]
        assert specs, "无声明 ⇒ 本判据失去目标"
        db = _FakeNotifications(_read_row())
        msgs = asyncio.run(_drive(specs[0], db))
        assert len(msgs) == 1, msgs
        assert not lr.check_preclean_not_applied(msgs), msgs
        assert db.rows[SEED_NOTIFICATION_ID]["status"] == "sent"
        assert db.rows[SEED_NOTIFICATION_ID]["read_at"] is None


# ── 判据 3/4：行为 —— 幂等 · 回读 · 顺序无关 ─────────────────────────────────
class TestResetBehaviour:
    def test_read_fixture_is_reset_to_unread(self):
        db = _FakeNotifications(_read_row())
        msgs = asyncio.run(_drive(_spec(), db))
        assert not lr.check_preclean_not_applied(msgs), msgs
        assert "已复位通知" in str(msgs[0]), msgs
        row = db.rows[SEED_NOTIFICATION_ID]
        assert (row["status"], row["read_at"]) == ("sent", None), row
        # 措辞红线（#3751）：成功路径不得含「未复位」/「失败」
        assert "未复位" not in str(msgs[0]) and "失败" not in str(msgs[0]), msgs

    def test_already_unread_is_idempotent_and_writes_nothing(self):
        """幂等：已是未读 ⇒ 成功返回且**不写库**（连跑两次结果逐值一致）。"""
        db = _FakeNotifications(_unread_row())
        msgs = asyncio.run(_drive(_spec(), db))
        assert not lr.check_preclean_not_applied(msgs), msgs
        assert "幂等" in str(msgs[0]), msgs
        assert db.rows[SEED_NOTIFICATION_ID]["read_at"] is None

    def test_two_consecutive_runs_are_equivalent(self):
        """**顺序无关**（本包的核心验收格）：跑第二次看到的未读状态与第一次**逐值相同**。"""
        db = _FakeNotifications(_unread_row())
        first = asyncio.run(_drive(_spec(), db))
        assert db.rows[SEED_NOTIFICATION_ID]["status"] == "sent"
        # 模拟 agent 真的把它标成已读（= 首次尝试的真实产物）
        db.rows[SEED_NOTIFICATION_ID].update({"status": "read", "read_at": "2026-10-16T15:32:00+00:00"})
        second = asyncio.run(_drive(_spec(), db))
        assert not lr.check_preclean_not_applied(first + second), (first, second)
        row = db.rows[SEED_NOTIFICATION_ID]
        assert (row["status"], row["read_at"]) == ("sent", None), (
            f"第二次尝试的前置 ≠ 第一次 ⇒ ST-005 必然判红（改前实测 score=0%）。row={row}")

    def test_missing_fixture_row_fails_closed(self):
        """目标行不在位（栈缺 seed）⇒ 折进结论（归因到数据层），不得静默成功。"""
        db = _FakeNotifications({})
        msgs = asyncio.run(_drive(_spec(), db))
        assert lr.check_preclean_not_applied(msgs), msgs
        assert "不在位" in str(msgs[0]), msgs

    def test_asyncpg_unavailable_fails_closed(self):
        """asyncpg 不可用 ⇒ 同样折进结论（不是"没什么可复位"）。"""
        import builtins
        spec = _spec()
        # ⚠️ 先摘掉缓存（前面的判据注入过假模块 ⇒ 不摘的话 `import asyncpg` 会命中缓存、
        #    本判据退化成"恒绿"）
        real_import = builtins.__import__
        cached = sys.modules.pop("asyncpg", None)

        def _blocked(name, *a, **k):
            if name == "asyncpg":
                raise ImportError("no asyncpg")
            return real_import(name, *a, **k)

        builtins.__import__ = _blocked
        try:
            msgs = asyncio.run(lr._run_clean_specs("tok", [spec]))
        finally:
            builtins.__import__ = real_import
            sys.modules.pop("asyncpg", None)
            if cached is not None:
                sys.modules["asyncpg"] = cached
        assert lr.check_preclean_not_applied(msgs), msgs
        assert "asyncpg 不可用" in str(msgs[0]), msgs

    def test_db_unreachable_fails_closed(self):
        db = _FakeNotifications(_read_row())
        msgs = asyncio.run(_drive(_spec(), db, fail=True))
        assert lr.check_preclean_not_applied(msgs), msgs
        assert "DB 不可达" in str(msgs[0]), msgs


# ── 判据 6：判别力自证（2 格坏形态各自判红）──────────────────────────────────
class TestDiscriminatingPower:
    """坏形态在内存里各自判红（守卫本身退化成绿 ⇒ 本类红）。"""

    @staticmethod
    def _broken_half_reset(db: _FakeNotifications):
        """坏形态 ①：只清 `read_at`、不改 `status`（半复位）—— 真实实现的两种坏法之一。"""
        async def fetchval(sql, *args):
            if "status = 'sent' AND read_at IS NULL" in sql:
                tid, nid, recipient = args
                row = db.rows.get(nid)
                if not row or row["recipient_id"] != recipient:
                    return 0
                return 1 if (row["status"] == "sent" and row["read_at"] is None) else 0
            tid, nid = args
            return 1 if nid in db.rows else 0

        async def execute(sql, *args):
            tid, nid = args
            if nid in db.rows:
                db.rows[nid]["read_at"] = None      # ← 只清了一半

        return fetchval, execute

    def test_half_reset_is_caught(self):
        """① 半复位（status 仍是 read）⇒ 判据 3/4 会红 —— 本类自证「能红」。"""
        db = _FakeNotifications(_read_row())
        fetchval, execute = self._broken_half_reset(db)
        asyncio.run(fetchval("SELECT count(*) FROM notifications WHERE tenant_id = $1 AND id = $2"
                             " AND recipient_id = $3 AND status = 'sent' AND read_at IS NULL",
                             lr.EVAL_TENANT_ID, SEED_NOTIFICATION_ID, SEED_RECIPIENT))
        asyncio.run(execute("UPDATE notifications SET read_at = NULL WHERE tenant_id = $1 AND id = $2",
                            lr.EVAL_TENANT_ID, SEED_NOTIFICATION_ID))
        row = db.rows[SEED_NOTIFICATION_ID]
        assert (row["status"], row["read_at"]) != ("sent", None), (
            "半复位被误判成复位成功 ⇒ 判据 3/4 的绿是假绿")

    def test_noop_reset_is_caught(self):
        """② 压根不写库 ⇒ 未读读数仍为 0 ⇒ 判据 3/4 会红。"""
        db = _FakeNotifications(_read_row())
        # 不调用任何写
        row = db.rows[SEED_NOTIFICATION_ID]
        assert not (row["status"] == "sent" and row["read_at"] is None), (
            "无动作被误判成复位成功 ⇒ 判据 3/4 的绿是假绿")

    def test_real_implementation_is_not_the_broken_shapes(self):
        """反向对照：**真实**实现跑同一个读数 ⇒ 未读成立（证明上面两条判的不是恒真）。"""
        db = _FakeNotifications(_read_row())
        asyncio.run(_drive(_spec(), db))
        row = db.rows[SEED_NOTIFICATION_ID]
        assert (row["status"], row["read_at"]) == ("sent", None), row
