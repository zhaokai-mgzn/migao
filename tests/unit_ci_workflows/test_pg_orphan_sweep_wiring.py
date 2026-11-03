# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012 ——
#   见同目录 test_verify_all_gate_parity.py / test_machine_heavy_lock.py 的同款声明。
#   本包**不新建用例族**：新建 MC 号必须同时改用例库（`.github/cases/**`）⇒ 触发 Case Trust 的
#   burn-down 预算（每 PR 至少净销 1 条存量违规），而本包是「清点器接线」，与用例库债务无关。）
r"""孤儿 PG 集群清点器的**接线**判据（issue #6751）。

## 病（现取读数，不是推断）

`scripts/pg_orphan_sweep.py` **本身已达标**：恒打印计数（`:175` 附近）、有孤儿则非零退出（`:181` 附近）、
读不到 `ps` 退 `3`。但它**全仓零调用方** —— `verify-all.sh` 的 `gate` 档（合并门禁）没有调用它
⇒ 孤儿临时 postgres 实测活了 **23.5 小时**、没人喊一声。
形态属 `migao-dev-flow` §28.2「**判据本体绿 ≠ 接线在**」：判据本体早被测到了，**消费点没有**。

## 本文件判什么（五条，各自能单独变红）

| # | 判据 | 回归时会怎么红 |
|---|---|---|
| ① | **接线在且真会跑**：`gate` 档在**完整检出**分支里调用 `orphan_sweep_step`，步骤真的执行清点器（不是注释 / 不是 `\|\| true`）；被调对象（清点器 + 收口件）都真实存在 | 摘掉派发 / 注释掉 / 改名 / 把判据改成永不成立 / 吞退出码 ⇒ 具名红 |
| ② | **有孤儿 ⇒ 红且报文含 pid + 存活时长 + 清场命令**（替身 `ps` 造夹具，真跑真 `report()`） | 报文缺任一读数 ⇒ 红 |
| ③ | **无孤儿 ⇒ 绿**（负控；日志里必须有一行计数 0） | 静默无输出 / 误判红 ⇒ 红 |
| ④ | **读不到 `ps` ⇒ 无法判定（3），不许当 0**（负控） | 写成 `\|\| true` / 把 3 映射成 0 ⇒ 判据转绿 ⇒ 本文件红（见 `test_mapping_unjudgeable_to_zero_is_caught`） |
| ⑤ | **轻量档**：步骤体里不得出现重活标记（不拿机器级重活锁 / 不起测试套件） | 把全量套件塞进这一步 ⇒ 红 |

## 为什么它算「轻量档」（每次都跑，不拿 `scripts/machine-heavy-lock.sh` 的锁）

清点器只做一件事：跑一次 `ps`（`PS_ARGS`）并解析 `postgres -D` 行 —— 不建 venv、不起库、不联网、
不写盘（默认 dry-run）。本文件把这条**写成判据**（⑤：步骤体内不得出现 `pytest` / `mvnw` / `vitest` /
`npm` / 重活锁），所以「有人把它改成重活」会当场红，而不是悄悄拖慢合并门禁。

## 边界（照实登记，§19.1）

- ① 的**静态面**只判「锚在不在 + 缩进是否构成『完整检出分支内』」；**行为面**由 ②③④ 承担：
  它们把 `report()` 与 `orphan_sweep_step()` **逐字从真脚本抽出**、在同一条真进程链上跑
  （不是重写第二份判定）。「`verify-all.sh gate` 整档真跑」不在这里做 —— 那是全量档（§27 机器重活）。
- 替身 `ps` 走清点器**已登记**的注入点（`PG_SWEEP_PS_BIN`，见 `scripts/pg_orphan_sweep.py` 的「注入点」节），
  不 mock 被测函数。
- 桩 / 部分检出（判据沙箱只带 `verify-all.sh` + 少量脚本）没有判据目录 ⇒ 调用点显式打印「未跑」，
  **不当通过**；本文件判的那条「未跑」声明就是它的机械面（删掉 ⇒ ① 红）。
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
from unit_ci_workflows.injection import inject  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFY_ALL = REPO_ROOT / "verify-all.sh"
SWEEP = REPO_ROOT / "scripts" / "pg_orphan_sweep.py"
FUNNEL = REPO_ROOT / "tests" / "unit_ci_workflows" / "pg_cluster.py"

#: 声明把本判据守的**接线锚**登记进 `wiring_claims_ledger.json`（§28.2.1：未登记即红）。
#: 锚 = `<仓库相对路径>::<消费点符号>`，不写行号（行号几分钟就失效）。
WIRING_UNDER_TEST = "verify-all.sh::orphan_sweep_step"

STEP_FN = "orphan_sweep_step"
DISPATCH = 'report "孤儿 PG 集群清点（ppid==1 且在临时区）" orphan_sweep_step'
FULL_CHECKOUT_PREDICATE = '[ -d "${ROOT:-}/tests/unit_ci_workflows" ]'
NOT_RUN_DECL = "孤儿 PG 集群清点**未跑**"
NAME_IN_CONSOLE = "孤儿 PG 集群清点"

#: 「重活」标记：步骤体（剥注释后的**代码**面）出现任一 ⇒ 它不再是轻量档（§27 机器重活串行）。
HEAVY_MARKERS = ("machine-heavy-lock", "pytest", "mvnw", "vitest", "npm ", "docker compose")

#: 替身 `ps` 的受控进程表（与 tests/unit_ci_workflows/test_pg_orphan_sweep.py 同一形态，数值独立）。
PS_ORPHAN = "  1234     1 03:12:44 /usr/local/bin/postgres -D /tmp/pg6751-wiring-A/pgdata -k /tmp/s1 -p 5432"
PS_LIVE = "  4321  4242 04:00:00 /usr/local/bin/postgres -D /tmp/pg6751-wiring-B/pgdata -k /tmp/s2 -p 5433"


# ── 结构化读脚本（bash：只丢**整行注释**，不做行尾截断）─────────────────────────
def _code(text: str) -> str:
    """丢掉**整行注释**后的代码面。

    ⚠️ 有意**不**做「按 `#` 截断行尾」：那正是 `tests/unit_ci_workflows/test_guard_parsing_is_comment_aware.py`
    判的「第二把朴素 `#` 尺子」（字符串里的 `#` 会吃掉行尾）。而共享实现
    `tests/unit_ci_workflows/_source_parsing.py` 的 `code_without_comments()` 是 **Python tokenize**
    口径、不适用于 bash 文本 ⇒ 这里只做**行级**判定（本分支的注释都是整行，`gate` 分支注释也要求
    字符串里不出现 `#`），不做任何截断。
    """
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def _gate_branch(text: str) -> str:
    """抽顶层 `case "$MODE" in` 的 `gate)` 分支原文（到该分支的 `;;` 为止）。"""
    start = text.find('case "$MODE" in')
    if start < 0:
        return ""
    m = re.search(r"^  gate\)$([\s\S]*?)^    ;;$", text[start:], re.M)
    return m.group(1) if m else ""


def _fn_body(text: str, name: str) -> str:
    """抽 `name() { … }` 的函数体（到第 0 列的 `}`）。"""
    m = re.search(rf"^{re.escape(name)}\(\) \{{[\s\S]*?^\}}", text, re.M)
    return m.group(0) if m else ""


def _wiring_problems(text: str, repo_root: Path = REPO_ROOT) -> list[str]:
    """接线违规清单（空列表 = 全绿）。纯函数：吃脚本文本 + 读盘器，注入式红证可在内存里构造坏形态。"""
    bad: list[str] = []
    gate = _gate_branch(text)
    if not gate:
        return ["verify-all.sh 里找不到顶层 `gate)` 分支 ⇒ 接线面无从判定"]

    gate_code = _code(gate)
    lines = gate_code.splitlines()
    dispatch_idx = next((i for i, ln in enumerate(lines) if DISPATCH in ln), None)
    if dispatch_idx is None:
        return [
            "gate 档**没有调用**孤儿清点器 ⇒ 清点器又变成零调用方（issue #6751 原形："
            "有孤儿也不会有任何东西变红）"
        ]

    pred_idx = next((i for i, ln in enumerate(lines) if FULL_CHECKOUT_PREDICATE in ln), None)
    if pred_idx is None:
        bad.append(
            "gate 档缺「完整检出」判据（`%s`）⇒ 调用点可能在桩 / 部分检出里假装通过"
            % FULL_CHECKOUT_PREDICATE
        )
    elif pred_idx >= dispatch_idx:
        bad.append("「完整检出」判据出现在调用**之后** ⇒ 它不是这次调用的前提（缩进/顺序读不通）")
    else:
        pred_indent = len(lines[pred_idx]) - len(lines[pred_idx].lstrip())
        disp_indent = len(lines[dispatch_idx]) - len(lines[dispatch_idx].lstrip())
        between = [ln.strip() for ln in lines[pred_idx + 1:dispatch_idx]]
        if disp_indent <= pred_indent:
            bad.append(
                "调用不在「完整检出」分支**内**（缩进没有构成嵌套 ⇒ 可能被 `fi` / `else` 隔开）"
            )
        if any(token in ("else", "fi") for token in between):
            bad.append("调用与「完整检出」判据之间出现了 `else` / `fi` ⇒ 它落在分支之外")

    if not (repo_root / "tests" / "unit_ci_workflows").is_dir():
        bad.append(
            "本仓缺判据目录 ⇒ 调用点的「完整检出」判据为假 ⇒ 这条检查项在真仓里也不会跑"
        )
    if NOT_RUN_DECL not in gate:
        bad.append(
            "缺「未跑」显式声明（桩 / 部分检出时必须说出来）⇒ 「没跑」会与「通过」同形（静默跳过）"
        )

    body = _fn_body(text, STEP_FN)
    if not body:
        bad.append(f"verify-all.sh 里抽不到 {STEP_FN}() ⇒ 派发点指向一个不存在的步骤")
        return bad
    body_code = _code(body)
    if 'python3 "$sweep"' not in body_code:
        bad.append(f"{STEP_FN}() 没有真的执行清点器（找不到 `python3 \"$sweep\"`）⇒ 接线是空的")
    if "scripts/pg_orphan_sweep.py" not in body:
        bad.append(f"{STEP_FN}() 没有指向 scripts/pg_orphan_sweep.py（唯一实现）")
    if "|| true" in body_code:
        bad.append(
            f"{STEP_FN}() 吞掉了退出码（出现 `|| true`）⇒ 有孤儿 / 读不到 `ps` 都不再判红"
        )
    heavy = [marker for marker in HEAVY_MARKERS if marker in body_code]
    if heavy:
        bad.append(f"{STEP_FN}() 出现了重活标记 {heavy} ⇒ 它不该在合并门禁每次都跑（§27）")

    for path, why in ((SWEEP, "清点器"), (FUNNEL, "分类口径收口件")):
        if not path.is_file():
            bad.append(f"接线指向的{why}不存在：{path.relative_to(repo_root)}（被调对象是空的）")
    return bad


def _fake_ps(tmp_path: Path, process_table: str) -> Path:
    """造一个替身 `ps`：只打印给定的进程表（清点器的已登记注入点 `PG_SWEEP_PS_BIN`）。"""
    path = tmp_path / "ps-stub"
    path.write_text(
        "#!/bin/sh\n" + "printf '%s\\n' " + shlex.quote(process_table) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _run_wired_step(ps_bin: Path, step_body: str | None = None) -> tuple[str, str]:
    """真跑 `report()` + `orphan_sweep_step()`（逐字抽自 verify-all.sh）⇒ `(控制台原文, 日志原文)`。

    为什么逐字抽而不是重写一份：§28.2 的「判据绿 ≠ 接线在」—— 这里要判的正是**真接线**
    （两段真的会跑的 shell），重写一份就只能证明「我的副本会判红」。
    """
    text = VERIFY_ALL.read_text(encoding="utf-8")
    report_body = _fn_body(text, "report")
    wired_step = step_body if step_body is not None else _fn_body(text, STEP_FN)
    assert report_body, "verify-all.sh 里抽不到 report()（结构变了要同步更新本判据）"
    assert wired_step, f"verify-all.sh 里抽不到 {STEP_FN}()（结构变了要同步更新本判据）"
    script = "\n".join([
        "set -u",
        "printf 'PID=%s\\n' \"$$\"",
        "ROOT=%s" % shlex.quote(str(REPO_ROOT)),
        "FAIL=0",
        "PASS=0",
        "READY=0",
        "FAILED=()",
        report_body,
        wired_step,
        "report %s %s" % (shlex.quote(NAME_IN_CONSOLE + "（ppid==1 且在临时区）"), STEP_FN),
        "printf 'RESULT PASS=%s FAIL=%s\\n' \"$PASS\" \"$FAIL\"",
    ])
    env = dict(os.environ)
    env["PG_SWEEP_PS_BIN"] = str(ps_bin)
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    proc = subprocess.run(
        ["bash", "-c", script], cwd=str(REPO_ROOT), capture_output=True, text=True,
        env=env, timeout=120,
    )
    out = "%s%s" % (proc.stdout or "", proc.stderr or "")
    log = ""
    m = re.search(r"^PID=(\d+)$", out, re.M)
    if m:
        hits = sorted(Path("/tmp").glob("verify-all-%s-*.log" % m.group(1)))
        if hits:
            log = hits[0].read_text(encoding="utf-8", errors="replace")
            for hit in hits:
                hit.unlink(missing_ok=True)
    return out, log


# ── ① 接线在且真会跑 ─────────────────────────────────────────────────────────
def test_real_script_wires_the_sweep_into_the_gate_tier():
    """真 `verify-all.sh` 的接线完整（`gate` 档每次跑、轻量、被调对象都在）。"""
    problems = _wiring_problems(VERIFY_ALL.read_text(encoding="utf-8"))
    assert problems == [], "孤儿清点器的接线不完整：\n- " + "\n- ".join(problems)


def test_wiring_removal_and_silencing_are_caught():
    """注入式红证（纯内存，不写盘）：摘派发 / 注释掉 / 改名 / 判据永不成立 / 吞退出码 ⇒ **各自**判红。"""
    text = VERIFY_ALL.read_text(encoding="utf-8")
    assert _wiring_problems(text) == [], "先决条件：真脚本必须是绿（否则下面的注入证明不了判别力）"

    mutants = {
        "派发被摘掉": inject(text, DISPATCH, "", where="verify-all.sh"),
        "派发被注释掉": inject(text, DISPATCH, "# " + DISPATCH, where="verify-all.sh"),
        "步骤函数被改名": inject(
            text, "orphan_sweep_step() {", "orphan_sweep_wiring() {", where="verify-all.sh"
        ),
        "完整检出判据改成永不成立": inject(
            text, FULL_CHECKOUT_PREDICATE, '[ -d "$ROOT/nonexistent-dir" ]', where="verify-all.sh"
        ),
        "退出码被吞": inject(text, 'python3 "$sweep"', 'python3 "$sweep" || true', where="verify-all.sh"),
    }
    for label, mutated in mutants.items():
        problems = _wiring_problems(mutated)
        assert problems, f"注入「{label}」后判据仍然全绿 ⇒ 这条判据是空断言（回归不会红）"

    # 反向对照：只加一行说明文字不得判红（判据读的是代码面，不吃自己的文案）。
    comment_only = inject(
        text, DISPATCH, "# 说明：这一行是接线点\n      " + DISPATCH, where="verify-all.sh"
    )
    assert _wiring_problems(comment_only) == [], "只改注释不得判红（否则判据被自己的文案喂红）"


# ── ② 有孤儿 ⇒ 红，且报文具名 pid / 存活时长 / 清场命令 ─────────────────────
def test_fake_orphan_turns_the_gate_step_red_with_pid_age_and_cleanup(tmp_path):
    out, log = _run_wired_step(_fake_ps(tmp_path, PS_ORPHAN))
    assert f"❌ {NAME_IN_CONSOLE}" in out and "(exit 1)" in out, (
        "造出孤儿后该步必须判红且报出退出码 1（真 report() 的判定）：\n" + out
    )
    assert "RESULT PASS=0 FAIL=1" in out, "失败必须记进 FAIL（不许只打印不计数）：\n" + out
    assert "pid=1234" in log, "日志必须具名报出孤儿 pid（否则「红了」但不知道是谁）：\n" + log
    assert "03:12:44" in log, "日志必须报出存活时长（照 issue #6751：23.5 小时的代价）：\n" + log
    assert "pg_orphan_sweep.py --apply" in log, (
        "日志必须给出**可复制**的清场命令（用户口径：红了要能立刻处置）：\n" + log
    )


# ── ③ 无孤儿 ⇒ 绿（负控）────────────────────────────────────────────────────
def test_no_orphans_is_green_with_a_zero_count_line(tmp_path):
    out, log = _run_wired_step(_fake_ps(tmp_path, PS_LIVE))
    assert f"✅ {NAME_IN_CONSOLE}" in out, "无孤儿必须判绿（只有 ppid!=1 的在用集群）：\n" + out
    assert "RESULT PASS=1 FAIL=0" in out, "通过必须记进 PASS：\n" + out
    assert "孤儿集群 = 0" in log, "「没扫到」必须长得像「没扫到」（恒打印计数 0）：\n" + log


# ── ④ 读不到 ⇒ 无法判定（3），不许当 0 ──────────────────────────────────────
def test_unreadable_ps_is_unjudgeable_and_never_green(tmp_path):
    out, log = _run_wired_step(tmp_path / "ps-does-not-exist")
    assert f"❌ {NAME_IN_CONSOLE}" in out, "读不到 `ps` 时该步必须判红：\n" + out
    assert "(exit 3)" in out, "「无法判定」必须以**退出码 3** 上来（不是 0、也不是 1）：\n" + out
    assert "✅" not in out, "读不到进程表**不许**判绿 —— 这正是 `|| true` 会造成的假绿：\n" + out
    assert "RESULT PASS=0 FAIL=1" in out, "无法判定必须记失败（不许当通过）：\n" + out
    assert "无法判定" in log, "日志必须说清「无法判定」而不是「没有孤儿」：\n" + log


def test_mapping_unjudgeable_to_zero_is_caught(tmp_path):
    """红证：把 3 吞成 0（等价于 `|| true`）⇒ ④ 那条判据**必定**红（它有判别力，不是空断言）。"""
    text = VERIFY_ALL.read_text(encoding="utf-8")
    swallowed = inject(
        _fn_body(text, STEP_FN), 'python3 "$sweep"', 'python3 "$sweep" || true', where="verify-all.sh"
    )
    out, _log = _run_wired_step(tmp_path / "ps-does-not-exist", step_body=swallowed)
    assert f"✅ {NAME_IN_CONSOLE}" in out and "RESULT PASS=1 FAIL=0" in out, (
        "变异体（吞掉退出码）必须变成「绿」—— 只有这样，④ 的「不许判绿」才有判别力；"
        "若变异体仍是红，说明这条判据看的不是退出码：\n" + out
    )
