# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012）
"""「用墙钟造期望值」机械守卫（`time_flaky_guard.py`）的 L0 测试 —— 关联 issue #4717。

## 为什么这条守卫值得存在

两次真实事故都是**随机红**、且都落在 **required** 的 job 里，于是**随机卡任何 PR**：
#4713（`fbc83a163` 修）期望值取自断言时的"现在"、被测组件渲染的却是消息自己的时间戳；
#4717（`13f6faaa3` 修）`await waitFor(A)` 后同步断言与 A 无因果关系的 B。
修事故点不够 —— 下一次同款会以别的文件、别的字段名再来一遍，所以本次落**机械判据**。

## 本文件锁五件事（每条都有反例输入）

1. **能区分「造夹具数据」与「造期望值」**：`created_at: new Date().toISOString()` 喂给
   `render(...)` ⇒ **不报**；`const expected = new Date()...` 后进 `expect(...)` ⇒ **报**；
2. **停表不是参照物**：`const start = Date.now()` … `expect(Date.now() - start).toBeGreaterThanOrEqual(x)`
   ⇒ **不报**（否则会误伤真实存在的 `retry.test.ts`）；
3. **冻结时间 ⇒ 不报**，但**冻结的作用域是块级的** —— 同文件另一条用例用墙钟造期望**仍要报**
   （否则「文件里有一处 `useFakeTimers` ⇒ 整文件免检」就是一条静默失效）；
4. **不许写死计数**：存量豁免从 `time_flaky_baseline.json` 派生，且**只许缩短**
   （新命中 / 计数增长 / 已修未销账 三种都判红）；
5. **形态 B 不做门禁**：朴素机械化规则在**合法**用例上就会命中（下面用同一次交互、同一个
   commit 产出两个 testid 的正常用例作反例）⇒ 它只能是 advisory 普查，不能进退出码。

## 红证

红证全部由**内联样本**驱动 `scan_text()` 本体（不落盘、不依赖 git 历史 —— 照 §18.3
「红证锚点禁读可变引用」）。`test_4713_verbatim_prefix_still_red` 里的样本是 `fbc83a163^`
的**逐字节片段**（出处写在样本上方）。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUARD = Path(__file__).resolve().parent / "time_flaky_guard.py"
LEDGER = Path(__file__).resolve().parent / "time_flaky_baseline.json"


def _load_guard():
    """按路径加载守卫模块（`tests/unit_ci_workflows/` 下的兄弟模块，不靠 sys.path）。"""
    spec = importlib.util.spec_from_file_location("time_flaky_guard", GUARD)
    module = importlib.util.module_from_spec(spec)
    sys.modules["time_flaky_guard"] = module
    spec.loader.exec_module(module)
    return module


mod = _load_guard()


# ── 样本：真红（期望值一侧来自墙钟） ────────────────────────────────────────

# 出处 `fbc83a163^:frontend/mini-app/tests/message-bubble.test.tsx`（issue #4713 的**改前**逐字片段）。
FLAKY_4713_VERBATIM = """  it('应渲染时间戳', () => {
    const now = new Date()
    const hours = String(now.getHours()).padStart(2, '0')
    const minutes = String(now.getMinutes()).padStart(2, '0')
    const expectedTime = `${hours}:${minutes}`

    render(<MessageBubble message={baseMsg} />)
    expect(screen.getByText(expectedTime)).toBeTruthy()
  })
"""

# 月粒度 + `toHaveBeenCalledWith`（现存 `production-piecework.test.tsx` 的同款形态）。
FLAKY_MONTH_GRANULARITY = """
  it('默认期间 = 当前月', async () => {
    const expected = new Date().toISOString().slice(0, 7)
    render(<Page />)
    await waitFor(() => expect(mockGet).toHaveBeenCalled())
    expect(mockGet).toHaveBeenCalledWith({ period: expected })
    expect(screen.getByTestId('period')).toHaveValue(expected)
  })
"""

# 毫秒级、**无**任何「时间桶」投影 —— 证明判据不是「只认 toISOString/slice 那几种写法」。
FLAKY_MS_LEVEL = """
  it('上报时刻 = 现在', async () => {
    const now = Date.now()
    await submit()
    expect(posted.at).toBe(now)
  })
"""

# ── 样本：合法（不许报） ────────────────────────────────────────────────────

LEGIT_FIXTURE_ONLY = """
  const msg = { id: 'm1', created_at: new Date().toISOString() }

  it('渲染内容', () => {
    render(<MessageBubble message={msg} />)
    expect(screen.getByText('你好')).toBeTruthy()
  })
"""

LEGIT_STOPWATCH = """
  it('指数退避的时长下界', async () => {
    const start = Date.now()
    const result = await withRetry(fn, { baseDelayMs: 100 })
    expect(result).toBe('ok')
    expect(Date.now() - start).toBeGreaterThanOrEqual(550)
  })
"""

LEGIT_FROZEN = """
  it('时间戳取自消息而非当前时间', () => {
    jest.useFakeTimers()
    jest.setSystemTime(FROZEN_NOW)
    try {
      const expected = new Date().toISOString()
      render(<MessageBubble message={baseMsg} />)
      expect(screen.getByText(expected)).toBeTruthy()
    } finally {
      jest.useRealTimers()
    }
  })
"""

LEGIT_COMMENT_MENTION = """
  // 期望值**不要**写成 new Date()（issue #4713）；Date.now() 同理
  it('内容', () => {
    expect(screen.getByText('你好')).toBeTruthy()  // 这里也别用 new Date()
  })
"""

# 块级冻结精度的反例：A 冻结、B 不冻结 ⇒ B 必须**仍然**被判红。
MIXED_FROZEN_AND_FLAKY = """
  it('a：冻结时间', () => {
    vi.useFakeTimers()
    vi.setSystemTime(FROZEN_NOW)
    const expected = new Date().toISOString()
    expect(screen.getByText(expected)).toBeTruthy()
  })

  it('b：同文件但没冻结', () => {
    const expected = new Date().toISOString()
    expect(mockPost).toHaveBeenCalledWith({ at: expected })
  })
"""


# ═══════════════════════════════════════════════════════════════════════════
# 1. 红证：判据**会**红
# ═══════════════════════════════════════════════════════════════════════════
def test_4713_verbatim_prefix_still_red():
    """#4713 改前逐字片段 ⇒ 必红（否则这条守卫治不了本单的原始事故）。"""
    found = mod.scan_text(FLAKY_4713_VERBATIM, "sample.test.tsx")
    assert [f.symbol for f in found] == ["expectedTime"], found


def test_month_granularity_expected_value_is_red():
    """月粒度 + `toHaveBeenCalledWith`（现存存量同款）⇒ 必红。"""
    found = mod.scan_text(FLAKY_MONTH_GRANULARITY, "sample.test.tsx")
    assert [f.symbol for f in found] == ["expected", "expected"], found


def test_ms_level_expected_value_is_red_without_time_bucket():
    """毫秒级、无时间桶投影 ⇒ 也必红（判据不是「只认某几种格式化写法」）。"""
    found = mod.scan_text(FLAKY_MS_LEVEL, "sample.test.tsx")
    assert [f.symbol for f in found] == ["now"], found


def test_frozen_scope_is_per_block_not_per_file():
    """同文件里 A 冻结、B 不冻结 ⇒ **B 仍要报**（防「文件里有一处 useFakeTimers ⇒ 整文件免检」）。"""
    found = mod.scan_text(MIXED_FROZEN_AND_FLAKY, "sample.test.tsx")
    assert [f.symbol for f in found] == ["expected"], found
    assert found[0].line > MIXED_FROZEN_AND_FLAKY[:MIXED_FROZEN_AND_FLAKY.index("it('b")].count("\n")


# ═══════════════════════════════════════════════════════════════════════════
# 2. 反向护栏：判据**不许**假红
# ═══════════════════════════════════════════════════════════════════════════
def test_fixture_only_use_is_not_red():
    """只造**夹具数据**（`created_at: new Date().toISOString()` 喂给组件）⇒ 不报。"""
    assert mod.scan_text(LEGIT_FIXTURE_ONLY, "sample.test.tsx") == []


def test_stopwatch_duration_is_not_red():
    """用同一只钟量**时长**（`expect(Date.now() - start)` 比下界）⇒ 不报。

    反例的真实出处：`frontend/admin-web/tests/unit/lib/retry.test.ts` 的
    `exponential backoff delays` 用例 —— 它是**合法**的（`setTimeout` 不会提前触发，
    下界断言对慢机器免疫），误判它等于一落地就红一个既有文件。
    """
    assert mod.scan_text(LEGIT_STOPWATCH, "sample.test.tsx") == []


def test_frozen_time_is_not_red():
    """正确冻结时间（`useFakeTimers()` + `setSystemTime`）⇒ 不报（这是**推荐修法**）。"""
    assert mod.scan_text(LEGIT_FROZEN, "sample.test.tsx") == []


def test_comment_mention_is_not_red():
    """注释里**提及** `new Date()` / `Date.now()` ⇒ 不报（否则整改说明自己会把门禁点红）。"""
    assert mod.scan_text(LEGIT_COMMENT_MENTION, "sample.test.tsx") == []


def test_string_literal_and_property_names_do_not_carry_taint():
    """字符串里的同名 token 与 `.` 之后的属性名不算载体（两条实测假红）。"""
    sample = """
  function todayLocal() {
    const d = new Date()
    const dd = String(d.getDate()).padStart(2, '0')
    return `${d.getFullYear()}-${dd}`
  }

  it('x', () => {
    expect(screen.getByPlaceholderText('交期 yyyy-MM-dd')).toBeInTheDocument()
  })
"""
    # 字符串 `'交期 yyyy-MM-dd'` 里的 `dd` 与污点变量 `dd` 撞名 —— 不得据此判红。
    assert mod.scan_text(sample, "sample.test.tsx") == []


def test_existing_suite_has_no_new_findings():
    """**现有全量前端测试面**：新增命中 = 0（存量从账本派生，不写死计数）。

    这条就是「反向护栏」的主读数：`--list` 打印的命中若不在账本里 ⇒ 本测试红。
    """
    findings, files = mod.scan_repo(ROOT)
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    result = mod.reconcile(findings, ledger)

    print(f"\n[时间守卫读数] 扫描面 {len(files)} 个前端测试文件；"
          f"形态 A 命中 {len(findings)} 处（全部已登记存量）；"
          f"新增 {len(result.new)} / 增长 {len(result.grown)} / 残留 {len(result.stale)}")
    for f in findings:
        print(f"  [存量] {f.path}:{f.line}  [{f.symbol}]")

    assert files, "扫描面为空 ⇒ 判据在空跑（0 命中会是假的）"
    assert result.new == [], f"新增「用墙钟造期望值」命中：{result.new}"
    assert result.grown == [], f"存量计数增长：{result.grown}"
    assert result.stale == [], f"账本残留（已修好却未销账）：{result.stale}"
    assert result.problems == [], f"账本形态问题：{result.problems}"


# ═══════════════════════════════════════════════════════════════════════════
# 3. 判据不许空跑 / 不许静默失效
# ═══════════════════════════════════════════════════════════════════════════
def test_scan_repo_end_to_end_on_temp_repo(tmp_path):
    """`scan_repo` 端到端：临时仓库里注入 ⇒ 能定位；同一仓库里的干净文件 ⇒ 不误伤。"""
    pkg = tmp_path / "frontend" / "demo-web" / "tests"
    pkg.mkdir(parents=True)
    (pkg / "flaky.test.tsx").write_text(FLAKY_MONTH_GRANULARITY, encoding="utf-8")
    (pkg / "clean.test.tsx").write_text(LEGIT_FIXTURE_ONLY, encoding="utf-8")

    findings, files = mod.scan_repo(tmp_path)
    assert sorted(p.name for p in files) == ["clean.test.tsx", "flaky.test.tsx"]
    assert {f.path for f in findings} == {"frontend/demo-web/tests/flaky.test.tsx"}


def test_scan_repo_also_covers_src_test_files(tmp_path):
    """扫描面必须同时覆盖 `frontend/*/src/**/*.test.*`（漏一半 = 半个面永久免检）。"""
    src = tmp_path / "frontend" / "demo-web" / "src" / "lib"
    src.mkdir(parents=True)
    (src / "util.test.ts").write_text(FLAKY_MS_LEVEL, encoding="utf-8")

    findings, files = mod.scan_repo(tmp_path)
    assert len(files) == 1
    assert [f.path for f in findings] == ["frontend/demo-web/src/lib/util.test.ts"]


def test_unreadable_surface_is_not_silently_empty(tmp_path):
    """扫描面不存在 ⇒ 返回空集（由 CLI 判 `exit 3` 不可判定），**不得**被读成「零命中 = 通过」。"""
    findings, files = mod.scan_repo(tmp_path)
    assert (findings, files) == ([], [])


# ═══════════════════════════════════════════════════════════════════════════
# 4. 账本：只许缩短 + 每条豁免都要有理由
# ═══════════════════════════════════════════════════════════════════════════
def _finding(key_path: str, symbol: str):
    return mod.Finding(key_path, 1, symbol, "snippet")


def test_reconcile_flags_new_growth_and_residue():
    """对账三态都要**真的**会红 —— 否则「零命中」可能只是 `reconcile` 恒真。"""
    ledger = {"entries": {"a.test.ts|wallclock-expected|expected": {"count": 1, "reason": "r"}}}

    ok = mod.reconcile([_finding("a.test.ts", "expected")], ledger)
    assert ok.ok

    new = mod.reconcile([_finding("b.test.ts", "expected")], ledger)
    assert [f.path for f in new.new] == ["b.test.ts"]
    assert not new.ok

    grown = mod.reconcile(
        [_finding("a.test.ts", "expected"), _finding("a.test.ts", "expected")], ledger
    )
    assert grown.grown == [("a.test.ts|wallclock-expected|expected", 2, 1)]
    assert not grown.ok

    residue = mod.reconcile([], ledger)
    assert residue.stale == ["a.test.ts|wallclock-expected|expected"]
    assert not residue.ok


def test_ledger_requires_reason_and_line_free_key():
    """账本形态判据：缺 `reason` / key 含行号 / `count` 非正整数 ⇒ 都要被指出来。"""
    problems = mod.validate_ledger({"entries": {
        "a.test.ts|wallclock-expected|expected": {"count": 1},
        "b.test.ts|wallclock-expected|expected:42": {"count": 1, "reason": "r"},
        "c.test.ts|wallclock-expected|expected": {"count": 0, "reason": "r"},
    }})
    assert any("缺非空 `reason`" in p for p in problems)
    assert any("含行号" in p for p in problems)
    assert any("正整数 `count`" in p for p in problems)
    assert mod.validate_ledger({"entries": {}}) == []


def test_repo_ledger_is_well_formed():
    """仓库里那份账本本身要合规，且每条豁免都带 `remedy`（可行动，不是「永久豁免」）。"""
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    assert mod.validate_ledger(ledger) == []
    for key, meta in ledger["entries"].items():
        assert meta.get("remedy", "").strip(), f"{key} 缺 remedy（豁免必须可行动）"
        assert meta.get("follow_up", "").strip(), f"{key} 缺 follow_up"


def test_scan_surface_still_has_discriminating_power():
    """**扫描面仍会判红**的自证（注入式红证）—— 账本清空后，「0 命中」必须有对照。

    issue #4761 把账本里最后 3 条（共 12 处命中）**销账** ⇒ `entries` 合法地变成**空**。
    旧版本文件用「`assert entries`（账本非空）」来防「扫描面失效导致 0 命中是假的」——
    那是**错的不变式**：账本的设计契约就是「只许缩短」（`_when_to_regen` 明写「修好了就删掉该条目」），
    全部修完 ⇒ 必然为空，这条断言会把**修完**判成红（正是本单踩到的形态）。

    改为**正向注入式红证**：把守卫自己文档里的红样本喂给 `scan_text()`，证明判据仍在判红；
    再对**真实仓库**断言「新命中 / 增长 / 残留」三态全空。⇒ 比「账本非空」**更强**：
    后者只证明账本里有字，前者证明**判据本身还会红**。
    """
    # ① 判据自证：期望值取自墙钟 ⇒ 必须判红（样本出自本守卫模块 docstring 的红样本）
    red_sample = """
  it('默认期间 = 当前月', async () => {
    const expected = new Date().toISOString().slice(0, 7)
    expect(mockGet).toHaveBeenCalledWith({ period: expected })
  })
"""
    hits = mod.scan_text(red_sample, "sample.test.tsx")
    assert hits, "扫描面已失效：注入的墙钟期望值样本没有被判红"
    assert [h.symbol for h in hits] == ["expected"], hits

    # ② 真实仓库：销账后应无任何命中（新 / 增长 / 残留 三态全空）
    findings, files = mod.scan_repo(ROOT)
    assert files, "扫描面为空 ⇒ 判据在空跑（0 命中会是假的）"
    result = mod.reconcile(findings, json.loads(LEDGER.read_text(encoding="utf-8")))
    assert result.new == [] and result.grown == [] and result.stale == [], (
        f"销账后仍有残留：new={result.new} grown={result.grown} stale={result.stale}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# 5. 形态 B：**不做门禁**的证据（可复现，不写死计数）
# ═══════════════════════════════════════════════════════════════════════════
def test_form_b_naive_rule_reds_a_legitimate_case():
    """朴素形态 B 规则会把**合法**用例判红 ⇒ 它不能当门禁（这是「为什么不假红」的机械证据）。

    样本是同一个 commit 产出两个 testid 的正常写法（`await waitFor(dialog)` 后同步
    `expect(editButton)` —— 点击一次、React 一次 commit 里两处都出现）。
    """
    legit = """
  it('打开编辑弹窗', async () => {
    await user.click(screen.getByTestId('edit-1'))
    await waitFor(() => expect(screen.getByTestId('category-dialog')).toBeInTheDocument())
    expect(screen.getByTestId('dialog-submit')).toBeInTheDocument()
  })
"""
    census = mod.form_b_census(legit, "sample.test.tsx")
    assert len(census) == 1, census
    # 同一份样本，**门禁判据**（形态 A）必须是绿的 —— 证明「advisory ≠ gate」不是一句口号。
    assert mod.scan_text(legit, "sample.test.tsx") == []


def test_form_b_census_is_deterministic_and_advisory_only():
    """普查必须**确定性**（同输入同输出），且只打印读数、不参与退出码。"""
    first = mod.census_repo(ROOT)
    second = mod.census_repo(ROOT)
    assert first == second
    print(f"\n[形态 B 普查 · advisory] 朴素规则命中 {len(first)} 处 / "
          f"{len({c.path for c in first})} 个文件（含大量合法同 commit 用例 ⇒ 不门禁）")
    assert first, "普查恒为空 ⇒ 它无法支撑「形态 B 不可机械判定」这个结论"


def test_cli_census_never_returns_violation_exit_code():
    """`--census` 是 advisory：无论命中多少，退出码必须是 0（不得变成隐形门禁）。"""
    assert mod.main(["--census"]) == 0


def test_cli_check_returns_1_on_new_finding(monkeypatch):
    """门禁模式：有新命中 ⇒ `exit 1`（否则「守卫」是个恒绿的空壳）。"""
    monkeypatch.setattr(mod, "scan_repo", lambda root=ROOT: ([_finding("new.test.ts", "expected")], [ROOT]))
    monkeypatch.setattr(mod, "load_ledger", lambda path=LEDGER: {"entries": {}})
    assert mod.main(["--check"]) == 1


def test_cli_check_returns_3_when_surface_is_empty(monkeypatch):
    """扫描面为空 ⇒ `exit 3`（**不可判定 ≠ 通过**）—— 空跑不许长得像绿。"""
    monkeypatch.setattr(mod, "scan_repo", lambda root=ROOT: ([], []))
    assert mod.main(["--check"]) == 3


def test_cli_check_returns_3_when_ledger_is_unreadable(monkeypatch):
    """账本读不到 ⇒ `exit 3`（fail-closed），不得退化成「无豁免 ⇒ 全红」或「无豁免 ⇒ 全绿」。"""
    monkeypatch.setattr(mod, "load_ledger", lambda path=LEDGER: json.loads("{"))
    assert mod.main(["--check"]) == 3
