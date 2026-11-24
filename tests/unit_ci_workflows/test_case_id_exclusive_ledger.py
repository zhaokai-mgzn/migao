# case_ids: MC-352
"""「加用例」在并行包里**不再需要人肉让号、也不再冲同一个数字**（issue #9090）。

## 两个病（2026-11-23 一晚上 5 次 rebase 的现场）

1. **取号不独占**：`scripts/next_case_id.py MC` 只**计算**一个号（候选 = main ∪ 全部 open PR ∪ 本工作区），
   两个包同时调用**必然**拿到同一个号 —— 工具自己的 docstring 早就登记「**不是互斥锁**」。
   ⇒ 让号靠人肉（rebase 后重取，再按本地报错原文改）。
2. **台账撞同一个数字**：`tests/unit_ci_workflows/case_machine_fail_channel_baseline.json` 的
   `entries.backend_contract_scoring_zero` 是**入库读数** —— 每加一条 `[backend-contract]` 用例
   （`expectations: []`）读数 +1 ⇒ 必须改**同一个 key** 并往 `history` **同一个尾部**追加一行
   ⇒ 两个并行包 100% 冲突。

## 本文件锁什么（每条都能单独变红）

| # | 判据 | 取法 | 红证 |
|---|---|---|---|
| 1 | **独占取号 · 离线**：`scripts/case_id_lease.py reserve MC` 在 `gh` **不可用**时也能给出一个号 | 真子进程 + 隔离租约目录 + `NCI_GH_BIN=<不存在>` | 只读分配器在同一环境下 `exit 3`（对照：它**必须**看不到在飞面就不给号） |
| 2 | 🔴 **并发取号必不撞**：N 个 `reserve` 同时起来 ⇒ N 个**互不相同**的号，且都不在语料里 | 真并发子进程（同一租约目录） | 把「原子占位」换成不排他的写（注入 `create=no-op`）⇒ 两个 racer 同号 |
| 3 | **旧路径的撞号现场**（判据 2 的判别力基线） | `allocate()` 纯函数两次调用 | 同一候选集两次都答同一个号（= 人肉让号的成因） |
| 4 | **分配器读租约**：租约占掉的号不得再被 `next_case_id.py` 发出去 | CLI + `gh` 替身（0 个 open PR）+ 预置租约 | 删掉租约来源 ⇒ 输出把被租的号当空闲 |
| 5 | 🔴 **台账入库读数已退役**：`entries` 只放**不变量**（`no_channel_total`），不许再存派生读数 | 读真锚点文件 + 判据的 `anchor_drift()` | 把读数写回 `entries` ⇒ 判据必红 |
| 6 | **加一条用例不动台账**：语料 +1 条 `[backend-contract]` 用例 ⇒ 锚点**一字不用改** | 内存构造（不写盘） | 旧口径（entries 存读数）在同一场景下必然「实测 ≠ 锚点」 |
| 7 | 🔴 **两个并行包的锚点不再相撞**（真 git） | `tmp_path` 里 `git init` + 两条分支 + 真 `git merge` | 旧形态（两分支各改同一个数字）⇒ **真冲突**；新形态 ⇒ 零冲突 |
| 8 | **归档只增不减**：`history` 234 行既有的历史**不许清空**、`no_channel_total` 恒 0 | 现取 | 清空 / 抬 `no_channel_total` ⇒ 红 |
| 9 | **`--pr` 顺带落 claim**（一次性动作）+ 幂等：同一 PR 重跑不新占号 | 临时 git 仓库（零污染本仓） | 同一个 PR 跑两次占两个号 ⇒ 红 |
| 10 | 🔴 **跨机互斥 = git ref 唯一性**：两台机器（本地 bare origin + 两个克隆）各自 reserve ⇒ 同号**第二次 push 被服务器拒绝**、自动顺延到下一个号 | 真 `git push` 到 `refs/tags/case-lease/<号>` | 用同一个号连推两次都成功 ⇒ 判红 |
| 11 | **离线仍可跑但要出声**：没有远端 ⇒ 照常给号 + 打印「跨机互斥不保证」 | 临时仓库（无 origin） | 静默给号（不打印那句）⇒ 红 |

## 边界（照实登记，别把它读成覆盖面更大的东西）

- ❌ **租约台账是机器级的**（`MIGAO_CASE_ID_LEASE_DIR`，默认 `~/.migao-case-id-leases`）⇒ 它只覆盖
  **同一台机器**上的并行包（含 `dev-worktree.sh add` 出来的多个 worktree、多个克隆）。
  **跨机器**仍要靠 `.github/cases/claims/**` + `test_case_id_claims.py` 的判据 2/7（PR 面）收口。
- ❌ **不清理陈旧租约**：一个被放弃的号会一直占着（只让尾部前进一位，不误伤）；本判据不判「该不该回收」。
- ❌ **看不到未 push 的别人的分支**（与只读分配器同一缺口）：租约是**自愿遵守**的台账 ——
  没跑 `reserve` 的包看不见。
- ❌ **同一语料文件尾部追加**仍可能文本冲突（issue #6255 的面，不在本单射程）。
- ❌ **只读分配器不读已发布的 ref**（它仍是离线计算 + 租约目录）⇒ 别人机器上的号它看不到；
  真仲裁在 `reserve` 的 **push 被拒**那一步（所以「取号必须走 reserve」是硬规矩，见 docs §14.2）。
- ❌ **跨机层需要推送权限**：没有权限 / 离线 ⇒ 输出里明说「跨机互斥不保证」（判据 11），
  此时只剩 claim 台账 + `test_case_id_claims.py` 判据 2/7 兜底（与改前同口径）。
- ❌ 本判据**不改任何门禁的通过条件、不新增豁免**；既有 287 条用例、既有 claim 文件继续有效。
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_case_machine_fail_channel as judge  # noqa: E402  —— 锚点判据的**唯一**实现（不另写一把尺子）

SCRIPTS = REPO_ROOT / "scripts"
TOOL = SCRIPTS / "next_case_id.py"
LEASE_TOOL = SCRIPTS / "case_id_lease.py"
ANCHOR = REPO_ROOT / "tests" / "unit_ci_workflows" / "case_machine_fail_channel_baseline.json"
LEASE_DIR_ENV = "MIGAO_CASE_ID_LEASE_DIR"
ID_RE = re.compile(r"\b([A-Z]{2,4})-(\d{3,})\b")
#: `history` 归档的**存量地板**（issue #9090 要求：既有的 234 行历史不许清空 ⇒ 只许增长）。
HISTORY_ARCHIVE_FLOOR = 234
#: 并发放数（判据 2）：真起 N 个进程，全部同名前缀。
RACERS = 6


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, str(path))
    assert spec and spec.loader, f"加载不了 {path}（判据 fail-closed）"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _lease_module():
    assert LEASE_TOOL.is_file(), (
        f"缺写面搭档 {LEASE_TOOL.relative_to(REPO_ROOT)} ⇒ 取号仍然只能「算一个号」（并行必撞）"
    )
    return _load(LEASE_TOOL, "case_id_lease_under_test")


def _nci_module():
    return _load(TOOL, "nci_under_test")


PUBLISH_ENV = "MIGAO_CASE_ID_LEASE_PUBLISH"


def _env(lease_dir: Path, gh_bin: str | None = None, publish: bool = False) -> dict:
    """隔离环境：主线段走 `HEAD`（CI 是 fetch-depth: 1）、租约目录隔离、`gh` **默认不可用**。

    `publish=False`（默认）⇒ 关掉跨机层：**判据绝不把 tag 推到真远端**（跨机面用本地 bare 仓判）。
    """
    env = dict(os.environ)
    env["NCI_MAIN_REF"] = "HEAD"
    env[LEASE_DIR_ENV] = str(lease_dir)
    env[PUBLISH_ENV] = "1" if publish else "0"
    env["NCI_GH_BIN"] = gh_bin or str(Path(lease_dir) / "no-such-gh")
    return env


def _run(script: Path, args: list[str], env: dict, cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(script), *args],
                          capture_output=True, text=True, env=env, cwd=str(cwd))


def _answer(stdout: str) -> str:
    """取分配行里的号（`… → 取 MC-352`）；没有分配行 ⇒ 空串。"""
    hits = re.findall(r"→ 取 ([A-Z]{2,4}-\d{3,})", stdout)
    assert hits, f"输出里没有分配行（`→ 取 <号>`）：\n{stdout[-1500:]}"
    return hits[-1]


def _first_id(stdout: str) -> str:
    m = ID_RE.search(stdout)
    assert m, f"输出里没有号：\n{stdout[-1500:]}"
    return f"{m.group(1)}-{m.group(2)}"


def _gh_stub(tmp_path: Path) -> str:
    """0 个 open PR 的 `gh` 替身（只为让 `next_case_id.py` 的**联网面**返回「没有在飞 PR」）。"""
    stub = tmp_path / "gh-empty"
    stub.write_text("#!/usr/bin/env python3\nimport json\nprint(json.dumps([]))\n", encoding="utf-8")
    stub.chmod(0o755)
    return str(stub)


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com",
                           "-C", str(repo), *args], capture_output=True, text=True, check=check)


def _init_repo(repo: Path, files: dict[str, str]) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", "-b", "main")
    for rel, text in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")


# ══════════════════════════════════════════════════════════════════════════════
# 判据 1/2/3：独占取号（离线 + 并发）
# ══════════════════════════════════════════════════════════════════════════════

def test_reserve_works_offline_while_the_readonly_allocator_refuses(tmp_path):
    """判据 1：`reserve` 在 `gh` 不可用时**照样给号**；只读分配器同一环境必须 `exit 3`（对照）。

    这条同时钉住「取号不需要访问 GitHub」与「只读面的 fail-closed 一点没松」。
    """
    lease = tmp_path / "leases"
    env = _env(lease)
    reserved = _run(LEASE_TOOL, ["reserve", "MC"], env)
    assert reserved.returncode == 0, (
        f"离线取号失败（rc={reserved.returncode}）——「并行包不需要访问 GitHub」不成立：\n"
        f"{reserved.stdout}\n{reserved.stderr}"
    )
    cid = _first_id(reserved.stdout)
    assert ID_RE.fullmatch(cid), cid

    control = _run(TOOL, ["MC"], env)
    assert control.returncode == 3, (
        f"只读分配器在看不到在飞面时竟然给了号（rc={control.returncode}）⇒ 三态判据被放宽了：\n"
        f"{control.stdout}"
    )


def test_concurrent_reservations_are_mutually_distinct(tmp_path):
    """判据 2（核心牙齿）：N 个 `reserve` **同时**起来 ⇒ N 个互不相同的号。"""
    lease = tmp_path / "leases"
    env = _env(lease)
    procs = [subprocess.Popen([sys.executable, str(LEASE_TOOL), "reserve", "MC"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                              env=env, cwd=str(REPO_ROOT)) for _ in range(RACERS)]
    outs = [p.communicate() for p in procs]
    ids = []
    for (out, err), proc in zip(outs, procs):
        assert proc.returncode == 0, f"并发 reserve 失败：rc={proc.returncode}\n{out}\n{err}"
        ids.append(_first_id(out))
    assert len(set(ids)) == len(ids), (
        f"{RACERS} 个并行包拿到了**同一个号**：{ids} —— 号段没有独占（这正是人肉让号的成因）"
    )
    used = _nci_module().read_worktree().ids.get("MC", set())
    clashes = sorted(n for p, n in (cid.split("-") for cid in ids) if int(n) in used)
    assert not clashes, f"租约发出的号已在语料里：{clashes}"
    leases = sorted(p.name for p in lease.glob("MC-*.json"))
    assert len(leases) == RACERS, f"租约文件数 {len(leases)} ≠ {RACERS}（{leases}）"


def test_red_proof_without_the_atomic_lease_two_racers_share_one_number(tmp_path):
    """判据 2 的红证：把「原子占位」换成**不排他**的写（= 旧的「算一个号」行为）⇒ 两个 racer 同号。

    对照臂（真原子占位）⇒ 必不同。这条是**同一份实现**上的单变量对照，不是两套口径。
    """
    mod = _lease_module()
    lease = tmp_path / "leases"
    lease.mkdir()
    occupied = {"MC": set(range(1, 41))}
    racer = lambda: mod.reserve("MC", occupied, lease, create=lambda path, body: None,  # noqa: E731
                                publish=False)[0]
    assert racer() == racer(), "注入的「不排他写」竟然给出了不同号 ⇒ 判据抓不到撞号形态"
    # 对照臂：真 `O_CREAT|O_EXCL` ⇒ 两次必不同
    assert mod.reserve("MC", occupied, lease, publish=False)[0] != \
        mod.reserve("MC", occupied, lease, publish=False)[0]


def test_red_proof_the_compute_only_allocator_answers_the_same_number_twice(tmp_path):
    """判据 3：只读分配器**单独**跑两次 ⇒ 同一个号（旧路径的撞号现场，判据 2 的判别力基线）。

    对照臂：42 号是「把 41 号**独占**出去」之后的下一个答案 —— 独占只多花一次原子创建，
    换掉的是「两个包同时拿到 41」这一整类事故。
    """
    occupied = {"MC": set(range(1, 41))}
    alloc = _nci_module().allocate
    first, second = alloc(occupied, ["MC"])["MC"], alloc(occupied, ["MC"])["MC"]
    assert first == second == 41, (
        f"只读分配器在**同一份候选集**上给出了不同号（{first} / {second}）⇒ 本判据的前提变了")
    reserved, state = _lease_module().reserve("MC", occupied, tmp_path / "leases", publish=False)
    assert reserved == 41, f"租约占的号与该轮的候选不一致：{reserved}"
    assert state == "unpublished", "发布被注入关闭时状态必须是 unpublished（不许谎报 published）"
    occupied_after = _nci_module().merge_ids(occupied, {"MC": {reserved}})
    assert alloc(occupied_after, ["MC"])["MC"] == 42, (
        "租约占了号却看不到它 ⇒ 独占等于没做")


def test_allocator_never_hands_out_a_reserved_number(tmp_path):
    """判据 4：租约占掉的号，只读分配器不得再发出去（否则租约等于白写）。"""
    gh = _gh_stub(tmp_path)
    empty = _run(TOOL, ["MC"], _env(tmp_path / "l-empty", gh))
    assert empty.returncode == 0, f"rc={empty.returncode}\n{empty.stdout}\n{empty.stderr}"
    free = _answer(empty.stdout)

    lease = tmp_path / "l-reserved"
    lease.mkdir()
    (lease / f"{free}.json").write_text(json.dumps({"id": free, "at": "2026-11-24"}), encoding="utf-8")
    out = _run(TOOL, ["MC"], _env(lease, gh))
    assert out.returncode == 0, f"rc={out.returncode}\n{out.stdout}\n{out.stderr}"
    assert _answer(out.stdout) != free, (
        f"租约已占 {free}，分配器仍把它当空闲发出去 ⇒ 分配器没读租约台账\n{out.stdout[-1200:]}")
    assert "租约" in out.stdout, "证据行没有点出租约来源 ⇒ 人无法复算\n" + out.stdout[-1200:]


# ══════════════════════════════════════════════════════════════════════════════
# 判据 5/6/8：台账脱冲突（派生读数 + 归档只增）
# ══════════════════════════════════════════════════════════════════════════════

def test_anchor_stores_only_the_invariant_not_the_reading():
    """判据 5：`entries` 只放不变量；派生读数（每加一条用例就变的那个数字）**不许入库**。"""
    anchor = json.loads(ANCHOR.read_text(encoding="utf-8"))
    entries = anchor.get("entries") or {}
    assert entries == {"no_channel_total": 0}, (
        f"`entries` 仍是入库读数形态：{entries} —— 每加一条 `[backend-contract]` 用例都要改同一个 key "
        f"⇒ 并行包 100% 冲突（issue #9090 的第 2 个病）"
    )
    assert not judge.anchor_drift(entries, anchor.get("history") or [])


def test_red_proof_restoring_the_stored_reading_reds_the_judge():
    """判据 5 的红证：把读数写回 `entries`（改动前的形态）⇒ 判据必须红。"""
    anchor = json.loads(ANCHOR.read_text(encoding="utf-8"))
    entries = dict(anchor.get("entries") or {})
    entries["backend_contract_scoring_zero"] = judge.scoring_zero_total(judge._real_cases())
    drift = judge.anchor_drift(entries, anchor.get("history") or [])
    assert any("backend_contract_scoring_zero" in d for d in drift), (
        f"把派生读数写回 entries 却没判红 ⇒ 撞锚点的形态会原样回来：{drift}")


def test_adding_a_case_no_longer_touches_the_anchor():
    """判据 6：语料 +1 条 `[backend-contract]` 用例 ⇒ 锚点**一字不用改**。

    对照（旧口径）：`entries` 存读数时，同一场景下「实测 ≠ 锚点」必然红 —— 这就是一晚上 5 次
    「按本地报错原文重锚」的来源。
    """
    anchor = json.loads(ANCHOR.read_text(encoding="utf-8"))
    entries, history = anchor.get("entries") or {}, anchor.get("history") or []
    assert judge.anchor_drift(entries, history) == [], "前置：真锚点必须先是自洽的"

    cases = judge._real_cases()
    extra = {"id": "ZZ-909", "skip_reason": "[backend-contract] 由某测试验证",
             "expectations": [], "data_checks": [], "traces": {}}
    assert judge.scoring_zero_total([*cases, extra]) == judge.scoring_zero_total(cases) + 1, (
        "新增的 `[backend-contract]` 用例没有让读数 +1 ⇒ 本判据的场景与真语料的形态不符")
    assert judge.anchor_drift(entries, history) == [], (
        "加了一条用例，锚点就必须改 ⇒ 「加用例」在并行包里仍会撞同一个数字")

    old_stored = judge.scoring_zero_total(cases)
    assert old_stored != judge.scoring_zero_total([*cases, extra]), (
        "旧口径（entries 存读数）在同一场景下并不会红 ⇒ 判据 5/6 的对照臂是空的")


def test_history_archive_is_preserved_and_stays_zero():
    """判据 8：既有历史**不许清空**（既有 234 行是归档，只许增长），`no_channel_total` 恒 0。"""
    history = json.loads(ANCHOR.read_text(encoding="utf-8")).get("history") or []
    assert len(history) >= HISTORY_ARCHIVE_FLOOR, (
        f"`history` 只剩 {len(history)} 行（地板 {HISTORY_ARCHIVE_FLOOR}）—— 既有历史被清空了")
    assert history[0].get("backend_contract_scoring_zero") == 53, (
        f"归档首行不再是 #5079 的 53（现取 {history[0].get('backend_contract_scoring_zero')!r}）"
        f" ⇒ 出处被改写了")
    assert {row.get("no_channel_total") for row in history} == {0}, "历史里出现非 0 的真债务读数"


# ══════════════════════════════════════════════════════════════════════════════
# 判据 7：两个并行包的锚点不再相撞（真 git，两个临时分支）
# ══════════════════════════════════════════════════════════════════════════════

def _merge_conflicts(tmp_path: Path, base: dict[str, str], left: dict[str, str],
                     right: dict[str, str]) -> list[str]:
    """两个临时分支各改各的 ⇒ 真 `git merge` 的冲突文件清单（空 = 干净合并）。"""
    repo = tmp_path / "repo"
    _init_repo(repo, base)
    for branch, files in (("left", left), ("right", right)):
        _git(repo, "checkout", "-q", "main")
        _git(repo, "checkout", "-qb", branch)
        for rel, text in files.items():
            (repo / rel).write_text(text, encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", branch)
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", "-m", "m1", "left")
    proc = _git(repo, "merge", "--no-ff", "--no-edit", "right", check=False)
    conflicts = sorted(p for p in _git(repo, "diff", "--name-only", "--diff-filter=U",
                                       check=False).stdout.splitlines() if p)
    assert proc.returncode != 0 or not conflicts, f"合并失败但没有冲突文件：{proc.stderr}"
    return conflicts


def _anchor_text(entries: dict, history: list) -> str:
    return json.dumps({"entries": entries, "history": history}, ensure_ascii=False, indent=2) + "\n"


def test_red_proof_two_parallel_branches_collide_on_the_stored_reading(tmp_path):
    """判据 7 的红证（**旧形态**）：两个包各加一条用例 ⇒ 都改 `entries` 的同一个数字 ⇒ **真文本冲突**。"""
    history = [{"sha": "0" * 12, "date": "2026-11-01", "no_channel_total": 0,
                "backend_contract_scoring_zero": 341, "note": "基线"}]
    base = {".github/cases/anchor.json": _anchor_text(
        {"no_channel_total": 0, "backend_contract_scoring_zero": 341}, history)}
    left_row = {"sha": "a" * 12, "date": "2026-11-24", "no_channel_total": 0,
                "backend_contract_scoring_zero": 342, "note": "包 A 加了一条用例"}
    right_row = {"sha": "b" * 12, "date": "2026-11-24", "no_channel_total": 0,
                 "backend_contract_scoring_zero": 343, "note": "包 B 加了一条用例"}
    left = {".github/cases/anchor.json": _anchor_text(
        {"no_channel_total": 0, "backend_contract_scoring_zero": 342}, history + [left_row])}
    right = {".github/cases/anchor.json": _anchor_text(
        {"no_channel_total": 0, "backend_contract_scoring_zero": 343}, history + [right_row])}
    conflicts = _merge_conflicts(tmp_path, base, left, right)
    assert ".github/cases/anchor.json" in conflicts, (
        f"旧形态下两个并行包**没有**冲突（{conflicts}）⇒ 本判据的红证不成立；"
        f"issue #9090 的「一晚 5 次 rebase」也就无从解释")


def test_two_parallel_branches_no_longer_touch_a_shared_number(tmp_path):
    """判据 7（**新形态**）：同样两个包各加一条用例 ⇒ 锚点零改动 ⇒ 合并**零冲突**。

    语料落在**不同文件**上（同一文件尾部追加仍是 issue #6255 的面，见文件头「边界」）。
    """
    anchor = json.loads(ANCHOR.read_text(encoding="utf-8"))
    base = {
        ".github/cases/anchor.json": _anchor_text(anchor["entries"], anchor["history"]),
        ".github/cases/misc.yml": "  - id: MC-001\n",
        ".github/cases/order.yml": "  - id: OR-001\n",
    }
    left = {".github/cases/misc.yml": "  - id: MC-001\n  - id: MC-002\n"}
    right = {".github/cases/order.yml": "  - id: OR-001\n  - id: OR-002\n"}
    assert _merge_conflicts(tmp_path, base, left, right) == [], (
        "新形态下两个并行包仍冲突 ⇒ 派生读数与号段独占没有把摩擦消掉")


# ══════════════════════════════════════════════════════════════════════════════
# 判据 9：`--pr` 顺带落 claim（一次性动作）+ 幂等
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# 判据 10/11：跨机互斥 = git ref 唯一性（本地 bare origin 模拟两台机器）
# ══════════════════════════════════════════════════════════════════════════════

def _two_machines(tmp_path: Path, max_id: int = 350):
    """**两台机器**的现场：本地 bare `origin` + 两个独立克隆（各自独立的租约目录）。"""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-q", str(origin)], check=True, capture_output=True)
    _git(origin, "symbolic-ref", "HEAD", "refs/heads/main")
    seed = tmp_path / "seed"
    seed.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True, capture_output=True)
    cases = seed / ".github" / "cases"
    cases.mkdir(parents=True)
    (cases / "misc.yml").write_text(
        "".join(f"  - id: MC-{n:03d}\n" for n in range(1, max_id + 1)), encoding="utf-8")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-qm", "base")
    _git(seed, "remote", "add", "origin", str(origin))
    _git(seed, "push", "-q", "-u", "origin", "main")
    machines = []
    for name in ("machine-a", "machine-b"):
        clone = tmp_path / name
        subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True,
                       capture_output=True)
        machines.append(clone)
    return origin, machines


def test_cross_machine_second_publish_of_the_same_number_is_rejected(tmp_path):
    """判据 10：同号**第二次 push 必被服务器拒**；`reserve` 被拒后自动顺延到下一个号。"""
    _origin, (a, b) = _two_machines(tmp_path)
    first = _run(LEASE_TOOL, ["reserve", "MC"], _env(tmp_path / "lease-a", publish=True), cwd=a)
    assert first.returncode == 0, f"{first.stdout}\n{first.stderr}"
    assert _first_id(first.stdout) == "MC-351", first.stdout
    assert "已发布" in first.stdout and "refs/tags/case-lease/MC-351" in first.stdout, (
        f"发布成功却没有打印跨机证据行：{first.stdout}")

    # 现实形态：B 机器上有**自己的提交** ⇒ 用同一个号再推就是 non-FF ⇒ 服务器必拒
    (b / "work.txt").write_text("machine-b 自己的工作\n", encoding="utf-8")
    _git(b, "add", "-A")
    _git(b, "commit", "-qm", "b 自己的改动")
    dup = _git(b, "push", "--porcelain", "origin", "HEAD:refs/tags/case-lease/MC-351", check=False)
    both = (dup.stdout or "") + (dup.stderr or "")
    assert dup.returncode != 0 and ("[rejected]" in both or "already exists" in both), (
        f"同一个号**第二次** push 竟然成功了 ⇒ 跨机互斥不存在：{both}")

    # 边界（照实钉住）：两台机器**恰好在同一个提交**时，git 只回 `[up to date]`（不算新建）
    # ⇒ 实现必须把它当「被占」（否则同号会被两台机器同时认领）。
    state, detail = _lease_module().publish_state(a, "MC-351")
    assert state == "taken" and "up-to-date" in detail, (
        f"up-to-date 被当成了「发布成功」⇒ 同提交的两台机器会同时认领一个号：{state} / {detail}")

    second = _run(LEASE_TOOL, ["reserve", "MC"], _env(tmp_path / "lease-b", publish=True), cwd=b)
    assert second.returncode == 0, f"{second.stdout}\n{second.stderr}"
    assert _first_id(second.stdout) != "MC-351", f"被拒的号又被发出来 ⇒ 顺延没生效：{second.stdout}"
    assert _first_id(second.stdout) == "MC-352", second.stdout
    assert sorted(p.name for p in (tmp_path / "lease-b").glob("MC-*.json")) == ["MC-352.json"], (
        "被拒的号没有撤回本地租约 ⇒ 本机永久占着一个用不上的号")

    # 时间序（A 先成功、B 后被拒）：B 的撤回**只许撤自己的**，A 的号与 A 的远端占位都必须还在
    assert (tmp_path / "lease-a" / "MC-351.json").is_file(), (
        "B 的顺延把 A 的租约撤掉了 ⇒ 撤回逻辑误伤别人（A 先发布成功，号应当仍归 A）")
    assert _git(_origin, "show-ref", "refs/tags/case-lease/MC-351", check=False).returncode == 0, (
        "A 发布的 351 ref 消失了 ⇒ 跨机仲裁的占位被别人的失败清掉")
    state_a, _detail_a = _lease_module().publish_state(a, "MC-351")
    assert state_a == "taken", f"A 再发布自己的 351 竟然不是「已占」：{state_a}"


def test_offline_reserve_still_works_but_says_cross_machine_is_not_guaranteed(tmp_path):
    """判据 11：没有远端 ⇒ 照常给号，但**必须出声**「跨机互斥不保证」（离线不能冒充已发布）。"""
    repo = tmp_path / "repo"
    _init_repo(repo, {".github/cases/misc.yml": "  - id: MC-001\n"})
    out = _run(LEASE_TOOL, ["reserve", "MC"], _env(tmp_path / "leases", publish=True), cwd=repo)
    assert out.returncode == 0, f"{out.stdout}\n{out.stderr}"
    assert _first_id(out.stdout) == "MC-002", out.stdout
    assert "跨机互斥不保证" in out.stdout, f"离线给了号却没说「跨机不保证」⇒ 静默假绿：{out.stdout}"
    assert "已发布" not in out.stdout, out.stdout


def test_reserve_with_pr_writes_a_claim_and_is_idempotent(tmp_path):
    """判据 9：`reserve MC --pr N --title …` 一次动作 = 租约 + claim；同一 PR 重跑**不新占号**。"""
    repo = tmp_path / "repo"
    _init_repo(repo, {".github/cases/misc.yml": "  - id: MC-001\n"})
    env = _env(tmp_path / "leases")
    first = _run(LEASE_TOOL, ["reserve", "MC", "--pr", "9091", "--title", "夹具用例"], env, cwd=repo)
    assert first.returncode == 0, f"rc={first.returncode}\n{first.stdout}\n{first.stderr}"
    cid = _first_id(first.stdout)
    claim_path = repo / ".github/cases/claims" / f"9091-{cid}.json"
    assert claim_path.is_file(), f"没有落 claim 文件：{claim_path}（实际：{sorted((repo/'.github/cases').rglob('*'))}）"
    claim = json.loads(claim_path.read_text(encoding="utf-8"))
    assert claim["pr"] == 9091 and claim["id"] == cid, claim
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", claim["claimed_at"]), claim

    again = _run(LEASE_TOOL, ["reserve", "MC", "--pr", "9091", "--title", "夹具用例"], env, cwd=repo)
    assert again.returncode == 0, f"{again.stdout}\n{again.stderr}"
    assert _first_id(again.stdout) == cid, "同一 PR 重跑换了一个号 ⇒ 号会白白泄漏"
    claims = sorted(p.name for p in (repo / ".github/cases/claims").glob("*.json"))
    assert claims == [f"9091-{cid}.json"], f"重跑换/多占了 claim：{claims}"
