# case_ids: MC-148
"""本地 E2E 认证链的**复用判据**：只复用「token 自己还没过期」的 `admin.json`（issue #6411）。

## 病灶（issue #6411 逐字读数，2026-10-06）

`tests/e2e/fixtures/auth.setup.ts` 的复用判据只有一条 `age < 3600_000`（文件 mtime 与 1 小时比），
**不校验 token 是否还有效** ⇒ 复用窗口（1h）> 登录态真实有效期（实测约 30 分钟；
同一份 `admin.json` 10:15:40 生成、10:23 全绿、10:49 起全红且 mtime 未变）
⇒ 复用一个已失效的 token，**所有 spec 连带红，且没有任何一句话指向「登录态过期」**
（判别性对照：同一时刻代码一字未改的 UI-056 也 3/3 红）。

## 判据（都**会红**）

- **判据 1（行为面）**：token 的 `exp` 已过 ⇒ `reuse=false` / `reason=token-expired`；
  **文件 mtime 仍新鲜（1 分钟内）**也照样判「需重登」。修前的 mtime 判据在这里会判「可复用」
  ⇒ 本判据在修前必红（红证见判据 4）。
- **判据 2（行为面·负控）**：`exp` 还有 30 分钟 ⇒ `reuse=true`；且**即使 mtime 已 2 小时**
  （超出旧窗口）仍判可复用 —— 证明判据由 `exp` 主导，不是把阈值从 1h 调成 30min。
- **判据 3（行为面·兜底出声）**：token 不是合法 JWT（`E2E_MOCK_AUTH` 的占位 token）⇒ 回落 mtime，
  且 `message` 里**明写**「按 mtime 兜底」（不许静默）；mtime 过期 ⇒ `mtime-fallback-stale` 判需重登。
- **判据 4（判别力自证 / 红证）**：把 `exp` 解析摘掉（回到只看 mtime 的历史口径）⇒ 判据 1 的断言
  **全部不成立**，而「`exp` 未过期 ⇒ 可复用」这一结论仍成立（这正是「只调窗口从 1h 到 30min」
  抓不到本缺陷的原因）；注入只落在 tmp，仓内模块逐字节未变。
  实测读数（注入后）：**5 failed / 3 passed**；恢复后 **8 passed**。
- **判据 5（静态面·接线 + 自愈）**：`auth.setup.ts` 用共享判定器、把结论**打印出来**、
  不再有裸 mtime 窗口直接 `return`，且判定为「需重登」时**继续走真登录**（自愈，不是报错退出）。

判定器 = `tests/e2e/helpers/auth-state-freshness.mjs`，用**真 node** 执行（不是静态字符串匹配）；
与 `tests/e2e/helpers/api-base-url.mjs` 同一范式（无依赖 `.mjs` + 真跑）。

## 边界（照实登记）

- 判据**不跑真 Playwright / 真后端**：`exp` 解析与复用判定是纯函数（时钟可注入），
  「真起 admin-api 后 auth.setup 能否自愈」不在本判据射程内 —— 那属环境事实（本机常态不起 admin-api，
  见 issue #6411 的「剩下那一半在仓外」），由 PR body 明确登记。
- 判据只看 `exp`：token 被提前吊销 / 服务端换密钥时 `exp` 仍可能未到，本模块不判、也不声称判。
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DECISION = REPO_ROOT / "tests" / "e2e" / "helpers" / "auth-state-freshness.mjs"
SETUP = REPO_ROOT / "tests" / "e2e" / "fixtures" / "auth.setup.ts"

#: 固定时钟（毫秒）—— 判定器把 `now` 作为入参，判据因此**不受挂钟影响**（不会跨午夜变红/变绿）。
NOW_MS = 1_700_000_000_000

#: `E2E_MOCK_AUTH=true` / 登录失败兜底时写进 storageState 的占位 token（不是 JWT）。
NON_JWT_TOKEN = "e2e-mock-token"


def _node() -> str:
    node = shutil.which("node")
    assert node, "node 不可用（本判据的结构前提：复用判定必须用真 node 跑一次）"
    return node


def _b64url(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _jwt(exp_ms: int) -> str:
    """造一个带 `exp` 的合法 JWT（只看 payload 的 `exp`，签名不参与判定）。"""
    header = _b64url({"alg": "HS256", "typ": "JWT"})
    payload = _b64url({"sub": "1", "exp": exp_ms // 1000})
    return f"{header}.{payload}.sig"


def _state(token: str, *, with_cookie: bool = True) -> dict:
    """`admin.json` 的真实形态：`access_token` cookie + zustand persist 的 `auth-storage`。"""
    cookies = (
        [
            {
                "name": "access_token",
                "value": token,
                "domain": "localhost",
                "path": "/",
                "expires": -1,
                "httpOnly": False,
                "secure": False,
                "sameSite": "Lax",
            }
        ]
        if with_cookie
        else []
    )
    persist = {"state": {"accessToken": token, "isAuthenticated": True}, "version": 0}
    return {
        "cookies": cookies,
        "origins": [
            {
                "origin": "http://localhost:3001",
                "localStorage": [{"name": "auth-storage", "value": json.dumps(persist)}],
            }
        ],
    }


def _decide(options: dict, module: Path | None = None) -> dict:
    """用真 node 跑判定器，回吐它的决策对象（`reuse` / `source` / `reason` / `message`）。"""
    target = module or DECISION
    script = (
        "import { decideAuthStateReuse } from " + json.dumps(target.as_uri()) + ";"
        "const input = JSON.parse(process.env.E2E_AUTH_DECISION_INPUT);"
        "console.log('__RESULT__' + JSON.stringify(decideAuthStateReuse(input)));"
    )
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", "/tmp"),
        "E2E_AUTH_DECISION_INPUT": json.dumps(options, ensure_ascii=False),
    }
    proc = subprocess.run(
        [_node(), "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, (
        "Node 执行判定器失败 ⇒ 判据空转，故这里必须红：\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    m = re.search(r"__RESULT__(\{.*\})\s*$", proc.stdout.strip(), re.M | re.S)
    assert m, f"判定器没有回吐决策对象（空跑）：\n{proc.stdout}\n{proc.stderr}"
    return json.loads(m.group(1))


# ── 判据 1（行为面）：exp 已过 ⇒ 需重登，mtime 再新鲜也不复用 ──────────────────


def test_expired_token_is_not_reused_even_when_the_file_is_fresh() -> None:
    decision = _decide(
        {
            "storageState": _state(_jwt(NOW_MS - 10 * 60_000)),
            "mtimeMs": NOW_MS - 60_000,  # 1 分钟前刚写 ⇒ 旧判据（1h 窗口）会判「可复用」
            "now": NOW_MS,
        }
    )
    assert decision["reuse"] is False, (
        "token 的 exp 已过 10 分钟却被判「可复用」—— 这正是 issue #6411 的形态"
        f"（复用一个已失效的登录态）：{decision}"
    )
    assert decision["reason"] == "token-expired", decision
    assert decision["source"] == "jwt-exp", f"有 exp 时不得回落到 mtime：{decision}"
    assert decision["remainingMs"] < 0, decision


# ── 判据 2（行为面·负控）：exp 主导，不是把窗口从 1h 调成 30min ────────────────


def test_token_with_thirty_minutes_left_is_reused() -> None:
    decision = _decide(
        {
            "storageState": _state(_jwt(NOW_MS + 30 * 60_000)),
            "mtimeMs": NOW_MS - 5 * 60_000,
            "now": NOW_MS,
        }
    )
    assert decision["reuse"] is True, decision
    assert decision["reason"] == "token-fresh", decision
    assert decision["remainingMs"] == 30 * 60_000, decision


def test_fresh_token_is_reused_even_when_mtime_exceeds_the_old_window() -> None:
    """mtime 已 2 小时（旧的 1h 窗口会判「重登」）但 token 还有效 ⇒ 仍可复用（exp 才是真值）。"""
    decision = _decide(
        {
            "storageState": _state(_jwt(NOW_MS + 30 * 60_000)),
            "mtimeMs": NOW_MS - 2 * 3600_000,
            "now": NOW_MS,
        }
    )
    assert decision["reuse"] is True, f"exp 未过期时 mtime 不应参与判定：{decision}"
    assert decision["source"] == "jwt-exp", decision


def test_token_expiring_inside_the_safety_margin_forces_relogin() -> None:
    """距 exp 只剩 2 分钟（< 5 分钟余量）⇒ 需重登，避免跑到一半在 spec 里过期。"""
    decision = _decide(
        {
            "storageState": _state(_jwt(NOW_MS + 2 * 60_000)),
            "mtimeMs": NOW_MS - 10 * 60_000,
            "now": NOW_MS,
        }
    )
    assert decision["reuse"] is False, decision
    assert decision["reason"] == "token-expiring", decision


def test_token_is_read_from_zustand_state_when_the_cookie_is_absent() -> None:
    """cookie 缺失时仍能从 `auth-storage` 解出 token —— 否则会静默回落 mtime（本缺陷的旧形态）。"""
    decision = _decide(
        {
            "storageState": _state(_jwt(NOW_MS - 10 * 60_000), with_cookie=False),
            "mtimeMs": NOW_MS - 60_000,
            "now": NOW_MS,
        }
    )
    assert decision["source"] == "jwt-exp", f"未从 localStorage 取到 token：{decision}"
    assert decision["reuse"] is False, decision


# ── 判据 3（行为面·兜底出声）：解不出 exp ⇒ 回落 mtime 且明写「按 mtime 兜底」 ──


def test_unparseable_token_falls_back_to_mtime_and_says_so() -> None:
    fresh = _decide(
        {
            "storageState": _state(NON_JWT_TOKEN),
            "mtimeMs": NOW_MS - 60_000,
            "now": NOW_MS,
        }
    )
    assert fresh["source"] == "mtime", fresh
    assert fresh["reason"] == "mtime-fallback-fresh", fresh
    assert fresh["reuse"] is True, fresh
    assert "mtime" in fresh["message"] and "兜底" in fresh["message"], (
        f"回落 mtime 时必须**出声**（明写按 mtime 兜底），不许静默：{fresh}"
    )

    stale = _decide(
        {
            "storageState": _state(NON_JWT_TOKEN),
            "mtimeMs": NOW_MS - 2 * 3600_000,
            "now": NOW_MS,
        }
    )
    assert stale["source"] == "mtime", stale
    assert stale["reason"] == "mtime-fallback-stale", stale
    assert stale["reuse"] is False, stale
    assert "mtime" in stale["message"], f"判「需重登」时同样要出声：{stale}"


# ── 判据 4（判别力自证 / 红证）：摘掉 exp 解析 ⇒ 判据 1 必红 ────────────────────


def test_guard_discriminates_the_mtime_only_criterion(tmp_path: Path) -> None:
    """把判定器改回历史形态（只看 mtime）⇒ 判据 1 的断言全部不成立，而判据 2 仍绿。"""
    original = DECISION.read_text(encoding="utf-8")
    mutated = tmp_path / "auth-state-freshness.mjs"
    injected = original.replace(
        "export function decodeJwtExpMs(token) {",
        "export function decodeJwtExpMs(token) {\n  return null // 注入：历史形态（只看 mtime）",
        1,
    )
    assert injected != original, "注入未生效（判定器签名变了？）——红证自证失败"
    mutated.write_text(injected, encoding="utf-8")

    # ① 同一份「exp 已过 + mtime 新鲜」的输入：历史形态判「可复用」⇒ 判据 1 必红
    expired = _decide(
        {
            "storageState": _state(_jwt(NOW_MS - 10 * 60_000)),
            "mtimeMs": NOW_MS - 60_000,
            "now": NOW_MS,
        },
        module=mutated,
    )
    assert expired["reuse"] is True, "注入后仍判不可复用 ⇒ 这不是历史形态，红证不成立"
    assert expired["source"] == "mtime", expired

    # ② 同一注入下「exp 未过期 ⇒ 可复用」的结论仍成立（mtime 新鲜 ⇒ 旧判据同样判可复用）
    #    ⇒ 光把窗口从 1h 调成 30min 抓不到本缺陷；能抓住的只有「exp 已过」这一侧（判据 1）。
    fresh = _decide(
        {
            "storageState": _state(_jwt(NOW_MS + 30 * 60_000)),
            "mtimeMs": NOW_MS - 5 * 60_000,
            "now": NOW_MS,
        },
        module=mutated,
    )
    assert fresh["reuse"] is True, fresh

    # ③ 自证注入只落在 tmp：仓内判定器逐字节未变
    assert DECISION.read_text(encoding="utf-8") == original


# ── 判据 5（静态面·接线 + 自愈）────────────────────────────────────────────────


def test_setup_uses_the_shared_decision_logs_it_and_falls_through_to_login() -> None:
    setup_src = SETUP.read_text(encoding="utf-8")

    assert re.search(r"from '\.\./helpers/auth-state-freshness\.mjs'", setup_src), (
        "auth.setup 必须用共享判定器（单一真值，别在 fixture 里另写一份）"
    )
    assert "decideAuthStateReuse" in setup_src

    # 出声：判定结论（含 reason / message）必须被打印 —— 静默兜底会把本缺陷重新藏起来
    assert re.search(r"console\.(log|warn)\(\s*`\[auth-setup\][^`]*\$\{decision\.message\}", setup_src), (
        "复用判定的结论必须打印出来（含 decision.message），不许静默"
    )

    # 历史漏洞形态必须消失：裸 mtime 窗口直接 return
    assert "age < 3600_000" not in setup_src, "旧的裸 mtime 判据仍在 ⇒ 失效 token 会被复用"
    assert re.search(r"if \(decision\.reuse\) return", setup_src), (
        "只有判定为「可复用」时才跳过登录"
    )

    # 自愈：判定为「需重登」⇒ 继续走下面的真登录（不是报错退出）
    assert setup_src.index("decideAuthStateReuse") < setup_src.index(
        "loginViaApi(TEST_PHONE, TEST_SMS_CODE)"
    ), "复用判定之后必须能落到真登录（自愈）"
