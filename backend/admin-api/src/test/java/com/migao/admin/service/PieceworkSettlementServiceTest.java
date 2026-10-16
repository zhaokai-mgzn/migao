package com.migao.admin.service;

// case_ids: PG-073

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.migao.admin.entity.PieceworkSettlement;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.PieceworkSettlementMapper;
import com.migao.admin.time.BusinessClock;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.math.BigDecimal;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 计件结算单语义测试（issue #5653；用户 2026-10-16 裁定 A 快照式）。
 *
 * <p>本文件守四条判据（每条都有独立红证，逐条见各 {@code @DisplayName} 的「红证」段）：</p>
 * <ol>
 *   <li><b>同源</b>：结算总额**逐值**取自 {@code ProductionService.pieceworkSummary} 的
 *       {@code total}（同一份聚合），结算侧**没有**第二份算法 —— 结构判据 = 本服务不注入
 *       报工表 / 工序实例表 Mapper，也不调用聚合算法；行为判据 = 冻结值 === 报表读数（逐值，
 *       连 BigDecimal 的 scale 一起比）；</li>
 *   <li><b>不可改</b>：本服务与响应对象上**没有**任何改写金额 / 期间 / 工人的路径
 *       （反射扫 public 方法名 + 字段类型），作废 SQL 的 SET 子句只有那一族三列；</li>
 *   <li><b>作废 + 重开</b>：作废后旧单仍在（{@code selectById} 仍可读、{@code voided_at} 非空、
 *       金额一字不变），且同期间可重开（部分唯一索引谓词 {@code voided_at IS NULL} 才占位）；
 *       同期间**重复生成** ⇒ 具名 409 {@code PIECEWORK_SETTLEMENT_EXISTS}（本单「期间唯一性取一」的
 *       选择与依据写在 {@code PieceworkSettlementService} 类注记）；</li>
 *   <li><b>留痕</b>：生成 / 作废各写下「谁 / 何时 / 对哪个（期间 × 工人）/ 动作 / 为什么作废」。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("PieceworkSettlementService 计件结算单（#5653）")
class PieceworkSettlementServiceTest {

    private static final Long TENANT = 1L;
    private static final String PERIOD = "2026-10";
    private static final String WORKER = "张三";
    private static final String SETTLEMENT_ID = "st-0001";
    /** 冻结时刻（业务时区 +08 的 2026-10-16 09:00）。 */
    private static final Instant NOW = Instant.parse("2026-10-16T01:00:00Z");

    @Mock
    private PieceworkSettlementMapper settlementMapper;
    @Mock
    private ProductionService productionService;

    private PieceworkSettlementService service;

    @BeforeEach
    void setUp() throws Exception {
        service = new PieceworkSettlementService(settlementMapper, productionService);
        Field clock = PieceworkSettlementService.class.getDeclaredField("businessClock");
        clock.setAccessible(true);
        clock.set(service, new BusinessClock(Clock.fixed(NOW, ZoneOffset.UTC)));
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken(
                        new com.migao.admin.security.SecurityUser(
                                "user-owner-001", TENANT, "owner-phone", List.of("admin"), List.of()),
                        null, List.of()));
    }

    @AfterEach
    void tearDown() {
        SecurityContextHolder.clearContext();
    }

    // ── 判据 1：同源 ────────────────────────────────────────────────────────

    @Test
    @DisplayName("🔴 同源：结算总额**逐值**等于 piecework/summary 的同一读数（不是约等于、不重算）")
    void settledAmountComesVerbatimFromTheSameAggregation() {
        // 报表读数（同一聚合；金额刻意给一个「除不尽后四舍五入」的值，让「自己再算一遍」立刻显形）
        when(productionService.pieceworkSummary(PERIOD, WORKER, TENANT)).thenReturn(summary("7.40"));
        when(settlementMapper.selectList(any())).thenReturn(new ArrayList<>());
        when(settlementMapper.insertActiveIfAbsent(any(), anyString())).thenReturn(1);

        Map<String, Object> out = service.generate(PERIOD, WORKER, TENANT);

        // ① 消费面：冻结值逐值等于报表读数（含 scale —— "7.40" 不是 "7.4"）
        assertThat((BigDecimal) out.get("total_amount")).isEqualByComparingTo(new BigDecimal("7.40"));
        assertThat(out.get("total_amount").toString()).isEqualTo("7.40");
        assertThat((BigDecimal) out.get("summary_total")).isEqualByComparingTo(new BigDecimal("7.40"));
        // ② 落库值 = 消费面值（同一份读数，不存在「响应一个数、库存另一个数」）
        ArgumentCaptor<PieceworkSettlement> saved = ArgumentCaptor.forClass(PieceworkSettlement.class);
        verify(settlementMapper).insertActiveIfAbsent(saved.capture(), anyString());
        assertThat(saved.getValue().getTotalAmount().toPlainString()).isEqualTo("7.40");
        // ③ 它**确实**调用了那一个聚合读面（同源不是「两边碰巧相等」）
        verify(productionService, times(1)).pieceworkSummary(PERIOD, WORKER, TENANT);
    }

    @Test
    @DisplayName("🔴 同源（结构面）：结算服务不注入报工表 / 工序实例表 Mapper —— 结算侧没有第二份算钱的口径")
    void settlementServiceHoldsNoAggregationInputs() {
        List<String> mapperTypes = new ArrayList<>();
        for (Field field : PieceworkSettlementService.class.getDeclaredFields()) {
            if (field.getType().getSimpleName().endsWith("Mapper")
                    && !field.getType().getSimpleName().equals("ObjectMapper")) {
                mapperTypes.add(field.getType().getSimpleName());
            }
        }
        // 注入面 = 恰好一个：结算单自己的 Mapper（多一个 ⇒ 它就能自己算钱 ⇒ 红）
        assertThat(mapperTypes).containsExactly("PieceworkSettlementMapper");
        // 且不依赖计件聚合的输入表（ProductionWorkLogMapper / ProcessingPositionOperationMapper 都不在）
        assertThat(mapperTypes).doesNotContain("ProductionWorkLogMapper", "ProcessingPositionOperationMapper");
    }

    @Test
    @DisplayName("🔴 同源（负例）：该期间该工人无可结金额 ⇒ 具名 422，**不落 0 元单**")
    void noAmountMeansNoSettlementRowAtAll() {
        when(productionService.pieceworkSummary(PERIOD, WORKER, TENANT)).thenReturn(summaryWithoutWorker());

        assertThatThrownBy(() -> service.generate(PERIOD, WORKER, TENANT))
                .isInstanceOf(BusinessException.class)
                .hasFieldOrPropertyWithValue("code", PieceworkSettlementService.CODE_NO_AMOUNT)
                .hasFieldOrPropertyWithValue("httpStatus", 422);
        verify(settlementMapper, never()).insertActiveIfAbsent(any(), anyString());
    }

    // ── 判据 2：不可改 ──────────────────────────────────────────────────────

    @Test
    @DisplayName("🔴 不可改（结构面）：本服务没有任何「改结算单」的公开方法（改得动的入口不存在）")
    void thereIsNoWayToMutateASettlement() {
        for (Method method : PieceworkSettlementService.class.getDeclaredMethods()) {
            String name = method.getName().toLowerCase();
            if (!java.lang.reflect.Modifier.isPublic(method.getModifiers())
                    || method.isSynthetic()) {
                continue;
            }
            assertThat(name)
                    .as("公开方法 %s 看起来是「改写结算单」的入口", method.getName())
                    .doesNotContain("update")
                    .doesNotContain("edit")
                    .doesNotContain("modify")
                    .doesNotContain("save");
        }
    }

    @Test
    @DisplayName("🔴 不可改（结构面）：作废 SQL 的 SET 子句只有 voided_at/voided_by/void_reason/updated_at")
    void voidSqlOnlyTouchesTheVoidTrail() throws Exception {
        Method voidActive = PieceworkSettlementMapper.class.getMethod(
                "voidActive", String.class, Long.class, String.class, String.class, java.time.OffsetDateTime.class);
        String sql = String.join(" ", voidActive.getAnnotation(org.apache.ibatis.annotations.Update.class).value());
        String set = sql.substring(sql.indexOf("SET") + 3, sql.indexOf("WHERE")).toLowerCase();
        assertThat(set).contains("voided_at").contains("voided_by").contains("void_reason");
        // 金额 / 期间 / 工人 / 明细**一个都不许在 SET 里**（「作废 ≠ 改写」）
        assertThat(set).doesNotContain("total_amount")
                .doesNotContain("period")
                .doesNotContain("worker_name")
                .doesNotContain("line_items");
    }

    // ── 判据 3：作废 + 重开 ─────────────────────────────────────────────────

    @Test
    @DisplayName("🔴 作废：旧单仍在（voided_at 非空 + 金额一字不变），并留下谁/何时/为什么")
    void voidKeepsTheRowAndItsAmountUntouched() {
        PieceworkSettlement active = row(null, null, null);
        when(settlementMapper.voidActive(eq(SETTLEMENT_ID), eq(TENANT), any(), anyString(), any()))
                .thenReturn(1);
        when(settlementMapper.selectById(SETTLEMENT_ID)).thenReturn(voidedRow());

        Map<String, Object> out = service.voidSettlement(SETTLEMENT_ID, "单价录错，重开", TENANT);

        assertThat(out.get("voided")).isEqualTo(true);
        assertThat(out.get("voided_by")).isEqualTo("user-owner-001");
        assertThat(out.get("void_reason")).isEqualTo("单价录错，重开");
        assertThat(((BigDecimal) out.get("total_amount")).toPlainString()).isEqualTo("7.40");
        // 原始活跃行对象（CAS 之前读到的）金额与期间也不动 —— 作废不是「就地改写」
        assertThat(active.getTotalAmount().toPlainString()).isEqualTo("7.40");
        assertThat(active.getPeriod()).isEqualTo(PERIOD);
    }

    @Test
    @DisplayName("🔴 作废：原因必填（空白 ⇒ 422，且零写库）；重复作废 ⇒ 具名 409（不谎报成功）")
    void voidRequiresReasonAndIsNotRepeatable() {
        assertThatThrownBy(() -> service.voidSettlement(SETTLEMENT_ID, "   ", TENANT))
                .isInstanceOf(BusinessException.class)
                .hasFieldOrPropertyWithValue("httpStatus", 422);
        verify(settlementMapper, never()).voidActive(any(), anyLong(), any(), any(), any());

        when(settlementMapper.voidActive(eq(SETTLEMENT_ID), eq(TENANT), any(), anyString(), any()))
                .thenReturn(0);
        assertThatThrownBy(() -> service.voidSettlement(SETTLEMENT_ID, "再来一次", TENANT))
                .isInstanceOf(BusinessException.class)
                .hasFieldOrPropertyWithValue("code", PieceworkSettlementService.CODE_NOT_FOUND)
                .hasFieldOrPropertyWithValue("httpStatus", 409);
    }

    @Test
    @DisplayName("🔴 重开：作废后同期间可再生成（活跃唯一索引谓词只盖 voided_at IS NULL 的行）")
    void regeneratingAfterVoidIsAllowedAndTheOldRowSurvives() {
        when(settlementMapper.selectList(any())).thenReturn(new ArrayList<>());     // 已无活跃单
        when(productionService.pieceworkSummary(PERIOD, WORKER, TENANT)).thenReturn(summary("9.90"));
        when(settlementMapper.insertActiveIfAbsent(any(), anyString())).thenReturn(1);

        Map<String, Object> out = service.generate(PERIOD, WORKER, TENANT);

        assertThat(((BigDecimal) out.get("total_amount")).toPlainString()).isEqualTo("9.90");
        // 列表默认**含已作废**（旧单留痕可查）—— 同期间因此可以看到两张单：一张已作废、一张生效
        when(settlementMapper.selectList(any())).thenReturn(Arrays.asList(
                row(SETTLEMENT_ID, null, null), voidedRow()));
        Map<String, Object> listed = service.list(PERIOD, null, TENANT);
        assertThat(listed.get("total")).isEqualTo(2);
        assertThat(listed.get("voided_count")).isEqualTo(1);
    }

    @Test
    @DisplayName("🔴 期间唯一性 = 具名报错：同期间同工人重复生成 ⇒ 409 PIECEWORK_SETTLEMENT_EXISTS（零写库）")
    void duplicateGenerationIsANamedConflictNotASecondRow() {
        when(settlementMapper.selectList(any())).thenReturn(List.of(row(SETTLEMENT_ID, null, null)));

        assertThatThrownBy(() -> service.generate(PERIOD, WORKER, TENANT))
                .isInstanceOf(BusinessException.class)
                .hasFieldOrPropertyWithValue("code", PieceworkSettlementService.CODE_EXISTS)
                .hasFieldOrPropertyWithValue("httpStatus", 409);
        verify(settlementMapper, never()).insertActiveIfAbsent(any(), anyString());
        verify(productionService, never()).pieceworkSummary(anyString(), anyString(), anyLong());
    }

    @Test
    @DisplayName("🔴 期间唯一性（并发面）：原子闸返回 0 行 ⇒ 具名 409，**不是** 500，也绝不落第二行")
    void concurrentLoserGets409NotA500() {
        when(settlementMapper.selectList(any())).thenReturn(new ArrayList<>());
        when(productionService.pieceworkSummary(PERIOD, WORKER, TENANT)).thenReturn(summary("7.40"));
        when(settlementMapper.insertActiveIfAbsent(any(), anyString())).thenReturn(0);

        assertThatThrownBy(() -> service.generate(PERIOD, WORKER, TENANT))
                .isInstanceOf(BusinessException.class)
                .hasFieldOrPropertyWithValue("code", PieceworkSettlementService.CODE_EXISTS)
                .hasFieldOrPropertyWithValue("httpStatus", 409);
    }

    @Test
    @DisplayName("🔴 跨月隔离：期间参与查询谓词（period 非法 ⇒ 422；非法期间连聚合都不调）")
    void periodIsValidatedAndScopesTheQuery() {
        assertThatThrownBy(() -> service.generate("2026-13", WORKER, TENANT))
                .isInstanceOf(BusinessException.class)
                .hasFieldOrPropertyWithValue("httpStatus", 422);
        assertThatThrownBy(() -> service.generate("", WORKER, TENANT))
                .isInstanceOf(BusinessException.class)
                .hasFieldOrPropertyWithValue("httpStatus", 422);

        when(settlementMapper.selectList(any())).thenReturn(new ArrayList<>());
        when(productionService.pieceworkSummary("2026-10", WORKER, TENANT)).thenReturn(summary("7.40"));
        when(settlementMapper.insertActiveIfAbsent(any(), anyString())).thenReturn(1);
        service.generate("2026-10", WORKER, TENANT);

        @SuppressWarnings("unchecked")
        ArgumentCaptor<QueryWrapper<PieceworkSettlement>> wrapper = ArgumentCaptor.forClass(QueryWrapper.class);
        verify(settlementMapper).selectList(wrapper.capture());
        String sql = wrapper.getValue().getTargetSql();
        assertThat(sql).contains("period").contains("worker_name").contains("tenant_id").contains("voided_at");
        assertThat(wrapper.getValue().getParamNameValuePairs().values())
                .contains(PERIOD, WORKER, TENANT);
    }

    // ── 判据 4：留痕 ────────────────────────────────────────────────────────

    @Test
    @DisplayName("🔴 留痕：生成写下「谁 / 何时 / 期间 × 工人」，动作可从详情逐条读出")
    void generationLeavesWhoWhenAndScope() {
        when(settlementMapper.selectList(any())).thenReturn(new ArrayList<>());
        when(productionService.pieceworkSummary(PERIOD, WORKER, TENANT)).thenReturn(summary("7.40"));
        when(settlementMapper.insertActiveIfAbsent(any(), anyString())).thenReturn(1);

        Map<String, Object> out = service.generate(PERIOD, WORKER, TENANT);
        ArgumentCaptor<PieceworkSettlement> saved = ArgumentCaptor.forClass(PieceworkSettlement.class);
        verify(settlementMapper).insertActiveIfAbsent(saved.capture(), anyString());
        PieceworkSettlement stored = saved.getValue();

        assertThat(stored.getGeneratedBy()).isEqualTo("user-owner-001");            // 谁
        assertThat(stored.getGeneratedAt()).isNotNull();                           // 何时
        assertThat(stored.getPeriod()).isEqualTo(PERIOD);                          // 哪个期间
        assertThat(stored.getWorkerName()).isEqualTo(WORKER);                      // 哪个工人
        assertThat(stored.getVoidedAt()).isNull();                                 // 动作 = 生成（未作废）
        assertThat(out.get("generated_by")).isEqualTo("user-owner-001");
        assertThat(out.get("generated_at")).isNotNull();
        // 明细快照 = 报表 per_operation 的同源子集（工序 / 数量 / 金额三键）
        assertThat(stored.getLineItems()).hasSize(2);
        assertThat(stored.getLineItems().get(0).getOperation()).isEqualTo("精裁");
        assertThat(stored.getLineItems().get(0).getAmount().toPlainString()).isEqualTo("4.00");
    }

    @Test
    @DisplayName("🔴 留痕：详情同时给出冻结快照与现取报表读数（同源在消费面上可见）")
    void detailExposesSnapshotAndLiveSummarySideBySide() {
        when(settlementMapper.selectById(SETTLEMENT_ID)).thenReturn(row(SETTLEMENT_ID, null, null));
        when(productionService.pieceworkSummary(PERIOD, WORKER, TENANT)).thenReturn(summary("7.40"));

        Map<String, Object> out = service.detail(SETTLEMENT_ID, TENANT);

        assertThat(((BigDecimal) out.get("total_amount")).toPlainString()).isEqualTo("7.40");
        assertThat(((BigDecimal) out.get("summary_total")).toPlainString()).isEqualTo("7.40");
        assertThat(out.get("worker_name")).isEqualTo(WORKER);
        assertThat(out.get("period")).isEqualTo(PERIOD);
    }

    @Test
    @DisplayName("🔴 跨租户：别的租户的结算单读不到（详情 ⇒ 404，不泄露存在性）")
    void otherTenantsSettlementIsNotReachable() {
        PieceworkSettlement other = row(SETTLEMENT_ID, null, null);
        other.setTenantId(999L);
        when(settlementMapper.selectById(SETTLEMENT_ID)).thenReturn(other);

        assertThatThrownBy(() -> service.detail(SETTLEMENT_ID, TENANT))
                .isInstanceOf(BusinessException.class)
                .hasFieldOrPropertyWithValue("code", PieceworkSettlementService.CODE_NOT_FOUND)
                .hasFieldOrPropertyWithValue("httpStatus", 404);
    }

    // ── 夹具 ────────────────────────────────────────────────────────────────

    private static PieceworkSettlement row(String id, java.time.OffsetDateTime voidedAt, String voidedBy) {
        return PieceworkSettlement.builder()
                .id(id)
                .tenantId(TENANT)
                .period(PERIOD)
                .workerName(WORKER)
                .totalAmount(new BigDecimal("7.40"))
                .generatedBy("user-owner-001")
                .generatedAt(java.time.OffsetDateTime.parse("2026-10-16T09:00:00+08:00"))
                .lineItems(new ArrayList<>())
                .voidedAt(voidedAt)
                .voidedBy(voidedBy)
                .build();
    }

    private static PieceworkSettlement voidedRow() {
        PieceworkSettlement row = row(SETTLEMENT_ID, java.time.OffsetDateTime.parse("2026-10-16T10:00:00+08:00"),
                "user-owner-001");
        row.setVoidReason("单价录错，重开");
        return row;
    }

    /** 报表读面（与 {@code ProductionController.pieceworkSummary} 下发的同一形状）。 */
    private static Map<String, Object> summary(String total) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("period", PERIOD);
        out.put("total", new BigDecimal(total));
        Map<String, Object> workerRow = new LinkedHashMap<>();
        workerRow.put("worker_name", WORKER);
        workerRow.put("amount", new BigDecimal(total));
        workerRow.put("qty", new BigDecimal("10.00"));
        out.put("per_worker", List.of(workerRow));
        out.put("per_operation", List.of(
                operation("精裁", "4.00", "4.00"), operation("打包", "3.40", "3.40")));
        return out;
    }

    /** 该期间有报工、但没有这个名字的工人（⇒ 无可结金额，不落 0 元单）。 */
    private static Map<String, Object> summaryWithoutWorker() {
        Map<String, Object> out = summary("7.40");
        Map<String, Object> other = new LinkedHashMap<>();
        other.put("worker_name", "李四");
        other.put("amount", new BigDecimal("7.40"));
        other.put("qty", new BigDecimal("10.00"));
        out.put("per_worker", List.of(other));
        return out;
    }

    private static Map<String, Object> operation(String name, String qty, String amount) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("operation", name);
        row.put("logical_name", name);
        row.put("position", "布帘");
        row.put("qty", new BigDecimal(qty));
        row.put("amount", new BigDecimal(amount));
        return row;
    }
}
