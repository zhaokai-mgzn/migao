# case_ids: MC-140
"""批次合并工具判据（`scripts/batch_merge_lib.py` / `scripts/batch-merge.sh`，issue #8321）。

## 为什么单列这一条

多 PR 同批落地时，**逐个合 = N×28 个 required job**（分支保护 `strict=true`），合批 = **1×28**。
今晚人工做过一次（PR #8519），踩了四个坑（冲突全在追加型台账上 / 用例号互撞 /
`--no-commit` 后不提交就合下一支 rc=128 / 批量 body 不能带关闭词）——本工具就是用来根治它们的。
⇒ 判据必须钉住**这四件事本身**，而不是"工具能跑通"。

## 判据（6 条，每条都带**可执行**红证）

| # | 判什么 | 红证（注入方式，见对应测试） |
|---|---|---|
| ① | 两个 PR 各加一条用例 ⇒ 合批后**两条都在**、全语料**无重复 id** | 把让号逻辑删掉（`plan_renames → []`）⇒ ② 的「无重复 id」当场红 |
| ② | 两个 PR 同占一个用例号 ⇒ **后合入者让号**，claim 文件名/内容、测试文件头 `# case_ids:`、渲染物**同步** | 同 ①（删让号 ⇒ claim/文件头/渲染三条断言同时红） |
| ③ | 锚点「**从 origin/main 重建 + 实测重锚**」⇒ 产出能过**真**判据 `test_case_machine_fail_channel.py` | 把锚点换成 main 版（= `--ours` 解冲突的产物）⇒ 真判据必红 |
| ④ | 「是否在合并中」用 `git rev-parse -q --verify MERGE_HEAD` | 夹具是 **worktree**（`.git` 是文件）⇒ `Path(".git")/"MERGE_HEAD"` **恒不存在**（同一现场实测 False） |
| ⑤ | 生成的 PR body **零关闭关键词**（且 body 里确实带 `#NNNN` 引用 ⇒ 不是空断言） | 用 `pr_body_guard.find_close_keywords` **同一实现**断言 = 0；负控 = body 含 `#9001` 却不命中 |
| ⑥ | `--dry-run` **零落盘**（不建分支/不提交/不动远端） | 正控 = 去掉 `--dry-run` 后同一夹具的分支表与提交数**确实**变了（否则"没变"是空断言） |

## 夹具（不碰真仓库）

每个用例在 `tmp_path` 里 **造一个 bare origin + 一个 clone + 一个 worktree**（worktree 是判据 ④ 的
必要形态：`.git` 是**文件**），把下面这些**真实实现**拷进去再跑：

  `.github/{render_cases,yaml_light,cases_yaml,assertion_taxonomy}.py`、
  `tests/unit_ci_workflows/test_case_machine_fail_channel.py`（**真**锚点判据）、
  `scripts/{batch_merge_lib.py,batch-merge.sh,pr_body_guard.py}`（**真**工具与**真**守卫）。

⇒ 渲染、锚点测量、body 守卫走的都是**生产同一份实现**（不是替身）。
`gh` 用桩（`BATCH_MERGE_GH_BIN`）—— 只替身"读 PR 元数据 / 开 draft PR"这一层网络面。

## 边界（照实登记，§19.1）

- ❌ 判不了"合批后 CI 会不会绿"：那是集成分支的 CI 的事，本判据只保证**工具产出内部一致**；
- ❌ 判不了"让号后与**批次之外**的在飞 PR 撞不撞"（工具只用批次内 `max+1`，见模块 docstring 的覆盖面）；
- ❌ 判不了"未知冲突面的语义合并"：判据只保证它 **fail-closed**（那段逻辑在 `resolve_conflicts`，
  本文件未覆盖它的红证 —— 有意留下：真实未知冲突是**业务语义**，无法在夹具里诚实构造）。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import batch_merge_lib as lib  # noqa: E402

TODAY = "2026-11-03"
BRANCH = f"batch/{TODAY}"
PR_ONE, PR_TWO = 9001, 9002

#: 夹具基线用例（`get_smoke_cases()` / `get_adversarial_cases()` 要求**非空且 skip_reason 为空**
#: ⇒ MC-001/002 必须带机器计分断言；MC-003 是 `[backend-contract]`（计入 scoring==0 的读数））
MISC_BASE = """schema: "case-contract/1.0"
domain: misc

cases:
  - id: MC-001
    legacy_id: ""
    title: "夹具基线：冒烟档 + 机器计分断言"
    domains:
      - misc
    tier: smoke
    tags:
      - fixture
    truths_ref: []
    user_inputs:
      - "夹具输入"
    expectations: []
    data_checks:
      - "生成成功（$.data[i].success=true）"
    skip_reason: ""
    merge_log: "夹具基线（MC-001）"
    traces:
      tests:
        - "tests/unit_ci_workflows/test_fixture_contracts.py"
      ci:
        - pr-check.yml
      verifies: []
  - id: MC-002
    legacy_id: ""
    title: "夹具基线：对抗档 + 机器计分断言"
    domains:
      - misc
    tier: adversarial
    tags:
      - fixture
    truths_ref: []
    user_inputs:
      - "夹具输入"
    expectations: []
    data_checks:
      - "越权被拒（$.error.code=PERMISSION_DENIED）"
    skip_reason: ""
    merge_log: "夹具基线（MC-002）"
    traces:
      tests:
        - "tests/unit_ci_workflows/test_fixture_contracts.py"
      ci:
        - pr-check.yml
      verifies: []
  - id: MC-003
    legacy_id: ""
    title: "夹具基线：走豁免通道的用例"
    domains:
      - misc
    tier: normal
    tags:
      - fixture
    truths_ref: []
    user_inputs:
      - "夹具输入"
    expectations: []
    data_checks:
      - "**会红**：夹具断言（由 tests/unit_ci_workflows/test_fixture_contracts.py 承担）"
    skip_reason: "[backend-contract] 夹具判据由 tests/unit_ci_workflows/test_fixture_contracts.py 验证，非 LLM 行为"
    merge_log: "夹具基线（MC-003）"
    traces:
      tests:
        - "tests/unit_ci_workflows/test_fixture_contracts.py"
      ci:
        - pr-check.yml
      verifies: []
"""

#: 负控需要**真实形态**的两条（`test_case_machine_fail_channel.py` 的负控按 id 取它们）：
#: PG-001 = 有 `success=true` 计分断言（不在 53 里）；PG-002 = `[backend-contract]` + traces（在 53 里）
PROCESSING_BASE = """schema: "case-contract/1.0"
domain: processing-order

cases:
  - id: PG-001
    legacy_id: ""
    title: "夹具：有机器计分断言的用例（负控 ②）"
    domains:
      - processing-order
    tier: normal
    tags:
      - fixture
    truths_ref: []
    user_inputs:
      - "夹具输入"
    expectations: []
    data_checks:
      - "生成加工单成功（$.data[i].success=true）"
    skip_reason: ""
    merge_log: "夹具基线（PG-001）"
    traces:
      tests:
        - "tests/unit_ci_workflows/test_fixture_contracts.py"
      ci:
        - pr-check.yml
      verifies: []
  - id: PG-002
    legacy_id: ""
    title: "夹具：走豁免通道的用例（负控 ①）"
    domains:
      - processing-order
    tier: normal
    tags:
      - fixture
    truths_ref: []
    user_inputs:
      - "夹具输入"
    expectations: []
    data_checks:
      - "**会红**：夹具断言（由 tests/unit_ci_workflows/test_fixture_contracts.py 承担）"
    skip_reason: "[backend-contract] 夹具判据由 tests/unit_ci_workflows/test_fixture_contracts.py 验证，非 LLM 行为"
    merge_log: "夹具基线（PG-002）"
    traces:
      tests:
        - "tests/unit_ci_workflows/test_fixture_contracts.py"
      ci:
        - pr-check.yml
      verifies: []
"""

#: 基线锚点：`entries` 必须与实测一致（MC-001/002/003 + PG-002 = 4 条 scoring==0）
ANCHOR_BASE = {
    "_note": "夹具：复刻 #5079 的「53 条读数 + traces.tests 分流」出处说明（只为满足锚点出处判据）。",
    "_anchor_sha": "0000000000000000000000000000000000000000",
    "entries": {"no_channel_total": 0, "backend_contract_scoring_zero": 2},
    "history": [{"sha": "000000000000", "date": TODAY, "no_channel_total": 0,
                 "backend_contract_scoring_zero": 2, "note": "夹具基线"}],
}

#: 拷进夹具的**生产实现**（真渲染器 / 真锚点判据 / 真工具 / 真守卫）
COPY = (
    ".github/render_cases.py",
    ".github/yaml_light.py",
    ".github/cases_yaml.py",
    ".github/assertion_taxonomy.py",
    "tests/unit_ci_workflows/test_case_machine_fail_channel.py",
    "scripts/batch_merge_lib.py",
    "scripts/batch-merge.sh",
    "scripts/pr_body_guard.py",
)

GH_STUB = '''#!/usr/bin/env python3
"""夹具替身 gh：只实现 `pr view`（读元数据）与 `pr create`（记录 body）。"""
import json, pathlib, shutil, sys

here = pathlib.Path(__file__).resolve().parent
args = sys.argv[1:]
if args[:2] == ["pr", "view"]:
    print(json.dumps(json.loads((here / "prs.json").read_text())[args[2]]))
    sys.exit(0)
if args[:2] == ["pr", "create"]:
    body = args[args.index("--body-file") + 1]
    shutil.copyfile(body, here / "created-body.md")
    (here / "created-args.json").write_text(json.dumps(args, ensure_ascii=False))
    print("https://example.invalid/pull/9999")
    sys.exit(0)
sys.exit(3)
'''

_CONTRACT_TEST = """# 夹具契约判据（被夹具用例的 traces.tests 引用）

def test_fixture_contracts():
    assert True
"""


class Fixture:
    """临时仓库现场：bare origin + clone（main）+ worktree（`--detach origin/main`）。"""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.origin = tmp / "origin.git"
        self.clone = tmp / "clone"
        self.wt = tmp / "wt"
        self.stub_dir = tmp / "gh"
        self.stub = self.stub_dir / "gh"
        self.prs = {
            str(PR_ONE): {"number": PR_ONE, "state": "OPEN", "isDraft": False,
                          "headRefName": "pr/one", "baseRefName": "main",
                          "headRefOid": "0" * 40, "title": "PR 一：新增 MC-140",
                          "url": "https://example.invalid/pull/9001"},
            str(PR_TWO): {"number": PR_TWO, "state": "OPEN", "isDraft": False,
                          "headRefName": "pr/two", "baseRefName": "main",
                          "headRefOid": "0" * 40, "title": "PR 二：也占 MC-140（应让号）",
                          "url": "https://example.invalid/pull/9002"},
        }

    # ── 便捷读数 ────────────────────────────────────────────────────────────
    def git(self, *args, check=True):
        return _sh(["git", "-C", str(self.wt), *args], check=check)

    def head(self) -> str:
        return self.git("rev-parse", "HEAD").stdout.strip()

    def commit_count(self) -> int:
        """集成分支上**新增**的提交数（`origin/main..HEAD`；两支 merge + 一次清理 = 3）。"""
        return int(self.git("rev-list", "--count", "origin/main..HEAD").stdout.strip())

    def branches(self) -> "set[str]":
        return {ln.strip().lstrip("* ").strip()
                for ln in self.git("branch", "--format=%(refname:short)").stdout.splitlines()
                if ln.strip()}

    def all_case_ids(self) -> "list[str]":
        out = []
        for f in sorted((self.wt / lib.CASES_DIR).glob("*.yml")):
            out += [cid for cid, _ in lib.split_blocks(f.read_text(encoding="utf-8"))]
        return out

    def git_dir(self) -> Path:
        return Path(self.git("rev-parse", "--absolute-git-dir").stdout.strip())

    def anchor(self) -> dict:
        return json.loads((self.wt / lib.ANCHOR).read_text(encoding="utf-8"))

    def env(self) -> dict:
        return {**os.environ, "BATCH_MERGE_GH_BIN": str(self.stub),
                "BATCH_MERGE_TODAY": TODAY}


def _sh(cmd, cwd=None, env=None, check=True):
    p = subprocess.run([str(c) for c in cmd], cwd=str(cwd) if cwd else None,
                       text=True, capture_output=True, env=env)
    if check and p.returncode != 0:
        raise AssertionError(f"命令失败：{' '.join(str(c) for c in cmd)}\n{p.stdout}\n{p.stderr}")
    return p


def _write(repo: Path, files: dict) -> None:
    for rel, text in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def _case_block(cid: str, title: str) -> str:
    return f"""  - id: {cid}
    legacy_id: ""
    title: "{title}"
    domains:
      - misc
    tier: normal
    tags:
      - fixture
    truths_ref: []
    user_inputs:
      - "夹具输入"
    expectations: []
    data_checks:
      - "**会红**：夹具断言（由 tests/unit_ci_workflows/test_fixture_contracts.py 承担）"
    skip_reason: "[backend-contract] 夹具判据由 tests/unit_ci_workflows/test_fixture_contracts.py 验证，非 LLM 行为"
    merge_log: "批次合并夹具（{cid}）"
    traces:
      tests:
        - "tests/unit_ci_workflows/test_fixture_contracts.py"
      ci:
        - pr-check.yml
      verifies: []
"""


def _claim(pr: int, cid: str) -> str:
    return json.dumps({"id": cid, "pr": pr, "title": f"夹具 claim {cid}",
                       "claimed_at": TODAY}, ensure_ascii=False, indent=2) + "\n"


def _anchor_with_row(n: int) -> str:
    """分支侧像**单个 PR**那样自己重锚一行（这正是合批时要被「取 main 版 + 实测重锚」取代的东西）。"""
    data = json.loads(json.dumps(ANCHOR_BASE))
    data["entries"] = {"no_channel_total": 0, "backend_contract_scoring_zero": n}
    data["history"] = data["history"] + [{
        "sha": "111111111111", "date": TODAY, "no_channel_total": 0,
        "backend_contract_scoring_zero": n, "note": f"单支 PR 自己重锚到 {n}"}]
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def _new_branch(clone: Path, name: str, files: dict, msg: str) -> None:
    _sh(["git", "-C", str(clone), "checkout", "-q", "-B", name, "main"])
    _write(clone, files)
    _sh(["git", "-C", str(clone), "add", "-A"])
    _sh(["git", "-C", str(clone), "commit", "-q", "-m", msg])
    _sh(["git", "-C", str(clone), "checkout", "-q", "main"])


def build(tmp: Path) -> Fixture:
    fx = Fixture(tmp)
    _sh(["git", "init", "--bare", "-q", str(fx.origin)])
    _sh(["git", "-C", str(fx.origin), "symbolic-ref", "HEAD", "refs/heads/main"])
    _sh(["git", "clone", "-q", str(fx.origin), str(fx.clone)])
    for k, v in (("user.email", "migao-agent@loop.local"), ("user.name", "migao-agent"),
                 ("commit.gpgsign", "false")):
        _sh(["git", "-C", str(fx.clone), "config", k, v])

    for rel in COPY:
        src, dst = REPO_ROOT / rel, fx.clone / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
        dst.chmod(src.stat().st_mode)                       # 保住 `batch-merge.sh` 的可执行位

    _write(fx.clone, {
        ".github/cases/misc.yml": MISC_BASE,
        ".github/cases/processing-order.yml": PROCESSING_BASE,
        ".github/workflows/pr-check.yml": "name: pr-check\non: pull_request\n",
        "backend/admin-api/pom.xml": "<project/>\n",
        lib.ANCHOR: json.dumps(ANCHOR_BASE, ensure_ascii=False, indent=2) + "\n",
        "tests/unit_ci_workflows/test_fixture_contracts.py": _CONTRACT_TEST,
    })
    (fx.clone / "docs/testing").mkdir(parents=True, exist_ok=True)   # 渲染器不建 md 的父目录
    # 基线生成物由**真渲染器**产出（与生产同一份实现）
    _sh([sys.executable, str(fx.clone / lib.RENDER), "--cases", lib.CASES_DIR,
         "--out-eval", lib.EVAL_OUT, "--out-md", lib.CASEBOOK], cwd=fx.clone)
    _sh(["git", "-C", str(fx.clone), "add", "-A"])
    _sh(["git", "-C", str(fx.clone), "commit", "-q", "-m", "fixture base"])
    _sh(["git", "-C", str(fx.clone), "push", "-q", "-u", "origin", "main"])

    _new_branch(fx.clone, "pr/one", {
        ".github/cases/misc.yml": MISC_BASE + _case_block("MC-140", "PR 一新增的用例"),
        ".github/cases/claims/9001-MC-140.json": _claim(PR_ONE, "MC-140"),
        "tests/unit_ci_workflows/test_batch_one.py": "# case_ids: MC-140\n\ndef test_one():\n    assert True\n",
        lib.ANCHOR: _anchor_with_row(3),
    }, "pr one: add MC-140")
    _new_branch(fx.clone, "pr/two", {
        ".github/cases/misc.yml": MISC_BASE + _case_block("MC-140", "PR 二**也**占 MC-140 的用例"),
        ".github/cases/claims/9002-MC-140.json": _claim(PR_TWO, "MC-140"),
        "tests/unit_ci_workflows/test_batch_two.py": "# case_ids: MC-140\n\ndef test_two():\n    assert True\n",
        lib.ANCHOR: _anchor_with_row(3),
    }, "pr two: add MC-140 too")
    _sh(["git", "-C", str(fx.clone), "push", "-q", "origin", "pr/one", "pr/two"])
    _sh(["git", "-C", str(fx.clone), "fetch", "-q", "origin"])

    _sh(["git", "-C", str(fx.clone), "worktree", "add", "--detach", str(fx.wt), "origin/main"])

    fx.stub_dir.mkdir(parents=True, exist_ok=True)
    fx.stub.write_text(GH_STUB, encoding="utf-8")
    fx.stub.chmod(0o755)
    (fx.stub_dir / "prs.json").write_text(json.dumps(fx.prs), encoding="utf-8")
    return fx


@pytest.fixture()
def fx(tmp_path, monkeypatch):
    fixture = build(tmp_path)
    for k, v in fixture.env().items():
        monkeypatch.setenv(k, v)
    return fixture


def run_tool(fx: Fixture, *extra, prs=(PR_ONE, PR_TWO)):
    """**进程内**跑工具（红证要能 monkeypatch 内部函数）。"""
    return lib.main([str(p) for p in prs] + [str(e) for e in extra], cwd=str(fx.wt))


def run_entry(fx: Fixture, *extra, prs=(PR_ONE, PR_TWO)):
    """**真入口**（`scripts/batch-merge.sh`）跑工具 —— 证明接线在，不只是判据本体绿（§28.2）。"""
    return _sh([str(fx.wt / "scripts" / "batch-merge.sh"), *[str(p) for p in prs],
                *[str(e) for e in extra]], cwd=fx.wt, env=fx.env(), check=False)


def run_anchor_test(fx: Fixture):
    return _sh([sys.executable, "-m", "pytest", lib.ANCHOR_TEST, "-q"],
               cwd=fx.wt, env=fx.env(), check=False)


# ══════════════════════════════════════════════════════════════════════════════
# ① / ② 合批后两条都在 + 后合入者让号（claim / 文件头 / 渲染物同步）
# ══════════════════════════════════════════════════════════════════════════════

def test_batch_lands_both_prs_and_renumbers_the_later_one(fx):
    """① + ②：两条用例都在、无重复 id；后合入者让号且三处同步。"""
    p = run_entry(fx)                                       # 走真入口（接线判据）
    assert p.returncode == 0, f"{p.stdout}\n{p.stderr}"
    assert "让号" in p.stdout, "工具没有报告让号 —— ② 的「谁让给谁」必须打印给人复算"

    ids = fx.all_case_ids()
    assert "MC-140" in ids and "MC-141" in ids, f"两条用例没有都落地：{sorted(set(ids))}"
    assert len(ids) == len(set(ids)), f"语料里仍有重复 id：{sorted(ids)}"

    # 后合入者（PR 二）让号 —— 号归先合入的那一支
    assert "PR 一新增的用例" in (fx.wt / ".github/cases/misc.yml").read_text(encoding="utf-8")
    assert "也**占 MC-140" in (fx.wt / ".github/cases/misc.yml").read_text(encoding="utf-8")
    claims = sorted(p.name for p in (fx.wt / ".github/cases/claims").glob("*.json"))
    assert claims == ["9001-MC-140.json", "9002-MC-141.json"], f"claim 文件没跟让号同步：{claims}"
    loser = json.loads((fx.wt / ".github/cases/claims/9002-MC-141.json").read_text(encoding="utf-8"))
    assert loser["id"] == "MC-141", "claim 的 `id` 字段没改 ⇒ 让号只改了文件名"

    # 测试文件头 `# case_ids:` 同步（growth gate 的唯一声明面）
    assert (fx.wt / "tests/unit_ci_workflows/test_batch_one.py").read_text(
        encoding="utf-8").startswith("# case_ids: MC-140")
    assert (fx.wt / "tests/unit_ci_workflows/test_batch_two.py").read_text(
        encoding="utf-8").startswith("# case_ids: MC-141"), "让号没同步到测试文件头 ⇒ QA Growth Gate 会 red"

    # 渲染物同步（重渲染 ⇒ 新号出现在生成物里）
    rendered = (fx.wt / lib.EVAL_OUT / "misc.py").read_text(encoding="utf-8")
    assert "MC-140" in rendered and "MC-141" in rendered

    # 每支都必须成功提交（= 2 个 merge commit）+ 收尾一次清理提交；
    # 集成分支上新增的提交总数 = 2 个被合入的支线提交 + 2 个 merge + 1 个清理 = 5
    merges = [ln for ln in fx.git("rev-list", "--merges", "origin/main..HEAD").stdout.splitlines() if ln]
    assert len(merges) == 2, f"merge commit 数不对：{len(merges)}（每支都必须成功提交）"
    assert fx.commit_count() == 5, f"提交总数不对：{fx.commit_count()}（2 支线 + 2 merge + 1 清理）"
    assert fx.git("log", "-1", "--format=%s").stdout.startswith("chore(batch)"), \
        "收尾提交（重渲染 + 实测重锚）缺失"


def test_red_proof_without_renumbering_duplicate_ids_survive(fx, monkeypatch):
    """② 的红证：把让号逻辑删掉（`plan_renames → []`）⇒ 重复 id 当场留下。

    「后合入者让号」这条判据的判别力就在这里：删掉它，`test_batch_lands_both_prs_and_renumbers_the_later_one`
    的「无重复 id / claim 同步 / 文件头同步」三条会同时红。
    """
    monkeypatch.setattr(lib, "plan_renames", lambda added, taken: [])
    assert run_tool(fx) == 0, "删让号后工具就不该再跑不通（否则红证证明的是别的东西）"
    ids = fx.all_case_ids()
    assert len(ids) != len(set(ids)), "删掉让号逻辑后重复 id 竟然消失了 ⇒ ② 的断言是空断言"
    assert sorted(p.name for p in (fx.wt / ".github/cases/claims").glob("*.json")) == [
        "9001-MC-140.json", "9002-MC-140.json"], "claim 文件在无让号时应当保持原样（对照读数）"


# ══════════════════════════════════════════════════════════════════════════════
# ③ 锚点：从 origin/main 重建 + **实测**重锚 ⇒ 产出能过真判据
# ══════════════════════════════════════════════════════════════════════════════

def test_anchor_is_rebuilt_from_main_and_reanchored_by_measurement(fx):
    """③：锚点取 main 版 + 实测重锚 ⇒ `test_case_machine_fail_channel.py` 全绿。"""
    assert run_tool(fx) == 0

    # 锚点是**合法 JSON**（不是 `--ours/--theirs` 留下的冲突标记）
    text = (fx.wt / lib.ANCHOR).read_text(encoding="utf-8")
    assert "<<<<<<<" not in text and ">>>>>>>" not in text, "锚点里残留冲突标记 ⇒ 用 --ours 解冲突了"
    anchor = json.loads(text)

    # entries == 实测（2 条基线 + 2 条新增 = 4），且 history 末行同步
    assert anchor["entries"] == {"no_channel_total": 0, "backend_contract_scoring_zero": 4}, \
        f"锚点没有按**实测**重锚：{anchor['entries']}"
    assert anchor["history"][-1]["backend_contract_scoring_zero"] == 4
    assert anchor["history"][-1].get("note"), "重锚那一行缺 note ⇒ `anchor_drift` 会判红"
    # 分支自己那行（5）不该被留下 —— 合批取的是 **main 版 + 一行实测**
    assert [row["backend_contract_scoring_zero"] for row in anchor["history"]] == [2, 4]

    p = run_anchor_test(fx)
    assert p.returncode == 0, f"锚点判据在合批产出上判红：\n{p.stdout[-4000:]}"


def test_red_proof_conflict_resolved_by_ours_fails_the_real_anchor_test(fx):
    """③ 的红证：把锚点换成 **main 版**（= `git checkout --ours` 解冲突的产物）⇒ 真判据必红。"""
    assert run_tool(fx) == 0
    assert run_anchor_test(fx).returncode == 0, "前置：正常产出必须先是绿的，否则红证不成立"

    ours = _sh(["git", "-C", str(fx.wt), "show", f"origin/main:{lib.ANCHOR}"]).stdout
    (fx.wt / lib.ANCHOR).write_text(ours, encoding="utf-8")
    p = run_anchor_test(fx)
    assert p.returncode != 0, "拿 main 版锚点（未按实测重锚）竟然还能过 ⇒ ③ 的断言是空断言"
    assert "不一致" in p.stdout or "实测读数" in p.stdout, \
        f"红得不对（应当是实测与 entries 不一致）：\n{p.stdout[-2000:]}"


# ══════════════════════════════════════════════════════════════════════════════
# ④ 「是否在合并中」用 MERGE_HEAD（worktree 里 `.git` 是文件）
# ══════════════════════════════════════════════════════════════════════════════

def test_in_merge_progress_uses_merge_head_in_a_worktree(fx):
    """④：worktree 里 `.git` 是**文件** ⇒ 路径判据恒 False；真判据必须为 True。"""
    assert (fx.wt / ".git").is_file(), "夹具必须是 worktree 形态（`.git` 是文件），否则 ④ 测不到真形态"
    assert lib.in_merge_progress(fx.wt) is False

    # 造一次**真冲突**的合并（用本批外的两个分支改同一行）
    _sh(["git", "-C", str(fx.wt), "checkout", "-q", "-B", "conflict/ours", "origin/main"])
    _write(fx.wt, {"tests/unit_ci_workflows/test_fixture_contracts.py": "# ours\n"})
    _sh(["git", "-C", str(fx.wt), "commit", "-qam", "ours"])
    _sh(["git", "-C", str(fx.wt), "checkout", "-q", "-B", "conflict/theirs", "origin/main"])
    _write(fx.wt, {"tests/unit_ci_workflows/test_fixture_contracts.py": "# theirs\n"})
    _sh(["git", "-C", str(fx.wt), "commit", "-qam", "theirs"])
    p = fx.git("merge", "--no-commit", "conflict/ours", check=False)
    assert p.returncode != 0, "夹具没造出冲突 —— ④ 的现场不成立"

    assert lib.in_merge_progress(fx.wt) is True, "冲突未收尾时必须判「在合并中」"
    # 红证：naive 实现（`Path(repo)/'.git'/'MERGE_HEAD'`）在同一现场**恒不存在**
    assert not (fx.wt / ".git" / "MERGE_HEAD").exists(), \
        "worktree 里 `.git/MERGE_HEAD` 竟然存在 ⇒ 请复核 ④ 的前提（这会让红证失效）"

    # 工具自己的收口：没在合并中却要"提交合并" ⇒ fail-closed（每支都必须成功提交）
    fx.git("merge", "--abort")
    with pytest.raises(lib.BatchError):
        lib.commit_merge(fx.wt, {"number": 1, "headRefName": "x", "title": "x"}, "HEAD")
    for br in ("conflict/ours", "conflict/theirs"):
        fx.git("branch", "-D", br, check=False)
    fx.git("checkout", "-q", "--detach", "origin/main")


# ══════════════════════════════════════════════════════════════════════════════
# ⑤ 生成的 PR body **零关闭关键词**
# ══════════════════════════════════════════════════════════════════════════════

def test_pr_body_has_zero_close_keywords(fx):
    """⑤：body 零关闭词（负控：body 里**确实**带 `#NNNN` 引用，所以 0 命中不是空断言）。"""
    assert run_tool(fx, "--no-push") == 0, "没走成完整流程 —— ⑤ 的对象（body）没生成"

    body_path = fx.git_dir() / "batch-merge-pr-body.md"
    body = body_path.read_text(encoding="utf-8")
    assert "#9001" in body and "#9002" in body, "body 里没有 PR 号引用 ⇒ 「0 命中」可能是空断言"

    guard = lib._guard()
    hits = guard.find_close_keywords(body)
    assert hits == [], f"body 命中关闭关键词（必须 0 条）：{hits}"

    # 与 CLI 同一实现复核（共享根判定关掉：判据在 pytest 的临时目录里跑，那不是生产落点）
    p = _sh([sys.executable, str(REPO_ROOT / "scripts/pr_body_guard.py"), "check",
             "--expect", "0", str(body_path)],
            env={**os.environ, "PR_BODY_GUARD_SHARED_ROOTS": ""}, check=False)
    assert p.returncode == 0, f"`pr_body_guard check --expect 0` 判红：\n{p.stdout}\n{p.stderr}"


def test_pr_body_is_what_gh_received_and_is_drafted(fx):
    """⑤ 的接线那一半：`gh pr create --draft --body-file <body>` 收到的**就是**这份 body。"""
    assert run_tool(fx) == 0
    created = fx.stub_dir / "created-body.md"
    assert created.is_file(), "没走到 `gh pr create`（接线断了：§28.2「判据绿 ≠ 接线在」）"
    assert created.read_text(encoding="utf-8") == \
        (fx.git_dir() / "batch-merge-pr-body.md").read_text(encoding="utf-8")
    args = json.loads((fx.stub_dir / "created-args.json").read_text(encoding="utf-8"))
    assert "--draft" in args, "必须开 **draft** PR（绿了再 ready）"
    assert "--base" in args and args[args.index("--base") + 1] == "main"


# ══════════════════════════════════════════════════════════════════════════════
# ⑥ `--dry-run` 零落盘（+ 正控：不加 --dry-run 时读数**确实**会变）
# ══════════════════════════════════════════════════════════════════════════════

def test_dry_run_touches_nothing(fx):
    """⑥：`--dry-run` 不建分支/不提交/不推送；正控证明这些读数对工具的行为**敏感**。"""
    before = {
        "head": fx.head(),
        "count": fx.commit_count(),
        "branches": fx.branches(),
        "remote": _sh(["git", "-C", str(fx.origin), "for-each-ref",
                       "--format=%(refname:short)"]).stdout,
        "status": fx.git("status", "--porcelain").stdout,
    }
    assert run_tool(fx, "--dry-run") == 0
    after = {
        "head": fx.head(),
        "count": fx.commit_count(),
        "branches": fx.branches(),
        "remote": _sh(["git", "-C", str(fx.origin), "for-each-ref",
                       "--format=%(refname:short)"]).stdout,
        "status": fx.git("status", "--porcelain").stdout,
    }
    assert after == before, f"--dry-run 落盘了：{[(k, before[k], after[k]) for k in before if before[k] != after[k]]}"
    assert BRANCH not in after["branches"] and BRANCH not in after["remote"]

    # 正控：同一夹具不加 --dry-run ⇒ 分支表与提交数**确实**变了（否则上面是空断言）
    assert run_tool(fx) == 0
    assert BRANCH in fx.branches() and BRANCH in _sh(
        ["git", "-C", str(fx.origin), "for-each-ref", "--format=%(refname:short)"]).stdout
    assert fx.commit_count() > before["count"]


def test_entry_script_is_wired(fx):
    """接线：`scripts/batch-merge.sh` 真的把 argv 转给实现体（不是只有 .py 能跑）。"""
    p = _sh([str(fx.wt / "scripts/batch-merge.sh"), "--help"], cwd=fx.wt, env=fx.env(), check=False)
    assert p.returncode == 0, p.stderr
    for flag in ("--dry-run", "--no-push", "--force-branch"):
        assert flag in p.stdout, f"入口/实现体的用法里缺 {flag}"
