# GENERATED FILE — DO NOT EDIT
# 本文件由 render_cases.py 生成，勿手改（改了也留不住：下次重渲染会覆盖）
# 源: cases/*.yml（case-contract 单一源）
# 重新生成: python3 render_cases.py --cases <dir> --out-eval <包目录> --out-md <md>
# 域: utils（源: cases/utils.yml，2 条）

from ._schema import Difficulty, EvalCase, Skill

# ── UT-001 [NORMAL] 跨服务字段映射 - Java camelCase ↔ Python snake_case 双向转换与兼容取值（源: cases/utils.yml）──
_CASE_UT_001 = EvalCase(
    id='UT-001',
    legacy_id='',
    title='跨服务字段映射 - Java camelCase ↔ Python snake_case 双向转换与兼容取值',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['admin-api 返回商品 {basePrice, mainImage, categoryId}，ai-agent-service 转 snake_case 后消费'],
    expectations=['direct_reply'],
    data_checks=['java_to_python 把 basePrice→price / mainImage→main_image / categoryId→category_id，未知字段原样保留', 'python_to_java 反向还原，自定义 mapping 生效', 'get_price 兼容 price/basePrice（含 price=0 的 `or` 链语义）；get_main_image 兼容 mainImage/main_image/images[0]；get_category_id 兼容 categoryId/category_id'],
    skip_reason='[backend-contract] 纯函数字段映射由 pytest 单测验证（tests/test_utils_field_mapper.py），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['utils', 'field_mapping', 'data_contract'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── UT-002 [NORMAL] 数据库会话生命周期 - commit/rollback/close 与连接探活（源: cases/utils.yml）──
_CASE_UT_002 = EvalCase(
    id='UT-002',
    legacy_id='',
    title='数据库会话生命周期 - commit/rollback/close 与连接探活',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['ai-agent-service 依赖注入获取 db session 执行查询'],
    expectations=['direct_reply'],
    data_checks=['get_db_session 正常路径 commit、异常路径 rollback 后向上抛、finally close', 'init_db SELECT 1 探活失败向上 raise；close_db dispose 连接池'],
    skip_reason='[backend-contract] DB 会话生命周期由 pytest 单测验证（tests/test_utils_database.py），非 LLM 行为，不进入 agent-eval 冒烟',
    tags=['utils', 'database', 'session_lifecycle'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

CASES = (
    _CASE_UT_001,
    _CASE_UT_002,
)
