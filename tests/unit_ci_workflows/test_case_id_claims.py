# case_ids: MC-066
"""用例 id **取号登记台账**（claim）：并行开发下不再撞号（issue #6017，用户 2026-10-02 裁定方案 B）。

## 病（2026-10-02 一天**三次**撞号，有具名实证）

用例 `id` 是**全局唯一**登记键，而现行取号法 = 「现取 `origin/main` 最大号 + 1（再加"猜在飞 PR"）」
⇒ **并行下必然失效**。现场逐条记在 `.github/cases/misc.yml` 的 `MC-064` 的 `merge_log` 里
（起草取 `MC-062` ⇒ 被 #6001/#5976+#5977 占；让号到 `MC-063` ⇒ 被 #5983 占；再预判在飞 PR #5994
⇒ 跳成 `MC-065`）。形状是**预判在飞 PR** —— 那是不可靠启发式。

**症状形态**（诊断成本极高）：表现为 `.github/cases/misc.yml` 的**困惑冲突** + 生成物连带冲突，
而不是「你撞号了，请让号」—— 排查要靠 `git merge-tree`、逐条比对两侧用例块。

## 本文件锁什么（每一条都能单独变红）

| # | 判据 | 取法 | 红证 |
|---|---|---|---|
| 1 | **形态**：claim 文件名 `<PR号>-<CASE_ID>.json`、字段最小集齐全、文件名里的 `PR`/`CASE_ID` 与内容 `pr`/`id` 一致、`claimed_at` 是 `YYYY-MM-DD`；目录里出现非 claim 文件（除 `.gitkeep` / `README.md`）也判红 | 逐文件解析（纯静态） | 改错文件名 / 删字段 / 内容与文件名不一致 ⇒ 红 |
| 2 | **两 claim 同 id ⇒ 红**：**具名报出两个 PR 号** + 「后合入者让号」 | 按 `id` 分组 | 造两份同 id claim ⇒ 红 |
| 3 | **与已占号相撞 ⇒ 红**：claim 的 `id` 已在用例库被占用 ⇒ 报出该号 + 让号出口 | 用例库现取号集 ⇄ claim | 造 claim `MC-9xx` + 用例库里已有 `MC-9xx` ⇒ 红 |
| 4 | **陈旧即红**：claim 的 `id` 已进用例库（该 claim 已合并完成）而 claim 还在 ⇒ 红（台账**不许只增不减**） | 同上 + claim 的 `pr` ≠ 当前 PR | 造「main 侧遗留 claim」⇒ 红 |
| 5 | **占位不得超额**：每条 claim 的 `id` 必须在用例库里**有对应用例**；同一 PR 的 claim 数 ≤ **现取上限**（= 用例库现取条数；变更集不可得时的兜底，**不拍魔法数**） | 现取 | 造「claim 了一个没写用例的号」⇒ 红 |
| 6 | **负向对照**：没有 claim ⇒ 一条都不报（本台账是**新增可选面**，不能把不用的包判红） | —— | 空目录 ⇒ 全绿 |

## 为什么判据长这样（三条硬约束，逐条都踩过）

- 🔴 **纯静态**：CI 的 `ci workflow helper unit tests` 这个 job **只装 `pytest` + `pyyaml`**
  （不装 `pydantic` / `langchain_core` / `fastapi`）⇒ 本文件**零** ai-agent 依赖
  （自证 = `test_this_judgement_is_pure_static_and_never_skips`，AST 取 import 名）。
- 🔴 **禁 `try/except ImportError: pytest.skip`** —— 那会让判据在 CI 里**永远是空的**（"绿了但没跑"）。
- 🔴 **判据不查 GitHub / 不联网**（不用 `gh`）。⚠️ **也刻意不读 `origin/main`**：CI 的 `actions/checkout`
  是 `fetch-depth: 1`（先例与理由见 `tests/unit_ci_workflows/test_next_case_id_allocator.py` 的
  「判定方式是确定的」节）⇒ 读它会**因错的原因**变绿/变红，且让本机与 CI 得到不同读数。
  ⇒ 「**id 是否已进 main**」一律以**合并态近似**表达（见 `main_side_ids`）：合并态的用例库 ⊇ main 的用例库，
  再扣掉**本 PR 自己的号**（= 本 PR 的 claim 声明的号，设计上 1:1）。
  **精确的 main 侧读数**可由 `MIGAO_CASE_CLAIMS_MAIN_DIR` 注入（一个内含 `*.yml` 的目录；红证与判别力自证用它）。

## 边界（照实登记，**不要**把本判据读成覆盖面更大的东西）

- ❌ **看不到在飞分支**：别人的 open PR 上的 claim 不在我这棵树里 ⇒ 「两个在飞 PR 同时取到同一个号」
  只有在**其中一个合入 main 之后**才在我这棵树上现形（这正是 `MC-064` 的三次撞号的形状）。
- ❌ **「claim 了号、但还没写用例、而 main 恰好已有同号用例」这一角判不了**（近似口径把「本 PR 的号」扣掉了）；
  显形条件 = 早占号 + 对方已合并 + 本 PR 还没写用例。
- ❌ **变更集不可得**（不读 git / 不联网）⇒ 判据 5 一律用现取上限兜底；「占一堆号」的主要防线是
  「每条 claim 必须对应一条真用例」这一条，不是那个上限。
- ❌ **没有常驻守护跑在 main 上**（`pr-check` 只在 `pull_request` 触发）：本判据的陈旧面靠**下一个 PR**
  的合并态现形。
- ❌ 本判据**不改任何门禁的通过条件、不新增豁免**。
"""
from __future__ import annotations

import ast
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

#: 「用例号」的解析口径**复用仓内唯一实现**（不自写第二把尺子）：
#: `tests/unit_ci_workflows/test_dev_mode_failure_modes.py::case_id_lines`（它只依赖 stdlib + pyyaml ⇒ CI 装得上）。
from test_dev_mode_failure_modes import case_id_lines  # noqa: E402

CASES_REL = ".github/cases"
CLAIMS_REL = ".github/cases/claims"
#: 目录里允许存在的**非 claim** 文件（台账目录不是收破烂的 ⇒ 其余非 `*.json` 一律判红）。
ALLOWED_NON_CLAIM = (".gitkeep", "README.md")
#: claim 文件名 ↔ 内容的**双向绑定**（文件名含 PR 号 ⇒ 两个并行 PR 永远不写同一个文件 ⇒ 零文本冲突）。
CLAIM_FILE_RE = re.compile(r"^(?P<pr>[1-9][0-9]*)-(?P<cid>[A-Z]{2,6}-[0-9]{3,})\.json$")
CLAIMED_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
REQUIRED_FIELDS = ("id", "pr", "title", "claimed_at")
#: 注入点（与 `NCI_MAIN_REF` / `MG_GH_BIN` 同先例）：当前 PR 号 + **main 侧用例库目录**。
PR_ENV = "MIGAO_CASE_CLAIMS_PR"
MAIN_DIR_ENV = "MIGAO_CASE_CLAIMS_MAIN_DIR"
#: 本判据**不得**出现的依赖（CI 那个 job 只装 pytest + pyyaml）。
FORBIDDEN_IMPORTS = ("pydantic", "langchain_core", "langchain", "fastapi", "app")


# ─────────────────────────────────────────────────────────────────────────────
# 纯函数面（判据一律走纯函数；红证在**内存 / tmp_path** 里构造，不碰仓内文件）
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Claim:
    """一条 claim 登记（形态已合规）。"""

    file: str
    pr: int
    cid: str
    title: str


def scan_claims(claims_dir: Path) -> tuple[list[tuple[str, str]], list[str]]:
    """扫 claim 目录 ⇒ （`<仓库相对路径>` 与文本，目录形态违规）。

    目录不存在 **不是** 违规（本台账是新增可选面 ⇒ 没人用时必须全绿）。
    """
    entries: list[tuple[str, str]] = []
    problems: list[str] = []
    if not claims_dir.is_dir():
        return entries, problems
    for p in sorted(claims_dir.iterdir()):
        rel = f"{CLAIMS_REL}/{p.name}"
        if p.is_dir():
            problems.append(f"{rel}：claim 目录里不许有子目录")
            continue
        if p.name in ALLOWED_NON_CLAIM:
            continue
        if p.suffix != ".json":
            problems.append(f"{rel}：claim 目录里只许有 `<PR号>-<CASE_ID>.json`（已登记豁免：{list(ALLOWED_NON_CLAIM)}）")
            continue
        entries.append((rel, p.read_text(encoding="utf-8")))
    return entries, problems


def form_problems(entries: list[tuple[str, str]]) -> list[str]:
    """判据 1：文件名与内容的形态 + 双向绑定（每条都**具名**到文件 + 给出口）。"""
    problems: list[str] = []
    for rel, text in entries:
        name = Path(rel).name
        m = CLAIM_FILE_RE.match(name)
        if m is None:
            problems.append(f"{rel}：文件名不是 `<PR号>-<CASE_ID>.json` 形态 ⇒ 无法登记（改名）")
            continue
        try:
            obj = json.loads(text)
        except ValueError as e:
            problems.append(f"{rel}：不是合法 JSON（{e.__class__.__name__}）")
            continue
        if not isinstance(obj, dict):
            problems.append(f"{rel}：顶层必须是对象")
            continue
        missing = [k for k in REQUIRED_FIELDS if k not in obj]
        if missing:
            problems.append(f"{rel}：缺字段 {missing}（最小集 = {list(REQUIRED_FIELDS)}）")
            continue
        for key in ("id", "title", "claimed_at"):
            value = obj[key]
            if not isinstance(value, str) or not value.strip():
                problems.append(f"{rel}：字段 `{key}` 必须是非空字符串（现取 {value!r}）")
        pr = obj["pr"]
        if not isinstance(pr, int) or isinstance(pr, bool) or pr <= 0:
            problems.append(f"{rel}：字段 `pr` 必须是正整数（现取 {pr!r}）")
        elif pr != int(m.group("pr")):
            problems.append(f"{rel}：文件名里的 PR 号（{m.group('pr')}）≠ 内容 `pr`（{pr}）")
        if isinstance(obj["id"], str) and obj["id"] != m.group("cid"):
            problems.append(f"{rel}：文件名里的用例号（{m.group('cid')}）≠ 内容 `id`（{obj['id']}）")
        if isinstance(obj["claimed_at"], str) and not CLAIMED_AT_RE.match(obj["claimed_at"]):
            problems.append(f"{rel}：`claimed_at` 必须是 `YYYY-MM-DD`（现取 {obj['claimed_at']!r}）")
    return problems


def parse_claims(entries: list[tuple[str, str]]) -> list[Claim]:
    """把**形态合规**的 claim 解析成 `Claim`（形态不合规的由 `form_problems` 判红，这里跳过）。"""
    out: list[Claim] = []
    for rel, text in entries:
        m = CLAIM_FILE_RE.match(Path(rel).name)
        if m is None:
            continue
        try:
            obj = json.loads(text)
        except ValueError:
            continue
        if not isinstance(obj, dict) or any(k not in obj for k in REQUIRED_FIELDS):
            continue
        pr, cid = obj["pr"], obj["id"]
        if not isinstance(pr, int) or isinstance(pr, bool):
            continue
        if pr != int(m.group("pr")) or cid != m.group("cid"):
            continue
        out.append(Claim(file=rel, pr=pr, cid=str(cid), title=str(obj["title"])))
    return out


def current_pr(claims: list[Claim], env: dict[str, str] | None = None) -> int | None:
    """当前 PR 号：注入 → GitHub 事件载荷 → `GITHUB_REF` → **现取**（claim 里的最大 PR 号）。

    最后那一步是**现取启发式**（不是魔法数）：并行 PR 的号随时间递增 ⇒ main 侧遗留的 claim
    号一定小于当前在飞的那个。取不到（无 claim）⇒ `None`。
    """
    env = os.environ if env is None else env
    raw = env.get(PR_ENV)
    if raw and raw.strip().isdigit() and int(raw) > 0:
        return int(raw)
    path = env.get("GITHUB_EVENT_PATH")
    if path and os.path.isfile(path):
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = None
        if isinstance(payload, dict):
            number = payload.get("number")
            if isinstance(number, int) and not isinstance(number, bool) and number > 0:
                return number
    ref = env.get("GITHUB_REF") or ""
    m = re.match(r"refs/pull/(\d+)/", ref)
    if m:
        return int(m.group(1))
    return max((c.pr for c in claims), default=None)


def duplicate_problems(claims: list[Claim]) -> list[str]:
    """判据 2：**两个 claim 同 id** ⇒ 红（具名报出两个 PR 号 + 后合入者让号）。"""
    by_cid: dict[str, list[Claim]] = {}
    for c in claims:
        by_cid.setdefault(c.cid, []).append(c)
    out: list[str] = []
    for cid, group in sorted(by_cid.items()):
        if len(group) < 2:
            continue
        listed = "、".join(
            f"PR #{pr}（{f}）" for pr, f in sorted({(c.pr, c.file) for c in group})
        )
        out.append(
            f"用例号 {cid} 被 {len(group)} 个 claim 同时占着：{listed}"
            f" ⇒ 按 `docs/wiki/Change-Blast-Radius.md` 的陷阱 3：**后合入者让号**"
            f"（改号时同步改 claim 文件名与内容里的 `id`）"
        )
    return out


def main_side_ids(used: Counter, live_ids: set[str], injected: set[str] | None) -> set[str]:
    """「**已进 main** 的用例号」的现取口径。

    - `injected` 非空 ⇒ 用它（= 真正读到 main 侧用例库时；测试/红证注入点）；
    - 否则用**合并态近似**：① 在合并态里**重号**的号（本 PR 与 main 各写了一份 ⇒ 必有一份是 main 的）
      ② 用例库里**不属于本 PR** 的号（= 没有本 PR 的 claim 声明的号）。
    """
    if injected is not None:
        return set(injected)
    duplicated = {cid for cid, n in used.items() if n > 1}
    return duplicated | {cid for cid in used if cid not in live_ids}


def collision_problems(
    claims: list[Claim], used: Counter, current: int | None, injected: set[str] | None
) -> list[str]:
    """判据 3 + 判据 4：「与已占号相撞」与「陈旧 claim」—— 同一谓词（claim 的号已在 main 侧），
    按 claim 是不是**本 PR 的**分成两条**具名**出口。"""
    live_ids = {c.cid for c in claims if current is not None and c.pr == current}
    main_ids = main_side_ids(used, live_ids, injected)
    out: list[str] = []
    for c in sorted(claims, key=lambda x: (x.cid, x.pr, x.file)):
        if c.cid not in main_ids:
            continue
        if current is not None and c.pr == current:
            others = sorted({o.pr for o in claims if o.cid == c.cid and o.pr != c.pr})
            who = f"（同号 claim 还见 PR {'/'.join(f'#{p}' for p in others)}）" if others else ""
            out.append(
                f"{c.file}：claim 的用例号 {c.cid} **已进 main / 已被占用**{who}"
                f" ⇒ 请让号（陷阱 3 的兜底：后合入者让号），并同步改 claim 文件名与内容"
            )
        else:
            out.append(
                f"{c.file}：**陈旧 claim** —— {c.cid} 的用例已进用例库（PR #{c.pr} 的 claim 使命已完成）"
                f" ⇒ 删除该 claim 文件（台账不许只增不减）"
            )
    return out


def quota_problems(claims: list[Claim], used: Counter, cap: int | None = None) -> list[str]:
    """判据 5：占位必须对应一条**真用例**；同一 PR 的 claim 数 ≤ **现取上限**。"""
    out: list[str] = []
    for c in sorted(claims, key=lambda x: (x.pr, x.cid, x.file)):
        if c.cid not in used:
            out.append(
                f"{c.file}：占位 {c.cid} 在用例库（{CASES_REL}）里**没有对应的用例**"
                f" ⇒ 不许先占一堆号（本条就是「占位不得超额」的主防线）"
            )
    cap_now = len(used) if cap is None else cap
    for pr, n in sorted(Counter(c.pr for c in claims).items()):
        if n > cap_now:
            out.append(
                f"PR #{pr} 有 {n} 个 claim > 现取上限 {cap_now}"
                f"（= 用例库现取条数；变更集不可得时的兜底口径，**不是**魔法数）"
            )
    return out


def all_problems(
    claims_dir: Path, used: Counter, current: int | None, injected: set[str] | None
) -> list[str]:
    """六条判据的**唯一出口**（判定与红证走同一个函数 —— 不许判据本体与红证各写一份）。"""
    entries, stray = scan_claims(claims_dir)
    claims = parse_claims(entries)
    return (
        stray
        + form_problems(entries)
        + duplicate_problems(claims)
        + collision_problems(claims, used, current, injected)
        + quota_problems(claims, used)
    )


# ─────────────────────────────────────────────────────────────────────────────
# 仓内语料面（真值来自仓内文件；扫描面空 ⇒ fail-closed）
# ─────────────────────────────────────────────────────────────────────────────
def repo_used_ids() -> Counter:
    """用例库现取号集（`.github/cases/*.yml` 的 `- id:`）。"""
    out: Counter = Counter()
    for p in sorted((REPO_ROOT / CASES_REL).glob("*.yml")):
        for cid in case_id_lines(p.read_text(encoding="utf-8")):
            out[cid] += 1
    assert len(out) > 0, f"{CASES_REL} 下没解析到任何用例号 ⇒ 本判据会静默空跑（fail-closed）"
    return out


def base_used_ids() -> set[str] | None:
    """「**已进 main**」的用例号 —— **可选注入点**；取不到 ⇒ `None` ⇒ 退回合并态近似。

    注入形态 = `MIGAO_CASE_CLAIMS_MAIN_DIR`：一个内含 `*.yml`（用例源）的目录。
    ⚠️ **本判据刻意不读 `origin/main`**：CI 的 `actions/checkout` 是 `fetch-depth: 1`（先例与理由见
    `tests/unit_ci_workflows/test_next_case_id_allocator.py`）⇒ 生产路径上一律用**合并态近似**表达
    「已进 main」；这个注入点只给**红证 / 判别力自证 / 需要精确 main 侧读数的人**用。
    """
    raw = os.environ.get(MAIN_DIR_ENV)
    if not raw:
        return None
    directory = Path(raw)
    if not directory.is_dir():
        return None
    ids: set[str] = set()
    for p in sorted(directory.glob("*.yml")):
        ids.update(case_id_lines(p.read_text(encoding="utf-8")))
    return ids


def repo_claims() -> tuple[list[tuple[str, str]], list[str]]:
    return scan_claims(REPO_ROOT / CLAIMS_REL)


def repo_problems() -> list[str]:
    entries, _ = repo_claims()
    claims = parse_claims(entries)
    return all_problems(
        REPO_ROOT / CLAIMS_REL, repo_used_ids(), current_pr(claims), base_used_ids()
    )


def test_repo_case_id_claims_are_clean() -> None:
    """仓内六条判据的**常驻出口**：当前树上的 claim 台账必须干净（没有 claim 时天然全绿）。"""
    problems = repo_problems()
    assert problems == [], "取号登记台账判据报红：\n" + "\n".join(f"  - {p}" for p in problems)


def test_repo_casebook_scan_is_not_empty() -> None:
    """接线（判据本体绿 ≠ 扫描面在）：用例库扫描必须**真的读到**号，否则上面那条是空跑。"""
    used = repo_used_ids()
    assert len(used) > 0, f"{CASES_REL} 的号集为空"
    assert "MC-001" in used, f"用例库扫描口径失效：连 MC-001 都读不到（现取 {len(used)} 条）"


# ─────────────────────────────────────────────────────────────────────────────
# 判别力自证（每条坏形态都必须单独判红；负向对照必须不红）
# ─────────────────────────────────────────────────────────────────────────────
def _write_claim(tmp: Path, name: str, **fields: object) -> None:
    payload = {"id": "MC-901", "pr": 1, "title": "示范", "claimed_at": "2026-10-02"}
    payload.update(fields)
    (tmp / name).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_red_proof_two_claims_with_the_same_id(tmp_path: Path) -> None:
    """红证 ②：**同 id 两个 claim** ⇒ 红，且报出两个 PR 号 + 「后合入者让号」。"""
    _write_claim(tmp_path, "6010-MC-901.json", pr=6010, id="MC-901")
    _write_claim(tmp_path, "6011-MC-901.json", pr=6011, id="MC-901")
    problems = duplicate_problems(parse_claims(scan_claims(tmp_path)[0]))
    assert len(problems) == 1, problems
    assert "MC-901" in problems[0] and "#6010" in problems[0] and "#6011" in problems[0], problems[0]
    assert "后合入者让号" in problems[0], problems[0]


def test_red_proof_claim_collides_with_a_used_id(tmp_path: Path) -> None:
    """红证 ③：claim 与**已占号**相撞（main 侧用例库注入）⇒ 红 + 「请让号」。"""
    _write_claim(tmp_path, "6012-MC-902.json", pr=6012, id="MC-902")
    claims = parse_claims(scan_claims(tmp_path)[0])
    problems = collision_problems(claims, Counter({"MC-902": 1}), current=6012, injected={"MC-902"})
    assert len(problems) == 1, problems
    assert "MC-902" in problems[0] and "让号" in problems[0], problems[0]


def test_red_proof_stale_claim(tmp_path: Path) -> None:
    """红证 ④：**陈旧 claim**（该号已进 main、claim 还在）⇒ 红 + 「删除该 claim」。"""
    _write_claim(tmp_path, "6009-MC-903.json", pr=6009, id="MC-903")
    claims = parse_claims(scan_claims(tmp_path)[0])
    problems = collision_problems(claims, Counter({"MC-903": 1}), current=6013, injected={"MC-903"})
    assert len(problems) == 1, problems
    assert "陈旧" in problems[0] and "删除" in problems[0], problems[0]


def test_red_proof_claim_without_a_case(tmp_path: Path) -> None:
    """红证 ⑤：「占了一堆号，却没写用例」⇒ 红（占位不得超额的主防线）。"""
    _write_claim(tmp_path, "6014-MC-904.json", pr=6014, id="MC-904")
    claims = parse_claims(scan_claims(tmp_path)[0])
    problems = quota_problems(claims, Counter({"MC-001": 1}))
    assert len(problems) == 1, problems
    assert "MC-904" in problems[0] and "没有对应的用例" in problems[0], problems[0]


def test_red_proof_form_violations_are_named(tmp_path: Path) -> None:
    """红证 ①（形态）：文件名与内容脱钩 / 字段不全 / 目录里混进非 claim 文件 ⇒ 各自具名判红。"""
    _write_claim(tmp_path, "6015-MC-905.json", pr=6016, id="MC-905")
    (tmp_path / "6017-note.txt").write_text("随手记", encoding="utf-8")
    (tmp_path / "nonsense.json").write_text("{}", encoding="utf-8")
    entries, stray = scan_claims(tmp_path)
    problems = stray + form_problems(entries)
    joined = "\n".join(problems)
    assert "PR 号（6015）≠ 内容 `pr`（6016）" in joined, joined
    assert "6017-note.txt" in joined and "只许有" in joined, joined
    assert "nonsense.json" in joined and "形态" in joined, joined


def test_negative_control_no_claims_is_green(tmp_path: Path) -> None:
    """负向对照：**没有 claim 时不红**（台账是新增可选面；空目录 / 目录不存在都必须全绿）。"""
    used = Counter({"MC-001": 1, "MC-002": 1})
    assert all_problems(tmp_path, used, current=None, injected=None) == []
    assert scan_claims(tmp_path / "not-there") == ([], [])
    assert all_problems(tmp_path / "not-there", used, current=None, injected=None) == []


def test_control_clean_claim_is_green(tmp_path: Path) -> None:
    """对照读数：**形态齐全 + 号在自己 PR 的用例里** ⇒ 不红（防判据被自己的文案喂红）。"""
    _write_claim(tmp_path, "6018-MC-906.json", pr=6018, id="MC-906")
    used = Counter({"MC-001": 1, "MC-906": 1})
    entries, stray = scan_claims(tmp_path)
    assert all_problems(tmp_path, used, current=6018, injected=None) == [], stray
    assert parse_claims(entries)[0].cid == "MC-906"


def test_merge_state_approximation_flags_a_stale_claim_without_any_injection(tmp_path: Path) -> None:
    """合并态近似（CI 的真实口径，**无主线段注入**）：main 侧遗留的 claim 也必须被抓到。

    形状 = 用例库里有 `MC-907`（main 侧那份）而本 PR（#6020）只 claim 了 `MC-908` ⇒ `MC-907` 那条陈旧。
    """
    _write_claim(tmp_path, "6019-MC-907.json", pr=6019, id="MC-907")
    _write_claim(tmp_path, "6020-MC-908.json", pr=6020, id="MC-908")
    used = Counter({"MC-907": 1, "MC-908": 1})
    problems = all_problems(tmp_path, used, current=6020, injected=None)
    joined = "\n".join(problems)
    assert "MC-907" in joined and "陈旧" in joined, joined
    assert "MC-908" not in joined, f"本 PR 自己的 claim 被误判：{joined}"


def test_duplicate_and_stale_are_not_the_same_reading(tmp_path: Path) -> None:
    """判别力自证：**同号两条** 与 **一条陈旧** 必须产出不同读数（不许一个函数吞掉两种形态）。"""
    dup = tmp_path / "dup"
    dup.mkdir()
    _write_claim(dup, "6021-MC-909.json", pr=6021, id="MC-909")
    _write_claim(dup, "6022-MC-909.json", pr=6022, id="MC-909")
    stale = tmp_path / "stale"
    stale.mkdir()
    _write_claim(stale, "6021-MC-910.json", pr=6021, id="MC-910")
    used = Counter({"MC-909": 2, "MC-910": 1})
    dup_problems = all_problems(dup, used, current=6022, injected=None)
    stale_problems = all_problems(stale, used, current=6022, injected=None)
    assert any("同时占着" in p for p in dup_problems), dup_problems
    assert any("陈旧" in p for p in stale_problems), stale_problems


# ─────────────────────────────────────────────────────────────────────────────
# 纯静态自证（CI 那个 job 只装 pytest + pyyaml；禁 skip）
# ─────────────────────────────────────────────────────────────────────────────
def test_this_judgement_is_pure_static_and_never_skips() -> None:
    """AST 取本文件的 import：**零** ai-agent 依赖；且**不许**有 `pytest.skip` / `except ImportError` 兜底。

    ⚠️ 判据读的是**代码面**（AST），不是文本：本文档字符串里**刻意写着**那两个串（否则无法讲清禁忌）
    —— 文本层判会让守卫被自己的文案喂红（本文件首版就踩了，实测 1 failed）。
    """
    src = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    modules: set[str] = set()
    skip_lines: list[int] = []
    import_guard_lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
        elif isinstance(node, ast.Attribute) and node.attr == "skip":
            base = node.value
            if isinstance(base, ast.Name) and base.id == "pytest":
                skip_lines.append(getattr(node, "lineno", 0))
        elif isinstance(node, ast.Try):
            for handler in node.handlers:
                kinds = []
                if isinstance(handler.type, ast.Name):
                    kinds = [handler.type.id]
                elif isinstance(handler.type, ast.Tuple):
                    kinds = [e.id for e in handler.type.elts if isinstance(e, ast.Name)]
                if {"ImportError", "ModuleNotFoundError"} & set(kinds):
                    import_guard_lines.append(getattr(handler, "lineno", 0))
    bad = sorted(m for m in modules if m in FORBIDDEN_IMPORTS)
    assert bad == [], (
        f"本判据不得依赖 ai-agent 运行时依赖（CI 的 ci workflow helper unit tests 只装 pytest + pyyaml）：{bad}"
    )
    assert skip_lines == [], (
        f"禁 `pytest.skip`（会让判据在 CI 里永远是空的）—— 命中行 {skip_lines}"
    )
    assert import_guard_lines == [], (
        f"禁 `except ImportError` / `ModuleNotFoundError` 兜底（同族假绿）—— 命中行 {import_guard_lines}"
    )
