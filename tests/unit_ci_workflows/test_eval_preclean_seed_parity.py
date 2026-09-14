# case_ids: AS-004
"""前置复位的定义必须与 **seed 同源**（issue #3751 裁定条件 1）。

为什么单开一条守卫：**"初始状态"只能有一份定义** —— 它的真值来源是
`tests/agent_eval/fixtures/mibao_eval_seed.sql`（评测栈的前置本来就是直连 DB 灌 seed）。
如果 runner 里再手写一份"初始状态"（status/close_reason/closed_at/internal_notes…），
seed 一改两边就漂移：复位会把工单复位到**一个 seed 从没产生过的状态**，
而 `db_verify` 仍按 seed 语义断言 ⇒ 又是一种"数据层制造的红/绿"（本 issue 的形态）。
故本文件从 seed 里**解析**初始态，逐项与 `local_runner._RESET_AFTERSALES_TICKET_SQL` 对齐。

红证（改任一侧即红）：
  · seed 把 `status` 改成 `'processing'` → 复位仍写 `pending` ⇒ 必红；
  · 复位 SQL 去掉 `close_reason = NULL` → 与 seed 的"该列未给值（= NULL）"不一致 ⇒ 必红；
  · seed 的时间线基线 action 改字面量 → 复位的 `action <> '<seed 字面量>'` 不匹配 ⇒ 必红；
  · 复位 SQL 开始改写基线列（id/tenant_id/ticket_no/order_id/created_at…）⇒ 必红。
"""
import re
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SEED_PATH = REPO_ROOT / "tests" / "agent_eval" / "fixtures" / "mibao_eval_seed.sql"
RUNNER_PATH = REPO_ROOT / "tests" / "agent_eval" / "local_runner.py"
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))

# seed 里"关闭态留痕"字段：判定"复位是否真的清了留痕"就看这几个（只回状态不清留痕 =
# db_verify 的 expect_fields_nonempty[closedAt, closeReason] 被首跑残留满足 → 假绿）
CLOSED_STATE_COLUMNS = ("closed_at", "close_reason", "internal_notes")
# seed 的**基线列**：复位只允许改"状态/留痕"，这些一律不得动（否则对象与用例点名脱钩）
BASELINE_COLUMNS = ("id", "tenant_id", "ticket_no", "order_id", "customer_id", "ticket_type",
                    "source", "priority", "description", "refund_amount", "created_at",
                    "deleted")


def _load_runner():
    """导入 `local_runner`（L0 job 只装 pytest+pyyaml → 缺 httpx 时注入最小替身）。"""
    try:
        import httpx  # noqa: F401
    except ImportError:                      # pragma: no cover - 本地 venv 有 httpx
        stub = types.ModuleType("httpx")

        class _AsyncClient:
            def __init__(self, *a, **k):
                raise RuntimeError("httpx 替身：本文件的单测不得真实发起 HTTP")

        stub.AsyncClient = _AsyncClient
        sys.modules.setdefault("httpx", stub)
    import local_runner
    return local_runner


def _seed_text() -> str:
    return SEED_PATH.read_text(encoding="utf-8")


def _split_top_level(s: str) -> list:
    """按**顶层**逗号切分（跳过括号/引号内的逗号）——SQL 值列表用。"""
    out, buf, depth, quote = [], [], 0, ""
    for ch in s:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in "'\"":
            quote = ch
            buf.append(ch)
        elif ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            out.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if "".join(buf).strip():
        out.append("".join(buf).strip())
    return out


def _top_level_tuples(s: str) -> list:
    """取出 `s` 里**顶层**括号包裹的元组内容（跳过嵌套括号/引号）——解析 VALUES 用。

    为什么不能用 `re.findall(r"\\(.*?\\)")`：值里有 `'[]'::jsonb` 这类**嵌套括号**，
    非贪婪正则会停在第一个 `)` → 列数与值数不匹配 → 解析静默跳过该行（守卫形同虚设）。
    """
    out, depth, start, quote = [], 0, None, ""
    for i, ch in enumerate(s):
        if quote:
            if ch == quote:
                quote = ""
            continue
        if ch in "'\"":
            quote = ch
        elif ch == "(":
            if depth == 0:
                start = i + 1
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0 and start is not None:
                out.append(s[start:i])
                start = None
    return out


def _seed_ticket_row(ticket_id: str = "tkt_eval_as_9001") -> dict:
    """解析 seed 里该工单行的**列名 → 值**（缺列 ⇒ 该列为 NULL/默认，不入字典）。

    只认"第一个 INSERT INTO after_sales_tickets 的列清单 + 含该 id 的那条 VALUES 元组"。
    """
    text = _seed_text()
    ins = re.search(r"INSERT INTO after_sales_tickets\s*\((?P<cols>[^)]*)\)\s*VALUES\s*(?P<vals>.*?);",
                    text, re.S)
    if not ins:
        raise AssertionError("seed 里找不到 after_sales_tickets 的 INSERT（本守卫的前提失效）")
    cols = [c.strip() for c in _split_top_level(ins.group("cols")) if c.strip()]
    for raw in _top_level_tuples(ins.group("vals")):
        vals = _split_top_level(raw)
        if len(vals) != len(cols):
            continue
        row = dict(zip(cols, vals))
        if ticket_id in row.get("id", ""):
            return row
    raise AssertionError(f"seed 里找不到工单 {ticket_id} 的行（本守卫的前提失效）")


def _seed_timeline_action() -> str:
    """解析 seed 给该工单插的**建单时间线** action 字面量（复位必须保留它）。"""
    text = _seed_text()
    m = re.search(r"INSERT INTO ticket_timeline\s*\((?P<cols>[^)]*)\)\s*SELECT\s+(?P<vals>.*?)"
                  r"\s+FROM\s+after_sales_tickets", text, re.S)
    if not m:
        raise AssertionError("seed 里找不到 ticket_timeline 的 INSERT…SELECT（前提失效）")
    cols = [c.strip() for c in _split_top_level(m.group("cols")) if c.strip()]
    vals = _split_top_level(m.group("vals"))
    if len(cols) != len(vals):
        raise AssertionError("ticket_timeline 的列数与 SELECT 值数不一致（解析失败）")
    return vals[cols.index("action")].strip()


def _reset_sql(runner) -> str:
    return " ".join(runner._RESET_AFTERSALES_TICKET_SQL.split())


def _set_clause(sql: str) -> str:
    return sql.lower().split(" set ", 1)[1].split(" where ", 1)[0]


class TestSeedIsTheSingleSourceOfTheReset:
    def test_reset_target_is_a_real_seed_ticket(self):
        """复位的默认目标必须是 seed 里真实存在的工单号（不能是凭空写的常量）。"""
        runner = _load_runner()
        seed_row = _seed_ticket_row()
        seed_no = seed_row["ticket_no"].strip().strip("'")
        if runner._SEED_AFTERSALES_TICKET_NO != seed_no:
            raise AssertionError(
                f"复位目标 {runner._SEED_AFTERSALES_TICKET_NO!r} ≠ seed 的 ticket_no {seed_no!r}")

    def test_reset_status_matches_seed(self):
        """复位后的 `status` 必须等于 seed 给的值（seed 是初始状态的唯一真值来源）。"""
        runner = _load_runner()
        seed_status = _seed_ticket_row()["status"].strip()
        set_clause = _set_clause(_reset_sql(runner))
        want = f"status = {seed_status.lower()}"
        if want not in set_clause:
            raise AssertionError(
                f"复位 SQL 的 status 与 seed 不一致（seed={seed_status}）：{set_clause}")

    def test_closed_state_columns_follow_seed(self):
        """关闭态留痕字段：seed **没给值（= NULL）**的，复位必须显式置 NULL（双向一致）。

        这一条是本守卫的核心：只把状态回 pending、留着 closeReason/closedAt，
        会让 `db_verify[after_sales_ticket]` 的 `expect_fields_nonempty` 被**首跑残留**满足。
        """
        runner = _load_runner()
        seed_row = _seed_ticket_row()
        set_clause = _set_clause(_reset_sql(runner))
        for col in CLOSED_STATE_COLUMNS:
            seed_val = seed_row.get(col)
            if seed_val is None:
                if re.search(rf"\b{col} = null\b", set_clause) is None:
                    raise AssertionError(
                        f"seed 未给 {col}（= NULL），复位必须显式置 NULL：{set_clause}")
            else:
                want = f"{col} = {seed_val.strip().lower()}"
                if want not in set_clause:
                    raise AssertionError(
                        f"seed 的 {col}={seed_val} 与复位 SQL 不一致：{set_clause}")

    def test_reset_does_not_touch_seed_baseline_columns(self):
        """复位只改"状态/留痕"，**不得**改写基线列（否则复位对象与用例点名的对象脱钩）。"""
        runner = _load_runner()
        set_clause = _set_clause(_reset_sql(runner))
        touched = [c for c in BASELINE_COLUMNS if re.search(rf"\b{c} =", set_clause)]
        if touched:
            raise AssertionError(f"复位 SQL 改写了 seed 基线列 {touched}：{set_clause}")
        if "ticket_no = $1" not in _reset_sql(runner).lower():
            raise AssertionError(f"复位必须按**被点名的**工单号限定（WHERE ticket_no = $1）："
                                 f"{_reset_sql(runner)}")

    def test_timeline_reset_keeps_the_seed_baseline_action(self):
        """时间线复位必须保留 seed 插的那条基线（字面量从 seed 解析，不硬编码）。"""
        runner = _load_runner()
        action = _seed_timeline_action().strip().strip("'")
        helper_src = Path(RUNNER_PATH).read_text(encoding="utf-8")
        want = f"action <> '{action}'"
        if want not in helper_src:
            raise AssertionError(
                f"时间线复位必须保留 seed 基线 action（期望 {want!r} 出现在 local_runner.py）")
        if "DELETE FROM ticket_timeline" not in helper_src:
            raise AssertionError("时间线复位语句缺失（首跑新增的 status_change 会残留）")

    def test_reset_runs_through_db_not_product_api(self):
        """复位**不得**回落成产品 API（admin-api 的 `closed` 是终态，改了就是改产品契约）。

        平台约束：`AfterSalesTicketService.java:103-109` 的 `STATUS_TRANSITIONS`
        `closed → Set.of()`（无回到 pending 的写路径）+ 关闭分支只 set 不清空
        ⇒ 评测侧复位只能走带外（DB/seed）。这条守卫防止"顺手改成调 API"。
        """
        runner = _load_runner()
        src = Path(RUNNER_PATH).read_text(encoding="utf-8")
        start = src.index("async def _reset_aftersales_ticket(")
        body = src[start:src.index("async def _run_pre_clean(", start)]
        if "PUT" in body or "/status" in body:
            raise AssertionError("复位实现里出现了产品状态更新 API —— 平台约束禁改（见 docstring）")
        if "asyncpg" not in body:
            raise AssertionError("复位必须走 DB 直连（asyncpg）")
        if runner._eval_db_dsn().startswith("postgresql+asyncpg://"):
            raise AssertionError("DSN 未归一（SQLAlchemy 风格 DSN 直连会连不上）："
                                 f"{runner._eval_db_dsn()}")
