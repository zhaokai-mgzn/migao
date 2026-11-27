# case_ids: MC-012, CH-015
"""C 端「转人工」口径：**通道侧有人工客服**（2026-11-27 事实变更）⇄ **工具侧仍无 `human_handoff`**（2026-09-19 裁定）。

## 两条约束的交集（缺一条就会写错方向）

1. **2026-09-19 用户裁定**（工具面，**未变**）：「不应该存在 human_handoff 这种东西，以后全是
   AI 来判断」⇒ 工具不进注册表、不进任何 skill 工具集、prompt 不邀请调用。
   结构性反回退判据 = `tests/unit_ci_workflows/test_human_handoff_retired.py`，**本文件不复制**。
2. **2026-11-24~27 事实变更**（通道面，**新增**）：商家开通微信客服后，顾客在微信客服里发送
   「人工」会被 `backend/admin-api/src/main/java/com/migao/admin/service/kf/KfDecisionService.java`
   的 `HUMAN_WORDS` 规则**直接**判 `ESCALATE_HUMAN`（**不经 AI 判定**）；转接实现见
   `backend/admin-api/src/main/java/com/migao/admin/service/kf/KfTransferService.java`
   （类注释逐字：「这里不是 human_handoff 工具复活——是**通道能力**」）。

⇒ 两件事**同时成立**：AI 侧不做转接；通道侧有人做转接。旧 C 端文案通篇写着
「系统已无人工转接通道」「不要把人推给一个不存在的入口」—— 那是**把已经存在的能力说成不存在**
（顾客照做本可以成功，AI 却否认它），与「假承诺」是**相反**的两种失真，不能用一条禁令同时治。

## 本文件锁三条（每条都能单独变红，反方向注入读数见 PR body）

| # | 判据 | 反方向注入 ⇒ 具名红 |
|---|---|---|
| 1 | **不得否认人工客服的存在**：C 端 prompt 源码 / C 端参考层 / C 端用户可见文案里，不得出现「无人工 / 没有人工 / 人工转接通道 / 不存在的人工入口 / 不承诺转人工」 | 把「系统已无人工转接通道」写回任一处 ⇒ 点名 `文件:行` |
| 2 | **必须给可执行落点**：三个 C 端内联 prompt + `base/identity-xiaobu.md` 必须同时含「微信客服」与「发送「人工」」 | 删掉落点句 ⇒ 点名缺哪一处（prompt 常量名 / 参考文件） |
| 3 | **AI 自己不许承诺已完成转接**：三个 C 端内联 prompt 必须仍在**禁令语境**里点名「已为您转接人工客服 / 已提交转人工申请 / 已通知人工客服」 | 只留落点、删掉禁令 ⇒ 指名缺哪条禁令（顾客会以为通道转接 = AI 已办） |

## 口径边界（照实登记，别把它读成覆盖面更大的东西）

- 本文件**只判 C 端文案面**（skill 内联 prompt 字面量 / C 端参考层 / C 端用户可见文案全文）；
- **不判**工具可达性（任何 skill 工具集含 `human_handoff` ⇒ 红，那是 `test_human_handoff_retired.py`
  的结构判据）。本文件的任何改动**都不许**当作放宽那条判据的理由；
- **不判** admin-api 的转接实现（规则命中 / 回滚 / 工作台会话），那归 admin-api 单测与
  `.github/cases/` 的 kf 用例面（**不**在本 PR 的面内）；
- **不判** B 端（黄金策）prompt 的同类措辞 —— B 端没有微信客服通道，口径不同，不在此列；
- 纯静态（CI 的 `ci workflow helper unit tests` 只装 `pytest` + `pyyaml`）⇒ 零 ai-agent 依赖，
  不 import `app.*`（判据自证见 `TestCaliberGuardIsNotVacuous`）。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICE_ROOT = REPO_ROOT / "backend" / "ai-agent-service"
APP_DIR = SERVICE_ROOT / "app"
SKILLS_DIR = APP_DIR / "graph" / "skills"
REF_DIR = SKILLS_DIR / "references"

#: **C 端内联 prompt 的真值源**：`{skill 模块: 模块级 prompt 常量名}`。
#: 它们就是 `SkillConfig.system_prompts["xiaobu"]` 注入模型的那段文本（C 端规则主要在这层）。
CUSTOMER_PROMPTS = {
    SKILLS_DIR / "customer_general_skill.py": "CUSTOMER_GENERAL_SYSTEM_PROMPT",
    SKILLS_DIR / "customer_order_skill.py": "CUSTOMER_ORDER_SYSTEM_PROMPT",
    SKILLS_DIR / "customer_aftersales_skill.py": "CUSTOMER_AFTERSALES_SYSTEM_PROMPT",
}

#: C 端**模型可见的参考层**。`base/identity-xiaobu.md` 按 persona 只注入 C 端；
#: `base/principles.md` / `PROMPT-rules.md` 是**共享层**，同样会进 C 端 prompt ⇒ 一并判
#: （共享层里写「无人工通道」等于把同一个假真值喂给所有 skill，包括 C 端）。
CUSTOMER_REFERENCE_FILES = (
    REF_DIR / "base" / "identity-xiaobu.md",
    REF_DIR / "base" / "principles.md",
    REF_DIR / "PROMPT-rules.md",
    REF_DIR / "prompts" / "customer_knowledge.md",
    REF_DIR / "prompts" / "customer_quote.md",
)

#: C 端用户可见文案的承载文件（skill 源码含内联 prompt + 直接回复/能力清单）。
CUSTOMER_SURFACE_FILES = tuple(CUSTOMER_PROMPTS) + (APP_DIR / "agents" / "agents" / "xiaobu.py",)

#: 判据 1 的扫描面 = 上述两类 + C 端 few-shot（`EXAMPLES-customer_*.md` 注入对应 skill 的 L5）。
#: ⚠️ 刻意用 `EXAMPLES-customer_*.md`（带下划线）：`EXAMPLES-customer.md` 是 **B 端**客户管理域。
CUSTOMER_SCAN_FILES = (
    CUSTOMER_SURFACE_FILES
    + CUSTOMER_REFERENCE_FILES
    + tuple(sorted(REF_DIR.glob("EXAMPLES-customer_*.md")))
)

#: 「否认人工存在」的写法（同义反复的几种都算）。**只匹配否认句** ——
#: 正确文案（「不得否认人工客服的存在」「在微信客服里发送「人工」即转接真人客服」）不含其中任何一条。
DENIAL_PATTERNS = (
    "无人工",
    "没有人工",
    "人工转接通道",
    "不存在的人工入口",
    "不承诺转人工",
)

#: 落点判据：通道名 + **可执行动作**（告诉顾客发哪两个字）。只写「有人工」不算落点。
LANDING_CHANNEL = "微信客服"
LANDING_ACTION_RE = re.compile(r"发送\s*「人工」")

#: AI **无权承诺**的动作（通道转接是 kf 规则干的，不是 AI 干的）。三条都保留，缺一条即红。
CLAIM_PHRASES = ("已为您转接人工客服", "已提交转人工申请", "已通知人工客服")

#: 禁令语境窗口：命中「已为您转接…」时，它前后这些字符内必须出现禁令词（否则是**处方**不是禁令）。
_PROHIBITION_WINDOW_BEFORE = 80
_PROHIBITION_WINDOW_AFTER = 20
_PROHIBITION_WORDS = ("禁止", "不得", "不要")


# ──────────────────────────────────────────────────────────────────────────────
# 纯函数内核（供注入式红证/负例驱动，与被测真值解耦）
# ──────────────────────────────────────────────────────────────────────────────


def prompt_literal(path: Path, const: str) -> str:
    """取 `path` 里模块级 `const = "<字符串字面量>"` 的值（fail-closed）。

    反解的是**真的会进模型的那段文本**，不是整文件文本 —— 注释/文档串不能冒充 prompt 面。
    """
    assert path.is_file(), f"C 端 prompt 真值源不存在：{path}（fail-closed）"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if const not in names:
            continue
        value = node.value
        assert isinstance(value, ast.Constant) and isinstance(value.value, str), (
            f"{path.name}: `{const}` 不是字符串字面量（{ast.dump(value)[:60]}）"
            f"—— 判据无法反解，宁可红（fail-closed）"
        )
        return value.value
    raise AssertionError(
        f"{path.name} 里找不到模块级 `{const}` —— prompt 真值源消失（fail-closed）"
    )


def denial_hits(text: str) -> list[str]:
    """文本里的「否认人工存在」措辞（纯函数）。"""
    return [p for p in DENIAL_PATTERNS if p in str(text)]


def has_handoff_landing(text: str) -> bool:
    """是否给了**可执行落点**：通道名 + 「发送「人工」」（纯函数）。"""
    return LANDING_CHANNEL in str(text) and bool(LANDING_ACTION_RE.search(str(text)))


def claim_without_prohibition(text: str) -> list[str]:
    """`CLAIM_PHRASES` 里**出现在禁令语境之外**的条目（纯函数）。

    禁止列表里的「已为您转接人工客服」是**禁令**（正确）；正文里单独出现的
    「已为您转接人工客服，请稍等」是**假承诺**（错误）。两者只差上下文 ⇒ 判据必须看窗口。
    """
    offenders: list[str] = []
    for phrase in CLAIM_PHRASES:
        start = 0
        seen_any = False
        while True:
            idx = text.find(phrase, start)
            if idx < 0:
                break
            seen_any = True
            window = text[
                max(0, idx - _PROHIBITION_WINDOW_BEFORE): idx + len(phrase) + _PROHIBITION_WINDOW_AFTER
            ]
            if not any(w in window for w in _PROHIBITION_WORDS):
                offenders.append(phrase)
                break
            start = idx + len(phrase)
        if not seen_any:
            offenders.append(phrase)
    return offenders


# ──────────────────────────────────────────────────────────────────────────────
# 判据 ①：不得否认人工客服的存在
# ──────────────────────────────────────────────────────────────────────────────


def test_customer_surfaces_do_not_deny_human_support_exists():
    """C 端文案不得再出现「已无人工转接通道 / 没有人工」这类**否认人工存在**的句子。

    反例输入（任一处即可）：把「如实说明系统已无人工转接通道」写回
    `app/graph/skills/references/EXAMPLES-customer_general.md`，或写进
    `CUSTOMER_GENERAL_SYSTEM_PROMPT` ⇒ 本用例点名 `文件:行`。
    """
    offenders: list[str] = []
    for path in CUSTOMER_SCAN_FILES:
        assert path.is_file(), f"C 端文案面缺文件：{path}（fail-closed，不静默跳过）"
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            hits = denial_hits(line)
            if hits:
                rel = path.relative_to(REPO_ROOT)
                offenders.append(f"{rel}:{lineno}（命中 {'/'.join(hits)}）{line.strip()[:50]}")

    assert not offenders, (
        "以下 C 端文案仍在**否认人工客服的存在**（微信客服通道的人工转接已于 2026-11-24~27 上线，"
        "顾客发送「人工」由 kf 规则直接 ESCALATE_HUMAN）：\n  "
        + "\n  ".join(offenders)
        + "\n→ 正确口径：**不得否认人工客服的存在** + 给出可执行落点"
          "（在微信客服里发送「人工」即转接真人客服）；"
        "\n  AI 自己仍不许承诺「已为您转接 / 已提交申请 / 已通知客服」（它没这个能力）。"
    )
    # 自证扫描面非空（否则本判据是空跑）
    assert len(CUSTOMER_SCAN_FILES) >= 10, (
        f"扫描面只有 {len(CUSTOMER_SCAN_FILES)} 个文件 —— 判据射程被无声缩小（fail-closed）"
    )


# ──────────────────────────────────────────────────────────────────────────────
# 判据 ②：必须给可执行落点
# ──────────────────────────────────────────────────────────────────────────────


def test_customer_prompts_give_the_kf_handoff_landing():
    """三个 C 端内联 prompt + `base/identity-xiaobu.md` 必须给出**可执行落点**。

    落点 = 「微信客服」+「发送「人工」」；只写「有人工客服」不算（顾客不知道怎么用）。
    反例输入：删掉 `CUSTOMER_ORDER_SYSTEM_PROMPT` 的落点句 ⇒ 点名该常量。
    """
    missing: list[str] = []
    for path, const in CUSTOMER_PROMPTS.items():
        if not has_handoff_landing(prompt_literal(path, const)):
            missing.append(f"{path.relative_to(REPO_ROOT)}::{const}")

    identity_rel = REF_DIR / "base" / "identity-xiaobu.md"
    if not has_handoff_landing(identity_rel.read_text(encoding="utf-8")):
        missing.append(str(identity_rel.relative_to(REPO_ROOT)))

    assert not missing, (
        "以下 C 端 prompt 面**没有给出可执行的转人工落点**（缺「微信客服」或「发送「人工」」）：\n  "
        + "\n  ".join(missing)
        + "\n→ 正确写法示例：告诉他/她「在微信客服里发送「人工」，系统会转给真人客服」。"
        "\n  ⚠️ 这不是把工具加回来：AI 侧仍无 human_handoff，转接由客服通道的规则直接承接。"
    )


# ──────────────────────────────────────────────────────────────────────────────
# 判据 ③：AI 自己不许承诺已完成转接
# ──────────────────────────────────────────────────────────────────────────────


def test_customer_prompts_forbid_claiming_a_finished_handoff():
    """给了落点之后，AI 仍**不得**把「已转接/已提交/已通知」说成自己做过的动作。

    两种失真不会互相抵消：旧口径是「做得到却说没有」，新口径的风险是「顾客自己发的『人工』，
    AI 冒领成『已为您转接』」。故三个 C 端 prompt 都必须把这三条留在**禁令语境**里。
    反例输入：把 `CUSTOMER_GENERAL_SYSTEM_PROMPT` 的禁令行删掉（只留落点）⇒ 具名红。
    """
    offenders: list[str] = []
    for path, const in CUSTOMER_PROMPTS.items():
        text = prompt_literal(path, const)
        bare = claim_without_prohibition(text)
        if bare:
            offenders.append(
                f"{path.relative_to(REPO_ROOT)}::{const} → {bare}"
            )
    assert not offenders, (
        "以下 C 端 prompt 缺「AI 自己无权承诺已转接」的禁令（或该话术出现在**非禁令语境**）：\n  "
        + "\n  ".join(offenders)
        + "\n→ 必须写成禁令：**禁止**输出「已为您转接人工客服」「已提交转人工申请」「已通知人工客服」"
        "\n  —— AI 没有转接/提交/通知的能力；顾客要人工，只有「自己发送「人工」」这一条路。"
    )


# ──────────────────────────────────────────────────────────────────────────────
# 判据自身可红 + 不恒真（注入式夹具，含负例）
# ──────────────────────────────────────────────────────────────────────────────


class TestCaliberGuardIsNotVacuous:
    """:red_circle: **红证**（注入式）+ **负例**：判据必须能报出，也必须能不报。"""

    def test_denial_detector_reports_the_retired_wording(self):
        """**红证①**：旧口径原句（「如实说明系统已无人工转接通道」）必须被看见。"""
        planted = "顾客说「转人工」时：如实说明系统已无人工转接通道，然后自己继续受理。"
        hits = denial_hits(planted)
        assert "无人工" in hits and "人工转接通道" in hits, (
            f"旧口径没被判据看见（hits={hits}）—— 判据失效"
        )

    def test_denial_detector_quiet_on_the_new_caliber(self):
        """**负例**：新口径文案不得被误报（否则判据会逼人删掉正确文案）。"""
        legit = (
            "顾客明确要人工时**不得否认人工客服的存在**：告诉他/她在微信客服里发送「人工」，"
            "系统会转给真人客服；**禁止**输出\"已为您转接人工客服\"—— 你没有转接能力。"
        )
        assert not denial_hits(legit), (
            f"新口径文案被误报为「否认人工存在」：{denial_hits(legit)}"
        )

    def test_landing_detector_separates_old_and_new_wording(self):
        """**红证②**：旧口径（只有否认、没有落点）不得被判成「给了落点」。"""
        old_style = "顾客说「转人工」时，如实说明系统已无人工转接通道，然后自己继续办"
        assert not has_handoff_landing(old_style), (
            "旧口径被判成「给了可执行落点」—— 判据失效（会让删除落点以后的仓库照样绿）"
        )
        new_style = "告诉他/她在微信客服里发送「人工」即可转接真人客服"
        assert has_handoff_landing(new_style), "新口径没被判成「给了落点」—— 判据失效"

    def test_claim_detector_separates_prohibition_from_promise(self):
        """**红证③**：禁令语境里的三条话术 ⇒ 不报；正文里的假承诺 ⇒ 必报。"""
        prohibition = (
            "**禁止**输出\"已为您转接人工客服\"\"已提交转人工申请\"\"已通知人工客服\""
            "—— 你没有转接/提交/通知的能力。"
        )
        assert claim_without_prohibition(prohibition) == [], (
            f"禁令语境被误报成假承诺：{claim_without_prohibition(prohibition)}"
        )
        promise = "好的亲，已为您转接人工客服，请稍等~"
        assert claim_without_prohibition(promise) == list(CLAIM_PHRASES), (
            f"正文里的假承诺没被看见：{claim_without_prohibition(promise)}"
        )

    def test_prompt_extractor_sees_a_planted_prompt(self, tmp_path):
        """**解析器自证**：植入字面量 prompt ⇒ 必须反解出同一段文本。"""
        planted = tmp_path / "planted_customer_skill.py"
        planted.write_text(
            'X_SYSTEM_PROMPT = """顾客要人工：在微信客服里发送「人工」。"""\n',
            encoding="utf-8",
        )
        text = prompt_literal(planted, "X_SYSTEM_PROMPT")
        assert text == "顾客要人工：在微信客服里发送「人工」。", (
            f"植入的 prompt 反解结果不对：{text!r}"
        )

    def test_prompt_extractor_is_fail_closed_on_missing_constant(self, tmp_path):
        """**fail-closed**：常量不存在 ⇒ 报错，不静默返回空串（空串会让判据变成空跑）。"""
        planted = tmp_path / "no_prompt_skill.py"
        planted.write_text("OTHER = 'x'\n", encoding="utf-8")
        try:
            prompt_literal(planted, "X_SYSTEM_PROMPT")
        except AssertionError:
            return
        raise AssertionError(
            "找不到 prompt 常量时没有 fail-closed —— 真值源漂移会让判据静默空转"
        )

    def test_this_judgement_is_pure_static_and_never_skips(self):
        """自证：本文件**只** import 标准库（CI 那个 job 没有 ai-agent 依赖），且无 skip 分支。"""
        tree = ast.parse(Path(__file__).read_text(encoding="utf-8"), filename=__file__)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert imported == {"__future__", "ast", "re", "pathlib"}, (
            f"本判据引入了非标准库依赖（CI 装不上 ⇒ 变成 skip/collect 错）：{sorted(imported)}"
        )
        assert not any(
            isinstance(n, ast.Attribute) and n.attr == "skip" for n in ast.walk(tree)
        ), "判据里出现 skip —— 那是「绿了但没跑」"