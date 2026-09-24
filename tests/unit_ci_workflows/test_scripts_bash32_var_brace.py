# case_ids: MC-012
"""`scripts/**/*.sh` 里 `$VAR` 紧跟非 ASCII 字符必须写成 `${VAR}`（issue #5260；承 #5241 的类级锁）。

## 病灶（本机 macOS bash 3.2.57 实测原文，可复算）

    $ /bin/bash -c 'set -u; p=/tmp; echo "v: $p（x）"'; echo "exit=$?"
    /bin/bash: p<0xEF>: unbound variable
    exit=127
    $ /bin/bash -c 'set -u; p=/tmp; echo "v: ${p}（x）"'
    v: /tmp（x）

bash 3.2 把变量名后紧跟的非 ASCII **字节并进变量名** ⇒ `set -u` 下取到未定义变量 ⇒ 脚本当场死。
要害不是排版：同族两处都长在**报错分支**里 ⇒ 走到那里的人拿到的是 `unbound variable`，
而**可读文案就在同一行**：

    $ bash scripts/sync-main.sh --bogus
    scripts/sync-main.sh: line 68: arg<0xEF>: unbound variable     # 「❌ 未知参数: …」根本没机会打印
    $ ./scripts/batch-integrate-check.sh <branch> <pr>
    ... stranding-check exit=$SC_RC：缺 gh / 缺网络 ... —— 不许当通过   # 这句恰是关键告知

## 三条判据（各自能单独变红；红证见各测试 docstring）

| # | 判据 | 红证（改回坏形态 ⇒ 必红） |
|---|---|---|
| 1 | `scripts/**/*.sh` 的**代码面**（剥注释 + 屏蔽单引号字面量）不得出现 `$VAR` 紧跟非 ASCII | 把任一 `${VAR}` 改回 `$VAR` |
| 2 | 注释 / 单引号字面量里的同类文本**不得**判红（负例，防假红） | 只加一条注释含该形态 ⇒ 必须绿 |
| 3 | **行为级**：`bash scripts/sync-main.sh --bogus` 必须打印「未知参数」+ exit 1，且**不得**出现 `unbound variable` | 改回 `$arg（` ⇒ 必红 |

判据 3 是承重件（行为级比静态扫描硬）；判据 1 是「防新增」的类级扫描 —— #5241 的锁只锁了它自己
那个文件，本文件把覆盖面补到 `scripts/**`（issue 正文点名的两处存量随之被钉住）。

## 有意不做的（照实登记，**不是**「已覆盖」）

- **不**扫 `scripts/**` 之外的 shell（issue 的判据只到 `scripts/**/*.sh`）：`.github/scripts/**` 等
  本 PR 实测**零命中**，但本文件**不**把它钉成判据 —— 那面将来长出同族形态**不会有东西变红**。
- **不**模拟 heredoc 正文（`<<'EOF'` 里的 `$VAR` 不展开）：本 PR 实测 `scripts/**` 零命中该形态。
  ⇒ 若将来 heredoc 正文里写 `$VAR`+中文，本判据会**假红**（偏保守，不吞真判据）。
- **未改** `tests/unit_ci_workflows/test_ui_smoke_worktree_deps.py` 里「另有两处同族存量在别的脚本里」
  这句 —— 本 PR 把那两处修掉后它**已经过期**。按文件所有权（#5241 那个包的文件）本包**不越界**改动，
  在此显式登记，留待集成方决定是否另开小单。
- 判据 3 的**判别力依赖宿主 bash**：只有 bash 3.2 会把非 ASCII 并进变量名（bash 5 已改掉该语义）。
  宿主不可复现时行为腿退化为「该分支必须是 `${arg}`」的形态断言并打 warning，
  **不静默变成「绿了但没判」**（见判别力自证那条）。
"""
import re
import shutil
import subprocess
import warnings
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
SYNC_MAIN = SCRIPTS_DIR / "sync-main.sh"
BATCH_INTEGRATE = SCRIPTS_DIR / "batch-integrate-check.sh"

# 与 #5241 的类级锁同一个形态：`$NAME` 后**紧跟**一个非 ASCII 字节（`${NAME}` 合法，不命中）。
_UNBRACED_MULTIBYTE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)([^\x00-\x7F])")

# shell 里「词首」的元字符：`#` 只在词首才是注释开始（`a#b` 是字面量）。
_WORD_START = " \t\n;&|()<>"

_BASH = shutil.which("bash") or "/bin/bash"


def _code_face(src: str) -> str:
    """剥掉**注释**、并屏蔽**单引号字面量**后的代码面（逐字符等长替换 ⇒ 行号可定位）。

    为什么不能只做「整行以 `#` 开头」（两条都是本仓教训）：
      · **注释**：本仓已有 3 个脚本在注释里**讲解这个坑本身**（`$path（` 就是那行例子）⇒
        不剥注释就是「判据被自己的文案喂红」；行内注释同理（`echo ok  # 别写 $x（`）。
      · **单引号字面量**：`'$x（'` 里的 `$` **不展开**，是纯文本 ⇒ 判它红就是假红。
    **双引号不屏蔽** —— `"… $arg（…"` 里的 `$arg` 是**真展开**，本次两处病灶都长在双引号里。
    """
    out: list[str] = []
    state = ""  # ""=普通 / "'"=单引号 / '"'=双引号
    at_word_start = True
    i, n = 0, len(src)
    while i < n:
        ch = src[i]
        if state == "'":
            if ch == "'":
                state = ""
                at_word_start = False
                out.append("'")
            else:
                out.append("\n" if ch == "\n" else " ")  # 屏蔽：保长度、保行号
            i += 1
            continue
        if state == '"':
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(src[i + 1])
                i += 2
                continue
            if ch == '"':
                state = ""
                at_word_start = False
            i += 1
            continue
        if ch == "#" and at_word_start:
            while i < n and src[i] != "\n":
                out.append(" ")
                i += 1
            continue
        if ch == "\\" and i + 1 < n:
            out.append(ch)
            out.append(src[i + 1])
            at_word_start = False
            i += 2
            continue
        if ch == "'":
            state = "'"
        elif ch == '"':
            state = '"'
        out.append(ch)
        at_word_start = ch in _WORD_START
        i += 1
    return "".join(out)


def find_unbraced_var_before_non_ascii(src: str) -> list[str]:
    """→ `["第 N 行 $VAR<X>", …]`（只看代码面；注释与单引号字面量不算）。"""
    code = _code_face(src)
    return [
        f"第 {line_no} 行 ${m.group(1)}{m.group(2)}"
        for line_no, ln in enumerate(code.splitlines(), 1)
        for m in _UNBRACED_MULTIBYTE.finditer(ln)
    ]


def _run_sync_main(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [_BASH, str(script), *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=60,
    )


def _host_bash_merges_multibyte_into_var_name() -> bool:
    """宿主 bash 是否复现 bash 3.2 的「非 ASCII 字节并入变量名」语义（判据 3 行为腿的判别力前提）。"""
    r = subprocess.run(
        [_BASH, "-c", 'set -u; p=/tmp; echo "v: $p（x）"'],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
    )
    return r.returncode != 0 and "unbound variable" in (r.stderr + r.stdout)


def test_repo_scripts_code_face_has_no_unbraced_var_before_non_ascii():
    """判据 1 + 2：`scripts/**/*.sh` 的**代码面**零命中（注释不参与判定）。

    红证：把 `scripts/sync-main.sh` 未知参数分支或 `scripts/batch-integrate-check.sh` 的
    `stranding-check exit=` 文案里的 `${VAR}` 改回 `$VAR` ⇒ 本测试必红（原始读数见 PR body）。
    """
    files = sorted(SCRIPTS_DIR.rglob("*.sh"))
    rel = {p.relative_to(REPO_ROOT).as_posix() for p in files}
    # fail-closed：扫描集为空 / 缩小到不含病灶文件 ⇒ 判据恒绿，比没有判据更坏。
    assert files, f"扫描集为空（{SCRIPTS_DIR} 下没有 *.sh）—— 判据会恒绿"
    named = {"scripts/sync-main.sh", "scripts/batch-integrate-check.sh"}
    assert named <= rel, f"扫描集必须覆盖 issue 点名的两处，实际缺：{sorted(named - rel)}"
    bad = [
        f"{p.relative_to(REPO_ROOT).as_posix()} {hit}"
        for p in files
        for hit in find_unbraced_var_before_non_ascii(p.read_text(encoding="utf-8"))
    ]
    assert bad == [], (
        "这些变量展开后紧跟非 ASCII 字符（macOS bash 3.2 会把那个字节并进变量名 ⇒ `set -u` 下"
        f"unbound variable），必须写成 ${{VAR}}：{bad}"
    )


def test_scanner_discriminates_code_from_comment_and_literal_only():
    """判据 1/2 的**判别力自证**（缺它 ⇒ 上面那条可能恒空，绿了但没判）。

    红证：代码面（含双引号内部 —— 病灶正在双引号里）出现该形态 ⇒ 必须命中；
    负例（防假红）：整行注释、行内注释、单引号字面量 ⇒ 必须零命中。
    """
    assert find_unbraced_var_before_non_ascii('echo "❌ 未知参数: $arg（支持）" >&2') == ["第 1 行 $arg（"]
    # 同形态写成 ${arg} ⇒ 合法（#5241 修法 / 本 PR 形态）
    assert find_unbraced_var_before_non_ascii('echo "❌ 未知参数: ${arg}（支持）" >&2') == []
    # 负例 ①整行注释 ②行内注释 ③单引号字面量（后者 `$` 不展开，是纯文本）
    assert find_unbraced_var_before_non_ascii("# 讲解：`$path（` 会被并成变量名\n") == []
    assert find_unbraced_var_before_non_ascii("echo ok  # 别写 $x（\n") == []
    assert find_unbraced_var_before_non_ascii("echo '$x（' 是纯文本\n") == []
    # 负例 ④`${VAR}` 之后跟非 ASCII（合法形态，不是漏网）
    assert find_unbraced_var_before_non_ascii('echo "${p}（x）"\n') == []
    # 行号可定位（报告里指得出是哪一行）
    assert find_unbraced_var_before_non_ascii("echo 1\necho $p（\n")[0].startswith("第 2 行 ")


def test_sync_main_unknown_arg_branch_prints_readable_error_not_unbound_variable():
    """判据 3（**承重件**，行为级）：`bash scripts/sync-main.sh --bogus` 必须打印「未知参数」+ exit 1。

    红证（本机 bash 3.2 实测）：把该分支的 `${arg}` 改回 `$arg（` ⇒
    输出变成 `scripts/sync-main.sh: line 68: arg<0xEF>: unbound variable`，
    **看不到**「未知参数」⇒ 本测试必红。该红证由下一条测试在脚本**副本**上自动复跑。
    """
    r = _run_sync_main(SYNC_MAIN, "--bogus")
    combined = r.stdout + r.stderr
    assert r.returncode == 1, f"未知参数分支必须 exit 1，实际 {r.returncode}；输出：{combined!r}"
    assert "未知参数" in combined, f"必须打印可读的「未知参数」文案，实际输出：{combined!r}"
    assert "unbound variable" not in combined, (
        f"错误路径本身坏掉（bash 3.2 把非 ASCII 并进变量名 ⇒ unbound variable）：{combined!r}"
    )


def test_behavioral_leg_reproduces_unbound_variable_on_mutated_copy(tmp_path):
    """判据 3 的**判别力自证**：把坏形态注入脚本副本，行为腿必须在**同一宿主**上抓到它。

    · 宿主复现 3.2 语义（macOS 自带 bash 3.2）⇒ 注入 `${arg}` → `$arg` 后**必须**打印
      `unbound variable` —— 否则上一条就是「恒绿的空判据」；
    · 宿主不复现（bash ≥5 已改掉该语义，GitHub runner 即此）⇒ 行为腿**无法判别**，
      但**不静默放行**：退化为「未知参数分支必须是 `${arg}`」的形态断言 + 显式 warning
      （「没跑」要长得像「没跑」，见 `migao-dev-flow` §1 口径）。
    """
    src = SYNC_MAIN.read_text(encoding="utf-8")
    needle = 'echo "❌ 未知参数: ${arg}（'
    assert needle in src, f"定位未知参数分支失败（fail-closed，别静默跳过）：找不到 {needle!r}"
    mutated = tmp_path / "sync-main-mutated.sh"
    mutated.write_text(src.replace(needle, 'echo "❌ 未知参数: $arg（'), encoding="utf-8")

    if _host_bash_merges_multibyte_into_var_name():
        r = _run_sync_main(mutated, "--bogus")
        combined = r.stdout + r.stderr
        assert "unbound variable" in combined, (
            f"注入坏形态后行为腿**没能**变红 ⇒ 上一条判据是空判据：{combined!r}"
        )
        assert "未知参数" not in combined, f"坏形态下不应还能打印可读文案：{combined!r}"
        return

    branch = [ln for ln in _code_face(src).splitlines() if "未知参数" in ln]
    assert branch and "${arg}" in branch[0], f"未知参数分支必须用 ${{arg}} 包裹，实际：{branch}"
    warnings.warn(
        f"宿主 bash（{_BASH}）不复现 bash 3.2 的「非 ASCII 并入变量名」语义 ⇒ 判据 3 的行为腿"
        "在本宿主上**不可判别**，已退化为「未知参数分支必须 ${arg}」的形态断言"
        "（macOS 自带 bash 3.2 上行为腿满功率；CI runner 为 bash ≥5，属此分支）",
        stacklevel=1,
    )


def test_scripts_keep_env_bash_shebang_no_bash5_dependency():
    """反绕过锁：本单修法是 `${VAR}` 显式包裹，**不是**引入 bash 5 依赖假设（issue「不做」条）。

    红证：把任一 shebang 改成 `/opt/homebrew/bin/bash` 之类的**具体 bash 5 路径** ⇒ 必红。
    """
    wrong = [
        p.relative_to(REPO_ROOT).as_posix()
        for p in (SYNC_MAIN, BATCH_INTEGRATE)
        if p.read_text(encoding="utf-8").splitlines()[:1] != ["#!/usr/bin/env bash"]
    ]
    assert wrong == [], f"这些脚本的 shebang 不再是 `#!/usr/bin/env bash`（引入解释器依赖假设）：{wrong}"