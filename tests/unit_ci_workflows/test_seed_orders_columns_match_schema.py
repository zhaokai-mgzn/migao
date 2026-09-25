# case_ids: MC-012
"""issue #4056：**活 seed 脚本**里 `orders` 的 INSERT 列集必须跟得上已删列（否则打库当场中止）。

## 病灶（2026-09-25 实测，不是风险预测）

`V126__drop_zombie_db_objects.sql`（issue #5245 A2/A3）已 `DROP` 掉
`orders.stock_deducted` / `orders.payment_status`，建库脚本
`backend/admin-api/src/main/resources/db/init/schema.sql` 同步不再建这两列
（「删干净」的三面判据见 `tests/unit_ci_workflows/test_dropped_db_objects.py`）。

**但活 seed 没跟上**：三个 seed 脚本的 `orders` INSERT 仍逐字写着
`payment_status, stock_deducted`（值 `'paid', TRUE`）。而

* `scripts/eval_stack_seed.sh` 用 `psql -v ON_ERROR_STOP=1` 打**全新库**（= V126 之后的终态）；
* `docs/deployment/demo-seed.sql` 的用法就是 `psql "$DATABASE_URL" -v tenant_id=1 -f …`。

⇒ 载 seed 当场中止（`ERROR: column "stock_deducted" of relation "orders" does not exist`），
评测栈**根本起不来**。而这条链路不在这批判据的触发面里 —— 属
「没人会因为这件事变红」的形态（`migao-dev-flow` §18「读的是快照」同族）。

## 三条判据（各配注入式红证）

| # | 判据 | 为什么不能只留一条 |
|---|---|---|
| ① | INSERT 列集 ∩ **V126 删列集** = ∅ | 归因清晰（点名 V126 / #5245），但只覆盖**这一次**的删列 |
| ② | INSERT 列集 ⊆ **建库脚本现列集** | 类级：将来任何删列 / 改名都会红，不依赖「记得来改判据」 |
| ③ | 每条 INSERT 的**列数 = 值数** | 「删了列忘了删值」是同一次修复的**另一半**；①② 都看不见它 |

## 射程：**活** seed，不是档案

`LIVE_SEEDS` 是**冻结登记表**（新增活 seed ⇒ 必须入册，未登记即漏判）：

* `tests/agent_eval/fixtures/*.sql` —— 评测栈种子（`scripts/eval_stack_seed.sh` 唯一注入源）；
* `docs/deployment/demo-seed.sql` —— PoC 演示种子（`docs/deployment/poc-rehearsal-checklist.md`
  逐字让人 `psql -f` 它）。

**有意不含**：`docs/sql/archive/**`、`docs/sql/schema_full.sql` 等**历史档案** ——
它们**应当**保留当时的列；拿判据去吃档案 = 逼人改写历史（与 `test_dropped_db_objects.py`
「删了要留说明」同一条取舍，见该文件头）。

## ⚠️ 边界（如实登记）

解析是**静态文本**层面的（不是 SQL 引擎）：只认 `INSERT INTO orders (<列清单>)` 这一种显式
列清单形态，且只判 `orders` 一张表。**无列清单的形态**（`INSERT INTO orders VALUES …`）
**不做静默跳过**，直接判红 —— 「静态判不了 ⇒ 没得查 ⇒ 绿」正是本仓最忌讳的假绿。
"""
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent

# 共享解析件（issue #5245）：`tests/` 上 sys.path 才能按**包名**导入 —— 口径与
# `test_dropped_db_objects.py` 用的**是同一份**（不另造第二份 schema 解析）。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from unit_ci_workflows._migration_paths import LIVE_DIR  # noqa: E402
from unit_ci_workflows._sql_schema import (  # noqa: E402
    parse_schema_columns_strict,
    strip_sql_comments,
)

#: 判定删列的那条迁移（编号由 issue #5245 补充评论冻结：V126）
V126 = LIVE_DIR / "V126__drop_zombie_db_objects.sql"

#: **活** seed 的冻结登记表（相对仓库根）。新增活 seed ⇒ 必须入册。
LIVE_SEEDS = (
    "tests/agent_eval/fixtures/xiaobu_eval_seed.sql",
    "tests/agent_eval/fixtures/mibao_eval_seed.sql",
    "docs/deployment/demo-seed.sql",
)


# ══════════════════════════════════════════════════════════════════════════════════
# 解析本体（纯函数 ⇒ 注入式红证行使的是**同一份**判据，不是它的复制品）
# ══════════════════════════════════════════════════════════════════════════════════

_INSERT_ORDERS_RE = re.compile(r"INSERT\s+INTO\s+orders\b", re.I)
_COLUMN_LIST_RE = re.compile(r"INSERT\s+INTO\s+orders\s*\(([^)]*)\)", re.I | re.S)


def _next_semicolon(text: str, start: int) -> int:
    """`text[start:]` 里**引号之外**的第一个 `;` 的下标（-1 = 没有）。

    ⚠️ 不能裸 `text.index(";", start)`：SQL 字符串里可以合法地出现 `;`
    （本仓 seed 目前没有，但下一个编辑者加一条备注就会让「语句边界」判错）。
    """
    quote = ""
    for i in range(start, len(text)):
        ch = text[i]
        if quote:
            if ch == quote:
                quote = ""
            continue
        if ch in "'\"":
            quote = ch
        elif ch == ";":
            return i
    return -1


def _split_top_level(s: str) -> list:
    """按**顶层**逗号切分（跳过括号 / 引号内的逗号）—— SQL 列表用。"""
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
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    out.append("".join(buf))
    return [x.strip() for x in out]


def _top_level_groups(s: str) -> list:
    """`s` 里**顶层**括号组的内容（`(...)` 内的原文，不含外括号）。"""
    groups, buf, depth, quote = [], [], 0, ""
    for ch in s:
        if quote:
            if depth >= 1:
                buf.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in "'\"":
            quote = ch
            if depth >= 1:
                buf.append(ch)
            continue
        if ch == "(":
            depth += 1
            if depth == 1:
                buf = []
                continue
        elif ch == ")":
            depth -= 1
            if depth == 0:
                groups.append("".join(buf))
                buf = []
                continue
        if depth >= 1:
            buf.append(ch)
    return groups


def _values_arity(rest: str):
    """`VALUES (…), (…)` 形态 → 各元组的字段数列表；非该形态 ⇒ `None`。"""
    m = re.search(r"\bVALUES\b", rest, re.I)
    if not m:
        return None
    body = re.split(r"\bON\s+CONFLICT\b", rest[m.end():], 1, flags=re.I)[0]
    return [len(_split_top_level(g)) for g in _top_level_groups(body)]


def _select_arity(rest: str):
    """`SELECT a, b, …` 形态 → 列数（截到顶层 `FROM` / `WHERE`）；非该形态 ⇒ `None`。"""
    m = re.search(r"\bSELECT\b", rest, re.I)
    if not m:
        return None
    body = re.split(r"\b(?:WHERE|FROM)\b", rest[m.end():], 1, flags=re.I)[0]
    return len(_split_top_level(body))


def orders_inserts(sql: str) -> list:
    """一份 seed SQL → 每条 `INSERT INTO orders` 的解析结果。

    返回 `[{stmt, columns, arities, unknown, dropped}]`：

    * `columns` / `unknown`（不在建库脚本里的列） / `dropped`（∩ V126 删列集）都是**小写列名**；
    * `arities` = 各值元组的字段数（多行 VALUES）或 `[列数]`（单行 SELECT）；
    * **无列清单**（`INSERT INTO orders VALUES …`）⇒ `pytest.fail`（fail-closed，不许静默跳过）。
    """
    text = strip_sql_comments(sql)
    out = []
    for m in _INSERT_ORDERS_RE.finditer(text):
        end = _next_semicolon(text, m.start())
        assert end != -1, f"fail-closed：`INSERT INTO orders` 之后找不到语句结束的 `;`（读了 {m.start()}）"
        stmt = text[m.start():end + 1]
        cm = _COLUMN_LIST_RE.match(stmt)
        if not cm:
            pytest.fail(
                f"fail-closed：`INSERT INTO orders` **没有显式列清单** ⇒ 本条判据静态判不了。\n"
                f"  语句：{stmt[:160]}…\n"
                f"  「判不了 ⇒ 跳过 ⇒ 绿」正是本仓最忌讳的假绿；请补列清单，或把本判据扩到该形态"
                f"（issue #4056）。")
        cols = [c.strip().strip('"').lower() for c in cm.group(1).split(",") if c.strip()]
        rest = stmt[cm.end():]
        arities = _values_arity(rest)
        if arities is None:
            single = _select_arity(rest)
            if single is None:
                # fail-closed（同一形态的第二个出口）：这里**不写成存在性断言** ——
                # 存在性 / 非空断言正是 QA Growth Gate 的弱断言形态，新文件一律 fail-closed
                # （实证：首版即因此被判 `锚点 248 → 当前 249`，本地 gate 红）。
                # ⚠️ 连「说明这段禁忌」的文字本身都会按**文本**被扫中 ⇒ 此处故意不复述那个写法。
                pytest.fail(
                    f"fail-closed：既不是 `VALUES` 也不是 `SELECT` 形态 ⇒ 值数判不了。\n"
                    f"  语句：{stmt[:160]}…")
            arities = [single]
        out.append({"stmt": stmt, "columns": cols, "arities": arities})
    return out


def v126_dropped_orders_columns() -> set:
    """V126 里**幂等**删掉的 `orders` 列（小写）—— 反推自迁移本体，不另列一份清单。"""
    assert V126.is_file(), (
        f"fail-closed：找不到 {V126} —— 「删列」的真值源就是它；文件不在 ⇒ 判据①会空转成绿")
    code = strip_sql_comments(V126.read_text(encoding="utf-8"))
    return {mm.group(1).lower() for mm in re.finditer(
        r"ALTER\s+TABLE\s+orders\s+DROP\s+COLUMN\s+IF\s+EXISTS\s+\"?(\w+)\"?", code, re.I)}


def scan_seeds(schema_columns: dict, dropped: set, seeds=LIVE_SEEDS) -> dict:
    """全部活 seed 的 `orders` INSERT 体检 → `{相对路径: [违规说明]}`（只含违规的文件）。"""
    out = {}
    for rel in seeds:
        path = REPO / rel
        assert path.is_file(), f"fail-closed：登记的活 seed 不存在（读了 {rel}）—— 扫描会空转=假绿"
        violations = []
        for ins in orders_inserts(path.read_text(encoding="utf-8")):
            cols = ins["columns"]
            hit = sorted(set(cols) & dropped)
            if hit:
                violations.append(f"列 {hit} 已被 V126 删除（issue #5245 A2/A3）")
            unknown = sorted(c for c in cols if c not in schema_columns)
            if unknown:
                violations.append(f"列 {unknown} 不在建库脚本的 `orders` 里")
            bad = [n for n in ins["arities"] if n != len(cols)]
            if bad:
                violations.append(
                    f"列数 {len(cols)} ≠ 值数 {bad}（删列时忘了同步删值 ⇒ psql 仍会报 "
                    f"`INSERT has more expressions than target columns`）")
        if violations:
            out[rel] = violations
    return out


# ══════════════════════════════════════════════════════════════════════════════════
# 判据 ①②③
# ══════════════════════════════════════════════════════════════════════════════════

def test_v126_dropped_orders_columns_are_real_and_consistent():
    """前提自证（fail-closed）：V126 确实删了 `orders` 的列，且这些列**确实不在**建库脚本里。

    没有这条，判据①可能是**空断言** —— 比如有人把 V126 的 DROP 语句删掉/改写成别的表，
    `dropped` 变成空集，于是「INSERT 列集 ∩ 空集 = ∅」永远成立（绿着没跑）。
    第二半（不在建库脚本里）把**两个来源**钉在一起：谁把列加回 `schema.sql` 也照样红。
    """
    dropped = v126_dropped_orders_columns()
    assert len(dropped) >= 2, (
        f"V126 里解析出的 `orders` 删列只有 {sorted(dropped) or '空集'} —— 判据①会退化成空断言"
        f"（解析口径漂移？读了 {V126}）")
    schema_columns = parse_schema_columns_strict()["orders"]
    back = sorted(c for c in dropped if c in schema_columns)
    assert not back, (
        f"这些列被 V126 删了，却仍在建库脚本里建出来：{back} —— "
        f"新建库与存量库会变成两份真相（issue #5245 A2/A3，`db/init/schema.sql` 须同步）")


def test_live_seed_orders_inserts_avoid_dropped_columns():
    """判据①（issue #4056 的验收判据）：活 seed 的 `orders` INSERT 列集 ∩ V126 删列集 = ∅。"""
    dropped = v126_dropped_orders_columns()
    schema_columns = parse_schema_columns_strict()["orders"]
    hits = {rel: [v for v in vs if "已被 V126 删除" in v]
            for rel, vs in scan_seeds(schema_columns, dropped).items()}
    hits = {rel: vs for rel, vs in hits.items() if vs}
    assert not hits, (
        "这些活 seed 仍在 `orders` 的 INSERT 里写**已被 V126 物理删除**的列"
        "（issue #4056 / #5245 A2/A3）：\n  "
        + "\n  ".join(f"{rel}: {vs}" for rel, vs in sorted(hits.items()))
        + f"\n⇒ 打库当场中止（`ERROR: column … of relation \"orders\" does not exist`）："
          f"\n   · `scripts/eval_stack_seed.sh` 用 `psql -v ON_ERROR_STOP=1` 打**全新库** ⇒ 评测栈起不来；"
          f"\n   · `psql -f docs/deployment/demo-seed.sql` 同样中止。"
          f"\n修法：把该 INSERT 的**列清单与值同步删掉**这两列（V126 已裁定它们零读取点）。")


def test_live_seed_orders_insert_columns_exist_in_schema():
    """判据②（类级）：活 seed 的 `orders` INSERT 列集 ⊆ 建库脚本的现列集。

    与①的区别：① 只认 V126 这一批删列，② 认**任何**与建库脚本对不上的列
    （将来删列 / 改名 / 拼错列名都红），不依赖「记得回来改判据」。
    """
    schema_columns = parse_schema_columns_strict()["orders"]
    hits = {rel: [v for v in vs if "不在建库脚本" in v]
            for rel, vs in scan_seeds(schema_columns, v126_dropped_orders_columns()).items()}
    hits = {rel: vs for rel, vs in hits.items() if vs}
    assert not hits, (
        "这些活 seed 的 `orders` INSERT 写了**建库脚本里不存在**的列：\n  "
        + "\n  ".join(f"{rel}: {vs}" for rel, vs in sorted(hits.items()))
        + "\n⇒ 全新库上必然 `column … does not exist`。真值源 = "
          "backend/admin-api/src/main/resources/db/init/schema.sql 的 `orders` 建表段"
          "（必须先核它，不要凭记忆猜列）。")


def test_live_seed_orders_insert_column_value_arity_matches():
    """判据③：每条 INSERT 的**列数 = 值数**（「删了列忘了删值」是同一修复的另一半）。"""
    schema_columns = parse_schema_columns_strict()["orders"]
    hits = {rel: [v for v in vs if "列数" in v]
            for rel, vs in scan_seeds(schema_columns, v126_dropped_orders_columns()).items()}
    hits = {rel: vs for rel, vs in hits.items() if vs}
    assert not hits, (
        "这些活 seed 的 `orders` INSERT **列清单与值不同步**：\n  "
        + "\n  ".join(f"{rel}: {vs}" for rel, vs in sorted(hits.items()))
        + "\n⇒ psql 报 `INSERT has more expressions than target columns`（或反过来少给值）"
          "—— 判据①②只看列名，**看不见**这一半。")


# ══════════════════════════════════════════════════════════════════════════════════
# 红证（注入式）—— 判据必须**真的会红**，且不被自己的文案喂红
# ══════════════════════════════════════════════════════════════════════════════════

_SYNTH_SCHEMA = {"orders": {"id", "tenant_id", "order_no", "status", "total_amount"}}
_SYNTH_DROPPED = {"stock_deducted", "payment_status"}


def test_parser_can_go_red_on_each_of_the_three_criteria():
    """红证：三个判据各自**单独**能红（否则至少有一条是空断言）。

    三臂各注入一处**只**触发自己那条的缺陷，逐臂断言「该条命中、另两条不命中」——
    这样「三条判据」不是一句口号，而是三个可分辨的读数。
    """
    good = ("INSERT INTO orders (id, order_no, status)\n"
            "VALUES ('o-1', 'N-1', 'paid');\n")
    ok = orders_inserts(good)
    assert [len(i["columns"]) for i in ok] == [3], f"解析器读不出列清单：{ok}"
    assert [i["arities"] for i in ok] == [[3]], f"解析器读不出值数：{ok}"

    # ① 注入被 V126 删掉的列（真值形态：'paid', TRUE 一起给）
    dropped_arm = ("INSERT INTO orders (id, order_no, status, payment_status, stock_deducted)\n"
                   "VALUES ('o-1', 'N-1', 'completed', 'paid', TRUE);\n")
    ins = orders_inserts(dropped_arm)[0]
    assert set(ins["columns"]) & _SYNTH_DROPPED == {"payment_status", "stock_deducted"}, \
        "注入被删列却读不出 ⇒ 判据①是空断言"
    assert ins["arities"] == [5], "同臂的值数不该被判错 ⇒ 判据③会误红"

    # ② 注入建库脚本里没有、但**不在** V126 删列集里的列（拼错 / 将来改名）
    unknown_arm = ("INSERT INTO orders (id, order_no, statuss)\nVALUES ('o-1', 'N-1', 'x');\n")
    ins = orders_inserts(unknown_arm)[0]
    assert [c for c in ins["columns"] if c not in _SYNTH_SCHEMA["orders"]] == ["statuss"], \
        "注入不存在的列却读不出 ⇒ 判据②是空断言"
    assert not set(ins["columns"]) & _SYNTH_DROPPED, "同臂不该触发判据①（两臂必须可分辨）"

    # ③ 注入「删了列忘了删值」——判据①②**看不见**它
    arity_arm = ("INSERT INTO orders (id, order_no)\n"
                 "VALUES ('o-1', 'N-1', 'paid', TRUE);\n")
    ins = orders_inserts(arity_arm)[0]
    assert ins["arities"] == [4], f"注入列值不同步却读不出 ⇒ 判据③是空断言：{ins}"
    assert not set(ins["columns"]) & _SYNTH_DROPPED and \
        all(c in _SYNTH_SCHEMA["orders"] for c in ins["columns"]), \
        "同臂不该被判据①②看见 ⇒ ③ 不是冗余判据"

    # ④ 多行 VALUES：每行的值数都要核（只看第一行 = 漏掉其余订单）
    multi = ("INSERT INTO orders (id, order_no)\nVALUES ('o-1', 'N-1'), ('o-2', 'N-2', TRUE)\n"
             "ON CONFLICT (id) DO NOTHING;\n")
    assert orders_inserts(multi)[0]["arities"] == [2, 3], \
        "多行 VALUES 只核了第一行 ⇒ 后半段订单被漏判"
    # 负控：`ON CONFLICT (id)` 的括号**不得**被当成一个值元组
    assert orders_inserts(good)[0]["arities"] == [3], "值数被 `ON CONFLICT` 污染"

    # ⑤ SELECT 形态（`docs/deployment/demo-seed.sql` 的实际写法）+ 嵌套函数括号
    select_arm = ("INSERT INTO orders (id, order_no, status)\n"
                  "SELECT 'o-1', 'N-' || :n, 'completed'\n"
                  "WHERE NOT EXISTS (SELECT 1 FROM orders WHERE id = 'o-1');\n")
    assert orders_inserts(select_arm)[0]["arities"] == [3], \
        "SELECT 形态读不出值数（`WHERE` 之后的子查询混进来了？）⇒ feedback seed 判不了"


def test_parser_fails_closed_without_a_column_list_and_ignores_comments():
    """负控 + fail-closed（两个方向都钉住）。

    * **fail-closed**：`INSERT INTO orders VALUES (…)`（无列清单）⇒ **判红**，不许静默跳过；
    * **负控**：注释里提到被删列名 ⇒ **必须绿** —— 本仓要求「删了要留说明」，
      判据一旦吃自己的文案，最后一定是判据逼人删掉记录
      （`test_dropped_db_objects.py` 的负控同款取舍）。
    """
    with pytest.raises(BaseException) as ei:
        orders_inserts("INSERT INTO orders VALUES ('o-1', 'N-1');\n")
    assert "没有显式列清单" in str(getattr(ei.value, "msg", ei.value)), \
        "无列清单的 INSERT 没有被 fail-closed ⇒ 下一个作者换个写法就绕过了整条判据"

    commented = ("-- 历史说明：本 seed 曾写 payment_status / stock_deducted，V126 已删（issue #4056）\n"
                 "-- INSERT INTO orders (id, payment_status) VALUES ('o-1', 'paid');\n"
                 "INSERT INTO orders (id, order_no)\nVALUES ('o-1', 'N-1');\n")
    ins = orders_inserts(commented)
    assert len(ins) == 1, f"注释行被当成语句 ⇒ 判据被自己的说明文字喂红（读出了 {len(ins)} 条）"
    assert not set(ins[0]["columns"]) & _SYNTH_DROPPED, "注释里的被删列名被算成了引用"