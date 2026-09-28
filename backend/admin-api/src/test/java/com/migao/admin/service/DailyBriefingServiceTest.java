// case_ids: DA-001, DA-002, ST-001, DA-016, DA-017

package com.migao.admin.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.AbstractWrapper;
import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.migao.admin.config.MybatisPlusConfig;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.AfterSalesTicket;
import com.migao.admin.entity.AgentBatch;
import com.migao.admin.entity.AgentBatchItem;
import com.migao.admin.entity.AuditLog;
import com.migao.admin.entity.DailyBriefing;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.OrderLogistics;
import com.migao.admin.entity.Product;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.entity.Tenant;
import com.migao.admin.mapper.*;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.apache.ibatis.builder.MapperBuilderAssistant;
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

import java.lang.reflect.Field;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import com.migao.admin.time.BusinessClock;

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
    private OrderLogisticsMapper orderLogisticsMapper;
    @Mock
    private ProductSkuMapper productSkuMapper;
    @Mock
    private ProductMapper productMapper;
    @Mock
    private AuditLogMapper auditLogMapper;
    @Mock
    private AgentBatchMapper agentBatchMapper;
    @Mock
    private AgentBatchItemMapper agentBatchItemMapper;
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
        // MyBatis-Plus 实体 lambda 缓存：行数组装配（issue #5358）用 LambdaQueryWrapper，
        // 判据要读 wrapper 的 SQL 段与参数对 ⇒ 需先注册 TableInfo（同 OrderServiceTest 的做法）。
        MybatisConfiguration conf = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(conf, "");
        for (Class<?> entity : List.of(Order.class, OrderItem.class, OrderLogistics.class,
                ProductSku.class, Product.class, AfterSalesTicket.class, AuditLog.class,
                AgentBatch.class, AgentBatchItem.class)) {
            TableInfoHelper.initTableInfo(assistant, entity);
        }
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
            // 业务"今日"口径 = 单点 BusinessClock（Asia/Shanghai，issue #3802），断言必须与该单点同源：
            // 用 JVM 默认时区（CI = UTC）时，UTC 16:00–24:00（北京次日 00:00–08:00）两侧"今天"差一天
            // ⇒ 每天 8 小时必然假红、阻断所有 PR（issue #3796）。
            // 另独立钉死该时区值本身，避免"服务改时区、断言跟着漂移"式的空断言。
            assertThat(BusinessClock.BUSINESS_ZONE).isEqualTo(java.time.ZoneId.of("Asia/Shanghai"));
            assertThat(result.getBizDate()).isEqualTo(java.time.LocalDate.now(BusinessClock.BUSINESS_ZONE));
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
                    .isEqualTo("briefing:gen:1:" + LocalDate.now(BusinessClock.BUSINESS_ZONE));
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

    @Nested
    @DisplayName("行级快照装配（族 3 跨域视图内核，issue #5358）")
    class SnapshotRows {

        private Map<String, Object> orderRow() {
            Map<String, Object> row = new java.util.LinkedHashMap<>();
            row.put("order_no", "SO-1");
            row.put("status", "confirmed");
            row.put("customer_id", "C-1");
            row.put("created_at", OffsetDateTime.parse("2026-09-12T10:00:00+08:00"));
            row.put("shipped_at", null);          // 真实 MyBatis Map 结果里 NULL 列可能整键缺席
            row.put("sale_amount", new BigDecimal("1200.00"));
            return row;
        }

        private Map<String, Object> skuRow() {
            Map<String, Object> row = new java.util.LinkedHashMap<>();
            row.put("sku_id", 1L);
            row.put("product_id", "P-1");
            row.put("product_name", "雪尼尔-米白");
            row.put("stock", new BigDecimal("20.0"));
            return row;
        }

        private AfterSalesTicket returnTicket(String ticketNo, String orderId) {
            return AfterSalesTicket.builder()
                    .tenantId(1L).ticketNo(ticketNo).ticketType("return").orderId(orderId)
                    .customerId("C-1").refundAmount(new BigDecimal("100.00"))
                    .createdAt(OffsetDateTime.parse("2026-09-22T10:00:00+08:00"))
                    .build();
        }

        private OrderItem orderItem(String orderId, String productId) {
            return OrderItem.builder().tenantId(1L).orderId(orderId).productId(productId)
                    .quantity(new BigDecimal("2")).build();
        }

        private Order order(String orderNo) {
            return Order.builder().id("O-1").tenantId(1L).orderNo(orderNo).status("confirmed")
                    .userId("C-1").createdAt(OffsetDateTime.parse("2026-09-12T10:00:00+08:00"))
                    .actualAmount(new BigDecimal("1200.00")).totalAmount(new BigDecimal("1500.00"))
                    // 让利（issue #5388）：1500 应收 − 1200 实收 = 400 让利（26.7% < 30% ⇒ 不命中）
                    .discountAmount(new BigDecimal("400.00"))
                    .build();
        }

        /** 一条**改价**审计行（issue #5388）：`action_details.priceChange` 带改价真值 */
        private AuditLog priceAuditRow(String toolName, Double before, Double price) {
            Map<String, Object> priceChange = new java.util.LinkedHashMap<>();
            priceChange.put("product_id", "P-1");
            if (before != null) {
                priceChange.put("before_price", before);
            }
            if (price != null) {
                priceChange.put("price", price);
            }
            Map<String, Object> details = new java.util.LinkedHashMap<>();
            details.put("action", "update");
            details.put("params", Map.of("product_id", "<str>", "price", "<float>"));
            details.put("priceChange", priceChange);
            return AuditLog.builder().id("A-" + toolName).tenantId(1L)
                    .resourceType("agent_tool").toolName(toolName)
                    .createdAt(OffsetDateTime.parse("2026-09-22T09:30:00+08:00"))
                    .actionDetails(details)
                    .build();
        }

        /**
         * 一个**已执行**的批次（issue #5411）：`executed_at` 就是改价时刻。
         *
         * <p>`executedAt = null`（= `preview` 批次）在库里不可能有改价时刻 —— 装配层的
         * `executed_at >= 窗口起点` 一并对它做排除（未执行 ⇒ 价根本没动）。</p>
         */
        private AgentBatch batch(String id, String batchType, String executedAt) {
            return AgentBatch.builder().id(id).tenantId(1L).batchType(batchType)
                    .status("done").itemCount(1).successCount(1).failCount(0)
                    .executedAt(executedAt == null ? null : OffsetDateTime.parse(executedAt))
                    .build();
        }

        /** 一条批次明细（`agent_batch_items`）：`oldValue` / `newValue` 在库里是**字符串**（TEXT）。 */
        private AgentBatchItem batchItem(Long id, String batchId, String resourceId, String status,
                                        String oldValue, String newValue) {
            return AgentBatchItem.builder().id(id).batchId(batchId).tenantId(1L)
                    .resourceId(resourceId).field("basePrice")
                    .oldValue(oldValue).newValue(newValue).status(status).build();
        }

        private ProductSku sku() {
            return ProductSku.builder().id(7L).tenantId(1L).productId("P-1")
                    .stock(new BigDecimal("20.0")).salesCount(new BigDecimal("120.0"))
                    .price(new BigDecimal("168.00")).avgCost(new BigDecimal("10.0000")).build();
        }

        private Product product() {
            return Product.builder().id("P-1").tenantId(1L).name("雪尼尔-米白").status("on_sale").build();
        }

        private List<Order> orders(int n) {
            return java.util.stream.IntStream.rangeClosed(1, n)
                    .mapToObj(i -> order("SO-" + i)).toList();
        }

        private List<ProductSku> skus(int n) {
            return java.util.stream.IntStream.rangeClosed(1, n)
                    .mapToObj(i -> ProductSku.builder().id((long) i).tenantId(1L).productId("P-1")
                            .stock(new BigDecimal(i)).build())
                    .toList();
        }

        @SuppressWarnings("unchecked")
        private Map<String, Object> metaOf(Map<String, Object> snapshot, String array) {
            return (Map<String, Object>) ((Map<String, Object>) snapshot.get("row_meta")).get(array);
        }

        /** 标准行级 stub：一张单商品订单的退货 + 一张多商品订单的退货；SKU 库存 20（在售商品下）、均价 10 */
        private Map<String, Object> countRow(String productId, long orderLines) {
            Map<String, Object> row = new java.util.LinkedHashMap<>();
            row.put("product_id", productId);
            row.put("order_lines", orderLines);
            return row;
        }

        private List<Map<String, Object>> countRows(int n) {
            return java.util.stream.IntStream.rangeClosed(1, n)
                    .mapToObj(i -> countRow("P-" + i, i)).toList();
        }
        private void stubRows() {
            when(orderMapper.selectList(any())).thenReturn(List.of(order("SO-1")));
            when(orderLogisticsMapper.selectList(any())).thenReturn(List.of());   // 未发货
            when(productSkuMapper.selectList(any())).thenReturn(List.of(sku()));
            // 租户在做成本核算（#5348 的租户级事实：存在 avg_cost IS NOT NULL 的 SKU）
            when(productSkuMapper.selectCount(any())).thenReturn(1L);
            when(productMapper.selectList(any())).thenReturn(List.of(product()));
            when(afterSalesTicketMapper.selectList(any())).thenReturn(List.of(
                    returnTicket("RT-1", "O-1"), returnTicket("RT-2", "O-2")));
            when(orderItemMapper.selectList(any())).thenReturn(List.of(
                    orderItem("O-1", "P-1"), orderItem("O-2", "P-2"), orderItem("O-2", "P-3")));
            // 退货率分母（族 3 · 包 2，issue #5369）：P-1 有 4 条订单行、P-2 有 2 条
            when(orderItemMapper.selectProductOrderLineCounts(any(), any(), anyInt())).thenReturn(
                    List.of(countRow("P-1", 4L), countRow("P-2", 2L)));
            // 改价（审计源，issue #5388）：一条 product_update 的改价审计行 + 该租户审计在跑
            when(auditLogMapper.selectList(any())).thenReturn(List.of(
                    priceAuditRow("product_update", 200.0, 120.0)));
            when(auditLogMapper.selectCount(any())).thenReturn(1L);
            // 批量腿（issue #5411）：默认「本窗口内没有批量改价」⇒ 数组内容与 #5388 时逐字一致
            when(agentBatchMapper.selectList(any())).thenReturn(List.of());
            when(agentBatchItemMapper.selectList(any())).thenReturn(List.of());
        }

        /**
         * 某个 Mapper 收到的**全部**查询 wrapper（行数组装配的入参，用来钉「有界 + 租户」）。
         *
         * <p>**全部**而不是第一条：同一 Mapper 上现在有多条装配查询（#5348 的成本 join 也要查
         * `product_skus` / `order_items`）⇒ 只取第一条会让「有界 / 租户」这两条判据**只覆盖一半**
         * （这正是「判据把嫌疑指向错误的对象」那类假绿）。</p>
         */
        @SuppressWarnings({"unchecked", "rawtypes"})
        private java.util.List<AbstractWrapper<?, ?, ?>> capturedWrappers(Object mapper) {
            ArgumentCaptor<Wrapper> captor = ArgumentCaptor.forClass(Wrapper.class);
            if (mapper == orderMapper) {
                verify(orderMapper, atLeastOnce()).selectList(captor.capture());
            } else if (mapper == auditLogMapper) {
                verify(auditLogMapper, atLeastOnce()).selectList(captor.capture());
            } else if (mapper == orderLogisticsMapper) {
                verify(orderLogisticsMapper, atLeastOnce()).selectList(captor.capture());
            } else if (mapper == productSkuMapper) {
                verify(productSkuMapper, atLeastOnce()).selectList(captor.capture());
            } else if (mapper == productMapper) {
                verify(productMapper, atLeastOnce()).selectList(captor.capture());
            } else if (mapper == agentBatchMapper) {
                verify(agentBatchMapper, atLeastOnce()).selectList(captor.capture());
            } else if (mapper == agentBatchItemMapper) {
                verify(agentBatchItemMapper, atLeastOnce()).selectList(captor.capture());
            } else {
                verify(afterSalesTicketMapper, atLeastOnce()).selectList(captor.capture());
            }
            return captor.getAllValues().stream()
                    .map(raw -> (AbstractWrapper<?, ?, ?>) raw)
                    .peek(AbstractWrapper::getSqlSegment)   // 触发条件解析：参数对在解析时才填充
                    .collect(java.util.stream.Collectors.toList());
        }

        @SuppressWarnings("unchecked")
        private Set<Object> rowKeys(Map<String, Object> snapshot, String array) {
            Set<Object> keys = new LinkedHashSet<>();
            ((List<Map<String, Object>>) snapshot.get(array)).forEach(row -> keys.addAll(row.keySet()));
            return keys;
        }

        @Test
        @DisplayName("行数组契约：五个数组（含改价/让利两个新数组）；截断元信息逐数组齐备")
        void assemblesTheThreeContractArrays() {
            stubRows();

            Map<String, Object> snapshot = service.aggregateSnapshot(1L);

            assertThat((List<?>) snapshot.get("orders")).hasSize(1);
            assertThat((List<?>) snapshot.get("skus")).hasSize(1);
            assertThat((List<?>) snapshot.get("returns")).hasSize(2);
            // 改价（审计源）与让利（订单源）**都已装配**（issue #5388）—— 不再是「结构性不可达」
            assertThat((List<?>) snapshot.get("price_changes")).hasSize(1);
            assertThat((List<?>) snapshot.get("order_discounts")).hasSize(1);
            assertThat(snapshot.get("row_fields")).isEqualTo(DailyBriefingService.SNAPSHOT_ROW_FIELDS);
            assertThat(snapshot.get("audit_tool_logging")).isEqualTo(true);
            assertThat((Map<String, Object>) snapshot.get("row_meta"))
                    .as("截断必须显式：每个行数组（含退货率两端与两个新数组）都要有 row_meta")
                    .containsOnlyKeys("orders", "skus", "returns", "product_return_stats",
                            "price_changes", "order_discounts");
        }

        @Test
        @DisplayName("price_changes 行：审计行的价格真值 + 工具名；两行都来自改价类工具")
        void priceChangeRowsComeFromTheAuditLog() {
            stubRows();
            when(auditLogMapper.selectList(any())).thenReturn(List.of(
                    priceAuditRow("product_update", 200.0, 120.0),
                    priceAuditRow("sku_update", 500.0, 250.0)));

            @SuppressWarnings("unchecked")
            List<Map<String, Object>> rows =
                    (List<Map<String, Object>>) service.aggregateSnapshot(1L).get("price_changes");

            assertThat(rows).hasSize(2);
            assertThat(rows).extracting(r -> r.get("tool_name"))
                    .containsExactly("product_update", "sku_update");
            assertThat(rows.get(0))
                    .containsEntry("before_price", 200.0)
                    .containsEntry("new_price", 120.0)
                    .containsEntry("product_id", "P-1");
            assertThat(rows.get(0).get("changed_at")).isEqualTo("2026-09-22T09:30+08:00");
        }

        @Test
        @DisplayName("审计行读不出价（脱敏期历史行）⇒ 价格落 null（**未判定**，不是幅度 0）")
        void desensitizedHistoryYieldsNullPricesNotZero() {
            stubRows();
            // `params` 里有 price 键（= 确实改过价），但没有 priceChange 真值（该键上线前落库的行）
            AuditLog legacy = AuditLog.builder().id("A-legacy").tenantId(1L)
                    .resourceType("agent_tool").toolName("product_update")
                    .createdAt(OffsetDateTime.parse("2026-09-22T09:00:00+08:00"))
                    .actionDetails(Map.of("action", "update",
                            "params", Map.of("product_id", "<str>", "price", "<float>",
                                    "before_price", "<float>")))
                    .build();
            when(auditLogMapper.selectList(any())).thenReturn(List.of(legacy));

            @SuppressWarnings("unchecked")
            List<Map<String, Object>> rows =
                    (List<Map<String, Object>>) service.aggregateSnapshot(1L).get("price_changes");

            assertThat(rows).hasSize(1);
            assertThat(rows.get(0)).containsEntry("before_price", null).containsEntry("new_price", null);
            // 🔴 占位串**不得**被当成商品标识（看不见 ≠ 有值）
            assertThat(rows.get(0)).containsEntry("product_id", null);
        }

        @Test
        @DisplayName("只改名（params 无 price 键、无 priceChange）的审计行 ⇒ 不是改价事件，不进数组")
        void nonPriceAuditRowsAreNotPriceChanges() {
            stubRows();
            AuditLog rename = AuditLog.builder().id("A-rename").tenantId(1L)
                    .resourceType("agent_tool").toolName("product_update")
                    .createdAt(OffsetDateTime.parse("2026-09-22T09:00:00+08:00"))
                    .actionDetails(Map.of("action", "update", "params", Map.of("name", "<str>")))
                    .build();
            when(auditLogMapper.selectList(any())).thenReturn(List.of(rename));

            assertThat((List<?>) service.aggregateSnapshot(1L).get("price_changes")).isEmpty();
        }

        @Test
        @DisplayName("改价审计被行数上限截断 ⇒ row_meta.truncated 显式（不静默少报）")
        void priceChangeTruncationIsExplicit() {
            stubRows();
            int n = DailyBriefingService.SNAPSHOT_ROW_FETCH_LIMIT;
            when(auditLogMapper.selectList(any())).thenReturn(
                    java.util.stream.IntStream.rangeClosed(1, n)
                            .mapToObj(i -> priceAuditRow("product_update", 200.0 + i, 100.0)).toList());

            Map<String, Object> snapshot = service.aggregateSnapshot(1L);

            assertThat(metaOf(snapshot, "price_changes"))
                    .containsEntry("truncated", true)
                    .containsEntry("limit", DailyBriefingService.SNAPSHOT_ROW_LIMIT);
            assertThat((List<?>) snapshot.get("price_changes"))
                    .hasSize(DailyBriefingService.SNAPSHOT_ROW_LIMIT);
        }

        // ── 批量改价（issue #5411）：取数面 = 批次明细，**不是审计** ─────────────────────

        @Test
        @DisplayName("🔴 批量降价也进改价行（issue #5411）：取数面 = agent_batch_items 的 old/new 值")
        @SuppressWarnings("unchecked")
        void batchPriceRowsComeFromTheBatchItems() {
            stubRows();
            when(agentBatchMapper.selectList(any())).thenReturn(List.of(
                    batch("B-1", "product_price", "2026-09-22T10:05:00+08:00")));
            when(agentBatchItemMapper.selectList(any())).thenReturn(List.of(
                    batchItem(9L, "B-1", "P-9", "success", "200", "120")));

            List<Map<String, Object>> rows =
                    (List<Map<String, Object>>) service.aggregateSnapshot(1L).get("price_changes");

            Map<String, Object> batchRow = rows.stream()
                    .filter(r -> DailyBriefingService.BATCH_PRICE_TOOL.equals(r.get("tool_name")))
                    .findFirst()
                    .orElseThrow(() -> new AssertionError(
                            "批量改价行没进 price_changes ⇒ 批量降价不会被 price_change_over 发现"
                                    + "（现取行：" + rows + "）"));
            assertThat(batchRow)
                    .as("键名逐字 = 快照契约（与审计腿**同一形态**，不另立第二套）")
                    .containsOnlyKeys("change_no", "tool_name", "product_id",
                            "before_price", "new_price", "changed_at")
                    .containsEntry("before_price", 200.0)
                    .containsEntry("new_price", 120.0)
                    .containsEntry("product_id", "P-9")
                    .containsEntry("changed_at", "2026-09-22T10:05+08:00");
            assertThat(batchRow.get("change_no")).isNotNull();
            assertThat(rows).extracting(r -> r.get("tool_name"))
                    .as("审计腿**不回退**（#5388/#5410 的成果必须保住）")
                    .contains("product_update");
        }

        @Test
        @DisplayName("批量腿的筛选是承重的：批次类型 / 字段 / 排除「从未生效」/ 窗口 / 有界")
        @SuppressWarnings("rawtypes")
        void batchPriceLegFiltersAreLoadBearing() {
            stubRows();
            when(agentBatchMapper.selectList(any())).thenReturn(List.of(
                    batch("B-1", "product_price", "2026-09-22T10:05:00+08:00")));
            when(agentBatchItemMapper.selectList(any())).thenReturn(List.of(
                    batchItem(9L, "B-1", "P-9", "success", "200", "120")));

            service.aggregateSnapshot(1L);

            AbstractWrapper<?, ?, ?> batches = capturedWrappers(agentBatchMapper).get(0);
            assertThat(batches.getSqlSegment())
                    .as("批次腿：只取改价类型 + **已执行且在窗口内**（未执行的批次价没动）+ 有界")
                    .contains("batch_type = #{")
                    .contains("executed_at >= #{")
                    .contains("LIMIT " + DailyBriefingService.SNAPSHOT_ROW_FETCH_LIMIT);
            assertThat(batches.getParamNameValuePairs().values())
                    .contains(DailyBriefingService.BATCH_TYPE_PRICE);
            AbstractWrapper<?, ?, ?> items = capturedWrappers(agentBatchItemMapper).get(0);
            assertThat(items.getSqlSegment())
                    .as("条目腿：字段 = basePrice（`status` 批次的 on_sale/off_sale **不是价**）"
                            + " + 排除「从未生效」的状态（价根本没变 ⇒ 不是改价事件）")
                    .contains("field = #{")
                    .contains(" NOT IN (")
                    .contains("batch_id IN (");
            assertThat(items.getParamNameValuePairs().values())
                    .contains(DailyBriefingService.BATCH_FIELD_BASE_PRICE)
                    .containsAll(DailyBriefingService.BATCH_ITEM_NEVER_APPLIED);
        }

        @Test
        @DisplayName("两腿**同数组合并**：按时刻倒序；批量腿被上限截断 ⇒ truncated 显式")
        @SuppressWarnings("unchecked")
        void batchRowsMergeWithAuditRowsAndTruncationIsExplicit() {
            stubRows();   // 审计腿 1 行 @2026-09-22T09:30
            when(agentBatchMapper.selectList(any())).thenReturn(List.of(
                    batch("B-1", "product_price", "2026-09-22T10:05:00+08:00")));
            when(agentBatchItemMapper.selectList(any())).thenReturn(List.of(
                    batchItem(1L, "B-1", "P-9", "success", "200", "120")));

            assertThat((List<Map<String, Object>>) service.aggregateSnapshot(1L).get("price_changes"))
                    .as("最新在前（与审计腿同一排序口径）")
                    .extracting(r -> r.get("tool_name"))
                    .containsExactly(DailyBriefingService.BATCH_PRICE_TOOL, "product_update");

            int n = DailyBriefingService.SNAPSHOT_ROW_FETCH_LIMIT;
            when(agentBatchMapper.selectList(any())).thenReturn(
                    java.util.stream.IntStream.rangeClosed(1, n)
                            .mapToObj(i -> batch("B-" + i, "product_price",
                                    "2026-09-22T10:05:00+08:00")).toList());
            when(agentBatchItemMapper.selectList(any())).thenReturn(
                    java.util.stream.IntStream.rangeClosed(1, n)
                            .mapToObj(i -> batchItem((long) i, "B-" + i, "P-" + i, "success",
                                    "200", "120")).toList());

            Map<String, Object> truncatedSnap = service.aggregateSnapshot(1L);

            assertThat(metaOf(truncatedSnap, "price_changes"))
                    .as("截断必须显式（批量腿与审计腿共用同一个上限口径）")
                    .containsEntry("truncated", true)
                    .containsEntry("limit", DailyBriefingService.SNAPSHOT_ROW_LIMIT);
            assertThat((List<?>) truncatedSnap.get("price_changes"))
                    .hasSize(DailyBriefingService.SNAPSHOT_ROW_LIMIT);
        }

        @Test
        @DisplayName("租户级事实 audit_tool_logging：窗口内有任意写工具审计行 ⇒ true；0/缺 ⇒ false")
        void auditToolLoggingFactSeparatesTheTwoKindsOfEmpty() {
            stubRows();
            when(auditLogMapper.selectCount(any())).thenReturn(0L);
            when(auditLogMapper.selectList(any())).thenReturn(List.of());

            Map<String, Object> noAudit = service.aggregateSnapshot(1L);

            // 🔴 关键区分（issue #5388）：**从没改过价**与**审计没在跑**不许共用一个说法
            assertThat(noAudit.get("audit_tool_logging")).isEqualTo(false);

            when(auditLogMapper.selectCount(any())).thenReturn(3L);
            assertThat(service.aggregateSnapshot(1L).get("audit_tool_logging")).isEqualTo(true);

            when(auditLogMapper.selectCount(any())).thenReturn(null);   // 未知 ⇒ 不宣称「在跑」
            assertThat(service.aggregateSnapshot(1L).get("audit_tool_logging")).isEqualTo(false);
        }

        @Test
        @DisplayName("order_discounts 行：让利订单的四个契约字段（金额原样给，不在这里算）")
        void discountRowsCarryTheContractFields() {
            stubRows();

            @SuppressWarnings("unchecked")
            List<Map<String, Object>> rows =
                    (List<Map<String, Object>>) service.aggregateSnapshot(1L).get("order_discounts");

            assertThat(rows).hasSize(1);
            assertThat(rows.get(0))
                    .containsEntry("order_no", "SO-1")
                    .containsEntry("total_amount", new BigDecimal("1500.00"))
                    .containsEntry("discount_amount", new BigDecimal("400.00"));
            assertThat(rows.get(0).get("created_at")).isEqualTo("2026-09-12T10:00+08:00");
        }

        @Test
        @DisplayName("orders 行按契约字段装配：成交金额实付优先、customer_id 取下单用户、shipped_at 来自物流")
        void orderRowsFollowTheContract() {
            stubRows();

            Map<String, Object> snapshot = service.aggregateSnapshot(1L);

            @SuppressWarnings("unchecked")
            Map<String, Object> row = ((List<Map<String, Object>>) snapshot.get("orders")).get(0);
            assertThat(row.get("order_no")).isEqualTo("SO-1");
            assertThat(row.get("status")).isEqualTo("confirmed");
            assertThat(row.get("customer_id")).isEqualTo("C-1");
            assertThat(row.get("shipped_at")).isNull();
            assertThat(row.get("sale_amount")).isEqualTo(new BigDecimal("1200.00"));   // 实付优先，不是 1500
        }

        @Test
        @DisplayName("已发货（物流有 shipped_at）⇒ 行里带上发货时刻，引擎据此不再当未发货")
        void shippedAtIsCarriedFromLogistics() {
            stubRows();
            when(orderLogisticsMapper.selectList(any())).thenReturn(List.of(
                    OrderLogistics.builder().tenantId(1L).orderId("O-1")
                            .shippedAt(OffsetDateTime.parse("2026-09-13T10:00:00+08:00")).build()));

            Map<String, Object> snapshot = service.aggregateSnapshot(1L);

            @SuppressWarnings("unchecked")
            Map<String, Object> row = ((List<Map<String, Object>>) snapshot.get("orders")).get(0);
            assertThat(row.get("shipped_at")).isEqualTo("2026-09-13T10:00+08:00");
        }

        @Test
        @DisplayName("快照只放 JSON 原生类型：用**落库那个** ObjectMapper 能序列化（JSONB 不炸）")
        void snapshotSerializesWithThePersistenceObjectMapper() throws Exception {
            stubRows();

            Map<String, Object> snapshot = service.aggregateSnapshot(1L);

            // `daily_briefings.source_snapshot` 走 MyBatis-Plus JacksonTypeHandler，其 ObjectMapper 是
            // **裸 new ObjectMapper()（无 JavaTimeModule）** ⇒ 快照里混进 java.time/POJO 值会在 insert 时
            // 抛 InvalidDefinitionException（本机实测：「Java 8 date/time type not supported by default」）。
            // 这条判据就是那个形态的红证：把行里的 ISO 串改回 OffsetDateTime ⇒ 本断言必红。
            String json = com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler
                    .getObjectMapper().writeValueAsString(snapshot);
            assertThat(json).contains("\"order_no\":\"SO-1\"", "\"created_at\":\"2026-09-12T10:00+08:00\"");
            assertThat(json).contains("\"returned_at\":\"2026-09-22T10:00+08:00\"");
        }

        @Test
        @DisplayName("退货行的 product_id：订单商品唯一才给，多商品订单给 null（不猜）")
        void returnProductIdIsNotGuessed() {
            stubRows();

            @SuppressWarnings("unchecked")
            List<Map<String, Object>> rows =
                    (List<Map<String, Object>>) service.aggregateSnapshot(1L).get("returns");

            assertThat(rows).extracting(r -> r.get("product_id")).containsExactly("P-1", null);
            assertThat(rows).extracting(r -> r.get("return_no")).containsExactly("RT-1", "RT-2");
        }

        @Test
        @DisplayName("下架商品下的 SKU 不进快照（与 low_stock_items 同口径）")
        void skusOfOffSaleProductsAreDropped() {
            stubRows();
            when(productMapper.selectList(any())).thenReturn(List.of());   // 商品已下架/删除

            Map<String, Object> snapshot = service.aggregateSnapshot(1L);

            assertThat((List<?>) snapshot.get("skus")).isEmpty();
        }

        @Test
        @DisplayName("有界：行数组查询一律带行数上限（取数上限 = 上限 + 1，那多的一行用来判定截断）")
        void rowQueriesAreBounded() {
            stubRows();

            service.aggregateSnapshot(1L);

            for (Object mapper : List.of(orderMapper, productSkuMapper, afterSalesTicketMapper,
                    auditLogMapper)) {
                for (AbstractWrapper<?, ?, ?> wrapper : capturedWrappers(mapper)) {
                    assertThat(wrapper.getSqlSegment())
                            .as("行数组查询必须有界（逐条，不只第一条）")
                            .contains("LIMIT " + DailyBriefingService.SNAPSHOT_ROW_FETCH_LIMIT);
                }
            }
            for (Object mapper : List.of(orderLogisticsMapper, productMapper)) {
                for (AbstractWrapper<?, ?, ?> wrapper : capturedWrappers(mapper)) {
                    assertThat(wrapper.getSqlSegment())
                            .as("附带查询也有界（入参 id 有界 + 硬上限）")
                            .contains("LIMIT " + DailyBriefingService.SNAPSHOT_ROW_LIMIT);
                }
            }
        }

        @Test
        @DisplayName("截断必须显式：取到上限+1 行 ⇒ row_meta.truncated=true，且只留上限行数")
        void truncationIsExplicit() {
            stubRows();
            when(orderMapper.selectList(any())).thenReturn(orders(DailyBriefingService.SNAPSHOT_ROW_LIMIT + 1));
            when(productSkuMapper.selectList(any())).thenReturn(skus(DailyBriefingService.SNAPSHOT_ROW_LIMIT + 1));

            Map<String, Object> snapshot = service.aggregateSnapshot(1L);

            assertThat(metaOf(snapshot, "orders"))
                    .containsEntry("truncated", true)
                    .containsEntry("limit", DailyBriefingService.SNAPSHOT_ROW_LIMIT)
                    .containsEntry("count", DailyBriefingService.SNAPSHOT_ROW_LIMIT);
            assertThat(metaOf(snapshot, "skus")).containsEntry("truncated", true);
            assertThat((List<?>) snapshot.get("orders")).hasSize(DailyBriefingService.SNAPSHOT_ROW_LIMIT);
            assertThat((List<?>) snapshot.get("skus")).hasSize(DailyBriefingService.SNAPSHOT_ROW_LIMIT);
            // 逐数组：没越界的退货数组照旧 false（不许整体拉黑）
            assertThat(metaOf(snapshot, "returns")).containsEntry("truncated", false);
        }

        @Test
        @DisplayName("退货率分母被上限截断 ⇒ row_meta 显式（看不见的商品不得读成「没有退货」）")
        void returnStatsTruncationIsExplicit() {
            stubRows();
            when(orderItemMapper.selectProductOrderLineCounts(any(), any(), anyInt()))
                    .thenReturn(countRows(DailyBriefingService.SNAPSHOT_ROW_FETCH_LIMIT));

            Map<String, Object> snapshot = service.aggregateSnapshot(1L);

            assertThat(metaOf(snapshot, "product_return_stats"))
                    .containsEntry("truncated", true)
                    .containsEntry("limit", DailyBriefingService.SNAPSHOT_ROW_LIMIT);
            assertThat((List<?>) snapshot.get("product_return_stats"))
                    .hasSize(DailyBriefingService.SNAPSHOT_ROW_LIMIT);
        }

        @Test
        @DisplayName("未越界 ⇒ 三个数组都报 truncated=false，count = 实际行数")
        void noTruncationWhenWithinLimit() {
            stubRows();

            Map<String, Object> snapshot = service.aggregateSnapshot(1L);

            assertThat(metaOf(snapshot, "orders")).containsEntry("truncated", false).containsEntry("count", 1);
            assertThat(metaOf(snapshot, "skus")).containsEntry("truncated", false).containsEntry("count", 1);
            assertThat(metaOf(snapshot, "returns")).containsEntry("truncated", false).containsEntry("count", 2);
            assertThat(metaOf(snapshot, "product_return_stats"))
                    .containsEntry("truncated", false).containsEntry("count", 2);
        }

        @Test
        @DisplayName("SKU 行带 SKU 级权威列（销量/售价/移动加权成本）；成本未知**原样 null**，不被 0 冒充")
        void skuRowCarriesAuthorityColumns() {
            stubRows();
            when(productSkuMapper.selectList(any())).thenReturn(List.of(
                    ProductSku.builder().id(7L).tenantId(1L).productId("P-1")
                            .stock(new BigDecimal("20.5")).salesCount(new BigDecimal("120.0"))
                            .price(new BigDecimal("168.00")).avgCost(new BigDecimal("100.0000")).build(),
                    ProductSku.builder().id(8L).tenantId(1L).productId("P-1")
                            .stock(new BigDecimal("0.0")).salesCount(new BigDecimal("30.5"))
                            .price(new BigDecimal("168.00")).avgCost(null).build()));

            @SuppressWarnings("unchecked")
            List<Map<String, Object>> rows =
                    (List<Map<String, Object>>) service.aggregateSnapshot(1L).get("skus");

            assertThat(rows).hasSize(2);
            assertThat(rows.get(0))
                    .containsEntry("sales_count", new BigDecimal("120.0"))
                    .containsEntry("price", new BigDecimal("168.00"))
                    .containsEntry("avg_cost", new BigDecimal("100.0000"));
            // 🔴 未知成本不得被 0 冒充（`schema.sql`：存量不回填、不猜 0）—— 视图侧据这个 null 判「未知」
            assertThat(rows.get(1).get("avg_cost"))
                    .as("成本未知必须是 null").isNull();
            assertThat(rows.get(1).get("stock")).isEqualTo(new BigDecimal("0.0"));
        }

        @Test
        @DisplayName("退货率两端：分子复用退货行的商品归属、分母来自订单行数；0 是**真 0**")
        void productReturnStatsMergesBothEnds() {
            stubRows();

            @SuppressWarnings("unchecked")
            List<Map<String, Object>> rows = (List<Map<String, Object>>)
                    service.aggregateSnapshot(1L).get("product_return_stats");

            assertThat(rows).extracting(row -> row.get("product_id")).containsExactly("P-1", "P-2");
            // RT-1 的订单只有 P-1（单商品 ⇒ 归属得到）；RT-2 的订单有两个商品 ⇒ 不猜、不进任何商品
            assertThat(rows.get(0)).containsEntry("return_tickets", 1)
                    .containsEntry("order_lines", 4L);
            // P-2 当期 0 退货、2 条订单行 ⇒ 退货率**真 0**（有分母才算得出 0，不是未知）
            assertThat(rows.get(1)).containsEntry("return_tickets", 0)
                    .containsEntry("order_lines", 2L);
        }

        @Test
        @DisplayName("退货率分母：显式租户 + 有界 + 与退货行**同一窗口**（issue #5369 的口径同源）")
        void orderLineCountsAreTenantScopedBoundedAndSameWindow() {
            stubRows();

            service.aggregateSnapshot(1L);

            ArgumentCaptor<OffsetDateTime> window = ArgumentCaptor.forClass(OffsetDateTime.class);
            ArgumentCaptor<Integer> limit = ArgumentCaptor.forClass(Integer.class);
            verify(orderItemMapper).selectProductOrderLineCounts(eq(1L), window.capture(),
                    limit.capture());

            assertThat(limit.getValue())
                    .as("分母查询必须有界（取数上限 = 上限 + 1）")
                    .isEqualTo(DailyBriefingService.SNAPSHOT_ROW_FETCH_LIMIT);
            java.util.List<Object> returnsWindows = capturedWrappers(afterSalesTicketMapper).stream()
                    .flatMap(wrapper -> wrapper.getParamNameValuePairs().values().stream())
                    .filter(value -> value instanceof OffsetDateTime)
                    .toList();
            assertThat(returnsWindows)
                    .as("退货行查询本次应恰好带一个时刻参数（窗口）—— 多个说明口径已开始分叉")
                    .hasSize(1);
            assertThat(window.getValue())
                    .as("分子与分母必须同窗口（两处各算一次就会漂）")
                    .isEqualTo(returnsWindows.get(0));
        }

        @Test
        @DisplayName("租户隔离：行数组查询一律显式带 tenantId；装配用的表都在拦截器覆盖范围内")
        void rowsAreTenantScoped() throws Exception {
            stubRows();

            service.aggregateSnapshot(1L);

            for (Object mapper : List.of(orderMapper, orderLogisticsMapper, productSkuMapper,
                    productMapper, afterSalesTicketMapper, auditLogMapper)) {
                for (AbstractWrapper<?, ?, ?> wrapper : capturedWrappers(mapper)) {
                    assertThat(wrapper.getParamNameValuePairs().values())
                            .as("行数组查询必须显式带 tenantId（拦截器之外的第二道，逐条）")
                            .contains(1L);
                }
            }

            // orders/product_skus/products/order_logistics 的 tenant_id 还由 TenantLineInnerInterceptor 注入
            // ⇒ 这几张表**不得**出现在忽略清单里（否则行数组会跨租户）
            Field field = MybatisPlusConfig.class.getDeclaredField("IGNORE_TENANT_TABLES");
            field.setAccessible(true);
            @SuppressWarnings("unchecked")
            List<String> ignored = (List<String>) field.get(null);
            assertThat(ignored).doesNotContain(
                    "orders", "order_logistics", "product_skus", "products", "after_sales_tickets",
                    "order_items");
        }

        @Test
        @DisplayName("行键集 = 装配层自描述（键名与声明不许各写一份）")
        void declaredFieldsMatchWhatIsActuallyAssembled() {
            stubRows();

            Map<String, Object> snapshot = service.aggregateSnapshot(1L);

            for (String array : DailyBriefingService.SNAPSHOT_ROW_FIELDS.keySet()) {
                assertThat(rowKeys(snapshot, array))
                        .as(array + " 行的键集必须逐字等于 row_fields 的声明")
                        .isEqualTo(new LinkedHashSet<>(DailyBriefingService.SNAPSHOT_ROW_FIELDS.get(array)));
            }
        }

        @Test
        @DisplayName("行级数组**不进 LLM 提示词**（提示词只喂 metrics + facts）")
        void rowArraysStayOutOfThePrompt() throws Exception {
            stubRows();
            when(tenantMapper.selectById(1L)).thenReturn(enabledTenant());
            when(dailyBriefingMapper.selectOne(any())).thenReturn(null);
            JsonNode parsed = objectMapper.readTree("""
                    {"summary": "x",
                     "todo": [{"priority": "high", "title": "t", "metrics": [{"key": "pending_ship_orders", "value": 10}]}],
                     "risks": [], "suggestions": []}
                    """);
            when(briefingGenerateClient.generate(eq(1L), anyMap())).thenReturn(parsed);

            service.generateForTenant(1L);

            ArgumentCaptor<Map<String, Object>> captor = ArgumentCaptor.forClass(Map.class);
            verify(briefingGenerateClient).generate(eq(1L), captor.capture());
            // 提示词视图 = 落库快照的**子集**（唯一来源仍是 aggregateSnapshot）
            assertThat(captor.getValue()).containsOnlyKeys("metrics", "facts");
            // 落库快照里行级数组照旧在（两件事各取所需）
            Map<String, Object> stored = service.aggregateSnapshot(1L);
            assertThat(stored).containsKeys("orders", "skus", "returns", "row_fields", "row_meta");
        }

        @Test
        @DisplayName("结构性不可达如实登记：price_changes 不入册（全仓仍无改价流水表）")
        void structuralGapsAreDeclared() {
            // 🔴 改价面（原「结构性接不通，另立 issue」）已由 #5388 接通：`price_changes` 现在
            // 由**审计日志**装配（裁定 C，不建流水表）⇒ 本判据翻面成**正面**断言（谁把数组摘掉 ⇒ 红）。
            // 让利面同批新增（`order_discounts`）。两条都在 `assemblesTheThreeContractArrays` 有行级断言。
            assertThat(DailyBriefingService.SNAPSHOT_ROW_FIELDS)
                    .containsKeys("price_changes", "order_discounts");
            assertThat(DailyBriefingService.PRICE_CHANGE_TOOLS)
                    .as("两个工具**都是改价**（只筛一个会漏一半，issue #5388）")
                    .containsExactly("product_update", "sku_update");
            assertThat(DailyBriefingService.AGENT_TOOL_RESOURCE_TYPE).isEqualTo("agent_tool");
        }
    }

    /**
     * 订单成本 join（issue #5348）—— 低于成本价从「结构性不可达」变成「可判定」。
     *
     * <p>冻结判据（issue #5348 评论）：逐行解析 SKU（① `processing_info.skuId` → ② 该商品**唯一** SKU
     * → ③ 不可解析）⇒ 行成本 = `quantity × avg_cost` ⇒ 订单成本 = **Σ 行成本**；
     * 🔴 **任一行不可解析或该行 `avg_cost` 为 NULL ⇒ 整单未知（`cost_amount = NULL`），不出部分和**。</p>
     */
    @Nested
    @DisplayName("订单成本 join（低于成本价，issue #5348）")
    class CostJoin {

        /** **判定本体**：`cost_amount` 是否为「整单不可判定」（NULL，而不是一个偏小的部分和）。 */
        private boolean judgedAsUnknown(Object costAmount) {
            return costAmount == null;
        }

        private Order order(String orderNo) {
            return Order.builder().id("O-1").tenantId(1L).orderNo(orderNo).status("confirmed")
                    .userId("C-1").createdAt(OffsetDateTime.parse("2026-09-22T09:00:00+08:00"))
                    .actualAmount(new BigDecimal("1200.00")).totalAmount(new BigDecimal("1500.00"))
                    .build();
        }

        private OrderItem line(String orderId, String productId, String quantity, Long skuId) {
            Map<String, Object> info = new java.util.LinkedHashMap<>();
            if (skuId != null) {
                info.put("skuId", skuId);   // processingInfo 键族见 OrderService.matchSkuId
            }
            return OrderItem.builder().tenantId(1L).orderId(orderId).productId(productId)
                    .quantity(quantity == null ? null : new BigDecimal(quantity))
                    .processingInfo(info.isEmpty() ? null : info)
                    .build();
        }

        private ProductSku costSku(long id, String productId, String avgCost) {
            return ProductSku.builder().id(id).tenantId(1L).productId(productId)
                    .stock(new BigDecimal("50")).salesCount(new BigDecimal("0"))
                    .avgCost(avgCost == null ? null : new BigDecimal(avgCost)).build();
        }

        /** 一张单商品订单（O-1）+ 给定订单行 + 给定 SKU 集 ⇒ 完整快照（成本解析的两个输入都由参数给）。 */
        @SuppressWarnings("unchecked")
        private Map<String, Object> snapshotWith(List<OrderItem> lines, List<ProductSku> skus) {
            when(orderMapper.selectList(any())).thenReturn(List.of(order("SO-1")));
            when(orderLogisticsMapper.selectList(any())).thenReturn(List.of());
            when(orderItemMapper.selectList(any())).thenReturn(lines);
            when(productSkuMapper.selectList(any())).thenReturn(skus);
            when(productSkuMapper.selectCount(any())).thenReturn(2L);   // 租户在做成本核算
            when(productMapper.selectList(any())).thenReturn(List.of());
            when(afterSalesTicketMapper.selectList(any())).thenReturn(List.of());
            return service.aggregateSnapshot(1L);
        }

        @SuppressWarnings("unchecked")
        private Map<String, Object> firstOrderRow(Map<String, Object> snapshot) {
            return ((List<Map<String, Object>>) snapshot.get("orders")).get(0);
        }

        @Test
        @DisplayName("判据 1：订单成本 = Σ(行数量 × 该行 SKU 的 avg_cost)（逐行求和，不是取某一行/取最贵）")
        void orderCostIsTheSumOfLineCosts() {
            Map<String, Object> row = firstOrderRow(snapshotWith(
                    List.of(line("O-1", "P-1", "2", 7L), line("O-1", "P-1", "3", 8L)),
                    List.of(costSku(7L, "P-1", "10.5000"), costSku(8L, "P-1", "5.0000"))));

            assertThat((BigDecimal) row.get("cost_amount"))
                    .as("2 × 10.5 + 3 × 5 = 36")
                    .isEqualByComparingTo(new BigDecimal("36.0000"));
        }

        @Test
        @DisplayName("判据 1（解析优先级 ②）：行上没声明 skuId ⇒ 该商品**唯一** SKU 无歧义可用")
        void uniqueSkuOfTheProductResolvesTheLine() {
            Map<String, Object> row = firstOrderRow(snapshotWith(
                    List.of(line("O-1", "P-1", "2.5", null)),
                    List.of(costSku(7L, "P-1", "4.0000"))));

            assertThat((BigDecimal) row.get("cost_amount")).isEqualByComparingTo(new BigDecimal("10.0000"));
        }

        @Test
        @DisplayName("判据 1（解析优先级 ①）：声明的 skuId 优先于商品唯一 SKU")
        void declaredSkuIdWinsOverTheOnlySku() {
            // 商品只有一个 SKU(7)，但行上声明的是 8（同一商品的另一个 SKU 只能来自库里的真值）
            Map<String, Object> row = firstOrderRow(snapshotWith(
                    List.of(line("O-1", "P-1", "2", 8L)),
                    List.of(costSku(7L, "P-1", "10.0000"), costSku(8L, "P-1", "3.0000"))));

            assertThat((BigDecimal) row.get("cost_amount"))
                    .as("按声明的 skuId 取价（2 × 3），不是商品的第一个 SKU（2 × 10）")
                    .isEqualByComparingTo(new BigDecimal("6.0000"));
        }

        @Test
        @DisplayName("判据 1（解析优先级 ③）：商品多 SKU 且行上无 skuId ⇒ 不可解析 ⇒ 整单未知")
        void ambiguousSkuIsUnresolvable() {
            Map<String, Object> row = firstOrderRow(snapshotWith(
                    List.of(line("O-1", "P-1", "2", null)),
                    List.of(costSku(7L, "P-1", "10.0000"), costSku(8L, "P-1", "20.0000"))));

            assertThat(judgedAsUnknown(row.get("cost_amount"))).isTrue();
        }

        @Test
        @DisplayName("🔴 判据 2：任一行成本未知 ⇒ 整单未知（**不出部分和**）")
        void oneUnknownLineMakesTheWholeOrderUnknown() {
            Map<String, Object> row = firstOrderRow(snapshotWith(
                    List.of(line("O-1", "P-1", "2", 7L),      // 可判定：2 × 10 = 20
                            line("O-1", "P-9", "3", null)),    // P-9 没有 SKU ⇒ 该行不可解析
                    List.of(costSku(7L, "P-1", "10.0000"))));

            assertThat(judgedAsUnknown(row.get("cost_amount")))
                    .as("部分和（20）会低估成本 ⇒ 宁可整单不判定")
                    .isTrue();
        }

        @Test
        @DisplayName("🔴 判据 2 红证：把判定喂成**部分和** ⇒ 同一判定必须变红（证明它不是恒真）")
        void partialSumTurnsTheJudgementRed() {
            // 注入：把「任一行未知 ⇒ 整单 NULL」改成「出部分和」（= 未知行当 0）⇒ 该单的 cost_amount 会是 20。
            // 下面这条断言必须为 false —— 否则上面那条「整单未知」是空断言（判定对任何输入都返回 true）。
            assertThat(judgedAsUnknown(new BigDecimal("20.0000")))
                    .as("部分和**不得**被判为「整单未知」")
                    .isFalse();
        }

        @Test
        @DisplayName("判据 4/5：该行 SKU 的 avg_cost 为 NULL（成本未知）⇒ 整单未知，不得用 0 冒充")
        void nullAvgCostMakesTheLineUnknown() {
            Map<String, Object> row = firstOrderRow(snapshotWith(
                    List.of(line("O-1", "P-1", "2", null)),
                    List.of(costSku(7L, "P-1", null))));

            assertThat(judgedAsUnknown(row.get("cost_amount"))).isTrue();
        }

        @Test
        @DisplayName("判据 2 边界：SKU 查询撞上行数上限 ⇒ 一律未知（截断会让「唯一 SKU」失真）")
        void truncatedSkuQueryYieldsUnknownForAllOrders() {
            List<ProductSku> tooMany = java.util.stream.IntStream
                    .rangeClosed(1, DailyBriefingService.SNAPSHOT_ROW_LIMIT + 1)
                    .mapToObj(i -> costSku(i, "P-1", "10.0000")).toList();

            Map<String, Object> row = firstOrderRow(snapshotWith(
                    List.of(line("O-1", "P-1", "2", null)), tooMany));

            assertThat(judgedAsUnknown(row.get("cost_amount")))
                    .as("截断后「该商品只有 1 个 SKU」不再可信 ⇒ 保守取未知")
                    .isTrue();
        }

        @Test
        @DisplayName("判据 3/5：orders 行自描述带上 cost_amount，且行里**恒有该键**（值可为 null）")
        void costAmountIsDeclaredAndAlwaysPresentOnTheRow() {
            Map<String, Object> snapshot = snapshotWith(
                    List.of(line("O-1", "P-1", "2", 7L)), List.of(costSku(7L, "P-1", "10.0000")));

            assertThat(DailyBriefingService.SNAPSHOT_ROW_FIELDS.get("orders")).contains("cost_amount");
            assertThat(firstOrderRow(snapshot)).containsKey("cost_amount");
            // 键集与声明逐字一致（既有判据）与「值可为 null」并不冲突：null 是「成本未知」，不是缺字段。
            assertThat(DailyBriefingService.SNAPSHOT_ROW_FIELDS.get("orders"))
                    .isEqualTo(List.of("order_no", "status", "customer_id", "created_at",
                            "shipped_at", "sale_amount", "cost_amount"));
        }

        @Test
        @DisplayName("判据 4：租户开关判据 = 是否存在 avg_cost IS NOT NULL 的 SKU（由事实推出，非人工配置项）")
        void tenantCostAccountingFactIsDerivedFromSkusWithCost() {
            when(productSkuMapper.selectCount(any())).thenReturn(0L);

            assertThat(service.costsAreTracked(1L))
                    .as("没有任何 SKU 有成本价 ⇒ 该租户没做成本核算")
                    .isFalse();

            when(productSkuMapper.selectCount(any())).thenReturn(3L);
            assertThat(service.costsAreTracked(1L)).isTrue();

            ArgumentCaptor<Wrapper> captor = ArgumentCaptor.forClass(Wrapper.class);
            verify(productSkuMapper, atLeastOnce()).selectCount(captor.capture());
            AbstractWrapper<?, ?, ?> wrapper = (AbstractWrapper<?, ?, ?>) captor.getValue();
            assertThat(wrapper.getSqlSegment())
                    .as("判据本体：数的是 avg_cost IS NOT NULL 的 SKU")
                    .contains("avg_cost IS NOT NULL");
            assertThat(wrapper.getParamNameValuePairs().values())
                    .as("租户级事实也必须显式带 tenantId")
                    .contains(1L);
        }

        @Test
        @DisplayName("判据 4：该事实随快照下发（cost_accounting），引擎据此落 not_enabled")
        void tenantFactIsCarriedInTheSnapshot() {
            Map<String, Object> snapshot = snapshotWith(
                    List.of(line("O-1", "P-1", "2", 7L)), List.of(costSku(7L, "P-1", "10.0000")));

            assertThat(snapshot.get("cost_accounting")).isEqualTo(Boolean.TRUE);
        }
    }
}
