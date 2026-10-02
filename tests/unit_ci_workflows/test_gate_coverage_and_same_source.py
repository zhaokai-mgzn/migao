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
  以及**两种** job 内门控：① 步骤级 —— 「一步把 `NAME=true|false` 写进 `$GITHUB_OUTPUT`、另一步的 `if:`
  引用 `steps.<id>.outputs.`」；② **job 级**（issue #6051）—— 「`needs: <判定 job>` + `if:` 引用
  `needs.<判定 job>.outputs.<名>`，且该输出名确由判定 job 产出」；
  **不按文件名/步骤文案清单**枚举。
  ⚠️ 第 ② 种**必须**在面内：被 job 级 `if` 跳过的 job **连创建都不会** ⇒ 它的断言整段不跑，
  而登记册与所有判据都不会因此变红（#4177 的同族形态）。
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
import copy
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


def _emitters(job: dict, all_jobs: dict | None = None) -> dict[str, dict]:
    """把 `<名>=true|false` 写进 `$GITHUB_OUTPUT` 的步骤（`id` → 步骤名 / 输出名 / run 原文）。

    这是「**步骤级路径门控**」的结构签名：门控输出只有这两个取值，且写在 `$GITHUB_OUTPUT`。

    `all_jobs` 非空时**额外**收集「**job 级**门控」那一路（issue #6051）：
    别的 job 用 `jobs.<that>.outputs.<名>: ${{ steps.<本 job 某 id>.outputs.<名> }}`
    把本 job 的判定结果转出去（`needs.<that>.outputs.<名>` 型门控的**前置结构**）。
    不收这一路 ⇒ 判定 job（`detect`）与其消费者会被读成「没有门控」而**静默漏登记**。
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
    for jid, other in (all_jobs or {}).items():
        if not isinstance(other, dict):
            continue
        for name, expr in (other.get("outputs") or {}).items():
            m = re.fullmatch(r"\$\{\{\s*steps\.([A-Za-z0-9_-]+)\.outputs\.[A-Za-z0-9_-]+\s*\}\}", str(expr))
            if not m or m.group(1) not in out:
                continue
            entry = out[m.group(1)]
            entry["outputs"] = sorted({*entry["outputs"], str(name)})
            entry.setdefault("consumed_by", []).append(f"{jid}.outputs.{name}")
    return out


#: `needs.<job>.outputs.<名>` 形态（job 级 `if:` 门控的**结构签名**，issue #6051）。
NEEDS_OUTPUT_RE = re.compile(r"needs\.([A-Za-z0-9_-]+)\.outputs\.([A-Za-z0-9_-]+)")


def _job_level_gate(job: dict, workflow_jobs: dict) -> dict | None:
    """本 job 的 **job 级**面门控：`needs: <判定 job>` + `if: needs.<判定 job>.outputs.<名> == ...`。

    为什么必须读这一路（issue #6051）：job 级 `if` 与步骤级门控是**两种不同形态**，
    而「会被路径门控的 PR 门禁必须登记」这条不变式原先只认后者 ⇒ 新造的 job 级门控会**整条漏登记**
    （它的断言整段不跑，而登记册与所有判据都不会因此变红 —— #4177 的同族形态）。
    """
    cond = str(job.get("if") or "")
    if not cond:
        return None
    needs = job.get("needs")
    need_ids = [str(needs)] if isinstance(needs, str) else [str(n) for n in (needs or [])]
    for m in NEEDS_OUTPUT_RE.finditer(cond):
        producer, output = m.group(1), m.group(2)
        if producer not in need_ids:
            continue  # 只看**真依赖**的那个判定 job（`needs` 里没写 ⇒ 该表达式在 GitHub 上取空）
        emit = _emitters(workflow_jobs.get(producer) or {}, workflow_jobs)
        produced = {name for e in emit.values() for name in e["outputs"]}
        if output not in produced:
            continue  # 该输出名不由判定 job 产出 ⇒ 不是面门控（宁缺勿滥）
        return {
            "needs": producer,
            "output": output,
            "emit_step": next((e["step"] for e in emit.values() if output in e["outputs"]), None),
            "if": cond,
        }
    return None


def _path_gated_jobs() -> dict[tuple[str, str], dict]:
    """现取的「**会被路径门控**的 PR 门禁」：workflow 级 `paths` 过滤、步骤级门控输出，或 **job 级门控**。

    为什么是这三条：它们正是「**断言可能整段不跑而结论照旧**」的三种结构（#4177 的现场是第二条；
    第三条由 issue #6051 引入 —— job 级 `if` 跳过时该 check **连创建都不会**，连空跑的 log 都没有）。
    `if: failure()` / `if: github.event_name == ...` 这类**不看路径**的条件不算门控 —— 它们不改变射程。
    """
    found: dict[tuple[str, str], dict] = {}
    for name, doc in _workflow_docs().items():
        pr = _pr_config(doc)
        if pr is None:
            continue
        paths = list(pr.get("paths") or [])
        ignored = list(pr.get("paths-ignore") or [])
        all_jobs = doc.get("jobs") or {}
        for jid, job in all_jobs.items():
            if not isinstance(job, dict):
                continue
            emitters = _emitters(job, all_jobs)
            gated_steps: list[str] = []
            for step in job.get("steps") or []:
                if not isinstance(step, dict):
                    continue
                cond = str(step.get("if") or "")
                if any(f"steps.{sid}.outputs." in cond for sid in emitters):
                    gated_steps.append(str(step.get("name") or step.get("id")))
            job_gate = _job_level_gate(job, all_jobs)
            if not (paths or ignored or gated_steps or job_gate):
                continue
            found[(name, str(jid))] = {
                "workflow": name,
                "job": str(jid),
                "check_name": str(job.get("name") or jid),
                "paths": paths,
                "paths_ignore": ignored,
                "gated_steps": gated_steps,
                "emitters": emitters,
                "job_gate": job_gate,
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


def test_module_literals_include_single_element_collections() -> None:
    """判据（issue #5771）：**一元组**的「单一实现」声明必须进登记面。

    病根（`#5740` §3-5 的原始读数）：`_module_literals` 只收 `len(elts) >= 2` 的字面量集合
    ⇒ `X_FROZEN = ("only-one.py",)` 这类**一元组**既不进「注释声称同源」面、也不进「只设下界」面
    ⇒ 「只此一份实现」的声明在**元素只有 1 个时无人核**。
    """
    src = 'A_FROZEN = ("only-one.py",)\nB_FROZEN = ("a.py", "b.py")\nC_NOT_LITERAL = make("x")\n'
    got = {name for name, _ in _module_literals(ast.parse(src))}
    assert "A_FROZEN" in got, "一元组没进面（下界还是 2）—— #5740 §3-5 的缺口没修"
    assert "B_FROZEN" in got
    assert "C_NOT_LITERAL" not in got, "非字面量集合混进来了（面被放宽到不该收的东西）"


def test_module_literals_bound_is_one() -> None:
    """判据（fail-closed）：下界一旦被改回 2 ⇒ 红（否则本单修的缺口会静默复发）。"""
    text = (REPO / "tests/unit_ci_workflows" / "test_gate_coverage_and_same_source.py").read_text(encoding="utf-8")
    assert "len(value.elts) < 1" in text, "下界被改回 2 ⇒ 一元组声明又漏在面外（issue #5771）"


def _module_literals(tree: ast.Module) -> list[tuple[str, int]]:
    """模块级「字面量字符串集合」声明（符号名 + 行号）；成员级名字回指也算（`IMPLEMENTATIONS` 形态）。"""
    out: list[tuple[str, int]] = []
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and len(value.args) == 1:
            value = value.args[0]
        if not isinstance(value, (ast.Tuple, ast.List, ast.Set)) or len(value.elts) < 1:
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
        # job 级门控（issue #6051）：登记项必须**双向**与现取相符 —— 未登记即红、登记未兑现即红。
        # 两个方向都不可省：只查「没登记」（`job_gate is None`）会漏掉「登记了但现取没有」，
        # 而后者正是「门控被摘掉却留着盖章」的形态（登记册沦为**空承诺**）。
        want_gate = gate.get("job_gate")
        live_gate = info.get("job_gate")
        if bool(want_gate) != bool(live_gate):
            problems.append(
                f"{key[0]}::{key[1]}：job 级门控**单边缺失** —— 登记 {want_gate!r} / 现取 {live_gate!r}"
                "（新增 job 级门控必须登记；门控被摘掉则必须撤登记）"
            )
        elif want_gate and live_gate:
            for field in ("needs", "output", "emit_step", "if"):
                if str(want_gate.get(field)) != str(live_gate.get(field)):
                    problems.append(
                        f"{key[0]}::{key[1]}：job 级门控的 `{field}` 不符 —— 登记 {want_gate.get(field)!r}"
                        f" / 现取 {live_gate.get(field)!r}"
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


def test_stock_batch_type_is_wired_in_both_batch_registries() -> None:
    """第三个具名批量 `inventory_stock`（issue #5950）在三处**同源**清单里都在场。

    为什么单独立判据：两侧**一起漏**（工具加了白名单却忘了字段配对/别名）时，上一条
    「两侧相等」判据照样绿，而该批类型会在工具里 KeyError / 被静默判成错字段。
    三处分别覆盖：工具白名单（`BATCH_TYPES`）、字段词（`stock`）、用例侧写方归类。
    **删掉任一处 ⇒ 本条红并具名报出**（= 摘掉接线的注入点）。
    """
    tool_rel = "backend/ai-agent-service/app/tools/product_batch_update.py"
    src = (REPO / tool_rel).read_text(encoding="utf-8")
    assert "inventory_stock" in _members_of(src, "BATCH_TYPES", tool_rel), (
        f"{tool_rel} 的 `BATCH_TYPES` 里没有 `inventory_stock` ⇒ 服务端批量类型在 Agent 侧不可达")
    assert '"stock"' in src or "'stock'" in src, (
        f"{tool_rel} 里找不到库存字段词 `stock`（字段配对表 / 别名表）⇒ #5950 的条目拿不到字段")
    guard_rel = "tests/unit_ci_workflows/test_shared_fixture_write_restore.py"
    guard_src = (REPO / guard_rel).read_text(encoding="utf-8")
    assert '("product_batch_update", "execute", "inventory_stock"): "stock"' in guard_src, (
        f"{guard_rel} 没有把 `inventory_stock` 的写方归类到 `stock` ⇒ 判据 ② 对它无对象（静默失效）")


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


# ══════════════════════════════════════════════════════════════════════════════
# 四、job 级面门控（issue #6051）：非 required 重腿整层跳过的形态与「未跑」可见性
# ══════════════════════════════════════════════════════════════════════════════

#: issue #6051 的**具名实例**：`<workflow 文件>::<job id>` → 该腿的 check_name。
#: 逐条具名（不是「至少有 4 条」那种计数式）：少一条 / 换一条都判红。
JOB_GATED_LEGS_FROZEN: dict[str, str] = {
    "bmini-app.yml::build": "bmini-app build (h5 + weapp)",
    "bmini-app.yml::tabbar-geometry": "bmini H5 tabBar geometry (e2e)",
    "mini-app.yml::xiaobu-h5-visual": "xiaobu H5 visual regression",
    "pr-check.yml::e2e-quality-gate": "E2E quality gate",
}

#: 面门控的判定 job（每条 workflow 一个 = 面口径的**单一来源**）。
FACE_DETECT_JOBS: dict[str, str] = {
    "bmini-app.yml": "detect",
    "mini-app.yml": "detect",
    "pr-check.yml": "detect",
}

#: 「未跑」的机器可读标记 + 必带口径（铁律 2：跳过的腿不许静默绿）。
NOT_RUN_MARKER = "⏭️"
NOT_RUN_CLAUSE = "未跑"
NOT_RUN_NOT_PASS = "这不是「通过」"


def _detect_script(workflow: str, detect_job: str) -> str:
    """判定 job 里**真正产出 `run` 输出**的那个步骤的 `run:` 原文。"""
    job = (_workflow_docs()[workflow].get("jobs") or {}).get(detect_job)
    assert isinstance(job, dict), f"{workflow} 里没有判定 job `{detect_job}`（面口径的单一来源没了）"
    emit = _emitters(job, _workflow_docs()[workflow].get("jobs") or {})
    outs = {name for e in emit.values() for name in e["outputs"]}
    assert "run" in outs, (
        f"{workflow}::{detect_job} 没有产出 `run` 输出 ⇒ job 级门控的 `needs.<job>.outputs.run` 恒为空"
        "（腿会**永远不跑**，而不是「按面跑」）"
    )
    return next(e["run"] for e in emit.values() if "run" in e["outputs"])


#: 面判定三种**等价**载体的取法（见判据 ④ 的 docstring）：
#:   · 锚定正则的交替 —— 腿内联 / 旧形态 / **登记册的 `trigger.predicate`**：`^(frontend/bmini-app/|tests/)`
#:   · `case` 路径模式 —— 判定 job 现形态：`case "$f" in tests) …` / `case "$rest_gh" in workflows/x) …`
_FACE_REGEX_RE = re.compile(r"(\^\([^']*?\))")
_FACE_CASE_RE = re.compile(r'case\s+"\$(?:f|rest|head|file|rest_gh|rest_fe)"\s+in\s+([^\s)]+)\)')


def _face_prefixes(script: str) -> set[str]:
    """把一份面判定归一到**路径面集合**（两种等价书写形态 + 登记册 predicate 都认）。

    `^(a/x/|b/|\.github/)` → {"a/x","b",".github"}；`case "$f" in a)` / `case "$rest_fe" in a/x/*)`
    → "a" / "a/x"。取不到 ⇒ **空集**（调用点据此 fail-closed 判红）。

    比的是**语义面**（扫哪些路径下的改动），不是书写形态 —— 同一份面既可写成锚定正则的交替，
    也可写成 `case` 路径模式（后者用于绕开管道库存判据把**引号内裸竖线**计成管道的误报，
    见 `.github/workflows/*.yml` 的 detect 注释）。
    """
    out: set[str] = set()
    for m in _FACE_REGEX_RE.finditer(script or ""):
        for part in m.group(1)[2:-1].split("|"):          # 去掉 `^(` 与 `)`
            part = part.strip().rstrip("/").replace("\\.", ".").rstrip("$")
            if part and "*" not in part and "\\" not in part:
                out.add(part)
    for m in _FACE_CASE_RE.finditer(script or ""):
        raw = m.group(1).strip()
        if "*" in raw:
            continue                                       # 兜底分支（`*)`）不是「面」
        part = raw.rstrip("/").replace("\\.", ".")
        if part.startswith("workflows/"):
            part = ".github/" + part                       # `rest_gh` 取自 `.github/*`
        if part:
            out.add(part)
    return out


def _covers(face: set[str], targets: set[str]) -> bool:
    """面 `face` 是否**覆盖** `targets` 里的每一条路径（**并集**语义：任一面命中即可）。

    `x` 覆盖 `x/y`；反向**不**成立。方向很重要：判定 job 的面**偏粗可接受**（代价只是腿被拉起后
    发现无改动，不是正确性问题），**偏细则静默少覆盖** ⇒ 只有「覆盖不足」才判红。
    ⚠️ 不是「每个 face 元素都要匹配每个 target」——那是全交叉，方向错了（本包实测踩过）。
    """
    return all(any(t == f or t.startswith(f + "/") for f in face) for t in targets)


#: 判定面必须覆盖的**路径空间**（判定 job 是这些前缀下的共用门）。
_FACE_PROBE_ROOTS = ("frontend", "tests", ".github", "backend", "docs", "scripts", "mobile")


def _bash_realised_face(script: str) -> set[str]:
    """**真跑一次 bash** 求出该判定脚本实际命中的**探针路径**（不靠解析、不靠猜）。

    做法：把 `git diff --name-only origin/main...HEAD` 换成 `cat "$STUB"`，在**同一个 bash 进程**里
    对每个探针各跑一遍判定体，读 `$GITHUB_OUTPUT` 的 `run`。探针 = `_FACE_PROBE_ROOTS` 每根 +
    `/<根>/__probe__`，覆盖「根目录本身」与「根下任意文件」。
    ⚠️ 必须**一次跑完**：逐探针各起一个 bash 会让本判据慢到分钟级（本包实测超时），
    而它要跑在 required 的 `ci workflow helper unit tests` 里。
    """
    import os as _os
    import subprocess as _sp
    import tempfile as _tf

    probes = list(_FACE_PROBE_ROOTS) + [r + "/__probe__" for r in _FACE_PROBE_ROOTS]
    marker = "git diff --name-only origin/main...HEAD"
    body = script.replace(marker, 'cat "$STUB"')
    # ⛔ 必须剔除 `git fetch origin main --quiet`：探针循环会把判定体跑 14 次 ⇒ 14 次**真联网**，
    #    本机实测直接把本判据挂到超时（而它要跑在 required 的 `ci workflow helper unit tests` 里）。
    body = "\n".join(l for l in body.splitlines() if "git fetch origin main" not in l)
    assert body != script, "判定脚本里找不到 diff 取法 ⇒ 本判据取不到真值（前提失效，需同步修订）"
    sh = ('GITHUB_EVENT_NAME=pull_request\n'
          'STUB=$(mktemp)\n'
          "printf '%s\\n' " + " ".join(f'"{p}"' for p in probes) + " > \"$STUB\"\n"
          '_run_one() {\n'
          '  P="$1"\n'
          '  printf \'%s\' "$P" > "$STUB"\n'
          '  GITHUB_OUTPUT=$(mktemp)\n'
          '  { ' + body + '\n  } >/dev/null 2>&1\n'
          '  if grep -q "^run=true" "$GITHUB_OUTPUT"; then printf "HIT:%s\\n" "$P"; fi\n'
          '}\n'
          'for p in ' + " ".join(f'"{p}"' for p in probes) + '; do _run_one "$p"; done\n')
    with _tf.NamedTemporaryFile("w", suffix=".sh", delete=False) as fh:
        fh.write(sh)
        fn = fh.name
    try:
        out = _sp.run(["/bin/bash", fn], capture_output=True, text=True).stdout
    finally:
        _os.unlink(fn)
    return {line[4:] for line in out.splitlines() if line.startswith("HIT:")}


def _unannounced_legs(script: str, workflow: str) -> list[str]:
    """`<workflow>` 里被 job 级门控的腿中，**没有**在 `detect` 脚本 else（未命中面）分支里公告的。

    只看该 workflow 自己的腿（别的 workflow 的腿不由这份脚本承担）；只看 else 分支
    （命中面时打印的是「✅ 跑」，不承担公告职责 —— 拿它顶替 = 假绿）。
    公告行的形态 = 「`⏭️ <腿名> 未跑：…（这不是「通过」）」」；三要素缺一即算未公告。
    ⚠️ 匹配**不锚定行首**：YAML 块标量里行首是 `echo "`，锚定行首会让判据永远判红（假红）。
    """
    body = script.rsplit("else", 1)[1] if "else" in script else ""
    announced = [
        line
        for line in body.splitlines()
        if f"{NOT_RUN_MARKER} " in line and NOT_RUN_CLAUSE in line and NOT_RUN_NOT_PASS in line
    ]
    return [
        f"{key}（{name}）"
        for key, name in JOB_GATED_LEGS_FROZEN.items()
        if key.startswith(f"{workflow}::")
        and not any(f"{NOT_RUN_MARKER} {name} {NOT_RUN_CLAUSE}" in line for line in announced)
    ]


#: 显式处置「上游被按面跳过」的守卫原子（`always()` 是仓内既有定式：
#: 默认 `if` 等价于 `success()`，而 `success()` 要求**每个** need 都成功 ⇒ skipped 不算成功）。
SKIP_PROOF_TOKENS = ("always()", "!cancelled()")
#: 显式读**本 job 自己某个 need** 的结果（`needs.<id>.result`）也算已处置跳过这一态。
NEEDS_REF_RE = re.compile(r"needs\.([A-Za-z0-9_-]+)\.")


def _unsafe_downstream_skips(skip_target: str, gate: dict, jobs: dict) -> list[str]:
    """「**依赖被 job 级门控的那条腿**（`skip_target`）、却会把它的跳过当成没问题」的下游 job（issue #6051）。

    病（一类）：被 job 级 `if` 跳过的 job 其 `needs` 未满足 ⇒ **下游 job 默认一并跳过**
    （默认 `if` 等价于 `success()`，而 `success()` 要求**每个** need 都成功 ⇒ skipped 不算成功）。
    于是一个「依赖所有前置 job」的收口 job（清僵尸标签 / 报账 / 收口）在**上游按面跳过时静默不跑** ——
    而那正是它最需要跑的情形（它要判的恰恰是「这一轮到底绿不绿」）。与「未跑被读成通过」同族。

    ⚠️ `skip_target` 是**真正被按面跳过的那条腿**（= 带 job 级门控的 job 自己），
    不是它 `needs` 的判定 job：`needs: detect` 只会让 detect **先跑**，跳过的是带门控的这条腿。
    """
    problems: list[str] = []
    for cid, job in sorted(jobs.items()):
        if not isinstance(job, dict) or cid == skip_target:
            continue
        needs = job.get("needs")
        need_ids = [needs] if isinstance(needs, str) else [str(n) for n in (needs or [])]
        if skip_target not in need_ids:
            continue
        cond = str(job.get("if") or "").strip()
        name = f"{cid}（{job.get('name') or cid}）"
        if any(tok in cond for tok in SKIP_PROOF_TOKENS):
            continue  # `always()` / `!cancelled()` ⇒ 上游被跳过也照跑
        if any(ref in need_ids for ref in NEEDS_REF_RE.findall(cond)):
            continue  # 显式读**自己的** need 结果（`needs.<id>.result`）⇒ 已处置跳过这一态
        if not cond:
            problems.append(
                f"{name} 没有 `if:` ⇒ 默认 `success()` 不穿透 skipped，`{skip_target}` 被按面跳过时它静默不跑"
            )
        else:
            problems.append(f"{name} 的 `if: {cond}` 只要求上游成功 ⇒ 同款静默不跑")
    return problems


def test_downstream_of_a_job_gated_leg_does_not_silently_skip() -> None:
    """⑤ **反向判据**：依赖「job 级门控腿」的下游 job，不得因上游按面跳过而静默不跑。

    这是本包**自己造成的破坏面**（issue #6051）：加 job 级门控后，凡 `needs:` 那条腿的下游 job
    都会跟着被跳过 —— `pr-check.yml` 的 `label-needs-changes` / `clear-needs-changes`
    （原本 `needs: [..., e2e-quality-gate]`）就会在**非 e2e 面的 PR** 上静默不跑
    ⇒ `review/needs-changes` 僵尸标签永不脱落，而**没有任何检查会变红**。
    """
    live = _path_gated_jobs()
    checked = 0
    problems: list[str] = []
    for (wf, jid), info in sorted(live.items()):
        gate = info.get("job_gate")
        if not gate:
            continue
        checked += 1
        for p in _unsafe_downstream_skips(jid, gate, _workflow_docs()[wf].get("jobs") or {}):
            problems.append(f"{wf}::{jid} 被按面跳过会带倒下游 —— {p}")
    print(f"扫到 job 级门控 {checked} 条；下游静默跳过={len(problems)} 条")
    assert checked > 0, "一条 job 级门控都没扫到 ⇒ 本判据静默空跑成绿"
    assert not problems, (
        "「上游 job 级跳过 ⇒ 下游静默不跑」—— 这正是「未跑被读成没问题」的同族形态"
        "（issue #6051 的连带破坏面）：\n"
        + "\n".join(f"  {p}" for p in problems)
        + "\n修法：给下游 job 的 `if:` 补 `always()`（仓内既有定式，见 pr-check.yml 的 "
        "`label-needs-changes`），或显式读 `needs.<上游>.result` 处置跳过这一态。"
    )

    # ── 判别力自证（注入式，§28.1 出口 ①）：把下游的 `always()` 拿掉 ⇒ 必须当场红 ──
    wf, jid = "pr-check.yml", "e2e-quality-gate"
    gate = live[(wf, jid)]["job_gate"]
    jobs = _workflow_docs()[wf]["jobs"]
    downstream = [
        cid
        for cid, job in sorted(jobs.items())
        if isinstance(job, dict)
        and jid in ([job["needs"]] if isinstance(job.get("needs"), str) else list(job.get("needs") or []))
    ]
    assert downstream, f"注入对照缺失：{jid} 现取没有下游 job（本自证会失真）"
    assert not _unsafe_downstream_skips(jid, gate, jobs), "未注入却判红 ⇒ 假红（判据被自己的文案喂红）"
    mutated = copy.deepcopy(jobs)
    mutated[downstream[0]]["if"] = "github.event_name == 'pull_request'"
    caught = _unsafe_downstream_skips(jid, gate, mutated)
    assert caught, f"把 `{downstream[0]}` 的 `always()` 拿掉后仍判绿 ⇒ 判据 ⑤ 没有判别力（空断言）"
    # 反向对照 ②：连 `if:` 一起删掉（默认 `success()` 形态）也必须判红
    del mutated[downstream[0]]["if"]
    assert _unsafe_downstream_skips(jid, gate, mutated), "删掉整个 `if:` 后仍判绿 ⇒ 「没写 if」这一形态漏判"
    print(f"判别力自证：拿掉 `{downstream[0]}` 的 always() ⇒ 判红 ✅；连 if 一起删 ⇒ 判红 ✅；未注入 ⇒ 不报 ✅")


class TestJobLevelFaceGates:
    """issue #6051：4 条非 required 重腿的 job 级面门控（逐条具名 + 反向 + 可见性 + 单一来源）。"""

    def test_every_named_leg_has_a_job_level_face_gate(self) -> None:
        """① 这 4 条腿**各自**都有 job 级面门控（逐条具名：少一条 / 换一条都红）。"""
        live = _path_gated_jobs()
        missing: list[str] = []
        hit = 0
        for key, check_name in JOB_GATED_LEGS_FROZEN.items():
            wf, jid = key.split("::", 1)
            info = live.get((wf, jid))
            if info is None:
                missing.append(f"{key}：已不是「会被路径门控的 PR 门禁」（门控被摘掉 / job 改名 / workflow 改了 on）")
                continue
            if info["check_name"] != check_name:
                missing.append(f"{key}：check_name 变了 —— 现取 {info['check_name']!r} / 冻结 {check_name!r}")
            gate = info.get("job_gate")
            if not gate:
                missing.append(f"{key}：**没有 job 级门控**（只有步骤级 ⇒ runner 仍空转，本单要治的就是它）")
                continue
            want = FACE_DETECT_JOBS[wf]
            if gate["needs"] != want:
                missing.append(f"{key}：门控来源是 `{gate['needs']}`，面口径应来自 `{want}`（单一来源）")
                continue
            hit += 1
        print(f"job 级面门控现取={hit} 条 / 冻结 {len(JOB_GATED_LEGS_FROZEN)} 条")
        assert not missing, (
            "非 required 重腿的 job 级面门控不完整（它会让 runner 继续空转，或让面口径不再是单一来源）：\n"
            + "\n".join(f"  {m}" for m in missing)
            + f"\n复算：python3 -m pytest {SELF_REL} -q -s"
        )

    def test_required_jobs_never_carry_a_job_level_gate(self) -> None:
        """② **反向判据**：required 的 job 不得带 job 级面门控（防止有人顺手加）。"""
        req_path = UNIT_CI_DIR / "required_status_snapshot.json"
        assert req_path.exists(), f"缺 required 集合快照：{req_path.relative_to(REPO)}（没有它本条会空跑成绿）"
        required = {str(c) for c in (json.loads(req_path.read_text(encoding="utf-8")).get("contexts") or [])}
        assert required, "required 集合取空 ⇒ 本判据恒真（空跑成绿）"
        offenders: list[str] = []
        for (wf, jid), info in sorted(_path_gated_jobs().items()):
            if info.get("job_gate") and info["check_name"] in required:
                offenders.append(
                    f"{wf}::{jid}（{info['check_name']}）带 job 级门控 "
                    f"`needs: {info['job_gate']['needs']}` + `if: {info['job_gate']['if']}`"
                )
        print(f"required 名={len(required)} 条；其中带 job 级门控的={len(offenders)} 条")
        assert not offenders, (
            "**required 检查被 job 级 `if` 门控** —— GitHub 对**被 job 级 `if` 跳过**的 job **不上报**"
            "该 context（只有 job 创建了才上报），而分支保护只等「上报过的」那些 ⇒ 不命中该面的 PR 上\n"
            "该检查**永不到来** ⇒ PR 永久 `BLOCKED`（`Expected — waiting for status to be reported`），"
            "而**没有任何检查会变红**（#5101 / #4786 的形态）：\n"
            + "\n".join(f"  {o}" for o in offenders)
            + "\n修法：① required 腿改用**步骤级**门控（job 保持创建、结论照常上报，口径见"
            " pr-check.yml 的 `Detect admin-web changes` 一族）；② 或从分支保护里撤掉该 required。"
            " 顺序不可换：**先改门控、再改分支保护**。"
        )

    def test_skipped_legs_are_announced_as_not_run(self) -> None:
        """③ 跳过路径**必然**打印「未跑」：每条具名腿都必须在判定 job 的 else 分支里被点到。"""
        unannounced: dict[str, list[str]] = {}
        for wf, detect_job in FACE_DETECT_JOBS.items():
            script = _detect_script(wf, detect_job)
            legs = {k: v for k, v in JOB_GATED_LEGS_FROZEN.items() if k.startswith(f"{wf}::")}
            assert legs, f"{wf} 在冻结清单里没有任何 job 级门控腿 ⇒ 本判据对它空跑"
            missing = _unannounced_legs(script, wf)
            if missing:
                unannounced[wf] = missing
        print(f"判定 job 现取={sorted(set(FACE_DETECT_JOBS.values()))}；"
              f"公告缺口={sum(len(v) for v in unannounced.values())} 条")
        assert not unannounced, (
            "被面门控跳过的腿**没有在判定 job 的 else（未命中面）分支里被具名公告** —— 那就是静默绿"
            "（铁律 2：跳过的腿必须显式打印「未跑」，且写明这不是「通过」）：\n"
            + "\n".join(f"  {wf}: {', '.join(v)}" for wf, v in unannounced.items())
        )

    def test_announcement_checker_has_discriminating_power(self) -> None:
        """③ 的**注入式红证**：把公告行删掉 / 换成中性措辞，判定必须**当场红**。"""
        wf = "bmini-app.yml"
        script = _detect_script(wf, FACE_DETECT_JOBS[wf])
        assert not _unannounced_legs(script, wf), "现取语料本应全部已公告 ⇒ 下面的注入无从对照（自证失败）"
        for label, mutated in (
            ("公告行退化成中性措辞（拿掉「⏭️ … 未跑」）", script.replace(f"{NOT_RUN_MARKER} bmini-app build (h5 + weapp) {NOT_RUN_CLAUSE}", "跳过")),
            ("只留中性措辞（去掉「这不是「通过」」）", script.replace(NOT_RUN_NOT_PASS, "")),
            ("把 else 分支整段删掉", script.rsplit("else", 1)[0]),
        ):
            assert mutated != script, f"注入未生效（自证）：{label} 没有改到语料"
            caught = _unannounced_legs(mutated, wf)
            assert caught, f"注入「{label}」后判定仍为绿 ⇒ 判据 ③ 没有判别力（空断言）"
        print(f"判别力自证：3 种坏形态各自被判红 ✅（现取语料 {len(script)} 字符）")

    def test_face_criterion_has_a_single_source_per_workflow(self) -> None:
        """④ 面口径**单一来源**：**真跑判定脚本**，其实际命中的面必须覆盖**登记册声明的面**。

        （不要求整个 workflow 只有一份面 —— `pr-check.yml` 的 `admin-api-test` /
        `admin-web-test` 各有自己的面，那是另一族门禁；本条只裁**同族**：job 级门控这一族。）

        为什么**真跑 bash** 而不是比对字符串（issue #6051 实测教训）：同一份面有三种等价载体 ——
        锚定正则的交替 `^(a/|b/)`（腿内联 + 登记册 `trigger.predicate`）、`case` 路径模式（判定 job 现形态，
        用于绕开管道库存判据把**引号内裸竖线**计成管道的误报）。按字面比对会把等价写法判成「第二份规则」⇒ 假红；
        而**验字符串是推不出行为**的（本包实测：正则字样正确、但 bash 逻辑漏掉了 `frontend/admin-web` 这一支）。

        判据规则（**覆盖不足判红，偏粗只记录**）：
          · 覆盖不足 = 声明面里的改动不再触发腿 = **静默少覆盖** ⇒ 判红；
          · 偏粗 = 判定 job 是这一族腿的**共用**门，按路径前缀取共用前缀必然可能比某腿声明面粗 —— 代价只是
            腿被拉起来后发现无改动，**不是正确性问题** ⇒ 记为读数（可复核），不判红。
        """
        problems: list[str] = []
        over: dict[str, list[str]] = {}
        reg = _gate_index()
        for wf, detect_job in FACE_DETECT_JOBS.items():
            legs = [k for k in JOB_GATED_LEGS_FROZEN if k.split("::", 1)[0] == wf]
            assert legs, f"{wf} 有判定 job `{detect_job}` 却没有被门控的腿 —— 面门控成了空转"
            declared: set[str] = set()
            for key in legs:
                _, jid = key.split("::", 1)
                predicate = ((reg.get((wf, jid)) or {}).get("trigger") or {}).get("predicate") or ""
                faces = {f for f in (_face_prefixes(predicate) or set())}
                if not faces:
                    problems.append(
                        f"{key}：登记册里 `trigger.predicate` 取不到面（{predicate!r}）⇒ "
                        "**声明的单一来源没了**（fail-closed：没有声明就没有可比对象）"
                    )
                    continue
                declared |= faces
                # ① 腿自己的步骤必须按**声明的那一份**面跑（同族的第二份规则）
                job = (_workflow_docs()[wf].get("jobs") or {}).get(jid) or {}
                for step in job.get("steps") or []:
                    if not isinstance(step, dict):
                        continue
                    inline = _face_prefixes(str(step.get("run") or ""))
                    if inline and inline != faces:
                        problems.append(
                            f"{key} 的步骤 `{step.get('name')}` 内联的面 {sorted(inline)}"
                            f" ≠ 登记册声明的面 {sorted(faces)} —— 两份面规则漂移，而没有任何东西会变红"
                        )
            # ② **真跑**判定脚本：实际命中的根必须覆盖每一条声明面
            realised = _bash_realised_face(_detect_script(wf, detect_job))
            roots = {p for p in realised if "/" not in p}
            missing = sorted(d for d in declared
                             if not any(d == r or d.startswith(r + "/") for r in roots))
            if missing:
                problems.append(
                    f"{wf}::{detect_job} 的判定脚本**实际命中** {sorted(roots)}，**覆盖不足**："
                    f"声明面 {missing} 里的改动不会触发判定（**静默少覆盖**）—— 真跑读数 = {sorted(realised)}"
                )
            extra = sorted(r for r in roots
                           if not any(d == r or d.startswith(d + "/") for d in declared))
            if extra:
                over[f"{wf}::{detect_job}"] = extra
        assert not problems, (
            "面口径出现**第二份**规则（同族门禁内）：\n" + "\n".join(f"  {p}" for p in problems)
        )
        print(f"面口径单一来源：{len(JOB_GATED_LEGS_FROZEN)} 条腿的声明面都被判定脚本**真跑命中** ✅"
              f"（判定面**偏粗**（可接受、非正确性问题）现取 = {over or '无'}）")

    def test_face_criterion_probe_has_discriminating_power(self) -> None:
        """④ 的**判别力自证**：真跑探针必须能判出「漏一支」的坏形态（本包实测踩过的那个 bug）。"""
        script = _detect_script("pr-check.yml", FACE_DETECT_JOBS["pr-check.yml"])
        realised = _bash_realised_face(script)
        assert ".github" in realised and "tests" in realised, f"探针取不到真值：{sorted(realised)}"
        # 注入式红证①：把 frontend 那一支整段删掉 ⇒ 探针必须立刻不再命中 frontend
        broken = "\n".join(l for l in script.splitlines()
                            if 'case "$f" in frontend' not in l)
        assert 'case "$f" in frontend/*)' not in broken, "注入没生效（删不到 frontend 支）"
        broken_realised = _bash_realised_face(broken)
        assert "frontend" not in broken_realised, (
            f"删掉 frontend 支后探针仍命中 ⇒ 判据 ④ 没有判别力（{sorted(broken_realised)}）"
        )
        # 注入式红证②：把判定改成恒 false ⇒ 一条都不命中
        always_off = script.replace('echo "run=true"', 'echo "run=false"')
        assert _bash_realised_face(always_off) == set(), "恒 false 的判定仍被判命中 ⇒ 探针坏了"
        print("判别力自证：删掉 frontend 支 ⇒ 真跑探针立刻不再命中 ✅；恒 false ⇒ 零命中 ✅")

    def test_announcement_checker_has_discriminating_power(self) -> None:
        """③ 的**注入式红证**：把公告行删掉 / 换成中性措辞，判定必须**当场红**。"""
        wf = "bmini-app.yml"
        script = _detect_script(wf, FACE_DETECT_JOBS[wf])
        assert not _unannounced_legs(script, wf), "现取语料本应全部已公告 ⇒ 下面的注入无从对照（自证失败）"
        for label, mutated in (
            ("公告行退化成中性措辞（拿掉「⏭️ … 未跑」）", script.replace(f"{NOT_RUN_MARKER} bmini-app build (h5 + weapp) {NOT_RUN_CLAUSE}", "跳过")),
            ("只留中性措辞（去掉「这不是「通过」」）", script.replace(NOT_RUN_NOT_PASS, "")),
            ("把 else 分支整段删掉", script.rsplit("else", 1)[0]),
        ):
            assert mutated != script, f"注入未生效（自证）：{label} 没有改到语料"
            caught = _unannounced_legs(mutated, wf)
            assert caught, f"注入「{label}」后判定仍为绿 ⇒ 判据 ③ 没有判别力（空断言）"
        print(f"判别力自证：3 种坏形态各自被判红 ✅（现取语料 {len(script)} 字符）")
