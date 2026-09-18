# case_ids: MC-012
"""`verify-all.sh` 检查项日志的**定位与清理口径**守卫（issue #4158，L0 零 LLM、零网络）。

## 缺陷（三路执行者独立撞到，非推断）

`report()` 把每个检查项的输出写进 `/tmp/verify-all-<PID>-<slug>.log`；守卫此前**只按 PID 通配**
定位它，这套口径有两个洞：

1. **PID 复用 ⇒ 读到别人的日志**。`/tmp` 是跨会话共享的，PID 会被复用；同前缀的**既有残骸**
   （上一个复用该 PID 的进程留下的）会被 `glob` 一并命中 ⇒ `len(paths)==1` 假红，
   或 `paths[0]` 直接读到**别人**的现场（"日志"指向的内容与本案无关 —— 与 `#3270` 的
   pipefail 假绿同源：**报错指向的证据与实际原因不一致**，比直接报错更难查）。
2. **日志被外部清理 ⇒ 裸 `FileNotFoundError` / 无信息的空串断言**。`Path.read_text()` 在
   glob 与读取之间被删就抛 `FileNotFoundError`；退一步也只是 `assert paths` 的「未能定位」——
   **都没有期望路径 / 实际命中 / 残骸清单**，排查只能靠猜。

**制造者**（本批实测，比 issue 原文更强的证据）：`test_verify_all_tri_state_noop.py` 的收尾清理
用的是**全局通配**（`/tmp/verify-all-` 后面直接跟通配符），而同文件另两处清理都是 `$$` 作用域
⇒ 本批约 40 个 sibling worktree 并行跑测试时，它会删掉**别的进程（含 `./verify-all.sh gate` 自己）
正在用的日志**，表现为 `grep/sed: /tmp/verify-all-<pid>-….log: No such file or directory` 且告警行丢失。
两个独立包各实测到「全量跑 5 次红 2 次 / 3 次、单跑恒绿」——**判据自己制造假红**，
是"为绿而绿"的镜像：用户会学会忽略红。

## 口径（issue「要做」1~3）

- **归属过滤**（只认**本次运行自己的**产物）：PID 通配 ∩ ①「运行前不存在，或虽存在但已被本次
  运行重写」∩ ②「mtime 落在本次运行窗口内」。两条合起来 = 残骸（定义上由**已死**进程写下、
  且早于本次运行）不可能被当成自己的。
- **定位失败 ⇒ 大声报红 + 全现场**：期望路径模式 / 本次 PID / 实际命中 / 被排除的同 PID 残骸 /
  `/tmp` 同族清单 / 控制台原文 / 处置线索。**绝不**裸 `FileNotFoundError`，**绝不**退化成空串断言。
- **清理只许作用域内**：`tests/unit_ci_workflows/**` 不得出现「`/tmp/verify-all-` 紧跟通配符」的
  全局清理（`test_no_unscoped_tmp_log_cleanup_in_test_dir` 静态锁定，并自带可失败证明）。

## 单一实现

`test_gate_uncommitted_noop.py` / `test_growth_gate_fail_closed.py` 的 `_run_gate` 都改为调用本模块的
`run_gate()` —— 定位/清理口径**只写一处**，改一处即全改（复制 = 双源漂移）。
"""
import os
import re
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
VERIFY_ALL = REPO_ROOT / "verify-all.sh"
TEST_DIR = Path(__file__).resolve().parent
TMP = Path("/tmp")

# 产物命名（`verify-all.sh` 的 `report()`）与「失败时才把路径打进控制台」的形态。
PID_LOG_GLOB = "verify-all-%s-*.log"
LOG_LINE_RE = re.compile(r"日志: (?P<path>\S+)")

# 被禁形态**拼接构造**：本文件自己会被 `test_no_unscoped_tmp_log_cleanup_in_test_dir` 扫描
# （被禁形态正是写在字符串里的，剥注释剥不掉它）⇒ 正文不得出现该字面量。
UNSCOPED_TMP_LOG_PREFIX = "/tmp/verify-all-" + "*"

# 模拟「PID 复用残骸」的外来日志：slug 以 `AAA-` 开头（排序**在**本案自己的日志之前，
# 旧口径取 `paths[0]` 必然读到它），正文带一个不可能出现在真实 gate 输出里的哨兵串。
FOREIGN_SLUG = "AAA-Foreign-Stale"
FOREIGN_SENTINEL = "FOREIGN-STALE-LOG-SENTINEL-4158"

# 归属判据②的时间容差：只吸收「文件系统 mtime 粒度 / 运行期间时钟微调」，
# **不用来**放宽外来残骸判据 —— 那由归属判据①（运行前快照）精确兜住。
MTIME_TOLERANCE_NS = 60 * 10 ** 9

RUN_TIMEOUT = 180


class VerifyAllLogNotFound(Exception):
    """定位不到**本次运行自己的**检查项日志（消息里带全现场，绝不退化成空串/裸 Errno）。"""


def snapshot_pid_logs() -> dict:
    """运行**之前**的现场：`/tmp` 下 `verify-all-` 开头的日志 → `(inode, mtime_ns)`。

    这些文件不可能是本次运行的产物 —— PID 在进程存活期间唯一，同 PID 的既有文件只可能是
    **上一个复用该 PID 的进程**留下的残骸（issue #4158 根因之一）。
    """
    snap = {}
    for p in TMP.glob("verify-all-*.log"):
        try:
            st = p.stat()
        except FileNotFoundError:
            continue  # 与外部清理器赛跑：忽略即可（下面定位阶段会重新取）
        snap[p] = (st.st_ino, st.st_mtime_ns)
    return snap


def is_own_log(path: Path, pre: dict, run_start_ns: int) -> bool:
    """`path` 是不是**本次运行**写出来的日志（issue #4158 的归属判据）。

    ① 「运行前就在、且一个字节都没被写过」⇒ 只可能是同 PID 的外来残骸，**排除**；
    ② mtime 必须在本次运行窗口内（残骸定义上由已死进程写下 ⇒ 时间戳在过去）。
    """
    try:
        st = path.stat()
    except FileNotFoundError:
        return False
    if pre.get(path) == (st.st_ino, st.st_mtime_ns):
        return False
    return st.st_mtime_ns >= run_start_ns - MTIME_TOLERANCE_NS


def _fmt(paths) -> str:
    return "\n".join("      %s" % p for p in paths) or "      （无）"


def _locate_report(pid, pre, hits, own, console) -> str:
    """定位失败的**全现场**（判据②：报红必须给出定位信息，而不是一句「找不到」）。"""
    pattern = PID_LOG_GLOB % pid
    residual = sorted(p for p in pre if p.name.startswith("verify-all-%s-" % pid))
    all_tmp = sorted(TMP.glob("verify-all-*.log"))
    verdict = (
        "PID 通配一条都没命中 ⇒ 本次检查项**没写出日志**，或运行期间被外部清理器删掉了"
        if not hits else
        "命中里没有一条属于本次运行 ⇒ 全是同 PID 的外来残骸（PID 复用），已被归属过滤排除"
    )
    return "\n".join([
        "未能定位**本次运行自己的**检查项日志（issue #4158）—— "
        "断言不许退化成空串/裸 Errno，故在此给出全现场：",
        "  期望路径模式    : /tmp/%s" % pattern,
        "  本次运行 PID    : %s" % pid,
        "  PID 通配命中    : %d 条" % len(hits),
        _fmt(hits),
        "  其中属于本次    : %d 条" % len(own),
        _fmt(own),
        "  运行前既有(同PID): %d 条 —— 同前缀外来残骸，已排除" % len(residual),
        _fmt(residual),
        "  /tmp 同族全部   : %d 条" % len(all_tmp),
        _fmt(all_tmp),
        "  判定            : %s" % verdict,
        "  处置线索        : 清理/定位只许在**自己作用域内**（全局通配清理会把别的会话正在用的"
        "现场删掉；本仓 `tests/unit_ci_workflows/**` 已静态锁死这一形态）；不要在测试里 sleep 等日志。",
        "  ── 控制台原文 ──",
        console,
    ])


def locate_own_logs(pid, pre, run_start_ns, console="") -> list:
    """按 PID 通配定位 + **归属过滤**；拿不到**恰好一条**自己的日志 ⇒ `VerifyAllLogNotFound`。"""
    pattern = PID_LOG_GLOB % pid
    hits = sorted(TMP.glob(pattern))
    own = [p for p in hits if is_own_log(p, pre, run_start_ns)]
    if len(own) == 1:
        return own
    raise VerifyAllLogNotFound(_locate_report(pid, pre, hits, own, console))


def run_gate(repo, *, mode="gate", env=None, plant_foreign_stale=False,
             delete_own_log=False, timeout=RUN_TIMEOUT):
    """真跑 `bash verify-all.sh <mode>`，返回 `(退出码, 控制台原文, 检查项日志原文)`。

    日志的**定位/归属/清理口径单一实现**（`test_gate_uncommitted_noop.py` 与
    `test_growth_gate_fail_closed.py` 都调用本函数）。用
    `bash -c 'echo PID=$$; exec bash verify-all.sh …'` 取 PID：`exec` 不换 PID ⇒
    `$$` 即 `report()` 日志名里的那个 PID；`report()` 成功时**不打印路径**，故 PID 定位是主路，
    「日志: <path>」（本进程自己打印 ⇒ 归属无疑）是兜底。

    两个注入开关只服务红证，默认关：
    - `plant_foreign_stale=True`：让本次 subprocess 在 `exec` **之前**先落一份**同 PID 前缀**、
      slug 排序在前、mtime 回拨到过去的外来日志 —— 精确模拟「PID 复用留下的残骸」；
    - `delete_own_log=True`：在脚本跑完、定位之前把 PID 通配命中的日志删掉 ——
      精确模拟「外部清理器与本测试赛跑」（删在运行中与删在读完之前，可观测量相同：
      fd 指向已 unlink 的 inode ⇒ 路径消失）。
    """
    e = dict(os.environ)
    e.update(env or {})
    assert TMP.is_dir(), "本守卫依赖 /tmp 存放 report() 日志（CI 与 macOS 均有）"
    body = 'echo "PID=$$"; '
    if plant_foreign_stale:
        body += (
            'f="/tmp/verify-all-$$-%s.log"; printf \'%%s\\n\' \'%s\' > "$f"; '
            'touch -t 202001010000 "$f"; ' % (FOREIGN_SLUG, FOREIGN_SENTINEL)
        )
    body += "exec bash verify-all.sh %s" % mode

    pre = snapshot_pid_logs()
    run_start_ns = time.time_ns()
    proc = subprocess.run(["bash", "-c", body], cwd=str(repo),
                          capture_output=True, text=True, env=e, timeout=timeout)
    out = "%s%s" % (proc.stdout, proc.stderr)
    m = re.search(r"^PID=(\d+)$", out, re.M)
    pid = m.group(1) if m else "?"
    if m:
        out = out.replace("PID=%s\n" % pid, "")

    hits = sorted(TMP.glob(PID_LOG_GLOB % pid)) if m else []
    if delete_own_log:
        for p in hits:
            p.unlink(missing_ok=True)
        hits = []
    own = [p for p in hits if is_own_log(p, pre, run_start_ns)]
    for mm in LOG_LINE_RE.finditer(out):  # 兜底：失败项自报路径（本进程打印 ⇒ 归属无疑）
        p = Path(mm.group("path"))
        if p.exists() and p not in own:
            own.append(p)

    if len(own) != 1:
        raise VerifyAllLogNotFound(_locate_report(pid, pre, hits, own, out))

    log_path = own[0]
    try:
        log = log_path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        raise VerifyAllLogNotFound(
            "检查项日志在**定位到之后、读取之前**被删掉了（外部清理器赛跑，issue #4158）：\n"
            + _locate_report(pid, pre, hits, own, out))
    if not log.strip():
        raise VerifyAllLogNotFound(
            "检查项日志为空（%s）—— 检查项没往日志写任何东西？\n%s" % (log_path, out)
            + "\n" + _locate_report(pid, pre, hits, own, out))

    log_path.unlink(missing_ok=True)          # 只清**本次运行自己的**现场（作用域内）
    if plant_foreign_stale and m:
        for p in TMP.glob(PID_LOG_GLOB % pid):  # 清掉本次自己种下的那份（精确 slug，非通配）
            if FOREIGN_SLUG in p.name:
                p.unlink(missing_ok=True)
    return proc.returncode, out, log


# ── 清理口径的静态守卫（issue #4158「要做 4」）─────────────────────────────────


def _unscoped_cleanup_offenders(root: Path) -> list:
    """扫出「`/tmp/verify-all-` 紧跟通配符」的 `(相对路径, 行号, 行原文)`。

    只剥 `#` 注释（本仓惯例），**不剥字符串** —— 被禁形态正是写在字符串里的
    （`+ "rm -f /tmp/…"`），剥字符串就永远扫不到它。故本文件正文按拼接构造写（见模块头）。
    """
    out = []
    for path in sorted(root.rglob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), 1):
            if UNSCOPED_TMP_LOG_PREFIX in line.split("#", 1)[0]:
                out.append((path.relative_to(root).as_posix(), i, line.strip()[:140]))
    return out


def test_no_unscoped_tmp_log_cleanup_in_test_dir():
    """`tests/unit_ci_workflows/**` 不得出现全局通配的 `/tmp` 日志清理（制造假红的源头）。"""
    offenders = _unscoped_cleanup_offenders(TEST_DIR)
    assert not offenders, (
        "以下位置用**全局通配**清理 `/tmp/verify-all-` 日志 —— 会删掉别的会话（含正在跑的 "
        "`./verify-all.sh`）正在用的现场 ⇒ 判据自己制造假红（issue #4158）：\n"
        + "\n".join("  %s:%d  %s" % o for o in offenders)
        + "\n改法：限定在自己作用域内（`$$` / 自建 tmpdir）。"
    )


def test_static_guard_can_fail_on_a_planted_offender(tmp_path):
    """判据**可失败**（不会红的断言 = 空断言）：种一份同族文件 ⇒ 守卫必须点名。"""
    d = tmp_path / "unit_ci_workflows"
    d.mkdir()
    planted = "# case_ids: MC-012\nCLEANUP = " + repr(
        "rm -f " + UNSCOPED_TMP_LOG_PREFIX + "-*.log") + "\n"
    (d / "test_planted.py").write_text(planted, encoding="utf-8")
    offenders = _unscoped_cleanup_offenders(d)
    assert offenders, "守卫对种下的全局通配清理**不报** ⇒ 判据空转（永远绿的假护栏）"
    assert offenders[0][0] == "test_planted.py" and offenders[0][1] == 2, (
        f"守卫命中的位置不对（要 file:line）：{offenders}")


# ── 定位口径的单元判据（① 残骸不误读 / ② 自己的日志消失要大声）────────────────


def _pid_scope(pid: str) -> str:
    return PID_LOG_GLOB % pid


def _named(pid: str, slug: str) -> Path:
    return TMP / _pid_scope(pid).replace("*", slug)


def test_locator_excludes_same_pid_stale_residual():
    """① 运行前就存在的同 PID 前缀残骸**不得**被当成自己的日志（PID 复用现场）。

    用本进程自己的 PID 当「被复用过的 PID」：残骸在运行前快照之内 ⇒ 归属判据①排除它。
    旧口径（只 `glob(PID)`）拿到 2 条 ⇒ `len(paths)==1` 假红，或取 `[0]` 读到哨兵。
    """
    pid = str(os.getpid())
    foreign, own = _named(pid, FOREIGN_SLUG), _named(pid, "QA-Growth-Gate-999")
    foreign.write_text(FOREIGN_SENTINEL + "\n", encoding="utf-8")
    try:
        pre = snapshot_pid_logs()          # 残骸**在**快照之内（= 上个进程的遗留）
        run_start_ns = time.time_ns()
        own.write_text("真实的检查项输出\n", encoding="utf-8")
        found = locate_own_logs(pid, pre, run_start_ns, "")
    finally:
        foreign.unlink(missing_ok=True)
        own.unlink(missing_ok=True)
    assert [p.name for p in found] == [own.name], (
        f"定位到 {[p.name for p in found]} —— 同 PID 的外来残骸被当成自己的日志了"
    )


def test_locator_fails_loudly_when_own_log_is_gone():
    """② 自己的日志不存在 ⇒ 大声报错 + 全现场（**不是**空 glob 断言，也不是裸 `Errno 2`）。"""
    pid = str(os.getpid())
    foreign = _named(pid, FOREIGN_SLUG)
    foreign.write_text(FOREIGN_SENTINEL + "\n", encoding="utf-8")
    try:
        pre = snapshot_pid_logs()
        run_start_ns = time.time_ns()
        with pytest.raises(VerifyAllLogNotFound) as ei:
            locate_own_logs(pid, pre, run_start_ns, "控制台原文占位")
    finally:
        foreign.unlink(missing_ok=True)
    msg = str(ei.value)
    assert _pid_scope(pid) in msg, f"报错必须给出**期望路径模式**：\n{msg}"
    assert foreign.name in msg, f"报错必须点出被排除的同前缀残骸（排查线索）：\n{msg}"
    assert "控制台原文占位" in msg, f"报错必须带上控制台原文：\n{msg}"
    assert "/tmp" in msg and "清理" in msg, f"报错必须给出 /tmp 现场与处置线索：\n{msg}"
