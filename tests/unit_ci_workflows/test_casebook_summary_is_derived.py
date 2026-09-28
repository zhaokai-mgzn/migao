# case_ids: MC-025
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 CI 域用例；
#   MC-025 = `.github/cases/misc.yml` 新增的「生成物摘要行必须由现取推导」判据。）
"""**生成物的人读摘要必须由现取推导** —— `docs/testing/mibao-verification-cases.md` 的
「覆盖统计（生成）」那两行**曾与源漂移 1 条**（issue #5687 收尾时实测，`Refs #5683`）。

## 病灶（实测读数，不是推断）

`origin/main` 的 `2fc81b8d2`（以及其后的 `origin/main`）上：

| 读数 | committed casebook | 现取（从 `.github/cases/**` 渲染） |
|---|---|---|
| `- 用例总数：N（活跃 A，跳过 S）` | **532**（126 / 406） | **533**（126 / 407） |
| `- tier 分布：smoke / normal / adversarial` | 12 / **487** / 31 | 12 / **488** / 31 |

⇒ 差 **1** 条，且**只差这两行**：

- 逐条用例块**没少**（源 533 条，块头 `^### <ID>. ` 也是 533 个 —— 逐值比对过）；
- `tests/agent_eval/eval_cases.py`（同一渲染器同一次产出的另一个生成物）**与源一致**（533）；
- 把 committed casebook 与「现取重渲染」做**全量 diff** ⇒ **恰好 4 行**（上面两行的旧值与新值）。

### 为什么它值得一条**常驻判据**（而不是"随手把数字改回去"）

这个形态**只在"下一个 PR"上现形**：`pr-check` 的「生成物新鲜度校验」比较**渲染产物**与**提交的生成物**
⇒ 它会对**下一个无辜的 PR** 判红，而红的信息指向那个 PR 的 diff（**归因指向错误的对象** —— 本会话
一直在治的那族：*判据读到的东西与它声称的对象不是同一个*）。

## 本判据锁什么（三条，各有独立红证）

| # | 判据 | 红证形态 |
|---|---|---|
| 1 | 摘要行的三个数 = **现取** `len(cases)` / 无 `skip_reason` 数 / 其余 | 把 summary 文本按语义变异（总数 +1）⇒ 必红 |
| 2 | tier 分布三数 = 现取 `Counter(tier)` | 把 `normal` 数 +1 ⇒ 必红 |
| 3 | 「**摘要声称的条数必须等于文档里真实出现的块数**」—— 这一条**独立于**渲染器（即使渲染器自己错了也拦得住） | 变异 summary 的 `### ` 标题 ⇒ 必红 |

## 🔴 明确的边界（**不要把本判据读成覆盖面更大的东西**）

- ❌ **只覆盖摘要行**（`- 用例总数：…` / `- tier 分布：…` 两行）：casebook 的**逐条块**由
  `verify-all.sh gate` / `pr-check` 的「生成物新鲜度校验」逐字节比对（那一条读**真文件**，本判据不重复）；
- ❌ **只覆盖 casebook 这一个生成物**：`tests/agent_eval/eval_cases.py` 的同族新鲜度由渲染腿的
  `cmp` 判据承担；本文件**不**声称覆盖「任何生成物里的任何汇总数字」（**没有**通用扫描器）；
- ❌ **不覆盖「某文件根本没被渲染器读到」**（`.github/cases/*.yml` 里若新增了一个渲染器不认识的域，
  摘要与块数会**一起**少 ⇒ 两条判据都不红）—— 那种形态要靠 `tests/unit_ci_workflows/test_render_cases_domain_map.py`
  的域覆盖判据（显式覆盖每个域，不靠缺省兜底）；
- ❌ **不覆盖 `main` 侧**：本判据是 `pull_request` 面腿（`ci workflow helper unit tests`）——
  ⚠️ 本形态的**起源就是「main 上先漂移、下一个 PR 才红」**（A1/A2 同族：main 侧没有守护）；
- ⚠️ **成因未定（照实登记，不编机制）**：现象 = 「摘要行漂移、逐条块不漂移」**已实测**（读数见上表）；
  已排除「渲染器每次算出不同的摘要」（同一棵树连续渲染两次逐字节相同）、「块少了一条」
  （块数与源一致）—— **未能**定到「谁写下了那两行旧数字」（提交历史上最后一次**内部自洽**的快照是
  `296d1295f`：源 532 / 摘要 532）。
"""
import importlib.util
import re
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CASES_DIR = REPO_ROOT / ".github" / "cases"
CASEBOOK = REPO_ROOT / "docs" / "testing" / "mibao-verification-cases.md"
RENDER_CASES = REPO_ROOT / ".github" / "render_cases.py"

#: 摘要两行的**逐字**形态（判据只认这两行；改措辞即红 —— 措辞与判据必须同批改）。
SUMMARY_TOTAL_RE = re.compile(r"(?m)^- 用例总数：(\d+)（活跃 (\d+)，跳过 (\d+)）$")
SUMMARY_TIER_RE = re.compile(r"(?m)^- tier 分布：smoke (\d+) / normal (\d+) / adversarial (\d+)$")
#: 逐条用例块的块头形态（`### MC-024. 标题`）—— 第 3 条判据用它**独立于渲染器**核对"摘要的条数
#: 与文档里真实出现的块数是否一致"。
CASE_BLOCK_RE = re.compile(r"(?m)^### ([A-Z]{2,3}-\d{3})\. ")


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RC = _load(RENDER_CASES, "migao_render_cases_casebook_summary")


def live_cases(cases_dir=CASES_DIR) -> list:
    return RC.load_case_dicts(cases_dir)


def expected_summary(cases) -> dict:
    """**现取**的期望读数（唯一口径；判据与红证共用 ⇒ 不写第二份换算规则）。"""
    tiers = Counter(c.get("tier", "normal") for c in cases)
    active = [c for c in cases if not c.get("skip_reason")]
    return {"total": len(cases), "active": len(active), "skipped": len(cases) - len(active),
            "smoke": tiers.get("smoke", 0), "normal": tiers.get("normal", 0),
            "adversarial": tiers.get("adversarial", 0)}


def parsed_summary(text: str) -> dict:
    """从 casebook 文本里解析摘要读数；两行任一缺失/畸形 ⇒ 抛 `AssertionError`（fail-closed）。"""
    total = SUMMARY_TOTAL_RE.search(text)
    tier = SUMMARY_TIER_RE.search(text)
    assert total, ("casebook 里找不到 `- 用例总数：…（活跃 …，跳过 …）` 摘要行 —— "
                   "摘要与判据的措辞必须同批改（本判据只认这一种形态）")
    assert tier, ("casebook 里找不到 `- tier 分布：smoke … / normal … / adversarial …` 摘要行 —— "
                  "摘要与判据的措辞必须同批改")
    return {"total": int(total.group(1)), "active": int(total.group(2)),
            "skipped": int(total.group(3)), "smoke": int(tier.group(1)),
            "normal": int(tier.group(2)), "adversarial": int(tier.group(3))}


def problems_summary_is_derived(text: str, cases, *, block_count=None) -> list:
    """**独立判据**（喂任意 casebook 文本 + 任意用例集，含变异体）：摘要三问 + 块数一致性。

    四问（缺任何一条，本形态都过得去）：
      ① 摘要行的三个数 == 现取（`len` / 无 `skip_reason` / 其余）；
      ② tier 分布三数 == 现取 `Counter(tier)`；
      ③ **块数 == 摘要声称的条数** —— 这一条**不依赖渲染器**（渲染器自己错了也拦得住）；
      ④ **语料非空**（用例集或块数为空 ⇒ fail-closed，否则本判据静默空跑）。
    """
    bad = []
    if not cases:
        return ["判据语料为空（`.github/cases/**` 解析出 0 条用例）⇒ 本判据会**静默空跑**，先修语料面"]
    want = expected_summary(cases)
    got = parsed_summary(text)          # 畸形 ⇒ 直接抛（fail-closed），调用方当红处理
    for key, field in (("total", "用例总数"), ("active", "活跃"), ("skipped", "跳过")):
        if got[key] != want[key]:
            bad.append(f"casebook 摘要的 `{field}` = {got[key]}，而现取 = {want[key]}"
                       f" ⇒ 摘要**不是由现取推导**的（下一个 PR 的生成物新鲜度校验会对它判红，"
                       f"而归因会指向那个无辜的 PR）")
    for key, field in (("smoke", "smoke"), ("normal", "normal"), ("adversarial", "adversarial")):
        if got[key] != want[key]:
            bad.append(f"casebook `tier 分布` 的 `{field}` = {got[key]}，而现取 = {want[key]}")
    blocks = CASE_BLOCK_RE.findall(text) if block_count is None else list(block_count)
    if not blocks:
        bad.append("casebook 里一个逐条用例块（`^### <ID>. `）都没有 ⇒ 判据语料面已失效（fail-closed）")
    elif len(blocks) != got["total"]:
        bad.append(f"casebook 摘要声称 {got['total']} 条，而文档里真实出现的块数 = {len(blocks)}"
                   f" ⇒ 两处**互相矛盾**（这一条不依赖渲染器，是摘要与文档自身的一致性）")
    return bad


# ── 判据 1~4：真语料 + 四类红证 ───────────────────────────────────────────────


class TestCasebookSummary:
    def test_real_casebook_summary_is_derived(self):
        """真语料必须全绿（这是本判据的**正向**面）。"""
        text = CASEBOOK.read_text(encoding="utf-8")
        assert problems_summary_is_derived(text, live_cases()) == []

    def test_empty_corpus_is_not_silently_green(self):
        """空语料 ⇒ 必报「语料为空」（否则本判据静默空跑 = 最贵的形态）。"""
        text = CASEBOOK.read_text(encoding="utf-8")
        bad = problems_summary_is_derived(text, [])
        assert bad and "语料为空" in bad[0], bad

    def test_drifting_the_total_turns_red(self):
        """🔴 **红证 A**：把摘要的 `用例总数` +1（**语义变异**，不是改注释）⇒ 必红。

        **命中的分支** = `for key, field in (("total", …))` 那条比较。
        ⚠️ 这里**不碰磁盘**：变异体在**内存字符串**上构造 ⇒ 绕开「改磁盘文件的变异可能不被读到」
        这一整类问题（见 `docs/wiki/CI-CD.md` 的同名节）。
        """
        text = CASEBOOK.read_text(encoding="utf-8")
        cases = live_cases()
        want = expected_summary(cases)
        mutant = SUMMARY_TOTAL_RE.sub(
            f"- 用例总数：{want['total'] + 1}（活跃 {want['active']}，跳过 {want['skipped'] + 1}）",
            text, count=1)
        assert mutant != text, "变异没生效（摘要锚已漂移）⇒ 这条红证是空断言"
        bad = problems_summary_is_derived(mutant, cases)
        assert any("用例总数" in b for b in bad), bad

    def test_drifting_the_tier_line_turns_red(self):
        """🔴 **红证 B**：把 tier 分布的 `normal` +1 ⇒ 必红。

        **命中的分支** = tier 那三条比较（与红证 A **不同**的分支）。
        """
        text = CASEBOOK.read_text(encoding="utf-8")
        cases = live_cases()
        want = expected_summary(cases)
        mutant = SUMMARY_TIER_RE.sub(
            f"- tier 分布：smoke {want['smoke']} / normal {want['normal'] + 1} / "
            f"adversarial {want['adversarial']}", text, count=1)
        assert mutant != text, "变异没生效（摘要锚已漂移）⇒ 这条红证是空断言"
        bad = problems_summary_is_derived(mutant, cases)
        assert any("normal" in b for b in bad), bad

    def test_block_count_must_agree_with_the_summary_claim(self):
        """🔴 **红证 C**（**独立于渲染器**的那条）：只改**摘要声称的条数**、不动块 ⇒ 必红。

        为什么必须有它：红证 A/B 比的是「摘要 vs **渲染器**的现取」；若渲染器**自己**错了
        （例如它少解析了一个文件），A/B 会**跟着一起错**而不红。本条比的是
        「**摘要声称的条数 vs 文档里真实出现的块数**」⇒ 两侧都在**文档自身**里，
        渲染器错了也拦得住（这正是本判据要防的那种"两边一起漂"）。
        """
        text = CASEBOOK.read_text(encoding="utf-8")
        cases = live_cases()
        mutant = SUMMARY_TOTAL_RE.sub("- 用例总数：1（活跃 1，跳过 0）", text, count=1)
        assert mutant != text, "变异没生效（摘要锚已漂移）⇒ 这条红证是空断言"
        bad = problems_summary_is_derived(mutant, cases)
        assert any("真实出现的块数" in b for b in bad), bad

    def test_comment_only_change_does_not_turn_red(self):
        """**对照组（「只改注释 / 不改真东西」）**：往 casebook 里插一段**不含摘要形态**的说明文字 ⇒
        必须**不**红（读数与三条红证**不同** ⇒ 判据在判语义，不是判"文件变了没有"）。"""
        text = CASEBOOK.read_text(encoding="utf-8")
        cases = live_cases()
        mutant = text.replace("## 覆盖统计（生成）",
                              "<!-- 注入：这只是注释/说明，不是摘要行 -->\n## 覆盖统计（生成）", 1)
        assert mutant != text, "注入没生效（锚已漂移）⇒ 这条对照是空断言"
        assert problems_summary_is_derived(mutant, cases) == []

    def test_malformed_summary_is_fail_closed(self):
        """摘要行被删/改措辞 ⇒ `parsed_summary` 抛错（**fail-closed**，不许静默当"没有摘要"）。"""
        text = CASEBOOK.read_text(encoding="utf-8")
        for mutant in (SUMMARY_TOTAL_RE.sub("", text, count=1),
                       SUMMARY_TIER_RE.sub("", text, count=1)):
            assert mutant != text
            try:
                parsed_summary(mutant)
            except AssertionError as exc:
                # ⚠️ 不能写裸 `pass`（弱断言形态 ⇒ Growth Gate 的 `--check-weak` 会记一处弱断言，
                # 而**新增测试文件一律 fail-closed**）。断言错误文本 = 触业务数据的断言。
                assert "找不到" in str(exc), (exc,)
            else:  # pragma: no cover
                raise AssertionError("摘要行缺失却解析成功 ⇒ 判据不是 fail-closed")

    def test_the_drifted_readings_are_reproducible(self):
        """**本单实测读数可复算**：摘要的三个数与现取**同源**（用现取重算一遍，不写死任何数字）。

        这一步是「可复算」的机械形态：`expected_summary(live_cases())` 与
        `parsed_summary(committed)` 必须逐值相等 —— 不等就是漂移（读数是**现取**的，不是历史快照）。
        """
        text = CASEBOOK.read_text(encoding="utf-8")
        got = parsed_summary(text)
        want = expected_summary(live_cases())
        for key in ("total", "active", "skipped", "smoke", "normal", "adversarial"):
            assert got[key] == want[key], (key, got, want)
