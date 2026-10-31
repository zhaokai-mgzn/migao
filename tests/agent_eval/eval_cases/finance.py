# GENERATED FILE — DO NOT EDIT
# 本文件由 render_cases.py 生成，勿手改（改了也留不住：下次重渲染会覆盖）
# 源: cases/*.yml（case-contract 单一源）
# 重新生成: python3 render_cases.py --cases <dir> --out-eval <包目录> --out-md <md>
# 域: finance（源: cases/finance.yml，6 条）

from ._schema import Difficulty, EvalCase, Skill

# ── FN-001 [NORMAL] 资金流水查询（只读；原「登记线下收款」随 #5247 写能力下线改判）（源: cases/finance.yml）──
_CASE_FN_001 = EvalCase(
    id='FN-001',
    legacy_id='',
    title='资金流水查询（只读；原「登记线下收款」随 #5247 写能力下线改判）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['查一下最近的资金流水'],
    expectations=['finance_api(action=get_transactions)'],
    data_checks=['流水列表逐值来自服务端（finance_api get_transactions 的成功返回体由 output_verify 机器核对：items 非空）—— 只读：不得声称已登记 / 已入账（原第 1 条「流水号 FIN- 前缀由服务端生成、type=income、amount=88、status=success」是写路径的产出断言，已随 #5247 写能力下线改判）', '查询失败时不得声称查到：must_succeed 读 tool_result.success 判红，output_verify 无成功调用即判红（原第 2 条「登记失败时不得声称成功」同口径改判；只读用例不得声称已登记）', '前置：财务查询面可用 —— 查询返回 success=true 即证前置成立（机器计分口径，同 must_succeed；原「财务写面可用且本次登记可落库」随写 action 下线必然为假 ⇒ 改判为只读面）'],
    skip_reason='',
    tags=['finance', 'query'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
    must_succeed=[{'tool': 'finance_api'}],
    output_verify=[{'tool': 'finance_api', 'action': 'get_transactions', 'expect': {'items': '__nonempty__'}}],
    namespaces=['finance_txn:88'],
)

# ── FN-002 [NORMAL] 收支汇总（源: cases/finance.yml）──
_CASE_FN_002 = EvalCase(
    id='FN-002',
    legacy_id='',
    title='收支汇总',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['本月收入退款净额'],
    expectations=['finance_api(action=get_summary)'],
    data_checks=['netIncome = totalIncome - totalRefund'],
    skip_reason='',
    tags=['finance', 'summary'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── FN-003 [NORMAL] 应收对账（源: cases/finance.yml）──
_CASE_FN_003 = EvalCase(
    id='FN-003',
    legacy_id='',
    title='应收对账',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['哪些订单没对平'],
    expectations=['finance_api(action=get_reconciliation)'],
    data_checks=['每条 difference = receivedAmount - receivableAmount'],
    skip_reason='',
    tags=['finance', 'reconcile'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── FN-004 [NORMAL] 收支汇总默认本期（自然月）时间范围（源: cases/finance.yml）──
_CASE_FN_004 = EvalCase(
    id='FN-004',
    legacy_id='',
    title='收支汇总默认本期（自然月）时间范围',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['本期收入退款是多少'],
    expectations=['finance_api(action=get_summary)'],
    data_checks=['默认加载时开始/结束日期填充本期（本月1号~今天），getSummary/getTransactions/getReconciliation 均携带该范围', '本期时间范围由工具层兜底（#3288：缺时间参数自动补本月1号~今天）——agent 不显式传时间时服务端默认保证本期语义'],
    skip_reason='',
    tags=['finance', 'summary'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── FN-005 [NORMAL] 财务 / 订单日期窗口 = 业务日（+08）整天，不是 UTC 日（issue #6200：北京 00:00–08:00 的数据归错天/月/年）（源: cases/finance.yml）──
_CASE_FN_005 = EvalCase(
    id='FN-005',
    legacy_id='',
    title='财务 / 订单日期窗口 = 业务日（+08）整天，不是 UTC 日（issue #6200：北京 00:00–08:00 的数据归错天/月/年）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户 2026-10-03 报告（issue #6200）：日期查询窗口按 UTC 日界而不是 +08，北京 00:00–08:00 的数据归到错误的天/月/年'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**窗口 = 业务日整天**：`startDate=endDate=2026-10-03` 的两个查询参数必须恰好是 `2026-10-02T16:00Z`（= 北京 10-03 00:00）与 `2026-10-03T16:00Z`（= 北京 10-04 00:00，不含）—— 库列是 `timestamptz`，MyBatis-Plus 参数**惰性绑定** ⇒ 断言前必须先触发 `getSqlSegment()`（否则 `paramNameValuePairs` 恒为空 = 假绿）。执行点 = backend/admin-api/src/test/java/com/migao/admin/time/BusinessDayWindowTest.java 的 financeTxnWindowIsTheBusinessDayItself / financeSummaryWindowIsTheBusinessDayItself / orderListWindowIsTheBusinessDayItself。红证（改前实测）：实际绑成 `2026-10-03T00:00Z` … `2026-10-03T23:59:59Z`（UTC 日）⇒ 该三条判据全红（读数 `Tests run: 8, Failures: 5`）。', '判据 2·**跨端点自洽（同系统内不得自相矛盾）**：同一笔「北京今日凌晨」记录，列表窗口起点必须等于 `BusinessClock.startOfDay(业务日)`（看板 / 订单趋势 / 简报用的同一只钟）。执行点 = 同文件 financeTxnWindowAgreesWithBusinessClock。实证档（只读）= acceptance/2026-10-03/finance-stock-time-sweep/out/C9-cross-endpoint.json：同一笔 `ordAt=2026-10-03 02:00+08` 的订单，看板 dashboardTodayOrders=351 收录而订单列表 listTotal=9 不收录（listHit=false）。', '判据 3·**跨月 / 跨年边界各落对月份**：`2026-10-01 00:00+08` 落 10 月、`2026-09-30 23:59:59+08` 落 9 月、`2026-01-01 00:01+08` 落 2026-01（改前会落进 2025-12-31）。执行点 = 同文件 monthEndToMonthStartFallsInTheRightMonths / yearBoundaryRecordFallsInTheNewYear（两条都带**缺陷形态自证**：同一时刻在 UTC 窗下判红 ⇒ 红的来源是日界本身，不是别的）。', '判据 4·**夹住边界 + 右界语义**：北京 `07:59:59` 与 `08:00:00` **同属当日**（都在业务日窗口内）；`endDate=D` 覆盖 D 当天整日（含 `23:59:59.999999999+08`），右界 = 次日业务日零点（不含）。执行点 = 同文件 boundaryPairIsInsideAndOutsideTheSameDay / windowCoversTheWholeDayNotToTheSecondBefore。红证：`T23:59:59Z` 在 +08 口径下等于「次日 07:59:59」⇒ 既漏掉当天 08:00 之后、又把次日凌晨 8 小时算进来（该自证断言改前为红）。', '判据 5·**类级固化（让同类进不来）**：admin-api/src/main 下出现 `T00:00:00Z` / `T23:59:59Z` 字面量、或日界形态的 `ZoneOffset.UTC` ⇒ 守卫判红（放行口径 = `now(ZoneOffset.UTC)` 这种「打时刻」拼写，闭括号紧邻）。执行点 = backend/admin-api/src/test/java/com/migao/admin/time/BusinessClockSourceGuardTest.java 的 onlyTheClockComponentReadsBusinessTimeFromMain + rulesHaveDiscriminatingPower（每条新禁则必须能命中一个坏样本 ⇒ 不会退化成空断言）。'],
    skip_reason='[backend-contract] 纯后端日期窗口判据（无 LLM 环节 ⇒ 不进 agent-eval 冒烟）：由 admin-api 单测 BusinessDayWindowTest + BusinessClockSourceGuardTest 执行',
    tags=['finance', 'time-window', 'admin-api', 'read-surface'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

# ── FN-006 [NORMAL] 涉钱入口的小数位准入：超 2 位有效小数显式拒绝、不静默四舍五入（issue #6228）（源: cases/finance.yml）──
_CASE_FN_006 = EvalCase(
    id='FN-006',
    legacy_id='',
    title='涉钱入口的小数位准入：超 2 位有效小数显式拒绝、不静默四舍五入（issue #6228）',
    skill=Skill.GENERAL,
    difficulty=Difficulty.NORMAL,
    user_inputs=['用户 2026-10-03 派单（issue #6228）：#6221 只修了订单退款一处，其余金额入口仍会把超精度金额静默交给 PG 四舍五入'],
    expectations=['direct_reply'],
    data_checks=['判据 1·**显式拒绝 + 零写入**：17 处金额入口（建单/改单的 setTotalAmount / setActualAmount / setDiscountAmount / setUnitPrice、售后 setRefundAmount、商品 setPrice / setBasePrice、批量改价 setBasePrice、入库 InboundOrderItem.builder() / setUnitCost、期初导入 setUnitCost、工人面 setUnitCost、加工费组合 setUnitPrice / builder、工序计件 setUnitPrice / builder、财务 FinanceTransaction.builder()）传 3 位有效小数（0.005 / 1.005 / 「积」1.5×0.01=0.015）⇒ 显式拒绝（常规 422、工人面 400）+ **写面零调用**（insert=never / updateById=never / updateProductForAgent=never）。执行点 = 各 service 单测（OrderServiceTest / InboundOrderServiceTest / FinanceServiceTest / AfterSalesTicketServiceTest / AgentBatchServiceTest / ProductServiceTest / OpeningRegisterImportServiceTest / WorkerInboundServiceTest / ProcessingFeeCombinationCommandServiceTest / ProductionOperationCommandServiceTest）。', '判据 2·**正对照（合法值逐字落库）**：2 位以内**有效**小数的值（0.01 = 1 分 / 12.50 / 31.250）**原样**落库（按 `toPlainString()` 逐字比对）；`null` 语义不变（退款金额未传 = 全额退，不得归一成 0）。', '判据 3·**类级固化（让同类进不来）**：backend/admin-api/src/test/java/com/migao/admin/service/MoneyEntryPrecisionMetaGuardTest.java 的入口台账现取 DEBT = 0（冻结上限 0）—— 新金额写面未登记 / 债务条数增长 / 声称 GATED 但文件里没有 `MoneyScale.requireTwoDecimals` 文本 ⇒ 当场红并具名；台账条目空转（写面被删 / 改名）同样红。'],
    skip_reason='[backend-contract] 纯后端金额精度准入（无 LLM 环节 ⇒ 不进 agent-eval 冒烟）：由 admin-api 单测 MoneyEntryPrecisionMetaGuardTest + 10 个 service 单测执行',
    tags=['finance', 'money-precision', 'admin-api', 'write-surface'],
    persona='',
    debug_user='',
    form_prefill=[],
    forbidden_card_text=[],
)

CASES = (
    _CASE_FN_001,
    _CASE_FN_002,
    _CASE_FN_003,
    _CASE_FN_004,
    _CASE_FN_005,
    _CASE_FN_006,
)
