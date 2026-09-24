// case_ids: DA-001, DA-002, ST-001, DA-016

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
                ProductSku.class, Product.class, AfterSalesTicket.class)) {
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
            return OrderItem.builder().tenantId(1L).orderId(orderId).productId(productId).build();
        }

        private Order order(String orderNo) {
            return Order.builder().id("O-1").tenantId(1L).orderNo(orderNo).status("confirmed")
                    .userId("C-1").createdAt(OffsetDateTime.parse("2026-09-12T10:00:00+08:00"))
                    .actualAmount(new BigDecimal("1200.00")).totalAmount(new BigDecimal("1500.00"))
                    .build();
        }

        private ProductSku sku() {
            return ProductSku.builder().id(7L).tenantId(1L).productId("P-1")
                    .stock(new BigDecimal("20.0")).build();
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

        /** 标准行级 stub：一张单商品订单的退货 + 一张多商品订单的退货；SKU 库存 20（在售商品下） */
        private void stubRows() {
            when(orderMapper.selectList(any())).thenReturn(List.of(order("SO-1")));
            when(orderLogisticsMapper.selectList(any())).thenReturn(List.of());   // 未发货
            when(productSkuMapper.selectList(any())).thenReturn(List.of(sku()));
            when(productMapper.selectList(any())).thenReturn(List.of(product()));
            when(afterSalesTicketMapper.selectList(any())).thenReturn(List.of(
                    returnTicket("RT-1", "O-1"), returnTicket("RT-2", "O-2")));
            when(orderItemMapper.selectList(any())).thenReturn(List.of(
                    orderItem("O-1", "P-1"), orderItem("O-2", "P-2"), orderItem("O-2", "P-3")));
        }

        /** 某个 Mapper 收到的查询 wrapper（行数组装配的入参，用来钉「有界 + 租户」） */
        @SuppressWarnings({"unchecked", "rawtypes"})
        private AbstractWrapper<?, ?, ?> capturedWrapper(Object mapper) {
            ArgumentCaptor<Wrapper> captor = ArgumentCaptor.forClass(Wrapper.class);
            if (mapper == orderMapper) {
                verify(orderMapper).selectList(captor.capture());
            } else if (mapper == orderLogisticsMapper) {
                verify(orderLogisticsMapper).selectList(captor.capture());
            } else if (mapper == productSkuMapper) {
                verify(productSkuMapper).selectList(captor.capture());
            } else if (mapper == productMapper) {
                verify(productMapper).selectList(captor.capture());
            } else {
                verify(afterSalesTicketMapper).selectList(captor.capture());
            }
            AbstractWrapper<?, ?, ?> wrapper = (AbstractWrapper<?, ?, ?>) captor.getValue();
            wrapper.getSqlSegment();   // 触发条件解析：参数对（paramNameValuePairs）在解析时才填充
            return wrapper;
        }

        @SuppressWarnings("unchecked")
        private Set<Object> rowKeys(Map<String, Object> snapshot, String array) {
            Set<Object> keys = new LinkedHashSet<>();
            ((List<Map<String, Object>>) snapshot.get(array)).forEach(row -> keys.addAll(row.keySet()));
            return keys;
        }

        @Test
        @DisplayName("契约三数组装配；price_changes **不存在**（不是「命中 0 条」）")
        void assemblesTheThreeContractArrays() {
            stubRows();

            Map<String, Object> snapshot = service.aggregateSnapshot(1L);

            assertThat((List<?>) snapshot.get("orders")).hasSize(1);
            assertThat((List<?>) snapshot.get("skus")).hasSize(1);
            assertThat((List<?>) snapshot.get("returns")).hasSize(2);
            assertThat(snapshot).doesNotContainKey("price_changes");
            assertThat(snapshot.get("row_fields")).isEqualTo(DailyBriefingService.SNAPSHOT_ROW_FIELDS);
            assertThat((Map<String, Object>) snapshot.get("row_meta"))
                    .as("截断必须显式：三个行数组都要有 row_meta")
                    .containsOnlyKeys("orders", "skus", "returns");
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

            for (Object mapper : List.of(orderMapper, productSkuMapper, afterSalesTicketMapper)) {
                assertThat(capturedWrapper(mapper).getSqlSegment())
                        .as("行数组查询必须有界")
                        .contains("LIMIT " + DailyBriefingService.SNAPSHOT_ROW_FETCH_LIMIT);
            }
            for (Object mapper : List.of(orderLogisticsMapper, productMapper)) {
                assertThat(capturedWrapper(mapper).getSqlSegment())
                        .as("附带查询也有界（入参 id 有界 + 硬上限）")
                        .contains("LIMIT " + DailyBriefingService.SNAPSHOT_ROW_LIMIT);
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
        @DisplayName("未越界 ⇒ 三个数组都报 truncated=false，count = 实际行数")
        void noTruncationWhenWithinLimit() {
            stubRows();

            Map<String, Object> snapshot = service.aggregateSnapshot(1L);

            assertThat(metaOf(snapshot, "orders")).containsEntry("truncated", false).containsEntry("count", 1);
            assertThat(metaOf(snapshot, "skus")).containsEntry("truncated", false).containsEntry("count", 1);
            assertThat(metaOf(snapshot, "returns")).containsEntry("truncated", false).containsEntry("count", 2);
        }

        @Test
        @DisplayName("租户隔离：行数组查询一律显式带 tenantId；装配用的表都在拦截器覆盖范围内")
        void rowsAreTenantScoped() throws Exception {
            stubRows();

            service.aggregateSnapshot(1L);

            for (Object mapper : List.of(orderMapper, orderLogisticsMapper, productSkuMapper,
                    productMapper, afterSalesTicketMapper)) {
                assertThat(capturedWrapper(mapper).getParamNameValuePairs().values())
                        .as("行数组查询必须显式带 tenantId（拦截器之外的第二道）")
                        .contains(1L);
            }

            // orders/product_skus/products/order_logistics 的 tenant_id 还由 TenantLineInnerInterceptor 注入
            // ⇒ 这几张表**不得**出现在忽略清单里（否则行数组会跨租户）
            Field field = MybatisPlusConfig.class.getDeclaredField("IGNORE_TENANT_TABLES");
            field.setAccessible(true);
            @SuppressWarnings("unchecked")
            List<String> ignored = (List<String>) field.get(null);
            assertThat(ignored).doesNotContain(
                    "orders", "order_logistics", "product_skus", "products", "after_sales_tickets");
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
        @DisplayName("结构性不可达如实登记：orders 无 cost_amount、price_changes 不入册")
        void structuralGapsAreDeclared() {
            // 谁把成本价/改价流水接上（另立数据模型后），这两条会红 ⇒ 逼他同步改引擎的逐规则接线判据。
            assertThat(DailyBriefingService.SNAPSHOT_ROW_FIELDS).doesNotContainKey("price_changes");
            assertThat(DailyBriefingService.SNAPSHOT_ROW_FIELDS.get("orders")).doesNotContain("cost_amount");
            assertThat(DailyBriefingService.orderRow(order("SO-1"), null)).doesNotContainKey("cost_amount");
        }
    }
}
