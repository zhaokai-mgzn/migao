# case_ids: MC-048
r"""真库 / 现场只读复核包（`docs/testing/production-readonly-verification-pack.md`）的**机械保证**。

## 病根（为什么一份「给人跑的取证清单」需要判据）

多张在飞单的**关单条件**要求「人在真库 / 现场做一次只读核对」，而这些 SQL 散落在
迁移文件头 · issue 评论 · PR body 三处 ⇒ 人得自己找齐，且**没有任何东西会因为这些 SQL 变坏而变红**：

1. 一块 `sql` 代码块里混进**写操作**（`UPDATE` / `DELETE` / DDL …）⇒ 人**照抄粘贴到生产库**就写库了
   —— 这是本判据存在的**唯一理由**，也是最贵的一种坏；
2. 写着「未在真库上验证」的那句声明被删掉 ⇒ 下一个人把这份清单读成**已取证的读数**；
3. **总表与各节脱钩**（表里列了 6 条、正文只有 4 节；或某节被删掉而表里还留着）
   ⇒ 人按表找节找不到、或按节跑完了却漏掉一条 —— 而同族的「说一套做一套」在本仓反复出现；
4. 某节只给 SQL、**不给判读口径**（或没有出处锚 / 没有安全说明）⇒ 拿到读数也不知道算什么样。

⇒ 本判据把这四件事各钉一条**能变红**的机械检查。**它不是新门禁**：它只保证这份文档**自己说的形态**成立。

## 判据（每条都能单独变红，红证见 `test_detection_red_proofs_in_memory`）

| # | 判据 | 取法（结构化，不读散文） | 红证（命中分支） |
|---|---|---|---|
| 1 | **`sql` 块只读** | 每个 ` ```sql ` 块过两面：**可执行面**（剥掉 SQL 注释后）里**以语句起始形态**（块首 / `;` 之后 / `(` 之后）出现的写 / DDL 动词；**原文**里**紧跟注释标记**（`--` / `/*`）的写 / DDL 动词（= 注释掉的写语句） | 塞 `;` 后的 `UPDATE` ⇒ 报「可执行面」；`WITH x AS (DELETE …)` ⇒ 报「可执行面」（`(` 形态）；`-- DELETE …` ⇒ 报「注释后」；`/* DROP … */` ⇒ 报「注释后」；小写 `delete from` ⇒ 报（大小写） |
| 2 | **诚实声明在位** | 文档必须含 `未在真库上验证` | 删掉该串 ⇒ 红 |
| 3 | **总表 ⇄ 各节逐条对应 + 锚唯一** | 总表行 `\| **R<n>** \|` 的集合 与 `## R<n> ·` 标题的集合**互相钉住**；同一个 id 不得出现两次 | 加一行无节 ⇒ 红；删一节 ⇒ 红；复制一节 ⇒ 红（锚不唯一） |
| 4 | **每节三件套在位** | `**出处锚**` / `**预期形状（判读口径）**` / `**安全说明**` 逐节必须在 | 删任一个 ⇒ 红（具名到节） |
| 5 | **fail-closed** | 文档不存在 / 文本为空 / 条目 < 下限 / 抽不到 `sql` 块 ⇒ **红**（「没东西可判」不是通过） | 清空条目 ⇒ 红；清空 `sql` 块 ⇒ 红 |

### 🔴 判据 1 为什么是「语句起始 + 注释后」这两面（第一次就写错过，如实登记）

第一版写成「**任意位置**出现写动词就红」，跑在真语料上立刻**假红 12 处**：
本包的 SQL 里到处是**权限码** `customer:create` / `inbound:create` / `order:update` / `processing:update`
—— 它们的 `create` / `update` 段被词边界命中（`: ` 是非词字符）。
⇒ 口径收紧为**只看两个真实位置**：① **可执行面里处于语句起始的动词**（`UPDATE …` / `; DELETE …` /
`WITH x AS (DELETE …)` —— 真会写库的形态）；② **注释标记之后的动词**（注释掉的写语句 ——
「照抄粘贴」时最容易被人手动放开的那一类）。
⚠️ 反过来，`UP/**/DATE` 这种「注释把动词劈两半」**不在射程**：PG 里注释等价于空白，
`UP DATE` 不是合法 `UPDATE` ⇒ 它不构成可执行面（边界照实登记，别读成本判据覆盖了它）。

## 判别力与对照（都**内存构造**，不改磁盘 —— 改磁盘的变异可能不被读到）

- 每条红证都断言**命中的是哪条分支**（报文含「可执行面」「注释后」这类点名串），
  并断言「坏形态读数 ≠ 基线读数」（防「变异没生效 ⇒ 空断言」）；
- **对照读数 ①**：在文档末尾**追加一段散文**（不碰表、不碰标题、不碰 `sql` 块）⇒ **不红**；
- **对照读数 ②**：往某个 `sql` 块里**只加一行 SQL 注释** ⇒ **不红**（注释不是可执行面；
  它同时证明判据 1 不是「见字就红」的粗暴文本匹配）。

## 明确的边界（**不要**把本判据读成覆盖面更大的东西）

- ❌ **不判 SQL 的语义正确性**：列名 / 谓词 / 结论对不对，本判据一概不管
  （「表里有没有这一列」由仓内建库脚本与真库决定，静态文本判不了）；
- ❌ **不判只读性在 PG 上的真实副作用**：它只做**文本层**判定（两个位置），
  不执行 SQL、不解析函数体 ⇒ 「某个自定义函数内部有副作用」这类形态**判不了**（本包不用自定义函数，边界照旧成立）；
- ❌ **不判注释夹心**（`UP/**/DATE`）：见上文，那不是合法 SQL（也不因此放行任何可执行面）；
- ❌ **不判出处锚能不能解析**：`出处锚` 只要求**非空**。跨库锚（issue 评论 / 在飞 PR / 未合并的迁移文件）
  本机解析不了；仓内相对路径的失效由 `tests/unit_ci_workflows/test_recomputable_command_paths.py`（M4）另行承接；
- ❌ **不判「读数回填去哪」**：那是人读文档的判断，不是机械面；
- ❌ **只覆盖这一个文件**：别的文档里混写 SQL 不在射程（M4 只管「反引号里的可复算命令指向的路径存在」）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIT_CI_DIR = REPO_ROOT / "tests" / "unit_ci_workflows"
if str(UNIT_CI_DIR) not in sys.path:
    sys.path.insert(0, str(UNIT_CI_DIR))

from _sql_schema import strip_sql_comments  # noqa: E402  （仓内唯一一份「剥 SQL 注释」实现）

#: 本判据的唯一语料（换文件必须改这里，diff 里看得见）。
DOC_REL = "docs/testing/production-readonly-verification-pack.md"
DOC_PATH = REPO_ROOT / DOC_REL

#: 写 / DDL 动词清单（大小写不敏感；只按下面两个**位置**判，不按「任意出现」判 —— 见 docstring）。
FORBIDDEN_VERBS: tuple[str, ...] = (
    "UPDATE", "INSERT", "DELETE", "CREATE", "DROP", "ALTER", "TRUNCATE", "GRANT",
    "REVOKE", "VACUUM", "MERGE", "CALL", "SET", "LOCK", "COPY", "BEGIN", "COMMIT", "ROLLBACK",
)
_VERBS = "|".join(FORBIDDEN_VERBS)
#: ① 可执行面（已剥注释）里**处于语句起始**的写 / DDL 动词：块首 / `;` 之后 / `(` 之后（含 CTE 里的写）。
EXEC_STMT_RE = re.compile(r"(?:^|;|\()\s*(" + _VERBS + r")\b", re.IGNORECASE | re.MULTILINE)
#: ② **原文**里**紧跟注释标记**的写 / DDL 动词（= 注释掉的写语句，照抄粘贴时最容易被放开的那一类）。
COMMENTED_STMT_RE = re.compile(r"(?:--|/\*)\s*(" + _VERBS + r")\b", re.IGNORECASE)

#: ` ```sql ` 围栏块（只认整行围栏；块内文本原样取出）。
SQL_BLOCK_RE = re.compile(r"^```sql[ \t]*\n(.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)
#: 总表行：`| **R1** | …`（`R` + 数字，加粗形态 —— 与正文里的 `R1-a` 这类子块记号区分开）。
TABLE_ROW_RE = re.compile(r"^\|\s*\*\*(R\d+)\*\*\s*\|", re.MULTILINE)
#: 节标题：`## R1 · …`（`###` 子标题不会被匹配：`##` 之后必须是空白）。
SECTION_RE = re.compile(r"^##\s+(R\d+)\b[^\n]*$", re.MULTILINE)
#: 每节必须有的三件套（逐字形态）。
SECTION_FIELDS: tuple[str, ...] = ("**出处锚**", "**预期形状（判读口径）**", "**安全说明**")
#: 诚实声明（逐字）。
HONESTY_MARKER = "未在真库上验证"
#: 覆盖边界节标题（逐字）。
BOUNDARY_MARKER = "## 覆盖边界"

#: 条目数下限（fail-closed：全删光 ⇒ 红；不是「没东西可判 ⇒ 绿」）。
MIN_ENTRIES = 4
#: `sql` 块数下限（同上：一块都没有 ⇒ 这份「取证清单」已经不再承载 SQL ⇒ 红）。
MIN_SQL_BLOCKS = 3


def table_entry_ids(text: str) -> list[str]:
    """总表里的条目 id（按出现顺序，含重复）。"""
    return [m.group(1) for m in TABLE_ROW_RE.finditer(text)]


def section_spans(text: str) -> list[tuple[str, str]]:
    """各节 `(id, 该节全文)`（含重复项 —— 重复正是「锚唯一」要抓的形态）。"""
    hits = list(SECTION_RE.finditer(text))
    out: list[tuple[str, str]] = []
    for i, m in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(text)
        out.append((m.group(1), text[m.start():end]))
    return out


def sql_blocks(text: str) -> list[str]:
    """文档里所有 ` ```sql ` 块的块内文本。"""
    return [m.group(1) for m in SQL_BLOCK_RE.finditer(text)]


def readonly_problems(blocks: list[str]) -> list[str]:
    """判据 1：两个位置（可执行面的语句起始 / 原文的注释之后）都不得出现写 / DDL 动词。"""
    out: list[str] = []
    for idx, block in enumerate(blocks, start=1):
        views = (
            ("可执行面（语句起始）", EXEC_STMT_RE.finditer(strip_sql_comments(block))),
            ("原文（注释标记之后）", COMMENTED_STMT_RE.finditer(block)),
        )
        for view, matches in views:
            for m in matches:
                out.append(
                    f"第 {idx} 块 `sql` 的【{view}】里出现写 / DDL 动词 {m.group(1).upper()!r}"
                    f"（只允许 SELECT / WITH / EXPLAIN）"
                )
    return out


def structure_problems(text: str) -> list[str]:
    """判据 2~5：诚实声明 / 总表 ⇄ 各节 / 锚唯一 / 三件套 / fail-closed。"""
    out: list[str] = []
    if not text.strip():
        return ["语料为空（文档不存在或没有内容）⇒ fail-closed 判红：没东西可判不是通过"]

    table = table_entry_ids(text)
    sections = section_spans(text)
    section_ids = [sid for sid, _ in sections]
    blocks = sql_blocks(text)

    if HONESTY_MARKER not in text:
        out.append(f"缺诚实声明：文档里必须逐字含 {HONESTY_MARKER!r}（否则会被读成已取证的读数）")
    if BOUNDARY_MARKER not in text:
        out.append(f"缺覆盖边界节（逐字 {BOUNDARY_MARKER!r}）")
    if len(table) < MIN_ENTRIES:
        out.append(f"总表条目 {len(table)} 条 < 下限 {MIN_ENTRIES} 条 ⇒ fail-closed")
    if len(blocks) < MIN_SQL_BLOCKS:
        out.append(f"`sql` 块 {len(blocks)} 块 < 下限 {MIN_SQL_BLOCKS} 块 ⇒ fail-closed")
    for label, ids in (("总表", table), ("各节", section_ids)):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            out.append(f"{label}里锚不唯一（同一 id 出现多次）：{dupes}")
    only_table = sorted(set(table) - set(section_ids))
    only_sections = sorted(set(section_ids) - set(table))
    if only_table:
        out.append(f"总表有而各节没有（人按表找节会找不到）：{only_table}")
    if only_sections:
        out.append(f"各节有而总表没有（人按表跑会漏掉这一节）：{only_sections}")
    for sid, body in sections:
        for field in SECTION_FIELDS:
            if field not in body:
                out.append(f"{sid} 节缺 {field}（只给 SQL 不给判读口径 / 没出处锚 / 没安全说明）")
    return out


def pack_problems(text: str) -> list[str]:
    """全部判据的合成（纯函数：喂内存构造的文本即可做红证）。"""
    return structure_problems(text) + readonly_problems(sql_blocks(text))


def read_pack() -> str:
    """真语料（磁盘上的那份文档）。"""
    return DOC_PATH.read_text(encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════════
# 一、真语料上的判据
# ══════════════════════════════════════════════════════════════════════════════


def test_pack_file_exists_and_carries_sql():
    """fail-closed 的前置：文档存在、且真的承载 SQL（否则后面几条判据会在空集上恒真）。"""
    assert DOC_PATH.exists(), f"复核包文档不存在：{DOC_REL}"
    text = read_pack()
    print(f"语料 {DOC_REL}：{len(text)} 字符 · 总表 {len(table_entry_ids(text))} 条 · "
          f"各节 {len(section_spans(text))} 节 · `sql` 块 {len(sql_blocks(text))} 块")
    assert table_entry_ids(text) and sql_blocks(text), "总表或 sql 块为空 ⇒ 判据会在空集上恒真（fail-closed）"


def test_sql_blocks_are_read_only():
    """判据 1：`sql` 块只读（可执行面的语句起始 + 原文的注释之后，大小写不敏感）。"""
    blocks = sql_blocks(read_pack())
    problems = readonly_problems(blocks)
    print(f"只读性：{len(blocks)} 块 `sql`，违规 {len(problems)} 处")
    for p in problems:
        print(f"  · {p}")
    assert problems == [], "复核包里有非只读 SQL：\n" + "\n".join(f"  · {p}" for p in problems)


def test_permission_codes_are_not_flagged():
    """**负控（第一次就踩过）**：权限码里的 `create` / `update` 段**不许**被当成写动词。"""
    probe = "SELECT 1 WHERE code IN ('customer:create', 'order:update', 'processing:update');\n"
    assert readonly_problems([probe]) == [], f"权限码被误判成写动词：{readonly_problems([probe])}"


def test_structure_is_self_consistent():
    """判据 2~5：诚实声明 / 总表 ⇄ 各节 / 锚唯一 / 三件套 / fail-closed。"""
    problems = structure_problems(read_pack())
    print(f"结构：违规 {len(problems)} 处")
    for p in problems:
        print(f"  · {p}")
    assert problems == [], "复核包结构不自洽：\n" + "\n".join(f"  · {p}" for p in problems)


def test_every_required_entry_has_sql_or_explicitly_says_it_has_none():
    """**强化**：总表里标「必做」的条目必须有 `sql` 块，或在该节里显式写「不开 SQL / 不跑 SQL / 没有 SQL」。"""
    text = read_pack()
    required = {m.group(1) for m in re.finditer(r"^\|\s*\*\*(R\d+)\*\*\s*\|\s*必做\s*\|", text, re.MULTILINE)}
    assert required, "总表里没有任何「必做」条目 ⇒ 判据在空集上恒真（fail-closed）"
    problems: list[str] = []
    for sid, body in section_spans(text):
        if sid not in required:
            continue
        has_sql = bool(sql_blocks(body))
        says_none = ("不跑 SQL" in body) or ("不开 SQL" in body) or ("没有 SQL" in body)
        if not (has_sql or says_none):
            problems.append(f"{sid} 是必做条目，但既没有 `sql` 块、也没有显式说明「不开 SQL」")
    assert problems == [], "\n".join(f"  · {p}" for p in problems)


# ══════════════════════════════════════════════════════════════════════════════
# 二、判别力自证（全部**内存构造**：真文档当基线、变异体直接喂纯函数）
# ══════════════════════════════════════════════════════════════════════════════


def _mutant(old: str, new: str) -> tuple[str, str]:
    """在真语料上做一次内存替换（**所有**命中）；返回 `(基线, 变异体)`；没换到 ⇒ 判红（防空断言）。

    ⚠️ 替换**全部**命中而不是第一处：诚实声明这类串在文档里出现多次，
    只换第一处会让「删掉声明 ⇒ 红」这条红证**恒绿**（读起来像「判据没生效」，实际是变异没删干净）。
    """
    base = read_pack()
    mutated = base.replace(old, new)
    assert mutated != base, f"变异没生效（锚失配）⇒ 红证会是空断言：{old!r}"
    return base, mutated


def test_detection_red_proofs_in_memory():
    """红证逐条：变异 → **命中分支**（报文点名）→ 与基线读数不同。"""
    base = read_pack()
    assert pack_problems(base) == [], f"基线必须先干净，否则后面的红证分不清是谁报的：{pack_problems(base)}"

    # ① 可执行面（`;` 之后的写语句）
    _, m1 = _mutant("LIMIT 500;", "LIMIT 500;\nUPDATE tenants SET name = name;")
    p1 = readonly_problems(sql_blocks(m1))
    assert any("可执行面" in p and "UPDATE" in p for p in p1), f"`;` 之后的写语句没被判红：{p1}"

    # ② 可执行面（`(` 形态：写语句藏在 CTE 里）
    _, m2 = _mutant("SELECT COUNT(*) AS scoped_tenants",
                    "WITH x AS (DELETE FROM role_permissions RETURNING 1) SELECT COUNT(*) AS scoped_tenants")
    p2 = readonly_problems(sql_blocks(m2))
    assert any("可执行面" in p and "DELETE" in p for p in p2), f"CTE 里的写语句没被判红：{p2}"

    # ③ 原文（`--` 注释掉的写语句 —— 照抄粘贴时最容易被放开的那一类）
    _, m3 = _mutant("-- R1-a 射程：", "-- R1-a 射程（先删干净）：\n-- DELETE FROM role_permissions;")
    p3 = readonly_problems(sql_blocks(m3))
    assert any("注释标记之后" in p and "DELETE" in p for p in p3), f"注释掉的写语句没被判红：{p3}"

    # ④ 原文（块注释形态）+ 大小写不敏感
    _, m4 = _mutant("-- R3-a 哪些岗位", "/* drop table users; */\n-- R3-a 哪些岗位")
    p4 = readonly_problems(sql_blocks(m4))
    assert any("注释标记之后" in p and "DROP" in p for p in p4), f"块注释里的 DDL 没被判红：{p4}"

    # ⑤ 诚实声明被删（**所有**命中一起换掉 —— 只换一处的话声明还在，红证会变成空断言）
    _, m5 = _mutant(HONESTY_MARKER, "已核对")
    assert any("缺诚实声明" in p for p in structure_problems(m5)), f"删掉诚实声明没被判红：{structure_problems(m5)}"

    # ⑥ 总表多一行、没有对应节
    _, m6 = _mutant("| **R6** | 可选 |", "| **R7** | 必做 | 临时加的条目 | 无 | 人 | 无 |\n| **R6** | 可选 |")
    assert any("总表有而各节没有" in p and "R7" in p for p in structure_problems(m6)), "孤儿表行没被判红"

    # ⑦ 删掉一整节（R3）⇒ 表里还留着
    _, m7 = _mutant("## R3 · 回退路径账号普查", "## （本节已删）")
    assert any("总表有而各节没有" in p and "R3" in p for p in structure_problems(m7)), "删节没被判红"

    # ⑧ 锚唯一：复制一份 R2 节标题
    _, m8 = _mutant("## R2 · `production:execute` 快照回填的命中面",
                    "## R2 · `production:execute` 快照回填的命中面\n\n蹭一节\n\n## R2 · `production:execute` 快照回填的命中面")
    assert any("锚不唯一" in p for p in structure_problems(m8)), "重复锚没被判红"

    # ⑨ 三件套缺失（具名到节）
    _, m9 = _mutant("**安全说明**：只读（四段 `SELECT`", "**安全说明（已删）**：只读（四段 `SELECT`")
    assert any("R2 节缺" in p and "安全说明" in p for p in structure_problems(m9)), "缺三件套没被判红（且没具名到节）"

    # ⑩ fail-closed：sql 块清空 / 条目清空 / 空语料
    emptied = re.sub(r"```sql.*?```", "", base, flags=re.DOTALL)
    assert emptied != base, "清空 sql 块的变异没生效"
    assert any("fail-closed" in p for p in structure_problems(emptied)), "清空 sql 块没判红（fail-closed）"
    assert structure_problems("") != [], "空语料没判红（fail-closed）"

    # ⑪ 判别力自证：坏形态读数 ≠ 基线读数（防「变异没被读到 ⇒ 空断言」）
    assert pack_problems(m1) != pack_problems(base), "坏形态与基线读数相同 ⇒ 变异没被读到（空断言）"


def test_comment_only_change_is_not_red():
    """对照读数（两条）：**只加散文 / 只加 SQL 注释** ⇒ **不红**，证明判据不是「见字就红」。"""
    base = read_pack()
    assert pack_problems(base) == []

    # ① 文档末尾追加一段散文（不碰总表 / 标题 / sql 块）
    _, prose = _mutant("# 真库 / 现场只读复核包（一次跑完）",
                       "# 真库 / 现场只读复核包（一次跑完）\n\n<!-- 复核记录：本轮只加了这句话 -->")
    assert pack_problems(prose) == [], f"只加散文却判红了：{pack_problems(prose)}"

    # ② 往 `sql` 块里**只加一行 SQL 注释**（注释不是可执行面）
    _, commented = _mutant("-- R1-a 射程：", "-- R1-a 射程（本轮只改了这行注释）：")
    assert pack_problems(commented) == [], f"只改 SQL 注释却判红了：{pack_problems(commented)}"
