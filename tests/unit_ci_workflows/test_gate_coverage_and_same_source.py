# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012 ——
#   见同目录 `_source_parsing.py` / `test_guard_parsing_is_comment_aware.py` 的同款声明。
#   本 PR 不新建用例族：仓库没有「开发工具链」用例族，塞进行为用例库会污染覆盖矩阵。）
r"""**「声明 / 契约」与「门禁是否真的覆盖它」之间的常驻判据**（issue #4177 + #5007）。

## 病根（一类缺陷：**声明与消费脱节**）

#4177 与 #5007 是同一族的两个实例 —— **改动落在门禁射程之外，没有任何东西会因此变红**：

| 实例 | 声明侧 | 消费侧 | 旧口径下为什么不会红 |
|---|---|---|---|
| **#4177** | 跨模块契约判据住在 `backend/ai-agent-service/tests/**` | 断言的对象是 `backend/admin-api/src/main/java/**` 的 Java DTO | PR 侧门禁的**触发谓词**只覆盖「守卫自己住的目录」⇒ 纯 Java PR 零命中 ⇒ `Run unit tests` 整段 skipped 而 job 结论仍是 success（红只在**部署腿**爆，部署腿又无路径门控、命令逐字相同） |
| **#5007①** | `tests/agent_eval/local_runner.py::_BLOCKING_VERDICT_KEYS` 的注释写着与 `scripts/eval_closeout.py` 的动态枚举**同源** | closeout 真的按 `set(completion) - NON_BLOCKING_VERDICT_KEYS` 枚举 | 「同源」只写在**注释**里、没有任何测试读那一侧 ⇒ 删一个桶名（`restore_failures`）⇒ 34 条守卫全绿、closeout 静默不阻塞 |
| **#5007②** | `FACES` 这类模块级冻结集合 | 守卫只写 `assert len(FACES) >= 5` | 下界**只防清空**、不防「删掉任意一个面」；`FACES` 的内容没有逐面锚点 |

本文件把两侧都变成**机械判据**（形态学 = `tests/unit_ci_workflows/test_guard_parsing_is_comment_aware.py`）：
**未登记即红** + 台账**逐项相等 / 只许缩短**。

## 判据（每条都能单独变红；注入式红证见 `TestRedProofs` 与 PR body 的逐字输出）

| # | 判据 | 语义 |
|---|---|---|
| 1 | 现取 ⊆ 登记册 | 凡「**会被路径门控**的 PR 门禁」必须登记（新增一条未登记 ⇒ 红） |
| 2 | 登记册 ⊆ 现取 | 登记项必须**存活**：workflow / job / check_name / **被门控的步骤名**与现取**逐字相符**（陈旧 ⇒ 红） |
| 3 | 触发谓词**逐字存在于 workflow** | 登记册里的谓词是**现取原文**（改 workflow 不改登记册 ⇒ 红；两边都改 ⇒ 判据 4 接着拦） |
| 4 | 触发面**覆盖** `must_cover` 面 | 每条 `must_cover` 路径必须被该门禁的触发谓词命中 —— **#4177 的实例判据**：把 `backend/admin-api/src/main/java` 从谓词里删掉 ⇒ 红 |
| 5 | 断言面**自动发现**（未登记即红） | 门禁的测试源码里凡「按仓根拼出的仓内路径」所指的目录，必须登记为 `must_cover` 或 `uncovered` ⇒ 新出现一个跨模块读取面而没人登记 ⇒ 红 |
| 6 | `uncovered` 逐条带**理由 + 单号 + owner** | 「扩面即改锚」：缺口不许匿名存在（§23 G5：面外不是安全区） |
| 7 | `_BLOCKING_VERDICT_KEYS` ≡ 消费侧现取键集（**三条腿**）| #5007①：runner 真产出的 verdict 键集 − closeout 的非阻塞键集；runner `completion_verdict` 的**每个** `return` 点；closeout 的 `blocking_buckets()` 实调 |
| 8 | 冻结集合**逐项**冻结 | #5007②：凡「对模块级字面量集合只设 `len(...) >= N` 下界」的声明，必须登记**逐项成员**（多一个/少一个都红） |
| 9 | 注释声称「同源 / 一致」⇒ 必须有判据 | `#` 注释块紧邻模块级字面量集合声明的同源声明，必须登记 `criterion`（可解析到**真实存在的测试**）或 `unfixed`（理由 + 单号 + owner） |
| 10 | **反空跑读数** | 各面计数**现取**打印；取空 ⇒ 红（「扫不到」不许长得像「通过」） |

数据文件 = `tests/unit_ci_workflows/declaration_gate_registry.json`（**豁免/登记都在 diff 里看得见**）。

## 读法（结构化证据，不是文案匹配）

- **门禁触发面**：读**真 YAML**（`yaml.safe_load`）的 `on.pull_request.paths` / `paths-ignore`，
  以及「一步把 `NAME=true|false` 写进 `$GITHUB_OUTPUT`、另一步的 `if:` 引用 `steps.<id>.outputs.`」这条**结构**；
  **不按文件名/步骤文案清单**枚举。
- **断言面自动发现**：读测试源码的 **AST**（`repo_base / "字面量"` 链表、`Path("字面量")`），
  且只认**在仓内真实存在**的路径（fixture 里当字符串传的路径不会被读成「读取面」）。
- **同源声明 / 冻结集合**：读模块级字面量集合（走共享读法 `_source_parsing.assigned_strings`，
  成员级名字回指另用 `declared_strings` 补一层），**注释块**按行取 —— 注释不是 AST 节点，故不会被当成声明；
  反过来，声明也不会因为「注释里提过」而被读出来。

## 残余（照实登记，见登记册 `unfixed`，别把「登记了」读成「治住了」）

① 自动发现只覆盖 **Python** 面的门禁（TS/JS 门禁的断言面仍是**人工声明**）；
② 自动发现只认两种路径构造式（`/` 链表 + `Path(字面量)`）—— `os.path.join(_HERE, "..", "..")` 这类**构造式**不在面内（假绿方向）；
③ 同源声明只扫「`#` 注释块**紧邻**模块级字面量集合声明」这一形态；docstring / 行内注释里的同源声明不在面内；
④ `criterion` 只被核到「**该测试真的存在**」—— 它是否**真的钉住**那句声明，机械判据判不了（假判据拦不住）；
⑤ `FACES` 那三处的**下界断言本身**未被移除（本包不改那些文件的归属面），靠的是**逐项冻结**这条更强的判据覆盖它们。

判据 = 本文件；一键复算：
`python3 -m pytest tests/unit_ci_workflows/test_gate_coverage_and_same_source.py -q -s`
"""

from __future__ import annotations

import ast
import json
import re
import sys
import types
from functools import lru_cache
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
UNIT_CI_DIR = REPO / "tests" / "unit_ci_workflows"
AGENT_EVAL_DIR = REPO / "tests" / "agent_eval"
GITHUB_DIR = REPO / ".github"
GITHUB_SCRIPTS_DIR = GITHUB_DIR / "scripts"
SCRIPTS_DIR = REPO / "scripts"
WORKFLOWS_DIR = GITHUB_DIR / "workflows"
REGISTRY_PATH = UNIT_CI_DIR / "declaration_gate_registry.json"
SELF_REL = "tests/unit_ci_workflows/test_gate_coverage_and_same_source.py"

# append（**不是** insert）：只作兜底解析路径，避免遮蔽 site-packages 里的同名模块。
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(AGENT_EVAL_DIR))
sys.path.append(str(SCRIPTS_DIR))

from unit_ci_workflows._source_parsing import (  # noqa: E402  （#5323 收敛：唯一取值口径）
    assigned_strings,
    declared_strings,
    java_literals,
)

#: 「跨实现一致」类措辞的形态清单（出现在「声明正上方」即意味着该声明有另一侧实现）。
CLAIM_MARKERS = ("同源", "逐字一致", "必须等于", "保持一致", "同一集合", "单一实现", "两份实现")

#: 同源声明 / 冻结集合的**判据面**（按路径取；缺面 ⇒ 红）。
SURFACE_SPECS = (
    (UNIT_CI_DIR, True, "tests/unit_ci_workflows/**"),
    (AGENT_EVAL_DIR, False, "tests/agent_eval/*.py"),
    (GITHUB_DIR, False, ".github/*.py"),
    (GITHUB_SCRIPTS_DIR, False, ".github/scripts/*.py"),
    (SCRIPTS_DIR, False, "scripts/*.py"),
)

#: 仓内路径字面量的**顶层形状**（第二个要素是「它不是外部 URL / API 路径」的结构性证据）。
REPO_PATH_RE = re.compile(r"^(backend|frontend|scripts|tests|product|deploy|docs|\.github)/")

#: `NAME=true|false` 写进 `$GITHUB_OUTPUT` 的赋值形态（门控输出名）。
OUTPUT_ASSIGN_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=(?:true|false)")


# ══════════════════════════════════════════════════════════════════════════════
# 一、登记册
# ══════════════════════════════════════════════════════════════════════════════


@lru_cache(maxsize=1)
def _registry() -> dict:
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    for key in ("gates", "same_source_claims", "frozen_declarations"):
        assert isinstance(data.get(key), list) and data[key], (
            f"登记册 `{key}` 必须是非空数组（空 ⇒ 判据在空集上恒真）"
        )
    return data


def _gate_index() -> dict[tuple[str, str], dict]:
    return {(str(g["workflow"]), str(g["job"])): g for g in _registry()["gates"]}


# ══════════════════════════════════════════════════════════════════════════════
# 二、门禁触发面：读**真 YAML**（结构，不是文件名清单）
# ══════════════════════════════════════════════════════════════════════════════


@lru_cache(maxsize=1)
def _workflow_docs() -> dict[str, dict]:
    docs: dict[str, dict] = {}
    for path in sorted(WORKFLOWS_DIR.glob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(doc, dict):
            docs[path.name] = doc
    assert docs, "workflows 目录取空（glob/路径失效）⇒ 本判据会静默空跑成绿"
    return docs


def _workflow_text(name: str) -> str:
    return (WORKFLOWS_DIR / name).read_text(encoding="utf-8")


def _pr_config(doc: dict) -> dict | None:
    """`on.pull_request` 配置；**不在 PR 面** ⇒ `None`（本判据只管 PR 阶段的门禁）。"""
    on = doc.get("on") if isinstance(doc.get("on"), dict) else doc.get(True)
    if not isinstance(on, dict) or on.get("pull_request") is None:
        return None
    pr = on["pull_request"]
    return pr if isinstance(pr, dict) else {}


def _emitters(job: dict) -> dict[str, dict]:
    """把 `<名>=true|false` 写进 `$GITHUB_OUTPUT` 的步骤（`id` → 步骤名 / 输出名 / run 原文）。

    这是「**步骤级路径门控**」的结构签名：门控输出只有这两个取值，且写在 `$GITHUB_OUTPUT`。
    """
    out: dict[str, dict] = {}
    for step in job.get("steps") or []:
        if not isinstance(step, dict) or not step.get("id"):
            continue
        run = step.get("run") or ""
        names: set[str] = set()
        for line in run.splitlines():
            if "GITHUB_OUTPUT" in line:
                names.update(OUTPUT_ASSIGN_RE.findall(line))
        if names:
            out[str(step["id"])] = {"step": str(step.get("name") or step["id"]), "outputs": sorted(names), "run": run}
    return out


def _path_gated_jobs() -> dict[tuple[str, str], dict]:
    """现取的「**会被路径门控**的 PR 门禁」：workflow 级 `paths` 过滤，或步骤级门控输出。

    为什么是这两条：它们正是「**断言可能整段不跑而结论照旧**」的两种结构（#4177 的现场是后者）。
    `if: failure()` / `if: github.event_name == ...` 这类**不看路径**的条件不算门控 —— 它们不改变射程。
    """
    found: dict[tuple[str, str], dict] = {}
    for name, doc in _workflow_docs().items():
        pr = _pr_config(doc)
        if pr is None:
            continue
        paths = list(pr.get("paths") or [])
        ignored = list(pr.get("paths-ignore") or [])
        for jid, job in (doc.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            emitters = _emitters(job)
            gated_steps: list[str] = []
            for step in job.get("steps") or []:
                if not isinstance(step, dict):
                    continue
                cond = str(step.get("if") or "")
                if any(f"steps.{sid}.outputs." in cond for sid in emitters):
                    gated_steps.append(str(step.get("name") or step.get("id")))
            if not (paths or ignored or gated_steps):
                continue
            found[(name, str(jid))] = {
                "workflow": name,
                "job": str(jid),
                "check_name": str(job.get("name") or jid),
                "paths": paths,
                "paths_ignore": ignored,
                "gated_steps": gated_steps,
                "emitters": emitters,
            }
    return found


def _glob_re(pattern: str) -> re.Pattern:
    """`paths:` glob → 正则（`**` 跨目录、`*` 不跨目录 —— **保守**：`*` 不许跨越 `/`）。"""
    out, i = [], 0
    while i < len(pattern):
        char = pattern[i]
        if char == "*":
            if pattern[i : i + 2] == "**":
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(char))
        i += 1
    return re.compile("^" + "".join(out) + "$")


def _globs_cover(patterns: list[str], path: str) -> bool:
    positives = [_glob_re(p) for p in patterns if not p.startswith("!")]
    negatives = [_glob_re(p[1:]) for p in patterns if p.startswith("!")]
    probe = path + "/__probe__"
    return any(rx.match(probe) or rx.match(path) for rx in positives) and not any(
        rx.match(probe) or rx.match(path) for rx in negatives
    )


#: 「通配一切」形态：空分支（`||` / `(|` / `|)`）或裸 `.*` —— 退化成「每个 PR 都跑」。
CATCH_ALL_RE = re.compile(r"\(\s*\||\|\s*\)|\|\|")


def _is_catch_all(predicate: str) -> bool:
    """该触发谓词是否已退化成「**通配一切**」（#4177 明确禁止的糊法：那样所有 PR 都跑重活）。"""
    return bool(CATCH_ALL_RE.search(predicate)) or predicate.strip() in (".*", "^", "")


def _trigger_covers(trigger: dict, path: str) -> bool:
    """该门禁的触发谓词是否覆盖 `path`（目录按 `<path>/__probe__` 探针测）。"""
    kind = str(trigger.get("kind"))
    if kind == "pull_request_paths":
        return _globs_cover(list(trigger.get("paths") or []), path)
    if kind in ("step-detect-regex", "step-detect-grep"):
        rx = re.compile(str(trigger["predicate"]))
        probe = path + "/__probe__"
        return bool(rx.search(probe) or rx.search(path))
    raise AssertionError(f"未知的触发面类型 {kind!r} ⇒ 本判据不认识它（口径漂移 ⇒ 红，同步登记册）")


# ══════════════════════════════════════════════════════════════════════════════
# 三、断言面自动发现（AST：按仓根拼出的**仓内真实路径**）
# ══════════════════════════════════════════════════════════════════════════════


def _div_chain(node: ast.AST) -> list[str] | None:
    """`BASE / "a" / "b"` 的**字面量尾链**（`BASE` 是任意名字，成员全是字符串字面量）。"""
    parts: list[ast.AST] = []
    while isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        parts.append(node.right)
        node = node.left
    if not isinstance(node, ast.Name) or not parts:
        return None
    if not all(isinstance(p, ast.Constant) and isinstance(p.value, str) for p in parts):
        return None
    return [p.value for p in parts]


def _path_literal(node: ast.AST) -> str | None:
    """`Path("a/b")` 的单字面量实参。"""
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Path"
        and len(node.args) == 1
        and not node.keywords
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    ):
        return node.args[0].value
    return None


def _deepest_existing(rel: str) -> str | None:
    """`rel` 在仓内**真实存在**的最深前缀（不存在任何前缀 ⇒ `None`）—— 判据的「真读了它」证据。"""
    cursor, found = REPO, None
    for segment in rel.strip("/").split("/"):
        nxt = cursor / segment
        if not nxt.exists():
            break
        cursor, found = nxt, str(nxt.relative_to(REPO))
    return found


@lru_cache(maxsize=4)
def _observed_surface(root_rel: str) -> dict[str, list[str]]:
    """该门禁的测试源码所**读到的仓内路径**（相对路径 → 见证位置清单）。

    只认两种构造式（`BASE / "字面量"` 链表 / `Path("字面量")`）且必须**在仓内存在** ——
    fixture 里当字符串传的路径（例如把 `frontend/…` 喂给某个 map 函数）不会被读成「读取面」。
    """
    found: dict[str, list[str]] = {}
    for path in sorted((REPO / root_rel).rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = str(path.relative_to(REPO))
        source = path.read_text(encoding="utf-8")
        if not any(trace in source for trace in ("backend/", "frontend/", "docs/", ".github/", "scripts/", "tests/")):
            continue
        for node in ast.walk(ast.parse(source, filename=rel)):
            parts = _div_chain(node)
            literal = "/".join(parts).lstrip("/") if parts else _path_literal(node)
            if not literal or not REPO_PATH_RE.match(literal):
                continue
            deepest = _deepest_existing(literal)
            if deepest is None:
                continue
            found.setdefault(deepest, []).append(f"{rel}")
    return {k: sorted(set(v)) for k, v in found.items()}


def _is_under(path: str, declared: str) -> bool:
    return path == declared or path.startswith(declared.rstrip("/") + "/")


# ══════════════════════════════════════════════════════════════════════════════
# 四、模块级字面量集合的**成员**（含成员级名字回指）
# ══════════════════════════════════════════════════════════════════════════════


def _assigned_value(source: str, symbol: str, where: str) -> ast.AST:
    """模块级 `symbol = <值>` / `symbol: T = <值>` 的**值节点**（未声明 ⇒ 红）。"""
    values = [
        node.value
        for node in ast.parse(source, filename=where).body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and any(
            isinstance(t, ast.Name) and t.id == symbol
            for t in (node.targets if isinstance(node, ast.Assign) else [node.target])
        )
    ]
    assert values, f"{where} 里找不到模块级 `{symbol} = …`（改名/搬家 ⇒ 判据的定位锚点失效 ⇒ 红）"
    return values[0]


def _try_shared_reader(source: str, symbol: str, where: str) -> tuple[str, ...] | None:
    """共享读法**能**直接给出成员时返回它；成员级名字回指会让它按口径漂移报错 ⇒ 返回 `None`。"""
    try:
        return assigned_strings(source, symbol, where)
    except AssertionError:
        return None


def _members_of(source: str, symbol: str, where: str) -> tuple[str, ...]:
    """模块级字面量字符串集合的成员（按源码顺序）。

    取值口径**复用共享实现** `_source_parsing.assigned_strings`（#5323 收敛：不新造读法）；
    它只解「**整体**名字回指」（`X = OTHER`），成员级回指（`IMPLEMENTATIONS = (HELPER, …)`）
    按口径漂移报错 ⇒ 这里补一层**成员级**解析：字面量成员直接取，名字成员走共享的
    `declared_strings`（认 `NAME = "字面量"`），其余形态一律报错（fail-closed，不静默给空集）。
    """
    shared = _try_shared_reader(source, symbol, where)
    if shared is not None:
        return shared
    node = _assigned_value(source, symbol, where)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and len(node.args) == 1:
        node = node.args[0]
    assert isinstance(node, (ast.Tuple, ast.List, ast.Set)), (
        f"{where} 的 `{symbol}` 不是字面量集合（{type(node).__name__}）⇒ 口径漂移 ⇒ 红"
    )
    out: list[str] = []
    for item in node.elts:
        if isinstance(item, ast.Constant) and isinstance(item.value, str):
            out.append(item.value)
            continue
        assert isinstance(item, ast.Name), (
            f"{where} 的 `{symbol}` 有非字面量成员（{ast.dump(item)[:60]}）⇒ 无法逐项冻结 ⇒ 红"
        )
        resolved = declared_strings(source, item.id, f"{where}::{symbol}")
        assert len(resolved) == 1, (
            f"{where} 的 `{symbol}` 成员 `{item.id}` 不是唯一字面量声明（{resolved}）⇒ 逐项冻结失效 ⇒ 红"
        )
        out.append(resolved[0])
    return tuple(out)


# ══════════════════════════════════════════════════════════════════════════════
# 五、扫描：同源声明 / 冻结集合下界（**只扫注释块，不扫 docstring**）
# ══════════════════════════════════════════════════════════════════════════════


@lru_cache(maxsize=1)
def _surface_files() -> tuple[Path, ...]:
    found: set[Path] = set()
    for base, recursive, _label in SURFACE_SPECS:
        if not base.is_dir():
            continue
        found.update(base.rglob("*.py") if recursive else base.glob("*.py"))
    return tuple(sorted(p for p in found if "__pycache__" not in p.parts))


def _comment_block_above(lines: list[str], lineno: int) -> str:
    """声明正上方**连续的 `#` 注释块**（空行/code 行即止）—— 注释不是 AST 节点，故只能按行取。"""
    out: list[str] = []
    i = lineno - 2
    while i >= 0 and lines[i].lstrip().startswith("#"):
        out.append(lines[i])
        i -= 1
    return "\n".join(reversed(out))


def _module_literals(tree: ast.Module) -> list[tuple[str, int]]:
    """模块级「字面量字符串集合」声明（符号名 + 行号）；成员级名字回指也算（`IMPLEMENTATIONS` 形态）。"""
    out: list[tuple[str, int]] = []
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and len(value.args) == 1:
            value = value.args[0]
        if not isinstance(value, (ast.Tuple, ast.List, ast.Set)) or len(value.elts) < 2:
            continue
        if not all(isinstance(e, (ast.Constant, ast.Name)) for e in value.elts):
            continue
        if not any(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in value.elts):
            continue
        for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
            if isinstance(target, ast.Name):
                out.append((target.id, node.lineno))
    return out


@lru_cache(maxsize=1)
def _scan_surface() -> dict[str, object]:
    """一趟扫描：`claims`（注释声称同源）与 `bounds`（冻结集合只设下界）两张现取清单。"""
    claims: dict[tuple[str, str], str] = {}
    bounds: dict[tuple[str, str], dict] = {}
    skipped: list[str] = []
    for path in _surface_files():
        rel = str(path.relative_to(REPO))
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=rel)
        literals = _module_literals(tree)
        for symbol, lineno in literals:
            block = _comment_block_above(source.splitlines(), lineno)
            if any(marker in block for marker in CLAIM_MARKERS):
                claims[(rel, symbol)] = " ".join(line.strip() for line in block.splitlines())[-160:]
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assert):
                continue
            test = node.test
            if not (
                isinstance(test, ast.Compare)
                and len(test.ops) == 1
                and isinstance(test.ops[0], (ast.GtE, ast.Gt))
                and isinstance(test.left, ast.Call)
                and isinstance(test.left.func, ast.Name)
                and test.left.func.id == "len"
                and test.left.args
                and isinstance(test.left.args[0], ast.Name)
                and test.comparators
                and isinstance(test.comparators[0], ast.Constant)
                and isinstance(test.comparators[0].value, int)
            ):
                continue
            symbol = test.left.args[0].id
            if symbol not in {name for name, _ln in literals}:
                continue
            try:
                members = _members_of(source, symbol, rel)
            except AssertionError as exc:
                skipped.append(f"{rel}::{symbol}（{exc}）")
                continue
            bounds[(rel, symbol)] = {"bound": int(test.comparators[0].value), "members": list(members)}
    return {"claims": claims, "bounds": bounds, "skipped": tuple(skipped)}


# ══════════════════════════════════════════════════════════════════════════════
# 六、同源判据（#5007① + 另两处注释里的「同源」）
# ══════════════════════════════════════════════════════════════════════════════


def _load_runner():
    """导入 `local_runner`（L0 job 只装 pytest+pyyaml ⇒ 缺 httpx 时注入最小替身，同 #3781 做法）。"""
    try:
        import httpx  # noqa: F401
    except ImportError:  # pragma: no cover - 本地 venv 有 httpx
        stub = types.ModuleType("httpx")

        class _AsyncClient:
            def __init__(self, *a, **k):
                raise RuntimeError("httpx 替身：本文件的单测不得真实发起 HTTP")

        stub.AsyncClient = _AsyncClient
        sys.modules.setdefault("httpx", stub)
    import local_runner

    return local_runner


def _return_dict_keys(source: str, func_name: str, where: str) -> dict[int, tuple[str, ...]]:
    """函数里**每个** `return {…}` 点的键集（`**` 展开 ⇒ 红：键集不完整就没有「逐字相等」可言）。"""
    out: dict[int, tuple[str, ...]] = {}
    for node in ast.walk(ast.parse(source, filename=where)):
        if not isinstance(node, ast.FunctionDef) or node.name != func_name:
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Return) or not isinstance(child.value, ast.Dict):
                continue
            keys: list[str] = []
            for key in child.value.keys:
                assert isinstance(key, ast.Constant) and isinstance(key.value, str), (
                    f"{where}::{func_name} 的 return 点含非字面量键（{ast.dump(key)[:60] if key else '** 展开'}）"
                    " ⇒ 键集不可逐字比对 ⇒ 红"
                )
                keys.append(key.value)
            out[child.lineno] = tuple(keys)
    assert out, f"{where}::{func_name} 里找不到返回字面量 dict 的点（改名 ⇒ 判据失锚 ⇒ 红）"
    return out


def _closeout():
    import eval_closeout as ec

    return ec


def _consumed_blocking_keys(runner, ec) -> set[str]:
    """消费侧真值：runner **真产出**的 verdict 键集 − closeout 的非阻塞键集。"""
    verdict = runner.completion_verdict([])
    return set(verdict) - set(ec.NON_BLOCKING_VERDICT_KEYS)


# ══════════════════════════════════════════════════════════════════════════════
# 判据 1/2/3：门禁触发面的登记与存活
# ══════════════════════════════════════════════════════════════════════════════


def test_every_path_gated_pr_gate_is_registered() -> None:
    """凡「会被路径门控的 PR 门禁」必须登记（新增一条未登记 ⇒ 红）。"""
    live = _path_gated_jobs()
    registered = set(_gate_index())
    missing = sorted(set(live) - registered)
    print(f"现取路径门控门禁={len(live)} 条；登记册={len(registered)} 条")
    for key in sorted(live):
        info = live[key]
        kind = "workflow.paths" if info["paths"] or info["paths_ignore"] else "step-detect"
        print(f"  {key[0]}::{key[1]}  [{kind}]  gated_steps={info['gated_steps']}")
    assert not missing, (
        "出现**未登记**的路径门控门禁（它的断言可能整段不跑，而没有任何判据会因此变红）：\n"
        + "\n".join(f"  {wf}::{job}" for wf, job in missing)
        + "\n修法：往 tests/unit_ci_workflows/declaration_gate_registry.json 的 `gates` 里登记它 ——"
        " 逐字写出触发谓词（或 paths 列表）+ `must_cover`（它断言所依赖的目录）+ `uncovered`（缺口，带理由/单号/owner）。\n"
        f"复算：python3 -m pytest {SELF_REL} -q -s"
    )


def test_registry_entries_are_live_and_verbatim() -> None:
    """登记册 ⊆ 现取：workflow / job / check_name / 被门控步骤名 / 谓词原文都必须**逐字相符**。"""
    live = _path_gated_jobs()
    problems: list[str] = []
    for key, gate in sorted(_gate_index().items()):
        if key not in live:
            problems.append(f"{key[0]}::{key[1]}：**陈旧条目** —— 现取已不是路径门控（删掉该登记或改正锚点）")
            continue
        info = live[key]
        if str(gate.get("check_name")) != info["check_name"]:
            problems.append(
                f"{key[0]}::{key[1]}：`check_name` 不符 —— 登记 {gate.get('check_name')!r} / 现取 {info['check_name']!r}"
                "（名字是分支保护 required 的锚点，改名必须同改登记册）"
            )
        if sorted(gate.get("gated_steps") or []) != sorted(info["gated_steps"]):
            problems.append(
                f"{key[0]}::{key[1]}：被门控的步骤名不符 —— 登记 {sorted(gate.get('gated_steps') or [])}"
                f" / 现取 {sorted(info['gated_steps'])}（按**步骤名**定位，改步骤序列必须同改登记册，§23.5）"
            )
        trigger = gate.get("trigger") or {}
        text = _workflow_text(key[0])
        if str(trigger.get("kind")) == "pull_request_paths":
            if list(trigger.get("paths") or []) != info["paths"]:
                problems.append(
                    f"{key[0]}::{key[1]}：`paths` 与现取不符 —— 登记 {trigger.get('paths')} / 现取 {info['paths']}"
                )
        else:
            predicate = str(trigger.get("predicate") or "")
            if predicate not in text:
                problems.append(
                    f"{key[0]}::{key[1]}：触发谓词在 workflow 里**找不到现取原文** —— 登记 {predicate!r}"
                    "（谓词必须逐字来自现取 YAML：改了 workflow 不改登记册 ⇒ 这里红）"
                )
            if _is_catch_all(predicate):
                problems.append(
                    f"{key[0]}::{key[1]}：触发谓词是**通配一切**形态（{predicate!r}）—— 空分支（`||` / `(|` / `|)`）"
                    "或裸 `.*` ⇒ 每个 PR 都跑全量（#4177 明确禁止用通配糊过去）。要么精确列路径，要么论证代价"
                )
    assert not problems, "登记册与现取门禁不一致：\n" + "\n".join(f"  {p}" for p in problems)


def test_trigger_surface_covers_declared_surface() -> None:
    """触发面必须**覆盖**每一条 `must_cover` 面（#4177 的实例判据）。"""
    problems: list[str] = []
    covered = 0
    for gate in _registry()["gates"]:
        for entry in gate["must_cover"]:
            path = str(entry["path"])
            if _trigger_covers(gate["trigger"], path):
                covered += 1
                continue
            problems.append(
                f"{gate['workflow']}::{gate['job']} 的触发谓词**不覆盖** `{path}` —— {entry['reason']}"
            )
    print(f"must_cover 面现取={covered} 条已覆盖 / 缺口={len(problems)} 条")
    assert not problems, (
        "「断言所读的对象面」落在触发面之外 ⇒ 改它不会跑这门禁（#4177 形态：红只在别人的腿上爆）：\n"
        + "\n".join(f"  {p}" for p in problems)
        + "\n修法（二选一）：① 把该路径加进触发谓词（**精确路径**，不许用通配一切糊过去）；"
        "② 若代价不可接受 ⇒ 把它登记到该门禁的 `uncovered`（带理由 + 单号 + owner），缺口就不许匿名存在。"
    )


def test_assertion_surface_is_declared() -> None:
    """断言面**自动发现**：门禁测试源码读到的仓内路径必须全部登记（未登记即红）。"""
    problems: list[str] = []
    total = 0
    for gate in _registry()["gates"]:
        root = gate.get("auto_discover_root")
        if not root:
            continue
        declared = [str(e["path"]) for e in gate["must_cover"]] + [str(u["path"]) for u in gate["uncovered"]]
        observed = _observed_surface(str(root))
        total += len(observed)
        print(f"  {gate['id']}: 自动发现 {len(observed)} 条读取面（root={root}）")
        for path in sorted(observed):
            if any(_is_under(path, d) for d in declared):
                continue
            problems.append(
                f"{gate['id']}：测试源码读了 `{path}`（见证：{observed[path][:3]}），但登记册里没有它"
                " ⇒ 改它不会触发本门禁，而断言会红"
            )
    print(f"自动发现面现取={total} 条")
    assert total >= 4, f"自动发现只扫到 {total} 条面 ⇒ 扫描口径疑似失效（本判据会静默空跑成绿）"
    assert not problems, (
        "出现**未登记**的断言依赖面：\n"
        + "\n".join(f"  {p}" for p in problems)
        + "\n修法：把它登记为 `must_cover`（⇒ 触发谓词必须覆盖它）或 `uncovered`（带理由 + 单号 + owner）。"
    )


def test_uncovered_entries_carry_reason_issue_and_owner() -> None:
    """缺口（`uncovered`）与未固化项必须带**理由 + 单号 + owner**（燃尽靶子：只许缩短）。"""
    problems: list[str] = []
    rows = 0
    for gate in _registry()["gates"]:
        for entry in gate.get("uncovered") or []:
            rows += 1
            _check_residue(entry, f"{gate['id']}::uncovered::{entry.get('path')}", problems)
    for entry in _registry().get("unfixed") or []:
        rows += 1
        _check_residue(entry, f"unfixed::{entry.get('what')}", problems)
    print(f"未固化/缺口登记现取={rows} 条")
    assert rows >= 4, f"缺口登记只有 {rows} 条 ⇒ 本判据在空集上恒真"
    assert not problems, "缺口登记不合规（豁免必须带理由 + 单号 + owner）：\n" + "\n".join(f"  {p}" for p in problems)


def _check_residue(entry: dict, where: str, problems: list[str]) -> None:
    reason = str(entry.get("reason") or entry.get("unfixed_reason") or "").strip()
    issue = str(entry.get("issue") or "").strip()
    owner = str(entry.get("owner") or "").strip()
    if len(reason) < 12:
        problems.append(f"{where}：`reason` 缺失或过短（{reason!r}）")
    if not re.fullmatch(r"#\d{3,}", issue):
        problems.append(f"{where}：`issue` 缺失或不是单号（{issue!r}）")
    if len(owner) < 4:
        problems.append(f"{where}：`owner` 缺失（谁看这个缺口）（{owner!r}）")


# ══════════════════════════════════════════════════════════════════════════════
# 判据 7：`_BLOCKING_VERDICT_KEYS` ≡ 消费侧现取键集（#5007①）
# ══════════════════════════════════════════════════════════════════════════════


def test_blocking_verdict_keys_match_closeout_consumption() -> None:
    """阻塞桶键集必须与**消费侧现取**逐字一致（三条腿：runner 产出 / 每个 return 点 / closeout 枚举）。"""
    runner = _load_runner()
    ec = _closeout()
    declared = tuple(runner._BLOCKING_VERDICT_KEYS)
    assert len(set(declared)) == len(declared), f"阻塞桶键有重复（{declared}）⇒ 枚举与集合口径不等价"
    consumed = _consumed_blocking_keys(runner, ec)
    runner_rel = "tests/agent_eval/local_runner.py"
    where = f"{runner_rel}::_BLOCKING_VERDICT_KEYS"
    print(f"阻塞桶（声明）={sorted(declared)}")
    print(f"阻塞桶（消费侧现取）={sorted(consumed)}")
    assert set(declared) == consumed, (
        f"{where} 与消费侧**不再是同一集合**（注释里声称的「同源」必须由本判据承担）：\n"
        f"  只在声明里、消费侧没有：{sorted(set(declared) - consumed)}\n"
        f"  只在消费侧、声明里没有：{sorted(consumed - set(declared))}\n"
        "修法：两边同改（runner 的枚举 / closeout 的 NON_BLOCKING_VERDICT_KEYS）；"
        "删一个桶名 ⇒ 该桶在 closeout 侧静默不再阻塞 —— 那是 #5007① 的原始缺陷。"
    )
    for lineno, keys in sorted(_return_dict_keys(runner_rel_text(), "completion_verdict", runner_rel).items()):
        got = set(keys) - set(ec.NON_BLOCKING_VERDICT_KEYS)
        assert got == set(declared), (
            f"{runner_rel}::completion_verdict 的 return 点（第 {lineno} 行）键集与阻塞桶不一致：\n"
            f"  该点独有：{sorted(got - set(declared))}\n  声明里独有：{sorted(set(declared) - got)}\n"
            "（两处 return 点必须同口径 —— 早退分支漏一个桶 = 那条结论永远不阻塞）"
        )
    completion = {key: [] for key in declared}
    completion.update({"ok": True, "reason": "", "flake_released": [], "total": 0, "passed": 0})
    assert set(ec.blocking_buckets(completion)) == set(declared), (
        "closeout 的 `blocking_buckets()`（动态枚举）与本清单**不是同一集合** ——"
        " 它多算/少算的桶会在 closeout 结论里静默出现或被漏掉"
    )


def runner_rel_text() -> str:
    return (REPO / "tests" / "agent_eval" / "local_runner.py").read_text(encoding="utf-8")


def test_pg_bin_dirs_match_java_side() -> None:
    """`pg_cluster.BIN_DIRS` 与其注释声称同源的 Java 侧 `PgCluster.BIN_DIRS` **逐项且同序**。"""
    py_rel = "tests/unit_ci_workflows/pg_cluster.py"
    java_rel = "backend/admin-api/src/test/java/com/migao/admin/service/PgCluster.java"
    python_side = _members_of((REPO / py_rel).read_text(encoding="utf-8"), "BIN_DIRS", py_rel)
    java_text = (REPO / java_rel).read_text(encoding="utf-8")
    match = re.search(r"BIN_DIRS\s*=\s*List\.of\(", java_text)
    assert match, f"{java_rel} 里找不到 `BIN_DIRS = List.of(` —— 判据失锚（改名 ⇒ 红）"
    depth, i = 1, 0
    chars = java_text[match.end() :]
    while i < len(chars) and depth:
        if chars[i] == "(":
            depth += 1
        elif chars[i] == ")":
            depth -= 1
        i += 1
    assert depth == 0, f"{java_rel} 的 `List.of(` 括号不平衡 ⇒ 判据失锚 ⇒ 红"
    java_side = tuple(value for _line, value in java_literals(chars[: i - 1]))
    print(f"Python BIN_DIRS={python_side}")
    print(f"Java   BIN_DIRS={java_side}")
    assert python_side == java_side, (
        f"两侧 `BIN_DIRS` 不再一致（注释声称「同源」，#5007 同族）：\n"
        f"  {py_rel}：{python_side}\n  {java_rel}：{java_side}\n"
        "  后果：一侧加了新路径、另一侧没加 ⇒ 只有一侧找不到 PG 二进制（缺 PG 会被判 FAIL / 静默 skip 成绿）。"
    )


def test_named_batch_types_match_tool_side() -> None:
    """`NAMED_BATCH_TYPES` 与其注释声称同源的**工具侧** `BATCH_TYPES` 逐项一致。"""
    guard_rel = "tests/unit_ci_workflows/test_shared_fixture_write_restore.py"
    tool_rel = "backend/ai-agent-service/app/tools/product_batch_update.py"
    guard_side = _members_of((REPO / guard_rel).read_text(encoding="utf-8"), "NAMED_BATCH_TYPES", guard_rel)
    tool_side = _members_of((REPO / tool_rel).read_text(encoding="utf-8"), "BATCH_TYPES", tool_rel)
    print(f"用例侧 NAMED_BATCH_TYPES={guard_side}")
    print(f"工具侧 BATCH_TYPES={tool_side}")
    assert guard_side == tool_side, (
        f"两侧批量类型清单不再一致（注释声称「同源口径」）：\n  用例侧：{guard_side}\n  工具侧：{tool_side}\n"
        "  后果：工具新增一个批类型而用例侧不认 ⇒ 该类型用例被静默跳过（少跑 = 假绿）。"
    )


def test_effect_layer_fields_are_a_subset_of_taxonomy() -> None:
    """`_EFFECT_LAYER_FIELDS` 与其注释声称**同源子集**的 `EFFECT_FIELDS` 必须真含于它。"""
    runner = _load_runner()
    tax_rel = ".github/assertion_taxonomy.py"
    universe = set(_members_of((REPO / tax_rel).read_text(encoding="utf-8"), "EFFECT_FIELDS", tax_rel))
    declared = tuple(runner._EFFECT_LAYER_FIELDS)
    print(f"runner 侧 _EFFECT_LAYER_FIELDS={declared}")
    print(f"taxonomy 侧 EFFECT_FIELDS={sorted(universe)}")
    assert declared, "runner 侧效果层清单为空 ⇒ 该口径失效"
    assert set(declared) <= universe, (
        f"runner 侧声明的效果层字段**不在** `.github/assertion_taxonomy.py::EFFECT_FIELDS` 里"
        "（注释声称「同源子集」）：\n"
        f"  多出来的：{sorted(set(declared) - universe)}\n"
        "  后果：这边把某个字段当效果层、那边不算 ⇒ 同一份用例在两条腿上被判成不同强度。"
    )


# ══════════════════════════════════════════════════════════════════════════════
# 判据 8/9：冻结集合逐项冻结 + 同源声明必须有判据（#5007②）
# ══════════════════════════════════════════════════════════════════════════════


def test_frozen_declarations_are_pinned_exactly() -> None:
    """凡「对模块级字面量集合只设 `len(...) >= N` 下界」的声明，必须**逐项冻结**（多/少都红）。"""
    scan = _scan_surface()
    bounds = scan["bounds"]
    assert isinstance(bounds, dict)
    registered = {(str(e["file"]), str(e["symbol"])): e for e in _registry()["frozen_declarations"]}
    unregistered = sorted(set(bounds) - set(registered))
    stale = sorted(set(registered) - set(bounds))
    print(f"现取「只设下界的冻结集合」={len(bounds)} 条；登记={len(registered)} 条；未判定的声明={scan['skipped']}")
    for key, info in sorted(bounds.items()):
        print(f"  {key[0]}::{key[1]}  下界>={info['bound']}  成员={len(info['members'])}")
    assert not unregistered, (
        "出现**未登记**的「只设下界的冻结集合」（下界只防清空、不防删掉任意一项 —— #5007② 形态）：\n"
        + "\n".join(f"  {rel}::{symbol}（下界>={bounds[(rel, symbol)]['bound']}，成员 {len(bounds[(rel, symbol)]['members'])} 个）"
                    for rel, symbol in unregistered)
        + "\n修法：把它的**逐项成员**登记进 declaration_gate_registry.json 的 `frozen_declarations`（多一个/少一个都会红）。"
    )
    assert not stale, (
        "登记册里的冻结声明**已陈旧**（现取没有该「只设下界」形态 —— 可能已改成逐项比对）：\n"
        + "\n".join(f"  {rel}::{symbol}" for rel, symbol in stale)
        + "\n修法：销账（台账只许缩短）。"
    )
    for (rel, symbol), entry in sorted(registered.items()):
        members = _members_of((REPO / rel).read_text(encoding="utf-8"), symbol, rel)
        assert tuple(entry["members"]) == members, (
            f"{rel}::{symbol} 的成员与登记册**不再逐项相等**（这正是 #5007② 要的「多一个/少一个都红」）：\n"
            f"  登记册：{tuple(entry['members'])}\n  现取：{members}\n"
            "  新增/删除一个成员 ⇒ 同一 PR 里同改登记册（在 diff 里看得见）。"
        )
        assert int(entry["bound"]) == bounds[(rel, symbol)]["bound"], (
            f"{rel}::{symbol} 的下界数值与现取不符（登记 {entry['bound']} / 现取 {bounds[(rel, symbol)]['bound']}）"
        )
        assert int(entry["bound"]) == len(members), (
            f"{rel}::{symbol} 的下界（{entry['bound']}）与成员数（{len(members)}）**不同步** ——"
            " 这正是 #5007② 登记的形态（下界未随 +1 同步）"
        )


def test_same_source_claims_have_criteria() -> None:
    """注释里声称的「同源 / 一致」必须有**可解析到真实测试**的判据，或登记为未固化。"""
    scan = _scan_surface()
    claims = scan["claims"]
    assert isinstance(claims, dict)
    registered = {(str(e["file"]), str(e["symbol"])): e for e in _registry()["same_source_claims"]}
    unregistered = sorted(set(claims) - set(registered))
    stale = sorted(set(registered) - set(claims))
    problems: list[str] = []
    print(f"现取「注释声称同源」的声明={len(claims)} 条；登记={len(registered)} 条")
    for key, claim in sorted(claims.items()):
        print(f"  {key[0]}::{key[1]}  «{claim[:90]}»")
    for rel, symbol in unregistered:
        problems.append(
            f"{rel}::{symbol}：注释声称同源但**未登记** —— «{claims[(rel, symbol)][:120]}»\n"
            "    修法：登记 `criterion`（`<测试文件>::<测试名>`，必须真实存在）或 `unfixed`（理由 + 单号 + owner）"
        )
    for rel, symbol in stale:
        problems.append(f"{rel}::{symbol}：登记已**陈旧**（现取没有该声明）⇒ 销账（台账只许缩短）")
    for (rel, symbol), entry in sorted(registered.items()):
        criterion = str(entry.get("criterion") or "")
        if not criterion:
            _check_residue(entry, f"{rel}::{symbol}", problems)
            continue
        test_file, sep, test_name = criterion.partition("::")
        if not (sep and test_name):
            problems.append(f"{rel}::{symbol}：`criterion` 必须写成 `<测试文件>::<测试名>`（现取 {criterion!r}）")
            continue
        target = REPO / test_file
        if not target.is_file():
            problems.append(f"{rel}::{symbol}：`criterion` 指向的文件不存在（{test_file}）⇒ **死判据**")
            continue
        if not re.search(rf"^def {re.escape(test_name)}\(", target.read_text(encoding="utf-8"), re.M):
            problems.append(f"{rel}::{symbol}：`criterion` 指向的测试不存在（{criterion}）⇒ **死判据**")
    assert not problems, (
        "「注释里的承诺」没有被判据承担（#5007① 的形态：承诺写在注释里，删一侧实现不会红）：\n"
        + "\n".join(f"  {p}" for p in problems)
    )


# ══════════════════════════════════════════════════════════════════════════════
# 判据 10：反空跑读数（「扫不到」不许长得像「通过」）
# ══════════════════════════════════════════════════════════════════════════════


def test_surfaces_are_complete_and_not_empty() -> None:
    """各判据面必须**取得到**且非空；本文件自己必须在面内（面取错了 ⇒ 一切判定都不可信）。"""
    surface = {str(p.relative_to(REPO)) for p in _surface_files()}
    assert SELF_REL in surface, f"本判据自身不在判据面内（{SELF_REL}）—— 面取错了"
    live = _path_gated_jobs()
    assert len(live) >= 5, f"只枚举到 {len(live)} 条路径门控门禁 ⇒ YAML 枚举口径疑似失效"
    scan = _scan_surface()
    assert len(scan["claims"]) >= 3, f"同源声明只扫到 {len(scan['claims'])} 条 ⇒ 扫描口径疑似失效"
    assert len(scan["bounds"]) >= 3, f"冻结集合只扫到 {len(scan['bounds'])} 条 ⇒ 扫描口径疑似失效"
    observed = sum(len(_observed_surface(str(g["auto_discover_root"])))
                   for g in _registry()["gates"] if g.get("auto_discover_root"))
    assert observed >= 4, f"自动发现只扫到 {observed} 条读取面 ⇒ AST 口径疑似失效"
    print(
        f"[燃尽锚点] 路径门控门禁={len(live)} / 登记={len(_gate_index())} / "
        f"同源声明={len(scan['claims'])} / 冻结集合={len(scan['bounds'])} / 自动发现面={observed}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# 红证（纯函数注入：喂**合成载荷**给判定函数；每条先自证 mutated != src）
# ══════════════════════════════════════════════════════════════════════════════


class TestRedProofs:
    """每条红证证明「注入生效 + 判据真红」（§23 G7）：注入未生效的「绿」不算证据。"""

    def test_deleting_a_blocking_key_is_detectable(self) -> None:
        runner = _load_runner()
        ec = _closeout()
        declared = tuple(runner._BLOCKING_VERDICT_KEYS)
        consumed = _consumed_blocking_keys(runner, ec)
        mutated = tuple(k for k in declared if k != "restore_failures")
        assert mutated != declared, "注入未生效（自证）：删一个键后与原文相同"
        assert set(mutated) != consumed, (
            "删掉 `restore_failures` 后判据仍判绿 ⇒ 判据没有判别力（#5007① 的注入式红证）"
        )

    def test_frozen_member_deletion_is_detectable(self) -> None:
        rel = "tests/unit_ci_workflows/test_operation_display_name_guard.py"
        members = _members_of((REPO / rel).read_text(encoding="utf-8"), "FACES", rel)
        mutated = tuple(m for m in members if "PieceworkTable.tsx" not in m)
        assert mutated != members, "注入未生效（自证）：删一个面后与原文相同"
        assert mutated != members and len(mutated) == len(members) - 1, "删一个面必须被逐项冻结判红"

    def test_lower_bound_only_would_pass_a_deleted_member(self) -> None:
        """反证「下界只防清空」：FACES 删一个面后 `len(...) >= 5` 之外的判据缺口。"""
        rel = "tests/unit_ci_workflows/test_operation_display_name_guard.py"
        source = (REPO / rel).read_text(encoding="utf-8")
        members = _members_of(source, "FACES", rel)
        mutated = tuple(m for m in members if "PieceworkTable.tsx" not in m)
        assert mutated != members, "注入未生效（自证）"
        bound = _scan_surface()["bounds"][(rel, "FACES")]["bound"]
        assert len(mutated) < bound, "删一个面后成员数仍 ≥ 下界 ⇒ 下界确实拦不住「删一项」（#5007② 的形态）"

    def test_claim_site_scanner_reads_the_synthetic_source(self) -> None:
        synthetic = (
            "#: 与另一侧的实现**同源**（这行是合成载荷）\n"
            "SYNTHETIC_KEYS = (\n"
            '    "alpha",\n'
            '    "beta",\n'
            ")\n"
        )
        tree = ast.parse(synthetic)
        lines = synthetic.splitlines()
        literals = _module_literals(tree)
        assert literals == [("SYNTHETIC_KEYS", 2)], f"扫描器没认出合成声明（{literals}）⇒ 判据失真"
        block = _comment_block_above(lines, 2)
        assert any(marker in block for marker in CLAIM_MARKERS), (
            f"扫描器没把注释块读成同源声明（{block!r}）⇒ 判据 9 会静默空跑"
        )

    def test_single_bound_scanner_reads_the_synthetic_assert(self) -> None:
        synthetic = (
            "SYNTHETIC_KEYS = (\n"
            '    "alpha",\n'
            '    "beta",\n'
            ")\n"
            "def test_x():\n"
            "    assert len(SYNTHETIC_KEYS) >= 2, '反空跑'\n"
        )
        tree = ast.parse(synthetic)
        literals = {name for name, _ln in _module_literals(tree)}
        assert literals == {"SYNTHETIC_KEYS"}, f"扫描器没认出合成声明（{literals}）"
        found = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Assert)
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Call)
        ]
        assert found, "扫描器没认出 `assert len(...) >= N` 形态 ⇒ 判据 8 会静默空跑"

    def test_predicate_gap_is_detectable(self) -> None:
        """把契约主体从谓词里删掉之后，覆盖判定必须为**假**（#4177 的注入式红证）。"""
        gate = _gate_index()[("ai-agent-tests.yml", "ai-agent-service-test")]
        target = "backend/admin-api/src/main"
        assert _trigger_covers(gate["trigger"], target), "现取谓词未覆盖契约主体 ⇒ 判据 4 现在就是红的"
        mutated = str(gate["trigger"]["predicate"]).replace("backend/admin-api/src/main/|", "")
        assert mutated != gate["trigger"]["predicate"], "注入未生效（自证）：谓词原文没被改到"
        assert not _trigger_covers({"kind": "step-detect-regex", "predicate": mutated}, target), (
            "删掉契约主体后覆盖判定仍为真 ⇒ 判据 4 没有判别力"
        )

    def test_empty_alternative_is_rejected_as_catch_all(self) -> None:
        """删一条分支却留下 `|` ⇒ 空分支 = **通配一切**（本条是判据 2 的判别力自证）。"""
        good = "^(backend/ai-agent-service/|backend/admin-api/src/main/|tests/)"
        bad = good.replace("backend/admin-api/src/main/", "")
        assert bad != good, "注入未生效（自证）：变形后与原文相同"
        assert _trigger_covers({"kind": "step-detect-regex", "predicate": bad}, "docs"), (
            f"空分支 `||` 形态（{bad!r}）本应**恒真**（连不在分支里的 `docs` 都命中）——"
            " 判据 4 会因此失去判别力，所以判据 2 必须把它判成通配一切"
        )
        assert _is_catch_all(bad), f"空分支未被识别成通配一切（{bad!r}）⇒ 这条门禁会静默放过「每个 PR 都跑」"
        assert not _is_catch_all(good), f"正常谓词被误判成通配（{good!r}）"
        assert _is_catch_all(".*"), "裸 `.*` 必须被判成通配一切"

    def test_glob_coverage_is_not_vacuous(self) -> None:
        paths = ["frontend/admin-web/**", "tests/e2e/**"]
        assert _globs_cover(paths, "frontend/admin-web")
        assert not _globs_cover(paths, "frontend/mini-app"), "`*` 不得跨越 `/`（宽松锚会遮蔽缺口）"