#!/usr/bin/env python3
"""pr_body_guard — PR body 的**会话/工作区作用域**临时文件 + 提交前自检 + 回读校验（issue #4232）。

## 病根（实测近失，非推断）

两个并发 DSH 会话都用 **`/tmp` 下同一个约定俗成的固定文件名**承载 PR body：

| 时刻 | 会话 | 动作 | 后果 |
|---|---|---|---|
| T1 | A | 写该文件（含 A 的关闭行）→ `gh pr edit A --body-file <该文件>` | 正常 |
| T2 | B | **覆盖**同一文件（含 B 的 4 条关闭行） | A 的文件被换掉 |
| T3 | A | 以为还是自己的内容，继续 `gh pr edit A --body-file <该文件>` | **A 的 body 被写成 B 的 body** |

若 A 在那个窗口被 auto-merge 合并 ⇒ **误关另外 4 个 issue**（另一会话的在建工作）。
归因 = 违反 `migao-dev-flow` §2.3「会话之间零共享写路径」—— **`/tmp` 就是一条共享写路径**；
病根与 §19.2「静默失效」同族：**没有任何东西会因此变红**，直到有人（或 auto-merge）用错内容。

## 用法（三态退出码：0 = 正常；1 = 检出问题；3 = **无法判定**，绝不谎报正常）

    # ① 在本工作区的**忽略目录**里分配唯一文件（含分支名/issue 号/pid + 随机后缀）
    BODY=$(python3 scripts/pr_body_guard.py new --issue 4232)
    cat > "$BODY" <<'EOF'
    ...PR body...
    EOF

    # ② 提交前**先打印再核**（首行 + 关闭关键词命中清单；--expect = 本意条数）
    python3 scripts/pr_body_guard.py check --expect 1 "$BODY"
    gh pr create --base main --title "..." --body-file "$BODY"

    # ③ 写完**回读校验**（从 GitHub 读回 body 与本地比对：内容哈希 + 首行）
    python3 scripts/pr_body_guard.py verify 4232 "$BODY"

    # ④ 静态守卫（机器可判的那半）：仓内被跟踪文件里不得有「共享固定名承载 PR body」形态
    python3 scripts/pr_body_guard.py scan

`new` 的落点规则（**fail-closed**）：必须 ① 在**本工作区内** ② 被 `.gitignore` 覆盖
③ 不在共享临时根下 —— 任一不满足即 exit 1 并给出可行动信息（默认依次尝试 `<worktree>/.dsh-tmp`、
`<worktree>/tests/tmp`，取第一个被忽略的；可用 `--dir` / `$PR_BODY_GUARD_DIR` 指定）。
文件名 = `<slug>-<分支 slug>-<i<issue>|p<pid>>-<6 位随机>.md`，用 `O_CREAT|O_EXCL` 原子创建
⇒ 真并发也不会撞车（**固定名正是本单的缺陷**）。

## `check` 的关闭关键词口径（与 §2.2 **同一套朴素正则**）

`(close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved)\\s*#\\d+`（大小写不敏感）。
**不区分语义** ⇒ 引用式样例（证据表里贴一条 `Closes` + `#NNNN`）、否定句（「不关闭」）**照样命中** ——
所以它**列出命中清单让人逐个确认**，而不是静默放行；想表达「不关某 issue」必须把关键词与号**拆开**写。
命中数 ≠ `--expect` ⇒ exit 1；`--expect` 缺省时「命中 > 0 ⇒ 1」。

## `verify` 只读

只调用 `gh pr view <n> --json body`（**绝不** `edit`/`create`/`api` 写操作；自测有替身 argv 断言）。
`gh` 缺失 / 非零退出 / 返回非 JSON ⇒ exit 3（「看不了」不得当「没问题」）。
`--gh-bin`（或 `$PR_BODY_GUARD_GH`）可换替身，供测试与多环境复用。

## `scan` 的判据与**边界**（照实登记，别把「登记了」读成「治住了」）

只扫 **`git ls-files` 的被跟踪文本文件**，两条规则：

- **R1**：同一逻辑行（含 `\\` 续行）里既有 `gh pr create|edit`，又有 `--body-file <共享临时根下的固定路径>`
  （路径含 `$`/反引号/`%`/`<(`/`mktemp` 视为「计算出来的」⇒ 不判）；
- **R2**：共享临时根下、文件名词干是 `pr-body` / `pr_body` 族的**任何**出现（如 `cat > …/pr-body.md`）。

**边界**：① 只覆盖**仓内文本**，**覆盖不到 agent 在 shell 里临时敲的命令**（本单的原始形态）；
② 变量/拼接/间接赋值（先 `BODY=/tmp/<固定名>`、再 `gh pr create --body-file "$BODY"`）**不可判**；
③ 非 PR body 的普通临时文件（如 workflow 里给 issue comment 用的 `--body-file`）**不判**（CI runner 内的
`/tmp` 不跨会话，且改 `.github/**` 不属本包所有权）；④ 引用/否定式说明文字**照样命中**（与 §2.2 同族，
不区分语义）。本脚本**未接 CI required check** —— 现为人工/流程调用 + 单测守卫
（`tests/unit_ci_workflows/test_pr_body_guard.py`）。

退出码汇总：`0` 正常（`check` 亦可为「命中数 = `--expect`」）；`1` 检出问题；`3` 无法判定。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

EXIT_OK, EXIT_FOUND, EXIT_UNKNOWN = 0, 1, 3

# 共享临时根（跨会话共享写路径）。macOS 的 `/tmp` 会 realpath 成 `/private/tmp`，两者都算。
SHARED_TEMP_ROOTS = ("/tmp", "/var/tmp")

# §2.2 的朴素正则（**同一口径**，不另立一份）：不区分语义 ⇒ 引用式/否定式照样命中。
CLOSE_KEYWORD_RE = re.compile(
    r"(close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved)\s*#\d+", re.IGNORECASE)

# scan 规则用的形态
SHARED_PATH_RE = re.compile(r"/(?:private/)?(?:var/)?tmp/[A-Za-z0-9._/-]*")
PR_BODY_BASENAME_RE = re.compile(r"^pr[-_.]?body(?:$|\.)", re.IGNORECASE)
BODY_FILE_RE = re.compile(r"--body-file[=\s]+(\S+)")
GH_PR_EDIT_RE = re.compile(r"\bgh\s+pr\s+(?:create|edit)\b")
# 出现这些标记 ⇒ 路径是「算出来的」（不是写死的固定名）⇒ 静态判据不可判，不报
COMPUTED_MARKERS = ("$", "`", "%", "<(", "mktemp", "*")

MAX_SCAN_BYTES = 512 * 1024
DEFAULT_DIR_CANDIDATES = (".dsh-tmp", "tests/tmp")


# ── 路径/作用域判定（纯函数，单测直调）────────────────────────────────────────

def shared_temp_root(path) -> "str | None":
    """返回 `path` 落在的**共享临时根**（原样返回 `SHARED_TEMP_ROOTS` 里的那个串），否则 None。"""
    p = Path(os.path.realpath(str(path)))
    for root in SHARED_TEMP_ROOTS:
        r = Path(os.path.realpath(root))
        if p == r or r in p.parents:
            return root
    return None


def user_temp_root(path) -> "str | None":
    """返回 `path` 落在的**用户级临时根**（`$TMPDIR`，同用户多会话共享）—— 只提示，不判红。"""
    p = Path(os.path.realpath(str(path)))
    try:
        r = Path(os.path.realpath(tempfile.gettempdir()))
    except OSError:
        return None
    if r in p.parents:
        return str(r)
    return None


def find_close_keywords(text: str) -> "list[tuple[int, str]]":
    """逐行找关闭关键词命中，返回 `[(行号, 命中原文), ...]`。"""
    hits = []
    for no, line in enumerate(text.splitlines(), 1):
        for m in CLOSE_KEYWORD_RE.finditer(line):
            hits.append((no, m.group(0)))
    return hits


def is_shared_fixed_path(token: str) -> bool:
    """该 token 是否是「共享临时根下的**写死**路径」（含变量/命令替换的算不出来 ⇒ 不判）。"""
    tok = token.strip().strip("\"'").rstrip("\\;,")
    if not tok or any(marker in tok for marker in COMPUTED_MARKERS):
        return False
    return shared_temp_root(tok) is not None


def scan_text(rel: str, text: str) -> "list[dict]":
    """按 R1/R2 扫一份文本，返回 `[{file, line, rule, excerpt, token}]`（同一行同一 token 只记一次）。"""
    findings: dict[tuple[int, str], dict] = {}
    logical = []            # (起始行号, 拼接后的逻辑行)
    buf, start = "", 0
    for no, raw in enumerate(text.splitlines(), 1):
        if not buf:
            start = no
        buf += raw[:-1] if raw.endswith("\\") else raw
        if not raw.endswith("\\"):
            logical.append((start, buf))
            buf = ""
    if buf:
        logical.append((start, buf))

    for no, line in logical:
        if GH_PR_EDIT_RE.search(line):
            for m in BODY_FILE_RE.finditer(line):
                tok = m.group(1).strip().strip("\"'").rstrip("\\;,")
                if is_shared_fixed_path(tok):
                    findings.setdefault((no, tok), {
                        "file": rel, "line": no, "rule": "R1",
                        "excerpt": line.strip()[:200], "token": tok,
                    })
        for m in SHARED_PATH_RE.finditer(line):
            tok = m.group(0)
            base = tok.rstrip("/").rsplit("/", 1)[-1]
            if PR_BODY_BASENAME_RE.match(base):
                findings.setdefault((no, tok), {
                    "file": rel, "line": no, "rule": "R2",
                    "excerpt": line.strip()[:200], "token": tok,
                })
    return sorted(findings.values(), key=lambda f: (f["line"], f["rule"]))


# ── git 边界 ─────────────────────────────────────────────────────────────────

def git(args, cwd=None) -> "subprocess.CompletedProcess | None":
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None


def resolve_root(explicit) -> "Path | None":
    """把 `explicit`（或 cwd）解析成 git 工作区根；不是工作区/拿不到 ⇒ None（调用方判 3）。"""
    cwd = str(Path(explicit).expanduser()) if explicit else None
    if explicit and not Path(cwd).is_dir():
        return None
    proc = git(["rev-parse", "--show-toplevel"], cwd=cwd)
    if proc is None or proc.returncode != 0 or not proc.stdout.strip():
        return None
    return Path(proc.stdout.strip())


def is_git_ignored(path: Path, cwd: Path) -> bool:
    proc = git(["check-ignore", "-q", "--", str(path)], cwd=cwd)
    return proc is not None and proc.returncode == 0


def current_branch(cwd: Path) -> str:
    proc = git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd)
    branch = (proc.stdout.strip() if proc and proc.returncode == 0 else "") or "nobranch"
    return re.sub(r"[^A-Za-z0-9._-]+", "-", branch).strip("-")[:40] or "nobranch"


# ── 子命令 ───────────────────────────────────────────────────────────────────

def cmd_new(args) -> int:
    root = resolve_root(args.root)
    if root is None:
        print(f"无法判定：{args.root or os.getcwd()} 不是 git 工作区 ⇒ 无法判定安全落点（exit 3）。",
              file=sys.stderr)
        return EXIT_UNKNOWN

    explicit = args.dir or os.environ.get("PR_BODY_GUARD_DIR")
    candidates = [Path(explicit).expanduser()] if explicit else [root / d for d in DEFAULT_DIR_CANDIDATES]

    name = re.sub(r"[^A-Za-z0-9._-]+", "-", args.name or "pr-body").strip("-") or "pr-body"
    uniq = f"i{args.issue}" if args.issue else f"p{os.getpid()}"
    filename = f"{name}-{current_branch(root)}-{uniq}-{secrets.token_hex(3)}.md"

    problems = []
    real_root = Path(os.path.realpath(str(root)))
    for d in candidates:
        rd = Path(os.path.realpath(str(d)))
        shared = shared_temp_root(rd)
        if shared is not None:
            problems.append(
                f"  · {d}：位于**共享临时根** {shared} —— `/tmp` 是跨会话共享写路径（§2.3），"
                f"另一会话可覆盖该文件（这正是本单的缺陷形态）。请改用**工作区内**的忽略目录，"
                f"例如 `{root}/tests/tmp`，或直接不带 `--dir` 让本脚本自动挑。")
            continue
        if rd != real_root and real_root not in rd.parents:
            problems.append(f"  · {d}：不在本工作区（{root}）内 —— 会话之间零共享写路径（§2.3）。")
            continue
        target = d / filename
        if not is_git_ignored(target, root):
            problems.append(
                f"  · {d}：未被 .gitignore 覆盖（会被误提交）。加一行忽略规则（如 `{d.name}/`）"
                f"或换一个已忽略的目录。")
            continue
        try:
            d.mkdir(parents=True, exist_ok=True)
            for _ in range(5):      # O_EXCL 原子创建：真并发下也不会撞车
                fd = os.open(str(target), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(fd)
                print(str(target))
                print(f"[scope] 工作区 {root} · 忽略目录 {d} · 唯一名 {filename}",
                      file=sys.stderr)
                print(f"[next] 写入 body 后：python3 scripts/pr_body_guard.py check --expect <本意条数> "
                      f"\"{target}\" → gh pr create --body-file \"{target}\" → "
                      f"python3 scripts/pr_body_guard.py verify <PR号> \"{target}\"", file=sys.stderr)
                return EXIT_OK
            problems.append(f"  · {d}：连续 5 次分配都撞上同名文件（异常）——请重跑或换目录。")
        except OSError as e:
            problems.append(f"  · {d}：无法创建（{e.__class__.__name__}: {e}）。")

    print("🔴 拒绝分配 PR body 临时文件（exit 1）：没有满足「工作区内 + 被 .gitignore 覆盖 + 非共享根」的落点。",
          file=sys.stderr)
    for p in problems:
        print(p, file=sys.stderr)
    print(f"[fix] 用 `python3 scripts/pr_body_guard.py new --issue <N>`（自动挑 {root} 下的忽略目录），"
          f"或 `--dir {root}/tests/tmp`；**不要**用共享临时根下的固定文件名。", file=sys.stderr)
    return EXIT_FOUND


def cmd_check(args) -> int:
    path = Path(args.file).expanduser()
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        print(f"无法判定：读不到 {path}（{e.__class__.__name__}）⇒ 不谎报正常（exit 3）。", file=sys.stderr)
        return EXIT_UNKNOWN

    first = text.splitlines()[0] if text.splitlines() else ""
    hits = find_close_keywords(text)
    findings = []

    shared = shared_temp_root(path)
    if shared is not None:
        findings.append(f"🔴 该文件位于**共享临时根** {shared} —— 另一会话可覆盖它（§2.3 / 本单缺陷形态）；"
                        f"改用 `python3 scripts/pr_body_guard.py new` 分配的工作区内路径。")
    else:
        utmp = user_temp_root(path)
        if utmp is not None:
            print(f"⚠️ 该文件位于用户级临时根 {utmp}（同用户多会话共享）——建议改用工作区内忽略目录。",
                  file=sys.stderr)
    if not text.strip():
        findings.append("🔴 body 为空 —— 空 body 既拿不到 `Closes` 关联，也说明写错了文件。")

    print(f"── PR body 自检：{path} ──")
    print(f"首行: {first}")
    print(f"命中 {len(hits)} 条（正则 (close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved)"
          f"\\s*#\\d+，口径同 migao-dev-flow §2.2）")
    for no, raw in hits:
        nums = re.findall(r"#(\d+)", raw)
        print(f"  第 {no} 行: {raw}  → 会关闭 {', '.join('#' + n for n in nums)}")
    for f in findings:
        print(f)
    if hits:
        print("⚠️ 以上 issue 会在本 PR 合并后被**自动关闭** —— 逐个确认是否本意"
              "（引用式/否定式同样命中；要表达「不关」请把关键词与号**拆开**写）。")
    else:
        print("✅ 未命中关闭关键词（0 条）。")

    if args.expect is not None:
        if len(hits) != args.expect:
            print(f"🔴 命中数 {len(hits)} ≠ --expect {args.expect} ⇒ 检出不本意的关闭行（exit 1）。")
            return EXIT_FOUND
        if not findings:
            print(f"✅ 命中数 {len(hits)} = --expect {args.expect} ⇒ 放行。")
    if findings or (args.expect is None and hits):
        return EXIT_FOUND
    return EXIT_OK


def cmd_verify(args) -> int:
    path = Path(args.file).expanduser()
    try:
        local_bytes = path.read_bytes()
    except OSError as e:
        print(f"无法判定：读不到本地文件 {path}（{e.__class__.__name__}）⇒ exit 3。", file=sys.stderr)
        return EXIT_UNKNOWN

    gh = args.gh_bin or os.environ.get("PR_BODY_GUARD_GH") or "gh"
    cmd = [gh, "pr", "view", str(args.pr), "--json", "body"]
    if args.repo:
        cmd += ["--repo", args.repo]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    except FileNotFoundError:
        print(f"无法判定：找不到可执行文件 {gh} ⇒ 读不回远端 body（exit 3，不谎报一致）。", file=sys.stderr)
        return EXIT_UNKNOWN
    except subprocess.SubprocessError as e:
        print(f"无法判定：调用 {gh} 失败（{e.__class__.__name__}）⇒ exit 3。", file=sys.stderr)
        return EXIT_UNKNOWN
    if proc.returncode != 0:
        print(f"无法判定：{gh} pr view {args.pr} 退出码 {proc.returncode}：{(proc.stderr or '').strip()[:400]}"
              f" ⇒ exit 3。", file=sys.stderr)
        return EXIT_UNKNOWN
    try:
        payload = json.loads(proc.stdout)
        remote = payload.get("body") if isinstance(payload, dict) else None
    except (ValueError, TypeError) as e:
        print(f"无法判定：{gh} 未返回可解析 JSON（{e.__class__.__name__}）⇒ exit 3。", file=sys.stderr)
        return EXIT_UNKNOWN
    remote_text = remote if isinstance(remote, str) else ""

    local_text = local_bytes.decode("utf-8", "replace")
    norm = lambda s: s.rstrip("\n").encode("utf-8")            # noqa: E731 —— 只差尾部换行不算不一致
    local_first = local_text.splitlines()[0] if local_text.splitlines() else ""
    remote_first = remote_text.splitlines()[0] if remote_text.splitlines() else ""
    local_hash = hashlib.sha256(norm(local_text)).hexdigest()
    remote_hash = hashlib.sha256(norm(remote_text)).hexdigest()

    print(f"── PR #{args.pr} body 回读校验 ──")
    print(f"本地首行: {local_first}")
    print(f"远端首行: {remote_first}")
    print(f"本地 sha256(去尾换行): {local_hash[:16]}")
    print(f"远端 sha256(去尾换行): {remote_hash[:16]}")
    if local_hash == remote_hash and local_first == remote_first:
        print("✅ 一致：远端 body 与本地文件内容相同。")
        return EXIT_OK

    print("🔴 不一致 —— 本地文件与 GitHub 上的 body 不同（**另一个会话可能把你的文件换掉了**，"
          "或 `gh pr edit` 用了别的文件）。")
    if local_first != remote_first:
        print(f"   首行差异：本地「{local_first}」 vs 远端「{remote_first}」")
    print("   ---- 本地 → 远端 逐行 diff ----")
    import difflib
    for line in list(difflib.unified_diff(local_text.rstrip("\n").splitlines(),
                                          remote_text.rstrip("\n").splitlines(),
                                          "local", "remote", lineterm=""))[:40]:
        print("   " + line)
    print("   [fix] 确认哪一份是本意后重写：`gh pr edit <PR> --body-file <本意文件>`，"
          "并重跑本命令复核（**不要**在共享临时根下用固定名文件）。")
    return EXIT_FOUND


def cmd_scan(args) -> int:
    root = resolve_root(args.root)
    if root is None:
        print(f"无法判定：{args.root or os.getcwd()} 不是 git 工作区 ⇒ 扫不到被跟踪文件（exit 3）。",
              file=sys.stderr)
        return EXIT_UNKNOWN
    proc = git(["ls-files", "-z"], cwd=root)
    if proc is None or proc.returncode != 0:
        print("无法判定：`git ls-files` 取不到被跟踪文件清单 ⇒ exit 3。", file=sys.stderr)
        return EXIT_UNKNOWN
    rels = [r for r in proc.stdout.split("\0") if r]

    findings, scanned = [], 0
    for rel in rels:
        f = root / rel
        try:
            if f.stat().st_size > MAX_SCAN_BYTES:
                continue
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue                      # 二进制/不可读 ⇒ 跳过（静态判据只覆盖仓内文本）
        scanned += 1
        findings.extend(scan_text(rel, text))

    print(f"── 静态守卫：扫描仓内被跟踪文件（{scanned}/{len(rels)} 个文本文件）──")
    print(f"命中 {len(findings)} 处「共享固定名临时文件承载 PR body」形态"
          f"{'：' if findings else ' ✅'}")
    for f in findings:
        print(f"  {f['file']}:{f['line']}  [{f['rule']}] {f['token']}")
        print(f"      {f['excerpt']}")
    if findings:
        print("🔴 改用 `python3 scripts/pr_body_guard.py new --issue <N>`（会话/工作区作用域唯一名）。")
    print("边界：只覆盖**仓内文本**，覆盖不到 agent 在 shell 里临时敲的命令；"
          "变量/拼接式路径不可判；非 PR body 的普通临时文件不判（详见脚本 docstring）。")
    return EXIT_FOUND if findings else EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pr_body_guard.py",
        description="PR body 的会话/工作区作用域临时文件 + 提交前自检 + 回读校验（issue #4232）")
    sub = p.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("new", help="在**本工作区内的忽略目录**分配唯一 body 文件并打印路径（exit 0/1/3）")
    n.add_argument("--name", default="pr-body", help="文件名前缀（默认 pr-body）")
    n.add_argument("--issue", type=int, default=None, help="关联 issue 号（并入文件名，保证唯一性）")
    n.add_argument("--dir", default=None, help="显式指定目录（必须在本工作区内且被忽略；共享根 ⇒ 拒绝）")
    n.add_argument("--root", default=None, help="工作区根（默认按 cwd 解析 git 工作区）")
    n.set_defaults(func=cmd_new)

    c = sub.add_parser("check", help="打印 body 首行 + 关闭关键词命中清单（exit 0/1/3）")
    c.add_argument("file")
    c.add_argument("--expect", type=int, default=None, help="本意关闭条数；命中数 ≠ 它 ⇒ exit 1")
    c.set_defaults(func=cmd_check)

    v = sub.add_parser("verify", help="从 GitHub 回读 body 与本地文件比对（只读；exit 0/1/3）")
    v.add_argument("pr")
    v.add_argument("file")
    v.add_argument("--repo", default=None, help="OWNER/NAME（默认 gh 推断）")
    v.add_argument("--gh-bin", default=None, help="gh 可执行文件（替身注入点；默认 $PR_BODY_GUARD_GH 或 gh）")
    v.set_defaults(func=cmd_verify)

    s = sub.add_parser("scan", help="静态守卫：仓内被跟踪文件里的共享固定名 PR body 形态（exit 0/1/3）")
    s.add_argument("--root", default=None, help="工作区根（默认按 cwd 解析）")
    s.set_defaults(func=cmd_scan)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
