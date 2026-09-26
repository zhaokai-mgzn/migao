# case_ids: PG-057
"""加工单过程明细三段夹具（`production_work_logs`）的**真库**判据（issue #4945 处 2 / 承 #4927）。

## 病灶（issue #4945 表格第 2 行）

评测栈对 `production_work_logs` **零 seed** ⇒ PG-057 只能断言「该单报工明细为空、数量与金额全 0」
—— 「合格 / 返工 / 报废数量 + 计件金额」这条**涉钱**读数在评测里**永远不被断言**，计数错了没人知道。
旧登记的阻塞理由是「写三段夹具需要在有 docker 处验证 SQL 可执行，而本机 `docker: command not found`」。

🔴 **那个阻塞理由不成立**（本文件即证据）：真库验证要的是**二进制**而不是容器 ——
`initdb` / `pg_ctl` / `psql` 起一次性集群即可（与 `.github/workflows/pr-check.yml` 的
`ci-workflow-tests` job 走的是同一条路，它会注入 `MIGAO_REQUIRE_REALDB=1`）。

## 本文件钉的四件事（各有红证，互不掩盖）

| # | 判据 | 红证形态 |
|---|---|---|
| 1 | 三段夹具在**真 PG** 上落地：加工单 ×1（`in_processing`）+ 工序实例 ×3（裁剪组 2 / 车位组 1）+ 报工 ×5（normal 3 / rework 1 / scrap 1） | 删掉 Phase 4 任一段 INSERT ⇒ 计数断言红 |
| 2 | 用例 PG-057 声明的数值 == **真库读回的数**（同口径：合格取 `normal` 的 `qualified_qty`，返工/报废各取该笔报工数量，计件 = Σ(合格 × 单价快照 × COALESCE(系数快照,1))） | 夹具里改任一个数值（或在**回滚事务内** `UPDATE` 一行）⇒ 对账断言红 |
| 3 | **同行订单的既有语义不被夹具破坏**：`EVAL-MB-ORD-0002/0003/0004` 在评测栈里**仍然没有加工单**（PG-013/015/016 与「生成加工单」用例的前置靠它） | 把夹具挂到 0003 ⇒ 断言红（且那两条用例会带着假前置跑） |
| 4 | 锚行**被完整消费**：用例侧 `[worklog-seed]` 锚里的键集必须 == 本文件对账的键集（加一个无人对账的数值 ⇒ 红） | 往用例锚里多加一个 `key=value` ⇒ 键集断言红 |

## 边界（如实登记，不冒充已覆盖）

* 本文件判的是「**夹具与用例声明一致 + 夹具真的可执行**」，**不是**服务端 `ProductionService.worklog`
  的实现判据 —— 后者由 `backend/admin-api/src/test/java/com/migao/admin/service/ProductionServiceTest.java`
  覆盖。两边的**口径**必须同源：本文件的 `_READINGS_SQL` 逐条对齐 `aggregate()` 的算法
  （`normal` 才算钱、返工/报废取 `qty` 且不计件、`factor` 为 NULL 时取 1）。
* `price_state='unpriced'`（V90 未定价 ≠ 0 元）那条路径**不在**本夹具内 —— 未覆盖项见 issue #4945。
* 缺 PG 的处置**只许**有一份：`tests/unit_ci_workflows/pg_cluster.py`（CI 判**红** / 本机显式 skip）。

## 真库

一次性集群（`initdb` + `pg_ctl`，随机端口、跑完即停；起/停经 `pg_cluster.start_cluster` /
`stop_cluster` 收口，模块自己**不**拼 `pg_ctl` argv）。建库顺序逐字复刻 mibao persona 的评测栈：
`db/init/schema.sql` → `xiaobu_eval_seed.sql` → `mibao_eval_seed.sql`，每份都 `-v ON_ERROR_STOP=1`
（= `scripts/eval_stack_seed.sh` 的口径 ⇒ 「seed SQL 写错会打挂整个 mibao 套件」这件事在本判据里**当场红**）。
"""
from __future__ import annotations

import re
import shutil
import socket
import subprocess
import tempfile
from decimal import Decimal
from pathlib import Path

import pytest
from unit_ci_workflows import pg_cluster  # noqa: E402  （起/停集群的唯一收口，issue #5263）

REPO = Path(__file__).resolve().parents[2]
SCHEMA = REPO / "backend/admin-api/src/main/resources/db/init/schema.sql"
XIAOBU_SEED = REPO / "tests/agent_eval/fixtures/xiaobu_eval_seed.sql"
MIBAO_SEED = REPO / "tests/agent_eval/fixtures/mibao_eval_seed.sql"
CASES_YML = REPO / ".github/cases/processing-order.yml"

#: 用例侧的**机器可读**声明锚（PG-057 的 `data_checks` 里那一行）。本文件按它取值对账 ——
#: 「用例说 14.5，夹具给 14.50」这类漂移在 CI 上**当场红**，不靠人读散文。
ANCHOR = "[worklog-seed]"
CASE_ID = "PG-057"

#: 夹具挂的**专用**订单（PG-057 的罐头输入点名它）。为什么不挂 0003：见判据 3 与 fixture 注释。
WORKLOG_ORDER_NO = "EVAL-MB-ORD-0007"
#: 同行订单 —— 它们在评测栈里**必须仍然没有加工单**（PG-013/015/016 及「生成加工单」用例的前置）。
SIBLING_ORDER_NOS = ("EVAL-MB-ORD-0002", "EVAL-MB-ORD-0003", "EVAL-MB-ORD-0004")

PROCESSING_ORDER_ID = "po_eval_wl_0007"

#: 本文件对账的数值键（= 用例锚行里**必须恰好**出现的键集，判据 4）。
READING_KEYS = ("qualified_qty", "rework_qty", "scrap_qty", "piecework_amount")

#: 计件金额口径 —— 与 `ProductionService.aggregate()` **同一份算法**：
#: 只算 `work_type='normal'`；金额 = Σ(合格数量 × **报工自己的单价快照** × **系数快照**)；
#: `factor IS NULL` ⇒ 取 1（#4589 起新报工不写该列 ⇒ 快照恒 NULL ⇒ 自然 1×）。
_READINGS_SQL = """
SELECT 'qualified_qty' AS k, COALESCE(sum(qualified_qty), 0)::text AS v
  FROM production_work_logs
 WHERE tenant_id = 1 AND processing_order_id = '{po}' AND deleted = 0 AND work_type = 'normal'
UNION ALL
SELECT 'rework_qty', COALESCE(sum(qty), 0)::text
  FROM production_work_logs
 WHERE tenant_id = 1 AND processing_order_id = '{po}' AND deleted = 0 AND work_type = 'rework'
UNION ALL
SELECT 'scrap_qty', COALESCE(sum(qty), 0)::text
  FROM production_work_logs
 WHERE tenant_id = 1 AND processing_order_id = '{po}' AND deleted = 0 AND work_type = 'scrap'
UNION ALL
SELECT 'piecework_amount',
       COALESCE(sum(qualified_qty * unit_price * COALESCE(factor, 1)), 0)::text
  FROM production_work_logs
 WHERE tenant_id = 1 AND processing_order_id = '{po}' AND deleted = 0 AND work_type = 'normal'
""".format(po=PROCESSING_ORDER_ID)

_ANCHOR_RE = re.compile(r"\[worklog-seed\]")
#: 锚的**声明**形态：data_checks 里以锚开头的那一条（注释里**引用**锚不算声明 —— 否则文档越写越红）
_ANCHOR_DECL_RE = re.compile(r'^\s*-\s*"\[worklog-seed\]')
#: 锚行里的 `key=value`（键只认小写字母与下划线 ⇒ 散文里的 `=` 不会误入）
_KV_RE = re.compile(r"([a-z_]+)=([A-Za-z0-9_.\-]+)")


# ── 用例侧解析（纯文本，零 YAML 依赖：该 job 不保证装了 PyYAML，见 #5170 ①）──

def parse_anchor_line(case_text: str) -> dict:
    """取 PG-057 的锚行 → `{key: value}`。

    ⚠️ 锚**必须恰好声明一次**（判据 2/4 的前提）：没有锚 ⇒ 对账判据是**空跑**
    （`migao-acceptance`：不会红的断言 = 空断言）⇒ 这里直接 fail，而不是返回空 dict
    让下游「恰好相等」。注释里**引用**锚（如「机器对账锚 = 下面那条」）不算声明 ——
    只有 `data_checks` 里以锚开头的那一条算。
    """
    declared = [ln for ln in case_text.splitlines()
                if _ANCHOR_RE.search(ln) and not ln.lstrip().startswith("#")]
    assert len(declared) == 1, (
        f"用例 {CASE_ID} 的 `{ANCHOR}` 锚行必须**恰好声明一次**（注释里引用不算），"
        f"实测 {len(declared)} 处：{declared}")
    assert _ANCHOR_DECL_RE.match(declared[0]), (
        f"锚行形态不对（应为 data_checks 里以 `- \"{ANCHOR}` 开头的一条）：{declared[0]!r}")
    return dict(_KV_RE.findall(declared[0]))


def readings_from_rows(rows: str) -> dict:
    """`psql -t -A` 的 `key|value` 输出 → `{key: Decimal}`。"""
    out = {}
    for line in rows.splitlines():
        line = line.strip()
        if not line:
            continue
        key, _, value = line.partition("|")
        out[key] = Decimal(value)
    return out


# ── 真库夹具（建库顺序逐字复刻 mibao persona 的评测栈）──

class _Pg:
    """一次性集群句柄：`run_file()` 复刻 `eval_stack_seed.sh` 的 `psql -f` + `ON_ERROR_STOP=1`；

    `run()` 走 stdin（一次调用可带 `BEGIN; … ROLLBACK;` ⇒ 注入式红证零残留）。
    """

    def __init__(self, sockdir: Path, port: int, bins: dict[str, str]):
        self.sockdir, self.port, self.bins = sockdir, port, bins

    def _psql(self, args: list[str], **kw) -> subprocess.CompletedProcess:
        return subprocess.run(
            [self.bins["psql"], "-h", str(self.sockdir), "-p", str(self.port),
             "-U", "postgres", "-d", "postgres", "-X", "-q", "-t", "-A",
             "-v", "ON_ERROR_STOP=1", *args],
            text=True, capture_output=True, **kw)

    def run(self, sql: str) -> str:
        proc = self._psql([], input=sql)
        assert proc.returncode == 0, f"psql 失败（ON_ERROR_STOP=1）：\n{proc.stdout}\n{proc.stderr}"
        return proc.stdout

    def run_file(self, path: Path) -> subprocess.CompletedProcess:
        """`-f` + `ON_ERROR_STOP=1` —— 与 `scripts/eval_stack_seed.sh` 打库同款。"""
        return self._psql(["-f", str(path)])

    def scalar(self, sql: str) -> str:
        return self.run(sql).strip()

    def readings(self) -> dict:
        return readings_from_rows(self.run(_READINGS_SQL))


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def seeded_pg(tmp_path_factory, realdb_binaries):
    """临时 PG 集群 + mibao persona 的评测栈种子（缺 PG ⇒ CI 判红 / 本机显式 skip）。"""
    tmp_path = tmp_path_factory.mktemp("pg4945")
    datadir = tmp_path / "pgdata"
    # ⚠️ socket 目录必须**短**：unix socket 路径有 ~104 字节上限，pytest 的 tmp_path 太长 ⇒
    # `pg_ctl start` 直接失败（实测）。故另起一个短前缀的临时目录。
    sockdir = Path(tempfile.mkdtemp(prefix="pg4945-"))
    log = tmp_path / "pg.log"
    port = _free_port()
    pg_cluster.start_cluster(realdb_binaries, datadir, sockdir=sockdir, port=port, log=log)
    pg = _Pg(sockdir, port, realdb_binaries)
    try:
        # 三份都跑 `-f` + `ON_ERROR_STOP=1`：任一份写错 ⇒ 这里当场红（= issue #4945 要堵的形态）
        for path in (SCHEMA, XIAOBU_SEED, MIBAO_SEED):
            proc = pg.run_file(path)
            assert proc.returncode == 0, (
                f"{path.name} 在全新库上 `ON_ERROR_STOP=1` 非零退出（exit={proc.returncode}）"
                f"——评测栈装不起来：\n{proc.stdout}\n{proc.stderr}")
        # 幂等：同一份 seed 再跑一遍必须仍然 exit 0（`eval_stack_seed.sh` 会被重复调用）
        again = pg.run_file(MIBAO_SEED)
        assert again.returncode == 0, f"seed 不幂等：\n{again.stdout}\n{again.stderr}"
        yield pg
    finally:
        pg_cluster.stop_cluster(realdb_binaries["pg_ctl"], datadir)
        shutil.rmtree(sockdir, ignore_errors=True)


# ── 判据 1：三段夹具在真库上落地 ──

def test_three_part_fixture_lands_on_real_postgres(seeded_pg):
    """加工单 ×1 + 工序实例 ×3（裁剪 2 / 车位 1）+ 报工 ×5（normal 3 / rework 1 / scrap 1）。"""
    row = seeded_pg.scalar(f"""
        SELECT count(*)::text || '|' || min(status) || '|' || min(processing_order_no)
          FROM processing_orders
         WHERE tenant_id = 1 AND id = '{PROCESSING_ORDER_ID}' AND deleted = 0;
    """)
    assert row == "1|in_processing|JG-EVAL-0007", f"加工单（第 ① 段）没落地：{row}"

    ops = seeded_pg.scalar(f"""
        SELECT count(*)::text || '|' || count(*) FILTER (WHERE group_name = '裁剪')::text
               || '|' || count(*) FILTER (WHERE group_name = '车位')::text
          FROM processing_position_operations
         WHERE tenant_id = 1 AND processing_order_id = '{PROCESSING_ORDER_ID}' AND deleted = 0;
    """)
    assert ops == "3|2|1", f"工序实例（第 ② 段）与声明不符（总数|裁剪|车位）：{ops}"

    logs = seeded_pg.scalar(f"""
        SELECT count(*)::text || '|' || count(*) FILTER (WHERE work_type = 'normal')::text
               || '|' || count(*) FILTER (WHERE work_type = 'rework')::text
               || '|' || count(*) FILTER (WHERE work_type = 'scrap')::text
          FROM production_work_logs
         WHERE tenant_id = 1 AND processing_order_id = '{PROCESSING_ORDER_ID}' AND deleted = 0;
    """)
    assert logs == "5|3|1|1", f"报工（第 ③ 段）与声明不符（总数|normal|rework|scrap）：{logs}"

    # 报工人 = 夹具里的两个人（用例的 forbidden_text 禁的是**编造**的具名报工人 ⇒ 真值必须在库里）
    # 🔴 **不得**在 SQL 里排序后比字符串：`ORDER BY worker_name` 的次序**随 collation 变**
    # （本机 macOS 的 en_US 与 CI 的 C/POSIX 对中文的次序**相反** ⇒ 同一份数据一边绿一边红。
    # 实测：PR #5632 首轮 CI 唯一红点就是它 —— `assert '王秀兰,陈国强' == '陈国强,王秀兰'`。）
    # ⇒ 取回**集合**，排序交给 Python（按码点，跨环境唯一）。
    workers = sorted(seeded_pg.run(f"""
        SELECT DISTINCT worker_name
          FROM production_work_logs
         WHERE tenant_id = 1 AND processing_order_id = '{PROCESSING_ORDER_ID}' AND deleted = 0;
    """).split())
    assert workers == sorted(["王秀兰", "陈国强"]), f"报工人集合与声明不符：{workers}"

    # 承载订单在位且 confirmed（工具按 order_no 解析订单 ⇒ 订单缺了整条链路查不到）
    order = seeded_pg.scalar(f"""
        SELECT status || '|' || customer_name FROM orders
         WHERE tenant_id = 1 AND order_no = '{WORKLOG_ORDER_NO}' AND deleted = 0;
    """)
    assert order == "confirmed|赵六", f"承载订单 {WORKLOG_ORDER_NO} 与声明不符：{order}"


# ── 判据 2：用例声明的数值 == 真库读回的数（PG-057 的数值断言）──

def test_case_declared_numbers_match_the_seeded_fixture(seeded_pg):
    """PG-057 的 `[worklog-seed]` 锚 ↔ 真库读数**逐值相等**，且锚点的订单就是夹具那张单。"""
    declared = parse_anchor_line(CASES_YML.read_text(encoding="utf-8"))
    assert declared.get("order_no") == WORKLOG_ORDER_NO, (
        f"用例锚点的 order_no={declared.get('order_no')!r} ≠ 夹具挂的 {WORKLOG_ORDER_NO!r}"
        f"——订单换了而夹具没跟（或反之），数值断言会指向另一张单")
    actual = seeded_pg.readings()
    assert {k: Decimal(declared[k]) for k in READING_KEYS} == {k: actual[k] for k in READING_KEYS}, (
        f"用例声明 {declared} ≠ 真库读数 {actual}（口径见 _READINGS_SQL 的注释）")


# ── 判据 3：同行订单的既有语义不被夹具破坏 ──

def test_sibling_orders_still_have_no_processing_order(seeded_pg):
    """0002/0003/0004 **仍然没有加工单** —— PG-013/015/016 与「生成加工单」用例的前置靠它。

    红证：把 Phase 4 的夹具挂到 0003（`order_id = …0003`）⇒ 本断言红；同时那两条用例会因为
    （a）PG-015 逐字要求「无加工单 ⇒ 0%/空工序」（b）「生成加工单」的前置要求「confirmed 且
    **无**加工单」而带着**假前置**跑 —— 这正是本判据要提前拦住的那一类改动。
    """
    rows = seeded_pg.scalar(f"""
        SELECT o.order_no || '=' || count(p.id)::text
          FROM orders o
          LEFT JOIN processing_orders p
                 ON p.order_id = o.id AND p.deleted = 0
         WHERE o.tenant_id = 1 AND o.deleted = 0
           AND o.order_no IN ({', '.join("'" + n + "'" for n in SIBLING_ORDER_NOS)})
         GROUP BY o.order_no ORDER BY o.order_no;
    """)
    # ⚠️ 与报工人那处同因：**不**拿 DB 的排序当真值 —— 比集合（本仓 CI 的 collation 与开发机不同，
    # 见同文件 `test_three_part_fixture_lands_on_real_postgres` 的注释；订单号当前是 ASCII ⇒
    # 两种 collation 次序相同，但把「次序」写进断言等于给未来埋一个跨环境假红）。
    assert sorted(rows.split()) == sorted(f"{n}=0" for n in SIBLING_ORDER_NOS), (
        f"同行订单的加工单数不为 0：{rows!r}（夹具挤占了 PG-013/015/016 的专用订单）")


# ── 判据 4：锚行被完整消费（加一个无人对账的数值 ⇒ 红）──

def test_anchor_keys_are_fully_consumed_by_this_guard():
    """锚里的数值键集 == 本文件对账的键集 ⇒ 不许在用例里加一个「没人对账」的数值。

    红证：往 `[worklog-seed]` 锚里加 `unpriced_qty=0` ⇒ 本断言红（那个数没有任何真库判据背书，
    正是 issue #4945 要消灭的形态：**判据看起来在，实际测不到那一层**）。
    """
    declared = parse_anchor_line(CASES_YML.read_text(encoding="utf-8"))
    extra = set(declared) - set(READING_KEYS) - {"order_no"}
    assert extra == set(), (
        f"锚里出现本文件**不会**对账的键 {sorted(extra)} —— 要么把它加进 READING_KEYS 并落码读数，"
        f"要么从用例挪进散文（未对账的数值 = 空断言）")
    assert set(READING_KEYS) - set(declared) == set(), (
        f"本文件对账的键 {sorted(set(READING_KEYS) - set(declared))} 在用例锚里缺失 —— "
        f"数值断言被删了一半（声明的只有 {sorted(declared)}）")


# ── 判据 2 的注入式红证：真库改一个数 ⇒ 对账必红（在**回滚事务**内做，零残留）──

def test_readings_go_red_when_a_seeded_value_is_wrong(seeded_pg):
    """把夹具里的一笔合格数量改坏（60 → 9），**同一个读数函数**必须报出与用例声明不符。

    形态与 #5190 的「红证 = 手动改一行 ⇒ 同一个读数函数必须报出不一致」一致：
    这里用 `BEGIN … ROLLBACK` ⇒ 注入的那一刻真的在库上生效（读数跟着变），跑完库状态**逐值复原**。
    """
    before = seeded_pg.readings()
    mutated_rows = seeded_pg.run(f"""
        BEGIN;
        UPDATE production_work_logs SET qualified_qty = 9.00
         WHERE tenant_id = 1 AND id = 'pwl_wl_0007_1';
        {_READINGS_SQL};
        ROLLBACK;
    """)
    mutated = readings_from_rows(mutated_rows)
    assert mutated["qualified_qty"] == Decimal("15.50"), (
        f"注入未在库上生效（读数没变 ⇒ 红证是空的）：{mutated}")
    declared = {k: Decimal(v) for k, v in parse_anchor_line(
        CASES_YML.read_text(encoding="utf-8")).items() if k in READING_KEYS}
    assert mutated != declared, "改坏一笔合格数量后读数仍与用例声明相等 ⇒ 对账判据不会红（空断言）"
    # 回滚后逐值复原（否则后续判据/复跑会拿到被污染的库）
    assert seeded_pg.readings() == before, "回滚没把库复原 —— 注入式红证必须零残留"
