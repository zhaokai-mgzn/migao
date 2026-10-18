# case_ids: AU-013
r"""商家手机端登录态「1 个月」的**单一真值** + **续期接线**守卫（issue #7249）。

## 病灶（2026-10-18 现场，读码非推断）

顶栏「手机端」二维码（#7198）打开 `https://app.migaozn.com/b/` 后，隔一段时间再打开必被踢回登录页。
三处叠加：

1. `application.yml` 的 `jwt.access-token-expiration: 7200`（2 小时）、
   `jwt.refresh-token-expiration: 604800`（7 天）⇒ 登录态实际寿命 = **2 小时**；
2. `frontend/bmini-app` 全仓**零** `/api/auth/refresh` 调用（PC 端 `admin-web` 早就有了）
   ⇒ 401 只能「清 token + 跳登录页」；
3. `authStore` 的 `initialize` / `checkAuth` 在 JWT `exp` 过期时直接 `logout()`
   ⇒ 即使只在请求层补续期，**页面装载**仍会先把人踢走。

## 冻结口径（用户 2026-10-18 逐字「是/b，方案选择A，但是登录态改为1个月」）

- refresh token / cookie = **2592000s（30 天）**；access token 仍 7200s（短凭据面不延长）；
- cookie 有效期**只有一个来源**（`JwtTokenProvider.getRefreshTokenExpiration()`）——
  `AuthService` 不许再抄一份字面量（改一处漏一处 = 一类缺陷，不是一处笔误）；
- 手机端必须有续期：`request.ts` 的 `refreshAccessToken()` + 401 重放一次（单飞），
  且 `authStore` 的 `initialize` / `checkAuth` 在 exp 过期时**先续期**、失败才登出。

## 判据

1. `application.yml` 的 `jwt.refresh-token-expiration` == 2592000 **且**
   `JwtTokenProvider` 的 `@Value` 兜底是同一个数（两处漂移 ⇒ 缺省环境静默回到 7 天）；
2. `AuthService` 不得声明 `REFRESH_TOKEN_COOKIE_MAX_AGE` 字面量常量；
   `setRefreshTokenCookie` 必须取自 `jwtTokenProvider.getRefreshTokenExpiration()`；
3. 手机端续期面存在：`request.ts` 导出 `refreshAccessToken`、401 分支调用它且**排除**工人端点与
   `skipAuth`（登录面）；`authStore` 的 `initialize` / `checkAuth` 均调用它；
4. **判别力自证**：把 yml 改回 604800 / 把 AuthService 常量加回 / 删掉 401 分支的续期调用
   ⇒ 上面的判据各自必红（注入在内存里做，不改工作树）。
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

APP_YML = REPO_ROOT / "backend/admin-api/src/main/resources/application.yml"
PROVIDER = REPO_ROOT / "backend/admin-api/src/main/java/com/migao/admin/security/JwtTokenProvider.java"
AUTH_SERVICE = REPO_ROOT / "backend/admin-api/src/main/java/com/migao/admin/service/AuthService.java"
BMINI_REQUEST = REPO_ROOT / "frontend/bmini-app/src/utils/request.ts"
BMINI_STORE = REPO_ROOT / "frontend/bmini-app/src/store/authStore.ts"

#: 30 天（用户 2026-10-18 裁定「登录态改为 1 个月」）
ONE_MONTH_SECONDS = 2_592_000


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _block_after(text: str, anchor: str) -> str:
    """取 `anchor` 之后第一个 `{...}` 块（花括号配平；找不到 ⇒ 空串）。"""
    idx = text.find(anchor)
    if idx < 0:
        return ""
    start = text.find("{", idx)
    if start < 0:
        return ""
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return text[start:]


def yml_refresh_seconds(text: str):
    """`application.yml` 的 `jwt.refresh-token-expiration`（解析失败 / 缺键 ⇒ None）。"""
    data = yaml.safe_load(text) or {}
    return (data.get("jwt") or {}).get("refresh-token-expiration")


def provider_default_seconds(text: str):
    """`JwtTokenProvider` 的 `@Value("${jwt.refresh-token-expiration:<兜底>}")`。"""
    m = re.search(r'@Value\("\$\{jwt\.refresh-token-expiration:(\d+)\}"\)', text)
    return int(m.group(1)) if m else None


def auth_service_violations(text: str) -> list[str]:
    """cookie 有效期必须**只有** `JwtTokenProvider` 一个来源。"""
    violations: list[str] = []
    if re.search(r"REFRESH_TOKEN_COOKIE_MAX_AGE\s*=\s*\d+", text):
        violations.append("AuthService 又声明了 `REFRESH_TOKEN_COOKIE_MAX_AGE` 字面量（第二份真值）")
    body = _block_after(text, "private void setRefreshTokenCookie(")
    if not body:
        violations.append("找不到 `setRefreshTokenCookie` 方法体")
    elif not re.search(r"jwtTokenProvider\.getRefreshTokenExpiration\(\)", body):
        violations.append("`setRefreshTokenCookie` 未取自 `jwtTokenProvider.getRefreshTokenExpiration()`")
    return violations


def bmini_violations(request_src: str, store_src: str) -> list[str]:
    """手机端续期面：导出 + 401 调用 + 取舍正确 + 页面装载也走它。"""
    violations: list[str] = []
    if "export function refreshAccessToken(" not in request_src:
        violations.append("`frontend/bmini-app/src/utils/request.ts` 未导出 `refreshAccessToken`")
    # 锚在**函数体的 `{`**，不是签名开头：签名里有 `options: RequestOptions = {}`，
    # 从签名开头找「第一个 `{`」会命中那个空默认值 `{}`（判据于是永远看不见函数体）。
    request_fn = _block_after(request_src, "): Promise<T> {")
    if not request_fn:
        violations.append("找不到 `request<T = any>(` 方法体")
    else:
        if "await refreshAccessToken()" not in request_fn:
            violations.append("`request()` 的 401 分支没有调用 `refreshAccessToken()`（2 小时一过必回登录页）")
        if "canRefreshSession(" not in request_fn:
            violations.append("`request()` 未按端点分流（工人端点 / 登录面不得续期）")
    if "function canRefreshSession(" not in request_src:
        violations.append("缺少 `canRefreshSession()`（工人端点 / skipAuth 的 401 必须排除出续期）")
    else:
        guard = _block_after(request_src, "function canRefreshSession(")
        if "WORKER_API_PREFIX" not in guard:
            violations.append("`canRefreshSession()` 未排除工人端点（其 401 不是商家会话过期，issue #6467）")
        if "skipAuth" not in guard:
            violations.append("`canRefreshSession()` 未排除 `skipAuth`（登录面的 401 是凭据错）")
    # 锚在**实现**（`async () => {`），不是接口里的类型声明（`initialize: () => Promise<void>`）
    for name, anchor in (("initialize", "initialize: async () => {"), ("checkAuth", "checkAuth: async () => {")):
        body = _block_after(store_src, anchor)
        if not body:
            violations.append(f"找不到 `{name}` 方法体")
        elif "await refreshAccessToken()" not in body:
            violations.append(f"`authStore.{name}` 在 exp 过期时未先续期（页面装载会先把人踢走）")
    return violations


def test_refresh_token_is_one_month_and_fallback_matches() -> None:
    seconds = yml_refresh_seconds(_read(APP_YML))
    assert seconds == ONE_MONTH_SECONDS, (
        f"application.yml: jwt.refresh-token-expiration = {seconds!r}"
        f"（期望 {ONE_MONTH_SECONDS} = 30 天；用户 2026-10-18 裁定「登录态改为 1 个月」）"
    )
    fallback = provider_default_seconds(_read(PROVIDER))
    assert fallback == ONE_MONTH_SECONDS, (
        f"JwtTokenProvider 的 @Value 兜底 = {fallback!r}（期望 {ONE_MONTH_SECONDS}）"
        "—— 两处漂移会让缺省配置的环境静默回到 7 天"
    )


def test_cookie_ttl_has_single_source() -> None:
    violations = auth_service_violations(_read(AUTH_SERVICE))
    assert violations == [], "；".join(violations)


def test_mobile_refresh_wiring_exists() -> None:
    violations = bmini_violations(_read(BMINI_REQUEST), _read(BMINI_STORE))
    assert violations == [], "；".join(violations)


def test_guard_has_discriminative_power() -> None:
    """注入式自证：三种回归形态各自必红（注入只在内存里做）。"""
    yml_text = _read(APP_YML)
    assert yml_refresh_seconds(yml_text) == ONE_MONTH_SECONDS, "自证前提：当前树 yml 应已是 30 天"
    reverted_yml = yml_text.replace(
        f"refresh-token-expiration: {ONE_MONTH_SECONDS}",
        "refresh-token-expiration: 604800",
    )
    assert yml_refresh_seconds(reverted_yml) == 604800, "注入未生效（yml 文本形态变了）"

    provider_text = _read(PROVIDER)
    reverted_provider = provider_text.replace(
        f"${{jwt.refresh-token-expiration:{ONE_MONTH_SECONDS}}}",
        "${jwt.refresh-token-expiration:604800}",
    )
    assert provider_default_seconds(reverted_provider) == 604800, "注入未生效（@Value 文本形态变了）"

    auth_text = _read(AUTH_SERVICE)
    assert auth_service_violations(auth_text) == [], "自证前提：当前树 AuthService 应是单源"
    with_constant = auth_text + "\n    private static final int REFRESH_TOKEN_COOKIE_MAX_AGE = 604800;\n"
    assert auth_service_violations(with_constant), "把 7 天常量加回去 ⇒ 判据必须红（否则这条守卫是空断言）"

    request_text = _read(BMINI_REQUEST)
    store_text = _read(BMINI_STORE)
    assert bmini_violations(request_text, store_text) == [], "自证前提：当前树续期接线应齐备"
    no_refresh_call = request_text.replace("await refreshAccessToken()", "null", 1)
    assert bmini_violations(no_refresh_call, store_text), "摘掉 401 分支的续期调用 ⇒ 判据必须红"

    store_without_refresh = store_text.replace("await refreshAccessToken()", "null", 1)
    assert bmini_violations(request_text, store_without_refresh), "摘掉 store 的续期调用 ⇒ 判据必须红"
