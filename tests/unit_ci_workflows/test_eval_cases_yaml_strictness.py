# case_ids: OR-013, CU-003, HR-003
"""用例库单一源（`cases/*.yml`）必须能被**标准 YAML** 解析（零 LLM、秒级）。

## 为什么单开这条守卫（2026-09-15 实证，本包自踩）

CI 里**没有任何环节**用标准 YAML 解析 `cases/*.yml`：

| 环节 | 用的解析器 |
|---|---|
| 生成物新鲜度校验 | `.github/render_cases.py` → `yaml_light` |
| Case Contract（`truths_ref`） | `.github/truths.py` → `yaml_light` |
| runner 的 YAML 装载路径（`--cases`） | `render_cases.load_case_dicts` → `yaml_light` |

而 `yaml_light` 比标准 YAML **宽松**：实测把 `merge_log` 的双引号标量里混进一个 ASCII `"`
（= 提前闭合标量）后，`render_cases.py` **照旧成功**（289 条 + 生成物"新鲜"），
而 `yaml.safe_load(...)` 直接 `ParserError`。
⇒ 一份**语法非法**的用例文件可以一路绿灯合入，然后在任何用真 YAML 的消费者那里炸开
（编辑器 / 第三方工具 / 本目录下用 `yaml.safe_load` 读用例的守卫），且报错点看起来与
被改的用例毫不相干 —— 典型"延迟引爆"的归因陷阱（`migao-acceptance` 的假绿/假红家族）。

## 本文件锁两条

1. **每个** `cases/*.yml` 都能被 `yaml.safe_load` 解析（fail-closed：**不留白名单** ——
   留白名单等于把"这个文件可以不合法"写进契约）；
2. 解析结果是 `{cases: [...]}` 且**非空**（防"清空文件也照样绿"这种伪通过）。

## 红证

| 断言 | 红证 |
|---|---|
| ① 真 YAML 可解析 | 在任意 `cases/*.yml` 的任意双引号标量里插一个 ASCII `"`（本次实证形态）⇒ 本文件红，而 `render_cases.py` 仍报"新鲜" |
| ② 结构非空 | 把某个 yml 的 `cases` 清成 `[]` ⇒ 红 |

（本文件不检查 yml 的**语义**：期望工具是否存在、`truths_ref` 是否可解析等由
`test_mibao_case_invariants.py` / `truths.py check` 承担。）
"""
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CASES_DIR = REPO_ROOT / ".github" / "cases"
CASE_FILES = sorted(CASES_DIR.glob("*.yml"))


def test_case_library_is_not_empty():
    """守卫的**前提**：用例库存在且被扫到（否则逐文件参数化会静默空跑）。"""
    assert CASE_FILES, f"没扫到任何 cases/*.yml（{CASES_DIR}）—— 本守卫会静默空跑"
    assert (CASES_DIR / "order.yml").exists()


@pytest.mark.parametrize("path", CASE_FILES, ids=[p.name for p in CASE_FILES])
def test_case_file_parses_with_standard_yaml(path: Path):
    """**核心守卫**：标准 YAML 必须能解析（`yaml_light` 宽松 ⇒ CI 其余环节挡不住）。"""
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:                     # pragma: no cover - 合法库不该触发
        raise AssertionError(
            f"{path.name} 不是合法 YAML（渲染器用的 yaml_light 比标准 YAML 宽松，"
            f"CI 的新鲜度/Case Contract 都不会报）：{type(e).__name__}: {str(e)[:200]}"
        ) from e
    assert isinstance(doc, dict), f"{path.name} 顶层不是映射：{type(doc).__name__}"
    cases = doc.get("cases")
    assert isinstance(cases, list) and cases, (
        f"{path.name} 的 `cases` 缺失/为空/类型不对（清空文件不得伪装成通过）：{type(cases).__name__}")
    for c in cases:
        assert isinstance(c, dict) and str(c.get("id") or "").strip(), (
            f"{path.name} 里有用例条目缺 `id`：{str(c)[:120]}")
