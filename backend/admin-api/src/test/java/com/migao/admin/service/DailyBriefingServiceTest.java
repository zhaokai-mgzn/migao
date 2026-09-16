// case_ids: DA-001, DA-002, ST-001

package com.migao.admin.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.DailyBriefing;
import com.migao.admin.entity.Tenant;
import com.migao.admin.mapper.*;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.Spy;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * DailyBriefingService 单元测试（智能每日经营简报，issue #3468）
 *
 * 重点覆盖数据安全四红线：
 * 1. 数字回填校验（红线 4）：LLM 编造 key/value → 条目被丢弃；
 * 2. 开关即熔断（红线 3）：关闭租户生成直接返回 null；
 * 3. 幂等：当日已生成不重复调用 LLM；
 * 4. PII 不进 prompt：快照只含聚合数字与脱敏事实（facts 无客户信息）。
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("DailyBriefingService 智能每日简报服务测试")
class DailyBriefingServiceTest {

    @Mock
    private DailyBriefingMapper dailyBriefingMapper;
    @Mock
    private TenantMapper tenantMapper;
    @Mock
    private OrderMapper orderMapper;
    @Mock
    private UserMapper userMapper;
    @Mock
    private SessionMapper sessionMapper;
    @Mock
    private AfterSalesTicketMapper afterSalesTicketMapper;
    @Mock
    private OrderItemMapper orderItemMapper;
    @Mock
    private ProductService productService;
    @Mock
    private BriefingGenerateClient briefingGenerateClient;
    @Mock
    private StringRedisTemplate redisTemplate;
    @Mock
    private ValueOperations<String, String> valueOperations;
    @Spy
    private ObjectMapper objectMapper = new ObjectMapper();

    @InjectMocks
    private DailyBriefingService service;

    private Tenant enabledTenant() {
        return Tenant.builder().id(1L).briefingEnabled(true).briefingGenerateTime("06:00").build();
    }

    private Tenant disabledTenant() {
        return Tenant.builder().id(1L).briefingEnabled(false).briefingGenerateTime("06:00").build();
    }

    /** 标准聚合快照 mock（与 Dashboard 同口径） */
    private void stubAggregations() {
        when(orderMapper.selectDashboardOrderStats(any(), any(), any(), any(), any())).thenReturn(Map.of(
                "total_orders", 50L,
                "today_orders", 5L,
                "yesterday_orders", 3L,
                "today_sales", new BigDecimal("1000"),
                "yesterday_sales", new BigDecimal("800"),
                "month_revenue", new BigDecimal("10000"),
                "last_month_revenue", new BigDecimal("9000"),
                "pending_ship", 10L));
        when(userMapper.selectDashboardUserStats(any())).thenReturn(Map.of(
                "total_customers", 200L,
                "new_customers_today", 10L));
        when(sessionMapper.selectDashboardSessionStats(any())).thenReturn(Map.of(
                "active_sessions", 3L,
                "ai_sessions", 2L));
        when(orderItemMapper.selectProcessingPendingOrdersCount()).thenReturn(5L);
        when(afterSalesTicketMapper.selectCount(any())).thenReturn(2L);
        when(productService.getLowStockSkuCount(eq(1L), eq(100))).thenReturn(8L);
    }

    @BeforeEach
    void setUp() {
        // 聚合快照默认 stub
        stubAggregations();
        // 分布式生成锁（issue #3957）：默认视为获取成功，既有生成用例语义不变；
        // 锁被占用 / Redis 异常场景在 GenerateFlow 内单独覆写。
        when(redisTemplate.opsForValue()).thenReturn(valueOperations);
        when(valueOperations.setIfAbsent(anyString(), anyString(), anyLong(), any())).thenReturn(true);
    }

    @Nested
    @DisplayName("开关熔断（红线 3）")
    class SwitchBreaker {

        @Test
        @DisplayName("开关关闭 → 生成返回 null，且不调用 LLM")
        void disabledTenantSkipsGeneration() {
            when(tenantMapper.selectById(1L)).thenReturn(disabledTenant());

            DailyBriefing result = service.generateForTenant(1L);

            assertThat(result).isNull();
            verify(briefingGenerateClient, never()).generate(anyLong(), anyMap());
        }

        @Test
        @DisplayName("租户不存在 → 返回 null")
        void missingTenantSkipsGeneration() {
            when(tenantMapper.selectById(1L)).thenReturn(null);

            assertThat(service.generateForTenant(1L)).isNull();
        }
    }

    @Nested
    @DisplayName("数字回填校验（红线 4）")
    class VerifyAndFilter {

        private Map<String, Number> metrics() {
            Map<String, Number> m = new HashMap<>();
            m.put("today_orders", 5L);
            m.put("pending_ship_orders", 10L);
            m.put("overdue_tickets", 2L);
            return m;
        }

        @Test
        @DisplayName("metrics 引用与快照一致 → 条目保留")
        void keepsMatchingItems() throws Exception {
            String llmOutput = """
                    {
                      "summary": "昨日订单 5 单",
                      "todo": [
                        {"priority": "high", "title": "10 个订单待发货", "metrics": [{"key": "pending_ship_orders", "value": 10}]}
                      ],
                      "risks": [],
                      "suggestions": []
                    }
                    """;
            JsonNode briefing = objectMapper.readTree(llmOutput);

            var vr = service.verifyAndFilter(briefing, metrics());

            assertThat(vr.status()).isEqualTo("verified");
            assertThat(vr.todoKept()).isEqualTo(1);
            assertThat(vr.content().toString()).contains("10 个订单待发货");
        }

        @Test
        @DisplayName("key 不在快照（LLM 编造）→ 条目丢弃")
        void dropsUnknownKey() throws Exception {
            String llmOutput = """
                    {
                      "summary": "x",
                      "todo": [
                        {"priority": "high", "title": "编造的指标", "metrics": [{"key": "fake_metric", "value": 99}]}
                      ],
                      "risks": [],
                      "suggestions": []
                    }
                    """;
            JsonNode briefing = objectMapper.readTree(llmOutput);

            var vr = service.verifyAndFilter(briefing, metrics());

            assertThat(vr.status()).isEqualTo("failed");
            assertThat(vr.todoKept()).isZero();
        }

        @Test
        @DisplayName("value 与快照不一致（LLM 篡改数字）→ 条目丢弃")
        void dropsMismatchedValue() throws Exception {
            String llmOutput = """
                    {
                      "summary": "x",
                      "todo": [
                        {"priority": "high", "title": "篡改的数字", "metrics": [{"key": "pending_ship_orders", "value": 999}]}
                      ],
                      "risks": [],
                      "suggestions": []
                    }
                    """;
            JsonNode briefing = objectMapper.readTree(llmOutput);

            var vr = service.verifyAndFilter(briefing, metrics());

            assertThat(vr.status()).isEqualTo("failed");
            assertThat(vr.todoKept()).isZero();
        }

        @Test
        @DisplayName("无 metrics 引用 → 条目丢弃（无法对账）")
        void dropsItemsWithoutMetrics() throws Exception {
            String llmOutput = """
                    {
                      "summary": "x",
                      "todo": [
                        {"priority": "high", "title": "无引用的条目"}
                      ],
                      "risks": [],
                      "suggestions": []
                    }
                    """;
            JsonNode briefing = objectMapper.readTree(llmOutput);

            var vr = service.verifyAndFilter(briefing, metrics());

            assertThat(vr.status()).isEqualTo("failed");
            assertThat(vr.todoKept()).isZero();
        }

        @Test
        @DisplayName("部分条目被丢弃 → status=partial")
        void partialDrop() throws Exception {
            String llmOutput = """
                    {
                      "summary": "x",
                      "todo": [
                        {"priority": "high", "title": "合法的条目", "metrics": [{"key": "today_orders", "value": 5}]},
                        {"priority": "high", "title": "编造的条目", "metrics": [{"key": "fake", "value": 1}]}
                      ],
                      "risks": [],
                      "suggestions": []
                    }
                    """;
            JsonNode briefing = objectMapper.readTree(llmOutput);

            var vr = service.verifyAndFilter(briefing, metrics());

            assertThat(vr.status()).isEqualTo("partial");
            assertThat(vr.todoKept()).isEqualTo(1);
        }

        @Test
        @DisplayName("summary 自由文本含快照外数字 → summary 降级为空（P2-2 防自由文本编造）")
        void summaryWithForeignNumberDegrades() throws Exception {
            // summary 里写 9999（快照无此数）→ summary 应被清空，条目仍保留
            String llmOutput = """
                    {
                      "summary": "昨日订单 9999 单，经营平稳",
                      "todo": [{"priority": "high", "title": "10 个订单待发货", "metrics": [{"key": "pending_ship_orders", "value": 10}]}],
                      "risks": [],
                      "suggestions": []
                    }
                    """;
            JsonNode briefing = objectMapper.readTree(llmOutput);

            var vr = service.verifyAndFilter(briefing, metrics());
            JsonNode content = objectMapper.valueToTree(vr.content());

            assertThat(vr.status()).isEqualTo("verified");
            assertThat(content.path("summary").asText()).isEmpty();
            assertThat(vr.todoKept()).isEqualTo(1);
        }

        @Test
        @DisplayName("summary 数字均来自快照 → summary 保留")
        void summaryWithSnapshotNumbersKept() throws Exception {
            String llmOutput = """
                    {
                      "summary": "昨日订单 5 单，10 个订单待发货",
                      "todo": [{"priority": "high", "title": "10 个订单待发货", "metrics": [{"key": "pending_ship_orders", "value": 10}]}],
                      "risks": [],
                      "suggestions": []
                    }
                    """;
            JsonNode briefing = objectMapper.readTree(llmOutput);

            var vr = service.verifyAndFilter(briefing, metrics());
            JsonNode content = objectMapper.valueToTree(vr.content());

            assertThat(content.path("summary").asText()).isEqualTo("昨日订单 5 单，10 个订单待发货");
        }
    }

    @Nested
    @DisplayName("生成流程")
    class GenerateFlow {

        @Test
        @DisplayName("开关开启 + LLM 成功 → 落库 verified 记录")
        void generateSuccessPersists() throws Exception {
            when(tenantMapper.selectById(1L)).thenReturn(enabledTenant());
            when(dailyBriefingMapper.selectOne(any())).thenReturn(null);
            String llmOutput = """
                    {
                      "summary": "昨日订单 5 单，经营平稳",
                      "review": [{"label": "今日订单", "value": 5, "unit": "单"}],
                      "todo": [{"priority": "high", "title": "10 个订单待发货", "metrics": [{"key": "pending_ship_orders", "value": 10}]}],
                      "risks": [],
                      "suggestions": []
                    }
                    """;
            JsonNode parsed = objectMapper.readTree(llmOutput);
            when(briefingGenerateClient.generate(eq(1L), anyMap())).thenReturn(parsed);

            DailyBriefing result = service.generateForTenant(1L);

            assertThat(result).isNotNull();
            assertThat(result.getVerifyStatus()).isEqualTo("verified");
            // 业务"今日"口径 = 服务常量（Asia/Shanghai），断言必须与该常量同源：
            // 用 JVM 默认时区（CI = UTC）时，UTC 16:00–24:00（北京次日 00:00–08:00）两侧"今天"差一天
            // ⇒ 每天 8 小时必然假红、阻断所有 PR（issue #3796）。
            // 另独立钉死该常量值本身，避免"服务改时区、断言跟着漂移"式的空断言。
            assertThat(DailyBriefingService.CST).isEqualTo(java.time.ZoneId.of("Asia/Shanghai"));
            assertThat(result.getBizDate()).isEqualTo(java.time.LocalDate.now(DailyBriefingService.CST));
            assertThat(result.getSourceSnapshot()).isNotNull();
            verify(dailyBriefingMapper).insert(any(DailyBriefing.class));
        }

        @Test
        @DisplayName("LLM 失败 → 落 failed 记录，不展示假数据")
        void generateFailurePersistsFailed() {
            when(tenantMapper.selectById(1L)).thenReturn(enabledTenant());
            when(dailyBriefingMapper.selectOne(any())).thenReturn(null);
            when(briefingGenerateClient.generate(eq(1L), anyMap())).thenReturn(null);

            DailyBriefing result = service.generateForTenant(1L);

            assertThat(result).isNotNull();
            assertThat(result.getVerifyStatus()).isEqualTo("failed");
            verify(dailyBriefingMapper).insert(any(DailyBriefing.class));
        }

        @Test
        @DisplayName("当日已生成 → 幂等跳过，不重复调 LLM")
        void idempotentSkip() {
            when(tenantMapper.selectById(1L)).thenReturn(enabledTenant());
            when(dailyBriefingMapper.selectOne(any())).thenReturn(
                    DailyBriefing.builder().tenantId(1L).verifyStatus("verified").build());

            DailyBriefing result = service.generateForTenant(1L);

            assertThat(result).isNotNull();
            verify(briefingGenerateClient, never()).generate(anyLong(), anyMap());
        }

        @Test
        @DisplayName("LLM 全部条目被校验丢弃 → 落 failed 记录（校验兜底）")
        void allItemsDroppedPersistsFailed() throws Exception {
            when(tenantMapper.selectById(1L)).thenReturn(enabledTenant());
            when(dailyBriefingMapper.selectOne(any())).thenReturn(null);
            String llmOutput = """
                    {
                      "summary": "x",
                      "todo": [{"priority": "high", "title": "编造指标", "metrics": [{"key": "fake", "value": 1}]}],
                      "risks": [],
                      "suggestions": []
                    }
                    """;
            JsonNode parsed = objectMapper.readTree(llmOutput);
            when(briefingGenerateClient.generate(eq(1L), anyMap())).thenReturn(parsed);

            DailyBriefing result = service.generateForTenant(1L);

            assertThat(result.getVerifyStatus()).isEqualTo("failed");
        }

        @Test
        @DisplayName("集群并发：锁被另一实例持有 → 跳过生成且不调 LLM（issue #3957）")
        void clusterLockHeldSkipsGeneration() {
            when(tenantMapper.selectById(1L)).thenReturn(enabledTenant());
            when(valueOperations.setIfAbsent(anyString(), anyString(), anyLong(), any())).thenReturn(false);

            DailyBriefing result = service.generateForTenant(1L);

            assertThat(result).isNull();
            verify(briefingGenerateClient, never()).generate(anyLong(), anyMap());
            verify(dailyBriefingMapper, never()).insert(any(DailyBriefing.class));
        }

        @Test
        @DisplayName("集群并发：锁 key 含租户+业务日期；获取成功则生成并释放锁（issue #3957）")
        void clusterLockAcquiredGeneratesAndReleases() throws Exception {
            when(tenantMapper.selectById(1L)).thenReturn(enabledTenant());
            when(valueOperations.setIfAbsent(anyString(), anyString(), anyLong(), any())).thenReturn(true);
            when(dailyBriefingMapper.selectOne(any())).thenReturn(null);
            String llmOutput = """
                    {
                      "summary": "昨日订单 5 单，经营平稳",
                      "todo": [{"priority": "high", "title": "10 个订单待发货", "metrics": [{"key": "pending_ship_orders", "value": 10}]}],
                      "risks": [],
                      "suggestions": []
                    }
                    """;
            JsonNode parsed = objectMapper.readTree(llmOutput);
            when(briefingGenerateClient.generate(eq(1L), anyMap())).thenReturn(parsed);

            DailyBriefing result = service.generateForTenant(1L);

            assertThat(result).isNotNull();
            assertThat(result.getVerifyStatus()).isEqualTo("verified");
            // 锁 key = 租户 + 业务日期（Asia/Shanghai），跨实例互斥粒度 = 租户×天
            ArgumentCaptor<String> keyCaptor = ArgumentCaptor.forClass(String.class);
            verify(valueOperations).setIfAbsent(keyCaptor.capture(), eq("1"),
                    eq(DailyBriefingService.BRIEFING_LOCK_TTL_SECONDS), eq(TimeUnit.SECONDS));
            assertThat(keyCaptor.getValue())
                    .isEqualTo("briefing:gen:1:" + LocalDate.now(DailyBriefingService.CST));
            verify(redisTemplate).delete(anyString());
            verify(dailyBriefingMapper).insert(any(DailyBriefing.class));
        }

        @Test
        @DisplayName("Redis 不可用 → fail-open 仍生成，不阻断简报（DB 唯一键兜底，issue #3957）")
        void clusterLockRedisDownFailsOpen() throws Exception {
            when(tenantMapper.selectById(1L)).thenReturn(enabledTenant());
            when(valueOperations.setIfAbsent(anyString(), anyString(), anyLong(), any()))
                    .thenThrow(new RuntimeException("redis down"));
            when(dailyBriefingMapper.selectOne(any())).thenReturn(null);
            String llmOutput = """
                    {
                      "summary": "昨日订单 5 单，经营平稳",
                      "todo": [{"priority": "high", "title": "10 个订单待发货", "metrics": [{"key": "pending_ship_orders", "value": 10}]}],
                      "risks": [],
                      "suggestions": []
                    }
                    """;
            JsonNode parsed = objectMapper.readTree(llmOutput);
            when(briefingGenerateClient.generate(eq(1L), anyMap())).thenReturn(parsed);

            DailyBriefing result = service.generateForTenant(1L);

            assertThat(result).isNotNull();
            assertThat(result.getVerifyStatus()).isEqualTo("verified");
            verify(dailyBriefingMapper).insert(any(DailyBriefing.class));
        }

        @Test
        @DisplayName("有事务上下文时：锁延迟到事务提交后释放（防先放锁后提交窗口，issue #3957）")
        void clusterLockReleasedAfterTransactionCommit() throws Exception {
            when(tenantMapper.selectById(1L)).thenReturn(enabledTenant());
            when(valueOperations.setIfAbsent(anyString(), anyString(), anyLong(), any())).thenReturn(true);
            when(dailyBriefingMapper.selectOne(any())).thenReturn(null);
            String llmOutput = """
                    {
                      "summary": "昨日订单 5 单，经营平稳",
                      "todo": [{"priority": "high", "title": "10 个订单待发货", "metrics": [{"key": "pending_ship_orders", "value": 10}]}],
                      "risks": [],
                      "suggestions": []
                    }
                    """;
            JsonNode parsed = objectMapper.readTree(llmOutput);
            when(briefingGenerateClient.generate(eq(1L), anyMap())).thenReturn(parsed);

            TransactionSynchronizationManager.initSynchronization();
            try {
                DailyBriefing result = service.generateForTenant(1L);

                assertThat(result).isNotNull();
                assertThat(result.getVerifyStatus()).isEqualTo("verified");
                // 事务未提交 → 锁必须仍持有（否则另一实例会读不到记录而重复生成）
                verify(redisTemplate, never()).delete(anyString());
                // 模拟事务提交完成 → 注册的回调释放锁
                TransactionSynchronizationManager.getSynchronizations()
                        .forEach(s -> s.afterCompletion(TransactionSynchronization.STATUS_COMMITTED));
                verify(redisTemplate).delete(anyString());
            } finally {
                TransactionSynchronizationManager.clear();
            }
        }
    }

    @Nested
    @DisplayName("定时调度（generateDueTenants，issue #3957）")
    class SchedulerFlow {

        @Test
        @DisplayName("调度线程无 JWT：daily_briefings 查询必须发生在 TenantContext 设置之后")
        void schedulerSetsTenantContextBeforeBriefingQuery() throws Exception {
            // 生产实证：scheduling-1 线程对 daily_briefings 的幂等预检在无 TenantContext 时
            // 被 TenantLineInnerInterceptor 拒绝（MybatisPlusConfig:84 抛
            // "Tenant context not initialized"）→ 每轮调度整体夭折、简报永不生成。
            // 用同一契约模拟拦截器：任何 daily_briefings 查询发生时 TenantContext 必须已注入租户。
            // 生成时刻用 00:00 保证「已到时刻」，测试不依赖墙钟（防每天 00:00–06:00 假红）。
            TenantContext.clear();
            Tenant dueTenant = Tenant.builder().id(1L).briefingEnabled(true).briefingGenerateTime("00:00").build();
            when(tenantMapper.selectList(any())).thenReturn(List.of(dueTenant));
            when(tenantMapper.selectById(1L)).thenReturn(dueTenant);
            when(dailyBriefingMapper.selectOne(any())).thenAnswer(inv -> {
                assertThat(TenantContext.getTenantId())
                        .as("调度路径查询 daily_briefings 前必须已设置 TenantContext")
                        .isEqualTo(1L);
                return null;
            });
            String llmOutput = """
                    {
                      "summary": "昨日订单 5 单，经营平稳",
                      "todo": [{"priority": "high", "title": "10 个订单待发货", "metrics": [{"key": "pending_ship_orders", "value": 10}]}],
                      "risks": [],
                      "suggestions": []
                    }
                    """;
            JsonNode parsed = objectMapper.readTree(llmOutput);
            when(briefingGenerateClient.generate(eq(1L), anyMap())).thenReturn(parsed);

            int generated = service.generateDueTenants();

            assertThat(generated).isEqualTo(1);
            verify(dailyBriefingMapper).insert(any(DailyBriefing.class));
        }

        @Test
        @DisplayName("当日已生成 → 调度跳过，不重复调 LLM")
        void schedulerSkipsWhenAlreadyGenerated() {
            TenantContext.clear();
            Tenant dueTenant = Tenant.builder().id(1L).briefingEnabled(true).briefingGenerateTime("00:00").build();
            when(tenantMapper.selectList(any())).thenReturn(List.of(dueTenant));
            when(dailyBriefingMapper.selectOne(any())).thenAnswer(inv -> {
                assertThat(TenantContext.getTenantId())
                        .as("调度路径幂等预检也必须带 TenantContext")
                        .isEqualTo(1L);
                return DailyBriefing.builder().tenantId(1L).verifyStatus("verified").build();
            });

            int generated = service.generateDueTenants();

            assertThat(generated).isZero();
            verify(briefingGenerateClient, never()).generate(anyLong(), anyMap());
        }
    }

    @Nested
    @DisplayName("聚合快照（PII 不进 prompt）")
    class Aggregation {

        @Test
        @DisplayName("快照只含聚合数字 + 脱敏事实，无客户 PII 字段")
        void snapshotHasNoPii() {
            Map<String, Object> snapshot = service.aggregateSnapshot(1L);

            // metrics 全是数字
            @SuppressWarnings("unchecked")
            Map<String, Object> metrics = (Map<String, Object>) snapshot.get("metrics");
            assertThat(metrics).isNotEmpty();
            for (Object v : metrics.values()) {
                assertThat(v).isInstanceOf(Number.class);
            }
            // facts 是脱敏事实（标题含数量，无手机号/姓名/地址）
            @SuppressWarnings("unchecked")
            List<Map<String, Object>> facts = (List<Map<String, Object>>) snapshot.get("facts");
            assertThat(facts).isNotNull();
            String json = snapshot.toString();
            assertThat(json).doesNotContain("phone", "手机号", "nickname", "customerName", "地址");
        }
    }
}
