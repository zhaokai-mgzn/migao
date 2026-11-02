# case_ids: MC-012
r"""`deploy/swas/nginx.conf`：静态面（`/w/` 所在的 `location /`）必须发 `Cache-Control: no-cache`。

## 为什么要一条常驻判据（issue #8355）

真机读数（2026-11-01）：`worker-h5` 发布成功（publish run 成功、服务端 `curl` 已是新模块）后，
手持机仍在跑**旧**的 `shipment-app.mjs` —— `performance.getEntriesByType('resource')` 里没有新加的
`flex-gap.mjs`，加 `?nocache=` 重开页面也没用（模块按自身 URL 的缓存条目复用）。

原因：静态面只有 `ETag` / `Last-Modified`，**没有** `Cache-Control` ⇒ 浏览器按启发式缓存
（通常取 age 的 ~10%）。对车间里**长期常开**的手持机，这个窗口不可控 ⇒「修好了但工人看到旧的」。

判据（删掉那行 / 把它挪出 `location /` ⇒ 红）：静态根 location 里必须有
`add_header Cache-Control "no-cache" always;`（**no-cache**，不是 no-store —— 要保留 304 复验）。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONF = ROOT / "deploy" / "swas" / "nginx.conf"


def _static_root_location() -> str:
    """承载静态站点的 `location / { … }` 块。

    ⚠️ 配置里有**两个** `location /`：:80 那个只 `return 301`（不是本判据的对象），
    这里按块内容认领 —— 静态站点那个才有 SPA fallback（`try_files $uri $uri/ /index.html`）。
    """
    text = CONF.read_text(encoding="utf-8")
    for m in re.finditer(r"^\s*location\s+/\s*\{", text, re.MULTILINE):
        depth = 0
        start = m.end() - 1
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    block = text[start : i + 1]
                    if "try_files $uri $uri/ /index.html" in block:
                        return block
                    break
    raise AssertionError("找不到承载静态站点的 location /（配置结构变了 ⇒ 本判据要跟着改）")


def test_static_root_serves_no_cache() -> None:
    block = _static_root_location()
    assert re.search(
        r'add_header\s+Cache-Control\s+"no-cache"\s+always\s*;', block
    ), (
        "静态根 location（承载 /w/ 工人端）必须发 Cache-Control: no-cache —— "
        "否则发布后手持机会按启发式缓存继续跑旧模块（issue #8355）"
    )
    # 只反对**指令**层面的 no-store（注释里为了解释「为什么不是 no-store」会提到这个词）
    assert 'Cache-Control "no-store"' not in block, (
        "要的是 no-cache（保留 ETag/304 复验），不是 no-store"
    )


def test_static_root_keeps_hsts_and_nosniff() -> None:
    """`add_header` 是**替换**语义：新增一条不得把同块已有的安全头挤掉。"""
    block = _static_root_location()
    assert "Strict-Transport-Security" in block
    assert "X-Content-Type-Options nosniff" in block
