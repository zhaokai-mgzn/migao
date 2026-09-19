# case_ids: PP-011
"""web 面**工序显示名**守卫（issue #4621，web 面工序命名统一 · 阶段 1）。

## 病根（实测）

web 面存在**两套工序名**：`production_operations.name` 是旧命名（把部位编进名字：
`布三边` / `精裁-布`），而主线 / 规则 / 矩阵用的是**逻辑名**（`三边` / `精裁`）
⇒ 商家在界面上一会儿看到 `布三边`、一会儿看到 `三边`。

冻结口径（issue #4621）：显示名 = **逻辑工序名**；该实例**有部位**时拼成 `逻辑名 · 部位`
（如 `三边 · 布帘`）；部位无关工序（`外帘装袋`）⇒ 只显示逻辑名。
后端读面在返回工序名的位置**同时**给出 `logical_name` + `position`（**读时派生、不写库**）；
既有 `operation` / `operation_name` 是**工人端快照名**（变体名）⇒ 保留，但
**web 界面不得渲染该键**。

⚠️ **白名单是判据的覆盖面**（issue #4630 的教训）：#4621 改了三个面，**第 4 个消费面**
（加工单「生产」页的计件表 `PieceworkTable.tsx`，同一份 `per_operation` 数据）漏了，
而当时它**不在** `FACES` 里 ⇒ 守卫照样全绿、没有任何东西会因此变红。
⇒ 判断「某面该不该在清单里」的判据 = **它是否消费了带 `logical_name`/`position` 的读面**，
而不是「#4621 当时改了哪几个文件」。

## 判据形态

| # | 判据 | 红证（怎么让它红） |
|---|---|---|
| C1 | 显示名 helper 存在、导出 `operationDisplayName`、且**拼装只有这一处** | 删/改名 helper ⇒ 必红 |
| C2 | 每个受管面**都 import 了** helper（反空跑：面文件必须是「真的那一个」） | 把 import 删掉 ⇒ 必红 |
| C3 | 受管面里**不得出现**变体名的直接渲染（`.operation` / `operation_name` / 裸 `{operation}`） | 把 `{operationDisplayName(op)}` 改回 `{op.operation}` ⇒ 必红 |
| C4 | 注入式红证 + **内容指纹**自证（禁 mtime/size） | 注入点不存在 / 注入没生效 ⇒ 必红 |

⚠️ **注释不算违规**（C3 先按字符串感知地剥注释）：判据自身不能把「注释里写的
`op.operation` 反例」判成违规 —— 那是假红，会逼人删掉解释性注释。

⚠️ **受管面清单是显式白名单**（不是「扫全仓」）：`routings/page.tsx` 里的 `cell.operation`
本来就是**逻辑名**（矩阵读面的值域），扫全仓会把它判成假红。
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: 显示名的**唯一**实现（拼装只此一份；各页各拼一份必然漂移，而漂移的那一份不会变红）
HELPER = "frontend/admin-web/src/lib/operation-display.ts"

#: 受管面（显式白名单）：工序名会出现在这些界面上的位置
#: 第 4 项是 issue #4630 补的**漏改面** —— 加工单「生产」页的计件表（`per_operation` 的
#: 第 4 个消费面；#4621 只改了前三个 ⇒ 它一直渲染变体名，而**没有任何判据会因此变红**）。
#: 第 5 项是 issue #4647 / D1 补的**会话卡面** —— 米宝会话里的生产进度卡（`current_operation`）；
#: 它改前不在任何清单里 ⇒ 退回裸渲染快照名时**四条判据全绿**。
FACES: tuple[str, ...] = (
    "frontend/admin-web/src/components/production/ProductionProgressTable.tsx",
    "frontend/admin-web/src/components/production/TaskCardPrint.tsx",
    "frontend/admin-web/src/app/(dashboard)/production/piecework/page.tsx",
    "frontend/admin-web/src/components/production/PieceworkTable.tsx",
    "frontend/admin-web/src/components/chat/ProductionProgressCard.tsx",
)

#: 面必须 import 的符号（C2 的反空跑锚点：面文件真的在用那一份实现）
REQUIRED_IMPORT = "operationDisplayName"

#: 变体名「直接渲染」的三种形态（C3）。**只匹配表达式位置**，不匹配 `operation-row-…` 这类
#: 文案/testid（那正是 `data-testid={`operation-row-${op.id}`}` 会误报的地方）。
_VIOLATION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("成员访问 .operation", re.compile(r"\.operation\b(?![\w$])")),
    ("快照键 operation_name", re.compile(r"\boperation_name\b")),
    ("裸标识符 {operation}", re.compile(r"\{\s*operation\b(?![\w$])")),
)

#: helper 必须导出的核心符号（C1 的非空锚点）
_HELPER_EXPORT_RE = re.compile(r"^export\s+(?:async\s+)?function\s+(\w+)", re.M)


def _read(rel: str) -> str:
    """读一个受管文件；**不存在 ⇒ 直接失败**（路径漂移不得退化成静默跳过 = 空跑通过）。"""
    path = REPO_ROOT / rel
    if not path.is_file():
        raise AssertionError(
            f"受管文件不存在：{rel} —— 工序显示名守卫必须能读到它，"
            "路径漂移 / 文件被删 ⇒ 红（**不得**静默跳过）"
        )
    return path.read_text(encoding="utf-8")


def _strip_comments(src: str) -> str:
    """剥掉 `//` 与 `/* */` 注释（**字符串字面量内的不剥**）。

    判据自身不得把注释里的反例（「不要渲染 `op.operation`」这类说明）判成违规 ——
    那是假红，会逼人删掉解释性注释。字符串感知是必须的：`'https://…'` 里的 `//` 不是注释。
    """
    out: list[str] = []
    i, n = 0, len(src)
    quote: str | None = None
    while i < n:
        ch = src[i]
        if quote is not None:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(src[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "\"'`":
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and src[i + 1] == "*":
            i += 2
            while i + 1 < n and not (src[i] == "*" and src[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _violations(src: str) -> list[str]:
    """受管面源码里的**变体名直接渲染**违规（剥注释后扫描；返回可读描述）。"""
    code = _strip_comments(src)
    found: list[str] = []
    for lineno, line in enumerate(code.splitlines(), start=1):
        for label, pattern in _VIOLATION_PATTERNS:
            if pattern.search(line):
                found.append(f"{label} @ 第 {lineno} 行：{line.strip()}")
    return found


def _fingerprint(text: str) -> str:
    """内容指纹（issue #4260 红证卫生：**禁 mtime/size** —— 它们会被同秒写入骗过）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── C1：唯一实现存在且导出核心符号 ────────────────────────────────────────────

def test_c1_helper_is_the_single_composition_point():
    """C1：显示名 helper 存在、导出 `operationDisplayName`、且**同时**读三个契约键。"""
    src = _read(HELPER)
    exported = set(_HELPER_EXPORT_RE.findall(src))
    assert REQUIRED_IMPORT in exported, (
        f"`{HELPER}` 未导出 `{REQUIRED_IMPORT}`（导出：{sorted(exported)}）—— "
        "各面按这个名字 import，改名/漏导出 ⇒ 消费方直接红"
    )
    for key in ("logical_name", "operation", "position"):
        assert key in src, (
            f"`{HELPER}` 里看不到契约键 `{key}` —— 拼装口径必须在这里写全"
            "（`logical_name` 缺失退回 `operation` 原文；`position` 为空只显示逻辑名）"
        )


# ── C2：受管面都用这一份实现（反空跑锚点）────────────────────────────────────

def test_c2_every_face_imports_the_shared_helper():
    """C2：每个受管面都 import 了 helper —— 面文件必须是「真的那一个」（反空跑）。"""
    assert len(FACES) >= 4, "受管面清单被清空 ⇒ 本守卫会空跑通过（判据必须能判红）"
    for rel in FACES:
        src = _read(rel)
        assert REQUIRED_IMPORT in src, (
            f"`{rel}` 没有用 `{REQUIRED_IMPORT}` —— 工序显示名必须走**同一份**拼装实现"
            f"（`{HELPER}`）；各页各拼一份必然漂移"
        )
        assert "@/lib/operation-display" in src, (
            f"`{rel}` 没有从 `@/lib/operation-display` 取 `{REQUIRED_IMPORT}`（换了一份实现？）"
        )


# ── C3：受管面不得直接渲染变体名 ──────────────────────────────────────────────

def test_c3_faces_never_render_the_variant_name():
    """C3：受管面里不得出现变体名的直接渲染（`.operation` / `operation_name` / 裸 `{operation}`）。"""
    offenders: list[str] = []
    for rel in FACES:
        for hit in _violations(_read(rel)):
            offenders.append(f"{rel}: {hit}")
    assert offenders == [], (
        "受管面直接渲染了**工人端快照名**（变体名，如 `精裁-布`）—— issue #4621 要求界面只显示"
        "「逻辑名 · 部位」（如 `精裁 · 布帘`）：\n  " + "\n  ".join(offenders)
        + "\n改用 `operationDisplayName(op)`（唯一实现："
        + HELPER + "）"
    )


# ── C4：注入式红证 + 内容指纹自证 ─────────────────────────────────────────────

def test_c4_injected_variant_render_is_red(tmp_path: Path):
    """C4：往临时副本塞「直接渲染变体名」⇒ 判据必红；并用**内容指纹**自证注入真生效。"""
    rel = FACES[0]
    original = _read(rel)
    assert _violations(original) == [], (
        f"`{rel}` 原文件本应干净（C3 已单独判）—— 这里先红说明 C3 的判据或本文件的预期已变：\n  "
        + "\n  ".join(_violations(original))
    )

    injected = original.replace(f"{{{REQUIRED_IMPORT}(op)}}", "{op.operation}")
    assert injected != original, (
        f"`{rel}` 里找不到注入点 `{{{REQUIRED_IMPORT}(op)}}` ⇒ 本红证会**空跑**"
        "（判据必须能判红）：面文件的渲染形态变了就同步改本守卫"
    )

    copy = tmp_path / Path(rel).name
    copy.write_text(injected, encoding="utf-8")
    after = copy.read_text(encoding="utf-8")

    assert _fingerprint(after) != _fingerprint(original), (
        "注入后内容指纹未变 ⇒ 注入没生效（**禁 mtime/size**：它们会被同秒写入骗过）"
    )
    assert _violations(after), (
        "注入 `{op.operation}` 后判据**没判红** ⇒ 守卫是空判据（不会红的断言 = 空断言）"
    )
