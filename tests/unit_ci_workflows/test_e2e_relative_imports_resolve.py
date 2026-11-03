# case_ids: MC-149
"""`tests/e2e/**` 的**相对 import 必须解析得到**（issue #6411 的链内顺带修）。

## 病灶（现取读数，origin/main）

```
$ npx playwright test --list
Error: Cannot find module './base.page'
Require stack:
- tests/e2e/pages/auth/login.page.ts 的 import 行
- tests/e2e/specs/auth/login-sms.spec.ts 里 import LoginPage 的那一行
Listing tests:
Total: 0 tests in 0 files
```

`tests/e2e/pages/auth/login.page.ts` 里 `import { BasePage } from './base.page'` 少一层 `../`
（`base.page.ts` 在 `tests/e2e/pages/` 下）⇒ **收集期**就炸：任何 import 该 POM 的 spec
连「跑」都跑不到。而单跑别的 spec 时**看不出来**（那个 spec 不 import 它）——
这正是它能在 main 上躺着的形态，也是「判据写了但跑不到」的同族（issue #6411：本地 E2E 认证链不可用）。

## 判据（都**会红**）

- **判据 1（实例，真语料）**：`tests/e2e/**` 里**每一处**相对 import（`from './x'` / `from '../x'`）
  都必须在本仓真实文件里解析得到（含无扩展名、`.ts` / `.tsx` / `.js` / `.mjs` / `.cjs`、
  `index.*`）。修复前这里会点名 `tests/e2e/pages/auth/login.page.ts -> './base.page'`。
- **判据 2（红证 / 判别力自证）**：把同一解析器跑在一棵**造出来的**树上 —— 复刻历史形态
  （`pages/auth/login.page.ts` 引 `./base.page`，而 `base.page.ts` 在 `pages/` 下）⇒ 必须点名；
  把那一行改成 `../base.page` ⇒ 必须零问题（负控，证明解析器不是恒红）。
- **判据 3（收集期可过，接线）**：仓库层的证据是 `npx playwright test --list` 退出 0 ——
  本判据不替代它（跑 Playwright 需要 `tests/node_modules`，判据 job 不装），只判**静态可解析性**。

## 边界（照实登记）

- 只判**相对** import（绝对包名 / `@playwright/test` 不在面内）：node_modules 的解析规则不归本判据。
- 只判 `tests/e2e/**` + 三个 `tests/playwright*.config.ts` 的 `e2e/` 引用面（同一棵树）。
- 判据不执行 Playwright、不联网、不烧 token。
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
E2E_ROOT = REPO_ROOT / "tests" / "e2e"

#: node/TS 的解析顺序（够用即可；`.tsx` 本仓 e2e 不用，仍纳入以免将来假红）。
SUFFIXES = ("", ".ts", ".tsx", ".js", ".mjs", ".cjs", "/index.ts", "/index.tsx", "/index.js")

#: `from './x'` / `import './x'` / `import('./x')` —— 只吃**相对**说明符（`.` 开头）。
RELATIVE_IMPORT_RE = re.compile(r"""(?:from\s+|import\s*\(?\s*)['"](\.[^'"]*)['"]""")


def resolve_relative_import(importer: Path, specifier: str) -> bool:
    """相对 import 是否能解析到真实文件（按 node/TS 的常见后缀顺序）。"""
    base = importer.parent / specifier
    return any(Path(f"{base}{suffix}").exists() for suffix in SUFFIXES)


def unresolved_relative_imports(root: Path) -> list[tuple[str, str]]:
    """返回 `[(文件, 说明符)]`：解析不到的相对 import。`root` 可注入（红证用 tmp 树）。"""
    problems: list[tuple[str, str]] = []
    if not root.is_dir():
        return problems
    for path in sorted(root.rglob("*.ts")):
        if "node_modules" in path.parts:
            continue
        for match in RELATIVE_IMPORT_RE.finditer(path.read_text(encoding="utf-8")):
            if not resolve_relative_import(path, match.group(1)):
                problems.append((str(path.relative_to(root)), match.group(1)))
    return problems


# ── 判据 1（实例，真语料）────────────────────────────────────────────────────


def test_every_relative_import_in_the_e2e_tree_resolves() -> None:
    problems = unresolved_relative_imports(E2E_ROOT)
    assert problems == [], (
        "tests/e2e 下存在解析不到的相对 import ⇒ `npx playwright test --list` 会在**收集期**就失败"
        f"（任何 import 它的 spec 连跑都跑不到）：{problems}"
    )


# ── 判据 2（红证 / 判别力自证）───────────────────────────────────────────────


def test_guard_discriminates_the_missing_parent_segment(tmp_path: Path) -> None:
    """复刻历史形态（少一层 `../`）⇒ 必须点名；改成 `../base.page` ⇒ 零问题。"""
    pages = tmp_path / "pages"
    auth = pages / "auth"
    auth.mkdir(parents=True)
    (pages / "base.page.ts").write_text("export class BasePage {}\n", encoding="utf-8")

    broken = auth / "login.page.ts"
    broken.write_text("import { BasePage } from './base.page'\n", encoding="utf-8")
    assert unresolved_relative_imports(tmp_path) == [
        ("pages/auth/login.page.ts", "./base.page")
    ], "历史形态（少一层 ../）没有被判红 ⇒ 判据是空的"

    # 负控：同一棵树上把说明符写对 ⇒ 零问题（解析器不是恒红）
    broken.write_text("import { BasePage } from '../base.page'\n", encoding="utf-8")
    assert unresolved_relative_imports(tmp_path) == [], "正确写法被误判 ⇒ 判据会假红"


def test_resolver_accepts_the_extensionless_and_index_forms() -> None:
    """本仓现有写法（无扩展名 / 显式 `.mjs`）都必须被判为可解析（防假红）。"""
    importer = E2E_ROOT / "helpers" / "probe.ts"  # 只为取基准目录，不建文件
    assert (E2E_ROOT / "helpers" / "auth.helper.ts").exists(), "夹具前提不成立"
    assert (E2E_ROOT / "helpers" / "auth-state-freshness.mjs").exists(), "夹具前提不成立"
    for specifier in ("auth.helper", "./auth.helper", "auth-state-freshness.mjs"):
        assert resolve_relative_import(importer, specifier), f"合法写法被判不可解析：{specifier}"
    # 反面：真的不存在 ⇒ 判不可解析（解析器不是恒真）
    assert not resolve_relative_import(importer, "no-such-helper"), "不存在的说明符被判可解析"
