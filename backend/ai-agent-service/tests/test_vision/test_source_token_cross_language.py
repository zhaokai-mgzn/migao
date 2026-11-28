# case_ids: PR-124
"""`[黄金策解读]` 来源标记：**跨语言重复字面量**的同源守卫（issue #9306）。

## 病（一类，不是一个）

「这格的值是模型推的、不是图上抄的」靠**一枚来源字符串**表达，而它在两个语言里各写一份：

| 侧 | 载体 | 作用 |
|---|---|---|
| 后端（生成） | `backend/ai-agent-service/app/vision/deep_channel.py` 的 `SOURCE_INTERPRETED` | 给解读格打标 |
| 前端（消费） | `frontend/admin-web/src/lib/agent-page-fill.ts` 的 `PAGE_FILL_SOURCE_INTERPRETED` | **按值逐字比较**决定挂哪枚徽标 |

两者**没有 import 关系**（跨语言），也没有任何东西同步它们。改一侧另一侧没跟的后果不是报错，
而是**静默错配**：前端把解读格当成普通格（一格都不挂徽标），而两侧各自的判据都还是绿的
—— 它们只断言「自己这一侧非空 / 等于自己写下的那个字面量」。

⇒ 本判据只判一件事：**两侧字面量逐字相等**。任一侧改字、改措辞、改成模板拼接（读不到字面量）
⇒ 具名红并打出两侧的值。

## 三态

`0` = 绿；`1` = 红（具名：两侧的值 + 文件）；本判据零网络、零时钟、零 LLM，**无 `3`**。
"""
from __future__ import annotations

from pathlib import Path

from app.vision.deep_channel import SOURCE_INTERPRETED

REPO_ROOT = Path(__file__).resolve().parents[4]
FRONTEND_TS = REPO_ROOT / "frontend" / "admin-web" / "src" / "lib" / "agent-page-fill.ts"

#: 前端那枚常量的名字（读不到 ⇒ fail-loud，不静默通过）
TS_CONST_NAME = "PAGE_FILL_SOURCE_INTERPRETED"

#: 退役品牌名（`[黄金策解读]` 取代 `[米宝解读]`；旧 token 不保留 —— 它是 DTO 值、不落库）
RETIRED_BRAND = "米宝"


def ts_token(text: str, name: str = TS_CONST_NAME) -> str:
    """从 TS 源码里取 `export const <name> = '…'` 的字面量。

    纯字符串操作（`startswith` + 切片），**不用正则捕获引号**：那族写法会把注释里的假字面量
    当成真值（`tests/unit_ci_workflows/test_guard_parsing_is_comment_aware.py` 的同族教训）。
    读不到单层引号字面量 ⇒ `AssertionError`（fail-loud，不返回空串）。
    """
    prefix = f"export const {name} ="
    lines = [line.strip() for line in text.split("\n") if line.startswith(prefix)]
    assert len(lines) == 1, (
        f"{FRONTEND_TS} 里 `{prefix}` 命中 {len(lines)} 行（应恰好 1 行）"
        "—— 判据读不到真值，拒绝静默通过"
    )
    raw = lines[0][len(prefix) :].strip().rstrip(";").strip()
    quote = raw[:1]
    assert quote in {"'", '"'} and len(raw) >= 2 and raw[-1] == quote and quote not in raw[1:-1], (
        f"`{name}` 的字面量形态不是单层引号（现取 {raw!r}）—— 改成模板 / 拼接后本判据读不到真值"
    )
    return raw[1:-1]


def token_mismatch(backend: str, frontend: str) -> str | None:
    """两侧字面量不一致 ⇒ 具名差异描述；一致 ⇒ None。纯函数（红证直接喂字符串）。"""
    if backend == frontend:
        return None
    return (
        f"来源标记两侧不一致：后端 deep_channel.SOURCE_INTERPRETED={backend!r} ≠ "
        f"前端 agent-page-fill.{TS_CONST_NAME}={frontend!r} —— "
        "前端按值逐字比较，改一侧不同批改另一侧 ⇒ 解读格静默不挂徽标"
    )


def test_frontend_and_backend_tokens_are_identical():
    """判据 1：跨语言字面量逐字相等（两侧独立写，不同源复制）。"""
    frontend = ts_token(FRONTEND_TS.read_text(encoding="utf-8"))
    assert frontend == SOURCE_INTERPRETED, (
        f"来源标记两侧不一致：后端 deep_channel.SOURCE_INTERPRETED={SOURCE_INTERPRETED!r} ≠ "
        f"前端 agent-page-fill.{TS_CONST_NAME}={frontend!r} —— "
        "前端按值逐字比较，改一侧不同批改另一侧 ⇒ 解读格静默不挂徽标"
    )


def test_token_is_not_the_retired_brand():
    """判据 2：token 不得含退役品牌名，且必须仍与识别标记可区分（来源可分辨是硬要求）。"""
    assert RETIRED_BRAND not in SOURCE_INTERPRETED, (
        f"来源标记仍含退役品牌名「{RETIRED_BRAND}」（{SOURCE_INTERPRETED!r}）—— "
        "用户 2026-11-28 裁定：退役品牌名不得出现在任何用户可见面"
    )
    from app.vision.deep_channel import SOURCE_RECOGNIZED

    assert SOURCE_INTERPRETED != SOURCE_RECOGNIZED, (
        f"解读标记与识别标记相同（{SOURCE_INTERPRETED!r}）—— 商家无法判断该信哪一格"
    )


def test_red_proof_each_side_alone_goes_red():
    """红证：**只改一侧**（任一侧）⇒ `token_mismatch` 具名红；两侧同改 ⇒ 绿（判据不是恒真）。"""
    frontend = ts_token(FRONTEND_TS.read_text(encoding="utf-8"))

    only_backend = token_mismatch(f"{SOURCE_INTERPRETED}（旧）", frontend)
    only_frontend = token_mismatch(SOURCE_INTERPRETED, f"{frontend}（旧）")
    assert only_backend and "后端" in only_backend, f"改后端一侧没红：{only_backend}"
    assert only_frontend and "前端" in only_frontend, f"改前端一侧没红：{only_frontend}"
    assert frontend == SOURCE_INTERPRETED, "两侧一致时应为绿（现取两侧不同）"


def test_red_proof_parser_has_teeth():
    """红证：解析器**读得到真值**（否则「两侧相等」是恒真断言），读不到时 fail-loud。"""
    src = "export const PAGE_FILL_SOURCE_INTERPRETED = '[示例解读]'\n"
    assert ts_token(src) == "[示例解读]"

    for broken in (
        "export const PAGE_FILL_SOURCE_INTERPRETED = `[示例解读]`;\n",  # 模板字符串
        "export const PAGE_FILL_SOURCE_INTERPRETED =\n  '[示例解读]'\n",  # 换行拼接写法
        "// export const PAGE_FILL_SOURCE_INTERPRETED = '[示例解读]'\n",  # 被注释掉
    ):
        try:
            ts_token(broken)
        except AssertionError:
            continue
        raise AssertionError(f"解析器对读不到真值的形态静默通过了：{broken!r}")
