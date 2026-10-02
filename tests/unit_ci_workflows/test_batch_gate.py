# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012）
r"""批次统一验证入口 `scripts/batch-gate.sh` 的实例判据（issue #6012；#6028 补就绪前置判定）。

## 治的形态（2026-10-02 17:24–17:29 CST 现场，读数现取）

机器级重活锁：1 个 `gate` 持锁、**7 个 gate 在跑**（6 个排队：已等 40 / 31 / 20 / 12 / 7 / 2 分钟）、
最高排队读数 `已等 2354s / 上限 2400s`；`load average` **21.6 / 43.6 / 61.3**（8 核）。
⇒ 类级病 = **「每个包各自跑一遍全量」× 「本机只装得下一份全量」**。
排他锁治的是 CPU 争用，治不了**份数**；本判据守的是份数。

#6028 补的第二半：**份数**治住之后，**「时机」**成了现取缺口 —— `#6003` / `#6005` 这类
**与 base 冲突（GitHub 侧 DIRTY）** 的包被拉进批次 ⇒ 集成结果必然红、且红在**别人**身上
（面级归因指向错误对象）⇒ 白烧一次全量。⇒ 那一次全量**之前**逐包判「就绪」（无冲突 + PR checks 全绿），
**任一不就绪 ⇒ 拒绝**（exit 3，不跑全量）。

## 判据（每条都能单独变红）

| # | 断言 | 回归时会怎么红 |
|---|---|---|
| 1 | N 个包 ⇒ 那一次全量**恰好被调用 1 次** | 有人把 gate 挪进 merge 循环（退回「每包一次」）⇒ 调用数 = N |
| 2 | 调用数**不随 N 增长**（2 包 / 3 包都得 1） | 同上；这条是 1 的**判别力**对照（N 变而读数不变才叫「统一」） |
| 3 | 红 ⇒ 面级归因点到**碰该面的包**，且不把面外包算进来 | 归因退化成「把所有包都列一遍」/ 指认错包 ⇒ 红 |
| 4 | 分支不存在 ⇒ exit **3**（无法判定）且**没跑** gate | 把「读不到分支」读成「绿」或照跑一次 ⇒ 红 |
| 5 | 整合冲突 ⇒ exit **1**、**没跑** gate、**具名**冲突分支 | 冲突也照跑 gate（把「没跑」记成「跑过」）⇒ 红 |
| 6 | 跑完不残留 worktree（本命令自建的那份自己收） | 临时集成 worktree 堆积 ⇒ 红 |
| 7 | 包与 base **有冲突（DIRTY）** ⇒ 拒绝（exit 3）、**没跑** gate、给同步出口 | 不判冲突就把它拉进批次（#6003/#6005 的形态）⇒ 红 |
| 8 | PR 有 `fail` / `pending` ⇒ 拒绝（exit 3）、**没跑** gate | 把「CI 未绿」当就绪 ⇒ 红 |
| 9 | **没有对应的 open PR** ⇒ 拒绝（exit 3）、**没跑** gate | 把「没开 PR」当就绪 ⇒ 红 |
| 10 | `gh` **在**但调用失败（无凭据/断网）⇒ **fail-closed 拒绝**（exit 3）+ 具名「无法判定 ≠ 就绪」 | 把「取不到 PR 状态」静默当就绪（fail-open）⇒ 红 |
| 10' | `gh` **不在 PATH**（PATH 桩驱动）⇒ 同上，且走「gh 不存在」具名分支 | 只有环境「碰巧没有 gh」才成立 ⇒ CI 上永远走不到（空断言）⇒ 红 |
| 11 | `--require-ready` **默认开启**（不传开关也判） | 默认值被改成 off ⇒ 判 11 红（沙箱里无 gh ⇒ 期望 fail-closed 却跑了 gate） |
| 12 | `--no-require-ready` ⇒ 跑，但**必须打印**「未跑（--no-require-ready）—— 这不是「就绪」」 | 逃生口静默跳过（看起来和「就绪」一样）⇒ 红 |

## 注入式红证（`test_mutations_turn_the_suite_red`，§28.1 出口①）

判据 7~12 都能**单独**变红这件事，不是靠"这些断言写得很细"，而是**注入式实测**：
把真脚本复制进临时沙箱 → 做 4 处**定向变异**（每处断言唯一命中，命中数 0 或 >1 即判红 = 变异没生效）
→ 各自跑一次 → **必须非 0 退出且命中具名断言关键字**（"没跑" / "无法判定" / "这不是「就绪」"）。
⇒ 判据不是空断言：变异体真红。

## 隔离（为什么这些判据是安全的）

全部在**自足临时仓库**里跑（`git init` + 桩 `verify-all.sh` + 桩 `gh`），**不碰共享检出、不跑真全量**：
判据造的是自己那几个分支与 worktree，`--base` 显式指向临时仓库的 `main`
（默认 `origin/main` 在临时仓库里不存在 —— 这正是「不许悄悄依赖环境」的形态）。
判据 1~6 走「未跑就绪判定」这条路（**显式** `--no-require-ready`）：
它们判的是**份数 / 归因 / 三态**，沙箱里既没有 remote 也没有真 PR ⇒ 就绪判定必然 fail-closed，
与本组判题无关（不是「为了让绿而关掉」—— 逃生口是脚本的**唯一**口子，且它必打印未跑声明）。
**判据 7~15 一律走真默认路径**（不传逃生口）。

⚠️ **两个环境相关的坑（CI 实测，2026-10-02）**：
① 「`gh` 不存在」这条路只能靠 **PATH 桩**驱动（把 `gh` 从 PATH 里摘干净）—— **不许**指望 CI 上没有 gh
（实测 runner 上 gh 是装着的、只是没凭据 ⇒ 走的是「gh 调用失败」那条分支）；
② 因此本文件对这两条**分别**判：`gh` 在但调用失败（挂桩 gh）与 `gh` 不在 PATH（`_slim_path`），
两条都断**语义 + 三态**（`❓ 无法判定` + 具名「无法判定 ≠ 就绪」+ exit 3 + 一次全量都没跑）。

⚠️ **DIRTY 的分支怎么造**（实测教训）：只在分支上改一行、而 base 没动那份文件 ⇒ `merge-tree` 是**快进**、
**退出码 0** —— 那**不是**冲突。真 DIRTY 的形态 = **分支切出后 main 前进了同一行**（`chapters-dirty`）；
第一版判据正是用了「快进分支」当 DIRTY，才把「不判冲突」的变异体放了过去。

## 边界（照实登记，§19.1）

- 桩替换了真 `verify-all.sh`：本判据**不判**真 gate 的通过条件（那是 `test_verify_all_*` 的事），
  只判**调用份数 / 归因 / 三态 / 就绪前置**这几件事；
- 桩替换了 `gh`：本判据**不判** `gh` 的真语义（真 API 的限流 / 权限 / 字段漂移**不在面内**），
  只判「拿到三种读数时脚本怎么处置」；
- 归因本身是**面级映射**：判据只锁「面内唯一候选时点名它、面内多候选时不指认唯一真凶」，
  不判「真凶确实是它」（那需要失败日志级语义，本仓没有该能力）；
- 判据不覆盖「就绪判定与真跑 gate 之间 base 前进」的竞态（`merge-tree` 是**快照**判定）；
- 本判据**不改**任何门禁的通过条件、不新增豁免。
"""

from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import uuid

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT_REL = "scripts/batch-gate.sh"
SCRIPT_SRC = REPO / SCRIPT_REL

#: 桩 `verify-all.sh`：把「被调用了几次」写成可计数的读数（= 本判据的主读数）。
#: 退出码与失败项由环境变量注入 ⇒ 同一个桩既能演绿也能演红。
STUB = """#!/usr/bin/env bash
echo "call" >> "${BATCH_GATE_STUB_LOG:?}"
echo "变更集：1 个文件（桩）"
echo "✅ QA Growth Gate 预检"
if [ -n "${BATCH_GATE_STUB_EXTRA:-}" ]; then eval "${BATCH_GATE_STUB_EXTRA}"; fi
exit "${BATCH_GATE_STUB_RC:-0}"
"""

#: 桩 `gh`：让就绪判定的两种读数（PR 列表 / checks 桶）可注入。
#: 只识别脚本真会用的那两条子命令；其余一律非零（**不静默给数** —— 静默给数就是假绿方向）。
GH_STUB = """#!/usr/bin/env bash
echo "${1:-} ${2:-} ${3:-} ${4:-} ${5:-} ${6:-} ${7:-}" >> "${BATCH_GATE_GH_LOG:?}"
mode="${BATCH_GATE_GH_MODE:?}"
if [ "${1:-}" = "pr" ] && [ "${2:-}" = "list" ]; then
  case "$mode" in
    # 真 gh 在「无匹配 PR」时输出 `[]`（空数组）。**空 stdout** 是另一码事
    # （= 取不到读数 ⇒ 脚本按「无法判定」fail-closed；见 `_gh_json_pick` 的空白输入分支）。
    no-pr) printf '[]\n'; exit 0 ;;
    offline) echo "error: could not resolve host: api.github.com" >&2; exit 1 ;;
    *) printf '[{"number": %s}]\n' "${BATCH_GATE_GH_PR:-6801}"; exit 0 ;;
  esac
fi
if [ "${1:-}" = "pr" ] && [ "${2:-}" = "checks" ]; then
  case "$mode" in
    fail)    printf '[{"name":"ci workflow helper 判据集","state":"FAILURE","bucket":"fail"},{"name":"QA Growth Gate","state":"SUCCESS","bucket":"pass"}]\n' ;;
    pending) printf '[{"name":"ci workflow helper 判据集","state":"PENDING","bucket":"pending"}]\n' ;;
    none)    printf '[]\n' ;;
    nonjson) printf 'not json at all\n' ;;
    offline) echo "error: could not resolve host: api.github.com" >&2; exit 1 ;;
    *)       printf '[{"name":"QA Growth Gate","state":"SUCCESS","bucket":"pass"},{"name":"Case Trust Gate","state":"SUCCESS","bucket":"pass"}]\n' ;;
  esac
  exit 0
fi
echo "gh stub: 未支持的调用：$*" >&2
exit 1
"""

CI_FAIL = (
    'echo "❌ ci workflow helper 判据集（本地跑 CI 同名 job） (exit 1)";'
    'echo "失败项: ci workflow helper 判据集（本地跑 CI 同名 job）"'
)


def _script_text() -> str:
    return SCRIPT_SRC.read_text(encoding="utf-8")


def _build_repo(root: pathlib.Path, script_text: str) -> pathlib.Path:
    """造一个自足临时仓库（`main` + 三个包分支 + 一对冲突分支 + 可计数桩）。

    `script_text` 参数 = **注入点**：红证用变异后的脚本文本走同一条构建路径（真对象、真运行）。
    """
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "batch-gate@test.invalid")
    _git(root, "config", "user.name", "batch-gate-test")

    (root / "scripts").mkdir()
    dst = root / SCRIPT_REL
    dst.write_text(script_text, encoding="utf-8")
    os.chmod(dst, 0o755)
    _write(root, "verify-all.sh", STUB)
    os.chmod(root / "verify-all.sh", 0o755)
    _write(root, "backend/admin-api/A.java", "base\n")
    _write(root, "backend/ai-agent-service/c.py", "base\n")
    _write(root, "frontend/admin-web/b.ts", "base\n")
    _write(root, "tests/unit_ci_workflows/guard_a.py", "base\n")
    _commit(root, "base")

    # pkg-a 碰 ci-helper 面（tests/unit_ci_workflows/**）与 admin-api 面
    _branch_with(root, "pkg-a", "tests/unit_ci_workflows/guard_a.py", "a\n")
    _branch_with(root, "pkg-b", "frontend/admin-web/b.ts", "b\n")
    _branch_with(root, "pkg-c", "backend/ai-agent-service/c.py", "c\n")
    # 一对必然冲突的分支（同一文件同一行两侧都改）
    _branch_with(root, "conf-a", "shared.txt", "A\n")
    _branch_with(root, "conf-b", "shared.txt", "B\n")
    # 一个**真 DIRTY** 的包：分支切出后 main 也改了同一行 ⇒ 它与 base 冲突
    # （⚠️ 「只在分支上改一行」在 merge-tree 里是**快进**、不算冲突 —— 这正是 #6003/#6005 的形态：
    #   分支切出后主线前进了。实测：`git merge-tree --write-tree --name-only main <这类分支>` 退出码 1）
    _branch_with(root, "chapters-dirty", "config/app.yml", "settings: 3\n")
    _write(root, "config/app.yml", "settings: 2\n")
    _commit(root, "main advances")
    return root


def _git(cwd, *args, check=True):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=check)


def _write(root: pathlib.Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _commit(root: pathlib.Path, msg: str) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", msg)


def _branch_with(root: pathlib.Path, name: str, rel: str, text: str) -> None:
    """从 `main` 切一个新分支，改一个文件，提交，再切回 `main`。"""
    _git(root, "checkout", "-q", "-b", name, "main")
    _write(root, rel, text)
    _commit(root, name)
    _git(root, "checkout", "-q", "main")


def _link_tools(sandbox: pathlib.Path) -> pathlib.Path:
    """给 sandbox 挂上**可计数的 `gh` 桩**，返回桩目录（调用方把它前置进 `PATH`）。"""
    bindir = sandbox.parent / f"ghbin-{uuid.uuid4().hex}"
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text(GH_STUB, encoding="utf-8")
    os.chmod(gh, 0o755)
    return bindir


@pytest.fixture
def sandbox(tmp_path: pathlib.Path) -> pathlib.Path:
    """自足临时仓库：`main` + 三个包分支 + 一对冲突分支 + 可计数的 verify-all 桩。"""
    assert SCRIPT_SRC.is_file(), f"载体不存在：{SCRIPT_REL}"
    return _build_repo(tmp_path / "repo", _script_text())


def run_batch(
    root: pathlib.Path,
    *args: str,
    stub_rc: str = "0",
    stub_extra: str = "",
    gh_mode: str | None = None,
    gh_pr: str = "6801",
    path: str | None = None,
):
    """跑真脚本；返回 (CompletedProcess, 桩被调用的次数, gh 桩被调用的行)。

    两种环境形态：
      - `gh_mode=<模式>`：挂**桩 gh**（`all-green` / `fail` / `pending` / `no-pr` / `offline` …），
        走**真默认路径**（判就绪）；
      - 默认（`gh_mode=None`）：给命令行**显式**加上 `--no-require-ready` —— 存量判据 1~6 在本沙箱里
        **够不到** GitHub，故走「未跑就绪判定」这条路（判的是份数/归因/三态，不是就绪）。
        ⚠️ 逃生口**只有命令行这一个**（脚本有意不做环境变量逃生口）。
        （要跑**真默认路径且什么都不传**用 `run_raw`。）
    """
    log = root.parent / f"stub-{uuid.uuid4().hex}.log"
    env = dict(os.environ)
    env.pop("MIGAO_HEAVY_WAIT", None)
    env.update({"BATCH_GATE_STUB_LOG": str(log), "BATCH_GATE_STUB_RC": stub_rc,
                "BATCH_GATE_STUB_EXTRA": stub_extra})
    gh_calls: list[str] = []
    if gh_mode is None:
        if "--no-require-ready" not in args:
            args = ("--no-require-ready", *args)
    else:
        gh_log = root.parent / f"gh-{uuid.uuid4().hex}.log"
        env.update({"BATCH_GATE_GH_MODE": gh_mode, "BATCH_GATE_GH_LOG": str(gh_log),
                    "BATCH_GATE_GH_PR": gh_pr})
        env["PATH"] = f"{_link_tools(root)}{os.pathsep}{env.get('PATH', '')}"
    if path is not None:
        env["PATH"] = path
    proc = subprocess.run(
        [str(root / SCRIPT_REL), "--base", "main", *args],
        cwd=str(root), capture_output=True, text=True, env=env, timeout=180,
    )
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    if gh_mode is not None:
        gh_calls = gh_log.read_text(encoding="utf-8").splitlines() if gh_log.exists() else []
    return proc, calls, gh_calls


# ── 判据 1~6：份数 / 归因 / 三态（issue #6012；这批**不**判就绪）────────────────

def test_one_gate_for_the_whole_batch(sandbox):
    """判据 1：N 个包 ⇒ 全量**一次**（不是每包一次）。"""
    proc, calls, _ = run_batch(sandbox, "pkg-a", "pkg-b")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert len(calls) == 1, f"gate 被调用 {len(calls)} 次（应为 1）：{calls}"
    assert "pkg-a" in proc.stdout and "pkg-b" in proc.stdout


def test_gate_call_count_does_not_scale_with_packages(sandbox):
    """判据 2（判别力）：2 包与 3 包的调用数都是 1 —— 与「每包一次」形态可判别。"""
    _, calls2, _ = run_batch(sandbox, "pkg-a", "pkg-b")
    _, calls3, _ = run_batch(sandbox, "pkg-a", "pkg-b", "pkg-c")
    assert (len(calls2), len(calls3)) == (1, 1), f"2 包 {len(calls2)} 次 / 3 包 {len(calls3)} 次"


def test_red_attributes_to_the_package_touching_the_face(sandbox):
    """判据 3：红 ⇒ 面级归因点到碰该面的包，且不把面外包算进来。"""
    proc, calls, _ = run_batch(sandbox, "pkg-a", "pkg-b", stub_rc="1", stub_extra=CI_FAIL)
    assert proc.returncode == 1
    assert len(calls) == 1, "红的时候也只该跑一次"
    m = re.search(
        r"失败项：.*ci workflow helper.*\n\s+面：ci workflow helper.*\n\s+面内包（可能引入方）：(\S+)",
        proc.stdout,
    )
    assert m, "归因段没有按「失败项 → 面 → 面内包」的形态打印：\n" + proc.stdout
    assert m.group(1) == "pkg-a", f"面内唯一候选应是 pkg-a，实得 {m.group(1)}"
    # pkg-b 只碰 admin-web，**不**该出现在 ci-helper 面的候选里
    assert "面内包：pkg-a、pkg-b" not in proc.stdout


def test_unknown_branch_is_undecidable_and_runs_nothing(sandbox):
    """判据 4：读不到分支 ⇒ exit 3 且**没跑**（「没跑」必须长得像「没跑」）。"""
    proc, calls, _ = run_batch(sandbox, "no-such-branch")
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert calls == [], f"无法判定时不该跑 gate，实得 {calls}"
    assert "无法判定" in proc.stdout + proc.stderr


def test_conflict_stops_before_the_gate(sandbox):
    """判据 5：整合冲突 ⇒ exit 1、没跑 gate、具名冲突分支。"""
    proc, calls, _ = run_batch(sandbox, "conf-a", "conf-b")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert calls == [], f"冲突时不该跑 gate，实得 {calls}"
    assert "conf-b" in proc.stdout, "冲突分支没有具名"
    assert "没有跑" in proc.stdout
    assert "conf-a" in proc.stdout


def test_in_mode_runs_in_the_existing_worktree(sandbox, tmp_path):
    """`--in <worktree>`：在既有集成工作区里只跑那一次（环境已备时的形态）。"""
    wt = tmp_path / "integration"
    _git(sandbox, "worktree", "add", "--detach", str(wt), "main")
    proc, calls, _ = run_batch(sandbox, "--in", str(wt), "pkg-a")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert len(calls) == 1
    assert str(wt) in proc.stdout


def test_no_worktree_left_behind(sandbox):
    """判据 6：自建的那份临时集成 worktree 跑完自己收掉。"""
    run_batch(sandbox, "pkg-a", "pkg-b")
    out = _git(sandbox, "worktree", "list", "--porcelain").stdout
    wts = [ln for ln in out.splitlines() if ln.startswith("worktree ")]
    assert len(wts) == 1, f"临时集成 worktree 残留：{out}"


def test_help_and_usage_are_actionable(sandbox):
    """出口必须真可行动：usage 写清两种形态 + 「没跑 ≠ 通过」。"""
    proc = subprocess.run([str(sandbox / SCRIPT_REL)], cwd=str(sandbox),
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "只跑一次" in proc.stderr, proc.stderr
    hel = subprocess.run([str(sandbox / SCRIPT_REL), "--help"], cwd=str(sandbox),
                         capture_output=True, text=True, timeout=60)
    assert hel.returncode == 0
    assert "--in" in hel.stdout and "退出码" in hel.stdout
    # ⚠️ `--help` 必须是**整个文件头**，不许写死行数区间 —— 实测：本包给头部加了「就绪判定」段后，
    # 写死的 `sed -n '1,58p'` 把「## 退出码」**从三态正文处截断**（标题在、0/1/3 看不见），
    # 而上面只断言「退出码」三个字 ⇒ 截断**不会红**。这三条锁住「三态正文 + 新逃生口」真的可见。
    for needle in ("0 = 那一次 gate 全绿", "1 = 红", "3 = 无法判定", "--no-require-ready"):
        assert needle in hel.stdout, f"--help 被截断了（缺 {needle!r}）：{hel.stdout}"


# ── 判据 7~12：就绪前置判定（issue #6028）─────────────────────────────────────

def test_dirty_package_is_refused_before_the_gate(sandbox):
    """判据 7：包与 base 有冲突（DIRTY）⇒ 拒绝（exit 3）、没跑 gate、出口可行动。

    形态来源（2026-10-02 实测）：`#6003` / `#6005` 这类 DIRTY 包被拉进批次 ⇒ 必红且归因指向别人。
    """
    proc, calls, gh_calls = run_batch(sandbox, "chapters-dirty", gh_mode="all-green")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 3, out
    assert calls == [], f"不就绪时**一次全量都不该跑**，实得 {calls}"
    assert "chapters-dirty" in out, "不就绪的包没有具名"
    assert "有冲突" in out, f"没有说清哪条不满足：{out}"
    assert "sync-main.sh --rebase" in out, "没有给出同步主线的出口命令"
    assert gh_calls == [], f"冲突是离线可判的 ⇒ 不该去问 gh（省一次网络调用），实得 {gh_calls}"


def test_red_required_checks_are_refused_before_the_gate(sandbox):
    """判据 8：PR checks 有 fail ⇒ 拒绝（exit 3）、没跑 gate、提示修红。"""
    proc, calls, _ = run_batch(sandbox, "pkg-a", gh_mode="fail")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 3, out
    assert calls == [], f"不就绪时不该跑 gate，实得 {calls}"
    assert "PR #6801" in out, f"没有具名到 PR：{out}"
    assert "红" in out and "先修红" in out, f"没有给出修红出口：{out}"


def test_pending_checks_are_refused_before_the_gate(sandbox):
    """判据 8'：PR checks 有 pending（未完成）⇒ 拒绝（exit 3）、没跑 gate。"""
    proc, calls, _ = run_batch(sandbox, "pkg-a", gh_mode="pending")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 3, out
    assert calls == [], f"不就绪时不该跑 gate，实得 {calls}"
    assert "未完成" in out, f"没有说清 pending：{out}"


def test_missing_pr_is_refused_before_the_gate(sandbox):
    """判据 9：找不到对应 open PR ⇒ 拒绝（exit 3）、没跑 gate、提示先开 PR。"""
    proc, calls, _ = run_batch(sandbox, "pkg-a", gh_mode="no-pr")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 3, out
    assert calls == [], f"不就绪时不该跑 gate，实得 {calls}"
    assert "没有对应的 open PR" in out, f"没有说清「无 PR」：{out}"
    assert "先开 PR" in out, f"没有给出开 PR 的出口：{out}"


def test_gh_unavailable_fails_closed_and_says_undecidable(sandbox):
    """判据 10：**`gh` 在、但调用失败**（无凭据 / 断网 / 限流）⇒ fail-closed（exit 3）、一次全量都没跑。

    这是 CI runner 上的**真实形态**（`gh` 装着、但拿不到 PR 读数）；不许 fail-open
    （把「取不到」当成「就绪」就是本条要拦的形态）。断言只吃**语义 + 三态**，不吃环境特定措辞。
    """
    proc, calls, _ = run_batch(sandbox, "pkg-a", gh_mode="offline")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 3, out
    assert calls == [], f"无法判定时不该跑 gate（fail-closed），实得 {calls}"
    assert "❓" in out, f"没有印出「无法判定」标记：{out}"
    assert "无法判定 ≠ 就绪" in out, f"没有具名「无法判定 ≠ 就绪」：{out}"
    assert "gh pr list 失败" in out, f"没有给出无法判定的现取依据（pr list 那一步）：{out}"
    # 用**逐包就绪行的形态**判 fail-open（裸 `✅` 会误伤：脚本 footer 里就有「别把 ❓ 读成 ✅」）
    assert "✅ pkg-a：" not in out, f"不许把「取不到」印成就绪（fail-open）：{out}"


#: 脚本与判据跑起来真正需要的命令（逐个软链进 slim PATH；缺一个都会当场红，不会静默降级）。
_SLIM_TOOLS = ("git", "python3", "sed", "grep", "head", "tail", "tr", "date", "mktemp", "rm",
               "cat", "dirname", "basename", "env", "sh", "bash", "sort", "uniq", "cut", "wc",
               "mkdir", "cp", "mv", "ls", "printf", "sleep")


def _slim_path(workdir: pathlib.Path) -> str:
    """造一个**真的没有 gh** 的 PATH —— 用来驱动「`gh` 不在 PATH」那条分支。

    ⚠️ **只返回软链目录**：早先的写法在末尾缀了 `/usr/bin:/bin`，而 CI runner 上 `/usr/bin/gh` 是**存在**的
    ⇒ `command -v gh` 照样命中 ⇒ 判据走的是「gh 调用失败」那条分支，却被断言成「gh 不存在」的措辞
    （CI 上**永远走不到** = 空断言形态；`--check-weak` 只扫字面串，拦不住这种）。
    """
    bindir = workdir / f"slimbin-{uuid.uuid4().hex}"
    bindir.mkdir()
    for tool in _SLIM_TOOLS:
        found = shutil.which(tool)
        if found:
            (bindir / tool).symlink_to(found)
    return str(bindir)


def run_raw(root: pathlib.Path, *args: str, path: str | None = None):
    """**什么都不注入**地跑真脚本（不挂桩 gh、不传逃生口）—— 判据 10'/11 与**红证**走这条路。

    返回 (CompletedProcess, gate 被调用次数)。
    """
    log = root.parent / f"stub-{uuid.uuid4().hex}.log"
    env = dict(os.environ)
    env.pop("MIGAO_HEAVY_WAIT", None)
    env.update({"BATCH_GATE_STUB_LOG": str(log), "BATCH_GATE_STUB_RC": "0",
                "BATCH_GATE_STUB_EXTRA": ""})
    if path is not None:
        env["PATH"] = path
    proc = subprocess.run([str(root / SCRIPT_REL), "--base", "main", *args],
                          cwd=str(root), capture_output=True, text=True, env=env, timeout=180)
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return proc, calls


def test_gh_missing_from_path_fails_closed(sandbox):
    """判据 10'：`gh` **不在 PATH** ⇒ fail-closed（exit 3）、一次全量都没跑、具名「无法判定 ≠ 就绪」。

    ⚠️ 这条路必须由 **PATH 桩**驱动（`_slim_path`）—— CI runner 上 `gh` 是**装着**的，
    靠环境「碰巧没有 gh」写断言 ⇒ 该断言在 CI 上**永远走不到**（空断言）。故先自证桩生效。
    """
    slim = _slim_path(sandbox.parent)
    assert shutil.which("gh", path=slim) is None, f"PATH 桩失效（还能找到 gh）：{slim}"
    proc, calls = run_raw(sandbox, "pkg-a", path=slim)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 3, out
    assert calls == [], f"gh 不在 PATH 时不该跑 gate（fail-closed），实得 {calls}"
    assert "❓" in out, f"没有印出「无法判定」标记：{out}"
    assert "无法判定 ≠ 就绪" in out, f"没有具名「无法判定 ≠ 就绪」：{out}"
    assert "gh 不存在" in out, f"PATH 桩生效时应走「gh 不存在」那条具名分支：{out}"
    # 用**逐包就绪行的形态**判 fail-open（裸 `✅` 会误伤：脚本 footer 里就有「别把 ❓ 读成 ✅」）
    assert "✅ pkg-a：" not in out, f"不许把「取不到」印成就绪（fail-open）：{out}"


def test_require_ready_is_on_by_default(sandbox):
    """判据 11：**不传任何开关**也判就绪（沙箱里没有真 PR/remote ⇒ 期望 fail-closed 拒绝、没跑 gate）。

    与判据 10' 的分别：这条判的是**默认值**（有没有开），只断三态与「没跑全量」；
    至于「无法判定具体走哪条具名分支」由 10'（gh 不在 PATH）与 10（gh 在但调用失败）各自承担。
    """
    slim = _slim_path(sandbox.parent)
    assert shutil.which("gh", path=slim) is None, f"PATH 桩失效（还能找到 gh）：{slim}"
    proc, calls = run_raw(sandbox, "pkg-a", path=slim)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 3, out
    assert calls == [], f"默认路径下不就绪时不该跑 gate，实得 {calls}"
    assert "就绪前置判定（--require-ready 默认开启" in out, f"默认没有开就绪判定：{out}"
    assert "❓" in out, f"默认路径没有印出「无法判定」标记：{out}"
    assert "无法判定 ≠ 就绪" in out, f"默认路径没有 fail-closed：{out}"


def test_no_require_ready_runs_but_says_it_was_skipped(sandbox):
    """判据 12：逃生口 = **显式** `--no-require-ready` ⇒ 跑 gate，但必须打印「未跑…不是就绪」。"""
    proc, calls, _ = run_batch(sandbox, "--no-require-ready", "pkg-a", "pkg-b")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert len(calls) == 1, f"逃生口下仍只跑一次全量，实得 {calls}"
    assert "--no-require-ready" in out, f"没有说明是哪条路跳过的：{out}"
    assert "这不是「就绪」" in out, f"跳过必须出声（不许静默，看起来像「就绪」）：{out}"


def test_all_ready_runs_exactly_one_gate(sandbox):
    """判据 13（正向路径不回归）：全部就绪 ⇒ 正常跑**一次** gate 并绿。"""
    proc, calls, gh_calls = run_batch(sandbox, "pkg-a", "pkg-b", gh_mode="all-green")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert len(calls) == 1, f"全绿路径下 gate 调用数应为 1，实得 {calls}"
    assert "全部 2 个包就绪" in out, f"没有打印就绪结论：{out}"
    assert "分支不存在" not in out, "就绪时不该出现任何「分支不存在」的噪声"
    # 每个包都查过 PR（两个包各一次 list + 一次 checks）
    assert len([ln for ln in gh_calls if "list" in ln]) == 2, f"gh 调用读数：{gh_calls}"


# ── 注入式红证（§28.1 出口①）：变异体必须真红 ────────────────────────────────

#: 四处**定向**变异：每处的 `old` 在真脚本里**恰好出现一次**（命中数 0 或 >1 即判红 =
#: 变异没生效，红证就成了空断言 —— 这条自证是本判据的一部分，不是注释）。
#: 每条变异对应它应当打红的那条判据（`expected`）与用来触发它的包分支（`branch`）。
MUTATIONS = [
    (
        "冲突不就绪 → 就绪",
        '    not_ready "$b" "与基准 ${BASE} 有冲突',
        '    ready_ok "$b" "与基准 ${BASE} 有冲突',
        "not_ready_became_ready",
        "chapters-dirty",
        "offline",   # 非 None ⇒ 走真就绪判定（gh_mode=None 会注入逃生口，变异体就抓不住了）
    ),
    (
        "无 PR 不就绪 → 就绪",
        '    not_ready "$b" "没有对应的 open PR',
        '    ready_ok "$b" "没有对应的 open PR',
        "not_ready_became_ready",
        "pkg-a",
        "no-pr",
    ),
    (
        "无法判定 → 就绪（fail-open：把 undecidable 整族改成 ready）",
        r"undecidable() { printf '?\t%s\t%s\n'",
        r"undecidable() { printf 'o\t%s\t%s\n'",
        "undecidable_became_ready",
        "pkg-a",
        "offline",
    ),
    (
        "就绪判定默认关（--require-ready 默认开启 → 关闭）",
        "READY=1\n",
        "READY=0\n",
        "default_off",
        "pkg-a",
        "offline",
    ),
    (
        "逃生口的「未跑」声明被摘掉（跳过变成静默）",
        '  echo "⏭️ 就绪判定未跑',
        '  : "⏭️ 就绪判定未跑',
        "skip_notice_gone",
        "pkg-a",
        None,        # 走 run_batch 的默认：显式 `--no-require-ready`
    ),
]


def _mutated_repo(tmp_path: pathlib.Path, old: str, new: str) -> pathlib.Path:
    """造一个**装了变异脚本**的沙箱（与正常沙箱同一条构建路径）—— 真对象、真运行。"""
    src = _script_text()
    hits = src.count(old)
    assert hits == 1, f"变异没生效（命中 {hits} 次，应为 1）：{old!r} ⇒ 红证就是空断言，先修变异锚点"
    assert new != old, "变异体与原文逐字相同 = 没变异"
    return _build_repo(tmp_path / f"mutant-{uuid.uuid4().hex}", src.replace(old, new, 1))


@pytest.mark.parametrize("label,old,new,expect,branch,gh_mode", MUTATIONS,
                         ids=[m[0] for m in MUTATIONS])
def test_mutations_turn_the_suite_red(sandbox, tmp_path, label, old, new, expect, branch, gh_mode):
    """判据 14：**注入式红证** —— 四处变异各自必须让对应判据真红（且报出具名读数）。

    每个变异都跑在**自己的**沙箱里；`branch` 是能走到目标分支的那个包：
      - 「冲突不就绪 → 就绪」走 `chapters-dirty`（切出后主线前进过 ⇒ 真冲突）；
      - 「无 PR 不就绪 → 就绪」必须**挂桩 gh 且 list 成功**（否则先死在「gh pr list 失败」上、
        根本走不到那条分支 —— 变异体会因为**别的**原因非零退出，红证就成了假红）；
      - 其余走 `pkg-a`。

    判红读数按 `expect` 分流（三种形态**互斥**，不许混着断 —— 混着断必然自相矛盾）：
      - `not_ready_became_ready` ⇒ 那个包被印成 **✅ <包>：<理由>**（不就绪被印成就绪）；
      - `undecidable_became_ready` ⇒ 那行被印成 **✅ pkg-a：gh pr list 失败**（fail-open 的可见形态）；
      - `default_off` ⇒ **就绪判定横幅整个不见**（连判都没判）；
      - `skip_notice_gone` ⇒ 走了逃生口却**不吭声**（「未跑…这不是「就绪」」那句没了）。

      这三条**都**会：① 不再打「⛔ 有包未通过就绪判定」；② 那一次全量**照跑**（`calls == 1`）。

      ⚠️ **不拿退出码当共同读数**：变异 A 的包真冲突 ⇒ 校验放行后会在 merge 阶段红（exit 1），
      与变异 B/C/D 的 exit 0 不同；共同读数是「就绪判定有没有再拒绝 + 全量有没有照跑」。
    """
    mutant = _mutated_repo(tmp_path, old, new)
    # ⚠️ 必须走**真默认路径**（不传 `--no-require-ready`）—— 否则脚本压根不判就绪，
    # 变异体一律「看起来绿」⇒ 这组红证就成了空断言（这不是假设：本判据第一版正是如此被抓出来的）。
    proc, calls, _ = run_batch(mutant, branch, gh_mode=gh_mode)
    out = proc.stdout + proc.stderr
    # 共同读数：就绪判定**没有再拒绝**（那句「⛔ 有包未通过就绪判定」不见了）——
    # 三条变异都会让它消失，而**正常脚本**下判据 7~10 正是靠它变红的。
    assert "⛔ 有包未通过就绪判定" not in out, f"变异「{label}」**没被抓住**（就绪判定仍拒绝了）：\n{out}"
    # 逐条读数（**每条都必须真的择得出来**，否则这条变异是空断言）：
    if expect == "not_ready_became_ready":
        marker = f"✅ {branch}："
        assert marker in out, f"变异「{label}」没被抓住（没有把不就绪印成就绪）：\n{out}"
        assert f"❌ {branch}（不就绪）" not in out, f"变异「{label}」仍印着「不就绪」：\n{out}"
        if branch != "chapters-dirty":   # chapters-dirty 真冲突 ⇒ 校验放行后死在 merge，全量不会跑
            assert len(calls) == 1, f"变异「{label}」没被抓住（没放行）：{calls}"
    elif expect == "undecidable_became_ready":
        assert "✅ pkg-a：gh pr list 失败" in out, f"变异「{label}」没被抓住（fail-open 那行不在）：\n{out}"
        assert "❓" not in out, f"变异「{label}」仍印着「无法判定」标记：\n{out}"
        assert len(calls) == 1, f"变异「{label}」没被抓住（没放行）：{calls}"
    elif expect == "skip_notice_gone":
        # 逃生活儿口静默了 ⇒ 使用者**看不出**「这次没判就绪」（与「就绪」长得一样）
        assert "这不是「就绪」" not in out, f"变异「{label}」没被抓住（声明还在）：\n{out}"
        assert len(calls) == 1, f"变异「{label}」没被抓住（本该照跑全量）：{calls}"
    elif expect == "default_off":
        # 就绪判定**根本没跑** ⇒ 横幅不见 + 打印「未跑」声明（这与脚本自带逃生口是两回事：
        # 「默认关」下连判都不判；逃生口下会显式打印 `--no-require-ready` 那句）
        assert "就绪前置判定（--require-ready 默认开启" not in out, f"变异「{label}」没被抓住（横幅还在）：\n{out}"
        assert "⏭️ 就绪判定未跑" in out, f"变异「{label}」没被抓住（连「未跑」都没印）：\n{out}"
        assert len(calls) == 1, f"变异「{label}」没被抓住（没放行）：{calls}"
    else:  # pragma: no cover - 防呆：expect 写错时当场红，不静默放行
        raise AssertionError(f"未知的 expect：{expect!r}（变异表写错 ⇒ 红证无效）")


def test_control_real_script_has_no_mutation_marker(sandbox):
    """判据 15（对照读数）：真脚本里没有留下任何变异——上面那组红证不是「冲着坏脚本测的」。"""
    src = (sandbox / SCRIPT_REL).read_text(encoding="utf-8")
    for _label, old, new, _expect, _branch, _gh_mode in MUTATIONS:
        assert new not in src, f"真脚本里出现了变异后的文本（红证会变成自证）：{new!r}"
        assert old in src, f"真脚本里找不到变异锚点（红证失效）：{old!r}"
