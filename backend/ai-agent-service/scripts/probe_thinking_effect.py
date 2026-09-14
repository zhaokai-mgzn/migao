#!/usr/bin/env python
"""思考开关实证探针（issue #3573）—— enable_thinking / force_no_think 在真实 provider 上是否生效。

背景
----
``LLMFactory.create_skill_llm`` 的思考开关实现于 MiniMax-M3 时代：

* ``enable_thinking=True``  → ``extra_body={"thinking": {"type": "enabled"}}`` + ``max_completion_tokens=384000``
* ``force_no_think=True``   → ``extra_body={"thinking": {"type": "disabled"}}``
* 两者都不传               → **不传 extra_body**（``tests/test_llm_factory.py:41`` 钉死）

但当前 provider 已是 DeepSeek（``api.deepseek.com`` / ``deepseek-flash``），而
``extra_body={"thinking": {...}}`` 是 MiniMax 的 API 形态，DeepSeek 官方 Thinking Mode
文档未记载它。同一 provider 的视觉路径（``create_vision_llm``）反而**刻意不传**该参数
（``tests/test_llm_factory.py:81-82``：DeepSeek 不传 MiniMax 专属 thinking extra_body）。

``_THINKING_INTENTS`` / ``_MULTI_TURN_THINKING_INTENTS``（base_skill.py:198-224）与
issue #3153 的全部收益，都以「该开关真的生效」为前提。本探针用**真实调用**把它定死。

判定规则（脚本自动输出）
------------------------
两组配置下若 ``reasoning_content`` 与 reasoning token 用量**无差异** → 「参数被忽略（no-op）」；
**有差异** → 「参数生效」；抛错（尤其 400）→ 「参数被拒」。

成本护栏
--------
* 固定 3 次调用（enabled / disabled / 无 extra_body 基线），prompt 极短、``max_completion_tokens``
  非思考组固定 2048（enabled 组按工厂现状 384000，只是上限声明、不预扣费）；
* **不跑任何评测用例**、不进 agent 图、不落库；
* 缺凭据时**优雅退出**（exit 0 + 明确 SKIPPED 标记），绝不静默假成功。

用法
----
    cd backend/ai-agent-service
    python scripts/probe_thinking_effect.py          # 需要 PRIMARY_API_KEY（CI 从 secret 注入）
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Optional

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# conftest 同款兜底：config.py 有若干无默认值的必填字段，探针不需要它们（不落库/不起服务），
# 但 Settings 实例化时会校验 —— 缺一个就 ValidationError。只补与 LLM 无关的占位值，
# **不设置** PRIMARY_API_KEY（缺凭据必须被下面显式检出，而不是被兜底成假成功）。
for _k, _v in (
    ("DATABASE_URL", "postgresql+asyncpg://probe:probe@localhost:5432/probe"),
    ("REDIS_URL", "redis://localhost:6379/0"),
    ("SERVICE_TOKEN", "probe-service-token"),
    ("JWT_PUBLIC_KEY", "probe-jwt-public-key"),
    ("LOGISTICS_API_URL", "http://localhost/probe"),
    ("LOGISTICS_APPCODE", "probe"),
    ("SSE_TIMEOUT", "300"),
    ("SSE_PING_INTERVAL", "15"),
    ("CORS_ALLOWED_ORIGINS", "http://localhost:3000"),
):
    os.environ.setdefault(_k, _v)

PROMPT = "只回答两个字：好的。不要任何解释。"

# 判定为「凭据缺失」的 key（CI 用 ci-dummy 兜底时视为无真实凭据）
_DUMMY_KEYS = {"", "ci-dummy", "dummy", "test"}


class _Tee:
    """把 stdout 同时写文件（CI 里供 artifact 长期留存，run 日志会被 GC）。

    不用 shell 管道（`python … | tee …`）：管道退出码取自 tee（恒 0）→
    探针失败被吞成 step success。先例见 xiaobu-acceptance.yml 的 pipefail 复盘。
    """

    def __init__(self, stream, path: str) -> None:
        self._stream = stream
        self._file = open(path, "w", encoding="utf-8")  # noqa: SIM115 —— 进程退出即关闭

    def write(self, data: str) -> int:
        self._file.write(data)
        self._file.flush()
        return self._stream.write(data)

    def flush(self) -> None:
        self._file.flush()
        self._stream.flush()


def _flatten(node: Any, prefix: str = "", depth: int = 0) -> dict[str, Any]:
    """把 response_metadata / additional_kwargs 展平成 key→value（截断超长值）。"""
    out: dict[str, Any] = {}
    if depth > 4:
        return out
    if isinstance(node, dict):
        for k, v in node.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, (dict, list)):
                out.update(_flatten(v, key, depth + 1))
            else:
                text = str(v)
                out[key] = text if len(text) <= 400 else text[:400] + "…"
    elif isinstance(node, list):
        for i, v in enumerate(node[:5]):
            out.update(_flatten(v, f"{prefix}[{i}]", depth + 1))
    return out


def _thinking_echo(meta: dict[str, Any]) -> Optional[str]:
    """provider 是否回显/承认了 thinking 参数（判断「被拒但被吞」的关键证据）。"""
    for k, v in meta.items():
        if "thinking" in k.lower() or "reasoning" in k.lower():
            return f"{k}={v}"
    return None


def _usage(resp: Any) -> dict[str, Any]:
    usage: dict[str, Any] = {}
    um = getattr(resp, "usage_metadata", None) or {}
    for k in ("input_tokens", "output_tokens", "total_tokens"):
        if um.get(k) is not None:
            usage[k] = um[k]
    for k, v in (um.get("output_token_details") or {}).items():
        usage[f"output_details.{k}"] = v
    meta = getattr(resp, "response_metadata", None) or {}
    tu = meta.get("token_usage") or meta.get("usage") or {}
    for k in ("prompt_tokens", "completion_tokens", "total_tokens",
              "reasoning_tokens", "completion_tokens_details"):
        if tu.get(k) is not None:
            usage[f"raw.{k}"] = tu[k]
    return usage


def _reasoning_signals(resp: Any, meta: dict[str, Any]) -> dict[str, Any]:
    """reasoning_content 是否出现（三个可能位置都查）+ 长度。"""
    sig: dict[str, Any] = {}
    ak = getattr(resp, "additional_kwargs", None) or {}
    rc = ak.get("reasoning_content")
    sig["additional_kwargs.reasoning_content"] = (
        f"len={len(rc)}" if isinstance(rc, str) and rc else "absent"
    )
    hit = _thinking_echo(meta)
    if hit:
        sig["metadata_hit"] = hit
    per_msg = []
    for m in (getattr(resp, "additional_kwargs", None) or {}).get("reasoning", []) or []:
        per_msg.append(str(m)[:120])
    if per_msg:
        sig["reasoning_blocks"] = per_msg
    return sig


def _http_error_code(exc: BaseException) -> Optional[int]:
    for attr in ("status_code", "http_status", "code"):
        val = getattr(exc, attr, None)
        if isinstance(val, int):
            return val
    m = re.search(r"\b(400|401|403|404|422|429|500|502|503)\b", str(exc))
    return int(m.group(1)) if m else None


class _CaptureTransport(httpx.AsyncBaseTransport):
    """记录**真正发到线上**的请求体（证据链：证明参数确实出网，而非被 langchain 丢弃）。

    langchain-openai 把 ``extra_body`` 作为顶层参数交给 OpenAI SDK，由 SDK 合并进 body
    （文档保证）。但「文档保证」不等于「本次真的发了」—— 这里直接拦 httpx 传输层兑现货真价实。

    防御式：hook 自身任何异常都不影响探针（只记 ``<capture failed>``）。
    """

    def __init__(self, inner: httpx.AsyncBaseTransport, sink: list[dict[str, Any]]) -> None:
        self._inner = inner
        self._sink = sink

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        try:
            raw = await request.aread()
            body = json.loads(raw.decode("utf-8"))
            self._sink.append(
                {
                    "url": str(request.url),
                    "thinking": body.get("thinking"),
                    "has_max_completion_tokens": "max_completion_tokens" in body,
                    "max_completion_tokens": body.get("max_completion_tokens"),
                    "top_level_keys": sorted(body.keys()),
                }
            )
            request = httpx.Request(
                request.method, request.url, headers=request.headers, content=raw
            )
        except Exception as exc:  # noqa: BLE001
            self._sink.append({"error": f"{type(exc).__name__}: {exc}"[:300]})
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


@contextlib.asynccontextmanager
async def _capture_wire(client: httpx.AsyncClient, sink: list[dict[str, Any]]):
    """临时把传输层换成记录版，yield 后无条件还原（探针自身不留副作用）。"""
    original = client._transport
    client._transport = _CaptureTransport(original, sink)
    try:
        yield
    finally:
        client._transport = original


async def _probe(label: str, enable_thinking: bool, force_no_think: bool) -> dict[str, Any]:
    """一次真实调用 + 完整证据 dump。异常被捕获为证据（不算脚本失败）。"""
    from app.llm.factory import LLMFactory

    result: dict[str, Any] = {
        "label": label,
        "factory_args": {"enable_thinking": enable_thinking, "force_no_think": force_no_think},
        "error": None,
    }

    llm = LLMFactory.create_skill_llm(
        enable_thinking=enable_thinking, force_no_think=force_no_think
    )
    # 工厂实际下发的 HTTP 参数（证明 extra_body 真的进了请求体，而非被 langchain 丢弃）
    result["sent_extra_body"] = getattr(llm, "extra_body", None)
    if result["sent_extra_body"] is None:
        result["sent_extra_body"] = (getattr(llm, "model_kwargs", None) or {}).get("extra_body")
    # langchain-openai 会把 max_completion_tokens 收进 model_kwargs（构造时告警），
    # 故这里两个位置都查；真正权威的是 wire_requests（出网 body）。
    result["factory_max_completion_tokens"] = (
        (getattr(llm, "model_kwargs", None) or {}).get("max_completion_tokens")
        or getattr(llm, "max_completion_tokens", None)
    )
    result["client_model"] = getattr(llm, "model_name", None) or getattr(llm, "model", None)
    result["base_url"] = str(
        getattr(llm, "api_base", None)
        or getattr(llm, "openai_api_base", None)
        or getattr(llm, "root_client", None) and getattr(llm.root_client, "base_url", "")
    )

    # 拦传输层，记录真正出网的 body（证明 extra_body 未被 langchain 静默丢弃）
    wire: list[dict[str, Any]] = []
    client = getattr(getattr(llm, "root_async_client", None), "_client", None)

    started = time.monotonic()
    try:
        if isinstance(client, httpx.AsyncClient):
            async with _capture_wire(client, wire):
                resp = await llm.ainvoke(PROMPT)
        else:
            resp = await llm.ainvoke(PROMPT)
    except BaseException as exc:  # noqa: BLE001 —— 异常本身就是要采集的证据
        result["error"] = {
            "type": type(exc).__name__,
            "http_code": _http_error_code(exc),
            "message": str(exc)[:1200],
        }
        result["elapsed_s"] = round(time.monotonic() - started, 2)
        result["wire_requests"] = wire
        return result

    result["elapsed_s"] = round(time.monotonic() - started, 2)
    result["wire_requests"] = wire
    meta = _flatten(getattr(resp, "response_metadata", None) or {})
    result["response_metadata"] = meta
    result["additional_kwargs"] = _flatten(getattr(resp, "additional_kwargs", None) or {})
    result["usage"] = _usage(resp)
    result["reasoning_signals"] = _reasoning_signals(resp, meta)
    result["thinking_param_echo"] = _thinking_echo(meta) or _thinking_echo(result["additional_kwargs"])
    content = getattr(resp, "content", "")
    result["content_len"] = len(content or "")
    result["content_preview"] = (content or "")[:120]
    return result


def _verdict(enabled: dict[str, Any], disabled: dict[str, Any]) -> tuple[str, list[str]]:
    """判定规则（与 docstring 一致）：no-op / 生效 / 被拒。"""
    reasons: list[str] = []

    for r in (enabled, disabled):
        if r.get("error"):
            code = (r["error"] or {}).get("http_code")
            reasons.append(f"{r['label']} 抛错 {r['error']['type']}（http_code={code}）")
    if any(r.get("error") for r in (enabled, disabled)):
        return "参数被拒（请求失败）", reasons

    def sig(r: dict[str, Any]) -> dict[str, Any]:
        return {
            "reasoning_content": r["reasoning_signals"].get("additional_kwargs.reasoning_content"),
            "metadata_hit": r["reasoning_signals"].get("metadata_hit"),
            "reasoning_tokens": r["usage"].get("output_details.reasoning")
            or r["usage"].get("raw.reasoning_tokens"),
            "thinking_echo": r.get("thinking_param_echo"),
        }

    se, sd = sig(enabled), sig(disabled)
    reasons.append(f"enabled  侧信号: {json.dumps(se, ensure_ascii=False)}")
    reasons.append(f"disabled 侧信号: {json.dumps(sd, ensure_ascii=False)}")

    if se == sd:
        reasons.append("两侧 reasoning_content / reasoning token / thinking 回显完全一致 → 参数未改变任何可观测行为")
        return "参数被忽略（no-op）", reasons

    reasons.append("两侧存在可观测差异 → 参数改变了 provider 行为")
    return "参数生效", reasons


async def main() -> int:
    print("=" * 78)
    print("思考开关实证探针（issue #3573）")
    print("=" * 78)

    from app.config import settings

    api_key = settings.PRIMARY_API_KEY or settings.VISION_API_KEY
    model = settings.LLM_MODEL
    base_url = settings.LLM_BASE_URL
    print(f"provider base_url : {base_url}")
    print(f"model             : {model}")
    print(f"prompt            : {PROMPT}")
    print(f"api_key           : {'<set,len=%d>' % len(api_key) if api_key else '<EMPTY>'}")

    if not api_key or api_key in _DUMMY_KEYS:
        print()
        print("SKIPPED: 无真实 LLM 凭据（PRIMARY_API_KEY/VISION_API_KEY 缺失或为占位值）。")
        print("SKIPPED: 真实探针需要凭据；本地无 .env 时请在 CI（llm-thinking-probe workflow）运行。")
        print("SKIPPED: 本次未发送任何 LLM 调用，**不构成任何结论**。")
        return 0

    print()
    print("── 下发参数（工厂产出 + 真正出网的请求体）──")
    variants = [
        ("A: enable_thinking=True（工厂现状）", True, False),
        ("B: force_no_think=True（工厂现状）", False, True),
        ("C: 无开关 / 不传 extra_body（基线）", False, False),
    ]
    results: dict[str, dict[str, Any]] = {}
    for label, et, fnt in variants:
        r = await _probe(label, et, fnt)
        results[label] = r
        print(f"  {label}")
        print(f"    sent_extra_body            = {r['sent_extra_body']}")
        print(f"    factory_max_completion_tokens = {r['factory_max_completion_tokens']}")
        print(f"    client_model / base_url    = {r['client_model']} / {r['base_url']}")
        for i, req in enumerate(r.get("wire_requests") or []):
            print(f"    wire#{i} url                 = {req.get('url')}")
            print(f"    wire#{i} thinking            = {json.dumps(req.get('thinking'), ensure_ascii=False)}")
            print(f"    wire#{i} max_completion_tok  = {req.get('max_completion_tokens')}")
            if req.get("error"):
                print(f"    wire#{i} capture_error       = {req['error']}")
    print("  （以上为 3 次真实调用前的参数确认，调用本身在下面逐条 dump）")

    print()
    print("── 逐条证据 dump ──")
    for label, _et, _fnt in variants:
        r = results[label]
        print(f"\n[{label}]")
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))

    enum_r = results[variants[0][0]]
    dis_r = results[variants[1][0]]
    base_r = results[variants[2][0]]

    verdict, reasons = _verdict(enum_r, dis_r)
    print()
    print("=" * 78)
    print(f"判定（enabled vs disabled）：{verdict}")
    for line in reasons:
        print(f"  - {line}")

    # 基线对照：无 extra_body 时的「provider 默认行为」，用于解释 no-op 的含义
    def _sig(r: dict[str, Any], key: str) -> Any:
        return (r.get("reasoning_signals") or {}).get(key)

    print()
    print("── 基线对照（不传 extra_body）──")
    print(f"  baseline reasoning_content = "
          f"{_sig(base_r, 'additional_kwargs.reasoning_content')}")
    print(f"  baseline thinking echo     = {base_r.get('thinking_param_echo')}")
    for name, r in (("baseline", base_r), ("enabled ", enum_r), ("disabled", dis_r)):
        print(f"  {name} usage             = {json.dumps(r.get('usage'), ensure_ascii=False)}")
        print(f"  {name} content / elapsed  = "
              f"{r.get('content_preview')!r} / {r.get('elapsed_s')}s")
    print()
    print("VERDICT=" + verdict)
    print("=" * 78)

    # 退出码语义：**结论**不影响退出码（no-op / 生效 / 被拒都是有效发现）；
    # 只有「探针自身没跑成」（凭据坏 / 网络不可达 / 服务端 5xx）才非零退出，
    # 避免 CI 假绿——按仓库既有红线的意思，静默成功比失败更危险。
    for label, r in results.items():
        err = r.get("error") or {}
        if err.get("http_code") in (401, 403):
            print(f"❌ 探针未跑成：{label} 凭据被拒（http_code={err.get('http_code')}）")
            return 1
        if err:
            print(f"❌ 探针未跑成：{label} 请求失败（{err.get('type')}）")
            return 1
    return 0


if __name__ == "__main__":
    _tee_path = os.environ.get("TEE_VERDICT", "").strip()
    if _tee_path:
        sys.stdout = _Tee(sys.stdout, _tee_path)  # type: ignore[assignment]
    sys.exit(asyncio.run(main()))
