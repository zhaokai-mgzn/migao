# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012 ——
#   见 `.github/cases/misc.yml` 的 MC-012「CI workflow 结构由 pytest 单测验证」。
#   本 PR 不新建用例族：塞进行为用例库会污染覆盖矩阵。）
"""`scripts/pr_body_guard.py` —— #4232「并发会话共用 `/tmp` 固定名 PR body ⇒ 差点误关 4 个 issue」的守卫。

## 缺陷（实测近失，非推断）

两个并发 DSH 会话都用了 `/tmp` 下**同一个约定俗成的固定文件名**承载 PR body：
会话 A 写它 → `gh pr edit A --body-file <该文件>`；会话 B 覆盖它（含 B 的 4 条关闭行）；
会话 A 以为还是自己的内容，继续 `gh pr edit A --body-file <该文件>` ⇒ **A 的 body 被写成 B 的 body**。
若 A 在那个窗口被 auto-merge 合并 ⇒ **误关另外 4 个 issue**（另一会话的在建工作）。
归因 = 违反 `migao-dev-flow` §2.3「会话之间零共享写路径」—— **`/tmp` 就是一条共享写路径**。

## 本测试守什么（每组都要有判别力，不是"跑通就算"）

① `new`：分配**工作区内、被 git 忽略**的**唯一**路径（真并发 4 路也不撞），文件名含分支/issue/pid；
   把目录指向共享 `/tmp` ⇒ **必红**（exit 1 + 可行动信息）；指向工作区外/未忽略目录 ⇒ 必红；
   根不是 git 工作区 ⇒ **3（无法判定）**，不是 0。
② `check`：打印 **body 首行** + 关闭关键词命中清单（口径 = §2.2 的朴素正则，**引用式/否定式照样命中**），
   命中 ⇒ exit 1；`--expect N` 只放行「命中数恰好 = 本意条数」；无命中 ⇒ 0；文件不可读 ⇒ 3；
   文件本身落在共享 `/tmp` 根下 ⇒ 也是命中（这正是本单要治的形态）。
③ `verify`：从 GitHub **回读** body 与本地文件比对（内容哈希 + 首行），不一致 ⇒ 红并指出差异
   （"另一个会话把我的文件换掉了"的检出点）；`gh` 缺失/报错/返回非 JSON ⇒ 3；
   **只读**：替身 `gh` 记录 argv，断言只有 `pr view`、绝无 `edit`/`create`/`POST`。
④ `scan`（静态守卫，机器可判的那半）：仓内**被跟踪文件**里不得存在「用共享固定名临时文件承载 PR body」
   的形态（`gh pr create|edit --body-file /tmp/<固定名>`、`/tmp/<pr-body 名>` 字面量）；
   变量式 `--body-file "$BODY"`、非 PR body 的普通临时文件**不误报**（边界照实登记，见脚本 docstring）。
⑤ **R3 = 行首 Git 合并冲突标记**（issue #5239，**全仓卫生面**，与 R1/R2 共用同一台扫描器）：
   实测病灶两处 —— `CHANGELOG.md` 在 `origin/main` 上带着**已提交的冲突块**三行（开 / 分隔 / 闭，
   且分隔与闭合之间**为空**），以及 `docs/design/agent-production-gap-analysis.md` 的 **4 行孤立闭合标记**
   （当年解冲突删了两兄弟、漏删闭合）。本组守：① 插一行开标记 ⇒ 必红（判据 1）；
   ② 一块的**三行都判** + **孤立闭合标记**无条件判（否则留下孤立标记，正是那 4 行的形态）；
   ③ **不得假红**：缩进 / 行中 / 行尾的标记不判、**合法的 markdown setext H1 下划线**（标题 + 恰好 7 个 `=`）不判
   （判据 3 —— 仓内当前**没有**合法 setext 样本，这条负例必须**自己造**，否则它是个空断言）；
   ④ 判据**真的扫到了文件**：样本集非空 + 覆盖 `CHANGELOG.md`，且扫描根不存在 ⇒ exit 3（不是 0）（判据 2）；
   ⑤ `CHANGELOG.md` 的 `## [Unreleased]` 里那几节正文**逐字仍在**（判据 4，防「修标记顺手删正文」）。

## 夹具纪律（含「不依赖平台」这一条 —— 首版在这里翻过车）

- `gh` 用**替身可执行文件**注入（`--gh-bin`）—— CLI 边界即注入点，**不打真实 GitHub API**、零写操作；
- **共享根清单一律由测试注入**（`$PR_BODY_GUARD_SHARED_ROOTS` / `shared_temp_root(roots=…)`），
  **不把「pytest 的 `tmp_path` 落在哪」当稳定前提**：本机在 `/var/folders/…`、Linux CI 在
  `/tmp/pytest-of-runner/…`（**就是**共享根）⇒ 首版同一断言本地绿 / CI 红 5 条。判据本体没错，
  错的是测试依赖了环境量；
- 测试自身**不写任何共享 `/tmp` 固定名**（本文件现在**完全不写** `/tmp`）：需要「共享根」场景时
  用 `tmp_path` 下的目录 + 注入清单；
- 「关键词 + `#号`」「`/tmp/…` 路径」样例一律**拆开拼**（本文件自身不得出现这些字面组合，见 §2.2 / 任务铁律）；
- **R3 的冲突标记同样拆开拼**（`OPEN7` / `MID7` / `CLOSE7`）：本文件也在扫描样本集里（`scan` 扫全仓
  被跟踪文件）⇒ 写出行首字面量会被**自己的守卫**抓（`test_scan_real_repo_...` 当场红）。这是有意的自洽。
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "pr_body_guard.py"

# 拆开写：本文件（以及脚本）自身不得出现「关闭关键词 + #号」「共享临时根 + 固定文件名」的字面组合。
TMP_TOKEN = "/" + "tmp"
SHARED_FIXED_PR_BODY = TMP_TOKEN + "/pr-body.md"
SHARED_OTHER_FILE = TMP_TOKEN + "/body-notes.md"


def _kw(word: str, num: int) -> str:
    """拼出「关键词 + `#号`」样例（**拆开写**，避免本文件自身被朴素正则/静态守卫命中）。"""
    return f"{word} #{num}"


def _load_module():
    """按路径加载被测脚本（`scripts/` 不是包）。"""
    spec = importlib.util.spec_from_file_location("pr_body_guard", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_cli(*args, cwd=None, env=None, timeout=180):
    e = dict(os.environ)
    e.update(env or {})
    return subprocess.run(
        [sys.executable, str(SCRIPT), *[str(a) for a in args]],
        capture_output=True, text=True, cwd=str(cwd or REPO_ROOT), env=e, timeout=timeout,
    )


def write_body(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _out(proc) -> str:
    return (proc.stdout or "") + (proc.stderr or "")


def _roots_env(*dirs) -> dict:
    """把**共享根清单**钉成测试自己的确定集合（`$PR_BODY_GUARD_SHARED_ROOTS` 注入）。

    为什么必须注入：默认清单含 `/tmp` + 本机 `$TMPDIR`，而 **pytest 的 `tmp_path` 落在哪随平台变**
    —— 本机在 `/var/folders/…`（非共享根）、Linux CI 在 `/tmp/pytest-of-runner/…`（**就是**共享根）
    ⇒ 同一断言本地绿 / CI 红（首版实测 CI 5 条红）。判据本体没错，错的是"把平台相关的 tmp 位置
    当稳定前提"。注入后每个场景的清单都由测试说了算，跨平台一致。
    """
    return {"PR_BODY_GUARD_SHARED_ROOTS": os.pathsep.join(str(d) for d in dirs)}


def _make_gh_stub(dirpath: Path, payload: str, *, name="gh-stub.py", exit_code=0) -> Path:
    """替身 `gh`：只打印 payload（JSON 文本）并按 exit_code 退出；可选把 argv 记进 GH_STUB_RECORD。"""
    stub = dirpath / name
    stub.write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys\n"
        "rec = os.environ.get('GH_STUB_RECORD')\n"
        "if rec:\n"
        "    with open(rec, 'a', encoding='utf-8') as f:\n"
        "        f.write(' '.join(sys.argv[1:]) + '\\n')\n"
        f"sys.stdout.write({payload!r})\n"
        f"sys.exit({exit_code})\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return stub


def _init_git_repo(path: Path, files: dict) -> None:
    """把 `files`（相对路径 → 文本）放进一个临时 git 仓库并**逐个** add（不用 `git add -A`）。"""
    subprocess.run(["git", "init", "-q"], cwd=path, check=True, capture_output=True)
    for name, text in files.items():
        f = path / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
        subprocess.run(["git", "add", name], cwd=path, check=True, capture_output=True)


@pytest.fixture
def shared_root(tmp_path):
    """**测试自己说了算**的共享根（注入给被测脚本）+ 落进它的一个 body 文件。

    不再往真 `/tmp` 写东西：判据的输入（共享根清单）由 `$PR_BODY_GUARD_SHARED_ROOTS` 注入
    ⇒ 跨平台确定，也不再需要"唯一名 + 自清理"来躲别的会话。
    """
    root = tmp_path / "shared-root"
    root.mkdir()
    return root


# ── ① new：作用域 + 唯一性 ────────────────────────────────────────────────────

def test_new_allocates_unique_path_inside_worktree_and_ignored():
    a = run_cli("new", "--issue", "4232")
    b = run_cli("new", "--issue", "4232")
    assert a.returncode == 0, _out(a)
    assert b.returncode == 0, _out(b)
    pa, pb = Path(a.stdout.strip()), Path(b.stdout.strip())
    try:
        assert pa != pb, "两次调用分配了同一个路径 —— 唯一性判据失效"
        for p in (pa, pb):
            assert p.is_file(), f"未真正创建文件：{p}"
            assert REPO_ROOT.resolve() in p.resolve().parents, f"不在本工作区内：{p}"
            ignored = subprocess.run(["git", "check-ignore", "-q", "--", str(p)],
                                     cwd=REPO_ROOT, capture_output=True)
            assert ignored.returncode == 0, f"未被 .gitignore 覆盖（会被误提交）：{p}"
            assert "4232" in p.name, f"文件名未含分支/issue 标识：{p.name}"
    finally:
        for raw in (a.stdout.strip(), b.stdout.strip()):
            if raw:
                Path(raw).unlink(missing_ok=True)


def test_new_concurrent_calls_never_collide():
    procs = [subprocess.Popen([sys.executable, str(SCRIPT), "new", "--issue", "4232"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=REPO_ROOT)
             for _ in range(4)]
    results = [p.communicate(timeout=180) for p in procs]
    paths = set()
    try:
        for p, (out, err) in zip(procs, results):
            assert p.returncode == 0, err
            paths.add(Path(out.strip()))
        assert len(paths) == 4, f"真并发下出现路径撞车：{sorted(str(p) for p in paths)}"
        for p in paths:
            assert p.is_file()
    finally:
        for p in paths:
            p.unlink(missing_ok=True)


def test_new_refuses_shared_tmp_root():
    r = run_cli("new", "--dir", TMP_TOKEN)
    assert r.returncode == 1, _out(r)
    assert r.stdout.strip() == "", "拒绝时不得打印可用路径"
    text = _out(r)
    # 判别力：必须是**共享临时根**这一支的措辞（不能被兜底措辞里的"共享写路径"蒙混过关 ——
    # 注入「不再识别共享临时根」后本断言必红，见报告红证①）。
    assert "共享临时根" in text and TMP_TOKEN in text
    assert "不在本工作区" not in text, "命中的应是共享根分支，不是工作区分支"
    assert "工作区" in text, "可行动信息必须指出正确落点（工作区内忽略目录）"
    assert "pr_body_guard.py new" in text


def test_new_refuses_dir_outside_worktree(tmp_path):
    # 注入确定清单（**不含** tmp_path）⇒ 命中「工作区」分支，不受平台 tmp 位置影响
    r = run_cli("new", "--dir", str(tmp_path), env=_roots_env(tmp_path / "elsewhere"))
    assert r.returncode == 1, _out(r)
    assert "不在本工作区" in _out(r)


def test_new_refuses_unignored_dir_inside_worktree():
    r = run_cli("new", "--dir", str(REPO_ROOT / "frontend"))
    assert r.returncode == 1, _out(r)
    assert ".gitignore" in _out(r), "未忽略目录必须报红并指出 .gitignore"


def test_new_non_git_root_is_tri_state(tmp_path):
    d = tmp_path / "not-a-repo"
    d.mkdir()
    r = run_cli("new", "--root", str(d))
    assert r.returncode == 3, _out(r)
    assert "无法判定" in _out(r)


# ── ② check：首行 + 关闭关键词自检 ────────────────────────────────────────────

def test_check_prints_first_line_and_flags_close_keywords(tmp_path):
    body = write_body(tmp_path / "b.md", _kw("Closes", 1) + "\n\n正文\n" + _kw("Fixes", 22) + "\n")
    r = run_cli("check", str(body))
    assert r.returncode == 1, _out(r)
    assert "首行" in r.stdout and _kw("Closes", 1) in r.stdout
    assert "命中 2 条" in r.stdout
    assert "#1" in r.stdout and "#22" in r.stdout
    assert "确认" in r.stdout, "必须提示逐个确认是否本意（不得静默放行）"


def test_check_clean_body_exits_zero(tmp_path):
    body = write_body(tmp_path / "b.md", "改用会话作用域临时文件承载 PR body\n\n无关闭关键词\n")
    r = run_cli("check", str(body), env=_roots_env(tmp_path / "shared-root"))
    assert r.returncode == 0, _out(r)
    assert "改用会话作用域临时文件承载 PR body" in r.stdout
    assert "命中 0 条" in r.stdout


def test_check_expect_only_allows_intended_hit_count(tmp_path):
    body = write_body(tmp_path / "b.md", _kw("Closes", 4232) + "\n")
    env = _roots_env(tmp_path / "shared-root")
    assert run_cli("check", str(body), env=env).returncode == 1
    ok = run_cli("check", "--expect", "1", str(body), env=env)
    assert ok.returncode == 0, _out(ok)
    assert "命中 1 条" in ok.stdout
    over = run_cli("check", "--expect", "0", str(body), env=env)
    assert over.returncode == 1, "本意 0 条却命中 1 条 ⇒ 必须红"


def test_check_reference_style_sample_is_not_silently_passed(tmp_path):
    env = _roots_env(tmp_path / "shared-root")
    naive_ref = write_body(tmp_path / "ref.md", "证据表：`" + _kw("Closes", 3559) + "`（引用式样例）\n")
    r = run_cli("check", str(naive_ref), env=env)
    assert r.returncode == 1, "引用式样例按 §2.2 口径照样命中，不得静默放行"
    assert "#3559" in r.stdout and "确认" in r.stdout

    split_ref = write_body(tmp_path / "split.md", "本 PR 不关闭 `Closes` + `#3559`（拆开写，安全）\n")
    r2 = run_cli("check", str(split_ref), env=env)
    assert r2.returncode == 0, _out(r2)


def test_check_flags_body_file_living_in_shared_root(shared_root):
    body = write_body(shared_root / "b.md", _kw("Closes", 4232) + "\n")
    r = run_cli("check", str(body), env=_roots_env(shared_root))
    assert r.returncode == 1, _out(r)
    assert "共享临时根" in r.stdout and str(shared_root) in r.stdout


def test_check_unreadable_file_is_tri_state(tmp_path):
    r = run_cli("check", str(tmp_path / "nope.md"))
    assert r.returncode == 3, _out(r)
    assert "无法判定" in _out(r)


def test_check_empty_body_is_flagged(tmp_path):
    body = write_body(tmp_path / "empty.md", "")
    r = run_cli("check", str(body))
    assert r.returncode == 1, _out(r)
    assert "空" in _out(r)


# ── ③ verify：回读比对（只读替身 gh）─────────────────────────────────────────

def test_verify_match_exits_zero(tmp_path):
    text = _kw("Closes", 4232) + "\n\n说明\n"
    local = write_body(tmp_path / "local.md", text)
    gh = _make_gh_stub(tmp_path, json.dumps({"body": text.rstrip("\n")}))
    r = run_cli("verify", "4232", str(local), "--gh-bin", str(gh))
    assert r.returncode == 0, _out(r)
    assert "一致" in r.stdout and _kw("Closes", 4232) in r.stdout


def test_verify_mismatch_is_red_and_shows_both_first_lines(tmp_path):
    local = write_body(tmp_path / "local.md", _kw("Closes", 4232) + "\n本地正文\n")
    gh = _make_gh_stub(tmp_path, json.dumps({"body": _kw("Closes", 4202) + "\n别人的正文\n"}))
    r = run_cli("verify", "4232", str(local), "--gh-bin", str(gh))
    assert r.returncode == 1, _out(r)
    assert "不一致" in r.stdout
    assert _kw("Closes", 4232) in r.stdout, "必须打印本地首行"
    assert _kw("Closes", 4202) in r.stdout, "必须打印远端首行（差异点）"


def test_verify_unavailable_gh_is_tri_state(tmp_path):
    local = write_body(tmp_path / "local.md", _kw("Closes", 4232) + "\n")
    missing = run_cli("verify", "4232", str(local), "--gh-bin", str(tmp_path / "no-such-gh"))
    assert missing.returncode == 3, _out(missing)
    assert "无法判定" in _out(missing)

    failing = _make_gh_stub(tmp_path, "", name="gh-fail.py", exit_code=1)
    r2 = run_cli("verify", "4232", str(local), "--gh-bin", str(failing))
    assert r2.returncode == 3, _out(r2)

    bad_json = _make_gh_stub(tmp_path, "not-json", name="gh-badjson.py")
    r3 = run_cli("verify", "4232", str(local), "--gh-bin", str(bad_json))
    assert r3.returncode == 3, _out(r3)


def test_verify_never_issues_write_commands(tmp_path):
    record = tmp_path / "calls.txt"
    text = _kw("Closes", 4232) + "\n"
    local = write_body(tmp_path / "local.md", text)
    gh = _make_gh_stub(tmp_path, json.dumps({"body": text}), name="gh-rec.py")
    r = run_cli("verify", "4232", str(local), "--gh-bin", str(gh),
                env={"GH_STUB_RECORD": str(record)})
    assert r.returncode == 0, _out(r)
    calls = record.read_text(encoding="utf-8").split()
    assert calls[:2] == ["pr", "view"], f"只允许只读回读，实际：{calls}"
    for forbidden in ("edit", "create", "POST", "PATCH", "PUT"):
        assert forbidden not in calls, f"verify 发出了写操作：{forbidden}"


# ── ④ scan：仓内静态守卫（机器可判的那半）────────────────────────────────────

def test_scan_real_repo_has_no_shared_fixed_pr_body_carrier():
    r = run_cli("scan")
    assert r.returncode == 0, _out(r)
    assert "命中 0 处" in r.stdout


def test_scan_flags_fixed_pr_body_path_literal(tmp_path):
    repo = tmp_path / "r-literal"
    repo.mkdir()
    _init_git_repo(repo, {"run.sh": "cat > " + SHARED_FIXED_PR_BODY + " <<'EOF'\n"})
    r = run_cli("scan", "--root", str(repo))
    assert r.returncode == 1, _out(r)
    assert "run.sh" in r.stdout
    assert "命中 1 处" in r.stdout
    assert "pr-body" in r.stdout, "命中清单必须给出原文"


def test_scan_flags_gh_pr_body_file_with_shared_fixed_path(tmp_path):
    repo = tmp_path / "r-ghpr"
    repo.mkdir()
    _init_git_repo(repo, {"notes.md": "gh pr create --body-file " + SHARED_OTHER_FILE + "\n"})
    r = run_cli("scan", "--root", str(repo))
    assert r.returncode == 1, _out(r)
    assert "notes.md" in r.stdout and "命中 1 处" in r.stdout


def test_scan_ignores_variable_paths_and_non_pr_body_files(tmp_path):
    repo = tmp_path / "r-clean"
    repo.mkdir()
    _init_git_repo(repo, {
        "a.sh": 'gh pr create --body-file "$BODY"\ngh pr edit 1 --body-file "${BODY_FILE}"\n',
        "b.yml": "gh issue comment 1 --body-file " + SHARED_OTHER_FILE + "\n",
        "c.py": "OUT = '" + SHARED_OTHER_FILE + "'  # 与 PR body 无关的普通临时文件\n",
    })
    r = run_cli("scan", "--root", str(repo))
    assert r.returncode == 0, _out(r)
    assert "命中 0 处" in r.stdout


def test_scan_non_git_root_is_tri_state(tmp_path):
    d = tmp_path / "plain"
    d.mkdir()
    r = run_cli("scan", "--root", str(d))
    assert r.returncode == 3, _out(r)
    assert "无法判定" in _out(r)


# ── ⑤ R3：行首 Git 合并冲突标记（issue #5239）───────────────────────────────
#
# ⚠️ 本文件自身也在扫描样本集里（`scan` 扫全仓被跟踪文件）⇒ 标记一律**拆开拼**（`OPEN7` 等）。

OPEN7, MID7, CLOSE7 = "<" * 7, "=" * 7, ">" * 7

CHANGELOG = REPO_ROOT / "CHANGELOG.md"
UNRELEASED_ANCHOR = "## [Unreleased]"

#: 判据 4：修标记时**必须逐字仍在**的条目（防「顺手删正文」）。
#: 键 = 条目标题里的 issue 号；值 = `(标题锚点, 正文锚点)`。
#: ⚠️ **正文锚点是必需的**：只判「标题在 + 正文非空」会放过「正文被砍掉一半仍绿」这个形态
#: —— 实测（红证驱动 M4）砍掉 `#5194` 整行正文，那种弱判据照旧绿。
#: 选这 4 条的**理由**（每条都紧贴被删的标记）：
#:  · `#5194` —— 冲突**开标记与分隔标记之间**的那一节（同号在文件里另有一节 ⇒ 按标题锚点找，不按号计数）；
#:  · `#5201` / `#5211` —— 闭合标记那行的提交说明**点名**的两条（「#5201 引擎自动推导 + #5211 推导项落单」）；
#:  · `#5218` —— 引入这三行标记的那个 PR（#5232）当批录入的条目。
SURVIVING_ENTRIES = {
    "5194": ("### 算料/余料说明里的重点词真的加粗了", "由新的行内渲染器"),
    "5201": ("### 新增订单的工艺配置改由系统自动推导", "算料引擎枚举 **5 个候选方案**"),
    "5211": ("### 系统推导出的「拼N次 / 接高」现在会真的落到订单", "specialOptions"),
    "5218": ("### 数字输入框收口：编辑「已有的值」时输 `0` 不再被清空", "只把「真缺值」映射成空"),
}

#: `[Unreleased]` 条目数的**判别力下界**（不是当前计数 —— 当前远高于它）：
#: 下界的作用是「面被收窄到判不到东西」时报警，不是钉住易变现值。
MIN_UNRELEASED_ENTRIES = 30


def _conflict_block(tag: str = "HEAD") -> str:
    """一份**逐字**的冲突块（Git 写出的形态 = 行首 7 个同字符 + 空格 + 版本标签）。"""
    return f"{OPEN7} {tag}\n保留的正文\n{MID7}\n被丢弃的正文\n{CLOSE7} {tag} (说明)\n"


def test_scan_flags_line_start_conflict_markers(tmp_path):
    """判据 1：任一被跟踪文件里插一行开标记 ⇒ 必红（红证就在这条测试本身）。"""
    repo = tmp_path / "r-conflict"
    repo.mkdir()
    _init_git_repo(repo, {"CHANGELOG.md": "## [Unreleased]\n\n正文\n" + OPEN7 + " HEAD\n"})
    r = run_cli("scan", "--root", str(repo))
    assert r.returncode == 1, _out(r)
    assert "CHANGELOG.md" in r.stdout
    assert "命中 1 处" in r.stdout
    assert "[R3]" in r.stdout, "命中清单必须标出规则名（否则读的人不知道该怎么修）"


def test_scan_flags_all_three_markers_of_one_block(tmp_path):
    """一块的**三行都要判** —— 少判一行就留下孤立标记，正是本单那 4 行的形态。"""
    repo = tmp_path / "r-block"
    repo.mkdir()
    _init_git_repo(repo, {"doc.md": "前置正文\n" + _conflict_block() + "后置正文\n"})
    r = run_cli("scan", "--root", str(repo))
    assert r.returncode == 1, _out(r)
    assert "命中 3 处" in r.stdout
    for line_no in ("2", "4", "6"):        # 三行在块里的位置（块从第 2 行起）
        assert f"doc.md:{line_no}  [R3]" in r.stdout, f"未在第 {line_no} 行命中：\n{r.stdout}"


def test_scan_flags_orphan_close_marker_alone(tmp_path):
    """**孤立闭合标记**（本单那 4 行的形态）无条件判 —— 它不依赖任何上下文门控。"""
    repo = tmp_path / "r-orphan"
    repo.mkdir()
    _init_git_repo(repo, {"notes.md": "正文\n" + CLOSE7 + " ab0806927 (说明)\n正文\n"})
    r = run_cli("scan", "--root", str(repo))
    assert r.returncode == 1, _out(r)
    assert "命中 1 处" in r.stdout
    assert "notes.md:2  [R3]" in r.stdout


def test_scan_does_not_flag_indented_or_inline_markers(tmp_path):
    """判据 3（假红面 ①）：Git 只把标记写在**行首** ⇒ 缩进 / 行中 / 行尾一律不判。"""
    repo = tmp_path / "r-soft"
    repo.mkdir()
    _init_git_repo(repo, {"doc.md": (
        "  " + OPEN7 + " HEAD\n"                # 缩进（引述标记的常见形态）
        "说明：" + CLOSE7 + " 不是标记行\n"       # 行中
        "x " + MID7 + "\n"                      # 行尾
        ">>>>\n"                                # 不足 7 个
    )})
    r = run_cli("scan", "--root", str(repo))
    assert r.returncode == 0, _out(r)
    assert "命中 0 处" in r.stdout


def test_scan_does_not_flag_legal_setext_underline(tmp_path):
    """判据 3（假红面 ②）：**合法的 markdown setext H1 下划线** = 「标题 + 恰好 7 个 `=`」⇒ 不得判。

    仓内当前**没有**合法 setext 样本（行首恰好 7 个 `=` 全仓只命中过原 CHANGELOG 的那行标记）
    ⇒ 这条负例必须**自己造**：它防的正是「把合法文档判红」。判别力的另一半（同一行在冲突块**里**必判）
    由 `test_scan_flags_all_three_markers_of_one_block` 与 `test_mid_marker_needs_conflict_context` 提供。
    """
    repo = tmp_path / "r-setext"
    repo.mkdir()
    _init_git_repo(repo, {
        "heading.md": "标题\n" + MID7 + "\n\n正文\n",          # 恰好 7 个 `=` 的 setext 下划线
        "heading2.md": "标题二\n" + "=" * 12 + "\n\n正文\n",   # 更长的下划线（行首锚定 + 恰好 7 个）
    })
    r = run_cli("scan", "--root", str(repo))
    assert r.returncode == 0, _out(r)
    assert "命中 0 处" in r.stdout


def test_mid_marker_needs_conflict_context(tmp_path):
    """**登记边界**（有意不判，不是"忘了"）：孤立分隔标记与合法 setext 下划线**静态不可区分**。

    这条把边界**钉成判据**：既证明 setext 负例不是"门控恰好关着"，也证明门控没有把真标记一起关掉。
    """
    mod = _load_module()
    assert mod.scan_text("x.md", "标题\n" + MID7 + "\n") == [], "孤立分隔标记不得判（与合法下划线同形）"
    assert [f["line"] for f in mod.scan_text("x.md", _conflict_block())] == [1, 3, 5], \
        "含完整冲突块时三行都必须判（否则门控把真标记也关掉了）"


def test_scan_sample_set_is_non_empty_and_covers_changelog():
    """判据 2：判据必须**真的扫到了文件** —— 样本集非空 + 覆盖 `CHANGELOG.md`（本单病灶所在）。

    走 `tracked_text()`（与 `cmd_scan` **同一个**枚举/跳过口径）—— 判据自己另抄一份枚举的话，
    「扫描器坏了」时它照样绿（空跑）。
    """
    mod = _load_module()
    root = mod.resolve_root(str(REPO_ROOT))
    assert isinstance(root, Path), f"工作区根解析失败：{root!r}"
    scanned = mod.tracked_text(root)
    assert isinstance(scanned, tuple), f"`git ls-files` 拿不到清单 ⇒ 判据无法判定（不得当 0 读）：{scanned!r}"
    rels, files = scanned
    assert len(files) >= 500, (
        f"样本集只有 {len(files)} 个文本文件 ⇒ 面被收窄到判不到东西（下界是**判别力下界**，不是当前计数）")
    assert "CHANGELOG.md" in rels, "被跟踪清单未覆盖 CHANGELOG.md"
    assert "CHANGELOG.md" in {rel for rel, _ in files}, \
        "CHANGELOG.md 在清单里却没进样本 —— 跳过规则把它吃掉了（判据会因此静默变空）"


def test_scan_nonexistent_root_is_not_reported_green(tmp_path):
    """判据 2 的红证：扫描根不存在 ⇒ **不得绿**（exit 3「无法判定」，不是 0「没问题」）。"""
    missing = tmp_path / "no-such-dir"
    assert not missing.exists()
    r = run_cli("scan", "--root", str(missing))
    assert r.returncode == 3, _out(r)
    assert "无法判定" in _out(r)
    assert "命中 0 处" not in r.stdout, "无法判定时不得打印「命中 0 处」—— 那会被读成「扫过了、干净」"


def test_tracked_text_empty_repo_is_discriminating(tmp_path):
    """反空跑：样本集**下界有判别力** —— 空仓枚举出 0 个 ⇒ 上面那条下界断言会红（不是恒真）。"""
    mod = _load_module()
    empty = tmp_path / "empty-repo"
    empty.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=empty, check=True, capture_output=True)
    rels, files = mod.tracked_text(empty)
    assert rels == [] and files == [], "空仓的样本集必须为空（否则下界断言无判别力）"


def _unreleased_section() -> str:
    """`## [Unreleased]` 到下一个 `## ` 之间的正文；锚点不在 ⇒ 直接红（不得因此变绿）。"""
    text = CHANGELOG.read_text(encoding="utf-8")
    at = text.find(UNRELEASED_ANCHOR)
    assert at >= 0, f"`{UNRELEASED_ANCHOR}` 锚点不见了 ⇒ 判据 4 没有受判面"
    rest = text[at + len(UNRELEASED_ANCHOR):]
    nxt = rest.find("\n## ")
    return rest if nxt < 0 else rest[:nxt]


def test_changelog_unreleased_entries_survived_the_marker_removal():
    """判据 4：`## [Unreleased]` 的条目**逐字仍在**（标题 + 正文锚点）—— 防「修标记顺手删正文」。

    两条路线各自实测过：删掉整个条目（标题）⇒ 红；**只删正文里被锚住的那句** ⇒ 同样红。
    """
    sec = _unreleased_section()
    entries = sec.count("\n### ")
    assert entries >= MIN_UNRELEASED_ENTRIES, (
        f"`[Unreleased]` 只剩 {entries} 个条目（下界 {MIN_UNRELEASED_ENTRIES}）⇒ 受判面被收窄、判据濒临空跑")
    for issue, (heading, body_anchor) in SURVIVING_ENTRIES.items():
        at = sec.find(heading)
        assert at >= 0, f"`issue #{issue}` 的条目不见了（修标记时被顺手删掉）：{heading}"
        body = sec[at:].split("\n### ")[0]
        assert body_anchor in body, (
            f"`issue #{issue}` 的条目正文缺了锚句（修标记时被顺手删正文）：{body_anchor!r}")


def test_changelog_has_no_leftover_conflict_markers():
    """判据 1 在**病灶文件**上的定点落地（全仓面由 `test_scan_real_repo_...` 覆盖；这条给更好的失败信息）。"""
    findings = [f for f in _load_module().scan_text("CHANGELOG.md",
                                                    CHANGELOG.read_text(encoding="utf-8"))
                if f["rule"] == "R3"]
    assert findings == [], f"CHANGELOG.md 仍带冲突标记行：{findings}"


def test_scan_real_repo_has_no_conflict_markers():
    """判据 1 **在本仓**的落地（enforcement point）：全仓被跟踪文本文件里不得有行首冲突标记。"""
    r = run_cli("scan")
    assert r.returncode == 0, _out(r)
    assert "命中 0 处" in r.stdout
    assert "[R3]" not in r.stdout


# ── 纯函数：口径本身（正则/共享根判定）──────────────────────────────────────

def test_close_keyword_regex_covers_section_2_2_forms():
    mod = _load_module()
    for word in ("close", "closes", "closed", "fix", "fixes", "fixed",
                 "resolve", "resolves", "resolved"):
        assert mod.CLOSE_KEYWORD_RE.search(_kw(word, 7)), f"漏掉关键词：{word}"
    assert mod.CLOSE_KEYWORD_RE.search(_kw("Closes", 7).replace(" ", "   "))
    assert not mod.CLOSE_KEYWORD_RE.search("`Closes` + `#7`"), "拆开写不得命中"


def test_shared_temp_root_classification(tmp_path, monkeypatch):
    """共享根判定**不得写平台常量**（首版硬编码 macOS 特有的 `/private/tmp` ⇒ Linux CI 红）。"""
    mod = _load_module()
    # ① 世界共享根：两个平台都成立（返回的是**清单里的那个串**，不依赖 realpath 结果）
    assert mod.shared_temp_root(TMP_TOKEN + "/x.md") == TMP_TOKEN
    assert mod.shared_temp_root("/var" + TMP_TOKEN + "/x.md") == "/var" + TMP_TOKEN
    # ② 默认清单含本机 `$TMPDIR`（由 tempfile.gettempdir() 推导；macOS=/var/folders/…、Linux=/tmp）
    tmpdir = tempfile.gettempdir()
    assert any(Path(r) == Path(tmpdir) for r in mod.default_shared_temp_roots()), \
        f"默认共享根清单未含本机 TMPDIR：{mod.default_shared_temp_roots()}"
    assert mod.shared_temp_root(str(Path(tmpdir) / "x.md")) is not None, "本机 TMPDIR 下的路径必须判为共享根"
    # ③ 工作区内目录不是共享根（两种平台都不在共享根下）
    assert mod.shared_temp_root(str(REPO_ROOT / "tests" / "tmp" / "x.md")) is None
    # ④ 显式传入清单 ⇒ 判据完全由调用方决定（跨平台确定）；空元组 ⇒ 判据关闭
    fake = str(tmp_path / "shared")
    assert mod.shared_temp_root(str(tmp_path / "shared" / "x.md"), roots=(fake,)) == fake
    assert mod.shared_temp_root(str(tmp_path / "shared" / "x.md"), roots=()) is None
    # ⑤ 环境变量注入整体替换默认清单（测试钉死场景的入口）
    monkeypatch.setenv(mod.SHARED_ROOTS_ENV, os.pathsep.join([fake, str(tmp_path / "other")]))
    assert mod.shared_temp_roots() == (fake, str(tmp_path / "other"))
    assert mod.shared_temp_root(str(tmp_path / "other" / "y.md")) == str(tmp_path / "other")
    assert mod.shared_temp_root(TMP_TOKEN + "/x.md") is None, "注入后默认清单被整体替换"
    monkeypatch.setenv(mod.SHARED_ROOTS_ENV, "")
    assert mod.shared_temp_roots() == () and mod.shared_temp_root(TMP_TOKEN + "/x.md") is None
