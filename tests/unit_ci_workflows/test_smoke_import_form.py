# case_ids: MC-343
"""冒烟面的**导入形态**判据（issue #9062 现场，2026-11-23）。

## 病根（实测读数，不是推演）

`tests/smoke/test_config_production_urls.py`（由 #8993 于 2026-11-22 引入）写的是**绝对导入**：

    from tests.smoke.config import get_config

而冒烟腿的执行方式是 `cd tests/smoke && pytest -m "p0" …`
（`.github/workflows/smoke-test.yml` 的 `P0 Smoke Test` 步），且仓库里 **`tests/__init__.py` 不存在**
（只有 `tests/smoke/__init__.py`）⇒ `tests` 不是包 ⇒ 采集阶段直接中断：

    E   ModuleNotFoundError: No module named 'tests'
    !!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!

⇒ `Post-Deploy Smoke Test` exit 2 ⇒ 整条 `Build and Deploy admin-api` 判红
（实测 run 45120925452：部署本体已成功、`JWT_KEY_SAME_SOURCE=OK`，红在冒烟这层）。

**为什么 24 小时没被发现**：上游的 JWT 同源断言红（#9051 / #9059）让这一步根本没跑到 ——
「上游红掩盖下游红」。所以本判据是**类级**的：不许这一类绝对导入再进来，而不是只改那一行。

## 判据

1. `tests/smoke/**/*.py` 里出现 `^(from|import) tests\\.` ⇒ 判红（具名 `文件:行: 原文`）。
2. 绿证（人工/CI 复核用，不在本判据里跑子进程）：`cd tests/smoke && python3 -m pytest -m p0 --collect-only -q`
   必须 `0 error`。
3. 红证（注入式）：把被测文件改回绝对导入 ⇒ 判据 1 必红；改回相对导入 ⇒ 绿。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SMOKE_DIR = REPO_ROOT / "tests" / "smoke"

# 只认「命令位置」的绝对导入：行首可选缩进 + from/import + tests.
_ABSOLUTE_TESTS_IMPORT = re.compile(r"^\s*(?:from|import)\s+tests\.", re.MULTILINE)


def _smoke_py_files() -> list[Path]:
    assert SMOKE_DIR.is_dir(), f"冒烟面目录不存在：{SMOKE_DIR}（判据失效，不得静默通过）"
    return sorted(p for p in SMOKE_DIR.rglob("*.py") if p.is_file())


def _offenders() -> list[str]:
    found: list[str] = []
    for path in _smoke_py_files():
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _ABSOLUTE_TESTS_IMPORT.match(line):
                found.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")
    return found


def test_no_absolute_tests_import_in_smoke_face() -> None:
    """冒烟面不许出现 `from tests.…` / `import tests.…`（该面是按目录当根跑的）。"""
    bad = _offenders()
    assert bad == [], (
        "冒烟面出现**绝对导入 tests 包**的写法 —— 冒烟腿是 `cd tests/smoke` 跑的，"
        "而 `tests/__init__.py` 不存在 ⇒ 采集阶段会 `ModuleNotFoundError: No module named 'tests'`，"
        "整条部署腿因此判红（issue #9062）。改成相对导入（如 `from .config import get_config`）：\n"
        + "\n".join(bad)
    )


def test_the_scanner_actually_sees_the_face() -> None:
    """判别力自证：扫描面非空，且至少能看到那个被修的文件（否则「绿」是零命中假绿）。"""
    files = [p.relative_to(REPO_ROOT).as_posix() for p in _smoke_py_files()]
    assert len(files) >= 5, f"冒烟面文件数异常（{len(files)} 个）⇒ 扫描面可能选错：{files[:5]}"
    assert "tests/smoke/test_config_production_urls.py" in files, (
        "被修的那个文件不在扫描面里 ⇒ 本判据管不到它（issue #9062 的现场文件）"
    )
