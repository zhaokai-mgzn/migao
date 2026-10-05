# case_ids: UI-084
"""聊天气泡「富文本渲染接线」普查 —— issue #6346 的**类级**视角（让同类进不来）。

## 病根（一类缺陷，不是一个缺陷）

米宝 / 小布的回复文本是 **markdown 标记 + 单个换行**（后端直答与 LLM 输出都这样写），
于是**每一处**「把 `message.content` 直接倒进气泡」的渲染面都要自己做一件事：

| 面 | 漏做会怎样（已实测两次） | 正确接线 |
|---|---|---|
| Taro 小程序（`mini-app` / `bmini-app`） | 换行在、但 `**加粗**` 与 `- ` 列表**原样上屏**成星号与短横线 | `import { parseRichText }` + 按行渲染 |
| admin-web（Next.js + react-markdown） | 段落内单个换行被 CommonMark 当**软换行**（= 空格）⇒ 多行回复折成**一整段**长文 | `remarkPlugins` 里挂 `remarkBreaks` |

- 第一次漏：C 端 `mini-app`，2026-09-15 真机实测（用例 UI-042）；
- 第二次漏：B 端 `bmini-app` + `admin-web`，2026-09-28 就存在、2026-10-05 才被用户截图发现（用例 UI-084）。
⇒ **同一个类犯了三次**，而每次都是「新面/新包照抄旧面」——**没有任何判据会因此变红**（旧面的判据只管旧面）。

## 判据（四层，逐条能红）

1. **普查集合冻结**：`frontend/*/src/components/chat/MessageBubble.tsx` 的**现取**集合必须逐字等于
   `FROZEN_BUBBLE_PACKAGES` ⇒ 新前端包（照抄一份气泡）即红、包改名/删除也红；
2. **每个小程序面接线齐全**：该包的气泡源码引用 `parseRichText`，且 `src/utils/richText.ts` 真实存在；
3. **admin-web 面接线**：`frontend/admin-web/src/components/chat/MessageList.tsx` 必须
   `import remarkBreaks` **且**把它放进 `remarkPlugins`（只 import 不挂 = 断线，同样红）；
4. **判别力自证 + 射程自证**：对真语料零违规；对**内存里的坏样例**（摘掉 `parseRichText` /
   摘掉 `remarkBreaks` 挂载 / 摘掉 import）逐条必须判红；普查面 ≥3 个文件（一起收窄 ⇒ 红）。

## 红证（实跑，任选其一）

```bash
# ① 把 bmini 气泡换回「一个 Text 装全文」（摘掉 parseRichText）⇒ 判据 2 判红
# ② 把 admin-web 的 remarkBreaks 从 remarkPlugins 里摘掉（只留 remarkGfm）⇒ 判据 3 判红
python3 -m pytest tests/unit_ci_workflows/test_chat_richtext_surface_guard.py -q
```

## 有意不做的（照实登记，不是「已覆盖」）

- **不**判渲染出来的样子（`<br>` 个数 / 加粗类名）—— 那由三层行为判据负责：
  `frontend/admin-web/tests/unit/components/chat-soft-breaks.test.tsx`、
  `frontend/bmini-app/tests/chat-rich-text.test.ts`、`frontend/bmini-app/tests/chat-rich-text-render.test.tsx`
  （本文件只保证「接线在」，判据 4 的最后一个断言保证那些文件还在）；
- **不**扫 `worker-h5` / 客服工作台等**非气泡**的纯文本展示面（它们按 `white-space: pre-wrap`
  逐字展示，本就不做富文本 —— 把它们拉进来只会造出新的一类假红）；
- 字面量匹配不认识「字段名拼接 / 从配置读」的写法（假绿方向，不会误伤）。
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = REPO_ROOT / "frontend"

BUBBLE_REL = "src/components/chat/MessageBubble.tsx"
RICH_TEXT_REL = "src/utils/richText.ts"
ADMIN_WEB_MESSAGE_LIST = "frontend/admin-web/src/components/chat/MessageList.tsx"

#: 冻结的普查集合（**两边一起收窄也逃不掉**：现取必须等于本常量，新包须连同本判据一起登记）
FROZEN_BUBBLE_PACKAGES = ("bmini-app", "mini-app")

#: 行为判据（判据 4 保证它们还在 —— 守卫绿而行为判据被删 = 空守）
BEHAVIOUR_TESTS = (
    "frontend/admin-web/tests/unit/components/chat-soft-breaks.test.tsx",
    "frontend/bmini-app/tests/chat-rich-text.test.ts",
    "frontend/bmini-app/tests/chat-rich-text-render.test.tsx",
)


def find_bubble_packages() -> list[str]:
    """现取的「有气泡渲染面的前端包」集合（frontend/*/src/components/chat/MessageBubble.tsx）。"""
    return sorted(p.parents[3].name for p in FRONTEND.glob(f"*/{BUBBLE_REL}"))


def judge_bubble_source(text: str) -> list[str]:
    """小程序气泡源码的接线判定（纯函数：坏样例可在内存里判红）。"""
    problems: list[str] = []
    if "parseRichText" not in text:
        problems.append("未引用 parseRichText（换行在、但 **与 - 会原样上屏）")
    if "message-bubble__text-strong" not in text:
        problems.append("未渲染加粗样式类 message-bubble__text-strong（粗体段没有落点）")
    return problems


def judge_admin_web_markdown_source(text: str) -> list[str]:
    """admin-web（react-markdown）的接线判定（纯函数）。

    ⚠️ 「挂载」必须判**插件数组本身**：只判 `remarkBreaks` 这个标识符出现会被 import 行满足
    —— 实测过「摘掉挂载只留 import ⇒ 判据仍绿」（假绿）。
    """
    problems: list[str] = []
    if "remark-breaks" not in text:
        problems.append("未 import remark-breaks（段落内单个换行会被折成空格）")
    if not re.search(r"remarkPlugins=\{\[[^\]]*\bremarkBreaks\b", text):
        problems.append("remarkPlugins 里没挂 remarkBreaks（只 import 不挂 = 断线）")
    return problems


def test_bubble_surface_census_is_frozen() -> None:
    """判据 1：现取集合逐字等于冻结集合（新包照抄一份气泡 ⇒ 红）。"""
    assert find_bubble_packages() == list(FROZEN_BUBBLE_PACKAGES)


def test_bubble_packages_wire_rich_text() -> None:
    """判据 2：每个小程序包都接上了 parseRichText，且解析器文件真实存在。"""
    assert len(FROZEN_BUBBLE_PACKAGES) >= 2, "射程自证：气泡面少于 2 个包 ⇒ 普查已失效"
    for pkg in FROZEN_BUBBLE_PACKAGES:
        parser = FRONTEND / pkg / RICH_TEXT_REL
        assert parser.is_file(), f"{pkg} 缺富文本解析器：frontend/{pkg}/{RICH_TEXT_REL}"
        problems = judge_bubble_source((FRONTEND / pkg / BUBBLE_REL).read_text(encoding="utf-8"))
        assert problems == [], f"frontend/{pkg}/{BUBBLE_REL} 接线断了：{problems}"


def test_admin_web_markdown_wires_remark_breaks() -> None:
    """判据 3：admin-web 的 ReactMarkdown 挂上了 remarkBreaks。"""
    problems = judge_admin_web_markdown_source(
        (REPO_ROOT / ADMIN_WEB_MESSAGE_LIST).read_text(encoding="utf-8")
    )
    assert problems == [], f"{ADMIN_WEB_MESSAGE_LIST} 接线断了：{problems}"


def test_behaviour_judges_still_exist() -> None:
    """判据 4a：三层行为判据文件都还在（守卫绿而行为判据被删 = 空守）。"""
    missing = [rel for rel in BEHAVIOUR_TESTS if not (REPO_ROOT / rel).is_file()]
    assert missing == [], f"行为判据文件缺失：{missing}"


def test_guard_has_discriminating_power() -> None:
    """判据 4b：判别力自证 —— 坏样例在内存里逐条判红，真语料零违规。"""
    good_bubble = "import { parseRichText } from '../../utils/richText'\n<Text className='message-bubble__text-strong'>{seg.text}</Text>"
    assert judge_bubble_source(good_bubble) == []

    bad_bubble_cases = {
        "摘掉 parseRichText": good_bubble.replace("parseRichText", "rawContent"),
        "摘掉加粗类": good_bubble.replace("message-bubble__text-strong", "message-bubble__text"),
    }
    for name, sample in bad_bubble_cases.items():
        assert judge_bubble_source(sample) != [], f"坏样例未被判红：{name}"

    good_md = "import remarkBreaks from 'remark-breaks'\n<ReactMarkdown remarkPlugins={[remarkGfm, remarkBreaks]}>"
    assert judge_admin_web_markdown_source(good_md) == []

    bad_md_cases = {
        # 实测过的假绿形态：import 行还在 ⇒ 只判标识符出现会漏（故用插件数组正则）
        "只 import 不挂载": "import remarkBreaks from 'remark-breaks'\n<ReactMarkdown remarkPlugins={[remarkGfm]}>",
        "摘掉 import": "<ReactMarkdown remarkPlugins={[remarkGfm, remarkBreaks]}>",
    }
    for name, sample in bad_md_cases.items():
        assert judge_admin_web_markdown_source(sample) != [], f"坏样例未被判红：{name}"
