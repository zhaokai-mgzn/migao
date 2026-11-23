# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI / 部署结构类 L0 不变式统一挂 MC-012 ——
#   见 .github/cases/misc.yml 的 MC-012「CI workflow 行为由 tests/unit_ci_workflows/ 单测验证」。）
"""**类级元守卫**：产物新鲜度闸门不许写成「裸时间戳 / 裸哈希不等 ⇒ 红」（issue #8924）。

## 病（这一类，不是这一处）

`Publish C-end H5` 的 notify 档连续红（#8860/#8861/#8862 → #8924），读数逐字
`线上产物陈旧：2026-11-18T09:38Z 早于 frontend/mini-app 最近改动 2026-11-19T01:45Z`，
而 issue body 明写「命中具名确定性闸门 ⇒ 重跑只会再命中同一条闸门」。

这类闸门的结构性缺陷是**判据只能读到代理**：

| 代理读数 | 它其实回答的问题 | 它**不**回答的问题 |
|---|---|---|
| 线上 `Last-Modified` | 「上一次发布发生在什么时候」 | 「线上内容与本次构建有没有差异」 |
| 产物文件哈希 | 「这一次取到的字节是什么」 | 「差异是不是**构建非确定性**（顺序 / 标识符重命名）」 |

⇒ 代理说「旧」时，必须再用**内容等价判定**把它转成结论（构建一次 + 逐字节比对），
否则只有两种结局：周期假红（devDependency 升级，发布出来字节一样）或永远红（没人发布）。
只修「这一条」= 没修 —— 下一次新加一条「线上时间 vs 源码时间」的闸门会重演。

## 本文件判什么（每条都能单独变红）

| # | 判据 | 回归时会怎么红 |
|---|---|---|
| 1 | **未登记即红**：仓库里任何读 `Last-Modified` 的闸门脚本都必须在 `freshness_gate_ledger.json` 登记（代理读数 + 内容等价判定 + 复核脚本 + 调用面） | 新写一个 `*_freshness*.py` 读 `Last-Modified` 不登记 ⇒ 红 |
| 2 | **登记项必须真有内容等价判定**：`content_proof_flag` 必须出现在该脚本的 argparse 里，且脚本里真有等价比对函数 | 把 `--dist-dir` 摘掉（退回裸时间戳判红）⇒ 红 |
| 3 | **调用面必须走同一份复核实现**：登记的每个 caller 都必须调用 `confirm_script`，**不得**直接 `python3 <gate script>` 裸跑代理判据 | 把某条腿改回直接跑 guard ⇒ 红 |
| 4 | **复核脚本两段式**：先跑代理（不带 `--dist-dir`），**只有**判「陈旧」才构建 + 带 `--dist-dir` 复跑；构建失败必须 fail-closed（非零） | 改成只跑一次 / 构建失败当等价 ⇒ 红 |
| 5 | **复核的构建 env 与发布腿同源**：`TARO_APP_API_URL` / `TARO_APP_AI_API_URL` 必须与发布步骤一致（否则字节必然不同 = 恒假红） | 去掉 env 注入 ⇒ 红 |

## 红证（改前 / 注入式）

```bash
# 判据 1：改前没有任何「新鲜度闸门登记表」这种东西
ls tests/unit_ci_workflows/freshness_gate_ledger.json 2>/dev/null || echo "改前：不存在"
# 判据 3：改前两条腿都是直接跑 guard（裸代理判据）
git show origin/main:.github/workflows/c-end-h5-publish.yml | grep -c 'python3 scripts/h5_freshness_guard.py'   # 改前 1
python3 -m pytest tests/unit_ci_workflows/test_freshness_gates_content_equivalence.py -q   # 摘掉等价判定 ⇒ 红
```
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LEDGER = REPO_ROOT / "tests" / "unit_ci_workflows" / "freshness_gate_ledger.json"


def _ledger() -> dict:
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def _gate_scripts_reading_last_modified() -> set[str]:
    """仓库里**读线上 `Last-Modified`** 的闸门脚本（相对路径）—— 也就是「代理读数」那一类。"""
    found: set[str] = set()
    for base in ("scripts", "deploy"):
        for path in (REPO_ROOT / base).rglob("*"):
            if path.suffix not in (".py", ".sh") or not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            # 只认**真的读这个头**的代码行（注释里提到它的发布脚本不算闸门 —— 否则登记表会被噪音灌满）
            reads_header = any(
                "Last-Modified" in line and not line.lstrip().startswith("#")
                for line in text.splitlines()
            )
            if reads_header:
                found.add(path.relative_to(REPO_ROOT).as_posix())
    return found


def test_every_last_modified_gate_is_registered():
    """判据 1（未登记即红）：凡是读 `Last-Modified` 的闸门，都得在登记表里说明它的内容等价判定。"""
    ledger = _ledger()
    registered = {g["script"] for g in ledger["gates"]}
    found = _gate_scripts_reading_last_modified()
    assert found, "反空跑锚点：一条读 Last-Modified 的脚本都没扫到（扫描面漂了）"
    unregistered = sorted(found - registered)
    assert not unregistered, (
        "这些闸门用**代理读数**判红却没有登记内容等价判定（issue #8924 的同一类缺陷）："
        f"{unregistered} ⇒ 到 {LEDGER.relative_to(REPO_ROOT)} 登记 "
        "`proxy_reading` / `content_proof_flag` / `confirm_script` / `callers`（未登记即红）"
    )


@pytest.mark.parametrize("gate", _ledger()["gates"], ids=lambda g: g["name"])
def test_registered_gate_really_exposes_content_proof(gate):
    """判据 2：登记的 `content_proof_flag` 必须真在脚本里，且脚本里真有一个等价比对函数。

    红证：把 `--dist-dir` 那个 argparse 参数删掉（= 退回「裸时间戳判红」）⇒ 本用例红。
    """
    script = (REPO_ROOT / gate["script"]).read_text(encoding="utf-8")
    flag = gate["content_proof_flag"]
    assert flag in script, (
        f"{gate['script']} 里没有内容等价判定的开关 {flag} ⇒ 该闸门只会「代理说旧就判红」"
    )
    assert re.search(r"def \w*equivalen\w*\(", script), (
        f"{gate['script']} 里找不到等价判定函数（`def *equivalen*`）—— 只登记一个 flag 不算有判定力"
    )


@pytest.mark.parametrize("gate", _ledger()["gates"], ids=lambda g: g["name"])
def test_every_caller_uses_the_shared_confirm_script(gate):
    """判据 3：登记过的调用面必须走 `confirm_script`，**不得**直接裸跑代理判据。"""
    for caller in gate["callers"]:
        text = (REPO_ROOT / caller).read_text(encoding="utf-8")
        assert gate["confirm_script"] in text, (
            f"{caller} 没有走 {gate['confirm_script']}（内容等价复核）⇒ 这条腿又会「代理说旧就判红」"
        )
        bare = re.search(r"python3\s+" + re.escape(gate["script"]), text)
        assert bare is None, (
            f"{caller} 里仍有**直接**跑 {gate['script']} 的裸调用（绕过了内容等价复核）"
        )


def test_confirm_script_is_two_phase_and_fails_closed():
    """判据 4：复核脚本必须「先代理、只有陈旧才构建 + 带 flag 复跑」，且构建失败 fail-closed。"""
    gate = _ledger()["gates"][0]
    text = (REPO_ROOT / gate["confirm_script"]).read_text(encoding="utf-8")
    calls = text.count(gate["script"])
    assert calls >= 2, (
        f"{gate['confirm_script']} 只调用了 {calls} 次 {gate['script']} —— 复核必须是**两段式**："
        "①先跑代理判据 ②陈旧时构建后带 --dist-dir 复跑"
    )
    assert gate["content_proof_flag"] in text, "复核脚本没有用上内容等价开关"
    assert "npm run build:h5" in text, "复核脚本不构建 ⇒ 没有可比对的对象（等于没复核）"
    # fail-closed：构建失败不得当等价
    assert re.search(r"build:h5[\s\S]{0,400}?exit 2", text), (
        "构建失败后没有非零退出 ⇒ 「建不出来」会被当成「内容等价」（假绿）"
    )


def test_confirm_script_build_env_matches_publish_step():
    """判据 5：复核构建必须与**发布步骤**同 env（否则 baked 进产物的 API 地址不同 ⇒ 恒假红）。"""
    gate = _ledger()["gates"][0]
    confirm = (REPO_ROOT / gate["confirm_script"]).read_text(encoding="utf-8")
    publish = (REPO_ROOT / ".github/workflows/c-end-h5-publish.yml").read_text(encoding="utf-8")
    for var in ("TARO_APP_API_URL", "TARO_APP_AI_API_URL"):
        assert var in confirm, f"{gate['confirm_script']} 没注入 {var} ⇒ 构建字节与发布腿不同（恒假红）"
        assert var in publish, f"发布腿没有 {var}（判据的对照面漂了）"
