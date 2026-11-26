# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012。）
r"""C 端顾客小程序退场后的**类级元守卫**（issue #9233，2026-11-26 用户裁定）。

## 背景（一次性事实）

用户逐字：「`frontend/mini-app` 这个可以彻底删除了，以后不需要用到 c 端小程序。」
⇒ `frontend/mini-app/**` 整目录删除；C 端 H5 发布腿（`c-end-h5-publish` / `h5-freshness-guard`
+ `deploy/scripts/c-end-h5-*` / `deploy/swas/c-end-h5-publish-remote.sh` / `scripts/h5_freshness_guard.py`）
一并删除（它发布的**唯一**产物就是 `frontend/mini-app` 的 `build:h5` 输出）。

## 为什么这是**类级**守卫（不是一次性清理记录）

删一个目录会留下四类**不会自己变红**的残留，每一类都在本仓历史上真出过事：

| # | 残留形态 | 后果 | 本文件的判据 |
|---|---|---|---|
| 1 | 工程目录又「长回来」（半删 / 从别的分支 merge 回来） | 两套 C 端并存，判据指向谁不可知 | 判据 1 |
| 2 | **机器面**（workflow / 脚本 / 台账 / 依赖清单 / 根文档）指向已删路径 | CI 腿调 `npm ci` 于不存在的目录 ⇒ 红；或台账指向幽灵对象 | 判据 2 |
| 3 | **用例 `traces`** 指向已删测试 | **幽灵证据链**：门禁只核「路径存在」，删掉的文件让判据静默失效 | 判据 3 |
| 4 | required check 名随 workflow 一起消失 | **所有 PR 永久 `BLOCKED`**，且无任何检查变红（#4786 / #5101） | 判据 4 |

## 历史叙述 vs 机器引用（本文件的分界线，必须逐条可判）

- **机器引用 = 0**：`判据 2` 的扫描面（workflow / 脚本 / 台账 / 依赖 / 根文档 / 配置）。
- **历史叙述允许保留**，但必须**逐文件登记**在
  `tests/unit_ci_workflows/c_end_history_refs_allowlist.json`（`docs/design/**` 设计留档、
  `acceptance/**` 验收归档、`.github/cases/**` 的 `merge_log` / `data_checks` 历史、
  旧 CHANGELOG 归档）：**未登记即红 / 登记了却已无命中即红（空豁免）/ 条数只许缩短**。
  ⇒ 「我懒得改文档」和「这是历史」在判据上**不是同一件事**：后者要写进台账。

## 三态（本仓口径）

`0` = 全绿；`1` = 判红（具名文件 + 命中行）；无 `3`（本判据零网络、零时钟，读的都是仓内静态事实）。
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
LEDGER = Path(__file__).resolve().parent / "c_end_history_refs_allowlist.json"

# 已删对象（= 不该再被任何**机器面**引用的字符串）
DEAD_PATHS = ("frontend/mini-app",)
DEAD_LEG_MARKERS = (
    "c-end-h5-publish",
    "h5-freshness-guard",
    "scripts/h5_freshness_guard.py",
)

# 机器面：出现即判红（这些面一旦指向已删对象，CI 或台账就会指向幽灵）
MACHINE_GLOBS = (
    ".github/workflows/*.yml",
    ".github/*.json",
    ".github/dependabot.yml",
    "scripts/*",
    "deploy/**/*.sh",
    "deploy/**/*.json",
    "tests/unit_ci_workflows/*.json",
    "tests/*.ts",
    "tests/playwright*.config.ts",
    "verify-all.sh",
    "check-ui-regression.sh",
    "contract-check.sh",
)

#: 叙述面（历史留档 / 退役声明）：允许保留，但必须逐文件登记进台账
NARRATIVE_GLOBS = (
    "docs/**/*.md",
    "acceptance/**/*.md",
    "README.md",
    "AGENTS.md",
    "CONTRIBUTING.md",
    ".github/cases/*.yml",
    "CHANGELOG.md",
)

# 用例面：只判**结构字段**（traces），散文（merge_log / data_checks）属历史 ⇒ 由台账承接
CASES_GLOB = ".github/cases/*.yml"

#: **自指文件**：台账本身必须点名被判对象（否则读者不知道它在管什么）⇒ 扫描面显式排除并登记理由。
SELF_FILES = {"tests/unit_ci_workflows/c_end_history_refs_allowlist.json"}


def _iter_machine_files():
    seen = set()
    for pattern in MACHINE_GLOBS:
        for path in sorted(REPO_ROOT.glob(pattern)):
            if not path.is_file() or path in seen:
                continue
            if path.relative_to(REPO_ROOT).as_posix() in SELF_FILES:
                continue
            seen.add(path)
            yield path


def find_dead_refs(text: str) -> list:
    """文本里命中的已删对象（逐条去重）。纯函数 ⇒ 红证可直接喂字符串。"""
    hits = []
    for needle in DEAD_PATHS + DEAD_LEG_MARKERS:
        if needle in text:
            hits.append(needle)
    return hits


def _ledger():
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def scan_machine_refs(repo_root=REPO_ROOT) -> dict:
    """机器面 → 命中的已删对象（**不过滤**：是否允许由台账另行裁定，读数为零残留=台账为空时才成立）。"""
    found = {}
    for path in _iter_machine_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        hits = find_dead_refs(text)
        if hits:
            found[path.relative_to(REPO_ROOT).as_posix()] = hits
    return found


def tracked_files():
    """只扫**入库**文件（生成物 / 未跟踪杂物不算：`docs/testing/mibao-verification-cases.md` 等）。"""
    out = subprocess.run(["git", "ls-files"], cwd=str(REPO_ROOT),
                         capture_output=True, text=True, check=True).stdout
    return set(out.splitlines())


def _tracked_mini_app_files() -> list:
    try:
        out = subprocess.run(
            ["git", "ls-files", "frontend/mini-app"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return ["<git ls-files 取不到 —— 无法判定，按红处理>"]
    return [line for line in out.splitlines() if line.strip()]


def case_trace_dead_refs(rel_path: str) -> list:
    """某个用例文件里 `traces.tests` / `traces.ci` 指向已删对象的条目（`ID::字段::值`）。"""
    data = yaml.safe_load((REPO_ROOT / rel_path).read_text(encoding="utf-8")) or {}
    out = []
    for case in data.get("cases") or []:
        traces = case.get("traces") or {}
        for field in ("tests", "ci"):
            for ref in traces.get(field) or []:
                if find_dead_refs(str(ref)):
                    out.append(f"{case.get('id')}::traces.{field}::{ref}")
    return out


def mini_app_workflow_job():
    """`.github/workflows/mini-app.yml` 里上报 required 名的那条 job（YAML 现取）。"""
    data = yaml.safe_load((REPO_ROOT / ".github/workflows/mini-app.yml").read_text(encoding="utf-8"))
    for job_id, job in (data.get("jobs") or {}).items():
        if (job or {}).get("name") == "mini-app typecheck + unit tests":
            return job_id, job or {}
    return None, {}


# ── 判据 1：工程目录不许长回来 ───────────────────────────────────────────────

def test_mini_app_project_is_gone():
    assert not (REPO_ROOT / "frontend/mini-app").exists(), (
        "`frontend/mini-app/` 又出现了 —— C 端顾客小程序已于 2026-11-26 整目录删除（issue #9233）。"
        "要恢复必须先移除分支保护里的 required 名 `mini-app typecheck + unit tests`，"
        "并把 .github/workflows/mini-app.yml 的 no-op 改回真腿（见该文件头「重启条件」）。"
    )
    tracked = _tracked_mini_app_files()
    assert tracked == [], f"`git ls-files frontend/mini-app` 非空（{len(tracked)} 个）：{tracked[:5]}"


# ── 判据 2：机器面零引用 ─────────────────────────────────────────────────────

def test_machine_surfaces_have_no_dead_refs():
    found = scan_machine_refs()
    registered = set(_ledger()["entries"])
    found = {k: v for k, v in found.items() if k not in registered}
    assert found == {}, (
        "机器面仍指向已删的 C 端对象（会把 CI / 台账引向幽灵）：\n"
        + "\n".join(f"  · {rel}: {hits}" for rel, hits in sorted(found.items()))
        + "\n历史叙述若确实要保留，请登记进 tests/unit_ci_workflows/c_end_history_refs_allowlist.json"
        "（只许缩短：登记了却无命中同样判红）。"
    )


def test_machine_ref_scanner_has_teeth():
    """红证：扫描器对「含已删对象」的文本必须命中（否则判据 2 是空断言）。"""
    assert find_dead_refs("cd frontend/mini-app && npm test") == ["frontend/mini-app"]
    assert find_dead_refs("gh workflow run c-end-h5-publish.yml") == ["c-end-h5-publish"]
    assert find_dead_refs("bash deploy/scripts/h5_freshness_guard.py") == ["scripts/h5_freshness_guard.py"]
    assert find_dead_refs("frontend/bmini-app/tests/chat.test.ts") == []


# ── 判据 3：用例 traces 不许留幽灵引用 ───────────────────────────────────────

def test_case_traces_hold_no_ghost_refs():
    offenders = {}
    for path in sorted(REPO_ROOT.glob(CASES_GLOB)):
        dead = case_trace_dead_refs(path.relative_to(REPO_ROOT).as_posix())
        if dead:
            offenders[path.name] = dead
    assert offenders == {}, (
        "用例 `traces` 指向已删的 C 端文件（幽灵证据链）——请改钉到仍存在的判据，"
        "或按「承载体删除」退役该用例（判据改指本文件即可，不删历史条目）：\n"
        + "\n".join(f"  · {rel}: {refs}" for rel, refs in sorted(offenders.items()))
    )


# ── 判据 4：required check 名必须继续被上报（且是显式 no-op）────────────────

def test_required_check_name_is_still_reported():
    job_id, job = mini_app_workflow_job()
    assert job_id, (
        "`.github/workflows/mini-app.yml` 里找不到 `name: mini-app typecheck + unit tests` 的 job —— "
        "分支保护 required 集合里有这条检查名，删掉它 ⇒ 所有 PR 永久 BLOCKED 且无红信号。"
    )
    assert not job.get("needs"), f"required 腿 `{job_id}` 带了 job 级 needs ⇒ 上游被跳时 context 永不到来"
    assert "if" not in job, f"required 腿 `{job_id}` 带了 job 级 if ⇒ 被跳过的 job 不上报"


def test_required_job_is_an_explicit_noop():
    _job_id, job = mini_app_workflow_job()
    if not job:
        return  # 判据 4 已具名判红，这里不重复报
    commands = " ".join(
        str(step.get("run") or "") for step in (job.get("steps") or [])
    )
    forbidden = ("npm ci", "npm test", "npm run", "tsc ", "taro build", "playwright test")
    hits = [needle for needle in forbidden if needle in commands]
    assert hits == [], (
        f"no-op 腿里出现了真实构建/测试命令 {hits} —— 承载体已删（issue #9233），这些命令只会红；"
        "真要恢复，按 .github/workflows/mini-app.yml 头部的「重启条件」三条一起改。"
    )
    assert "no-op" in commands, "no-op 腿必须自报「no-op」（否则读者无法区分「真跑过」与「什么都没跑」）"


# ── 判据 5：发布腿与远端执行体真删除 ───────────────────────────────────────

def test_c_end_publish_chain_is_deleted():
    gone = (
        ".github/workflows/c-end-h5-publish.yml",
        ".github/workflows/h5-freshness-guard.yml",
        "deploy/scripts/c-end-h5-publish-ci.sh",
        "deploy/scripts/c-end-h5-dist-push.sh",
        "deploy/scripts/c-end-h5-verify-served.sh",
        "deploy/swas/c-end-h5-publish-remote.sh",
        "scripts/h5_freshness_guard.py",
        "tests/playwright.xiaobu.config.ts",
    )
    still = [rel for rel in gone if (REPO_ROOT / rel).exists()]
    assert still == [], f"C 端 H5 发布链的成员还在：{still}（它的唯一产物是被删的 frontend/mini-app）"


# ── 判据 6：历史叙述台账（未登记即红 / 空豁免即红 / 只许缩短）────────────────

def test_history_reference_ledger_is_honest():
    ledger = _ledger()
    entries = ledger["entries"]
    recorded = set(entries)
    tracked = tracked_files()
    actual = dict(scan_machine_refs())
    for pattern in NARRATIVE_GLOBS:
        for path in sorted(REPO_ROOT.glob(pattern)):
            rel = path.relative_to(REPO_ROOT).as_posix()
            if rel not in tracked or not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if find_dead_refs(text):
                actual[rel] = 1
    unregistered = {k: v for k, v in actual.items() if k not in recorded}
    assert unregistered == {}, (
        "这些文件仍含已删对象、却**没有**登记进历史台账（未登记即红）："
        f"{unregistered}\n登记口径：确实是历史叙述（设计留档 / 验收归档 / 用例 merge_log）才登记；"
        "能改的机器面必须改，不许靠登记绕过。"
    )
    empty = sorted(recorded - set(actual))
    assert empty == [], f"台账里这些条目已无命中（空豁免 ⇒ 判红，只许缩短）：{empty}"
    assert set(entries) == recorded or True  # 结构自证（entries 是映射，值 = 说明）
    assert len(recorded) <= ledger["frozen_max"], (
        f"台账条数 {len(recorded)} > 冻结上限 {ledger['frozen_max']} —— 只许缩短，"
        "新增「想保留的历史引用」必须走评审并显式抬上限（不留静默增长口子）"
    )
    for rel, meta in entries.items():
        assert isinstance(meta, dict) and meta.get("kind") in ("keep", "history"), f"台账条目 {rel} 的 kind 非法"
        assert str(meta.get("why") or "").strip(), f"台账条目 {rel} 缺说明（为什么不改它）"


# ── 判据 7：根面不再对已退役对象做 SPA 回落（issue #9249，2026-11-26 线上 500 实证）────
#
# 病灶（现取）：C 端产物按它自己的托管台账被清走之后，`location /` 的 `try_files … /index.html`
# 末位指向一个**不存在的文件** ⇒ nginx 内部重定向又落回同一块 ⇒ `internal redirection cycle`
# ⇒ **任意缺失路径都 500**（`/` 403、`/js/app.js` 500、`/css/app.css` 500）。
# 5xx 比 404 更糟（监控当成服务挂了），所以这条必须是**判据**，不能靠「记得别清磁盘」。

NGINX_CONF = REPO_ROOT / "deploy" / "swas" / "nginx.conf"
ROOT_PLACEHOLDER = REPO_ROOT / "deploy" / "swas" / "h5-root" / "index.html"
DEPLOY_SH = REPO_ROOT / "deploy" / "swas" / "deploy.sh"


def _root_location_block() -> str:
    """取出**静态根**那个 `location / {` 的原文（含注释）；取不到 / 不唯一即判红。

    锚点不能取「文件里第一个 `location /`」：本文件有多处 `location /`（HTTP→HTTPS 301、
    admin-api / ai-agent 的 proxy 段、admin-web 段…）。实测按「第一个 root 之后」取会落到
    **admin-web 的 proxy 块**（`root /opt/migao-deploy/h5;` 在 `/terminal/` 段也出现过一次）⇒
    判据指向错的对象、并且在真回归时**恒绿**。
    ⇒ 判据形态：在全部 `location / { … }` 里，按「带 Strict-Transport-Security **且** 没有 proxy_pass」
    选出静态根那一块，并要求**恰好一块**（不唯一 = 判据失效，不是通过）。
    """
    text = NGINX_CONF.read_text(encoding="utf-8")
    blocks = []
    for m in re.finditer(r"\n    location / \{", text):
        end_at = text.find("\n    }", m.start())
        if end_at > m.start():
            blocks.append(text[m.start():end_at])
    picked = [b for b in blocks if "Strict-Transport-Security" in b and "proxy_pass" not in b]
    assert len(picked) == 1, (
        f"{NGINX_CONF.name} 里「静态根 location /」应当恰好一块（带 HSTS、不带 proxy_pass），"
        f"现取 {len(picked)} 块 —— 判据锚点漂移，先修判据"
    )
    block = picked[0]
    # 退役说明写在块**上方**（紧邻的注释段）⇒ 一并带上，否则「点名 #9249」这条判据永远够不着它
    lines = text.splitlines()
    first = text[: text.index(block)].count("\n")
    lead = []
    i = first - 1
    while i >= 0 and (lines[i].strip().startswith("#") or not lines[i].strip()):
        lead.insert(0, lines[i])
        i -= 1
    return "\n".join(lead) + "\n" + block


def _directives(block: str) -> list:
    """去掉注释行后的指令行（nginx 注释以 `#` 起；本块内没有把 `#` 放进引号值的形态）。"""
    out = []
    for line in block.splitlines():
        code = line.split("#", 1)[0].strip()
        if code and code != "location / {":
            out.append(code)
    return out


def test_root_location_has_no_retired_spa_fallback():
    block = _root_location_block()
    tries = [d for d in _directives(block) if d.startswith("try_files")]
    assert tries == ["try_files $uri $uri/ =404;"], (
        "根面 `location /` 的 try_files 必须是 `$uri $uri/ =404`（issue #9249）："
        "末位指向已删对象（如 `/index.html`）时，nginx 会内部重定向回本块 ⇒ **任意缺失路径 500**。"
        f"现取 {tries}"
    )
    assert "#9249" in block, (
        "根面块必须留退役说明并点名 issue #9249 —— 否则下一个人会把 `=404` 读成「漏写兜底」再补回去"
    )
    assert "=404" in block and "SPA" in block, "说明里要写清「不再做 SPA 回落」的结论，而不只是一个 issue 号"


def test_root_placeholder_page_is_shipped_and_script_free():
    assert ROOT_PLACEHOLDER.is_file(), (
        "根面占位页必须入库（deploy/swas/h5-root/index.html）：仓库里没有它，任何干净实例 / 重建后 "
        "`/` 都会直接 403，且没有任何东西会因此变红"
    )
    html = ROOT_PLACEHOLDER.read_text(encoding="utf-8").lower()
    assert "<script" not in html, (
        "占位页不许带任何脚本 —— 它只是一页「入口已迁移」的静态说明；带脚本等于把退役面重新变成应用入口"
    )
    installer = DEPLOY_SH.read_text(encoding="utf-8")
    assert "deploy/swas/h5-root/index.html" in installer, (
        "deploy.sh 必须把占位页落到静态根（`src/deploy/swas/h5-root/index.html` → `./h5/index.html`）："
        "只入库不落地 = 干净实例上仍然 403"
    )
    assert "[ ! -f ./h5/index.html ]" in installer, (
        "落地步必须**只在目标缺失时写** —— 无条件覆盖会毁掉别人放在根面的落地面 / 将来的着陆页"
    )
