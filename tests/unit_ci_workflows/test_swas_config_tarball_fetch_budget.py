# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 既有惯例：CI 结构类 L0 不变式统一挂 MC-012，
#   见 .github/cases/misc.yml 的 MC-012「CI workflow 行为由 tests/unit_ci_workflows/ 单测验证」。）
"""`deploy/swas/deploy.sh` **配置归档拉取**守卫 ——「预算 ≥ 600s ∧ 不依赖断点续传 ∧ ref 仍同源」（issue #6550）。

## 缺陷（**现取读数**，逐字来自失败 run 的远端输出，UTC）

测试环境三条部署腿（admin-api / frontend / ai-agent-service）对同一个 main HEAD `046298d` 全部 failure，
根因逐字相同 —— 服务器侧同步「与镜像 tag 同源」的 canonical 配置时，**整仓 tar.gz 在 120s 硬上限内下不完**：

| 时间(UTC) | ref | 已收 | 总量 | 折算速率 |
|---|---|---|---|---|
| 03:42:12 | 9ebdf73 | 26.0 MB | 66.55 MB | ~217 KB/s |
| 04:06:52 | 9ebdf73（重试） | 14.1 MB | 66.55 MB | ~118 KB/s |
| 04:31:32 | 03b1132（**回滚腿**） | 24.1 MB | 66.53 MB | ~201 KB/s |
| 04:56:32 | 046298d | 41.4 MB | 66.57 MB | ~345 KB/s |

⇒ 按最乐观的 345 KB/s 也要 ~193s > 120s ⇒ **不是偶发**；`deploy.sh` 的「失败即回滚」也因此回滚不了。

## 本文件锁什么（3 条判据，逐条可**单独**判红）

1. **预算有界且足够**：`deploy/swas/deploy.sh` 的配置归档拉取必须带 `--max-time <n>`，
   `n ≥ 600s`（下界**由实测推出**：`ARCHIVE_BYTES / 实测最慢速率 ≈ 566s`，见下 `measured_needed_secs()`），
   且 `n <` CI 侧单次尝试预算（`deploy/scripts/swas-deploy-ci.sh::C_BUILD_DEPLOY_TIMEOUT_SECONDS`）。
2. **不得依赖断点续传**（`-C -` / `--continue-at` **禁止**出现在这条拉取上）—— 这不是审美，是**实测**：
   ① `codeload` **不支持 Range**（本机只读实测 2026-10-08：`curl -r 0-1023 <tarball>` ⇒ **HTTP 200**
      + 整份 body 流式返回，响应头**没有** `content-range` / `accept-ranges`）；
   ② 半份 `src.tar.gz` 一旦存在，`-C -` 会发 `Range:`，服务器回 200 ⇒ curl **exit 33**
      「HTTP server doesn't seem to support byte ranges. Cannot resume.」（本地桩实测：文件停在 204800 字节、
      第二/第三次调用均 `rc=33`、**零进展**）；
   ③ 而半份文件**确实会被留下**：`deploy/swas/deploy.sh` 末尾那句 `rm -rf src src.tar.gz` 在
      `if [ -n "$BUILD_SERVICE" ]` **之内** ⇒ 非 C′ 路径不清它。
   ⇒ 加 `-C -` 会把「慢」换成「永久卡死」（下一次部署在 exit 33 上秒失败，要人工删文件才恢复）。
   （curl 自带的 `--retry` 也不续传：实测三次请求都不带 `Range`、半份文件被截断回原尺寸 ⇒ 重试仍从 0 重下。）
3. **ref 仍来自 `config_ref_for_tag`**：拉取 URL 仍是 `"$CONFIG_TARBALL_BASE/$CONFIG_REF_RESOLVED"`、
   推导仍是**恰好一处**的 `CONFIG_REF_RESOLVED=$(config_ref_for_tag "$TAG")`，且
   **权威判据** `tests/unit_ci_workflows/test_swas_deploy_config_pinning.py::judge_config_same_source`
   在改后仍判绿。⚠️ **本文件不重实现 ref 推导**（不另造第二套真相源）：推导逻辑的权威在那条判据里，
   这里只**调用**它，确保「这次拉取」这一侧没有绕过它。

## 反空跑锚点

取不到拉取行 / 取不到 CI 预算 / 取不到权威判据 ⇒ **显式失败**（不是「通过」）；判据本体读的是
**脚本当前文本**，不是「与某个历史版本等值」。
"""
import importlib
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SH = REPO_ROOT / "deploy" / "swas" / "deploy.sh"
CI_SCRIPT = REPO_ROOT / "deploy" / "scripts" / "swas-deploy-ci.sh"

# 配置归档拉取的那一行（唯一落点，issue #5083 钉过唯一性）
FETCH_ANCHOR = "-o src.tar.gz"

# 下界（issue #6550 方向 3：预算 ≥ 600s）。**由实测推出**：见 measured_needed_secs()
FLOOR_SECS = 600

# 四次失败 run 的「已收字节 / 用时毫秒」**逐字读数**（issue #6550）
MEASURED_SAMPLES = ((26040103, 120000), (14118222, 120000), (24146979, 120000), (41399245, 120000))
ARCHIVE_BYTES = 66570829  # 04:56:32Z 那条的「总量」逐字读数

# CI 侧单次尝试预算（锁等待上界 1800s + 冷构建上界 2400s + 余量 300s）
CI_BUDGET_RE = re.compile(
    r"C_BUILD_DEPLOY_TIMEOUT_SECONDS=\$\{SWAS_C_BUILD_DEPLOY_TIMEOUT_SECONDS:-(\d+)\}"
)
MAX_TIME_RE = re.compile(r"--max-time\s+(\d+)")
RESUME_RE = re.compile(r"(?:^|\s)(-C|--continue-at)(?:\s|=|$)")

URL_TOKEN = '"$CONFIG_TARBALL_BASE/$CONFIG_REF_RESOLVED"'
DERIVE_TOKEN = 'CONFIG_REF_RESOLVED=$(config_ref_for_tag "$TAG")'

# 权威判据（ref 同源的**唯一**真相源）。本文件只调用它，不复制它的实现。
AUTHORITY_MODULES = (
    "unit_ci_workflows.test_swas_deploy_config_pinning",
    "tests.unit_ci_workflows.test_swas_deploy_config_pinning",
    "test_swas_deploy_config_pinning",
)
AUTHORITY_SYMBOL = "judge_config_same_source"
AUTHORITY_LABEL = (
    "tests/unit_ci_workflows/test_swas_deploy_config_pinning.py::judge_config_same_source"
)


# ── 读源 + 反空跑锚点（取不到 ⇒ 显式失败，绝不静默空跑）─────────────────────────

def read_deploy_sh() -> str:
    assert DEPLOY_SH.is_file(), f"反空跑锚点：目标脚本不存在 → {DEPLOY_SH}"
    return DEPLOY_SH.read_text(encoding="utf-8")


def fetch_line_no(text: str):
    """定位配置归档拉取那一行 ⇒ `(行号, 该行原文)`；不是恰好一行 ⇒ 显式失败。"""
    hits = [
        (i + 1, ln)
        for i, ln in enumerate(text.splitlines())
        if "curl -fsSL" in ln and FETCH_ANCHOR in ln
    ]
    if len(hits) != 1:
        raise AssertionError(
            f"反空跑锚点：`deploy/swas/deploy.sh` 里 `curl -fsSL … {FETCH_ANCHOR}` 的行数是 "
            f"{len(hits)}（必须恰好 1）—— 判据已过期或配置下载出现了第二条路径；这不是「通过」"
        )
    return hits[0]


def ci_budget_secs() -> int:
    assert CI_SCRIPT.is_file(), f"反空跑锚点：CI 脚本不存在 → {CI_SCRIPT}"
    m = CI_BUDGET_RE.search(CI_SCRIPT.read_text(encoding="utf-8"))
    assert m, (
        "反空跑锚点：从 deploy/scripts/swas-deploy-ci.sh 里解析不出 "
        "`C_BUILD_DEPLOY_TIMEOUT_SECONDS=${SWAS_C_BUILD_DEPLOY_TIMEOUT_SECONDS:-<n>}` ⇒ 判据不能空跑"
    )
    return int(m.group(1))


def _authority_judge():
    """取权威判据 `test_swas_deploy_config_pinning::judge_config_same_source`（找不到 ⇒ 显式失败）。"""
    for mod in AUTHORITY_MODULES:
        try:
            fn = getattr(importlib.import_module(mod), AUTHORITY_SYMBOL)
        except Exception:  # noqa: BLE001 —— 换下一种导入路径再试
            continue
        assert callable(fn), f"反空跑锚点：{mod}.{AUTHORITY_SYMBOL} 不可调用"
        return fn
    raise AssertionError(
        f"反空跑锚点：取不到权威判据 {AUTHORITY_LABEL} —— 判据不能空跑"
        f"（试过 {AUTHORITY_MODULES}）"
    )


# ── 实测校准（下界不是拍的：由读数算出）────────────────────────────────────────

def measured_worst_rate_bps() -> float:
    """实测最慢速率（B/s）：四次读数里「已收 / 用时」的最小值。"""
    return min(recv / ms for recv, ms in MEASURED_SAMPLES) * 1000.0


def measured_needed_secs() -> float:
    """按实测最慢速率下完整仓归档所需的秒数。"""
    return ARCHIVE_BYTES / measured_worst_rate_bps()


# ── 判据本体（纯函数：文本进 → 违规清单出；注入式红证驱动**同一份本体**）──────

def judge_fetch_budget(text: str) -> list:
    """判据 1：拉取必须带 `--max-time <n>`，`FLOOR_SECS ≤ n < CI 单次尝试预算`。"""
    v = []
    no, line = fetch_line_no(text)
    m = MAX_TIME_RE.search(line)
    if not m:
        v.append(
            f"deploy/swas/deploy.sh:{no} 的配置归档拉取**没有** `--max-time`（无界下载会挂住部署）"
            f"：{line.strip()}"
        )
        return v
    got = int(m.group(1))
    need = measured_needed_secs()
    if got < FLOOR_SECS:
        v.append(
            f"deploy/swas/deploy.sh:{no} 的配置归档拉取预算过小：`--max-time {got}` < 下界 {FLOOR_SECS}s"
            f"（差 {FLOOR_SECS - got}s）。实测（issue #6550）：整仓归档 {ARCHIVE_BYTES} 字节、"
            f"服务器→codeload 最慢 {measured_worst_rate_bps() / 1000:.0f} KB/s ⇒ 需要 {need:.0f}s；"
            f"120s 上限下四次尝试一次都没下完。复算：`grep -n 'max-time' deploy/swas/deploy.sh`"
        )
    ci = ci_budget_secs()
    if got >= ci:
        v.append(
            f"deploy/swas/deploy.sh:{no} 的配置归档拉取预算 `--max-time {got}` **不小于** CI 侧单次尝试预算 "
            f"{ci}s（deploy/scripts/swas-deploy-ci.sh::C_BUILD_DEPLOY_TIMEOUT_SECONDS）⇒ 拉取会把整次尝试"
            f"挤过预算（CI 报硬超时、远端其实还在跑 ⇒ 假失败）。复算："
            f"`grep -n 'C_BUILD_DEPLOY_TIMEOUT_SECONDS' deploy/scripts/swas-deploy-ci.sh`"
        )
    return v


def judge_no_resume_flag(text: str) -> list:
    """判据 2：这条 codeload 拉取**不得**带 `-C -` / `--continue-at`（实测会让部署永久卡死）。"""
    no, line = fetch_line_no(text)
    if not RESUME_RE.search(line):
        return []
    return [
        f"deploy/swas/deploy.sh:{no} 给配置归档拉取加了断点续传（`-C -`/`--continue-at`）——**实测不可行且有害**："
        f"codeload 对 `Range:` 回 **HTTP 200**（无 `content-range`/`accept-ranges` 头 ⇒ 不支持 Range），"
        f"而 curl 在已有半份 `src.tar.gz` 时会 **exit 33**「HTTP server doesn't seem to support byte ranges. "
        f"Cannot resume.」且**零进展**；且非 C′ 路径（`BUILD_SERVICE` 为空）**不会**清掉半份文件"
        f"（末尾 `rm -rf src src.tar.gz` 在 `if [ -n \"$BUILD_SERVICE\" ]` 之内）⇒ 下一次部署秒失败。"
        f"复算：`grep -n -e '-C' -e 'continue-at' deploy/swas/deploy.sh`"
    ]


def judge_ref_still_from_authority(text: str) -> list:
    """判据 3：拉取 URL 仍消费 `$CONFIG_REF_RESOLVED`，且**权威判据**在改后仍判绿（不重实现推导）。"""
    v = []
    no, line = fetch_line_no(text)
    if URL_TOKEN not in line:
        v.append(
            f"deploy/swas/deploy.sh:{no} 的拉取 URL 不再使用 {URL_TOKEN} ⇒ ref 可能不再来自 `config_ref_for_tag`"
            f"（绝不回落 `refs/heads/main`，issue #5083）。复算：`grep -n 'CONFIG_REF_RESOLVED' deploy/swas/deploy.sh`"
        )
    if text.count(DERIVE_TOKEN) != 1:
        v.append(
            f"配置 ref 的推导不是恰好一处：`{DERIVE_TOKEN}` 出现 {text.count(DERIVE_TOKEN)} 次"
            f"（0 次 ⇒ 被绕过；>1 次 ⇒ 出现第二份真相源）"
        )
    sub = _authority_judge()(text)
    if sub:
        v.append(f"权威判据 {AUTHORITY_LABEL} 判红（ref 同源被破坏）：{sub[0]}")
    return v


def all_violations(text: str) -> list:
    return (
        judge_fetch_budget(text)
        + judge_no_resume_flag(text)
        + judge_ref_still_from_authority(text)
    )


# ── 一、静态判据（读脚本当前文本）─────────────────────────────────────────────

def test_real_script_satisfies_every_judgement():
    v = all_violations(read_deploy_sh())
    assert v == [], "配置归档拉取守卫判红（issue #6550）：\n- " + "\n- ".join(v)


@pytest.mark.parametrize("judge_name", [
    "judge_fetch_budget",
    "judge_no_resume_flag",
    "judge_ref_still_from_authority",
])
def test_each_judge_is_clean_on_the_real_script(judge_name):
    """逐条判据在真实脚本上各自干净（避免一条恒红被「整体红」掩盖）。"""
    v = globals()[judge_name](read_deploy_sh())
    assert v == [], f"{judge_name} 判红：\n- " + "\n- ".join(v)


def test_readings_are_named_and_recomputable():
    """具名读数：实际预算 / 下界 / CI 预算 / 实测最慢速率 ⇒ 需要多少秒。"""
    text = read_deploy_sh()
    no, line = fetch_line_no(text)
    got = int(MAX_TIME_RE.search(line).group(1))
    need = measured_needed_secs()
    ci = ci_budget_secs()
    assert FLOOR_SECS <= got < ci, f"读数为 --max-time={got}s（下界 {FLOOR_SECS}s / CI 预算 {ci}s）"
    assert need <= FLOOR_SECS, (
        f"实测校准失效：按最慢速率 {measured_worst_rate_bps() / 1000:.0f} KB/s 需要 {need:.0f}s，"
        f"已超过下界 {FLOOR_SECS}s ⇒ 下界该抬了（这正是本判据要拦住的手滑方向）"
    )
    print(
        f"[#6550] deploy/swas/deploy.sh:{no} --max-time={got}s"
        f"（下界 {FLOOR_SECS}s / CI 单次尝试预算 {ci}s；"
        f"实测最慢 {measured_worst_rate_bps() / 1000:.0f} KB/s ⇒ 需 {need:.0f}s）"
    )


def test_missing_fetch_anchor_fails_loudly():
    """反空跑：锚点取不到 ⇒ 判据显式失败（不是静默空跑成「通过」）。"""
    with pytest.raises(AssertionError):
        fetch_line_no("#!/bin/bash\necho 这里没有配置归档拉取\n")


def test_unparsable_ci_budget_fails_loudly(monkeypatch, tmp_path):
    """反空跑：CI 预算解析不出 ⇒ 显式失败。"""
    fake = tmp_path / "swas-deploy-ci.sh"
    fake.write_text("#!/bin/bash\nDEPLOY_TIMEOUT_SECONDS=900\n", encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "CI_SCRIPT", fake)
    with pytest.raises(AssertionError):
        ci_budget_secs()


def test_missing_authority_judge_fails_loudly(monkeypatch):
    """反空跑：权威判据取不到 ⇒ 显式失败（判据不能空跑）。"""
    monkeypatch.setattr(sys.modules[__name__], "AUTHORITY_MODULES", ("no_such_module_xyz",))
    with pytest.raises(AssertionError):
        _authority_judge()


# ── 二、注入式红证（每条判据各自可独立判红；注入必须真的落到文本上）──────────

def _inject_re(text: str, pattern: str, repl: str) -> str:
    """正则注入；**没替换到 ⇒ 显式失败**（否则「注入式红证」是空跑）。"""
    out, n = re.subn(pattern, repl, text, count=1)
    assert n == 1, f"注入锚点不存在（判据已过期）：{pattern!r}"
    assert out != text, "注入没有改变文本（空跑）"
    return out


def test_injected_old_120s_budget_turns_budget_judge_red():
    """判据 1 的红证：把预算改回**修复前**的 120s ⇒ 判据 1 红，判据 2/3 仍绿（单变量）。"""
    mutated = _inject_re(read_deploy_sh(), r"--max-time\s+\d+", "--max-time 120")
    assert judge_fetch_budget(mutated) != [], "预算退回 120s 后判据 1 没红（判据无判别力）"
    assert judge_no_resume_flag(mutated) == [], "预算退回不应影响判据 2"
    assert judge_ref_still_from_authority(mutated) == [], "预算退回不应影响判据 3"


def test_injected_budget_over_ci_budget_turns_budget_judge_red():
    """判据 1 的红证：预算抬到 ≥ CI 单次尝试预算 ⇒ 判据 1 红（另一个方向的越界）。"""
    ci = ci_budget_secs()
    mutated = _inject_re(read_deploy_sh(), r"--max-time\s+\d+", f"--max-time {ci + 100}")
    assert judge_fetch_budget(mutated) != [], "预算 ≥ CI 预算后判据 1 没红（判据无判别力）"


def test_injected_dropped_budget_turns_budget_judge_red():
    """判据 1 的红证：整条去掉 `--max-time`（无界下载）⇒ 判据 1 红。"""
    mutated = _inject_re(read_deploy_sh(), r"\s+--max-time\s+\d+", "")
    assert judge_fetch_budget(mutated) != [], "去掉 --max-time 后判据 1 没红（判据无判别力）"


def test_injected_resume_flag_turns_resume_judge_red():
    """判据 2 的红证：给拉取加上 `-C -`（issue #6550 方向 1 的建议形态）⇒ 判据 2 红，判据 1/3 仍绿。"""
    mutated = _inject_re(read_deploy_sh(), r"(curl -fsSL) ", r"\1 -C - ")
    assert judge_no_resume_flag(mutated) != [], "加 `-C -` 后判据 2 没红（判据无判别力）"
    assert judge_fetch_budget(mutated) == [], "加 `-C -` 不应影响判据 1"
    assert judge_ref_still_from_authority(mutated) == [], "加 `-C -` 不应影响判据 3"


def test_injected_main_ref_turns_ref_judge_red():
    """判据 3 的红证：把拉取 URL 换回 `refs/heads/main`（本单的病根形态）⇒ 判据 3 红。"""
    mutated = read_deploy_sh().replace(
        URL_TOKEN, '"https://codeload.github.com/zhaokai-mgzn/migao/tar.gz/refs/heads/main"', 1
    )
    assert mutated != read_deploy_sh(), "变异没生效 ⇒ 红证空跑"
    assert judge_ref_still_from_authority(mutated) != [], "回落 main 后判据 3 没红（判据无判别力）"
    assert judge_fetch_budget(mutated) == [], "回落 main 不应影响判据 1"


def test_injected_second_derivation_turns_ref_judge_red():
    """判据 3 的红证：删掉唯一那份推导（ref 变成硬编码）⇒ 判据 3 红。"""
    mutated = read_deploy_sh().replace(DERIVE_TOKEN, 'CONFIG_REF_RESOLVED="046298d"', 1)
    assert mutated != read_deploy_sh(), "变异没生效 ⇒ 红证空跑"
    assert judge_ref_still_from_authority(mutated) != [], "推导被删后判据 3 没红（判据无判别力）"


def test_comment_only_change_does_not_turn_guard_red():
    """对照读数：只改注释（不动那次调用）⇒ 守卫**不**红。"""
    mutated = read_deploy_sh() + "\n# 本次只加了一行注释（对照读数）\n"
    assert all_violations(mutated) == [], "只改注释就判红 ⇒ 守卫被自己的文案喂红"
