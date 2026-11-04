# case_ids: MC-012
r"""`deploy/swas/nginx.conf`：**所有承载可执行产物的静态面**必须发 `Cache-Control: no-cache`。

## 为什么要一条常驻判据（issue #8355）

真机读数（2026-11-01）：`worker-h5` 发布成功（publish run 成功、服务端 `curl` 已是新模块）后，
手持机仍在跑**旧**的 `shipment-app.mjs` —— `performance.getEntriesByType('resource')` 里没有新加的
`flex-gap.mjs`，加 `?nocache=` 重开页面也没用（模块按自身 URL 的缓存条目复用）。

原因：静态面只有 `ETag` / `Last-Modified`，**没有** `Cache-Control` ⇒ 浏览器按启发式缓存
（通常取 age 的 ~10%）。对车间里**长期常开**的手持机，这个窗口不可控 ⇒「修好了但工人看到旧的」。

## 为什么判据是**一组** location，且要有「未覆盖即红」的元判据（issue #8639 / #8643）

两次同类现场，都是「修在了走不到的块上 / 只修了一个前缀」：

1. **#8639**：`/b/`（手机与手持标签机的主入口）漏了 no-cache —— #8355 只修了 `location /`；
2. **#8643**：`/w/` 本身也有 no-cache 的空缺，而且 #8355 那行虽然加在 `location /` 里、
   注释还写着「本 location 同时承载 `/w/`」—— **nginx 前缀匹配取最长者**，`/w/…` 命中
   `location /w/` 后**永远走不到** `location /` 的 `add_header` ⇒ 判据跟着写就全绿、现场照旧。

⇒ 判据的口径是「**静态 location 一律要 no-cache**」，并且用
`test_no_static_location_is_uncovered` 把「新加了一个静态 location 却忘了登记」变成红
（只写一张表不够 —— 表本身会漏，这正是 #8643 的形态）。

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
#: 🔴 前缀变了 / 新增静态面 ⇒ 改这张表（`test_no_static_location_is_uncovered` 会逼你改）。
STATIC_LOCATIONS = (
    ("/", "try_files $uri $uri/ /index.html"),
    ("/w/", "try_files $uri $uri/ /w/index.html"),
    ("/b/", "try_files $uri $uri/ /b/index.html"),
)


def _iter_location_blocks() -> list[tuple[str, str]]:
    """全部 `location <prefix> { … }` 块 ⇒ [(prefix, block)]（块含花括号）。"""
    text = CONF.read_text(encoding="utf-8")
    out: list[tuple[str, str]] = []
    for m in re.finditer(r"^\s*location\s+(\S+)\s*\{", text, re.MULTILINE):
        prefix = m.group(1)
        start = m.end() - 1
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    out.append((prefix, text[start : i + 1]))
                    break
    return out


def _location_block(prefix: str, fallback: str) -> str:
    """取 `location <prefix> { … }` 块（按 fallback 认领 —— 配置里有**两个** `location /`）。"""
    for found, block in _iter_location_blocks():
        if found == prefix and fallback in block:
            return block
    raise AssertionError(f"找不到 location {prefix}（配置结构变了 ⇒ 本判据要跟着改）")


@pytest.mark.parametrize(("prefix", "fallback"), STATIC_LOCATIONS)
def test_static_location_serves_no_cache(prefix: str, fallback: str) -> None:
    block = _location_block(prefix, fallback)
    assert re.search(r'add_header\s+Cache-Control\s+"no-cache"\s+always\s*;', block), (
        f"静态 location {prefix} 必须发 Cache-Control: no-cache —— "
        "否则发布后手机 / 手持机会按启发式缓存继续跑旧产物（issue #8355 / #8639 / #8643）"
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


def test_no_static_location_is_uncovered() -> None:
    """元判据：**每个**带 `index.html` 兜底的 location 都必须在 `STATIC_LOCATIONS` 里。

    这条就是 #8643 的固化：当时的缺口不是「表里那一行写错」，而是「`/w/` 根本没人登记」
    —— 加静态面时忘了同步判据，判据再绿也没意义。新增静态 location ⇒ 本条必红，逼你决定它要不要 no-cache。
    """
    covered = {prefix for prefix, _ in STATIC_LOCATIONS}
    uncovered = [
        prefix
        for prefix, block in _iter_location_blocks()
        if re.search(r"try_files\s+[^;]*index\.html", block) and prefix not in covered
    ]
    assert not uncovered, (
        f"这些静态 location 带 index.html 兜底却不在 STATIC_LOCATIONS 里：{uncovered} —— "
        "请登记（并确认它的 no-cache 口径），否则又是一次「判据全绿、现场跑旧产物」"
    )
