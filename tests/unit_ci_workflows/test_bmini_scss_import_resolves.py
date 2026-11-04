# case_ids: MC-202
"""类级判据：bmini 的**每一条** SCSS `@use` / `@import` 相对路径都必须解析到仓里真实文件。

## 为什么要有这条（实测，2026-11-04）

`frontend/bmini-app/src/components/WorkerBackLink.scss` 里写了
`@use '../../styles/variables.scss'` —— 而该文件在 `src/components/`，
`../../` 解析到 `frontend/bmini-app/styles/…`（**不存在**）⇒ `sass-loader`
报 `ModuleBuildError: Can't find stylesheet to import`，
红掉 `bmini-app build (h5 + weapp)` 与 `bmini H5 tabBar geometry (e2e)` 两条腿。

**这一条最容易犯**：同目录族的 `src/components/cards/OrderCard.scss` 写
`../../styles/variables.scss` 是**对的**（它在 `cards/` 多一层）——
照抄兄弟文件就会多退一级。而 TypeScript 的 import 由 tsc 抓，Sass 的相对路径
在**构建期**才被解析 ⇒ 静态判据缺位时只能靠一轮 CI 发现。

判据（会红）：任何 `.scss` 的 `@use` / `@import` 目标（跳过 `sass:` 内置与 `~` 包名）
在 `(文件所在目录 / 目标)` 下**不存在** ⇒ 红并具名给出文件与目标。
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
BMINI_SRC = ROOT / "frontend" / "bmini-app" / "src"

_AT = re.compile(r"^\s*@(use|import)\s+(?:url\()?['\"]([^'\"]+)['\"]")


def _iter_targets():
    for f in sorted(BMINI_SRC.rglob("*.scss")):
        for line in f.read_text(encoding="utf-8").splitlines():
            m = _AT.match(line)
            if not m:
                continue
            target = m.group(2)
            if target.startswith(("sass:", "~")):
                continue
            yield f, target


def test_every_bmini_scss_import_resolves_to_a_real_file() -> None:
    bad: list[str] = []
    seen = 0
    for f, target in _iter_targets():
        seen += 1
        resolved = (f.parent / target).resolve()
        if not resolved.exists():
            bad.append(f"{f.relative_to(ROOT)}: {target} ⇒ 解析到不存在的 {resolved}")
    # 判据自己不能空转（扫不到任何 @use ⇒ 这条守着一段不存在的语料）
    if seen == 0:
        bad.append("扫到的 @use/@import 条数为 0 ⇒ 判据失明（bmini 的 SCSS 一定有 @use）")
    assert bad == [], "bmini SCSS 的 @use/@import 有解析不到的目标：\n" + "\n".join(f"  · {b}" for b in bad)
