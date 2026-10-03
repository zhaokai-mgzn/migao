# case_ids: MC-077
"""`git worktree` **登记表 × 磁盘不一致**：登记存在、目录不在 ⇒ `prune`/`remove` 均可能无效（issue #6235）。

## 病灶（2026-10-03 修复包 F-6219 开工第一步实测撞见；主会话已核实）

`git worktree list` **登记**了某个 worktree，但它的目录**在磁盘上不存在**：该分支被判
「已被该 worktree 占用」⇒ `git worktree add <path> <branch>` 直接
`fatal: … is already used by worktree at …`；而 `git worktree prune` 与
`git worktree remove --force` **都可能无效**。本机（git 2.54.0）实测两种顽固形态：

| 形态 | 现场构造 | `prune -v` 读数 | `remove --force` 读数 | 诊断代价 |
|---|---|---|---|---|
| **A `locked` 形态**（issue 现场同形） | 建工作区 → `worktree lock` → 删目录 | **rc=0 且什么都不删**（静默） | rc=128 `cannot remove a locked working tree` | 3~4 轮往返 |
| **B 未锁、目录消失** | 建工作区 → 删目录 | rc=0，**真会删掉**（故本单主判据用 A 取红证） | rc=128 `not a working tree` | 同上 |
| **C 目录残留、`.git` 已没** | 建工作区 → 删 `$wt/.git` | rc=0 且不动（登记照旧） | rc=128 `not a working tree` | 同上 |

⇒ 共同根因 = **一个声明没有对应的可达对象，而没有任何东西会因此变红**
（与铁律 11「声明存在 ≠ 可达」同族）。唯一有效修法 = `rm -rf .git/worktrees/<name>` + `prune`。

## 本文件判的九条（每条都带注入式红证；红证**只在 `tmp_path` 自造 fixture 上跑**，绝不碰真工作区）

| # | 判据 | 红证（注入 / 实测） |
|---|---|---|
| 1 | **旧行为红证**：形态 A 下 `git worktree add` 必须复现「被占用」失败，且 `prune`/`remove` 双双无效 | 断言逐字读数（否则第 2 条的绿可能是空断言） |
| 2 | **新行为**：`doctor` 默认**只读**判红（exit 1、逐条具名、**不动登记表**）；`doctor --heal` 自愈成功 + `add` 成功 | 见判据 1 的前后对照 |
| 3 | `add` **前置断言 + 自愈**：漂移存在时 `add` 打印将删清单 → 按白名单删除 → 复检 → 建工作区成功 | 删掉 `cmd_add` 里的断言调用 ⇒ 判据 9 当场红 |
| 4 | `rm` / `rebase` **入口断言**（类级：所有入口都过这道断言） | 同上（控制流元守卫） |
| 5 | **反向对照**：健康登记表下 `doctor` 绿（exit 0）且**登记条目一字未动**；误判 = 红 | ——（对照读数，防「为了自愈把正常条目删了」） |
| 6 | **安全护栏**：`rm -rf` 落点**只允许** `.git/worktrees/<name>`；`…/migao-wt/<name>` / `$HOME` / 本仓根 / 越界 / **软链逃逸**一部拒绝并打印原因 | 注入式：逐条候选路径真跑守卫，白名单外必须 `rc≠0` 且**一个都不删** |
| 7 | **拒绝即 fail-closed**：被拒落点不会让整体"看起来修好了" —— 漂移仍在 ⇒ 非零 | 见判据 6 的混合调用（允许 1 / 拒绝 5 ⇒ rc=1） |
| 8 | **判别力自证**：判定本体在内存构造的坏形态上判红、在对照形态上不红 | 纯函数级（不依赖仓内文件） |
| 9 | **类级元守卫**：`dev-worktree.sh` 里**每个命令函数**都必须具名出现前置断言（未走 ⇒ 红） | 从函数体里删掉调用 ⇒ 判红 |

## 覆盖不到什么（照实登记，§19.1）

- ❌ **只治「登记了但磁盘没有」一个方向**：「磁盘有、git 不认」（例如 `$wt/.git` 被人为替换成一个**别的**
  仓库的 `.git`、或 `$wt` 与 `gitdir` 指向的完全不是同一个目录）**不在**本判据的射程内 —— 那是 issue #6235
  的**观察项**（无 durable 证据、也不制造本单的红），登记在 PR body 的「未覆盖 / 存疑」里。
- ❌ **判不了「有人过去已经建好的漂移」的追溯修复**：本包拦的是**下一次**（下次 `add` 开工即自愈）；
  存量漂移要有人跑一次 `doctor --heal` —— 本包**不去**动本机任何真实工作区。
- ❌ **判定口径是「登记路径的目录 + 其中的 `.git` 是否都在」**：一个目录+`.git` 都在、但内容被换成
  别的东西的工作区会被判「健康」（git 自己也会认它）；这类形态靠 `git worktree list` 的
  `prunable` 标记，本判据不重复判它。
- ❌ 本判据守的消费点是 shell 脚本 ⇒ **登记不进** §28.2.1 的 `wiring_claims_ledger.json`
  （那个台账的判据 3 要求 `::` 左边以 `.py` 结尾）。缺口照实登记在此，本包**不放宽**那个门禁。
- ❌ 只跑定点：不跑 `verify-all.sh gate` / 全量 pytest（重活串行，见 `migao-dev-flow` §27）。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "dev-worktree.sh"
GIT = shutil.which("git")

#: 前置断言函数名（所有入口都必须调用它 —— 判据 9 的元守卫按名字扫）。
ENTRY_ASSERT_FN = "wt_registry_assert_for_entry"
GUARD_FN = "wt_registry_guard"
DOCTOR_FN = "wt_registry_doctor"
#: 必须过断言的命令函数（新增会动 worktree 存量的命令 ⇒ 必须同批加进这里）。
ENTRY_COMMANDS = ("cmd_add", "cmd_rm", "cmd_rebase")
#: **只读**命令函数（逐条写明它凭什么不过这道断言 —— 名单只许按此口径增长）。
READ_ONLY_COMMANDS = {
    "cmd_list": "只 `git worktree list` + 打印会话锁，不改任何状态",
}
#: 「旧行为」的逐字读数（git 自己的报错；不抄任何 JDK / 第三方栈帧）。
OLD_USED_BY_WORKTREE = "missing but locked worktree"
#: 新行为的可见读数（不许静默）。
HEAL_VISIBLE = "✅ 登记表 × 磁盘已一致（复检绿）"
DELETE_LIST_VISIBLE = "🧹 将删除登记条目"
DOCTOR_GREEN = "✅ 登记表 × 磁盘一致"


# ── 纯函数：控制流判定本体（可内存注入）────────────────────────────────────────
def command_function_names(src: str) -> list[str]:
    """`dev-worktree.sh` 里所有 `cmd_*()` 命令函数名（现取 ⇒ 新增命令自动进面）。"""
    return sorted(set(re.findall(r"^(cmd_[a-z0-9_]+)\(\) \{", src, flags=re.MULTILINE)))


def function_body(src: str, name: str) -> str:
    """取 shell 函数体（`name() {` → 顶格 `}`）。取不到即 fail-closed（不许静默返回空串）。"""
    start = src.find(f"\n{name}() {{\n")
    if start < 0:
        raise AssertionError(f"定位 `{name}()` 失败（fail-closed）：判据对象没了，不许当成通过")
    end = src.find("\n}\n", start)
    if end < 0:
        raise AssertionError(f"定位 `{name}()` 的结尾失败（fail-closed）")
    return src[start:end]

def executable_lines(body: str) -> list[str]:
    """去掉**注释行**与空行后的可执行行 —— 「只写在注释里」必须能被判出来。"""
    return [s for s in (raw.strip() for raw in body.splitlines()) if s and not s.startswith("#")]


def commands_missing_entry_assertion(src: str, *, include_read_only: bool = False) -> list[str]:
    """判据 9 的判定本体：每个 `cmd_*` 函数都必须有**可执行**的 `ENTRY_ASSERT_FN` 调用。

    `include_read_only=False`（默认）⇒ 只读名单里的函数不计入（它们的豁免理由写在
    `READ_ONLY_COMMANDS`，并由 `entry_commands_are_fully_covered` 双向核）。
    """
    names = command_function_names(src)
    if not names:
        return ["一个 `cmd_*()` 函数都扫不到（fail-closed：判据对象没了）"]
    scan = names if include_read_only else [n for n in names if n not in READ_ONLY_COMMANDS]
    if not scan:
        return ["待判的命令函数集合为空（fail-closed：名单把射程吃掉了）"]
    missing: list[str] = []
    for name in scan:
        body = function_body(src, name)
        if not any(ENTRY_ASSERT_FN in line and "()" not in line for line in executable_lines(body)):
            missing.append(name)
    return missing


def entry_commands_are_fully_covered(src: str) -> list[str]:
    """判据 9 的第二半：现存的每个 `cmd_*` 必须**要么**过断言、**要么**在只读名单里写明理由。

    少了 ⇒ 本判据的射程被悄悄缩窄（改个名 / 加个新命令就绕过）；多了 ⇒ 名单腐烂（陈旧登记）。
    """
    live = set(command_function_names(src))
    declared = set(ENTRY_COMMANDS)
    problems: list[str] = []
    if declared - live:
        problems.append(f"名单里有脚本中不存在的命令函数（陈旧登记）：{sorted(declared - live)}")
    unclaimed = live - declared - set(READ_ONLY_COMMANDS)
    if unclaimed:
        problems.append(
            f"脚本里有既没过断言、又没登记为只读的命令函数：{sorted(unclaimed)}"
            f" ⇒ 新增命令必须同批声明「它凭什么不过这道断言」"
        )
    stale_readonly = set(READ_ONLY_COMMANDS) - live
    if stale_readonly:
        problems.append(f"只读名单里有脚本中不存在的命令函数（陈旧登记）：{sorted(stale_readonly)}")
    return problems


# ── fixture：真 git 仓库 + 真 worktree（全部在 tmp_path 里，绝不碰真实工作区）────
def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=check, capture_output=True, text=True
    )


def build_fixture(base: Path, *, broken: str | list[str] | None = None, script_text: str | None = None) -> dict:
    """造一个真仓库 + 真 worktree（`broken` 可为单个形态或形态列表 —— 每个额外形态用 `feat-y`/`feat-z`）。

    `broken=None` ⇒ 健康；`"locked"` / `"gone"`（形态 A/B）；`"stale-dir"`（形态 C）。
    `script_text` 非 None ⇒ 用**注入变体**写入 fixture（红证的唯一入口）。
    """
    repo = base / "repo"
    (repo / "scripts").mkdir(parents=True)
    live = SCRIPT.read_text(encoding="utf-8")
    text = live if script_text is None else script_text
    if script_text is not None and text == live:
        raise AssertionError("注入没生效（源码与现役逐字相同）⇒ 下面的判红会变成空断言")
    script = repo / "scripts" / "dev-worktree.sh"
    script.write_text(text, encoding="utf-8")
    script.chmod(0o755)
    script_src = repo / "scripts" / "dev-worktree.sh"
    # ⚠️ fixture 里不写任何 shell 配方/文档（保持语料干净）
    (repo / "README.md").write_text("init\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-qm", "init")

    wt_base = base / "wtbase"
    wt = wt_base / "feat-x"
    _git(repo, "worktree", "add", "-q", "-b", "feat-x", str(wt))

    raw_shapes = [] if broken is None else ([broken] if isinstance(broken, str) else list(broken))
    shapes = ["ok" if s is None else s for s in raw_shapes]  # `None` = 该受害者保持健康（对照）
    extras: list[Path] = []
    for i, shape in enumerate(shapes):
        if i == 0:
            victim, branch = wt, "feat-x"
        else:
            branch = f"feat-{'yz'[i - 1]}" if i - 1 < 2 else f"feat-{i}"
            victim = wt_base / branch
            add_plain_worktree(repo, victim, branch)
            extras.append(victim)
        if shape == "locked":
            _git(repo, "worktree", "lock", "--reason", "stale session", str(victim))
            shutil.rmtree(victim)
        elif shape == "gone":
            shutil.rmtree(victim)
        elif shape == "stale-dir":
            # worktree 里的 `.git` 是一个**指针文件**（不是目录）⇒ 只能 unlink；
            # 其余内容**留着**：模拟"目录残留 + 里面有别人的东西"
            (victim / ".git").unlink()
        elif shape == "stale-dir-empty":
            # 同上，但残留目录是**空的**（`rmdir` 能收掉）⇒ 自愈后 add 可以一路走通
            (victim / ".git").unlink()
            for child in victim.iterdir():
                shutil.rmtree(child) if child.is_dir() else child.unlink()
        elif shape == "ok":
            pass  # 对照：这一条保持健康
        else:
            raise AssertionError(f"未知的 fixture 形态：{shape!r}")

    return {"repo": repo, "wt": wt, "base": base, "script": script_src, "broken": broken,
            "extras": extras}


def run_script(fx: dict, *args: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    """跑 fixture 里的**真脚本**（副本与原脚本逐字节相同）。"""
    env = dict(os.environ, MIGAO_WT_BASE=str(fx["base"] / "wtbase"))
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", str(fx["script"]), *args],
        capture_output=True, text=True, env=env, timeout=300, cwd=str(fx["repo"]),
    )


def registry_names(repo: Path) -> list[str]:
    reg = repo / ".git" / "worktrees"
    return sorted(p.name for p in reg.iterdir()) if reg.is_dir() else []


def add_plain_worktree(repo: Path, wt: Path, branch: str) -> None:
    """再造一个**健康**的 worktree（用来取「另有漂移时入口仍正常干活」的对照读数）。"""
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q", "-b", branch, str(wt)],
        check=True, capture_output=True,
    )


def add_old_style(repo: Path, path: Path, branch: str) -> subprocess.CompletedProcess:
    """**旧行为**：直接 `git worktree add`（不走本脚本）—— 用来钉住「被占用」这条读数。"""
    return subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", str(path), branch],
        capture_output=True, text=True,
    )


# ── 判据 1：旧行为红证（先证明"判据不是空断言"）────────────────────────────────
def test_old_behaviour_reproduces_the_reported_symptom(tmp_path: Path) -> None:
    """判据 1：形态 A 下 —— `add` 被占用拒绝、`prune` 静默无效、`remove --force` 也无效。

    这三条读数都是**git 自己**打出来的（本判据不复制任何 git 逻辑），三条缺一不可：
    若 `prune` 其实有效，那本单要治的形态就不成立 ⇒ 判据会当场红，而不是"绿着骗人"。
    """
    assert GIT, "本机没有 git，无法取证（fail-closed）"
    fx = build_fixture(tmp_path, broken="locked")
    assert registry_names(fx["repo"]) == ["feat-x"], "fixture 没造出登记条目（fail-closed）"

    old = add_old_style(fx["repo"], fx["wt"], "feat-x")
    assert old.returncode != 0, f"旧行为下 add 竟然成功了？{old.stdout!r} {old.stderr!r}"
    assert OLD_USED_BY_WORKTREE in old.stderr, (
        f"旧行为读数与 issue #6235 的现场不同形（期望含 {OLD_USED_BY_WORKTREE!r}）：{old.stderr!r}"
    )

    prune = _git(fx["repo"], "worktree", "prune", "-v")
    assert prune.returncode == 0, f"prune 竟然非零退出：{prune.stderr!r}"
    assert prune.stdout.strip() == "", (
        f"prune 竟然有动作（{prune.stdout!r}）⇒ 本单的「prune 无效」形态不成立，判据 2 会变成空断言"
    )
    assert registry_names(fx["repo"]) == ["feat-x"], "prune 竟然删掉了登记条目 ⇒ 形态不成立"

    rm = _git(fx["repo"], "worktree", "remove", str(fx["wt"]), "--force", check=False)
    assert rm.returncode != 0, f"remove --force 竟然成功了？（issue 现场是失败）：{rm.stdout!r}"
    assert "not a working tree" in rm.stderr or "locked" in rm.stderr, (
        f"remove --force 的失败形态与现场不同：{rm.stderr!r}"
    )


# ── 判据 2 / 5：doctor 只读判红 + 自愈 + 反向对照（登记表一字未动）──────────────
def test_doctor_is_read_only_and_red_on_drift(tmp_path: Path) -> None:
    """判据 2（前半）：`doctor` 默认只读 —— 判红（exit 1）、**逐条具名**、登记表**一字未动**。"""
    for shape in ("locked", "gone", "stale-dir"):
        fx = build_fixture(tmp_path / shape, broken=shape)
        before = sorted(p.name for p in (fx["repo"] / ".git" / "worktrees").rglob("*"))
        assert before, f"[{shape}] fixture 没造出登记条目（fail-closed）"

        proc = run_script(fx, "doctor")
        assert proc.returncode == 1, (
            f"[{shape}] doctor 应当判红 exit=1，实得 {proc.returncode}：{proc.stdout!r} {proc.stderr!r}"
        )
        assert "feat-x" in proc.stdout, f"[{shape}] 漂移没有被**具名**报出：{proc.stdout!r}"
        assert str(fx["wt"]) in proc.stdout, f"[{shape}] 漂移没有带上登记路径：{proc.stdout!r}"
        after = sorted(p.name for p in (fx["repo"] / ".git" / "worktrees").rglob("*"))
        assert after == before, f"[{shape}] 只读的 doctor **动了**登记表：{before} → {after}"


def test_doctor_heal_repairs_and_unblocks_add(tmp_path: Path) -> None:
    """判据 2（后半）：`doctor --heal` 自愈成功（可见"删了什么"）⇒ 随后 `worktree add` 成功。

    形态 A/B（登记目录整个消失）+ 形态 C 的**空残留**变体：三种都必须自愈到"能再建工作区"。
    """
    for shape in ("locked", "gone", "stale-dir-empty"):
        fx = build_fixture(tmp_path / shape, broken=shape)
        proc = run_script(fx, "doctor", "--heal")
        assert proc.returncode == 0, (
            f"[{shape}] doctor --heal 未成功（{proc.returncode}）：{proc.stdout!r} {proc.stderr!r}"
        )
        assert DELETE_LIST_VISIBLE in proc.stdout, (
            f"[{shape}] 删除前没有**打印将删清单**（issue #6235 / 铁律 10 的可审计要求）：{proc.stdout!r}"
        )
        assert HEAL_VISIBLE in proc.stdout, f"[{shape}] 没有复检绿的读数（不许静默）：{proc.stdout!r}"
        assert registry_names(fx["repo"]) == [], f"[{shape}] 登记条目没被清掉：{registry_names(fx['repo'])}"

        again = add_old_style(fx["repo"], fx["wt"], "feat-x")
        assert again.returncode == 0, f"[{shape}] 自愈后 add 仍失败：{again.stdout!r} {again.stderr!r}"
        assert fx["wt"].is_dir(), f"[{shape}] 自愈后工作区目录不存在：{fx['wt']}"


def test_nonempty_residue_is_named_and_never_deleted(tmp_path: Path) -> None:
    """判据 2（形态 C 的另一半）：登记目录**还在、里面有别人的文件** ⇒ 只清登记条目 + **具名交代残留**、
    绝不替操作者删那个非空目录（"显式入参"的人工出口）。

    这一步不是洁癖：这类残留目录里完全可能有别人未提交的改动（本机 2026-10-03 现场就有
    `pr-body-*.md` 之类躺在里面）⇒ 自动 `rm -rf` 它会直接吃掉别人的工作。
    """
    fx = build_fixture(tmp_path, broken="stale-dir")
    keep = fx["wt"] / "README.md"
    assert keep.is_file(), "fixture 没造出非空残留（fail-closed）"
    before = keep.read_text(encoding="utf-8")

    proc = run_script(fx, "doctor", "--heal")
    assert proc.returncode == 0, f"doctor --heal 未成功：{proc.stdout!r} {proc.stderr!r}"
    assert registry_names(fx["repo"]) == [], f"登记条目没被清掉：{registry_names(fx['repo'])}"
    assert "残留还在" in proc.stdout, f"目录残留没有被可见地交代（不许静默）：{proc.stdout!r}"
    assert f"rm -rf -- \"{fx['wt']}\"" in proc.stdout, (
        f"没有给出**显式入参**的手工出口（铁律：删除类动作不做无人值守）：{proc.stdout!r}"
    )
    assert keep.is_file() and keep.read_text(encoding="utf-8") == before, (
        "残留目录里的文件被删了 —— 那正是本判据要防的（别人的未提交改动）"
    )


def test_healthy_registry_is_green_and_untouched(tmp_path: Path) -> None:
    """判据 5（**反向对照**）：健康登记表 ⇒ `doctor` 绿（exit 0）且登记条目**一个都没动**。"""
    fx = build_fixture(tmp_path, broken=None)
    gd = fx["repo"] / ".git" / "worktrees" / "feat-x" / "gitdir"
    before = gd.read_text(encoding="utf-8")

    proc = run_script(fx, "doctor")
    assert proc.returncode == 0, f"健康形态被判红（误判）：{proc.stdout!r} {proc.stderr!r}"
    assert DOCTOR_GREEN in proc.stdout, f"缺绿色读数：{proc.stdout!r}"
    assert registry_names(fx["repo"]) == ["feat-x"], "健康形态的登记条目被动了"
    assert gd.read_text(encoding="utf-8") == before, "健康形态的 gitdir 被改了"
    assert fx["wt"].is_dir(), "健康形态的工作区目录被删了 —— **这是最危险的误判**"


# ── 判据 3 / 4：入口前置断言（`add` 自愈成功；`rm`/`rebase` 也过这道断言）────────
def test_add_preflight_self_heals_then_creates_the_worktree(tmp_path: Path) -> None:
    """判据 3：漂移存在时 `add` —— 前置自查判红 → 自愈（打印将删清单）→ 复检 → 工作区就绪。"""
    fx = build_fixture(tmp_path, broken="locked")
    proc = run_script(fx, "add", "feat-x")

    assert proc.returncode == 0, f"add 未成功：{proc.stdout!r} {proc.stderr!r}"
    assert "前置自查" in proc.stdout, f"add 没有走这道断言（issue #6235 的接线）：{proc.stdout!r}"
    assert DELETE_LIST_VISIBLE in proc.stdout, f"自愈没打印将删清单：{proc.stdout!r}"
    assert HEAL_VISIBLE in proc.stdout, f"自愈后没有复检绿的读数：{proc.stdout!r}"
    assert "工作区就绪" in proc.stdout, f"add 没走到最后（自愈把 add 弄坏了？）：{proc.stdout!r}"
    assert fx["wt"].is_dir(), f"工作区没建出来：{fx['wt']}"
    assert registry_names(fx["repo"]) == ["feat-x"], "登记条目没有重建（add 应当重新登记）"


def test_rm_entry_also_goes_through_the_assertion(tmp_path: Path) -> None:
    """判据 4（`rm`）：另有漂移时 `rm <健康工作区>` 先自愈**再**动手，本操作照常完成。

    形态 = `feat-x`（健康，本次要删的）+ `feat-y`（形态 A 漂移，别人的包留下的）：
    断言必须在**解析目标之前**跑（漂移会把 `worktree list` 的解析弄含糊），且自愈只许动 `feat-y`。
    """
    fx = build_fixture(tmp_path, broken=[None, "locked"])
    assert registry_names(fx["repo"]) == ["feat-x", "feat-y"], "fixture 没造出两个条目（fail-closed）"

    proc = run_script(fx, "rm", "feat-x")
    assert proc.returncode == 0, f"自愈后 rm 仍失败：{proc.stdout!r} {proc.stderr!r}"
    assert "前置自查" in proc.stdout, f"rm 没有走这道断言：{proc.stdout!r}"
    assert HEAL_VISIBLE in proc.stdout, f"rm 的前置自愈没有复检绿：{proc.stdout!r}"
    assert "已移除工作区" in proc.stdout, f"rm 没走到最后：{proc.stdout!r}"
    assert registry_names(fx["repo"]) == [], f"登记条目仍在：{registry_names(fx['repo'])}"
    assert not fx["wt"].exists(), f"目标工作区目录仍在：{fx['wt']}"


def test_rebase_entry_also_goes_through_the_assertion(tmp_path: Path) -> None:
    """判据 4（`rebase`）：断言排在 rebase 之前（漂移时给出可行动读数，而不是 git 的隐晦报错）。"""
    fx = build_fixture(tmp_path, broken="locked")
    proc = run_script(fx, "rebase", "feat-x")

    assert "前置自查" in proc.stdout, f"rebase 没有走这道断言：{proc.stdout!r}"
    assert HEAL_VISIBLE in proc.stdout, f"rebase 的前置自愈没有复检绿：{proc.stdout!r}"


# ── 判据 6 / 7：安全护栏 —— 白名单外的落点一律拒绝 ──────────────────────────────
GUARD_DRIVER = """set -u
PY_BIN="$(command -v python3.11 || command -v python3)"
WT_REGISTRY_DIR="$REPO/.git/worktrees"
export PY_BIN WT_REGISTRY_DIR
eval "$(sed -n '/^%(fn)s() {/,/^}/p' "$SCRIPT")"
%(fn)s %(args)s
echo "GUARD_RC=$?"
"""


def run_guard(fx: dict, base: Path, *paths: str, allow_empty: str = "false") -> subprocess.CompletedProcess:
    """跑**真守卫**（从现役脚本里抽出的 `wt_registry_guard` 函数体），逐条给候选落点。"""
    quoted = " ".join("'" + p.replace("'", "'\\''") + "'" for p in paths)
    driver = base / "guard-driver.sh"
    driver.write_text(
        GUARD_DRIVER % {"fn": GUARD_FN, "args": f'{allow_empty} {quoted}'}, encoding="utf-8"
    )
    env = dict(os.environ, SCRIPT=str(fx["script"]), REPO=str(fx["repo"]))
    return subprocess.run(
        ["bash", str(driver)], capture_output=True, text=True, env=env, timeout=120, cwd=str(fx["repo"])
    )


def test_guard_rejects_every_allowlist_outside_landing_zone(tmp_path: Path) -> None:
    """判据 6 / 7（**注入式红证**）：白名单外的落点逐个拒绝、打印原因，且整体判红（fail-closed）。

    覆盖 issue #6235 点名的每一类：`…/migao-wt/<name>`、`…/migao-dev/<name>`、`$HOME` 前缀、
    本仓 worktree 根目录、`..` 越界、以及**经软链逃逸**的落点（`rm -rf` 不跟随软链，但守卫必须
    在它之前 fail-closed）。
    """
    fx = build_fixture(tmp_path, broken="locked")
    home = Path(os.path.expanduser("~")).resolve()
    escape_target = tmp_path / "escape-target"
    escape_target.mkdir()

    # 软链逃逸形态：把登记条目换成一个**指向仓外**的软链（删除若非 fail-closed，落点就在仓外）
    escape_link = fx["repo"] / ".git" / "worktrees" / "escape"
    os.symlink(escape_target, escape_link)

    outsiders = [
        str(tmp_path / "migao-wt" / "feat-x"),
        str(tmp_path / "migao-dev" / "feat-x"),
        str(home),
        str(home / "migao-wt" / "feat-x"),
        str(fx["repo"]),
        str(fx["repo"] / ".git"),
        str(fx["repo"] / ".git" / "worktrees" / ".." / ".." / "outside"),
        str(escape_link),
    ]
    proc = run_guard(fx, tmp_path, *outsiders)
    assert proc.returncode == 0 or "GUARD_RC=" in proc.stdout, f"守卫没跑起来：{proc.stderr!r}"
    assert "GUARD_RC=1" in proc.stdout, (
        f"白名单外的落点**没有**让守卫判红（fail-closed 破了）：{proc.stdout!r}"
    )
    for p in outsiders:
        assert f"⛔ 拒绝删除：{p}" in proc.stdout, f"落点没被逐条具名拒绝：{p} —— {proc.stdout!r}"
    assert "原因：" in proc.stdout, "拒绝时没有打印原因（issue #6235 要求）"
    # 一个字都不许删（软链目标必须原样在）
    assert escape_link.is_symlink(), "软链落点被删了（守卫没拦住）"
    assert escape_target.is_dir() and not any(escape_target.iterdir()), "软链目标被动了"


def test_guard_allows_only_the_registry_landing_zone(tmp_path: Path) -> None:
    """判据 6（正向对照）：**只允许** `.git/worktrees/<name>`；混入白名单外落点 ⇒ 整体仍判红。"""
    fx = build_fixture(tmp_path, broken="locked")
    reg_entry = fx["repo"] / ".git" / "worktrees" / "feat-x"

    only_ok = run_guard(fx, tmp_path, str(reg_entry))
    assert "GUARD_RC=0" in only_ok.stdout, f"白名单内的落点竟然被拒：{only_ok.stdout!r}"
    assert "✅ 允许删除" in only_ok.stdout, f"缺允许读数：{only_ok.stdout!r}"
    assert reg_entry.is_dir(), "守卫只是判定，不该动手删（删除由调用方在判定后做）"

    mixed = run_guard(fx, tmp_path, str(reg_entry), str(tmp_path / "migao-wt" / "x"))
    assert "GUARD_RC=1" in mixed.stdout, (
        f"混合调用（1 允许 + 1 越界）竟然判绿 ⇒ fail-closed 破了：{mixed.stdout!r}"
    )
    assert "允许 1 / 拒绝 1" in mixed.stdout, f"汇总读数不对：{mixed.stdout!r}"


# ── 判据 8 / 9：判定本体的判别力自证 + 类级元守卫 ────────────────────────────────
def test_static_judgement_has_teeth_in_memory() -> None:
    """判据 8（判别力自证）：控制流判定本体在内存构造的坏形态上判红、对照形态不红。"""
    src = SCRIPT.read_text(encoding="utf-8")
    assert commands_missing_entry_assertion(src) == [], (
        f"现役脚本里有命令函数没走前置断言：{commands_missing_entry_assertion(src)}"
    )
    assert entry_commands_are_fully_covered(src) == [], entry_commands_are_fully_covered(src)

    body = function_body(src, "cmd_add")
    call = f'{ENTRY_ASSERT_FN} "add ${{branch}}"'
    assert call in body, f"注入无从构造：`cmd_add` 里找不到断言调用行（fail-closed）：{body[:400]!r}"
    dropped = src.replace(body, body.replace(call, ""), 1)
    assert dropped != src, "变异没生效（删掉断言调用）⇒ 下面会变成空断言"
    assert "cmd_add" in commands_missing_entry_assertion(dropped)

    commented = src.replace(body, body.replace(call, "# " + call), 1)
    assert commented != src, "变异没生效（把断言改成注释）"
    assert "cmd_add" in commands_missing_entry_assertion(commented)

    for fn in ENTRY_COMMANDS:
        b = function_body(src, fn)
        hit = [l for l in executable_lines(b) if ENTRY_ASSERT_FN in l and "()" not in l]
        assert hit, f"`{fn}` 里找不到可执行的断言调用（fail-closed）：{b[:200]!r}"
        broken = src.replace(b, b.replace(hit[0], "# " + hit[0]), 1)
        assert fn in commands_missing_entry_assertion(broken), f"`{fn}` 的注入变体没判红"

    # 名单腐烂的三侧都要红：新增一个没过断言的命令函数 / 把一个只读函数改名（⇒ 陈旧登记）/
    # 待判集合被名单吃空（fail-closed）
    ghost_src = src.replace("\ncmd_list() {\n", "\ncmd_ghost() {\n  echo ghost\n}\n\ncmd_list() {\n", 1)
    assert ghost_src != src, "变异没生效（插入幽灵命令函数）"
    assert "cmd_ghost" in commands_missing_entry_assertion(ghost_src), "新增的未断言命令竟然判绿"
    renamed = src.replace("cmd_list", "cmd_wt_list")
    assert renamed != src, "变异没生效（命令函数改名）"
    assert entry_commands_are_fully_covered(renamed) != [], "只读名单陈旧竟然判绿"
    single = "\ncmd_ghost() {\n  :\n}\n"
    assert commands_missing_entry_assertion(single) == ["cmd_ghost"], (
        "单函数语料（幽灵命令）应当判红"
    )
    try:
        function_body(single, "cmd_absent")
    except AssertionError as exc:
        assert "cmd_absent" in str(exc), (
            f"定位不到函数时报出的错必须**具名**（fail-closed 且可归因）：{exc}"
        )
    else:
        raise AssertionError("定位不到函数时必须 fail-closed 抛错，不许静默返回空串")


def test_the_guarded_consumption_points_resolve() -> None:
    """判据 9 的坐标自证：被守的符号必须在**真实文件**里逐字可解析（摘掉 ⇒ 判据当场红）。"""
    text = SCRIPT.read_text(encoding="utf-8")
    for sym in (ENTRY_ASSERT_FN, GUARD_FN, DOCTOR_FN, "_wt_registry_scan"):
        assert f"\n{sym}() {{\n" in text, f"消费点解析不到：scripts/dev-worktree.sh::{sym}"
    assert "\n  doctor)\n" in text, "`doctor` 子命令没接线（脚本的 case 分派里找不到它）"
