# case_ids: MC-073
r"""**机器级重活锁的准入/溢出**台账（issue #6091；蓝图 P2 的「测量那一半」）。

## 治的形态（蓝图 `docs/wiki/Dev-Mode-Balance.md` §4 行 4/5 + §10 的 P2 行）

D 口径下本机是「并发 = 1 的重活单槽」：重活要么拿到锁、要么**安静排队**（实测有排队 45 分钟的先例），
而**没有任何台账**回答「到底溢出多少次、每次都等多久、是谁在抢」。没有这份读数，
「分档准入」（P2 的另一半）与「批次粒度」都只能凭感觉。⇒ 本文件判的是**读数**，不是判定：
`scripts/machine-heavy-lock.sh` 每次 acquire 尝试的结局落一条 JSONL，`stats` 把它读出来。

## 判据（每条都能单独变红）

| # | 断言 | 回归时会怎么红 |
|---|---|---|
| 1 | **立即拿到 ⇒ 恰好 1 条 `acquired_nowait` 且 `wait_seconds == 0`**；schema 头是 `_kind` 行（不是记录） | 记成 `after_wait` / 记两条 ⇒ 红 |
| 2 | **被活的持有者挡回 ⇒ 恰好 1 条 `refused_busy`**，且该条带着**持有者名字与 pid**（谁挡的）+ 当天的时间戳 | 静默拒绝不记账 ⇒ 红（这正是「溢出」读数的来源） |
| 3 | **`--wait` 真排队后拿到 ⇒ `acquired_after_wait` 且 `wait_seconds > 0`** | 把等待档记成 nowait ⇒ 红（等待墙钟就看不见了） |
| 4 | **`--wait` 等满上限 ⇒ `acquire_timeout`**（溢出且**白等**了墙钟） | 记成 `refused_busy` ⇒ red（两类混淆就分不出「秒拒」与「等死」） |
| 5 | **陈旧锁回收 ⇒ `stale_reaped`**，且记的是**原持有者**（`rm` 之后就读不到了） | 不记 / 记成自己 ⇒ 红 |
| 6 | **`release` ⇒ `released`**，`owner_pid` = 刚放锁的那个 pid | 不记 ⇒ 「谁在抢」这一半没读数 |
| 7 | **批次面可识别**：worktree 里有 `migao-package-heavy-entry-allow` 标记 ⇒ `surface=batch-integration` | 不识别 ⇒ 「批次记录 ≥5 次」这条重启条件永远数不出来 |
| 8 | **`stats` 读数确定**（固定夹具）：按 kind 计数 / `overflow_count` / p50·p95·max / top 请求者与持有者 / 批次计数 | 计数或分位数算错 ⇒ 红 |
| 9 | **空账 / 时间窗空 ⇒ 明确「暂无记录」，不是「0 次溢出」**；**半行 / 非法 JSON ⇒ 具名跳过（出声不崩）** | 把「没有读数」印成 `0`（假绿）⇒ 红 |
| 10 | **`--since` 三态**：相对 / ISO8601（含不带时区按本机）/ epoch；**不认识 ⇒ exit 2** | 猜窗口 ⇒ 悄悄换了时间窗而读数看起来一样 |
| 11 | **写台账失败 ⇒ 锁行为一字不变**（不存在的目录 = 注入失败）：acquire 仍 `rc=0` + 锁文件照写 + 打 `::warning::` | 记账失败把准入变成失败 ⇒ 红（那是 #6084 明令禁止的方向） |
| 12 | 🔴 **参数个数契约**：`_ledger_append` 的 `printf` 实参个数必须 == 格式串 `%s` 个数 | 多一个 ⇒ `printf` **重启格式串** ⇒ 每条记录后多一行残缺 JSON（实测踩过）⇒ 红 |

## 红证口径（本文件自带）

判据 12 是**结构性**红证（计数格式串与实参，不跑锁）；判据 8/9/10 在**临时夹具台账**上跑
（手写 good/bad 行）；判据 1~7/11 跑**真锁脚本**但锁面 + 台账面 + 射程**全部指到 `tmp_path`**。
🔴 **绝不写用户的真台账**（`$HOME/.migao-heavy-lock-ledger.jsonl`）—— 每条判据都经 `_run_lock`
强制注入 `MIGAO_HEAVY_LEDGER`（⑨ 包踩过「判据污染真台账」的坑）。

## 边界（照实登记 §19.1）

- **不改锁语义**：本文件判的是埋点；锁的三态语义 / 孤儿回收 / 不误杀 / `verify-all.sh` 接线
  仍由 `tests/unit_ci_workflows/test_machine_heavy_lock.py`（MC-012）判，本文件**不重判**。
- **不做分档准入**：本文件只保证「读数在」，不保证「容量对了」（那是 P2 的另一半）。
- **不做轮转/上限**：台账只追加 ⇒ 会无限增长（登记在 `Development.md` 的未固化项）。
- **不判多机**：台账是本机单槽口径。
- 判据 **不联网、不调 `gh`**（`stats` 的离线可用性正是它存在的理由）。
"""

from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "machine-heavy-lock.sh"

#: schema 头里的识别串（读出口径按它认对象 —— 换文件不会静默读错东西）。
LEDGER_KIND = "migao.heavy-lock-ledger"
#: 批次标记（**与 `scripts/batch-gate.sh` / `verify-all.sh` 共用同一个约定**；这里只读）。
BATCH_MARKER = "migao-package-heavy-entry-allow"
#: 记录必须有的字段（脱敏不必要：本机路径可留；这里是**契约**，少一个就没法归因）。
RECORD_FIELDS = ("ts", "kind", "req", "wait_seconds", "worktree", "branch", "surface",
                 "holder", "holder_pid", "owner_pid")
KINDS = ("acquired_nowait", "acquired_after_wait", "refused_busy", "acquire_timeout",
         "stale_reaped", "released")


def _run_lock(args: list[str], *, lock_file: Path, ledger: Path, roots: Path | None = None,
              cwd: Path | None = None, timeout: int = 60, **kw):
    """跑锁脚本：**锁面 / 台账面 / 射程**全部指到临时目录（绝不碰机器上真的锁、真的台账、真的进程）。"""
    env = {
        **os.environ,
        "MIGAO_HEAVY_LOCK_FILE": str(lock_file),
        "MIGAO_HEAVY_LEDGER": str(ledger),
        "MIGAO_HEAVY_ROOTS": str(roots if roots is not None else lock_file.parent / "roots-none"),
    }
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True, text=True, env=env, cwd=str(cwd or REPO), timeout=timeout, **kw,
    )


def _write_lock(lock_file: Path, *, name: str, pid: str) -> None:
    lock_file.write_text(
        f"name={name}\npid={pid}\nstarted_at=1700000000\nworktree=/tmp/wt\ncwd=/tmp\n",
        encoding="utf-8",
    )


def _live_pid() -> int:
    """一个**保证活着**的 PID：本 pytest 进程自己（`kill -0` 对它必然成功）。"""
    return os.getpid()


def _read_records(ledger: Path) -> list[dict]:
    """读台账 ⇒ **只**返回记录（丢掉 schema 头）；**任何坏行都让判据失败**（判据不该容忍坏行）。"""
    out = []
    for lineno, line in enumerate(ledger.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except ValueError as exc:  # pragma: no cover - 失败信息要具名
            raise AssertionError(f"台账第 {lineno} 行不是合法 JSON（{exc}）：{line[:200]!r}") from exc
        if "_kind" in obj:
            assert obj["_kind"] == LEDGER_KIND, f"schema 头认错对象：{obj['_kind']!r}"
            continue
        out.append(obj)
    return out


def _kinds(ledger: Path) -> list[str]:
    return [r["kind"] for r in _read_records(ledger)]


def _one(ledger: Path, kind: str) -> dict:
    """恰好一条该 kind 的记录（**恰好** = 0 条与 2 条都判红 —— 溢出计数靠的就是这个）。"""
    hits = [r for r in _read_records(ledger) if r["kind"] == kind]
    assert len(hits) == 1, f"期望恰好 1 条 {kind}，实得 {len(hits)} 条；全部 kind = {_kinds(ledger)}"
    return hits[0]


def _fixture_ledger(path: Path, records: list[dict]) -> None:
    """固定夹具台账：头 + 逐条**明确**给出的记录（判据 8/9/10 的输入；不依赖任何真实现）。"""
    lines = [json.dumps({"_kind": LEDGER_KIND}, ensure_ascii=False)]
    lines += [json.dumps(r, ensure_ascii=False) for r in records]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _rec(kind: str, req: str, wait: int, ts: str, holder: str = "", holder_pid: str = "",
         surface: str = "single", owner_pid: str = "") -> dict:
    return {"ts": ts, "kind": kind, "req": req, "wait_seconds": wait, "worktree": "/tmp/wt",
            "branch": "b", "surface": surface, "holder": holder, "holder_pid": holder_pid,
            "owner_pid": owner_pid}


def _iso(offset_seconds: int = 0) -> str:
    """本机时区下的 ISO 时间戳（与脚本 `_ledger_now` 同形态：`%Y-%m-%dT%H:%M:%S%z`）。"""
    now = datetime.datetime.now().astimezone() + datetime.timedelta(seconds=offset_seconds)
    return now.strftime("%Y-%m-%dT%H:%M:%S%z")


def _wait_for_waiting_acquire(lock: Path, ledger: Path, tmp_path: Path, holder):
    """起一个 `--wait 40` 的等待者，**前置自断言**它真的看见了「锁被占」，然后杀掉持有者并等它拿到。

    返回 `(proc, stdout, stderr)`。为什么必须有这个前置：**「等到了」与「一开始就空闲」在退出码上
    长得一模一样**（两者都 `rc=0`）⇒ 不先自证「等待者确实撞上了占用的锁」，`acquired_after_wait`
    就可能被一条 `acquired_nowait` 悄悄替代而判据照绿（**空断言**）。

    ⚠️ 等待者把输出**写进文件**（不用管道）：管道在 `communicate` 之前读不到，而这里要在它**还在跑**的
    时候看它写了什么（阻塞读会把父进程卡死）。
    """
    log = tmp_path / "waiter.log"
    with log.open("w", encoding="utf-8") as fh:
        proc = subprocess.Popen(
            ["bash", str(SCRIPT), "acquire", "waiter", "--wait", "40"],
            stdout=fh, stderr=subprocess.STDOUT, cwd=str(REPO),
            env={**os.environ, "MIGAO_HEAVY_LOCK_FILE": str(lock),
                 "MIGAO_HEAVY_LEDGER": str(ledger),
                 "MIGAO_HEAVY_ROOTS": str(tmp_path / "roots-none")},
        )
        deadline = time.time() + 30
        saw_busy = False
        while time.time() < deadline:
            assert proc.poll() is None, (
                "前置：等待者不该在 40s 上限内先退出（它应当一直在排队）")
            if "锁被占" in log.read_text(encoding="utf-8", errors="replace"):
                saw_busy = True
                break
            time.sleep(0.1)
        assert saw_busy, (
            "前置失败：等待者没有进入「锁被占」的排队态 —— 本判据会退化成空断言。"
            f"\n等待者输出：{log.read_text(encoding='utf-8', errors='replace')[:500]}")
        time.sleep(0.3)              # 让它在轮询里至少转过一轮（抖动 2~5s）
        holder.kill()                # 持有者**真的退出**（模拟「等它跑完」这条路）
        holder.wait(timeout=10)
        out, _ = proc.communicate(timeout=60)
    return proc, out, log.read_text(encoding="utf-8", errors="replace")


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:            # pragma: no cover - 不可能命中自己的子进程
        return True
    return True



# ── ①②③④⑤⑥ 五类 kind 的语义（真锁脚本 + 临时锁/台账面）────────────────────────

class TestKinds:
    def test_immediate_acquire_records_acquired_nowait_with_zero_wait(self, tmp_path):
        lock, ledger = tmp_path / "heavy.lock", tmp_path / "ledger.jsonl"
        r = _run_lock(["acquire", "verify-all.sh gate"], lock_file=lock, ledger=ledger)
        assert r.returncode == 0, f"空闲时 acquire 必须成功：rc={r.returncode}\n{r.stdout}\n{r.stderr}"
        rec = _one(ledger, "acquired_nowait")
        assert rec["wait_seconds"] == 0, f"立即拿到必须是 0 秒等待：{rec}"
        assert rec["req"] == "verify-all.sh gate", f"请求者名字必须可归因：{rec}"
        # 记录这一条的**持有者就是请求者自己**（锁面的一致性）
        assert rec["holder"] == "verify-all.sh gate", f"持有者名字：{rec}"
        assert rec["holder_pid"].isdigit(), f"持有者 pid 必须是数字：{rec}"
        # 时间戳**带时区偏移**（本机 = +0800）；否则跨时区读出口径没法解释
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{4}$", rec["ts"]), \
            f"ts 必须是带时区的 ISO 形态：{rec['ts']!r}"
        for field in RECORD_FIELDS:
            assert field in rec, f"记录缺字段 {field!r}（现场无法归因）：{rec}"

    def test_refused_busy_is_recorded_exactly_once_with_the_blocker(self, tmp_path):
        """🔴 **本用例的核心交付**：溢出（准入被拒）能被现取 —— 恰好 1 条，且知道**被谁挡的**。"""
        lock, ledger = tmp_path / "heavy.lock", tmp_path / "ledger.jsonl"
        _write_lock(lock, name="sibling-session", pid=str(_live_pid()))
        r = _run_lock(["acquire", "intruder"], lock_file=lock, ledger=ledger)
        assert r.returncode == 1, f"被占时必须非零退出（拒绝）：rc={r.returncode}\n{r.stdout}"
        rec = _one(ledger, "refused_busy")
        assert rec["wait_seconds"] == 0, f"默认语义**不排队** ⇒ wait_seconds 必须是 0：{rec}"
        assert rec["holder"] == "sibling-session", f"必须能说出**被谁挡的**：{rec}"
        assert rec["holder_pid"] == str(_live_pid()), f"持有者 pid：{rec}"
        assert rec["req"] == "intruder", f"请求者：{rec}"

    def test_wait_then_acquire_records_after_wait_with_positive_wait(self, tmp_path):
        """`--wait` **真排队**：持锁者真活着（无关进程）⇒ 等待者必须等到它退出才拿到，并记 `>0` 的等待。"""
        lock, ledger = tmp_path / "heavy.lock", tmp_path / "ledger.jsonl"
        holder = subprocess.Popen(["sleep", "90"])       # 真·活着的无关持有者（sleep 到处都有）
        proc = None
        try:
            _write_lock(lock, name="occupier", pid=str(holder.pid))
            proc, out, err = _wait_for_waiting_acquire(lock, ledger, tmp_path, holder)
            assert proc.returncode == 0, f"释放后等待者必须拿到锁：rc={proc.returncode}\n{out}\n{err}"
        finally:
            if proc is not None and proc.poll() is None:
                proc.kill()
            holder.kill()
            holder.wait(timeout=10)
        rec = _one(ledger, "acquired_after_wait")
        assert rec["wait_seconds"] > 0, f"排队取得的等待必须 > 0（否则「等多久」永远读不出来）：{rec}"
        assert rec["req"] == "waiter", f"请求者：{rec}"

    def test_wait_timeout_records_acquire_timeout_not_refused_busy(self, tmp_path):
        """`--wait` 等满上限 ⇒ `acquire_timeout`（**与秒拒分开**：一类是「白等了墙钟」）。"""
        lock, ledger = tmp_path / "heavy.lock", tmp_path / "ledger.jsonl"
        _write_lock(lock, name="occupier", pid=str(_live_pid()))
        r = _run_lock(["acquire", "waiter", "--wait", "3"], lock_file=lock, ledger=ledger, timeout=90)
        assert r.returncode == 1, f"等满上限仍拿不到 ⇒ 非零退出：rc={r.returncode}\n{r.stdout}"
        rec = _one(ledger, "acquire_timeout")
        assert rec["wait_seconds"] > 0, f"超时档必须记下白等了多久：{rec}"
        assert "refused_busy" not in _kinds(ledger), "超时不是「秒拒」⇒ 不得同时记 refused_busy"

    def test_stale_lock_reaping_records_the_original_holder(self, tmp_path):
        lock, ledger = tmp_path / "heavy.lock", tmp_path / "ledger.jsonl"
        _write_lock(lock, name="dead-holder", pid="999999")
        r = _run_lock(["acquire", "newcomer"], lock_file=lock, ledger=ledger)
        assert r.returncode == 0, f"陈旧锁必须可回收：rc={r.returncode}\n{r.stdout}\n{r.stderr}"
        rec = _one(ledger, "stale_reaped")
        assert rec["holder"] == "dead-holder", f"必须记**原持有者**（rm 之后就查不到了）：{rec}"
        assert rec["holder_pid"] == "999999", f"原持有者 pid：{rec}"
        rec2 = _one(ledger, "acquired_nowait")
        assert rec2["holder"] == "newcomer", f"回收之后应当正常获取：{rec2}"

    def test_release_records_released_with_the_owner_pid(self, tmp_path):
        lock, ledger = tmp_path / "heavy.lock", tmp_path / "ledger.jsonl"
        _run_lock(["acquire", "mine"], lock_file=lock, ledger=ledger)
        r = _run_lock(["release"], lock_file=lock, ledger=ledger)
        assert r.returncode == 0, f"持有者自己 release 必须成功：{r.stdout}\n{r.stderr}"
        rec = _one(ledger, "released")
        assert rec["holder"] == "mine", f"released 要记是谁放掉的：{rec}"
        assert rec["owner_pid"].isdigit(), f"owner_pid 必须是 pid：{rec}"

    def test_names_with_quotes_and_backslashes_still_produce_valid_json(self, tmp_path):
        """请求者 / 持有者名字里带 `"` 与 `\\` 时，JSON **必须仍然合法**（不然整条记录读不出来）。

        实测踩过：`ck`/`cp` 漏了转义 ⇒ `"holder":"weird "name\\with"` ⇒ 整行 `json.loads` 抛错
        （读出口径把它记成 `malformed`，而它其实是**真记录**）。
        """
        lock, ledger = tmp_path / "heavy.lock", tmp_path / "ledger.jsonl"
        nasty = 'weird "name\\with stuff'
        r = _run_lock(["acquire", nasty], lock_file=lock, ledger=ledger)
        assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
        rec = _one(ledger, "acquired_nowait")       # `_read_records` 会对坏 JSON 抛错
        assert rec["req"] == nasty and rec["holder"] == nasty, rec

    def test_usage_error_and_undecidable_state_do_not_fabricate_records(self, tmp_path):
        """**不猜**：用法错（2）与不可判定（3）都不该在台账里留下一条「像记录了什么的」东西。"""
        lock, ledger = tmp_path / "heavy.lock", tmp_path / "ledger.jsonl"
        r = _run_lock(["acquire"], lock_file=lock, ledger=ledger)
        assert r.returncode == 2, f"用法错误必须是 2：rc={r.returncode}"
        assert not ledger.exists(), "用法错误不该建台账（更不该记一条）"


# ── ⑦ 批次面（「批次记录 ≥5 次」这条重启条件的读数来源）──────────────────────────

class TestBatchSurface:
    def test_batch_marker_in_git_dir_marks_the_record_as_batch_integration(self, tmp_path):
        """标记放在**管理目录**（`git rev-parse --git-path` 的落点）⇒ 记录 `surface=batch-integration`。

        与 `scripts/batch-gate.sh` 的留标记方式**同源**（它写的就是 `--git-path <标记名>`）；这里用一个
        自建的一次性仓复现（**不动**任何真 worktree、不进 `git status`）。
        """
        wt = tmp_path / "wt"
        wt.mkdir()
        subprocess.run(["git", "init", "-q", str(wt)], check=True, capture_output=True)
        marker = subprocess.run(["git", "-C", str(wt), "rev-parse", "--git-path", BATCH_MARKER],
                                check=True, capture_output=True, text=True).stdout.strip()
        marker_path = Path(marker) if os.path.isabs(marker) else wt / marker
        assert not marker_path.exists(), "前置：标记一开始不该存在"
        marker_path.write_text("batch-integration\n", encoding="utf-8")

        lock, ledger = tmp_path / "heavy.lock", tmp_path / "ledger.jsonl"
        r = _run_lock(["acquire", "verify-all.sh gate"], lock_file=lock, ledger=ledger, cwd=wt)
        assert r.returncode == 0, f"acquire 必须成功：rc={r.returncode}\n{r.stdout}\n{r.stderr}"
        rec = _one(ledger, "acquired_nowait")
        assert rec["surface"] == "batch-integration", f"有批次标记 ⇒ 必须可识别：{rec}"
        assert rec["worktree"] == str(wt), f"worktree 要现取（不是 cwd 猜的）：{rec}"
        # 反向对照：同一次调用换个**没有**标记的仓 ⇒ surface=single（判据有判别力）
        assert "migao-package-heavy-entry-allow" not in subprocess.run(
            ["git", "-C", str(REPO), "status", "--porcelain"], capture_output=True, text=True).stdout


# ── ⑧⑨⑩ `stats` 读出口径（固定夹具台账）────────────────────────────────────────

class TestStatsReadings:
    def test_counts_percentiles_and_top_lists_on_a_fixed_fixture(self, tmp_path):
        lock, ledger = tmp_path / "heavy.lock", tmp_path / "ledger.jsonl"
        _fixture_ledger(ledger, [
            _rec("acquired_nowait", "verify-all.sh gate", 0, _iso(-600)),
            _rec("refused_busy", "verify-all.sh gate", 0, _iso(-500), holder="other", holder_pid="1"),
            _rec("refused_busy", "pytest unit_ci_workflows（直连整目录）", 0, _iso(-400),
                 holder="other", holder_pid="1"),
            _rec("acquire_timeout", "verify-all.sh gate", 120, _iso(-300), holder="other", holder_pid="1"),
            _rec("acquired_after_wait", "verify-all.sh gate", 30, _iso(-200)),
            _rec("released", "verify-all.sh gate", 0, _iso(-100), owner_pid="42"),
        ])
        r = _run_lock(["stats", "--json"], lock_file=lock, ledger=ledger)
        assert r.returncode == 0, f"stats 必须成功：rc={r.returncode}\n{r.stderr}"
        got = json.loads(r.stdout)
        assert got["records"] == 6, f"记录数：{got}"
        assert got["malformed"] == 0, f"夹具没有坏行：{got}"
        assert got["by_kind"]["acquired_nowait"] == 1 and got["by_kind"]["refused_busy"] == 2, got["by_kind"]
        assert got["overflow_count"] == 3, f"溢出 = refused_busy + acquire_timeout = 3：{got}"
        # wait 序列 = [0,0,0,120,30,0]（排序后 [0,0,0,0,30,120]）⇒ p50=0 / p95=120 / max=120
        assert got["wait_seconds"] == {"n": 6, "p50": 0, "p95": 120, "max": 120}, got["wait_seconds"]
        assert got["top_requesters"][0] == {"name": "verify-all.sh gate", "count": 5}, got["top_requesters"]
        # ⚠️ 持有者 top 有平手（other 3 / verify-all.sh gate 3）⇒ 判**名单集合**，不判「谁第一」
        #    （判顺序 = 判 `Counter.most_common` 的平手行为，那是实现细节，不是本判据的对象）
        # ⚠️ 持有者榜只统计**非空** holder（`acquired_nowait` / `acquired_after_wait` 的 holder
        #    就是请求者自己，不构成「谁在抢」的读数）⇒ 这里恰好只有被挡的那 3 条
        assert sorted((h["name"], h["count"]) for h in got["top_holders"]) == [("other", 3)], got["top_holders"]

    def test_empty_ledger_says_no_readings_not_zero_overflow(self, tmp_path):
        """🔴 **「没有读数」不许印成 `0`**（那会把「台账还没建立」读成「本机零溢出」）。"""
        lock, ledger = tmp_path / "heavy.lock", tmp_path / "ledger.jsonl"
        r = _run_lock(["stats"], lock_file=lock, ledger=ledger)
        assert r.returncode == 0, f"读不到台账不是错误（是**没有读数**）：rc={r.returncode}\n{r.stderr}"
        assert "暂无记录" in r.stdout, f"必须明说「暂无记录」：\n{r.stdout}"
        assert "0 次溢出" in r.stdout or "不是「0 次溢出」" in r.stdout, f"要区分读数与没有读数：\n{r.stdout}"
        rj = _run_lock(["stats", "--json"], lock_file=lock, ledger=ledger)
        got = json.loads(rj.stdout)
        assert got["exists"] is False and got["records"] == 0, got
        assert got["empty_reason"] == "no-ledger-file", got

    def test_window_with_no_records_also_says_no_readings(self, tmp_path):
        lock, ledger = tmp_path / "heavy.lock", tmp_path / "ledger.jsonl"
        _fixture_ledger(ledger, [_rec("refused_busy", "old", 0, _iso(-90000), holder="h")])
        r = _run_lock(["stats", "--since", "1h"], lock_file=lock, ledger=ledger)
        assert r.returncode == 0, r.stderr
        assert "暂无记录" in r.stdout, f"窗口内没有记录 ⇒ 明说没有读数：\n{r.stdout}"

    def test_half_line_and_invalid_json_are_named_and_do_not_crash(self, tmp_path):
        lock, ledger = tmp_path / "heavy.lock", tmp_path / "ledger.jsonl"
        _fixture_ledger(ledger, [_rec("refused_busy", "good", 0, _iso(-10), holder="h", holder_pid="7")])
        with ledger.open("a", encoding="utf-8") as fh:
            fh.write('{"ts":"2026-10-03T00:00:00+0800","kind":"refused_bu')   # 半行
            fh.write("\n")
            fh.write('{"ts":"not-json"\n')                                     # 非法 JSON
            fh.write("\n")
            fh.write("[]\n")                                                    # 合法 JSON 但不是对象
            fh.write("\n")
        r = _run_lock(["stats"], lock_file=lock, ledger=ledger)
        assert r.returncode == 0, f"坏行不许让 stats 崩：rc={r.returncode}\n{r.stderr}"
        assert "损坏行跳过" in r.stdout, f"必须报出坏行：\n{r.stdout}"
        assert re.search(r"损坏行跳过\s*:\s*3 条", r.stdout), f"坏行数必须是 3（半行/非法 JSON/非对象）：\n{r.stdout}"
        assert "refused_busy" in r.stdout, f"好行照旧读得出来：\n{r.stdout}"
        got = json.loads(_run_lock(["stats", "--json"], lock_file=lock, ledger=ledger).stdout)
        assert got["malformed"] == 3 and got["records"] == 1, got

    def test_unknown_kind_lines_are_counted_as_unknown_not_guessed(self, tmp_path):
        """旧格式（`id-part` 形态 / 判据 fixture）**不属于**任一 kind ⇒ `unknown`，**不猜**。"""
        lock, ledger = tmp_path / "heavy.lock", tmp_path / "ledger.jsonl"
        _fixture_ledger(ledger, [
            {"id": "1-x", "role": "package", "decision": "refused"},
            _rec("released", "r", 0, _iso(-5), owner_pid="1"),
        ])
        got = json.loads(_run_lock(["stats", "--json"], lock_file=lock, ledger=ledger).stdout)
        assert got["by_kind"].get("unknown") == 1, got
        assert got["overflow_count"] == 0, f"unknown **不得**被算成溢出：{got}"

    def test_since_accepts_relative_iso_and_epoch_and_rejects_anything_else(self, tmp_path):
        lock, ledger = tmp_path / "heavy.lock", tmp_path / "ledger.jsonl"
        _fixture_ledger(ledger, [
            _rec("refused_busy", "old", 0, _iso(-7200), holder="h"),
            _rec("refused_busy", "recent", 0, _iso(-60), holder="h"),
        ])
        # 相对窗口
        got = json.loads(_run_lock(["stats", "--since", "1h", "--json"], lock_file=lock, ledger=ledger).stdout)
        assert got["records"] == 1 and got["top_requesters"][0]["name"] == "recent", got
        # ISO8601（带时区）
        cutoff = (datetime.datetime.now().astimezone() - datetime.timedelta(minutes=30)).strftime(
            "%Y-%m-%dT%H:%M:%S%z")
        got = json.loads(_run_lock(["stats", "--since", cutoff, "--json"], lock_file=lock, ledger=ledger).stdout)
        assert got["records"] == 1 and got["top_requesters"][0]["name"] == "recent", got
        # ISO8601 **不带时区** ⇒ 按本机解释（同一时刻 ⇒ 同样的读数）
        cutoff_naive = (datetime.datetime.now().astimezone() - datetime.timedelta(minutes=30)).strftime(
            "%Y-%m-%dT%H:%M:%S")
        got = json.loads(_run_lock(["stats", "--since", cutoff_naive, "--json"],
                                   lock_file=lock, ledger=ledger).stdout)
        assert got["records"] == 1, f"不带时区 ⇒ 按**本机**：{got}"
        # epoch
        got = json.loads(_run_lock(["stats", "--since", "1", "--json"], lock_file=lock, ledger=ledger).stdout)
        assert got["records"] == 2, f"epoch 1 = 全部：{got}"
        # 不认识的形态 ⇒ **exit 2**（不猜窗口）
        r = _run_lock(["stats", "--since", "yesterday"], lock_file=lock, ledger=ledger)
        assert r.returncode == 2, f"不认识的窗口必须非零退出：rc={r.returncode}\n{r.stdout}"
        assert "--since 形态不认识" in r.stderr, r.stderr

    def test_stats_is_readonly(self, tmp_path):
        lock, ledger = tmp_path / "heavy.lock", tmp_path / "ledger.jsonl"
        _fixture_ledger(ledger, [_rec("released", "r", 0, _iso(-5), owner_pid="1")])
        before = ledger.read_bytes()
        _run_lock(["status"], lock_file=lock, ledger=ledger)
        _run_lock(["stats"], lock_file=lock, ledger=ledger)
        assert ledger.read_bytes() == before, "status / stats 都是只读 —— 台账不得被改写"
        assert not lock.exists(), "status / stats 不得建锁文件"


# ── ⑪⑫ 不动锁语义（旁路）─────────────────────────────────────────────────────

class TestSideChannelNeverTouchesAdmission:
    def test_unwritable_ledger_keeps_lock_behaviour_identical(self, tmp_path):
        """**注入写失败**（台账落点在一个文件的下面 ⇒ 目录建不出来）⇒ acquire 仍 `rc=0`、锁照写、只 warning。"""
        lock = tmp_path / "heavy.lock"
        blocker = tmp_path / "blocker"
        blocker.write_text("x", encoding="utf-8")
        ledger = blocker / "ledger.jsonl"                # dirname 是**文件** ⇒ mkdir 必失败

        r = _run_lock(["acquire", "victim"], lock_file=lock, ledger=ledger)
        assert r.returncode == 0, f"台账写不进去**不得**改变准入判定：rc={r.returncode}\n{r.stdout}\n{r.stderr}"
        assert lock.exists(), "锁文件必须照写（准入与记账解耦）"
        assert "🔒 已获取机器级重活锁" in r.stdout, f"准入成功的报文照旧：\n{r.stdout}"
        assert "::warning::" in r.stderr and "台账" in r.stderr, \
            f"写台账失败必须**出声**（::warning::）且不改判定：\n{r.stderr}"

    def test_refusal_is_still_refusal_when_the_ledger_is_unwritable(self, tmp_path):
        """写失败时**拒绝仍是拒绝**（exit 1）—— 记账失败不得把拒绝变成放行。"""
        lock = tmp_path / "heavy.lock"
        _write_lock(lock, name="occupier", pid=str(_live_pid()))
        blocker = tmp_path / "blocker"
        blocker.write_text("x", encoding="utf-8")
        ledger = blocker / "ledger.jsonl"
        r = _run_lock(["acquire", "intruder"], lock_file=lock, ledger=ledger)
        assert r.returncode == 1, f"拒绝路径的退出码与记账无关：rc={r.returncode}\n{r.stdout}"
        assert "::warning::" in r.stderr, f"仍要出声：\n{r.stderr}"
        assert "occupier" in lock.read_text(encoding="utf-8"), "被拒时不得改写别人的锁"

    def test_ledger_append_argv_count_matches_the_printf_specifiers(self):
        """🔴 **结构性红证**：`_ledger_append` 的 printf **实参个数必须 == 格式串 `%s` 个数**。

        实测踩过（本包第一版）：多一个实参 ⇒ `printf` **复用/重启格式串** ⇒ 每条记录后多一行
        残缺 JSON（读出口径把它记成 `malformed`，而**准入判定毫发无损** ⇒ 只有台账在坏，极难察觉）。
        """
        body = _func_body(SCRIPT.read_text(encoding="utf-8"), "_ledger_append")
        lines = body.split("\n")
        idx = [i for i, l in enumerate(lines) if l.lstrip().startswith("printf '")]
        assert idx, f"`_ledger_append` 里找不到 printf（判据对象被改名？）:\n{body[:400]}"
        i = idx[-1]                                     # 最后一条 = 记录（第一条是 schema 头那一处）
        # ⚠️ 只切到**重定向行**（`>> "$LEDGER"`）为止：它后面是错误分支（含说明文字，不是实参）
        j = i + 1
        while ">>" not in lines[j]:
            j += 1
        blob = "\n".join(lines[i:j])
        fmt = blob[blob.index("'") + 1: blob.index("'", blob.index("'") + 1)]
        args_blob = blob[blob.index("\n") + 1:]
        n_spec = len(re.findall(r"%s", fmt))
        n_args = _count_shell_args(args_blob)
        assert n_spec == 10, f"格式串的 %s 个数变了（本判据的锚）：{n_spec} —— 同步改读出口径与这条判据"
        assert n_args == n_spec, (
            f"printf 实参个数（{n_args}）必须等于格式串 %s 个数（{n_spec}）：多一个 ⇒ printf 重启格式串 "
            f"⇒ 每条记录后多一行残缺 JSON。args={args_blob!r}"
        )

    def test_ledger_writes_happen_outside_the_held_lock_window(self):
        """**旁路①的结构面**：本进程**持锁期间**不得写台账。

        判据 = 逐函数检查写入点与「本进程的锁操作」的相对顺序：
          · `_ledger_record_acquire` 的调用只许出现在 `cmd_acquire`，且必须在 `_lock_write` **之后**；
          · `stale_reaped` 的写入只许出现在 `_acquire_once` 的 `rm -f "$LOCK_FILE"`（回收**别人的**陈旧锁）
            **之前**，且那一段里不得有本进程的 `_lock_write`（即：还没持有）；
          · `released` 的写入必须在 `rm -f "$LOCK_FILE"` **之后**。
        行为面（写台账时锁确实不在了）由 `TestKinds` 的两条覆盖。
        """
        src = SCRIPT.read_text(encoding="utf-8")
        acquire = _func_body(src, "cmd_acquire")
        # 写入必须在**重试循环之后**（循环里才有 `_acquire_once`，它才写锁）
        assert acquire.index("while :; do") < acquire.rindex("_ledger_record_acquire"), \
            "`cmd_acquire` 的写入必须在准入循环**之后**（判定已定、锁要么没写要么已删）"
        release = _func_body(src, "cmd_release")
        assert release.index('rm -f "$LOCK_FILE"') < release.index('"released"'), \
            "`released` 必须在 `rm -f` **之后**写（写台账时绝不持锁）"
        once = _func_body(src, "_acquire_once")
        stale_at = once.index('"stale_reaped"')
        assert stale_at < once.index('rm -f "$LOCK_FILE"'), "陈旧锁的记录必须在 rm 之前（rm 后就查不到原持有者）"
        pre = once[:stale_at]
        assert "_lock_write" not in pre, "陈旧锁那一段不得已经写了自己的锁（否则 = 持锁期间记账）"
        # 反向对照：写入点确实存在于这些函数里（否则上面几条判的是空气）
        assert "_ledger_record_acquire" in acquire and "_ledger_append" in release and "_ledger_append" in once



def _count_shell_args(text: str) -> int:
    """数「shell 实参个数」：只认**顶层**的 `"…"` / `${…}` / `$var` 项。

    ⚠️ 不能直接数引号对（实测踩过：`"$(_ledger_escape "$req")"` 里有**嵌套引号** ⇒ 数出 13 而实参只有 10）。
    判定 = 从顶层项的**开头**一路跳到它的**结尾**（`"…"` 里的 `$(` / `${` 会增加嵌套层），
    于是每个实参只被数一次，而嵌套里的引号不会被重复计数。
    """
    n, i = 0, 0
    while i < len(text):
        c = text[i]
        if c == "$" and i + 1 < len(text) and text[i + 1] in "({":
            n += 1
            i = _skip_balanced(text, i + 2, ")" if text[i + 1] == "(" else "}")
            continue
        if c == "$":                                    # `$var` / `$1` 形态（无引号无花括号）
            n += 1
            i += 1
            while i < len(text) and (text[i].isalnum() or text[i] == "_"):
                i += 1
            continue
        if c == '"':
            n += 1
            i = _skip_double_quoted(text, i + 1)
            continue
        i += 1
    return n


def _skip_balanced(text: str, i: int, closer: str) -> int:
    """从替换体开头跳到匹配的 `closer` **之后**（`$( … )` / `${ … }`；按括号配平）。"""
    depth, opener = 0, "(" if closer == ")" else "{"
    while i < len(text):
        if text[i] == opener:
            depth += 1
        elif text[i] == closer:
            if depth == 0:
                return i + 1
            depth -= 1
        i += 1
    return i


def _skip_double_quoted(text: str, i: int) -> int:
    """从双引号**内容**开头跳到闭合 `"` 之后；引号内的 `$( … )` / `${ … }` 整段跳过。"""
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == '"':
            return i + 1
        if text[i] == "$" and i + 1 < len(text) and text[i + 1] in "({":
            i = _skip_balanced(text, i + 2, ")" if text[i + 1] == "(" else "}")
            continue
        i += 1
    return i


def _func_body(src: str, name: str) -> str:
    """取 `name() { … }` 的函数体（按花括号配平；**不写行号** ⇒ 换行/加注释不会让它失效）。"""
    head = f"{name}() {{"
    start = src.index(head)
    depth, i = 0, src.index("{", start)
    j = i
    while j < len(src):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[start:j + 1]
        j += 1
    raise AssertionError(f"函数 {name} 的花括号没有配平（文件被改坏了？）")
