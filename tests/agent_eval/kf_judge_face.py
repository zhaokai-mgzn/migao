"""微信客服（kf）的「判定 JSON 面」—— 评测台的一层**新能力面**（关联 #9224 / CASE-AUDIT §四）。

## 为什么需要这一层

C 端 mini-app 已于 2026-11-26 删除 ⇒ 微信客服（kf）是 C 端顾客**唯一主入口**，
而评测台原先**只驱动 ai-agent 的 chat 面**（送消息、断言工具 / 回复文本）。
kf 的「这条顾客消息该不该转真人」决策落在另一条链上：

    KfMessageRouter → KfDecisionService.decide()（admin-api）
        ├─ 规则命中（人工词 / 风险词）⇒ ESCALATE_HUMAN，**不发起**语义判定
        └─ 规则未命中 ⇒ KfJudgeClient.judge() → POST /api/internal/kf/judge
                        → app/api/kf_judge.py 的 judge_text()

⇒ 这条链在用例库里**零覆盖**（`.github/cases/kf.yml` 的 30 条全是 `[backend-contract]` 单测）。
本模块补的正是那一格：**喂顾客消息 → 断言判定 JSON**。

## 口径（最小面；判定逻辑一行都不复制）

- **输入** = `case.user_inputs` 的最后一条文本 —— 与后端契约逐字一致：`KfJudgeRequest.text`
  是「客户最新一条消息」（`backend/ai-agent-service/app/api/kf_judge.py`）。
- **输出** = 真端点产出的判定 JSON：`intent / risk / emotion / confidence / escalate`。
- **真实现**（不是 mock、不是常量）：传输面 = `POST {AI_API_URL}/api/internal/kf/judge`
  （`JUDGE_PATH`），由 ai-agent 的 `kf_judge_endpoint` 直接调 `judge_text()` ——
  与 admin-api 的生产调用方 `KfJudgeClient` **同一端点、同一函数、同一套 Service Token 契约**。
  ⚠️ **刻意不在进程内 import `app.api.kf_judge`**：评测腿（`.github/workflows/agent-eval.yml`）
  只 `pip install httpx`，进程内没有 fastapi / langchain ⇒ 进程内 import 在**真评测里永远不可用**，
  那等于把「零覆盖」换成「永远 skip」。走端点还顺带验证**真实部署的那一份**。
- **失败关闭**（绝不静默 pass）：端点不可达 / 非 2xx / `success=false` / `data` 为空或形状不对
  ⇒ `{"available": False, "skip_reason": "kf_judge_unavailable: ..."}`，runner 把该条期望**判红**
  并带出原因（`migao-acceptance`：「没跑」必须长得像「没跑」）。
- **只读**：本模块不发任何写请求；判定端点本身无副作用（`judge_text` 只读 LLM）。

## 断言形态（字段级，不逐字比整段 JSON）

```yaml
expectations:
  - kf_judge:
      escalate: false          # 布尔字段：逐字相等
      intent: price            # 枚举字段：逐字相等
      emotion: [upset, angry]  # 列表 = one-of（模型对同一句话可能给两个近义值，逐字锁死会造 flake）
      confidence_min: 0.5      # 下界（唯一的数值字段）
```

期望的**规范串**由 `render_expectation()` 产出（`kf_judge({...json...})`），
`.github/render_cases.py` 的 `exp_to_str` 复用它 ⇒ 渲染 / 装载 / runner 三处**只有一份**格式实现。
`parse_expectation()` 是它的逆；两者由 `tests/unit_ci_workflows/test_kf_judge_face.py` 逐值锁住。

## 依赖纪律

仅标准库（`json` / `os` / `urllib.request` / `asyncio`）—— CI 的 `ci workflow helper unit tests`
job 只装 `pytest` + `pyyaml`，本模块必须能在那里被 import 且**不 skip**。
"""
from __future__ import annotations

import asyncio
import json
import os
import urllib.request

#: 用例 `expectations[].kf_judge` 的键名（面名；`render_cases.exp_to_str` 与 runner 共用）。
FACE_KEY = "kf_judge"

#: 真实现端点路径 = `app/config.py` 的 `API_PREFIX`（`/api`）+ `app/api/routes.py` 的
#: `/internal/kf` + `app/api/kf_judge.py` 的 `@router.post("/judge")`。
JUDGE_PATH = "/api/internal/kf/judge"

#: 与 `app/api/kf_judge.py` 的 `TEXT_MAX_CHARS` 同值（超长截断口径与真实现一致）。
MESSAGE_MAX_CHARS = 2000

#: 字段级断言面（`check()` 只认这些键 + `confidence_min`）。
FACE_FIELDS = ("escalate", "intent", "risk", "emotion")
CONFIDENCE_MIN_KEY = "confidence_min"

#: 端点调用超时（秒）。生产侧 `KfJudgeClient` 用的是 800ms 读超时 + **fail-open 到规则**；
#: 评测面**不**照抄那个 fail-open —— 超时在评测里是「判定没跑」，必须判红（见模块 header）。
DEFAULT_TIMEOUT_S = 20.0
DEFAULT_BASE_URL = "http://localhost:8001"

UNAVAILABLE_PREFIX = "kf_judge_unavailable"


class JudgeUnavailable(RuntimeError):
    """端点响应不符合真实现契约（`{success, data, error}`）⇒ 按「未评估」处理。"""


# ══════════════════════════════════════════════════════════════════════════════
# 一、期望形态（渲染 / 解析的唯一实现）
# ══════════════════════════════════════════════════════════════════════════════

def render_expectation(spec) -> str:
    """`{escalate: false}` → `kf_judge({"escalate": false})`（规范串；`.github/render_cases.py` 复用）。"""
    return "%s(%s)" % (FACE_KEY, json.dumps(spec, ensure_ascii=False, sort_keys=True))


def parse_expectation(exp):
    """规范串 / YAML 原始 dict → 断言 spec；**不是** kf 判定面 ⇒ `None`。

    两种来源形态都要吃：`.github/cases/*.yml`（dict）与渲染后的 `EvalCase.expectations`（str）。
    """
    if isinstance(exp, dict):
        if FACE_KEY not in exp:
            return None
        spec = exp.get(FACE_KEY)
        return spec if isinstance(spec, dict) else {}
    if isinstance(exp, str):
        s = exp.strip()
        if not s.startswith(FACE_KEY + "(") or not s.endswith(")"):
            return None
        inner = s[len(FACE_KEY) + 1:-1]
        try:
            spec = json.loads(inner)
        except ValueError:
            return {}
        return spec if isinstance(spec, dict) else {}
    return None


def is_face_expectation(exp) -> bool:
    """该计分断言是否走 kf 判定面（runner 据此**绕开** chat 面的 `check_expectation`）。"""
    return parse_expectation(exp) is not None


# ══════════════════════════════════════════════════════════════════════════════
# 二、输入
# ══════════════════════════════════════════════════════════════════════════════

def message_text(user_inputs) -> str:
    """取 `case.user_inputs` 的**最后一条**文本（真实现一次只判「客户最新一条消息」）。

    多轮声明里最后一条是顾客此刻说的话；dict 形态（带图消息）取 `text` 字段。
    取不到（空用例 / 末轮是纯 `auto_respond` 载荷）⇒ 空串 ⇒ 调用方按「未评估」判红。
    """
    items = list(user_inputs or [])
    for item in reversed(items):
        if isinstance(item, dict):
            text = item.get("text") or ""
        else:
            text = item
        if isinstance(text, str) and text.strip():
            return text
    return ""


# ══════════════════════════════════════════════════════════════════════════════
# 三、判定（真实现传输）
# ══════════════════════════════════════════════════════════════════════════════

def _http_transport(text, *, base_url, service_token, timeout):
    """真端点调用（标准库；评测腿只装 httpx ⇒ 不能引第三方依赖）。"""
    url = base_url.rstrip("/") + JUDGE_PATH
    body = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if service_token:
        req.add_header("X-Service-Token", service_token)
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — 端点由部署配置给定
        charset = resp.headers.get_content_charset() or "utf-8"
        return json.loads(resp.read().decode(charset))


def normalize(raw) -> dict:
    """真响应（`make_response` 契约）→ 面的判定 JSON；不合契约 ⇒ `JudgeUnavailable`（具名）。"""
    if not isinstance(raw, dict):
        raise JudgeUnavailable("响应不是 JSON 对象（实得 %s）" % type(raw).__name__)
    if not raw.get("success"):
        err = raw.get("error") if isinstance(raw.get("error"), dict) else {}
        code = err.get("code") or "（响应未带 error.code）"
        msg = err.get("message") or "（响应未带 error.message）"
        raise JudgeUnavailable("端点返回 success=false：%s / %s" % (code, msg))
    data = raw.get("data")
    if not isinstance(data, dict) or not data:
        raise JudgeUnavailable("响应缺 data 对象（判定 JSON 为空）")
    try:
        confidence = float(data.get("confidence") or 0.0)
    except (TypeError, ValueError):
        raise JudgeUnavailable("confidence 不是数值：%r" % (data.get("confidence"),))
    return {
        "intent": str(data.get("intent") or "other").strip(),
        "risk": str(data.get("risk") or "none").strip().lower(),
        "emotion": str(data.get("emotion") or "calm").strip().lower(),
        "confidence": confidence,
        "escalate": bool(data.get("escalate")),
    }


def _unavailable(reason: str) -> dict:
    return {"available": False, "skip_reason": "%s: %s" % (UNAVAILABLE_PREFIX, reason)}


def judge_message(text, *, base_url=None, service_token=None, timeout=None, transport=None) -> dict:
    """喂一条顾客消息 → 判定 JSON（或具名「未评估」）。

    `transport` 是**唯一**为测试留的 seam（HTTP 边界）；缺省 = 真端点 `_http_transport`。
    """
    content = (text or "").strip()
    if not content:
        return _unavailable("输入为空 —— 用例 user_inputs 没给出可判定的顾客消息")
    content = content[:MESSAGE_MAX_CHARS]
    base_url = (base_url if base_url is not None
                else os.environ.get("AI_API_URL") or DEFAULT_BASE_URL).strip()
    if not base_url:
        return _unavailable("未配置 AI_API_URL（ai-agent 地址）")
    service_token = (service_token if service_token is not None
                     else os.environ.get("SERVICE_TOKEN", ""))
    timeout = float(DEFAULT_TIMEOUT_S if timeout is None else timeout)
    call = transport or _http_transport
    try:
        raw = call(content, base_url=base_url, service_token=service_token, timeout=timeout)
    except Exception as e:  # noqa: BLE001 — 端点不可达必须变成「未评估」，不能冒泡成假失败
        return _unavailable("POST %s%s 调用失败：%s: %s"
                            % (base_url.rstrip("/"), JUDGE_PATH, type(e).__name__, e))
    try:
        judgment = normalize(raw)
    except JudgeUnavailable as e:
        return _unavailable(str(e))
    return {"available": True, "judgment": judgment, "text": content}


def judge_case_inputs(user_inputs, **kwargs) -> dict:
    """`case.user_inputs` → 判定 JSON（同步；测试与脚本入口用）。"""
    return judge_message(message_text(user_inputs), **kwargs)


async def judge_case_inputs_async(user_inputs, **kwargs) -> dict:
    """runner（async）入口：把阻塞的 HTTP 调用挪出事件循环。"""
    return await asyncio.to_thread(judge_case_inputs, user_inputs, **kwargs)


# ══════════════════════════════════════════════════════════════════════════════
# 四、字段级断言
# ══════════════════════════════════════════════════════════════════════════════

def _coerce_bool(value):
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("true", "yes", "1"):
            return True
        if low in ("false", "no", "0"):
            return False
    return value


def check(spec, outcome) -> tuple:
    """一条 `kf_judge` 期望 → `(ok, detail)`；失败**必须具名**（哪个字段 / 期望 / 实得）。"""
    if not isinstance(spec, dict) or not spec:
        return False, ("kf_judge 期望必须是非空映射（面字段：%s / %s）—— 空期望是空断言"
                       % ("/".join(FACE_FIELDS), CONFIDENCE_MIN_KEY))
    allowed = set(FACE_FIELDS) | {CONFIDENCE_MIN_KEY}
    unknown = sorted(set(spec) - allowed)
    if unknown:
        return False, ("kf_judge 期望含未支持字段 %s（支持面：%s / %s）"
                       % (unknown, "/".join(FACE_FIELDS), CONFIDENCE_MIN_KEY))
    if not isinstance(outcome, dict) or not outcome.get("available"):
        reason = (outcome or {}).get("skip_reason") if isinstance(outcome, dict) else None
        return False, (reason or "%s: 判定面没有产出（未评估，不按通过计）" % UNAVAILABLE_PREFIX)
    judgment = outcome.get("judgment") or {}
    gaps = []
    for field in sorted(spec):
        want = spec[field]
        if field == CONFIDENCE_MIN_KEY:
            try:
                floor = float(want)
            except (TypeError, ValueError):
                gaps.append("%s 期望不是数值（%r）" % (field, want))
                continue
            got = float(judgment.get("confidence") or 0.0)
            if got < floor:
                gaps.append("confidence=%s < %s" % (got, floor))
            continue
        got = judgment.get(field)
        if field == "escalate":
            want = _coerce_bool(want)
            if got != want:
                gaps.append("escalate 期望 %s 实得 %s" % (want, got))
            continue
        if isinstance(want, (list, tuple)):
            if got not in list(want):
                gaps.append("%s 期望 ∈ %s 实得 %r" % (field, list(want), got))
            continue
        if got != want:
            gaps.append("%s 期望 %r 实得 %r" % (field, want, got))
    if gaps:
        return False, "kf_judge 未满足：%s（判定 JSON=%s）" % (
            "；".join(gaps), json.dumps(judgment, ensure_ascii=False, sort_keys=True))
    return True, "kf_judge 满足：%s（判定 JSON=%s）" % (
        json.dumps(spec, ensure_ascii=False, sort_keys=True),
        json.dumps(judgment, ensure_ascii=False, sort_keys=True))