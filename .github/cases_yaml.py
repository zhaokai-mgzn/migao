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
| flow 集合（`[` / `{`）**到文件结尾未闭合**（含跨行） | 重复键（PyYAML 本身也不报） |
| | flow 集合内部的其它语法错误（如 `[a: b, c` 之外的分隔符错） |
| | 引号**跨行**时的那一行之后、闭合之前的内容（按"续行"整体跳过） |

⚠️ 后端②**只许更严不许更宽**：它绝不因为"看起来可疑"就拒（那会把合法用例判红 = 反向护栏
失守）。上表右侧**不是"可以不管"**，而是**已知的覆盖缺口**，由
`tests/unit_ci_workflows/test_render_cases_yaml_fail_closed.py` 的 `NOT_COVERED` 逐条钉住 ——
**登记有死亡条件**：谁把某条补上了，那条登记会当场变红，逼他更新表（本仓 §17.3 ④ 的口径）。
"""
from __future__ import annotations

import re
from pathlib import Path

__all__ = ["CasesYamlError", "pyyaml_available", "strict_error", "require_strict",
           "load_document"]


class CasesYamlError(Exception):
    """**严格判定不通过**（消息里带 `文件:行:列` 与原因）—— 两条腿都必须 fail-closed。"""


try:                      # 模块级可选导入：渲染腿的 CI job 没有 PyYAML（见模块 docstring）
    import yaml as _pyyaml
except ImportError:       # pragma: no cover —— 由「无 PyYAML」子进程夹具覆盖
    _pyyaml = None


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
# 判定入口（两侧共用这一处）
# ═══════════════════════════════════════════════════════════════════════════
def strict_error(path) -> str | None:
    """**唯一的严格判定**（渲染腿与判据腿共用这一处实现）。`None` = 合法。

    返回的字符串**必须指名文件与位置** —— "哪一处"是 #5151 的判据之一：旧形态要么报
    「渲染成功」（无从定位），要么直接抛整条 traceback（读者以为病在别处）。
    """
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if _pyyaml is not None:                                     # 后端 ①
        try:
            _pyyaml.safe_load(text)
        except _pyyaml.YAMLError as e:
            mark = getattr(e, "problem_mark", None)
            where = f"{mark.line + 1}:{mark.column + 1}" if mark is not None else "<位置不明>"
            problem = getattr(e, "problem", None) or str(e)
            return f"{p}:{where}: {problem}（标准 YAML 解析失败）"
        return None
    rel = _zero_dep_syntax_error(text)                          # 后端 ②
    return f"{p}:{rel}（零依赖严格闸）" if rel else None


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
    return _pyyaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
