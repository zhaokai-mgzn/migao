# case_ids: CI-001
"""fixture 录制基址守卫：只认 `BASE_URL`，缺失即 fail-closed，绝不静默回落到本机地址（issue #8391）。

## 病灶（run 41358293178 逐字，2026-11-01 月度 schedule）

```
BASE_URL: https://api.migaozn.com          ← 脚本自己打印的 env
录制失败: apiRequestContext.post: connect ECONNREFUSED 127.0.0.1:8080
  - → POST http://127.0.0.1:8080/api/auth/sms/login
```

根因不是网络：env 明明是生产地址，但录制入口的**登录**走的是
`tests/e2e/helpers/auth.helper.ts` 的 `NEXT_PUBLIC_API_BASE_URL || 'http://127.0.0.1:8080'`
（录制 job 从不设前者）⇒ 静默回落到 Playwright 默认地址。同一形态 2026-09 起连红三次。

## 判据（都**会红**）

- **判据 1（行为面·正向）**：`BASE_URL=https://example.test` ⇒ 解析器返回值逐字等于它 ——
  用**真 node** 执行 `tests/e2e/helpers/api-base-url.mjs`（不是静态字符串匹配）。
- **判据 2（行为面·fail-closed）**：不设 `BASE_URL` ⇒ 非零退出 + 具名报错（含 `BASE_URL` 与「未设置」）；
  输出里**不得**出现 `127.0.0.1:8080` / `localhost:8080`（静默回落的历史形态）。
- **判据 3（静态面·单一真值 + 接线）**：录制入口把解析结果显式传给登录（`loginViaApi(PHONE, CODE, BASE)`）、
  自身不含本机默认值；`auth.helper` 的登录 URL 用显式入参；workflow 的 `BASE_URL` 由 `secrets.*` 透传且无本机地址。
- **判据 4（判别力自证）**：把解析器改回历史形态（`BASE_URL || 'http://127.0.0.1:8080'`）后，
  判据 2 的三条断言**全部不成立** —— 证明判据不是空断言（同一注入下判据 1 仍绿，
  这正是「只测设置了 env 的路径」抓不到本次缺陷的原因）。

## 边界（照实登记，§19.1）

- 判据不跑真 Playwright / 真后端：录制 job 的网络行为面由 run 日志承担，本判据只判**基址解析与接线**；
- 判据 3 是静态面（只读源码）：它判「基址被显式传进登录」，**不**判「远端 API 真的可用」。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RESOLVER = REPO_ROOT / "tests" / "e2e" / "helpers" / "api-base-url.mjs"
RECORDER = REPO_ROOT / "tests" / "e2e" / "scripts" / "record-fixtures.ts"
AUTH_HELPER = REPO_ROOT / "tests" / "e2e" / "helpers" / "auth.helper.ts"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "fixture-record.yml"

EXPECTED_BASE = "https://example.test"
#: 历史形态（issue #8391 的失败地址）；任何一处在「缺 BASE_URL」路径上出现都算静默回落。
LOCAL_FALLBACK_TOKENS = ("127.0.0.1:8080", "localhost:8080")


def _node() -> str:
    node = shutil.which("node")
    assert node, "node 不可用（本判据的结构前提：解析器必须用真 node 跑一次）"
    return node


def _run_resolver(
    extra_env: dict[str, str], module: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """用真 node 跑解析器：`console.log(resolveRecordingBaseUrl())` = 录制脚本实际会用的基址。"""
    target = module or RESOLVER
    script = (
        "import { resolveRecordingBaseUrl } from "
        + json.dumps(target.as_uri())
        + ";console.log(resolveRecordingBaseUrl())"
    )
    env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "/tmp")}
    env.update(extra_env)
    return subprocess.run(
        [_node(), "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )


# ── 判据 1（行为面·正向）────────────────────────────────────────────────────


def test_base_url_env_is_adopted_verbatim() -> None:
    proc = _run_resolver({"BASE_URL": EXPECTED_BASE})
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == EXPECTED_BASE


# ── 判据 2（行为面·fail-closed）──────────────────────────────────────────────


def test_missing_base_url_fails_closed_without_local_fallback() -> None:
    proc = _run_resolver({})
    assert proc.returncode != 0, "缺 BASE_URL 必须非零退出（fail-closed），不得带默认基址继续录制"
    combined = proc.stdout + proc.stderr
    assert "BASE_URL" in combined, "报错必须点名 BASE_URL（可归因）"
    assert "未设置" in combined, "报错必须说清是「未设置」，不是一次网络错误"
    for token in LOCAL_FALLBACK_TOKENS:
        assert token not in combined, (
            f"缺 BASE_URL 时输出里出现了本机默认地址 {token} —— 这正是 issue #8391 的静默回落形态"
        )


# ── 判据 3（静态面·单一真值 + 接线）───────────────────────────────────────────


def test_recording_entry_threads_resolved_base_into_login() -> None:
    recorder = RECORDER.read_text(encoding="utf-8")
    assert "resolveRecordingBaseUrl" in recorder, "录制入口必须走单一基址解析器"
    assert re.search(r"const\s+BASE\s*=\s*resolveRecordingBaseUrl\(\)", recorder), (
        "解析必须在任何请求之前完成（fail-closed）"
    )
    assert re.search(r"loginViaApi\(\s*PHONE\s*,\s*CODE\s*,\s*BASE\s*\)", recorder), (
        "登录必须拿到同一个基址（issue #8391 的根因：登录走 auth.helper 的默认值）"
    )
    assert "process.env.BASE_URL ||" not in recorder, "录制入口不得自行拼默认基址"
    for token in LOCAL_FALLBACK_TOKENS:
        assert token not in recorder, f"录制入口不得出现本机默认地址 {token}"


def test_auth_helper_login_uses_explicit_base() -> None:
    helper = AUTH_HELPER.read_text(encoding="utf-8")
    assert re.search(r"apiBaseUrl\?\s*:\s*string", helper), "loginViaApi 必须接受显式基址入参"
    assert "${baseUrl}/api/auth/sms/login" in helper, "登录 URL 必须用入参基址，不得只用模块常量"


def test_workflow_passes_base_url_through_secrets() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "npx tsx e2e/scripts/record-fixtures.ts" in workflow
    assert re.search(r"BASE_URL:\s*\$\{\{\s*secrets\.E2E_ADMIN_API_URL", workflow), (
        "workflow 的 BASE_URL 必须由 secrets 透传（可覆盖的显式默认，不是本机地址）"
    )
    for token in LOCAL_FALLBACK_TOKENS:
        assert token not in workflow, f"workflow 不得出现本机默认地址 {token}"


# ── 判据 4（判别力自证）──────────────────────────────────────────────────────


def test_guard_discriminates_the_historical_silent_fallback(tmp_path: Path) -> None:
    """把解析器改回历史形态 ⇒ 判据 2 全部不成立（证明它不是空断言）。"""
    original = RESOLVER.read_text(encoding="utf-8")
    mutated = tmp_path / "api-base-url.mjs"
    mutated.write_text(
        "export function resolveRecordingBaseUrl(env = process.env) {\n"
        "  return (env.BASE_URL || 'http://127.0.0.1:8080').trim().replace(/\\/+$/, '')\n"
        "}\n",
        encoding="utf-8",
    )

    # ① 历史形态在「缺 BASE_URL」路径上静默回落到本机地址 ⇒ 判据 2 的三条断言都不成立
    silent = _run_resolver({}, module=mutated)
    assert silent.returncode == 0
    assert "127.0.0.1:8080" in silent.stdout
    assert "未设置" not in (silent.stdout + silent.stderr)

    # ② 同一注入下判据 1 仍然绿 ⇒ 「只测设置了 BASE_URL 的路径」抓不到本次缺陷
    adopted = _run_resolver({"BASE_URL": EXPECTED_BASE}, module=mutated)
    assert adopted.returncode == 0
    assert adopted.stdout.strip() == EXPECTED_BASE

    # ③ 自证注入只落在 tmp：仓内解析器逐字节未变
    assert RESOLVER.read_text(encoding="utf-8") == original
