#!/usr/bin/env python3
"""agent-presets-guard — `.agent-presets/**` 版本单调性守卫 + 活锚新鲜度 + worktree 存量体检。

## 这守的是什么（三颗同族地雷）

**地雷 A：worktree 里的预设是「创建时刻的快照」（issue #3851）**

worktree 的 `.agent-presets/**` 是**创建时刻的快照**；此后 main 上预设再推进，工作区**不会自动跟上**
⇒ 这些文件相对 `origin/main` 就是「改动」（内容在**回退**）⇒ 一条 `git add -A` + push 就提交一个
**把研发模式回退若干版本**的 PR，而 **CI 不看 `.agent-presets/**` 的版本 ⇒ 不红**。

- **第一层防线（创建路径）**：`scripts/dev-worktree.sh add` 建完工作区后自动刷新到 `origin/main`。
- **第二层防线（提交路径，本脚本 `check`）**：判定暂存/工作区的 `.agent-presets/**` 是否构成
  **版本下降** ⇒ 命中即**非零退出**（fail-closed）。**合法升级必须绿**（改研发模式本身不能被堵死）。
- **第三层防线（机械安全网，别的单在做）**：`#3843` 的统一审计 `drift_audit --check` 将加
  「`.agent-presets/**` 版本单调性」守卫。本脚本与之**互补**：本脚本管**提交路径**（增量、贴合工作区），
  审计管**全库机械对账**（存量、定时）。详见 `docs/wiki/DEV-FLOW.md` 的「预设快照地雷」节。
  （A 的落地单是 `#3859`；事实单是 `#3851`。）

**地雷 B（更隐蔽）：内容全对，但**到不了加载点**（issue #4026）**

**活锚** = DSH 真正加载的那份内容：软链 `~/.dsh/.agent-presets/migao` 解析出的目录。
只查「仓库里的版本单调性」**查不出活锚落后** —— 实测活锚曾指向一个落后 `origin/main` **42 个提交**的
主工作区：**内容当时恰好一致（无害）**，但只要下一次有人改 `.agent-presets/**` 并合并，
改进就**永远到不了加载点**，后续所有会话读到的仍是旧模式（「迭代了但模式没进化」的确切机制）。
⇒ 本脚本 `anchor` 子命令/`check` 的活锚段：**活锚解析出来的检出 sha 与内容**都要对 `origin/main` 核，
落后即**非零退出**并打印同步命令（`./scripts/preset-anchor-refresh.sh`）。
**活锚必须指向专职只读镜像**（不是任何会被开发/会被 `rm -rf`、`worktree prune` 命中的工作区）——
issue #3956 实证过「软链目标被误删 ⇒ DSH 研发模式当场消失（静默）」。

**地雷 C：存量工作区积压** —— `prune` 只出清单、绝不删除（见下）。

## 为什么不用 `git update-index --skip-worktree`

那会把**合法的预设改动**（改研发模式本身）一起吞掉 —— 「眼不见为净」在这里等于把正事也堵死。
本脚本只**判定版本方向**，升级照样放行。

## 用法

    # 提交路径守卫（默认同时看暂存区与工作区；有任何一处版本下降即 exit 1）
    python3 scripts/agent-presets-guard.py check
    python3 scripts/agent-presets-guard.py check --source index     # 只看暂存区
    python3 scripts/agent-presets-guard.py check --source worktree  # 只看工作区文件
    python3 scripts/agent-presets-guard.py check --ref origin/main

    # 活锚新鲜度（DSH 真正加载的那份内容；红 = 落后/悬空/坏掉）
    python3 scripts/agent-presets-guard.py anchor
    python3 scripts/agent-presets-guard.py anchor --anchor /tmp/fake-anchor   # 指定要比的活锚（显式 ⇒ 一律判定）

    # 存量体检（只打印清单，绝不删除；--dry-run 必须显式给出）
    python3 scripts/agent-presets-guard.py prune --dry-run

退出码：0 = 绿；1 = 判定为「版本下降 / 活锚落后 / 不可判定」（fail-closed）；2 = 用法错误。

## 活锚段的三态（照实登记，别读成「有硬门禁」）

| 形态 | 判定 |
|---|---|
| 活锚路径不存在（本机没接线：CI / 容器 / 新队友未接线） | `⏭️ 未跑判定`（exit 0）—— 没有活锚要维持新鲜，红了才是误伤 |
| 活锚是软链但**目标不存在**（悬空）/ 不是 preset 目录 | ❌ 红 —— 这是 #3956 的静默失效形态（DSH 加载不到，且**不报错**） |
| 活锚内容 ≠ `origin/main`（缺文件 / 内容不同） | ❌ 红（含逐文件清单 + 版本对比 + 同步命令） |
| 内容一致但活锚检出**落后** `origin/main` | ❌ 红（现在无害，但**下一次改预设就到不了加载点** —— 正是 #4026 的病灶） |
| 内容一致、sha 也是同一个提交 | ✅ 绿 |
| 活锚检出与本仓库**不同源**（默认活锚路径才适用） | `⏭️ 未跑判定`（exit 0）—— 拿无关仓库的 main 量活锚没有意义 |

**显式 `--anchor` 一律判定**（你明确指定了要比的对象）；`⏭️` 一律**不是**「通过」。
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

PRESETS_DIR = ".agent-presets/"
DEFAULT_REF = "origin/main"
#: 活锚应指向的那一层（软链 `~/.dsh/.agent-presets/migao` 指向的就是它）。
PRESET_SUBDIR = ".agent-presets/migao"
#: 本机活锚（DSH 的 preset root `~/.dsh/.agent-presets/` 下的 preset id 目录）。
DEFAULT_ANCHOR = Path.home() / ".dsh" / ".agent-presets" / "migao"
REFRESH_CMD = "./scripts/preset-anchor-refresh.sh"
#: worktree 里唯一带 `version:` 的预设文件形态（技能 SKILL.md）。
#: 其余预设文件（preset.yml / agent.cordis.yml / README.md）**无版本号**，不参与单调性判定，
#: 只由创建路径的刷新负责带上 main 的最新内容。
VERSION_FILE_RE = re.compile(r"/skills/[^/]+/SKILL\.md$")


class GitError(RuntimeError):
    """git 调用不可用/不可判定 —— 一律 fail-closed，不得退化成「放行」。"""


class AnchorError(RuntimeError):
    """活锚本身坏掉（悬空软链 / 不是 preset 目录）—— 一律红（#3956 的静默失效形态）。"""


def git(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True
    )
    if check and proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} 失败（exit {proc.returncode}）：{proc.stderr.strip()}")
    return proc


def git_bytes(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """bytes 版：内容比对必须**逐字节**（`text=True` 会做换行/编码转换 ⇒ 判据被污染）。"""
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True)


def parse_version(text: str) -> str | None:
    """从 SKILL.md 的 YAML frontmatter 里取 `version:`。

    只认**首个 frontmatter 块**（第 1 行 `---` 到下一个 `---`）内的顶层标量，
    避免正文里的 `version:` 字样（本文件自己的文档、版本沿革里的叙述）被误当版本号。
    按 YAML 标量规则丢掉行尾注释（`#` 起），并剥引号。
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    for raw in lines[1:]:
        if raw.strip() == "---":
            break
        m = re.match(r"^version\s*:\s*(.+)$", raw)
        if not m:
            continue
        val = m.group(1).split("#", 1)[0].strip().strip("'\"")
        return val or None
    return None


def version_key(version: str) -> tuple[int, ...]:
    """`1.28.0` → (1, 28, 0)。非数字段（如 `1.29.0-rc1`）取数字前缀。"""
    parts: list[int] = []
    for chunk in version.split("."):
        m = re.match(r"^(\d+)", chunk.strip())
        if not m:
            raise ValueError(f"无法解析版本号：{version!r}")
        parts.append(int(m.group(1)))
    if not parts:
        raise ValueError(f"空版本号：{version!r}")
    return tuple(parts)


def blobs_equal(ref: str, path: str, source: str, cwd: Path) -> bool | None:
    """ref 版内容 vs 被检内容是否逐字节相同。None = 不可判定（路径在 ref 侧不存在）。"""
    existed = git("cat-file", "-e", f"{ref}:{path}", cwd=cwd, check=False)
    if existed.returncode != 0:
        return None
    if source == "worktree":
        target = (cwd / path)
        if not target.is_file():
            return False
        content = target.read_text(encoding="utf-8")
    else:
        content = git("show", f":{path}", cwd=cwd).stdout
    ref_content = git("show", f"{ref}:{path}", cwd=cwd).stdout
    return content == ref_content


def ref_version(ref: str, path: str, cwd: Path) -> str | None:
    proc = git("show", f"{ref}:{path}", cwd=cwd, check=False)
    if proc.returncode != 0:
        return None
    return parse_version(proc.stdout)


def changed_paths(ref: str, source: str, cwd: Path) -> list[str]:
    """被检的 `.agent-presets/**` 路径（相对仓库根）。

    `--diff-filter=d` 排除**删除**路径（只判「版本下降」这一种回退；预设在基准里被删是**另一类**
    回退，归 `#3843` 的 `drift_audit --check` 全库对账管，本脚本不越界）。
    """
    if source == "index":
        proc = git("diff", "--cached", "--name-only", "--diff-filter=d", ref, cwd=cwd, check=False)
        # 无 HEAD/无索引基线时退化到「暂存 vs HEAD」
        if proc.returncode != 0:
            proc = git("diff", "--cached", "--name-only", "--diff-filter=d", cwd=cwd)
        paths = proc.stdout.splitlines()
    else:
        proc = git("diff", "--name-only", "--diff-filter=d", ref, cwd=cwd)
        paths = proc.stdout.splitlines()
    return [p for p in paths if p.startswith(PRESETS_DIR)]


def check_source(ref: str, source: str, cwd: Path, out=sys.stdout, seen: dict | None = None) -> int:
    """单来源判定。返回 0（绿）/ 1（红）。

    `seen` 跨来源共享：同一路径在另一来源已被报过（如 `git checkout <sha> -- <path>` 会**同时**改
    工作区与索引）就**只报一次** —— 否则 `both` 模式把同一条降级打印两遍，读起来像两个问题。
    """
    seen = {} if seen is None else seen
    try:
        paths = changed_paths(ref, source, cwd)
    except GitError as exc:
        print(f"❌ [{source}] 无法判定（fail-closed）：{exc}", file=out)
        return 1

    label = {"index": "暂存区", "worktree": "工作区文件"}[source]
    downgrades: list[str] = []
    upgrades: list[str] = []
    forks: list[str] = []
    unchecked: list[str] = []

    for path in paths:
        if seen.get(path, "").startswith("downgrade"):
            print(f"  ℹ️  {path}：{label}同为此降级（已在另一来源报出，不重复列）", file=out)
            continue
        if not VERSION_FILE_RE.search(path):
            if seen.get(path) != "unchecked":
                unchecked.append(path)
                seen[path] = "unchecked"
            continue
        target = (cwd / path)
        if source == "index":
            proc = git("show", f":{path}", cwd=cwd, check=False)
            new_text = proc.stdout if proc.returncode == 0 else ""
        else:
            new_text = target.read_text(encoding="utf-8") if target.is_file() else ""
        new_v = parse_version(new_text)
        base_v = ref_version(ref, path, cwd)

        if base_v is None:
            print(f"❌ [{label}] {path}：{ref} 侧不存在或读不出版本 —— 不可判定（fail-closed）", file=out)
            return 1
        if new_v is None:
            print(f"❌ [{label}] {path}：取不到 `version:`（{ref} 侧为 {base_v}）—— 不可判定（fail-closed）", file=out)
            return 1
        try:
            new_k, base_k = version_key(new_v), version_key(base_v)
        except ValueError as exc:
            print(f"❌ [{label}] {path}：版本号不可比较（{exc}）—— 不可判定（fail-closed）", file=out)
            return 1

        if new_k < base_k:
            seen[path] = "downgrade"
            downgrades.append(
                f"  ❌ {path}\n     版本下降：{base_v} → {new_v}（相对 {ref}，来源：{label}）\n"
                f"     修：git checkout {ref} -- {PRESETS_DIR}"
            )
        elif new_k > base_k:
            seen[path] = "upgrade"
            upgrades.append(f"  ✅ {path}：{base_v} → {new_v}（合法升级，来源：{label}）")
        else:
            same = blobs_equal(ref, path, source, cwd)
            if same is False:
                seen[path] = "fork"
                forks.append(
                    f"  ⚠️  {path}：版本同为 {new_v} 但**内容与 {ref} 不同**（分叉，不是升级；来源：{label}）\n"
                    f"     多为「在旧快照上改了预设」⇒ 请 rebase 到最新 {ref} 后再改，避免把旧内容带回去"
                )
            else:
                seen[path] = "same"
                print(f"  ✅ {path}：版本与 {ref} 相同（{new_v}）", file=out)

    for line in upgrades:
        print(line, file=out)
    for line in forks:
        print(line, file=out)
    for line in unchecked:
        print(f"  ℹ️  {line}：无 `version:` 字段，不参与单调性判定", file=out)

    if downgrades:
        print(f"\n❌ 检出 {len(downgrades)} 处 `.agent-presets/**` **版本下降**（相对 {ref}）—— 拒绝提交：", file=out)
        for line in downgrades:
            print(line, file=out)
        print(
            "\n根因：worktree 的 `.agent-presets/**` 是**创建时刻快照**，main 推进后工作区不会自动跟上；\n"
            "      `git add -A` 就会把它当作改动提交（**内容回退**），而 CI 不看预设版本 ⇒ 不红。\n"
            f"修：git checkout {ref} -- {PRESETS_DIR}   # 然后重跑本检查\n"
            "     （若你**就是**要改研发模式：先把分支 rebase 到最新 main，再在此基础上改 + 升 version）",
            file=out,
        )
        return 1

    if not paths:
        print(f"  ⏭️  [{label}] 无 `.agent-presets/**` 变更（与 {ref} 对比）—— 本来源未跑判定", file=out)
    return 0


# ── 活锚新鲜度（地雷 B，issue #4026）─────────────────────────────────────────
# 判据的形状：**活锚解析出来的那份内容**（DSH 真正加载的）与基准 ref 的 preset 子树
# ① 逐字节比内容（版本号相同也可能已分叉 ⇒ 只看版本号会漏）；
# ② 比检出 sha（内容恰好一致但 sha 落后 ⇒ 现在无害，**下一次改预设就到不了加载点**）。
# 三态照实区分：`⏭️ 未跑判定`（没接线 / 不同源）≠ `✅ 通过`（见文件头表格）。

def _remote_url(repo: Path) -> str:
    """origin 的**生效** URL（`remote get-url` 会应用 insteadOf 重写；`config --get` 只给原始值）。"""
    proc = git("-C", str(repo), "remote", "get-url", "origin", check=False)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _same_history(ref: str, cwd: Path, anchor_repo: Path) -> tuple[bool, str]:
    """活锚检出与基线是否**同一份历史**（决定「活锚落后」这条判据能不能比）。

    ⚠️ **不能比 URL 字符串**：本机实测同一仓库有两种写法 —— 配置里是
    `https://github.com/…`，而 `url.ssh://git@ssh.github.com:443/.insteadOf` 把它重写成
    `ssh://…`。按 URL 比 ⇒ 同一仓库被判「不同源」⇒ 判据被**静默跳过**（正是本单要治的
    「绿了但没跑」）。故改用**对象级**判据：活锚检出里有没有基线 ref 的那个提交。
    """
    ref_sha = git("rev-parse", ref, cwd=cwd, check=False).stdout.strip()
    if not ref_sha:
        return False, f"读不到基线 ref：{ref}"
    if anchor_repo.resolve() == cwd.resolve():
        return True, "活锚就在本仓库检出内"
    if git("-C", str(anchor_repo), "cat-file", "-e", f"{ref_sha}^{{commit}}", check=False).returncode == 0:
        return True, f"活锚检出拥有基线提交 {ref_sha[:12]}（同一份历史）"
    return False, f"活锚检出里没有基线提交 {ref_sha[:12]}（不是同一份历史：可能是别的仓库 / 未 fetch）"


def _anchor_checkout(anchor: Path) -> tuple[Path | None, str | None]:
    """活锚所在的 git 检出（best-effort）。不是检出（手抄副本）⇒ (None, None)。"""
    proc = git("-C", str(anchor), "rev-parse", "--show-toplevel", check=False)
    if proc.returncode != 0:
        return None, None
    top = Path(proc.stdout.strip())
    head = git("-C", str(anchor), "rev-parse", "HEAD", check=False)
    sha = head.stdout.strip() if head.returncode == 0 else ""
    return top, (sha or None)


def _resolve_anchor(anchor: Path) -> Path:
    """活锚路径 → 真实目录。不存在 ⇒ FileNotFoundError；悬空/不成形 ⇒ AnchorError（一律红）。"""
    if not anchor.exists() and not anchor.is_symlink():
        raise FileNotFoundError(str(anchor))
    if anchor.is_symlink() and not anchor.exists():
        raise AnchorError(
            f"活锚**悬空**：软链 {anchor} → {os.readlink(anchor)}（目标不存在）"
        )
    real = anchor.resolve()
    if not real.is_dir():
        raise AnchorError(f"活锚不是目录：{real}")
    if not (real / "preset.yml").is_file():
        raise AnchorError(
            f"活锚不是 preset 目录（缺 preset.yml）：{real}\n"
            f"      （活锚应指向 `<检出>/{PRESET_SUBDIR}` 这一层）"
        )
    return real


def _ref_preset_paths(ref: str, cwd: Path) -> list[str]:
    """基准 ref 里 preset 子树的文件清单（相对 preset 子树根）。"""
    prefix = PRESET_SUBDIR + "/"
    proc = git("ls-tree", "-r", "--name-only", ref, "--", prefix, cwd=cwd, check=False)
    if proc.returncode != 0:
        raise GitError(
            f"读不到 {ref}:{prefix} 的文件清单（{proc.stderr.strip()}）—— 无法判定活锚"
        )
    return [p[len(prefix):] for p in proc.stdout.splitlines() if p.startswith(prefix)]


def _anchor_content(ref: str, cwd: Path, anchor: Path) -> tuple[list[str], list[str], list[str], list[str]]:
    """(expected, differing, missing, extra) —— 全部逐字节比对，不做任何「聪明」归一化。"""
    expected = _ref_preset_paths(ref, cwd)
    differing: list[str] = []
    missing: list[str] = []
    for rel in expected:
        target = anchor / rel
        if not target.is_file():
            missing.append(rel)
            continue
        blob = git_bytes("cat-file", "blob", f"{ref}:{PRESET_SUBDIR}/{rel}", cwd=cwd)
        if blob.returncode != 0:
            raise GitError(
                f"读不到 {ref}:{PRESET_SUBDIR}/{rel}（{blob.stderr.decode(errors='replace').strip()}）"
            )
        if target.read_bytes() != blob.stdout:
            differing.append(rel)
    known = set(expected)
    extra = sorted(
        p.relative_to(anchor).as_posix()
        for p in anchor.rglob("*")
        if p.is_file() and not p.is_symlink() and p.relative_to(anchor).as_posix() not in known
    )
    return expected, differing, missing, extra


def _frontmatter_problems(skill_file: Path) -> list[tuple[str, str]]:
    """技能能否被 DSH 加载器**读到**（(severity, message)；severity ∈ {red, warn}）。

    加载器规则（本目录 README 已登记）：**只读 `name` + `description`**，缺任一即**忽略整个技能**，
    且要求**第 1 行就是 `---`**（frontmatter 之前加注释会让整个技能被忽略）。
    另：`description` 是 YAML **纯标量** ⇒ 在第一个「空白 + `#`」处**静默截断**（实测丢过 2400+ 字符）。
    """
    name = skill_file.parent.name if skill_file.name == "SKILL.md" else skill_file.name
    try:
        lines = skill_file.read_text(encoding="utf-8").split("\n")
    except OSError as exc:
        return [("red", f"{name}：读不到 {skill_file}（{exc}）")]
    if not lines or lines[0].strip() != "---":
        return [("red", f"{name}：第 1 行不是 `---` ⇒ **整个技能被加载器忽略**")]
    end = next((i for i, l in enumerate(lines[1:], 1) if l.strip() == "---"), None)
    if end is None:
        return [("red", f"{name}：frontmatter 没有收尾 `---` ⇒ **整个技能被加载器忽略**")]
    block = lines[1:end]
    problems: list[tuple[str, str]] = []
    for key in ("name", "description"):
        line = next((l for l in block if re.match(rf"^{key}\s*:", l)), None)
        if line is None:
            problems.append(("red", f"{name}：frontmatter 缺 `{key}:` ⇒ **缺任一即整个技能被忽略**"))
            continue
        raw = line.split(":", 1)[1]
        if not raw.split("#", 1)[0].strip():
            problems.append(("red", f"{name}：frontmatter 的 `{key}:` 是空值 ⇒ 加载器读不到"))
            continue
        head = raw.strip()[:1]
        if head not in ("'", '"', "|", ">") and " #" in raw:
            problems.append((
                "warn",
                f"{name}：`{key}` 是**未加引号的纯标量**且含「空白 + #」⇒ YAML 会从 `#` 起当注释"
                f"**静默截断**（「文件里写了」≠「加载器读到了」）",
            ))
    return problems


def _lag_state(ref: str, cwd: Path, sha: str | None) -> str:
    """活锚检出相对基准的 sha 关系：same | behind | divergent | unknown。"""
    if not sha:
        return "unknown"
    if git("cat-file", "-e", f"{sha}^{{commit}}", cwd=cwd, check=False).returncode != 0:
        return "unknown"          # 对象不在基准仓（跨仓比较）⇒ 不判，退到内容级
    ref_sha = git("rev-parse", ref, cwd=cwd, check=False).stdout.strip()
    if ref_sha and ref_sha == sha:
        return "same"
    if git("merge-base", "--is-ancestor", sha, ref, cwd=cwd, check=False).returncode == 0:
        return "behind"
    return "divergent"


def _commits_behind(ref: str, sha: str, cwd: Path) -> str:
    proc = git("rev-list", "--count", f"{sha}..{ref}", cwd=cwd, check=False)
    return proc.stdout.strip() if proc.returncode == 0 and proc.stdout.strip() else "?"


def judge_anchor(ref: str, cwd: Path, anchor: Path, explicit: bool = False, out=sys.stdout) -> int:
    """活锚新鲜度判定。0 = 绿（或 `⏭️` 未跑判定）；1 = 红（落后 / 悬空 / 内容不同 / 不可加载）。

    `explicit=True`（用户显式 `--anchor`）⇒ **一律判定**；否则默认活锚只在「与当前仓库同源」时判定
    （拿无关仓库的 `main` 量活锚没有意义：夹具仓库、别的产品仓库都会误报）。
    """
    print("\n🔎 活锚新鲜度（DSH 真正加载的那份内容；地雷 B / issue #4026）", file=out)
    print(f"   活锚：{anchor}", file=out)
    try:
        real = _resolve_anchor(anchor)
    except FileNotFoundError:
        print("   ⏭️ 未接线：该路径不存在 —— 本机没有活锚要维持新鲜"
              "（**未跑判定**，不等于「通过」）", file=out)
        return 0
    except AnchorError as exc:
        print(f"   ❌ {exc}", file=out)
        print("      后果：DSH **静默**加载不到研发模式（不报错，只是「模式不见了」—— #3956 同款事故）", file=out)
        print("      修：确认专职只读镜像在位后重链；见根 AGENTS.md「开发环境准备」/ "
              f"{PRESET_SUBDIR}/README.md", file=out)
        return 1

    top, sha = _anchor_checkout(real)
    base_sha = git("rev-parse", "--short", ref, cwd=cwd, check=False).stdout.strip() or "?"
    if top is None:
        print("   ⚠️ 活锚不是 git 检出（判不了 sha/落后）—— 形态上属**手抄副本**：没有跟随机制", file=out)
    else:
        if not explicit:
            same, why = _same_history(ref, cwd, top)
            if not same:
                print(f"   ⏭️ 未跑判定：{why}", file=out)
                print(f"      （活锚检出 origin={_remote_url(top) or '—'}；本仓库 origin={_remote_url(cwd) or '—'}）", file=out)
                return 0
        state = _lag_state(ref, cwd, sha)
        lag_txt = {
            "same": "与基线同一提交",
            "behind": f"落后 {_commits_behind(ref, sha, cwd)} 个提交",
            "divergent": "不在基线历史上（分叉）",
            "unknown": "sha 关系未判（对象不在基准仓）",
        }[state]
        print(f"   活锚检出：{top} @{(sha or '?')[:12]}（{lag_txt}）", file=out)
    print(f"   基线：{ref} @{base_sha}（仓库 {cwd}；只读**本地** ref —— 要连远端一起核请先 fetch/刷新）", file=out)

    try:
        expected, differing, missing, extra = _anchor_content(ref, cwd, real)
    except GitError as exc:
        print(f"   ❌ 无法判定活锚内容（fail-closed）：{exc}", file=out)
        return 1

    for rel in [p for p in expected if VERSION_FILE_RE.search("/" + p)]:
        target = real / rel
        live_v = parse_version(target.read_text(encoding="utf-8")) if target.is_file() else None
        ref_v = ref_version(ref, f"{PRESET_SUBDIR}/{rel}", cwd)
        print(f"   {rel.split('/')[-2]:<18} 活锚={live_v or '?'} 基线={ref_v or '?'}", file=out)

    fm_problems: list[tuple[str, str]] = []
    for skill in sorted((real / "skills").glob("*/SKILL.md")):
        fm_problems += _frontmatter_problems(skill)
    for severity, msg in fm_problems:
        print(f"   {'❌' if severity == 'red' else '⚠️'} {msg}", file=out)
    if extra:
        print(f"   ⚠️ 活锚里有 {len(extra)} 个基线中不存在的文件（就地编辑残留 / 本机备份？"
              f"活锚应**只读**）：", file=out)
        for rel in extra[:10]:
            print(f"      - {rel}", file=out)

    if differing or missing:
        print(f"   ❌ 活锚内容与 {ref} 不一致：{len(differing)} 个文件内容不同、{len(missing)} 个文件缺失", file=out)
        for rel in (differing + missing)[:20]:
            print(f"      - {PRESET_SUBDIR}/{rel}", file=out)
        print("   ⇒ 这正是「迭代了但模式没进化」：改进**到不了加载点**。**先同步再动手**：", file=out)
        print(f"      {REFRESH_CMD}", file=out)
        return 1

    if any(sev == "red" for sev, _ in fm_problems):
        print(f"   ⇒ 活锚内容与基线一致，但**技能本身加载不了**（加载器会静默忽略它）。先修 frontmatter 再动手。", file=out)
        return 1

    state = _lag_state(ref, cwd, sha) if top else "unknown"
    if state == "divergent":
        print(f"   ❌ 活锚检出不在 {ref} 的历史上（分叉）：{(sha or '?')[:12]} —— 按「先同步」处理", file=out)
        print(f"      {REFRESH_CMD}", file=out)
        return 1
    if state == "behind":
        print(f"   ❌ 活锚**落后** {ref} {_commits_behind(ref, sha, cwd)} 个提交"
              f"（内容当前恰好一致：0 个文件不同）—— **先同步再动手**", file=out)
        print("      此刻加载到的模式与 main 相同（无害），但**下一次有人改预设，改进就到不了加载点**"
              "（#4026 的病灶机制）", file=out)
        print(f"      {REFRESH_CMD}", file=out)
        return 1

    tail = "，且 sha 为同一提交" if state == "same" else "（sha 关系未判：活锚不是 git 检出）"
    print(f"   ✅ 活锚新鲜：内容与 {ref} 逐字节一致（{len(expected)} 个文件）{tail}", file=out)
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    cwd = Path(args.repo).resolve()
    sources = [args.source] if args.source != "both" else ["index", "worktree"]
    print(f"🔎 `.agent-presets/**` 版本单调性守卫（基准 {args.ref}）")
    seen: dict = {}
    rc = 0
    for source in sources:
        rc |= check_source(args.ref, source, cwd, seen=seen)
    if rc == 0:
        print("✅ 通过：无 `.agent-presets/**` 版本下降（升级与「与基准相同」均放行）")

    # 地雷 B（issue #4026）：仓库内容全对 ≠ 活锚新鲜 —— 活锚落后时改进到不了加载点。
    # 显式 `--anchor` 一律判定；默认活锚只在「与当前仓库同源」时判定（见 judge_anchor）。
    anchor = Path(args.anchor).expanduser() if args.anchor else DEFAULT_ANCHOR
    rc |= judge_anchor(args.ref, cwd, anchor, explicit=bool(args.anchor), out=sys.stdout)
    return rc


def cmd_anchor(args: argparse.Namespace) -> int:
    """活锚新鲜度（独立入口；供 `scripts/preset-anchor-check.sh` 与开工自检调用）。"""
    cwd = Path(args.repo).resolve()
    return judge_anchor(args.ref, cwd, Path(args.anchor).expanduser(), explicit=True, out=sys.stdout)


def _worktrees(cwd: Path) -> list[dict]:
    proc = git("worktree", "list", "--porcelain", cwd=cwd)
    entries: list[dict] = []
    cur: dict = {}
    for line in proc.stdout.splitlines():
        if line.startswith("worktree "):
            if cur:
                entries.append(cur)
            cur = {"path": line.split(" ", 1)[1], "branch": "", "sha": ""}
        elif line.startswith("branch refs/heads/") and cur:
            cur["branch"] = line[len("branch refs/heads/"):]
        elif line.startswith("HEAD ") and cur:
            cur["sha"] = line.split(" ", 1)[1]
        elif line.startswith("detached") and cur:
            cur["branch"] = ""
    if cur:
        entries.append(cur)
    return entries


def _unmerged_commits(ref: str, branch: str, cwd: Path) -> int:
    """该分支相对 ref 还有多少提交**未被合入**（`git cherry` 的 `+` 行数）。"""
    proc = git("cherry", ref, branch, cwd=cwd, check=False)
    if proc.returncode != 0:
        return -1
    return sum(1 for line in proc.stdout.splitlines() if line.startswith("+ "))


def _merged_into(ref: str, branch: str, cwd: Path) -> bool:
    """分支是否**已合入** ref。

    squash 合并后 commit 可达性不是判据（§17.3/§17.4），故：
    ① 祖先可达 → 已合入；② 否则用 `git cherry` 看有无「未进 upstream」的提交（`+` 行）。
    """
    if not branch:
        return False
    if git("merge-base", "--is-ancestor", branch, ref, cwd=cwd, check=False).returncode == 0:
        return True
    return _unmerged_commits(ref, branch, cwd) == 0


def _locked_branches(cwd: Path) -> set[str]:
    """活跃会话锁涉及的分支（PID 仍存活）—— 被锁的工作区一律不判「可安全移除」。

    锁目录一律按 **common git dir** 定位（worktree 内的 `$WT/.git` 是指针文件、不是目录，
    直接拼 `.git/sessions` 会永远读不到 —— 那会让守卫**静默失效**）。
    """
    common = git("rev-parse", "--git-common-dir", cwd=cwd, check=False)
    lock_dir = Path(common.stdout.strip() or (cwd / ".git"))
    if not lock_dir.is_absolute():
        lock_dir = cwd / lock_dir
    lock_dir = lock_dir / "sessions"
    if not lock_dir.is_dir():
        return set()
    alive: set[str] = set()
    for f in lock_dir.glob("*.lock"):
        try:
            fields = f.read_text(encoding="utf-8").split("|")
        except OSError:
            continue
        pid = fields[0].strip() if fields else ""
        branch = fields[2].strip() if len(fields) > 2 else ""
        if not (pid.isdigit() and branch):
            continue
        try:
            os.kill(int(pid), 0)
        except (OSError, ValueError):
            continue
        alive.add(branch)
    return alive


def cmd_prune(args: argparse.Namespace) -> int:
    cwd = Path(args.repo).resolve()
    if not args.dry_run:
        print("❌ 本子命令**只出判定与清单，不执行删除**（存量工作区可能有未合并工作）。", file=sys.stderr)
        print("   请传 --dry-run 看清单；真删请按清单后打印的单条命令人工执行。", file=sys.stderr)
        return 2
    ref = args.ref
    entries = _worktrees(cwd)
    root = Path(git("rev-parse", "--show-toplevel", cwd=cwd).stdout.strip())
    locked = _locked_branches(cwd)

    safe: list[tuple[str, str]] = []
    manual: list[tuple[str, str, str]] = []
    for e in entries:
        path, branch = e["path"], e["branch"]
        if Path(path).resolve() == root.resolve():
            manual.append((path, branch or "(detached)", "主工作区，永不判可移除"))
            continue
        if not Path(path).is_dir():
            manual.append((path, branch or "(detached)", "目录已不存在（stale worktree 记录）→ 用 `git worktree prune` 清理"))
            continue
        dirty = git("status", "--porcelain", cwd=Path(path), check=False).stdout.strip()
        reasons = []
        if dirty:
            reasons.append(f"工作树不干净（{len(dirty.splitlines())} 条改动）")
        if not branch:
            reasons.append("detached HEAD，无分支可核合入状态")
        elif branch in locked:
            reasons.append("有活跃会话锁（可能有会话在用）")
        elif not _merged_into(ref, branch, cwd):
            ahead = _unmerged_commits(ref, branch, cwd)
            reasons.append(
                f"分支未合入 {ref}（{ahead if ahead >= 0 else '?'} 个提交未进 upstream，可能仍有未合并工作）"
            )
        if reasons:
            manual.append((path, branch or "(detached)", "；".join(reasons)))
        else:
            safe.append((path, branch))

    print(f"🧹 worktree 存量体检（基准 {ref}，工作区共 {len(entries)} 个）—— **只出清单，不删除**\n")
    print(f"── 可安全移除（分支已合入 {ref} + 工作树干净 + 无活跃锁）：{len(safe)} 个 ──")
    for path, branch in safe:
        print(f"  ✅ {path}  （分支 {branch}）")
    if not safe:
        print("  （无）")
    print(f"\n── 需人看（其余 {len(manual)} 个）：")
    for path, branch, why in manual:
        print(f"  ⚠️  {path}  （{branch}）：{why}")
    print(
        "\n如何真删（**人工逐条确认后执行**，本脚本不代劳）：\n"
        "  ./scripts/dev-worktree.sh rm <分支或路径> --delete-branch\n"
        f"⚠️ 判据是「已合入 {ref}」的**内容级**判定（祖先可达 + `git cherry` 无 `+` 行）；\n"
        "   若你不确定，先 `git -C <path> log --oneline -3` 与 `git status` 人工过一遍。"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agent-presets-guard",
        description="`.agent-presets/**` 版本单调性守卫（提交路径 fail-closed）+ worktree 存量体检（只列清单）",
    )
    parser.add_argument("--repo", default=".", help="仓库根（默认当前目录）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_check = sub.add_parser("check", help="判定被检内容是否构成 `.agent-presets/**` 版本下降（含活锚新鲜度）")
    p_check.add_argument("--ref", default=DEFAULT_REF, help=f"基准 ref（默认 {DEFAULT_REF}）")
    p_check.add_argument(
        "--source", choices=["both", "index", "worktree"], default="both",
        help="both=暂存区+工作区（默认）；index=只看 `git diff --cached`；worktree=只看工作区文件",
    )
    p_check.add_argument(
        "--anchor", default=None,
        help=f"活锚路径（默认 {DEFAULT_ANCHOR}）；**显式给出即一律判定**，不因「不同源」跳过",
    )
    p_check.set_defaults(func=cmd_check)

    p_anchor = sub.add_parser("anchor", help="活锚新鲜度判定（活锚 vs 基准 ref；落后/悬空/内容不同即非零退出）")
    p_anchor.add_argument("--ref", default=DEFAULT_REF, help=f"基准 ref（默认 {DEFAULT_REF}）")
    p_anchor.add_argument(
        "--anchor", default=str(DEFAULT_ANCHOR),
        help=f"活锚路径（默认 {DEFAULT_ANCHOR}）",
    )
    p_anchor.set_defaults(func=cmd_anchor)

    p_prune = sub.add_parser("prune", help="worktree 存量体检（只打印清单，不删除）")
    p_prune.add_argument("--ref", default=DEFAULT_REF, help=f"合入判定基准（默认 {DEFAULT_REF}）")
    p_prune.add_argument("--dry-run", action="store_true", help="必须显式给出；本子命令只出清单")
    p_prune.set_defaults(func=cmd_prune)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
