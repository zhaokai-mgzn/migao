# case_ids: PR-013
"""运行期 prompt 里**不得出现测试代码痕迹**（issue #8300 自测发现）。

## 为什么（真发现，不是假想）

`grep -n "tests/\\|test_[a-z_]+\\.py\\|Test[A-Z]" prompts/*.md` 在 origin/main 上命中一处：

原句（改动前，见 PR 的 diff）：`**不落库、不提交**（\`backend/ai-agent-service/tests/…\` 的
`TestNoWriteBoundary` 钉住识别内核不 import 任何写入缝）` —— 就写在 `prompts/product.md` 的
「图片识别」小节里，把测试文件路径与测试类名带进了运行期提示。

这是**给模型看的系统提示**：测试文件路径与测试类名对模型没有任何行为价值，只会：
① 白占 prompt 预算（每轮都要付）；② 泄漏内部实现（测试布局）给用户可见的推理链；
③ 误导 —— 模型可能把「有测试钉住」理解成「这个能力被限制得更多」。

## 判据

扫描 `app/graph/skills/references/` 下**所有** prompt / examples 文件（`.md`），逐文件断言不含：
- `tests/` 路径片段；
- `test_*.py` 文件名；
- `Test[A-Z][A-Za-z]+` 测试类名。

红证：把 `product.md` 的原文改回去 ⇒ 本条红（已实跑）。
边界：本判据只管 **prompt 文本**；测试文件自己引用测试文件当然不算（不在扫描集里）。
"""
from pathlib import Path

import pytest

REFS = (Path(__file__).resolve().parents[1] / "app" / "graph" / "skills" / "references")
PROMPT_FILES = sorted(str(p) for p in REFS.rglob("*.md"))


def _violations(path: str) -> list:
    text = Path(path).read_text(encoding="utf-8")
    hits = []
    for marker in ("tests/", "test_", "Test"):
        for i, line in enumerate(text.splitlines(), 1):
            if marker == "tests/" and "tests/" in line:
                hits.append((i, marker, line.strip()[:120]))
            elif marker == "test_" and ".py" in line and "test_" in line:
                hits.append((i, marker, line.strip()[:120]))
            elif marker == "Test" and _has_test_class(line):
                hits.append((i, marker, line.strip()[:120]))
    return hits


def _has_test_class(line: str) -> bool:
    import re
    return bool(re.search(r"\bTest[A-Z][A-Za-z]+\b", line))


@pytest.mark.parametrize("path", PROMPT_FILES)
def test_prompt_files_carry_no_test_artifacts(path):
    """运行期 prompt 不得引用测试文件 / 测试类（模型看不到它们的任何价值）。"""
    hits = _violations(path)
    assert not hits, (
        f"{Path(path).name}: 运行期 prompt 里出现测试痕迹 {hits[:3]} —— "
        f"测试路径/类名对模型无行为价值，只会白占预算并泄漏内部结构")


def test_scan_surface_is_not_vacuous():
    """防恒真：扫描面必须真的覆盖 prompt 文件（空集 ⇒ 判据恒绿）。"""
    assert len(PROMPT_FILES) >= 10, f"扫描面过小（{len(PROMPT_FILES)} 个 .md）—— 判据退化成空断言"
    names = {Path(p).name for p in PROMPT_FILES}
    assert "product.md" in names, "扫描面缺 product.md（#8300 的现场就在这个文件）"
