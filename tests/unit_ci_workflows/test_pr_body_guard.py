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

## 夹具纪律

- `gh` 用**替身可执行文件**注入（`--gh-bin`）—— CLI 边界即注入点，**不打真实 GitHub API**、零写操作；
- 测试自身**不写任何共享 `/tmp` 固定名**：唯一一处 `/tmp` 用法是「被测行为就是检出共享根」，
  用 `mkdtemp(prefix=…pid…)` 唯一名 + 自清理（结构上不可能覆盖别的会话 —— 本包治的正是固定名被覆盖）；
- 「关键词 + `#号`」「`/tmp/…` 路径」样例一律**拆开拼**（本文件自身不得出现这些字面组合，见 §2.2 / 任务铁律）。
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
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
def unique_shared_tmp():
    """共享根下的**唯一名**目录（pid + 随机），用完即删。

    这是本文件唯一一处写共享根的地方 —— 被测行为就是「检出 body 落在共享根」，
    必须有一个**真的**在那儿的文件；唯一名 + 自清理 ⇒ 结构上不可能覆盖别的会话。
    """
    d = Path(tempfile.mkdtemp(prefix=f"pr-body-guard-test-{os.getpid()}-", dir=TMP_TOKEN))
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


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
    r = run_cli("new", "--dir", str(tmp_path))
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
    r = run_cli("check", str(body))
    assert r.returncode == 0, _out(r)
    assert "改用会话作用域临时文件承载 PR body" in r.stdout
    assert "命中 0 条" in r.stdout


def test_check_expect_only_allows_intended_hit_count(tmp_path):
    body = write_body(tmp_path / "b.md", _kw("Closes", 4232) + "\n")
    assert run_cli("check", str(body)).returncode == 1
    ok = run_cli("check", "--expect", "1", str(body))
    assert ok.returncode == 0, _out(ok)
    assert "命中 1 条" in ok.stdout
    over = run_cli("check", "--expect", "0", str(body))
    assert over.returncode == 1, "本意 0 条却命中 1 条 ⇒ 必须红"


def test_check_reference_style_sample_is_not_silently_passed(tmp_path):
    naive_ref = write_body(tmp_path / "ref.md", "证据表：`" + _kw("Closes", 3559) + "`（引用式样例）\n")
    r = run_cli("check", str(naive_ref))
    assert r.returncode == 1, "引用式样例按 §2.2 口径照样命中，不得静默放行"
    assert "#3559" in r.stdout and "确认" in r.stdout

    split_ref = write_body(tmp_path / "split.md", "本 PR 不关闭 `Closes` + `#3559`（拆开写，安全）\n")
    r2 = run_cli("check", str(split_ref))
    assert r2.returncode == 0, _out(r2)


def test_check_flags_body_file_living_in_shared_tmp(unique_shared_tmp):
    body = write_body(unique_shared_tmp / "b.md", _kw("Closes", 4232) + "\n")
    r = run_cli("check", str(body))
    assert r.returncode == 1, _out(r)
    assert "共享临时根" in r.stdout and TMP_TOKEN in r.stdout


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


# ── 纯函数：口径本身（正则/共享根判定）──────────────────────────────────────

def test_close_keyword_regex_covers_section_2_2_forms():
    mod = _load_module()
    for word in ("close", "closes", "closed", "fix", "fixes", "fixed",
                 "resolve", "resolves", "resolved"):
        assert mod.CLOSE_KEYWORD_RE.search(_kw(word, 7)), f"漏掉关键词：{word}"
    assert mod.CLOSE_KEYWORD_RE.search(_kw("Closes", 7).replace(" ", "   "))
    assert not mod.CLOSE_KEYWORD_RE.search("`Closes` + `#7`"), "拆开写不得命中"


def test_shared_temp_root_classification():
    mod = _load_module()
    assert mod.shared_temp_root(TMP_TOKEN + "/x.md") == TMP_TOKEN
    assert mod.shared_temp_root("/var" + TMP_TOKEN + "/x.md") == "/var" + TMP_TOKEN
    assert mod.shared_temp_root("/private" + TMP_TOKEN + "/x.md") == TMP_TOKEN
    inside = REPO_ROOT / "tests" / "tmp" / "x.md"
    assert mod.shared_temp_root(str(inside)) is None, "工作区内目录不是共享根"
