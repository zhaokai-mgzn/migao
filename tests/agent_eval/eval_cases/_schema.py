# GENERATED FILE — DO NOT EDIT
# 本文件由 render_cases.py 生成，勿手改（改了也留不住：下次重渲染会覆盖）
# 源: cases/*.yml（case-contract 单一源）
# 重新生成: python3 render_cases.py --cases <dir> --out-eval <包目录> --out-md <md>
# 包内唯一 schema：EvalCase / Skill / Difficulty **只定义这一份**（域模块从 `._schema` 导入，不许复制第二份定义）

from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum


class Difficulty(Enum):
    SMOKE = "smoke"       # 冒烟，必须 100% 通过
    NORMAL = "normal"     # 正常流程
    EDGE = "edge"         # 边缘情况
    ADVERSARIAL = "adversarial"  # 对抗性，弱 LLM 可能挂


class Skill(Enum):
    PRODUCT = "product"
    ORDER = "order"
    AFTERSALES = "aftersales"
    CUSTOMER = "customer"
    CROSS = "cross"
    MULTI_TURN = "multi_turn"
    GENERAL = "general"


@dataclass
class EvalCase:
    id: str
    title: str
    skill: Skill
    difficulty: Difficulty
    # 每轮可为 str（纯文本）或 dict（{text, images[]} 带图消息，issue #2794）
    user_inputs: List[str]
    expectations: List[str]
    data_checks: List[str]
    skip_reason: str = ""
    legacy_id: str = ""
    tags: List[str] = field(default_factory=list)
    pre_turns: List = field(default_factory=list)
    persona: str = ""   # 归属 agent: mibao / xiaobu / ""(双端)，issue #2855
    order_before: List[str] = field(default_factory=list)   # 时序断言 "A before B"（跨轮，acceptance-protocol §3.1）
    forbidden_text: List[str] = field(default_factory=list) # final_text 反模式词，命中即失败（§3.4 幻觉式撤回/报错文案）
    forbidden_tools: List = field(default_factory=list) # 全程禁用工具断言（任何轮都不得调用；must_succeed 的镜像，issue #3544 收口批）
    want_text: List[str] = field(default_factory=list) # final_text 正向关键词，全缺即失败（§3.4 正反关键词双轨）
    required_args: List[dict] = field(default_factory=list) # 必填参数断言（create 缺 specifications/加工项价格即失败，§3.2）
    forbidden_args: List[dict] = field(default_factory=list) # 禁止参数断言（隔离/越权下限：如物流工具不得接受快递单号，issue #3270）
    must_succeed: List[dict] = field(default_factory=list) # 写工具成功断言（至少成功一次；"调了≠成了"，§3.2/issue #3361）
    must_fail: List[dict] = field(default_factory=list) # 必须失败断言（零成功调用；must_succeed 的镜像，issue #3544 收口批）
    amount_verify: List[dict] = field(default_factory=list) # 金额正确性断言（单价接地/小计/总额，§3.2/issue #3365）
    db_verify: List[dict] = field(default_factory=list) # 落库层验证（创建后查 admin-api 断言价格=确认价，§3.2/issue #3056）
    output_verify: List[dict] = field(default_factory=list) # 产出侧断言（工具计算结果 payload，如算料用布量/spec公式，issue #3367）
    pre_clean: List[dict] = field(default_factory=list) # 评测前数据清理（写类 case 自我污染防线）
    post_clean: List[dict] = field(default_factory=list) # 用例结束后复位共享夹具（写方复位，issue #4075）
    post_session: List[dict] = field(default_factory=list) # 会话关闭后落库断言（user_memories 只在 close 时 flush，issue #3357）
    debug_user: str = ""   # 多身份评测：以哪个 DEBUG 顾客身份跑（如 debug_customer_new，issue #3391）
    debug_permissions: str = ""   # 评测可控权限（B 端）：逗号分隔权限码，非空才下发 X-Debug-Permissions（issue #4108）
    form_prefill: List[dict] = field(default_factory=list) # form 卡预填断言（老客户收货信息自动带出，issue #3397）
    forbidden_card_text: List = field(default_factory=list) # 卡片内容反模式（卡里不得出现「用量/倍数」等把金额翻倍的框架，issue #3402）
    forbidden_interact: List = field(default_factory=list) # 负向**按轮**卡片约束（该轮不得出现 interact 卡 = 用例判别性红路径的形状前提，issue #3789）
    arg_values: List[dict] = field(default_factory=list) # 入参**值级**断言（值相等；证据 = 落盘的 round_trace[*].call_args，issue #3823）
    namespaces: List[str] = field(default_factory=list) # 全局命名空间声明（<kind>:<值>，如 customer_phone:13800138000）；两条用例有交集 → 自动串行（issue #3781 并行污染隔离）
    precondition: List[dict] = field(default_factory=list) # 运行期前置断言（order_count_for_phone：运行期间订单数不得增长；不成立则判「前置不成立」而非行为失败，issue #3781）
    auto_fill: dict = field(default_factory=dict) # **用例级**表单载荷（全场可用）：让客户信息脱离轮次位置（issue #3804）


