#!/usr/bin/env python3
"""cases_yaml — 用例源文件（`cases/*.yml`）的**唯一严格 loader**（issue #5151）。

## 为什么必须收敛到一处（#5063 收尾实测 / PR #5147，差一步造成破坏）

解析在两条腿上**宽严不一**：

| 腿 | 用什么解析 |
|---|---|
| 渲染腿 `.github/render_cases.py` | `yaml_light`（**宽松**：能吃下标准 YAML 拒绝的文件） |
| 判据腿 `scripts/drift_audit.py` | `yaml.safe_load`（**严格**：抛 `ParserError`） |

⇒ `.github/cases/product.yml` 里一个写在双引号标量内、**未转义的裸 `"`**：
· 渲染腿**照旧成功**（399 条 + 生成物新鲜度全绿）⇒ 坏文件**零信号**；
· 判据腿整条抛错 ⇒ `findings = 0` ⇒ 9 条 `component|*` 基线条目被下游读成「已归零」⇒
  报告写「**基线归零未删 9（阻塞）**」并**建议 `--regen-baseline`** —— 照做就**凭一次解析错误
  永久删掉 9 条合法豁免**（当时靠包主提交前复核才没删成）。

⇒ 「宽严不一」本身就是 bug：两侧必须问**同一个函数**。本模块就是那一处 —— `strict_error()`
是**唯一**判定实现，渲染腿与判据腿都只许调它（不许各自再写一份"看起来一样"的）。

## 零第三方依赖是硬约束（决定判定后端怎么分层）

`.github/` 下的脚本跑在**没有 `pip install` 的 CI job**（`pr-check.yml` 的 `case-truth-check`
job 只有 `actions/checkout` + 系统 `python3`）。实测该环境**没有 PyYAML**：runner 镜像的
`toolset-2404.json` **没有 `pip` 段**（`yamllint` / `ansible-core` 走 **pipx 隔离 venv**），apt
清单里也**没有** `python3-yaml` ⇒ 在这里硬 `import yaml` 会让**每个 PR 常红**，而红的原因与
用例质量无关（比缺口本身更糟：它挡住所有合并）—— 同
`tests/unit_ci_workflows/test_xiaobu_coverage.py` 的 `TestCoverageGateRunsOnCiDependencies`
留下的现场记录。

⇒ **CI 里渲染腿走的正是"没有 PyYAML"那条路**，所以后端②（零依赖严格闸）必须**真能抓住事故
形态**（否则"渲染腿 fail-closed"在 CI 上只是名义上的，两层分歧原样保留）。实测：
**#5147 的真实坏形态在两条后端下都被判红**（语料一致性守卫见
`tests/unit_ci_workflows/test_render_cases_yaml_fail_closed.py` 的 `CORPUS`）。

后端分两层，**判定口径写在这一个函数里、两侧共用**：
① `yaml.safe_load` 可用 ⇒ **用它**（= 判据腿原口径，逐字不变）；
② 不可用 ⇒ `_zero_dep_syntax_error()`（纯标准库状态机）：

| 后端②**能**抓 | 后端②**抓不到**（照实登记，见守卫里的 `NOT_COVERED`） |
|---|---|
| 引号标量**提前闭合**（`"… "x" …"` = #5147 形态） | 用**制表符**做缩进（标准 YAML 拒绝） |
| 引号**到文件结尾未闭合**（单/双引号，含跨行） | 锚点 / 别名 / 标签的语义错误 |
| flow 集合（`[` / `{`）**到文件结尾未闭合**（含跨行） | flow 集合内部的其它语法错误（如 `[a: b, c` 之外的分隔符错） |
| | 引号**跨行**时的那一行之后、闭合之前的内容（按"续行"整体跳过） |

## 重复键：**两个后端共用的独立检测**（issue #4291 / #4336）

⚠️ **重复键不在上面那张表的任何一侧** —— 它是**语法之外**的一层：YAML 规范不禁止同一
mapping 里出现重复键，**PyYAML 默认也只保留最后一个、不报错**。⇒ "换成严格解析器"治不了它：

- `#4291`：`.github/templates/fabric-calc.yml` 的 `reviewer_asserts` 同一 mapping 里
  **5 个 `expect:`** ⇒ 装载后只剩最后一个，**前 4 条真值断言静默消失**（源文件看起来有 5 条）；
- `#4336`：`.github/cases/*.yml` 里 5 个映射共有 **12 处**重复键（如 OR-030 尾块里一整套
  `data_checks` / `skip_reason` / `merge_log` / `traces` 被静默丢弃）。

⇒ 本模块新增 `_zero_dep_key_anomalies()`：**零依赖**（纯标准库状态机，块映射面），
且**两个后端都跑它**（不是"后端②的补丁"）—— 这样"两侧判定一致"是**构造上成立**的，
不靠两边各写一份"看起来一样"的实现去对。它在**语法判定之后**执行（语法先错就先报语法）。

| 重复键检测**能**抓 | 重复键检测**抓不到**（照实登记，守卫的 `NOT_COVERED_DUPLICATE` 逐条钉住） |
|---|---|
| 块映射里同一缩进层的同名键（含 `- key: v` 序列项自成一层） | **flow 映射**里的重复键（`{a: 1, a: 2}` —— flow 整段跳过） |
| 引号键（`"a"` 与 `a` 归一为同一个键） | 跨锚点/别名的键重复（`<<: *x` 展开后的重名） |
| **键落在标量序列项的续行区**（`- 标量项` + 更深行的 `key: ` ⇒ 标准 YAML 报 `mapping values are not allowed here`，宽松腿把该键**静默吞掉**；`ai-chat.yml` 实例） | **非空裸标量值**之后的更深键行（`k: v` + 更深 `k2: v2` —— PyYAML 同样报错）：**有意不判** —— 制表符缩进会让行级缩进失真（既有 `NOT_COVERED["tab_indent"]` 已登记），判它会把那条登记顶成**假红** |

⚠️ 与上面同口径：**只许更严不许更宽** —— 右侧不是"可以不管"，而是**已知缺口**，带死亡条件登记
（谁补上了，那条登记当场变红）。

⚠️ 后端②**只许更严不许更宽**：它绝不因为"看起来可疑"就拒（那会把合法用例判红 = 反向护栏
失守）。上表右侧**不是"可以不管"**，而是**已知的覆盖缺口**，由
`tests/unit_ci_workflows/test_render_cases_yaml_fail_closed.py` 的 `NOT_COVERED` 逐条钉住 ——
**登记有死亡条件**：谁把某条补上了，那条登记会当场变红，逼他更新表（本仓 §17.3 ④ 的口径）。
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

__all__ = ["CasesYamlError", "pyyaml_available", "strict_loader_name", "strict_error",
           "require_strict", "load_document", "key_anomaly_error", "key_anomalies"]


class CasesYamlError(Exception):
    """**严格判定不通过**（消息里带 `文件:行:列` 与原因）—— 两条腿都必须 fail-closed。"""


try:                      # 模块级可选导入：渲染腿的 CI job 没有 PyYAML（见模块 docstring）
    import yaml as _pyyaml
except ImportError:       # pragma: no cover —— 由「无 PyYAML」子进程夹具覆盖
    _pyyaml = None

#: 严格解析用的 loader：**C 加速版优先**，纯 Python 兜底。
#: 两者是**同一套安全构造规则**（PyYAML 官方 drop-in），本仓 25 个用例文件实测**逐值深比较相同**、
#: 报错的 `problem_mark`（行/列）也相同 —— 只是 C 版快 ~11×（1.05MB 语料 0.626s → 0.055s）。
#: ⚠️ 这不是可选优化：渲染腿的严格判定会被 `load_case_dicts()` 调用上百次（CI 的
#: `tests/unit_ci_workflows` 套件），纯 Python loader 每调用一次多 0.66s ⇒ 该 job 逼近/撞上自己的
#: 8 分钟超时（实测 CI：套件 253s → 357s；#4793 已因同类原因把该 job 的超时从 3 分钟提到 8 分钟）。
_SAFE_LOADER = ((getattr(_pyyaml, "CSafeLoader", None) or _pyyaml.SafeLoader)
                if _pyyaml is not None else None)


def strict_loader_name() -> str:
    """当前严格解析用的 loader 名（报告/守卫用：`CSafeLoader` = C 加速，`SafeLoader` = 纯 Python）。"""
    return getattr(_SAFE_LOADER, "__name__", "<无 PyYAML>")


def _safe_load(text: str):
    """**唯一**的严格解析调用点 —— `strict_error()`（判定）与 `load_document()`（取值）共用它。

    两条腿口径一致的前提就是"只有这一处真的调 loader"（不许各自 `yaml.safe_load(...)`）。
    """
    return _pyyaml.load(text, Loader=_SAFE_LOADER)


def pyyaml_available() -> bool:
    """严格后端 ① 是否可用（= 判定口径是否就是判据腿的原口径）。"""
    return _pyyaml is not None


# ═══════════════════════════════════════════════════════════════════════════
# 后端 ②：零依赖严格闸（无 PyYAML 时的判定）
# ═══════════════════════════════════════════════════════════════════════════
#: 块标量头（`|` / `>`，可带 `-`/`+` 与缩进指示数字）—— 它的**内容行**不是"值位置"
_BLOCK_SCALAR_HEAD = re.compile(r"^[|>][+-]?\d*$")


def _find_close(line: str, start: int, quote: str) -> int | None:
    """从 `start` 起找 `quote` 的闭合列；`\\"`（双引号内）/ `''`（单引号内）是转义，不算闭合。

    找不到 ⇒ `None`（可能是**合法的跨行标量**，闭合在后面的行上 —— 由调用方转成"续行"状态）。
    """
    j = start
    while j < len(line):
        ch = line[j]
        if quote == '"' and ch == "\\":
            j += 2
            continue
        if ch == quote:
            if quote == "'" and j + 1 < len(line) and line[j + 1] == "'":
                j += 2
                continue
            return j
        j += 1
    return None


def _flow_delta(text: str) -> int:
    """`text` 里 flow 括号的**净深度**（引号内不计；空白后的 `#` 起行内注释，注释内不计）。

    引号在本行内没闭合 ⇒ 立刻返回当前深度（余下的交给"续行"处理，绝不猜）。
    """
    depth = 0
    j = 0
    while j < len(text):
        ch = text[j]
        if ch in ('"', "'"):
            end = _find_close(text, j + 1, ch)
            if end is None:
                return depth
            j = end + 1
            continue
        if ch == "#" and j > 0 and text[j - 1].isspace():
            break
        if ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        j += 1
    return depth


def _value_offset(line: str, indent: int) -> int | None:
    """该行**值**的起始下标（`key: v` / `- key: v` / `- v`）；不是值位置 ⇒ `None`。"""
    body = line[indent:]
    if body.startswith("- ") or body == "-":
        pos = indent + 1
        while pos < len(line) and line[pos] == " ":
            pos += 1
        rest = line[pos:]
        if ":" in rest and rest[0] not in ('"', "'"):
            return pos + len(rest.partition(":")[0]) + 1      # `- key: value`
        return pos                                            # `- value`
    if ":" in body:
        return indent + len(body.partition(":")[0]) + 1        # `key: value`
    return None


def _zero_dep_syntax_error(text: str) -> str | None:
    """**零依赖严格闸**：只拒**确定的语法非法**，返回 `"行:列: 原因"` 或 `None`。

    判据（**保守**：宁可漏也不误拒 —— 误拒会把合法用例判红，正是 #5151 判据 3 禁止的形态）：
      · **引号标量**：闭合引号之后还有内容 ⇒ 提前闭合（#5147 的真实形态）；到文件结尾仍未
        闭合 ⇒ 未闭合。（合法的**跨行**引号标量在收尾时已闭合 ⇒ 不判。）
      · **flow 集合**：值位置以 `[` / `{` 起头 ⇒ 括号必须配平（**可以跨行**，收尾时仍为净正
        深度 ⇒ 未闭合）。（`[` 出现在**标量中间**是合法的 —— 实测 PyYAML 接受 `a: 见 [文档`，
        故只在**值位置**判 flow，不做全文括号计数。）
      · **块标量**（`|` / `>`）的内容行整行跳过（那里的引号/括号是文本）。
    """
    block_indent: int | None = None
    open_quoted: tuple[int, int, str] | None = None      # (行, 列, 引号)
    open_flow: tuple[int, int] | None = None             # (行, 列)
    flow_depth = 0
    for lineno, line in enumerate(text.split("\n"), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if block_indent is not None:                     # 块标量内容行
            if indent > block_indent:
                continue
            block_indent = None
        if open_quoted is not None:                      # 跨行引号标量的续行
            if _find_close(line, 0, open_quoted[2]) is not None:
                open_quoted = None
            continue
        if open_flow is not None:                        # 跨行 flow 集合的续行
            flow_depth += _flow_delta(line)
            if flow_depth <= 0:
                open_flow = None
            continue
        off = _value_offset(line, indent)
        if off is None:
            continue
        value = line[off:]
        stripped = value.lstrip()
        if not stripped:
            continue
        if _BLOCK_SCALAR_HEAD.match(stripped.split("#")[0].strip()):
            block_indent = indent                        # 值本身是块标量头
            continue
        start = off + (len(value) - len(stripped))
        head = stripped[0]
        if head in ('"', "'"):
            end = _find_close(line, start + 1, head)
            if end is None:
                open_quoted = (lineno, start + 1, head)
                continue
            tail = line[end + 1:]
            if tail.strip() and not tail.lstrip().startswith("#"):
                return (f"{lineno}:{start + 1}: 引号提前闭合：`{head}` 标量在列 {end + 1} 处闭合，"
                        f"其后还有内容 {tail.strip()[:40]!r} —— 标量内出现了**未转义的 {head}**"
                        f"（要表达字面 {head}，双引号里写 `\\{head}`）")
            continue
        if head in "[{":                                 # 只有**值位置**起头的括号才是 flow 节点
            flow_depth = _flow_delta(line[start:])
            if flow_depth > 0:
                open_flow = (lineno, start + 1)
        # 裸标量：里面的引号/括号是合法文本（实测 PyYAML 接受 `a: 见 [文档`）⇒ 不判
    if open_quoted is not None:
        lineno, col, quote = open_quoted
        return f"{lineno}:{col}: 引号未闭合（到文件结尾都没有出现配对的 `{quote}`）"
    if open_flow is not None:
        lineno, col = open_flow
        return f"{lineno}:{col}: flow 集合未闭合（`[` / `{{` 到文件结尾都没有配对）"
    return None


# ═══════════════════════════════════════════════════════════════════════════
# 重复键检测（issue #4291 / #4336）：**两个后端共用这一处**（判定一致 = 构造上成立）
# ═══════════════════════════════════════════════════════════════════════════
def _key_colon(text: str) -> int | None:
    """块映射**键**后面那个冒号的下标；不是键位置 ⇒ `None`。

    只认「`:` 后是行尾或空白」这一形态（YAML 块映射的要求）⇒ 裸标量里的 `见 [文档]` /
    `12:30` 不会被误判成键。引号内的 `:` 用 `_find_close` 跳过；以 `[` / `{` 起头的
    **flow 键**（`[a, b]: v`）不在本检测面内（照实登记，见模块头的"抓不到"表）。
    """
    j = 0
    while j < len(text):
        ch = text[j]
        if ch in ('"', "'"):
            end = _find_close(text, j + 1, ch)
            if end is None:
                return None                        # 引号未闭合 ⇒ 交给语法闸，不在这里判键
            j = end + 1
            continue
        if ch == ":" and (j + 1 == len(text) or text[j + 1] in " \t"):
            return j
        if ch in "[{":
            return None
        j += 1
    return None


def _cut_inline_comment(text: str) -> str:
    """截到**行内注释**起点（行首或空白后的 `#`）；**引号内的 `#` 不算**。

    ⚠️ 不许写裸 `split("#")` / `partition("#")` / `re.sub` 做这件事：本仓有一条**类级判据**
    专治「朴素 `#` 截断」（`tests/unit_ci_workflows/test_guard_parsing_is_comment_aware.py` 的
    `naive-hash-cut` + **只许缩短**的豁免台账）—— 新增解析代码必须走引号感知的剥离，
    **不许**往台账里加条目（加了 = 新增债务 = 红）。
    """
    j = 0
    while j < len(text):
        ch = text[j]
        if ch in ('"', "'"):
            end = _find_close(text, j + 1, ch)
            if end is None:
                return text                            # 引号未闭合 ⇒ 交给语法闸，这里不猜
            j = end + 1
            continue
        if ch == "#" and (j == 0 or text[j - 1].isspace()):
            return text[:j]
        j += 1
    return text


def _normalize_key(raw: str) -> str:
    """键的归一形态：**引号键去引号**（YAML 里 `"a": 1` 与 `a: 1` 是同一个键 ⇒ 必须归一，
    否则 `"a"` 与后文的 `a` 之间那次重复会被漏掉）。解码只做最小集（`\\"` / `\\\\` / `''`）。
    """
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ('"', "'"):
        body, q = raw[1:-1], raw[0]
        if q == '"':
            return body.replace('\\"', '"').replace("\\\\", "\\")
        return body.replace("''", "'")
    return raw


def _scan_key_anomalies(text: str) -> list[str]:
    """**零依赖的行级键异常扫描**（块映射面）：返回**全部**异常的 `["行:列: 原因", ...]`
    （文件顺序；空列表 = 无异常 —— 计数取这一处，不写死数字）。

    两类，都是"键 / 断言被静默吞掉"同一族（且**两个后端跑同一份实现** ⇒ 判定一致靠构造）：

    ① **重复键**：同一 mapping 缩进层内同名键。⚠️ PyYAML **不报错**、只保留最后一个
       ⇒ "换成严格解析器"治不了它（`#4291` 的 5 个 `expect:`、`#4336` 的 12 处）；
    ② **键落在标量序列项的续行区**：`- 标量项` 之后的更深行里出现 `key: ` —— 标准 YAML
       在此报 `mapping values are not allowed here`（实测），宽松腿会把这条键**静默吞掉**
       （`ai-chat.yml` 的 `- 工具调用失败场景` + `expect:` 就是这个形态：
       那条断言**从来没有被装载过**，而它看起来在文件里）。

    为什么必须零依赖：CI 的 `case-truth-check` job **没有 PyYAML**（模块头），而渲染腿
    （`render_cases.py` 的 `load_case_dicts`）正是在那里跑的 ⇒ 若只在"有 PyYAML"那一侧检测，
    "渲染腿 fail-closed"在 CI 上就只是名义上的（#5151 已为语法面吃过这个亏）。

    形态（保守：宁可漏也不误拒 —— 误拒会把合法用例判红，正是 #5151 判据 3 禁止的形态）：
      · 缩进栈：键只在**同一 mapping 缩进层**内比重复；`- key: v` 的序列项自成一层
        （连续两个 `- ` 项各自开新 mapping，同名键**不算**重复）；
      · **块标量内容行** / **跨行引号标量续行** / **跨行 flow 续行** / **标量项续行区**
        整段跳过（那里的冒号是文本）；
      · flow 映射内部的重复键**不判**；非空裸标量值之后的更深键行**有意不判**
        （同族形态，但判它会把既有 `NOT_COVERED["tab_indent"]` 登记顶成假红 —— 见模块头表）。
    """
    stack: list[tuple[int, dict[str, int]]] = []      # (mapping 缩进, {归一键: 首次行号})
    hits: list[str] = []
    block_indent: int | None = None
    open_quote: str | None = None
    cont: tuple[int, int] | None = None               # (标量项缩进, 该项所在行)：更深的行是它的续行
    flow_depth = 0
    for lineno, line in enumerate(text.split("\n"), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if block_indent is not None:                  # 块标量内容行：整行是文本
            if indent > block_indent:
                continue
            block_indent = None
        if open_quote is not None:                    # 跨行引号标量的续行
            if _find_close(line, 0, open_quote) is not None:
                open_quote = None
            continue
        if flow_depth > 0:                            # 跨行 flow 集合的续行
            flow_depth += _flow_delta(line)
            continue
        body = line[indent:]
        if cont is not None:                          # 标量序列项的续行区
            if indent > cont[0]:
                if _key_colon(body) is not None:
                    hits.append(
                        f"{lineno}:{indent + 1}: 标量序列项（第 {cont[1]} 行）的**续行**里出现 `key: `"
                        f" —— 标准 YAML 在此报 `mapping values are not allowed here`，"
                        f"宽松腿会把这条键**静默吞掉**")
                continue
            cont = None
        is_item = body.startswith("- ") or body == "-"
        if is_item:                                   # `- key: v`：项内容自成一层
            pos = indent + 1
            while pos < len(line) and line[pos] == " ":
                pos += 1
            entry = line[pos:]
            while stack and stack[-1][0] >= pos:      # 序列项 ⇒ 每次开新 mapping
                stack.pop()
            if _key_colon(entry) is None:             # 标量项
                if _BLOCK_SCALAR_HEAD.match(_cut_inline_comment(entry).strip()):
                    block_indent = indent             # `- |` 块标量项：更深行整段是**合法文本**
                else:
                    cont = (indent, lineno)           # 标量项：更深行是它的续行，不是键
                continue
        else:
            pos, entry = indent, body
        key_col = _key_colon(entry)
        if key_col is None:                           # 无键行
            continue
        key = _normalize_key(entry[:key_col])
        if key:                # ⚠️ 键**先入栈**：值的形态只决定"后续行要不要整段跳过"，
            if not is_item:    # 不影响这一行是不是键（`verifies: []` 的键也必须入栈，
                while stack and stack[-1][0] > pos:   # 否则同键的第二次出现被判"首次"两遍 ⇒ 漏报）
                    stack.pop()
            if not stack or stack[-1][0] < pos:
                stack.append((pos, {}))
            seen = stack[-1][1]
            if key in seen:
                hits.append(f"{lineno}:{pos + 1}: 同一 mapping 内重复键 `{key}`"
                            f"（首次在第 {seen[key]} 行）—— YAML 只保留最后一份")
            else:
                seen[key] = lineno                        # 只记首次 ⇒ 3 次以上也逐对点到
        rest = entry[key_col + 1:]
        stripped = rest.lstrip()
        if stripped[:1] in ("[", "{"):                # 值本身是 flow 集合 ⇒ **跨行**时跳过后续行
            flow_depth = max(0, _flow_delta(rest))    # （同行闭合 ⇒ 计 0，不影响下一个逻辑行）
        elif _BLOCK_SCALAR_HEAD.match(_cut_inline_comment(stripped).strip()):
            block_indent = pos                        # 值本身是块标量头
        elif (stripped[:1] in ('"', "'")
                and _find_close(rest, len(rest) - len(stripped) + 1, stripped[0]) is None):
            open_quote = stripped[0]                  # 值是多行引号标量
    return hits


#: 报错里最多列几处异常（防病态文件刷屏）；**计数**另走 `key_anomalies()`（现取，不受此限）。
_MAX_REPORTED_ANOMALIES = 5


def key_anomalies(text: str) -> list[str]:
    """**全部**行级键异常（`["行:列: 原因", ...]`）—— 判据计数用这一处（现取，不写死数字）。"""
    return _scan_key_anomalies(text)


def _zero_dep_key_anomalies(text: str) -> str | None:
    """扫描结果的**报错形态**（`None` = 无异常；最多列 `_MAX_REPORTED_ANOMALIES` 处 + 余量）。"""
    hits = _scan_key_anomalies(text)
    if not hits:
        return None
    more = (f"（另有 {len(hits) - _MAX_REPORTED_ANOMALIES} 处）"
            if len(hits) > _MAX_REPORTED_ANOMALIES else "")
    return "；".join(hits[:_MAX_REPORTED_ANOMALIES]) + more


# ═══════════════════════════════════════════════════════════════════════════
# 判定入口（两侧共用这一处）
# ═══════════════════════════════════════════════════════════════════════════
#: 判定缓存：**键 = 文件内容的 sha256**（不是路径/时间戳）⇒ 不可能读到过期结论（内容变了键就变）。
#: 只缓存**不含文件名的判定结论**，**绝不缓存解析结果** —— 那会把同一份可变对象共享给多个调用方
#: （本仓 `tests/unit_ci_workflows/conftest.py` 有专门的共享对象污染防线，不能自己造一个）。
#: 为什么需要：渲染腿的严格判定会被 `load_case_dicts()` 调用上百次（CI 的
#: `tests/unit_ci_workflows` 套件），实测每次 0.66s（C loader 后 0.055s）⇒ 累计会让该 job 撞上
#: 自己的 8 分钟超时。缓存后同一进程内重复调用只付"读文件 + sha256"的代价。
_VERDICT_CACHE: dict[str, str | None] = {}
_VERDICT_CACHE_MAX = 1024          # 纯防病态增长；命中率与容量无关（套件里内容种类有限）


def _verdict_core(text: str) -> str | None:
    """**与路径无关**的严格判定（`"行:列: 原因"` 或 `None`）—— 缓存的正是它。

    ⚠️ 缓存键是内容 ⇒ 结论里的位置/原因必须**不含文件名**：否则同内容的两份文件（如两份坏夹具）
    会拿到**指错文件**的报错（那是"报错指向错误的对象"，本仓的经典假红形态）。
    """
    if _pyyaml is not None:                                     # 后端 ①
        try:
            _safe_load(text)
        except _pyyaml.YAMLError as e:
            mark = getattr(e, "problem_mark", None)
            where = f"{mark.line + 1}:{mark.column + 1}" if mark is not None else "<位置不明>"
            problem = getattr(e, "problem", None) or str(e)
            return f"{where}: {problem}（标准 YAML 解析失败）"
    else:
        rel = _zero_dep_syntax_error(text)                      # 后端 ②
        if rel:
            return f"{rel}（零依赖严格闸）"
    # 重复键：**语法之外**，且**两个后端共用同一份实现**（见本节上方）—— PyYAML 对重复键
    # 不报错（只保留最后一个），所以它必须在这里独立判，不是"换个严格解析器就好了"。
    return _zero_dep_key_anomalies(text)


def strict_error(path) -> str | None:
    """**唯一的严格判定**（渲染腿与判据腿共用这一处实现）。`None` = 合法。

    返回的字符串**必须指名文件与位置** —— "哪一处"是 #5151 的判据之一：旧形态要么报
    「渲染成功」（无从定位），要么直接抛整条 traceback（读者以为病在别处）。
    """
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    key = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if key not in _VERDICT_CACHE:
        if len(_VERDICT_CACHE) >= _VERDICT_CACHE_MAX:
            _VERDICT_CACHE.clear()
        _VERDICT_CACHE[key] = _verdict_core(text)
    core = _VERDICT_CACHE[key]
    return f"{p}:{core}" if core else None


def require_strict(path) -> None:
    """不合法 ⇒ `raise CasesYamlError`（两条腿的 fail-closed 入口）。"""
    err = strict_error(path)
    if err:
        raise CasesYamlError(err)


def load_document(path) -> dict:
    """严格解析 ⇒ `dict`（**判据腿**用它：解析口径 = 原 `yaml.safe_load`，逐字不变）。

    渲染腿**不用**它：生成物必须逐字不变，所以渲染口径仍是 `yaml_light`（见
    `.github/render_cases.py` 的 `load_case_dicts`），它只用 `require_strict()` 取"合法/非法"
    的**结论**。两条腿消费的字段本就不同 ⇒ **共用的是"严格判定"**，那正是 #5151 里分叉的东西。

    无 PyYAML ⇒ 抛 `CasesYamlError`（**不可判**）：判据腿的 job 本就装了 pyyaml，缺了它是环境
    事故，**不许**静默降级成宽松解析（那会把"判据没跑"写成"没有漂移"）。
    """
    require_strict(path)
    if _pyyaml is None:                                         # pragma: no cover - 环境事故
        raise CasesYamlError(
            f"{path}: 严格解析需要 PyYAML，而本环境不可导入 ⇒ 判据**不可判**（三态 3），"
            f"不是「发现数为 0」")
    return _safe_load(Path(path).read_text(encoding="utf-8")) or {}


def key_anomaly_error(path) -> str | None:
    """**只**判行级键异常（重复键 / 键落在标量项续行区），**不判语法** ⇒ `"文件:行:列: 原因"` 或 `None`。

    `strict_error()` 已含这一层；本函数单列是给**语法上非法、但按行可判**的面用的：
    `.github/templates/*.yml` 的 `- [真值 ID] 说明` 是**有意**的类 YAML 约定（26 个模板在
    标准 YAML 下全是 `ParserError`），而 `#4291` 的真值断言静默丢弃正出在那里
    ⇒ 模板面只能走这条**行级**判据（`truths.py` 用 `yaml_light` 读它们，宽松腿看不见重复键）。
    """
    p = Path(path)
    rel = _zero_dep_key_anomalies(p.read_text(encoding="utf-8"))
    return f"{p}:{rel}" if rel else None
