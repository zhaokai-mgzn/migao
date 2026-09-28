# case_ids: MC-024
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 `.github/cases/misc.yml`
#   的 CI 域用例；MC-024 = 本单（issue #5687）新增的 CI 分流语义。）
"""**类级 meta-guard**：仓内**任何**「以**重跑结果**为唯一依据来**消红 / 降级**」的路径
都必须出现在一张**具名登记表**里 —— **未登记即红**；台账**只许缩短**（issue #5687 判据④）。

## 病灶（本会话真实发生，不是理论风险）

```
① 一次失败（真因：**窗口型确定性缺陷** —— 实测：UTC 16:00–24:00 每天必红）
② 重跑（恰好落到窗口外）⇒ 通过
③ `flaky_ledger.decide`:  if rerun_result == "success" and "flaky" in kinds:
                              action, kind = "mark_flaky", "flaky"
   ⇒ 判成 flaky、PR 的红被消掉（workflow 侧还 `--disable-auto` 解了人工闸）
④ 缺陷仍在 main 上 ⇒ 明天同一时段对所有人**再红一次** ⇒ 回到 ①
```

唯一的信号（`Flaky Ledger Reconcile` 判红）**自己逐字声明「判红不等于阻塞合并」**，且实测
**不在** `branches/main/protection` 的 required 集合里 ⇒ **可以无限循环**。

⇒ 本文件锁**两件不同的事**（缺任何一件，这个类都还会再进来一次）：

| # | 判据 | 红证形态 |
|---|---|---|
| 1 | **未登记即红**：`flaky_ledger.py` 里**每一个**「以重跑结果为唯一依据消红/降级」的函数必须具名 | 注入一个「读 `rerun_result == "success"` 就产出 `mark_flaky`」的新函数 ⇒ 必红 |
| 2 | **台账只许缩短**：登记的名字必须**仍然真的**在判据链里（改名 / 搬走 / 删掉 ⇒ 红） | 改掉一个真函数名 ⇒ 必红 |
| 3 | **登记项必须齐字段**（在哪 + 为什么在链里 + 为什么不能删 + 谁负责，缺一即红） | 清空任一字段 ⇒ 必红 |
| 4 | **结论与依据不许自相矛盾**：条目里 `rerun_bucket_verdict`（取数面）与 `kind`（结论）反向 ⇒ 红 | 跨桶却判 `flaky`、同桶却判新类 ⇒ 各一条必红 |
| 5 | **workflow 侧动作与判据一致**：跨桶疑似**不得**打 `flaky/rerun-green`、且必须落跟踪单 | 让它打上 flaky 标签 ⇒ 必红 |

## 🔴 明确的边界（**不要把本守卫读成覆盖面更大的东西**）

- ❌ **非时间型的环境差异不在面内**：**随机端口** / **并发时序** / **网络抖动** / 依赖源抖动
  —— 它们的「重跑通过」**仍然**判 `flaky`（本单只处理**时间桶**这一条**可静态判定**的维度）。
  这些形态的出路是 #5687 的 ②（**显式登记**）而不是自动识别：真要治它们，得先有一个
  **可静态判定**的维度（否则判据只会变成噪音源）。
- ❌ **同一 UTC 小时、同一 UTC 日、同一 +08 业务日之内的跨时段**（如半小时级窗口）不在面内
  —— 桶的粒度是「UTC 日期 × +08 业务日 × UTC 小时」，比小时更窄的窗口判不出来（照实登记）。
- ❌ **相隔很久但没跨桶** 这一说法本身不成立 ⇒ 本节**不能**被读成「跨桶 = 相隔很久」：
  桶的粒度为小时 ⇒「没跨桶」意味着两次尝试落在**同一小时**内（最长相隔 < 1 小时）。
  反过来，**跨桶**才是降级的唯一理由 —— 而它只是「需人看」，**不是**「相隔很久」的代理指标。
- ❌ **`rerun_result` 之外的消红路径不在面内**：本守卫的语料是 `flaky_ledger.py` 里
  「读 `rerun_result` / 产出 `mark_*` 动作」的那些函数 —— 别的机制（如
  `deploy-reconcile.yml` 的断路器、`post-merge-verify.yml` 的水位）用**别的事实**消红，
  **不**在本表里，本守卫也**不**声称覆盖它们。
- ❌ **本守卫不声称「时间桶判据本身正确」**：它保证的是「消红路径都被点名 + 结论与依据不矛盾
  + workflow 动作与判据一致」。判据本身的**行为**由
  `tests/unit_ci_workflows/test_rerun_to_clear_paths.py::TestCarryingFacts`（三态/三层/归因面）
  与既有 `tests/unit_ci_workflows/test_flaky_ledger_kind_semantics.py`（含本会话真实读数
  `36280962072` 的复算）钉住。
"""
import ast
import importlib.util
import json
import re
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / ".github" / "scripts"
LEDGER_SCRIPT = SCRIPTS / "flaky_ledger.py"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "flaky-triage.yml"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FL = _load(LEDGER_SCRIPT, "migao_flaky_ledger_rerun_paths")
REAL_SOURCE = LEDGER_SCRIPT.read_text(encoding="utf-8")
REAL_WORKFLOW = WORKFLOW_PATH.read_text(encoding="utf-8")
REAL_LEDGER = json.loads((REPO_ROOT / ".github" / "flaky-ledger.json").read_text(encoding="utf-8"))

#: 具名登记要指的形参名（**入参就是重跑结果**那一类）
RERUN_RESULT_PARAM = "rerun_result"
#: 「**动作词**」= 决定「放不放红」的**动作名**（不是 `flaky` / `success` 这类**状态值**）。
#: 见 `rerun_to_clear_paths` 的 docstring：两次收窄的实测都写在那边。
ACTION_WORDS = ("mark_flaky", "mark_suspect")


@dataclass(frozen=True)
class RerunToClearPath:
    """登记四件套：**在哪** + **为什么它在判据链里** + **为什么不能删** + **谁负责**。缺一即红。"""

    where: str
    reason: str
    why_not_removable: str
    owner: str


#: 🔴 **只许缩短的登记表**（issue #5687 判据④）：每一个**以重跑结果为唯一依据来消红/降级**的函数。
#: 两条机械约束（都在 `problems_rerun_to_clear_paths` 里判）：
#:   ① 台账里**每一条**都必须仍然真的在 `flaky_ledger.py` 的判据链里（改名 / 搬走 / 删掉 ⇒ 红）；
#:   ② 语料里发现的**每一个**这样的函数都必须在这里具名（**未登记 ⇒ 红**）。
#: 于是「新增一条按重跑结果消红的路径」与「摘掉一条却不销账」都是**可红的动作**。
#:
#: ⚠️ 与 #5088 的 `ATTRIBUTABLE_KINDS` 的分工：那张表管「**哪些 kind 可以用于归因**」；
#: 本表管「**哪些代码路径能凭重跑结果放掉一个红**」。两者**不互相替代**。
RERUN_TO_CLEAR_PATHS: dict[str, RerunToClearPath] = {
    "build_entries": RerunToClearPath(
        where=".github/scripts/flaky_ledger.py",
        reason=(
            "**消红判据的落点**：`rerun_result == \"success\"` 这一支决定条目 `kind` —— "
            "`flaky`（放掉红）/ `suspect-window-deterministic`（降级为「需人看」+ 强制跟踪）；"
            "infra / 两次都红这两支不消红。时间桶判据（`classify_rerun_green`）从这里被调用，"
            "`failed_at` / `rerun_at` / `rerun_bucket_verdict` 也从这里写进条目（**可离线复算**）。"
        ),
        why_not_removable=(
            "删掉它 = 台账不再记录终态失败（`decide` 的终态分支没有任何条目可写）⇒ "
            "「重跑通过 ⇒ 消红」这条链**失去唯一的可审计落点**，而消红动作仍在 workflow 侧发生。"
        ),
        owner="CI 分流机制（`.github/scripts/flaky_ledger.py`）+ 本守卫的登记表",
    ),
    "_terminal": RerunToClearPath(
        where=".github/scripts/flaky_ledger.py",
        reason=(
            "**终态动作的唯一产地**：由条目的 `kind` 派生 `mark_flaky` / `mark_suspect` / "
            "`record_infra` / `record_both_red` —— 也就是「这次的红该怎么处置」这句话本身"
            "（#5687 起**不再**由 `rerun_result` 单独派生）。"
        ),
        why_not_removable=(
            "它是**唯一**产出 `mark_*` 动作的地方：把动作派生散回调用点 ⇒ "
            "「跨时间桶 ⇒ mark_suspect」与「同桶 ⇒ mark_flaky」会在两处各判一次"
            "（同一真值两处投影），workflow 侧的护栏（不打 `flaky/rerun-green`）随之失去唯一依据。"
        ),
        owner="CI 分流机制（`.github/scripts/flaky_ledger.py`）+ 本守卫的登记表",
    ),
    "classify_rerun_green": RerunToClearPath(
        where=".github/scripts/flaky_ledger.py",
        reason=(
            "**「重跑通过」能推出什么**的**唯一**判据（入参就是失败时刻与重跑时刻）："
            "#5687 的三层 —— 证据不足 ⇒ 旧口径 `flaky` + **显式声明**；同桶 ⇒ `flaky`"
            "（**安全边界**）；跨桶 ⇒ `suspect-window-deterministic`。"
            "本单的**核心**：旧口径在这里只有一句 `rerun_result == \"success\" ⇒ flaky`。"
        ),
        why_not_removable=(
            "删掉 / 改回旧口径 ⇒ `build_entries` 只能退回「重跑通过就判 flaky」⇒ 本单的病灶"
            "**原样复发**，而这句改动**不会有任何东西变红** —— 正是「未登记即红」要拦的形态。"
        ),
        owner="CI 分流机制（`.github/scripts/flaky_ledger.py`）+ 本守卫的登记表",
    ),
}


def _arg_names(fn: ast.AST) -> set[str]:
    args = fn.args
    names = {a.arg for a in list(args.args) + list(args.kwonlyargs) + list(args.posonlyargs)}
    if args.vararg:
        names.add(args.vararg.arg)
    if args.kwarg:
        names.add(args.kwarg.arg)
    return names


def _is_field_read(node: ast.AST) -> bool:
    """`entry.get("kind")` / `x["kind"]` 这类**取值**表达式（读台账字段，而不是读重跑结果）。"""
    if isinstance(node, ast.Call):
        func = node.func
        return isinstance(func, ast.Attribute) and func.attr in ("get", "pop")
    return isinstance(node, ast.Subscript)


def _clear_action_nodes(fn: ast.AST) -> list:
    """该函数里「**把红放掉 / 降级**」的那几处**代码**节点（不是文档，也不是纯读台账字段）。

    取五种**语境**（任一命中即算，方向仍是**多收**）：
      ① `x = <动作词>` —— **产出**一个消红/降级动作；
      ② `return (<动作词>, …)` / `return <动作词>` —— **返回**一个消红/降级动作；
      ③ 动作词出现在 **`==` / `is` 比较**或**字典值**里 —— **按动作分流**（`_terminal` / `decide`）；
      ④ `return` / `=` 的值是**新类常量**（`SUSPECT_WINDOW_KIND`，`Name` 而非 `Constant`）
         —— `classify_rerun_green` 的形状（**把默认结论从 flaky 翻成新类**，正是「放不放红」的翻转点）。

    ⚠️ 有意**不**收（收了只是噪音，实测把语料从 4 个吹到 5～8 个）：
      · `entry.get("kind") == "flaky"` / `decision.get("action") == "mark_suspect"` ——
        左侧是**台账字段取值**（`aggregate` / `reconcile` / `render_comment` 的形状）：
        它们既不看**重跑结果**、也不产出动作，只是在**读**已经写好的条目；
      · **文案字符串里提到动作词**（`ledger_violations` 的**报错消息**就是这种：
        它写「跨桶却判 `mark_flaky` / `mark_suspect` ⇒ 违规」）—— 报错文案不是判据链。
    """
    hits = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            if isinstance(node.value, ast.Name) and node.value.id == "SUSPECT_WINDOW_KIND":
                hits.append(node)
            elif isinstance(node.value, ast.Constant) and node.value.value in ACTION_WORDS:
                hits.append(node)
            elif any(isinstance(t, ast.Name) and t.id == "SUSPECT_WINDOW_KIND"
                     for t in node.targets):
                hits.append(node)
        elif isinstance(node, ast.Return) and node.value is not None:
            values = node.value.elts if isinstance(node.value, ast.Tuple) else [node.value]
            for value in values:
                if isinstance(value, ast.Constant) and value.value in ACTION_WORDS:
                    hits.append(node)
                elif isinstance(value, ast.Name) and value.id == "SUSPECT_WINDOW_KIND":
                    hits.append(node)
        elif isinstance(node, ast.Dict):
            for value in node.values:
                if isinstance(value, ast.Constant) and value.value in ACTION_WORDS:
                    hits.append(node)
    return hits


def rerun_to_clear_paths(source: str) -> list[str]:
    """**现取**：`source` 里每个「以重跑结果为唯一依据来消红/降级」的函数名（升序）。

    判据（两条，任一命中即算；**都只看代码面**，不看文档）：

      ① **入参就是重跑结果** —— `rerun_result` 是它的形参（`build_entries` / `_terminal`
         这条链的形状）：函数**签名**里就写着「我按重跑结果判」；
      ② **动作词 / 新类常量出现在代码里** —— `mark_flaky` / `mark_suspect` / `SUSPECT_WINDOW_KIND`
         （见 `_clear_action_nodes` 的五种语境）。

    ⚠️ **为什么 ② 里不含 `flaky` / `success` / `failure` 这些值**（**两次收窄的实测**，照实登记）：
    把值字面量也算进来的第一版收进 **13 个函数**（其中 9 个是误报：`is_failed` /
    `failed_step_name` / `runs_needing_rerun` 只是**比较** `conclusion` 就被收）；
    第二版收到 **8 个**（`aggregate` / `reconcile` / `ledger_violations` / `main` 读的是
    **台账字段**）⇒ 登记表被逼着登记半个模块 ⇒「未登记即红」退化成噪音。
    ⇒ **动作词是「放不放红」的分界线**：`flaky` 是**状态值**（谁都能读），
    `mark_flaky` / `mark_suspect` 是**动作**（只有决定放红的地方才产出它）。
    """
    tree = ast.parse(source)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if RERUN_RESULT_PARAM in _arg_names(node) or _clear_action_nodes(node):
            out.append(node.name)
    return sorted(set(out))


def problems_rerun_to_clear_paths(source: str = REAL_SOURCE, table=None) -> list[str]:
    """**独立判据**（喂任意源码 + 任意登记表，含变异体）：未登记即红 / 只许缩短 / 字段不齐即红。

    三问缺一不可（第 ④ 问是**fail-closed** 的落点）：
      ① **覆盖** —— 现取集合里每个名字都在表里（未登记 ⇒ 红）；
      ② **只许缩短** —— 表里每个名字都仍在现取集合里（陈旧 ⇒ 红）；
      ③ **字段齐** —— `where` / `reason` / `why_not_removable` / `owner` 都非空；
      ④ **语料非空** —— 现取为空 ⇒ 红（否则本判据恒绿 = 静默空跑，本仓最贵的形态）。
    """
    table = RERUN_TO_CLEAR_PATHS if table is None else table
    bad = []
    found = rerun_to_clear_paths(source)
    if not found:
        return [f"判据语料为空（`{LEDGER_SCRIPT.name}` 里找不到任何消红判据函数）"
                f" ⇒ 本守卫会**静默空跑**，先修语料面"]
    for name in found:
        if name not in table:
            bad.append(
                f"`{name}` 在 `{LEDGER_SCRIPT.name}` 的**消红判据链**里（它读 `rerun_result` "
                f"或产出 `mark_*` 动作），但没有具名登记在 `RERUN_TO_CLEAR_PATHS` 里。"
                "**未登记即红**：任何「以重跑结果为唯一依据来消红/降级」的路径都必须被点名"
                "（否则它一变，就没人知道 PR 的红是被什么放掉的）"
            )
    for name in sorted(set(table) - set(found)):
        bad.append(
            f"`RERUN_TO_CLEAR_PATHS['{name}']` 已不再出现在判据链里（改名 / 搬走 / 删掉）"
            " ⇒ **删掉这条登记**（台账只许缩短；陈旧条目会把下一次真回归读成「已登记」）"
        )
    for name, entry in sorted(table.items()):
        empty = [field for field, value in (("where", entry.where), ("reason", entry.reason),
                                            ("why_not_removable", entry.why_not_removable),
                                            ("owner", entry.owner))
                 if not str(value).strip()]
        if empty:
            bad.append(f"`RERUN_TO_CLEAR_PATHS['{name}']` 缺字段 {empty}"
                       "（在哪 / 为什么在链里 / 为什么不能删 / 谁负责 缺一即红）")
    return bad


# ── workflow 侧的结构锁（判据对了，动作也要对） ───────────────────────────────


def steps_of(text: str) -> list:
    import yaml
    wf = yaml.safe_load(text) or {}
    return ((wf.get("jobs") or {}).get("triage") or {}).get("steps") or []


def _step_text(step) -> str:
    step = step or {}
    return "\n".join([str(step.get("name") or ""), str(step.get("if") or ""),
                      str(step.get("run") or ""), str(step.get("uses") or ""),
                      json.dumps(step.get("env") or {}, ensure_ascii=False)])


def workflow_structure_violations(text: str) -> list[str]:
    """**workflow 侧的结构锁**（判据 5：判据对了，动作也要对）。

    四条（每条都对着一个「判据变了、动作没变」的失效形态）：
      · `mark_suspect` 必须有**独占**的步骤（否则跨桶疑似**没有任何动作** ⇒ 静默放行）；
      · 该步骤必须 **`--disable-auto` + `block/merge`**（仍然不许自动放行）；
      · 该步骤**不得**打 `flaky/rerun-green`（跨桶 ≠ flaky —— 那个标签读作「已查清是重跑才绿」）；
      · 必须有 `triage-follow-up` 调用（机械落跟踪单 = 「强制跟踪」的实体动作）。
    """
    bad = []
    suspects = [s for s in steps_of(text) if "mark_suspect" in str(s.get("if") or "")]
    if not suspects:
        return ["没有 `action == 'mark_suspect'` 的步骤 ⇒ 跨时间桶的疑似**没有任何动作落地**"
                "（= 静默放行，红线）"]
    body = "\n".join(_step_text(s) for s in suspects)
    if not re.search(r"gh pr merge\b[^\n]*--disable-auto", body):
        bad.append("mark_suspect 缺 `gh pr merge … --disable-auto`（**调用形态**，非文案）"
                   "⇒ 已 arm 的 auto-merge 拦不住（#4248 同族）= 自动放行（红线）")
    if '--add-label "block/merge"' not in body:
        bad.append("mark_suspect 缺 `--add-label \"block/merge\"` ⇒ 防不住再次 arm（红线）")
    if "--add-label \"flaky/rerun-green\"" in body:
        bad.append("mark_suspect **打了** `flaky/rerun-green` ⇒ 把「跨时间桶的疑似」读成"
                   "「已查清是 flaky」（#5687 的病根就是这两个被混为一谈）⇒ 红线")
    if not re.search(r"flaky_ledger\.py\s+triage-follow-up\b", text):
        bad.append("没有调用 `flaky_ledger.py triage-follow-up` 的步骤 ⇒ 「强制跟踪」没有实体动作"
                   "（该类条目会被 `ledger_violations` 判违规 ⇒ 分流整条链 fail-closed）")
    return bad


# ── 判据 1~3：登记表三问 ─────────────────────────────────────────────────────


class TestRegistry:
    def test_real_script_is_fully_registered(self):
        """**未登记即红**（判据 1）+ **只许缩短**（判据 2）+ 字段齐（判据 3）—— 真语料必须全绿。"""
        assert problems_rerun_to_clear_paths() == []

    def test_empty_source_is_not_silently_green(self):
        """空语料 ⇒ 必须报「判据语料为空」（否则本守卫**静默空跑** = 最贵的形态）。"""
        bad = problems_rerun_to_clear_paths(source="")
        assert bad and "语料为空" in bad[0], bad

    def test_unregistered_clear_path_turns_red(self):
        """🔴 **红证 A**（未登记即红）：注入一个「读 `rerun_result == "success"` 就把失败降级」
        的新函数 ⇒ 必须红。

        **命中的分支** = `for name in found: if name not in table`（即**覆盖**那条，
        不是「只许缩短」那条）—— 见 `test_comment_only_injection_does_not_turn_red` 的对照。
        """
        injected = REAL_SOURCE + (
            "\n\ndef clear_red_after_retry(rerun_result, kinds):\n"
            "    \"\"\"注入：按重跑结果消红（本函数**不在**登记表里）。\"\"\"\n"
            "    if rerun_result == \"success\":\n"
            "        return \"mark_flaky\"\n"
            "    return None\n"
        )
        bad = problems_rerun_to_clear_paths(source=injected)
        if not any("clear_red_after_retry" in b for b in bad):
            raise AssertionError(f"注入未登记的消红路径后守卫仍判绿 ⇒ 空断言（bad={bad!r}）")
        assert any("未登记即红" in b for b in bad), bad

    def test_comment_only_injection_does_not_turn_red(self):
        """**对照组（「只改注释」）**：把同一句话写进**注释** ⇒ 必须**不**红。

        为什么必须有这条对照（本单的验收第 7 条）：另一包实测发现「**只改注释的红证会命中
        锚失配、而不是目标分支**」⇒ 那条判据其实是**空断言**。本守卫的语料面显式剥注释
        ⇒「注释里提一句」不触发；而上面那条注入是**真代码**注入 ⇒ 它命中的是**覆盖**分支。
        两条红证的读数**必须不同**（一条红、一条绿）才说明判据在按代码面判。
        """
        injected = REAL_SOURCE.replace(
            "def append_entries(ledger: dict, entries: list) -> tuple:",
            "# 注入：clear_red_after_retry(rerun_result) 会把 rerun_result == \"success\" 判成 "
            "mark_flaky（**注释**，不是代码）\n"
            "def append_entries(ledger: dict, entries: list) -> tuple:", 1)
        assert injected != REAL_SOURCE, "注入没生效（锚已漂移）⇒ 这条对照是空断言"
        assert problems_rerun_to_clear_paths(source=injected) == []

    def test_stale_registry_entry_turns_red(self):
        """🔴 **红证 B**（只许缩短）：把真函数名改掉 ⇒ 表里那条变陈旧 ⇒ 必红。

        **命中的分支** = `for name in sorted(set(table) - set(found))`（与红证 A **不同**的分支）。
        """
        renamed = REAL_SOURCE.replace("def classify_rerun_green(",
                                      "def classify_rerun_green_v2(", 1)
        assert "def classify_rerun_green_v2(" in renamed
        bad = problems_rerun_to_clear_paths(source=renamed)
        if not any("classify_rerun_green" in b and "只许缩短" in b for b in bad):
            raise AssertionError(f"改名后陈旧登记仍判绿 ⇒ 空断言（bad={bad!r}）")

    def test_missing_registry_field_turns_red(self):
        """🔴 **红证 C**（字段齐）：清空任一字段 ⇒ 必红。"""
        broken = dict(RERUN_TO_CLEAR_PATHS)
        broken["_terminal"] = RerunToClearPath(
            where="", reason="r", why_not_removable="w", owner="o")
        bad = problems_rerun_to_clear_paths(table=broken)
        if not any("缺字段" in b and "_terminal" in b for b in bad):
            raise AssertionError(f"字段清空后守卫仍判绿 ⇒ 空断言（bad={bad!r}）")

    def test_registry_names_are_real_functions(self):
        """登记的名字必须真的是 `flaky_ledger.py` 里的顶层函数（防「登记一个不存在的名字」凑绿）。"""
        defined = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\s*\(", REAL_SOURCE))
        missing = sorted(set(RERUN_TO_CLEAR_PATHS) - defined)
        assert missing == [], f"登记表点名了不存在的函数：{missing}"


# ── 判据 4：字段语义承重（时间桶判据的取数面 + 结论不许与依据矛盾） ─────────────


class TestCarryingFacts:
    def test_bucket_verdict_is_three_valued_and_fail_safe(self):
        """`rerun_bucket_verdict` 的**三态**：取不到时刻 ⇒ `None`（**证据不足**），
        不得当 `False`（跨桶）读 —— 否则「读不到」会变成降级理由，判据在历史调用点上变成噪音源。"""
        assert FL.same_bucket("", "") is None
        assert FL.same_bucket("2026-09-26T22:12:00Z", "") is None
        assert FL.same_bucket("2026-09-26T22:12:00Z", "2026-09-26T22:12:08Z") is True
        assert FL.same_bucket("2026-09-26T22:12:00Z", "2026-09-27T00:05:00Z") is False

    def test_three_layer_classification_is_named(self):
        """三层判定必须**各有一条**：证据不足 ⇒ 旧口径 + **显式声明**；同桶 ⇒ flaky；跨桶 ⇒ 新类。

        ⚠️ 「证据不足」那层**必须**在 `reason` 里写明（否则读的人会把「没数」读成「已排除」）。
        ⚠️ 这是**验收第 2 条的安全边界**：同桶内失败→重跑通过 **仍然** 判 `flaky`。
        """
        kind, reason = FL.classify_rerun_green("", "")
        assert kind == "flaky" and "证据不足" in reason, (kind, reason)
        kind, reason = FL.classify_rerun_green("2026-09-26T22:12:00Z", "2026-09-26T22:12:08Z")
        assert kind == "flaky" and "同一时间桶" in reason, (kind, reason)
        kind, reason = FL.classify_rerun_green("2026-09-26T22:12:00Z", "2026-09-27T00:05:00Z")
        assert kind == FL.SUSPECT_WINDOW_KIND and "不同时间桶" in reason, (kind, reason)

    def test_new_kind_is_not_an_attribution_kind(self):
        """新类**不得**进 `ATTRIBUTABLE_KINDS`：它是「需人看」，不是归因（同 #5088 的 `unknown`）。

        红证形态 = 把 `SUSPECT_WINDOW_KIND` 加进 `ATTRIBUTABLE_KINDS` ⇒ 本断言必红
        （「用一个未取证的 kind 做归因计数」正是 #5088 治过的形态）。
        """
        assert FL.SUSPECT_WINDOW_KIND in FL.ENTRY_KINDS
        assert FL.SUSPECT_WINDOW_KIND not in FL.ATTRIBUTABLE_KINDS

    def test_kind_and_verdict_cannot_contradict_each_other(self):
        """🔴 **红证 D**（结论与依据不许矛盾）：`rerun_bucket_verdict` 是**取数面**、
        `kind` 是**结论** —— 两者反向 = 判据被绕过（或条目被人手改过）。两个方向各测一条。

        **命中的分支** = `ledger_violations` 里那两条「不许自相矛盾」的判据
        （跨桶却判 flaky / 同桶却判新类）+ 一条「该类缺 `follow_up`」。
        """
        def entry(**over):
            base = {"workflow": "PR Check", "job": "j", "run_id": 1,
                    "rerun_result": "success", "observed_at": "t",
                    "reason": "r", "remedy": "m", "status": "open", "follow_up": None}
            base.update(over)
            return base

        # ① 跨桶却判普通 flaky ⇒ 红（#5687 的病根本身）
        bad = FL.ledger_violations({"version": 2, "note": "", "_schema": {}, "entries": [
            entry(kind="flaky", rerun_bucket_verdict=False)]})
        assert any("判为普通 flaky" in b for b in bad), bad
        # ② 同桶却判窗口型疑似 ⇒ 红（把真 flaky 一起关掉 = 本单的安全边界）
        bad = FL.ledger_violations({"version": 2, "note": "", "_schema": {}, "entries": [
            entry(kind=FL.SUSPECT_WINDOW_KIND, rerun_bucket_verdict=True, follow_up=1)]})
        assert any("安全边界" in b for b in bad), bad
        # ③ 该类缺 follow_up ⇒ 红（判据③：强制跟踪）
        bad = FL.ledger_violations({"version": 2, "note": "", "_schema": {}, "entries": [
            entry(kind=FL.SUSPECT_WINDOW_KIND, rerun_bucket_verdict=False)]})
        assert any("强制跟踪" in b for b in bad), bad
        # ④ 齐了 ⇒ 绿（否则③是空断言：任何输入都红）
        assert FL.ledger_violations({"version": 2, "note": "", "_schema": {}, "entries": [
            entry(kind=FL.SUSPECT_WINDOW_KIND, rerun_bucket_verdict=False, follow_up=5687)]}) == []

    def test_shipped_ledger_is_still_clean(self):
        """出厂台账仍自洽 + 三态干净（本单只**新增** kind，**不改**既有条目的语义）。"""
        assert FL.ledger_violations(REAL_LEDGER) == []
        assert {k: len(v) for k, v in FL.reconcile(REAL_LEDGER).items()} == {
            "new_events": 0, "duplicates": 0, "fixed_not_deducted": 0}
        assert REAL_LEDGER["version"] >= 2


# ── 判据 5：workflow 侧的结构锁（判据对了，动作也要对） ────────────────────────


class TestWorkflowStructure:
    """workflow 侧的结构锁（判据 5）。

    ⚠️ **注入方式有意不用「字符串替换真文件」**：本单实测踩过一个**假红证**——
    用 `REAL_WORKFLOW.replace(...)` 构造变异体时，判据在某些跑法下拿到的是**未变异**的文本
    （实测：`pytest` 下该用例恒绿、而同一函数在 `python -c` 直调下正确判红）⇒ 那条红证
    在 CI 上**永远不会红**（= 本单要治的「空断言」形态）。
    ⇒ 本类改成**显式构造**：从真 workflow 解析出 steps，**深拷贝**后按判据语义改 YAML 结构，
    再 `yaml.safe_dump` 成文本喂给判据。变异体是**当场构造**的 ⇒ 不存在「拿到旧文本」的窗口。
    """

    @staticmethod
    def mutate(flip_condition=None, add_label_to_suspect=False, break_tracking=False) -> str:
        import yaml
        wf = yaml.safe_load(REAL_WORKFLOW)
        steps = wf["jobs"]["triage"]["steps"]
        for step in steps:
            if step.get("if") == "steps.decide.outputs.action == 'mark_suspect'":
                if flip_condition:
                    step["if"] = flip_condition
                if add_label_to_suspect:
                    step["run"] = ('gh pr edit "$PR_NUMBER" --add-label "flaky/rerun-green" '
                                   '--repo "$GITHUB_REPOSITORY"\n') + str(step.get("run") or "")
            if break_tracking and "triage-follow-up" in str(step.get("run") or ""):
                step["run"] = str(step["run"]).replace("triage-follow-up", "no-such-subcommand")
        return yaml.safe_dump(wf, allow_unicode=True, sort_keys=False)

    def test_real_workflow_is_clean(self):
        assert workflow_structure_violations(REAL_WORKFLOW) == []

    def test_guard_has_discriminating_power_in_memory(self):
        """**判别力自证**（在内存里构造坏形态，不碰任何磁盘文件）：三种坏形态必须各自判红。

        ⚠️ 为什么单独要有这一条（本单的实测教训）：用「改磁盘上的真文件」当红证时，实测出现过
        **红证与病因不符**的形态（判据函数直调能判红、而测试跑法下拿到的是未变异的文本
        ⇒ 该红证在 CI 上永远绿 = 空断言）。把坏形态**当场构造**就绕开了这条整类问题。
        """
        import yaml
        wf = yaml.safe_load(REAL_WORKFLOW)
        steps = wf["jobs"]["triage"]["steps"]
        base = [dict(s) for s in steps]
        findings = []
        # ① 改掉 mark_suspect 的条件
        wf["jobs"]["triage"]["steps"] = [
            dict(s, **({"if": "false"} if s.get("if") ==
                       "steps.decide.outputs.action == 'mark_suspect'" else {})) for s in base]
        findings.append(workflow_structure_violations(
            yaml.safe_dump(wf, allow_unicode=True, sort_keys=False)))
        # ② 给 mark_suspect 步加 flaky 标签
        wf["jobs"]["triage"]["steps"] = [
            dict(s, **({"run": 'gh pr edit "$PR_NUMBER" --add-label "flaky/rerun-green"\n' +
                               str(s.get("run") or "")}
                       if s.get("if") == "steps.decide.outputs.action == 'mark_suspect'" else {}))
            for s in base]
        findings.append(workflow_structure_violations(
            yaml.safe_dump(wf, allow_unicode=True, sort_keys=False)))
        # ③ 摘掉 triage-follow-up
        wf["jobs"]["triage"]["steps"] = [
            dict(s, **({"run": str(s.get("run") or "").replace("triage-follow-up", "no-such-cmd")}
                       if "triage-follow-up" in str(s.get("run") or "") else {})) for s in base]
        findings.append(workflow_structure_violations(
            yaml.safe_dump(wf, allow_unicode=True, sort_keys=False)))
        empty = [i for i, bad in enumerate(findings) if not bad]
        if empty:
            raise AssertionError(
                f"第 {empty} 种坏形态**没有**被判红 ⇒ 判据缺判别力（逐条读数={findings!r}）")

    def test_empty_workflow_is_not_silently_green(self):
        assert workflow_structure_violations("") != [], "空输入判绿 ⇒ 守卫会静默空跑"

    def test_mutation_harness_really_changes_the_text(self):
        """**前提自证**（否则下面三条红证都是空断言）：三种变异各自都真的改了文本。"""
        for kwargs in ({"flip_condition": "false"},
                       {"add_label_to_suspect": True},
                       {"break_tracking": True}):
            mutant = self.mutate(**kwargs)
            assert mutant != REAL_WORKFLOW, f"变异没生效：{kwargs}"
            assert "mark_suspect" in mutant or "triage" in mutant, kwargs

    def test_removing_the_suspect_step_turns_red(self):
        """🔴 **红证 E**：`mark_suspect` 步骤不再被触发（条件改成 `false`）⇒
        跨桶疑似没有任何动作 ⇒ 必红。

        **命中的分支** = `if not suspects: return [...]`（最早那条短路）。
        """
        bad = workflow_structure_violations(self.mutate(flip_condition="false"))
        if not any("没有任何动作落地" in b for b in bad):
            raise AssertionError(f"把 mark_suspect 步骤的条件改成 false 后守卫仍判绿 ⇒ 空断言（bad={bad!r}）")

    def test_suspect_step_gaining_the_flaky_label_turns_red(self):
        """🔴 **红证 F**：让 `mark_suspect` 也打 `flaky/rerun-green` ⇒ 必红
        （那正是「跨桶疑似被读成已查清是 flaky」的形态）。

        **命中的分支** = `if "--add-label \"flaky/rerun-green\"" in body`。
        """
        bad = workflow_structure_violations(self.mutate(add_label_to_suspect=True))
        if not any("flaky/rerun-green" in b for b in bad):
            raise AssertionError(f"给 mark_suspect 步加上 flaky 标签后守卫仍判绿 ⇒ 空断言（bad={bad!r}）")

    def test_removing_tracking_step_turns_red(self):
        """🔴 **红证 G**：摘掉 `triage-follow-up` 调用 ⇒ 「强制跟踪」没有实体动作 ⇒ 必红。

        **命中的分支** = `if not re.search(r"flaky_ledger\.py\s+triage-follow-up\b", text)`。
        """
        bad = workflow_structure_violations(self.mutate(break_tracking=True))
        if not any("triage-follow-up" in b for b in bad):
            raise AssertionError(f"摘掉 triage-follow-up 调用后守卫仍判绿 ⇒ 空断言（bad={bad!r}）")


# ── 判据 6：覆盖面被**显式登记**（本文件 docstring 的「明确的边界」是判据的一部分） ──


class TestDeclaredBoundary:
    def test_boundary_section_names_the_out_of_scope_forms(self):
        """覆盖面**必须显式写下**（照 #5675 的「明确的边界」写法）—— 至少点名三类面外形态。

        为什么把它做成判据（而不是只写在人读的散文里）：**未被登记的边界 = 读者会以为被覆盖**，
        而那正是「判据被读成覆盖面更大」的形态（#5687 的教训同族）。
        """
        doc = __doc__ or ""
        assert "明确的边界" in doc, "本文件的覆盖面声明被删掉了"
        for form in ("随机端口", "并发时序", "网络抖动"):
            assert form in doc, f"面外形态 `{form}` 没有被显式登记"
        for form in ("同一 UTC 小时", "相隔很久但没跨桶", "`rerun_result` 之外的消红路径"):
            assert form in doc, f"边界形态 `{form}` 没有被显式登记"

    def test_reconcile_is_declared_non_required(self):
        """③ 顺带登记（**不修**）：`Flaky Ledger Reconcile` 的非 required 属性是**有意**的
        —— 它的红是给人看的，不是拦合并的。本判据把它**钉在 `flaky_ledger.py` 的模块 docstring 里**，
        免得后来人误以为「没红就是没问题」。

        ⚠️ 本判据**不**改它的 required 位（人已裁定不做），只钉「该声明仍在」。
        """
        ledger_doc = FL.__doc__ or ""
        assert "未接 required 门禁" in ledger_doc, \
            "`flaky_ledger.py` 的模块 docstring 必须保留「未接 required 门禁」的登记"
        assert "判红不等于阻塞合并" in ledger_doc, \
            "必须逐字写明「判红不等于阻塞合并」（免得被读成「没红就是没问题」）"
