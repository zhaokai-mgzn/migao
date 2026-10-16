# case_ids: MC-012
"""商家冒烟 spec 判据可信度守卫 —— issue #4226（三处判据不可信：空判据 / 假红 / 假绿）。

守的东西：`scripts/ui-smoke-merchant/spec.mjs` 是商家后台的**主要 UI 回归网**（31 旅程），
而它的**判据本身**曾不可信 —— 判据坏了不会有人因此变红，反而会（a）恒假（空判据）、
（b）把真回归淹没在长期红灯里、（c）把失败豁免掉（假绿）。三处互相独立，本文件是它们的**形状判据**
（静态可判；运行期真跑需要线上/真实商家数据，见下）：

① **空判据**：判「加工单块出现」用 `text=/PO-[0-9-]+|PG-[0-9-]+/`，而真实加工单号前缀是 `JG-`
   （实测 `JG-20260918-9049`）⇒ 正则永不命中 ⇒ 证据恒为「加工单可见=false」。
② **假红淹没回归**：`16-` 的「发加工」等流转按钮用**定长 sleep 后单次 `isVisible()`** 判定 ⇒
   偶发不可见 ⇒ 加工单不完成 ⇒ `17-order-ship` 被「须先完成加工单后再发货」守卫阻断（A/B 两轮均红）。
③ **假绿**：404 探测豁免条件是「**错误消息文本**含 404」⇒ 旅程自身抛出、文案里恰好带 404 的错误
   被一并豁免。

判据源单点：本文件**不复制**判据逻辑，只做两件事 ——
  · 静态扫描 spec.mjs 的形状（① 不再猜前缀 / ② 用 waitFor 而非定长 sleep / ③ 结构化 404 豁免）；
  · 以子进程跑 `node --test scripts/ui-smoke-merchant/criteria.test.mjs`，把 ①③ 的**可执行判据级红证**
    纳入 CI（`node:test` + `node:assert`，无新依赖）。
node 缺失时**判红而不是跳过**（fail-closed：判据没被行使不得读成通过）。

case_ids 口径：与同族开发/CI 工具链守卫（`test_red_proof_guard.py` #4260、`test_stranding_check.py`
#4065、`test_dev_worktree_rebase.py` #3972）沿用 `MC-012` —— 仓库没有「开发工具链」用例族，
塞进行为用例库会污染覆盖矩阵（同族 PR 的既有裁定）。

**运行期验证照实登记**：本轮本机云 dev 库不可达（`admin-api` 日志 `PSQLException: 尝试连线已失败`
/ `nc -z <RDS_HOST> 5432` FAIL）⇒ 无法跑真旅程，「`17-` 连续 ≥3 轮稳定绿」**未做运行期验证**，
故 ② 用「源码形状判据 + 改动前后形态 diff」兜底（issue #4226「红证的替代口径」允许口径）。
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))

from unit_ci_workflows._source_parsing import java_code  # noqa: E402  （#5323：剥注释的唯一实现）

REPO_ROOT = Path(__file__).resolve().parents[2]
SMOKE_DIR = REPO_ROOT / "scripts" / "ui-smoke-merchant"
SPEC = SMOKE_DIR / "spec.mjs"
CRITERIA = SMOKE_DIR / "criteria.mjs"
CRITERIA_TEST = SMOKE_DIR / "criteria.test.mjs"

# 改动前的三处判据原文（红证形态：这些字面量必须消失/被替代）
OLD_PREFIX_LOCATOR = "text=/PO-[0-9-]+|PG-[0-9-]+/"
OLD_TEXT_EXEMPTION = "errors.every(e => e.includes('404'))"
NODE_TIMEOUT_SECONDS = 120


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _journey_body(name: str) -> str:
    """取 `async function <name>(...)` 的函数体。
    """
    return _function_body(name, keyword="async function")


def _function_body(name: str, keyword: str = "function") -> str:
    """取 `function <name>(...)` / `async function <name>(...)` 的函数体。

    取不到即判红（fail-closed）：判据的定位方式失效时**不得**静默退化成「空字符串扫描通过」。

    issue #6982 起改「**列 0 的右花括号**」口径（旧口径 = 到下一个 `\\n// ─` 章节分隔注释为止）：
    函数体**内部**的行注释（如「// 🔴 判别力不许丢……」）会让旧口径**提前截断** ⇒ 判据读到半个函数体、
    把明明写着的锚点判成缺失（假红）。

    ⚠️ **不许**改用「配平 `{`/`}`」口径（本轮踩过）：这些函数体里到处是**对象字面量**
    （`getByRole('button', { name: … })`）与模板串 `${…}`，按括号计数会**在第一个对象字面量处收尾**
    ⇒ 判据又是假红。顶层函数体在 `spec.mjs` 里逐字约定为「右花括号顶格（列 0）」，故定位也照这个约定。
    """
    src = _read(SPEC)
    head = f"{keyword} {name}("
    start = src.find(head)
    if start < 0:
        pytest.fail(f"spec.mjs 里找不到函数 {name}（判据定位失效 ⇒ 本守卫未行使，不得读成通过）")
    end = src.find("\n}\n", start)
    if end < 0:
        pytest.fail(f"{name} 的函数体没有顶格右花括号（判据定位失效 ⇒ 不得读成通过）")
    body = src[start:end + 2]
    if len(body) < 80:
        pytest.fail(f"{name} 函数体只取到 {len(body)} 字符（判据定位失效 ⇒ 不得读成通过）")
    return body


def _flow_loop_body() -> str:
    """取 16- 旅程里「发加工 → 开始加工 → 加工完成」流转循环体。"""
    src = _read(SPEC)
    m = re.search(r"for \(const \[btn, [^\]]+\] of \[", src)
    if not m:
        pytest.fail("spec.mjs 里找不到流转循环（判据定位失效 ⇒ 不得读成通过）")
    tail = src[m.start():]
    end = tail.find("if (!poVisible")
    if end < 0:
        pytest.fail("流转循环取不到结束边界（判据定位失效 ⇒ 不得读成通过）")
    return tail[:end]


def _wait_helper_line() -> str:
    """取「等元素出现」助手 `const waitVisible = ...` 的定义（判据本体，不得退化成恒真）。"""
    src = _read(SPEC)
    start = src.find("const waitVisible =")
    if start < 0:
        pytest.fail("spec.mjs 里找不到等元素助手 waitVisible（判据定位失效 ⇒ 不得读成通过）")
    # 箭头函数跨行书写：取定义处起 3 行（足够覆盖 waitFor + catch 两段）
    return "\n".join(src[start:].split("\n")[:3])


def test_no_prefix_guessing_processing_order_no():
    """① 空判据：不得再用 PO-/PG- 前缀猜真实加工单号。"""
    src = _read(SPEC)
    assert OLD_PREFIX_LOCATOR not in src, (
        f"spec.mjs 仍在使用永不命中的旧判据 {OLD_PREFIX_LOCATOR!r}"
        "（真实加工单号前缀是 JG-，实测 JG-20260918-9049 ⇒ 证据恒为「加工单可见=false」）"
    )
    # 同族漏改处扫描：文件里不得再出现**任何** PO-/PG- 单号正则形态（注释里提旧写法不算，
    # 故判据锚在正则本体 `PO-[0-9-]`/`PG-[0-9-]` 上，不锚裸前缀）
    assert "PO-[0-9-]" not in src and "PG-[0-9-]" not in src, "spec.mjs 仍残留 PO-/PG- 单号正则（同族漏改处）"
    body = _journey_body("orderDetailJourney")
    assert "matchProcessingOrderNo(" in body, "16- 旅程未用「不猜前缀」的形态判据（criteria.mjs 的 matchProcessingOrderNo）"
    assert "'.po-print-area'" in body, (
        "16- 未把单号判据限定在「加工单块容器」内（全页按形态取号会命中同页其它 XX-日期-序号 单号 ⇒ 换个形态的假绿）"
    )


def test_processing_order_block_uses_shared_criteria_module():
    """① 判据源单点：形态判据/404 豁免必须来自 criteria.mjs（可独立执行的判据级红证载体）。"""
    src = _read(SPEC)
    assert "from './criteria.mjs'" in src, "spec.mjs 未从同目录 criteria.mjs 导入判据（判据又会退回内联不可验证态）"
    assert CRITERIA.exists(), "criteria.mjs 缺失 ⇒ criteria.test.mjs 的判据级红证无处可跑"
    assert CRITERIA_TEST.exists(), "criteria.test.mjs 缺失 ⇒ ①③ 的可执行红证不在仓库里"


def test_flow_buttons_wait_for_element_not_fixed_sleep():
    """② 假红：流转按钮必须以「等元素出现」判定，不得定长 sleep 后单次 isVisible。"""
    loop = _flow_loop_body()
    for label in ("发加工", "开始加工", "加工完成"):
        assert label in loop, f"流转循环里找不到「{label}」步骤（判据定位失效）"
    assert "waitVisible(" in loop, "流转按钮未用「等元素出现」助手判定（② 的判据形态）"
    assert ".isVisible()" not in loop, "流转循环里仍有单次 isVisible 判定（偶发不可见 ⇒ 假红 ⇒ 17- 被守卫阻断）"
    assert "waitForTimeout" not in loop, "流转循环里仍有定长 sleep（issue #4226② 要求改为等元素出现）"


def test_wait_helper_waits_and_fails_closed():
    """② 判据本体不得退化：等元素助手必须真的 waitFor，且超时返回 false（不是恒真）。"""
    line = _wait_helper_line()
    assert "waitFor({ state: 'visible'" in line, f"等元素助手未用 waitFor 等可见：{line.strip()!r}"
    assert ".catch(() => false)" in line, f"等元素助手超时未返回 false ⇒ 判定恒真（空判据）：{line.strip()!r}"


def test_journey16_waits_instead_of_fixed_sleep():
    """② 同族：16- 旅程整段不得再靠定长 sleep 后判 isVisible 决定流程。"""
    body = _journey_body("orderDetailJourney")
    assert "waitForTimeout" not in body, "16- 旅程仍有定长 sleep（等页面/等状态就位应改为 waitFor）"
    assert ".isVisible()" not in body, "16- 旅程仍有单次 isVisible 判定（同族假红形态）"
    assert body.count("waitVisible(") >= 5, "16- 旅程的「等元素出现」判定数量异常（付款/生成/单号/流转/状态回显都该等元素）"


def test_journey17_waits_for_form_or_guard():
    """② `17-order-ship`：必须等「发货表单 或 加工单守卫」出现再判，不得定长 sleep 后数控件。"""
    body = _journey_body("orderShipJourney")
    assert "waitForTimeout" not in body, "17- 旅程仍有定长 sleep（1500ms 内加工单状态未回来 ⇒ 判「无表单」= 假红）"
    assert "waitVisible(" in body, "17- 旅程未用「等元素出现」判定页面稳定"
    assert "须先完成加工单后再发货" in body, (
        "17- 未区分「被加工单前置守卫阻断」与「页面无表单」——两者都判同一句 ⇒ 归因不可读"
    )
    # issue #6982 ③：守卫出现是**合法分支** ⇒ 记 skip（既不是红，也不与「无表单」混判）
    assert "markSkipped(" in body, (
        "17- 仍在把「加工单前置守卫」当失败抛出 —— 守卫出现是**合法**终态（该单的加工单未完成），"
        "判红 = 假红；本旅程应记 skip"
    )


def test_journey33_keeps_the_same_three_state_verdict():
    """issue #6982 ③：`33-`（真提交那条）必须与 `17-` **同一份**三态口径（守卫 ⇒ skip，不是红）。"""
    body = _journey_body(REAL_SHIP_JOURNEY)
    assert "classifyShipPage(" in body, (
        "33- 未走 criteria.mjs 的纯判据 classifyShipPage（守卫分支的可分辨性无处可单独红证）"
    )
    assert "markSkipped(" in body, "33- 把「加工单前置守卫」当失败 —— 守卫出现是**合法**终态，应记 skip"
    assert "须先完成加工单后再发货" in body, "33- 的守卫已从「加工单守卫页」漂成别的文案（守卫分支不再可判）"


# ─────────── issue #6982：判据可信度的 **类级** 一半 ───────────
# 病灶（issue #6982 正文现取读数）：云 dev 库 `order_shipments` 全表 **0 行** —— 因为 `17-order-ship`
# 只断言「发货页表单渲染（N 控件）」即 `done(true)`，**不点【确认发货】**。
# 于是「页面长得对」被读成了「发货这条旅程是绿的」，而**发货单从来没有被真发过一次**。
#
# 本组把「必须真实提交并断言落地」变成**可机械判定**的形状要求：`33-ship-order-real` 的源码里
# 必须同时出现 ① 提交动作（点提交按钮 + 等原子端点响应）② 幂等键请求头（同一个键用于重放）
# ③ **从库读**的读数 ④ 从 API 读订单状态的读数。缺任一条 ⇒ 红 —— 后人把断言改回「渲染即过」时，
# CI（本文件在 `tests/unit_ci_workflows` 面内）当场响，而不是等下一次「发货单怎么还是 0 行」再被发现。
REAL_SHIP_JOURNEY = "orderShipRealJourney"
# (锚点字面量, 它钉住的判据, 缺了会怎样)
REAL_SHIP_ANCHORS: list[tuple[str, str]] = [
    ("POST", "真提交：只有 UI 真打出请求才有 POST 这个方法名可读"),
    ("/production/orders/", "真提交：拦的是**原子端点**的 URL（退回两步老路 ⇒ 抓不到）"),
    ("submit.click(", "真提交：必须真的点提交控件（不点 = 本单的病灶本身）"),
    ("x-client-request-id", "幂等键：请求头必须被读出来（服务端幂等键的唯一来源）"),
    ("replayed", "幂等语义的另一面：同键重放必须断言 replayed"),
    ("shipmentSnapshot(page, orderId)", "**从库读**：断言落地时读发货单真值（不读前端状态）"),
    ("/api/admin/orders/", "**从 API 读**：订单状态回读（不读 toast / 前端状态）"),
    ("shipmentDeltaOk(", "恰 +1（不是 `after > before` 那种对「多建一行」恒真的弱判据）"),
]

# 「渲染即过」的假旅程（issue #6982 改动前**逐字**形态）：用来证明上面的要求**真的会红**
# —— 判据若对这条也绿，那它就是「不会红的断言」（空断言），本组就白写了。
RENDER_ONLY_JOURNEY = """
async function orderShipRealJourney(page, orderId) {
  const h = await journey('33-ship-order-real')(page)
  try {
    await ensureLoggedIn(page)
    if (!orderId) orderId = await createPlainOrderFixture(page, '冒烟发货提交')
    await nav(page, `/orders/${orderId}/ship`, '')
    const submit = page.getByRole('button', { name: /确认发货/ }).first()
    const hasForm = await page.locator('input, textarea, select').count()
    if (hasForm === 0) throw new Error(`发货页无表单（url=${page.url()}）`)
    await h.done(true, '', `发货页表单渲染（${hasForm} 控件）`)
  } catch (e) {
    await h.done(false, `发货页失败: ${String(e).slice(0, 300)}`)
  }
}
"""


def _real_ship_failures(body: str) -> list[str]:
    """`33-ship-order-real` 里**缺失**的「真提交 + 断言落地」锚点（空 = 合规）。"""
    return [f"{why} —— 锚点 {anchor!r}" for anchor, why in REAL_SHIP_ANCHORS if anchor not in body]


def test_journey33_submits_for_real_and_asserts_landing():
    """issue #6982：`33-ship-order-real` 必须**真实提交并断言落地**，不许退回「渲染即过」。"""
    body = _journey_body(REAL_SHIP_JOURNEY)
    failures = _real_ship_failures(body)
    assert failures == [], (
        "「发货真提交」旅程缺少判据锚点（判据退回「渲染即过」⇒ 发货单又会长期 0 行）：\n  - "
        + "\n  - ".join(failures)
    )
    # 「从库读」那一半的**真值面**：`shipmentSnapshot` 必须真的打 `order_shipments`（不是只读 API 就算数）
    snap = _function_body("shipmentSnapshot")
    assert "from order_shipments where order_id =" in snap, (
        "shipmentSnapshot 未从 `order_shipments` 真库读（判据 ② 的库读面落空 ⇒ 「恰 +1」只证了 API 读面）"
    )
    assert "spawnSync('psql'" in snap, "shipmentSnapshot 未走 psql 真库读"
    assert "apiCount" in snap, "shipmentSnapshot 缺失 API 读面（两条读路要都判，见 issue #6982 判据 ②）"


def test_render_only_journey_is_red():
    """issue #6982 的**判别力自证（注入式红证）**：把旅程改回「只渲染即判过」⇒ 本组必须红。

    红证的两种取法都在这里（同一条判据的两侧）：
      ① **改动前逐字形态**（issue #6982 正文引用的 `17-` 老断言）⇒ 缺失至少 8 个锚点；
      ② **单点注入**：只把「点提交」那一行删掉 ⇒ 只缺那一个锚点，仍要红（判据不是被某一条撑起来的）。
    """
    # ① 改动前形态（本次改动的 spec.mjs 里不存在这个函数体 ⇒ 用上面的逐字复刻）
    failures = _real_ship_failures(RENDER_ONLY_JOURNEY)
    assert len(failures) == len(REAL_SHIP_ANCHORS), (
        f"「渲染即过」的假旅程没有被判红：只缺 {len(failures)}/{len(REAL_SHIP_ANCHORS)} 条 ⇒ 本判据是空断言"
    )
    # ② 单点注入（在真旅程体上删掉「点提交」那一行）
    body = _journey_body(REAL_SHIP_JOURNEY)
    injected = body.replace("await submit.click()", "")
    assert injected != body, "注入未生效：找不到 `await submit.click()`"
    assert any("submit.click(" in f for f in _real_ship_failures(injected)), (
        "删掉「真点提交」后判据未红 ⇒ 「必须真实提交」这条要求没被钉住"
    )


def test_real_ship_guard_is_not_vacuous_on_comment_only_edit():
    """对照读数：只改注释 ⇒ 不红（否则判据在吃自己的说明文字，会被迫删注释消红）。"""
    body = _journey_body(REAL_SHIP_JOURNEY)
    assert _real_ship_failures(body) == [], "夹具不成立：现状应当合规"
    commented = "// 说明：本旅程会 POST /production/orders/{id}/ship 并读 order_shipments\n" + body
    assert _real_ship_failures(commented) == [], "只改注释就红了（判据吃自己的说明文字）"
    # 反向对照：把锚点**只**写进注释、可执行面缺失 ⇒ 仍红（注释不许充当判据的承载体）
    stripped = "// POST /production/orders/ submit.click( x-client-request-id replayed\n" + RENDER_ONLY_JOURNEY
    assert _real_ship_failures(stripped) != [], "锚点只写在注释里也算数 ⇒ 判据可被注释骗过"


def _text_scan_exemption_failures(spec_text: str) -> list[str]:
    """③ 的纯判据：可执行面里不许出现「按错误文本判豁免」的写法（空 = 合规，注释不算）。"""
    code = java_code(spec_text)
    out: list[str] = []
    if "includes('404')" in code:
        out.append("spec.mjs 仍在按错误文本判 404（同族漏改处）")
    if "Failed to load resource" in code:
        out.append("spec.mjs 的可执行面仍在扫 console 文案以决定豁免（应为结构化判据）")
    return out


def test_404_exemption_is_structural_not_text_scan():
    """③ 假绿：404 豁免必须按结构化响应判定，不得扫错误文本。

    ⚠️ 扫的是**可执行面**（`java_code` 剥注释，#5323 的唯一实现）：注释里**解释**某个文案不算
    「按文案判豁免」；豁免逻辑里出现该文案仍然是红（见下面的判别力自证）。
    """
    src = _read(SPEC)
    assert OLD_TEXT_EXEMPTION not in src, f"spec.mjs 仍有「错误文本含 404 就豁免」的写法：{OLD_TEXT_EXEMPTION!r}"
    assert _text_scan_exemption_failures(src) == [], "spec.mjs 有按错误文本判豁免的写法：\n" + "\n".join(
        f"  - {f}" for f in _text_scan_exemption_failures(src)
    )
    body = _journey_body("orderDetailJourney")
    assert "page.on('response'" in body, "16- 旅程未收集结构化响应（无 response.status() 可供判定）"
    assert "isProbe404Exempt(" in body, "404 豁免未走 criteria.mjs 的结构化判据 isProbe404Exempt()"


def test_404_text_scan_criterion_has_teeth():
    """③ 判别力自证（注入式红证）：把「扫 console 文案」写回**可执行面** ⇒ 红；只写进注释 ⇒ 绿。"""
    src = _read(SPEC)
    assert _text_scan_exemption_failures(src) == [], "夹具不成立：现状应当绿"
    injected = src.replace("const isConsoleResourceLoadError = (e) => {",
                           "const isConsoleResourceLoadError = (e) => String(e).includes('Failed to load resource') && {")
    assert injected != src, "注入未生效：找不到 isConsoleResourceLoadError 定义"
    failures = _text_scan_exemption_failures(injected)
    assert any("console 文案" in f for f in failures), f"把文案扫描写回可执行面后判据未红：{failures}"
    # 对照读数：只改注释 ⇒ 不红
    commented = "// 说明：豁免必须结构化，不得扫 'Failed to load resource' 这类文案\n" + src
    assert _text_scan_exemption_failures(commented) == [], "只改注释就红了（判据吃自己的说明文字）"


def test_executable_criteria_red_proofs_pass():
    """①③ 的可执行判据级红证（node:test，无新依赖）必须全绿 —— 红证不在仓库外。"""
    node = shutil.which("node")
    if node is None:
        pytest.fail("node 不可用 ⇒ ①③ 的可执行判据未行使（不得读成通过；本仓库 CI/本地均依赖 node 跑 playwright）")
    proc = subprocess.run(
        [node, "--test", str(CRITERIA_TEST)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=NODE_TIMEOUT_SECONDS,
    )
    assert proc.returncode == 0, (
        "criteria.test.mjs 未通过（① JG- 形态命中 / ③ 结构化 404 豁免的判据级红证）\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
