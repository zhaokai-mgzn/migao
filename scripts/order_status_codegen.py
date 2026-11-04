#!/usr/bin/env python3
"""订单状态**单一源 → TS / Python 生成物**的生成器 + 新鲜度判定（issue #8198 的 P2-2b）。

## 单一源是哪一份（**不是**新类型）

`backend/admin-api/src/main/java/com/migao/admin/service/OrderStatusTransitions.java` ——
P2-2a（issue #8198 评论 2026-10-31 裁定「**加常量、不加类型**」）之后，它是订单状态的
**唯一取值载体**：7 个 `public static final String` 常量 + 三张表
（`STATUS_TRANSITIONS` / `ORDER_STATUS_LABELS` / `CONTENT_EDITABLE_STATUSES`）。

本生成器**只读**它，产出两份**入库**生成物（不引入枚举、不引入第三个载体）：

| 生成物 | 消费方 |
|---|---|
| `frontend/admin-web/src/types/order-status.generated.ts` | 前端类型与映射表 |
| `backend/ai-agent-service/app/constants/order_status_generated.py` | Agent 工具 schema |

## 确定性（同样的源 ⇒ 逐字节同样的产物）

1. **排序键显式写死**：状态全集按**常量声明顺序**；每张表的键按全集顺序；
   流转目标集合按全集顺序（`Set.of(...)` 在源里的书写顺序**不参与**排序 —— 它只是源文本）；
2. **产物里没有任何环境指纹**：无时间戳、无 git sha、无主机名、无生成器版本号；
3. **同一份源连跑两次 `--write` ⇒ `cmp` 逐字节相等**（判据里实跑自证）。

## 新鲜度判定（一条命令，CI / 本地同一个入口）

    python3 scripts/order_status_codegen.py --check     # 0 = 同步 / 1 = 陈旧 / 3 = 无法判定
    python3 scripts/order_status_codegen.py --write     # 重新生成两份产物（改完源再提交）

三态**没有「跳过」这一态**（`3` 不得当 `0` 读）：源缺失 / 产物缺失 / 解析不出结构 ⇒ `3` + 具名原因。
判红输出**具名**（哪个产物、差多少行、首个差异的两侧原文、复算与重生成命令）。

## 复算

    python3 scripts/order_status_codegen.py --check --json /tmp/order-status-codegen.json
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

#: 仓根（本文件在 `<repo>/scripts/` 下）；`--repo` 可覆盖（判据夹具用）。
REPO_ROOT = Path(__file__).resolve().parents[1]

#: 剥注释走**仓内唯一一份**引号感知实现（`#5323`）：脚本与判据共用一个词法走查，
#: 不新增第二份「按引号扫原文」的尺子（那正是那一族缺陷的来源）。
sys.path.insert(0, str(REPO_ROOT / "tests"))
from unit_ci_workflows._source_parsing import java_code  # noqa: E402

#: 单一源（Java）与两份生成物。
SOURCE_REL = "backend/admin-api/src/main/java/com/migao/admin/service/OrderStatusTransitions.java"
TS_REL = "frontend/admin-web/src/types/order-status.generated.ts"
PY_REL = "backend/ai-agent-service/app/constants/order_status_generated.py"

#: 生成物清单（顺序 = 判红/日志里的顺序；新增产物只需在这里加一行）。
ARTIFACTS: tuple[tuple[str, str], ...] = ((TS_REL, "ts"), (PY_REL, "py"))

#: 生成物里唯一允许出现的「重新生成」命令原文（产物与文档同一份措辞）。
GENERATE_COMMAND = "python3 scripts/order_status_codegen.py --write"
CHECK_COMMAND = "python3 scripts/order_status_codegen.py --check"

#: 三态退出码（语义见模块 docstring）。
RC_FRESH, RC_DRIFT, RC_UNDECIDABLE = 0, 1, 3

#: 判红/无法判定时打进日志的 GitHub 注解前缀（**单行**）。
ERROR_PREFIX = "::error::"

#: 解析失败一律具名抛出（不静默回落成空表 —— 空表生成的产物会是"看起来合法"的假绿）。
class SourceParseError(AssertionError):
    """源里取不到预期结构（格式变了 / 文件不是它声称的那份）。"""


@dataclass(frozen=True)
class OrderStatusSource:
    """解析出来的单一源（**顺序即常量声明顺序**，三张表都按它排序）。"""

    #: 常量名 → 值，按源里的声明顺序。
    constants: tuple[tuple[str, str], ...]
    #: 状态值 → 允许流转到的目标值（已按全集顺序排序）。
    transitions: dict[str, tuple[str, ...]]
    #: 状态值 → 中文标签。
    labels: dict[str, str]
    #: 内容可编辑的状态值（按全集顺序）。
    content_editable: tuple[str, ...]

    @property
    def values(self) -> tuple[str, ...]:
        """状态全集（= `STATUS_TRANSITIONS` 的键集，顺序 = 常量声明顺序）。"""
        return tuple(value for _name, value in self.constants)


# ── 解析：只做词法 + 保守的结构定位（不猜语义）────────────────────────────────


def _strip_comments(text: str) -> str:
    return java_code(text)


def _parse_constants(code: str) -> tuple[tuple[str, str], ...]:
    """`public static final String NAME = "value";` —— 按声明顺序取 `(NAME, value)`。"""
    marker = "public static final String "
    out: list[tuple[str, str]] = []
    for line in code.splitlines():
        stripped = line.strip()
        if not stripped.startswith(marker):
            continue
        rest = stripped[len(marker):]
        name, sep, tail = rest.partition(" = ")
        if not sep:
            raise SourceParseError(f"常量声明取不到 ` = `：{stripped[:120]}")
        name = name.strip()
        if not tail.startswith('"'):
            raise SourceParseError(f"常量 {name} 的值不是双引号字面量：{tail[:120]}")
        close = tail.find('"', 1)
        if close < 0:
            raise SourceParseError(f"常量 {name} 的值没有闭合引号：{tail[:120]}")
        value = tail[1:close]
        if tail[close + 1:].strip() != ";":
            raise SourceParseError(f"常量 {name} 的声明不是 `= \"…\";` 形态：{stripped[:120]}")
        if name in [n for n, _ in out]:
            raise SourceParseError(f"常量 {name} 重复声明（取值载体必须唯一）")
        out.append((name, value))
    if not out:
        raise SourceParseError("源里没有任何 `public static final String` 常量 —— 载体搬走了？")
    return tuple(out)


def _balanced(text: str, start: int) -> str:
    """从 `start`（某个 `(`）起取到**配对的** `)` 之间的正文；**字符串里的括号不算**。"""
    depth, i, n = 0, start, len(text)
    quote = ""
    while i < n:
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[start + 1:i]
        i += 1
    raise SourceParseError("括号不配对（解析器读到的源结构变了）")


def _field_body(code: str, field: str) -> str:
    """取 `field = <call>(…)` 的**参数正文**（剥掉最外层那一对括号）。"""
    marker = f" {field} = "
    pos = code.find(marker)
    if pos < 0:
        raise SourceParseError(f"源里没有字段 `{field}` 的声明")
    open_paren = code.find("(", pos + len(marker))
    if open_paren < 0:
        raise SourceParseError(f"字段 `{field}` 的声明里没有调用括号")
    return _balanced(code, open_paren)


def _split_top_level(body: str) -> list[str]:
    """按**顶层**逗号切段（`Set.of(a, b)` 里的逗号不算）。"""
    parts: list[str] = []
    depth, buf, quote = 0, [], ""
    for ch in body:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in "\"'":
            quote = ch
            buf.append(ch)
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    tail = "".join(buf)
    if tail.strip():
        parts.append(tail)
    return [p.strip() for p in parts if p.strip()]


def _resolve(token: str, constants: dict[str, str], where: str) -> str:
    """把 `PENDING`（常量引用）或 `"pending"`（字面量）解析成状态值。

    🔴 **两种形态都认**是**有意**的：P2-2a 已把三张表的键改成常量引用（Java 判据守着），
    但生成器不该因为「源里回了字面量」就静默取空 —— 那会让产物比源**少键**而判据看起来是绿的。
    取值口径必须与源**逐值相等**，载体形态由 Java 判据管，不由本生成器管。
    """
    token = token.strip()
    if token in constants:
        return constants[token]
    if len(token) >= 2 and token[0] == '"' and token[-1] == '"':
        return token[1:-1]
    raise SourceParseError(f"{where}：取不到状态值（既不是已知常量名也不是字符串字面量）：{token[:120]}")


def _members_from_body(body: str, constants: dict[str, str], where: str) -> list[str]:
    """`A, B` 形态的**成员正文** → 状态值列表（保持源里的书写顺序，调用方再排序）。"""
    return [_resolve(part, constants, where) for part in _split_top_level(body)]


def _set_members(token: str, constants: dict[str, str], where: str) -> list[str]:
    """`Set.of(A, B)` / `Set.of()` → 成员状态值列表（保持源里的书写顺序，调用方再排序）。

    `Set.of(X)` 的**参数正文**就是 `X`（`_field_body` 已经把最外层括号剥掉了），所以单成员
    集合会以裸 `PENDING` 形态进来 —— 那是合法形态，不是解析失败。
    """
    text = token.strip()
    for prefix in ("Set.of(", "java.util.Set.of("):
        if text.startswith(prefix) and text.endswith(")"):
            return _members_from_body(text[len(prefix):-1], constants, where)
    return _members_from_body(text, constants, where)


def _parse_pairs(body: str, constants: dict[str, str], where: str) -> list[tuple[str, str]]:
    """`A, Set.of(…), B, "标签", …` → `[(键值, 值原文), …]`（**成对**切分）。"""
    parts = _split_top_level(body)
    if len(parts) % 2 != 0:
        raise SourceParseError(f"{where}：条目不是「键, 值」成对出现（{len(parts)} 段）")
    pairs: list[tuple[str, str]] = []
    for i in range(0, len(parts), 2):
        key = _resolve(parts[i], constants, where)
        pairs.append((key, parts[i + 1]))
    return pairs


def parse_source(text: str) -> OrderStatusSource:
    """把 `OrderStatusTransitions.java` 的正文解析成 `OrderStatusSource`（纯函数，夹具可直接喂）。"""
    code = _strip_comments(text)
    constants = _parse_constants(code)
    order = [value for _name, value in constants]
    by_name = {name: value for name, value in constants}
    where = "OrderStatusTransitions.java"

    transitions_raw = _parse_pairs(_field_body(code, "STATUS_TRANSITIONS"), by_name, where)
    labels_raw = _parse_pairs(_field_body(code, "ORDER_STATUS_LABELS"), by_name, where)
    editable_raw = _members_from_body(
        _field_body(code, "CONTENT_EDITABLE_STATUSES"), by_name, where)

    # 键集**必须**等于常量集：两边不等 = 源自己不自洽（状态全集有两个答案）⇒ 不当成"能生成"。
    if [key for key, _ in transitions_raw] != order:
        raise SourceParseError(
            "STATUS_TRANSITIONS 的键集与常量集不一致（顺序/成员任一不同都不行）："
            f"键={[k for k, _ in transitions_raw]} 常量={order}")
    if [key for key, _ in labels_raw] != order:
        raise SourceParseError(
            "ORDER_STATUS_LABELS 的键集与常量集不一致："
            f"键={[k for k, _ in labels_raw]} 常量={order}")

    index = {value: i for i, value in enumerate(order)}

    def sort_values(values: list[str], where_: str) -> tuple[str, ...]:
        unknown = [v for v in values if v not in index]
        if unknown:
            raise SourceParseError(f"{where_}：出现不在常量集里的状态值 {unknown} ⇒ 源不自洽")
        return tuple(sorted(values, key=lambda v: index[v]))

    transitions: dict[str, tuple[str, ...]] = {}
    for key, token in transitions_raw:
        transitions[key] = sort_values(_set_members(token, by_name, where), f"STATUS_TRANSITIONS[{key}]")

    labels: dict[str, str] = {}
    for key, token in labels_raw:
        text_value = token.strip()
        if len(text_value) < 2 or text_value[0] != '"' or text_value[-1] != '"':
            raise SourceParseError(f"ORDER_STATUS_LABELS[{key}] 的值不是双引号字面量：{token[:80]}")
        labels[key] = text_value[1:-1]

    return OrderStatusSource(
        constants=constants,
        transitions=transitions,
        labels=labels,
        content_editable=sort_values(editable_raw, "CONTENT_EDITABLE_STATUSES"),
    )


# ── 渲染：两份产物的**唯一**生成点 ────────────────────────────────────────────


def _q(value: str) -> str:
    """Python/TS 共用的双引号字面量（`json.dumps` ⇒ 转义规则确定，`ensure_ascii=False` 保中文）。"""
    return json.dumps(value, ensure_ascii=False)


def _header(comment_start: str) -> list[str]:
    """两份产物共用的**同一段**抬头（只有注释符号不同 ⇒ 口径不会分叉）。"""
    return [
        f"{comment_start}⚠️ 生成物 —— **不要手改**（改这里会在判据上判红）。",
        f"{comment_start}源：{SOURCE_REL}",
        f"{comment_start}重新生成：{GENERATE_COMMAND}",
        f"{comment_start}新鲜度判据：{CHECK_COMMAND}（0 = 同步 / 1 = 陈旧 / 3 = 无法判定）",
    ]


def render_ts(source: OrderStatusSource) -> str:
    """渲染 `order-status.generated.ts`（确定性：见模块 docstring 的三条）。"""
    values = source.values
    # 抬头与 Python 那份**同一段文本**（同一份 `_header`），只换注释符号 ⇒ 口径不会分叉。
    lines = ["/**"] + [f" * {ln[3:]}" if ln[3:] else " *" for ln in _header("// ")] + [" */", ""]

    lines += ["/** 后端订单状态的唯一取值全集（顺序 = Java 常量声明顺序，排序键显式写死）。 */"]
    lines += ["export const ORDER_STATUSES = ["]
    lines += [f"  {_q(v)}," for v in values]
    lines += ["] as const", ""]
    lines += ["export type CanonicalOrderStatus = (typeof ORDER_STATUSES)[number]", ""]

    lines += ["/** Java 侧常量名 → 值（消费方按名引用，避免裸字面量）。 */"]
    lines += ["export const ORDER_STATUS_VALUES = {"]
    lines += [f"  {name}: {_q(value)}," for name, value in source.constants]
    lines += ["} as const", ""]

    lines += ["/** 状态 → 中文业务术语（源 = Java `ORDER_STATUS_LABELS`）。 */"]
    lines += ["export const ORDER_STATUS_LABELS: Record<CanonicalOrderStatus, string> = {"]
    lines += [f"  {_q(v)}: {_q(source.labels[v])}," for v in values]
    lines += ["}", ""]

    lines += ["/** 合法流转（源 = Java `STATUS_TRANSITIONS`；目标按全集顺序排序）。 */"]
    lines += ["export const ORDER_STATUS_TRANSITIONS: "
              "Record<CanonicalOrderStatus, readonly CanonicalOrderStatus[]> = {"]
    for v in values:
        targets = ", ".join(_q(t) for t in source.transitions[v])
        lines += [f"  {_q(v)}: [{targets}],"]
    lines += ["}", ""]

    lines += ["/** 内容可编辑的状态（源 = Java `CONTENT_EDITABLE_STATUSES`；按全集顺序排序）。 */"]
    lines += ["export const CONTENT_EDITABLE_STATUSES: readonly CanonicalOrderStatus[] = ["
              + ", ".join(_q(v) for v in source.content_editable) + "]", ""]
    return "\n".join(lines)


def render_python(source: OrderStatusSource) -> str:
    """渲染 `order_status_generated.py`（确定性口径与 TS 那份**同一套**）。"""
    values = source.values
    lines = ['"""']
    lines += [ln[3:] for ln in _header("// ")]
    lines += ['"""', ""]

    lines += ["#: 后端订单状态的唯一取值全集（顺序 = Java 常量声明顺序，排序键显式写死）。"]
    lines += ["ORDER_STATUSES: tuple[str, ...] = ("]
    lines += [f"    {_q(v)}," for v in values]
    lines += [")", ""]

    lines += ["#: Java 侧常量名 → 值（逐名导出，消费方按名引用，避免裸字面量）。"]
    lines += [f"{name} = {_q(value)}" for name, value in source.constants]
    lines += [""]

    lines += ["#: 状态 → 中文业务术语（源 = Java `ORDER_STATUS_LABELS`）。"]
    lines += ["ORDER_STATUS_LABELS: dict[str, str] = {"]
    lines += [f"    {_q(v)}: {_q(source.labels[v])}," for v in values]
    lines += ["}", ""]

    lines += ["#: 合法流转（源 = Java `STATUS_TRANSITIONS`；目标按全集顺序排序）。"]
    lines += ["STATUS_TRANSITIONS: dict[str, tuple[str, ...]] = {"]
    for v in values:
        targets = source.transitions[v]
        if not targets:                                  # 空元组
            rendered = "()"
        elif len(targets) == 1:                          # 单元素元组**必须**带尾逗号（否则是字符串）
            rendered = f"({_q(targets[0])},)"
        else:
            rendered = "(" + ", ".join(_q(t) for t in targets) + ")"
        lines += [f"    {_q(v)}: {rendered},"]
    lines += ["}", ""]

    lines += ["#: 内容可编辑的状态（源 = Java `CONTENT_EDITABLE_STATUSES`；按全集顺序排序）。"]
    editable = ", ".join(_q(v) for v in source.content_editable)
    lines += [f"CONTENT_EDITABLE_STATUSES: tuple[str, ...] = ({editable},)" if editable
              else "CONTENT_EDITABLE_STATUSES: tuple[str, ...] = ()", ""]
    return "\n".join(lines)


RENDERERS = {"ts": render_ts, "py": render_python}


def render_all(source: OrderStatusSource) -> dict[str, str]:
    """产物仓库相对路径 → 正文（**唯一**的"该长什么样"来源）。"""
    return {rel: RENDERERS[kind](source) for rel, kind in ARTIFACTS}


# ── 判定 / 落盘 ──────────────────────────────────────────────────────────────


def _changed_line_count(committed: str, renewed: str) -> tuple[int, int, int]:
    """`(提交版行数, 现取行数, 不同的行数)`。"""
    import difflib

    a, b = committed.splitlines(), renewed.splitlines()
    changed = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag != "equal":
            changed += max(i2 - i1, j2 - j1)
    return len(a), len(b), changed


def _first_diff(committed: str, renewed: str, limit: int = 2) -> list[str]:
    """首个（至多 `limit` 个）差异块的**两侧原文**（带 1-based 行号）。"""
    import difflib

    a, b = committed.splitlines(), renewed.splitlines()
    out: list[str] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        out.append(f"第 {i1 + 1} 行起：")
        out.append(f"  - 提交版：{a[i1][:160]}" if i1 < i2 else "  - 提交版：**该行不存在**")
        out.append(f"  + 现取　：{b[j1][:160]}" if j1 < j2 else "  + 现取　：**该行不存在**")
        if len(out) >= limit * 3:
            break
    return out


def check(repo: Path) -> dict:
    """跑一次新鲜度判定，返回机器可读报告（`verdict` ∈ fresh / drifted / undecidable）。"""
    report: dict = {
        "schema": 1,
        "source": SOURCE_REL,
        "artifacts": [rel for rel, _kind in ARTIFACTS],
        "verdict": "undecidable",
        "problems": [],
        "drifted": [],
        "undecidable": [],
        "recompute_command": CHECK_COMMAND,
        "generate_command": GENERATE_COMMAND,
    }
    source_path = repo / SOURCE_REL
    if not source_path.is_file():
        report["undecidable"].append(f"单一源缺失：{SOURCE_REL}")
    try:
        source = parse_source(source_path.read_text(encoding="utf-8")) if not report["undecidable"] else None
    except (OSError, SourceParseError) as exc:
        report["undecidable"].append(f"单一源解析失败：{type(exc).__name__}: {exc}")
        source = None
    if source is None:
        report["problems"] = [
            f"{ERROR_PREFIX}订单状态生成物新鲜度**无法判定**（fail-closed，绝不当「通过/跳过」读）："
            + "；".join(report["undecidable"]),
            f"   复算（可复制）：{CHECK_COMMAND}",
        ]
        return report

    renewed = render_all(source)
    for rel, _kind in ARTIFACTS:
        path = repo / rel
        if not path.is_file():
            report["undecidable"].append(f"生成物缺失：{rel}")
            continue
        committed = path.read_text(encoding="utf-8")
        if committed == renewed[rel]:
            continue
        n_c, n_r, n_d = _changed_line_count(committed, renewed[rel])
        report["drifted"].append(
            {"artifact": rel, "committed_lines": n_c, "renewed_lines": n_r, "changed_lines": n_d})
        report["problems"] += [
            f"❌ 产物：{rel}",
            f"   差量：提交版 {n_c} 行 / 现取 {n_r} 行；不同 {n_d} 行",
            *[f"   {ln}" for ln in _first_diff(committed, renewed[rel])],
        ]
    if report["undecidable"]:
        report["problems"] = [
            f"{ERROR_PREFIX}订单状态生成物新鲜度**无法判定**（fail-closed）："
            + "；".join(report["undecidable"]),
            f"   复算（可复制）：{CHECK_COMMAND}",
        ]
        return report
    if report["drifted"]:
        report["verdict"] = "drifted"
        report["problems"].append(f"   重生成并提交（可复制）：{GENERATE_COMMAND}")
        report["problems"].append("   注意：生成物**不许手改** —— 改 Java 单一源后重生成并提交。")
        return report
    report["verdict"] = "fresh"
    report["problems"].append(
        f"✅ 生成物与单一源同步（检查 {len(ARTIFACTS)} 个产物："
        + "、".join(rel for rel, _k in ARTIFACTS) + f"；源 = {SOURCE_REL}）")
    return report


def write(repo: Path) -> dict:
    """按单一源重新生成两份产物（返回写盘清单；解析失败时**一个字节都不写**）。"""
    source = parse_source((repo / SOURCE_REL).read_text(encoding="utf-8"))
    rendered = render_all(source)
    written: list[str] = []
    for rel, _kind in ARTIFACTS:
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered[rel], encoding="utf-8")
        written.append(rel)
    return {"written": written, "source": SOURCE_REL}


def summary_line(report: dict) -> str:
    """机器可读的单行读数（**与负载无关**，不含任何时长）。"""
    if report["verdict"] == "fresh":
        why = "全部新鲜"
    elif report["verdict"] == "drifted":
        why = "陈旧：" + "、".join(d["artifact"] for d in report["drifted"])
    else:
        why = "无法判定：" + "；".join(report.get("undecidable") or [])[:160]
    return (f"MIGAO-ORDER-STATUS-CODEGEN seen={len(report.get('artifacts') or [])} "
            f"acted={len(report.get('drifted') or [])} verdict={report['verdict']} why={why}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="订单状态单一源 → TS/Python 生成物（生成 + 新鲜度判定）")
    ap.add_argument("--repo", default=str(REPO_ROOT), help="仓根（缺省 = 本文件所在仓库）")
    ap.add_argument("--check", action="store_true",
                    help="新鲜度判定（**缺省行为**；显式写出来是为了让命令可读、可复制）")
    ap.add_argument("--write", action="store_true", help="重新生成两份产物并落盘")
    ap.add_argument("--json", default="", help="把机器可读报告写到该路径")
    args = ap.parse_args(argv)
    repo = Path(args.repo)

    if args.write and args.check:
        print(f"{ERROR_PREFIX}--write 与 --check 是两件事，不许同时给（一次只做一件）")
        return RC_UNDECIDABLE

    if args.write:
        try:
            report = write(repo)
        except (OSError, SourceParseError) as exc:
            print(f"{ERROR_PREFIX}订单状态生成失败（**一个字节都没写**）：{type(exc).__name__}: {exc}")
            return RC_UNDECIDABLE
        print(f"✅ 已生成 {len(report['written'])} 个产物（源 = {report['source']}）：")
        for rel in report["written"]:
            print(f"   - {rel}")
        return RC_FRESH

    report = check(repo)
    for line in report["problems"]:
        print(line)
    print(summary_line(report))
    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"fresh": RC_FRESH, "drifted": RC_DRIFT}.get(report["verdict"], RC_UNDECIDABLE)


if __name__ == "__main__":
    raise SystemExit(main())
