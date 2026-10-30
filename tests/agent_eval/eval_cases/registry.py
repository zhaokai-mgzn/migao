# GENERATED FILE — DO NOT EDIT
# 本文件由 render_cases.py 生成，勿手改（改了也留不住：下次重渲染会覆盖）
# 源: cases/*.yml（case-contract 单一源）
# 重新生成: python3 render_cases.py --cases <dir> --out-eval <包目录> --out-md <md>
# 域: registry（源: cases/registry.yml，1 条）

from ._schema import Difficulty, EvalCase, Skill

# ── RG-001 [NORMAL] ToolRegistry 注册/查询/执行审计（源: cases/registry.yml）──
_CASE_RG_001 = EvalCase(
    id='RG-001',
    legacy_id='',
    title='ToolRegistry 注册/查询/执行审计',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['ai-agent-service 注册工具并执行（含权限拒绝、写操作审计、异常泛化）'],
    expectations=['direct_reply'],
    data_checks=['register 重复名覆盖并 warning；unregister/get_tool/get_all_tools/get_tool_names/has_tool/clear 语义正确', 'get_tools_description 空注册器返回「暂无可用工具」；get_tool_registry 单例 + reset_tool_registry 重置', 'execute_tool 工具不存在→未知工具、权限不足→Permission denied、写操作（not read_only）记 [AUDIT] 日志且参数脱敏（仅记类型不记值）、执行异常→泛化 tool_execution_failed'],
    skip_reason='[backend-contract] 注册器/执行审计由 pytest 单测验证（tests/test_tools_registry.py），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['registry', 'tool_execute', 'audit'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

CASES = (
    _CASE_RG_001,
)
