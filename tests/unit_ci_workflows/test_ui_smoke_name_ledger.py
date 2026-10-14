# case_ids: MC-012
"""商家冒烟 spec 的**旅程名台账**守卫（issue #6942 ③）。

## 病灶（issue #6942 ③，2026-10-14 现取读数）

`scripts/ui-smoke-merchant/spec.mjs` 的 `ALL_JOURNEY_NAMES` 是「整轮看门狗到点时把**没跑到的**
旅程补记 skip」用的**名称台账**。它当时写的是 `27-corporate` / `28-register`，
而实际注册名是 `27-corporate-home` / `28-corporate-about` / `29-corporate-contact` /
`30-corporate-services` / `31-register` / `32-production-qr-and-piecework` ⇒ 台账与注册面**双向**漂移：

- 台账里 6 个名字**没有任何旅程注册**（看门狗到点给**不存在的旅程**补记 skip）；
- 实测 `--group 28` 因此匹配不到任何旅程：`0 pass / 0 fail / 29 skip`（issue 正文逐字）。

## 三道判据（都**会红**，且红得具名）

- **判据 G（静态面，双向）**：`ALL_JOURNEY_NAMES` 里的每个名字 :: 都必须在 spec 里**真的注册**
  （`jrun('<名>')` 调用点）；反过来，spec 里 `jrun` 的每个名字 :: 都必须在台账里。
  任一方向缺 ⇒ 红并报出**差集**（哪个名字 / 差多少 / 可复制命令）。
- **判据 G-R（运行面，fail-closed）**：用**桩 playwright** 真跑 `spec.mjs`（`--group 01-`
  把其余旅程全部过滤掉、`SMOKE_RUN_BUDGET_MS=0` 让看门狗**当场**到点），
  产出的 `smoke-results.json` 里**恰好**是台账那 32 个名字、且**全是 skip**：
  ① 台账里有「注册不了的名字」⇒ 它不会出现在结果里 ⇒ 红；
  ② 有「注册了却没登记」的名字 ⇒ 它出现在结果里 ⇒ 红；
  ③ 看门狗**没到点**（预算机制被改坏）⇒ 名字数量对不上 ⇒ 红。
- **判据 G-X（判别力自证）**：把台账**改回历史漂移形态**（`27-corporate` / `28-register`）
  ⇒ 判据 G 与 G-R **都**必须红（否则本判据是空判据）。

## 边界（照实登记，§19.1）

- 判据 G 是**静态面**（只读源码）：它**不**跑真栈、**不**证明「每个名字对应的旅程功能正常」——
  那是真栈行为面，证据在 PR body。
- `journey()` 内层名与 `jrun` 名的**同一性**在本判据里由**运行面**承担（G-R 的「恰好 32 个」）：
  `journey('<内层名>')` 若与 `jrun` 名分家，运行面记录的是**内层名** ⇒ G-R 当场红。
- 本判据**不改**任何旅程的业务断言。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from unit_ci_workflows._source_parsing import java_code  # noqa: E402  （#5323：剥注释的唯一实现）

SPEC = REPO_ROOT / "scripts" / "ui-smoke-merchant" / "spec.mjs"
SPEC_REL = "scripts/ui-smoke-merchant/spec.mjs"

# 实用上限：三条判据都能各自跑完（判据 G-R 要真起 node 跑桩）。
RUN_TIMEOUT_SECONDS = 120


# ────────────────────────── 判据 G：静态面（双向） ──────────────────────────
def _spec_code() -> str:
    """spec.mjs 的可执行面（**剥注释**）：注释里的示例名不算注册（#5323 的唯一实现）。"""
    return java_code(SPEC.read_text(encoding="utf-8"))


def ledger_names(spec_code: str) -> list[str] | None:
    """`ALL_JOURNEY_NAMES` 台账的**逐字**名字清单；定位不到 ⇒ `None`（fail-closed，见判据 G）。

    ⚠️ 取值面**必须是剥注释面**（`_spec_code()` = `_source_parsing.java_code()`，`#5323` 的唯一实现）：
    注释里写 `'99-ghost'` 不能变成台账成员（红证 = `test_ledger_read_ignores_comments`）。
    也**刻意不用** `re.findall(r"'...'")` 那种形态 —— 元守卫
    `test_guard_parsing_is_comment_aware.py` 把「引号定界捕获组 + 注释语料喂得中」判成
    「按引号扫**原文**」（本读法的注释无关性由**剥注释**给出，不由 pattern 的锚点给出）。
    """
    m = re.search(r"const ALL_JOURNEY_NAMES = \[(.*?)\n\]", spec_code, re.S)
    if not m:
        return None
    # 按单引号切分取**奇数段** = 字符串字面量的内容（spec.mjs 的台账成员一律单引号）
    return [part for part in m.group(1).split("'")[1::2] if part.strip()]


def registered_names(spec_code: str) -> list[str]:
    """spec 里真正被注册的旅程名（去重后按出现顺序）。

    **两个注册点都要收**：`jrun('<名>')`（走 45s 硬超时那批）与 `inGroup('<名>')`
    （`16-` / `17-` 这两条因为「现造 + 全流转」超 45s，由 `main` 里的 `if (inGroup(...))` 直接驱动，
    不过 `jrun`）—— 只收一个会把这两条**误判**成「台账里的幽灵名」。
    """
    return list(dict.fromkeys(re.findall(r"(?:jrun|inGroup)\('([^']+)'", spec_code)))


def ledger_drift(spec_code: str) -> list[str]:
    """判据 G 本体：返回**双向**差集（空 = 台账 ⇄ 注册面一致）。"""
    names = ledger_names(spec_code)
    if names is None:
        return [f"定位不到 `const ALL_JOURNEY_NAMES = [`（{SPEC_REL} 改名/改形）⇒ 本判据未行使，不得读成通过"]
    if not names:
        return [f"`ALL_JOURNEY_NAMES` 为空（{SPEC_REL}）—— 看门狗到点将不再补记任何 skip（fail-closed）"]
    registered = registered_names(spec_code)
    if not registered:
        return [f"`jrun('<名>')` 一个都定位不到（{SPEC_REL}）⇒ 本判据未行使，不得读成通过"]
    failures: list[str] = []
    ghost = [n for n in names if n not in registered]
    unlisted = [n for n in registered if n not in names]
    if ghost:
        failures.append(
            "台账里的名字**没有任何旅程注册**（看门狗到点会给不存在的旅程补记 skip）："
            f"{ghost} —— 逐字注册名 = `jrun('<名>')` / `inGroup('<名>')` 调用点；"
            f"改台账对齐（{SPEC_REL} 的 ALL_JOURNEY_NAMES）"
        )
    if unlisted:
        failures.append(
            "有旅程注册了却**不在台账里**（看门狗到点 / 预算到点都不会补记它）："
            f"{unlisted} —— 把**逐字注册名**补进 {SPEC_REL} 的 ALL_JOURNEY_NAMES"
        )
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        failures.append(f"台账里有重复名字（看门狗会重复补记 skip）：{dup}")
    return failures


# ────────────────────────── 判据 G-R：运行面（桩 playwright 真跑） ──────────────────────────
STUB_PLAYWRIGHT = r"""
// 桩 playwright（issue #6790/#6779 的既有沙箱形态；本判据只要求 spec 能跑到 finalize）：
// 不启真浏览器。登录步骤一律成功（cookie 置上），页面动作全部 no-op。
class Loc {
  constructor(page, label) { this.page = page; this.label = label }
  first() { return this }
  last() { return this }
  nth() { return this }
  locator(sel) { return new Loc(this.page, this.label + ' >> ' + sel) }
  filter() { return this }
  async isVisible() { return true }
  async allTextContents() { return ['1'] }
  async waitFor() { return true }
  async click() {
    this.page._url = this.page._url.replace('/login', '/dashboard')
    this.page.context()._cookies.set('access_token', 'stub-token')
    return true
  }
  async fill() { return true }
  async count() { return 1 }
  async selectOption() { return true }
  async inputValue() { return '' }
  async innerText() { return '' }
  async textContent() { return '' }
  async getAttribute() { return null }
  async evaluate() { return 1234 }
}
class Page {
  constructor(context) { this.ctx = context; this._url = ''; this.handlers = [] }
  context() { return this.ctx }
  // ⚠️ 真 playwright 的 `page.url()` 是**方法**（spec 里按 `page.url()` 用）—— 桩必须同形，
  //    否则「桩缺件」会把真判据染成噪声红（正是本判据要防的反面）。
  url() { return this._url }
  removeAllListeners() { this.handlers = [] }
  removeListener() { return this }
  on() { return this }
  async goto(url) {
    const u = String(url)
    // 登录后的导航都落在 BASE 下（`/login` 之外的页面）⇒ 一律记成 /dashboard，
    // 与真栈「登录成功即跳 /dashboard」一致；否则 `url()` 上会挂着一个不存在的 /login 页
    this._url = u.includes('/login') ? u : 'http://127.0.0.1:3001/dashboard'
  }
  async reload() { return true }
  async screenshot() { return Buffer.from('') }
  async evaluate() { return ['2.8米'] }
  async waitForTimeout() { return true }
  async waitForURL() { return true }
  async waitForFunction() { return true }
  async title() { return 'stub' }
  getByText(t) { return new Loc(this, 'text:' + t) }
  getByRole(_role, opts) { return new Loc(this, 'role:' + ((opts || {}).name || '')) }
  getByTestId(t) { return new Loc(this, 'testid:' + t) }
  locator(sel) { return new Loc(this, 'css:' + sel) }
  async fill() { return true }
}
class Context {
  constructor() { this._cookies = new Map(); this.pages = [] }
  async newPage() { const p = new Page(this); this.pages.push(p); return p }
  async cookies() { return [...this._cookies.entries()].map(([name, value]) => ({ name, value })) }
}
export const chromium = {
  async launch() {
    return {
      async newPage() { return new Page(new Context()) },
      async newContext() { return new Context() },
      async close() { return true },
    }
  },
}
"""


class SmokeSandbox:
    """桩 playwright 沙箱：`REPO_ROOT` 指向桩（`createRequire(REPO_ROOT/tests/package.json)`）。"""

    def __init__(self, tmp_path: Path, spec_source: str | None = None) -> None:
        self.tmp = tmp_path
        pkg = tmp_path / "tests/node_modules/playwright"
        pkg.mkdir(parents=True)
        (tmp_path / "tests/package.json").write_text("{}\n", encoding="utf-8")
        (pkg / "package.json").write_text('{"name":"playwright","main":"index.mjs"}\n', encoding="utf-8")
        (pkg / "index.mjs").write_text(STUB_PLAYWRIGHT, encoding="utf-8")
        self.spec = SPEC
        if spec_source is not None:
            # 变异注入：把**变异后的源码**写到与被驱动面**同构**的目录（真 spec 一字不动）。
            # ⚠️ `spec.mjs` 里 `import ... from './criteria.mjs'` 是**同目录相对 import** ——
            #    变异文件必须与 `criteria.mjs` 放进同一个 `scripts/ui-smoke-merchant/`，
            #    否则会以「模块找不到」退出（那是夹具缺件，会把判据染成噪声红）。
            d = tmp_path / "scripts" / "ui-smoke-merchant"
            d.mkdir(parents=True, exist_ok=True)
            shutil.copy(SPEC.parent / "criteria.mjs", d / "criteria.mjs")
            self.spec = d / "spec.mjs"
            self.spec.write_text(spec_source, encoding="utf-8")

    def run(self, **env_extra: str) -> subprocess.CompletedProcess:
        env = {
            **os.environ.copy(),
            "REPO_ROOT": str(self.tmp),
            "BASE_URL": "http://127.0.0.1:3001",
            "OUT_DIR": str(self.tmp / "out"),
            "GROUP": "",
            "SPEC_STUB_FAIL": "",
        }
        env.update(env_extra)
        return subprocess.run(
            ["node", str(self.spec)],
            cwd=str(self.tmp),
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=RUN_TIMEOUT_SECONDS,
        )

    def results(self) -> list[dict]:
        return json.loads((self.tmp / "out" / "smoke-results.json").read_text(encoding="utf-8"))


@pytest.fixture()
def smoke(tmp_path: Path) -> SmokeSandbox:
    return SmokeSandbox(tmp_path)


# ── 判据 G ──
def test_journey_name_ledger_matches_registered_names():
    """① 说真话的那条：台账 ⇄ 注册面**双向**一致（issue #6942 ③）。"""
    failures = ledger_drift(_spec_code())
    assert failures == [], "冒烟 spec 的旅程名台账已漂移：\n" + "\n".join(f"  - {f}" for f in failures)


def test_ledger_is_not_vacuous_and_names_are_disjoint():
    """② 夹具自证：台账非空、无重复、且确实覆盖了 27~31 这批**曾漂移**的名字。"""
    code = _spec_code()
    names = ledger_names(code)
    assert names, f"夹具不成立：{SPEC_REL} 里取不到 ALL_JOURNEY_NAMES"
    assert len(names) == len(set(names)), f"台账有重复名字：{names}"
    for n in ("27-corporate-home", "28-corporate-about", "29-corporate-contact",
              "30-corporate-services", "31-register"):
        assert n in names, f"夹具不成立：{n} 不在台账里（本判据的射程对象已经变了）"


def test_stale_ledger_names_would_be_caught():
    """③ 判别力自证（注入式红证）：台账改回历史漂移形态（`27-corporate` / `28-register`）⇒ 判据 G 红且具名。"""
    code = _spec_code()
    # ⚠️ 注入必须只落在**台账块内**：`'27-corporate-home'` 在注册点（`jrun(...)`）里也逐字出现，
    #    全文 `replace` 会把两边一起改掉 ⇒ 台账与注册面**仍然一致**、判据照旧绿（「注入未生效」）。
    m = re.search(r"const ALL_JOURNEY_NAMES = \[.*?\n\]", code, re.S)
    assert m, "夹具不成立：台账块定位失败"
    block = m.group(0)
    stale_block = block.replace("'27-corporate-home'", "'27-corporate'").replace("'31-register'", "'28-register'")
    assert stale_block != block, "注入未生效：台账块里找不到 '27-corporate-home' / '31-register'"
    stale = code[:m.start()] + stale_block + code[m.end():]
    failures = ledger_drift(stale)
    joined = "\n".join(failures)
    assert failures, "把台账改回漂移形态后判据 G 未红（判别力失效）"
    assert "27-corporate" in joined and "28-register" in joined, f"判红未具名（哪个名字）：{failures}"
    assert "没有任何旅程注册" in joined, f"判红未点明方向（台账→注册面）：{failures}"


def test_ledger_criterion_is_not_vacuous_on_comment_only_edit():
    """④ 对照读数（判据 G）：**只改注释** ⇒ 不红（判据不吃自己的说明文字）。"""
    commented = "// 说明：台账里曾写 27-corporate / 28-register（已随 issue #6942 对齐）\n" + SPEC.read_text(encoding="utf-8")
    assert ledger_drift(java_code(commented)) == []


def test_ledger_locator_fails_closed_when_block_disappears():
    """⑤ fail-closed：台账块被改名/删除 ⇒ 红（**不是**静默绿）。"""
    code = _spec_code()
    gone = code.replace("const ALL_JOURNEY_NAMES = [", "const SOME_OTHER_NAMES = [")
    assert gone != code, "注入未生效：找不到台账声明行"
    failures = ledger_drift(gone)
    assert failures and "定位不到" in failures[0], f"台账块消失后未 fail-closed：{failures}"


# ── 判据 G-R ──
def test_run_watchdog_skips_exactly_the_ledger_names(smoke: SmokeSandbox):
    """⑥ 运行面（fail-closed）：看门狗到点时，补记 skip 的名字**恰好**是台账那批。

    `--group 01-` 把其余旅程全部过滤掉 + 预算压到 1ms ⇒ 看门狗当场到点 ⇒ finalize 必须把
    **台账里每一个**名字都补记成 skip。台账里的「幽灵名」不会出现在结果里（→ 红），
    「注册了却没登记」的名字会出现在结果里（→ 红）。
    """
    ledger = ledger_names(_spec_code())
    assert ledger, "夹具不成立：取不到台账"
    proc = smoke.run(GROUP="01-", SMOKE_RUN_BUDGET_MS="0")
    out = proc.stdout + proc.stderr
    recs = smoke.results()
    names = [r["journey"] for r in recs]
    missing = [n for n in ledger if n not in names]
    extra = [n for n in names if n not in ledger]
    assert not missing and not extra, (
        f"运行面记录的名字与台账不一致：账里有而结果里没有={missing}；结果里有而账里没有={extra}"
    )
    # 口径（照实）：本判据钉的是「**看门狗的工作清单里，每个台账名都在**」这一层 ——
    # 即 finalize 的补记循环**不会漏记任何台账名**（漏记 ⇒ missing 非空 ⇒ 红）。
    # ⚠️ **不**断言「全部条目都是 skip」：`setTimeout(0)` 与同步快路径存在竞态，
    #    到点之前已经跑完的旅程本来就该是 pass/fail（那是**真跑**的读数，不能为了绿而抹平）。
    #    「到点后剩下的必须记成 skip 且写明到点」这一形态由 GROUP 过滤路径（上面那条）承担。
    assert "===== 汇总:" in out, f"spec 未走到 finalize：\n{out[-1500:]}"
    if "整轮预算" in out:
        noted = [r["journey"] for r in recs if r["skipped"] and r["notes"] and "到点" in r["notes"][0]]
        assert noted, "看门狗到点却没有任何补记条目带「到点」说明（「没跑」不像「没跑」）"


def test_watchdog_ledger_records_stay_in_sync_with_the_registered_names(tmp_path: Path):
    """⑦ 运行面（全量 + 看门狗到点）：补记 skip 之后，结果里的名字仍然**恰好**是注册面那批。

    看门狗到点会给「台账里、但本轮没跑到」的名字补记 skip —— 这条钉的是**补记之后**仍然一致：
    台账里的幽灵名会被补记出来（→ 结果里多出没有注册点的名字 ⇒ 红），
    注册面里有而台账没有的名字则**永远补记不到**（→ 结果里少名字 ⇒ 红）。
    """
    box = SmokeSandbox(tmp_path)
    box.run(SMOKE_RUN_BUDGET_MS="0")
    names = [r["journey"] for r in box.results()]
    registered = registered_names(_spec_code())
    ledger = ledger_names(_spec_code())
    assert sorted(names) == sorted(ledger) == sorted(set(registered)), (
        f"名册三方不一致：结果={sorted(names)}\n台账={sorted(ledger)}\n注册面={sorted(set(registered))}"
    )


def test_run_finalize_catches_a_journey_missing_from_the_ledger(tmp_path: Path):
    """⑧ 运行面另一半（fail-closed）：**注册了却没登记**的名字 ⇒ 运行面必须判红。

    静态面判据 G 抓的是「台账 → 注册面」；反方向（新增旅程忘了登记台账）**只能**在运行面看见 ——
    这里把 `31-register` 的注册名改成台账里没有的名字，真跑一遍（桩形态，网络面失败与本判据无关：
    看的是 `journey-name-ledger` 这条**台账记录**，不是旅程自身的通过与否）。
    """
    original = _spec_code()
    # 用正则按**调用形态**注入（缩进/换行无关）—— 字面 replace 会因剥注释后的缩进差异静默落空。
    # ⚠️ 注册点有**两处**：`jrun('<名>')`（工作清单/finalize 补记用）与 `journey('<名>')`（真正进
    #    results 的那一处）—— 只改一处时，results 里仍然记着旧名 ⇒ 注入静默失效（实测踩过）。
    mutated, n = re.subn(r"(jrun\('|journey\(')31-register(')", r"\g<1>99-unlisted-journey\g<2>", original)
    assert mutated != original and n == 2, f"注入未生效：31-register 的注册点命中 {n} 处（期望 2）"
    box = SmokeSandbox(tmp_path, spec_source=mutated)
    box.run(SMOKE_RUN_BUDGET_MS="60000")
    names = [r["journey"] for r in box.results()]
    assert "99-unlisted-journey" in names, f"夹具不成立：全量跑未记录到注入的旅程名：{names}"
    assert "journey-name-ledger" in names, f"运行面未报台账漂移条目（fail-closed 失效）：{names}"
    ledger_rec = next(r for r in box.results() if r["journey"] == "journey-name-ledger")
    assert ledger_rec["pass"] is False, "台账漂移条目被标成通过（空判据）"
    assert "99-unlisted-journey" in " ".join(ledger_rec["errors"]), (
        f"判红未具名（哪个名字没登记）：{ledger_rec['errors']}"
    )


def test_ledger_read_ignores_comments():
    """⑭ 判据 G 的**取值面**自证：注释里的幽灵名不得被读成台账成员（`#5323` 族）。"""
    code = _spec_code()
    names = ledger_names(code)
    assert names, "夹具不成立：台账读不到名字"
    # 在台账块**内部**插一行注释（形态与真实注释一致），其中写一个不存在的旅程名
    injected_src = SPEC.read_text(encoding="utf-8").replace(
        "const ALL_JOURNEY_NAMES = [",
        "const ALL_JOURNEY_NAMES = [\n  // 示例（不是成员）：'99-ghost-journey',",
        1,
    )
    injected = java_code(injected_src)
    assert "'99-ghost-journey'" in injected_src, "注入未生效：注释没写进去"
    got = ledger_names(injected)
    assert got == names, f"注释里的幽灵名被读成台账成员：{got}"
    # 判别力对照：同一条幽灵名写在**可执行面**（不是注释）⇒ 必须被读到
    live = java_code(injected_src.replace("  // 示例（不是成员）：'99-ghost-journey',", "  '99-ghost-journey',"))
    assert "99-ghost-journey" in (ledger_names(live) or []), "对照组不成立：可执行面的成员没被读到"


# ── 判据 K（issue #6942 ②：单组跑时的登录自补，**逐旅程**静态守卫） ──
# 免登录面：`/`（门户四页之一）/ 门户其余路径 / `/register` —— 它们**本来就不该**要登录态。
LOGIN_OPTIONAL_PATHS = ("/", "/about", "/contact", "/services", "/register", "/login")


def _page_visit_functions(spec_code: str) -> dict[str, list[str]]:
    """spec 里「会导航到某个页面」的函数 ⇒ 它访问过的路径（`nav(page, '<路径>'` / `page.goto(BASE + '<路径>'`）。"""
    out: dict[str, list[str]] = {}
    for block in re.split(r"\nasync function ", spec_code)[1:]:
        name = block.split("(")[0]
        navs = re.findall(r"(?:nav\(page, |page\.goto\(BASE \+ )'([^']*)'", block)
        if navs:
            out[name] = navs
    return out


def login_selfheal_failures(spec_code: str) -> list[str]:
    """判据 K 本体：访问**需登录页面**的函数必须 `await ensureLoggedIn(page)`（空 = 合规）。

    病灶（issue #6942 ②）：`--group NN` 会把 `01-login` 一并过滤掉 ⇒ 单组跑时**没有前置会话**。
    早先只有一部分旅程自补登录（`10-`/`11-`），其余靠「全量跑里 01- 先跑过」这个**顺序依赖**
    —— 单跑就红（实测 `--group 12` / `--group 21`：停在 `/login` + 401）。
    """
    failures: list[str] = []
    visited = _page_visit_functions(spec_code)
    assert visited, f"夹具不成立：{SPEC_REL} 里一个页面访问点都定位不到（原语改名了？）"
    for name, navs in visited.items():
        needs = [p for p in navs if p not in LOGIN_OPTIONAL_PATHS]
        if not needs:
            continue  # 只访问免登录面（门户 / 注册）
        block = re.split(r"\nasync function ", spec_code)[1:]
        body = next((b for b in block if b.split("(")[0] == name), "")
        if "ensureLoggedIn(page)" not in body:
            failures.append(
                f"{name} 会访问需登录页面 {needs}，却没有 `await ensureLoggedIn(page)` —— "
                f"单组跑（`--group NN` 过滤掉 01-login）时没有前置会话 ⇒ 会被弹回 /login（issue #6942 ②）"
            )
    return failures


def test_every_page_visit_selfheals_login():
    """⑫ 说真话的那条（判据 K）：每个访问需登录页面的旅程都必须自补登录态。"""
    failures = login_selfheal_failures(_spec_code())
    assert failures == [], "有旅程缺登录自补（单组跑会红）：\n" + "\n".join(f"  - {f}" for f in failures)


def test_login_selfheal_criterion_has_teeth():
    """⑬ 判别力自证（判据 K）：摘掉某旅程的 `ensureLoggedIn` ⇒ 当场红且具名。"""
    code = _spec_code()
    assert login_selfheal_failures(code) == [], "夹具不成立：现状应当绿"
    # 注入：摘掉 dashboardJourney 里那一行登录自补（**按旅程块**摘，避免误伤别的旅程的同名行）
    blocks = re.split(r"\nasync function ", code)
    out = [blocks[0]]
    hit = False
    for b in blocks[1:]:
        if b.split("(")[0] == "dashboardJourney":
            assert "    await ensureLoggedIn(page)\n" in b, "注入未生效：dashboardJourney 里找不到登录自补"
            b = b.replace("    await ensureLoggedIn(page)\n", "", 1)
            hit = True
        out.append(b)
    assert hit, "注入未生效：找不到 dashboardJourney"
    injected = "\nasync function ".join(out)
    failures = login_selfheal_failures(injected)
    assert any("dashboardJourney" in f for f in failures), f"摘掉登录自补后判据 K 未红：{failures}"
    # 对照读数：只改注释 ⇒ 不红
    commented = "// 说明：每个需登录旅程都要 ensureLoggedIn(page)（issue #6942 ②）\n" + code
    assert login_selfheal_failures(commented) == [], "只改注释就红了（判据吃自己的说明文字）"


# ── 判据 J（issue #6942 ① 的**类级**判据：打向不存在商品对象的 404） ──
def test_product_404_criterion_can_be_injected_red(smoke: SmokeSandbox):
    """⑪ 判别力自证：`SMOKE_PRODUCT_404_STRICT=1` 让「指向不存在对象」的那一刻可复现 ⇒ 旅程判红。

    真形态（issue #6942 ① 正文逐字）= `404 GET /api/admin/products/73cc4ac45d4053719865a88d3570b932`
    —— 它是**偶发**的（取决于别的旅程/上一轮有没有把那个对象清掉）⇒ 真栈上没法稳定复现；
    这条注入把「本旅程窗口里出现指向不存在商品的 404」这一**事件面**做成了可复现的红证。
    """
    # ⚠️ 两次真跑要各写各的 OUT_DIR：同目录会被第二次覆盖（结果面读数会张冠李戴）
    out_red = smoke.tmp / "out-red"
    red = smoke.run(GROUP="12-", SMOKE_RUN_BUDGET_MS="60000", OUT_DIR=str(out_red), SMOKE_PRODUCT_404_STRICT="1")
    recs = {r["journey"]: r for r in json.loads((out_red / "smoke-results.json").read_text(encoding="utf-8"))}
    assert "12-processing" in recs, f"夹具不成立：12- 未记录：{list(recs)}"
    assert recs["12-processing"]["pass"] is False, "注入「指向不存在对象的 404」后旅程未判红（空判据）"
    assert any("不存在" in e and "product" in e for e in recs["12-processing"]["errors"]), (
        f"判红未点名「哪个对象 404」：{recs['12-processing']['errors']}"
    )
    assert red.returncode != 0, "注入后退出码仍为 0（红灯不落地）"
    # 对照读数：不开开关 ⇒ 同一旅程不红（判据不是恒真）
    out_clean = smoke.tmp / "out-clean"
    smoke.run(GROUP="12-", SMOKE_RUN_BUDGET_MS="60000", OUT_DIR=str(out_clean))
    recs2 = {r["journey"]: r for r in json.loads((out_clean / "smoke-results.json").read_text(encoding="utf-8"))}
    assert recs2["12-processing"]["pass"] is True, (
        f"夹具不成立：不开注入时 12- 本应绿：{recs2['12-processing']['errors']}"
    )


# ── 夹具自身的可运行性自证（否则上面几条会因桩缺件而假红） ──
def test_stub_sandbox_can_reach_the_finalize_section(smoke: SmokeSandbox):
    """⑨ 桩自证：真跑（`--group 01-`）能走到 finalize 并落盘两个产物。"""
    proc = smoke.run(GROUP="01-", SMOKE_RUN_BUDGET_MS="60000")
    out = proc.stdout + proc.stderr
    # ⚠️ 判据 = 「spec 走到了 finalize」而**不是**「零失败」：桩没有真栈的 fetch / DOM，
    #    依赖它们的旅程本就会失败（那是桩的已知边界，与本判据无关）。
    assert "===== 汇总:" in out, f"spec 未走到 finalize（桩缺件）：\n{out[-1500:]}"
    assert (smoke.tmp / "out" / "smoke-results.json").exists(), "未落盘 smoke-results.json"
    assert (smoke.tmp / "out" / "smoke-summary.md").exists(), "未落盘 smoke-summary.md"
    assert shutil.which("node"), "node 不可用（本判据的结构前提）"


def test_no_journey_name_is_silently_dropped_between_calls(tmp_path: Path):
    """⑩ 运行面（全量）：不设 `--group` 时，**每个**注册名都必须被记录，且不得触发台账漂移。

    ⚠️ 判据是 `journey-name-ledger` 记录**不存在**（不是退出码）：桩形态下依赖网络的旅程
    （`fetch` 不可达）本就会失败，退出码非 0 与「名字台账一致」无关 —— 用退出码会把判据变成噪声。
    """
    box = SmokeSandbox(tmp_path)
    box.run(SMOKE_RUN_BUDGET_MS="60000")
    names = [r["journey"] for r in box.results()]
    ledger = ledger_names(_spec_code())
    assert sorted(names) == sorted(ledger), (
        f"全量跑记录的名字与台账不一致：账里有而结果里没有={[n for n in ledger if n not in names]}；"
        f"结果里有而账里没有={[n for n in names if n not in ledger]}"
    )
    assert "journey-name-ledger" not in names, (
        "全量跑触发了台账漂移条目（注册了却没登记）："
        + str(next((r["errors"] for r in box.results() if r["journey"] == "journey-name-ledger"), []))
    )
