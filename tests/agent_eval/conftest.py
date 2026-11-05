"""`tests/agent_eval` 的生成物前置：产物出库（issue #8167 P1-1）。

## 为什么这里必须有一条命令

`tests/agent_eval/eval_cases/`（按域分包）与 `docs/testing/mibao-verification-cases.md`
都能 **100%** 从 `.github/cases/**` 重建 ⇒ **不入库**（`.gitignore` 覆盖）。
而本目录的模块在 **import 期**就要用它（`local_runner.py` 的
`from eval_cases import ALL_CASES, …`，`eval_fixture_case_contract.py` 的目录读取）
⇒ 干净检出里没有它，pytest **收集阶段**就会炸。

⇒ 在收集之前跑**一条**生成命令（与 CI / `verify-all.sh` / `tests/unit_ci_workflows/conftest.py`
**逐字相同**）。`check=True`：生成失败 = 收集阶段抛错 = **红**。

🔴 不许改成 `if missing: pytest.skip(...)` / `return` —— 那正是「没跑长得像通过」。
判据：`tests/unit_ci_workflows/test_generated_artifacts_clean_checkout.py`（干净检出能跑 +
把这条命令删掉/改名 ⇒ 同一棵树变红）。

# case_ids: MC-210
"""
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

subprocess.run(
    [sys.executable, str(REPO_ROOT / "scripts" / "generated_artifacts_freshness.py"), "--write"],
    check=True, cwd=str(REPO_ROOT),
)
