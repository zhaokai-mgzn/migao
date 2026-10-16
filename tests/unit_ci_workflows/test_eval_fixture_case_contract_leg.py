# case_ids: FN-001, OR-001, OR-002, PR-001, PR-024
r"""把评测夹具判据（issue #7043）**并进这条腿的收集面**（issue #7048 · P2）。

## 治的形态（现取读数，不是推断）

`tests/agent_eval/test_eval_fixture_case_contract.py`（类级元守卫：用例的非空断言 ⇄ 夹具真被提供）
已在 main 上，但 CI 的 `ci workflow helper unit tests` 腿**只跑 `tests/unit_ci_workflows`**
⇒ 该判据**不进 CI**，不构成门禁（#7043 的「未固化项 #1」，逐字登记在那个模块的 docstring 第 4 条）。

## 为什么落成**这一个文件**，而不是改 argv / 加配置 / 把判据搬走

`.github/workflows/pr-check.yml` 在该腿上方**逐字**写着两条既有契约：

1. 「**pytest 命令行一字不改**」——保住「CI ⇄ 本地 argv 逐字相同」（判据 =
   `tests/unit_ci_workflows/test_ci_helper_leg.py`）；
2. 「**全量命令只许出现一次**」（判据 = `tests/unit_ci_workflows/test_ci_execution_scope.py`）。

⇒ **往 argv 里塞路径是双重违约**（同时打破上面两条）。而实测过：pytest 的
`testpaths` 在**命令行给了路径**时被**整个忽略**（本机读数：`testpaths = tests/agent_eval` +
`pytest tests/unit_ci_workflows` ⇒ **7400** collected，与不加配置逐值相同；只有 `addopts` 能追加，
而那是**往这条腿的 argv 上贴东西**，正是契约 1 禁的事）。

⇒ 于是**收集面**这件事在本仓只有两个可落点：**argv 本身**（禁）或**判据目录**（= 收集面的定义处）。
本文件走后者：把那份套件**并进 `tests/unit_ci_workflows`** —— argv 一字不改、全量命令仍只出现一次、
`conftest.py` / `helper_leg_shape_ledger.json` / `ci_execution_scope_ledger.json` 三个台账
**一格都不用动**（收集面的**成员集合**没变，只是这一份套件进了面）。

## 事实源只有一个

判定本体与全部断言都住在 `tests/agent_eval/test_eval_fixture_case_contract.py`
（**单一实现**：本文件不复制、不改写、不重写任何一条断言）——
本文件只做**同名再导出**，让 pytest 在本目录的收集面里**执行同一批测试函数**。
同款先例（本目录既有的跨文件借用）：`tests/unit_ci_workflows/test_remedy_registry_guard.py`
`from unit_ci_workflows import test_dead_capability_meta_guard as dc`。

⚠️ **不许**在这里写「复制一份断言」的实现：那样会多出第二份会漂的判据（同 `migao-dev-flow` §23.7 A6）。

## 红证（注入式，跑真语料）

剪掉 `FN-001` 依赖的那段种子（`tests/agent_eval/fixtures/mibao_eval_seed.sql` 的
`finance_transactions`）⇒ 本文件里的 `test_removing_finance_seed_is_red_and_names_FN_001`
**当场判红且具名 `FN-001`**。复算（在仓库根，不改仓库文件）：

```bash
# 剪掉种子 ⇒ 判红且具名（预期：1 failed，报文含 FN-001）
python3 - <<'PY'
from pathlib import Path
p = Path("tests/agent_eval/fixtures/mibao_eval_seed.sql")
Path("/tmp/mibao_seed.bak").write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
src = p.read_text(encoding="utf-8")
lines, out, skip = src.splitlines(True), [], False
for ln in lines:                                   # 剪掉 `INSERT INTO finance_transactions` 那条语句
    if "INSERT INTO finance_transactions" in ln:
        skip = True
    if skip:
        if ln.rstrip().endswith(";"):
            skip = False
        continue
    out.append(ln)
p.write_text("".join(out), encoding="utf-8")
PY
python3 -m pytest tests/unit_ci_workflows/test_eval_fixture_case_contract_leg.py -q -p no:cacheprovider
cp /tmp/mibao_seed.bak tests/agent_eval/fixtures/mibao_eval_seed.sql     # 还原（必须）
```

> ⚠️ 也**必须**有「未注入 ⇒ 不报」的反向对照：还原后同一条命令**全绿**。
> 只有红一侧的读数分不清「判据有牙」与「判据恒红」。
"""
from __future__ import annotations

import pathlib

# 再导出 = 让 pytest 在本目录的收集面里跑**同一批**测试函数（导入期不执行任何断言）。
from agent_eval.test_eval_fixture_case_contract import (  # noqa: F401
    test_comment_mention_does_not_count_as_seed,
    test_empty_ledger_is_red,
    test_ledger_entry_that_no_longer_matches_is_red,
    test_real_repo_satisfies_the_contract,
    test_removing_finance_seed_is_red_and_names_FN_001,
    test_requirement_scan_actually_sees_the_five_assertions,
    test_unmutated_memory_overlay_is_green,
    test_unregistered_nonempty_assertion_is_named_red,
)

#: 本再导出**必须**覆盖的测试函数清单（源文件里现取的那 8 条）。
#: 用途 = 下游判据核对「再导出是不是漏了几条」——漏了会让 CI 的覆盖面静默缩水
#: （源文件新增一条断言，而本文件忘了再导出 ⇒ 那条判据**不进 CI**，且**没有任何东西会红**）。
EXPECTED_EXPORTS = (
    "test_real_repo_satisfies_the_contract",
    "test_requirement_scan_actually_sees_the_five_assertions",
    "test_unregistered_nonempty_assertion_is_named_red",
    "test_removing_finance_seed_is_red_and_names_FN_001",
    "test_unmutated_memory_overlay_is_green",
    "test_comment_mention_does_not_count_as_seed",
    "test_ledger_entry_that_no_longer_matches_is_red",
    "test_empty_ledger_is_red",
)


def test_this_reexport_covers_every_guard_test_in_the_source_suite() -> None:
    """**再导出不许漏**：源套件里现取的测试函数，本文件必须逐条再导出。

    治的形态（本文件自己最容易出的坏形态）：源套件新增一条断言，而这里忘了再导出
    ⇒ 那条判据**不进 CI** 且**没有任何东西会红** —— 正是 #7043 未固化项 #1 的原形复发。
    判据按**现取**源文件里的测试函数集合复算，不写死清单（新增函数 ⇒ 自动进面）。
    """
    import inspect

    from agent_eval import test_eval_fixture_case_contract as source

    # ⚠️ 归属判定用**源文件路径**，不用 `__module__` 名：同一个文件在本目录里可能以**两个**模块对象
    #    存在（pytest 顶层导入 + 命名空间包 `agent_eval.*` 导入），按名字比会把已再导出的测试判成
    #    「没再导出」（本包实测：判据被自己的导入形态喂红）。也不要求两条路径逐字相同
    #    （本机是符号链接路径时 realpath 会差一级）⇒ 用**文件名 + 源文件现取**两条一起判。
    source_file = pathlib.Path(inspect.getsourcefile(source) or "")
    live = {name for name, obj in vars(source).items()
            if name.startswith("test_") and inspect.isfunction(obj)
            and getattr(obj, "__module__", "").rsplit(".", 1)[-1] == source.__name__.rsplit(".", 1)[-1]
            and pathlib.Path(inspect.getsourcefile(obj) or "").name == source_file.name}
    declared = set(EXPECTED_EXPORTS)
    missing_here = live - declared
    assert not missing_here, (
        f"源套件里现取到 {sorted(live)}，而本文件的再导出清单只有 {sorted(declared)} ⇒ "
        f"这几条判据**不进 CI**（漏再导出 = #7043 未固化项 #1 的原形复发）：{sorted(missing_here)}"
    )
    stale = declared - live
    assert not stale, (
        f"再导出清单里有源套件已不存在的测试：{sorted(stale)} ⇒ 清单已腐，请按现取读数收敛"
    )
    # ⚠️ 用 `globals()` 取**本模块**的绑定，不用 `__import__(__name__)`：后者在 pytest 的收集面里
    #    拿到的是**顶层包**而不是本模块（本包实测：`__import__("test_x_leg")` ⇒ `AttributeError` 一族，
    #    判据会把 8 条**已经**再导出的测试判成「没能再导出」= 被自己的导入形态喂红）。
    not_reexported = {n for n in declared if not callable(globals().get(n))}
    assert not not_reexported, (
        f"清单声明了却没能再导出（导入失败 / 被改名）：{sorted(not_reexported)}"
    )
