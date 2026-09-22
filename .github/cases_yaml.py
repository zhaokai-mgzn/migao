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

故判定后端分两层，而**判定口径写在这一个函数里、两侧共用**：
① 有 `yaml.safe_load` ⇒ **用它**（= 判据腿原口径，逐字不变）；
② 没有 ⇒ `_quote_syntax_error()`（纯标准库）：**只拒确定的语法非法**。
⚠️ ②**只许更严不许更宽** —— 它绝不因为"看起来可疑"就拒（那会把合法用例判红 = 反向护栏失守）；
代价是它覆盖不到 ① 能拒的全部形态，这条边界照实登记在
`tests/unit_ci_workflows/test_render_cases_yaml_fail_closed.py`（在 PyYAML 环境对**全部**
`cases/*.yml` 用 ① 复算）。
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


def _quoted_scalar_tail_error(line: str, off: int, quote: str) -> str | None:
    """`line[off]` 处起一个 `quote` 引号标量 ⇒ 检查它的**闭合位置**。

    合法：闭合引号之后只剩空白或行内注释（`key: "a"   # 说明`）。
    非法：闭合引号之后**还有内容** ⇒ 该标量**提前闭合**了
    （`key: "… type == "number" …"`，#5147 的实测形态）。
    本行找不到闭合引号 ⇒ **不判**（可能是合法的多行标量，跨行才闭合）。
    """
    i, n = off + 1, len(line)
    while i < n:
        ch = line[i]
        if quote == '"' and ch == "\\":
            i += 2                      # `\"` = 双引号标量内的转义引号（合法）
            continue
        if ch == quote:
            if quote == "'" and i + 1 < n and line[i + 1] == "'":
                i += 2                  # `''` = 单引号标量内的转义引号（合法）
                continue
            tail = line[i + 1:]
            if tail.strip() and not tail.lstrip().startswith("#"):
                return (f"引号提前闭合：`{quote}` 标量在列 {i + 1} 处闭合，其后还有内容 "
                        f"{tail.strip()[:40]!r} —— 标量内出现了**未转义的 {quote}**"
                        f"（要表达字面 {quote}，双引号里写 `\\{quote}`）")
            return None
        i += 1
    return None


def _quote_syntax_error(text: str) -> str | None:
    """**零依赖严格闸**：只拒**确定的语法非法**，返回 `"行:列: 原因"` 或 `None`。

    判据（**保守**：宁可漏也不误拒 —— 误拒会把合法用例判红，正是 #5151 判据 3 禁止的形态）：
      · 只看**值位置**（`key: …` / `- key: …` / `- …`）以 `"` / `'` 起头的标量；
      · 只判「**闭合引号之后还有内容**」（= 提前闭合，见 `_quoted_scalar_tail_error`）；
      · 块标量（`|` / `>`）的**内容行整体跳过** —— 那些行里的引号是合法文本，不是标量起点。
    """
    block_indent: int | None = None
    for lineno, line in enumerate(text.split("\n"), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if block_indent is not None:
            if indent > block_indent:
                continue                # 块标量内容行（引号在这里是文本）
            block_indent = None
        body = line[indent:]
        if body.startswith("- ") or body == "-":
            pos = indent + 1
            while pos < len(line) and line[pos] == " ":
                pos += 1
            rest = line[pos:]
            if ":" in rest and rest[0] not in ('"', "'"):
                off = pos + len(rest.partition(":")[0]) + 1     # `- key: value`
            else:
                off = pos                                        # `- value`
        elif ":" in body:
            off = indent + len(body.partition(":")[0]) + 1       # `key: value`
        else:
            continue
        value = line[off:]
        stripped = value.lstrip()
        if not stripped:
            continue
        if _BLOCK_SCALAR_HEAD.match(stripped.split("#")[0].strip()):
            block_indent = indent       # 值本身是块标量头 ⇒ 后续更深的行是它的内容
            continue
        if stripped[0] not in ('"', "'"):
            continue                    # 裸标量里的引号是合法文本（`key: 他说 "好"`）
        off += len(value) - len(stripped)
        err = _quoted_scalar_tail_error(line, off, stripped[0])
        if err:
            return f"{lineno}:{off + 1}: {err}"
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
    rel = _quote_syntax_error(text)                             # 后端 ②
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
