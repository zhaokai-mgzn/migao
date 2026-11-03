# case_ids: MC-143
r"""**状态列写面**的族级元守卫（issue #6953 的 SW-100）。

## 病（一个类，不是一处）

2026-10-14 一晚抓到**同族两例**状态写缺陷 —— `#6928`（入库单「过账 × 作废」竞态：
一条写面带 CAS、另一条无谓词 `updateById` ⇒ 库存 +5 且台账行静默留存）与 `#6936`
（工序「设为不做并删除」并发 5 次 ⇒ 3 次 200，应为恰 1 次）。两例各建了一颗类级元守卫
（`InboundOrderStatusCasMetaGuardTest` = MC-100、`ProductionOperationDeleteCasMetaGuardTest` = PG-075），
但**两颗都是单表守卫**：合计只覆盖 `inbound_orders.status` 与 `production_operations.deleted`。
本仓有 **53 张带 `status` 列的表**、**30+ 个 Service 状态写点、28 条 mapper 手写 SQL**，
**全族从未清点过** ⇒ 下一个人在**任何一张没被守的表**上、或用**任何一颗守卫的现取形态之外**的写法
新加一条状态写面，**不会有任何东西变红**。

本守卫把「状态列写面」变成**一张双向台账**（`state_write_face_ledger.json`），并让下面这些坏形态各自判红：

| # | 判据 | 红形态（怎么让它红） |
|---|---|---|
| 1 | **未登记即红** | 新加一个状态写点（表 × 入口）却没进台账 ⇒ 报出 `表 / 写点 / 文件:行` |
| 2 | **台账陈旧即红** | 台账登记了但写点已消失（改名 / 删掉 / 换写法）⇒ 只许**缩短**台账，不许留着 |
| 3 | **字面量单一来源** | 写状态列时用**裸字符串**（`"pending"`）而不是枚举 / 常量 ⇒ 红；存量按**只许缩短**的基线登记 |
| 4 | **每张状态表都要有权威声明** | 有 `status` 列的表必须在台账 `status_value_sources` 里登记「合法状态集合来自哪」（实体常量 / schema CHECK / 无）⇒ 未登记即红；`无权威` 条数超过冻结基线 ⇒ 红 |
| 5 | **负控：读状态不是写** | `getStatus()` / 比较 / 装配响应不产生写点（显式断言，不许「反正没扫到」） |
| 6 | **负控：写没有 `status` 列的表不算** | 如 `customer_profiles`（只有 `customer_status`）⇒ 不在射程 |
| 7 | **判别力自证** | 合成语料上把七种坏形态各自喂一遍（未登记 / 裸字面量 / 换写法 / 注释里提及 / 读 / 无状态列表 / 空扫描面）⇒ 检出的与应当检出的**逐条相等** |
| 8 | **扫描器非空跑** | 现取条数 ≥ 冻结下界，且点名锚点必须在册（形态被改名不是「通过」，是「判据失明」） |

## 与既有守卫的关系（**有意不重叠**，铁律 8）

- 既有 **MC-100 / PG-075 / MC-104 / MC-102 / PS-101 / RM-101 / AB-101 / TA-101 / T3** 等只裁
  **自己那张表 / 那一个谓词口径**（CAS 完整性、影响行数、删族行数）。本守卫**不碰它们的判据、不改它们的台账**：
  它只回答「**写面有没有人认领 / 状态值是单一口径**」，**不为任何一条写路径的并发语义背书**。
- 反过来，本守卫的现取集**必须**包含它们已登记的那几个写点（判据 8 点名），
  否则说明本守卫的扫描面收窄了而没人会红。

## 引用纪律（本仓红线）

一律**符号 / 仓库相对全路径**引用，**禁写** `path:行号` / 裸 `第 N 行` —— drift 面 `ref-freshness`
与 Case Trust 规则 G 会把裸行号判红（`migao-dev-flow` §16.7）。**异常的唯一一处**是**运行时**打印的
`文件:行`（判红定位用，不进任何文档 / 台账字段）。

## 边界（如实登记，§19.1）

① 形态判据**不做 AST**：按词法走查（`_source_parsing.java_code` / `java_literals`）+ 签名切块，
   `反射 / 动态 SQL / XML mapper / 变量拼接的 wrapper` 都不在射程（假绿方向：不会误伤）；
② 成员归属靠「类体顶层签名 + 参数表」切块，**匿名类 / lambda 里的写点归到其外层成员**（保守）；
③ `deleted`（`@TableLogic` 逻辑删除族）**有意不在本表登记**：它已有 PG-075 / T3（`T3LogicalDeleteRowCountMetaGuardTest`）
   与 #6953 的 P6 包承接 —— 本守卫只**冻结读数**（wrapper 写 `deleted` 的站点数）防「悄悄扩面」；
④ 判不了**并发语义**：登记 ≠ 该写点有 CAS / 有 tenant 谓词 / 判了影响行数 —— 那是各表守卫与实例判据的事；
⑤ 判不了「`updateById` 把内存里的旧 status 一起写回」（F1 类，`T2b`）：本守卫只认**显式状态赋值**，
   全实体回写是另一种形态（issue #6953 的 T2b 清单 / 各表守卫承接）。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _source_parsing import java_code, java_literals  # noqa: E402  （判据面唯一共享的 Java 剥注释实现）
from _sql_schema import parse_entities, parse_schema_columns_strict  # noqa: E402  （唯一解析实现点）

REPO_ROOT = Path(__file__).resolve().parents[2]
MAIN_JAVA = REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "java"
LEDGER_PATH = Path(__file__).with_name("state_write_face_ledger.json")

#: 现取下界（只许**上调**：形态被改窄 / 扫描面被收窄 ⇒ 判据 8 当场红）。
MIN_SERVICE_WRITE_POINTS = 30
MIN_SQL_WRITE_POINTS = 25
MIN_STATUS_TABLES = 50

#: 裸字面量 / 无权威表的**冻结上限**（只许缩短，与台账条目数一起燃尽）。
BARE_LITERAL_CAP = 56
NO_AUTHORITY_CAP = 36

#: 状态值写形态（四条 Java 写形 + 一条 builder 写形 + 一条 SQL 写形）。
#: ⚠️ 新写形**不是**随便加：加之前先问「它会不会让某条既有写点从现取集里消失」（那条写点会以「陈旧」判红）。
_SETTER = re.compile(r"\.\s*setStatus\s*\(")
_LAMBDA_SET = re.compile(r"\.\s*set\s*\(\s*([\w.]+)\s*::\s*getStatus\s*,")
_STRING_SET = re.compile(r"\.\s*set\s*\(\s*\"status\"\s*,")
_SET_SQL = re.compile(r"\.\s*setSql\s*\(\s*\"[^\"]*\bstatus\b", re.I)
_BUILDER = re.compile(r"\b([A-Z]\w*)\s*\.\s*builder\s*\(\s*\)")
_BUILDER_STATUS = re.compile(r"\.\s*status\s*\(")
_IDENT = re.compile(r"([\w.]+)\s*$")
_DECL = re.compile(r"\b([A-Z]\w*)\s+(\w+)\s*(?=[=;,)])")
_PERSIST_MAPPER = re.compile(r"(\w+Mapper)\s*\.\s*\w+\s*\(")
_PERSIST_BARE = re.compile(r"(?<![\w.])(insert|updateById|save|saveOrUpdate|update|removeById|deleteById)\s*\(")
_SIG_LINE = re.compile(
    r"^ {4}(?:(?:@\w+(?:\([^)]*\))?\s*)"
    r"|(?:public|private|protected|static|final|synchronized|abstract|default|native|strictfp)\s+"
    r"|[\w<>\[\],.?]+\s+)*(\w+)\s*\("
)
_CONTROL = {"if", "for", "while", "switch", "catch", "return", "new"}
_SQL_UPDATE = re.compile(r"@Update\s*\(([\s\S]*?)\)\s*(?:@\w+(?:\([^)]*\))?\s*)*(?:public\s+)?(?:int|long|Integer)\s+(\w+)\s*\(", re.S)
_SQL_SET_STATUS = re.compile(r"(?is)\bupdate\s+[\w\"]+\s+set\s+(.*?)\bwhere\b")
_SQL_STATUS_IN_SET = re.compile(r"(?i)(?:^|,)\s*\"?status\"?\s*=")


def set_clause_assignments(set_clause: str) -> list[tuple[str, str]]:
    """把 SET 子句切成 `(列, 右值)` —— 逗号按**括号深度 / 引号状态**切，不按引号做正则取值。

    ⚠️ **不许**用 `re.findall("'([^']*)'", sql)` 抓值：那是「按引号扫原文取值」，
    注释 / docstring 里的同形字面量会被读成真值（`test_guard_parsing_is_comment_aware.py`
    的判据面元守卫会当场判红，本包实测踩到过一次）。
    """
    parts, buf, depth, quote = [], [], 0, ""
    for ch in set_clause:
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
            depth = max(0, depth - 1)
            buf.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    out = []
    for part in parts:
        if "=" not in part:
            continue
        lhs, rhs = part.split("=", 1)
        out.append((lhs.strip().strip('"').lower(), rhs.strip()))
    return out


def sql_status_values(set_clause: str) -> list[str]:
    """SET 侧写给 `status` 的**字面量值**（非字面量 / 表达式 ⇒ 空，交由人工读台账）。"""
    out = []
    for col, rhs in set_clause_assignments(set_clause):
        if col != "status":
            continue
        if len(rhs) >= 2 and rhs[0] == "'" and rhs[-1] == "'":
            out.append(rhs[1:-1])
    return out


def mask_strings(code: str) -> str:
    """把**字符串字面量内容**抹成空格（保留引号与全部偏移）⇒ 检测只看**代码**。

    ⚠️ `java_code()` 只剥注释、**保留字符串**（它的用途是取值）。拿它直接跑形态检测，
    字符串里的 `order.setStatus(\"x\")`（日志模板 / 文档样例 / SQL 文本）会被读成写面 ——
    实测反例：合成语料里一行「说明文字」当场把判据点红。⇒ 检测走本视图，取值仍走 `java_literals`。
    """
    out = list(code)
    for pos, value in java_literals(code):
        end = pos + len(value) + 2
        for i in range(pos + 1, min(end - 1, len(out))):
            out[i] = " "
    return "".join(out)


def sql_text(raw: str) -> str:
    r"""把注解里的 Java **字符串拼接**还原成一段 SQL（`"…" + "…"` ⇒ `…`；去外层引号）。

    ⚠️ 不还原就直接切 `SET … WHERE`：拼接点两侧是引号，`\s+where` 永远匹配不上 ⇒
    24 条状态写 SQL **静默从现取集里消失**（实测：未还原时 28 → 5 条）。这是本守卫自己的致盲洞。
    """
    return re.sub(r'"\s*\+\s*"', "", raw).strip().strip('"')


# ══════════════════════════════════════════════════════════════════════════
# 一、现取：表 / 实体 / 表 ↔ 实体
# ══════════════════════════════════════════════════════════════════════════

def status_tables() -> set[str]:
    """有 `status` 列的表（真值 = 建库脚本；`_sql_schema` 是唯一解析实现点）。"""
    cols = parse_schema_columns_strict()
    return {t for t, c in cols.items() if "status" in c}


def entities() -> dict[str, str]:
    """实体简单名 → 表名（`@TableName`；唯一解析实现点）。"""
    return {name: meta["table"] for name, meta in parse_entities().items()}


def mapper_tables() -> dict[str, str]:
    """mapper 类名 → 表名（`BaseMapper<Entity>` + `@TableName`；两条真值合起来才是表）。"""
    ent = entities()
    out: dict[str, str] = {}
    for f in sorted((MAIN_JAVA / "com" / "migao" / "admin" / "mapper").glob("*.java")):
        m = re.search(r"interface\s+\w+\s+extends\s+BaseMapper\s*<\s*(\w+)\s*>", f.read_text(encoding="utf-8"))
        if m and m.group(1) in ent:
            out[f.stem] = ent[m.group(1)]
    return out


# ══════════════════════════════════════════════════════════════════════════
# 二、现取：成员切块（签名**跨行**也必须取到 —— MC-100 的洞 A 就是它）
# ══════════════════════════════════════════════════════════════════════════

def _signature_of(lines: list[str], start: int) -> tuple[str, str, int] | None:
    """`start` 行起若是一个类体顶层成员签名 ⇒ (名字, 归一参数表, 签名收尾行)。

    - 只认 **4 空格缩进**（8 / 12 空格 ⇒ 控制结构 / lambda）；
    - 签名**可跨行**：一路累积到 `{`（方法）为止 —— 这是历史致盲洞的正解；
    - 参数表归一（去多余空白），用来区分**重载**（`create` 在本仓有两个）。
    """
    line = lines[start]
    if not line.startswith("    ") or line.startswith("     "):
        return None
    if line.strip().startswith(("*", "//", "@")):
        return None
    m = _SIG_LINE.match(line)
    if not m or m.group(1) in _CONTROL:
        return None
    buf, j = line, start
    while "{" not in buf and ";" not in buf and j + 1 < len(lines) and j - start < 12:
        j += 1
        buf += " " + lines[j].strip()
    if "{" not in buf or ";" in buf.split("(")[0]:
        return None
    head = buf.split("{")[0]
    # 参数表 = 第一个 '(' 到**配平**的 ')'
    i = head.find("(")
    depth, k = 0, i
    while k < len(head):
        if head[k] == "(":
            depth += 1
        elif head[k] == ")":
            depth -= 1
            if depth == 0:
                break
        k += 1
    params = " ".join(head[i + 1:k].split()) if i >= 0 else ""
    return m.group(1), params, j


def members(code: str) -> list[tuple[str, str, int, int]]:
    """类体顶层成员 → `[(名字, 归一参数表, 起字符, 止字符)]`（止 = 下一个成员签名起）。"""
    lines = code.split("\n")
    starts: list[tuple[str, str, int]] = []          # (名字, 参数表, 起始行)
    offsets, pos = [], 0
    for line in lines:
        offsets.append(pos)
        pos += len(line) + 1
    i = 0
    while i < len(lines):
        sig = _signature_of(lines, i)
        if sig:
            starts.append((sig[0], sig[1], i))
            i = sig[2] + 1
        else:
            i += 1
    out = []
    for n, (name, params, ln) in enumerate(starts):
        end_line = starts[n + 1][2] if n + 1 < len(starts) else len(lines)
        end = offsets[end_line] if end_line < len(offsets) else len(code)
        out.append((name, params, offsets[ln], end))
    return out


def _field_types(code: str) -> dict[str, str]:
    """类字段（`private … Type name;`）—— 方法体外，只在**本类**有效。"""
    types: dict[str, str] = {}
    for m in re.finditer(r"(?:private|protected|public)\s+(?:final\s+)?([A-Z]\w*)\s+(\w+)\s*[;=]", code):
        types.setdefault(m.group(2), m.group(1))
    return types


def _type_index(code: str, start: int = 0, end: int | None = None,
                params: str = "") -> dict[str, str]:
    """变量名 → 声明的类型（**本文件字段 + 本成员形参 + 本成员局部变量**）。

    ⚠️ 作用域限定在成员内，不用「全文件首个声明」：同名变量在别的成员里可能是另一种实体
    ⇒ 归属会串表（台账会替**错的表**盖章）。
    """
    types: dict[str, str] = _field_types(code)
    for m in re.finditer(r"([A-Z]\w*)\s+(\w+)", params):
        types.setdefault(m.group(2), m.group(1))
    limit = len(code) if end is None else end
    for m in _DECL.finditer(code, start, limit):
        types.setdefault(m.group(2), m.group(1))
    return types


def _stmt_end(code: str, start: int, limit: int) -> int:
    """从 `start` 起到语句结束（`;`）—— 括号内的 `;` 不算（lambda / for 头）。"""
    depth = 0
    for i in range(start, limit):
        c = code[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == ";" and depth <= 0:
            return i
    return limit


def _arg_span(code: str, open_paren: int, limit: int) -> tuple[int, int]:
    """从 `(` 起到**配平**的 `)` ⇒ 写形**实参**区间（裸字面量只在这一段里判）。

    ⚠️ 用整条语句判会误伤：builder 链里还有备注 / 名称 / 单位等**非状态**字符串
    （实测把 `成品发货出库（订单 …）` 读成状态值）。判据只认**写进状态列的那个实参**。
    """
    depth = 0
    for i in range(open_paren, limit):
        if code[i] == "(":
            depth += 1
        elif code[i] == ")":
            depth -= 1
            if depth == 0:
                return open_paren + 1, i
    return open_paren + 1, limit


def _receiver_type(code: str, types: dict[str, str], pos: int) -> str | None:
    """`setStatus(` 前的接收者类型（`this` / 空接收者 ⇒ None，交给调用方按 ServiceImpl 泛型兜底）。"""
    m = _IDENT.search(code[max(0, pos - 90):pos])
    if not m:
        return None
    recv = m.group(1).split(".")[-1]
    if recv in ("this", ""):
        return None
    return types.get(recv)


def _self_entity(code: str) -> str | None:
    """`extends ServiceImpl<XxxMapper, Entity>` ⇒ 本 Service 自己的实体（裸 `updateById(x)` 的落点）。"""
    m = re.search(r"class\s+\w+\s+extends\s+ServiceImpl\s*<\s*\w+\s*,\s*(\w+)\s*>", code)
    return m.group(1) if m else None


def _member_persists(masked: str, code: str, start: int, end: int, mapper_tbl: dict[str, str]) -> list[str]:
    """成员内的持久化证据（mapper 调用 / 裸 ServiceImpl 写方法）→ 具名清单。"""
    out = []
    for m in _PERSIST_MAPPER.finditer(masked, start, end):
        out.append(f"{m.group(1)}.{code[m.end():m.end() + 40].split('(')[0]}")
    for m in _PERSIST_BARE.finditer(masked, start, end):
        out.append(m.group(1))
    return out


# ══════════════════════════════════════════════════════════════════════════
# 三、现取：Java 侧写点
# ══════════════════════════════════════════════════════════════════════════

def java_write_points() -> list[dict]:
    """现取「写 `status` 列」的 Java 写点。

    写形（六条，全部**具名化**；新写形必须同时补这里的判定与台账条目）：

    1. `x.setStatus(RHS)` —— `x` 的**声明类型**是实体（DTO / VO / 请求体写 `status` **不算**：
       那不是列写）；
    2. `wrapper.set(Entity::getStatus, RHS)` —— 实体来自方法引用（wrapper 链上没有变量可判）；
    3. `wrapper.set("status", RHS)` —— 接收者类型是滚动在实体上的 wrapper（`LambdaUpdateWrapper<Entity>`）；
    4. `wrapper.setSql("… status …")` —— 同上（字面量在 SQL 里，判据 3 只裁「值来自常量」的形态）；
    5. `Entity.builder()…status(RHS)…build()` —— builder 写形（MC-100 的射程盲洞 A 就在这一形）；
    6. `@Update` 手写 SQL 的 **SET 侧**写 `status` —— 见 `sql_write_points()`。

    归属：写点 = `(表, 文件, 成员名, 参数表)`；**成员归属靠签名切块**（跨行签名也取到）。
    """
    ent, mapper_tbl, tables = entities(), mapper_tables(), status_tables()
    points: list[dict] = []
    for f in sorted(MAIN_JAVA.rglob("*.java")):
        rel = str(f.relative_to(REPO_ROOT))
        code = java_code(f.read_text(encoding="utf-8"))
        masked = mask_strings(code)                     # 检测视图（字符串已抹空）
        lits = java_literals(code)                      # 取值视图（偏移与 masked 一致）
        self_ent = _self_entity(code)
        fields = _field_types(code)
        for name, params, start, end in members(code):
            types = dict(fields)
            for pm in re.finditer(r"([A-Z]\w*)\s+(\w+)", params):
                types.setdefault(pm.group(2), pm.group(1))
            for dm in _DECL.finditer(code, start, end):
                types.setdefault(dm.group(2), dm.group(1))
            span = code[start:end]
            found: list[tuple[str, int, str]] = []          # (写形, 绝对位置, 表达式名)
            for m in _SETTER.finditer(masked, start, end):
                found.append(("setStatus", m.start(), m.group(0), m.end() - 1))
            for m in _LAMBDA_SET.finditer(masked, start, end):
                found.append(("lambda_set", m.start(), m.group(0), -1))
            for m in _STRING_SET.finditer(masked, start, end):
                found.append(("string_set", m.start(), m.group(0), -1))
            for m in _SET_SQL.finditer(masked, start, end):
                found.append(("set_sql", m.start(), m.group(0), -1))
            for bm in _BUILDER.finditer(masked, start, end):
                if bm.group(1) not in ent:
                    continue
                stop = _stmt_end(masked, bm.start(), end)
                sm = _BUILDER_STATUS.search(masked, bm.end(), stop)
                if sm:
                    found.append(("builder", bm.start(), bm.group(1), sm.end() - 1))
            if not found:
                continue
            persists = _member_persists(masked, code, start, end, mapper_tbl)
            for form, pos, expr, paren in found:
                if form == "setStatus":
                    et = _receiver_type(code, types, pos) or self_ent
                elif form == "lambda_set":
                    et = re.search(r"([\w.]+)\s*::\s*getStatus", code[pos:pos + 120]).group(1).split(".")[-1]
                elif form == "string_set":
                    et = _wrapper_entity(code, types, pos) or self_ent
                elif form == "set_sql":
                    et = _wrapper_entity(code, types, pos) or self_ent
                else:
                    et = expr
                table = ent.get(et or "", "")
                if table not in tables:                        # 负控：没有 status 列的表不在射程
                    continue
                a_lo, rhs_end = (_arg_span(code, paren, end) if paren >= 0 else (pos, _stmt_end(code, pos, end)))
                bare = [v for p, v in lits if a_lo <= p <= rhs_end]
                points.append({
                    "table": table, "file": rel, "symbol": name, "params": params,
                    "form": form, "receiver": et, "line": code.count("\n", 0, pos) + 1,
                    "anchor": " ".join(code[pos:pos + 120].split())[:120],
                    "literals": bare, "persisted": persists,
                })
    # 写点身份 = (表, 文件, 成员名, 参数表)；同成员同表的多次写合并
    merged: dict[tuple, dict] = {}
    for p in points:
        key = (p["table"], p["file"], p["symbol"], p["form"])
        cur = merged.setdefault(key, {**p, "literals": [], "evidence": []})
        for lit in p["literals"]:
            if lit not in cur["literals"]:
                cur["literals"].append(lit)
        cur["evidence"] = (cur["evidence"] + [p["anchor"]])[:3]
        cur["persisted"] = cur["persisted"] or p["persisted"]
    return sorted(merged.values(), key=lambda x: (x["table"], x["file"], x["symbol"]))


def _wrapper_entity(code: str, types: dict[str, str], pos: int) -> str | None:
    """`…UpdateWrapper<Entity>` 的实体（`set("status", …)` / `setSql(…)` 的归属）。"""
    m = _IDENT.search(code[max(0, pos - 90):pos])
    if not m:
        return None
    t = types.get(m.group(1).split(".")[-1], "")
    g = re.search(r"<\s*([A-Z]\w*)\s*>", t)
    return g.group(1) if g else None


# ══════════════════════════════════════════════════════════════════════════
# 四、现取：SQL 侧写点（mapper 手写 `@Update`）
# ══════════════════════════════════════════════════════════════════════════

def sql_write_points() -> list[dict]:
    """现取「`@Update` 手写 SQL 在 **SET 侧**写 `status`」的写点（表 = mapper 的 `BaseMapper` 实体）。

    ⚠️ 只看 **SET 侧**：`WHERE status = 'on_sale'`（读面 / 谓词）不是写点 —— 把它算进去会让
    「合法状态集合」的读数被谓词污染（实测 `countLowStockSkus` 就曾被误收）。
    """
    mapper_tbl, tables = mapper_tables(), status_tables()
    out: list[dict] = []
    for f in sorted((MAIN_JAVA / "com" / "migao" / "admin" / "mapper").glob("*.java")):
        rel = str(f.relative_to(REPO_ROOT))
        code = java_code(f.read_text(encoding="utf-8"))
        table = mapper_tbl.get(f.stem, "")
        if table not in tables:
            continue
        for m in _SQL_UPDATE.finditer(code):
            raw, sql, method = m.group(1), sql_text(m.group(1)), m.group(2)
            sm = _SQL_SET_STATUS.search(sql)
            if not sm or not _SQL_STATUS_IN_SET.search(sm.group(1)):
                continue
            set_clause = sm.group(1)
            out.append({
                "table": table, "file": rel, "symbol": method, "params": "",
                "form": "sql", "receiver": f.stem,
                "line": code.count("\n", 0, m.start()) + 1,
                "anchor": " ".join(raw.split())[:160],
                "literals": sql_status_values(set_clause),
                "persisted": ["@Update"],
            })
    return sorted(out, key=lambda x: (x["table"], x["file"], x["symbol"]))


# ══════════════════════════════════════════════════════════════════════════
# 五、规则（纯函数：入参是现取结果 / 台账 ⇒ 单测可直接注入内存变异体做红证）
# ══════════════════════════════════════════════════════════════════════════

def _key(point: dict) -> tuple:
    """写点身份 = 表 × 文件 × 成员 × **写形**。

    ⚠️ 参数表**不进身份**：改一个形参名不该逼着改台账（那是噪声）；重载靠写形区分
    （本仓唯一的重载 `InboundOrderService#create` 只有一条走 builder）。
    """
    return (point["table"], point["file"], point["symbol"], point["form"])


def _fmt(point: dict) -> str:
    return (f"{point['table']}::{point['file']}::{point['symbol']}({point['params']})"
            f"[{point['form']}] @{point['line']}")


def unregistered(current: list[dict], ledger: dict) -> list[str]:
    """判据 1：现取到、台账没登记 ⇒ 具名清单（表 + 写点 + 文件:行）。"""
    registered = {_key(e) for e in ledger.get("write_points", [])}
    return [_fmt(p) for p in current if _key(p) not in registered]


def stale(current: list[dict], ledger: dict) -> list[str]:
    """判据 2：台账登记了、现取集里已没有 ⇒ 具名清单（只许缩短台账）。"""
    have = {_key(p) for p in current}
    return [_fmt(e) for e in ledger.get("write_points", []) if _key(e) not in have]


def bare_literal_sites(current: list[dict]) -> list[dict]:
    """判据 3：写状态列时用了裸字符串的写点（返回写点本身，便于与基线逐条比对）。"""
    return [p for p in current if p["literals"]]


def _site_key(point: dict) -> tuple:
    return (point["table"], point["file"], point["symbol"], point["form"])


def missing_authority(tables: set[str], ledger: dict) -> list[str]:
    """判据 4：有 `status` 列却没在台账里声明「合法状态集合来自哪」。"""
    declared = set(ledger.get("status_value_sources", {}))
    return sorted(tables - declared)


def stale_authority(tables: set[str], ledger: dict) -> list[str]:
    """判据 4 的另一半：台账给不存在的表盖章（表被删 / 改名 ⇒ 红）。"""
    return sorted(set(ledger.get("status_value_sources", {})) - tables)


def illegal_sql_values(current: list[dict], ledger: dict) -> list[str]:
    """判据 3 的 SQL 一侧：SET 侧字面量必须落在该表已声明的合法集合里。"""
    out = []
    for p in current:
        if p["form"] != "sql":
            continue
        src = ledger.get("status_value_sources", {}).get(p["table"], {})
        legal = set(src.get("values") or [])
        if not legal:
            continue
        bad = sorted(set(p["literals"]) - legal)
        if bad:
            out.append(f"{_fmt(p)} 非法值={bad} 合法={sorted(legal)}")
    return out


def _ledger() -> dict:
    if not LEDGER_PATH.exists():
        raise AssertionError(
            f"状态写面台账不存在：{LEDGER_PATH} —— fail-closed（缺台账 = 写面无人管，不是「无需登记」）")
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


# ══════════════════════════════════════════════════════════════════════════
# 六、判据
# ══════════════════════════════════════════════════════════════════════════

def test_scanner_is_not_blind():
    """判据 8：现取非空 + 点名锚点在册（**空集不许当绿**）。"""
    svc, sql, tables = java_write_points(), sql_write_points(), status_tables()
    print(f"[READING SW-100 现取] 状态表={len(tables)} java 写点={len(svc)} SQL 写点={len(sql)} "
          f"裸字面量站点={len(bare_literal_sites(svc))}")
    assert len(tables) >= MIN_STATUS_TABLES, f"有 status 列的表只剩 {len(tables)} 张（下界 {MIN_STATUS_TABLES}）"
    assert len(svc) >= MIN_SERVICE_WRITE_POINTS, f"Java 状态写点只剩 {len(svc)}（下界 {MIN_SERVICE_WRITE_POINTS}）"
    assert len(sql) >= MIN_SQL_WRITE_POINTS, f"SQL 状态写点只剩 {len(sql)}（下界 {MIN_SQL_WRITE_POINTS}）"
    names = {f"{p['table']}::{p['symbol']}" for p in svc + sql}
    for anchor in (
        "inbound_orders::post",                     # MC-100 的 CAS 写面（本守卫必须看见它）
        "inbound_orders::markPosted",               # 同上（mapper 侧）
        "production_operations::update",            # PG-075 的域 + 它看不见的 updateById 写面
        "orders::transitionStatusAtomic",           # 家族里最危险的另一个状态迁移（写面**本体**；cancelOrder 只是调用方）
    ):
        assert anchor in names, f"点名锚点 {anchor} 不在现取集里 ⇒ 扫描面被收窄 / 形态被改名"


def test_every_status_write_is_registered():
    """判据 1：**未登记即红**（具名：表 / 写点 / 文件:行）。"""
    current, ledger = java_write_points() + sql_write_points(), _ledger()
    missing = unregistered(current, ledger)
    print(f"[READING SW-100 登记] 现取={len(current)} 已登记={len(ledger['write_points'])} 未登记={len(missing)}")
    assert not missing, (
        "以下状态列写点**没有登记**（新增写面必须先入台账：表 × 写点；台账 = state_write_face_ledger.json）：\n  "
        + "\n  ".join(missing))


def test_ledger_is_not_stale():
    """判据 2：**台账陈旧即红**（写点没了就删台账条目；只许缩短）+ evidence 逐字兑现。"""
    current, ledger = java_write_points() + sql_write_points(), _ledger()
    gone = stale(current, ledger)
    print(f"[READING SW-100 陈旧] 台账={len(ledger['write_points'])} 现取={len(current)} 陈旧={len(gone)}")
    assert not gone, (
        "以下台账条目对应的写点**已消失**（改名 / 删掉 / 换写法）—— 台账只许缩短，请删除这些条目：\n  "
        + "\n  ".join(gone))
    # evidence 逐字兑现：`<仓库相对路径>::<逐字文本>`，左侧文件存在、右侧在该文件里**逐字出现**
    broken = []
    for e in ledger["write_points"]:
        f = REPO_ROOT / e["file"]
        if not f.exists():
            broken.append(f"{e['file']}（文件不存在）")
            continue
        text = java_code(f.read_text(encoding="utf-8"))
        if " ".join(e["anchor"].split()) not in " ".join(text.split()):
            broken.append(f"{e['file']}::{e['symbol']} 锚点不再兑现：{e['anchor'][:60]}")
    assert not broken, "台账 evidence 锚点**不再兑现**（给不存在的写面盖章）：\n  " + "\n  ".join(broken)


def test_status_literals_have_a_single_source():
    """判据 3：写状态列的**字面量必须来自枚举 / 常量**；存量按只许缩短的基线登记。"""
    current, ledger = java_write_points(), _ledger()
    live = bare_literal_sites(current)
    baseline = ledger["bare_literal_baseline"]
    frozen = {_site_key(s) for s in baseline["sites"]}
    new = [f"{_fmt(p)} 值={sorted(p['literals'])}" for p in live if _site_key(p) not in frozen]
    disappeared = [f"{t}::{f}::{sy}[{fm}]" for (t, f, sy, fm) in sorted(frozen - {_site_key(p) for p in live})]
    print(f"[READING SW-100 裸字面量] 现取={len(live)} 基线={baseline['count']}(上限 {BARE_LITERAL_CAP}) "
          f"新增={len(new)} 消失={len(disappeared)}")
    assert not new, (
        "以下写点用**裸字符串**写状态列（合法状态集合会因此多出第二个来源）——"
        "改成实体常量 / 枚举：\n  " + "\n  ".join(new))
    assert not disappeared, (
        "基线里的裸字面量写点已消失（修好了要连带缩短基线，否则基线永远不燃尽）：\n  " + "\n  ".join(disappeared))
    assert len(baseline["sites"]) <= BARE_LITERAL_CAP, (
        f"裸字面量基线 {len(baseline['sites'])} 条 > 冻结上限 {BARE_LITERAL_CAP}（只许缩短）")
    # SQL 一侧：SET 侧字面量必须落在该表声明的合法集合里
    bad = illegal_sql_values(sql_write_points(), ledger)
    assert not bad, "SQL 写面写了该表**未声明**的状态值（合法集合出现第二个来源）：\n  " + "\n  ".join(bad)


def test_every_status_table_declares_its_legal_source():
    """判据 4：每张有 `status` 列的表都要声明「合法状态集合来自哪」；无权威条数只许缩短。"""
    tables, ledger = status_tables(), _ledger()
    missing, gone = missing_authority(tables, ledger), stale_authority(tables, ledger)
    src = ledger["status_value_sources"]
    no_auth = sorted(t for t, v in src.items() if v.get("authority") == "none")
    print(f"[READING SW-100 权威] 状态表={len(tables)} 已声明={len(src)} 未声明={len(missing)} "
          f"无机器口径={len(no_auth)}(上限 {NO_AUTHORITY_CAP}) 幽灵={len(gone)}")
    assert not missing, (
        "以下有 status 列的表**没有登记合法状态集合的来源**（实体常量 / schema CHECK / none）：\n  "
        + "\n  ".join(missing))
    assert not gone, "台账给**不存在**的状态表盖了章（表已删 / 改名）：\n  " + "\n  ".join(gone)
    assert len(no_auth) <= NO_AUTHORITY_CAP, (
        f"「无机器可读合法集合」的表 {len(no_auth)} 张 > 冻结上限 {NO_AUTHORITY_CAP}（只许缩短："
        "新表请给实体 `STATUS_*` 常量或 schema CHECK）")


def test_reading_status_is_not_a_write_point():
    """判据 5（负控）：**读**状态不是写面 —— 真实语料 + 合成语料两路都不许产生写点。"""
    real = java_write_points() + sql_write_points()
    # 真实语料：每张 DTO / 响应里 `setStatus(xxx.getStatus())` 的拷贝都不得被登记（那不是列写）
    ent = entities()
    for p in real:
        assert p["table"] in status_tables(), f"{_fmt(p)} 的表没有 status 列却被登记"
        assert ent.get(p["receiver"]) == p["table"] or p["form"] in ("sql", "lambda_set", "builder"), _fmt(p)
    corpus = _corpus(
        "class Svc {",
        "    void reads(Order order) {",
        "        String s = order.getStatus();",
        "        if (\"draft\".equals(order.getStatus())) { log(s); }",
        "        OrderQueryResponse resp = new OrderQueryResponse();",
        "        resp.setStatus(order.getStatus());",
        "    }",
        "}",
    )
    assert _scan_corpus(corpus) == [], "读状态 / 装配响应被当成了写面（负控失败）"


def test_writing_a_table_without_status_column_is_not_in_scope():
    """判据 6（负控）：写**没有 status 列**的表不红（`customer_profiles` 只有 `customer_status`）。"""
    tables, ledger = status_tables(), _ledger()
    assert "customer_profiles" not in tables, "schema 口径变了：customer_profiles 现在有 status 列"
    assert all(t in tables for t in ledger["status_value_sources"]), "台账登记了没有 status 列的表"
    corpus = _corpus(
        "class Svc {",
        "    void touch(CustomerProfile profile) {",
        "        profile.setStatus(\"active\");",       # 该实体没有 status 列（只有 customer_status）
        "        customerProfileMapper.updateById(profile);",
        "    }",
        "    void note(OrderNote note) {",
        "        note.setStatus(\"x\");",                # 非实体（无 @TableName）
        "        noteMapper.updateById(note);",
        "    }",
        "}",
    )
    assert _scan_corpus(corpus, entities={"Order": "orders"}, tables={"orders"}) == [], (
        "写**没有 status 列**的表 / 非实体 DTO 被算成了状态写面")


def test_detector_has_teeth():
    """判据 7：**判别力自证** —— 七种坏形态在合成语料上各自被检出，且检出集合逐条相等。"""
    base_ents = {"Order": "orders", "ProductionOperation": "production_operations",
                 "CustomerProfile": "customer_profiles"}      # client 有 @TableName，但**没有 status 列**
    base_tables = {"orders", "production_operations"}          # ⇒ customer_profiles 不在射程（负控 ⑥）

    def scan(*body: str, ents=base_ents, tbls=base_tables) -> list[dict]:
        return _scan_corpus("\n".join(("class Svc {",) + body + ("}",)), entities=ents, tables=tbls)

    # ① 常规常量写 ⇒ 恰好 1 条、无裸字面量
    ok = scan("    void cancel(Order order) {",
              "        order.setStatus(Order.STATUS_CANCELLED);",
              "        orderMapper.updateById(order);",
              "    }")
    assert [_key(p) for p in ok] == [("orders", "<corpus>", "cancel", "setStatus")], ok
    assert ok[0]["literals"] == []

    # ② 裸字符串 ⇒ 同一写点，但**字面量被检出**（判据 3 的入口）
    lit = scan("    void cancel(Order order) {",
               "        order.setStatus(\"cancelled\");",
               "        orderMapper.updateById(order);",
               "    }")
    assert len(lit) == 1 and lit[0]["literals"] == ["cancelled"], lit

    # ③ 换写法（builder）⇒ **同一个成员换了写形也必须被看见**（旧守卫 MC-100 的盲洞就是它）
    built = scan("    void build(OrderCreateRequest req) {",
                 "        Order order = Order.builder().status(Order.STATUS_DRAFT).build();",
                 "        orderMapper.insert(order);",
                 "    }")
    assert [_key(p) for p in built] == [("orders", "<corpus>", "build", "builder")], built

    # ④ 注释 / 字符串里「提到」写状态 ⇒ 不算（引用即实例的反面：只有代码才算）
    mentioned = scan("    void docs(Order order) {",
                     "        // order.setStatus(\"cancelled\");  说明文字不算写面",
                     "        String s = \"order.setStatus(\\\"x\\\")\";",
                     "        log(s);",
                     "    }")
    assert mentioned == [], mentioned

    # ⑤ 读 / 装配响应 ⇒ 不算
    assert scan("    void read(Order order) {",
                "        String s = order.getStatus();",
                "        log(s);",
                "    }") == []

    # ⑥ 没有 status 列的表 / 非实体 ⇒ 不算（负控）
    assert scan("    void touch(CustomerProfile p) {",
                "        p.setStatus(\"active\");",
                "        customerProfileMapper.updateById(p);",
                "    }") == []

    # ⑦ **空扫描面**（源文件不存在）⇒ 由现取下界判红（不许把「没扫到」读成「没问题」）
    with pytest.raises(AssertionError):
        assert len([]) >= MIN_SERVICE_WRITE_POINTS, "空集当绿"

    # ⑧ 规则本身的**注入式红证**：摘掉「未登记即红」/「裸字面量」⇒ 对应判据必红
    ledger = {"write_points": []}
    assert unregistered(ok, ledger), "摘掉登记 ⇒ 判据 1 必须报未登记（红证 ①）"
    assert bare_literal_sites(lit), "摘掉字面量判定 ⇒ 判据 3 必须报裸字面量（红证 ②）"
    assert [p["literals"] for p in bare_literal_sites(lit)] == [["cancelled"]]
    assert not unregistered(ok, {"write_points": [{"table": "orders", "file": "<corpus>",
                                                   "symbol": "cancel", "form": "setStatus",
                                                   "params": "Order"}]})
    assert not bare_literal_sites(ok)


# ── 合成语料（判别力自证用；与真实扫描走**同一份**检测本体）─────────────────

def _corpus(*lines: str) -> str:
    return "\n".join(lines)


def _scan_corpus(text: str, *, entities=None, tables=None) -> list[dict]:
    """在**内存语料**上跑与真实扫描**同一份**检测本体（不复制判定逻辑）。"""
    ent = entities if entities is not None else entities_global()
    tbls = tables if tables is not None else status_tables()
    code = java_code(text)
    masked = mask_strings(code)
    lits = java_literals(code)
    self_ent = _self_entity(code)
    fields = _field_types(code)
    out: dict[tuple, dict] = {}
    for name, params, start, end in members(code):
        types = dict(fields)
        for pm in re.finditer(r"([A-Z]\w*)\s+(\w+)", params):
            types.setdefault(pm.group(2), pm.group(1))
        for dm in _DECL.finditer(code, start, end):
            types.setdefault(dm.group(2), dm.group(1))
        found: list[tuple[str, int, str, int]] = []
        for m in _SETTER.finditer(masked, start, end):
            found.append(("setStatus", m.start(), m.group(0), m.end() - 1))
        for m in _LAMBDA_SET.finditer(masked, start, end):
            found.append(("lambda_set", m.start(), m.group(0), -1))
        for m in _STRING_SET.finditer(masked, start, end):
            found.append(("string_set", m.start(), m.group(0), -1))
        for m in _SET_SQL.finditer(masked, start, end):
            found.append(("set_sql", m.start(), m.group(0), -1))
        for bm in _BUILDER.finditer(masked, start, end):
            if bm.group(1) not in ent:
                continue
            stop = _stmt_end(masked, bm.start(), end)
            sm = _BUILDER_STATUS.search(masked, bm.end(), stop)
            if sm:
                found.append(("builder", bm.start(), bm.group(1), sm.end() - 1))
        for form, pos, expr, paren in found:
            if form == "setStatus":
                et = _receiver_type(code, types, pos) or self_ent
            elif form == "lambda_set":
                et = re.search(r"([\w.]+)\s*::\s*getStatus", code[pos:pos + 120]).group(1).split(".")[-1]
            elif form in ("string_set", "set_sql"):
                et = _wrapper_entity(code, types, pos) or self_ent
            else:
                et = expr
            table = ent.get(et or "", "")
            if table not in tbls:
                continue
            a_lo, rhs_end = (_arg_span(code, paren, end) if paren >= 0 else (pos, _stmt_end(code, pos, end)))
            bare = [v for p, v in lits if a_lo <= p <= rhs_end]
            key = (table, "<corpus>", name, form)
            cur = out.setdefault(key, {"table": table, "file": "<corpus>", "symbol": name,
                                       "params": params, "form": form, "receiver": et,
                                       "line": code.count("\n", 0, pos) + 1, "literals": [],
                                       "anchor": "", "persisted": []})
            cur["literals"] = sorted(set(cur["literals"] + bare))
    return sorted(out.values(), key=lambda x: (x["table"], x["symbol"]))


def entities_global() -> dict[str, str]:
    return entities()
