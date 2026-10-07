# case_ids: UI-082
"""**产品定位文案**守卫：米高不得再被写成「电商管理系统 / 电商管理解决方案」（issue #6463）。

用户 2026-10-07 逐字：「米高 / 企业级AI电商管理解决方案，这里的定位已经不太对了，我们不单单管理电商了，
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

#: 旧定位串（米高**自身**被写成电商管理系统的两种形态）
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
        "生产源码里出现了旧定位串（用户 2026-10-07 裁定：米高定位改「企业级AI经营管理平台」）：\n  "
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
    sample = "const title = '米高 - AI电商管理系统'\nconst ok = '企业级AI经营管理平台'\n"
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
        "const title = '米高 - AI经营管理平台'\n"
    )
    assert violations_in("sample.tsx", sample) == [], "注释面被误判成违规（假红）"


def test_string_with_double_slash_is_not_eaten_as_a_comment():
    """引号感知的反向对照：URL 里的 `//` 不得把后续代码面吃掉（否则真违规会漏判 = 假绿）。"""
    sample = "const u = \"https://app.migaozn.com/s/7Q2M4K8P\"\nconst bad = \"AI电商管理系统\"\n"
    assert [v.split(":")[1] for v in violations_in("sample.ts", sample)] == ["2"], (
        "字符串里的 `//` 把后面的真违规吃掉了（复用了按 `//` 截断的旧尺子？）"
    )
