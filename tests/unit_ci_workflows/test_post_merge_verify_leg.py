# case_ids: MC-012
"""合并后 main 侧守护腿的判据（issue #5423 = `migao-dev-flow` §23.7 **A2** 的机械化）。

## 病根（2026-09-24 现场）

`pr-check` **只在 `pull_request` 触发** ⇒ **main 上的破坏没有任何 run 会报**：`#5396` 新增了
「装配层字段 ⊆ DA-016 契约键清单」这条判据（`tests/unit_ci_workflows/test_wiring_status_case_truth_sync.py`
的 C3），**但同一 PR 没把 DA-016 的清单补上** ⇒ 半成品落 main ⇒ 它爆在**下一次任何 PR** 的
required 检查上，**卡住全队列**，最后由人花一整轮热修（`#5405`）+ 4 个分支逐一 rebase。

⇒ 本文件钉的是那条**新腿**（`.github/workflows/post-merge-verify.yml` +
`scripts/post_merge_verify.py`）的**可见性前提**与**判定力**，而不是它跑出来的某个结论。

## 判据与被钉住的形态（每条都带能单独变红的红证）

| # | 判据 | 红证（注入 ⇒ 必红） |
|---|---|---|
| 1 | 真判据（`#5396` 那条 C3）的**引用面**必须同时含「装配层 Java」与「`.github/cases` 目录」两个方向 | 读真文件做 AST：把两个方向之一从语料里抹掉（负控在 `test_..._negative_control`） |
| 2 | 判据**自身**变更 ⇒ 必被选中（Tier A） | 夹具：只改判据文件 ⇒ 选中集必须含它 |
| 3 | **「判据改了、数据没改」⇒ 该腿必红**（本单要求的注入形态） | 夹具：判据新增一条要求，数据不动 ⇒ `rc=1` |
| 4 | **「装配层改了、数据没改」⇒ 必红**（`#5396` 的历史形态） | 夹具：装配层声明多一个键，数据不动 ⇒ `rc=1` |
| 5 | **「数据改了、判据没改」⇒ 必红**（反向同族） | 夹具：数据删一个键，判据不动 ⇒ `rc=1` |
| 6 | **零动作也要出声**（§23 G6）：不相关变更 ⇒ `rc=0` **且**打印「零动作 + 原因」 | 夹具：只改不相关文件 ⇒ 输出必须含零动作与未命中清单 |
| 7 | 无法判定 ⇒ 退出码 **3**（不得当 `0` 读，§19.1 三态） | 夹具：判定面为空 ⇒ `rc=3` |
| 8 | 触发面齐备（`push` 是必须的那一面 + `push` 被吞时的补偿面） | 变异解析后的 YAML：删任一面 ⇒ 判据函数非空 |
| 9 | 判定基准 = **main**（PR 事件时 `GITHUB_SHA` 是 PR head ⇒ 必须显式切 main） | 变异 checkout 步骤的 `ref` ⇒ 判据函数非空 |
| 10 | 判红出口 = **P1 值班 issue**（run 链接 + 清零判据 + 谁看），复用既有通道形态 | 变异失败钩子的 run 文本（去 `gh issue create` / 去 `priority/P1`）⇒ 非空 |
| 11 | 读数步的 **fail-open 护栏**：发射器不在检出里 ⇒ `::warning::` 明说「读数缺失（不是零动作）」 | 变异该分支文本 ⇒ 非空 |
| 12 | **最小写权限**：唯一写作用域 = `issues`（本腿没有 PR 对象，不给它 PR 写权限） | 变异 `permissions` 加 `pull-requests: write` ⇒ 非空 |
| 13 | **不许放宽既有门禁**（判据 6）：本腿**不得**出现在 `pr-check.yml` 里（报告型 ≠ required） | 变异：在文本里塞一处 ⇒ 非空 |
| 14 | **禁挂钟**（§23 G8）：机器可读报告只报与负载无关的量，**不含**任何时长字段 | 变异：往报告里塞一个时长键 ⇒ 非空 |
| 15 | **首发日护栏**：判定本体尚未在 main 上落地 ⇒ **出声但不判红**（不许自造假红）；「workflow 在、脚本没了」⇒ **红** | 变异四个要素（`[ ! -f scripts/post_merge_verify.py ]` / `pending-merge` / workflow 存在判据 / `::error::`）**各能单独变红** |

## 边界（照实登记，别读成「已覆盖」）

- **判定面 = `tests/unit_ci_workflows/test_*.py`**；其它测试面（vitest / Java / ai-agent `tests/**`）
  **不判** —— 本腿是**报告型**守护，不假装覆盖它们（原因见 `scripts/post_merge_verify.py` 的 docstring）。
- **可见性前提 = 既有引用纪律**（§16.7）：判据要读某文件，路径必须写成**可静态解析**的形态
  （仓库相对全路径，或 `REPO / "a" / "b"` 链）。写成散文（docstring / 注释）**不算引用**
  —— 这是有意的（§23.8 **B1**：判据语料不含自身说明；否则改任一判据会命中几乎所有判据）。
- 本腿**不翻 required**（`push`/`schedule` 腿没有 PR 对象；且它判定依赖 main 当前状态，
  翻 required 会让所有 PR 永久 `BLOCKED`）。判红只走**值班 issue** 这条既有通道。
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
SCRIPT_REL = "scripts/post_merge_verify.py"
WORKFLOW_REL = ".github/workflows/post-merge-verify.yml"
SCRIPT = REPO / SCRIPT_REL
WORKFLOW = REPO / WORKFLOW_REL
PR_CHECK = REPO / ".github" / "workflows" / "pr-check.yml"
FACE_DIR = "tests/unit_ci_workflows"
EMITTER = ".github/scripts/mechanism_liveness.sh"

#: `#5396` 那条判据（C3）与它的两个输入方向 —— 本单的**原始形态**，用真文件钉住。
WIRING_CRITERION = f"{FACE_DIR}/test_wiring_status_case_truth_sync.py"
ASSEMBLY_JAVA = "backend/admin-api/src/main/java/com/migao/admin/service/DailyBriefingService.java"
CASES_DIR_REL = ".github/cases"

#: 夹具判据（最小复刻 C3 的形态：判据读「装配层声明」×「数据清单」两侧做比较）。
FIXTURE_CRITERION = '''\
"""夹具判据：装配层声明的键必须逐字出现在 `data/contract.yml` 清单里（#5396 形态的最小复刻）。"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CONTRACT = REPO / "data" / "contract.yml"
DECLARED = REPO / "data" / "declared.txt"


def test_declared_keys_are_listed():
    listed = CONTRACT.read_text(encoding="utf-8")
    missing = [k for k in DECLARED.read_text(encoding="utf-8").split() if k not in listed]
    assert missing == [], f"装配层声明但契约清单里没有的键：{missing}"
'''
FIXTURE_CRITERION_REL = f"{FACE_DIR}/test_contract_covers_declared.py"
FIXTURE_CONSISTENT = {"contract": "alpha\nbeta\ngamma\n", "declared": "alpha\nbeta\n"}


def _leg():
    """把 `scripts/post_merge_verify.py` 当模块加载（不复制它的任何逻辑）。"""
    spec = importlib.util.spec_from_file_location("post_merge_verify_leg", SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError(f"加载不了 {SCRIPT_REL}（本判据无从判定 ⇒ 大声失败）")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True,
                          env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(repo)})
    if proc.returncode != 0:
        raise AssertionError(f"夹具 git {' '.join(args)} 失败：{proc.stderr[:400]}")
    return proc.stdout


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=case@example.invalid", "-c", "user.name=case",
         "commit", "-q", "-m", message)


def _fixture(tmp_path: Path) -> Path:
    """一致状态的夹具仓库（基线绿）：判据 × 装配层声明 × 契约清单三者同刻。

    两次提交：① 三者一致；② **只动判据**（追加一行注释）—— 第二次是为了让 `--lookback 1`
    有 `HEAD~1` 可解析（单提交的仓库 `HEAD~1` 不存在 ⇒ 窗口退化成 root..HEAD = 空窗口），
    顺带把 Tier A（判据自身变更 ⇒ 必选）在基线里就证明一次。
    """
    repo = tmp_path / "fixture"
    (repo / FACE_DIR).mkdir(parents=True)
    (repo / "data").mkdir()
    crit = repo / FACE_DIR / Path(FIXTURE_CRITERION_REL).name
    crit.write_text(FIXTURE_CRITERION, encoding="utf-8")
    (repo / "data" / "contract.yml").write_text(FIXTURE_CONSISTENT["contract"], encoding="utf-8")
    (repo / "data" / "declared.txt").write_text(FIXTURE_CONSISTENT["declared"], encoding="utf-8")
    _git(repo, "init", "-q")
    _commit(repo, "base: 三者一致")
    crit.write_text(crit.read_text(encoding="utf-8") + "# Tier A：判据自身变更也必须被选中\n", encoding="utf-8")
    _commit(repo, "base2: 只动判据")
    return repo


def _run_leg(repo: Path, *args: str) -> tuple[int, str, dict]:
    """真跑腿（子进程；**不接管道**：命令的退出码必须原样带回来，§23.6）。"""
    out = repo / "leg-report.json"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), *args, "--json", str(out)],
        capture_output=True, text=True, cwd=str(repo))
    text = (proc.stdout or "") + (proc.stderr or "")
    report = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else {}
    return proc.returncode, text, report


# ═══════════════════════════════════════════════════════════════════════════
# 一、真判据的引用面（判据 1~2）—— 判据 3/5 两个方向都必须可见
# ═══════════════════════════════════════════════════════════════════════════
class TestRealCriterionIsVisible:
    def test_c3_criterion_declares_both_input_directions(self):
        """判据 1：`#5396` 那条判据的引用面必须含装配层 Java 与用例目录两侧。

        只含一侧 = 本腿对该形态**半盲**（改装配层看得见、改 DA-016 看不见，或反之）。
        """
        leg = _leg()
        needles = leg._path_needles((REPO / WIRING_CRITERION).read_text(encoding="utf-8"))
        paths, fragments, modules = needles
        java_visible = leg._referenced(needles, ASSEMBLY_JAVA)
        data_visible = leg._referenced(needles, f"{CASES_DIR_REL}/data.yml")
        if not (java_visible and data_visible):
            raise AssertionError(
                f"{WIRING_CRITERION} 的引用面缺方向：装配层 Java 可见={java_visible} / "
                f"用例目录可见={data_visible}（引用面 = 该判据的路径常量与代码级字面量；"
                f"散文里的提及**有意**不算 —— 见 §23.8 B1）\npaths={sorted(paths)[:8]}")

    def test_criterion_file_change_selects_itself(self):
        """判据 2（Tier A）：判据文件自身变更 ⇒ 必被选中（否则改动判据的人看不见自己）。"""
        leg = _leg()
        crit = leg.collect_criteria(REPO)
        if WIRING_CRITERION not in crit:
            raise AssertionError(f"{WIRING_CRITERION} 不在判定面里（{len(crit)} 条）—— 判定面选错了")
        selected, _unmatched = leg.select([WIRING_CRITERION], crit)
        if WIRING_CRITERION not in selected:
            raise AssertionError(f"判据文件自身变更却没被选中：{selected[:5]}")

    def test_prose_mentions_are_not_references(self):
        """§23.8 B1：docstring / 注释里的路径**不算引用**（否则改一个判据会命中几乎所有判据）。

        负控：真实判据里那句「同款声明与 `.github/cases/misc.yml` MC-012 的登记」就在 docstring 里。
        """
        leg = _leg()
        src = (REPO / WIRING_CRITERION).read_text(encoding="utf-8")
        doc_only = '"""夹具：见 .github/workflows/nonexistent-probe.yml 与 docs/probe/nothing.md。"""\n'
        needles = leg._path_needles(doc_only)
        if leg._referenced(needles, ".github/workflows/nonexistent-probe.yml"):
            raise AssertionError("docstring 里的路径被当成了引用（§23.8 B1 退化）")
        needles_real = leg._path_needles(src)
        # 正控：同一文件在**代码级**声明的路径确实可见（否则上一条是空断言）。
        if not leg._referenced(needles_real, ASSEMBLY_JAVA):
            raise AssertionError("代码级路径常量也没被识别 ⇒ 上一条「散文不算引用」是空断言")


# ═══════════════════════════════════════════════════════════════════════════
# 二、端到端注入式红证（判据 3~7）—— 每条注入各能单独变红
# ═══════════════════════════════════════════════════════════════════════════
class TestEndToEndInjections:
    def test_baseline_is_green(self, tmp_path):
        """红证的前提自证（§23.7 A1）：注入**之前**这条腿必须是绿的，否则红证什么都不证明。"""
        repo = _fixture(tmp_path)
        rc, out, report = _run_leg(repo, "--lookback", "1")
        if rc != 0:
            raise AssertionError(f"基线（三者一致）应绿，实测 rc={rc}：\n{out}")
        if report.get("selected_count") != 1:
            raise AssertionError(f"基线应选中 1 条夹具判据，实测 {report.get('selected_count')}：\n{out}")

    def test_judgement_changed_data_not_changed_is_red(self, tmp_path):
        """判据 3（本单逐字要求的注入形态）：**判据改了、数据没改** ⇒ 该腿必红。"""
        repo = _fixture(tmp_path)
        crit = repo / FIXTURE_CRITERION_REL
        src = crit.read_text(encoding="utf-8")
        mutated = src.replace(
            'missing = [k for k in DECLARED.read_text(encoding="utf-8").split() if k not in listed]',
            'REQUIRED = ("alpha", "beta", "probe_never_listed")\n'
            '    missing = [k for k in REQUIRED if k not in listed]')
        if mutated == src:
            raise AssertionError("注入点失配：判据文本未被改动（红证不得是空断言）")
        crit.write_text(mutated, encoding="utf-8")
        _commit(repo, "inject: 判据新增一条要求，数据不动")
        rc, out, report = _run_leg(repo, "--lookback", "1")
        if rc != 1:
            raise AssertionError(f"「判据改了、数据没改」⇒ 必红（实测 rc={rc}）：\n{out}")
        if WIRING_CRITERION in report.get("selected", []):
            raise AssertionError("夹具仓库里不该有真判据被选中（夹具隔离失效）")

    def test_assembly_changed_data_not_changed_is_red(self, tmp_path):
        """判据 4：**装配层（判据约束的真值侧）改了、数据没改** ⇒ 必红 —— `#5396` 的历史形态。"""
        repo = _fixture(tmp_path)
        declared = repo / "data" / "declared.txt"
        declared.write_text(declared.read_text(encoding="utf-8") + "probe_new_field\n", encoding="utf-8")
        _commit(repo, "inject: 装配层多一个键，数据不动")
        rc, out, _report = _run_leg(repo, "--lookback", "1")
        if rc != 1:
            raise AssertionError(f"装配层加字段而未补数据 ⇒ 必红（实测 rc={rc}）：\n{out}")
        if "probe_new_field" not in out:
            raise AssertionError(f"判红读数里应点名那个未列入的键（可归因，§23 G3）：\n{out}")

    def test_data_changed_judgement_not_changed_is_red(self, tmp_path):
        """判据 5（反向同族）：**数据改了、判据没改** ⇒ 必红（且该数据只由**目录常量**引用）。"""
        repo = _fixture(tmp_path)
        contract = repo / "data" / "contract.yml"
        contract.write_text("beta\ngamma\n", encoding="utf-8")  # 删掉 alpha
        _commit(repo, "inject: 数据少一个键，判据不动")
        rc, out, report = _run_leg(repo, "--lookback", "1")
        if rc != 1:
            raise AssertionError(f"数据删键而未改判据 ⇒ 必红（实测 rc={rc}）：\n{out}")
        if report.get("selected") != [FIXTURE_CRITERION_REL]:
            raise AssertionError(
                f"只改数据也必须选中该判据（靠 `REPO / \"data\" / \"contract.yml\"` 的路径链）："
                f"{report.get('selected')}")

    def test_unrelated_change_is_zero_action_but_loud(self, tmp_path):
        """判据 6：不相关变更 ⇒ `rc=0` **且必须出声**（零动作 + 原因 + 未命中清单）。"""
        repo = _fixture(tmp_path)
        (repo / "docs").mkdir(exist_ok=True)
        (repo / "docs" / "notes.md").write_text("无关变更\n", encoding="utf-8")
        _commit(repo, "inject: 只改不相关文件")
        rc, out, report = _run_leg(repo, "--lookback", "1")
        if rc != 0:
            raise AssertionError(f"不相关变更应绿（零动作），实测 rc={rc}：\n{out}")
        if "零动作" not in out or "未触及判定面" not in out:
            raise AssertionError(f"零动作必须**出声**并给原因（§23 G6）—— 静默退出即缺陷：\n{out}")
        if "docs/notes.md" not in out:
            raise AssertionError(f"未命中清单必须可见（看不见 ≠ 没问题，§23 G5）：\n{out}")
        if report.get("zero_action") in (None, ""):
            raise AssertionError("机器可读报告里零动作也要留痕（下游按它做读数）：" f"{report}")

    def test_empty_face_is_undecidable_not_green(self, tmp_path):
        """判据 7：判定面为空 ⇒ 退出码 **3**（不得当 0 读 —— 「没跑」绝不能长得像「通过」）。"""
        repo = _fixture(tmp_path)
        for path in (repo / FACE_DIR).glob("test_*.py"):
            path.unlink()
        _commit(repo, "inject: 判定面被清空")
        rc, out, _report = _run_leg(repo, "--lookback", "1")
        if rc != 3:
            raise AssertionError(f"判定面为空 ⇒ 必须 3（无法判定），实测 rc={rc}：\n{out}")


# ═══════════════════════════════════════════════════════════════════════════
# 三、接线（判据 8~13）—— 纯函数 + 变异：每条判据都能单独变红
# ═══════════════════════════════════════════════════════════════════════════
def _on_block(doc: dict) -> dict:
    """`on:` 在 YAML 1.1 里会被解析成布尔 `True` —— 两种键都认。"""
    block = doc.get("on", doc.get(True))
    return block if isinstance(block, dict) else {}


def _trigger_problems(doc: dict) -> list[str]:
    problems = []
    on = _on_block(doc)
    push = on.get("push")
    if not isinstance(push, dict) or [b for b in (push.get("branches") or [])] != ["main"]:
        problems.append("缺 `push: branches: [main]`（合并后分钟级发现的那一面）")
    pr = on.get("pull_request")
    if not isinstance(pr, dict) or not {"opened", "reopened"} <= set(pr.get("types") or []):
        problems.append(
            "缺 `pull_request: [opened, reopened]`（push 被吞时的补偿面 —— 实测最近 ~15 次合并只有 2 次"
            "产生了 main 上的 push run，见 .github/workflows/deploy-reconcile.yml 头部与 issue #3113）")
    if not on.get("schedule"):
        problems.append("缺 `schedule`（触发全面停摆时的定时兜底）")
    if "workflow_dispatch" not in on:
        problems.append("缺 `workflow_dispatch`（值班复算入口）")
    return problems


def _steps(doc: dict) -> list[dict]:
    jobs = doc.get("jobs") or {}
    out: list[dict] = []
    for job in jobs.values():
        if isinstance(job, dict):
            out += [s for s in (job.get("steps") or []) if isinstance(s, dict)]
    return out


def _checkout_ref_problems(doc: dict) -> list[str]:
    problems = []
    refs = [str(s.get("with", {}).get("ref", "")) for s in _steps(doc)
            if uses_checkout(s)]
    if refs != ["main"]:
        problems.append(
            f"checkout 的 `ref` 必须是 `main`（实测：PR 事件时 `GITHUB_SHA` 是 PR head ⇒ 不显式切 main "
            f"就会去判 PR 的代码而不是 main 的状态）；实测 refs={refs}")
    return problems


def uses_checkout(step: dict) -> bool:
    return str(step.get("uses", "")).startswith("actions/checkout@")


def _failure_hook_problems(doc: dict) -> list[str]:
    problems = []
    hooks = [s for s in _steps(doc) if "failure()" in str(s.get("if", ""))]
    if not hooks:
        problems.append("没有 `if: failure()` 的判红出口（判红不许静默）")
        return problems
    text = "\n".join(str(s.get("run", "")) for s in hooks)
    for needle, why in (
        ("gh issue create", "判红要能**开** P1 值班 issue"),
        ("gh issue list", "判红要能**复用/更新**既有的值班 issue（不新造第二套约定）"),
        ("priority/P1", "值班 issue 必须带 `priority/P1`（不是一个没人看的标签）"),
        ("actions/runs/${{ github.run_id }}", "正文必须带 run 链接（可归因）"),
        ("清零判据", "正文必须写清零判据（谁看 + 怎么关）"),
    ):
        if needle not in text:
            problems.append(f"失败钩子缺：{why}（未见 `{needle}`）")
    return problems


def _reading_step_problems(doc: dict) -> list[str]:
    """只判 registry 判据**不判**的那一半：发射器缺席时的 fail-open 措辞（缺失 ≠ 零动作）。"""
    problems = []
    steps = _steps(doc)
    idx = [i for i, s in enumerate(steps) if EMITTER in str(s.get("run", ""))]
    if not idx:
        problems.append(f"没有一步调用读数发射器 `{EMITTER}`（读数缺失时无法与「零动作」区分）")
        return problems
    step = steps[idx[-1]]
    if "always()" not in str(step.get("if", "")):
        problems.append("读数步必须 `if: always()`（判红轮同样要出声）")
    text = str(step.get("run", ""))
    if "读数缺失" not in text or "::warning::" not in text:
        problems.append(
            "读数步缺 fail-open 护栏：发射器不在检出里时必须 `::warning::` 明说「读数缺失」"
            "（**不是**「零动作」）")
    return problems


def _bootstrap_guard_problems(doc: dict) -> list[str]:
    """判据 15：**首发日护栏**（`pending-merge`）—— 判定本体尚未在 main 上落地时不许自造假红。

    本 PR 首轮实测的**真形态**：`pull_request` 事件的 workflow 定义取自 **PR**，而判定基准是显式
    checkout 的 `main` ⇒ 本 PR 刚打开时 main 上还没有 `scripts/post_merge_verify.py` ⇒ 退出码 2 ⇒
    失败钩子当场开出一张**假的 P1 值班单**。护栏要同时满足两件相反的事：
    ① 本体缺席 + workflow 缺席（首发日）⇒ **出声但不判红**；
    ② 本体缺席 + workflow 在（机制被拆掉半截）⇒ **红**（否则「删掉判定本体」= 一条静默的绿）。
    """
    text = "\n".join(str(s.get("run", "")) for s in _steps(doc))
    problems = []
    for needle, why in (
        ("[ ! -f scripts/post_merge_verify.py ]", "缺「判定本体是否在检出里」的判据（首发日会当场假红）"),
        ("pending-merge", "缺 `pending-merge` 口径（与 check_heartbeat 的同族约定）"),
        ("[ -f .github/workflows/post-merge-verify.yml ]", "缺「机制被拆掉半截 ⇒ 红」那一支"),
        ("::error::", "「拆掉半截」那一支必须是 error（不许静默 / 不许只 warning）"),
    ):
        if needle not in text:
            problems.append(f"首发日护栏缺：{why}（未见 `{needle}`）")
    return problems


def _bootstrap_guard_snippet() -> str:
    """从 workflow 里取出**首发日护栏那一段 bash**（真跑它，而不是读它的文本）。"""
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for step in _steps(doc):
        run = str(step.get("run", ""))
        marker = "if [ ! -f scripts/post_merge_verify.py ]"
        if marker in run:
            start = run.index(marker)
            return run[start:run.index("set +e", start)]
    raise AssertionError(f"{WORKFLOW_REL} 里找不到首发日护栏片段（判据 15 无从判定 ⇒ 大声失败）")


def _permission_problems(doc: dict) -> list[str]:
    problems = []
    perms = doc.get("permissions")
    if not isinstance(perms, dict):
        problems.append("缺 `permissions`（最小权限必须显式写出来）")
        return problems
    if perms.get("contents") != "read":
        problems.append(f"`contents` 必须 read（实测 {perms.get('contents')!r}）")
    if perms.get("issues") != "write":
        problems.append("必须有 `issues: write`（否则判红的出口自己崩溃、红而不留痕）")
    writes = sorted(k for k, v in perms.items() if v == "write" and k != "issues")
    if writes:
        problems.append(f"唯一写作用域只许是 `issues`（本腿没有 PR 对象，多余的写面 = 放宽面）：{writes}")
    return problems


def _gate_relaxation_problems(pr_check_text: str) -> list[str]:
    problems = []
    if "post-merge-verify" in pr_check_text:
        problems.append(
            "`pr-check.yml` 里出现了本腿 —— 判据 6：本腿是**报告/值班型**，"
            "不得进 required 集合（那是另一条线的裁定；且它没有 `pull_request` 的稳定判定面）")
    return problems


#: 禁挂钟（§23 G8）：报告 / 接线里不得出现任何**时长**字段。
WALL_CLOCK_TOKENS = ("duration", "elapsed", "wall_clock", "seconds", "挂钟时长")


def _wall_clock_problems(report_keys: list[str], doc: dict) -> list[str]:
    problems = []
    bad = [k for k in report_keys if any(t in k.lower() for t in WALL_CLOCK_TOKENS)]
    if bad:
        problems.append(f"机器可读报告里出现了时长字段（禁挂钟当判据，§23 G8）：{bad}")
    # 注释里**说明**「不用挂钟」是合法的（§23.4 T2：别被自己的文案喂红）⇒ 只看 YAML 的**值**。
    values = json.dumps({k: v for k, v in doc.items() if k != "on"}, ensure_ascii=False).lower()
    bad_v = [t for t in WALL_CLOCK_TOKENS if t.lower() in values]
    if bad_v:
        problems.append(f"接线里把时长当判据了（禁挂钟，§23 G8）：{bad_v}")
    return problems


class TestWorkflowWiring:
    def test_trigger_faces_are_complete(self):
        """判据 8：触发面齐备（`push` 是必须的那一面，另加 push 被吞时的补偿面）。"""
        problems = _trigger_problems(yaml.safe_load(WORKFLOW.read_text(encoding="utf-8")))
        assert problems == [], "\n".join(problems)

    def test_dropping_any_trigger_face_turns_it_red(self):
        """判据 8 的红证：删掉任一面 ⇒ 该判据函数非空（逐面各能单独变红）。"""
        doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        for face in ("push", "pull_request", "schedule", "workflow_dispatch"):
            mutated = {**doc, "on": {k: v for k, v in _on_block(doc).items() if k != face}}
            if face == "push":
                mutated["on"] = {k: v for k, v in _on_block(doc).items() if k != face}
            assert _trigger_problems(mutated) != [], f"删掉 `{face}` 之后判据没红 ⇒ 空断言"

    def test_judgement_base_is_main(self):
        """判据 9：判定基准必须是 **main**（不是 PR head）。"""
        problems = _checkout_ref_problems(yaml.safe_load(WORKFLOW.read_text(encoding="utf-8")))
        assert problems == [], "\n".join(problems)

    def test_wrong_checkout_ref_turns_it_red(self):
        """判据 9 的红证：把 checkout 的 ref 改成 `${{ github.sha }}` ⇒ 必红（PR 事件下会判错对象）。"""
        doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        for job in (doc.get("jobs") or {}).values():
            for step in (job.get("steps") or []):
                if isinstance(step, dict) and uses_checkout(step):
                    step.setdefault("with", {})["ref"] = "${{ github.sha }}"
        assert _checkout_ref_problems(doc) != [], "ref 改错之后判据没红 ⇒ 空断言"

    def test_failure_hook_opens_p1_duty_issue(self):
        """判据 10：判红出口 = P1 值班 issue（run 链接 + 清零判据 + 谁看），复用既有通道形态。"""
        problems = _failure_hook_problems(yaml.safe_load(WORKFLOW.read_text(encoding="utf-8")))
        assert problems == [], "\n".join(problems)

    def test_mutating_failure_hook_turns_it_red(self):
        """判据 10 的红证：把 `gh issue create` / `priority/P1` / run 链接各删一次 ⇒ 各能单独变红。"""
        base = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        for needle in ("gh issue create", "priority/P1", "actions/runs/${{ github.run_id }}", "清零判据"):
            doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
            hit = False
            for job in (doc.get("jobs") or {}).values():
                for step in (job.get("steps") or []):
                    if isinstance(step, dict) and "failure()" in str(step.get("if", "")):
                        text = str(step.get("run", ""))
                        if needle in text:
                            step["run"] = text.replace(needle, "（已变异）")
                            hit = True
            if not hit:
                raise AssertionError(f"变异点失配：失败钩子里找不到 `{needle}`（红证不得是空断言）")
            assert _failure_hook_problems(doc) != [], f"删掉 `{needle}` 之后判据没红 ⇒ 空断言"
        assert _failure_hook_problems(base) == [], "变异过程中把基线弄坏了（红证前提自证失败）"

    def test_reading_step_has_fail_open_guard(self):
        """判据 11：读数步的 fail-open 护栏 —— 发射器缺席时明说「读数缺失（不是零动作）」。"""
        problems = _reading_step_problems(yaml.safe_load(WORKFLOW.read_text(encoding="utf-8")))
        assert problems == [], "\n".join(problems)

    def test_mutating_fail_open_text_turns_it_red(self):
        """判据 11 的红证：抹掉 fail-open 措辞 ⇒ 必红。"""
        doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        hit = False
        for job in (doc.get("jobs") or {}).values():
            for step in (job.get("steps") or []):
                if isinstance(step, dict) and EMITTER in str(step.get("run", "")):
                    step["run"] = str(step["run"]).replace("读数缺失", "（已变异）")
                    hit = True
        if not hit:
            raise AssertionError("变异点失配：找不到读数步")
        assert _reading_step_problems(doc) != [], "抹掉护栏之后判据没红 ⇒ 空断言"

    def test_bootstrap_guard_prevents_self_inflicted_red(self):
        """判据 15：首发日护栏 —— 判定本体尚未在 main 上落地 ⇒ 出声但**不判红**（不许自造假红）。"""
        problems = _bootstrap_guard_problems(yaml.safe_load(WORKFLOW.read_text(encoding="utf-8")))
        assert problems == [], "\n".join(problems)

    def test_mutating_bootstrap_guard_turns_it_red(self):
        """判据 15 的红证：四个要素各删一次 ⇒ 各能单独变红。"""
        for needle in ("[ ! -f scripts/post_merge_verify.py ]", "pending-merge",
                       "[ -f .github/workflows/post-merge-verify.yml ]", "::error::"):
            doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
            hit = False
            for job in (doc.get("jobs") or {}).values():
                for step in (job.get("steps") or []):
                    if isinstance(step, dict) and needle in str(step.get("run", "")):
                        step["run"] = str(step["run"]).replace(needle, "（已变异）")
                        hit = True
            if not hit:
                raise AssertionError(f"变异点失配：找不到 `{needle}`（红证不得是空断言）")
            assert _bootstrap_guard_problems(doc) != [], f"删掉 `{needle}` 之后判据没红 ⇒ 空断言"

    def test_first_day_is_loud_but_not_red(self, tmp_path):
        """判据 15（**行为级**）：首发日形态（本体与 workflow 都不在检出里）⇒ `exit 0` + `::notice::`。

        这条是 ⑤ 那次自伤的真形态复刻：真跑 workflow 里那段 bash，不是读它的文本。
        """
        proc = subprocess.run(["bash", "-c", _bootstrap_guard_snippet()], cwd=str(tmp_path),
                              capture_output=True, text=True)
        out = (proc.stdout or "") + (proc.stderr or "")
        assert proc.returncode == 0, f"首发日应**不判红**（实测 rc={proc.returncode}）：\n{out}"
        assert "::notice::" in out and "pending-merge" in out, f"首发日必须出声并点名 pending-merge：\n{out}"
        assert "::error::" not in out, f"首发日不得报 error：\n{out}"

    def test_half_removed_mechanism_turns_it_red(self, tmp_path):
        """判据 15（**行为级**红证）：workflow 在、判定本体不见了 ⇒ `exit 1` + `::error::`。

        ⛔ 不许静默 —— 否则「删掉判定本体」会变成一条永远绿的腿。
        """
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "post-merge-verify.yml").write_text("name: probe\n", encoding="utf-8")
        proc = subprocess.run(["bash", "-c", _bootstrap_guard_snippet()], cwd=str(tmp_path),
                              capture_output=True, text=True)
        out = (proc.stdout or "") + (proc.stderr or "")
        assert proc.returncode == 1, f"机制被拆掉半截 ⇒ 必须判红（实测 rc={proc.returncode}）：\n{out}"
        assert "::error::" in out, f"拆掉半截必须报 error：\n{out}"

    def test_write_scope_is_least_privilege(self):
        """判据 12：唯一写作用域 = `issues`（本腿没有 PR 对象 ⇒ 不给它 PR 写权限）。"""
        problems = _permission_problems(yaml.safe_load(WORKFLOW.read_text(encoding="utf-8")))
        assert problems == [], "\n".join(problems)

    def test_extra_write_scope_turns_it_red(self):
        """判据 12 的红证：加一个 `pull-requests: write` ⇒ 必红。"""
        doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        doc["permissions"]["pull-requests"] = "write"
        assert _permission_problems(doc) != [], "加了多余写权限之后判据没红 ⇒ 空断言"

    def test_does_not_relax_the_required_gate(self):
        """判据 13：本腿不得出现在 `pr-check.yml` 里（报告型 ≠ required，判据 6）。"""
        problems = _gate_relaxation_problems(PR_CHECK.read_text(encoding="utf-8"))
        assert problems == [], "\n".join(problems)

    def test_gate_relaxation_red_proof(self):
        """判据 13 的红证：在 pr-check 文本里塞一处本腿名字 ⇒ 必红。"""
        text = PR_CHECK.read_text(encoding="utf-8") + "\n# post-merge-verify\n"
        assert _gate_relaxation_problems(text) != [], "塞进去之后判据没红 ⇒ 空断言"

    def test_cost_reading_is_wall_clock_free(self, tmp_path):
        """判据 14：机器可读报告只报与负载无关的量（§23 G8）。"""
        repo = _fixture(tmp_path)
        _rc, _out, report = _run_leg(repo, "--lookback", "1")
        doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        problems = _wall_clock_problems(sorted(report.keys()), doc)
        assert problems == [], "\n".join(problems)

    def test_wall_clock_key_turns_it_red(self):
        """判据 14 的红证：往报告键里塞一个时长字段 ⇒ 必红。"""
        doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        assert _wall_clock_problems(["changed_count", "pytest_duration_seconds"], doc) != [], \
            "塞了时长字段却没红 ⇒ 空断言"
        assert _wall_clock_problems(["changed_count", "selected_count"], doc) == [], \
            "负控：正常读数不得被判红"