# case_ids: MC-023
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012；
#   本单是**新的一类**（部署触发面 vs 部署对账面同源），按用例号顺延取 MC-023（先取的 MC-022 在 rebase 时被 #5651 收口包占用）。）
"""「只改配置」的改动能**自动生效** —— `deploy/swas/**` 接进部署触发面（关联 #5001）。

## 病（实测，非推断）

`deploy/swas/nginx.conf` / `docker-compose*.yml` 这类**只改配置**的改动，合并后**静默不生效**：

| 事实 | 读数 |
|---|---|
| 触发面 | `deploy-admin-api.yml` 的 `on.push.paths` 原先**只有** `backend/admin-api/**` ⇒ 改配置**不触发任何部署腿** |
| 「有触发面」的那条腿 | `bmini-h5-publish.yml` 的 paths 里**有** `deploy/swas/nginx.conf`，但那条腿**只往静态根发文件**（全程没有 `cp` / 没有 `reload` / 不跑 `deploy.sh`）⇒ **配置不被应用** |
| 应用面 | **只在** `deploy/swas/deploy.sh`：`cp src/deploy/swas/nginx.conf ./nginx/nginx.conf` + `docker compose up -d --no-deps nginx` + `nginx -s reload`（`nginx` 是 `UP_SERVICES` 的初值、那段在逐服务循环**之外** ⇒ **任何**一条部署腿跑起来都会应用配置） |
| 后果（已咬两次） | #5668 的 `/b/`、#5676 的 `/i/`（两次都是 `deploy/swas/nginx.conf` 的改动）**只能靠人工 `workflow_dispatch` 才生效** |

⇒ 修法（用户逐字裁定 **A**：把 `deploy/swas/**` 加进 `deploy-admin-api` 的 paths，最小改动）：
**触发面**（`deploy-admin-api.yml` 的 `on.push.paths`）与**对账面**（`deploy-reconcile.yml` 里
admin-api 腿的第 4 个参数）**同批**加上 `deploy/swas/**`。

## 本文件锁什么（每条都有「先绿」+「注入后必红」）

1. **端到端自证**（执行式）：造一个「**只动 `deploy/swas/nginx.conf`**」的 commit，把
   `deploy-reconcile.yml` 的判定正文抽出来，在真实 git 仓库 + 桩 `gh`/`docker` 下**真跑** ⇒
   必须判定**有漂移**并 dispatch `deploy-admin-api.yml`（= 会触发部署）。**不往 main 推任何测试提交**。
2. **应用面仍在**：`deploy/swas/deploy.sh` 必须仍然 `cp` canonical 配置 + 无条件 `up -d nginx` + reload
   —— 否则「触发了部署」也不等于「配置被应用」（触发面与应用面必须同时在位）。
3. **类级 meta-guard**（本单真正的价值）：「某服务的触发路径集合」**同时**写在
   `deploy-*.yml` 的 `on.push.paths` 与 `deploy-reconcile.yml` 的腿参数里，**只改一处 ⇒ 触发面与
   对账面脱钩**（同类病的根源）。⇒ 逐服务**双向**比对两处（防静默 / 防空转）+ 排除项对齐 +
   存量缺口台账（只许缩短）；另配**执行式**版本：触发面的每一条正向路径都真的能落到自己的对账腿。
4. **另外 4 条腿逐值不变**：冻结它们的调用点 + 执行式验证各自判定未变。

⚠️ 桩化的诚实标注（与 `test_reconcile_no_silent_skip.py` 同口径）：`gh`/`docker` 是**桩**，
本文件证明的是「判定逻辑在给定 diff 下会 dispatch」，**不是**「GitHub 真的会 dispatch」。
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
LEDGER_PATH = Path(__file__).with_name("reconcile_trigger_paths_ledger.json")
HARNESS_PATH = Path(__file__).with_name("test_reconcile_no_silent_skip.py")
GUARD_PATH = Path(__file__).with_name("test_swas_deploy_ci_hardening.py")

ADMIN_API_WF = "deploy-admin-api.yml"
CONFIG_TRIGGER = "deploy/swas/**"
CONFIG_ONLY_FILE = "deploy/swas/nginx.conf"

# 配置与镜像同源（deploy/swas/deploy.sh 第 0/1 段 + #5083）：脚本只认这**三份** canonical 配置，
# 其余路径的改动都到不了线上（`docker-compose.bluegreen.yml` 是 #4785 的蓝绿 override）。
CANONICAL_SWAS_CONFIGS = (
    "deploy/swas/nginx.conf",
    "deploy/swas/docker-compose.yml",
    "deploy/swas/docker-compose.bluegreen.yml",
)

# `deploy.sh` 的**应用面**三步（触发面把控制权交给部署腿之后，配置靠这三步落地）。
APPLIED_SURFACE = (
    "cp src/deploy/swas/nginx.conf ./nginx/nginx.conf",
    "docker compose up -d --no-deps nginx",
    "nginx -s reload",
)

# 另外 4 条对账腿的调用点（**冻结**：本单只允许 admin-api 那条变；改动其中任何一条 ⇒ 红）。
OTHER_LEGS_FROZEN = {
    "ai-agent-service": {
        "wf": "deploy-ai-agent-service.yml",
        "path": "backend/ai-agent-service",
        "extra": ":(exclude)backend/ai-agent-service/tests",
    },
    "admin-web": {"wf": "deploy-frontend.yml", "path": "frontend/admin-web", "extra": ""},
    "worker-h5": {"wf": "worker-h5-publish.yml", "path": "frontend/worker-h5", "extra": ""},
    "bmini-h5-hosting": {"wf": "bmini-h5-publish.yml", "path": "frontend/bmini-app", "extra": ""},
}


def _load_module(path: Path, name: str):
    """按路径载入同目录的既有守卫文件（**复用**它们的桩与解析口径，不复制第二份真值源）。"""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"载入不了同族守卫：{path.name}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


HARNESS = _load_module(HARNESS_PATH, "reconcile_exec_harness")   # 执行式桩跑（#4827 的范式）
GUARD = _load_module(GUARD_PATH, "reconcile_call_parser_guard")  # 调用点解析 + 腿登记册


# ══════════════════════════════════════════════════════════════════════════
# 读两处真值（触发面 = 真 YAML；对账面 = reconcile 正文里的调用行）
# ══════════════════════════════════════════════════════════════════════════

def on_push_paths(wf: str) -> list[str]:
    """读某个 workflow 的 `on.push.paths`（取不到 ⇒ 显式失败，不是「通过」）。"""
    path = WORKFLOWS_DIR / wf
    assert path.is_file(), f"反空跑锚点：{wf} 不存在（判据已过期）"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    # ⚠️ YAML 1.1 里裸 `on` 被解析成布尔 True（PyYAML 已知坑）⇒ 两种键都试
    on = doc.get("on") if doc.get("on") is not None else doc.get(True)
    assert isinstance(on, dict) and isinstance(on.get("push"), dict), f"{wf} 的 `on.push` 结构变了（判据已过期）"
    paths = on["push"].get("paths")
    assert paths, f"反空跑锚点：{wf} 没有 `on.push.paths`（判据会在空集上恒真）"
    return [str(p) for p in paths]


def all_push_paths() -> dict[str, list[str]]:
    """现取每个 deploy/发布 workflow 的 `on.push.paths`（按对账腿的 workflow 名索引）。"""
    calls = parse_calls()
    return {c["wf"]: on_push_paths(c["wf"]) for c in calls.values()}


def parse_calls() -> dict:
    """现取 `deploy-reconcile.yml` 正文里的逐服务调用（复用既有解析口径，不另写一套）。"""
    return GUARD.parse_reconcile_calls(HARNESS.reconcile_script())


def norm(pattern: str) -> str:
    """`deploy/swas/**` / `deploy/swas` ⇒ `deploy/swas`（两处比较用**前缀**，与既有守卫同口径）。"""
    return pattern[:-3] if pattern.endswith("/**") else pattern


def leg_paths(call: dict) -> tuple[list[str], list[str]]:
    """→ (该腿的正向 pathspec, 排除项)。

    `reconcile_one <svc> <deploy workflow> <服务代码路径> <额外 pathspec>`：第 4 个参数是
    **空格分隔的额外 pathspec** —— `:(exclude)X` 是排除项，其余是**附加包含项**
    （`deploy/swas` 就走这个现成的口子）。
    """
    includes, excludes = [str(call["path"])], []
    for token in str(call["excl"]).split():
        if token.startswith(":(exclude)"):
            excludes.append(token[len(":(exclude)"):])
        else:
            includes.append(token)
    return includes, excludes


# ══════════════════════════════════════════════════════════════════════════
# 路径 glob 语义（GitHub Actions 的 paths 过滤：`*` **不**跨 `/`，`**` 跨）
# ══════════════════════════════════════════════════════════════════════════

def _glob_regex(pattern: str) -> re.Pattern:
    out: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def glob_covers(pattern: str, path: str) -> bool:
    return bool(_glob_regex(pattern).match(path))


def leg_covers(pathspec: str, path: str) -> bool:
    """对账腿的 pathspec 是 **git pathspec**（目录/文件前缀，带 glob 时按同一套语义）⇒ 两种都判。"""
    if pathspec == path or path.startswith(pathspec.rstrip("/") + "/"):
        return True
    return glob_covers(pathspec, path)


# ══════════════════════════════════════════════════════════════════════════
# 判据 ③（类级 meta-guard）：触发面 vs 对账面，逐服务双向比对
# ══════════════════════════════════════════════════════════════════════════

def load_ledger() -> dict:
    assert LEDGER_PATH.is_file(), f"反空跑锚点：缺缺口台账 {LEDGER_PATH.name}（判据会静默空跑）"
    data = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    entries = data.get("entries")
    assert isinstance(entries, list), "台账的 `entries` 必须是数组"
    for e in entries:
        for key in ("svc", "wf", "path", "why"):
            assert str(e.get(key) or "").strip(), f"台账条目缺 `{key}`（缺口不许匿名存在）：{e}"
    return data


def check_trigger_paths_are_in_sync(calls: dict, wf_paths: dict, ledger: dict) -> None:
    """逐服务比对「触发面」与「对账面」，两个方向都必须成立。

    · **防静默**（承重，本单的病）：触发面的每一条正向路径都要落在对账面上 —— 触发面有、
      对账面没有 ⇒ 该路径的改动一旦 push 触发被吞，就**静默不部署**（#5668 / #5676 的形态）。
      未落地的必须**逐条**登记进缺口台账（台账只许缩短：条目必须逐字等于现取缺口）。
    · **防空转**：对账面上的每一条正向路径都要来自触发面 —— 否则每次对账都会为一个**不该部署**
      的改动空转 dispatch（重建重部署 ⇒ 502 窗口 + 覆盖回滚风险，#4827）。
    · **排除项逐字对齐**（沿既有口径）。
    """
    entries = {(str(e["svc"]), norm(str(e["path"]))) for e in ledger["entries"]}
    assert len(entries) == len(ledger["entries"]), "缺口台账有重复条目（同一 (服务, 路径) 登记两次）"
    for e in ledger["entries"]:
        svc, wf = str(e["svc"]), str(e["wf"])
        assert svc in calls and str(calls[svc]["wf"]) == wf, (
            f"缺口台账条目 {svc}/{e['path']} 的 workflow 记成 {wf}，"
            f"而现取该腿指向 {calls.get(svc, {}).get('wf')!r}（陈旧条目）"
        )
    assert len(entries) <= int(ledger["frozen_max"]), (
        f"缺口台账条目数 {len(entries)} > 冻结上界 {ledger['frozen_max']}（只许缩短：新增缺口必须先显式登记）"
    )
    for svc, call in sorted(calls.items()):
        wf = str(call["wf"])
        assert wf in wf_paths, f"{svc} 的对账腿指向 {wf}，但没取到它的 on.push.paths"
        raw = [str(p) for p in wf_paths[wf]]
        positives = [norm(p) for p in raw if not p.startswith("!")]
        negatives = [norm(p.lstrip("!")) for p in raw if p.startswith("!")]
        includes, excludes = leg_paths(call)
        assert includes, f"{svc} 的对账腿没有正向 pathspec"

        stray = sorted(set(includes) - set(positives))
        assert not stray, (
            f"{svc} 的对账腿判了 {wf} 的 `on.push.paths` **里没有**的路径 {stray}"
            f"（触发面 {positives}）⇒ 每次对账都会为不该部署的改动空转 dispatch"
        )
        missing = sorted(set(positives) - set(includes))
        unregistered = sorted(p for p in missing if (svc, p) not in entries)
        assert not unregistered, (
            f"🔴 {svc}：`{wf}` 的 `on.push.paths` 里有这些路径**没落在对账腿上**：{unregistered}\n"
            f"   ⇒ 它们一旦 push 触发被吞（auto-merge 的 GITHUB_TOKEN 抑制 / 连续快合并）就**静默不部署**"
            f"（#5668 `deploy/swas/nginx.conf`、#5676 的同款形态）。\n"
            f"   修法（二选一）：① 在 `deploy-reconcile.yml` 那条 `reconcile_one` 的第 4 个参数里补上它"
            f"（空格分隔；排除项写 `:(exclude)X`）；② 确实不该对账 ⇒ 在 "
            f"{LEDGER_PATH.name} 里逐条登记（带 `why`），并说明为什么静默可接受。"
        )
        assert sorted(excludes) == sorted(negatives), (
            f"{svc} 的排除项 {excludes} 与 `{wf}` 的 `on.push.paths` 排除项 {negatives} 不一致"
        )
        stale = sorted(p for (s, p) in entries if s == svc and p not in missing)
        assert not stale, (
            f"{svc} 的缺口台账里有**已不是缺口**的条目 {stale}（已被覆盖 / 已不是触发路径）"
            f"⇒ 台账只许缩短，请删掉它们"
        )
    for svc, _ in sorted(entries):
        assert svc in calls, f"缺口台账登记了不存在的对账腿 `{svc}`（陈旧条目）"


def check_canonical_configs_are_covered(wf_paths: dict, calls: dict) -> None:
    """三份 canonical 配置必须**同时**落在触发面与对账面上。

    ⚠️ 这条判据不能由「两处相等」代替：把**两边一起**收窄成 `deploy/swas/*.sh`（`*` 不跨 `/`
    ⇒ 不覆盖 `nginx.conf`）时两处仍然相等，但配置改动的静默不生效**照样复发**。
    """
    positives = [p for p in wf_paths[ADMIN_API_WF] if not p.startswith("!")]
    includes, _ = leg_paths(calls["admin-api"])
    for cfg in CANONICAL_SWAS_CONFIGS:
        assert any(glob_covers(p, cfg) for p in positives), (
            f"`{ADMIN_API_WF}` 的 `on.push.paths` {positives} **不覆盖** {cfg}"
            f" ⇒ 只改这份配置不触发任何部署腿（配置与镜像同源，配置改动必须由部署腿应用）"
        )
        assert any(leg_covers(q, cfg) for q in includes), (
            f"admin-api 对账腿的 pathspec {includes} **不覆盖** {cfg}"
            f" ⇒ 该配置改动的 push 触发被吞时，对账判定「无漂移」⇒ 静默不生效"
        )


# ══════════════════════════════════════════════════════════════════════════
# 判据 ②：应用面仍在（触发了部署 ≠ 配置被应用）
# ══════════════════════════════════════════════════════════════════════════

def check_applied_surface(text: str) -> None:
    for needle in APPLIED_SURFACE:
        assert needle in text, (
            f"`deploy/swas/deploy.sh` 里找不到应用面的 `{needle}` ⇒ 配置改动即使触发了部署也**落不了地**\n"
            "（这正是本单的另一半：触发面与应用面必须同时在位）"
        )
    assert 'UP_SERVICES="nginx"' in text, (
        "`nginx` 不再是 UP_SERVICES 的初值 ⇒ nginx 可能被逐服务循环跳过（配置不落地）"
    )


# ══════════════════════════════════════════════════════════════════════════
# 造仓库：C1（各腿路径 + 配置）→ C2（**只改一个文件**）→ D1（docs = HEAD）
# ══════════════════════════════════════════════════════════════════════════

def repo_with_single_change(tmp_path: Path, probe: str, name: str) -> dict:
    """造「只改了 `probe` 这一个文件」的 main 历史。

    每条对账腿的路径下各放一个 seed 文件（保证基线与腿一一对应），配置也在 C1 就位
    ⇒ C2 对 `probe` 是**修改**（不是新增），与线上事故的形态一致。
    """
    repo = tmp_path / name / "repo"
    repo.mkdir(parents=True)
    HARNESS.git(repo, "init", "-q", "-b", "main")
    for call in parse_calls().values():
        seed = repo / str(call["path"]) / "seed.txt"
        seed.parent.mkdir(parents=True, exist_ok=True)
        seed.write_text("seed", encoding="utf-8")
    target = repo / probe
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("v1", encoding="utf-8")
    if not (repo / CONFIG_ONLY_FILE).exists():
        cfg = repo / CONFIG_ONLY_FILE
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text("server { listen 80; }  # v1", encoding="utf-8")
    HARNESS.git(repo, "add", "-A")
    HARNESS.git(repo, "commit", "-qm", "code C1")
    c1 = HARNESS.git(repo, "rev-parse", "HEAD")

    target.write_text("v2 —— 只改这一个文件", encoding="utf-8")
    HARNESS.git(repo, "add", "-A")
    HARNESS.git(repo, "commit", "-qm", f"chore: 只改 {probe}")
    c2 = HARNESS.git(repo, "rev-parse", "HEAD")

    docs = repo / "docs" / "D1.md"
    docs.parent.mkdir(parents=True, exist_ok=True)
    docs.write_text("docs", encoding="utf-8")
    HARNESS.git(repo, "add", "-A")
    HARNESS.git(repo, "commit", "-qm", "docs D1")
    head = HARNESS.git(repo, "rev-parse", "HEAD")
    assert len({c1, c2, head}) == 3, "三个提交 sha 必须互不相同"
    return {"repo": repo, "C1": c1, "C2": c2, "head7": head[:7], "probe": probe}


def run_reconcile_on(tmp_path: Path, fx: dict, name: str, *, script_text: str | None = None):
    """在 `fx` 的仓库上跑对账正文（桩 gh/docker）；每次调用用**独立**临时目录（dispatch 日志不串）。"""
    scratch = tmp_path / name / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    return HARNESS.run_reconcile(
        scratch, fx["repo"], HARNESS.runs_all(fx["C1"], "success"),
        head7=fx["head7"], script_text=script_text,
    )


# ══════════════════════════════════════════════════════════════════════════
# 判据 ①（端到端自证）：只改 deploy/swas/nginx.conf 的 commit ⇒ 判定有漂移 ⇒ 会 dispatch
# ══════════════════════════════════════════════════════════════════════════

def test_config_only_commit_is_judged_as_drift_and_dispatches_a_deploy(tmp_path):
    """🔴 本单唯一的「真的会生效」证明：只动 `deploy/swas/nginx.conf` ⇒ **dispatch 部署腿**。

    历史 = C1（各腿路径 + 配置就位）→ C2（**只**改 `deploy/swas/nginx.conf`）→ D1（docs，HEAD）；
    基准 = C1 的成功部署（= 事故形态：C2 的 push 触发被吞）⇒ 对账必须判「有漂移」并
    `gh workflow run deploy-admin-api.yml`（该腿跑 `deploy.sh` ⇒ cp 配置 + nginx up/reload）。

    不给测试往 main 推任何提交（§「不真的推一个测试 commit」）。
    """
    fx = repo_with_single_change(tmp_path, CONFIG_ONLY_FILE, "config-only")
    proc, summary, dispatches = run_reconcile_on(tmp_path, fx, "config-only-run")

    assert proc.returncode == 0, f"对账正文非零退出 → {proc.stderr}\n{proc.stdout}"
    assert dispatches == [ADMIN_API_WF], (
        f"只改 `{CONFIG_ONLY_FILE}` 的 commit 必须触发且只触发 `{ADMIN_API_WF}`（配置与镜像同源，"
        f"配置靠这条腿的 `deploy.sh` 落地）→ 实得 {dispatches}\n{proc.stdout}"
    )
    assert "已 dispatch 补部署" in summary and ADMIN_API_WF in summary, f"summary 没写清动作 → {summary!r}"
    assert "判定 pathspec：backend/admin-api deploy/swas" in summary, (
        f"summary 没点名**判定所用的 pathspec** ⇒ 读的人会把「只改了配置」误读成「服务代码改了」\n{summary!r}"
    )
    assert fx["C2"][:7] in summary, f"summary 没给出判定依据（漂移 commit 的 sha）→ {summary!r}"
    assert "**结论**：dispatch=1" in summary, f"{summary!r}"


def test_config_only_criterion_has_discriminating_power(tmp_path):
    """🔴 红证①：把 `deploy/swas` 从 admin-api 腿上**拿掉**（= 改回改前的形态）⇒ 同一 diff **零 dispatch**。

    「不会红的判据 = 空断言」：这条证明上面那条判据真能判红（拿掉接线 ⇒ 静默不部署复现）。
    """
    real = HARNESS.reconcile_script()
    anchor = 'reconcile_one admin-api deploy-admin-api.yml backend/admin-api "deploy/swas"'
    assert anchor in real, f"注入点已漂移（判据过期）：{anchor!r}"
    broken = real.replace(anchor, 'reconcile_one admin-api deploy-admin-api.yml backend/admin-api ""')
    assert broken != real, "注入未生效（判据自证）"

    fx = repo_with_single_change(tmp_path, CONFIG_ONLY_FILE, "config-only-2")
    proc, summary, dispatches = run_reconcile_on(tmp_path, fx, "config-only-run-2", script_text=broken)
    assert proc.returncode == 0, f"注入后脚本应仍能跑完（只去掉一条 pathspec）→ {proc.stderr}"
    assert dispatches == [], f"拿掉接线后仍 dispatch ⇒ 上面那条判据没有判别力（空断言）→ {dispatches}"
    assert "无漂移" in summary, f"拿掉接线后应判「无漂移」（这正是静默形态）→ {summary!r}"


def test_narrowed_config_pathspec_criterion_has_discriminating_power(tmp_path):
    """🔴 红证④（执行式）：把对账面写成**不覆盖 `nginx.conf`** 的形态（`deploy/swas/*.sh`）⇒ 零 dispatch。

    `*` 不跨 `/` 且不匹配 `.conf` ⇒ 该形态看着像「接进去了」，实际仍静默（GitHub paths 与 git
    pathspec 同款陷阱）。
    """
    real = HARNESS.reconcile_script()
    anchor = 'reconcile_one admin-api deploy-admin-api.yml backend/admin-api "deploy/swas"'
    assert anchor in real, f"注入点已漂移（判据过期）：{anchor!r}"
    broken = real.replace(anchor, 'reconcile_one admin-api deploy-admin-api.yml backend/admin-api "deploy/swas/*.sh"')
    assert broken != real, "注入未生效（判据自证）"

    fx = repo_with_single_change(tmp_path, CONFIG_ONLY_FILE, "config-only-3")
    proc, _summary, dispatches = run_reconcile_on(tmp_path, fx, "config-only-run-3", script_text=broken)
    assert proc.returncode == 0, f"{proc.stderr}"
    assert dispatches == [], (
        f"`deploy/swas/*.sh` 不覆盖 `deploy/swas/nginx.conf`，却仍判「有漂移」⇒ 判据失效 → {dispatches}"
    )


# ══════════════════════════════════════════════════════════════════════════
# 判据 ③-a（执行式）：触发面的**每一条**正向路径都真的能落到自己的对账腿
# ══════════════════════════════════════════════════════════════════════════

def probe_path(pattern: str) -> str:
    """把触发面的一条正向 glob 落成**一个具体文件路径**（用于造「只改这个路径」的 commit）。"""
    return pattern[:-3] + "/probe.txt" if pattern.endswith("/**") else pattern


def test_every_deploy_trigger_path_reaches_its_reconcile_leg(tmp_path):
    """类级（执行式）：逐服务、**逐条**正向触发路径造「只改它」的 commit ⇒ 必须 dispatch 自己的腿。

    这是「两处路径集合一致」的**功能形态**：静态比对能对上、而执行上收不到（写成不覆盖的 glob、
    或判据把路径读错）的形态在这里必红。台账里的**存量缺口**（另 4 条腿，本单按裁定不动）逐条跳过
    —— 它们由 `check_trigger_paths_are_in_sync` 的台账判据点名，不许匿名存在。
    """
    calls = parse_calls()
    wf_paths = all_push_paths()
    entries = {(str(e["svc"]), norm(str(e["path"]))) for e in load_ledger()["entries"]}
    todo = [(svc, str(c["wf"]), p) for svc, c in sorted(calls.items())
            for p in wf_paths[str(c["wf"])] if not p.startswith("!") and (svc, norm(p)) not in entries]
    checked: list[str] = []
    for svc, wf, pattern in todo:
        probe = probe_path(pattern)
        fx = repo_with_single_change(tmp_path, probe, f"probe-{len(checked)}")
        proc, _summary, dispatches = run_reconcile_on(tmp_path, fx, f"probe-{len(checked)}-run")
        assert proc.returncode == 0, f"[{svc} · {pattern}] 对账正文非零退出 → {proc.stderr}\n{proc.stdout}"
        assert dispatches == [wf], (
            f"[{svc}] 触发面 `{pattern}` 上的改动没有落到自己的对账腿：期望 [{wf}]，实得 {dispatches}\n"
            f"⇒ 该路径的 push 触发被吞时会静默不部署（本单的病）\n{proc.stdout}"
        )
        checked.append(f"{svc}:{pattern}")
    assert checked == [f"{svc}:{p}" for svc, _wf, p in todo], (
        f"执行式覆盖与「触发面 − 台账」逐条不符（判据疑似空跑 / 跳过了路径）：{checked}"
    )
    assert checked, "一条路径都没覆盖 ⇒ 本判据在空集上恒真（空跑）"


# ══════════════════════════════════════════════════════════════════════════
# 判据 ③-b（静态）：逐服务双向比对 + 台账 + 三份 canonical 配置的覆盖
# ══════════════════════════════════════════════════════════════════════════

def test_trigger_paths_and_reconcile_legs_are_in_sync_for_every_service():
    """🔴 类级 meta-guard：**每一个**有 deploy workflow 的服务，触发面 ≡ 对账面（含台账）。"""
    calls, wf_paths, ledger = parse_calls(), all_push_paths(), load_ledger()
    assert len(calls) == len(GUARD.SVC_TO_DEPLOY_WORKFLOW), (
        f"腿数 {len(calls)} 与登记册 {len(GUARD.SVC_TO_DEPLOY_WORKFLOW)} 不符"
    )
    check_trigger_paths_are_in_sync(calls, wf_paths, ledger)


def test_canonical_swas_configs_are_covered_by_trigger_and_leg():
    """三份 canonical 配置（配置与镜像同源的**唯一**应用面）必须被两处同时覆盖。"""
    check_canonical_configs_are_covered(all_push_paths(), parse_calls())


def check_canonical_configs_match_the_deploy_script(text: str) -> None:
    """`CANONICAL_SWAS_CONFIGS` 声称的那三份必须**逐字**等于 `deploy.sh` 真正 `cp` 的那一组。

    真值在脚本的**应用面**（`cp src/deploy/swas/<f> ./...`）：只改一侧（脚本多/少应用一份，
    或常量随手改）⇒ 红 —— 否则「配置应用面 = 哪几份」这个前提会静默漂移，而上面的触发面/对账面
    判据会继续在**错的集合**上恒真。
    """
    copied = {f"deploy/swas/{n}" for n in re.findall(r"^cp src/deploy/swas/([A-Za-z0-9._-]+) \./", text, re.M)}
    assert copied == set(CANONICAL_SWAS_CONFIGS), (
        f"`deploy/swas/deploy.sh` 实际 `cp` 的配置 {sorted(copied)} 与本判据声称的三份 "
        f"{sorted(CANONICAL_SWAS_CONFIGS)} 不一致 ⇒ 「配置与镜像同源」的应用面变了（同源声明必须同批更新）"
    )


def test_canonical_configs_match_the_deploy_script_surface():
    """`CANONICAL_SWAS_CONFIGS` 与 `deploy.sh` 的应用面（`cp` 那一组）逐字一致。"""
    check_canonical_configs_match_the_deploy_script(
        (REPO_ROOT / "deploy" / "swas" / "deploy.sh").read_text(encoding="utf-8")
    )


def test_canonical_configs_same_source_criterion_has_discriminating_power():
    """🔴 红证：把应用面里 `cp nginx.conf` 那一行注入掉 ⇒ 同源判据必红（不是空断言）。"""
    text = (REPO_ROOT / "deploy" / "swas" / "deploy.sh").read_text(encoding="utf-8")
    check_canonical_configs_match_the_deploy_script(text)  # 前提：真文本先绿
    broken = text.replace("cp src/deploy/swas/nginx.conf ./nginx/nginx.conf", "true")
    assert broken != text, "注入未生效（判据自证）"
    with pytest.raises(AssertionError):
        check_canonical_configs_match_the_deploy_script(broken)


def test_meta_guard_red_proof_1_remove_config_glob_from_trigger(tmp_path):
    """🔴 红证①：从 `on.push.paths` 删掉 `deploy/swas/**` ⇒ 必红（触发面缺、对账面还在）。"""
    calls, wf_paths, ledger = parse_calls(), all_push_paths(), load_ledger()
    check_trigger_paths_are_in_sync(calls, wf_paths, ledger)  # 前提：真数据先绿
    broken = dict(wf_paths)
    broken[ADMIN_API_WF] = [p for p in wf_paths[ADMIN_API_WF] if p != CONFIG_TRIGGER]
    assert broken[ADMIN_API_WF] != wf_paths[ADMIN_API_WF], "注入未生效（判据自证）"
    with pytest.raises(AssertionError):
        check_trigger_paths_are_in_sync(calls, broken, ledger)


def test_meta_guard_red_proof_2_remove_config_from_reconcile_leg(tmp_path):
    """🔴 红证②：从 reconcile 的 admin-api 腿删掉 `deploy/swas` ⇒ 必红（对账面缺）。"""
    calls, wf_paths, ledger = parse_calls(), all_push_paths(), load_ledger()
    check_trigger_paths_are_in_sync(calls, wf_paths, ledger)
    broken = {k: dict(v) for k, v in calls.items()}
    broken["admin-api"]["excl"] = ""
    assert broken != calls, "注入未生效（判据自证）"
    with pytest.raises(AssertionError):
        check_trigger_paths_are_in_sync(broken, wf_paths, ledger)


def test_meta_guard_red_proof_3a_new_trigger_path_only_one_place(tmp_path):
    """🔴 红证③-a：触发面**新增**一条路径而没同步对账面（= 新增一条腿只写一处）⇒ 必红。"""
    calls, wf_paths, ledger = parse_calls(), all_push_paths(), load_ledger()
    check_trigger_paths_are_in_sync(calls, wf_paths, ledger)
    broken = dict(wf_paths)
    broken["deploy-frontend.yml"] = [*wf_paths["deploy-frontend.yml"], CONFIG_TRIGGER]
    with pytest.raises(AssertionError):
        check_trigger_paths_are_in_sync(calls, broken, ledger)


def test_meta_guard_red_proof_3b_new_leg_path_only_one_place(tmp_path):
    """🔴 红证③-b：对账面**新增**一条路径而触发面没有（防空转方向）⇒ 必红。"""
    calls, wf_paths, ledger = parse_calls(), all_push_paths(), load_ledger()
    check_trigger_paths_are_in_sync(calls, wf_paths, ledger)
    broken = {k: dict(v) for k, v in calls.items()}
    broken["admin-web"]["excl"] = "deploy/swas"
    with pytest.raises(AssertionError):
        check_trigger_paths_are_in_sync(broken, wf_paths, ledger)


def test_meta_guard_red_proof_3c_new_leg_without_registry_entry(tmp_path):
    """🔴 红证③-c：新增一条腿但没登记册条目（`SVC_TO_DEPLOY_WORKFLOW`）⇒ 必红（既有判据同源）。"""
    real = HARNESS.reconcile_script()
    extra = 'reconcile_one ghost deploy-admin-api.yml backend/ghost ""'
    broken = real.replace("reconcile_one admin-api", extra + "\nreconcile_one admin-api")
    assert broken != real, "注入未生效（判据自证）"
    with pytest.raises(AssertionError):
        GUARD.parse_reconcile_calls(broken)


def test_config_coverage_criterion_has_discriminating_power():
    """🔴 红证④（静态）：两处**一起**收窄成 `deploy/swas/*.sh` ⇒ 相等判据仍绿、覆盖判据必红。"""
    calls, wf_paths = parse_calls(), all_push_paths()
    check_canonical_configs_are_covered(wf_paths, calls)  # 前提：真数据先绿
    narrowed = "deploy/swas/*.sh"
    both = dict(wf_paths)
    both[ADMIN_API_WF] = [p if p != CONFIG_TRIGGER else narrowed for p in wf_paths[ADMIN_API_WF]]
    brokencalls = {k: dict(v) for k, v in calls.items()}
    brokencalls["admin-api"]["excl"] = narrowed
    # 两处**相等** ⇒ 同步判据不会红（证明「相等」不够，覆盖判据不可省）
    check_trigger_paths_are_in_sync(brokencalls, both, load_ledger())
    with pytest.raises(AssertionError):
        check_canonical_configs_are_covered(both, brokencalls)


def test_applied_surface_criterion_has_discriminating_power():
    """🔴 红证：把应用面（`cp` canonical 配置）注入掉 ⇒ 必红（否则本判据是空断言）。"""
    text = (REPO_ROOT / "deploy" / "swas" / "deploy.sh").read_text(encoding="utf-8")
    check_applied_surface(text)  # 前提：真文本先绿
    broken = text.replace("cp src/deploy/swas/nginx.conf ./nginx/nginx.conf", "true")
    assert broken != text, "注入未生效（判据自证）"
    with pytest.raises(AssertionError):
        check_applied_surface(broken)


# ══════════════════════════════════════════════════════════════════════════
# 判据 ④：另外 4 条对账腿**逐值不变**（本单只允许 admin-api 那条变）
# ══════════════════════════════════════════════════════════════════════════

def check_other_legs_frozen(calls: dict) -> None:
    """另外 4 条腿的调用点必须**逐字**等于冻结表（本单裁定：只加 admin-api 一条）。"""
    actual = {svc: {"wf": calls[svc]["wf"], "path": calls[svc]["path"], "extra": calls[svc]["excl"]}
              for svc in OTHER_LEGS_FROZEN if svc in calls}
    assert set(actual) == set(OTHER_LEGS_FROZEN), f"另外 4 条腿有缺失：{sorted(set(OTHER_LEGS_FROZEN) - set(actual))}"
    assert actual == OTHER_LEGS_FROZEN, (
        f"另外 4 条对账腿的调用点变了（本单裁定：只加 admin-api 一条）\n  期望 {OTHER_LEGS_FROZEN}\n  实得 {actual}"
    )


def test_other_reconcile_legs_are_unchanged():
    """🔴 另外 4 条腿的调用点冻结（改其中任何一条 ⇒ 红）。"""
    check_other_legs_frozen(parse_calls())


def test_other_legs_verdicts_are_unchanged(tmp_path):
    """🔴 执行式「逐值不变」：每条腿只在自己的路径上有改动时，判定仍只 dispatch 自己。"""
    calls = parse_calls()
    for idx, svc in enumerate(sorted(OTHER_LEGS_FROZEN)):
        wf = OTHER_LEGS_FROZEN[svc]["wf"]
        probe = probe_path(f"{calls[svc]['path']}/**")
        fx = repo_with_single_change(tmp_path, probe, f"leg-{idx}")
        proc, _summary, dispatches = run_reconcile_on(tmp_path, fx, f"leg-{idx}-run")
        assert proc.returncode == 0, f"[{svc}] {proc.stderr}\n{proc.stdout}"
        assert dispatches == [wf], f"[{svc}] 判定变了：期望 [{wf}]，实得 {dispatches}\n{proc.stdout}"


def test_other_legs_frozen_table_has_discriminating_power():
    """🔴 红证：把其中一条腿的路径改掉 ⇒ 冻结判据必红（不是只会因为「什么都没变」而绿）。"""
    calls = parse_calls()
    check_other_legs_frozen(calls)  # 前提：真数据先绿
    broken = {k: dict(v) for k, v in calls.items()}
    broken["admin-web"]["path"] = "frontend"
    assert broken != calls, "注入未生效（判据自证）"
    with pytest.raises(AssertionError):
        check_other_legs_frozen(broken)
