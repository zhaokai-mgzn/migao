"""CI workflow 辅助测试 conftest：共享 `EvalCase` 的跨文件污染防线（issue #4061）。

## 病灶

`tests/agent_eval/eval_cases.py`（生成物，源 = `.github/cases/**`）的 `ALL_CASES` 是
**模块级共享单例**：同进程内任何测试原地改写它（如 `x.namespaces = []`）都会污染其后
所有测试，而 **CI 判不出来** —— `pr-check.yml` 从仓库根按路径字母序收集，
`test_eval_case_asset_truth` 排在 `test_eval_namespace_isolation` **之前** ⇒
受害者先跑、投毒者后跑 ⇒ 恒绿；只有显式把投毒者排到前面才红（改前实测 1 failed）。
（形态属 `migao-acceptance` §19.1「不会红的假绿」：判据在 CI 上永不触发。）

## 两道防线（治**机制**，不是修那个点位）

1. **深拷贝句柄** `shared_eval_cases()` / `eval_cases_snapshot` fixture —— 要改造拿自己那份；
2. **常驻守卫**（本文件 `_shared_eval_cases_stay_pristine`，autouse + fail-closed）——
   每个测试跑完比对共享对象的内容指纹；变了 ⇒ 先就地恢复干净、再**判当前测试红**
   （指名道姓、不级联、不加豁免清单）。

红证与负例见 `tests/unit_ci_workflows/test_shared_eval_case_immutability.py`（喂真·原地改写 ⇒ 守卫必红）。
"""
import copy
import pickle
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
# append（**不是** insert）：只作兜底解析路径，避免遮蔽 app/ 或 site-packages 里的同名模块。
# 下面这个 `import eval_cases` 必须在**任何测试跑过之前**完成 —— 基线要钉在"无人改过"的时刻。
sys.path.append(str(REPO_ROOT / "tests" / "agent_eval"))

import eval_cases  # noqa: E402


def eval_cases_fingerprint(cases) -> bytes:
    """共享用例集合的**内容指纹**：任一字段被原地改写 ⇒ 指纹不同。"""
    return pickle.dumps(list(cases))


def shared_eval_cases() -> list:
    """共享 `ALL_CASES` 的**深拷贝** —— 用例可自由原地改写，污染不了同进程其它测试。"""
    return copy.deepcopy(list(eval_cases.ALL_CASES))


_CANONICAL = eval_cases.ALL_CASES                 # 原元组对象（元素即共享实例）
_PRISTINE = copy.deepcopy(list(_CANONICAL))       # 字段内容的基线
_BASELINE = eval_cases_fingerprint(_CANONICAL)


def restore_shared_eval_cases() -> None:
    """把共享对象**就地**还原成基线（保持对象身份 —— 持有引用的用例不受影响）。"""
    eval_cases.ALL_CASES = _CANONICAL             # 兜住"有人把模块全局换了"
    for live, pristine in zip(_CANONICAL, _PRISTINE):
        live.__dict__.clear()                     # 连测试私自加的属性一起清掉
        live.__dict__.update(copy.deepcopy(pristine.__dict__))


def guard_shared_eval_cases():
    """守卫判定**本体**（普通生成器）：setup 无事，teardown 比对指纹 + fail-closed。

    抽成生成器而不是把逻辑直接写进夹具，是为了让红证能驱动**同一份本体**
    （pytest 9 的 `@pytest.fixture` 返回 `FixtureFunctionDefinition`，直接调用会被拒）。
    """
    yield
    if eval_cases_fingerprint(eval_cases.ALL_CASES) == _BASELINE:
        return
    restore_shared_eval_cases()                   # 先恢复：只判红投毒者，不级联牵连后面的测试
    pytest.fail(
        "本测试**原地改写**了共享 `eval_cases.ALL_CASES` 对象（issue #4061）："
        "它会被同进程后续测试读到 ⇒ 产生与用例顺序相关、CI 判不出来的假红/假绿。\n"
        "取自己那份再改：`from unit_ci_workflows import conftest` → `conftest.shared_eval_cases()`，"
        "或用 `eval_cases_snapshot` fixture。\n"
        "（共享对象已恢复干净：本次判红，不牵连其它测试。）",
        pytrace=False)


@pytest.fixture(autouse=True)
def _shared_eval_cases_stay_pristine():
    """常驻守卫（L0 fail-closed）：本测试不得原地改写共享 `EvalCase`（issue #4061）。"""
    yield from guard_shared_eval_cases()


@pytest.fixture
def eval_cases_snapshot():
    """共享用例集合的深拷贝（夹具形态，供需要改写的测试使用）。"""
    return shared_eval_cases()