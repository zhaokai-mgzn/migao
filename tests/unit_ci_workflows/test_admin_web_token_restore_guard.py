# case_ids: AU-012
"""admin-web「裸 fetch + Bearer」面的 token 恢复接线 —— issue #6352 的**类级**视角。

## 病根（一类缺陷，不是一个缺陷）

admin-web 的 token 只在**内存**里（审计 07 P1-F1：JWT 不落 localStorage），整页加载后必须**重新取回**。
仓里有两条 HTTP 路，**对「token 没了」的反应完全不同**：

| 路 | 401 时的行为 | 载重面 |
|---|---|---|
| axios（`src/lib/request.ts` + `src/lib/token-refresh-manager.ts`） | 拦截器**自动 refresh + 重放**（失败队列串行化） | 业务页面（`/orders`、看板…） |
| **裸 `fetch` + `Authorization: Bearer`** | **零重试** —— token 为空就一路 401 | 聊天面（直连 ai-agent）、打印抓取 |

⇒ 于是长出一个**极具误导性**的现象（#6352 实测）：整页加载后**业务页面全部正常**、唯独聊天面
「创建会话失败，请稍后重试」，而 ai-agent 日志只说 `no token provided`。
根因不在聊天面，而在**会话恢复只跑了 `/api/auth/me`**——而 `/api/auth/me` **从不下发 accessToken**
（键集实测 = `user/roles/permissions/menus/capabilities`），恢复内存 token 的唯一入口是
`POST /api/auth/refresh`（HttpOnly cookie 换新 token）。

## 判据（三层，逐条能红）

1. **裸 fetch + Bearer 面冻结**：`frontend/admin-web/src/**` 里同时出现 `Bearer` 与 `fetch(` 的**文件集合**
   必须逐项等于 `FROZEN_RAW_FETCH_SURFACES`（新面 ⇒ 红：作者必须回答「它的 token 从哪来」）；
2. **会话恢复必须换 token**：`frontend/admin-web/src/store/auth.ts` 的 `initialize` 必须调用
   `refreshAccessToken()`（只跑 `/me` = 改前形态 ⇒ 红）；
3. **判别力自证**：坏样例（摘掉 refresh 调用 / 裸 fetch 面集合少一个）在内存里逐条判红。

## 红证（实跑）

```bash
# ① 把 src/store/auth.ts 的 initialize 换回改前版本（只跑 /me）⇒ 判据 2 红
# ② 从 FROZEN_RAW_FETCH_SURFACES 里去掉 src/store/chat.ts ⇒ 判据 1 红
python3 -m pytest tests/unit_ci_workflows/test_admin_web_token_restore_guard.py -q
```

## 有意不做的（照实登记，**不是**「已覆盖」）

- **不**给裸 fetch 面加 401 自动重试（那是另一件事：token **中途过期**仍会让聊天面断一次）。
  本次只治「整页加载后 token 从未被取回」这条；中途过期面按 issue #6352 的边界登记在案。
- **不**扫 `frontend/bmini-app/**`、`frontend/mini-app/**`（两端 token 由各自的 store/cookie 路径持有，
  不在本判据射程内）。
- 字面量匹配不认识 `headers` 拼装出来的 Bearer（假绿方向，不会误伤）。
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ADMIN_WEB_SRC = REPO_ROOT / "frontend" / "admin-web" / "src"
AUTH_STORE = "frontend/admin-web/src/store/auth.ts"

#: 冻结的「裸 fetch + Bearer」面（现取必须与它**逐项相等** —— 判据 1 用等号，不设下界）
FROZEN_RAW_FETCH_SURFACES = (
    "frontend/admin-web/src/lib/api.ts",
    "frontend/admin-web/src/store/chat.ts",
)


def raw_fetch_bearer_surfaces() -> list[str]:
    """现取的「同时出现 `Bearer` 与 `fetch(`」的 admin-web 源码文件集合（仓库根相对、字典序）。"""
    hits = []
    for path in sorted(ADMIN_WEB_SRC.rglob("*")):
        if path.suffix not in (".ts", ".tsx") or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if "Bearer" in text and "fetch(" in text:
            hits.append(path.relative_to(REPO_ROOT).as_posix())
    return hits


def judge_initialize_restores_token(source: str) -> list[str]:
    """会话恢复判定（纯函数：坏样例可在内存里判红）。"""
    body = source[source.index("initialize: async () =>") :] if "initialize: async () =>" in source else ""
    if not body:
        return ["找不到 `initialize` 实现（会话恢复入口改名/被删）"]
    # 只取 initialize 的函数体（到下一个顶层方法前的 `},` 收口）
    head, _, tail = body.partition("\n    // 清除认证状态")
    body = head or tail
    if not re.search(r"refreshAccessToken\(\)", body):
        return ["initialize 未调用 refreshAccessToken()（只跑 /api/auth/me ⇒ token 永不落内存）"]
    return []


def test_raw_fetch_bearer_surfaces_are_frozen() -> None:
    """判据 1：裸 fetch + Bearer 面逐项冻结（新面 ⇒ 红）。"""
    assert raw_fetch_bearer_surfaces() == list(FROZEN_RAW_FETCH_SURFACES)


def test_initialize_restores_access_token() -> None:
    """判据 2：整页加载后必须经 /api/auth/refresh 把 token 装回内存。"""
    problems = judge_initialize_restores_token((REPO_ROOT / AUTH_STORE).read_text(encoding="utf-8"))
    assert problems == [], f"{AUTH_STORE} 的会话恢复接线断了：{problems}"


def test_behaviour_judge_exists() -> None:
    """判据 3a：行为判据文件仍在（守卫绿而行为判据被删 = 空守）。"""
    rel = "frontend/admin-web/tests/unit/store/auth.test.ts"
    assert (REPO_ROOT / rel).is_file(), f"行为判据文件缺失：{rel}"


def test_guard_has_discriminating_power() -> None:
    """判据 3b：判别力自证 —— 坏样例逐条判红。"""
    good = "initialize: async () => {\n      await get().refreshAccessToken()\n    },\n    // 清除认证状态"
    assert judge_initialize_restores_token(good) == []

    bad = "initialize: async () => {\n      await get().fetchUserInfo()\n    },\n    // 清除认证状态"
    assert judge_initialize_restores_token(bad) != [], "「只跑 /me」的坏样例未被判红"

    narrowed = [p for p in FROZEN_RAW_FETCH_SURFACES if not p.endswith("chat.ts")]
    assert narrowed != list(FROZEN_RAW_FETCH_SURFACES), "冻结集合收窄未改变读数（自证失效）"
