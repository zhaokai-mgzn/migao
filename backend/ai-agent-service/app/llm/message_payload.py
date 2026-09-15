"""LLM 请求体的**单一来源**：思考模式的 `reasoning_content` 回传约束（issue #3852）。

## 契约（上游规定，不是我们的偏好）

    assistant 消息若在思考模式下由上游**产出过** `reasoning_content`，
    下一次请求**必须原样带回**；上游**没给**时**不得凭空造**。

判定跑 `34908262839`（main `2b8dfbc2`）B 端腿 OR-014 的实测 400 原文：

    The `reasoning_content` in the thinking mode must be passed back to the API.

## 为什么需要这里做一层

`ChatDeepSeek` 从响应里**正确提取**了 `reasoning_content`（存进
`AIMessage.additional_kwargs`，见 `langchain_deepseek/chat_models.py`），但请求方向
**不回传**：被依赖的 `langchain_openai.chat_models.base._convert_message_to_dict`
只挑 `content` / `name` / `role` / `tool_calls` / `function_call` / `audio` 六个字段，
`additional_kwargs` 里其它键（含 `reasoning_content`）一律丢弃。

于是 ReAct 循环里 iter=2 的请求体只有 `assistant(tool_calls)` 而**没有** `reasoning_content`
⇒ iter=1 通、iter=2 必 400（首轮请求里没有 assistant 消息，规则无从触发）。
这是**产品侧**缺陷：上游对我们提契约要求，我们的请求体不满足，失败只能靠兜底话术收场
（#3805 病灶）；补上后失败才只剩下"真的故障"那一类，且仍可归因（#3809 短码）。

## 单一来源纪律

上游把"思考模式"判定在**请求体**上（顶层 `thinking` 段，或任何 assistant 消息带
`reasoning_content` —— 这正是 iter=2 用 `force_no_think` 客户端仍会 400 的解释）。
所以约束**不能**按"当前 LLM 是否开 thinking"来分叉，否则真实失败形态仍会漏网：
一律"有则回传、无则不动"。全仓构造 LLM 请求的地点必须经由此模块，**禁止**各处各写一份
（抄两份的代价：某一条路径漏回传 ⇒ 同一条 400 换个地方复发）。
"""
from __future__ import annotations

from typing import Any, List

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage

#: 需要回传的字段名（上游约定）；只在**上游给过**时才回传。
REASONING_KEY = "reasoning_content"


def ensure_reasoning_content(messages: List[Any]) -> List[Any]:
    """返回**带 `reasoning_content` 回传**的消息列表（只读变换，不改调用方对象）。

    规则（单一来源，上游契约的唯一定义处）：

    1. `AIMessage.additional_kwargs["reasoning_content"]` **有值** ⇒ 该消息以副本形式
       带上该键（有则原样回传）；
    2. **没有** ⇒ 一个字段都不加（无则不得凭空造）；
    3. 调用方传入的消息对象**不被就地改写** —— 它们常与会话历史 / `state["messages"]`
       共享引用，就地写会把状态面污染成"我们伪造过思考内容"。

    未改动任何内容时**原样返回同一列表**（零拷贝快路径：绝大多数轮次无 reasoning）。

    实现注记：光把键放进 `additional_kwargs` **到不了请求体**（`_convert_message_to_dict`
    对 `additional_kwargs` 是白名单取值），所以真正接线在下方 `ReasoningPassthroughChatModel`
    的 payload 注入；本函数是"哪些消息该带、带什么"的**单一判据**，供单测与注入共用。
    """
    out: List[Any] = []
    changed = False
    for msg in messages:
        extra = getattr(msg, "additional_kwargs", None) or {}
        reasoning = extra.get(REASONING_KEY) if isinstance(msg, AIMessage) else None
        if not reasoning:
            out.append(msg)
            continue
        out.append(msg.model_copy(update={"additional_kwargs": {**extra,
                                                               REASONING_KEY: reasoning}}))
        changed = True
    return out if changed else messages


class ReasoningPassthroughChatModel:
    """把上面的单一来源接到**请求体组装点**的混入类（协作式继承）。

    ⚠️ 为什么不能只改消息对象就算了：`AIMessage.additional_kwargs` 里除
    `name` / `tool_calls` / `function_call` / `audio` 之外的键，在
    `_convert_message_to_dict` 里被**白名单**丢弃 —— 也就是说，把
    `reasoning_content` 放进 `additional_kwargs`（哪怕已经在里面）**根本到不了请求体**。
    故本混入在父类产出 payload 之后，按**位置对应**把该键补进 payload 的 assistant 消息。

    继承纪律：本混入必须写在继承列表**第一位**，且 MRO 中它后面那个类要**协作式**
    （自己的 `_get_request_payload` 走 `super()`），否则上层实现会被跳过。
    `ChatDeepSeek` 是协作式的（只做 content 归一化），故 `app/llm/factory.py` 用
    `(混入, ChatDeepSeek, ChatOpenAI)` 的组合 —— 顺序由单测钉死。
    """

    def _get_request_payload(
        self, input_: LanguageModelInput, *, stop: Any = None, **kwargs: Any
    ) -> dict:
        messages = self._convert_input(input_).to_messages()
        payload = super()._get_request_payload(messages, stop=stop, **kwargs)
        _inject_reasoning_content(payload.get("messages") or [], messages)
        return payload


def _inject_reasoning_content(payload_messages: List[dict], messages: List[Any]) -> None:
    """把源消息里**上游给过**的 `reasoning_content` 按位置补进 payload（就地）。

    位置对应是可靠的：父类的转换是**逐条一一对应**的（不增删消息），
    故 `payload_messages[i]` 恒对应 `messages[i]`。

    判据与 `ensure_reasoning_content` 是**同一条**（都读 `additional_kwargs[REASONING_KEY]`
    的真值），只是这里直接写 payload —— 因为 `_convert_message_to_dict` 对
    `additional_kwargs` 是白名单取值，光改消息对象根本到不了请求体。
    """
    for payload_msg, msg in zip(payload_messages, messages):
        if not isinstance(payload_msg, dict) or payload_msg.get("role") != "assistant":
            continue
        reasoning = (getattr(msg, "additional_kwargs", None) or {}).get(REASONING_KEY)
        if reasoning:
            payload_msg[REASONING_KEY] = reasoning
