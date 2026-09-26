"""渲染腿「取值保真」比较器 —— 真值（PyYAML） vs 产物（生成物里的**字面量**）。

## 它比对的是什么（口径写死在这里；**别处不许再写第二份**）

| 侧 | 来源 | 取法 |
|---|---|---|
| **真值** | `.github/cases/*.yml`（用例库单一源） | `yaml.safe_load`（标准 YAML 就是"真值"的定义） |
| **产物** | `tests/agent_eval/eval_cases.py` | `ast.literal_eval` 取每个 `EvalCase(...)` 的**关键字字面量**（**不 exec** —— 产物是数据，不是该被执行的代码） |

比的是**取值**（不是"能不能解析"）：逐 `(文件, 用例 id, 字段)` 深比较。
`expectations` 是派生字段，两侧都过 `render_cases.exp_to_str`（**同一份实现**，不复制第二份）。

## 三个读数 —— 说"多少处"必须同时说口径，否则数字不可复算

· `sites`：取值不同的 `(文件, 用例 id, 字段)` 三元组数；
· `leaf_diffs`：上述差异里**不同的叶子字符串**个数（list/dict 元素级）；
· `escape_overflow`：产物侧**多出**的转义序列逐类计数（非重叠 —— `\\` 记「两个反斜杠」这个序列）。

⚠️ issue #5179 原文写「36 处」（31 处 `\\"` + 5 处 `\\\\` / `\\/`）：那个脚本是 heredoc、**未入库**，
且当时用例数是 424（现 428）⇒ **口径不可复算**。落地时以本模块的三个读数 + 逐处清单为准
（实证：`sites=33` / `leaf_diffs=45` / `escape_overflow` 合计 163），**不把 33 写成 36**。

## 自证「比较器真的抓到了数据」（本模块存在的第二个理由）

#5179 派工方**两次**独立测量都因猜错结构而无效 —— 真值侧解析出 **0 条**，而"0 条"看起来
与"没有差异"一模一样（一次假绿就此诞生）。⇒ `Report.assert_sane()` 把这件事变成**断言**：
任一侧条数为 0、或两侧 id 序列不是逐位相同 ⇒ **抛错**（那是"比较器坏了"，不是"没差异"）。
"""
from __future__ import annotations

import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
GH = REPO_ROOT / ".github"
if str(GH) not in sys.path:
    sys.path.insert(0, str(GH))

from render_cases import exp_to_str  # noqa: E402  ← 派生字段的**单一实现**，不复制第二份

#: 渲染腿**逐字搬运**的字段（identity / `repr`）：两侧可直接比。
#: 派生字段（`id` / `skill` / `difficulty`）不在其中；`expectations` 走 `exp_to_str`。
VERBATIM_FIELDS = (
    "title", "user_inputs", "data_checks", "skip_reason", "legacy_id", "tags", "persona",
    "debug_user", "debug_permissions", "form_prefill", "forbidden_card_text", "order_before",
    "forbidden_text", "forbidden_tools", "want_text", "required_args", "forbidden_args",
    "forbidden_interact", "arg_values",
    "must_succeed", "must_fail", "amount_verify", "db_verify", "output_verify", "pre_clean",
    "post_clean", "post_session", "namespaces", "precondition", "auto_fill",
)
#: 缺省是**列表**的字段（`None` 与 `[]` 同义 —— 渲染腿对未声明字段不落字面量）
_LIST_FIELDS = frozenset(VERBATIM_FIELDS) - {
    "title", "skip_reason", "persona", "debug_user", "debug_permissions", "legacy_id",
}

#: 产物侧多出的转义序列逐类计数用（**非重叠**匹配）
ESCAPE_FORMS = ("\\\"", "\\\\", "\\/", "\\n", "\\t", "\\r")


@dataclass
class Report:
    """一次比较的全部读数 + 逐处清单。"""

    truth_count: int
    artifact_count: int
    missing_in_artifact: list[str] = field(default_factory=list)
    missing_in_truth: list[str] = field(default_factory=list)
    #: `(文件, 用例 id, 字段, 真值, 产物)`；两个值都可能是 list/dict
    sites: list[tuple[str, str, str, Any, Any]] = field(default_factory=list)
    #: `(文件, 用例 id, 字段, 真值叶子, 产物叶子)`
    leaf_diffs: list[tuple[str, str, str, str, str]] = field(default_factory=list)
    escape_overflow: dict[str, int] = field(default_factory=dict)

    @property
    def total_escape_overflow(self) -> int:
        return sum(self.escape_overflow.values())

    def assert_sane(self) -> None:
        """**比较器自身的健康断言**：抓不到数据 ⇒ 抛错（不是"没有差异"）。

        实测教训（#5179）：真值侧解析出 0 条时，`sites == []` 与"完全一致"长得一模一样。
        """
        assert self.truth_count > 0, (
            "比较器坏了：真值侧（yaml.safe_load 用例库）解析出 **0 条** —— 结构猜错了？"
            "「0 条」不是「没有差异」。")
        assert self.artifact_count > 0, (
            "比较器坏了：产物侧（eval_cases.py 的 EvalCase 字面量）解析出 **0 条** —— "
            "`ast.literal_eval` 的取法过时了？「0 条」不是「没有差异」。")
        assert not self.missing_in_artifact, (
            f"产物缺用例（渲染腿丢条）：{self.missing_in_artifact[:10]}")
        assert not self.missing_in_truth, (
            f"产物多出真值库里没有的用例 id：{self.missing_in_truth[:10]}")


def truth_cases(cases_dir) -> dict[str, dict]:
    """真值侧：`yaml.safe_load` 每个 `*.yml` ⇒ `{用例 id: 用例 dict}`（附 `_file`）。"""
    out: dict[str, dict] = {}
    for f in sorted(Path(cases_dir).glob("*.yml")):
        doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        for c in doc.get("cases") or []:
            c = dict(c)
            c["_file"] = f.name
            out[c["id"]] = c
    return out


def artifact_cases(path) -> tuple[dict[str, dict], set[str]]:
    """产物侧：`ast.literal_eval` 取每个 `EvalCase(...)` 的关键字字面量（**不 exec**）。

    返回 `({用例 id: 字段 dict}, 取不出字面量的关键字名)` —— 后者应恰为两个枚举
    （`skill` / `difficulty`），它是"产物结构没变"的自证之一。
    """
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    non_literal: set[str] = set()
    for stmt in tree.body:
        if not isinstance(stmt, ast.Assign):
            continue
        call = stmt.value
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                and call.func.id == "EvalCase"):
            continue
        case: dict = {}
        for kw in call.keywords:
            try:
                case[kw.arg] = ast.literal_eval(kw.value)
            except ValueError:
                non_literal.add(kw.arg)
        out[case["id"]] = case
    return out, non_literal


def _norm(value, field_name: str):
    """未声明字段（产物里不落字面量）与显式空值同义。"""
    if value is None:
        return [] if field_name in _LIST_FIELDS else ""
    return value


def _truth_field(case: dict, field_name: str):
    if field_name == "expectations":
        return [exp_to_str(e) for e in (case.get("expectations") or [])]
    return _norm(case.get(field_name), field_name)


def _artifact_field(case: dict, field_name: str):
    if field_name == "expectations":
        return _norm(case.get("expectations"), field_name)
    return _norm(case.get(field_name), field_name)


def _leaf_pairs(a, b, acc: list) -> None:
    """递归收集叶子对：`str` 逐值、list/dict 逐元素（**不**把整串差异算作 1 处）。"""
    if isinstance(a, str) and isinstance(b, str):
        acc.append((a, b))
        return
    if isinstance(a, list) and isinstance(b, list):
        for x, y in zip(a, b):
            _leaf_pairs(x, y, acc)
        return
    if isinstance(a, dict) and isinstance(b, dict):
        for k in a:
            if k in b:
                _leaf_pairs(a[k], b[k], acc)
        return
    if a != b:
        acc.append((a, b))


def compare(cases_dir, artifact_path) -> Report:
    """跑一次完整对照（真值 vs 产物），返回 `Report`。**比较器的唯一入口。**"""
    truth = truth_cases(cases_dir)
    artifact, _non_literal = artifact_cases(artifact_path)
    rep = Report(truth_count=len(truth), artifact_count=len(artifact))
    rep.missing_in_artifact = [k for k in truth if k not in artifact]
    rep.missing_in_truth = [k for k in artifact if k not in truth]

    fields = list(VERBATIM_FIELDS) + ["expectations"]
    overflow = {form: 0 for form in ESCAPE_FORMS}
    for cid, t in truth.items():
        got = artifact.get(cid)
        if got is None:
            continue
        for name in fields:
            a, b = _truth_field(t, name), _artifact_field(got, name)
            if a == b:
                continue
            rep.sites.append((t["_file"], cid, name, a, b))
            pairs: list = []
            _leaf_pairs(a, b, pairs)
            for x, y in pairs:
                if x == y or not isinstance(y, str):
                    continue
                rep.leaf_diffs.append((t["_file"], cid, name, x, y))
                if isinstance(x, str):
                    for form in ESCAPE_FORMS:
                        overflow[form] += y.count(form) - x.count(form)
    rep.escape_overflow = {k: v for k, v in overflow.items() if v}
    return rep


def format_sites(rep: Report, limit: int = 0, width: int = 72) -> str:
    """逐处清单（人读 / 贴报告用）。`limit=0` ⇒ 全列。"""
    rows = rep.sites if not limit else rep.sites[:limit]
    out = []
    for fn, cid, name, a, b in rows:
        out.append(f"· {fn} {cid}.{name}")
        out.append(f"    真值: {str(a)[:width]!r}")
        out.append(f"    产物: {str(b)[:width]!r}")
    return "\n".join(out)
