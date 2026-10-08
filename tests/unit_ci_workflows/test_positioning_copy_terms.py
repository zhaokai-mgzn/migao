# case_ids: UI-082, UI-094
"""**品牌文案**守卫（两组判据同处一文件）：

① **产品定位文案**（issue #6463）：观星台不得再被写成「电商管理系统 / 电商管理解决方案」；
② **品牌称呼**（issue #6525）：旧称呼（米高 / 米宝 / 小布）不得在用户可见面回流，
   新称呼（观星台 / 黄金策 / 元元）必须在关键落点**正向存在** —— 见文末「品牌称呼」一节。

── ① 的正文 ────────────────────────────────────────────────────────────────

**产品定位文案**守卫：观星台不得再被写成「电商管理系统 / 电商管理解决方案」（issue #6463）。

用户 2026-10-07 逐字：「观星台 / 企业级AI电商管理解决方案，这里的定位已经不太对了，我们不单单管理电商了，
你想个更贴切的」⇒ 定位统一为 **企业级AI经营管理平台**。

## 为什么要有这条守卫（而不是改完 3 处就算完）

同一句定位**散落**在三个用户可见落点 + 一条断言里（本次实测：登录页副标题、首次登录改密页副标题、
`frontend/admin-web/src/app/layout.tsx` 的 `<title>`/description、`tests/unit/pages/login.test.tsx`）。
改一处漏一处**没有任何东西会红** —— 浏览器标签页写着「AI电商管理系统」、登录页写着「经营管理平台」，
两套定位同屏共存（这正是本次改动的起因形态）。

## 判据（逐条可红）

| # | 判什么 | 怎么红 |
|---|---|---|
| 1 | **代码面**零旧定位串 | 生产源码里出现 `AI电商管理系统` / `电商管理解决方案` ⇒ 具名报 `文件:行 + 原句` |
| 2 | **正向锚**：三个用户可见落点都**已**改口 | 任一处不含「经营管理平台」⇒ 红（防「删掉旧词」被当成「改完了」） |
| 3 | **注入式红证**：合成源里把旧串放进字符串 / JSX 文本 ⇒ 判红且指到行 | 判据不是空断言 |
| 4 | **注释面允许保留**（正面对照） | 注释里的沿革说明不判红 —— 否则守卫会逼人删掉历史记录 |
| 5 | 扫面为空 ⇒ 红 | 射程断了（路径写错）不比没有守卫好 |

## 边界（照实登记，不粉饰）

- 注释剥离复用**全仓唯一一份**实现 `tests/unit_ci_workflows/_source_parsing.py::java_code`
  （引号感知，issue #5323 收口）—— **不**在这里写第二把「按 `//` 截断」的尺子。
- 该走查是 **Java 口径的词法**：TS 的单引号字符串被归入 `char` 片段、模板串未单列
  （内容都**原样保留**，只有注释被抹白）。⇒ 误读的方向只能是「把注释当代码」（假红），
  不会把代码面藏起来（假绿）；本仓现状下两者都不发生（改后前 `grep` 与剥注释两条路径均为 0 命中）。
- 射程只到四个前端包的 `src`（生产源码）：文档、测试、`verify-*` 生产快照**不在面内**。
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests"))

from unit_ci_workflows._source_parsing import java_code  # noqa: E402

#: 旧定位串（观星台**自身**被写成电商管理系统的两种形态）
BANNED_IN_CODE_FACE = ("AI电商管理系统", "电商管理解决方案")

#: 改后的定位锚（正向：三处用户可见落点都必须含它）
REQUIRED_TAGLINE = "经营管理平台"

#: 登录页 / 改密页共用的**那一句**副标题（两页同形，抄一份改一份的形态要当场红）
SHARED_SUBTITLE = "企业级AI经营管理平台"

#: 扫面 = 四个前端包的**生产源码**（不含测试：测试里的旧词多在描述历史）
SCAN_ROOTS = (
    "frontend/admin-web/src",
    "frontend/bmini-app/src",
    "frontend/worker-h5/src",
    "frontend/mini-app/src",
)
SCAN_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs")

#: 正向锚落点（用户看得见这行字的地方）
USER_FACING_FILES = (
    "frontend/admin-web/src/app/login/page.tsx",
    "frontend/admin-web/src/app/change-password/page.tsx",
    "frontend/admin-web/src/app/layout.tsx",
)


def code_face(source: str) -> str:
    """**只保留代码面**：注释抹成空格（换行保留 ⇒ 行号不变），字符串 / JSX 文本原样留下。

    复用全仓唯一一份引号感知实现（`#5323`）；这里只是给它起一个本守卫语境的别名。
    """
    return java_code(source)


def violations_in(name: str, source: str) -> list[str]:
    """代码面里的旧定位串 ⇒ `名字:行: 原句`（原句取**原文**那一行，便于照抄去改）。"""
    face_lines = code_face(source).splitlines()
    raw_lines = source.splitlines()
    found: list[str] = []
    for index, line in enumerate(face_lines, start=1):
        if any(term in line for term in BANNED_IN_CODE_FACE):
            raw = raw_lines[index - 1].strip() if index - 1 < len(raw_lines) else ""
            found.append(f"{name}:{index}: {raw[:100]}")
    return found


def scan_repo() -> tuple[list[str], list[Path]]:
    """扫生产源码；返回（违规清单, 扫到的文件）。"""
    violations: list[str] = []
    scanned: list[Path] = []
    for root in SCAN_ROOTS:
        base = REPO_ROOT / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix not in SCAN_EXTS:
                continue
            if "node_modules" in path.parts or ".next" in path.parts:
                continue
            scanned.append(path)
            violations.extend(
                violations_in(path.relative_to(REPO_ROOT).as_posix(), path.read_text(encoding="utf-8"))
            )
    return violations, scanned


# ── 判据 ①：代码面零旧定位串 ────────────────────────────────────────────────


def test_no_stale_positioning_in_code_face():
    violations, scanned = scan_repo()
    assert scanned, "扫面为空 —— 守卫的射程断了（SCAN_ROOTS 路径写错？）"
    assert violations == [], (
        "生产源码里出现了旧定位串（用户 2026-10-07 裁定：观星台定位改「企业级AI经营管理平台」）：\n  "
        + "\n  ".join(violations)
    )


# ── 判据 ②：正向锚（三处用户可见落点都已改口）──────────────────────────────


def test_user_facing_surfaces_now_use_the_new_tagline():
    for rel in USER_FACING_FILES:
        source = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert REQUIRED_TAGLINE in code_face(source), f"{rel} 的定位文案还没改成「{REQUIRED_TAGLINE}」"
    # 登录页 / 改密页的副标题是**同一句**（两页同形），抄一份改一份的形态要当场红
    login = code_face((REPO_ROOT / USER_FACING_FILES[0]).read_text(encoding="utf-8"))
    change = code_face((REPO_ROOT / USER_FACING_FILES[1]).read_text(encoding="utf-8"))
    assert SHARED_SUBTITLE in login and SHARED_SUBTITLE in change, (
        f"登录页与首次改密页的副标题必须是同一句「{SHARED_SUBTITLE}」"
    )


# ── 判据 ③④：注入式红证 + 注释面正面对照（判别力自证）──────────────────────


def test_injection_turns_red_with_attribution():
    """把旧串放进**字符串 / JSX 文本** ⇒ 必须判红，且**指到行**（可归因）。"""
    sample = "const title = '观星台 - AI电商管理系统'\nconst ok = '企业级AI经营管理平台'\n"
    found = violations_in("sample.tsx", sample)
    assert len(found) == 1, f"注入没被判红 ⇒ 判据是空断言：{found}"
    # ⚠️ 这里**不写**「合成文件名 + 冒号 + 行号」的字面量：`sample.tsx` 是**合成**源（按定义不存在），
    #    而引用新鲜度判据（scripts/drift_audit.py 的 ref-freshness）会把那种形态当成真实引用去核。
    name, line_no, _ = found[0].split(":", 2)
    assert (name, line_no) == ("sample.tsx", "1"), f"归因不对（应指到合成源第 1 行）：{found[0]}"

    jsx = "export const C = () => (\n  <p>企业级AI电商管理解决方案</p>\n)\n"
    assert [v.split(":")[1] for v in violations_in("sample.tsx", jsx)] == ["2"], "JSX 文本没被扫到"


def test_comment_mention_is_not_a_violation():
    """注释里的沿革说明**不算违规** —— 否则守卫会逼人删掉历史记录（用户裁定的范围是用户可见面）。"""
    sample = (
        "// 2026-10-07：本页副标题原为「企业级AI电商管理解决方案」（issue #6463）\n"
        "/* 改名自 AI电商管理系统 */\n"
        "const title = '观星台 - AI经营管理平台'\n"
    )
    assert violations_in("sample.tsx", sample) == [], "注释面被误判成违规（假红）"


def test_string_with_double_slash_is_not_eaten_as_a_comment():
    """引号感知的反向对照：URL 里的 `//` 不得把后续代码面吃掉（否则真违规会漏判 = 假绿）。"""
    sample = "const u = \"https://app.migaozn.com/s/7Q2M4K8P\"\nconst bad = \"AI电商管理系统\"\n"
    assert [v.split(":")[1] for v in violations_in("sample.ts", sample)] == ["2"], (
        "字符串里的 `//` 把后面的真违规吃掉了（复用了按 `//` 截断的旧尺子？）"
    )


# ── ② 品牌称呼（issue #6525）：旧名不得回流 + 新名正向存在 ────────────────────
#
# 为什么要有这条（而不是改完 662 个文件就算完）：
# 改名是**一次性的批量动作**，而「旧名回流」会以两种形态持续发生 ——
#   · 新增页面 / 新写文案的人不知道旧名已废，照抄旧稿（同 #5747「C 端 agent 名混进 B 端空态」的形态）；
#   · 一部分文件（历史迁移、归档、活环境数据名）**有意保留旧名**，于是"全仓 grep 零命中"永远不成立
#     ⇒ 必须有**面**的判据：只判**用户可见的生产源码**，且把计量义与内部协议标签排除在外。
#
# 判据（逐条可红）：
# | # | 判什么 | 怎么红 |
# |---|---|---|
# | 1 | 四个前端包生产源码的**代码面**零旧称呼 | `米宝` / `小布` 命中即具名；`米高` 命中且**非计量义**即具名 |
# | 2 | **正向锚**：agent 定义与三个前端品牌工具都已是新名 | 任一锚缺失 ⇒ 红（防「删掉旧词」被当成「改完了」） |
# | 3 | **判别力自证**：字符串里的旧名判红 / 计量义不假红 / 注释面不假红 / 新名零命中 | 判据不是空断言，也不会被领域文案喂红 |
#
# 边界（照实登记，不粉饰）：
# - **计量义豁免**：`米高` 前一个非空白字符是数字 / 小数点 /「米」时**不是品牌名**
#   （实测全仓 30 行 `2.7 米高窗` / `宽2米高2.5米` 这类算料文案）⇒ 不许把它们判红。
# - **协议标签豁免**：`[米宝解读]` 是服务端 SSE source 的**协议值**（Python `SOURCE_INTERPRETED`
#   与 TS `PAGE_FILL_SOURCE_INTERPRETED` 同值；issue #6461 跟踪「内部标签上屏」）⇒ 不是称呼，不判红。
# - **射程**：只到四个前端包的 `src` 代码面（注释抹白）。`docs/`、`tests/`、历史迁移、
#   `acceptance/` 与**活环境数据名**（如租户名「米高测试环境」）**不在面内** —— 那里的旧名是
#   历史记录或 DB 真值，改了就是伪造证据 / 制造代码与数据不一致。

#: 旧称呼（改名前的口径）；回流 = 称呼又漂了
OLD_AGENT_NAMES = ("米宝", "小布", "米高")

#: 计量义的合法前导字符（`米高` 专用）
_MEASURE_PREFIX = tuple("0123456789.．０１２３４５６７８９米")

#: 协议内部标签（不是称呼）
_PROTOCOL_TAG = "米宝解读"

#: 新称呼必须**正向存在**的落点（防「只删旧词就算改完」）
NEW_NAME_ANCHORS = (
    ("frontend/admin-web/src/app/(corporate)/page.tsx", ("元元", "黄金策")),
    ("frontend/bmini-app/src/utils/brand.ts", ("黄金策",)),
    ("frontend/mini-app/src/utils/brand.ts", ("元元",)),
    ("backend/ai-agent-service/app/agents/agents/xiaobu.py", ('display_name="元元"',)),
    ("backend/ai-agent-service/app/agents/agents/mibao.py", ('display_name="黄金策"',)),
)


def _is_brand_occurrence(text: str, index: int, name: str) -> bool:
    """该命中是不是**品牌称呼**（而非计量义 / 协议标签）。"""
    if name == "米宝" and text[index : index + len(_PROTOCOL_TAG)] == _PROTOCOL_TAG:
        return False
    if name != "米高":
        return True
    j = index - 1
    while j >= 0 and text[j] in " \u3000\t":
        j -= 1
    return not (j >= 0 and text[j] in _MEASURE_PREFIX)


def old_name_violations(source: str) -> list[tuple[int, str, str]]:
    """代码面里的旧称呼 ⇒ `(行号, 旧名, 原句)`。"""
    face_lines = code_face(source).splitlines()
    raw_lines = source.splitlines()
    found: list[tuple[int, str, str]] = []
    for index, line in enumerate(face_lines, start=1):
        for name in OLD_AGENT_NAMES:
            pos = line.find(name)
            while pos >= 0:
                if _is_brand_occurrence(line, pos, name):
                    raw = raw_lines[index - 1].strip()[:100] if index - 1 < len(raw_lines) else ""
                    found.append((index, name, raw))
                    break
                pos = line.find(name, pos + len(name))
    return found


def test_old_agent_names_do_not_come_back_in_code_face():
    violations: list[str] = []
    scanned: list[Path] = []
    for root in SCAN_ROOTS:
        base = REPO_ROOT / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix not in SCAN_EXTS:
                continue
            if "node_modules" in path.parts or ".next" in path.parts:
                continue
            scanned.append(path)
            rel = path.relative_to(REPO_ROOT).as_posix()
            for line_no, name, raw in old_name_violations(path.read_text(encoding="utf-8")):
                violations.append(f"{rel}:{line_no}: 旧称呼「{name}」: {raw}")
    assert scanned, "扫面为空 —— 守卫的射程断了（SCAN_ROOTS 路径写错？）"
    assert violations == [], (
        "用户可见面出现**已废的**品牌称呼（issue #6525：米高→观星台 / 米宝→黄金策 / 小布→元元）：\n  "
        + "\n  ".join(violations)
    )


def test_new_agent_names_are_present_at_key_surfaces():
    """正向锚：改名的**结果**真的在（只删旧词不算改完）。"""
    for rel, anchors in NEW_NAME_ANCHORS:
        path = REPO_ROOT / rel
        assert path.is_file(), f"正向锚文件不存在（路径漂移？）: {rel}"
        source = path.read_text(encoding="utf-8")
        for anchor in anchors:
            assert anchor in source, f"{rel} 缺新称呼锚「{anchor}」"


def test_agent_name_guard_discriminating_power():
    """判别力自证：会红 / 不假红 / 不误判。"""
    # ① 字符串里的旧称呼 ⇒ 判红且**指到行**
    assert old_name_violations("const a = '米宝'\n") == [(1, "米宝", "const a = '米宝'")]
    # ② 计量义**不得假红**（算料领域文案：「2.7 米高窗」是尺寸不是品牌）
    assert old_name_violations("const q = '2.7 米高窗报价'\n") == []
    assert old_name_violations("const q = '宽2米高2.5米'\n") == []
    # ③ 协议标签**不得假红**（服务端 source 值，issue #6461 跟踪的是「不上屏」而非改名）
    assert old_name_violations("const SOURCE = '[米宝解读]'\n") == []
    # ④ 注释面豁免（历史沿革照旧保留）
    assert old_name_violations("// 2026-10-08 改名自米宝\n") == []
    # ⑤ 新称呼零命中（正面对照：守卫不会被自己的新口径喂红）
    assert old_name_violations("const a = '黄金策'\nconst b = '元元'\nconst c = '观星台'\n") == []
