# case_ids: MC-066
"""用例 id **取号登记台账**（claim）：并行开发下不再撞号（issue #6017，用户 2026-10-02 裁定方案 B）。

## 病（2026-10-02 一天**三次**撞号，有具名实证）

用例 `id` 是**全局唯一**登记键，而现行取号法 = 「现取 `origin/main` 最大号 + 1（再加"猜在飞 PR"）」
⇒ **并行下必然失效**。现场逐条记在 `.github/cases/misc.yml` 的 `MC-064` 的 `merge_log` 里
（起草取 `MC-062` ⇒ 被 #6001/#5976+#5977 占；让号到 `MC-063` ⇒ 被 #5983 占；再预判在飞 PR #5994
⇒ 跳成 `MC-065`）。形状是**预判在飞 PR** —— 那是不可靠启发式。

**症状形态**（诊断成本极高）：表现为 `.github/cases/misc.yml` 的**困惑冲突** + 生成物连带冲突，
而不是「你撞号了，请让号」—— 排查要靠 `git merge-tree`、逐条比对两侧用例块。

🔴 **2026-10-02 收窄（issue #6037）**：本判据首版把「claim 的号已进用例库、而这条 claim 还在」判成
**陈旧即红**（「台账不许只增不减」）。实测后果：`.github/cases/claims/6033-MC-067.json`（PR #6033 已合并、
MC-067 已进用例库）落 main 之后，**下一个 PR 一律被判红** ⇒ 阻塞所有并行开发。
现行口径 = **取号台账是累积的分配登记**：落地 claim **继续留在** `.github/cases/claims/` 是**有意设计**
（它记录「这个号已经分配过」），**不是垃圾、不是要删的东西**；只有 `claim.pr == 当前 PR`
（= **你自己这个 PR 的** claim）与已用号相撞才判红。规则表见下（判据 3 / 4 的边界即在此）。

## 本文件锁什么（每一条都能单独变红）

| # | 判据 | 取法 | 红证 |
|---|---|---|---|
| 1 | **形态**：claim 文件名 `<PR号>-<CASE_ID>.json`、字段最小集齐全、文件名里的 `PR`/`CASE_ID` 与内容 `pr`/`id` 一致、`claimed_at` 是 `YYYY-MM-DD`；目录里出现非 claim 文件（除 `.gitkeep` / `README.md`）也判红 | 逐文件解析（纯静态） | 改错文件名 / 删字段 / 内容与文件名不一致 ⇒ 红 |
| 2 | **两 claim 同 id ⇒ 红**：**具名报出两个 PR 号** + 「后合入者让号」 | 按 `id` 分组 | 造两份同 id claim ⇒ 红 |
| 3 | **本 PR 自己的 claim 与已用号相撞 ⇒ 红**：`claim.pr == 当前 PR` 且该 `id` 已在 main 侧被占用 ⇒ 报出该号 + 让号出口 | 用例库现取号集 ⇄ **本 PR 的** claim | 造 claim `MC-9xx`（`pr` = 当前 PR）+ main 侧已有 `MC-9xx` ⇒ 红 |
| 4 | **他人 claim 一律不判红（累积台账）**：`claim.pr ≠ 当前 PR` 的 claim —— **含已落地的历史 claim** —— 是「这个号已分配过」的登记，**不是错误** ⇒ 一条都不报 | 与判据 3 同一谓词，作用域按 `claim.pr` 收窄 | 造「别人的落地 claim」（号已在用例库、claim 还在）⇒ **不红**（= 判据 3/4 的分界线） |
| 5 | **占位不得超额**：每条 claim 的 `id` 必须在用例库里**有对应用例**；同一 PR 的 claim 数 ≤ **现取上限**（= 用例库现取条数；变更集不可得时的兜底，**不拍魔法数**） | 现取 | 造「claim 了一个没写用例的号」⇒ 红 |
| 6 | **负向对照**：没有 claim ⇒ 一条都不报（本台账是**新增可选面**，不能把不用的包判红） | —— | 空目录 ⇒ 全绿 |
| 7 | 🔴 **跨在飞 PR 重号 ⇒ 红（issue #6245 新增）**：**本 PR** 的 claim 号若与**另一个 open PR** 的 claim 同号 ⇒ 红并**点名对方 PR 号**。读法 = GitHub REST 列 open PR（`state=open`）⇒ 逐 PR 读它那个 ref 的 `.github/cases/claims/*.json`（纯 stdlib `urllib`，无新依赖） | 网络（open PR 列表 + 各 PR 的 claims 目录） | 桩造「另一个 open PR 占了同一个号」⇒ 红并点名；**对方已合并/已关闭 ⇒ 不在 open 列表 ⇒ 不红**；**读不到 / 无 token ⇒ 红（fail-closed）且信息写明"是判定不了"** |

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
- 🔴 **作用域 = 本 PR 自己**（判据 3/4 的唯一分界线；`current_pr` 的取法见其 docstring）：台账**累积**，
  别人的 claim（无论它的用例有没有进 main）都不判红；真正的撞号面是判据 2（**两个 claim 同 id，全量判红**，
  它不看 `pr`）。⚠️ 收窄**只**收窄作用域，**不放宽**任何其他判据、不新增豁免。
- 🔴 **判据 7 是唯一联网面**（issue #6245）：它**只**在「本 PR 号可判定 + 有 API 凭据」时发起；
  判定语义 = 「**本 PR 的号 ∩ 另一个 open PR 的号**」，**不**与 main 侧比（那是判据 3 的面）。
  成本 = 1 次列 open PR + 每个 open PR 1 次读 claims 目录（**不拉整库、不跑重活、不装依赖**），
  逐请求超时 + 总预算，超预算即停。**看不到 ⇒ 红**（fail-closed），但**报错文本必须区分
  「判定不了」与「真撞号」** —— 本仓口径：❓ 不许读成 ✅。

## 边界（照实登记，**不要**把本判据读成覆盖面更大的东西）

- ❌ **看不到在飞分支**：别人的 open PR 上的 claim 不在我这棵树里 ⇒ 「两个在飞 PR 同时取到同一个号」
  只有在**其中一个合入 main 之后**才在我这棵树上现形（这正是 `MC-064` 的三次撞号的形状）。
- ❌ **「claim 了号、但还没写用例、而 main 恰好已有同号用例」这一角判不了**（近似口径把「本 PR 的号」扣掉了）；
  显形条件 = 早占号 + 对方已合并 + 本 PR 还没写用例。
- ❌ **变更集不可得**（不读 git / 不联网）⇒ 判据 5 一律用现取上限兜底；「占一堆号」的主要防线是
  「每条 claim 必须对应一条真用例」这一条，不是那个上限。
- ❌ **没有常驻守护跑在 main 上**（`pr-check` 只在 `pull_request` 触发）：**本 PR 自己**的 claim 与 main 侧
  相撞（判据 3）只能在**它自己那个 PR** 的 CI 上现形；⚠️ **别人的** claim **不是**判红对象（见上面「作用域」一节），
  落地 claim 留在 main 上**不再**有任何后续 PR 会因此变红。
- ❌ 本判据**不改任何门禁的通过条件、不新增豁免**。

### 判据 7（跨在飞 PR 重号，issue #6245）的边界 —— 照实登记，别把它读成覆盖面更大的东西

- ❌ **读不到凭据 / 离线 ⇒ 红（fail-closed），不是绿**：`current_pr` 可判定而无 API 凭据时，判据 7 判红并把
  「**无法判定**」写进文本。⇒ 这是**有意**取舍：本仓的失效形态是「静默 + 两个 PR 同时绿」，静默比误红贵得多。
- ❌ **本机（无 `GITHUB_TOKEN` / 无 `GITHUB_EVENT_PATH`）不发起判定**：本地跑与 CI 跑读数不同，
  本判据**只**承诺 CI 面。⇒ 本机**看不到**「两个在飞 PR 撞号」—— 那是**声明过的**缺口，
  不是「本机绿 ⇒ 没问题」（本机绿只说明判据 1~6 干净）。
- ❌ **只看 claim 面**：判不了「生成物新鲜度 / 用例库文本冲突」（那是 issue #6255 的面）。
- ❌ **不是互斥锁**：两个包在**同一瞬间**开 PR 时仍是「两边都红」而不是「后开的那个被挡住」——
  它把**发现**从「合并时人工核对」提前到「**开 PR 时就红**」，但**不**做抢占。
- ❌ **fork PR 的对象可能读不到**（`contents` API 对 fork 头 ref 的可见性受 token 权限限制）⇒ 那种 PR 是
  「无法判定」⇒ 红并把 PR 号列出来（`undecidable`），**不**当成「它没 claim」。
- ⚠️ **open PR 数超过一页上限** ⇒ 也判「无法判定」⇒ 红（宁红不绿：《本仓口径》）。
"""
from __future__ import annotations

import ast
import base64
import concurrent.futures
import http.server
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
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

# ── 判据 7（跨在飞 PR 重号，issue #6245）的网络面：stdlib `urllib`，**零新依赖** ──
#: GitHub API 根（注入点：本地用 `MIGAO_CASE_CLAIMS_API` 指向替身，判据红证明它）。
API_ENV = "MIGAO_CASE_CLAIMS_API"
#: 凭据环境变量（按序取第一个非空的）：CI 用 `GITHUB_TOKEN`（GitHub 自动注入的 installation token），
#: 本机通常只有 `gh` 的 `GH_TOKEN`。**一个都没有 ⇒ 判定不了**（判据 7 判红，见 `cross_pr_claims_problems`）。
TOKEN_ENVS = ("GITHUB_TOKEN", "GH_TOKEN")
#: 仓库全名（CI 自动注入）——取不到 ⇒ 判定不了。
REPO_ENV = "GITHUB_REPOSITORY"
#: 单请求超时（秒）+ 整轮总预算（秒）：**不把 CI 拖重**的机械保证（超预算即停 ⇒ 判「无法判定」）。
#: ⚠️ 读数（本机 2026-10-03 实测，见 PR body）：**串行** + 逐 claim 文件下载 ⇒ 9 个 open PR 读到
#: **31.1s**（撞当时的 30s 预算 ⇒ 一个**合法** PR 会因预算变红 = fail-closed 误伤）。
#: ⇒ 四条一起上：① 两个阶段都**并行**（`FETCH_CONCURRENCY` 路，纯 stdlib 线程池）；
#: ② 逐 PR claim 文件按**内容 SHA 去重**（git 对象：同 SHA ⇒ 同字节 ⇒ 只下载一次）；
#: ③ **瞬时失败重试一次**（`RETRY_STATUSES` + 连接/读超时）—— 实测本机一次读超时会把
#: **所有引用同一 blob 的 PR** 一起判「读不到」（去重的反作用面）⇒ 不重试的话，同一个瞬时抖动
#: 会放大成整面不可判（红）。⚠️ 重试**不加退避等待**：等 = 白付墙钟，而 CI 上 5xx/超时本就是瞬时态；
#: 最坏 2 轮 × 并发 4 ⇒ 仍有界（`BUDGET_S` 兜底）。
#: ④ 预算按「并行 + 去重 + 重试」定，留一倍余量。
HTTP_TIMEOUT_S = 8.0
BUDGET_S = 60.0
#: 读在飞面的**并发度**（上限受任务数收敛；纯网络 IO ⇒ 不占 CPU、不影响同 job 的其它判据）。
FETCH_CONCURRENCY = 4
#: 值得重试一次的 HTTP 状态（限流 / 服务端瞬时态）；**4xx 业务错不重试**（重试也不会变）。
RETRY_STATUSES = (429, 500, 502, 503, 504)
#: open PR 的取数上限（`per_page` 的硬上限）。命中上限 ⇒ **无法判定**（宁红不绿：可能还有下一页）。
PR_LIST_LIMIT = 100
#: 远端 claims 目录（判据 7 只读这个路径；不拉整库、不拉语料）。
CLAIMS_API_PATH = ".github/cases/claims"
#: 报错文本的截断长度（防替身 / 代理返回一整页 HTML 把红证淹没）。
ERR_MAX = 200


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


# ─────────────────────────────────────────────────────────────────────────────
# 判据 7：跨在飞 PR 重号（issue #6245）—— 唯一的联网面
#   病：两个**同时在飞**的 PR 各自 claim 同一个号 ⇒ **两边 CI 都绿**（各自的工作树里只有自己那份），
#   要等其中一个合入 main / 另一个 rebase 才现形。本轮实测撞了 3 次（AS-011/012、PG-059/069、MC-076），
#   每次都要人工跨 refs 核对。判据 2 只看**本地工作树** ⇒ 结构上看不见另一个在飞分支。
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class OpenPrClaims:
    """一个 open PR 的 claim 读数。

    `ids is None` ⇒ **读不到**（网络 / 凭据 / 该 ref 的 claims 目录读不了）⇒ 判定不了（fail-closed）。
    `ids == frozenset()` ⇒ **读得到、且它一条 claim 都没有**（合法：claim 面是可选台账）。
    """

    pr: int
    ids: frozenset[str] | None


def token_value(env: dict[str, str] | None = None) -> str | None:
    """API 凭据（按 `TOKEN_ENVS` 顺序取；都没有 ⇒ `None` = 判定不了）。"""
    env = os.environ if env is None else env
    for name in TOKEN_ENVS:
        value = (env.get(name) or "").strip()
        if value:
            return value
    return None


def _api_get(url: str, token: str, timeout: float) -> str:
    """一次**只读** GET ⇒ 文本；任何失败抛 `OSError`（调用方捕获 ⇒ 判定不了）。

    scheme 白名单（`http` 只给本地替身用）+ 显式超时 + `Accept` 钉版本（GitHub API 版本漂移的护栏）。
    """
    scheme = urllib.parse.urlsplit(url).scheme
    if scheme not in ("https", "http"):
        raise OSError(f"不允许的 scheme：{scheme!r}")
    request = urllib.request.Request(  # noqa: S310 —— scheme 已白名单（http 只给本地替身）
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "migao-case-id-claims-guard",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return response.read().decode("utf-8", errors="replace")


def _api_get_retrying(url: str, token: str, timeout: float, attempts: int = 2) -> str:
    """`_api_get` + **瞬时失败重试一次**（连接/读超时、`RETRY_STATUSES`）。

    🔴 为什么必须重试：去重后**一个 blob 被多个 PR 共用** ⇒ 那一次读一抖，就会把**所有**引用它的
    PR 一起判成「读不到」⇒ 一个瞬时抖动被放大成整面不可判（红）。重试**不加退避等待**
    （等待 = 白付墙钟；CI 上 5xx / 超时本就是瞬时态），最坏 `attempts` 轮 ⇒ 仍有界。
    4xx（401/403/404 等）**不重试**（重试也不会变，只会白等）。
    """
    last: Exception | None = None
    for attempt in range(max(1, attempts)):
        try:
            return _api_get(url, token, timeout)
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in RETRY_STATUSES:
                raise
        except urllib.error.URLError as e:
            last = e
        except OSError as e:
            last = e
    assert last is not None
    raise last


def _short(text: str) -> str:
    """报错文本截断（防整页 HTML 淹没红证）。"""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= ERR_MAX else flat[:ERR_MAX] + "…"


def _api_json(url: str, token: str, timeout: float) -> tuple[object, str]:
    """`_api_get_retrying` + JSON 解析 ⇒ `(值, 错误文本)`（二者恰一有值 —— 不许静默吞）。"""
    try:
        return json.loads(_api_get_retrying(url, token, timeout)), ""
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except urllib.error.URLError as e:
        return None, f"连接失败（{_short(getattr(e, 'reason', e))}）"
    except (OSError, ValueError) as e:
        return None, _short(e)


def _claims_from_json(text: str) -> tuple[set[str], list[str]]:
    """从**一个** claims JSON 文本里取用例号。

    🔴 **与 CI 侧同口径**：`REQUIRED_FIELDS` 缺一不可 ⇒ 缺字段 = **判定不了**（不是「忽略这个文件」）。
    忽略会与 `form_problems` 的严格性脱钩（远端静默漏号 ⇒ 假绿）。
    """
    try:
        obj = json.loads(text)
    except ValueError as e:
        return set(), [f"不是合法 JSON（{e.__class__.__name__}）"]
    if not isinstance(obj, dict):
        return set(), ["顶层不是对象"]
    missing = [k for k in REQUIRED_FIELDS if k not in obj]
    if missing:
        return set(), [f"缺字段 {missing}"]
    cid = obj["id"]
    if not isinstance(cid, str) or not cid.strip():
        return set(), [f"字段 `id` 不是非空字符串（现取 {cid!r}）"]
    return {cid}, []


def list_claim_files(base: str, repo: str, token: str, number: int, sha: str
                     ) -> tuple[list[tuple[str, str]], str]:
    """读一个 open PR 的 claims **目录** ⇒ `([(文件名, 内容 SHA)], 错误文本)`。

    只读 `.github/cases/claims` 这一层（**不拉整库**）；形态不合 `CLAIM_FILE_RE` 的条目交给
    CI 侧判据 1（本判据只管取号）。
    """
    directory, derr = _api_json(
        f"{base}/repos/{repo}/contents/{CLAIMS_API_PATH}?ref={sha}", token, HTTP_TIMEOUT_S
    )
    if derr or not isinstance(directory, list):
        return [], derr or "响应不是数组"
    out: list[tuple[str, str]] = []
    for entry in directory:
        if not isinstance(entry, dict):
            continue
        name, blob = entry.get("name"), entry.get("sha")
        if not isinstance(name, str) or CLAIM_FILE_RE.match(name) is None:
            continue
        if not isinstance(blob, str) or not blob:
            return [], f"目录里的 `{name}` 没有内容 SHA"
        out.append((name, blob))
    return out, ""


def read_one_open_pr(base: str, repo: str, token: str, number: int, sha: str
                     ) -> tuple[list[tuple[str, str]], str]:
    """读**一个** open PR 的 claims 目录 ⇒ `([(文件名, 内容 SHA)], 错误文本)`（判据 7 的取数单元）。"""
    return list_claim_files(base, repo, token, number, sha)


def read_blob(base: str, repo: str, token: str, blob_sha: str) -> tuple[str, str]:
    """按**内容 SHA** 读一个 git blob ⇒ `(文本, 错误文本)`。

    🔴 用 blob 而**不是**路径：git 对象按内容寻址 ⇒ **同 SHA = 同字节** ⇒ 多个 PR 里**逐字节相同**
    的 claim 文件只下载一次（现取 11 个 open PR 有大量重复 claim 文件 ⇒ 请求数 30+ → 12）。
    """
    raw, err = _api_json(f"{base}/repos/{repo}/git/blobs/{blob_sha}", token, HTTP_TIMEOUT_S)
    if err or not isinstance(raw, dict) or not isinstance(raw.get("content"), str):
        return "", err or "响应里没有 content"
    try:
        return base64.b64decode(raw["content"]).decode("utf-8", errors="replace"), ""
    except (ValueError, TypeError) as e:
        return "", _short(e)


def _parallel_map(jobs: list, work, concurrency: int = FETCH_CONCURRENCY) -> list:
    """`jobs` 并发跑 `work(job)` ⇒ 与 `jobs` **同序**的结果列表（`dict` 保序）。

    纯网络 IO ⇒ 4 路并发；`work` 的异常**不外溢**（由调用方按「判定不了」处理）。
    """
    results: dict[int, object] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(concurrency, max(1, len(jobs)))) as pool:
        futures = {pool.submit(work, job): i for i, job in enumerate(jobs)}
        for future in concurrent.futures.as_completed(futures):
            index = futures[future]
            try:
                results[index] = future.result()
            except Exception as e:  # 单点异常不许炸掉整张在飞面
                results[index] = (None, f"{e.__class__.__name__}: {_short(e)}")
    return [results[i] for i in range(len(jobs))]


def fetch_open_pr_claims(env: dict[str, str] | None = None) -> tuple[list[OpenPrClaims], list[str]] | None:
    """列**同仓 open PR** + 并行读各 PR 的 claims（**按内容 SHA 去重**）。

    返回 `None` ⇒ **不发起判定**（非 Actions 环境；见下与 `cross_pr_claims_problems`）。
    返回 `(读数, 问题)` ⇒ 覆盖度问题（凭据缺 / 列不出 / 读不到）逐条具名 ⇒ 判据 7 判红（fail-closed）。

    成本（**不拖重 CI** 的机械保证）：1 次列 PR + 每 PR 1 次读目录 + **每个唯一 blob 1 次**
    （阶段内并行 4 路），逐请求 `HTTP_TIMEOUT_S` 超时、整轮 `BUDGET_S` 预算，超预算即停 ⇒ 判「无法判定」。
    **不拉整库、不跑重活、不装依赖**（纯 stdlib）。读数与三次提速的实测见 `BUDGET_S` 上方注释。
    """
    env = os.environ if env is None else env
    base = (env.get(API_ENV) or "https://api.github.com").rstrip("/")
    repo = (env.get(REPO_ENV) or "").strip()
    token = token_value(env)
    # 🔴 **「不发起判定」两态（语义必须分清）**：① 非 Actions 环境（无 `GITHUB_REPOSITORY`）⇒
    #    **不发起**（本机口径 ⇒ 本地 `pytest` 不因没配 token 而红）；② Actions 环境里**没凭据** ⇒
    #    **判红**（fail-closed：那正是「两个 PR 都绿」的病根，静默比误红贵得多）。
    if not repo:
        return None
    problems: list[str] = []
    if not token:
        return [], [
            f"判定不了：没有 API 凭据（环境变量 {'/'.join(TOKEN_ENVS)} 都为空）"
            f" ⇒ 看不到其他在飞 PR 的 claim（**这不是「没有重号」**）"
        ]
    started = time.monotonic()
    listing, err = _api_json(
        f"{base}/repos/{repo}/pulls?state=open&per_page={PR_LIST_LIMIT}", token, HTTP_TIMEOUT_S
    )
    if err or not isinstance(listing, list):
        return [], [
            f"判定不了：列 open PR 失败（{err or '响应不是数组'}）⇒ 跨在飞 PR 的重号面**这一轮没判**"
            f"（**不是「没有重号」**）"
        ]
    if len(listing) >= PR_LIST_LIMIT:
        return [], [
            f"判定不了：open PR 数达到取数上限 {PR_LIST_LIMIT} ⇒ 可能还有下一页，覆盖面不完整"
            f" ⇒ 不许据此判「没有重号」"
        ]
    targets: list[tuple[int, str]] = []
    for item in listing:
        if not isinstance(item, dict):
            continue
        number = item.get("number")
        head = item.get("head")
        sha = head.get("sha") if isinstance(head, dict) else None
        if not isinstance(number, int) or isinstance(number, bool) or not isinstance(sha, str) or not sha:
            problems.append(f"判定不了：open PR 列表里有一项读不到 `number` / `head.sha`（现取 {item!r}）")
            continue
        targets.append((number, sha))
    if time.monotonic() - started > BUDGET_S:
        problems.append(
            f"判定不了：读在飞面超过 {BUDGET_S:.0f}s 预算 ⇒ 停在 0/{len(targets)} 个 PR"
            f"（**判据不把 CI 拖重**；这一轮没判完）"
        )
        return [], problems
    # 阶段 1：并行读各 PR 的 claims 目录（只拿文件名 + 内容 SHA，不下载内容）
    listings = _parallel_map(targets, lambda t: read_one_open_pr(base, repo, token, t[0], t[1]))
    per_pr: list[tuple[int, list[tuple[str, str]] | None]] = []
    for (number, _sha), (files, why) in zip(targets, listings):
        if files is None or why:
            problems.append(
                f"判定不了：读 PR #{number} 的 `{CLAIMS_API_PATH}` 失败（{why or '未知'}）"
                f" ⇒ 看不到它 claim 了什么"
            )
            per_pr.append((number, None))
            continue
        per_pr.append((number, files))
    # 阶段 2：每个**唯一 blob** 只下载一次（同 SHA ⇒ 同字节），并行读内容
    unique = sorted({blob for _n, files in per_pr if files for _name, blob in files})
    blobs = _parallel_map(unique, lambda b: read_blob(base, repo, token, b))
    texts: dict[str, str] = {}
    for blob, (text, why) in zip(unique, blobs):
        if text:
            texts[blob] = text
        else:
            problems.append(f"判定不了：读 claim 内容（blob {blob[:8]}）失败（{why or '未知'}）")
    out: list[OpenPrClaims] = []
    for number, files in per_pr:
        if files is None:
            out.append(OpenPrClaims(pr=number, ids=None))
            continue
        ids: set[str] = set()
        readable = True
        for name, blob in files:
            text = texts.get(blob)
            if text is None:
                readable = False
                continue
            found, why = _claims_from_json(text)
            if why:
                problems.append(f"判定不了：PR #{number} 的 `{name}` {'；'.join(why)}")
                readable = False
                continue
            ids |= found
        out.append(OpenPrClaims(pr=number, ids=frozenset(ids) if readable else None))
    out.sort(key=lambda p: p.pr)
    problems.sort()
    if time.monotonic() - started > BUDGET_S:
        problems.append(
            f"判定不了：读在飞面超过 {BUDGET_S:.0f}s 预算（读完 {len(out)}/{len(targets)} 个 PR）"
            f" ⇒ 这一轮没判完的内容未纳入比对"
        )
    return out, problems


def cross_pr_claims_problems(
    claims: list[Claim],
    current: int | None,
    fetch: object | None = None,
) -> list[str]:
    """判据 7：**本 PR** 的号 ∩ **其他 open PR** 的号 ⇒ 红并点名。

    🔴 **语义只跟「别的 open PR」比**，**不**跟 main 侧比（那是判据 3 的面）—— 两件事：
    「本 PR ↔ main 已合入」（判据 3，rebase 即可见）与「本 PR ↔ 另一个在飞 PR」（判据 7，本轮才治）。

    - 当前 PR 不可判定（非 PR 上下文）⇒ **不发起**判定 ⇒ `[]`（判据 7 整条不适用）；
    - 取数面返回 `None`（非 Actions 环境 ⇒ 不发起）⇒ `[]`；
    - 判定不了（Actions 环境里没凭据 / 离线 / 读不到某个 PR）⇒ **判红**且文本写明「**判定不了**」
      （❓ 不许读成 ✅）；
    - 对方 PR **已合并 / 已关闭** ⇒ 它**不在** open 列表里 ⇒ 天然不报（反向对照 2）。
    """
    fetch = fetch_open_pr_claims if fetch is None else fetch
    if current is None:
        return []
    result = fetch()
    if result is None:
        return []
    open_prs, problems = result
    out = list(problems)
    for p in open_prs:
        if p.ids is None:
            out.append(
                f"判定不了：读不到在飞 PR #{p.pr} 的 claim（网络 / 权限 / 该 ref 读不了）"
                f" ⇒ 它的号**这一轮没纳入比对**（**不是「它没占号」**）"
            )
    live_ids = {c.cid for c in claims if c.pr == current}
    seen = {p.pr for p in open_prs}
    if seen and current not in seen:
        out.append(
            f"判定不了：本 PR #{current} 不在 open PR 列表里（现取 {sorted(seen)}）⇒ 在飞面读数不可信"
        )
    for cid in sorted(live_ids):
        others = sorted({p.pr for p in open_prs if p.pr != current and cid in (p.ids or frozenset())})
        if not others:
            continue
        out.append(
            f"用例号 {cid} **本 PR（#{current}）与在飞 PR {'/'.join(f'#{p}' for p in others)} 同时占着**"
            f" ⇒ 按 `docs/wiki/Change-Blast-Radius.md` 的陷阱 3：**后合入者让号**"
            f"（在**合并前**就会红 —— 这就是 issue #6245 要的那个判据）"
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
    """判据 3：**本 PR 自己**的 claim 与已用号相撞 ⇒ 红（具名到文件 + 让号出口）。

    🔴 **作用域收窄（issue #6037）**：`claim.pr != 当前 PR` 的 claim —— **含已落地的历史 claim** ——
    只是「这个号分配过」的登记（**累积台账**），**一律不判红**。修前的「陈旧即红」分支正是本单要修的病：
    它让一条落地 claim 把**每一个后续 PR** 都判红。
    """
    live_ids = {c.cid for c in claims if current is not None and c.pr == current}
    main_ids = main_side_ids(used, live_ids, injected)
    out: list[str] = []
    for c in sorted(claims, key=lambda x: (x.cid, x.pr, x.file)):
        if current is None or c.pr != current:
            continue  # 别人的 claim（含已落地）= 台账记录，不是错误
        if c.cid not in main_ids:
            continue
        others = sorted({o.pr for o in claims if o.cid == c.cid and o.pr != c.pr})
        who = f"（同号 claim 还见 PR {'/'.join(f'#{p}' for p in others)}）" if others else ""
        out.append(
            f"{c.file}：claim 的用例号 {c.cid} **已进 main / 已被占用**{who}"
            f" ⇒ 请让号（陷阱 3 的兜底：后合入者让号），并同步改 claim 文件名与内容"
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
    claims_dir: Path,
    used: Counter,
    current: int | None,
    injected: set[str] | None,
    cross_fetch: object | None = None,
) -> list[str]:
    """七条判据的**唯一出口**（判定与红证走同一个函数 —— 不许判据本体与红证各写一份）。

    `cross_fetch` = 判据 7 的取数面：
    - **不传** ⇒ 判据 7 **整条不生效**（判据 1~6 的红证**一词不改**、也**不碰网络**）；
    - 传 callable ⇒ 用它取数（红证与判别力自证用**桩**）；
    - 常驻出口（`repo_problems`）**显式**传 `fetch_open_pr_claims` ⇒ 只有它联网。
    """
    entries, stray = scan_claims(claims_dir)
    claims = parse_claims(entries)
    return (
        stray
        + form_problems(entries)
        + duplicate_problems(claims)
        + collision_problems(claims, used, current, injected)
        + quota_problems(claims, used)
        + (cross_pr_claims_problems(claims, current, cross_fetch) if cross_fetch is not None else [])
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


def repo_problems(cross_fetch: object | None = None) -> list[str]:
    """仓内判据的**常驻出口**。

    `cross_fetch` 默认 = `fetch_open_pr_claims`（**唯一联网入口**，判据 7）；
    判据 7 内部再按「当前 PR 号可判定」收口 ⇒ 本机 / 非 PR 上下文**不发起**联网。
    """
    entries, _ = repo_claims()
    claims = parse_claims(entries)
    return all_problems(
        REPO_ROOT / CLAIMS_REL,
        repo_used_ids(),
        current_pr(claims),
        base_used_ids(),
        fetch_open_pr_claims if cross_fetch is None else cross_fetch,
    )


def test_repo_case_id_claims_are_clean() -> None:
    """仓内七条判据的**常驻出口**：当前树上的 claim 台账必须干净（没有 claim 时天然全绿）。

    CI 面这里**真的**会去读同仓 open PR 的 claims（判据 7）；读不到 ⇒ 判红且写明「判定不了」。
    """
    problems = repo_problems()
    assert problems == [], "取号登记台账判据报红：\n" + "\n".join(f"  - {p}" for p in problems)


def test_cross_pr_check_is_wired_into_the_repo_exit() -> None:
    """**接线判据（§28.2：判据本体绿 ≠ 接线在）**：`repo_problems()` 必须**真的**把判据 7 接上。

    🔴 事实：判据 7 的**行为**只在他处测（桩），它完全可以「实现正确但**没接进常驻出口**」——
    那时上面那条 `test_repo_case_id_claims_are_clean` 照旧全绿，而 issue #6245 的病**原样复发**。
    这里用**注入一个念过**的桩把接线本身判红：桩被调用 ⇒ 接线在。
    """
    called: list[int] = []

    def probe() -> tuple[list[OpenPrClaims], list[str]]:
        called.append(1)
        return [], []

    assert repo_problems(cross_fetch=probe) == []
    assert called == [1], (
        "`repo_problems()` 没有把判据 7 接进常驻出口（跨在飞 PR 的重号面又变成看不见了）"
    )


def test_live_probe_open_pr_claims_endpoint_is_readable(monkeypatch) -> None:
    """**直连真对象（§28.1 出口 ④）**：判据 7 的取数面**真的**能读同仓 open PR 的 claims。

    三态**各自可读**（本机常走 2/3，CI 走 1/3）：
    1. **Actions 环境 + 凭据**（= CI 口径）⇒ 必须读出一张 open PR 列表 + 逐 PR 的 claim 数（打进输出，
       这就是「这一轮真的读在飞面」的证据）；
    2. **Actions 环境、无凭据** ⇒ 恰好一条「**判定不了**」（fail-closed 的**可读**行为）；
    3. **非 Actions 环境**（本机没注入）⇒ `None` = **不发起判定**（判据 7 不适用），**零外呼**。
    """
    if not (os.environ.get(REPO_ENV) or "").strip():
        assert fetch_open_pr_claims() is None, "非 Actions 环境（无仓库名）⇒ 必须**不发起**判定"
        print("[cross-pr-claims-live-probe] 非 Actions 环境 ⇒ 判据 7 不发起（本机口径）")
        return
    monkeypatch.setenv(REPO_ENV, os.environ[REPO_ENV])
    result = fetch_open_pr_claims()
    assert result is not None, f"`{REPO_ENV}` 在环境里却返回 `None` ⇒ 门未按声明生效"
    open_prs, problems = result
    if token_value():
        assert all("判定不了" in p for p in problems), f"有凭据却出现非「判定不了」的问题：{problems}"
        print(
            "[cross-pr-claims-live-probe] open PR = "
            + str(len(open_prs))
            + "；逐 PR claim 数 = "
            + str({p.pr: ("读不到" if p.ids is None else len(p.ids)) for p in open_prs})
            + (f"；问题 = {problems}" if problems else "")
        )
    else:
        assert len(problems) == 1 and "判定不了" in problems[0], problems
        print(f"[cross-pr-claims-live-probe] 无凭据 ⇒ fail-closed：{problems[0]}")


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


def test_control_another_prs_landed_claim_is_a_ledger_record_not_an_error(tmp_path: Path) -> None:
    """本单核心修复的对照读数：**别人的落地 claim**（号已进用例库、claim 还在）⇒ **不红**。

    形状 = main 上真实存在的 `.github/cases/claims/6033-MC-067.json`（PR #6033 已合并、MC-067 已进用例库，
    见 issue #6037 的复算证据）+ 当前 PR（#6060）什么都没占。
    修前：它是「**陈旧 claim** ⇒ 删除该 claim 文件」；修后：它是**累积台账**里的一条分配登记 ⇒ 一条都不报。
    """
    _write_claim(tmp_path, "6033-MC-067.json", pr=6033, id="MC-067")
    claims = parse_claims(scan_claims(tmp_path)[0])
    assert claims, "夹具没被读到 ⇒ 本条的绿是空跑"
    used = Counter({"MC-067": 1, "MC-068": 1})
    # 判别力自证：**同一个 claim** 若被当成「本 PR 自己的」⇒ 立刻判红（绿只因作用域收窄，不是因为假绿）
    assert collision_problems(claims, used, current=6033, injected={"MC-067"}) != []
    assert collision_problems(claims, used, current=6060, injected={"MC-067"}) == []
    assert all_problems(tmp_path, used, current=6060, injected={"MC-067"}) == []


def test_red_proof_only_the_current_prs_claim_is_named(tmp_path: Path) -> None:
    """作用域判别力（收窄 ≠ 关掉判据）：同一批里**别人的**落地 claim 静默，**本 PR 自己撞号的那条**具名。

    ⇒ 「收窄」与「全量判红」在这条夹具上读数不同（不是把判据整体关掉）。
    """
    _write_claim(tmp_path, "6033-MC-067.json", pr=6033, id="MC-067")
    _write_claim(tmp_path, "6060-MC-068.json", pr=6060, id="MC-068")
    used = Counter({"MC-067": 1, "MC-068": 1})
    problems = all_problems(tmp_path, used, current=6060, injected={"MC-067", "MC-068"})
    joined = "\n".join(problems)
    assert len(problems) == 1, problems
    assert "6060-MC-068.json" in joined and "让号" in joined, joined
    assert "6033-MC-067.json" not in joined, joined


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


def test_merge_state_approximation_does_not_flag_another_prs_landed_claim(tmp_path: Path) -> None:
    """**无主线段注入**（= CI 的真实口径）下，**别人的落地 claim** 也不许被误判。

    形状 = main 侧遗留 claim（`MC-907`，PR #6019）+ 本 PR（#6020）自己的干净 claim `MC-908`，
    合并态里两个号都在用例库。修前：`MC-907` 被判「陈旧」（本单要修的病，实测读数见 issue #6037）；
    修后：它只是台账记录 ⇒ 不报；本 PR 自己的 `MC-908` 也不报（两边都不误伤）。
    """
    _write_claim(tmp_path, "6019-MC-907.json", pr=6019, id="MC-907")
    _write_claim(tmp_path, "6020-MC-908.json", pr=6020, id="MC-908")
    assert len(parse_claims(scan_claims(tmp_path)[0])) == 2, "夹具没被读到 ⇒ 本条的绿是空跑"
    used = Counter({"MC-907": 1, "MC-908": 1})
    problems = all_problems(tmp_path, used, current=6020, injected=None)
    assert problems == [], "\n".join(problems)


# ─────────────────────────────────────────────────────────────────────────────
# 判据 7 的红证（issue #6245）：跨在飞 PR 重号
#   取数面一律用**桩**（`fetch` 参数）⇒ 纯函数面**零网络、零时钟**；
#   真网络面只有一条**直连**判据（`test_live_probe_*`，两态都自证读了什么）。
# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
# 判据 7 的真 HTTP 面：`fetch_open_pr_claims` 自己（本机替身服务器，零外网）
# ─────────────────────────────────────────────────────────────────────────────
class _ApiStub:
    """GitHub REST 的**最小替身**（只认判据 7 用到的那两条路径 + `ref` 区分分支）。

    用它直连 `fetch_open_pr_claims`（真 `urllib` / 真超时 / 真状态码）⇒
    「替身桩」与「本机 / CI 拿不到网络 / 凭据」这两态都有**可读读数**。
    """

    def __init__(self, pulls: list[dict], contents: dict[str, object], status: int,
                 blobs: dict[str, str] | None = None, fail_first_status: int | None = None) -> None:
        self.pulls = pulls
        self.contents = contents
        self.status = status
        self.blobs = blobs or {}
        self.fail_first_status = fail_first_status
        self.seen_paths: set[str] = set()
        self.requests: list[str] = []

    def snapshot(self) -> tuple[int, list[str]]:
        return self.status, list(self.requests)

    def handle(self, method: str, path: str, query: str, authorized: bool
               ) -> tuple[int, object, str]:
        self.requests.append(f"{method} {path}")
        first_hit = path not in self.seen_paths
        self.seen_paths.add(path)
        if method != "GET":
            return 405, {"message": "Method Not Allowed"}, ""
        if not authorized:
            return 401, {"message": "Requires authentication"}, ""
        if self.fail_first_status is not None and first_hit and "/git/blobs/" in path:
            return self.fail_first_status, {"message": "transient"}, ""
        if path.endswith("/pulls"):
            return self.status, self.pulls, ""
        if "/git/blobs/" in path:
            content = self.blobs.get(path.rsplit("/git/blobs/", 1)[-1])
            if content is None:
                return 404, {"message": "Not Found"}, ""
            return 200, {
                "content": base64.b64encode(content.encode("utf-8")).decode(),
                "encoding": "base64",
            }, ""
        ref = (urllib.parse.parse_qs(query).get("ref") or [""])[0]
        tail = path.rsplit("/contents/", 1)[-1] if "/contents/" in path else ""
        got = self.contents.get(f"{ref}/{tail}") if tail else self.contents.get(ref)
        if got is None:
            return 404, {"message": "Not Found"}, ""
        if isinstance(got, list):
            return 200, got, ""
        return 200, {
            "content": base64.b64encode(got["content"].encode("utf-8")).decode(),
            "encoding": "base64",
        }, ""


def _serve_api(monkeypatch, stub: _ApiStub) -> str:
    """把 `_ApiStub` 挂成一个**真** HTTP 服务（后台线程），返回它的 `base` URL。"""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 的接口名
            parsed = urllib.parse.urlsplit(self.path)
            status, body, _ = stub.handle(
                "GET", parsed.path, parsed.query, bool(self.headers.get("Authorization"))
            )
            payload = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args: object) -> None:  # 静音（判据输出里不要 HTTP 日志）
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(stub, "_server", server, raising=False)
    return f"http://127.0.0.1:{server.server_address[1]}"


def _api_env(monkeypatch, base: str, token: str | None = "t") -> None:
    monkeypatch.setenv(API_ENV, base)
    monkeypatch.setenv(REPO_ENV, "acme/demo")
    for name in TOKEN_ENVS:
        if token is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, token)


def _release(stub: _ApiStub) -> None:
    server = getattr(stub, "_server", None)
    if server is not None:
        server.shutdown()
        server.server_close()


def test_http_no_token_is_fail_closed_and_reports_why(monkeypatch) -> None:
    """**反向对照 3（真 HTTP 面）**：**没有凭据** ⇒ 判「无法判定」⇒ 红，且**不发第一个请求**（零外呼）。"""
    stub = _ApiStub([], {}, 200)
    base = _serve_api(monkeypatch, stub)
    _api_env(monkeypatch, base, token=None)
    try:
        result = fetch_open_pr_claims()
        assert result is not None and len(result[1]) == 1 and "判定不了" in result[1][0], result
        assert stub.snapshot()[1] == [], "无凭据时不应该发出任何 HTTP 请求"
    finally:
        _release(stub)


def test_http_401_is_fail_closed(monkeypatch) -> None:
    """**反向对照 3（真 HTTP 面）**：替身返回 **401**（凭据无权限 / 过期）⇒ 判「无法判定」⇒ 红。"""
    stub = _ApiStub([], {}, 401)
    base = _serve_api(monkeypatch, stub)
    _api_env(monkeypatch, base)
    try:
        result = fetch_open_pr_claims()
        assert result is not None and len(result[1]) == 1, result
        assert "判定不了" in result[1][0] and "401" in result[1][0], result[1]
    finally:
        _release(stub)


def test_http_full_path_names_the_other_in_flight_pr(monkeypatch) -> None:
    """🔴 **红证（真 HTTP 面 / 端到端取数 + 去重）**：替身给两个 open PR，各自 claim 同一个号 ⇒

    ① 真取数路径把**别的 PR** 的号读出来（`fetch_open_pr_claims` 直连）；
    ② **同内容 SHA 的 claim 文件只下载一次**（请求序列里 `/git/blobs/<sha>` 各只出现一次）；
    ③ `cross_pr_claims_problems` **点名 #7002**。

    与桩版红证互补：**这一条证明「真取数路径 + 去重」都接对了**（§28.2 的「接线在」）。
    """
    pulls = [{"number": 7001, "head": {"sha": "sha-a"}}, {"number": 7002, "head": {"sha": "sha-b"}}]
    claim = json.dumps({"id": "MC-950", "pr": 7001, "title": "示范", "claimed_at": "2026-10-03"})
    directory = [{"name": "7001-MC-950.json", "sha": "blob-1"}]
    contents = {
        f"sha-a/{CLAIMS_API_PATH}": directory,
        f"sha-b/{CLAIMS_API_PATH}": [{"name": "7002-MC-950.json", "sha": "blob-2"}],
    }
    blobs = {"blob-1": claim, "blob-2": claim.replace('"pr": 7001', '"pr": 7002')}
    stub = _ApiStub(pulls, contents, 200, blobs)
    base = _serve_api(monkeypatch, stub)
    _api_env(monkeypatch, base)
    try:
        fetched = fetch_open_pr_claims()
        assert fetched is not None, "取数面返回 `None` ⇒ 不该发生（凭据与环境都已注入）"
        open_prs, problems = fetched
        assert problems == [], problems
        by_pr = {p.pr: p.ids for p in open_prs}
        assert by_pr == {7001: frozenset({"MC-950"}), 7002: frozenset({"MC-950"})}, by_pr
        blob_reads = [r for r in stub.snapshot()[1] if "/git/blobs/" in r]
        assert sorted(blob_reads) == ["GET /repos/acme/demo/git/blobs/blob-1", "GET /repos/acme/demo/git/blobs/blob-2"], blob_reads
        problems = cross_pr_claims_problems(
            [Claim(file=".github/cases/claims/7001-MC-950.json", pr=7001, cid="MC-950", title="示范")],
            current=7001,
            fetch=lambda: (open_prs, []),
        )
        assert len(problems) == 1 and "MC-950" in problems[0] and "#7002" in problems[0], problems
    finally:
        _release(stub)


def test_http_transient_500_is_retried_once_then_succeeds(monkeypatch) -> None:
    """**稳定性（瞬时重试）**：blob 第一次 **503**、第二次 200 ⇒ **不判「判定不了」**，读数正常。

    🔴 为什么值得一条判据：去重后一个 blob 被多个 PR 共用 ⇒ 一次瞬时抖动会把**所有**引用它的 PR
    一起判「读不到」⇒ 放大成整面红。没有这条重试，「合法 PR 因网络抖动变红」就是常态。
    同时自证**重试有界**：同一路径**恰好** 2 次（不是无限）。
    """
    claim = json.dumps({"id": "MC-952", "pr": 7001, "title": "示范", "claimed_at": "2026-10-03"})
    stub = _ApiStub(
        [{"number": 7001, "head": {"sha": "sha-a"}}],
        {"sha-a/" + CLAIMS_API_PATH: [{"name": "7001-MC-952.json", "sha": "blob-retry"}]},
        200,
        {"blob-retry": claim},
        fail_first_status=503,
    )
    base = _serve_api(monkeypatch, stub)
    _api_env(monkeypatch, base)
    monkeypatch.setattr("time.sleep", lambda _s: None)  # 重试不付等待（判据自己的时间不被偷）
    try:
        fetched = fetch_open_pr_claims()
        assert fetched is not None and fetched[1] == [], fetched
        assert {p.pr: p.ids for p in fetched[0]} == {7001: frozenset({"MC-952"})}, fetched[0]
        blob_reads = [r for r in stub.snapshot()[1] if "/git/blobs/" in r]
        assert blob_reads == [
            "GET /repos/acme/demo/git/blobs/blob-retry",
            "GET /repos/acme/demo/git/blobs/blob-retry",
        ], blob_reads
    finally:
        _release(stub)


def test_http_identical_claim_blob_is_downloaded_once(monkeypatch) -> None:
    """**成本红线（去重）**：三个 open PR 里**逐字节相同**的 claim 文件（同内容 SHA）⇒ 只下载 **1 次**。

    ⇒ 请求数从「每 PR 每文件一次」降到「唯一 blob 一次」；这是把墙钟压进预算的主要手段之一。
    """
    claim = json.dumps({"id": "MC-951", "pr": 7001, "title": "示范", "claimed_at": "2026-10-03"})
    pulls = [{"number": n, "head": {"sha": f"sha-{n}"}} for n in (7001, 7002, 7003)]
    contents = {
        f"sha-{n}/{CLAIMS_API_PATH}": [{"name": f"{n}-MC-951.json", "sha": "blob-shared"}]
        for n in (7001, 7002, 7003)
    }
    stub = _ApiStub(pulls, contents, 200, {"blob-shared": claim})
    base = _serve_api(monkeypatch, stub)
    _api_env(monkeypatch, base)
    try:
        fetched = fetch_open_pr_claims()
        assert fetched is not None and fetched[1] == [], fetched
        assert {p.pr: p.ids for p in fetched[0]} == {
            7001: frozenset({"MC-951"}),
            7002: frozenset({"MC-951"}),
            7003: frozenset({"MC-951"}),
        }, fetched[0]
        blob_reads = [r for r in stub.snapshot()[1] if "/git/blobs/" in r]
        assert blob_reads == ["GET /repos/acme/demo/git/blobs/blob-shared"], blob_reads
    finally:
        _release(stub)


def test_http_timeout_is_fail_closed_and_bounded(monkeypatch) -> None:
    """**成本红线（可判定 + 有界）**：取数面**必须**带超时；不可达 ⇒ 判「无法判定」⇒ 红（fail-closed）。

    替身指向一个**必拒连**的端口（1 号端口，本机不会监听）⇒ 真走 `urllib` 的失败分支；
    同时用 `HTTP_TIMEOUT_S` 自证**超时被真的传下去了**（不无限等 ⇒ 不拖 CI）。
    """
    calls: list[float] = []
    real = urllib.request.urlopen

    def spy(request, timeout=None):  # type: ignore[no-untyped-def]
        calls.append(timeout)
        return real(request, timeout=timeout)

    monkeypatch.setattr(urllib.request, "urlopen", spy)
    _api_env(monkeypatch, "http://127.0.0.1:1")
    monkeypatch.setattr("time.monotonic", lambda: 0.0)
    result = fetch_open_pr_claims()
    assert calls == [HTTP_TIMEOUT_S, HTTP_TIMEOUT_S], calls  # 恰好 2 次（瞬时重试一次，有界）
    assert result is not None and len(result[1]) == 1, result
    assert "判定不了" in result[1][0] and "open PR" in result[1][0], result[1]


def test_budget_stops_reading_the_in_flight_face(monkeypatch) -> None:
    """**成本红线（预算）**：读在飞面**到点即停**（记得住地判「无法判定」），不许把 CI 拖长。

    注入 `time.monotonic`（第一次 0，之后超 `BUDGET_S`）⇒ 第一个 PR **不读**就停，
    读数里出现「超过 Ns 预算」—— 这就是「**有界**」的机械证据。
    """
    stub = _ApiStub([{"number": 7003, "head": {"sha": "sha-c"}}], {"sha-c": []}, 200)
    base = _serve_api(monkeypatch, stub)
    _api_env(monkeypatch, base)
    ticks = iter([0.0] + [BUDGET_S + 1.0] * 50)
    monkeypatch.setattr("time.monotonic", lambda: next(ticks))
    try:
        fetched = fetch_open_pr_claims()
        assert fetched is not None and fetched[0] == [], fetched
        assert len(fetched[1]) == 1 and "预算" in fetched[1][0], fetched[1]
        assert stub.snapshot()[1] == ["GET /repos/acme/demo/pulls"], stub.snapshot()[1]
    finally:
        _release(stub)


def _stub(calls: list[int], **readings: frozenset[str] | None):
    """造一个 `fetch_open_pr_claims` 替身：`calls` 计次，各 PR 的号集由实参给。"""

    def fetch() -> tuple[list[OpenPrClaims], list[str]]:
        calls.append(1)
        return [OpenPrClaims(pr=int(k[1:]), ids=v) for k, v in sorted(readings.items())], []

    return fetch


def test_red_proof_two_in_flight_prs_claim_the_same_id(tmp_path: Path) -> None:
    """🔴 **红证（本单的牙）**：**本 PR** 的号与**另一个在飞 open PR** 同号 ⇒ 红，**点名对方 PR 号**。

    修前（= issue #6245 报到主会话之前的形态）：这份夹具里 `#6060-MC-911.json` 在**本工作树**，
    `#6061-MC-911.json` 在**别人的在飞分支**上 —— 旧判据（只扫本地目录 + main 侧近似）**一条都不报**。
    """
    _write_claim(tmp_path, "6060-MC-911.json", pr=6060, id="MC-911")
    claims = parse_claims(scan_claims(tmp_path)[0])
    calls: list[int] = []
    problems = cross_pr_claims_problems(
        claims, current=6060, fetch=_stub(calls, p6060=frozenset({"MC-911"}), p6061=frozenset({"MC-911"}))
    )
    joined = "\n".join(problems)
    assert calls == [1], "取数面没被调用 ⇒ 本条的绿/红都是空跑"
    assert len(problems) == 1, problems
    assert "MC-911" in joined and "#6060" in joined and "#6061" in joined, joined
    assert "后合入者让号" in joined, joined


def test_control_same_pr_claim_shape_is_not_a_cross_pr_collision(tmp_path: Path) -> None:
    """**反向对照 1**：**同一个 PR 内部**的合法形态（含仓内真语料 `6223-CH-045.json` 的等价物）⇒ **不红**。

    形态 = 本 PR（#6223）在**两个不同的用例域**各占一个号 —— 这是**合法**的（`6223-CH-045` + `6223-MC-075`
    就长这样，现取仓内真语料）；对方 PR 只占别的号。⇒ 判据 7 **必须**按 `pr` 收敛到「别的 open PR」，
    不许把本 PR 自己的两条 claim 算成撞号（那会逼着每个多 claim 的 PR 改号 ⇒ 判据自己制造摩擦）。

    判别力自证（同一份夹具）：把**对方**那个 PR 的号改成与 `MC-916` 相同 ⇒ 立刻红（见
    `test_control_merged_or_closed_pr_is_not_in_the_in_flight_face` 的第二半）。
    """
    _write_claim(tmp_path, "6223-CH-045.json", pr=6223, id="CH-045")
    _write_claim(tmp_path, "6223-MC-916.json", pr=6223, id="MC-916")
    claims = parse_claims(scan_claims(tmp_path)[0])
    assert len(claims) == 2, "夹具没被读到 ⇒ 本条的绿是空跑"
    calls: list[int] = []
    problems = cross_pr_claims_problems(
        claims,
        current=6223,
        fetch=_stub(calls, p6223=frozenset({"CH-045", "MC-916"}), p6224=frozenset({"MC-914"})),
    )
    assert calls == [1], "取数面没被调用 ⇒ 本条的绿是空跑"
    assert problems == [], "\n".join(problems)


def test_control_merged_or_closed_pr_is_not_in_the_in_flight_face(tmp_path: Path) -> None:
    """**反向对照 2**：对方 PR **已合并 / 已关闭** ⇒ 它**不在** `state=open` 列表里 ⇒ **不红**。

    那一档（本 PR ↔ main 已合入）由**判据 3** 管，判据 7 **不**重复、也**不**越界：
    桩只返回 open 的那些 ⇒ 已合并的 `#6064`（同号 `MC-915`）**读不到** ⇒ 判据 7 静默。
    这一条正是「分界线」：**同一份夹具**换成「#6064 仍在 open」⇒ 立刻红（判别力自证）。
    """
    _write_claim(tmp_path, "6065-MC-915.json", pr=6065, id="MC-915")
    claims = parse_claims(scan_claims(tmp_path)[0])
    merged_away = _stub([], p6065=frozenset({"MC-915"}), p6066=frozenset({"MC-916"}))
    assert cross_pr_claims_problems(claims, current=6065, fetch=merged_away) == []
    still_open = _stub([], p6065=frozenset({"MC-915"}), p6064=frozenset({"MC-915"}))
    problems = cross_pr_claims_problems(claims, current=6065, fetch=still_open)
    assert len(problems) == 1 and "#6064" in problems[0], problems


def test_red_proof_unreadable_in_flight_face_is_fail_closed_and_says_so(tmp_path: Path) -> None:
    """**反向对照 3（可判定性）**：读不到某个在飞 PR / 没有凭据 ⇒ **红（fail-closed）**，
    且文本**必须写明「判定不了」** —— 不许读成「没有重号」（本仓口径：❓ 不许读成 ✅）。

    四态一次给全（每一态的**读数不同**，不是同一句话重复四遍）：
    ① 某个 PR 的答案读不到（`ids=None`）⇒ 红，**点名那个 PR 号**；
    ② 取数面自报问题（Actions 环境里没凭据）⇒ 原样进红证，**不许**被吞成绿；
    ③ 本 PR 不在 open 列表里（时序竞态 / 权限）⇒ 读数不可信 ⇒ 红；
    ④ 非 Actions 环境（`fetch` 返回 `None`）⇒ 判据 7 整条不适用（本机口径，**零外呼**）。
    """
    _write_claim(tmp_path, "6067-MC-917.json", pr=6067, id="MC-917")
    claims = parse_claims(scan_claims(tmp_path)[0])
    # ① 某个在飞 PR 读不到 ⇒ 红且具名是哪个 PR
    partial = cross_pr_claims_problems(
        claims, current=6067, fetch=_stub([], p6067=frozenset({"MC-917"}), p6068=None)
    )
    assert len(partial) == 1, partial
    assert "判定不了" in partial[0] and "#6068" in partial[0], partial
    # ② 取数面自报问题（无凭据 / 离线）⇒ 原样进红证，且**不许**被吞成绿
    def broken() -> tuple[list[OpenPrClaims], list[str]]:
        return [], ["判定不了：没有 API 凭据（GITHUB_TOKEN/GH_TOKEN 都为空）"]

    assert cross_pr_claims_problems(claims, current=6067, fetch=broken) == [
        "判定不了：没有 API 凭据（GITHUB_TOKEN/GH_TOKEN 都为空）"
    ]
    # ③ 本 PR 不在 open 列表里 ⇒ 红：见同文件的
    #    `test_control_own_pr_absent_from_open_list_is_fail_closed`（分工登记，不在本条重复构造）
    assert cross_pr_claims_problems(claims, current=None, fetch=broken) == []
    assert cross_pr_claims_problems(claims, current=6067, fetch=lambda: None) == []


def test_control_own_pr_absent_from_open_list_is_fail_closed(tmp_path: Path) -> None:
    """**接线/一致性**：open 列表里**没有本 PR**（时序竞态 / 权限）⇒ 在飞面读数不可信 ⇒ 红。"""
    _write_claim(tmp_path, "6069-MC-918.json", pr=6069, id="MC-918")
    claims = parse_claims(scan_claims(tmp_path)[0])
    problems = cross_pr_claims_problems(claims, current=6069, fetch=_stub([], p6070=frozenset({"MC-919"})))
    assert problems and "判定不了" in problems[0] and "6069" in problems[0], problems


def test_duplicate_is_full_volume_while_collision_is_own_pr_scoped(tmp_path: Path) -> None:
    """判别力自证：**判据 2 全量判红** vs **判据 3 只看本 PR** —— 两条读数必须不同。

    - 别人的**两个** claim 同 id ⇒ 仍红（判据 2 不看 `pr`；那才是真正的撞号）；
    - 别人的**一条** claim 占着已用号（没有第二个 claim 与它同号）⇒ 不红（累积台账）。
    """
    dup = tmp_path / "dup"
    dup.mkdir()
    _write_claim(dup, "6019-MC-909.json", pr=6019, id="MC-909")
    _write_claim(dup, "6020-MC-909.json", pr=6020, id="MC-909")
    dup_problems = all_problems(dup, Counter({"MC-909": 2}), current=6060, injected={"MC-909"})
    assert any("同时占着" in p for p in dup_problems), dup_problems

    ledger = tmp_path / "ledger"
    ledger.mkdir()
    _write_claim(ledger, "6019-MC-910.json", pr=6019, id="MC-910")
    assert all_problems(ledger, Counter({"MC-910": 1}), current=6060, injected={"MC-910"}) == []


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
