# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 既有惯例：CI / 流程结构类 L0 不变式统一挂 MC-012 ——
#   见 test_seed_orders_columns_match_schema.py / test_schema_bootstrap_order.py 的同款声明
#   与 `.github/cases/misc.yml` MC-012 的登记。本 PR 不新建用例族。）
r"""issue #5502：**dollar-quoted 块内不得出现 psql `:变量`**（静态类级锁 + 真库判据）。

## 病灶（2026-09-25 **实测**，不是风险预测）

`docs/deployment/demo-seed.sql` 第 3 节的 SKU 段用 `DO $$ … $$` 取色号 `cid`，块体里逐字写着
`WHERE tenant_id = :tenant_id`。而 **psql 不在 dollar-quoted 体内做变量替换**
（`psql` 手册：「variable interpolation will not be performed within quoted SQL literals and
identifiers」；`$$ … $$` 内的 `:name` 原样进服务端）⇒ 服务端收到字面量 `:tenant_id`：

    psql:docs/deployment/demo-seed.sql:97: ERROR:  syntax error at or near ":"
    第4行...id INTO cid FROM product_colors WHERE tenant_id = :tenant_id...
                                                              ^
    EXIT=3

⇒ **该脚本在任何 schema 上都跑不起来**（与「列变更」无关 —— 这是**语法**层面的中止，
块里后面的 `INSERT` 一条都没执行过）。而文档正逐字让人跑它
（`docs/deployment/poc-demo-rehearsal-checklist.md` / `docs/deployment/poc-demo-script.md`
的 `psql "$DATABASE_URL" -v tenant_id=1 -f docs/deployment/demo-seed.sql`）
⇒ PoC 彩排到「装演示数据」这一步当场卡住，且**没有任何判据会因此变红**。

🔴 **为什么它瞒得住**：块内 `:变量` 是**合法 psql 语法**在**不合法的位置**上 ——
静态看「文件里确实出现了 `:tenant_id`」（像是对参数化了）、
真库看「没人真跑过它」（`test_seed_orders_columns_match_schema.py` 只做**列集**静态比对，
不执行语句）⇒ 两个方向都像「没问题」。这就是本仓 `migao-dev-flow` §18「读的是快照」的同族形态。

## 本文件钉的三件事（各配会红的判据）

| # | 判据 | 红证 |
|---|---|---|
| ① | **类级静态锁**：射程内（`docs/**/*.sql` + `tests/**/*.sql`）所有 dollar-quoted 块**体内**、引号字面量**外**，零 psql 变量引用 | 把原始 `DO $$ … :tenant_id … $$` 段**注入真语料**（`test_injected_var_in_a_block_reddens_the_real_corpus`）⇒ 必红 |
| ② | **真库判据**：全新库上按**文件自己声明的用法**（`-v` 键值**从用法行现取**）跑完整份 seed ⇒ `ON_ERROR_STOP=1` 下 **exit 0** + **零 ERROR** + 完成标记打印 + 目标表行数 == 文件里的语句数；**同一份库上第二遍**行数不变（文件自己声称「可重复执行」） | `test_harness_detects_a_broken_seed`：把原始病灶段喂进**同一条 psql 调用**⇒ 断言非零退出 + 报错原文命中 ⇒ 证明真库判据**不是空跑** |
| ③ | **解析件自身的负控**：`:var` / `:'var'` 在块**外**（psql 合法形态）、`::` 转型、`:=` 赋值、块内 `'HH24:MI:SS'` 这类**引号字面量**、`$1` 位置参数、注释里的 `DO $$` ⇒ 一律**不判** | 同一条用例内逐形态断言读数为 0（防「判据恒红」把下一个作者逼去删说明） |

## ⚠️ 边界（如实登记 —— 不是「已覆盖」）

- **有意不判**：`:{?name}` / `:'name'`（带引号形态本判据**会**认，见下）之外的 psql 元命令形态
  （`\set` / `\gexec`）不在面内；块内**引号字面量里**的 `:name` 不判（psql 在引号内同样不替换 ⇒
  判它就是误伤 `to_char(…, 'HH24:MI:SS')` 这类合法写法）。
- **注释先遮罩**：判定前把 `--` / `/* */` 注释**按原长度**换成空格（保留换行 ⇒ 行号不漂）。
  代价（已知、可接受）：`-- 说明：$$ …` 这类注释里的 `$$` 不会被当成块起点；
  而**真** dollar-quoted 体内写着 `$$` 的病态写法同样遮不住（psql 语义下它本就提前闭合）⇒
  这类形态若要判，得换成单遍词法，本判据有意不做（低频、且会引入新误报面）。
- **射程只有两个 glob**：`docs/**/*.sql` + `tests/**/*.sql`（= 文档样例 + 评测栈种子）。
  迁移链（`backend/…/db/migration/**`，Flyway 执行，不经 psql）与 `.sh` 内联 SQL **不在面内**。
- ② 只跑 **`docs/deployment/demo-seed.sql`** 一份：另外两份活 seed（`tests/agent_eval/fixtures/*.sql`）
  由 `scripts/eval_stack_seed.sh` 在**迁移后**的栈上注入，不在本判据的建库路径上
  ⇒ **未固化**（照实登记，别把「没跑」读成「没问题」）。
"""
from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import tempfile
from pathlib import Path

import pytest
from unit_ci_workflows import pg_cluster  # noqa: E402  （起/停集群的唯一收口，issue #5263）
from unit_ci_workflows._sql_schema import (  # noqa: E402
    _SQL_BLOCK_COMMENT_RE,
    _SQL_LINE_COMMENT_RE,
)

REPO = Path(__file__).resolve().parents[2]

#: 射程（**glob 现取**：新增文件自动进面）
CORPUS_GLOBS = ("docs/**/*.sql", "tests/**/*.sql")

#: 文档里**逐字让人 `psql -f`** 的脚本（②的真库判据就跑它）。新增同类脚本 ⇒ 同批入册。
PSQL_RUNNABLE_SEEDS = ("docs/deployment/demo-seed.sql",)

#: 建库脚本（真库判据的前置：全新库 = 它建出来的终态）
SCHEMA = REPO / "backend/admin-api/src/main/resources/db/init/schema.sql"

#: `-v name=value`（psql 变量）—— 从用法行**现取**，不在这里再写一份 `tenant_id=1`
_PSQL_VAR_ARG_RE = re.compile(r"-v\s+([A-Za-z_]\w*)=(\S+)")

#: dollar-quoted 的定界 tag：`$$` 或 `$tag$`（`$1` 这类位置参数**不**匹配）
_DOLLAR_TAG_RE = re.compile(r"\$([A-Za-z_]\w*)?\$")

#: psql 变量引用：`:name` 与 `:'name'`（后者 = 取引用值形态）。`::`（转型）与 `:=`（赋值）不匹配。
#: ⚠️ `[']?` 写成字符类（**不是** `'?`）：判据面的「原文口径」元守卫
#: （`test_guard_parsing_is_comment_aware.py`）把「引号紧跟 `(`」当取值型正则的形态，
#: 而本 pattern 的取值区间是**标识符**、不是引号之间的原文 ⇒ 别改成 `:'?` 那种写法。
_PSQL_VAR_RE = re.compile(r"(?<!:):(?!:)([']?)([A-Za-z_][A-Za-z0-9_]*)")


# ══════════════════════════════════════════════════════════════════════════════════
# 解析件（纯函数 ⇒ 注入式红证行使的是**同一份**判据，不是它的复制品）
# ══════════════════════════════════════════════════════════════════════════════════

def mask_comments(sql: str) -> str:
    """注释 → **等长**空格（保留换行）。口径 = `_sql_schema.strip_sql_comments` 的**同一对正则**。

    为什么不用 `strip_sql_comments()` 本体：它把注释**删掉** ⇒ 偏移量漂移 ⇒ 报不出行号。
    遮罩与删除对「什么样的文本算注释」的判断**完全一致**，只是保留长度。
    """
    return _SQL_LINE_COMMENT_RE.sub(
        lambda m: re.sub(r"[^\n]", " ", m.group(0)),
        _SQL_BLOCK_COMMENT_RE.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), sql),
    )


def _blocks_in(masked: str) -> list:
    """已遮罩文本里的 dollar-quoted 区域 → `[(起, 止, tag)]`（止 = 闭合 tag 之后）。

    **未闭合 ⇒ 抛 `AssertionError`**（fail-closed）：「块边界判不了」不许退化成「没块 ⇒ 没违规」。
    """
    out = []
    i = 0
    while True:
        m = _DOLLAR_TAG_RE.search(masked, i)
        if m is None:
            return out
        tag = m.group(0)
        close = masked.find(tag, m.end())
        assert close != -1, (
            f"fail-closed：dollar-quoted 起点 {tag}（第 {masked.count(chr(10), 0, m.start()) + 1} 行）"
            f"找不到闭合 tag ⇒ 块边界判不了，本判据不许静默跳过")
        out.append((m.start(), close + len(tag), tag))
        i = close + len(tag)


def dollar_quoted_blocks(sql: str) -> list:
    """`sql` 里的 dollar-quoted 区域（注释先遮罩 ⇒ 注释里的 `$$` 不算块起点）。"""
    return _blocks_in(mask_comments(sql))


def _unquoted_spans(body: str) -> list:
    """块体内**不在引号字面量里**的片段。

    psql 在引号字面量内同样不做变量替换（`RAISE NOTICE 'a:b'` / `to_char(…, 'HH24:MI:SS')`）
    ⇒ 那些位置上的 `:xxx` **不是**缺陷，判它就是误伤（并会把下一个作者逼去删掉合法格式化串）。
    `''`（SQL 的转义单引号）按**一个字面量**处理。
    """
    spans = []
    start = 0
    i = 0
    n = len(body)
    while i < n:
        ch = body[i]
        if ch not in "'\"":
            i += 1
            continue
        if i > start:
            spans.append((start, i))
        i += 1
        while i < n:
            if body[i] == ch:
                if ch == "'" and i + 1 < n and body[i + 1] == "'":
                    i += 2
                    continue
                i += 1
                break
            i += 1
        start = i
    if start < n:
        spans.append((start, n))
    return spans


def psql_vars_in_dollar_blocks(sql: str) -> list:
    """→ `[(行号, 原文片段)]`：dollar-quoted 块**体内**、引号字面量**外**的 psql 变量引用。

    行号按**遮罩后**的文本数（遮罩保留换行 ⇒ 与原文行号一致）。
    """
    masked = mask_comments(sql)
    hits = []
    for start, end, _tag in _blocks_in(masked):
        body = masked[start:end]
        for span_start, span_end in _unquoted_spans(body):
            for m in _PSQL_VAR_RE.finditer(body, span_start, span_end):
                hits.append((masked.count("\n", 0, start + m.start()) + 1, m.group(0)))
    return hits


def corpus_texts(repo: Path = REPO) -> dict:
    """射程内的全部 `.sql` → `{仓库相对路径: 原文}`（按 glob **现取**）。"""
    out = {}
    for pattern in CORPUS_GLOBS:
        for path in sorted(repo.glob(pattern)):
            if path.is_file():
                out[path.relative_to(repo).as_posix()] = path.read_text(encoding="utf-8")
    return out


def scan_corpus(files: dict) -> dict:
    """体检整份语料 → `{相对路径: [违规说明]}`（只含违规的文件）。注入式红证调的就是**它**。"""
    out = {}
    for rel, text in sorted(files.items()):
        hits = psql_vars_in_dollar_blocks(text)
        if hits:
            out[rel] = [f"第 {line} 行 `{token}` 在 dollar-quoted 体内" for line, token in hits]
    return out


def usage_variables(sql: str) -> dict:
    """从「用法」行现取 psql 变量（`-v name=value`）—— 文档说什么，真库判据就跑什么。

    取不到（0 个）⇒ **fail-closed 抛错**：真库判据会退化成「不带变量跑一遍」，
    而那样的失败信息指向的是「脚本坏了」而不是「用法行没了」（判据把嫌疑指向错误的对象）。
    """
    found = dict(_PSQL_VAR_ARG_RE.findall(sql))
    assert found, (
        "docs/deployment/demo-seed.sql 的用法行里解析不到任何 `-v name=value` ⇒ 真库判据无法按"
        "文档指引执行（请检查该文件的「用法：psql …」行）")
    return found


def _insert_statements(sql: str, table: str) -> int:
    """文件里 `INSERT INTO <table>` 的**语句数**。

    ⚠️ 本 seed 的每条语句**恰落 1 行**（单行 `SELECT … WHERE NOT EXISTS` 守卫形态）——
    这把「行数 == 语句数」当判据，比写死数字稳（文件改了数字自己跟着变）；
    将来若有人写多行 `VALUES`，这里会红，出口是把派生口径升级成「数 rows」而不是改数字。
    """
    return len(re.findall(rf"INSERT\s+INTO\s+{table}\b", mask_comments(sql), re.I))


# ══════════════════════════════════════════════════════════════════════════════════
# 判据 ①③：解析件本身（注入必红 / 合规不误报）
# ══════════════════════════════════════════════════════════════════════════════════

#: 原始病灶（issue #5502 实测报错的那一段 —— 逐字取自 `git show origin/main:docs/deployment/demo-seed.sql`）
_BROKEN_BLOCK = """-- SKU：星空全遮光
DO $$
DECLARE cid BIGINT;
BEGIN
  SELECT id INTO cid FROM product_colors WHERE tenant_id = :tenant_id AND product_id = 'p-zg-001' AND color_name = '象牙白';
  IF cid IS NOT NULL THEN
    INSERT INTO product_skus (tenant_id, product_id, color_id, selling_method, door_width, price, stock, sku_code)
    SELECT :tenant_id, 'p-zg-001', cid, 'bulk_cut', '2.8米', 98.00, 500, 'ZG001-象牙白-散剪-2.8'
    WHERE NOT EXISTS (SELECT 1 FROM product_skus WHERE tenant_id = :tenant_id AND product_id = 'p-zg-001' AND color_id = cid);
  END IF;
END $$;
"""


def test_broken_block_from_the_issue_is_detected_with_line_numbers():
    """判据①的**锚点红证**：issue 原文那段病灶必须被判出来（否则整条锁是空断言）。"""
    hits = psql_vars_in_dollar_blocks(_BROKEN_BLOCK)
    tokens = [tok for _line, tok in hits]
    assert tokens, "issue #5502 的病灶段（`DO $$ … :tenant_id … $$`）没被判出来 ⇒ 判据是空断言"
    assert set(tokens) == {":tenant_id"}, f"读到的变量引用是 {sorted(set(tokens))}"
    # 病灶段的三处：`SELECT … INTO`（第 5 行）、`SELECT :tenant_id, …`（第 8 行）、
    # `WHERE NOT EXISTS (… tenant_id = :tenant_id …)`（第 9 行）
    assert [line for line, _tok in hits] == [5, 8, 9], (
        f"行号读数 {[line for line, _tok in hits]} 与病灶段不符（注释行也算进去了？遮罩把偏移量弄漂了？）")
    assert len(dollar_quoted_blocks(_BROKEN_BLOCK)) == 1, "病灶段里的 `DO $$ … $$` 没被当成一个块"


def test_parser_is_negative_on_legal_forms():
    """判据③（负控）：合规写法**一律不判** —— 含 psql 合法引用在块**外**的形态。

    没有这一条，「块内不得写 `:变量`」会退化成「文件里不许出现 `:`」，
    下一个作者只能删掉 `::` 转型或格式化串才能过门禁。
    """
    legal_outside = (
        "INSERT INTO product_skus (tenant_id, product_id, price)\n"
        "SELECT :tenant_id, 'p-1', :'price'\n"
        "WHERE NOT EXISTS (SELECT 1 FROM product_skus WHERE tenant_id = :tenant_id);\n"
    )
    assert psql_vars_in_dollar_blocks(legal_outside) == [], \
        "块**外**的 `:var` / `:'var'` 是 psql 合法用法，判红就是误伤"

    casts = "SELECT '1'::bigint, now()::text FROM product_skus WHERE tenant_id = 1;\n"
    assert psql_vars_in_dollar_blocks(casts) == [], "`::` 转型被读成了 psql 变量"

    quoted_in_block = """DO $$
DECLARE ts TEXT;
BEGIN
  ts := to_char(NOW(), 'YYYY-MM-DD HH24:MI:SS');
  RAISE NOTICE 'tenant: % / %', ts, 'http://x/y';
  PERFORM 1;
END $$;
"""
    assert psql_vars_in_dollar_blocks(quoted_in_block) == [], \
        "块内**引号字面量**里的 `:MI` / `:SS` / `: %` / `://` 被读成了变量引用（psql 在引号内不替换）"

    assignments = """DO $$
DECLARE n INT;
BEGIN
  n := 1;
  n = n + 1;
END $$;
"""
    assert psql_vars_in_dollar_blocks(assignments) == [], "`:=` 赋值被读成了 psql 变量"

    positional = "CREATE FUNCTION f(INT) RETURNS INT AS $fn$ SELECT $1 + 1; $fn$ LANGUAGE sql;\n"
    assert psql_vars_in_dollar_blocks(positional) == [], "`$1` 位置参数被当成了变量引用"

    commented = ("-- 说明（勿删）：本段曾用 `DO $$ … :tenant_id … $$` 取色号，issue #5502 已改成\n"
                 "-- 相关子查询。注释里的 $$ 不该被当成块起点。\n"
                 "INSERT INTO product_skus (tenant_id) SELECT :tenant_id;\n")
    assert psql_vars_in_dollar_blocks(commented) == [], \
        "注释里的 `$$` 被当成了块起点 ⇒ 判据被自己的说明文字喂红"

    assert psql_vars_in_dollar_blocks("") == [], "空文本读出违规？"


def test_unterminated_dollar_quote_fails_closed():
    """fail-closed：块没闭合 ⇒ 判**红**（不是「没块 ⇒ 没违规」）。"""
    with pytest.raises(AssertionError) as ei:
        dollar_quoted_blocks("DO $$\nBEGIN\n  PERFORM 1;\n")   # 有意缺闭合 tag
    assert "找不到闭合 tag" in str(ei.value), "未闭合的 dollar quote 没有被 fail-closed"


# ══════════════════════════════════════════════════════════════════════════════════
# 判据 ①：真语料（射程内零违规）+ 机制存活读数
# ══════════════════════════════════════════════════════════════════════════════════

def test_corpus_has_no_psql_vars_inside_dollar_quoted_blocks():
    """判据①（承重）：射程内所有 `.sql` 的 dollar-quoted 块体内零 psql 变量引用。"""
    files = corpus_texts()
    hits = scan_corpus(files)
    assert not hits, (
        "这些 `.sql` 在 dollar-quoted 体内写了 psql `:变量` —— psql **不在体内做替换**，"
        "服务端会当场 `syntax error at or near \":\"`（issue #5502 实测）：\n  "
        + "\n  ".join(f"{rel}: {vs}" for rel, vs in sorted(hits.items()))
        + "\n修法（本仓既有范式，二选一）：① 把变量拼进块**外层**的语句"
          "（`INSERT … SELECT … FROM <表> WHERE …`）；② 用 `current_setting()` 传参。"
          "**不要**把变量直接写进 `DO $$ … $$` / 函数体。"
          "\n一键复算：python3 -m pytest tests/unit_ci_workflows/"
          "test_psql_vars_outside_dollar_quotes.py -q")


def test_corpus_and_mechanism_are_alive():
    """机制存活读数（**现取**，不写死）：语料非空、登记的脚本真在语料里、块数 > 0。

    没有这一条，射程一旦被收窄（glob 改错 / 文件搬走）判据会**绿着空转**。
    """
    files = corpus_texts()
    assert files, f"射程 {CORPUS_GLOBS} 一个 `.sql` 都没取到 ⇒ 判据①是空跑"
    for rel in PSQL_RUNNABLE_SEEDS:
        assert rel in files, (
            f"登记的 psql 可执行脚本不在射程内：{rel}（改名前请同批更新本文件的 "
            f"PSQL_RUNNABLE_SEEDS 与 CORPUS_GLOBS）")
    blocks = sum(len(dollar_quoted_blocks(text)) for text in files.values())
    print(f"🔎 射程 {CORPUS_GLOBS}：{len(files)} 个 `.sql` / {blocks} 个 dollar-quoted 块被扫过")
    assert blocks > 0, (
        "整份语料里一个 dollar-quoted 块都没有 ⇒ 判据①此刻是**空断言**（绿着没跑）。"
        "若这是有意为之（例如块都改成了普通语句），请连同本判据一起改判，别让它空转")


def test_injected_var_in_a_block_reddens_the_real_corpus():
    """判据①的注入式红证：把**原始病灶段**注入**真语料** ⇒ 必红，且只红那一个文件。"""
    files = corpus_texts()
    assert scan_corpus(files) == {}, "注入前真语料就不干净 —— 先修语料再谈红证"

    target = PSQL_RUNNABLE_SEEDS[0]
    injected = dict(files)
    injected[target] = files[target] + "\n" + _BROKEN_BLOCK
    hits = scan_corpus(injected)
    assert set(hits) == {target}, f"注入只该让 {target} 变红，实际：{sorted(hits)}"
    assert any(":tenant_id" in v for v in hits[target]), \
        f"注入病灶后读数是 {hits[target]} —— 判据没看到 `:tenant_id`（判红不可归因）"


# ══════════════════════════════════════════════════════════════════════════════════
# 判据 ②：真库（全新库 + 按文档用法跑 + 幂等 + 目标段落真跑到）
# ══════════════════════════════════════════════════════════════════════════════════

def _var_args(variables: dict) -> str:
    """`-v k=v` 串（只用于断言消息里给出**可复制**的命令）。"""
    return " ".join(f"-v {k}={v}" for k, v in variables.items())


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _Pg:
    """一次性集群的 psql 外壳（起/停走收口件 `pg_cluster`，issue #5263）。

    `schema_build` = 建库脚本那一跑的读数（在夹具里跑一次就够，**不依赖用例顺序**）。
    """

    def __init__(self, sockdir, port, bins, schema_build):
        self.sockdir, self.port, self.bins = sockdir, port, bins
        self.schema_build = schema_build

    def psql(self, args: list, **kw) -> subprocess.CompletedProcess:
        return subprocess.run(
            [self.bins["psql"], "-h", str(self.sockdir), "-p", str(self.port), "-U", "postgres",
             "-d", "postgres", "-X", "-q", *args],
            text=True, capture_output=True, **kw,
        )

    def query(self, sql: str) -> str:
        proc = self.psql(["-t", "-A", "-v", "ON_ERROR_STOP=1", "-c", sql])
        assert proc.returncode == 0, f"psql 失败：\n{proc.stdout}\n{proc.stderr}"
        return proc.stdout.strip()

    def run_file(self, path: Path, variables=None, env=None) -> subprocess.CompletedProcess:
        """`ON_ERROR_STOP=1` + 变量跑一份 `.sql`（与文档的 `psql … -v tenant_id=1 -f …` 同款）。"""
        args = ["-v", "ON_ERROR_STOP=1"]
        for name, value in (variables or {}).items():
            args += ["-v", f"{name}={value}"]
        kw = {} if env is None else {"env": {**os.environ, **env}}
        return self.psql([*args, "-f", str(path)], **kw)


@pytest.fixture(scope="module")
def pg(realdb_binaries):
    """真库夹具；缺 PG 的处置收口在 `pg_cluster.py`（CI 判**红** / 本机显式 skip，issue #5203）。

    ⚠️ **建库脚本在这里跑一次**（不在某个用例里）：否则「只跑其中一条用例」时前置没建，
    真库判据会红在一堆 `relation … does not exist` 上 —— 那样的红会把嫌疑指向错误的对象。
    """
    with tempfile.TemporaryDirectory(prefix="migao5502-") as td:
        tmp = Path(td)
        datadir = tmp / "pgdata"
        # ⚠️ socket 目录必须**短**：unix socket 路径有 ~104 字节上限
        sockdir = Path(tempfile.mkdtemp(prefix="pg5502-"))
        log = tmp / "pg.log"
        port = _free_port()
        pg_cluster.start_cluster(realdb_binaries, datadir, sockdir=sockdir, port=port, log=log)
        try:
            handle = _Pg(sockdir, port, realdb_binaries, None)
            handle.schema_build = handle.run_file(SCHEMA)
            yield handle
        finally:
            pg_cluster.stop_cluster(realdb_binaries["pg_ctl"], datadir)
            shutil.rmtree(sockdir, ignore_errors=True)


def test_fresh_db_harness_actually_ran(pg):
    """自证：集群起来了、建库脚本跑通了（否则后面的「绿」是夹具坏了之后的假绿）。"""
    assert pg.query("SELECT 1") == "1", "临时集群没起来"
    build = pg.schema_build
    combined = build.stdout + build.stderr
    errors = [ln for ln in combined.splitlines() if "ERROR:" in ln or "错误:" in ln]
    assert errors == [], f"建库脚本在全新库上报错：\n  " + "\n  ".join(errors)
    assert build.returncode == 0, f"建库脚本非零退出（exit={build.returncode}）：\n{combined[-1200:]}"


def test_demo_seed_runs_on_a_fresh_db_and_is_idempotent(pg):
    """判据②（承重）：按**文件自己声明的用法**跑完整份 seed ⇒ exit 0 + 零 ERROR + 幂等。

    三条一起看才有意义：① `exit 0` 只证「psql 没报错」；② 完成标记只证「最后一句执行了」；
    ③ 行数 == 文件里的语句数才证「**每一段**真落了数据」（`DO` 块那种形态正是**假装跑了**）。
    """
    seed = REPO / PSQL_RUNNABLE_SEEDS[0]
    text = seed.read_text(encoding="utf-8")
    variables = usage_variables(text)
    assert "tenant_id" in variables, f"用法行里没给出 tenant_id ⇒ 真库判据跑的不是文档那条命令：{variables}"

    first = pg.run_file(seed, variables)
    combined = first.stdout + first.stderr
    errors = [ln for ln in combined.splitlines() if "ERROR:" in ln or "错误:" in ln]
    assert errors == [], (
        f"`psql -v ON_ERROR_STOP=1 {_var_args(variables)} -f {PSQL_RUNNABLE_SEEDS[0]}` 在全新库上报错：\n  "
        + "\n  ".join(errors))
    assert first.returncode == 0, (
        f"全新库上跑 {PSQL_RUNNABLE_SEEDS[0]} 非零退出（exit={first.returncode}）⇒ 文档让人照抄的命令"
        f"跑不起来（issue #5502 的形态）。输出尾部：\n{combined[-1200:]}")
    assert "POC 演示数据 seed 完成" in first.stdout, (
        f"完成标记没打印 ⇒ 文件**没跑到最后**（`ON_ERROR_STOP=0` 时错误会被吞掉、看起来像成功）：\n"
        f"{combined[-1200:]}")

    tenant = variables["tenant_id"]
    expected_skus = _insert_statements(text, "product_skus")
    expected_orders = _insert_statements(text, "orders")
    expected_items = _insert_statements(text, "order_items")
    assert expected_skus > 0 and expected_orders > 0 and expected_items > 0, (
        f"派生出的语句数不对劲（skus={expected_skus} / orders={expected_orders} / "
        f"items={expected_items}）⇒ 本判据会退化成空断言")
    counted = {
        "product_skus": pg.query(f"SELECT count(*) FROM product_skus WHERE tenant_id = {tenant};"),
        "orders": pg.query(f"SELECT count(*) FROM orders WHERE tenant_id = {tenant};"),
        "order_items": pg.query(f"SELECT count(*) FROM order_items WHERE tenant_id = {tenant};"),
    }
    assert counted == {"product_skus": str(expected_skus), "orders": str(expected_orders),
                       "order_items": str(expected_items)}, (
        f"落库行数与文件里的语句数不符：实得 {counted} / "
        f"期望 skus={expected_skus} orders={expected_orders} items={expected_items} "
        "⇒ 某一段没跑到（或守卫把该插的行挡掉了）")

    # 文件头自称「幂等：所有 INSERT 用 WHERE NOT EXISTS 守卫，可重复执行」⇒ 真跑第二遍断言它
    second = pg.run_file(seed, variables)
    combined2 = second.stdout + second.stderr
    errors2 = [ln for ln in combined2.splitlines() if "ERROR:" in ln or "错误:" in ln]
    assert errors2 == [], f"第二遍执行报错：\n  " + "\n  ".join(errors2)
    assert second.returncode == 0, f"第二遍执行非零退出（exit={second.returncode}）：\n{combined2[-1200:]}"
    recounted = {
        "product_skus": pg.query(f"SELECT count(*) FROM product_skus WHERE tenant_id = {tenant};"),
        "orders": pg.query(f"SELECT count(*) FROM orders WHERE tenant_id = {tenant};"),
        "order_items": pg.query(f"SELECT count(*) FROM order_items WHERE tenant_id = {tenant};"),
    }
    assert recounted == counted, (
        f"第二遍把行数改了：{counted} → {recounted} ⇒ `WHERE NOT EXISTS` 守卫失效"
        f"（与文件头「幂等」声明不符）")


def test_harness_detects_a_broken_seed(pg, tmp_path):
    """判据②的**红证**：同一批 psql 调用碰上 issue #5502 的原始病灶 ⇒ 真断言失败。

    这是「判据会红」的机械版：把病灶段喂进**上面那条判据用的同一条命令**，
    断言非零退出 **且**报错原文命中 `syntax error at or near ":"`
    —— 没有这一条，「exit 0」可能只是因为判据根本没执行 SQL。
    """
    broken = tmp_path / "broken-seed.sql"
    broken.write_text(_BROKEN_BLOCK, encoding="utf-8")
    # 钉住**英文**报错原文：服务端消息按 `lc_messages` 本地化（本机实测中文、CI 英文），
    # 不钉死语言的话同一条判据在不同机器上读数不同。
    proc = pg.run_file(broken, {"tenant_id": "1"}, env={"PGOPTIONS": "-c lc_messages=C"})
    combined = proc.stdout + proc.stderr
    assert proc.returncode != 0, f"病灶 SQL 竟然 exit 0 ⇒ 真库判据读不出故障（假绿）：\n{combined}"
    assert 'syntax error at or near ":"' in combined, (
        f"病灶 SQL 的报错不是期待的那条 ⇒ 判据指向了错误的对象：\n{combined[-1200:]}")


def _var_args(variables: dict) -> str:
    """`-v k=v` 串（只用于断言消息里给出**可复制**的命令）。"""
    return " ".join(f"-v {k}={v}" for k, v in variables.items())