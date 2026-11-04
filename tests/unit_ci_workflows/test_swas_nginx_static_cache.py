# case_ids: MC-012
r"""`deploy/swas/nginx.conf`：**所有承载可执行产物的静态面**必须发 `Cache-Control: no-cache`。

## 为什么要一条常驻判据（issue #8355）

真机读数（2026-11-01）：`worker-h5` 发布成功（publish run 成功、服务端 `curl` 已是新模块）后，
手持机仍在跑**旧**的 `shipment-app.mjs` —— `performance.getEntriesByType('resource')` 里没有新加的
`flex-gap.mjs`，加 `?nocache=` 重开页面也没用（模块按自身 URL 的缓存条目复用）。

原因：静态面只有 `ETag` / `Last-Modified`，**没有** `Cache-Control` ⇒ 浏览器按启发式缓存
（通常取 age 的 ~10%）。对车间里**长期常开**的手持机，这个窗口不可控 ⇒「修好了但工人看到旧的」。

## 为什么判据是**一组** location（issue #8639）

#8355 只修了 `location /`（承载 `/w/`），**漏了 `location /b/`** —— 而 `/b/` 才是手机 / 手持标签机的
主入口（APK 的 WebView 直接加载 `https://app.migaozn.com/b/#/pages/worker/home/index`）。实测
2026-11-04：`/b/chunk/393.js` 在服务端已是新版（`待出库单` 在、`发货标签` 不在），标签机却仍显示旧菜单
⇒ **同一个坑、同一类现场**。所以判据的口径写成「**静态 location 一律要 no-cache**」，
而不是「`location /` 要 no-cache」—— 后者正是漏掉 `/b/` 的那种写法。

判据（删掉任一行 / 把它挪出对应 location ⇒ 红）：:data:`STATIC_LOCATIONS` 里每个块都必须有
`add_header Cache-Control "no-cache" always;`（**no-cache**，不是 no-store —— 要保留 304 复验）。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CONF = ROOT / "deploy" / "swas" / "nginx.conf"

#: 承载可执行产物的静态 location —— (前缀, 该块必须有的 SPA fallback)。
#: fallback 用来**认领正确的那个块**（配置里有**两个** `location /`，:80 那个只 `return 301`）。
#: 🔴 新增静态面 ⇒ 在这里加一行，判据自动覆盖（这就是「类级固化」的落点，issue #8639）。
STATIC_LOCATIONS = (
    ("/", "try_files $uri $uri/ /index.html"),
    ("/b/", "try_files $uri $uri/ /b/index.html"),
)


def _location_block(prefix: str, fallback: str) -> str:
    """取 `location <prefix> { … }` 块（含花括号，块内文本原样返回）。"""
    text = CONF.read_text(encoding="utf-8")
    pattern = r"^\s*location\s+" + re.escape(prefix) + r"\s*\{"
    for m in re.finditer(pattern, text, re.MULTILINE):
        depth = 0
        start = m.end() - 1
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    block = text[start : i + 1]
                    if fallback in block:
                        return block
                    break
    raise AssertionError(f"找不到 location {prefix}（配置结构变了 ⇒ 本判据要跟着改）")


@pytest.mark.parametrize(("prefix", "fallback"), STATIC_LOCATIONS)
def test_static_location_serves_no_cache(prefix: str, fallback: str) -> None:
    block = _location_block(prefix, fallback)
    assert re.search(r'add_header\s+Cache-Control\s+"no-cache"\s+always\s*;', block), (
        f"静态 location {prefix} 必须发 Cache-Control: no-cache —— "
        "否则发布后手机 / 手持机会按启发式缓存继续跑旧产物（issue #8355 / #8639）"
    )
    # 只反对**指令**层面的 no-store（注释里为了解释「为什么不是 no-store」会提到这个词）
    assert 'Cache-Control "no-store"' not in block, (
        "要的是 no-cache（保留 ETag/304 复验），不是 no-store"
    )


@pytest.mark.parametrize(("prefix", "fallback"), STATIC_LOCATIONS)
def test_static_location_keeps_hsts_and_nosniff(prefix: str, fallback: str) -> None:
    """`add_header` 是**替换**语义：新增一条不得把同块已有的安全头挤掉。"""
    block = _location_block(prefix, fallback)
    assert "Strict-Transport-Security" in block
    assert "X-Content-Type-Options nosniff" in block
