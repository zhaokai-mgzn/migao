"""评测**跑批策略版本**（machine-computable；verdict ledger 的键的一部分）。

## 为什么必须有它（issue #3769，用户裁定：同一件事不重复跑）

「同一 SHA 已有结论 ⇒ 不重复跑」要成立，键里必须包含**跑批策略**：判定放行口径
（`_COMPLETION_RELEASED_CLASSES`）或两次尝试的分类/指纹实现（`_classify_attempts` /
`_failure_signature`）一变，"上次那个结论"就不再等价 —— 拿它复用就是**假绿**
（`migao-acceptance` v1.2：真值与被测行为无关的复用）。

`policy_version` 由这三个对象的**源码文本**哈希而来：

* 机器可算（不需要人手工 bump —— 手工版本号迟更/漏更本身就是假绿来源）；
* 保守方向：**任何**改动（含注释）都让版本变 ⇒ 最坏结果是"多跑一次"，而不是"复用过期结论"。

## 为什么单独一个文件（而不是写在 local_runner 里）

派发侧守卫（`.github/scripts/eval_dispatch_guard.sh`）要在**不 import local_runner** 的前提下
算出同一个值（`local_runner` 模块级依赖 httpx/asyncpg，派发机上未必有）。故本模块**只用标准库**，
既可被 `local_runner` import，也可独立执行：

    python3 tests/agent_eval/eval_policy_version.py            # 打印版本
    python3 tests/agent_eval/eval_policy_version.py --path X   # 指定 runner 源文件

两者一致性由 `tests/unit_ci_workflows/test_eval_verdict_ledger.py` 钉死（同一个算法、
同一段文本 ⇒ 同一个值；漂移即红）。
"""
import ast
import hashlib
import sys
from pathlib import Path

# 参与"策略"定义的对象（改动其中任何一个 = 旧结论不再可复用）
POLICY_OBJECTS = ("_COMPLETION_RELEASED_CLASSES", "_classify_attempts", "_failure_signature")

DEFAULT_RUNNER = Path(__file__).resolve().parent / "local_runner.py"


def policy_version(runner_path=None) -> str:
    """返回跑批策略版本（16 位十六进制）。

    算法（**必须与派发侧守卫一致**）：对 `POLICY_OBJECTS` 三个对象的**源码片段**按名称升序
    拼接后取 sha256 前 16 位。用 `ast.get_source_segment`（而非 `inspect`）是为了在
    "只读源码、不执行模块"的前提下拿到稳定文本 —— 两侧用同一函数，故不会漂移。
    找不到某个对象 ⇒ 返回 `"unknown"`（派发侧据此**拒绝复用**，宁可多跑）。
    """
    path = Path(runner_path) if runner_path else DEFAULT_RUNNER
    tree = ast.parse(path.read_text(encoding="utf-8"))
    segments = {}
    for node in tree.body:
        name = None
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = node.name
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
        if name in POLICY_OBJECTS:
            seg = ast.get_source_segment(path.read_text(encoding="utf-8"), node)
            if seg:
                segments[name] = seg
    if len(segments) != len(POLICY_OBJECTS):
        return "unknown"
    blob = "".join(segments[k] for k in sorted(segments))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


if __name__ == "__main__":
    args = sys.argv[1:]
    target = None
    if "--path" in args:
        target = args[args.index("--path") + 1]
    print(policy_version(target))
