# case_ids: MC-130
r"""`.env.ai-agent` 凭据探针：**缺 key ⇒ 部署期可行动告警**（issue #7718 的裁定 B，2026-11-02）。

## 治的形态

`deploy/swas/deploy.sh` **从不写** `.env.ai-agent`（该文件人工维护）⇒ 2026-10-24 语音 / 生图切到
MaaS token-plan（#7661）之后，服务器那份仍停在**旧百炼 key**，线上 `401 InvalidApiKey` 被内核按
#7680 归入 `IMAGE_GEN_NO_KEY`，商家看到「商品图 AI 生成未配置完成」—— 而**部署链路没有任何面**会报
这件事，只能等人发现（#7718 的实测链）。

裁定（AI，2026-11-02）选 **B**：**不**把 MaaS 密钥接进 CI secret（A 会让「部署期」成为密钥的
唯一来源、扩大涉密面），只在部署链路加一条**只读探针**：缺 key ⇒ 打印**可行动告警**
（缺哪一项 / 怎么补 / 影响是什么），且**不打印密钥值**。

## 判据（每条都能单独变红）

| # | 判据 | 红证（怎么让它单独变红） |
|---|---|---|
| 1 | 缺 key ⇒ 输出含 `::warning::` + 键名 + 影响 + 补法，且 `MISSING=<N>` | 把探针段删掉 ⇒ 判据 7 的接线判据先红；把 `::warning::` 改成 `echo` ⇒ 告警面消失 ⇒ 红 |
| 2 | key 都在 ⇒ **不告警**（`::warning::` 零命中、`MISSING=0`） | 把「已设置」分支错写成告警 ⇒ 红 |
| 3 | **输出里绝不出现密钥值**（假值注入；含 8/12 字符前缀断言） | 把 `长度 N` 换成 `值=$_migao_ai_out` ⇒ 红 |
| 4 | **只读 + 不判失败**：退出码 0、env 文件逐字节不变、段内无 `exit` / 写动作 | 加 `exit 1` 或 `>> "$MIGAO_AI_ENV_FILE"` ⇒ 结构判据红 |
| 5 | **生图复用 ASR** 与运行期同口径（`IMAGE_GEN_API_KEY` 未配但 `ASR_API_KEY` 有 ⇒ **不**报缺） | 改成两键独立判 ⇒ 红（会与 `app/images/generator.py` 的复用语义对不上） |
| 6 | 键名 / 回落语义与 `backend/ai-agent-service/app/config.py`、`app/images/generator.py` **同源**（漂移守卫） | 把环境变量改名 / 删掉复用行 ⇒ 红 |
| 7 | **接线**：探针段在 deploy.sh 里、位于第 3 步健康检查循环**之后**（部署后自证），且**顶层执行**（首行代码顶格，不藏在函数 / if 体内） | 删段 / 挪到健康检查之前 / 把首行代码缩进进某个分支 ⇒ 红（判据 8 用同一份本体做注入式红证；位置锚是**代码符号**，不用中文文案） |

## 边界（照实登记，§19.1）

- 判的是**脚本语义 + 文本结构**，**不是**真实服务器：探针只在本地沙箱里跑（`MIGAO_AI_AGENT_ENV_FILE`
  指向 tmp_path 的假 `.env.ai-agent`），零网络、零容器、零真实密钥。
- **判不了**「服务器上那份 key 是不是**旧百炼 key 形态**」—— 探针只判「有没有」；形态 / 指纹判定属
  #7718 的线上自证（`sk-sp-…` / 长度 115）与 issue 记录的 hotfix，不在此射程。
- **不改任何门禁的通过条件、不新增豁免**；本文件不改线上、不改 `.env.ai-agent`。
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SH = REPO_ROOT / "deploy" / "swas" / "deploy.sh"
AI_AGENT_CONFIG = REPO_ROOT / "backend" / "ai-agent-service" / "app" / "config.py"
IMAGE_GENERATOR = REPO_ROOT / "backend" / "ai-agent-service" / "app" / "images" / "generator.py"

BLOCK_START = "# >>> ai-agent-key-probe"
BLOCK_END = "# <<< ai-agent-key-probe"

# 结构位置锚 = **代码符号**（ASCII），不用中文文案（issue #6802 的类级判据
# `test_cjk_position_anchor_guard.py` 禁止把文案级字符串当位置锚：注释里出现同一句话就会误伤）。
HEALTH_CHECK_ANCHOR = 'for spec in "8080 admin-api /actuator/health"'  # 第 3 步健康检查循环的起首行

# 探针必需项（真名以 app/config.py 为准；判据 6 守着这条「不许改名漂移」）。
REQUIRED_KEYS = ("PRIMARY_API_KEY", "VISION_API_KEY", "ASR_API_KEY", "IMAGE_GEN_API_KEY")

# 三条可行动要素：缺 key 时**必须**给出（只写「未配置」不算可行动）。
ACTIONABLE_MARKERS = ("影响：", "补法：", "AI_AGENT_KEY_STATUS=")


def _read(path: Path) -> str:
    assert path.exists(), f"缺 {path.relative_to(REPO_ROOT)}（判据的坐标对象不存在 ⇒ 不许静默跳过）"
    return path.read_text(encoding="utf-8")


def _deploy_block() -> str:
    """从 deploy.sh 里**原样**抽出探针段（真跑那一段，不是复刻第二份实现）。"""
    text = _read(DEPLOY_SH)
    assert BLOCK_START in text and BLOCK_END in text, (
        f"deploy.sh 里找不到探针段标记（{BLOCK_START} / {BLOCK_END}）——"
        "本判据要真跑那一段，标记是唯一锚点（删掉探针 ⇒ 这里必红）"
    )
    return text.split(BLOCK_START, 1)[1].split(BLOCK_END, 1)[0]


def _run_probe(env_file: Path, cwd: Path) -> subprocess.CompletedProcess:
    """真跑 deploy.sh 的凭据探针段（`env_file` 可以**不存在** —— 那正是「从未人工创建」的形态）。"""
    script = "set -euo pipefail\n"
    script += f"export MIGAO_AI_AGENT_ENV_FILE={shlex.quote(str(env_file))}\n"
    script += _deploy_block()
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env={k: v for k, v in os.environ.items() if k != "MIGAO_AI_AGENT_ENV_FILE"},
    )


def _write_env(path: Path, lines: list[str]) -> Path:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _code_lines(block: str) -> list[str]:
    """剥掉整行注释后的代码行 —— 判据只判「真的会执行的那一行」（注释里刻意引用了旧写法）。"""
    return [ln for ln in block.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


# ══════════════════════════════════════════════════════════════════════════════
# 判据本体（纯函数：文本进 → 违规清单出；注入式红证驱动**同一份本体**）
# ══════════════════════════════════════════════════════════════════════════════

def judge_probe_wiring(text: str) -> list[str]:
    """判据 7：探针段存在、在部署后（健康检查之后 / 收尾之前）、且是**只读 + 不判失败**。"""
    v: list[str] = []
    i_start = text.find(BLOCK_START)
    i_end = text.find(BLOCK_END)
    if i_start < 0 or i_end < 0 or i_end < i_start:
        return [f"deploy.sh 里找不到探针段标记（{BLOCK_START} / {BLOCK_END}）—— 探针没接进部署链路"]
    i_hc = text.find(HEALTH_CHECK_ANCHOR)
    if i_hc < 0:
        v.append(f"找不到健康检查循环的锚点 `{HEALTH_CHECK_ANCHOR}`（判据已过期，需重新定位）")
    elif i_start < i_hc:
        v.append("探针排在健康检查循环**之前** —— 那是在部署前查凭据，不是部署后自证")
    block = text[i_start:i_end]
    code = "\n".join(_code_lines(block))
    first_code = _code_lines(block)[0] if _code_lines(block) else ""
    if first_code != first_code.lstrip():
        v.append(f"探针段首行代码带缩进（= 藏在函数 / if 体内，未必会执行）：{first_code.strip()[:60]}")
    for line in code.splitlines():
        if line.lstrip().startswith("exit "):
            v.append(f"探针段出现 `exit`（缺 key 会让整次部署失败）：{line.strip()[:60]}")
    for forbidden in ("sed -i", "tee ", ">>", "rm ", "mv ", "truncate"):
        if forbidden in code:
            v.append(f"探针段出现写动作 / 破坏性动作「{forbidden}」—— 探针必须只读")
    for key in REQUIRED_KEYS:
        if key not in block:
            v.append(f"探针段没有检查 `{key}`（必需项被漏掉）")
    for marker in ACTIONABLE_MARKERS:
        if marker not in block:
            v.append(f"告警/结论面缺「{marker}」—— 缺 key 时给不出可行动信息")
    if "::warning::" not in block:
        v.append("探针段没有任何 `::warning::` —— 缺 key 时告警面消失（只在日志里说一句 = 没人看）")
    return v


def judge_no_secret_value(out: str, secrets: list[str]) -> list[str]:
    """判据 3：输出里**绝不出现**密钥值（含长前缀），且给了脱敏读数。"""
    v: list[str] = []
    for secret in secrets:
        if secret in out:
            v.append(f"输出里出现了**完整**密钥值（{secret[:4]}…）—— 探针泄密")
        for n in (12, 8):
            if len(secret) >= n and secret[:n] in out:
                v.append(f"输出里出现了密钥值的前 {n} 个字符（{secret[:4]}…）—— 只许打印长度")
    return v


# ══════════════════════════════════════════════════════════════════════════════
# 判据 1 / 2 / 5：缺 ⇒ 可行动告警；有 ⇒ 不告警；生图复用 ASR
# ══════════════════════════════════════════════════════════════════════════════

def test_probe_warns_actionably_for_each_missing_key(tmp_path):
    """判据 1：文件在、但关键项缺失 ⇒ 每一项都给出「影响 + 补法」，且 `MISSING=<N>` 对得上。"""
    env_file = _write_env(
        tmp_path / ".env.ai-agent",
        [
            "PRIMARY_MODEL=deepseek-flash",
            "PRIMARY_API_KEY=sk-prim-present-000000",
            # ASR_API_KEY / IMAGE_GEN_API_KEY 都缺
        ],
    )
    proc = _run_probe(env_file, cwd=tmp_path)
    assert proc.returncode == 0, f"缺 key 不许让部署失败：\n{proc.stdout}\n{proc.stderr}"
    out = proc.stdout

    assert "::warning::" in out, f"缺 key 没有任何告警面（商家侧继续 401）：\n{out}"
    assert "缺 **ASR_API_KEY**" in out, f"ASR_API_KEY 缺失没点名：\n{out}"
    assert "缺 **IMAGE_GEN_API_KEY**" in out, f"IMAGE_GEN_API_KEY 缺失没点名：\n{out}"
    assert "缺 **LLM_API_KEY**" not in out, f"PRIMARY_API_KEY 已设置却报缺（误报）：\n{out}"
    assert "✅ LLM_API_KEY（PRIMARY_API_KEY / VISION_API_KEY）：已设置" in out, out
    assert "MISSING=2" in out, f"机器可读结论与实况不符：\n{out}"
    assert "AI_AGENT_KEY_STATUS=" in out and "ASR_API_KEY:missing" in out, out

    # 可行动 = 受影响的能力 + 具体怎么补（不是只写「未配置」）。
    assert "语音识别 fail-closed" in out, f"ASR 告警没写影响：\n{out}"
    assert "建品页「AI 生成商品图」" in out, f"生图告警没写影响：\n{out}"
    assert "--force-recreate ai-agent" in out, f"补齐动作没给 recreate（env_file 不重读）：\n{out}"
    assert ".env.ai-agent" in out, f"补齐动作没点名要改哪个文件：\n{out}"
    assert "不判失败" in out, f"没写明「缺 key 不判失败」（会被读成部署失败）：\n{out}"


def test_probe_stays_quiet_when_all_keys_present(tmp_path):
    """判据 2：三项都在 ⇒ **零告警** + `MISSING=0`（否则运维会习惯性忽略告警）。"""
    env_file = _write_env(
        tmp_path / ".env.ai-agent",
        [
            "PRIMARY_API_KEY=sk-prim-present-111111",
            "ASR_API_KEY=sk-sp-asr-present-222222",
            "IMAGE_GEN_API_KEY=sk-sp-image-present-333333",
        ],
    )
    proc = _run_probe(env_file, cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "::warning::" not in out, f"key 齐全却告警（假告警会训练人忽略它）：\n{out}"
    assert "MISSING=0" in out, out
    for status in ("LLM_API_KEY:set", "ASR_API_KEY:set", "IMAGE_GEN_API_KEY:set"):
        assert status in out, f"状态行缺 {status}：\n{out}"


def test_missing_env_file_is_reported_not_fatal(tmp_path):
    """文件整个不在（从未人工创建）⇒ 告警 + 逐项点名 + 仍然退出 0。"""
    proc = _run_probe(tmp_path / ".env.ai-agent", cwd=tmp_path)
    assert proc.returncode == 0, f"文件缺失不许让部署失败：\n{proc.stdout}\n{proc.stderr}"
    out = proc.stdout
    assert "盘上没有" in out and ".env.ai-agent" in out, f"文件缺失没有单独点名：\n{out}"
    assert "MISSING=3" in out, f"三项都应判缺：\n{out}"


def test_image_gen_reuses_asr_key_like_runtime(tmp_path):
    """判据 5：只配 `ASR_API_KEY` ⇒ 生图**可用**（`generator.py` 的复用语义）⇒ 不许报缺。"""
    env_file = _write_env(tmp_path / ".env.ai-agent", ["ASR_API_KEY=sk-sp-asr-only-444444"])
    proc = _run_probe(env_file, cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "缺 **IMAGE_GEN_API_KEY**" not in out, (
        "ASR_API_KEY 在、IMAGE_GEN_API_KEY 空缺时生图会复用 ASR —— 报缺就是假告警\n" + out
    )
    assert "复用 ASR_API_KEY" in out, f"应明示复用关系（否则运维以为还要单独配一份）：\n{out}"
    assert "IMAGE_GEN_API_KEY:set" in out, out
    # 漂移守卫：运行期确实有这条复用（不是本判据自创口径）。
    generator = _read(IMAGE_GENERATOR)
    assert "settings.IMAGE_GEN_API_KEY or settings.ASR_API_KEY" in generator, (
        "generator.py 的复用语义变了 —— 探针的「生图复用 ASR」口径要跟着改"
    )


def test_quoted_and_duplicate_env_values_follow_env_file_semantics(tmp_path):
    """解析语义：成对引号去掉、空串算未设置、同名多行取**最后一行**（compose env_file 行为）。"""
    env_file = _write_env(
        tmp_path / ".env.ai-agent",
        [
            'ASR_API_KEY=""',
            "ASR_API_KEY=sk-sp-first-wins-not-555555",
            'ASR_API_KEY="sk-sp-quoted-666666"',
        ],
    )
    proc = _run_probe(env_file, cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    quoted = "sk-sp-quoted-666666"
    assert f"✅ ASR_API_KEY：已设置（长度 {len(quoted)}，值不打印）" in out, (
        f"引号没去掉 / 没取最后一行（长度应为 {len(quoted)}）：\n{out}"
    )
    assert "sk-sp-first-wins-not" not in out, f"同名多行取了第一行（与 compose 生效语义不符）：\n{out}"


# ══════════════════════════════════════════════════════════════════════════════
# 判据 3：绝不打印密钥值（假值注入）
# ══════════════════════════════════════════════════════════════════════════════

def test_probe_never_prints_secret_values(tmp_path):
    """判据 3：假值注入后，输出里不得出现任何值 / 长前缀；只许出现「长度 N」。"""
    secrets = [
        "sk-prim-Q7XQ7XQ7Q7SECRET",
        "sk-sp-ASR9ASR9ASR9SECRET",
        "sk-img-IMG5IMG5IMG5SECRET",
    ]
    env_file = _write_env(
        tmp_path / ".env.ai-agent",
        [
            f"PRIMARY_API_KEY={secrets[0]}",
            f"ASR_API_KEY={secrets[1]}",
            f"IMAGE_GEN_API_KEY={secrets[2]}",
        ],
    )
    proc = _run_probe(env_file, cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout + proc.stderr
    violations = judge_no_secret_value(out, secrets)
    assert not violations, "探针把密钥写进部署日志（会进 CI 日志 / issue）：\n" + "\n".join(violations) + f"\n---\n{out}"
    for secret in secrets:
        assert f"长度 {len(secret)}" in out, (
            f"没有给出脱敏长度读数（运维无法判断「旧 key 35 字节」这类形态）：\n{out}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 判据 4：只读 + 不判失败
# ══════════════════════════════════════════════════════════════════════════════

def test_probe_is_read_only_and_never_fails(tmp_path):
    """判据 4：三项全缺也退出 0；env 文件逐字节不变；不在 cwd 落任何文件。"""
    content = "ASR_API_KEY=\nPRIMARY_MODEL=deepseek-flash\n"
    env_file = tmp_path / ".env.ai-agent"
    env_file.write_text(content, encoding="utf-8")
    before = env_file.read_bytes()
    snapshot = sorted(p.name for p in tmp_path.iterdir())

    proc = _run_probe(env_file, cwd=tmp_path)
    assert proc.returncode == 0, f"缺 key ⇒ 探针不许判失败（那是运维态，不是构建失败）：\n{proc.stdout}\n{proc.stderr}"
    assert env_file.read_bytes() == before, "探针改了 .env.ai-agent —— 它是只读探针（写它需要新的下发通道）"
    assert sorted(p.name for p in tmp_path.iterdir()) == snapshot, "探针在 cwd 落了文件（只读探针不许有副作用）"


def test_probe_block_has_no_exit_and_no_write_actions():
    """判据 4（结构面）：段内没有 `exit` / 写动作 —— 与运行期读数互为独立两半。"""
    block = _deploy_block()
    code = "\n".join(_code_lines(block))
    for line in code.splitlines():
        assert not line.lstrip().startswith("exit "), f"探针段出现 exit：{line.strip()}"
    for forbidden in ("sed -i", "tee ", ">>", "rm ", "mv ", "truncate"):
        assert forbidden not in code, f"探针段出现写/破坏性动作「{forbidden}」—— 必须只读"
    assert "grep -E" in code, "探针不再读 env 文件（判据已过期）"


# ══════════════════════════════════════════════════════════════════════════════
# 判据 6：键名 / 回落语义与 ai-agent 配置同源（漂移守卫）
# ══════════════════════════════════════════════════════════════════════════════

def test_probe_key_names_match_ai_agent_config():
    """判据 6：四个键名都是 config.py 的字段，且 `LLM_API_KEY` 的回落语义逐字对得上。"""
    config = _read(AI_AGENT_CONFIG)
    for key in REQUIRED_KEYS:
        assert re.search(rf"^\s+{key}:\s*str", config, re.M), (
            f"config.py 里找不到字段 `{key}` —— 探针检查的键名与运行期配置漂移了"
        )
    assert "return self.PRIMARY_API_KEY or self.VISION_API_KEY" in config, (
        "LLM_API_KEY 的回落语义变了（PRIMARY → VISION）—— 探针的「二选一」口径要跟着改"
    )
    block = _deploy_block()
    for key in REQUIRED_KEYS:
        assert key in block, f"探针段没有检查 `{key}`"


# ══════════════════════════════════════════════════════════════════════════════
# 判据 7：接线（部署后自证）+ 判据 8：注入式红证
# ══════════════════════════════════════════════════════════════════════════════

def test_probe_is_wired_into_the_deploy_flow_after_health_check():
    """判据 7：段在 deploy.sh 里、在健康检查**之后**、收尾**之前**（= 部署后自证），且只读不判失败。"""
    text = _read(DEPLOY_SH)
    violations = judge_probe_wiring(text)
    assert not violations, "探针接线不合格：\n" + "\n".join(violations)


def test_red_proof_removing_the_probe_goes_red():
    """判据 8（红证）：把探针段从 deploy.sh 文本里摘掉 ⇒ **同一份本体**判红（判据不是空断言）。

    这是**内存注入**（不写盘）；PR body 另附一次**物理删段**的实跑读数（同一形态）。
    """
    text = _read(DEPLOY_SH)
    assert not judge_probe_wiring(text), "对照组：未注入时报违规（判据本身有缺陷）"
    start = text.find(BLOCK_START)
    end = text.find(BLOCK_END)
    assert 0 <= start < end, "反空跑锚点：找不到可摘除的探针段"
    injected = text[:start] + text[end + len(BLOCK_END):]
    violations = judge_probe_wiring(injected)
    assert violations, "摘掉探针后接线判据未红（判据无判别力 = 空断言）"
    assert any("找不到探针段标记" in s for s in violations), violations


def test_red_proof_deleting_the_warning_marker_goes_red():
    """判据 8（红证二）：把 `::warning::` 降级成普通 echo（告警面消失）⇒ 必红。"""
    text = _read(DEPLOY_SH)
    start, end = text.find(BLOCK_START), text.find(BLOCK_END)
    assert 0 <= start < end, "反空跑锚点：找不到探针段"
    block = text[start:end]
    stripped = block.replace("::warning::", "")
    assert stripped != block, "反空跑锚点：探针段里找不到 `::warning::`（判据已过期）"
    injected = text[:start] + stripped + text[end:]
    assert judge_probe_wiring(injected), "告警面被摘掉后接线判据未红"


def test_red_proof_probe_moved_before_health_check_goes_red():
    """判据 8（红证三）：把探针段挪到健康检查**之前**（部署前查）⇒ 位置判据必红。"""
    text = _read(DEPLOY_SH)
    start = text.find(BLOCK_START)
    end = text.find(BLOCK_END)
    assert 0 <= start < end
    block = text[start:end + len(BLOCK_END)] + "\n"
    removed = text[:start] + text[end + len(BLOCK_END):]
    i_hc = removed.find(HEALTH_CHECK_ANCHOR)
    assert i_hc > 0, "反空跑锚点：找不到健康检查锚点"
    injected = removed[:i_hc] + block + removed[i_hc:]
    violations = judge_probe_wiring(injected)
    assert any("部署前查凭据" in s for s in violations), violations
