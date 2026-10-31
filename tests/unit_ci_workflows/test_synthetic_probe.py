# case_ids: MC-124
"""只读合成探针 + 构建身份接线的常驻判据（issue #8203 · P0-04）。

## 病（改前，durable 读数）

- `docs/deployment/production-deployment.md` §5 把「SLS 采集 + 告警触达值班」列为**必须项**，
  而仓库内**零实现**；线上**唯一**可信探针是 `GET /api/version`（200）与 `ai-api/health`（200）
  ⇒ **没有外部合成探针** ⇒ 5xx / 白屏 / 证书到期 / 发布失败都不会主动惊动人；
- `https://ai-api.migaozn.com/api/version|/version|/build-info` 改前**全 404** ⇒ ai-agent 线上
  「跑的是哪个 commit」不可判定（审计 P1-01）。

## 判据面

| # | 判据 | 会红的注入 |
|---|---|---|
| 1 | 三个**当前真实存在**的只读面被覆盖（`/api/version` + `/b/` + `/w/`）；刻意不探 404 面 | 加一条必然 404 的目标 ⇒ 永久红（P1-04 的教训） |
| 2 | 判定语义：200 + 非空 body；`/api/version` 要求 JSON 含 `app`/`sha`/`builtAt`；连不上 / 非 JSON / 缺字段 / 顶层非对象都判红 | 只看状态码 ⇒ 「200 + 空 body」也算绿（白屏探不到）⇒ 红 |
| 3 | 重试**只对瞬态**（连接失败 / 5xx）生效；4xx 与形状不符当场定案 | 4xx 也重试 ⇒ 把红推后 5 分钟、还掩盖真因 ⇒ 红 |
| 4 | **三态**：`0` 全通过 / `1` 至少一条失败 / `3` **无法判定**（没有可探目标）；`3` 不得当 `0` 读 | 空目标退化成 0 ⇒ 假绿 ⇒ 红 |
| 5 | 接线：`.github/workflows/post-merge-verify.yml` 的 main 侧步（**在 `if: failure()` 的 P1 出口之前**、PR 面不跑、退出码原样上抛、判据本体缺席即 fail-closed） | 摘掉该步 / 挪到出口之后 / `3` 归一化成 `0` / 摘掉 `if:` ⇒ 各自判红 |
| 6 | **不新增 schedule / 不新造告警通道**：判据本体只被**一个** workflow 引用 | 再建一条探针 workflow ⇒ 红 |
| 7 | 构建身份**五跳**：runner 现取 → 驱动脚本位置参数 `$9/$10` → BOOTSTRAP 占位符 → `deploy.sh` 的 `--build-arg` → Dockerfile `ARG`+`ENV` ⇒ `Settings` ⇒ `/version` | 任一跳缺失 ⇒ 线上 `/version` 的 `sha` 恒空（= 探不到）⇒ 红 |

## 零网络 / 零时钟

`check()` / `run()` / `main()` 的 `fetch_fn` / `sleep_fn` 全部注入假实现（无 `urllib`、无 `time.sleep`）；
接线判据只读仓内文件。⇒ 同一份代码任何时刻同一读数，可在 CI 与本地反复跑。

## 覆盖边界（照实登记，§19.1）

- 判据**不联网**：证的是「脚本在给定响应下会做什么」，**不是**「线上此刻真的这么回」；
- 真实读数只能看 `.github/workflows/post-merge-verify.yml` 的 run（step summary + P1 值班 issue），
  或本机 `python3 scripts/synthetic_probe.py`（会联网，故不在判据里跑）；
- 构建身份那一跳链证的也是**静态接线**：`sha` 真正落到线上要等一次部署（复算见
  `docs/deployment/observability-minimum.md` 的「部署后自证」）。
"""

from __future__ import annotations

import copy
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
PROBE = REPO / "scripts" / "synthetic_probe.py"
POST_MERGE = REPO / ".github" / "workflows" / "post-merge-verify.yml"
AI_DEPLOY = REPO / ".github" / "workflows" / "deploy-ai-agent-service.yml"
AI_DOCKERFILE = REPO / "backend" / "ai-agent-service" / "Dockerfile"
AI_CONFIG = REPO / "backend" / "ai-agent-service" / "app" / "config.py"
SWAS_DRIVER = REPO / "deploy" / "scripts" / "swas-deploy-ci.sh"
SWAS_DEPLOY = REPO / "deploy" / "swas" / "deploy.sh"

API_BASE = "https://api.example.test"
APP_BASE = "https://app.example.test"
VERSION_URL = f"{API_BASE}/api/version"

PROBE_STEP_KEYWORD = "合成探针"
EXIT_STEP_KEYWORD = "P1 值班 issue"


def _load_probe():
    """按路径加载 `scripts/synthetic_probe.py`（`scripts/` 不是包，不能 `import`）。"""
    spec = importlib.util.spec_from_file_location("migao_synthetic_probe", PROBE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


probe = _load_probe()


# ── 假响应工具（**零网络**）────────────────────────────────────────────────


def version_payload(**overrides) -> bytes:
    payload = {
        "app": "ai-agent-service",
        "sha": "6f3aec2b" * 5,
        "builtAt": "2026-10-31T01:02:03Z",
    }
    payload.update(overrides)
    return json.dumps(payload).encode()


class SequenceFetcher:
    """按顺序返回预设响应，并记录被调用次数（用来判「有没有重试」）。"""

    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls = 0

    def __call__(self, url, timeout):  # noqa: ARG002 - 签名与 probe.fetch 一致
        self.calls += 1
        assert self._responses, "假 fetch 被多调了一次（期望恰好用掉 N 个响应，即不重试）"
        return self._responses.pop(0)


def target(name: str = "t", **kwargs):
    return probe.Target(name=name, url=f"{APP_BASE}/b/", **kwargs)


# ── 1. 覆盖面 ──────────────────────────────────────────────────────────────


def test_covers_the_three_live_read_faces():
    """三个**当前真实存在**的只读面（且刻意不探 404 面 —— 那会做成永久红）。"""
    targets = probe.default_targets(API_BASE, APP_BASE)

    assert [t.name for t in targets] == [
        "admin-api /api/version",
        "B 端 H5 落地 /b/",
        "工人报工落地 /w/",
    ]
    assert [t.url for t in targets] == [
        f"{API_BASE}/api/version",
        f"{APP_BASE}/b/",
        f"{APP_BASE}/w/",
    ]
    # 构建身份面必须要求三个字段（否则「200 但缺 sha」也会绿）
    assert targets[0].require_fields == ("app", "sha", "builtAt")
    # 静态面必须有非空 body（挡「200 + 空 body = 白屏」）
    assert all(t.min_body_bytes >= 1 for t in targets[1:])


# ── 2. 判定语义 ────────────────────────────────────────────────────────────


def test_version_target_passes_with_full_payload():
    version = probe.default_targets(API_BASE, APP_BASE)[0]
    result = probe.check(version, fetch_fn=SequenceFetcher((200, version_payload(), "")))

    assert result.ok is True
    assert result.fields["sha"] == "6f3aec2b" * 5
    assert "sha=6f3aec2b" in result.detail


def test_status_page_passes_with_non_empty_body():
    result = probe.check(
        target(min_body_bytes=1),
        fetch_fn=SequenceFetcher((200, b"<!doctype html><title>B</title>", "")),
    )

    assert result.ok is True
    assert result.body_bytes > 0


@pytest.mark.parametrize(
    ("response", "expected_snippet"),
    [
        ((200, b"", ""), "字节"),
        ((404, b"nope", ""), "期望 200"),
        ((None, b"", "URLError: timed out"), "连接失败"),
    ],
    ids=["空 body", "状态码不符", "连不上"],
)
def test_static_target_fails_loudly(response, expected_snippet):
    result = probe.check(target(min_body_bytes=1), fetch_fn=SequenceFetcher(response))

    assert result.ok is False
    assert expected_snippet in result.detail


def test_json_shape_is_checked_not_just_status():
    version = probe.default_targets(API_BASE, APP_BASE)[0]

    missing = probe.check(version, fetch_fn=SequenceFetcher((200, json.dumps({"app": "x"}).encode(), "")))
    assert missing.ok is False
    assert "缺字段" in missing.detail and "sha" in missing.detail

    not_json = probe.check(version, fetch_fn=SequenceFetcher((200, b"<html>502</html>", "")))
    assert not_json.ok is False
    assert "不是合法 JSON" in not_json.detail

    not_object = probe.check(version, fetch_fn=SequenceFetcher((200, b'["a"]', "")))
    assert not_object.ok is False
    assert "顶层不是对象" in not_object.detail


def test_empty_sha_is_reported_but_not_judged_here():
    """`sha` 为空 = 探不到（人看输出判断），**不在探针里判红** —— 与 `/version` 的三态口径一致。"""
    version = probe.default_targets(API_BASE, APP_BASE)[0]
    result = probe.check(
        version,
        fetch_fn=SequenceFetcher((200, version_payload(sha="", builtAt=""), "")),
    )

    assert result.ok is True
    assert result.fields["sha"] == ""
    assert "探不到" in result.detail


def test_allow_status_is_not_a_failure():
    """`allow_status` 给「发布前必然 404」的面留的语义（现在没接，但语义必须对）。"""
    allowed = target(allow_status=(404,))
    result = probe.check(allowed, fetch_fn=SequenceFetcher((404, b"", "")))

    assert result.ok is True
    assert "允许的状态码 404" in result.detail


# ── 3. 重试只对瞬态 ────────────────────────────────────────────────────────


def test_retries_transient_then_succeeds():
    sleeps: list[float] = []
    fetcher = SequenceFetcher((502, b"", ""), (200, b"<html>ok</html>", ""))

    results = probe.run(
        [target(min_body_bytes=1)],
        fetch_fn=fetcher,
        attempts=2,
        retry_delay=0,
        sleep_fn=sleeps.append,
    )

    assert fetcher.calls == 2
    assert len(sleeps) == 1
    assert results[0].ok is True


def test_does_not_retry_4xx_or_shape_mismatch():
    """4xx 与形状不符当场定案（重试改变不了它们，只会把红推后）。"""
    fetcher = SequenceFetcher((404, b"", ""))
    results = probe.run([target()], fetch_fn=fetcher, attempts=3, retry_delay=0, sleep_fn=lambda _: None)

    assert fetcher.calls == 1
    assert results[0].ok is False


def test_exhausted_retries_are_named():
    fetcher = SequenceFetcher((503, b"", ""), (503, b"", ""))
    results = probe.run([target()], fetch_fn=fetcher, attempts=2, retry_delay=0, sleep_fn=lambda _: None)

    assert fetcher.calls == 2
    assert results[0].ok is False
    assert "已重试 2 次" in results[0].detail


# ── 4. 三态（0 / 1 / 3）───────────────────────────────────────────────────


def _all_pass_fetcher():
    responses = {
        VERSION_URL: (200, version_payload(), ""),
        f"{APP_BASE}/b/": (200, b"<html>b</html>", ""),
        f"{APP_BASE}/w/": (200, b"<html>w</html>", ""),
    }
    return lambda url, timeout: responses[url]  # noqa: ARG005


def test_main_returns_0_when_all_faces_pass(capsys):
    rc = probe.main(
        ["--api-base", API_BASE, "--app-base", APP_BASE],
        fetch_fn=_all_pass_fetcher(),
        sleep_fn=lambda _: None,
    )

    out = capsys.readouterr().out
    assert rc == 0
    assert "SYNTHETIC_PROBE pass=3 fail=0 total=3" in out
    assert "sha=6f3aec2b" in out


def test_main_returns_1_when_any_face_fails(capsys):
    responses = {
        VERSION_URL: (200, version_payload(), ""),
        f"{APP_BASE}/b/": (200, b"<html>b</html>", ""),
        f"{APP_BASE}/w/": (404, b"", ""),
    }
    rc = probe.main(
        ["--api-base", API_BASE, "--app-base", APP_BASE],
        fetch_fn=lambda url, timeout: responses[url],  # noqa: ARG005
        sleep_fn=lambda _: None,
    )

    out = capsys.readouterr().out
    assert rc == 1
    assert "fail=1" in out
    # 判红必须给**可复制的复算命令**（不是「自己去看日志」）
    assert "python3 scripts/synthetic_probe.py" in out


def test_main_returns_3_when_there_is_nothing_to_probe(monkeypatch, capsys):
    """「没有探针目标」不是通过（空跑 = 假绿）。`3` 不得当 `0` 读。"""
    monkeypatch.setattr(probe, "default_targets", lambda *_a, **_k: [])

    rc = probe.main([], fetch_fn=_all_pass_fetcher(), sleep_fn=lambda _: None)

    out = capsys.readouterr().out
    assert rc == 3
    assert "无法判定" in out


# ── 5/6. workflow 接线（摘掉即红）───────────────────────────────────────────


def _load_workflow(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _verify_steps(workflow: dict) -> list[dict]:
    return workflow["jobs"]["verify"]["steps"]


def probe_wiring_problems(workflow: dict) -> list[str]:
    """返回接线问题清单（空 = 接线在）。**只读结构**，不联网。"""
    problems: list[str] = []
    steps = _verify_steps(workflow)
    hits = [i for i, step in enumerate(steps) if PROBE_STEP_KEYWORD in str(step.get("name", ""))]
    if len(hits) != 1:
        return [f"合成探针步必须**恰好一个**，实际 {len(hits)} 个"]

    index = hits[0]
    step = steps[index]
    run = str(step.get("run", ""))

    if "scripts/synthetic_probe.py" not in run:
        problems.append("该步没有调用判据本体 scripts/synthetic_probe.py")
    if "github.event_name != 'pull_request'" not in str(step.get("if", "")):
        problems.append("该步必须在 PR 面不跑（PR 红该反映 PR，不该被生产站点此刻的状态判红）")
    if "if [ ! -f scripts/synthetic_probe.py ]" not in run:
        problems.append("判据本体缺席时必须 fail-closed（否则摘掉脚本 = 静默跳过）")
    if 'exit "${rc}"' not in run:
        problems.append("退出码必须原样上抛（3 不得归一化成 0）")
    if "if [ \"${rc}\" = '0' ]" not in run:
        problems.append("必须显式区分 rc=0 与其它（不许默认成功）")

    exit_hits = [i for i, s in enumerate(steps) if EXIT_STEP_KEYWORD in str(s.get("name", ""))]
    if not exit_hits:
        problems.append("找不到 `if: failure()` 的 P1 值班 issue 出口步")
    elif index > min(exit_hits):
        problems.append(
            f"合成探针步（第 {index} 个）必须排在 P1 值班出口（第 {min(exit_hits)} 个）**之前**"
            "（之后 ⇒ 判红不产生值班单 = 静默）"
        )
    return problems


def test_probe_is_wired_into_post_merge_verify():
    assert probe_wiring_problems(_load_workflow(POST_MERGE)) == []


def test_probe_has_a_single_wiring_point():
    """不新增 schedule / 不新造第二条告警通道：判据本体只被一个 workflow 引用。"""
    referencing = sorted(
        path.name
        for path in (REPO / ".github" / "workflows").glob("*.yml")
        # 只看**执行面**引用（`scripts/synthetic_probe.py`）；文档 / 判据名里的提及不算接线
        if "scripts/synthetic_probe.py" in path.read_text(encoding="utf-8")
    )
    assert referencing == ["post-merge-verify.yml"]
    # 也没有另建一条「探针专用」workflow（那才是新增 schedule 的形态）
    assert not list((REPO / ".github" / "workflows").glob("*synthetic*"))


def _mutate_probe_wiring(workflow: dict, mutation: str) -> dict:
    mutated = copy.deepcopy(workflow)
    steps = _verify_steps(mutated)
    index = next(i for i, s in enumerate(steps) if PROBE_STEP_KEYWORD in str(s.get("name", "")))
    exit_index = next(i for i, s in enumerate(steps) if EXIT_STEP_KEYWORD in str(s.get("name", "")))

    if mutation == "remove_step":
        steps.pop(index)
    elif mutation == "drop_pull_request_guard":
        steps[index].pop("if", None)
    elif mutation == "exit_zero":
        steps[index]["run"] = str(steps[index]["run"]).replace('exit "${rc}"', "exit 0")
    elif mutation == "move_after_exit":
        steps.insert(exit_index, steps.pop(index))
    elif mutation == "drop_fail_closed_guard":
        steps[index]["run"] = str(steps[index]["run"]).replace(
            "if [ ! -f scripts/synthetic_probe.py ]", "if false"
        )
    else:  # pragma: no cover - 防止拼错
        raise AssertionError(mutation)
    return mutated


@pytest.mark.parametrize(
    "mutation",
    ["remove_step", "drop_pull_request_guard", "exit_zero", "move_after_exit", "drop_fail_closed_guard"],
)
def test_removing_the_wiring_turns_it_red(mutation):
    """判别力自证：五种坏形态**各自**让判据非空（不是「读一遍 YAML 看着对」）。"""
    problems = probe_wiring_problems(_mutate_probe_wiring(_load_workflow(POST_MERGE), mutation))
    assert problems, f"注入 `{mutation}` 后判据仍然全绿 ⇒ 这是空断言"


# ── 7. 构建身份五跳（issue #8203 / P1-01）──────────────────────────────────


def _all_steps(workflow: dict) -> list[dict]:
    return [step for job in workflow["jobs"].values() for step in job.get("steps", [])]


def build_identity_problems(workflow: dict) -> list[str]:
    """ai-agent 部署腿把构建身份送到远端的接线清单一（空 = 接线在）。"""
    problems: list[str] = []
    steps = _all_steps(workflow)

    deploy = [s for s in steps if "Deploy to SWAS" in str(s.get("name", ""))]
    if len(deploy) != 1:
        return [f"Deploy to SWAS 步必须恰好一个，实际 {len(deploy)} 个"]
    step = deploy[0]
    env = step.get("env") or {}
    run = str(step.get("run", ""))

    for var in ("BUILD_SHA", "BUILT_AT"):
        if f"steps.build_id.outputs.{var}" not in str(env.get(var, "")):
            problems.append(f"Deploy 步的 env.{var} 没有取自 steps.build_id.outputs.{var}")
        if f'"${var}"' not in run:
            problems.append(f"驱动脚本调用没有把 {var} 作为位置参数送到远端（C′ 的构建在服务器上）")

    # 不改变其它语义：服务键仍在（第 8 个位置参数）
    if " ai-agent " not in run:
        problems.append("调用点丢了服务键 `ai-agent`（会走成「拉 ACR 镜像」路径）")

    build_id = [s for s in steps if s.get("id") == "build_id"]
    if len(build_id) != 1:
        problems.append(f"build_id 步必须恰好一个，实际 {len(build_id)} 个")
    else:
        body = str(build_id[0].get("run", ""))
        if 'echo "BUILD_SHA=$SHA"' not in body:
            problems.append("build_id 没有输出 BUILD_SHA（`git rev-parse HEAD`）")
        if 'echo "BUILT_AT=${BUILT_AT}"' not in body:
            problems.append("build_id 没有输出 BUILT_AT（runner 时钟 ISO8601）")
    return problems


def test_ai_agent_deploy_leg_sends_build_identity():
    assert build_identity_problems(_load_workflow(AI_DEPLOY)) == []


@pytest.mark.parametrize("mutation", ["drop_positional_arg", "drop_env", "drop_build_id_step"])
def test_dropping_build_identity_wiring_turns_it_red(mutation):
    workflow = _load_workflow(AI_DEPLOY)
    deploy = next(s for s in _all_steps(workflow) if "Deploy to SWAS" in str(s.get("name", "")))

    if mutation == "drop_positional_arg":
        deploy["run"] = str(deploy["run"]).replace(' "$BUILD_SHA" "$BUILT_AT"', "")
    elif mutation == "drop_env":
        deploy["env"].pop("BUILD_SHA")
    else:
        for job in workflow["jobs"].values():
            job["steps"] = [s for s in job.get("steps", []) if s.get("id") != "build_id"]

    assert build_identity_problems(workflow), f"注入 `{mutation}` 后判据仍然全绿 ⇒ 空断言"


def test_driver_accepts_and_renders_build_identity():
    """第 2/3 跳：驱动脚本按位置参数收（`$9`/`$10`）并渲染进远端 BOOTSTRAP。"""
    text = SWAS_DRIVER.read_text(encoding="utf-8")

    assert "BUILD_SHA=${9:-${BUILD_SHA:-}}" in text
    assert "BUILT_AT=${10:-${BUILT_AT:-}}" in text
    assert "__BUILD_SHA__" in text
    assert "__BUILT_AT__" in text


def test_deploy_script_passes_build_args_to_docker_build():
    """第 4 跳：远端的 `docker build` 真的带 `--build-arg`。"""
    text = SWAS_DEPLOY.read_text(encoding="utf-8")

    assert '--build-arg "MIGAO_BUILD_SHA=${BUILD_SHA:-}"' in text
    assert '--build-arg "MIGAO_BUILT_AT=${BUILT_AT:-}"' in text


def test_dockerfile_turns_build_args_into_runtime_env():
    """第 5 跳：`ARG` 只在构建期存在 ⇒ 必须 `ENV` 转成运行期环境变量。"""
    text = AI_DOCKERFILE.read_text(encoding="utf-8")

    for var in ("MIGAO_BUILD_SHA", "MIGAO_BUILT_AT"):
        assert f'ARG {var}=""' in text, f"Dockerfile 缺 ARG {var}（默认空串 = 未注入时不伪造身份）"
        assert f"ENV {var}=${var}" in text, f"Dockerfile 没有把 {var} 转成运行期环境变量"


def test_settings_declare_build_identity_with_empty_default():
    text = AI_CONFIG.read_text(encoding="utf-8")

    for var in ("MIGAO_BUILD_SHA", "MIGAO_BUILT_AT"):
        assert re.search(rf'^\s+{var}: str = ""$', text, re.MULTILINE), f"Settings 缺 {var}（或默认值不是空串）"
