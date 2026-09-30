# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 既有惯例：CI 结构类 L0 不变式统一挂 MC-012，
#   见 .github/cases/misc.yml。）
r"""任何 `docker push` 步骤必须有**显式上界** —— issue #5814 的类级元守卫（铁律 8 ②）。

## 病（**实测读数**，非推断；来源 = issue #5814 的施工单与 PR #5816）

部署端到端时长从 ~10min 恶化到 45–60min，大量 run 以 `cancelled` 收场。根因是
**从境外 GitHub 托管 runner 跨境推送大镜像到阿里云 ACR（cn-hangzhou）挂住**：

| 事实 | 现取读数 |
|---|---|
| `Build and push Docker image` 步 32 个样本 | **双峰**：`2.0 2.1 2.2 3.2 4.2`（健康）｜`11.7 … 40.2 40.4 42.6 43.4`（病态，min） |
| 三条腿中位 | ai-agent **40.2m** / admin-api **37.7m** / frontend **37.6m** |
| 现场日志（run `36582359732` · job `109453551643`） | `#14 pushing layers` → `#15 [auth] …aliyuncs.com pull,push token`（鉴权**成功**）⇒ **约 40 分钟零输出** ⇒ `##[error]The operation was canceled.` |
| 失败率 vs 体积（近 6 次/腿） | admin-api 302MB ⇒ **1/6**；admin-web 954MB ⇒ **2/6**；ai-agent 1.12GB ⇒ **3/6** |

⇒ 挂点是「推送到 ACR」而**没有上界**：它一直挂着直到 job 的 `timeout-minutes` 把 run 打死，
而打死报的是 `cancelled`（**不是** `failure`）⇒ 断路器不跳闸 ⇒ cron 自放大。

PR #5816 给三条 deploy 腿补了**单次 `timeout` 上界 + 重试 1 次**（最坏 2×720s = 24min < 45min），
但**留下 `bmini-h5-publish.yml` 一处未加固**（issue #5814 的 C′ 同批补齐；同时 ai-agent 腿的
`--push` 已随服务器侧构建**整体删除** ⇒ 它退出射程，相应地本判据的冻结元组由 4 条缩到 3 条
—— 这正是「台账/射程**只许缩短**」的形态：删掉一个推送面 ⇒ 射程同步收窄）。（该文件 `docker push` 后紧跟
`docker manifest inspect` 复验，job 级 `timeout-minutes: 30`，step 内**无** `timeout` 命令）。

## 射程（**现取，不按口头描述写** —— 铁律 11）

```bash
grep -rn "docker push\|--push" .github/workflows/
```

| 文件 | 命中 | 说明 |
|---|---|---|
| `.github/workflows/deploy-admin-api.yml` | **0**（原 2） | `docker push` ×2 **已由 issue #5814 的 C′ 整体删除**（改服务器侧构建 ⇒ 不推 ACR） |
| `.github/workflows/deploy-frontend.yml` | **0**（原 2） | 同上 |
| `.github/workflows/deploy-ai-agent-service.yml` | **0**（原 1） | `docker buildx build --push` **已由 C′ 删除** |
| `.github/workflows/bmini-h5-publish.yml` | 1 | `docker push` —— C′ 同批补上界后**现取唯一**的推送面 |
| `.github/workflows/worker-h5-publish.yml` | **0** | 静态落地面腿，无镜像 |
| `.github/workflows/c-end-h5-publish.yml` | **0** | 静态落地面腿，无镜像 |

⇒ 若把后两条 0 命中的腿写进射程，会得到**恒真的空断言**（或长出**幻影台账条目**）——
正是铁律 8「条数现取、台账只许缩短」要拦的形态。
非 workflow 载体（`scripts/` / `deploy/` / `.github/scripts/`）唯一命中是
`scripts/ci_cost_ledger.py` 的**文案**（不是真实推送）⇒ 射程 = `.github/workflows/**` 的 `run:` 正文。

## 判据（每条都能单独变红；注入式红证见 `test_discriminating_power`）

| # | 判据 | 变红的形态 |
|---|---|---|
| 1 | 语料与推送面**非空**，读数现取打印 | 扫不到任何 workflow / 推送面为空 ⇒ 红（反空跑：空集不是通过） |
| 2 | 每条 `docker push` / `--push` 的**命令行**必须带 `timeout` 上界 | 新腿自带 `docker push` 而无上界 ⇒ 红 |
| 3 | **反查口径**：命中集 ⊆ 射程 ∪ 台账 | 真语料里出现射程外的推送文件 ⇒ 红（射程被悄悄放大/漏登记） |
| 4 | 冻结射程 ⇄ 现取**双向相等** | 改冻结元组而不改语料（或反之）⇒ 红 |
| 5 | 台账**只许缩短** + **双向登记** | 台账里的文件必须**真的有**无上界推送（陈旧条目 ⇒ 红） |
| 6 | 冻结文件**存在** | 射程点名不存在的 workflow ⇒ 红（陈旧登记） |

🔴 **判据 2 只判「命令前有没有 `timeout <上界>`」，不判「有没有复验」**：`bmini-h5-publish.yml`
的 `docker push` 后**已有** `docker manifest inspect` 复验（fail-closed）⇒ 把「复验」算进判据会**误判**。

## 判定方式是确定的（零网络、零时钟）

本判据**只读仓内文件**（`.github/workflows/*.yml` + 本目录的台账 JSON）⇒ 同一份代码在任何时刻
给出**同一读数**。运行期读数（`gh run list`）**刻意不进判据**，只作为上面的证据表 + 复算命令。

## 覆盖面（照实登记，**不是**「已全覆盖」）

① 判不了「上界值够不够小」（本判据只判**命令行有没有 `timeout`**，值域另由各腿自己的判据钉住）；
② 判不了运行期「推送真的会挂」（本判据是**静态**的，静态上界在 ≠ 运行期不挂）；
③ 判不了 `docker push` 被写进别的形态（如 `docker image push` 别名、`buildx` 以外的封装脚本）；
④ `.github/workflows/**` 之外的新载体不在射程内（现取 0 真实命中，见上）。
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO / ".github" / "workflows"
LEDGER_PATH = Path(__file__).with_name("push_bound_ledger.json")

# 冻结射程（现取 3 条：真语料里**有**推送命令且**已**加上界的那三条）。改它必须同批改语料 ⇒ diff 里看得见。
# ⚠️ 射程**随事实收窄**（issue #5814 C′，2026-09-30）：三条部署腿的构建/推送步已被整体删除
# （改服务器侧构建 ⇒ 不推 ACR）⇒ 现取只剩 bmini 一处推送面。这正是「台账/射程**只许缩短**」。
PUSH_BOUND_GUARD_FILES_FROZEN = (
    "bmini-h5-publish.yml",
)
# 台账条数上限（只许缩短）。
LEDGER_MAX_FROZEN = 0

# 推送命令的**命令行**判据（`.github/workflows/` 现取两种形态）：
#   ① `docker push <ref>`        ② `docker buildx build … --push …`
PUSH_LINE_RE = re.compile(r"(?:\bdocker\s+push\b)|(?:^\s*--push\b)|(?:\s--push\b)")
# 「命令前有显式上界」= 同一命令行上 `timeout <上界>` 作为**前缀**出现。
# 上界形态：coreutils 的字面秒数（`timeout 720`）或变量展开（`timeout "${PUSH_TIMEOUT_SECS}"`）。
TIMEOUT_PREFIX_RE = re.compile(r"\btimeout\s+(?:-[A-Za-z]+\s+)*(?:\"?\$\{?[A-Za-z_][A-Za-z0-9_]*\}?\"?|\d+)\s")
def _iter_workflow_names() -> list[str]:
    return sorted(p.name for p in WORKFLOWS_DIR.glob("*.yml"))


# 一条 shell **语句**的起点：行首（允许缩进）就是命令名，且该行以 2+ 空格（YAML 续行）或
# 行首对齐打出。用它把多行命令切成语句 —— `timeout 720 docker buildx build \` 与其续行
# `--push .` 属**同一条语句**，所以续行上的 `--push` 继承了前面的上界。
STATEMENT_START_RE = re.compile(r"^\s{0,}[A-Za-z_./\"'$]")


def _cmd_lines(text: str) -> list[tuple[int, str, str]]:
    """纯函数：把 workflow 文本切成 (行号, 缩进, 正文)，剥掉注释行与行尾注释。

    只保留**非注释**行 ⇒ 注释里写 `docker push` / `timeout 720` 都是说明文字，不进判据。
    行尾注释（`#` 起）一并截掉 ⇒「把 timeout 写进注释」不会假绿。
    """
    out: list[tuple[int, str, str]] = []
    for i, raw in enumerate(text.splitlines(), start=1):
        body = raw.split("#", 1)[0].rstrip()
        if not body.strip():
            continue
        out.append((i, raw[: len(raw) - len(raw.lstrip())], body))
    return out


def _shell_corpus(text: str) -> list[tuple[int, str, str]]:
    """纯函数：只取 `run:` / `script:` 键之下的**缩进 shell 正文**（行号, 缩进, 正文）。

    ⚠️ 为什么必须只吃 shell 正文：把整份 YAML 都当命令 ⇒ YAML 结构行
    （`steps:` / `name:` / `on:` …）会被当成一条**永不结束**的命令，把后文真正的
    `docker push` 吸进同一条语句 ⇒ 报出 `bmini-h5-publish.yml:102: steps:` 这种
    **指错对象**的判红（实测踩到）。shell 正文的边界由缩进决定：`run:` 之下、
    下一个缩进 ≤ 键所在缩进的行为止。
    """
    lines = text.splitlines()
    out: list[tuple[int, str, str]] = []
    i = 0
    while i < len(lines):
        raw = lines[i]
        stripped_comment = raw.split("#", 1)[0].rstrip()
        m_block = re.match(r"^(\s*)(?:-\s+)?(?:run|script):\s*(?:\|[-+]?|>[-+]?)?\s*$", stripped_comment)
        m_inline = re.match(r"^(\s*)(?:-\s+)?(?:run|script):\s+(\S.*)$", stripped_comment)
        if m_block:
            key_indent = len(m_block.group(1))
            i += 1
            while i < len(lines):
                sub = lines[i]
                if not sub.strip():
                    i += 1
                    continue
                sub_indent = len(sub) - len(sub.lstrip())
                if sub_indent <= key_indent:
                    break
                body = sub.split("#", 1)[0].rstrip()
                if body.strip():
                    out.append((i + 1, " " * sub_indent, body))
                i += 1
            continue
        if m_inline:
            body = m_inline.group(2).rstrip()
            base = len(m_inline.group(1)) + 2
            out.append((i + 1, " " * base, body))
        i += 1
    return out


def push_violations_in_text(text: str) -> list[tuple[int, str]]:
    """纯函数：给一份 workflow 文本，返回**缺显式上界**的推送命令 (行号, 命令行)。

    判定单位 = **一条 shell 语句**（不是单行）：语句从其起点行累积到该语句结束
    （下一条**同缩进或更浅**的语句起点）—— 在累积文本里找 `timeout <上界>`。
    这样 `timeout "${PUSH_TIMEOUT_SECS}" docker buildx build \\` + 续行 `--push .`
    被正确认成**有上界**（PR #5816 的形态），而把 `timeout` 只写进注释、
    或写在**下一条**独立命令上，都判**无上界**。
    """
    bad: list[tuple[int, str]] = []
    buf: list[str] = []
    stmt_indent = 0
    stmt_start = 0

    def flush() -> None:
        nonlocal buf
        if buf:
            joined = "\n".join(buf)
            if PUSH_LINE_RE.search(joined) and not TIMEOUT_PREFIX_RE.search(joined):
                bad.append((stmt_start, buf[0].strip()))
        buf = []

    for lineno, indent, body in _shell_corpus(text):
        ind = len(indent)
        starts_stmt = (not buf) or ind <= stmt_indent
        if starts_stmt and buf:
            flush()
        if not buf:
            stmt_indent = ind
            stmt_start = lineno
        buf.append(body)
    flush()
    return bad


def scan(workflows: dict[str, str]) -> tuple[dict[str, int], list[str]]:
    """纯函数：扫一份 {文件名: 文本} 语料。

    返回 (逐文件推送命令条数, 违规行清单)。**语料由调用方给**（真语料 = 读仓；
    注入语料 = 内存构造）⇒ 同一份判定逻辑既能判真、也能判红。
    """
    counts: dict[str, int] = {}
    bad: list[str] = []
    for name in sorted(workflows):
        text = workflows[name]
        counts[name] = sum(1 for _l, _i, b in _shell_corpus(text) if PUSH_LINE_RE.search(b))
        bad.extend(f"{name}:{ln}: {line}" for ln, line in push_violations_in_text(text))
    return counts, bad


def load_real_workflows() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(WORKFLOWS_DIR.glob("*.yml"))}


def load_ledger() -> dict:
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


# ── 判据 1：语料与推送面非空（反空跑）──────────────────────────────────────────
def test_corpus_and_push_surface_are_non_empty() -> None:
    wfs = load_real_workflows()
    assert len(wfs) >= 20, f"反空跑锚点：只读到 {len(wfs)} 个 workflow —— 语料面几乎空，判据没有判别力"
    counts, _ = scan(wfs)
    hit = {k: v for k, v in counts.items() if v}
    print("推送面（现取，逐文件推送命令条数）：")
    for k in sorted(hit):
        print(f"  {k}: {hit[k]}")
    assert hit, "反空跑锚点：全仓一个 `docker push` / `--push` 都没扫到 —— 判据恒真，等于没判"


# ── 判据 2：每条推送命令行必须有显式上界（这就是本单要治的形态）────────────────
def test_every_push_command_has_explicit_timeout() -> None:
    _, bad = scan(load_real_workflows())
    assert not bad, (
        "以下推送命令**没有显式上界**（挂住时只能等 job 的 timeout-minutes 打死，"
        "而那是 `cancelled` ⇒ 断路器不跳闸 ⇒ cron 自放大；issue #5814）：\n  "
        + "\n  ".join(bad)
    )


# ── 判据 3：反查口径 —— 命中集 ⊆ 射程 ∪ 台账 ───────────────────────────────────
def test_hits_are_within_scope_or_ledger() -> None:
    counts, _ = scan(load_real_workflows())
    hits = {k for k, v in counts.items() if v}
    allowed = set(PUSH_BOUND_GUARD_FILES_FROZEN) | set(load_ledger().get("unbounded", {}))
    extra = sorted(hits - allowed)
    assert not extra, (
        f"推送面出现**射程外**的文件 {extra} ⇒ 新腿自带 `docker push` 却没登记。\n"
        f"出口：把它加进推送上界（推荐）或登记进 {LEDGER_PATH.name}。"
    )


# ── 判据 4：冻结射程 ⇄ 现取双向相等 ────────────────────────────────────────────
def test_frozen_scope_matches_live_read() -> None:
    counts, _ = scan(load_real_workflows())
    hits = {k for k, v in counts.items() if v}
    frozen = set(PUSH_BOUND_GUARD_FILES_FROZEN)
    assert hits == frozen, (
        "冻结射程与现取不一致（两处要一起改）：\n"
        f"  现取有推送但不在冻结射程：{sorted(hits - frozen)}\n"
        f"  冻结声明但没有推送（陈旧）：{sorted(frozen - hits)}"
    )


# ── 判据 5：台账双向 —— 只许缩短 + 条目必须真的无上界 ─────────────────────────
def test_ledger_is_shortenable_and_bidirectional() -> None:
    ledger = load_ledger()
    unbounded = ledger.get("unbounded", {})
    assert len(unbounded) <= LEDGER_MAX_FROZEN, (
        f"台账条数 {len(unbounded)} > 上限 {LEDGER_MAX_FROZEN}（台账**只许缩短**）"
    )
    _, bad = scan(load_real_workflows())
    still_bad = {b.split(":", 1)[0] for b in bad}
    stale = sorted(set(unbounded) - still_bad)
    assert not stale, (
        f"台账条目 {stale} 已**不再**是无上界推送（陈旧登记）⇒ 从台账里删掉它（只许缩短）"
    )


# ── 判据 6：冻结文件必须存在 ───────────────────────────────────────────────────
def test_frozen_files_exist() -> None:
    missing = [f for f in PUSH_BOUND_GUARD_FILES_FROZEN if not (WORKFLOWS_DIR / f).is_file()]
    assert not missing, f"射程点名了不存在的 workflow：{missing}（陈旧登记）"


# ── 注入式红证：每条判据各自能单独变红（真病，不是纸面）──────────────────────
def _wf(run_body: str) -> str:
    """一条最小可解析的 workflow，其 shell 正文 = `run_body`（按 10 空格缩进）。"""
    body = "\n".join((" " * 10 + ln) if ln.strip() else "" for ln in run_body.splitlines())
    return (
        "name: injected\non:\n  push:\n    branches: [main]\njobs:\n  b:\n"
        "    runs-on: ubuntu-latest\n    steps:\n      - name: s\n        run: |\n" + body + "\n"
    )


def test_discriminating_power() -> None:
    """往**真语料**注入变异 ⇒ 对真语料跑的那几条判据**必须**判红；且变异**真的被读到**。

    🔴 本测试对**真语料**重跑判据主体（不是只在内存里另算一遍）—— 否则「红证」证明的是
    另一份实现。判据 5（台账）例外：它读台账**文件**，故其红证走参数化（见
    `test_ledger_bidirectional_logic`）。
    """
    real = load_real_workflows()
    base_counts, base_bad = scan(real)
    base_hits = {k for k, v in base_counts.items() if v}
    assert not base_bad, "基线必须先绿（否则红证分不清是注入还是存量）"
    assert base_bad == [] and base_hits, "反空跑：基线既要有推送面、又不能有违规"

    # ① 新造一条带 `docker push` 而无上界的腿 ⇒ 判据 2/3/4 变红，且**点名**它
    injected = dict(real)
    injected["aaa-new-unbounded-leg.yml"] = _wf('docker build -t x .\ndocker push x:latest')
    inj_counts, inj_bad = scan(injected)
    assert inj_bad, "注入无上界推送后判据 2 没红 ⇒ 空断言"
    assert "aaa-new-unbounded-leg.yml" in inj_bad[0], f"判红没点名注入的文件 ⇒ 归因不可用：{inj_bad}"
    full_hits = {k for k, v in inj_counts.items() if v}
    assert full_hits - base_hits == {"aaa-new-unbounded-leg.yml"}, "注入的腿没被现取口径读到 ⇒ 变异没生效"

    # ② 把已加固的那条腿的 `timeout` 前缀拿掉 ⇒ 判据 2 变红（证明它真的在判上界）
    stripped = dict(real)
    stripped["bmini-h5-publish.yml"] = real["bmini-h5-publish.yml"].replace("timeout ", "")
    assert scan(stripped)[1], "去掉 `timeout` 前缀后判据 2 没红 ⇒ 上界判定是空断言"

    # ③ 上界只在**同一语句的注释**里（形态冒充）⇒ 仍须红：判据吃的是命令、不是说明文字
    assert push_violations_in_text(_wf('docker push x:latest   # timeout 720')), (
        "上界只出现在**行尾注释**里却判绿 ⇒ 判据读到了说明文字而非命令"
    )
    # ③b 上界写在**另一条独立命令**上（转移冒充）⇒ 仍须红
    assert push_violations_in_text(_wf('timeout 720 echo warm\ndocker push x:latest')), (
        "上界写在另一条独立命令上却判绿 ⇒ 语句切分把两条命令并成了一条"
    )
    # ③c 真正的多行形态（PR #5816 的样子）⇒ 必须**绿**（续行继承了上界）
    assert not push_violations_in_text(
        _wf('timeout "${PUSH_TIMEOUT_SECS}" docker buildx build \\\n  --push .')
    ), "多行 `timeout … docker buildx build \\` + `--push` 被误判为无上界（会假红）"

    # ④ 对照读数：**只加注释**（其中提到 docker push / timeout）⇒ 不红
    benign = dict(real)
    benign["bmini-h5-publish.yml"] = real["bmini-h5-publish.yml"] + (
        "\n# 这是一行新增注释：提到 timeout 720 与 docker push，但都不是命令\n"
    )
    assert not scan(benign)[1], "只加注释就判红 ⇒ 判据误吃说明文字（假红）"
    # ④b 读者一致性：变异**真的被读到**（坏形态读数 ≠ 基线读数）
    assert scan(benign)[0] == base_counts, "只加注释却改变了推送条数读数 ⇒ 读数不干净"


def test_ledger_bidirectional_logic() -> None:
    """判据 5 红证（参数化，不靠改仓内台账文件）：陈旧条目 / 超上限 / 真条目各一条。"""
    def problems(unbounded: dict, bad_files: set[str]) -> list[str]:
        out: list[str] = []
        if len(unbounded) > LEDGER_MAX_FROZEN:
            out.append("条数超上限（只许缩短）")
        stale = sorted(set(unbounded) - bad_files)
        if stale:
            out.append(f"陈旧条目 {stale}")
        return out

    # 真语料当前**没有**无上界推送 ⇒ 任何台账条目都是陈旧的（这正是「只许缩短」的语义）
    _, bad_now = scan(load_real_workflows())
    bad_files = {b.split(":", 1)[0] for b in bad_now}
    assert problems({}, bad_files) == [], "空台账 + 合规语料却报问题 ⇒ 判据 5 有假红"
    assert problems({"bmini-h5-publish.yml": "r"}, bad_files), "陈旧台账条目没报 ⇒ 判据 5 是空断言"
    assert problems({"a.yml": "r", "b.yml": "r"}, bad_files), "台账超上限没报 ⇒ 只许缩短失效"
    # 台账**文件**本身：结构齐备（反空跑）
    ledger = load_ledger()
    assert isinstance(ledger.get("unbounded"), dict), "台账缺 unbounded 字段 ⇒ 判据 5 会静默空跑"


def test_reader_mirror_matches_scan() -> None:
    """读者一致性：真语料扫描 ⇄ 深拷贝语料扫描走的是**同一条码路**（防「判的是另一份实现」）。"""
    real = load_real_workflows()
    mirrored = copy.deepcopy(real)
    assert scan(real) == scan(mirrored)
