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
| 16 | **水位只取落在 main 上的成功 run**：查询必须含 `--branch main`（否则取到 PR head ⇒ 永不解析 ⇒ 永久冷启动窗口，issue #6312 真根因） | 变异：去掉 `--branch main` ⇒ 判据函数非空 |

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
import copy
import os
import re
import subprocess
import sys
import pytest
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


def _bash_code_lines(text: str) -> str:
    """只留**会执行的行**：去掉整行注释（`#` 开头，允许前导空白）。

    ⚠️ 必须剥（§23.8 **B1**「判据语料不含自身说明」的 bash 版）：workflow 的注释为了讲清病灶
    会**引用** `--branch main` 这个字面量 ⇒ 不剥就变成「注释里留着字样 = 判据绿」：把查询改回
    旧形态而注释不动 ⇒ 判据**不红**（**本判据第一版就是这么被自己的红证抓到的**）。
    """
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def _watermark_query_text(doc: dict) -> str:
    """取出**水位查询**所在那一步里**可执行**的 bash 原文（跑 `post_merge_verify.py` 且含 `gh run list`）。"""
    for step in _steps(doc):
        text = str(step.get("run", ""))
        if "gh run list" in text and "post_merge_verify.py" in text:
            return _bash_code_lines(text)
    return ""


def _watermark_problems(doc: dict) -> list[str]:
    """判据 16：水位只能由**落在 main 上**的成功 run 推进（issue #6312 的**真根因**）。

    病灶（2026-10-09 实测；本腿此前 10 次修复都没打中它）：原来的查询是
    `gh run list --workflow post-merge-verify.yml --status success` —— **不筛事件 / 分支** ⇒
    取到的是「最近一次成功的 run」，而本腿在 `pull_request: [opened, reopened]` 上也会跑 ⇒
    那个 `headSha` 是 **PR 的分支头**（实测 `463e511`，`headBranch=docs/6408-demo-seed-evidence`），
    **不在 main 检出里** ⇒ `git cat-file -e` **必失败** ⇒ **永远**退回 `HEAD~40`。

    这不是「首次运行的兜底」，而是**常驻状态**：每轮都跑满整个 40 提交窗口（本机实测
    `863` 变更文件 / `284` 条命中判据）⇒ 撞 job 上限被杀（实测 cancelled 样本 `914s`/`917s`
    ≈ `timeout-minutes: 15`）⇒ 更不可能成功 ⇒ **正反馈**（近 200 次 run：`12 success / 82 failure /
    98 cancelled`），且**水位永远停在原地**（最近一次成功 = 2026-10-06T06:17Z）。

    ⇒ 判据两条：① 查询必须含 `--branch main`；② 必须保留 `--status success`（水位只许被成功推进）。
    """
    text = _watermark_query_text(doc)
    if not text:
        return ["找不到水位查询所在的那一步（跑 `post_merge_verify.py` 且含 `gh run list`）⇒ 本判据无从判定"]
    problems = []
    if "--branch main" not in text:
        problems.append(
            "水位查询没有限定 `--branch main` ⇒ 会取到 `pull_request` run 的 **PR head**"
            "（不在 main 检出里）⇒ `git cat-file -e` 必失败 ⇒ **永久**退回 `HEAD~40` 冷启动窗口"
            "（issue #6312 实测根因；实测取到的 sha = `463e511`，headBranch = `docs/6408-demo-seed-evidence`）")
    if "--status success" not in text:
        problems.append(
            "水位查询丢了 `--status success` ⇒ 水位会被失败 / 取消的 run 推进 = **跳验**"
            "（方向必须是「多验」，见本 workflow 头部的水位口径）")
    return problems


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

    def test_watermark_query_is_scoped_to_main(self):
        """判据 16：水位只取**落在 main 上**的成功 run（issue #6312 的真根因）。"""
        problems = _watermark_problems(yaml.safe_load(WORKFLOW.read_text(encoding="utf-8")))
        assert problems == [], "\n".join(problems)

    def test_dropping_branch_filter_turns_the_watermark_red(self):
        """判据 16 的红证：把水位查询退回「不筛分支」的旧形态 ⇒ 必红（那就是 2026-10-09 之前的形状）。"""
        doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        needle = "--branch main --status success"
        mutated = False
        for job in (doc.get("jobs") or {}).values():
            for step in (job.get("steps") or []):
                if isinstance(step, dict) and needle in str(step.get("run", "")):
                    step["run"] = str(step["run"]).replace(needle, "--status success")
                    mutated = True
        if not mutated:
            raise AssertionError(f"变异点失配：找不到 `{needle}`（红证不得是空断言）")
        assert _watermark_problems(doc) != [], "去掉 `--branch main` 之后判据没红 ⇒ 空断言"

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

# ══════════════════════════════════════════════════════════════════════════════
# 判据 20~22（issue #6312，2026-10-08）：**上限必须按本腿自己的工作量上界算出来**
#
# 病灶（现取读数，不是估算）：本腿的窗口起点 = 「最近一次**成功** run 的 headSha」，而水位取不到就
# **一直退回** `LOOKBACK=40` ⇒ 本腿从未成功 ⇒ 每一轮都是同一个 40 提交窗口。实测该窗口命中
# **296 条判据 / 5652 条用例**（`--list-only --lookback 40` 的现取读数；现取目录里 371 个判据文件）
# ⇒ **正反馈**：越不成功 ⇒ 窗口越宽 ⇒ 越跑不完 ⇒ 越不成功。
#   掐死点在 run `37722027828` 的判定步日志里逐字可见：判定步 03:18:09 起、末行 03:18:24（in-leg 复现），
#   之后**静默 658s**，下一条即 `##[error]Process completed with exit code 143`（SIGTERM）03:29:22
#   ⇒ `failure` 结论、`updatedAt - createdAt` = 710s。
#   ⛔ 本 workflow 里**没有** step 级 `timeout`、`scripts/post_merge_verify.py` 里**没有** `timeout=` 包装
#     （两处都逐字复核过）⇒ 掐死它的声明方只有 job `timeout-minutes`。
#
# 🔴 **判据的形态（§23 G8：禁挂钟）**：钉的是**与负载无关的结构量** ——
# ① 判定面**并行跑**（`-n` = 常驻常量，且 ≥ 托管 runner 的核数）；② 上限 ≥ 本腿自己的工作量上界
#    （本腿在**一个** runner 上要干 `pr-check.yml` **两片**的活，两片各自 `timeout-minutes: 20`
#    ⇒ 上界 = 两片上限之和）；③ **判据面的单文件把脚本与 workflow 的结构声明绑在一起**
#    （「全量命令只许出现一次」的同族：同一条不变量在文本里长出第二份实现 ⇒ 红）。
# ⛔ 没有任何一条把**实测时长**写进判据（那正是降成本类固化禁止的挂钟固化）。
# ══════════════════════════════════════════════════════════════════════════════

#: 托管 runner 的核数（`runs-on: ubuntu-latest` = 4 vCPU；`pr-check.yml` 把 `-n 4` 与它对上）。
#: **不是实测时长** —— 它是 runner 规格这个结构量。
RUNNER_VCPUS = 4
#: `pr-check.yml` 里那两片 helper 腿的 job 名（现取用，不写死分片数）。
HELPER_JOB_NAME = "ci workflow helper unit tests"
#: 上限族的三段取值（现取自脚本文本，判据不复制它们的值 —— 只断言它们彼此自洽）。
_MIN_TIMEOUT_RE = re.compile(r"^\s*MIN_TIMEOUT_MINUTES\s*=\s*([A-Z_]+)\s*\*\s*(\d+)\s*$", re.M)
_BOUND_SHARDS_RE = re.compile(r"^\s*WORKLOAD_BOUND_SHARDS\s*=\s*(\d+)\s*$", re.M)
_PARALLEL_RE = re.compile(r"^\s*PARALLEL_WORKERS\s*=\s*(\d+)\s*$", re.M)

#: 上限真值源的环境变量名（**与 `scripts/post_merge_verify.py::TIMEOUT_ENV` 同名同义** ——
#: workflow 级 `env:` 里那一项就是它，job `timeout-minutes` 与判定步的读数都从它派生）。
TIMEOUT_ENV = "MIGAO_JOB_TIMEOUT_MINUTES"
#: 上限族依赖的**模块级**常量名（现取文本断言它们真的可被现取 = 不是塞在函数体里的局部量）。
SCRIPT_SOURCE_CONSTANTS = (
    "PEER_HELPER_JOB_TIMEOUT_MINUTES",
    "WORKLOAD_BOUND_SHARDS",
    "MIN_TIMEOUT_MINUTES",
    "PARALLEL_WORKERS",
)


def _peer_workload_bound(doc: dict) -> tuple[int, int, int]:
    """现取对等腿的工作量上界 ⇒ `(片数, 单片上限分钟, 上界分钟)`；取不到 ⇒ 抛。

    对等腿 = `pr-check.yml` 的 `ci workflow helper unit tests`（**同一个判定面、同一个 runner 规格**）：
    本腿在一个 runner 上要干它**两片**的活 ⇒ 上界 = `片数 × 单片 timeout-minutes`。
    """
    ci = yaml.safe_load(PR_CHECK.read_text(encoding="utf-8"))
    job = next((j for j in (ci.get("jobs") or {}).values()
                if str(j.get("name") or "").startswith(HELPER_JOB_NAME)), None)
    if job is None:
        raise AssertionError(f"{PR_CHECK.name} 里找不到 job `{HELPER_JOB_NAME}` —— "
                             "对等腿没了 ⇒ 上界无从计算（大声失败，不静默）")
    matrix = ((job.get("strategy") or {}).get("matrix") or {}).get("include") or []
    shards = [m for m in matrix if isinstance(m, dict) and m.get("shard")]
    minutes = int(job.get("timeout-minutes") or 0)
    if not shards or minutes <= 0:
        raise AssertionError(f"{HELPER_JOB_NAME} 的分片/上限取不到：shards={shards} / "
                             f"timeout-minutes={job.get('timeout-minutes')!r}")
    return len(shards), minutes, len(shards) * minutes


def _declared_workload_bound(doc: dict) -> str | None:
    """本腿 job 上**显式声明**上限的那一项的**原始值**；没有 ⇒ `None`。

    ⚠️ 取的是 **job key**（不是注释里的字样，§23.4 T2：判据不许被自己的说明文字喂红）。
    ⚠️ 取**原始文本**而不是解出来的数字：本腿的上限走 `${{ fromJSON(env.…) }}`（唯一真值源），
    `yaml.safe_load` 拿到的是那句表达式字符串，**数字由 GitHub 在运行期解** ⇒ 判据要判的是
    「它**从句法上**只能来自那个真值源」，解出来的数字由运行期自证 + 行为级红证承担。
    """
    jobs = doc.get("jobs") or {}
    if len(jobs) != 1:
        raise AssertionError(f"本 workflow 应当只有一个 job（实测 {list(jobs)}）—— 结构变了，判据需同批改")
    value = next(iter(jobs.values())).get("timeout-minutes")
    return str(value) if value is not None else None


def upper_bound_problems(doc: dict, script_text: str) -> list[str]:
    """**纯函数**：上限族的结构问题清单（空 = 成立）。

    全部与负载无关，三段：
      ① **上限是字面整数**，且 workflow 级 `env.MIGAO_JOB_TIMEOUT_MINUTES` **逐字等于它**
         （两边分叉 ⇒ 判定本体拿到的读数与 job 实际声明不是一个数 ⇒ 红）；
         —— 为什么必须是字面量：`timeout-minutes` 是全仓成本台账的读数字段
         （`tests/unit_ci_workflows/ci_cost_ledger.json` 的 `hard_kill_seconds` == `timeout-minutes × 60`，
         由 `tests/unit_ci_workflows/test_ci_cost_ledger.py` 逐条复比）⇒ 写 `${{ … }}` 表达式会让那套判据
         取不到整数（本单实测踩过）。**按仓库契约办**：表达式那条路被既有契约排除。
      ② **上界自洽**：上限 ≥ 本腿自己的工作量上界（= 对等腿 `片数 × 单片上限`）——
         「抬上限」**不是口味**：上界是**算出来的**，改小了就与本腿自己声明的工作量矛盾；
      ③ **脚本侧派生式**：`MIN_TIMEOUT_MINUTES = <具名常量> * <片数>` 逐字在位，片数 == 对等腿现取的片数
         （「单文件把脚本与 workflow 绑在一起」；改成裸数字 ⇒ 两边分叉 ⇒ 红）；
         且运行期自证**真的接线**（谓词在 + 在 `main()` 里被调）。
    """
    problems: list[str] = []
    declared = _declared_workload_bound(doc)
    if declared is None:
        return ["job 上**没有** `timeout-minutes` ⇒ 退回 GitHub 默认（360 分）⇒ 本族无从判定（fail-closed）"]
    if not declared.isdigit():
        problems.append(
            f"`timeout-minutes: {declared}` 不是字面整数 ⇒ 全仓成本台账（`ci_cost_ledger.json` 的 "
            "`hard_kill_seconds`）取不到值（本单实测：`ValueError: invalid literal for int()`）"
        )
    source = str((doc.get("env") or {}).get(TIMEOUT_ENV) or "")
    if not source.isdigit():
        problems.append(f"workflow 级 `env.{TIMEOUT_ENV}` 缺失或非整数（= {source!r}）"
                        "⇒ 判定本体拿不到上限读数（自证会退化成没数据可判）")
    elif declared.isdigit() and int(source) != int(declared):
        problems.append(
            f"上限两边分叉：`env.{TIMEOUT_ENV} = {source}` != job `timeout-minutes = {declared}` "
            "⇒ 判定本体自证的是另一个数（§18.6：环境静默即缺陷）"
        )
    shard_count, shard_minutes, bound = _peer_workload_bound(doc)
    if source.isdigit() and int(source) < bound:
        problems.append(
            f"上限 {source} < 本腿自己的工作量上界 {bound}"
            f"（对等腿 `{HELPER_JOB_NAME}` = {shard_count} 片 × 每片 {shard_minutes} 分 —— "
            "本腿在一个 runner 上要干两片的活）⇒ 撞上限被 SIGTERM（issue #6312 的形态，无结论）"
        )
    m = _MIN_TIMEOUT_RE.search(script_text)
    bound_decl = _BOUND_SHARDS_RE.search(script_text)
    if not m or not bound_decl:
        problems.append(f"`{SCRIPT_REL}` 里没有 `MIN_TIMEOUT_MINUTES = <常量> * <片数>` / "
                        f"`WORKLOAD_BOUND_SHARDS` 声明 ⇒ 上限没有可复算的派生式")
    else:
        if m.group(1) != "PEER_HELPER_JOB_TIMEOUT_MINUTES":
            problems.append(f"派生式的被乘项 = {m.group(1)!r} ⇒ 应当引对等腿的**具名常量**"
                            "（裸数字会让脚本与 workflow 各说各话）")
        if int(m.group(2)) != shard_count or int(bound_decl.group(1)) != shard_count:
            problems.append(f"派生式的片数 = {m.group(2)} / `WORKLOAD_BOUND_SHARDS` = {bound_decl.group(1)}"
                            f"，而 `{PR_CHECK.name}` 现取是 {shard_count} 片 ⇒ 两边分叉")
    # 运行期自证必须**真的接线**：谓词存在 + 在 `main()` 里真的被调（写出来没人读 = 死声明）
    if "declared_timeout_problem" not in script_text:
        problems.append(f"`{SCRIPT_REL}` 里没有运行期自证谓词（`declared_timeout_problem`）"
                        "⇒ 「上限 ≥ 上界」只是纸面约定，声明值不会流到判定本体")
    elif not re.search(r"^\s*problem\s*=\s*_check_declared_timeout\(\)\s*$", script_text, re.M):
        problems.append(f"`{SCRIPT_REL}` 里运行期自证**没在 `main()` 里被调用**"
                        "（缺 `problem = _check_declared_timeout()`）⇒ 声明值不再流到判定本体")
    return problems


def parallel_problems(script_text: str) -> list[str]:
    """**纯函数**：判定面**并行跑**的结构问题清单（空 = 成立）。

    为什么钉在 `SCRIPT_REL` 上：并行是**判定本体**的属性（判定步只调它一个脚本，判定面由它拉起），
    钉在 workflow 文本上会因为「判定步里根本没有 pytest 命令行」而变成空断言。
    """
    problems: list[str] = []
    if "PARALLEL_WORKERS" not in script_text:
        problems.append(f"`{SCRIPT_REL}` 里没有 `PARALLEL_WORKERS` ⇒ 判定面并行度无从判定")
    m = _PARALLEL_RE.search(script_text)
    if not m:
        problems.append(f"`{SCRIPT_REL}` 里 `PARALLEL_WORKERS` 不是模块级整数字面量 ⇒ 判据无从复算")
    elif int(m.group(1)) < RUNNER_VCPUS:
        problems.append(f"`PARALLEL_WORKERS = {m.group(1)}` < runner 的 {RUNNER_VCPUS} vCPU "
                        "⇒ 判定面跑不满一台 runner（本腿撞上限的形态）")
    # argv 必须真的把并行度接进 pytest（只声明常量不接线 = 死声明）
    if not re.search(r'"-n"\s*,\s*str\(PARALLEL_WORKERS\)', script_text):
        problems.append(f"`{SCRIPT_REL}` 没有把并行度接进 pytest argv（缺 `\"-n\", str(PARALLEL_WORKERS)`）"
                        "⇒ 常量是死声明，判定面仍串行")
    if "notes.append(XDIST_MISSING_NOTE)" not in script_text:
        problems.append("缺 xdist 时的降级路径没有**出声**说明（`notes.append(XDIST_MISSING_NOTE)` 缺）"
                        "⇒ 「慢回去」会静默发生（§23 G6：没跑 / 退化必须长得像没跑 / 退化）")
    return problems


class TestUpperBoundIsDerivedFromWorkload:
    """判据 20~21：上限是**算出来的**，且判定面真的并行跑（issue #6312）。"""

    def test_real_tree_satisfies_the_bound(self):
        doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        script_text = SCRIPT.read_text(encoding="utf-8")
        assert upper_bound_problems(doc, script_text) == [], "\n".join(upper_bound_problems(doc, script_text))
        assert parallel_problems(script_text) == [], "\n".join(parallel_problems(script_text))

    #: 变异锚点 ⇒（脚本文本, 期望红）。锚点**逐字只出现一次**（下方断言把关）。
    BOUND_MUTATIONS = {
        # ① 把上限改回病态值 15（本单的主诉：15 = 掐死点）
        "timeout_back_to_15": ("    timeout-minutes: 45", "    timeout-minutes: 15"),
        # ② 摘掉上限读数源（判定本体拿不到数 ⇒ 自证退化成没数据可判）
        "timeout_env_removed": ("  MIGAO_JOB_TIMEOUT_MINUTES: '45'\n", ""),
        # ③ 两边分叉（job 45 / env 30）⇒ 自证的是另一个数
        "timeout_env_diverges": ("  MIGAO_JOB_TIMEOUT_MINUTES: '45'", "  MIGAO_JOB_TIMEOUT_MINUTES: '30'"),
        # ④ 把派生式拉低到低于上界（`* 2` → `* 1` = 只算一片）
        "bound_shrunk_to_one_shard": ("MIN_TIMEOUT_MINUTES = PEER_HELPER_JOB_TIMEOUT_MINUTES * 2",
                                      "MIN_TIMEOUT_MINUTES = PEER_HELPER_JOB_TIMEOUT_MINUTES * 1"),
        # ⑤ 派生式改成裸数字（脚本与 workflow 各说各话）
        "bound_becomes_a_bare_number": ("MIN_TIMEOUT_MINUTES = PEER_HELPER_JOB_TIMEOUT_MINUTES * 2",
                                        "MIN_TIMEOUT_MINUTES = 45"),
        # ⑥ 运行期自证被摘掉（声明值不再流到判定本体 ⇒ 「上限 ≥ 上界」退回纸面约定）
        "self_check_unwired": ("    problem = _check_declared_timeout()", "    problem = None"),
    }
    #: 摘掉并行（本单的另一半）：判定面回到串行
    PARALLEL_MUTATIONS = {
        "parallel_flag_dropped": ('argv += ["-n", str(PARALLEL_WORKERS)]', "pass  # 并行被摘掉"),
        "parallel_workers_lowered": ("PARALLEL_WORKERS = 4", "PARALLEL_WORKERS = 1"),
        "xdist_note_removed": ("notes.append(XDIST_MISSING_NOTE)",
                               "notes.append('（降级说明被摘掉）')"),
    }
    #: 每种变异作用于**哪个**文件（上界是「两边绑在一起」的不变量，单改任一边都必须红）。
    BOUND_TARGETS = {
        "timeout_back_to_15": "workflow",
        "timeout_env_removed": "workflow",
        "timeout_env_diverges": "workflow",
        "bound_shrunk_to_one_shard": "script",
        "bound_becomes_a_bare_number": "script",
        "self_check_unwired": "script",
    }

    @pytest.mark.parametrize("name", sorted(BOUND_MUTATIONS))
    def test_each_bound_mutation_turns_it_red(self, name):
        """**红证**：上限变小 / 被摘掉 / 派生式分叉 / 自证没接线 —— 各能单独判红（§23.8 B3 同族：
        只改一侧 ⇒ 静默分叉，所以两侧各有一条）。"""
        old, new = self.BOUND_MUTATIONS[name]
        target = SCRIPT if self.BOUND_TARGETS[name] == "script" else WORKFLOW
        text = target.read_text(encoding="utf-8")
        assert text.count(old) == 1, f"变异锚点失配（{name}）：{old!r} 在 {target.name} 里出现 {text.count(old)} 次"
        mutated = text.replace(old, new, 1)
        assert mutated != text, "变异没落到文本上（红证会是空断言）"
        doc = yaml.safe_load(mutated if target is WORKFLOW else WORKFLOW.read_text(encoding="utf-8"))
        script_text = mutated if target is SCRIPT else SCRIPT.read_text(encoding="utf-8")
        assert upper_bound_problems(doc, script_text) != [], f"{name} 注入后判据没红 ⇒ 空断言"

    @pytest.mark.parametrize("name", sorted(PARALLEL_MUTATIONS))
    def test_each_parallel_mutation_turns_it_red(self, name):
        """**红证**：摘掉 `-n` / 把并行度降到 1 / 摘掉降级说明**那一处调用** —— 各能单独判红。"""
        old, new = self.PARALLEL_MUTATIONS[name]
        text = SCRIPT.read_text(encoding="utf-8")
        assert text.count(old) == 1, f"变异锚点失配（{name}）：{old!r} 出现 {text.count(old)} 次"
        mutated = text.replace(old, new, 1)
        assert mutated != text, "变异没落到文本上（红证会是空断言）"
        assert parallel_problems(mutated) != [], f"{name} 注入后判据没红 ⇒ 空断言"

    def test_script_declared_bound_constant_is_wired(self):
        """判据 21 的**接线**面：脚本里那三个常量必须**可现取**（不是塞在函数体里的局部量），
        且运行期自证必须**真的被调用**（`_check_declared_timeout()` 在 `main()` 里）——
        常量被写出来却没人读 = 死声明，判据不许把死声明读成达标。"""
        script_text = SCRIPT.read_text(encoding="utf-8")
        for name in ("PEER_HELPER_JOB_TIMEOUT_MINUTES", "WORKLOAD_BOUND_SHARDS", "MIN_TIMEOUT_MINUTES"):
            assert name in SCRIPT_SOURCE_CONSTANTS, f"常量 {name} 没登记进 `SCRIPT_SOURCE_CONSTANTS`"
        assert _MIN_TIMEOUT_RE.search(script_text) and _BOUND_SHARDS_RE.search(script_text), \
            "模块级常量取不到（被挪进函数体 / 改名）⇒ 判据退化成空断言"
        assert re.search(r"^\s*problem\s*=\s*_check_declared_timeout\(\)\s*$", script_text, re.M), \
            "运行期自证 `_check_declared_timeout()` 没在 `main()` 里被调用（声明值不再流到判定本体）"
        assert "declared_timeout_problem" in script_text, "纯函数式的判定谓词不存在"

    def test_comment_only_change_does_not_turn_red(self):
        """**对照读数**：只改注释 ⇒ **不**红（§23.4 T2：判据不许被自己的说明文字喂红）。"""
        doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        script_text = SCRIPT.read_text(encoding="utf-8")
        noisy_wf = WORKFLOW.read_text(encoding="utf-8").replace(
            "  verify:", "  # 注释里提到 timeout-minutes: 45 与 ci workflow helper unit tests 都不算实现\n  verify:", 1)
        noisy_script = script_text.replace(
            "PARALLEL_WORKERS = 4", "# 注释里提到 PARALLEL_WORKERS = 1 不算实现\nPARALLEL_WORKERS = 4", 1)
        assert upper_bound_problems(yaml.safe_load(noisy_wf), noisy_script) == [], \
            "只加注释却判红 ⇒ 判据在读原文"
        assert parallel_problems(noisy_script) == [], "只加注释却判红 ⇒ 判据在读原文"
        assert upper_bound_problems(doc, script_text) == [], "基线本身应当绿"

    def test_runtime_declared_timeout_self_check_goes_red(self, tmp_path):
        """**行为级红证**：给腿**真传**一个病态上限（15）⇒ `rc=1` + 具名归因；正常值 ⇒ 照旧跑。

        为什么还要这一层：上面几条只判**结构**（YAML 的值 + 脚本里的派生式）。这一条证明
        「声明值**真的**流到判定本体、且真的会拦」—— 否则「上限 ≥ 上界」只是一句纸面约定
        （`migao-acceptance` 的「修复必须重放」同族）。
        ⚠️ 用**外部子进程 + 真 env**（不走 pytest 的 monkeypatch）：xdist worker 里改 `os.environ`
        不保证传到 `subprocess` 拉起的解释器，那会让红证变成「测的是测试自己的注入」（假红/假绿）。
        """
        repo = _fixture(tmp_path)
        env = dict(os.environ)

        def run_with(timeout_value: str) -> tuple[int, str, dict]:
            env["MIGAO_JOB_TIMEOUT_MINUTES"] = timeout_value
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), "--repo", str(repo), "--list-only", "--lookback", "1",
                 "--json", str(repo / "selfcheck.json")],
                capture_output=True, text=True, cwd=str(repo), env=env)
            return proc.returncode, (proc.stdout or "") + (proc.stderr or ""), {}

        # ① 注入病态上限 15 ⇒ 必须 rc=1 且具名（点名病态值与上界）
        rc_bad, out_bad, _ = run_with("15")
        assert rc_bad == 1, f"注入 `timeout-minutes: 15` 后 rc={rc_bad}（应 1）—— 自证没接线：{out_bad[:300]!r}"
        upper = str(_leg().MIN_TIMEOUT_MINUTES)
        assert "15" in out_bad and upper in out_bad, \
            f"归因串没点名病态值与上界 {upper}（不可行动）：{out_bad[:300]!r}"
        # ② 对照读数：正常上限 ⇒ 不拦（`--list-only` 便宜，不真跑判据）
        rc_ok, out_ok, _ = run_with(upper)
        assert rc_ok == 0, f"正常上限下 `--list-only` rc={rc_ok}（应 0）：{out_ok[:300]!r}"
        # ③ 缺变量（本地手跑）⇒ 也不拦
        env.pop("MIGAO_JOB_TIMEOUT_MINUTES", None)
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--repo", str(repo), "--list-only", "--lookback", "1"],
            capture_output=True, text=True, cwd=str(repo), env=env)
        assert proc.returncode == 0, f"缺上限变量时 rc={proc.returncode}（本地手跑被误伤）：{proc.stdout[:200]!r}"


class TestWorkloadSurfaceIsBoundedByConstruction:
    """判据 22：判定面的**全量**是耗时上界（最坏窗口 = 全中），上限只需覆盖**它**。

    为什么不是空断言：判定面的**最坏形态**不是估算出来的 —— 它是「窗口里每个判据文件都被选中」，
    而选中规则是 `_referenced()` 做的**确定性** AST 匹配（`pr-check.yml` 那条 #5396 的形态：
    一条判据引用 45 个文件 ⇒ 一个文件就能让该判据入选）。⇒ 上界 = **全量判据面**，
    常数 = `(文件数 / 并行度) × 每文件工作量常数`，全部与负载无关。
    """

    #: 单 worker 每分钟能跑的**用例数**（**声明值，不是挂钟读数**）：判据面是纯 CPU / 子进程绑定，
    #: `pr-check.yml` 的 helper 腿已有 `-n 4` 的库存台账（`helper_leg_shape_ledger.json`）。
    #: 取值**保守于**该腿的实际吞吐（同一 runner 规格：一片 ≈3231 条 / 4 路 ≈5 分钟 ⇒ ≈160 条/分
    #: /worker；这里取 100）—— 判的是「上限与声明的工作量自洽」，不是实测量。
    TESTS_PER_WORKER_MINUTE = 100

    def test_declared_timeout_covers_the_worst_case_face(self):
        """最坏窗口 = 判定面**全中**；上限必须盖住「全量判据面 + 4 路并行」的工作量。

        复算（零 LLM、确定性）：`ceil(判据文件数 × 每文件用例数 / 并行度 / 每 worker 每分钟用例数)`
        —— 全部量都**现取**（文件数 = 目录现取；每文件用例数 = 冻结库存 / 文件数，取整往上），
        没有一个是实测时长。同时断言「上限 ≥ 声明的最小上限」（= 2 × 对等腿单片上限）——
        即 `timeout-minutes: 15` 那种「回到病态值」在本判据下**必红**。
        """
        doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        declared = _declared_workload_bound(doc)
        assert declared is not None and declared.isdigit(), f"job 上限不是字面整数：{declared!r}"
        source = str((doc.get("env") or {}).get(TIMEOUT_ENV) or "")
        assert source == declared, f"上限两边分叉：env={source!r} / job={declared!r}"
        files = sorted(p.name for p in (REPO / FACE_DIR).glob("test_*.py"))
        assert files, f"判定面为空：{REPO / FACE_DIR}（本判据无从判定 ⇒ 大声失败）"
        workers = int(_PARALLEL_RE.search(SCRIPT.read_text(encoding="utf-8")).group(1))
        inventory = json.loads((REPO / FACE_DIR / "helper_leg_shape_ledger.json").read_text(encoding="utf-8"))
        total_cases = int((inventory.get("frozen_inventory") or {}).get("collected_total") or 0)
        assert total_cases > 0, "冻结库存取不到（= 0）⇒ 本判据会退化成空断言（fail-closed 判红）"
        cases_per_file = -(-total_cases // len(files))
        need = -(-(len(files) * cases_per_file) // (workers * self.TESTS_PER_WORKER_MINUTE))
        _, _, peer_bound = _peer_workload_bound(doc)
        assert int(source) >= max(need, peer_bound), (
            f"上限 {source} 盖不住工作量：判定面 {len(files)} 个判据文件 × "
            f"{cases_per_file} 用例/文件 / {workers} 路并行 / 每 worker 每分钟 {self.TESTS_PER_WORKER_MINUTE} 条 "
            f"⇒ 需要 {need} 分钟；且必须 ≥ 对等腿两片之和 {peer_bound} 分钟（issue #6312）"
        )

    def test_cost_ledger_hard_kill_ceiling_stays_in_sync(self):
        """**与既有契约对齐**：`timeout-minutes` 是全仓成本台账的读数字段 ⇒ 台账必须同步更新。

        仓库契约（`tests/unit_ci_workflows/test_ci_cost_ledger.py::test_hard_kill_ceiling_matches_workflow_verbatim`）：
        `ci_cost_ledger.json` 的 `hard_kill_seconds` == 现取 `timeout-minutes × 60`。
        本腿抬上限 ⇒ **必须**同批把该条更新（否则那条判据红 —— 本单实测踩过：台账里还写着 900）。
        为什么这一条放在这里：抬上限的人只会打开本文件与 workflow，不一定会想到成本台账 ——
        把「抬起必须同步」钉在**同一个判据文件**里，才拦得住下一次。
        """
        doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        declared = _declared_workload_bound(doc)
        ledger = json.loads((REPO / FACE_DIR / "ci_cost_ledger.json").read_text(encoding="utf-8"))
        entry = next((leg for leg in ledger.get("legs") or []
                      if leg.get("workflow") == WORKFLOW.name and leg.get("job") == "verify"), None)
        assert entry and entry.get("hard_kill_seconds") == int(declared) * 60, (
            f"成本台账里没有 `{WORKFLOW.name}::verify` 条目（⇒ 抬上限没有**承接面**，fail-closed），"
            f"或它的 `hard_kill_seconds` = {(entry or {}).get('hard_kill_seconds')} != 现取 `timeout-minutes "
            f"{declared} × 60` = {int(declared) * 60} ⇒ 那条既有判据会红"
            f"（修法：把该条改成 {int(declared) * 60} 并把 `hard_kill_source` 写成现取的 `timeout-minutes`）"
        )
        assert str(declared) in str(entry.get("hard_kill_source") or ""), (
            f"`hard_kill_source` 没说清上限从哪来（现为 {entry.get('hard_kill_source')!r}）"
        )


def test_deps_and_judging_step_share_one_interpreter():
    import re
    from pathlib import Path
    import yaml

    wf = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "post-merge-verify.yml"
    doc = yaml.safe_load(wf.read_text(encoding="utf-8"))
    steps = doc["jobs"]["verify"]["steps"]
    install = next((s for s in steps if "pip install" in str(s.get("run") or "")), None)
    judging = next((s for s in steps if "post_merge_verify.py" in str(s.get("run") or "")), None)
    # ⚠️ **不用「存在性」弱断言**（只证明"有东西"、不触业务数据）——本仓的弱断言账本判据会当场判红
    # （本 PR 第一版就是这么被 CI 抓到的）。⚠️ 连注释里都**不能写出那个模式的字面文本**：
    # 扫描器是**按原文正则**扫的 ⇒ 注释里的示例会把自己喂成一处弱断言（§23.8 B1 同族）。
    # 改成对**结构结论**断言（下面这条）。
    missing = [label for label, step in (("Install deps（装依赖）", install),
                                         ("判定（跑判据）", judging)) if step is None]
    assert missing == [], f"workflow 结构变了 ⇒ 找不到这些步（判据需同步）：{missing}"

    install_run = str(install["run"])
    judging_run = str(judging["run"])

    # ① 装依赖必须**显式用某个解释器变量**（`"$PY" -m pip install …`），不许裸 `pip install`
    #    —— 裸 pip 正是「装到 A、跑到 B」的分叉点。
    assert re.search(r'"?\$[A-Z_]+"?\s+-m\s+pip\s+install', install_run), (
        "装依赖步必须显式用解释器变量（`\"$PY\" -m pip install …`），不得裸 `pip install`：\n"
        + install_run
    )
    # ② 该变量必须经 `$GITHUB_ENV` 传给后续步骤（否则判定步拿不到同一个解释器）
    assert "GITHUB_ENV" in install_run and "MIGAO_PY" in install_run, (
        "装依赖步必须把解释器经 `$GITHUB_ENV` 交给后续步骤（`MIGAO_PY`）：\n" + install_run
    )
    # ③ 判定步必须用同一个变量，且**显式 --python**（脚本默认取 `sys.executable`，但显式传更不容易分叉）
    assert "MIGAO_PY" in judging_run, "判定步没有用装依赖时定下的解释器（MIGAO_PY）：\n" + judging_run
    assert "--python" in judging_run, f"判定步没显式传 `--python`：{judging_run[:200]}"
    # ④ 判定步**不得**裸调 `python3 scripts/post_merge_verify.py`（改前的形态）
    assert not re.search(r"(^|\s)python3\s+scripts/post_merge_verify\.py", judging_run, re.M), (
        "判定步又在裸调 `python3 scripts/post_merge_verify.py` ⇒ 解释器可分叉（#5434）：\n" + judging_run
    )


def test_judging_step_fails_loudly_when_the_interpreter_lacks_pytest():
    """环境是我们的责任 ⇒ 缺 pytest 要**响亮地失败**（可归因），不许退化成不可归因的 rc=3。"""
    from pathlib import Path

    text = (Path(__file__).resolve().parents[2] / ".github" / "workflows"
            / "post-merge-verify.yml").read_text(encoding="utf-8")
    assert 'import pytest, yaml' in text and "::error::" in text, (
        "判定步缺「解释器前置断言」（`import pytest, yaml` + `::error::` 指明根因）"
    )


# ── main 侧漂移兜底（2026-09-25 实测缺口）────────────────────────────────────

def _drift_backstop_problems(doc: dict) -> list[str]:
    """纯函数：漂移兜底步的结构问题清单（空 = 成立）。变异样本据此判红（`#6144 §1-C1`）。

    判据的要点（顺序即重要性）：
      ① 恰好一步（缺 ⇒ 没兜底；多 ⇒ 判据要同步）；
      ② `scripts/drift_audit.py` 在位；
      ③ 🔴 **必须带 `--check`** —— 这是本单的主诉：`drift_audit.py` 的 `tri_state()` 第一行
         是 `if not check: return 0` ⇒ **不带 `--check` 时该脚本永远 exit 0**（模块头自述）
         ⇒ 本步**永不失败**（「跑了但不判」= 死步）。旧断言只查 `exit ${RC}` 在位，
         而 `exit 0` 同样满足它 ⇒ **空断言**（本条就是被那个空断言放过去的）。
      ④ 退出码要带出去（`exit ${RC}`）。
    顺序与「在判定步之前」由调用方另行断言。
    """
    problems: list[str] = []
    steps = (doc.get("jobs") or {}).get("verify", {}).get("steps") or []
    hits = [s for s in steps if s.get("name") and "漂移" in str(s["name"])]
    if len(hits) != 1:
        return [f"「漂移审计兜底」步必须**恰好一个**，实测 {len(hits)} 个"]
    run = str(hits[0].get("run") or "")
    if "scripts/drift_audit.py" not in run:
        problems.append(f"该步没跑漂移审计：{run[:200]}")
    # `--check` 必须是**真参数**（行内出现 `--check`），不是注释里的字样：
    # 用 `re.search` 找 `drift_audit.py` 那一行的参数串。
    cmd_lines = [ln for ln in run.split("\n") if "drift_audit.py" in ln]
    if not any(re.search(r"--check(?![-\w])", ln) for ln in cmd_lines):
        problems.append(
            "该步**没有**真传 `--check` ⇒ `drift_audit.py` 的 `tri_state()` 在 "
            "`if not check: return 0` 处直接返回 0 ⇒ **本步永不失败**（死步，#6144 §1-C1）："
            + run[:200]
        )
    if "exit ${RC}" not in run and "exit $RC" not in run:
        problems.append(
            "该步必须把 drift_audit 的**退出码**带出去（非 0 ⇒ 本步失败），否则等于「跑了但不判」："
            + run[:200]
        )
    return problems


def test_main_side_has_a_drift_audit_backstop():
    """本腿必须带**漂移审计兜底**步（否则"PR 带进 main 的漂移"没有 CI 兜底）。

    现场：#5502 的包实测发现 `tests/unit_ci_workflows/test_drift_audit_contract.py
    ::test_real_repo_audit_is_green_on_current_tree` 在 **CI 的浅检出**里**自己 skip**
    （`origin/main` 不可解析）⇒ 一次合并在 main 上带进了**面内阻塞**漂移，**只在有人本机跑时才发现**。
    本腿全历史检出 ⇒ 这一步能真判，且**非 0 退出码要带出去**（0 通过 / 1 判红 / 3 不可判）。

    🔴 `#6144 §1-C1` 加严：**必须真传 `--check`**。旧断言（只查 `exit ${RC}`）是**空断言** ——
    不带 `--check` 的形态同样满足它，而那种形态下 `drift_audit.py` **永远 exit 0**（`tri_state()`
    第一条 `if not check: return 0`）⇒ 本步永不失败。红证见
    `test_red_proof_dropping_check_makes_it_red`。
    """
    wf = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "post-merge-verify.yml"
    doc = yaml.safe_load(wf.read_text(encoding="utf-8"))
    problems = _drift_backstop_problems(doc)
    assert problems == [], "漂移兜底步结构不成立：\n" + "\n".join(f"  · {p}" for p in problems)
    steps = doc["jobs"]["verify"]["steps"]
    step = [s for s in steps if s.get("name") and "漂移" in str(s["name"])][0]
    names = [str(s.get("name") or "") for s in steps]
    assert names.index(str(step["name"])) < names.index("判定（定向跑判据面）"), (
        "漂移兜底应排在「判定（定向跑判据面）」**之前**（先做便宜的全局兜底，再跑定向判据面）"
    )


def test_red_proof_dropping_check_makes_it_red():
    """注入红证（`#6144 §1-C1`）：把 `--check` 摘掉 ⇒ 判据**必红**。

    这正是修前形态（`python3 scripts/drift_audit.py` + `exit ${RC}`）：它满足旧断言、
    而本步永不失败。注入必须**真命中**（命中数 ≠ 1 就断言失败，防「变异没生效」的空断言）。
    """
    doc = copy.deepcopy(yaml.safe_load(WORKFLOW.read_text(encoding="utf-8")))
    steps = doc["jobs"]["verify"]["steps"]
    hit = 0
    for s in steps:
        run = str(s.get("run") or "")
        if "scripts/drift_audit.py --check" in run:
            s["run"] = run.replace("scripts/drift_audit.py --check", "scripts/drift_audit.py")
            hit += 1
    assert hit == 1, f"注入点命中 {hit} 处（应为 1）—— 变异没生效，红证失效"
    problems = _drift_backstop_problems(doc)
    assert any("--check" in p for p in problems), (
        f"摘掉 `--check` 后判据未变红 ⇒ 该断言是空断言：{problems!r}"
    )


def test_red_proof_dropping_exit_rc_makes_it_red():
    """注入红证②：把 `exit ${RC}` 摘掉 ⇒ 判据必红（「跑了但不带退出码」也等于不判）。"""
    doc = copy.deepcopy(yaml.safe_load(WORKFLOW.read_text(encoding="utf-8")))
    hit = 0
    for s in doc["jobs"]["verify"]["steps"]:
        run = str(s.get("run") or "")
        if "scripts/drift_audit.py" in run:  # 只钉漂移兜底那一步（别的步也有 exit ${RC}）
            s["run"] = run.replace("exit ${RC}", "exit 0")
            hit += 1
    assert hit == 1, f"注入点命中 {hit} 处（应为 1）—— 变异没生效，红证失效"
    problems = _drift_backstop_problems(doc)
    assert any("退出码" in p for p in problems), f"应判红却得到 {problems!r}"


# ── 类级固化：凡跑 `gh` 的步都必须带 token（2026-09-25 自伤实证）────────────────

def test_every_gh_using_step_declares_a_token():
    """本 workflow 里**任何**跑 `gh` 的步骤都必须声明 `GH_TOKEN`，否则 `gh` 未认证。

    现场（自伤，2026-09-25）：我加的「零新开核验」步跑了 `gh issue list` 却**没带 token** ⇒
    该步退出码 **3「无法判定」** ⇒ **本腿从那一刻起每次合并都红**（实测：11:55 success →
    12:01/12:05/12:10/12:14 连续 failure，时间点正是该步被引入的那一刻）。
    这条**不是**只钉那一步：凡是本 workflow 里 `run` 含 `gh ` 的步，都得有 `GH_TOKEN`
    （env 里显式写，或该步引用了 workflow 级 `env`）。
    """
    import re
    import yaml
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    wf = root / ".github" / "workflows" / "post-merge-verify.yml"
    doc = yaml.safe_load(wf.read_text(encoding="utf-8"))
    job = doc["jobs"]["verify"]
    wf_env = {**(doc.get("env") or {}), **(job.get("env") or {})}

    # ⚠️ **必须覆盖"间接调 gh"**（我这条判据第一版就是栽在这）：那个红掉的步，`run` 里根本没有字面
    # `gh ` —— 它调的是 `python3 scripts/issue_lifecycle.py check-new-issues`，而 gh 在那个脚本**内部**。
    # ⇒ 口径 = ① 直接出现 gh 调用；② **调用了"自己会调 gh 的仓内脚本"**（清单**现取**：读脚本源码，
    #    不写死清单，否则下一个人新加一个 gh 脚本又漏）。两类都要求声明 GH_TOKEN。
    gh_scripts = set()
    for f in [*root.glob("scripts/*.py"), *root.glob(".github/scripts/*.py")]:
        src = f.read_text(encoding="utf-8", errors="ignore")
        if re.search(r"gh_bin\(|subprocess\.[a-z]+\(\s*\[?\s*[\"']gh[\"']|github-actions", src):
            gh_scripts.add(f.name)

    missing = []
    for step in job["steps"]:
        run = str(step.get("run") or "")
        direct = bool(re.search(r"(^|\s|&&|\|\||;|\$\()gh\s", run))
        indirect = any(name in run for name in gh_scripts)
        if not (direct or indirect):
            continue
        env = {**wf_env, **(step.get("env") or {})}
        if "GH_TOKEN" not in env:
            why = "直接调 gh" if direct else f"调用会调 gh 的脚本（{sorted(gh_scripts)} 之一）"
            missing.append(f"{step.get('name') or '?'} —— {why}")
    assert gh_scripts or True, ""  # 保持变量被使用（清单为空时本判据自动退化为只管直接调用）
    assert missing == [], (
        "这些步会（直接或间接）跑 `gh` 却没带 GH_TOKEN（未认证 ⇒ 退出码 3「无法判定」⇒ 本腿每次合并都红）：\n  "
        + "\n  ".join(missing)
    )


# ══════════════════════════════════════════════════════════════════════════════
# 判据 16~18（台账 `FM-E21`）：**判红出口的体积预算** —— 三处出口都不能被输出压垮
#   实测 2026-09-28：完整 pytest 输出现取 **17613k** > GitHub 的 step summary 上限 **1024k**
#   ⇒ 整份摘要上传被拒（`$GITHUB_STEP_SUMMARY upload aborted … got 17613k`）
#   ⇒ 「红了但看不到红在哪」；而承接面（P1 值班 issue）的 body 上限 **65536 字符**
#   ⇒ 超了会**开不出值班单**（判红无人接盘）。三处出口 = stdout 失败清单 / 摘要摘录 / 承接单摘录。
# ══════════════════════════════════════════════════════════════════════════════

SUMMARY_HARD_LIMIT = 1024 * 1024      # GitHub step summary 硬上限（1 MiB）
ISSUE_BODY_HARD_LIMIT = 65536         # GitHub issue body 上限（字符）
FAILURE_LIST_NEEDLE = "grep -E '^(FAILED|ERROR) '"
EXCERPT_FILE = "/tmp/post-merge-verify-excerpt.txt"
ISSUE_EXCERPT_FILE = "/tmp/post-merge-verify-issue-excerpt.txt"
BUDGET_RE = re.compile(r"^\s*(SUMMARY_EXCERPT_BYTES|ISSUE_EXCERPT_BYTES|FAILED_MAX)=(\d+)\s*$", re.MULTILINE)
BUDGET_STEP_MARKER = "GITHUB_STEP_SUMMARY"
HOOK_STEP_MARKER = "gh issue list --state open --search"


def _budget_job(doc: dict) -> dict:
    jobs = doc.get("jobs") or {}
    assert len(jobs) == 1, f"本 workflow 应当只有一个 job（实测 {list(jobs)}）—— 结构变了，判据需同批改"
    return next(iter(jobs.values()))


def _marker_run(doc: dict, marker: str) -> str:
    """含 `marker` 的那个 step 的 `run` 文本，**去掉整行注释**（注释里的提及不算实现）。"""
    for step in (_budget_job(doc).get("steps") or []):
        run = str(step.get("run") or "")
        if marker in run:
            return "\n".join(ln for ln in run.splitlines() if not ln.strip().startswith("#"))
    return ""


def summary_budget_problems(doc: dict) -> list[str]:
    """**纯函数**：三处判红出口各带**显式体积预算**，且预算值真的在硬上限之内。"""
    problems: list[str] = []
    judging = _marker_run(doc, BUDGET_STEP_MARKER)
    if not judging:
        return ["找不到写 step summary 的 step（结构变了 ⇒ 本判据需同批改）"]
    budgets = {m.group(1): int(m.group(2)) for m in BUDGET_RE.finditer(judging)}
    missing = [k for k in ("SUMMARY_EXCERPT_BYTES", "ISSUE_EXCERPT_BYTES", "FAILED_MAX") if k not in budgets]
    if missing:
        problems.append(f"缺体积预算常量：{missing}（判红出口必须自带显式预算）")
    else:
        if budgets["SUMMARY_EXCERPT_BYTES"] > SUMMARY_HARD_LIMIT:
            problems.append(f"SUMMARY_EXCERPT_BYTES={budgets['SUMMARY_EXCERPT_BYTES']} > step summary 上限 "
                            f"{SUMMARY_HARD_LIMIT} ⇒ 摘录本身仍会被拒（这就是实测形态）")
        if budgets["ISSUE_EXCERPT_BYTES"] > ISSUE_BODY_HARD_LIMIT:
            problems.append(f"ISSUE_EXCERPT_BYTES={budgets['ISSUE_EXCERPT_BYTES']} > issue body 上限 "
                            f"{ISSUE_BODY_HARD_LIMIT} ⇒ 承接单开不出来")
    if 'tail -c "$SUMMARY_EXCERPT_BYTES"' not in judging:
        problems.append("摘要没有按 SUMMARY_EXCERPT_BYTES 截断（`tail -c` 缺）⇒ 完整输出会压垮摘要上传")
    if ISSUE_EXCERPT_FILE not in judging:
        problems.append(f"没有为承接单生成限长摘录（{ISSUE_EXCERPT_FILE}）")
    if FAILURE_LIST_NEEDLE not in judging:
        problems.append("失败清单没打到 stdout（缺 `grep -E '^(FAILED|ERROR) '`）⇒ 判红不可 grep")
    elif 'head -n "$FAILED_MAX"' not in judging:
        problems.append('失败清单没有条数上限（缺 `head -n "$FAILED_MAX"`）⇒ 清单自身也会压垮输出')
    if 'echo "ISSUE_EXCERPT_BYTES=$ISSUE_EXCERPT_BYTES" >> "$GITHUB_ENV"' not in judging:
        problems.append("预算常量没有经 `$GITHUB_ENV` 传给承接单那一步 ⇒ **兜底路径**只能读未限长文件")
    hook = _marker_run(doc, HOOK_STEP_MARKER)
    if not hook:
        problems.append("找不到判红出口（P1 值班钩子）step（结构变了 ⇒ 本判据需同批改）")
    elif "cat /tmp/post-merge-verify.txt" in hook:
        problems.append("承接单仍在读**完整**输出（`cat /tmp/post-merge-verify.txt`）⇒ 超 issue body 上限、开不出单")
    elif ISSUE_EXCERPT_FILE not in hook:
        problems.append(f"承接单没有用限长摘录文件（{ISSUE_EXCERPT_FILE}）")
    # 🔴 验收 P2-2：**兜底路径也必须限长** —— 原兜底直接 `cat` 摘录（200000 B）⇒ 仍会超 65536
    if "cat /tmp/post-merge-verify-excerpt.txt" in hook:
        problems.append("承接单的**兜底**路径仍直接 `cat` 摘录（200000 B > issue body 上限 65536）")
    elif 'tail -c "${ISSUE_EXCERPT_BYTES:-30000}" /tmp/post-merge-verify-excerpt.txt' not in hook:
        problems.append("承接单兜底路径没有限长（缺 `tail -c \"${ISSUE_EXCERPT_BYTES:-30000}\"`）")
    return problems


class TestVolumeBudgets:
    def test_real_workflow_has_the_three_budgets(self):
        doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        assert summary_budget_problems(doc) == [], "\n".join(summary_budget_problems(doc))

    BUDGET_MUTATIONS = {
        "drop_summary_tail": (
            'tail -c "$SUMMARY_EXCERPT_BYTES" /tmp/post-merge-verify.txt > /tmp/post-merge-verify-excerpt.txt',
            'cp /tmp/post-merge-verify.txt /tmp/post-merge-verify-excerpt.txt'),
        "summary_over_limit": ("SUMMARY_EXCERPT_BYTES=200000", "SUMMARY_EXCERPT_BYTES=2000000"),
        "issue_over_limit": ("ISSUE_EXCERPT_BYTES=30000", "ISSUE_EXCERPT_BYTES=999999"),
        "drop_failure_list": ("grep -E '^(FAILED|ERROR) ' /tmp/post-merge-verify.txt", "true  # 清单被删"),
        "drop_failure_cap": ('head -n "$FAILED_MAX" \\\n            > /tmp/post-merge-verify-failed.txt',
                             '> /tmp/post-merge-verify-failed.txt'),
        "hook_fallback_uncapped": ('tail -c "${ISSUE_EXCERPT_BYTES:-30000}" /tmp/post-merge-verify-excerpt.txt',
                                   "cat /tmp/post-merge-verify-excerpt.txt"),
        "hook_reads_full_output": ("cat /tmp/post-merge-verify-issue-excerpt.txt 2>/dev/null \\",
                                   "cat /tmp/post-merge-verify.txt 2>/dev/null \\"),
    }

    @pytest.mark.parametrize("mutation", sorted(BUDGET_MUTATIONS))
    def test_each_budget_mutation_turns_it_red(self, mutation):
        """**红证（判据 16~18）**：逐条破坏三处出口 ⇒ 各能单独变红（**预算值是判据的一部分**）。"""
        text = WORKFLOW.read_text(encoding="utf-8")
        old, new = self.BUDGET_MUTATIONS[mutation]
        assert text.count(old) == 1, f"变异锚点失配（{mutation}）：{old!r}"
        mutated = text.replace(old, new, 1)
        assert mutated != text, "变异没落到文本上（红证会是空断言）"
        assert summary_budget_problems(yaml.safe_load(mutated)) != [], f"{mutation} 注入后判据没红 ⇒ 空断言"

    def test_comment_only_change_does_not_turn_red(self):
        """**对照读数**：只加注释（文字里出现 needle 也不算实现）⇒ **不**红。"""
        text = WORKFLOW.read_text(encoding="utf-8")
        assert summary_budget_problems(yaml.safe_load(text)) == [], "基线本身应当绿"
        noisy = text.replace("    steps:", "    # 注释里提到 tail -c \"$SUMMARY_EXCERPT_BYTES\" 与 "
                                          "grep -E '^(FAILED|ERROR) ' 都不算实现\n    steps:", 1)
        assert noisy != text, "注释注入没生效"
        assert summary_budget_problems(yaml.safe_load(noisy)) == [], "只加注释却判红 ⇒ 判据在读原文"


# ══════════════════════════════════════════════════════════════════════════════
# 判据 19（**行为级**，`FM-E21` 的第二半）：把 workflow 里那两段 shell **抠出来真跑**，量真实字节数
#   为什么还要这一层：上面 16~18 只判「结构 + 值域」（常量在不在、值在不在限内）。独立验收指出
#   「`FM-E21` 的通过在**生产**上没有重放（没遇到 17.6MB 输出的场景）」⇒ 本判据把判定步的预算段
#   与钩子的 body 拼装段在沙箱里执行，把「摘录 / 清单 / 承接单 body 都在限内」变成**行为读数**，
#   并配「换回 `cat` ⇒ 真的溢界」的红证（否则仍是纸面判据）。
# ══════════════════════════════════════════════════════════════════════════════

BUDGET_BLOCK_START = "FAILED_MAX=40"
BUDGET_BLOCK_END = 'if [ "$RC" = "3" ]; then'
HOOK_BLOCK_START = "BODY=$(mktemp)"
HOOK_BLOCK_END = "exit 0"          # 连 gh 调用段一起（body 组装只是前半段）
GH_EXPR_RE = re.compile(r"\$\{\{[^}]+\}\}")


def _step_run(marker: str) -> str:
    """含 `marker` 的那个 step 的 `run` 文本（锚点缺失 ⇒ 大声失败）。"""
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for step in _budget_job(doc).get("steps") or []:
        run = str(step.get("run") or "")
        if marker in run:
            return run
    raise AssertionError(f"找不到含 {marker!r} 的 step（结构变了 ⇒ 本判据需同批改）")


def _slice(run: str, start: str, end: str, *, include_end: bool = False) -> str:
    """抠出 `[start, end)`；`include_end=True` 时**连 end 行一起**（`{ … } > file` 这种成对结构必须带上）。"""
    assert start in run, f"锚点缺失：{start!r}"
    assert end in run, f"锚点缺失：{end!r}"
    i = run.index(start)
    j = run.index(end, i)
    return run[i:(j + len(end)) if include_end else j]


def _sandbox(tmp: Path) -> Path:
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "summary.md").write_text("", encoding="utf-8")
    return tmp


def _bash(script: str, cwd: Path, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", script], cwd=str(cwd), capture_output=True, text=True, env=env)


def _big_output(tmp: Path, *, noise: int = 60000, failed: int = 40) -> None:
    """造一份「像真实判红那样大」的输出：> 1MiB，且带可 grep 的 `FAILED` 行。"""
    lines = [f"pytest noise line {i}" for i in range(noise)]
    lines += [f"FAILED tests/unit_ci_workflows/test_case_{i}.py::test_x - assert {i} == {i + 1}"
              for i in range(failed)]
    (tmp / "post-merge-verify.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _budget_shell(tmp: Path) -> tuple[Path, str, dict]:
    tmp = _sandbox(tmp)
    _big_output(tmp)
    script = _slice(_step_run("FAILED_MAX="), BUDGET_BLOCK_START, BUDGET_BLOCK_END)
    script = script.replace("/tmp/", f"{tmp}/")
    env = {**os.environ, "GITHUB_STEP_SUMMARY": str(tmp / "summary.md"), "GITHUB_ENV": str(tmp / "env"),
           "SEEN": "3", "ACTED": "2", "EVENT": "pull_request", "BASE": "abc1234",
           "BASE_SOURCE": "test", "RC": "1"}
    return tmp, script, env


class TestBudgetBehaviour:
    def test_summary_list_and_excerpts_are_byte_bounded(self, tmp_path):
        tmp, script, env = _budget_shell(tmp_path / "sandbox")
        proc = _bash("set -u\n" + script, tmp, env)
        assert proc.returncode == 0, proc.stderr[-600:]

        summary = (tmp / "summary.md").stat().st_size
        assert summary <= SUMMARY_HARD_LIMIT, f"摘要 {summary} B 超过 GitHub 上限 {SUMMARY_HARD_LIMIT}"
        text = (tmp / "summary.md").read_text(encoding="utf-8")
        assert "仅附**尾部**" in text, "摘要没有声明「仅附尾部」（读者会以为看到了全文）"

        excerpt = (tmp / "post-merge-verify-excerpt.txt").stat().st_size
        assert excerpt == 200000, f"摘要摘录应等于 SUMMARY_EXCERPT_BYTES（实测 {excerpt}）"
        issue_excerpt = (tmp / "post-merge-verify-issue-excerpt.txt").stat().st_size
        assert issue_excerpt <= ISSUE_BODY_HARD_LIMIT, f"承接单摘录 {issue_excerpt} 超过 issue body 上限"

        failed_list = (tmp / "post-merge-verify-failed.txt").read_text(encoding="utf-8").splitlines()
        assert len(failed_list) == 40, f"失败清单必须被 head -n 限到 40 条（实测 {len(failed_list)}）"
        assert "FAILED tests/unit_ci_workflows/test_case_0.py" in proc.stdout, \
            "失败清单必须打到 **stdout**（判红要可 grep，不能只躺在摘要里）"

    def test_unbounded_variant_really_overflows(self, tmp_path):
        """**红证（判据 19）**：把 `tail -c` 换回 `cat` ⇒ 摘要**真的**溢界（证明上面那条不是恒真）。"""
        tmp, script, env = _budget_shell(tmp_path / "sandbox-mutant")
        mutated = script.replace('tail -c "$SUMMARY_EXCERPT_BYTES"', "cat", 1)
        assert mutated != script, "锚点失配（没换成 cat）"
        proc = _bash("set -u\n" + mutated, tmp, env)
        assert proc.returncode == 0, proc.stderr[-400:]
        summary = (tmp / "summary.md").stat().st_size
        assert summary > SUMMARY_HARD_LIMIT, (
            f"换回 `cat` 之后摘要仍只有 {summary} B ⇒ 上面那条「≤ 上限」不是这条截断挣来的（空断言）")


class TestHookBodyBehaviour:
    def _hook_sandbox(self, tmp: Path, *, fallback: str) -> tuple[Path, str, dict]:
        tmp = _sandbox(tmp)
        # 只放**摘要摘录**（200000 B），不放 issue 摘录 ⇒ 强制走**兜底路径**
        (tmp / "post-merge-verify-excerpt.txt").write_text("x" * 200000, encoding="utf-8")
        shim = tmp / "bin"
        shim.mkdir(exist_ok=True)
        gh = shim / "gh"
        gh.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$GH_LOG"\nexit 0\n', encoding="utf-8")
        gh.chmod(0o755)
        hook = _slice(_step_run("gh issue list --state open --search"), HOOK_BLOCK_START, HOOK_BLOCK_END,
                      include_end=True)
        hook = GH_EXPR_RE.sub("stub", hook)                     # GitHub 表达式在沙箱里没有值
        hook = hook.replace("/tmp/", f"{tmp}/").replace("BODY=$(mktemp)", f"BODY={tmp}/body.txt")
        if fallback == "cat":
            hook = hook.replace('tail -c "${ISSUE_EXCERPT_BYTES:-30000}"', "cat", 1)
        env = {**os.environ, "PATH": f"{shim}:{os.environ.get('PATH', '')}",
               "GH_LOG": str(tmp / "gh.log"), "ISSUE_EXCERPT_BYTES": "30000",
               "GITHUB_TOKEN": "stub"}
        return tmp, hook, env

    def test_issue_body_stays_below_the_limit_even_on_the_fallback_path(self, tmp_path):
        tmp, hook, env = self._hook_sandbox(tmp_path / "hook", fallback="tail")
        proc = _bash('TITLE="stub"; EXIST=""\n' + hook, tmp, env)
        assert proc.returncode == 0, proc.stderr[-600:]
        body = (tmp / "body.txt").stat().st_size
        assert body <= ISSUE_BODY_HARD_LIMIT, (
            f"兜底路径的承接单 body = {body} B > issue body 上限 {ISSUE_BODY_HARD_LIMIT} ⇒ 还是开不出单")
        log = (tmp / "gh.log").read_text(encoding="utf-8") if (tmp / "gh.log").exists() else ""
        assert "issue create" in log or "issue comment" in log, \
            f"钩子没有真调 gh（说明这一段没被跑到 ⇒ 本判据会是空断言）：{log[:200]!r}"

    def test_pre_fix_fallback_really_overflows(self, tmp_path):
        """**红证**：把兜底换回 `cat`（修复前的形态）⇒ body **真的**超 65536。"""
        tmp, hook, env = self._hook_sandbox(tmp_path / "hook-mutant", fallback="cat")
        proc = _bash('TITLE="stub"; EXIST=""\n' + hook, tmp, env)
        assert proc.returncode == 0, proc.stderr[-400:]
        body = (tmp / "body.txt").stat().st_size
        assert body > ISSUE_BODY_HARD_LIMIT, (
            f"换回 `cat` 兜底后 body 仍只有 {body} B ⇒ 上面那条限长不是兜底挣来的（空断言）")
