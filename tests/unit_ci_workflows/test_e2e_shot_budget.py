# case_ids: UI-007, CH-010, AS-001, CH-013
"""小程序 e2e **取证预算**的 L0 静态不变式（issue #3761）。

## 背景（实测，2026-09-14 21:56 真实一轮）

`frontend/mini-app/e2e/` 每轮全量跑 6 个场景、抓 16 张图。对落盘产物做 md5 比对发现
**5 张与另一张逐字节相同**（同一场景内两次抓取之间没有任何交互 ⇒ 状态没变）：

    aftersales/01-aftersales-reply.png == aftersales/02-final.png
    handoff/01-handoff.png             == handoff/02-final.png
    multiturn/04-order-card.png        == multiturn/05-final.png
    chat/03-quick-action-reply.png     == chat/04-typed-reply.png == chat/05-final.png

而 `capture()` 的稳定帧判据要求「连续两帧 md5 一致」⇒ **每次调用至少 2 次 `mp.screenshot()`**
（下限，实测见 `lib/shot-budget.selfcheck.js`）⇒ 一轮底层抓取 ≥32 次，其中 31% 是重复取证。

## 本测试锁什么（**判据来自行为，不来自实现细节**）

① **稳定帧机制不得被删**（`migao-acceptance` v1.4「证据层假绿」的正确治法）：
   两帧比对、`maxAttempts=5`、`intervalMs=1500` 三者缺一即红 —— 收紧 `maxAttempts` 需要
   "每张图实际抓了几帧"的实测分布（`formatShotStats()` 输出 + 自检 ② 的红证），不能凭感觉改。
② **终态图必须走失败门**：`*-final.png` 只能是 `rep.captureFinal(...)`，不得退回无条件
   `capture(...)`（那会把 5 张重复取证加回来）；同时 `captureFinal` 的失败门（`!steps.some(!pass)`）
   不得被删 —— 删了就变成"失败时不抓终态"，正是 §16.5「失败即丢证据」的反面。
③ **报告登记必须与实际抓取一致**：`report.md` 里列出的图必须真的被抓过
   （实测缺陷：`multiturn` 登记了从未抓取的 `03-confirm-card.png`）。

## 红证（注入式，不依赖真实模拟器）

下面的检查器是**纯函数 over 源码文本**，测试用**改坏的副本**证明它会红：
   · 删掉两帧比对            → ① 必报
   · 把 `*-final` 改回 capture → ② 必报
   · 塞回 `shot('03-confirm-card.png')` → ③ 必报
动态层（真跑桩 `mp` 数 `mp.screenshot()` 次数）在 `lib/shot-budget.selfcheck.js`，由
`node frontend/mini-app/e2e/lib/shot-budget.selfcheck.js` 运行（6/6 通过）。
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
E2E_DIR = REPO_ROOT / "frontend" / "mini-app" / "e2e"
HARNESS = E2E_DIR / "lib" / "harness.js"
SCENARIOS = sorted((E2E_DIR / "scenarios").glob("*.js"))


# ── 检查器（纯函数 over 源码文本；便于注入式红证） ──────────────────────────

def _strip_comments(src: str) -> str:
    """去掉块注释与行注释 —— 检查器只看**代码**。

    为什么必须剥（实测）：`multiturn` 删掉历史缺陷时留下的说明注释里写着
    `shot('03-confirm-card.png')`，不剥的话检查器会对**注释**报红（假红），
    从而逼着后人把解释性注释也删掉（把"为什么"丢掉）。
    """
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def harness_violations(src: str) -> list:
    """`lib/harness.js` 的取证预算不变式违规清单（空 = 合规）。"""
    src = _strip_comments(src)
    v = []
    if "if (hash === prevHash)" not in src:
        v.append("稳定帧判据（连续两帧 md5 一致）被删/改写 —— 过渡帧会当证据落盘"
                 "（migao-acceptance v1.4 证据层假绿）")
    if "maxAttempts = 5" not in src:
        v.append("capture 的 maxAttempts 默认值被改动 —— 收紧必须附「每张图实际抓几帧」的"
                 "实测分布（formatShotStats 输出），否则会落过渡帧")
    if "intervalMs = 1500" not in src:
        v.append("capture 的 intervalMs 默认值被改动 —— 同上，需实测依据")
    if "SHOT_STATS.calls += 1" not in src:
        v.append("缺 mp.screenshot() 调用计数 —— 取证成本将再次不可测（issue #3761）")
    if "async captureFinal(mp, scenario, name)" not in src:
        v.append("缺 captureFinal（证据按需：终态只在失败时补抓）")
    if "if (!steps.some((s) => !s.pass))" not in src:
        v.append("captureFinal 的失败门被删/改写 —— 会退回无条件终态重拍（或失败时不抓）")
    return v


_CAPTURE_RE = re.compile(r"(?:capture|captureFinal)\(mp,\s*SCENARIO,\s*'([^']+)'")
_SHOT_RE = re.compile(r"shot\('([^']+)'\)")
_REP_SHOT_RE = re.compile(r"rep\.screenshot\(SCENARIO,\s*'([^']+)'\)")
_UNCONDITIONAL_FINAL_RE = re.compile(r"await capture\(mp,\s*SCENARIO,\s*'([^']*final[^']*)'")


def scenario_violations(name: str, src: str) -> list:
    """单个场景文件的取证预算不变式违规清单（空 = 合规）。"""
    src = _strip_comments(src)
    v = []
    captured = set(_CAPTURE_RE.findall(src))
    registered = set(_SHOT_RE.findall(src)) | set(_REP_SHOT_RE.findall(src))
    phantom = sorted(registered - captured)
    if phantom:
        v.append(f"{name}: 报告登记了从未抓取的图 {phantom} —— "
                 "report.md 的证据清单与实际产物不一致（声称有、磁盘上没有）")
    for m in _UNCONDITIONAL_FINAL_RE.finditer(src):
        v.append(f"{name}: 终态图 {m.group(1)} 用 `capture(...)`（无条件抓）而非 `rep.captureFinal` "
                 "—— 绿路径下这对**同帧**重拍是纯浪费（实测 5 张逐字节重复）")
    return v


# ── ① 现状：真实源码必须合规 ────────────────────────────────────────────────

class TestCurrentSourcesAreClean:
    def test_harness_invariants_hold(self):
        v = harness_violations(HARNESS.read_text(encoding="utf-8"))
        assert v == [], "harness.js 取证预算不变式被破坏：\n" + "\n".join(v)

    def test_every_scenario_is_clean(self):
        all_v = []
        for p in SCENARIOS:
            all_v += scenario_violations(p.name, p.read_text(encoding="utf-8"))
        assert all_v == [], "场景取证预算不变式被破坏：\n" + "\n".join(all_v)

    def test_final_captures_are_failure_gated(self):
        """至少有一个场景用 captureFinal（否则本改造等于没做，或者被整体回退）。"""
        uses = [p.name for p in SCENARIOS if "captureFinal(" in p.read_text(encoding="utf-8")]
        assert uses, "没有任何场景使用 rep.captureFinal —— 终态重拍的浪费回来了"


# ── ② 红证：改坏的副本必须被检查器抓到（否则上面的"合规"是空断言） ──────────

class TestCheckerGoesRedOnMutations:
    """注入式红证：每条判据都要有"喂坏数据必报"的证明（migao-acceptance 铁律 2）。"""

    def test_red_when_stability_loop_deleted(self):
        src = HARNESS.read_text(encoding="utf-8")
        mutated = src.replace("if (hash === prevHash)", "if (false)")
        assert mutated != src, "变异未生效（锚点不存在）—— 本红证是空断言"
        assert any("稳定帧判据" in m for m in harness_violations(mutated)), \
            "删掉两帧比对后检查器没报 —— 稳定帧机制可以被静默删除"

    def test_red_when_failure_gate_deleted(self):
        src = HARNESS.read_text(encoding="utf-8")
        mutated = src.replace("if (!steps.some((s) => !s.pass))", "if (false)")
        v = harness_violations(mutated)
        assert any("失败门" in m for m in v), "captureFinal 的失败门被删后检查器没报"

    def test_red_when_counter_deleted(self):
        src = HARNESS.read_text(encoding="utf-8")
        mutated = src.replace("SHOT_STATS.calls += 1", "// counter removed")
        v = harness_violations(mutated)
        assert any("计数" in m for m in v), "去掉 screenshot 计数后检查器没报（成本又不可测）"

    def test_red_when_final_capture_becomes_unconditional(self):
        """把 captureFinal 退回 capture（= #3761 之前的形态）→ 必须报。"""
        src = (E2E_DIR / "scenarios" / "aftersales-scenario.js").read_text(encoding="utf-8")
        mutated = src.replace("await rep.captureFinal(mp, SCENARIO, '02-final.png')",
                              "await capture(mp, SCENARIO, '02-final.png')")
        assert mutated != src, "变异未生效 —— 本红证是空断言"
        assert any("captureFinal" in m for m in scenario_violations("aftersales-scenario.js", mutated)), \
            "终态图退回无条件 capture 后检查器没报（5 张重复取证的浪费会静默回来）"

    def test_red_when_phantom_registration_returns(self):
        """实测缺陷复现：`multiturn` 曾登记从未抓取的 `03-confirm-card.png`。"""
        src = (E2E_DIR / "scenarios" / "multiturn-scenario.js").read_text(encoding="utf-8")
        mutated = src.replace("  shot('04-order-card.png')",
                              "  shot('03-confirm-card.png')\n  shot('04-order-card.png')")
        assert mutated != src, "变异未生效 —— 本红证是空断言"
        v = scenario_violations("multiturn-scenario.js", mutated)
        assert any("03-confirm-card.png" in m for m in v), \
            "报告登记了不存在的图却没报 —— 证据清单可以与产物脱节"
