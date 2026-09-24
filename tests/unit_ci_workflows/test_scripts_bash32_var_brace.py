# case_ids: MC-012
"""全仓受控 `*.sh` 里 `$VAR` 紧跟非 ASCII 字符必须写成 `${VAR}`（issue #5260 → **#5284**；承 #5241 的类级锁）。

## 病灶（本机 macOS bash 3.2.57 实测原文，可复算）

    $ /bin/bash -c 'set -u; p=/tmp; echo "v: $p（x）"'; echo "exit=$?"
    /bin/bash: p<0xEF>: unbound variable
    exit=127
    $ /bin/bash -c 'set -u; p=/tmp; echo "v: ${p}（x）"'
    v: /tmp（x）

bash 3.2 把变量名后紧跟的非 ASCII **字节并进变量名** ⇒ `set -u` 下取到未定义变量 ⇒ 脚本当场死。
要害不是排版：同族全部长在**报错/告警分支**里 ⇒ 走到那里的人拿到的是 `unbound variable`，
而**可读文案就在同一行**：

    $ bash scripts/sync-main.sh --bogus
    scripts/sync-main.sh: line 68: arg<0xEF>: unbound variable     # 「❌ 未知参数: …」根本没机会打印
    $ ./check-ui-regression.sh      # 工作区某关键 UI 文件的 neutral 少于 origin/main 时
    check-ui-regression.sh: line 73: f<0xEF>: unbound variable     # 「⚠️ UI token 减少: …」没机会打印

## 射程是**结构化声明**，不是一句文案（这正是 #5284 的缺口）

射程由模块级常量 `GUARD_SCOPE` 声明，**实际扫描集** = 它点名的枚举函数 `scanned_shell_files()`
的返回集（全仓受控 `*.sh`，剪枝 `.git` / `node_modules` / `.venv` 等，见 `CENSUS_EXCLUDE_DIRS`）。
「声称 == 实际」由 `tests/unit_ci_workflows/test_guard_scope_declaration.py` 常驻钉住
（**未登记即红 + 未覆盖面台账只许缩短 + 语料闭包**）—— 不许再出现「docstring 说全仓、实际只扫 `scripts/**`」。

沿革：#5260 / PR #5277 把射程钉在 `scripts/**/*.sh`（11 个文件），并在 docstring 里**显式登记**
「仓库根 `*.sh` 不在射程」；#5284 把射程扩到**全仓**并修掉扩面后暴露的**存量 12 处**
（仓库根 3 处 = `check-ui-regression.sh` ×2 + `contract-check.sh` ×1；`deploy/**` 9 处）。

## 五条判据（各自能单独变红；红证见各测试 docstring）

| # | 判据 | 红证（改回坏形态 ⇒ 必红） |
|---|---|---|
| 1 | 射程内 `*.sh` 的**代码面**（剥注释 + 屏蔽单引号字面量）不得出现 `$VAR` 紧跟非 ASCII | 把任一 `${VAR}` 改回 `$VAR` |
| 2 | 注释 / 单引号字面量里的同类文本**不得**判红（负例，防假红） | 只加一条注释含该形态 ⇒ 必须绿 |
| 3 | 射程**真的覆盖**（a）**仓库根** `*.sh` 全集、（b）`.github/scripts/**` 这一族面（#5283 残余② 选甲：扩面，不登记缺口） | 把 `GUARD_SCOPE.roots` 收窄成 `["scripts"]` ⇒ 必红（两条射程自证） |
| 4 | **行为级**：`bash scripts/sync-main.sh --bogus` 必须打印「未知参数」+ exit 1；`./check-ui-regression.sh` 走「token 减少」分支必须打印可读文案 | 改回 `$arg（` / `$f（` ⇒ 必红 |
| 5 | 反绕过锁：shebang 必须是 `#!/usr/bin/env bash`（不引入 bash 5 依赖假设） | 改成具体 bash 5 路径 ⇒ 必红 |

判据 4 的两条行为腿是**承重件**（行为级比静态扫描硬）；判据 1 是「防新增 + 防存量回退」的类级扫描；
判据 3 是 #5284 的**射程自证**（没有它，「扩了射程」只是一句话）。

## 有意不做的（照实登记，**不是**「已覆盖」）

- **不**模拟 heredoc 正文（`<<'EOF'` 里的 `$VAR` 不展开）：扩到全仓后实测零命中该形态。
  ⇒ 若将来 heredoc 正文里写 `$VAR`+中文，本判据会**假红**（偏保守，不吞真判据）。
- 射程 = `*.sh` 这一**语料**；**不带 `*` 的具体脚本名不算语料引用**（否则普查无法判别）。
  非 `*.sh` 的 shell 载体（workflow 内联 `run:` 块、`.bash` / `.zsh` 文件）**不在面内**：
  仓库当前零个此类文件；语料闭包判据（`test_guard_scope_declaration.py`）管的是**已入册语料**的覆盖面。
- **边界口径（#5283 残余② 裁定 = 甲：扩面，不登记缺口）**：射程是**全仓受控 `*.sh`** ——
  `scripts/**`、**仓库根**、`.github/scripts/**`、`deploy/**`、`acceptance/**`、`tests/e2e/scripts/**`
  一视同仁（剪枝只排除 `.git` / `node_modules` / `.venv` 等非本仓受控目录）。
  **未登记任何「不扫的面」** ⇒ 台账 `uncovered_faces` 现取 0 条（元守卫把 0 钉死）。
- 判据 4 的**判别力依赖宿主 bash**：只有 bash 3.2 会把非 ASCII 并进变量名（bash 5 已改掉该语义）。
  宿主不可复现时行为腿退化为「该分支必须是 `${VAR}`」的形态断言并打 warning，
  **不静默变成「绿了但没判」**（见两条判别力自证）。
"""
import os
import re
import shutil
import subprocess
import warnings
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
SYNC_MAIN = SCRIPTS_DIR / "sync-main.sh"
BATCH_INTEGRATE = SCRIPTS_DIR / "batch-integrate-check.sh"
UI_REGRESSION = REPO_ROOT / "check-ui-regression.sh"

#: 语料普查剪枝（**不是**豁免面：这些目录里的 `.sh` 都不是本仓受控脚本 —— VCS 元数据 / 依赖树 /
#: 构建产物）。台账与元守卫用同一份常量（元守卫 `test_guard_scope_declaration.py` 逐字钉住它）。
CENSUS_EXCLUDE_DIRS = (
    ".git", "node_modules", ".venv", "venv", "site-packages", ".next", "dist", "build", "coverage",
)

#: **射程声明**（结构化、机器可读）。`roots` / `glob` / `exclude_dirs` 三者合起来定义语料；
#: `enumerator` 点名的函数返回**实际**扫描集。元守卫要求「本常量 == 台账副本 == 实际枚举结果」。
GUARD_SCOPE = {
    "roots": ["."],
    "glob": "*.sh",
    "exclude_dirs": list(CENSUS_EXCLUDE_DIRS),
    "enumerator": "scanned_shell_files",
    "uncovered_faces": [],
}

# 与 #5241 的类级锁同一个形态：`$NAME` 后**紧跟**一个非 ASCII 字节（`${NAME}` 合法，不命中）。
_UNBRACED_MULTIBYTE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)([^\x00-\x7F])")

# shell 里「词首」的元字符：`#` 只在词首才是注释开始（`a#b` 是字面量）。
_WORD_START = " \t\n;&|()<>"

_BASH = shutil.which("bash") or "/bin/bash"


def scanned_shell_files() -> list[Path]:
    """本判据**实际**扫描的脚本集 —— 射程的唯一来源（`GUARD_SCOPE.enumerator` 点名的就是它）。

    用 `os.walk` 手动剪枝（不是 `rglob`）：开发机上 `node_modules` / `.venv` 可能有十万级文件，
    剪枝要在**下降之前**发生，否则判据的耗时取决于依赖树的形状（挂钟不可当判据，§23 G8）。
    """
    roots = [REPO_ROOT / r for r in GUARD_SCOPE["roots"]]
    suffix = GUARD_SCOPE["glob"].lstrip("*")
    out: list[Path] = []
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in CENSUS_EXCLUDE_DIRS)
            for name in sorted(filenames):
                if name.endswith(suffix):
                    out.append(Path(dirpath) / name)
    return sorted(out)


def _code_face(src: str) -> str:
    """剥掉**注释**、并屏蔽**单引号字面量**后的代码面（逐字符等长替换 ⇒ 行号可定位）。

    为什么不能只做「整行以 `#` 开头」（两条都是本仓教训）：
      · **注释**：本仓已有多个脚本在注释里**讲解这个坑本身**（`$path（` 就是那行例子）⇒
        不剥注释就是「判据被自己的文案喂红」；行内注释同理。
      · **单引号字面量**：`'$x（'` 里的 `$` **不展开**，是纯文本 ⇒ 判它红就是假红。
    **双引号不屏蔽** —— `"… $arg（…"` 里的 `$arg` 是**真展开**，本次病灶全部长在双引号里。
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


def _run(script: Path, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [_BASH, str(script), *args],
        cwd=str(cwd or REPO_ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=120,
    )


def _host_bash_merges_multibyte_into_var_name() -> bool:
    """宿主 bash 是否复现 bash 3.2 的「非 ASCII 字节并入变量名」语义（行为腿的判别力前提）。"""
    r = subprocess.run(
        [_BASH, "-c", 'set -u; p=/tmp; echo "v: $p（x）"'],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
    )
    return r.returncode != 0 and "unbound variable" in (r.stderr + r.stdout)


def _ui_regression_sandbox(tmp_path: Path, script_src: str | None = None) -> Path:
    """造一个**最小 git 仓**，让 `check-ui-regression.sh` 必走「token 减少」告警分支。

    沙箱内容：`origin/main` 上 `Button.tsx` 含 2 个 `neutral`，工作区只剩 1 个
    ⇒ `main_neutral=2 > cur_neutral=1 > 0` ⇒ 命中第 73 行那条 `echo`（既不是回退分支，也不是放行分支）。
    其余 11 个关键文件在 `origin/main` 上不存在 ⇒ `main_neutral` 为空 ⇒ `[ "" -gt 0 ]` 为假 ⇒ 跳过。
    """
    wt = tmp_path / "ui-sandbox"
    (wt / "frontend/admin-web/src/components/ui").mkdir(parents=True)
    src = script_src if script_src is not None else UI_REGRESSION.read_text(encoding="utf-8")
    (wt / "check-ui-regression.sh").write_text(src, encoding="utf-8")
    target = wt / "frontend/admin-web/src/components/ui/Button.tsx"
    target.write_text("neutral\nneutral\n", encoding="utf-8")

    def g(*args: str) -> None:
        subprocess.run(["git", *args], cwd=str(wt), check=True, capture_output=True, timeout=60)

    g("init", "-q")
    g("config", "user.email", "redproof@example.invalid")
    g("config", "user.name", "redproof")
    g("add", "-A")
    g("commit", "-qm", "baseline（origin/main 基线：2 个 neutral）")
    g("update-ref", "refs/remotes/origin/main", "HEAD")
    target.write_text("neutral\n", encoding="utf-8")  # 工作区少一个 token ⇒ 走告警分支
    return wt


def test_repo_shell_code_face_has_no_unbraced_var_before_non_ascii():
    """判据 1：射程（全仓受控 `*.sh`）的**代码面**零命中（注释与单引号字面量不参与判定）。

    红证：把 `scripts/sync-main.sh` 未知参数分支、`scripts/batch-integrate-check.sh` 的
    `stranding-check exit=` 文案、`check-ui-regression.sh` 的告警行或 `contract-check.sh` 的
    `$SKU_EP（` 任一处 `${VAR}` 改回 `$VAR` ⇒ 本测试必红（原始读数见 PR body）。
    """
    files = scanned_shell_files()
    rel = {p.relative_to(REPO_ROOT).as_posix() for p in files}
    # fail-closed：扫描集为空 / 缩小到不含病灶文件 ⇒ 判据恒绿，比没有判据更坏。
    assert files, f"扫描集为空（射程 {GUARD_SCOPE['roots']} / {GUARD_SCOPE['glob']}）—— 判据会恒绿"
    named = {
        "scripts/sync-main.sh",                       # #5260 病灶
        "scripts/batch-integrate-check.sh",           # #5260 病灶
        "check-ui-regression.sh",                     # #5284 病灶（仓库根）
        "contract-check.sh",                          # #5284 扩面后暴露的存量（仓库根）
        "deploy/scripts/wx-mini-test-env-setup.sh",   # #5284 扩面后暴露的存量（deploy 面）
    }
    assert named <= rel, f"扫描集必须覆盖 issue 点名的存量，实际缺：{sorted(named - rel)}"
    bad = [f"{p.relative_to(REPO_ROOT).as_posix()} {hit}" for p in files
           for hit in find_unbraced_var_before_non_ascii(p.read_text(encoding="utf-8"))]
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


def test_repo_root_face_is_inside_range_and_mutation_is_detected():
    """判据 3（#5284 的**射程自证**）：仓库根 `*.sh` 在射程内，且注入同族形态必被抓到。

    红证：把 `GUARD_SCOPE['roots']` 从 `["."]` 收窄成 `["scripts"]` ⇒
    「仓库根在射程内」这半条立即红（元守卫 `test_guard_scope_declaration.py` 另有独立一条钉死同一形态）。
    变异自证：注入 `$f（` 后必须 `mutated != src`，且扫描器报出的正是第 73 行。
    """
    rel = {p.relative_to(REPO_ROOT).as_posix() for p in scanned_shell_files()}
    root_face = {p.name for p in REPO_ROOT.glob("*.sh")}
    assert root_face, "仓库根没有任何 *.sh ⇒ 本判据失去对象（fail-closed）"
    missing = sorted(f for f in root_face if f not in rel)
    assert missing == [], (
        f"仓库根这些脚本不在射程内（#5284 的缺口本身）：{missing}；"
        f"现取射程 = {GUARD_SCOPE['roots']} / {GUARD_SCOPE['glob']} / 剪枝 {GUARD_SCOPE['exclude_dirs']}"
    )
    src = UI_REGRESSION.read_text(encoding="utf-8")
    needle = 'echo "⚠️ UI token 减少: ${f}（'
    assert needle in src, f"定位告警分支失败（fail-closed，别静默跳过）：找不到 {needle!r}"
    mutated = src.replace(needle, 'echo "⚠️ UI token 减少: $f（')
    assert mutated != src, "变异注入未生效（自证失败 ⇒ 本判据的红证是空断言）"
    assert find_unbraced_var_before_non_ascii(mutated) == ["第 73 行 $f（"], (
        "把告警分支改回坏形态后扫描器没抓到 ⇒ 判据 1 对「仓库根」这一面没有判别力"
    )


def test_sync_main_unknown_arg_branch_prints_readable_error_not_unbound_variable():
    """判据 4 之①（**承重件**，行为级）：`bash scripts/sync-main.sh --bogus` 必须打印「未知参数」+ exit 1。

    红证（本机 bash 3.2 实测）：把该分支的 `${arg}` 改回 `$arg（` ⇒
    输出变成 `scripts/sync-main.sh: line 68: arg<0xEF>: unbound variable`，
    **看不到**「未知参数」⇒ 本测试必红。该红证由下一条测试在脚本**副本**上自动复跑。
    """
    r = _run(SYNC_MAIN, "--bogus")
    combined = r.stdout + r.stderr
    assert r.returncode == 1, f"未知参数分支必须 exit 1，实际 {r.returncode}；输出：{combined!r}"
    assert "未知参数" in combined, f"必须打印可读的「未知参数」文案，实际输出：{combined!r}"
    assert "unbound variable" not in combined, (
        f"错误路径本身坏掉（bash 3.2 把非 ASCII 并进变量名 ⇒ unbound variable）：{combined!r}"
    )


def test_behavioral_leg_reproduces_unbound_variable_on_mutated_copy(tmp_path):
    """判据 4 之①的**判别力自证**：把坏形态注入脚本副本，行为腿必须在**同一宿主**上抓到它。

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
        r = _run(mutated, "--bogus")
        combined = r.stdout + r.stderr
        assert "unbound variable" in combined, (
            f"注入坏形态后行为腿**没能**变红 ⇒ 上一条判据是空判据：{combined!r}"
        )
        assert "未知参数" not in combined, f"坏形态下不应还能打印可读文案：{combined!r}"
        return

    branch = [ln for ln in _code_face(src).splitlines() if "未知参数" in ln]
    assert branch and "${arg}" in branch[0], f"未知参数分支必须用 ${{arg}} 包裹，实际：{branch}"
    warnings.warn(
        f"宿主 bash（{_BASH}）不复现 bash 3.2 的「非 ASCII 并入变量名」语义 ⇒ 判据 4 之① 的行为腿"
        "在本宿主上**不可判别**，已退化为「未知参数分支必须 ${arg}」的形态断言"
        "（macOS 自带 bash 3.2 上行为腿满功率；CI runner 为 bash ≥5，属此分支）",
        stacklevel=1,
    )


def test_check_ui_regression_token_decrease_branch_is_readable_on_bash32(tmp_path):
    """判据 4 之②（#5284 判据 1 的**行为级**红证）：仓库根脚本的告警分支必须打印可读文案且 exit≠127。

    场景（不是推断，是造出来的）：沙箱里 `origin/main` 的 `Button.tsx` 有 2 个 `neutral`、
    工作区只剩 1 个 ⇒ 走第 73 行的「token 减少」分支。坏形态下（bash 3.2）这一行会变成
    `f<0xEF>: unbound variable`。

    ⚠️ **读数订正（本机实测；issue #5284 正文的 127 只适用于 `bash -c` 形态）**：脚本形态下
    bash 3.2 的 unbound variable 退出码是 **1**，与 `check-ui-regression.sh` 判到**真回退**时的
    `exit 1` **完全同码** ⇒ 区分只剩「stderr 多一行 unbound variable、少一行可读文案」，
    **诊断性损失比 issue 正文描述的更彻底**。
    """
    wt = _ui_regression_sandbox(tmp_path)
    r = _run(wt / "check-ui-regression.sh", cwd=wt)
    combined = r.stdout + r.stderr
    assert "unbound variable" not in combined, (
        f"告警分支被 bash 3.2 的变量名并字节语义打断（#5284 病灶）：{combined!r}"
    )
    assert "⚠️ UI token 减少" in combined, f"必须打印可读的「token 减少」文案，实际：{combined!r}"
    assert "main=2 → 当前=1" in combined, f"文案必须带真值读数（main/当前），实际：{combined!r}"
    assert r.returncode == 0, (
        f"只触发「token 减少」告警（不是回退）时不应改变退出码，实际 {r.returncode}；输出：{combined!r}"
    )


def test_ui_regression_mutation_reds_the_behavioral_leg(tmp_path):
    """判据 4 之②的**判别力自证**：把 `$f（` 注入仓库根脚本副本 ⇒ 行为腿必须变红。

    与 `scripts/sync-main.sh` 那条同款降级口径：宿主 bash ≥5 不复现 3.2 语义时不静默放行，
    退化为「告警分支必须是 `${f}`」的形态断言 + 显式 warning。
    """
    src = UI_REGRESSION.read_text(encoding="utf-8")
    needle = 'echo "⚠️ UI token 减少: ${f}（'
    assert needle in src, f"定位告警分支失败（fail-closed）：找不到 {needle!r}"
    mutated_src = src.replace(needle, 'echo "⚠️ UI token 减少: $f（')
    assert mutated_src != src, "变异注入未生效（自证失败 ⇒ 本判据的红证是空断言）"

    if _host_bash_merges_multibyte_into_var_name():
        wt = _ui_regression_sandbox(tmp_path, script_src=mutated_src)
        r = _run(wt / "check-ui-regression.sh", cwd=wt)
        combined = r.stdout + r.stderr
        assert "unbound variable" in combined, (
            f"注入坏形态后行为腿**没能**变红 ⇒ 上一条判据是空判据：{combined!r}"
        )
        assert "⚠️ UI token 减少" not in combined, f"坏形态下不应还能打印可读文案：{combined!r}"
        assert r.returncode == 1, (
            "坏形态下脚本形态的 bash 3.2 实测退出 1（`bash -c` 形态才是 127）——"
            f"与真回退的 exit 1 同码，正是「与真红灯无法区分」的病灶，实际 {r.returncode}"
        )
        return

    branch = [ln for ln in _code_face(src).splitlines() if "token 减少" in ln]
    assert branch and "${f}" in branch[0], f"告警分支必须用 ${{f}} 包裹，实际：{branch}"
    warnings.warn(
        f"宿主 bash（{_BASH}）不复现 bash 3.2 的「非 ASCII 并入变量名」语义 ⇒ 判据 4 之② 的行为腿"
        "在本宿主上**不可判别**，已退化为「告警分支必须 ${f}」的形态断言"
        "（macOS 自带 bash 3.2 上行为腿满功率；CI runner 为 bash ≥5，属此分支）",
        stacklevel=1,
    )


def test_scripts_keep_env_bash_shebang_no_bash5_dependency():
    """判据 5（反绕过锁）：本单修法是 `${VAR}` 显式包裹，**不是**引入 bash 5 依赖假设（issue「不做」条）。

    红证：把任一 shebang 改成 `/opt/homebrew/bin/bash` 之类的**具体 bash 5 路径** ⇒ 必红。
    """
    wrong = [
        p.relative_to(REPO_ROOT).as_posix()
        for p in (SYNC_MAIN, BATCH_INTEGRATE, UI_REGRESSION)
        if p.read_text(encoding="utf-8").splitlines()[:1] != ["#!/usr/bin/env bash"]
    ]
    assert wrong == [], f"这些脚本的 shebang 不再是 `#!/usr/bin/env bash`（引入解释器依赖假设）：{wrong}"


def test_github_scripts_face_is_inside_range_and_mutation_is_detected():
    """判据 3 之②（#5283 残余② 的**甲方案自证**）：`.github/scripts/**` 这一族面也在射程内。

    红证（issue #5283 判据 2 逐字要求的那条）：往 `.github/scripts/` 造一处同族形态 ⇒ 必红。
    这里用「在副本上追加同族形态行」的形式（= 将来有人在那个面里加一条中文告警文案的真实形态）：
    扫描器必须报出**该文件 + 行号**；同时断言该面的 `.sh` **全集**都在射程内（不是只挑了某一个文件）。
    """
    gh = REPO_ROOT / ".github" / "scripts"
    face = {p.relative_to(REPO_ROOT).as_posix() for p in sorted(gh.glob("*.sh"))}
    assert face, "`.github/scripts/` 下没有 *.sh ⇒ 本判据失去对象（fail-closed）"
    rel = {p.relative_to(REPO_ROOT).as_posix() for p in scanned_shell_files()}
    missing = sorted(face - rel)
    assert missing == [], f"`.github/scripts/**` 这些脚本不在射程内（#5283 残余② 的缺口本身）：{missing}"
    victim = gh / "mechanism_liveness.sh"
    src = victim.read_text(encoding="utf-8")
    base = src.rstrip("\n")  # 不依赖「文件是否以换行结尾」这个小前提（否则行号断言会脆）
    probe_line = 'echo "❌ 机制存活读数缺失: $probe（别名未登记）"'
    mutated = f"{base}\n{probe_line}\n"
    assert mutated != src, "变异注入未生效（自证失败 ⇒ 本判据的红证是空断言）"
    hits = find_unbraced_var_before_non_ascii(mutated)
    assert hits == [f"第 {len(base.splitlines()) + 1} 行 $probe（"], (
        f"`.github/scripts/` 面注入同族形态后扫描器没抓到（#5283 残余② 的射程仍是缺口）：{hits}"
    )
    assert victim.name in " ".join(sorted(rel)), "该面文件必须在射程内（与上面 face ⊆ rel 互为佐证）"
