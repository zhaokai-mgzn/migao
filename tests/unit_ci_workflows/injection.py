# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012 ——
#   见同目录 `_source_parsing.py` / `test_guard_parsing_is_comment_aware.py` 的同款声明。
#   本 PR **不新建用例族**：现取号 MC-133 未使用 —— 新增用例族要改 `.github/cases/*.yml` +
#   重渲染生成物，而本包是「既有红证注入原语」的类级固化，不是新业务用例。）
"""注入式红证的**唯一**原语：`inject()`（issue #7017 类级固化的承载体）。

## 病（一类缺陷，不是一个缺陷）

红证普遍用「把 A 逐字替换成 B」造坏形态。A 一旦**上下文漂移**（间距 / 换行 / 变量名变了），
`str.replace` **找不到目标就返回原串** —— 注入静默变成空操作：

- 判据仍绿 ⇒ 被读成「判据没牙」（动作 = 补判据）；
- 真因是「红证没生效」（动作 = 改锚点）。

两个**处置相反**的故障同一个读数，而**没有任何东西会提醒你**。#6611 现场：某包把部署调用改成
`admin-web "$BUILD_SHA" "$BUILT_AT"`（走位置实参面）⇒ 锚点不再是「服务键独占一行」，
`str.replace` 什么都没替换 ⇒ 那条守卫一直报「**变异没有被判红**」—— 读起来像判据没有牙。

## 本模块钉的三条（每条都会**当场**抛错，没有静默路径）

| 情形 | 行为 |
|---|---|
| **0 命中** | 抛 `AnchorDrift`：报文含**语料文件名 + 锚点前 60 字 + 同前缀仍存在的行** ⇒ 一眼看出「锚点漂了」 |
| **命中数 ≠ `count`** | 抛 `AmbiguousAnchor`：旧写法 `replace(..., 1)` 会**静默只改第一处**，注入语义已不确定 |
| **`old == new`**（换了等于没换） | 抛 `InjectionError`：空操作不是注入，造不出坏形态 |

**没有**「找不到就返回原串」的分支 —— 这是本模块存在的全部理由（它是缺陷形态本身）。

## 用法

    from unit_ci_workflows.injection import inject

    broken = inject(
        src,
        'run: bash scripts/acr_login.sh ${{ env.ACR_REGISTRY }} "${{ secrets.ACR_USERNAME }}" '
        '"${{ secrets.ACR_PASSWORD }}"',
        "run: echo x | docker login ${{ env.ACR_REGISTRY }} -u u --password-stdin",
        where=".github/workflows/deploy-ai-agent-service.yml",
    )

⚠️ 请**总是**传 `where=`（语料文件名）：不传时错误里只剩 `<未指明语料>`，把一个**具名**红
变成匿名红。类级判据 `test_red_proof_anchor_liveness.py` 要求登记在案的迁移点都带 `where=`。

## 边界（照实登记，§19.1）

- 本模块只保证「**这一次替换**命中且唯一」；它不知道锚点**语义**是否仍是当初那条坏形态 ——
  判据该不该红仍由红证自己证明（本模块治的是「注入有没有生效」，不是「判据有没有牙」）。
- `count=N` 是「**恰好 N 次**」而不是「至多 N 次」：N 次全替换；少一次也抛 `AmbiguousAnchor`。
- 只覆盖 `str.replace` 形态的注入；按行插入 / `sed -i` / `rpartition` 等其它变异形态不在射程内
  （它们的失效模式不同，须各自自证）。
"""
from __future__ import annotations

MAX_ANCHOR_PREVIEW = 60

#: 未传 `where=` 时的占位符：故意写得像「缺了东西」，而不是像某个真实文件名。
UNKNOWN_WHERE = "<未指明语料>"


class InjectionError(AssertionError):
    """注入失败。

    继承 `AssertionError` 而不是 `Exception`：pytest 里它是一条**失败断言**（红），
    不是 collect/setup 阶段的 error —— 红证的失败必须长得像判据失败，而不是像测试写错了。
    """


class AnchorDrift(InjectionError):
    """锚点在当前语料上 **0 命中** ⇒ 注入没生效（**不是**「判据没牙」）。"""


class AmbiguousAnchor(InjectionError):
    """锚点命中数 ≠ 期望 ⇒ 注入语义不确定（旧写法会静默只改第一处）。"""


def _preview(text: str, limit: int = MAX_ANCHOR_PREVIEW) -> str:
    """锚点预览：折成一行的前 `limit` 个字符（报文里一眼能看出该改哪一段）。"""
    one_line = text.replace("\n", "\\n")
    return one_line if len(one_line) <= limit else one_line[:limit] + "…"


def _nearby_lines(corpus: str, anchor: str, limit: int = 3) -> str:
    """漂移提示：锚点首行的前 32 字**仍出现在**语料哪些行（连前缀都没有 ⇒ 不硬猜）。

    这是「可归因」的最小实现：漂一格时前缀通常还在，直接把候选行贴出来。
    """
    first = anchor.strip().splitlines()[0].strip()[:32] if anchor.strip() else ""
    if len(first) < 6:
        return ""
    hits = [(i, line.strip()[:90]) for i, line in enumerate(corpus.splitlines(), 1) if first in line]
    if not hits:
        return ""
    shown = "；".join(f"L{i}: {line}" for i, line in hits[:limit])
    more = f"（另有 {len(hits) - limit} 行）" if len(hits) > limit else ""
    return f"\n  同前缀仍在：{shown}{more} —— 锚点是不是漂了一格？"


def inject(text: str, old: str, new: str, *, count: int = 1, where: str = UNKNOWN_WHERE) -> str:
    """把 `old` **恰好**替换成 `new`；「没命中 / 不唯一 / 空操作」一律抛错。

    Args:
        text: 语料原文（通常是从真文件读出来的）。
        old: 注入锚点。**必须**在当前语料上恰好出现 `count` 次。
        new: 替换内容（坏形态 / 变异体）。
        count: 期望命中次数，默认 1（= 唯一锚点）。显式给 N 表示「恰好 N 处一起换」。
        where: 语料文件名（仓库相对路径）。漂移/歧义报错会把它写进报文。

    Returns:
        替换后的文本（**保证**与 `text` 不同 —— 相同即为空操作，已抛错）。

    Raises:
        AnchorDrift: 0 命中 ⇒ 锚点漂移，注入没生效。
        AmbiguousAnchor: 命中数 ≠ `count`。
        InjectionError: `old == new`（空操作）。
        TypeError / ValueError: 参数形态不对（非 str / 空锚点 / count < 1）。
    """
    for name, value in (("text", text), ("old", old), ("new", new)):
        if not isinstance(value, str):
            raise TypeError(f"inject() 的 {name} 必须是 str（收到 {type(value).__name__}）")
    if not old:
        raise ValueError("inject() 不许用空锚点：空串 replace 会在每个字符间插值，不是注入")
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError(f"inject() 的 count 必须是 >=1 的整数（收到 {count!r}）")

    hits = text.count(old)
    if hits == 0:
        raise AnchorDrift(
            f"锚点漂移（AnchorDrift）：{where} 里找不到注入锚点 ⇒ **注入没生效**，这条红证不成立；"
            "这**不是**「判据没牙」（两者处置相反：改锚点 vs 补判据）。"
            f"\n  锚点前 {MAX_ANCHOR_PREVIEW} 字：{_preview(old)!r}"
            f"{_nearby_lines(text, old)}"
        )
    if hits != count:
        hit_lines = [i for i, line in enumerate(text.splitlines(), 1) if old in line]
        raise AmbiguousAnchor(
            f"锚点不唯一（AmbiguousAnchor）：{where} 里锚点命中 {hits} 次（期望 count={count}）"
            "⇒ 注入语义已不确定（旧写法 `replace(..., 1)` 会**静默只改第一处**，红证可能改了别处）。"
            f"\n  锚点前 {MAX_ANCHOR_PREVIEW} 字：{_preview(old)!r}"
            f"\n  命中行：{hit_lines[:10] or '（跨行锚点，无单行命中）'}"
        )

    replaced = text.replace(old, new, count)
    if replaced == text:
        raise InjectionError(
            f"注入是空操作：{where} 的替换内容与锚点相同（old == new）⇒ 造不出坏形态"
            f"\n  锚点前 {MAX_ANCHOR_PREVIEW} 字：{_preview(old)!r}"
        )
    return replaced
