# case_ids: MC-360
"""贵腿必须给「按次下载」的东西上暖缓存（issue #9120 成本追因）。

## 病

三条腿的耗时大头**不是判据**，而是每次重下的依赖：

| 腿 | 每次要下载的东西 | 实测 |
|---|---|---|
| `E2E quality gate` | `tests` + `frontend/admin-web` 两份 `npm ci` | 合计 ~56s（其中 admin-web **55s**） |
| `E2E quality gate` | Playwright chromium | 未缓存时每次下载 |
| `Secret Scan (gitleaks)` | gitleaks Release 二进制（**版本钉死** 8.30.1） | 每 PR 一次 curl + 解包 |

## 判据（三条，纯静态、现取 YAML）

1. e2e 的 `setup-node` 必须 `cache: npm`，且 `cache-dependency-path` **覆盖两份 lockfile**；
2. e2e 必须缓存 Playwright 浏览器（`actions/cache` + `path: ~/.cache/ms-playwright`）；
3. gitleaks 二进制必须缓存，且缓存键**钉版本**（8.30.1）；下载必须**只在未命中时**发生。
"""

from __future__ import annotations

import pathlib
import re

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pr-check.yml"


def _jobs() -> dict:
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return doc.get("jobs") or {}


def _steps(job: str) -> list[dict]:
    steps = _jobs()[job].get("steps") or []
    assert steps, f"{job} 没有 steps（约束类判据必须与被约束对象对齐）"
    return steps


def _step_named(job: str, name: str) -> dict:
    for s in _steps(job):
        if s.get("name") == name:
            return s
    raise AssertionError(f"{job} 里找不到步骤 `{name}`")


def test_e2e_npm_cache_covers_both_lockfiles():
    step = _step_named("e2e-quality-gate", "Setup Node.js")
    with_ = step.get("with") or {}
    assert with_.get("cache") == "npm", (
        "e2e 腿的 setup-node 没开 `cache: npm` ⇒ 两次 `npm ci`（实测合计 ~56s，admin-web 55s）每次全量重装"
    )
    paths = str(with_.get("cache-dependency-path") or "")
    for lock in ("tests/package-lock.json", "frontend/admin-web/package-lock.json"):
        assert lock in paths, f"`cache-dependency-path` 没覆盖 `{lock}` ⇒ 该目录的 npm 缓存不会命中"


def test_e2e_caches_playwright_browsers():
    paths = [str((s.get("with") or {}).get("path") or "") for s in _steps("e2e-quality-gate")]
    assert any("ms-playwright" in p for p in paths), (
        "e2e 腿没有缓存 Playwright 浏览器（`~/.cache/ms-playwright`）⇒ 缓存未命中时每次重下 chromium"
    )


def test_gitleaks_binary_is_cached_and_keyed_by_version():
    steps = _steps("gitleaks-scan")
    cache = [s for s in steps if "gitleaks" in str((s.get("with") or {}).get("path") or "")]
    assert cache, "gitleaks 腿没有缓存二进制 ⇒ 每 PR 一次 GitHub Release 下载"
    key = str((cache[0].get("with") or {}).get("key") or "")
    assert "8.30.1" in key, f"缓存键没钉版本（实得 {key!r}）⇒ 版本升级后仍命中旧二进制 = 假绿"

    body = "\n".join(str(s.get("run") or "") for s in steps)
    assert re.search(r"if \[ ! -x \./gitleaks \]", body), (
        "下载没有「未命中才下」的守卫（`if [ ! -x ./gitleaks ]`）⇒ 缓存在也照下，缓存等于没上"
    )
