# case_ids: MC-012
"""#5100：台账**追加路径自愈**的判据（L0，离线、零 LLM、秒级）。

根因（**实测**，不是照抄 issue 文本）
------------------------------------
台账分支 `chore/flaky-ledger` 的追加路径**不自愈**：`flaky-triage.yml` 步骤④ 取**分支自己的
HEAD** 当基线（`git checkout -B "$BRANCH" FETCH_HEAD`）⇒ 追加提交的父提交是**旧**分支 HEAD；
而台账 PR 走 **squash 合并** ⇒ 分支历史**永不含** main 上那个 squash 提交
（实测 `compare/main...chore/flaky-ledger` = `diverged, ahead_by 34, behind_by 16`）
⇒ **只追加**的分支**每轮都会再冲突**（兜底判据 ~72 次/天红 ⇒ 告警疲劳且掩盖真实失效）。

修法（本文件锁的就是它）：**推前先与 main 对齐** —— 取 main 侧台账 → 按幂等键
`(workflow, run_id, job)` **并集**（复用 `append_entries`，不新写第二套并集逻辑）→
`git checkout -B "$BRANCH" origin/main` → 在**最新 main 之上**重放 → `--force-with-lease` 推送
（lease 失败 = 别人刚推 ⇒ **重取重算，绝不强推**）。**单一写者**设计不变：仍然只有
`flaky-triage.yml` 写这条分支（`flaky-ledger-reconcile.yml` 只 approve/arm，不写内容）。

六条验收判据（本文件逐条落码；每条都有**能单独让它红**的变异）
------------------------------------------------------------
1. 改前红：夹具（main 已前进 + 分支在旧基线追加）跑**修复前**的步骤④ ⇒ `behind_by > 0`；
2. 改后绿：同夹具跑**出货的**步骤④（真 git 夹具 + 真 bash + 真 bare remote）⇒ `behind_by == 0`；
3. 并集幂等：同一 key 重复追加 ⇒ 条目数不变（纯函数 + 夹具两层）；
4. 不丢条目：并集后条目数 ≥ max(main, 分支)，且两侧键全在（纯函数 + 夹具两层）；
5. 单一写者：全仓 workflow 扫描 ⇒ 写 `chore/flaky-ledger` 的**只有** `flaky-triage.yml`；
6. 注入式红证：把「推前先对齐」删掉（摘掉 `--align-main`）⇒ 判据 2 的断言**必须**红。

红证卫生（照 `migao-dev-flow` §19.1 元规则 ③）
----------------------------------------------
· 「改前」实现取**不可变出处** `@1e4f17d80`（修复前的 `origin/main`）—— 逐字节内联片段 +
  一条**溯源交叉校验**（浅克隆里取不到该提交 ⇒ 显式 `skip`，绝不谎报通过）；
· 夹具是**真 git**（bare remote + 真 bash + 真 `git push --force-with-lease`）—— 判据读的是
  **远端 ref 拓扑**（`git rev-list --count`），不是字符串 / mtime / 文件大小；
· 出货步骤④ 的正文按**原文**执行，只把**输入路径** `/tmp/flaky-entries.json` 换成夹具私有路径，
  并机械自证「除该路径外一字未改」（见 `_run_step`）—— 夹具产物全部落在 `tmp_path`，不写 `/tmp`。
"""
import hashlib
import importlib.util
import json
import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / ".github" / "scripts"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
SCRIPT_PATH = SCRIPTS / "flaky_ledger.py"
TRIAGE_PATH = WORKFLOWS / "flaky-triage.yml"
RECONCILE_PATH = WORKFLOWS / "flaky-ledger-reconcile.yml"
TRIAGE_NAME = TRIAGE_PATH.name

LEDGER_REL = ".github/flaky-ledger.json"
BRANCH = "chore/flaky-ledger"

#: 修复前的最后一个 `origin/main`（本包基点）—— 「改前」实现的**不可变**出处（§18.3）。
PRE_FIX_SHA = "1e4f17d80"

#: **逐字节内联**的修复前步骤④ 正文（出处 = `git show 1e4f17d80:.github/workflows/flaky-triage.yml`，
#: 由 `TestPreFixProvenance` 与 git 历史交叉校验）。它是「改前红」判据的锚点 ——
#: **不读 `origin/main`**（那是可变引用：本 PR 合并后它就变成「修复后」的文本 ⇒ 判据自红）。
PRE_FIX_STEP_BODY = r'''set -uo pipefail
BRANCH="chore/flaky-ledger"
# 台账分支已存在 ⇒ 以它为基线（避免与未合并的既有条目分叉）
if git ls-remote --exit-code --heads origin "$BRANCH" >/dev/null 2>&1; then
  git fetch --quiet origin "$BRANCH"
  git checkout -B "$BRANCH" FETCH_HEAD
else
  git checkout -B "$BRANCH"
fi
python3 .github/scripts/flaky_ledger.py append \
  --ledger .github/flaky-ledger.json --entries /tmp/flaky-entries.json
# 幂等判据（机械）：同 (workflow, run_id, job) 已登记 ⇒ append 是空操作 ⇒ 无 diff
if git diff --quiet -- .github/flaky-ledger.json; then
  echo "::notice::⏭️ 台账无新增（幂等：同一 (workflow, run_id, job) 已登记）"
else
  git config user.name "migao-flaky-bot"
  git config user.email "flaky-bot@users.noreply.github.com"
  git add .github/flaky-ledger.json
  git commit -q -m "chore(ci): flaky 台账追加（run ${RUN_ID}）"
  git push --quiet origin "$BRANCH" || {
    echo "::error::台账 push 失败 ⇒ 记账**未落仓**（fail-closed，不静默）"; exit 1; }
  # 落仓复核：**远端 ref** 必须就是本次提交（判据是远端，不是本地 git log）
  git fetch --quiet origin "$BRANCH"
  [ "$(git rev-parse FETCH_HEAD)" = "$(git rev-parse HEAD)" ] || {
    echo "::error::台账未落到远端分支 $BRANCH（落仓复核失败）"; exit 1; }
fi
PR=$(gh pr list --head "$BRANCH" --state open --json number \
       --jq '.[0].number // empty' --repo "$GITHUB_REPOSITORY")
if [ -z "$PR" ]; then
  # ⚠️ body 里**不得**出现 issue 关闭关键词 + 号（本仓库 close-linked-issues 是朴素正则，
  #    任何「关键词 + #号」形态都会被误判为关闭意图，包括反引号里的样例）。
  gh pr create --base main --head "$BRANCH" --repo "$GITHUB_REPOSITORY" \
    --title "chore(ci): flaky 台账滚动追加" \
    --body "由 \`.github/workflows/flaky-triage.yml\` 自动追加（关联 issue 4717，**不关闭**它）。

    只改 \`.github/flaky-ledger.json\`：**只追加**、幂等（键 = \`(workflow, run_id, job)\`）、可审计。

    消费方式：**条数现取**（本台账不写任何计数）；同一 \`job\` 反复出现 \`kind=flaky\` ⇒ 按 \`migao-acceptance\`「随机红 = 归因层失效」开单修根因，而不是继续重跑。" \
    || { echo "::error::台账 PR 创建失败 ⇒ 台账停在分支上、main 不增长（fail-closed）"; exit 1; }
  PR=$(gh pr list --head "$BRANCH" --state open --json number \
         --jq '.[0].number // empty' --repo "$GITHUB_REPOSITORY")
  [ -n "$PR" ] || { echo "::error::台账 PR 创建后取不到 PR 号 ⇒ fail-closed"; exit 1; }
fi
echo "pr=$PR" >> "$GITHUB_OUTPUT"
echo "::notice::📒 flaky 台账已追加并推送 $BRANCH（远端 ref 复核通过）—— PR #$PR 待批准后走 required 检查"
'''


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FL = _load(SCRIPT_PATH, "migao_flaky_ledger_append_selfheal")
REAL_TRIAGE = TRIAGE_PATH.read_text(encoding="utf-8")
REAL_SCRIPT = SCRIPT_PATH.read_text(encoding="utf-8")


# ── 台账条目夹具（形状与真实台账一致；只用 `entry_key` 需要的三字段做键） ──────────


def entry(n: int, kind: str = "infra_suspect", rerun: str = "not_rerun") -> dict:
    return {
        "workflow": "PR Check",
        "job": f"job-{n}",
        "run_id": 900000 + n,
        "run_attempt": 1,
        "run_url": f"https://example.invalid/runs/{900000 + n}",
        "pr": 5000 + n,
        "head_sha": "0" * 40,
        "head_branch": "ci/fixture",
        "first_failure_step": "Run unit tests",
        "rerun_result": rerun,
        "kind": kind,
        "observed_at": "2026-09-21T00:00:00Z",
        "reason": "夹具条目",
        "remedy": "夹具条目",
        "status": "open",
        "follow_up": None,
    }


def ledger(entries) -> dict:
    return {"version": 1, "note": "夹具台账", "_schema": "migao.flaky-ledger/1",
            "entries": [dict(e) for e in entries]}


def keys(led) -> set:
    return {FL._key_str(FL.entry_key(e)) for e in led["entries"]}


# ── 真 git 夹具（bare remote + work 检出） ──────────────────────────────────────


def _git(cwd, *args, check=True):
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} 失败（rc={proc.returncode}）："
                             f"{(proc.stderr or proc.stdout).strip()}")
    return proc


def _commit(work, message: str) -> str:
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", message)
    return _git(work, "rev-parse", "HEAD").stdout.strip()


def _write_ledger(work, led) -> None:
    (work / LEDGER_REL).write_text(json.dumps(led, ensure_ascii=False, indent=2) + "\n",
                                   encoding="utf-8")


class Fixture:
    """真 git 夹具：`origin.git`（bare）+ `work`（检出），台账在 `.github/flaky-ledger.json`。"""

    def __init__(self, tmp_path, script_src: str = REAL_SCRIPT):
        self.root = tmp_path / "fx"
        self.bare = self.root / "origin.git"
        self.work = self.root / "work"
        self.root.mkdir(parents=True, exist_ok=True)
        _git(self.root, "init", "-q", "--bare", "--initial-branch=main", str(self.bare))
        _git(self.bare, "config", "receive.denyNonFastForwards", "false")
        _git(self.root, "init", "-q", "--initial-branch=main", str(self.work))
        _git(self.work, "config", "user.name", "fixture")
        _git(self.work, "config", "user.email", "fixture@example.invalid")
        _git(self.work, "remote", "add", "origin", str(self.bare))
        scripts = self.work / ".github" / "scripts"
        scripts.mkdir(parents=True, exist_ok=True)
        (scripts / "flaky_ledger.py").write_text(script_src, encoding="utf-8")

    # —— 拓扑读数（判据一律读**远端 ref**，不读本地 git log）——
    def fetch(self):
        _git(self.work, "fetch", "-q", "--prune", "origin")

    def behind_by(self) -> int:
        self.fetch()
        return int(_git(self.work, "rev-list", "--count",
                        f"origin/{BRANCH}..origin/main").stdout.strip())

    def ahead_by(self) -> int:
        self.fetch()
        return int(_git(self.work, "rev-list", "--count",
                        f"origin/main..origin/{BRANCH}").stdout.strip())

    def branch_contains_main(self) -> bool:
        self.fetch()
        return _git(self.work, "merge-base", "--is-ancestor",
                    "origin/main", f"origin/{BRANCH}", check=False).returncode == 0

    def remote_ledger(self) -> dict:
        self.fetch()
        return json.loads(_git(self.work, "show",
                               f"origin/{BRANCH}:{LEDGER_REL}").stdout)

    def remote_sha(self) -> str:
        self.fetch()
        return _git(self.work, "rev-parse", f"origin/{BRANCH}").stdout.strip()

    def seed_main(self, entries) -> str:
        _write_ledger(self.work, ledger(entries))
        sha = _commit(self.work, f"main: ledger({len(entries)})")
        _git(self.work, "push", "-q", "origin", "main")
        return sha

    def append_on_branch(self, base_sha: str, entries) -> str:
        """在**旧基线**（`base_sha`）上追加并推送 —— 这正是修复前步骤④ 的基线选择。"""
        _git(self.work, "checkout", "-q", "-B", BRANCH, base_sha)
        _write_ledger(self.work, ledger(entries))
        sha = _commit(self.work, f"branch: ledger({len(entries)})")
        _git(self.work, "push", "-q", "origin", BRANCH)
        return sha

    def advance_main(self, entries, marker: str = "squash") -> str:
        """main 前进（模拟台账 PR 被 **squash 合并**：内容进 main，但历史里没有分支提交）。"""
        _git(self.work, "checkout", "-q", "main")
        (self.work / f"{marker}-marker.txt").write_text(f"{marker}\n", encoding="utf-8")
        _write_ledger(self.work, ledger(entries))
        sha = _commit(self.work, f"main: {marker}")
        _git(self.work, "push", "-q", "origin", "main")
        return sha


def squash_fixture(tmp_path) -> Fixture:
    """「main 已前进（squash 合并）+ 分支在旧基线追加」—— issue #5100 的**逐字**形态。"""
    fx = Fixture(tmp_path)
    base = [entry(i) for i in range(3)]
    c1 = fx.seed_main(base)
    pending = base + [entry(3), entry(4)]
    c3 = fx.append_on_branch(c1, pending)
    c2 = fx.advance_main(pending)          # squash：main 的台账内容 == 分支内容
    # 前提自证：分支历史**不含** main 的 squash 提交（否则夹具没在测这条）
    assert _git(fx.work, "merge-base", "--is-ancestor", c3, c2,
                check=False).returncode != 0, "夹具前提变了：分支已包含 main 的提交"
    assert fx.behind_by() == 1, "夹具前提变了：分支应落后 main 1 个提交"
    return fx


# ── 执行出货的步骤④ 正文（真 bash；只把输入路径换成夹具私有路径） ────────────────

_GH_STUB = """#!/bin/sh
case "$1 $2" in
  "pr list") echo "${FIXTURE_PR:-5093}" ;;
  "pr create") echo "https://example.invalid/pull/5093" ;;
  *) exit 0 ;;
esac
"""


def step_body(src: str, needle: str = "flaky_ledger.py append") -> str:
    """从 workflow 源里取**调用形态**命中 `needle` 的步骤 `run:` 正文（原文，不加工）。"""
    wf = yaml.safe_load(src) or {}
    for step in ((wf.get("jobs") or {}).get("triage") or {}).get("steps") or []:
        if needle in (step.get("run") or ""):
            return step["run"]
    raise AssertionError(f"取不到步骤正文（锚点 {needle!r} 失效 ⇒ 先修本测试）")


#: bash 3.2（macOS 自带）把 `$VAR` **紧跟多字节字符**时的首字节当成变量名的一部分
#: （实测 `bash: line 44: BRANCH\xef: unbound variable`；runner 的 bash 5 **没有**这个问题）。
#: ⇒ 夹具只对**这一处**做**可逆**的环境性归一（给变量名加花括号），并机械自证改动仅此而已。
#: ⚠️ 出货步骤④ 已把该形态全部写成 `${BRANCH}` ⇒ **零归一**（见 `test_shipped_step_runs_verbatim`）。
_MULTIBYTE_AFTER_VAR = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)(?=[^\x00-\x7F])")


def _normalize_multibyte(body: str) -> str:
    return _MULTIBYTE_AFTER_VAR.sub(lambda m: "${" + m.group(1) + "}", body)


def _unbrace(src: str) -> str:
    """把 `${NAME}` 折回 `$NAME` —— 只用于自证「改动仅限加花括号」（不用于执行）。"""
    return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", r"$\1", src)


def _run_step(body: str, fx: Fixture, tmp_path, entries) -> subprocess.CompletedProcess:
    """按**原文**执行步骤正文；只做两处**环境性**替换（输入路径 / 变量名加花括号）。"""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(_GH_STUB, encoding="utf-8")
    gh.chmod(0o755)
    entries_file = tmp_path / "flaky-entries.json"
    entries_file.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    with_path = body.replace("/tmp/flaky-entries.json", str(entries_file))
    assert with_path != body, "输入路径锚点失效（先修本测试）"
    assert with_path.replace(str(entries_file), "/tmp/flaky-entries.json") == body, \
        "除输入路径外不得改动步骤正文（红证卫生：判据必须跑**出货的**正文）"
    run_body = _normalize_multibyte(with_path)
    assert _unbrace(run_body) == _unbrace(with_path), \
        "除「给变量名加花括号」外不得改动步骤正文（红证卫生）"
    env = dict(os.environ)
    env.update({
        "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
        "GITHUB_REPOSITORY": "fixture/repo",
        "GITHUB_OUTPUT": str(tmp_path / "gh_output"),
        "RUN_ID": "900123",
        "GH_TOKEN": "fixture",
        "FIXTURE_PR": "5093",
    })
    return subprocess.run(["bash", "-c", run_body], cwd=str(fx.work), env=env,
                          capture_output=True, text=True, errors="replace")


SHIPPED_BODY = step_body(REAL_TRIAGE)


# ── 判据 3 / 4：并集幂等 + 不丢条目（纯函数层） ─────────────────────────────────


class TestUnionIsIdempotentAndLossless:
    """`union_ledgers` = **并集**（幂等键 `workflow|run_id|job`）；复用 `append_entries`。"""

    def test_union_never_loses_entries(self):
        """判据 4（纯函数）：并集后条目数 ≥ max(main, 分支)，且两侧键**全在**。"""
        main = ledger([entry(i) for i in range(3)])
        branch = ledger([entry(i) for i in range(3)] + [entry(7), entry(8)])
        merged = FL.union_ledgers(main, branch)
        assert len(merged["entries"]) >= max(len(main["entries"]), len(branch["entries"]))
        assert keys(main) <= keys(merged), "main 的条目丢了 ⇒ 并集不成立"
        assert keys(branch) <= keys(merged), "分支的条目丢了 ⇒ 并集不成立"
        assert keys(merged) == keys(main) | keys(branch)

    def test_union_is_idempotent(self):
        """判据 3（纯函数）：同一 key 重复并集 ⇒ 条目数不变（且台账自洽：键唯一）。"""
        main = ledger([entry(i) for i in range(3)])
        branch = ledger([entry(i) for i in range(3)] + [entry(3), entry(3), entry(4)])
        once = FL.union_ledgers(main, branch)
        twice = FL.union_ledgers(once, branch)
        assert len(once["entries"]) == len(twice["entries"]) == 5
        assert keys(once) == keys(twice)
        assert FL.ledger_violations(once) == [], "并集后台账必须自洽（幂等键不许重复）"

    def test_union_of_disjoint_sides_keeps_both(self):
        """两侧各有独有条目 ⇒ 并集必须两边都保留（这是「不丢条目」的**判别力**下界）。"""
        main = ledger([entry(1), entry(2), entry(3)])
        branch = ledger([entry(1), entry(2), entry(9)])
        merged = FL.union_ledgers(main, branch)
        assert keys(merged) == keys(main) | keys(branch)
        assert len(merged["entries"]) == 4

    def test_union_keeps_main_order_and_main_version_on_collision(self):
        """同 key 内容不同 ⇒ 以 **main** 为准（main 是已合并的权威态）—— 有意的取舍，钉住它。"""
        main = ledger([entry(1)])
        main["entries"][0]["status"] = "fixed"
        main["entries"][0]["fixed_by"] = 4242
        branch = ledger([entry(1)])            # 分支侧还是 status=open
        merged = FL.union_ledgers(main, branch)
        assert len(merged["entries"]) == 1
        assert merged["entries"][0]["status"] == "fixed"
        assert merged["entries"][0]["fixed_by"] == 4242

    def test_empty_sides_are_not_silently_green(self):
        """空/缺 `entries` 的一侧不许抛错、也不许凭空造条目。"""
        assert keys(FL.union_ledgers(ledger([]), ledger([]))) == set()
        assert len(FL.union_ledgers(ledger([entry(1)]), {} or None)["entries"]) == 1
        assert len(FL.union_ledgers(ledger([entry(1)]), {"entries": None})["entries"]) == 1


# ── 判据 1 / 2 / 6：真 git 夹具（远端 ref 拓扑） ────────────────────────────────


class TestAppendPathSelfHeals:
    """判据 1 / 2 / 6：跑**出货的**步骤④ 正文（真 bash + 真 bare remote）。"""

    def test_pre_fix_implementation_leaves_branch_behind_main(self, tmp_path):
        """判据 1（**改前红**）：修复前的步骤④ ⇒ `behind_by > 0`（会冲突）。"""
        fx = squash_fixture(tmp_path)
        proc = _run_step(PRE_FIX_STEP_BODY, fx, tmp_path, [entry(5)])
        assert proc.returncode == 0, f"修复前实现本应成功推送（夹具问题）：{proc.stderr}"
        assert not fx.branch_contains_main(), "夹具/实现前提变了：分支竟包含 main"
        assert fx.behind_by() > 0, "修复前实现竟不落后 main —— 夹具没在测这条"
        # 内容是**只追加超集**（零信息损失）—— 冲突是纯历史形态的，与 issue 的实测一致
        branch_keys = keys(fx.remote_ledger())
        assert len(branch_keys) == 6, branch_keys

    def test_shipped_implementation_is_not_behind_main(self, tmp_path):
        """判据 2（**改后绿**）：出货的步骤④ ⇒ `behind_by == 0`（不再冲突）。"""
        fx = squash_fixture(tmp_path)
        proc = _run_step(SHIPPED_BODY, fx, tmp_path, [entry(5)])
        assert proc.returncode == 0, f"出货实现执行失败：{proc.stdout}\n{proc.stderr}"
        assert fx.branch_contains_main(), (
            "推前未与 main 对齐 ⇒ 分支落后 main ⇒ 只追加的分支每轮再冲突（#5100 未根治）")
        assert fx.behind_by() == 0, fx.behind_by()
        assert fx.ahead_by() == 1, "对齐后分支应恰好 = main + 1 个追加提交"
        # 并集：分支原独有条目 + main 条目 + 本次条目，一条不丢
        assert len(keys(fx.remote_ledger())) == 6, keys(fx.remote_ledger())

    def test_inject_removing_align_turns_the_criterion_red(self, tmp_path):
        """判据 6（**注入式红证**）：把「推前先对齐」摘掉 ⇒ 判据 2 的断言必须红。

        注入 = 从**唯一**写路径摘掉 `--align-main`（= 退化成修复前「在旧基线上追加」的形态）。
        实测形态：提交落在旧基线 / 被落仓复核拦下 ⇒ **无论如何都不对齐**（`behind_by > 0`），
        即判据 2 的那条断言确实在防这条 —— 它不是空断言。
        """
        mutated = SHIPPED_BODY.replace("--align-main", "")
        assert mutated != SHIPPED_BODY, "注入锚点失效（先修本测试）"
        assert "--align-main" in SHIPPED_BODY, "出货步骤未调用 `--align-main` ⇒ 推前根本没对齐"
        fx = squash_fixture(tmp_path)
        _run_step(mutated, fx, tmp_path, [entry(5)])
        assert not fx.branch_contains_main(), "摘掉对齐后竟仍包含 main ⇒ 判据 2 是空断言"
        assert fx.behind_by() > 0, "摘掉对齐后竟不落后 main ⇒ 判据 2 是空断言"

    def test_repeated_append_of_same_key_is_idempotent(self, tmp_path):
        """判据 3（夹具层）：同一 key 重复追加 ⇒ 条目数不变、无重复键。"""
        fx = squash_fixture(tmp_path)
        first = _run_step(SHIPPED_BODY, fx, tmp_path, [entry(5)])
        assert first.returncode == 0, first.stderr
        after_first = fx.remote_ledger()
        second = _run_step(SHIPPED_BODY, fx, tmp_path, [entry(5)])
        assert second.returncode == 0, second.stderr
        after_second = fx.remote_ledger()
        assert len(after_second["entries"]) == len(after_first["entries"]) == 6
        assert keys(after_second) == keys(after_first)
        assert FL.ledger_violations(after_second) == [], "重复追加造出了重复条目（幂等被破坏）"
        assert fx.behind_by() == 0

    def test_no_entry_is_lost_when_both_sides_have_unique_entries(self, tmp_path):
        """判据 4（夹具层）：main 独有 + 分支独有 ⇒ 对齐重放后**两边都还在**。"""
        fx = Fixture(tmp_path)
        c1 = fx.seed_main([entry(1), entry(2)])
        c3 = fx.append_on_branch(c1, [entry(1), entry(2), entry(9)])
        fx.advance_main([entry(1), entry(2), entry(3)])
        assert fx.behind_by() == 1
        proc = _run_step(SHIPPED_BODY, fx, tmp_path, [entry(5)])
        assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
        got = fx.remote_ledger()
        assert keys(got) == {FL._key_str(FL.entry_key(entry(i))) for i in (1, 2, 3, 5, 9)}, keys(got)
        assert len(got["entries"]) >= 5
        assert fx.behind_by() == 0
        assert _git(fx.work, "merge-base", "--is-ancestor", c3, "HEAD", check=False).returncode != 0

    def test_lease_failure_refetches_instead_of_force_pushing(self, tmp_path):
        """lease 语义（判据 2 的并发面）：推之前别人刚推过 ⇒ **重取重算**，不丢他的条目、不强推。

        机制：`pre-push` 钩子在**首次**推送前把远端分支挪到一个「并发写者」的提交
        （该提交带一条独有条目）⇒ 本次 `--force-with-lease` 必须被拒（`stale info`）
        ⇒ 步骤④ 重取重算 ⇒ 最终：`behind_by == 0` **且**并发写者的条目仍在。
        """
        fx = squash_fixture(tmp_path)
        # 造「并发写者」的提交：在**另一个检出**里基于分支 HEAD 追加一条，推到临时 ref（只送对象）
        racer = tmp_path / "racer"
        _git(tmp_path, "clone", "-q", str(fx.bare), str(racer))
        _git(racer, "config", "user.name", "racer")
        _git(racer, "config", "user.email", "racer@example.invalid")
        _git(racer, "checkout", "-q", BRANCH)
        racer_ledger = json.loads((racer / LEDGER_REL).read_text(encoding="utf-8"))
        racer_ledger["entries"].append(entry(77))
        _write_ledger(racer, racer_ledger)
        _git(racer, "add", "-A")
        _git(racer, "commit", "-q", "-m", "racer: append 77")
        racer_sha = _git(racer, "rev-parse", "HEAD").stdout.strip()
        _git(racer, "push", "-q", "origin", f"{racer_sha}:refs/heads/lease-race-objects-only")
        sentinel = tmp_path / "hook-fired"
        hook = fx.work / ".git" / "hooks" / "pre-push"
        hook.write_text(
            "#!/bin/sh\n"
            f'if [ ! -f "{sentinel}" ]; then\n'
            f'  touch "{sentinel}"\n'
            f'  git -C "{fx.bare}" update-ref refs/heads/{BRANCH} {racer_sha}\n'
            "fi\nexit 0\n", encoding="utf-8")
        hook.chmod(0o755)
        proc = _run_step(SHIPPED_BODY, fx, tmp_path, [entry(5)])
        assert sentinel.exists(), "钩子没触发 ⇒ 本用例没在测并发（夹具失效）"
        assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
        assert "lease" in proc.stderr or "lease" in proc.stdout, \
            "未见 lease 失败告警 ⇒ 未走到「重取重算」分支"
        got = keys(fx.remote_ledger())
        assert FL._key_str(FL.entry_key(entry(77))) in got, "并发写者的条目被强推丢了（不许强推）"
        assert FL._key_str(FL.entry_key(entry(5))) in got, "本次条目没落仓"
        assert fx.behind_by() == 0, "重取重算后仍落后 main ⇒ 自愈失败"

    def test_bootstrap_when_branch_does_not_exist(self, tmp_path):
        """引导期（分支还不存在）：不许因缺分支而红 —— 并集退化为 main + 本次条目。"""
        fx = Fixture(tmp_path)
        fx.seed_main([entry(1), entry(2)])
        proc = _run_step(SHIPPED_BODY, fx, tmp_path, [entry(5)])
        assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
        assert keys(fx.remote_ledger()) == {FL._key_str(FL.entry_key(entry(i))) for i in (1, 2, 5)}
        assert fx.behind_by() == 0

    def test_align_is_fail_closed_when_main_ledger_is_unreadable(self, tmp_path):
        """取不到 main 侧台账 ⇒ **必须红**（不许当「main 无条目」继续 ⇒ 那会丢 main 的条目）。"""
        fx = Fixture(tmp_path)
        fx.seed_main([entry(1)])
        _git(fx.work, "rm", "-q", LEDGER_REL)
        _git(fx.work, "commit", "-q", "-m", "main: 台账文件被删（畸形态）")
        _git(fx.work, "push", "-q", "origin", "main")
        proc = _run_step(SHIPPED_BODY, fx, tmp_path, [entry(5)])
        assert proc.returncode != 0, "取不到 main 台账却继续 ⇒ 静默丢条目（fail-closed 缺失）"
        assert "::error::" in proc.stdout + proc.stderr


# ── 判据 5：单一写者 ───────────────────────────────────────────────────────────


def _workflow_steps(src: str) -> list:
    wf = yaml.safe_load(src) or {}
    out = []
    for job in (wf.get("jobs") or {}).values():
        for step in (job or {}).get("steps") or []:
            parts = [step.get("run") or "", str((step.get("with") or {}).get("script") or "")]
            env = step.get("env")
            if isinstance(env, dict):
                parts.extend(str(v) for v in env.values())
            out.append("\n".join(parts))
    return out


#: 写台账的**调用形态**（不是「提及」——本仓库「提及 ≠ 调用」已踩过多次）
_WRITE_CALL = re.compile(r"flaky_ledger\.py\s+append\b")
_LEDGER_ADD = "git add .github/flaky-ledger.json"
_PUSH_CMD = re.compile(r"git\s+push\b")


def _command_form(text: str) -> str:
    """剥掉**引号串**与 `#` 注释 ⇒ 只留**命令本体**（判据读结构化位置，不读「文本里提到过」）。

    ⚠️ 为什么必须这样（本仓库「提及 ≠ 调用」的**第 4 次**现场；前三次：`--disable-auto` /
    `autoMergeRequest` / `head_branch=`）：`flaky-ledger-reconcile.yml` 的**错误提示文案**里
    **逐字**写着 `git push --force-with-lease origin HEAD:$LEDGER_BRANCH`（#5102 给人工留的
    「可行动出口」）⇒ 裸子串判据会把「给建议」读成「第二个写者」= **判据被自己的文案喂红**
    （§17.3「判据能被自己的文案 / 输出喂绿」的**镜像形态**，同一缺陷类）。
    """
    out = []
    for line in text.splitlines():
        line = re.sub(r'"(?:[^"\\]|\\.)*"', '""', line)     # 双引号串
        line = re.sub(r"'(?:[^'\\]|\\.)*'", "''", line)     # 单引号串
        line = re.sub(r"(?<!\S)#.*$", "", line)             # 行首/空白后的 `#` 注释
        out.append(line)
    return "\n".join(out)


def ledger_writers(src: str) -> list:
    """返回写 `chore/flaky-ledger` 的步骤下标（空 = 本文件不写台账）。

    判据只看**命令本体**（`_command_form`）：写调用（`flaky_ledger.py append` / `git add` 台账文件）
    或**真实命令行** `git push`（该 workflow 与这条分支有关时）。
    """
    branch_named = BRANCH in src
    hits = []
    for i, raw in enumerate(_workflow_steps(src)):
        cmd = _command_form(raw)
        if _WRITE_CALL.search(cmd) or _LEDGER_ADD in cmd:
            hits.append(i)
        elif branch_named and _PUSH_CMD.search(cmd):
            hits.append(i)
    return hits


class TestSingleWriter:
    """判据 5：这条分支仍然**只有一个写者**（`flaky-triage.yml`）。"""

    def test_only_triage_writes_the_ledger_branch(self):
        writers = {p.name for p in sorted(WORKFLOWS.glob("*.yml"))
                   if ledger_writers(p.read_text(encoding="utf-8"))}
        assert writers == {TRIAGE_NAME}, (
            f"写 `{BRANCH}` 的 workflow 不止一个：{sorted(writers)} ⇒ 双写者会互相覆盖（#5100 的修法前提）")

    def test_reconcile_only_reads_and_approves(self):
        """兜底 workflow 只 approve/arm：**不写内容**（否则第二个写者与主路径打架）。

        「不写」的**结构性声明** = `permissions.contents: read`（**不是**在自由文本里搜命令）——
        该文件的错误文案里逐字含 `git push`（给人工的建议），故文本判据只认**命令本体**。
        """
        src = RECONCILE_PATH.read_text(encoding="utf-8")
        assert ledger_writers(src) == [], "兜底 workflow 竟在写台账 ⇒ 引入第二个写者"
        assert not _PUSH_CMD.search(_command_form(src)), \
            "兜底 workflow 出现**命令本体**的 `git push` ⇒ 第二个写者（文案里的建议不算调用）"
        assert re.search(r"flaky_ledger\.py\s+(ledger-drift|approve)\b", src), \
            "兜底必须复用主路径脚本（否则判据会漂移）"
        perms = (yaml.safe_load(src) or {}).get("permissions") or {}
        assert str(perms.get("contents") or "").lower() == "read", \
            "兜底必须 `contents: read`（写权限 = 写者的前提条件）"

    def test_red_proof_a_second_writer_is_detected(self):
        """注入式红证：给兜底 workflow 塞一个写调用 ⇒ 判据 5 必须红。"""
        src = RECONCILE_PATH.read_text(encoding="utf-8")
        mutated = src.replace(
            "run: python3 .github/scripts/flaky_ledger.py selftest",
            "run: python3 .github/scripts/flaky_ledger.py append --ledger .github/flaky-ledger.json", 1)
        assert mutated != src, "注入锚点失效（先修本测试）"
        assert ledger_writers(mutated) != [], "注入第二个写者后判据 5 仍绿 ⇒ 空断言"

    def test_red_proof_a_real_push_command_is_detected(self):
        """注入式红证：塞一条**真命令行**（**不在任何字符串里**）⇒ 判据 5 必须红；还原 ⇒ 绿。

        这条专门钉「文案 vs 命令」的判别力：该文件**本来就有** `git push` 字样（在错误文案里），
        故「注入一条命令本体的 push ⇒ 必须红」才是**可单独变红**的判据（不会红的断言 = 空断言）。
        还原用**内容指纹**自证（§19.1 元规则 ③：不用 mtime / size）。
        """
        src = RECONCILE_PATH.read_text(encoding="utf-8")
        fingerprint = hashlib.sha256(src.encode("utf-8")).hexdigest()
        mutated = src.replace(
            "        run: python3 .github/scripts/flaky_ledger.py selftest",
            "        run: |\n"
            "          git push --force-with-lease origin HEAD:$LEDGER_BRANCH\n"
            "          python3 .github/scripts/flaky_ledger.py selftest", 1)
        assert mutated != src, "注入锚点失效（先修本测试）"
        assert _PUSH_CMD.search(_command_form(mutated)), "注入没落到**命令本体**上（先修本测试）"
        assert ledger_writers(mutated) != [], \
            "注入**命令本体**的 push 后判据 5 仍绿 ⇒ 判据是空断言（只认不了真命令）"
        # 还原自证（内容指纹）：源文件一字未改 ⇒ 判据绿
        restored = RECONCILE_PATH.read_text(encoding="utf-8")
        assert hashlib.sha256(restored.encode("utf-8")).hexdigest() == fingerprint, \
            "源文件在用例期间被改动（夹具不干净）"
        assert ledger_writers(restored) == []


# ── 既有护栏锚点（**不由本包修改**的测试文件依赖它们） ───────────────────────────


class TestShippedStepKeepsExistingAnchors:
    """步骤④ 被本包重写 ⇒ 钉住**别人**（`test_flaky_triage.py` / `test_flaky_ledger_reconcile.py`）
    依赖的逐字锚点，并逐条给注入式红证（锚点漂了要**显式**红，而不是在别的文件里莫名其妙红）。"""

    ANCHORS = (
        "flaky_ledger.py append",
        "if git diff --quiet -- .github/flaky-ledger.json; then",
        "git rev-parse FETCH_HEAD",
        'BRANCH="chore/flaky-ledger"',
        "::error::",
    )

    def test_anchors_are_present_in_the_shipped_step(self):
        missing = [a for a in self.ANCHORS if a not in SHIPPED_BODY]
        assert missing == [], f"步骤④ 丢了既有护栏锚点 {missing} ⇒ 别的守卫文件会红"

    def test_red_proof_each_anchor_is_load_bearing(self):
        """每条锚点各注入一次 ⇒ 必须能被检出，且**恰好**打掉它自己（判据可分离）。"""
        for anchor in self.ANCHORS:
            mutated = SHIPPED_BODY.replace(anchor, "X" + anchor[1:])
            assert mutated != SHIPPED_BODY, f"注入锚点失效（先修本测试）：{anchor!r}"
            assert [a for a in self.ANCHORS if a not in mutated] == [anchor], (
                f"注入 {anchor!r} 连带打掉了别的锚点（或没生效）⇒ 判据不可分离")

    def test_idempotency_gate_line_keeps_its_indent(self):
        """幂等闸那行必须仍在**顶层 10 空格**缩进（别的文件按整行匹配，缩进变了就失效）。"""
        line = "          if git diff --quiet -- .github/flaky-ledger.json; then\n"
        assert line in REAL_TRIAGE, "幂等闸行被改了缩进/内容 ⇒ test_flaky_ledger_reconcile.py 会红"

    def test_shipped_step_runs_verbatim_on_local_bash(self):
        """出货步骤④ **不需要任何环境性归一**（判据跑的就是逐字出货正文）。

        bash 3.2（macOS 自带）会把 `$BRANCH（` 的多字节首字节当成变量名的一部分
        （bash 5 = runner 的真实环境没有这个问题）⇒ 变量名紧跟非 ASCII 字符时必须写 `${NAME}`。
        这条红了说明判据不再逐字执行出货正文（判据降级），或被重新引入该形态。
        """
        assert _MULTIBYTE_AFTER_VAR.search(SHIPPED_BODY) is None, \
            "步骤④ 出现「变量名紧跟非 ASCII 字符」⇒ 本机 bash 无法逐字执行出货正文"

    def test_align_is_opt_in_and_used_by_the_only_write_path(self):
        """`--align-main` 必须是**显式开关**（默认语义不变），且**唯一**写路径必须传它。"""
        assert "--align-main" in SHIPPED_BODY, "唯一写路径没传 `--align-main` ⇒ 推前根本没对齐"
        assert '"--align-main", action="store_true"' in REAL_SCRIPT, \
            "`--align-main` 必须是 opt-in（默认对齐会静默改变 `append` 的语义）"


# ── 「改前」实现的溯源交叉校验（§18.3：红证锚点禁读可变引用） ─────────────────────


class TestPreFixProvenance:
    def test_inline_pre_fix_body_matches_git_history(self):
        """内联的「改前」正文必须与**不可变提交** `@1e4f17d80` 逐字一致（浅克隆 ⇒ skip）。"""
        proc = subprocess.run(["git", "cat-file", "-e", f"{PRE_FIX_SHA}^{{commit}}"],
                              cwd=str(REPO_ROOT), capture_output=True, text=True)
        if proc.returncode != 0:
            pytest.skip(f"本地没有 {PRE_FIX_SHA}（浅克隆）⇒ 无法交叉校验；"
                        "内联片段仍是逐字节出处，见本文件模块 docstring")
        old = subprocess.run(["git", "show", f"{PRE_FIX_SHA}:.github/workflows/flaky-triage.yml"],
                             cwd=str(REPO_ROOT), capture_output=True, text=True)
        assert old.returncode == 0, old.stderr
        assert step_body(old.stdout) == PRE_FIX_STEP_BODY, \
            "内联的「改前」正文与 git 历史不一致 ⇒ 判据 1 的锚点是编的（先修本测试）"
