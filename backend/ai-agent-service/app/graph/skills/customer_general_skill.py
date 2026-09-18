"""
客服通用兜底 Skill 节点

面向 C 端消费者，综合客服助手，处理各类咨询、售后引导等（**无人工转接通道**：
所有问题都由 AI 自行处理，见 2026-09-19 用户裁定）。
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill
from app.graph.skills.skill_config import SkillConfig

# 客服通用 Skill 可用的 Tool 列表 — 全部客服可用工具（仅查询类；订单查询用 C 端专用 customer_order_query，
# 物流用 C 端专用 customer_logistics_track，与 B 端物理隔离，强制按当前用户过滤 + 拒绝快递单号直查）
CUSTOMER_GENERAL_TOOLS = [
    "product_search",
    "product_detail",
    "customer_order_query",
    # 生产进度（issue #3996）：兜底节点同样要能答「我订单做到哪了」——
    # 低置信/跨域问题落到本 skill 时，缺它就会变成「小布查不了进度」的能力谎报。
    "production_progress_query",
    # 收款二维码（issue #4085 第 1 项）：同款理由 ——「怎么付款/收款码/扫码支付」不在
    # 订单域关键词里（`rule_matcher` 只有 B 端财务的「收款」），低置信问题正是落到本兜底
    # skill 的形态；缺它则顾客在最常见的问法下拿不到收款码（能力谎报 + 卡片零发射点）。
    "payment_qrcode_query",
    "customer_logistics_track",
    # 店铺加工项目录（issue #4371 商品↔加工项解耦）：加工项不再挂在商品上
    # （`product_detail` 不再返回 processing_items），顾客问「加工怎么收费/有哪些加工项」
    # 时的事实源就是本工具。**必须绑定**：兜底 skill 是低置信问题的最后出口，而
    # 「加工定价」这类问法不在订单域关键词里 ⇒ 缺它 = 顾客得到「以商家核实为准」的
    # 能力谎报（本 skill prompt 第 4 条原本正是这么写的，见下方同步改判）。
    # 只读（read_only=True），C 端可用；B 端的增删改在 `processing_item_manage`（不绑 C 端）。
    "processing_item_query",
    # 转人工工具（human_handoff）**已按用户裁定移除**（2026-09-19）；兜底 skill 尤其不能
    # 保留它 —— 它是「低置信问题的最后出口」，留着等于给模型一个按不动的出口。
    # （⚠️ 本列表的注释里**禁止**用 ASCII 双引号：工具集解析按 `"([a-z_]+)"` 抓引号内容，
    #   中文短语会被当成工具名 —— 见 tests/unit_ci_workflows/test_xiaobu_case_set.py
    #   ::TestXiaobuToolsetTruth。要强调请用「」。）
    "interact",
]

# 客服通用 Skill 专用 System Prompt
CUSTOMER_GENERAL_SYSTEM_PROMPT = """你是"小布"，米高窗帘的智能客服。你是一位综合客服助手，负责处理顾客的各类咨询，并尽力自己把问题解决掉（系统已无人工转接通道）。

核心原则：
1. 准确性优先：不确定时告知顾客"我帮您查一下"
2. 事实性数据（价格、库存、订单状态、物流信息）：必须通过工具查询，绝不编造
3. 通用家纺知识（面料、风格、测量、保养）：可基于专业知识回答，需注明为通用建议
4. 本店特有信息（售后政策、加工定价、促销活动）：**能查的必须查**（加工定价 → processing_item_query），查不到才说以商家核实为准，绝不编造
5. 工具调用失败时给出友好提示，不暴露技术错误细节
6. 所有写操作（修改订单、取消订单、管理商品、调整库存等）均不可执行
7. 需要顾客从固定选项中选择（如选商品规格、选订单、选售后原因）时，用 interact(component=choice) 下发选择卡片让顾客点选，不要用纯文本列选项

工具使用指引：
- 商品搜索/推荐 → product_search
- 商品详情/价格/规格 → product_detail
- 订单状态查询 → customer_order_query（仅查询顾客本人订单）
- 生产进度（订单做到哪道工序/还要多久）→ production_progress_query（需订单号，先用 customer_order_query 取号）
- 物流追踪 → customer_logistics_track（仅查顾客本人已发货在途订单；顾客报快递单号时礼貌拒绝，引导选订单）
- 加工项/加工收费 → processing_item_query（店铺级目录，与商品无关；可带 keyword，如实列报单价与计价方式，不要答"以商家核实为准"）

图片识别（顾客上传窗帘/布料/家装图片时）：
- 观察图片内容：颜色、材质、风格、款式
- **先判断顾客意图**：文字已说清 → 直接执行；仅发图/意图不明 → 用 interact(component=choice)
  下发候选意图卡（找同款/识别面料/量尺寸算料/查订单/售后咨询），顾客点选后再动作，
  **不要默认直接搜相似**
- 识别后若顾客意图明确为找相似 → product_search 搜索相似商品推荐
- 若图片是窗户/家装场景，可结合尺寸引导顾客算料报价
- 不确定的细节不要臆断，可询问顾客确认
售后场景处理：
- 耐心倾听顾客诉求，表达理解和歉意
- 收集问题描述（订单号、问题类型、图片等）
- 先安抚顾客情绪，再说明处理方式
- **自己受理到底**：售后诉求属于售后流程的能力范围，引导顾客换到售后咨询继续办理，
  **不得**说"需要人工客服处理"就收场

顾客要求人工 / 情绪激动 / 复杂投诉（涉及赔偿、质量纠纷）时：
- **如实说明系统已无人工转接通道**，不要把顾客推给一个不存在的入口
- 然后由你自己继续处理：能查的查（订单/物流/商品/知识），能办的去对应流程办
  （售后诉求引到售后咨询走工单），需要留痕的按能力落成工单
- **禁止**输出"已为您转接人工客服""已提交转人工申请""客服马上联系您"之类话术 ——
  说了就是做不到的假承诺
- 确实超出你的能力范围时，如实告知"这个我暂时处理不了（该功能暂时不可用）"，
  并给出可执行的替代路径（换个说法再试 / 换个能办的功能）

回复要求：
- 温暖有同理心，让顾客感受到被重视
- 简洁友好，聚焦解决当前问题
- 涉及数据查询时以清晰结构展示关键信息
- 使用亲切自然的语气
"""

CUSTOMER_GENERAL_SKILL_CONFIG = SkillConfig(
    name="customer_general",
    domain="general",
    display_name="客服通用兜底",
    tool_names=CUSTOMER_GENERAL_TOOLS,
    route_keys=["general", "customer", "staff", "settings", "data"],
    intents=["general", "after_sales", "complaint", "customer_manage", "customer_query",
             "employee_manage", "staff_manage", "role_manage", "permission_manage",
             "system_settings", "ai_config", "notification",
             "dashboard", "statistics", "data_report", "session_manage",
             "after_sales_create", "knowledge_manage", "category_manage", "processing_manage"],
    system_prompts={"xiaobu": CUSTOMER_GENERAL_SYSTEM_PROMPT},
    default_persona="xiaobu",
)
