"""
后续问题建议生成器

在 AI 回复结束后，自动推荐 2-3 个后续问题建议，引导用户继续对话。

策略：
- 高频意图使用预设模板（<5ms）
- 涉及具体实体时使用轻量模型动态生成（~100-200ms）
- 超时或失败时返回预设模板兜底

Agent 感知：
- 米宝（mibao）：企业内部员工的 AI 助手和 AI 操作系统，B 端管理视角
- 小布（xiaobu）：C 端智能客服，消费者视角
"""

import json
import re
from typing import Optional

import httpx
from langchain_core.messages import HumanMessage
from loguru import logger

from app.config import settings
from app.llm import LLMFactory, MINIMAX_API_KEY, cost_tracker


# ========== Stage hint 映射（用于预设 fallback 和动态 prompt） ==========

STAGE_HINTS: dict[str, str] = {
    "initial": "用户刚开始对话，建议探索性、引导性问题，帮助用户发现系统能力",
    "querying": "用户已获得信息，建议深层钻取问题，帮用户进一步分析具体数据",
    "confirming": "用户即将执行操作，建议帮助用户确认操作细节、核对关键信息，或询问是否确认提交",
    "processing": "用户正在处理业务，建议相关辅助操作或快捷入口",
    "completed": "对话即将结束，建议开启新话题或查看汇总数据",
}

# ========== 米宝预设建议（B 端：企业内部员工的 AI 助手和 AI 操作系统） ==========
# 结构: intent_type → stage → [suggestions]
# stage fallback 链: 指定 stage → querying → general/default
# farewell 返回空列表（用户要走了，不推荐）

MIBAO_PRESET_SUGGESTIONS: dict[str, dict[str, list[str]]] = {
    # --- 订单域 ---
    "order_query": {
        "initial":   ["查看今日新订单", "筛选待发货订单", "查看异常订单"],
        "querying":  ["查看该订单物流", "查看客户历史订单", "修改订单状态"],
        "confirming": ["确认订单信息", "打印发货单", "通知客户发货"],
        "processing": ["查看关联售后工单", "查看商品库存", "导出订单报表"],
        "completed":  ["查看今日订单汇总", "处理下一订单", "查看经营数据"],
    },
    "order_create": {
        "initial":   ["查看待处理订单", "查看商品列表", "新建客户订单"],
        "querying":  ["选择商品添加到订单", "填写客户收货信息", "查看历史订单参考"],
        "confirming": ["确认订单金额", "提交订单", "通知仓库备货"],
        "processing": ["查看物流发货", "打印订单详情", "查看关联客户信息"],
        "completed":  ["查看今日新订单", "查看订单趋势", "查看库存变化"],
    },
    "logistics_track": {
        "initial":   ["查看待发货订单", "查看物流异常件", "批量查询物流"],
        "querying":  ["查看签收状态", "查看物流轨迹详情", "联系快递催件"],
        "confirming": ["确认签收", "处理异常签收", "通知客户已签收"],
        "processing": ["查看关联订单详情", "查看客户联系方式", "记录物流备注"],
        "completed":  ["查看物流状态汇总", "查看待处理物流", "查看今日发货量"],
    },
    "after_sales": {
        "initial":   ["查看待处理工单", "查看工单分类统计", "查看退款申请"],
        "querying":  ["查看工单处理进度", "查看关联订单详情", "查看客户历史工单"],
        "confirming": ["同意退款申请", "拒绝并说明原因", "转主管审核"],
        "processing": ["查看退款政策", "查看商品售后记录", "记录处理备注"],
        "completed":  ["查看工单处理汇总", "查看售后趋势分析", "处理下一工单"],
    },
    "after_sales_create": {
        "initial":   ["查看已有工单", "查看退款政策", "查看待处理售后"],
        "querying":  ["选择售后类型", "填写售后原因", "上传相关凭证"],
        "confirming": ["确认创建工单", "查看工单详情", "通知相关部门"],
        "processing": ["查看关联订单", "查看客户沟通记录", "添加处理备注"],
        "completed":  ["查看工单列表", "查看售后统计", "创建新工单"],
    },
    "complaint": {
        "initial":   ["查看待处理投诉", "查看投诉分类", "查看高优先级投诉"],
        "querying":  ["查看投诉详情", "查看关联订单", "查看客户历史记录"],
        "confirming": ["提出处理方案", "升级主管处理", "联系客户致歉"],
        "processing": ["查看投诉处理规范", "记录处理过程", "跟踪处理进度"],
        "completed":  ["查看投诉处理汇总", "分析投诉原因", "查看满意度趋势"],
    },
    # --- 商品域 ---
    "product_inquiry": {
        "initial":   ["查看商品列表", "按分类浏览商品", "搜索商品信息"],
        "querying":  ["查看商品详情", "查看商品库存", "查看关联加工项"],
        "confirming": ["修改商品信息", "调整商品价格", "更新商品图片"],
        "processing": ["查看商品销量", "查看商品评价", "查看关联订单"],
        "completed":  ["查看商品总览", "查看新品上架", "查看库存预警"],
    },
    "category_manage": {
        "initial":   ["查看分类列表", "查看分类树结构", "搜索特定分类"],
        "querying":  ["查看分类下商品", "查看分类销量统计", "调整分类排序"],
        "confirming": ["新建子分类", "修改分类名称", "合并重复分类"],
        "processing": ["批量移动商品", "查看分类效果", "设置分类属性"],
        "completed":  ["查看分类总览", "查看分类统计报表", "优化分类结构"],
    },
    "processing_manage": {
        "initial":   ["查看加工项列表", "查看加工项分类", "搜索加工项"],
        "querying":  ["查看加工项详情", "查看关联商品", "查看加工项价格"],
        "confirming": ["新增加工项", "修改加工项信息", "调整加工价格"],
        "processing": ["查看加工项使用统计", "查看关联订单量", "批量调整价格"],
        "completed":  ["查看加工项总览", "查看热门加工项", "查看加工收入"],
    },
    # --- 客户域 ---
    "customer_manage": {
        "initial":   ["查看客户列表", "搜索客户信息", "查看新增客户"],
        "querying":  ["查看客户详情", "查看客户历史订单", "查看客户标签"],
        "confirming": ["修改客户信息", "添加客户备注", "设置客户等级"],
        "processing": ["查看客户消费统计", "查看客户售后记录", "发送客户关怀"],
        "completed":  ["查看客户总览", "查看客户增长趋势", "查看活跃客户"],
    },
    "customer_query": {
        "initial":   ["查看客户列表", "搜索客户信息", "查看今日新增客户"],
        "querying":  ["查看客户详情", "查看客户历史订单", "查看客户偏好标签"],
        "confirming": ["添加跟进备注", "设置客户标签", "分配跟进人"],
        "processing": ["查看客户沟通记录", "查看客户消费趋势", "推荐关联商品"],
        "completed":  ["查看客户分析报表", "查看客户分层", "批量导入客户"],
    },
    # --- 人事域 ---
    "employee_manage": {
        "initial":   ["查看员工列表", "查看部门架构", "搜索员工信息"],
        "querying":  ["查看员工详情", "查看员工角色权限", "查看员工绩效"],
        "confirming": ["修改员工信息", "调整员工角色", "设置员工权限"],
        "processing": ["查看员工操作日志", "查看员工服务统计", "重置员工密码"],
        "completed":  ["查看员工总览", "查看部门统计", "新增员工账号"],
    },
    "staff_manage": {
        "initial":   ["查看员工列表", "查看部门架构", "查看角色分配"],
        "querying":  ["查看员工详情", "查看员工权限明细", "查看员工出勤"],
        "confirming": ["调整岗位", "修改权限", "更新员工档案"],
        "processing": ["查看员工考核记录", "查看员工培训记录", "安排轮岗"],
        "completed":  ["查看人事报表", "查看编制统计", "查看离职率"],
    },
    "role_manage": {
        "initial":   ["查看角色列表", "查看角色权限树", "查看角色分配情况"],
        "querying":  ["查看角色详情", "查看角色关联员工", "查看角色操作日志"],
        "confirming": ["新增角色", "修改角色权限", "调整角色菜单"],
        "processing": ["批量分配角色", "复制角色权限", "查看权限冲突"],
        "completed":  ["查看角色总览", "查看权限分布", "优化角色体系"],
    },
    "permission_manage": {
        "initial":   ["查看权限列表", "查看菜单配置", "查看权限分配情况"],
        "querying":  ["查看权限详情", "查看关联角色", "查看权限使用统计"],
        "confirming": ["新增权限项", "修改权限配置", "调整菜单可见性"],
        "processing": ["批量授权", "查看权限变更记录", "权限安全审计"],
        "completed":  ["查看权限总览", "查看权限风险", "优化权限体系"],
    },
    # --- 系统配置域 ---
    "system_settings": {
        "initial":   ["查看系统配置", "查看通知设置", "查看AI配置"],
        "querying":  ["查看配置详情", "查看配置变更记录", "对比默认配置"],
        "confirming": ["修改配置项", "保存配置变更", "恢复默认配置"],
        "processing": ["查看配置生效状态", "灰度发布配置", "配置备份"],
        "completed":  ["查看配置总览", "查看配置审计", "优化系统参数"],
    },
    "ai_config": {
        "initial":   ["查看当前模型", "查看AI对话统计", "查看Token用量"],
        "querying":  ["查看模型参数详情", "查看各模块AI用量", "查看回复质量"],
        "confirming": ["切换AI模型", "调整Temperature", "修改系统提示词"],
        "processing": ["查看模型效果对比", "A/B测试提示词", "查看成本分析"],
        "completed":  ["查看AI配置总览", "查看月度AI报告", "优化AI策略"],
    },
    "notification": {
        "initial":   ["查看未读通知", "查看通知历史", "查看通知设置"],
        "querying":  ["查看通知详情", "查看同类型通知", "查看通知发送记录"],
        "confirming": ["标记已读", "设置通知规则", "开启/关闭推送"],
        "processing": ["批量标记已读", "导出通知记录", "设置免打扰时段"],
        "completed":  ["查看通知汇总", "查看通知统计", "清理历史通知"],
    },
    "quick_reply": {
        "initial":   ["查看快捷回复", "查看回复模板", "按分类浏览回复"],
        "querying":  ["查看回复详情", "查看回复使用统计", "搜索回复内容"],
        "confirming": ["新增快捷回复", "修改回复内容", "调整回复分类"],
        "processing": ["批量导入回复", "导出回复模板", "设置快捷回复快捷键"],
        "completed":  ["查看回复总览", "查看热门回复", "优化回复模板"],
    },
    # --- 数据分析域 ---
    "dashboard": {
        "initial":   ["查看今日经营数据", "查看订单趋势", "查看客户增长"],
        "querying":  ["查看销售明细", "对比上月数据", "查看分品类统计"],
        "confirming": ["导出数据报表", "设置数据预警", "分享数据看板"],
        "processing": ["查看实时数据", "查看异常指标", "刷新数据缓存"],
        "completed":  ["查看周报汇总", "查看月度趋势", "开启新数据查询"],
    },
    "statistics": {
        "initial":   ["查看今日订单", "查看销售趋势", "查看订单状态分布"],
        "querying":  ["按时间段筛选", "按品类对比分析", "查看区域销售分布"],
        "confirming": ["导出统计报表", "设置自动推送", "保存查询条件"],
        "processing": ["查看环比增长率", "查看同比数据", "钻取异常数据"],
        "completed":  ["查看统计总览", "查看月度报表", "新建统计查询"],
    },
    "data_report": {
        "initial":   ["查看订单统计", "查看销售趋势", "查看客户分析"],
        "querying":  ["选择报表维度", "设置时间范围", "对比历史数据"],
        "confirming": ["生成报表", "导出Excel", "定时发送报表"],
        "processing": ["查看报表生成进度", "预览报表内容", "调整报表参数"],
        "completed":  ["查看报表列表", "查看已发送报表", "新建自定义报表"],
    },
    "session_manage": {
        "initial":   ["查看在线会话", "查看会话统计", "查看活跃客户"],
        "querying":  ["查看会话详情", "查看会话消息记录", "查看客户信息"],
        "confirming": ["转接人工客服", "标记会话标签", "设置会话优先级"],
        "processing": ["查看等待队列", "批量分配会话", "设置自动回复"],
        "completed":  ["查看会话汇总", "查看客服绩效", "优化会话策略"],
    },
    # --- 知识库域 ---
    "knowledge_faq": {
        "initial":   ["查看常见问题", "搜索知识内容", "按分类浏览FAQ"],
        "querying":  ["查看FAQ详情", "查看关联FAQ", "查看FAQ阅读量"],
        "confirming": ["标记为有用", "反馈FAQ问题", "申请更新FAQ"],
        "processing": ["查看FAQ覆盖率", "查看热门搜索词", "补充遗漏FAQ"],
        "completed":  ["查看FAQ总览", "查看FAQ效果分析", "浏览其他分类"],
    },
    "knowledge_manage": {
        "initial":   ["查看知识条目", "搜索知识内容", "查看分类统计"],
        "querying":  ["查看知识详情", "查看关联知识", "查看知识使用频率"],
        "confirming": ["新增知识条目", "修改知识内容", "调整知识分类"],
        "processing": ["批量导入知识", "审核待发布知识", "下架过期知识"],
        "completed":  ["查看知识库总览", "查看知识覆盖报告", "优化知识结构"],
    },
    # --- 通用 ---
    "greeting": {
        "initial":   ["查看今日订单", "查看经营数据", "查看待处理事项"],
        "querying":  ["查看订单详情", "查看客户信息", "查看数据分析"],
        "confirming": ["查看待办事项", "查看系统通知", "查看快捷操作"],
        "processing": ["查看工作进度", "查看团队动态", "查看消息通知"],
        "completed":  ["开启新对话", "查看帮助文档", "反馈使用体验"],
    },
    "capabilities": {
        "initial":   ["查看商品管理", "查看订单处理", "查看数据分析"],
        "querying":  ["试试订单查询", "试试客户管理", "试试数据报表"],
        "confirming": ["查看功能列表", "查看快捷操作", "查看使用帮助"],
        "processing": ["查看操作指引", "查看视频教程", "联系技术支持"],
        "completed":  ["查看功能总览", "查看更新日志", "反馈功能建议"],
    },
    "farewell": {},
    "general": {
        "initial":   ["查看今日订单", "查看经营数据", "搜索帮助内容"],
        "querying":  ["查看待办事项", "查看系统通知", "查看数据分析"],
        "confirming": ["查看快捷操作", "查看功能列表", "查看使用帮助"],
        "processing": ["查看工作台", "查看消息中心", "查看团队协作"],
        "completed":  ["开启新话题", "查看系统通知", "反馈使用体验"],
    },
}

# 米宝默认兜底建议（B 端管理视角）
MIBAO_DEFAULT_SUGGESTIONS: list[str] = ["查看待办事项", "查看经营数据", "查看系统通知"]


# ========== 小布预设建议（C 端：智能客服，消费者视角） ==========
# 结构: intent_type → stage → [suggestions]

XIAOBU_PRESET_SUGGESTIONS: dict[str, dict[str, list[str]]] = {
    "order_query": {
        "initial":   ["查看我的订单", "查看物流信息", "浏览热门商品"],
        "querying":  ["查看物流详情", "申请退货退款", "修改收货地址"],
        "confirming": ["确认收货地址", "选择退款原因", "提交申请"],
        "processing": ["查看退款进度", "联系人工客服", "查看退款政策"],
        "completed":  ["查看订单评价", "继续购物", "查看我的优惠券"],
    },
    "order_create": {
        "initial":   ["浏览商品", "查看购物车", "查看促销活动"],
        "querying":  ["选择商品规格", "查看商品详情", "咨询定制服务"],
        "confirming": ["确认订单信息", "选择支付方式", "使用优惠券"],
        "processing": ["查看订单状态", "查看预计发货时间", "修改订单备注"],
        "completed":  ["查看我的订单", "继续浏览商品", "查看会员权益"],
    },
    "logistics_track": {
        "initial":   ["查看物流信息", "查看我的订单", "查询快递进度"],
        "querying":  ["查看物流轨迹", "确认收货", "查看预计送达时间"],
        "confirming": ["确认收货", "延长收货时间", "联系快递员"],
        "processing": ["查看签收详情", "评价商品", "查看售后政策"],
        "completed":  ["查看其他订单物流", "浏览商品", "联系客服"],
    },
    "product_inquiry": {
        "initial":   ["浏览热门商品", "查看新品上架", "按分类浏览"],
        "querying":  ["查看商品详情", "查看商品规格", "咨询定制服务"],
        "confirming": ["加入购物车", "立即购买", "收藏商品"],
        "processing": ["查看相似商品", "查看商品评价", "咨询优惠活动"],
        "completed":  ["继续浏览商品", "查看购物车", "查看我的收藏"],
    },
    "after_sales": {
        "initial":   ["查看售后进度", "申请售后服务", "查看退款政策"],
        "querying":  ["查看工单详情", "查看处理进度", "补充售后说明"],
        "confirming": ["确认退款金额", "选择退货方式", "提交售后申请"],
        "processing": ["查看退款进度", "联系人工客服", "查看退货地址"],
        "completed":  ["评价售后服务", "查看其他订单", "继续购物"],
    },
    "knowledge_faq": {
        "initial":   ["查看常见问题", "搜索帮助内容", "咨询具体问题"],
        "querying":  ["查看问题详情", "查看关联问题", "咨询更多细节"],
        "confirming": ["标记已解决", "反馈问题不准确", "查看更多帮助"],
        "processing": ["联系人工客服", "查看视频教程", "下载使用手册"],
        "completed":  ["查看其他FAQ", "评价帮助内容", "反馈使用体验"],
    },
    "greeting": {
        "initial":   ["查看我的订单", "浏览热门商品", "咨询窗帘定制"],
        "querying":  ["查看订单物流", "了解促销活动", "咨询产品问题"],
        "confirming": ["查看购物车", "查看会员权益", "了解退换政策"],
        "processing": ["查看客服热线", "查看门店地址", "查看营业时间"],
        "completed":  ["开启新话题", "查看帮助中心", "反馈使用体验"],
    },
    "complaint": {
        "initial":   ["查看投诉处理进度", "提交新投诉", "查看投诉政策"],
        "querying":  ["查看投诉详情", "补充投诉说明", "联系主管处理"],
        "confirming": ["确认投诉内容", "上传相关凭证", "选择期望处理方式"],
        "processing": ["查看处理进度", "联系人工客服", "了解赔偿政策"],
        "completed":  ["评价投诉处理", "查看其他订单", "继续购物"],
    },
    "capabilities": {
        "initial":   ["查询订单", "浏览商品", "咨询问题"],
        "querying":  ["试试查订单物流", "试试咨询产品", "试试申请售后"],
        "confirming": ["查看功能列表", "联系人工客服", "查看帮助中心"],
        "processing": ["查看使用帮助", "联系在线客服", "查看常见问题"],
        "completed":  ["查看功能总览", "反馈功能建议", "开启新话题"],
    },
    "farewell": {},
    "general": {
        "initial":   ["查看我的订单", "浏览商品", "联系人工客服"],
        "querying":  ["查看物流信息", "了解促销活动", "咨询产品问题"],
        "confirming": ["查看帮助中心", "联系在线客服", "查看退换政策"],
        "processing": ["查看订单状态", "查看会员权益", "联系客服热线"],
        "completed":  ["开启新话题", "查看我的优惠券", "浏览新品推荐"],
    },
}

# 小布默认兜底建议（C 端消费者视角）
XIAOBU_DEFAULT_SUGGESTIONS: list[str] = ["查看我的订单", "浏览商品", "联系人工客服"]


# ========== 动态生成 Prompt（Agent 感知） ==========

MIBAO_DYNAMIC_PROMPT = """你是米宝，词元通达商家管理后台的企业内部 AI 工作助手。

根据以下对话内容，生成 3 个用户最可能继续询问的后续问题。

用户问题：{query}
AI 回复：{answer}
对话上下文：{context}

## 当前对话阶段：{stage}
{stage_hint}
{user_context}
{preference_context}
{entity_context}

## 米宝能力范围（只能建议这些能做的事）

✅ **能做**：查订单/物流、查商品/加工项、查看经营数据/统计报表、查客户信息、查知识库/FAQ
❌ **不能做**：打电话/发短信/发邮件、导出文件到本地、修改系统配置、操作第三方平台（微信/支付宝等）、线下操作（联系快递公司等）

## 要求

1. 问题要简短自然（≤15字），像企业内部员工会说的话
2. 问题必须与当前对话主题紧密相关，且比当前问题更具体（不要建议比用户原问题更泛的问题）
3. 问题必须在上述 ✅ 能力范围内
4. 问题之间不要重复
5. 直接返回 JSON 数组格式，不要其他内容

## 禁止事项

- ❌ 不要建议 AI 已经在回复中明确回答过的问题（如回复已展示订单详情，不要再建议"查看订单详情"）
- ❌ 不要建议比用户当前问题更泛的问题（如用户问具体订单物流，不要建议"查看订单列表"）
- ❌ 不要建议"查看所有XX"这类泛泛的列表查看，建议具体的下一步操作

输出格式示例：["问题1", "问题2", "问题3"]"""

XIAOBU_DYNAMIC_PROMPT = """你是小布，面向消费者的智能客服助手。
根据以下对话内容，生成 3 个用户最可能继续询问的后续问题。

用户问题：{query}
AI 回复：{answer}
对话上下文：{context}

## 当前对话阶段：{stage}
{stage_hint}
{user_context}
{preference_context}
{entity_context}

## 要求

1. 问题要简短自然（≤15字），像消费者会说的话
2. 问题必须与当前对话主题紧密相关（商品咨询、订单查询、售后服务等），且比当前问题更具体
3. 问题之间不要重复
4. 直接返回 JSON 数组格式，不要其他内容

## 禁止事项

- ❌ 不要建议 AI 已经在回复中明确回答过的问题
- ❌ 不要建议比用户当前问题更泛的问题（如用户问具体订单物流，不要建议"查看我的订单"）

输出格式示例：["问题1", "问题2", "问题3"]"""


# 用于检测回复中是否包含具体实体的正则
_ENTITY_PATTERNS = [
    re.compile(r"订单号[：:\s]*\w+"),
    re.compile(r"[A-Z]{2}\d{9,}[A-Z]{2}"),  # 物流单号
    re.compile(r"商品[：:\s]*[「「【]?.+?[」」】]?"),
    re.compile(r"¥\d+"),  # 价格
    re.compile(r"\d{4}-\d{2}-\d{2}"),  # 日期
]


def _has_specific_entities(answer: str) -> bool:
    """检测回复中是否包含具体实体（订单号、商品名、价格等）"""
    for pattern in _ENTITY_PATTERNS:
        if pattern.search(answer):
            return True
    return False


def _parse_suggestions_from_response(text: str) -> Optional[list[str]]:
    """从模型响应中解析建议列表"""
    text = text.strip()
    # 尝试直接解析 JSON 数组
    try:
        result = json.loads(text)
        if isinstance(result, list) and all(isinstance(s, str) for s in result):
            return result[:3]
    except json.JSONDecodeError:
        pass

    # 尝试从文本中提取 JSON 数组
    match = re.search(r"\[.*?\]", text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, list) and all(isinstance(s, str) for s in result):
                return result[:3]
        except json.JSONDecodeError:
            pass

    return None


def _sanitize_prompt_value(value: str, max_len: int = 200) -> str:
    """清洗注入 prompt 的用户输入值：移除花括号防注入、移除换行、截断长度"""
    if not value:
        return ""
    # 移除花括号（防止 str.format() 注入和崩溃）
    value = value.replace("{", "｛").replace("}", "｝")
    # 移除换行符和制表符
    value = value.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    # 截断
    if len(value) > max_len:
        value = value[:max_len]
    return value


def _safe_format(template: str, **kwargs) -> str:
    """安全的模板填充：先清洗所有值再 format，防止注入和崩溃"""
    safe_kwargs = {}
    for key, val in kwargs.items():
        if isinstance(val, str):
            safe_kwargs[key] = _sanitize_prompt_value(val)
        else:
            safe_kwargs[key] = val
    return template.format(**safe_kwargs)


# 懒加载 PreferenceTracker 单例
_pref_tracker = None


def _get_preference_tracker():
    """懒加载 PreferenceTracker（避免循环导入）"""
    global _pref_tracker
    if _pref_tracker is None:
        from app.suggestions.preference_tracker import PreferenceTracker
        _pref_tracker = PreferenceTracker()
    return _pref_tracker


class FollowUpSuggestionGenerator:
    """后续问题建议生成器（Agent 感知）"""

    def __init__(self):
        self._api_key = MINIMAX_API_KEY
        self._model = settings.INTENT_MODEL  # 轻量模型，关闭思考模式
        self._llm = None  # 懒加载 LangChain LLM 实例

    async def generate(
        self,
        query: str,
        answer: str,
        intent_type: str,
        chat_history: Optional[list] = None,
        agent_type: str = "mibao",
        stage: str = "initial",
        session_id: str = "",
        tenant_id: int = 0,
        user_id: int = 0,
        user_role: str = "",
        user_name: str = "",
        entities: Optional[list[dict]] = None,
    ) -> list[str]:
        """
        生成 2-3 个后续问题建议

        Args:
            query: 用户原始问题
            answer: AI 回复内容
            intent_type: 意图类型
            chat_history: 对话历史消息列表（LangChain messages）
            agent_type: Agent 类型（"mibao" 或 "xiaobu"）
            stage: 对话阶段 (initial/querying/confirming/processing/completed)
            session_id: 会话 ID（用于日志）
            tenant_id: 租户 ID（用于日志）
            user_id: 用户 ID（用于日志 + 偏好查询）
            user_role: 用户角色（admin/agent/operator 等）
            user_name: 用户昵称
            entities: 本轮对话涉及的具体实体列表

        Returns:
            2-3 个后续问题建议字符串列表
        """
        strategy = "preset"
        try:
            # 智能选择策略：有 API Key 且回复涉及具体内容时优先动态生成
            if self._should_use_dynamic(answer, intent_type):
                # 查询用户偏好（用于动态 Prompt 注入）
                preference_intents = None
                if tenant_id and user_id:
                    try:
                        tracker = _get_preference_tracker()
                        preference_intents = await tracker.get_top_intents(
                            tenant_id, user_id, limit=3
                        )
                    except Exception:
                        pass  # 偏好查询失败不影响主流程

                suggestions = await self._generate_dynamic(
                    query, answer, agent_type,
                    chat_history=chat_history,
                    stage=stage,
                    user_role=user_role,
                    user_name=user_name,
                    entities=entities,
                    preference_intents=preference_intents,
                )
                if suggestions:
                    strategy = "dynamic"
                    result = suggestions[:3]
                    self._log_generation(
                        query, answer, intent_type, agent_type, stage,
                        session_id, tenant_id, user_id, strategy, result,
                    )
                    return result

            # 使用预设模板
            result = self._get_preset(intent_type, agent_type, stage)
            self._log_generation(
                query, answer, intent_type, agent_type, stage,
                session_id, tenant_id, user_id, strategy, result,
            )
            return result

        except Exception as e:
            logger.warning(f"Failed to generate follow-up suggestions: {e}")
            result = self._get_preset(intent_type, agent_type, stage)
            self._log_generation(
                query, answer, intent_type, agent_type, stage,
                session_id, tenant_id, user_id, "preset(fallback)", result,
            )
            return result

    @staticmethod
    def _log_generation(
        query: str,
        answer: str,
        intent_type: str,
        agent_type: str,
        stage: str,
        session_id: str,
        tenant_id: int,
        user_id: int,
        strategy: str,
        suggestions: list[str],
    ) -> None:
        """输出结构化日志，用于后续训练数据分析

        ⚠️ 数据安全：日志包含用户对话内容（已脱敏手机号/邮箱），
        应配置日志访问权限和保留策略，仅用于产品体验优化分析。
        """
        import json as _json
        from app.utils.log_sanitizer import LogSanitizer

        sanitized_suggestions = [LogSanitizer.mask_text(s) for s in suggestions]
        logger.info(
            "[suggestion:generated]",
            _json.dumps({
                "session_id": session_id,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "agent_type": agent_type,
                "intent_type": intent_type,
                "stage": stage,
                "strategy": strategy,
                "user_query": LogSanitizer.mask_text(query[:100]),
                "ai_answer": LogSanitizer.mask_text(answer[:150]),
                "suggestions": sanitized_suggestions,
            }, ensure_ascii=False),
        )

    def _should_use_dynamic(self, answer: str, intent_type: str) -> bool:
        """判断是否应该使用动态生成

        当回复内容包含具体信息（数字、状态、实体名称等）时使用动态生成，
        比纯正则检测更宽松，覆盖更多真实场景。
        """
        # 没有 API Key 时不使用动态生成
        if not self._api_key:
            return False
        # 回复太短（如问候语）不使用动态生成
        if len(answer) < 20:
            return False
        # 回复包含中文实体相关关键词时使用动态生成
        entity_keywords = [
            "订单", "商品", "客户", "物流", "退款", "发货", "收货",
            "工单", "售后", "投诉", "统计", "数据", "报表", "加工",
        ]
        if any(kw in answer for kw in entity_keywords):
            return True
        # 兜底：回复足够长时也尝试动态生成（避免漏掉）
        if len(answer) > 100:
            return True
        return _has_specific_entities(answer)

    def _get_preset(self, intent_type: str, agent_type: str = "mibao", stage: str = "querying") -> list[str]:
        """获取预设建议模板（Agent 感知 + Stage 感知）

        Fallback 链: intent[stage] → intent["querying"] → intent["initial"] → 第一个非空 stage → defaults
        """
        presets = XIAOBU_PRESET_SUGGESTIONS if agent_type == "xiaobu" else MIBAO_PRESET_SUGGESTIONS
        defaults = XIAOBU_DEFAULT_SUGGESTIONS if agent_type == "xiaobu" else MIBAO_DEFAULT_SUGGESTIONS

        intent_suggestions = presets.get(intent_type)
        if intent_suggestions is None:
            intent_suggestions = presets.get("general", {})

        # 空 dict 表示不需要建议（如 farewell）
        if isinstance(intent_suggestions, dict) and len(intent_suggestions) == 0:
            return []

        if isinstance(intent_suggestions, dict):
            # 按 stage 查找，fallback: 指定 stage → querying → 第一个可用 stage → defaults
            for fallback_stage in (stage, "querying", "initial"):
                suggestions = intent_suggestions.get(fallback_stage)
                if suggestions:
                    return suggestions
            # 如果以上都没有，取第一个非空 stage
            for s in intent_suggestions.values():
                if s:
                    return s

        return defaults

    async def _generate_dynamic(
        self, query: str, answer: str, agent_type: str = "mibao",
        chat_history: Optional[list] = None,
        stage: str = "querying",
        user_role: str = "",
        user_name: str = "",
        entities: Optional[list[dict]] = None,
        preference_intents: Optional[list[dict]] = None,
    ) -> Optional[list[str]]:
        """使用轻量模型动态生成后续问题建议（走 LangChain 统一接口）"""
        # 根据 agent_type 选择 prompt 和角色配置
        if agent_type == "xiaobu":
            prompt_template = XIAOBU_DYNAMIC_PROMPT
            # xiaobu 场景下所有用户均视为消费者（C 端定位）
            role_label = "消费者"
            permission_hint = "可查询订单、商品、售后信息"
            role_display = "小布"
        else:
            prompt_template = MIBAO_DYNAMIC_PROMPT
            role_display = "米宝"
            # 角色白名单校验：未匹配角色统一标注为"员工"，不暴露原始值（防 prompt 注入）
            ROLE_LABELS = {
                "admin": "管理员（有全部权限）",
                "tenant_admin": "门店店长（管理订单、商品、客户、员工）",
                "agent": "客服人员（处理订单、售后、客户咨询）",
                "operator": "运营人员（查看数据、管理商品、处理订单）",
            }
            role_label = ROLE_LABELS.get(user_role, "员工") if user_role else "员工"
            permission_hint = "根据角色权限，可操作订单、商品、客户、数据等模块"

        # 构建 stage hint
        stage_hint = STAGE_HINTS.get(stage, STAGE_HINTS["querying"])

        # 构建用户上下文（清洗 user_name 防注入）
        user_context = ""
        safe_user_name = _sanitize_prompt_value(user_name, max_len=20) if user_name else ""
        name_part = f"（{safe_user_name}）" if safe_user_name else ""
        user_context = f"- 角色：{role_label}{name_part}\n- 权限范围：{permission_hint}"

        # 构建偏好上下文
        preference_context = ""
        if preference_intents:
            top_items = ", ".join(
                f"{_sanitize_prompt_value(item['label'], max_len=20)}({item['click_count']}次)"
                for item in preference_intents[:3]
            )
            preference_context = f"- 该用户最常使用：{top_items}\n- 请优先围绕这些方向提供建议。"

        # 构建实体上下文（清洗 entity labels 防注入）
        entity_context = ""
        if entities:
            entity_labels = [
                _sanitize_prompt_value(e.get("label", e.get("value", "")), max_len=30)
                for e in entities[:5]
            ]
            entity_labels = [l for l in entity_labels if l]  # 过滤空值
            if entity_labels:
                entity_text = "、".join(entity_labels)
                # initial 阶段弱化禁止性指令，避免与探索性引导冲突
                if stage == "initial":
                    entity_context = f"- 本轮对话涉及：{entity_text}\n- 请围绕这些具体对象，给用户提供下一步可以了解的探索方向。"
                else:
                    entity_context = f"- 本轮对话涉及：{entity_text}\n- 请围绕这些具体对象给出下一步操作建议（如具体到某个订单号/商品名），不要给泛泛的列表查看建议。"

        # 构建对话上下文（最近 3 轮，使用动态角色名）
        context_text = ""
        if chat_history:
            recent = chat_history[-6:]  # 最近 3 轮（每轮 user+assistant）
            lines = []
            for msg in recent:
                role = "用户" if getattr(msg, "type", "") == "human" else role_display
                content = getattr(msg, "content", "")
                if isinstance(content, str) and content.strip():
                    lines.append(f"{role}: {_sanitize_prompt_value(content, max_len=200)}")
            if lines:
                context_text = "\n".join(lines)

        # 使用安全格式化（清洗所有用户可控输入）
        prompt = _safe_format(
            prompt_template,
            query=query[:200],
            answer=answer[:500],
            context=context_text or "（无历史对话）",
            stage=stage,
            stage_hint=stage_hint,
            user_context=user_context or "（无用户上下文）",
            preference_context=preference_context or "（暂无用户偏好数据）",
            entity_context=entity_context or "（本轮未涉及具体实体）",
        )

        try:
            if self._llm is None:
                self._llm = LLMFactory.create_suggestion_llm()

            response = await self._llm.ainvoke([HumanMessage(content=prompt)])

            # 成本追踪（失败仅 warning）
            try:
                usage_meta = getattr(response, "usage_metadata", None) or {}
                input_tokens = int(usage_meta.get("input_tokens", 0) or 0)
                output_tokens = int(usage_meta.get("output_tokens", 0) or 0)
                if not (input_tokens or output_tokens):
                    resp_meta = getattr(response, "response_metadata", None) or {}
                    token_usage = resp_meta.get("token_usage") or resp_meta.get("usage") or {}
                    input_tokens = int(
                        token_usage.get("prompt_tokens")
                        or token_usage.get("input_tokens")
                        or 0
                    )
                    output_tokens = int(
                        token_usage.get("completion_tokens")
                        or token_usage.get("output_tokens")
                        or 0
                    )
                if input_tokens or output_tokens:
                    cost_tracker.track_call(
                        model=self._model,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                    )
            except Exception as track_exc:
                logger.warning(f"[follow_up] cost tracking failed: {track_exc}")

            content = response.content if isinstance(response.content, str) else ""
            return _parse_suggestions_from_response(content)

        except httpx.TimeoutException:
            logger.debug("Dynamic suggestion generation timed out, falling back to preset")
            return None
        except Exception as e:
            logger.warning(f"Dynamic suggestion generation failed: {e}")
            return None
