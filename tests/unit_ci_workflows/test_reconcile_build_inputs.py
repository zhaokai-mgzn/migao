# case_ids: MC-144
"""`deploy-reconcile` 的漂移判据必须看得见**构建输入**（issue #7034）。

## 病（现取读数，不是推断）

判据 ② 原先只问「自上次成功部署起 `${svc_path}`（应用代码目录）有没有改动」。所以**只改
构建输入**（`.github/workflows/**` / `deploy/**` 的部署脚本）的修复合入后：

```
✅ admin-api：自上次成功部署 fbbb798 起 backend/admin-api 无代码改动 ⇒ 无漂移（HEAD 的代码已在线上）
```

而同一时刻线上 `GET /api/version` 的 `builtAt` 仍是空串（issue #7029 要修的就是它）⇒
**修复没上线、告警面报绿、还会自动关闭值守单**。「CI 改好了」被读成了「线上兑现了」。

## 本文件锁什么（每条都「先绿」+「注入后必红」）

1. **实例判据（执行式，逐条派生自登记册）**：对**每一条**登记的构建输入造一次「只改它」的
   commit（C1 → C2 → docs HEAD），在真实 git 仓库 + 桩 `gh`/`docker` 下跑**当前**的对账正文 ⇒
   期望 dispatch 的腿集合 = 现取算出「覆盖面包含该路径」的腿集合。判据 ① ② 就在其中
   （`deploy/**` 的脚本、`.github/workflows/<本腿>.yml`），**且新登记的条目自动进入射程**（不用改判据）。
2. **负控 ③（证明没扩成全仓）**：只改 `docs/wiki/About.md` ⇒ **零 dispatch** + summary 全是「无漂移」。
3. **负控 ④（既有行为不回归）**：只改应用代码（`backend/admin-api/…`）⇒ 仍判「有漂移」并 dispatch。
4. **红证 ⑤（判别力自证）**：把追加构建输入的那一行注入成空串（= 改前的形态）⇒ ①② 两条探针
   **必红**（零 dispatch）。**不注入 ⇒ 绿**，故「绿」不是空断言。
5. **类级元守卫（未登记即红）**：现取每条腿 workflow 里**真被调用**的仓内路径
   （`bash <p>` / `source <p>` / `python3 <p>` / `uses: ./.github/workflows/<x>.yml`）——
   每一条都必须**被该腿的 pathspec 覆盖**，或在 `NOT_BUILD_INPUTS` 里**逐条带理由**登记。
   新加一句 `bash deploy/scripts/foo.sh` 而没登记 ⇒ 当场红（这就是「同类进不来」的那一半）。
6. **豁免不许陈旧**：`NOT_BUILD_INPUTS` 的每条都必须「仍被引用」且「确实没被覆盖」，否则红。
7. **登记册本身不许腐烂**：腿名与 `reconcile_one` 调用行**双向相等**；每条路径必须**真的存在**
   （拼错 = 静默匹配不到 = 又一种假绿）；每条必须有非空理由。

⚠️ 桩化的诚实标注（与 `test_reconcile_no_silent_skip.py` 同口径）：`gh`/`docker` 是**桩**，
本文件证明的是「**判定逻辑**在给定 diff 下会做什么」，**不是**「GitHub 真的 dispatch 了」；
后者只有真跑 CI 才能验证。本文件不联网、不碰真实云/ACR、不写共享 `/tmp`（产物全落 `tmp_path`）。
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
HELPER = REPO_ROOT / ".github" / "scripts" / "reconcile_build_inputs.py"
HARNESS_PATH = Path(__file__).with_name("test_reconcile_no_silent_skip.py")
CFG_PATH = Path(__file__).with_name("test_config_change_triggers_deploy.py")


def _load(path: Path, name: str):
    """按路径载入同族模块（**复用**既有桩与解析口径，不复制第二份真值源）。"""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"载入不了：{path}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BI = _load(HELPER, "reconcile_build_inputs")          # 被测的**唯一**取值源
HARNESS = _load(HARNESS_PATH, "reconcile_exec_harness_bi")   # 执行式桩跑（#4827 的范式）
CFG = _load(CFG_PATH, "config_change_triggers_deploy_bi")    # 造仓 + 调用行解析 + glob 语义


# ══════════════════════════════════════════════════════════════════════════
# 现取真值：腿 → workflow / 服务路径 / 附加 pathspec（来自 workflow 的调用行，不写死）
# ══════════════════════════════════════════════════════════════════════════

def leg_calls() -> dict:
    calls = CFG.parse_calls()
    assert calls, "反空跑锚点：一条对账腿都没解析出来（判据已过期）"
    return calls


LEGS = leg_calls()


def face(svc: str) -> list:
    """该腿**实际**的 pathspec（应用代码 + 附加项 + 构建输入），排除项单独回。"""
    call = LEGS[svc]
    return [p for p in BI.pathspec(svc, str(call["path"]), str(call["excl"])) if not p.startswith(":(exclude)")]


def wf_of(svc: str) -> str:
    return str(LEGS[svc]["wf"])


def expected_legs_for(probe: str) -> list:
    """「只改 `probe`」时**按登记册现算**应当 dispatch 的腿集合（不手抄期望值）。"""
    return sorted({wf_of(svc) for svc in LEGS if any(CFG.leg_covers(p, probe) for p in face(svc))})


def probe_for(pathspec_entry: str) -> str:
    """把一条 pathspec 落成**一个具体文件路径**（用于造「只改它」的 commit）。"""
    return pathspec_entry[:-3] + "/probe.txt" if pathspec_entry.endswith("/**") else pathspec_entry


def run_only_change(tmp_path: Path, probe: str, name: str, *, script_text: str | None = None):
    fx = CFG.repo_with_single_change(tmp_path, probe, name)
    scratch = tmp_path / name / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    return HARNESS.run_reconcile(
        scratch, fx["repo"], HARNESS.runs_all(fx["C1"], "success"),
        head7=fx["head7"], script_text=script_text,
    )


# 构建输入的「逐条」探针（**从登记册派生** ⇒ 新登记一条就自动进入射程）
BUILD_INPUT_PROBES = [
    (svc, pathspec_entry, probe_for(pathspec_entry))
    for svc in sorted(BI.BUILD_INPUTS)
    for pathspec_entry in BI.build_inputs(svc)
]


# ══════════════════════════════════════════════════════════════════════════
# 判据 1（实例，执行式）：每一条登记的构建输入 ⇒ 都真的判「有漂移」并 dispatch
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("svc,pathspec_entry,probe", BUILD_INPUT_PROBES,
                         ids=[f"{s}:{p}" for s, p, _ in BUILD_INPUT_PROBES])
def test_registered_build_input_is_judged_as_drift(tmp_path, svc, pathspec_entry, probe):
    """🔴 本单的承重判据：**只改一个构建输入** ⇒ 必须判「有漂移」并 dispatch 对应的腿。

    这条覆盖 issue 的两条具名判据：
    ① 只改 `deploy/**` 里的一个脚本（如 `deploy/scripts/swas-deploy-ci.sh`）；
    ② 只改 `.github/workflows/<本腿>.yml`。
    """
    proc, summary, dispatches = run_only_change(tmp_path, probe, f"bi-{abs(hash((svc, probe))) % 10**8}")
    assert proc.returncode == 0, f"[{svc} · {probe}] 对账正文非零退出 → {proc.stderr}\n{proc.stdout}"
    want = expected_legs_for(probe)
    assert want, f"[{svc} · {probe}] 按登记册算出的期望腿集合为空 ⇒ 该登记项根本没接进任何一条腿"
    assert sorted(dispatches) == want, (
        f"[{svc} · 只改 {probe}] 期望 dispatch {want}，实得 {sorted(dispatches)}\n"
        f"⇒ 该构建输入改了却判「无漂移」= 修复没上线而告警面报绿（issue #7034）\n{proc.stdout}"
    )
    assert wf_of(svc) in dispatches, f"[{svc}] 自己那条腿没被 dispatch：{sorted(dispatches)}"
    # 读数与事实一致：判定依据里必须**点名**这条构建输入（否则读的人会以为是应用代码改了）
    assert pathspec_entry in summary or probe in summary, (
        f"[{svc} · 只改 {probe}] summary 没点名判定所用的构建输入 ⇒ 归因会跑偏\n{summary!r}"
    )


# ══════════════════════════════════════════════════════════════════════════
# 判据 2（负控 ③）：只改无关文档 ⇒ 判「无漂移」（证明没扩成「任何文件变动都算」）
# ══════════════════════════════════════════════════════════════════════════

def test_unrelated_docs_change_is_not_drift(tmp_path):
    """负控：`docs/wiki/About.md` 不在任何构建输入面里 ⇒ **零 dispatch**。

    若这条变红，说明判据被扩成了「全仓任何改动都算漂移」⇒ 该腿会永远红、每次空转一次生产重建。
    """
    probe = "docs/wiki/About.md"
    assert expected_legs_for(probe) == [], f"文档被算进了某条腿的判定面：{expected_legs_for(probe)}"
    proc, summary, dispatches = run_only_change(tmp_path, probe, "docs-only")
    assert proc.returncode == 0, f"{proc.stderr}\n{proc.stdout}"
    assert dispatches == [], f"只改无关文档却 dispatch 了 {dispatches} ⇒ 判据扩过头\n{proc.stdout}"
    assert summary.count("无漂移") >= len(LEGS), (
        f"每一条腿都应明写「无漂移」（不是静默 success）→ {summary!r}"
    )


# ══════════════════════════════════════════════════════════════════════════
# 判据 3（负控 ④）：只改应用代码 ⇒ 仍判「有漂移」（既有行为不回归）
# ══════════════════════════════════════════════════════════════════════════

def test_app_code_change_still_counts_as_drift(tmp_path):
    """负控：应用代码改动**照旧**判「有漂移」—— 本单只加面，不动既有判据。"""
    probe = "backend/admin-api/Changed.java"
    proc, _summary, dispatches = run_only_change(tmp_path, probe, "app-code")
    assert proc.returncode == 0, f"{proc.stderr}\n{proc.stdout}"
    assert sorted(dispatches) == expected_legs_for(probe) == ["deploy-admin-api.yml"], (
        f"应用代码改动的判定变了（既有行为回归）→ {sorted(dispatches)}\n{proc.stdout}"
    )


# ══════════════════════════════════════════════════════════════════════════
# 判据 4（红证 ⑤）：把「追加构建输入」那一行注入成空 ⇒ 判据 1 的两条具名探针必红
# ══════════════════════════════════════════════════════════════════════════

#: 注入点 = 追加构建输入的那一句（改它 = 退回改前形态：pathspec 只有 svc_path + extra）。
INJECT_ANCHOR = 'bi=$(python3 .github/scripts/reconcile_build_inputs.py "$svc" 2>/dev/null) || bi=""'


def test_pre_fix_shape_has_no_build_inputs(tmp_path):
    """🔴 红证⑤：**改前形态**（不带构建输入）下，①② 两条具名探针**零 dispatch**。

    不注入时它们绿（判据 1），注入后必红 ⇒ 判据 1 不是空断言。
    """
    real = HARNESS.reconcile_script()
    assert INJECT_ANCHOR in real, f"注入点已漂移（判据过期）：{INJECT_ANCHOR!r}"
    broken = real.replace(INJECT_ANCHOR, 'bi=""')
    assert broken != real, "注入未生效（判据自证）"

    # ①② 的具名形态各一条（issue 施工单里的判据 ① 与 ②）
    for probe in ("deploy/scripts/swas-deploy-ci.sh", ".github/workflows/deploy-admin-api.yml"):
        proc, summary, dispatches = run_only_change(
            tmp_path, probe, "red-" + probe.replace("/", "_"), script_text=broken,
        )
        assert proc.returncode == 0, f"[{probe}] 注入后脚本应仍能跑完 → {proc.stderr}"
        assert dispatches == [], (
            f"[{probe}] 退回改前形态（不带构建输入）却仍 dispatch {dispatches} ⇒ "
            f"判据 1 没有判别力（空断言）\n{proc.stdout}"
        )
        assert "无漂移" in summary, f"[{probe}] 改前形态应判「无漂移」（这正是假绿）→ {summary!r}"


# ══════════════════════════════════════════════════════════════════════════
# 判据 5（类级元守卫）：腿里**真被调用**的仓内路径，必须被覆盖或逐条豁免
# ══════════════════════════════════════════════════════════════════════════

#: `bash <p>` / `source <p>` / `sh <p>` / `python3 <p>` 形态（只取仓内相对路径）
REF_RE = re.compile(r"\b(?:bash|source|sh|python3)\s+(?:\./)?((?:deploy|scripts|\.github)/[A-Za-z0-9_./-]+)")
#: `uses: ./.github/workflows/<x>.yml`（可复用腿 = 「我们对线上说的那句话」的一半）
USES_RE = re.compile(r"uses:\s*\./(\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml)")


def referenced_paths(wf_text: str) -> list:
    """现取：某条腿的 workflow 里**真被调用**的仓内路径（**剥掉整行注释**，注释里的举例不算）。"""
    code = "\n".join(
        line for line in wf_text.splitlines()
        if not line.lstrip().startswith("#")
    )
    return sorted(set(REF_RE.findall(code)) | set(USES_RE.findall(code)))


def uncovered_references(svc: str, wf_text: str) -> list:
    """该腿 workflow 里**没被** pathspec 覆盖、也没登进 `NOT_BUILD_INPUTS` 的引用（= 缺口）。"""
    covered = face(svc)
    out = []
    for ref in referenced_paths(wf_text):
        if ref in BI.NOT_BUILD_INPUTS:
            continue
        if any(CFG.leg_covers(p, ref) for p in covered):
            continue
        out.append(ref)
    return out


def test_every_script_a_leg_runs_is_a_build_input_or_exempted():
    """🔴 类级元守卫（未登记即红）：腿调用的每个脚本 / 可复用 workflow 都必须在判定面里。

    这是「同类进不来」的那一半：将来谁给某条腿加一句 `bash deploy/scripts/foo.sh` 而没登记，
    下一次那处改动就会静默不上线 —— 现在它在**加引用时**就红。
    """
    problems = []
    for svc in sorted(LEGS):
        wf_text = (WORKFLOWS_DIR / wf_of(svc)).read_text(encoding="utf-8")
        refs = referenced_paths(wf_text)
        assert refs, f"反空跑锚点：{wf_of(svc)} 里一个脚本引用都没取到（判据已过期）"
        for ref in uncovered_references(svc, wf_text):
            problems.append(f"{svc}（{wf_of(svc)}）调用了 {ref}，但它不在该腿的判定面里")
    assert not problems, (
        "以下被对账腿调用的文件改了**不会**被判「有漂移」⇒ 修复合入后静默不上线：\n  "
        + "\n  ".join(problems)
        + "\n修法：在 .github/scripts/reconcile_build_inputs.py 的 BUILD_INPUTS 里登记（带理由），"
          "确实不该算构建输入 ⇒ 登进 NOT_BUILD_INPUTS（带理由）。"
    )


def test_meta_guard_has_discriminating_power():
    """🔴 红证：在真 workflow 文本里注入一句 `bash deploy/scripts/ghost.sh` ⇒ 元守卫必红。"""
    wf_text = (WORKFLOWS_DIR / wf_of("admin-api")).read_text(encoding="utf-8")
    assert uncovered_references("admin-api", wf_text) == []  # 前提：真语料先绿
    injected = wf_text + "\n      - run: bash deploy/scripts/ghost.sh\n"
    assert "deploy/scripts/ghost.sh" in referenced_paths(injected), "注入未生效（判据自证）"
    assert uncovered_references("admin-api", injected) == ["deploy/scripts/ghost.sh"], (
        "注入了未登记的脚本引用而元守卫没抓到 ⇒ 它没有判别力（空断言）"
    )


def test_exemptions_are_necessary_and_alive():
    """豁免不许陈旧：每条 `NOT_BUILD_INPUTS` 必须**仍被某条腿引用**、且**确实没被覆盖**。"""
    all_refs = {
        svc: set(referenced_paths((WORKFLOWS_DIR / wf_of(svc)).read_text(encoding="utf-8")))
        for svc in LEGS
    }
    for path in BI.NOT_BUILD_INPUTS:
        assert str(BI.NOT_BUILD_INPUTS[path]).strip(), f"豁免 {path} 没有理由（缺口不许匿名存在）"
        assert any(path in refs for refs in all_refs.values()), (
            f"豁免 {path} 已经没有任何腿引用了 ⇒ 陈旧条目，删掉它（台账只许缩短）"
        )
        covering = [svc for svc in LEGS if any(CFG.leg_covers(p, path) for p in face(svc))]
        assert not covering, (
            f"豁免 {path} 其实已被腿 {covering} 的判定面覆盖 ⇒ 豁免陈旧：要么删豁免，要么删覆盖"
        )


# ══════════════════════════════════════════════════════════════════════════
# 判据 6：登记册本身不许腐烂（腿名双向相等 / 路径真的存在 / 理由非空 / CLI 三态）
# ══════════════════════════════════════════════════════════════════════════

def test_registry_legs_match_the_reconcile_calls():
    """登记册与 `reconcile_one` 调用行**双向相等**：新增一条腿而不登记 ⇒ 红，反之亦然。"""
    assert sorted(BI.BUILD_INPUTS) == sorted(LEGS), (
        f"构建输入登记册 {sorted(BI.BUILD_INPUTS)} 与对账腿 {sorted(LEGS)} 不一致\n"
        "⇒ 要么给新腿登记构建输入，要么删掉陈旧条目（两侧都不许缺席）"
    )


@pytest.mark.parametrize("svc", sorted(BI.BUILD_INPUTS))
def test_every_registered_path_exists_and_has_a_reason(svc):
    """每条登记路径必须**真的存在**且带理由：拼错 = 静默匹配不到 = 又一种假绿。"""
    reasons = BI.build_input_reasons(svc)
    assert reasons, f"{svc} 的构建输入清单为空（判据会在空集上恒真）"
    for pathspec_entry, why in reasons.items():
        assert str(why).strip(), f"{svc} 的 {pathspec_entry} 没写理由"
        base = pathspec_entry[:-3] if pathspec_entry.endswith("/**") else pathspec_entry
        target = REPO_ROOT / base
        assert target.exists(), (
            f"{svc} 登记的构建输入 {pathspec_entry} 在仓里**不存在** ⇒ "
            f"`git log … -- {pathspec_entry}` 会静默匹配不到（正是本单要治的假绿形态）"
        )
        if pathspec_entry.endswith("/**"):
            assert any(target.iterdir()), f"{svc} 登记的 {pathspec_entry} 目录是空的（判据会恒真）"


def test_cli_contract_for_the_workflow():
    """workflow 只调用它 ⇒ CLI 契约必须钉住：已知腿给空格分隔的清单，未知腿**不给号**（退出 3）。"""
    for svc in sorted(BI.BUILD_INPUTS):
        out = subprocess.run([sys.executable, str(HELPER), svc],
                             capture_output=True, text=True, check=False)
        assert out.returncode == 0, f"{svc}: CLI 退出 {out.returncode} → {out.stderr}"
        entries = out.stdout.split()
        assert entries == list(BI.build_inputs(svc)), f"{svc}: CLI 输出 {entries} 与登记册不一致"
        for entry in entries:
            assert not any(ch.isspace() for ch in entry), (
                f"{svc}: {entry!r} 含空白 ⇒ 调用方 `pathspec+=( $bi )` 会把它切成两半"
            )

    bad = subprocess.run([sys.executable, str(HELPER), "ghost-leg"],
                         capture_output=True, text=True, check=False)
    assert bad.returncode == 3, f"未知腿必须退 3（不猜），实得 {bad.returncode}"
    assert bad.stdout.strip() == "", "未知腿不许打印任何 pathspec（否则调用方会照单全收）"
