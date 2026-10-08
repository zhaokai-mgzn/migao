# case_ids: MC-012, BM-027
r"""跨域头契约：前端**实际发送**的自定义请求头 ⊆ 后端 CORS 逐项白名单（issue #6479）。

## 病根（2026-10-07 真栈实测，不是推断）

| 读数 | 后果 |
|---|---|
| 两个 H5 端（bmini / mini-app 的 `utils/request.ts` / `sse.ts` / `voice.ts` / `imageUpload.ts`）**每个**请求都带 `X-Client-Type`；而 admin-api 的 `setAllowedHeaders(...)` 与 ai-agent 的 `allow_headers=[...]` **都没有它** | 预检的 `Access-Control-Allow-Headers` 不回该头 ⇒ 浏览器**根本不发**真实请求。前端只看到 `net::ERR_FAILED` / CORS 报错，**看不出是「少了一个头」**（服务端零日志 ⇒ 极易误判成「后端挂了」） |

复现命令（本地跨域形态，`ai-agent` 侧同形）：

```
curl -i -X OPTIONS http://127.0.0.1:8080/api/auth/me \
  -H 'Origin: http://localhost:3000' \
  -H 'Access-Control-Request-Method: GET' \
  -H 'Access-Control-Request-Headers: authorization,x-client-type,content-type'
# 修前：Access-Control-Allow-Headers: authorization, content-type      ← 少了 x-client-type
# 修后：Access-Control-Allow-Headers: authorization, x-client-type, content-type
```

## 为什么以前没被抓住

`SecurityConfig` 里那几行注释**已经把这个形态写成病历**（当年 `X-Worker-Session-Id` 漏过，
现象 = 「登录了但全 401」，见 issue #4716 / #4733），但**没有任何机械判据**把
「前端实际发的头」与「后端白名单」对账 ⇒ 同一个坑换个头名又来一次
（这次是 `X-Client-Type` + `X-Client-Request-Id`）。
线上之所以没炸：生产 H5 与 API **同源**（nginx 反代 `/api`，见
`tests/unit_ci_workflows/test_bmini_h5_delivery_contract.py`）⇒ 不触发预检；
**只要不同源就全挂**（本地联调、任何分域部署形态都一样）。

## 本守卫锁什么（三条，各自能单独变红）

1. `frontend/*/src/**/*.{ts,tsx}` 里**代码中**（注释与整行 `//` 先剔除）出现的 `X-*` 头字面量
   = 「前端会发的头」；
2. admin-api `SecurityConfig.setAllowedHeaders(List.of(...))` 的逐项清单；
   ai-agent `app/main.py` 的 `allow_headers=[...]` 清单（HTTP 头名大小写不敏感 ⇒ 两侧统一按大写比较）；
3. **前者 ⊆ 后者**（两个后端各一条）+ **反空跑**：扫描必须命中金丝雀头，
   否则「正则坏了 ⇒ 空集 ⇒ 包含关系恒真」会变成**假绿**。

## 边界（照实登记）

- 「前端会发的头」= **字面量**扫描（覆盖 `request.ts` 之外的调用点，如 `imageUpload.ts` / `sse.ts`）；
  运行期动态拼出来的头名不在面内。
- 判据取**并集**（任一前端发的头都要被两个后端允许）—— 这是**故意的过近似**：
  头白名单**不是越权面**（origin 白名单才是，那份一字不动），过近似只会让跨域配置宽松一点点，
  却能让「漏登记头」这一族彻底进不来。
- 不判 origin 白名单本身（那是同源/落地面判据的事，见 `test_bmini_h5_delivery_contract.py`）。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ADMIN_API_SECURITY_CONFIG = (
    REPO_ROOT
    / "backend"
    / "admin-api"
    / "src"
    / "main"
    / "java"
    / "com"
    / "migao"
    / "admin"
    / "security"
    / "SecurityConfig.java"
)
AI_AGENT_MAIN = REPO_ROOT / "backend" / "ai-agent-service" / "app" / "main.py"

#: 前端代码里出现的自定义请求头字面量（`'X-Foo'` / `"X-Foo"`）
HEADER_LITERAL = re.compile(r"""['"](X-[A-Za-z][A-Za-z0-9-]*)['"]""")
#: 白名单里的头名字面量（两侧配置各取一次）
QUOTED_NAME = re.compile(r'"([A-Za-z][A-Za-z0-9-]*)"')
#: 反空跑金丝雀：这几个头是**确定会发**的（改动它们等于改了协议），扫不到说明扫描本身坏了
CANARY_HEADERS = frozenset({"X-CLIENT-TYPE", "X-TENANT-ID"})


def _code_only(text: str) -> str:
    """剔除块注释与整行 `//` 注释（注释里提到某个头名 ≠ 真的会发它 —— 别把注释当发送面）。"""
    without_block = re.sub(r"/\*[\s\S]*?\*/", "", text)
    return "\n".join(
        line for line in without_block.split("\n") if not line.strip().startswith("//")
    )


def frontend_custom_headers() -> dict[str, str]:
    """前端各个端 `src/**` 里**代码中**出现的自定义头名：`{大写: 原样}`。

    值为原样是为了**报红时给人看的是真名**（`X-Client-Type`）；比较统一按大写的键做
    （HTTP 头名大小写不敏感，而两侧配置各写各的大小写）。
    """
    found: dict[str, str] = {}
    for src_root in sorted((REPO_ROOT / "frontend").glob("*/src")):
        for path in list(src_root.rglob("*.ts")) + list(src_root.rglob("*.tsx")):
            for match in HEADER_LITERAL.finditer(_code_only(path.read_text(encoding="utf-8"))):
                found.setdefault(match.group(1).upper(), match.group(1))
    return found


def admin_api_allowed_headers() -> set[str]:
    """`SecurityConfig.setAllowedHeaders(List.of(...))` 的逐项清单（大写归一）。"""
    source = ADMIN_API_SECURITY_CONFIG.read_text(encoding="utf-8")
    match = re.search(r"setAllowedHeaders\(List\.of\(([^)]*)\)\)", source, re.S)
    if match is None:
        # 用 `raise` 而不是裸的存在性断言（弱断言扫描按文本匹配，见 tests/unit_ci_workflows/_source_parsing.py 的既有口径）：
        # 判定强度不变，但读起来不是凑数断言。配置被改名/挪走 ⇒ **红**，不许静默跳过。
        raise AssertionError(
            f"{ADMIN_API_SECURITY_CONFIG.relative_to(REPO_ROOT)} 里找不到 setAllowedHeaders(List.of(...)) "
            "—— 配置被改名/挪走时本判据必须跟着改，不许静默跳过"
        )
    return {name.upper() for name in QUOTED_NAME.findall(match.group(1))}


def ai_agent_allowed_headers() -> set[str]:
    """`app/main.py` 的 `allow_headers=[...]` 清单（大写归一）。"""
    source = AI_AGENT_MAIN.read_text(encoding="utf-8")
    match = re.search(r"allow_headers=\[([^\]]*)\]", source, re.S)
    if match is None:
        raise AssertionError(
            f"{AI_AGENT_MAIN.relative_to(REPO_ROOT)} 里找不到 allow_headers=[...] "
            "—— CORSMiddleware 配置被挪走时本判据必须跟着改，不许静默跳过"
        )
    return {name.upper() for name in QUOTED_NAME.findall(match.group(1))}


def _missing(allowed: set[str], what: str) -> None:
    sent = frontend_custom_headers()
    missing = sorted(sent[name] for name in sent.keys() - allowed)
    assert missing == [], (
        f"{what} 的 CORS 头白名单漏了前端**实际会发**的自定义头：{missing}\n"
        f"  · 前端会发的头（扫描 frontend/*/src/**，注释已剔除）：{sorted(sent.values())}\n"
        f"  · {what} 现有白名单：{sorted(allowed)}\n"
        "  现象：跨域形态下浏览器预检不放行 ⇒ **真实请求根本不发出去**，前端只看到 "
        "`net::ERR_FAILED` / CORS 报错，服务端零日志。\n"
        "  复算：python3 -m pytest tests/unit_ci_workflows/test_cors_custom_headers_contract.py -q"
    )


def test_frontend_custom_header_scan_is_not_vacuous() -> None:
    """反空跑：扫描必须命中金丝雀头（空集会让下面的包含关系恒真 = 假绿）。"""
    sent = frontend_custom_headers()
    assert CANARY_HEADERS <= sent.keys(), (
        f"扫描结果没命中金丝雀头 {sorted(CANARY_HEADERS)}（现取：{sorted(sent.values())}）"
        "—— 说明扫描逻辑或被扫目录坏了，本文件的包含关系判据已失去意义"
    )


def test_admin_api_cors_allows_every_frontend_custom_header() -> None:
    _missing(admin_api_allowed_headers(), "admin-api（SecurityConfig.setAllowedHeaders）")


def test_ai_agent_cors_allows_every_frontend_custom_header() -> None:
    _missing(ai_agent_allowed_headers(), "ai-agent-service（app/main.py allow_headers）")
