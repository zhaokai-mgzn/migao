# GENERATED FILE — DO NOT EDIT
# 本文件由 render_cases.py 生成，勿手改（改了也留不住：下次重渲染会覆盖）
# 源: cases/*.yml（case-contract 单一源）
# 重新生成: python3 render_cases.py --cases <dir> --out-eval <包目录> --out-md <md>
# 域: category（源: cases/category.yml，3 条）

from ._schema import Difficulty, EvalCase, Skill

# ── CT-001 [NORMAL] 分类树（源: cases/category.yml）──
_CASE_CT_001 = EvalCase(
    id='CT-001',
    legacy_id='2.10',
    title='分类树',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=['看看商品分类'],
    expectations=['category_manage(action=tree)'],
    data_checks=['返回树形分类（data.tree）'],
    skip_reason='',
    tags=['query', 'tree'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── CT-002 [NORMAL] 创建分类（源: cases/category.yml）──
_CASE_CT_002 = EvalCase(
    id='CT-002',
    legacy_id='2.11',
    title='创建分类',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.NORMAL,
    user_inputs=["新建一个'轻奢系列'分类", '确认'],
    expectations=['category_manage(action=tree)'],
    data_checks=['name 必填校验通过后创建成功（扁平分类，无 parent 父分类，对齐 #2905）', '前置：分类树可查（category_manage action=tree）—— 工具返回 success=true 即证前置成立（机器计分口径；2026-09-24 issue #5247：原「分类管理写面可用且「轻奢系列」未被占用 / 写操作 success=true」随写能力下线必然为假 ⇒ 改判为只读面；原 `must_succeed` 已整格移除，见上）'],
    skip_reason='[backend-contract] #5247 B 端只读化（用户裁定 2026-09-23：B 端黄金策只做数据查询与分析，创建/更新能力与对应 tools 全部从 B 端移除）⇒ 本用例断言的「创建分类」（category_manage / action=create）已从 B 端下线、工具已收窄为只读。用例条目与退役理由保留（不删除）；断言面改判为存活的只读路径 category_manage(action=tree)（只读查询分类树）。本条的正确判定层 = 工具层单测与 B 端绑定判据（traces.tests 已钉住）⇒ 按 [backend-contract] 分类：判定不在 LLM 层。',
    tags=['create'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    namespaces=['category:轻奢系列'],
)

# ── CT-003 [ADVERSARIAL] 删除分类 - 二次确认 + 风险提示（源: cases/category.yml）──
_CASE_CT_003 = EvalCase(
    id='CT-003',
    legacy_id='2.12',
    title='删除分类 - 二次确认 + 风险提示',
    skill=Skill.PRODUCT,
    difficulty=Difficulty.ADVERSARIAL,
    user_inputs=["删除'轻奢系列'分类"],
    expectations=['direct_reply'],
    data_checks=['如实说明黄金策不做删除分类（B 端只读化 #5247：写能力与对应 tools 已从 B 端整体移除），并引导去后台商品分类页面；不得谎称已删除（原第 1 条「二次确认 + 风险提示后才执行删除」的写路径前提已消失 ⇒ 同条改判）', '前置：目标分类「轻奢系列」在位（否则「删除」没有对象、红的表现像「agent 不会删分类」）—— 删除写操作 success=true 即证前置成立；分类不在位 / 删除被拒时本判据判红，不与「agent 不会删分类」同形 ｜ ⚠️ 2026-09-24（issue #5247，B 端只读化）：删除能力已下线 ⇒ 该**写面前置必然为假**（悬空声明），改判为只读面：分类树可查（`category_manage(action=tree)`）返回 success=true 即证前置成立（机器计分口径不变；`must_succeed` 已整格移除）'],
    skip_reason='[backend-contract] #5247 B 端只读化（用户裁定 2026-09-23：B 端黄金策只做数据查询与分析，创建/更新能力与对应 tools 全部从 B 端移除）⇒ 本用例断言的「删除分类」（category_manage / action=delete）已从 B 端下线、工具已收窄为只读。用例条目与退役理由保留（不删除）；断言面改判为**如实说明 + 引导去后台商品分类页面**（没有存活的只读路径可承载删除 ⇒ 用既有伪工具形态 direct_reply）。本条的正确判定层 = 工具层单测与 B 端绑定判据（traces.tests 已钉住）⇒ 按 [backend-contract] 分类：判定不在 LLM 层。',
    tags=['delete', 'destructive', 'confirm'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    namespaces=['category:轻奢系列'],
)

CASES = (
    _CASE_CT_001,
    _CASE_CT_002,
    _CASE_CT_003,
)
