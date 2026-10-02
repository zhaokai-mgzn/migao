# case_ids: MC-067
"""§15.7 页面多模态验收**承载体**的工具面判据（issue #6009）—— 纯静态、零依赖、零网络、不跑 node。

## 病（本单的现场读数，不是推断）

`.agent-presets/migao/skills/migao-dev-flow/scripts/ui-multimodal-acceptance.mjs`（§15.7 的唯一承载体）
的登录步原来是「`domcontentloaded` + 1.2s ⇒ 点提示文案『手机验证码』⇒ 填手机号」。而登录页是**客户端渲染**的
（`useSearchParams` ⇒ SSR 出来的是空壳，连「手机验证码」四个字都不在 HTML 里）⇒ 慢首帧下那次点击打在**还不存在**
的元素上、异常又被 `.catch(() => {})` **吞掉** ⇒ 页面仍停在「员工登录」页签 ⇒ 等手机号输入框 30s ⇒ `TimeoutError`
（`#5976+#5977` / `#5983` 两包实测撞的就是这一形态）。
⇒ 症状与**被验功能无关**，任何人跑 §15.7 都会撞同一堵墙 —— 这正是「看起来跑了、其实拿不到证据」。

## 本文件锁什么（每条都能单独变红；红证 = 内存注入，见文末）

| # | 判据 | 取法 |
|---|---|---|
| 1 | 登录步**顺序**：先切「管理员登录」（`role=tab` 语义锚）再等/填手机号 | 两个锚的**位置关系** |
| 2 | 登录步内**不许**静默吞异常（`.catch(() => {})` 空处理器） | 正则扫空 body 的 catch |
| 3 | **形态指纹**在位：`LOGIN_SHAPE`（两页签名+副标题 / 手机号·验证码占位 / `获取验证码` / `登 录`）+ 两阶段判定函数 + `--login-shape-check` 自检开关 | 逐字锚 |
| 4 | **fail-closed**：`dieShape` 走非零退出；登录段里失败路径**逐个具名**（≥4 处），不许退化成一个笼统超时 | 逐字锚 + 计数 |
| 5 | **§15.7** 写明**唯一入口** / **登录页形态指纹** / **「取不到证据时怎么判」三态**（不许把"跑不出来"写成"通过"） | §15.7 段内逐字锚 |

**纯静态硬约束**：零 ai-agent 依赖（CI 的 `ci workflow helper unit tests` 只装 `pytest` + `pyyaml`）、零网络、
**不跑** node / Playwright、**禁** `try/except` 里调 `pytest` 的 `skip`（自证见 `test_this_judgement_is_pure_static_and_never_skips`）。
它**不**判「工具跑没跑」「截图看得对不对」—— 那两条按 §15.7 的边界照实登记为**判不了**。
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
#: 🔴 S4（issue #6020）：承载体与技能都在**预设仓** ⇒ 统一走 `preset_corpus`。
# ── 预设语料读取（S4 / issue #6020）：与 `test_source_parsing_shared.py` 同款的命名空间包导入 ──
import sys as _sys

_sys.path.append(str(Path(__file__).resolve().parents[1]))  # tests/（append：只作兜底解析路径）

from unit_ci_workflows.preset_corpus import (  # noqa: E402
    DEV_FLOW_CARRIER_REL,
    DEV_FLOW_SKILL_REL,
    require_preset_path,
    require_preset_text,
)
CARRIER = require_preset_path(DEV_FLOW_CARRIER_REL)
SKILL = require_preset_path(DEV_FLOW_SKILL_REL)

# 逐字锚（改承载体时这些串就是契约；改契约必须同时改本判据 —— 那正是本判据存在的意义）
ADMIN_TAB_ANCHOR = "const adminTab = page.getByRole('tab'"
PHONE_WAIT_ANCHOR = "await phoneInput.first().waitFor("
PHONE_FILL_ANCHOR = "await phoneInput.first().fill(phone)"
SHAPE_CHECK_FLAG = "has('login-shape-check')"
SHAPE_CONST = "const LOGIN_SHAPE = {"
SHAPE_MARKERS = (
    "LOGIN_SHAPE.tabs[1].label",
    "phonePlaceholderIncludes: '手机号'",
    "codePlaceholderIncludes: '验证码'",
    "sendCodeText: '获取验证码'",
    r"submitTextRe: /登\s*录/",
)
SHAPE_FUNCS = ("function probeLoginShape(", "function judgeLoginTabs(", "function judgeAdminForm(")
SHAPE_TAB_LITERALS = ("'员工登录'", "'账号密码'", "'管理员登录'", "'手机验证码'")
FAIL_CLOSED_MSG = "页面形态已变"
SILENT_CATCH_RE = re.compile(r"\.catch\(\s*\(\s*\)\s*=>\s*\{\s*\}\s*\)")
LOGIN_SECTION_MARKERS = ("── ①", "── ⑤")

# §15.7 文档侧逐字锚
DOC_ANCHORS = (
    "ui-multimodal-acceptance.mjs",
    "--login-shape-check",
    "--site http://localhost:3001",
    "唯一入口",
    "CORS_ALLOWED_ORIGINS",
    "取不到证据时怎么判",
    "跑不出来",
    "未覆盖",
    "页面形态已变",
)


def _login_section(src: str) -> str:
    """登录段（① 打开登录页 → ⑤ 目标页证据之间）—— 顺序/静默/具名报出的判定面。"""
    start, end = (src.find(m) for m in LOGIN_SECTION_MARKERS)
    if start < 0 or end < 0 or end <= start:
        return ""
    return src[start:end]


def carrier_issues(src: str) -> list[str]:
    """承载体（`.mjs`）的工具面问题清单；空 = 通过。纯函数 ⇒ 红证可在内存里注入。"""
    issues: list[str] = []

    # ① 顺序：先切「管理员登录」再等/填手机号
    i_tab = src.find(ADMIN_TAB_ANCHOR)
    i_wait = src.find(PHONE_WAIT_ANCHOR)
    i_fill = src.find(PHONE_FILL_ANCHOR)
    if i_tab < 0:
        issues.append(f"登录步里找不到「切管理员登录」的语义锚：{ADMIN_TAB_ANCHOR}")
    if i_wait < 0 or i_fill < 0:
        issues.append("登录步里找不到手机号输入框的「等可见」/「填值」锚")
    if i_tab >= 0 and i_fill >= 0 and not i_tab < i_wait < i_fill:
        issues.append(
            f"登录步顺序不对（切页签 idx={i_tab} / 等手机号 idx={i_wait} / 填手机号 idx={i_fill}）："
            "必须先切「管理员登录」再等/填手机号 —— 否则停在员工表单，只能靠 30s 超时（#6009 的病）"
        )

    # ② 不许静默吞异常（缺陷原文形态）
    if SILENT_CATCH_RE.search(src):
        issues.append("登录步里出现 `.catch(() => {})` 空处理器（静默吞异常 = #6009 的静默超时形态）")

    # ③ 形态指纹 + 自检开关在位
    if SHAPE_CONST not in src:
        issues.append(f"缺登录页形态指纹常量：{SHAPE_CONST}")
    for marker in SHAPE_MARKERS:
        if marker not in src:
            issues.append(f"形态指纹里缺锚点：{marker}")
    for literal in SHAPE_TAB_LITERALS:
        if literal not in src:
            issues.append(f"形态指纹里缺页签文案：{literal}")
    for func in SHAPE_FUNCS:
        if func not in src:
            issues.append(f"缺形态判定的纯函数：{func}")
    if SHAPE_CHECK_FLAG not in src:
        issues.append(f"缺 `--login-shape-check` 自检开关的解析：{SHAPE_CHECK_FLAG}")

    # ④ fail-closed + 失败路径逐个具名
    if FAIL_CLOSED_MSG not in src:
        issues.append(f"缺「{FAIL_CLOSED_MSG}」的报错文案（fail-closed 的可行动指引）")
    if "process.exit(1)" not in src:
        issues.append("承载体没有非零退出路径（fail-closed 退化成静默通过）")
    section = _login_section(src)
    if not section:
        issues.append("找不到登录段标记（── ① … ── ⑤）—— 判据的射程锚失效")
    else:
        named = section.count("dieShape(") + section.count("die(")
        if named < 4:
            issues.append(f"登录段的失败路径只有 {named} 处具名报出（要求 ≥4）：失败必须逐个报出，不许退化成一次超时")

    return issues


def doc_issues(md: str) -> list[str]:
    """§15.7 段内的问题清单；空 = 通过。纯函数 ⇒ 红证可在内存里注入。"""
    start = md.find("### 15.7 ")
    end = md.find("\n## 16.", start if start >= 0 else 0)
    if start < 0 or end <= start:
        return ["`migao-dev-flow` §15.7 段找不到（判据的射程锚失效）"]
    section = md[start:end]
    return [f"§15.7 缺逐字锚：{a}" for a in DOC_ANCHORS if a not in section]


def _read(path: Path) -> str:
    if not path.is_file():
        raise AssertionError(f"判据的被测对象不存在（门禁空转）：{path}")
    return path.read_text(encoding="utf-8")


def test_carrier_login_step_is_wired():
    issues = carrier_issues(_read(CARRIER))
    assert not issues, "承载体（§15.7 的 `.mjs`）工具面判据未通过：\n" + "\n".join(f"  - {i}" for i in issues)


def test_skill_15_7_states_entry_and_three_way_verdict():
    issues = doc_issues(_read(SKILL))
    assert not issues, "§15.7 文档面判据未通过：\n" + "\n".join(f"  - {i}" for i in issues)


# ── 判别力自证（注入式红证：对**真语料**做内存变异，坏形态必须各自判红）──────────────
def test_red_proof_login_order_inverted():
    src = _read(CARRIER)
    mutated = src.replace(ADMIN_TAB_ANCHOR, PHONE_FILL_ANCHOR + "\n" + ADMIN_TAB_ANCHOR, 1)
    assert mutated != src, "注入未生效（红证自己先失效：锚点已漂移）"
    issues = carrier_issues(mutated)
    assert any("顺序不对" in i for i in issues), f"顺序反转必须判红，实测 {issues}"


def test_red_proof_silent_catch_comes_back():
    src = _read(CARRIER)
    mutated = src + "\nawait page.getByText('x').click({ timeout: 5000 }).catch(() => {})\n"
    issues = carrier_issues(mutated)
    assert any("静默吞异常" in i for i in issues), f"加回静默 catch 必须判红，实测 {issues}"


def test_red_proof_fingerprint_removed():
    src = _read(CARRIER)
    for mutated in (src.replace(SHAPE_CONST, "const LOGIN_SHAPE_GONE = {", 1), src.replace(SHAPE_CHECK_FLAG, "false", 1)):
        issues = carrier_issues(mutated)
        assert issues, "指纹/自检开关被摘掉必须判红（否则『页面改版后工具失配』下次不会自己爆）"


def test_red_proof_fail_closed_exit_removed():
    src = _read(CARRIER)
    mutated = src.replace("process.exit(1)", "process.exit(0)")
    issues = carrier_issues(mutated)
    assert any("非零退出" in i for i in issues), f"非零退出被摘掉必须判红，实测 {issues}"


def test_red_proof_doc_loses_unique_entry_or_three_way():
    md = _read(SKILL)
    for needle in ("唯一入口", "取不到证据时怎么判", "未覆盖"):
        issues = doc_issues(md.replace(needle, "（已删除）"))
        assert issues, f"§15.7 删掉「{needle}」必须判红"


def test_control_comment_only_change_is_green():
    """对照读数：只加注释不改语义 ⇒ 不红（判据别把自己的文案喂红）。"""
    assert carrier_issues("// 只加一行注释\n" + _read(CARRIER)) == []
    assert doc_issues(_read(SKILL) + "\n<!-- 只加一行注释 -->\n") == []


def test_this_judgement_is_pure_static_and_never_skips():
    """CI 的 `ci workflow helper unit tests` 只装 `pytest` + `pyyaml` ⇒ 本判据必须零 ai-agent 依赖、零 skip。"""
    this = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(this)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    # 🔴 S4（issue #6020）扩了**两种**：都**不是**第三方依赖，本判据的射程（「CI 只装 pytest+pyyaml
    # ⇒ 不许引运行时/第三方」）**一字未松**：
    #   · `sys` —— 标准库（加它只为把 `tests/` 挂进 `sys.path` 以便导入下面的仓内测试助手）；
    #   · `unit_ci_workflows` —— **本目录自己的**测试助手包（`preset_corpus`，纯标准库实现）。
    # 预设内容迁出业务仓后，读那份语料必须走仓内统一口径（镜像 / git 基线），否则本判据读空 ⇒
    # 要么静默绿、要么在本机与 CI 之间口径漂移（本 PR 实测踩过）。**第三方 / ai-agent 运行时照旧禁止。**
    allowed = {"__future__", "ast", "re", "pathlib", "pytest", "sys", "unit_ci_workflows"}
    unexpected = sorted(imported - allowed)
    assert not unexpected, f"判据引入了额外依赖（CI 里会因缺依赖变红）：{unexpected}；且不许 import ai-agent 运行时"
    skip_needle = "pytest." + "skip"
    assert skip_needle not in this, "禁止在 try/except 里调 pytest 的 skip —— 那会让本判据在 CI 里永远是空的"
    # 同上，但针脚要拼出来：判据自身不能出现这些字面量（否则它扫到自己 = 永远红）
    orskip_needle = "import" + "orskip"
    assert orskip_needle + "(" not in this, "禁止用 pytest 的 " + orskip_needle + "（同上：CI 里会静默空转）"
