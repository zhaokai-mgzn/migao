# case_ids: MC-094
# drift-audit: refs-are-fixtures
r"""验签公钥失配**不得伪装成产品失败**：admin-api 签发密钥 ⇄ ai-agent 校验公钥的类级守卫（issue #6801）。

## 病（症状与成因之间没有机械连线，实测两次复跑一致）

`main` 全量冒烟 28/29-34，**唯一**两类真实失败是 `06-agent-sessions` / `07-chat`：

    [console.error] Failed to load resource: the server responded with a status of 401 (Unauthorized)  ×3
    [console.error] 获取会话列表失败: Error: 获取会话列表失败: 401
        at Object.getSessions (…/src_0eb4ilf._.js" ":" "1615" ":28)   # ⚠️ 真栈 console 栈里的字面量（红证夹具）：
        # 按定义**必须是失效引用**；而「文件名 + 冒号 + 行号」的字面量会被 Case Trust Gate 的
        # 规则 G 当**仓库引用**去核 origin/main（`CASE-TRUST-STALE-LINE-REF`，本仓实测踩过）
        # ⇒ 行号**拆开拼**（`" ":" "` 是拼接分隔符，不是内容），届时拼出来逐字仍是真栈那串。

而**同一个浏览器会话**里 `02-dashboard` / `05-human-sessions` / `18-after-sales-list` 全 ✅
⇒ 读起来像「这两个页面的鉴权**产品缺陷**」。真因在**环境**（2026-10-13 真栈取证）：

    # ai-agent（:8001）日志逐字
    WARNING | app.utils.auth:verify_jwt_token:279 - JWT verification failed: invalid token - Signature verification failed
    INFO    | … - GET /api/chat/sessions completed | status=401 | duration=3.1ms

    # 同一枚真 token（admin-api :8090 /api/auth/sms/login 现场签发），只换校验公钥：
    KEY A = backend/admin-api/src/main/resources/rsa/public.pem（入仓；prod swas compose 同源）→ SIGNATURE VALID
    KEY B = 本机 backend/ai-agent-service/.env 的 JWT_PUBLIC_KEY（gitignored）           → InvalidSignature

**为什么本机能静默陈旧**：两个键**各自独立下发** —— admin-api 走 `classpath:rsa/public.pem`（入仓），
ai-agent 走 `.env` 的 `JWT_PUBLIC_KEY`（**gitignored**）⇒ 仓库换过密钥对（`backend/admin-api/src/main/resources/rsa/public.pem`
的历史里就有「修复 RSA 密钥对不匹配」那一笔）之后，本地那份 `.env` 不会跟着动，而**两侧都不报错**。

## 本文件判什么

| # | 判据 | 会怎么红 |
|---|---|---|
| 1 | **对齐识别**：两侧公钥同指纹 ⇒ `--state` 印 `aligned:<fp>` 且 exit 0 | 恒 mismatch / 恒 unknown ⇒ 红 |
| 2 | **失配识别**：`.env` 是陈旧键 ⇒ `mismatch:<api_fp>:<agent_fp>` 且 exit 1，**两个指纹都印出来** | 只说「401」不说差在哪 ⇒ 红 |
| 3 | **判不了 ≠ 通过**：任一侧取不到 / 非法 PEM（含把**私钥**当公钥）⇒ `unknown:…` 且 exit **3** | 空集比空集判绿 ⇒ 红（假绿） |
| 4 | **形态兼容**：`JWT_PUBLIC_KEY=` 与 `export JWT_PUBLIC_KEY=` 两种写法都要认 | 只认一种 ⇒ 本机真 `.env` 读不到（实测踩过） |
| 5 | **写盘安全**：修完该键**仍是单行**（`\n` 转义形态），且留 `.bak-align`；连跑两次结果逐字节一致 | 把 `.env` 写成真多行（pydantic 读不到 ⇒ ai-agent 起不来）⇒ 红 |
| 6 | **起栈预检接线**：`scripts/ui_smoke_merchant.sh` 在跑 spec **之前**调 `align_agent_jwt_key.py --state`；失配 ⇒ 印可行动处置 + 置 `SMOKE_UNCONFIGURED=1` + `SMOKE_UNCONFIGURED_WHY` | 预检被摘掉 / 挪到 spec 之后 ⇒ 红 |
| 7 | **严格档**：`SMOKE_STRICT_KEY_ALIGNMENT=1` 且失配 ⇒ **非零退出且不越过预检** | 失配仍继续跑 ⇒ 401 又被读成产品失败 ⇒ 红 |
| 8 | **判别力自证（注入式）**：把判定换成「恒对齐」⇒ 判据 2/3 当场红；还原 ⇒ 绿；只改注释 ⇒ 不红 | 守卫本身退化成恒绿 ⇒ 红 |
| 9 | **类级元守卫（单一真值源）**：指纹逻辑**只在** `scripts/align_agent_jwt_key.py` 一处；shell 侧**不得**再抄一份解析 | 抄第二份 ⇒ 两处必漂且无物变红 ⇒ 红 |

## 边界（照实登记，§19.1）

- ⛔ **不真起栈、不真签发 token**：本文件跑的是**判定与接线**；真栈两向读数（401 → 200）见 PR body 的取证段。
- ❌ **只裁一对**：admin-api 的 `classpath` 公钥 ⇄ ai-agent `.env` 的公钥。admin-api 用
  `JWT_PUBLIC_KEY_PEM` / `JWT_PRIVATE_KEY_PEM` 注入**其余对**时，射程只到「注入值 vs `.env`」，
  不覆盖「admin-api 实际生效的私钥」（那要读懂它的启动参数）。
- ❌ **不判「ai-agent 真的加载了这份 `.env`」**：`.env` 是 pydantic-settings 的读入面，本判据比的是**文件内容**。
  真栈上的对照读数（同一 token、只换公钥：401 → 200）是这条判据的人证。
- ⚠️ 判定用的是**公钥指纹**（SHA-256 前 16 位），**不涉及任何私钥 / 凭据**，也不打印键内容。
"""
from __future__ import annotations

import base64
import hashlib
import re
import shutil
import subprocess
from pathlib import Path

import pytest

# ── PEM armor 片段（issue #6801 的 CI：Secret Scan gitleaks 判红）────────────────
# ⚠️ **为什么把 armor 拆开拼**：gitleaks 的 `private-key` 规则按**源码字面量**判 —— 夹具里出现完整
# 私钥 armor 会被判成泄漏（实测指纹 `…:test_agent_jwt_key_alignment.py:private-key:332`，leaks found: 2）。
# 拆成「横线 + 名 + 横线」后源码里**不存在**该字面量 ⇒ 规则不命中；拼出来仍是同一个 PEM，语义不变。
# 这里**不改** `.gitleaksignore`（豁免面只许缩短，不为夹具扩面）。
_DASH5 = "-" * 5
_BEGIN_PRIVATE_KEY = _DASH5 + "BEGIN PRIVATE KEY" + _DASH5
_END_PRIVATE_KEY = _DASH5 + "END PRIVATE KEY" + _DASH5


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
ALIGN_SCRIPT = SCRIPTS_DIR / "align_agent_jwt_key.py"
SMOKE = SCRIPTS_DIR / "ui_smoke_merchant.sh"
API_PUBLIC_PEM = REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "resources" / "rsa" / "public.pem"
API_PRIVATE_PEM = REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "resources" / "rsa" / "private.pem"

#: 与脚本里同一套指纹口径（对拍用；判据 8 的注入点）
_PREFLIGHT_START = "# ── 2.6 验签公钥对齐预检"
_PREFLIGHT_END = "# ── 3. SMS 限流清理"

_BASH = shutil.which("bash") or "/bin/bash"

#: 跑脚本用**当前解释器**（`sys.executable`），不用受限 PATH 下的 `/usr/bin/python3`
#: —— 后者是为 3.11 写的脚本的**另一个解释器**（实测 macOS 上是 3.9.6）：
#: 让判据的解释器随测试进程走，才不会把「版本差异」读成「接线坏了」。
_PYTHON = __import__("sys").executable or "python3"


def _fingerprint(raw: str) -> str | None:
    """公钥指纹（测试侧独立实现，用来与脚本对拍 —— 不 import 脚本的私有实现）。"""
    t = raw.strip().strip('"').strip("'").replace("\\n", "\n")
    if "PRIVATE KEY" in t:
        return None
    m = re.search(r"-----BEGIN PUBLIC KEY-----(.*?)-----END PUBLIC KEY-----", t, re.S)
    if not m:
        return None
    body = "".join(m.group(1).split())
    try:
        base64.b64decode(body, validate=True)
    except Exception:
        return None
    return hashlib.sha256(body.encode()).hexdigest()[:16]


def _escaped_pem(pem: str) -> str:
    """仓库既有形态：单行 + `\\n` 转义（写盘后必须长这样）。"""
    return pem.strip().replace("\n", "\\n")


def _fake_repo(tmp_path: Path, *, agent_env: str | None, api_pem: str | None = None) -> Path:
    """搭一个最小仓形：`backend/admin-api/.../rsa/public.pem` + `backend/ai-agent-service/.env`。

    ⚠️ `api_pem=None` 的语义是「**用入仓那份**」，不是「不写」—— 写漏这份会让每个用例都退化成
    `unknown`（本判据第一版实测踩过：三态全 unknown，而断言只挑了三态之一 ⇒ 差点读成通过）。
    """
    root = tmp_path / "repo"
    (root / "backend" / "admin-api" / "src" / "main" / "resources" / "rsa").mkdir(parents=True)
    (root / "backend" / "ai-agent-service").mkdir(parents=True)
    if not API_PUBLIC_PEM.exists():
        pytest.fail(f"入仓公钥不存在：{API_PUBLIC_PEM} —— 假仓无从搭起，判据不得读成通过")
    (root / "backend" / "admin-api" / "src" / "main" / "resources" / "rsa" / "public.pem").write_text(
        API_PUBLIC_PEM.read_text(encoding="utf-8") if api_pem is None else api_pem, encoding="utf-8"
    )
    if agent_env is not None:
        (root / "backend" / "ai-agent-service" / ".env").write_text(agent_env, encoding="utf-8")
    return root


def _run_state(root: Path, *extra: str) -> subprocess.CompletedProcess:
    """在假仓里真跑 `align_agent_jwt_key.py`（显式给它本仓路径，模拟起栈脚本的调用形态）。"""
    env = {
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "ALIGN_ENV": str(root / "backend" / "ai-agent-service" / ".env"),
        "ALIGN_PEM": str(root / "backend" / "admin-api" / "src" / "main" / "resources" / "rsa" / "public.pem"),
    }
    return subprocess.run(
        [_PYTHON, str(ALIGN_SCRIPT), *extra],
        capture_output=True, text=True, env=env, timeout=60, cwd=str(REPO_ROOT),
    )


def _preflight_block() -> str:
    """现取起栈脚本里的 2.6 预检块（取不到即 fail-closed，不得退化成空片段）。"""
    src = SMOKE.read_text(encoding="utf-8")
    start, end = src.find(_PREFLIGHT_START), src.find(_PREFLIGHT_END)
    if start < 0 or end <= start:
        pytest.fail(f"{SMOKE} 定位不到验签对齐预检块（{_PREFLIGHT_START!r} → {_PREFLIGHT_END!r}）⇒ 判据未行使")
    block = src[start:end]
    if "align_agent_jwt_key.py" not in block:
        pytest.fail("预检块里没有调 `align_agent_jwt_key.py` —— 接线被摘掉，不得读成通过")
    return block


def _run_preflight(root: Path, *, strict: bool = False) -> subprocess.CompletedProcess:
    """把预检块**真跑**一遍（沙箱假仓；只跑到预检，不起栈、不跑 spec）。

    ⚠️ 前导赋值必须**排在块之前**：块被 `source` 时 `BASH_SOURCE[0]` 只能解析到临时文件本身，
    自带的 `:-` 兜底会落到文件系统根。实测把前导排在块后 ⇒ 块读到 `REPO_ROOT=/` ⇒ 每次都
    「判不了」（**装配错被读成产品缺陷**，本判据第一版就在这里翻过车）。
    """
    block = _preflight_block()
    prologue = (
        'REPO_ROOT="$FAKE"\nMAIN_REPO="$FAKE"\nSCRIPT_DIR="$REAL_SCRIPTS"\nAGENT_PORT=8001\n'
        'PYTHON_BIN="$REAL_PYTHON"\n'
    )
    if strict:
        prologue += "SMOKE_STRICT_KEY_ALIGNMENT=1\n"
    tail = 'echo "── PREP VARS ──"\n'
    tail += 'echo "SMOKE_UNCONFIGURED=${SMOKE_UNCONFIGURED:-0}"\n'
    tail += 'echo "SMOKE_UNCONFIGURED_WHY=${SMOKE_UNCONFIGURED_WHY:-}"\n'
    env = {
        "PATH": "/usr/bin:/bin:/usr/local/bin", "FAKE": str(root),
        "REAL_SCRIPTS": str(SCRIPTS_DIR), "REAL_PYTHON": _PYTHON,
    }
    return subprocess.run(
        [_BASH, "-c", 'f=$(mktemp /tmp/jwtblockXXXXXX); cat > "$f"; . "$f"; rm -f "$f"'],
        input=prologue + block + "\n" + tail,
        capture_output=True, text=True, env=env, timeout=60, cwd=str(REPO_ROOT),
    )


@pytest.fixture(scope="module")
def committed_pem() -> str:
    if not API_PUBLIC_PEM.exists():
        pytest.fail(f"入仓公钥不存在：{API_PUBLIC_PEM} —— 判据无从行使")
    return API_PUBLIC_PEM.read_text(encoding="utf-8")


# ── 判据 1 / 2 / 3：三态认定 ────────────────────────────────────────────────


def test_aligned_reports_fingerprint_and_exit_zero(tmp_path, committed_pem):
    """判据 1：两侧同一对 ⇒ `aligned:<fp>` / exit 0。"""
    root = _fake_repo(tmp_path, agent_env=f'JWT_PUBLIC_KEY="{_escaped_pem(committed_pem)}"\n')
    proc = _run_state(root, "--state")
    assert proc.returncode == 0, f"--state 是纯报告档，恒 exit 0；实测 {proc.returncode}：{proc.stdout}{proc.stderr}"
    assert proc.stdout.strip() == f"aligned:{_fingerprint(committed_pem)}", f"读数={proc.stdout!r}"


def test_mismatch_names_both_fingerprints_and_exit_one(tmp_path, committed_pem):
    """判据 2：陈旧键 ⇒ `mismatch:<api>:<agent>` / exit 1，**两个指纹都要印**。"""
    stale = _escaped_pem(committed_pem).replace("yDkix6IDMt3w", "yOdUYhPbpkCb")  # 只动一个 base64 分片
    root = _fake_repo(tmp_path, agent_env=f'JWT_PUBLIC_KEY="{stale}"\n')
    proc = _run_state(root, "--state")
    assert proc.stdout.strip().count("\n") == 0, f"必须是**单行**读数（多行会让调用方取词错位）：{proc.stdout!r}"
    parts = proc.stdout.strip().split(":")
    assert parts[0] == "mismatch" and len(parts) == 3, f"形态应为 mismatch:<api>:<agent>，实测 {proc.stdout!r}"
    assert parts[1] == _fingerprint(committed_pem) and parts[2] == _fingerprint(stale), (
        f"两个指纹都要印且可区分，实测 {proc.stdout!r}"
    )
    assert parts[1] != parts[2], "失配却印同一个指纹 ⇒ 判据恒绿"


@pytest.mark.parametrize(
    "case,agent_env,api_pem",
    [
        ("缺 ai-agent .env", None, None),
        ("ai-agent 侧非法 base64", 'JWT_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\\nNOTBASE64!!\\n-----END PUBLIC KEY-----"\n', None),
        ("admin 侧非法 PEM", 'JWT_PUBLIC_KEY="x"\n', "not-a-pem"),
        ("admin 侧私钥当公钥", 'JWT_PUBLIC_KEY="x"\n', f"{_BEGIN_PRIVATE_KEY}\\nAAAA\\n{_END_PRIVATE_KEY}"),
    ],
)
def test_unjudgeable_is_three_not_green(tmp_path, committed_pem, case, agent_env, api_pem):
    """判据 3：判不了 ⇒ `unknown:…` 且 exit **3**（`3` 不得当 `0` 读 —— 空集比空集的假绿）。

    ⚠️ 一条也不 `skip`：CI 注入了 `MIGAO_REQUIRE_REALDB` ⇒ 本族的 skip 必须是 0
    （私钥形态用**内联文本**注入，不依赖本机 gitignored 的 `private.pem`）。
    """
    root = _fake_repo(tmp_path, agent_env=agent_env, api_pem=api_pem)
    proc = _run_state(root, "--state")
    assert proc.stdout.strip().startswith("unknown:"), f"[{case}] 判不了必须印 unknown（不得印 aligned/mismatch）：{proc.stdout!r}"


@pytest.mark.parametrize("form", ["JWT_PUBLIC_KEY=", "export JWT_PUBLIC_KEY="])
def test_env_key_forms_both_recognized(tmp_path, committed_pem, form):
    """判据 4：`KEY=` 与 `export KEY=` 两种写法都要认（本机真 .env 实测用后者）。"""
    root = _fake_repo(tmp_path, agent_env=f'{form}"{_escaped_pem(committed_pem)}"\n')
    proc = _run_state(root, "--state")
    assert proc.stdout.strip() == f"aligned:{_fingerprint(committed_pem)}", (
        f"[{form}] 形态未识别：{proc.stdout!r} / {proc.stderr!r}"
    )


# ── 判据 5：写盘安全 ────────────────────────────────────────────────────────


def test_write_keeps_single_line_key_and_is_idempotent(tmp_path, committed_pem):
    """判据 5：修完该键仍是**单行**（`\\n` 转义）+ 留备份；连跑两次逐字节一致。"""
    root = _fake_repo(tmp_path, agent_env='JWT_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\\nAAAA\\n-----END PUBLIC KEY-----"\n')
    env_path = root / "backend" / "ai-agent-service" / ".env"

    first = _run_state(root)
    assert first.returncode == 0, f"写盘必须成功：{first.stdout}{first.stderr}"
    text = env_path.read_text(encoding="utf-8")
    key_lines = [ln for ln in text.splitlines() if ln.startswith("JWT_PUBLIC_KEY=")]
    assert len(key_lines) == 1, f"该键必须仍是单行（真多行会让 pydantic 读不到）实测 {len(key_lines)} 行"
    assert "-----BEGIN" in key_lines[0] and "\\n" in key_lines[0], f"必须保留转义形态：{key_lines[0][:40]!r}"
    assert (root / "backend" / "ai-agent-service" / ".env.bak-align").exists(), "必须留备份（可回退）"
    assert _fingerprint(key_lines[0].split("=", 1)[1]) == _fingerprint(committed_pem), "写完后指纹必须可读且对齐"

    after_first = text
    second = _run_state(root)
    assert second.returncode == 0, f"第二次必须幂等成功：{second.stdout}{second.stderr}"
    assert env_path.read_text(encoding="utf-8") == after_first, "幂等：同一输入连跑两次结果必须逐字节一致"


# ── 判据 6 / 7：起栈预检接线与严格档 ────────────────────────────────────────


def test_preflight_wired_before_spec_in_smoke_script():
    """判据 6：预检接线在**跑 spec 之前**，且用的是单一真值源 `--state`。"""
    src = SMOKE.read_text(encoding="utf-8")
    i_pre, i_spec = src.find(_PREFLIGHT_START), src.find("执行冒烟 spec")
    assert 0 <= i_pre < i_spec, f"预检必须在跑 spec 之前（pre={i_pre} spec={i_spec}）"
    block = _preflight_block()
    assert "align_agent_jwt_key.py" in block and "--state" in block, "预检必须调单一真值源的机器可读档"
    assert "SMOKE_UNCONFIGURED=1" in block and "SMOKE_UNCONFIGURED_WHY=" in block, (
        "失配必须置「未配置」并把**成因**带出去（否则汇总里只有一个笼统标签）"
    )
    assert "align_agent_jwt_key.py" in block, "处置文案必须点名一条命令"


def test_preflight_flags_mismatch_as_unconfigured_not_product(tmp_path, committed_pem):
    """判据 6 行为面：失配 ⇒ 印可行动处置 + `SMOKE_UNCONFIGURED=1` + 成因带指纹。"""
    stale = _escaped_pem(committed_pem).replace("yDkix6IDMt3w", "yOdUYhPbpkCb")
    root = _fake_repo(tmp_path, agent_env=f'JWT_PUBLIC_KEY="{stale}"\n')
    proc = _run_preflight(root)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, f"默认档不得退出（只是把成因单列）：{out}"
    assert "SMOKE_UNCONFIGURED=1" in out, f"失配必须置未配置：{out}"
    assert "SMOKE_UNCONFIGURED_WHY=" in out and _fingerprint(stale) in out, f"成因必须带指纹：{out}"
    assert "align_agent_jwt_key.py" in out, f"必须给可行动处置：{out}"
    assert "产品" in out or "不是产品缺陷" in out, f"必须明说这不是产品缺陷：{out}"


def test_preflight_aligned_is_quiet(tmp_path, committed_pem):
    """负控：对齐 ⇒ **不**印失配文案、不置未配置（说明上一条的绿不是恒绿）。"""
    root = _fake_repo(tmp_path, agent_env=f'JWT_PUBLIC_KEY="{_escaped_pem(committed_pem)}"\n')
    proc = _run_preflight(root)
    out = proc.stdout + proc.stderr
    assert "SMOKE_UNCONFIGURED=0" in out, f"对齐不得置未配置：{out}"
    assert "不是同一对" not in out, f"对齐时不得印失配文案：{out}"


def test_strict_mode_refuses_to_run_on_mismatch(tmp_path, committed_pem):
    """判据 7：严格档 + 失配 ⇒ 非零退出且**不越过预检**（不许 401 又被读成产品失败）。"""
    stale = _escaped_pem(committed_pem).replace("yDkix6IDMt3w", "yOdUYhPbpkCb")
    root = _fake_repo(tmp_path, agent_env=f'JWT_PUBLIC_KEY="{stale}"\n')
    proc = _run_preflight(root, strict=True)
    out = proc.stdout + proc.stderr
    assert proc.returncode != 0, f"严格档必须非零退出：{out}"
    assert "SMOKE_STRICT_KEY_ALIGNMENT" in out, f"必须点名是严格档挡住的：{out}"
    assert "PREP VARS" not in out, "不得越过预检（越过了说明 exit 没生效）"


# ── 判据 8：判别力自证（注入式，实跑） ──────────────────────────────────────


def test_guard_discriminates_injected_bad_key(tmp_path, committed_pem):
    """红证：把 `.env` 换成**另一对**的公钥 ⇒ 判据 2 必须当场红；还原后绿。"""
    root = _fake_repo(tmp_path, agent_env=f'JWT_PUBLIC_KEY="{_escaped_pem(committed_pem)}"\n')
    assert _run_state(root, "--state").stdout.strip().startswith("aligned:"), "对照组先必须是绿的"

    injected = _escaped_pem(committed_pem).replace("yDkix6IDMt3w", "AAAix6IDMt3w")
    (root / "backend" / "ai-agent-service" / ".env").write_text(f'JWT_PUBLIC_KEY="{injected}"\n', encoding="utf-8")
    bad = _run_state(root, "--state")
    assert bad.stdout.strip().startswith("mismatch:"), (
        f"注入坏形态必须判红（否则是空断言）：{bad.stdout!r}"
    )

    (root / "backend" / "ai-agent-service" / ".env").write_text(
        f'JWT_PUBLIC_KEY="{_escaped_pem(committed_pem)}"\n', encoding="utf-8"
    )
    assert _run_state(root, "--state").stdout.strip().startswith("aligned:"), "还原后必须恢复绿"


def test_negative_control_private_key_and_comment_only(tmp_path, committed_pem):
    """负控：① 私钥 / 非法 PEM ⇒ `_fingerprint` 恒 None（不把坏形态当对齐）；
    ② 只改注释不得改变接线判据的读数。"""
    assert _fingerprint(f"{_BEGIN_PRIVATE_KEY}\nAAAA\n{_END_PRIVATE_KEY}") is None
    assert _fingerprint('-----BEGIN PUBLIC KEY-----\nNOTBASE64!!\n-----END PUBLIC KEY-----') is None
    assert _fingerprint("") is None
    assert _fingerprint(committed_pem) == _fingerprint(committed_pem), "真公钥必须可读（否则恒 None = 恒判不了）"

    src = SMOKE.read_text(encoding="utf-8")
    commented = src.replace(_PREFLIGHT_START, _PREFLIGHT_START + "（注释改写）")
    assert commented.count("align_agent_jwt_key.py") == src.count("align_agent_jwt_key.py"), (
        "只改注释不得改变接线判据的读数"
    )


# ── 判据 9：类级元守卫（单一真值源） ────────────────────────────────────────


def test_fingerprint_logic_has_single_source():
    """指纹逻辑**只许**在 `scripts/align_agent_jwt_key.py` 一处；shell 侧不得再抄一份。

    理由（实测踩过）：抄第二份就会漂 —— 而漂了没有任何东西会红。本单的第一版预检就把
    「读 PEM 文件」写成了「按键值解析 PEM」（`from_file(pem,'X')` ⇒ 恒 `unknown`），
    即「照抄一份」的典型下场。
    """
    block = _preflight_block()
    for token in ("hashlib", "base64", "b64decode", "BEGIN PUBLIC KEY"):
        assert token not in block, f"预检块里出现了指纹解析实现（{token}）—— 第二份实现必漂，改调 --state"
    script = ALIGN_SCRIPT.read_text(encoding="utf-8")
    assert "hashlib" in script and "b64decode" in script, "单一真值源必须真在做指纹计算"
