# case_ids: MC-012, AU-014
r"""扫码即登录的**公开面边界**（issue #7825）—— 类级元守卫。

## 为什么要有这条判据（不是纸上规范）

本单新增了**一个公开端点**（`POST /api/auth/qr/exchange`）：它凭一张 120 秒、单次有效的票据
**换出一份完整会话**。这类端点最容易出现的两类坏，都是「没有任何东西会红」的：

1. **放行名单漏登记** ⇒ 手机端兑换永远 401，功能静默失效（现象只是「扫码后还是要登录」，
   与本次要治的原症状**一模一样**）；
2. **把签发端点也放行** ⇒ 任何人可以匿名替任意用户签发持有凭证（越权面，而不是功能坏）。
   签发必须带有效商家会话 —— 它等价于「替当前登录用户发一张 120 秒的持有凭证」。

同族还有两条更难发现的：
3. 票据类型与 access / refresh **撞串** ⇒ 票据可当会话用（或反之），单次有效/短窗口全部失效；
4. `JwtAuthenticationFilter` 若不再区分类型 ⇒ 票据直接变成 access token。

## 判据（每条都能单独变红）

- Q1 放行名单**有** `/api/auth/qr/exchange`；
- Q2 放行名单**没有** `/api/auth/qr/ticket`（在 `SecurityConfig` 全文里不出现）；
- Q3 `AuthController` 两个端点都在，且 **ticket 方法体不读 `@RequestBody`**（不接受「替别人签发」的参数）；
- Q4 `JwtTokenProvider` 三种 token 类型取值互不相同；
- Q5 `JwtAuthenticationFilter` 仍以 `isAccessToken` 为准（票据过不了鉴权）。

## 边界（照实登记）

- 判据读的是**源码文本/结构**，不是运行结果：行为面（兑换一次成功、二次 401、过期 401、
  access 当票据 401、fail-closed 503）由 `backend/admin-api/src/test/java/com/migao/admin/service/QrLoginTicketServiceTest.java`
  与 `backend/admin-api/src/test/java/com/migao/admin/controller/AuthControllerTest.java` 承担。
- 它**不**校验票据 TTL 的具体秒数（那是配置真值，由 `test_refresh_token_lifetime.py` 的同族判据守着
  `jwt.*` 配置面）；这里只钉「公开面」这一层。
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SECURITY_CONFIG = REPO_ROOT / "backend/admin-api/src/main/java/com/migao/admin/security/SecurityConfig.java"
CONTROLLER = REPO_ROOT / "backend/admin-api/src/main/java/com/migao/admin/controller/AuthController.java"
TOKEN_PROVIDER = REPO_ROOT / "backend/admin-api/src/main/java/com/migao/admin/security/JwtTokenProvider.java"
JWT_FILTER = REPO_ROOT / "backend/admin-api/src/main/java/com/migao/admin/security/JwtAuthenticationFilter.java"

EXCHANGE = "/api/auth/qr/exchange"
TICKET = "/api/auth/qr/ticket"
#: 控制器用的是**类内相对路径**（类上 `@RequestMapping("/api/auth")`）
EXCHANGE_MAPPING = '@PostMapping("/qr/exchange")'
TICKET_MAPPING = '@PostMapping("/qr/ticket")' 


def _read(path: Path) -> str:
    assert path.exists(), f"判据对象不存在: {path.relative_to(REPO_ROOT)}"
    return path.read_text(encoding="utf-8")


def test_exchange_is_public_but_ticket_is_not() -> None:
    """Q1 + Q2：兑换公开、签发必须已登录（两条都单独会红）。"""
    config = _read(SECURITY_CONFIG)

    assert f'"{EXCHANGE}"' in config, (
        f"放行名单缺少 {EXCHANGE} ⇒ 手机端兑换恒 401（症状与「扫码后还要登录」一模一样）"
    )
    assert f'"{TICKET}"' not in config, (
        f"{TICKET} 不得进放行名单：签发 = 替当前登录用户发一张 120 秒持有凭证"
        "（匿名签发 = 越权面）"
    )


def test_ticket_endpoint_takes_no_foreign_identity() -> None:
    """Q3：两个端点都在，且签发端点不读 body（不接受「替别人签发」）。"""
    controller = _read(CONTROLLER)

    ticket_block = _endpoint_block(controller, TICKET_MAPPING)
    exchange_block = _endpoint_block(controller, EXCHANGE_MAPPING)

    assert "@RequestBody" not in ticket_block, (
        "签发端点不得读请求体：它只按**当前会话**的用户/租户签发（读 body 就是「替别人签发」的口子）"
    )
    assert "@RequestBody" in exchange_block, "兑换端点必须读票据（body {ticket}）"


def _endpoint_block(source: str, marker: str) -> str:
    start = source.index(marker)
    nxt = source.find("@PostMapping", start + len(marker))
    return source[start:] if nxt == -1 else source[start:nxt]


def test_token_types_are_distinct() -> None:
    """Q4：access / refresh / qr_login 三种类型取值互不相同。"""
    provider = _read(TOKEN_PROVIDER)
    values = {}
    for name in ("TOKEN_TYPE_ACCESS", "TOKEN_TYPE_REFRESH", "TOKEN_TYPE_QR_LOGIN"):
        match = re.search(rf'{name}\s*=\s*"([^"]+)"', provider)
        assert match, f"JwtTokenProvider 里找不到 {name} 的字面量取值"
        values[name] = match.group(1)

    assert len(set(values.values())) == 3, f"三种 token 类型必须互不相同，实际 = {values}"


def test_auth_filter_still_requires_access_token() -> None:
    """Q5：鉴权过滤器只认 access token（票据不能当会话用）。"""
    filter_source = _read(JWT_FILTER)
    assert "isAccessToken" in filter_source, (
        "JwtAuthenticationFilter 不再以 isAccessToken 为准 ⇒ 二维码票据可能被当成 access token 使用"
    )
