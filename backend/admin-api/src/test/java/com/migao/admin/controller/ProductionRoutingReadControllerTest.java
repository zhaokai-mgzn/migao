// case_ids: PG-018, PG-035
package com.migao.admin.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.ProductionOperationPosition;
import com.migao.admin.entity.ProductionRouteRule;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProcessingPositionOperationMapper;
import com.migao.admin.mapper.ProductionOperationMapper;
import com.migao.admin.mapper.ProductionOperationPositionMapper;
import com.migao.admin.mapper.ProductionOperationPriceVersionMapper;
import com.migao.admin.mapper.ProductionRouteRuleMapper;
import com.migao.admin.mapper.ProductionCraftMapper;
import com.migao.admin.mapper.ProductionRouteSignalMapper;
import com.migao.admin.mapper.ProductionRouteTemplateMapper;
import com.migao.admin.mapper.ProductionRoutingVersionMapper;
import com.migao.admin.mapper.ProductionWorkLogMapper;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.ClientRequestIdService;
import com.migao.admin.service.OrderService;
import com.migao.admin.service.ProcessingOrderService;
import com.migao.admin.service.ProductionOperationCommandService;
import com.migao.admin.service.ProductionOperationQtyClient;
import com.migao.admin.service.ProductionOperationQueryService;
import com.migao.admin.service.ProductionRoutingCommandService;
import com.migao.admin.service.ProductionRoutingReadService;
import com.migao.admin.service.ProductionService;
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
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.lang.reflect.Method;
import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 两个**只读**端点（issue #4500 = 母单 #4423 的 P2c，P3 前端 #4433 的数据面前置）的契约测试。
 *
 * <ul>
 *   <li>{@code GET /api/admin/production/operation-positions} —— 部位价目矩阵（84 格，按 {@code (operation, position)}）</li>
 *   <li>{@code GET /api/admin/production/route-rules} —— 规则区（26 条，按 {@code (priority, id)}）</li>
 * </ul>
 *
 * <p><b>判据口径</b>：走 standalone MockMvc + **真实** {@link ProductionRoutingReadService}（只 mock DB 层
 * Mapper）⇒ 断言的是「服务端真实排序/整形/过滤」而不是「被调用过」。mocked mapper 返回的是
 * <b>乱序</b>行 —— 排序判据因此**可红**（去掉排序 ⇒ 返回乱序 ⇒ 断言失败）。</p>
 *
 * <p><b>为什么本类单独存在</b>：既有 {@code ProductionControllerTest} 的装配是 6 参构造 + 字段注入，
 * 本批只追加两个端点 ⇒ 不复制第二份装配、也不改既有测试（同 #4308/#4386 的「不复制装配」口径）。
 * 控制器侧只做转发，语义判据在 {@link ProductionRoutingReadServiceTest}。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("生产 · 新模型只读端点（部位价目矩阵 / 规则区，issue #4500）")
class ProductionRoutingReadControllerTest {

    private static final Long TENANT = 1L;

    private MockMvc mockMvc;
    private final ObjectMapper objectMapper = new ObjectMapper();

    // ── 被测端点的两个数据源（新两表）──
    @Mock
    private ProductionOperationPositionMapper productionOperationPositionMapper;
    @Mock
    private ProductionRouteRuleMapper productionRouteRuleMapper;

    // ── 只为装配 ProductionController 而存在（本类不触碰这些链路；口径同 P2b 后的
    //    ProductionControllerTest 装配：queryService 已改读新三表 + 工艺表）──
    @Mock
    private ProcessingOrderMapper processingOrderMapper;
    @Mock
    private ProcessingPositionOperationMapper positionOperationMapper;
    @Mock
    private ProductionWorkLogMapper workLogMapper;
    @Mock
    private OrderMapper orderMapper;
    @Mock
    private OrderItemMapper orderItemMapper;
    @Mock
    private ProcessingItemMapper processingItemMapper;
    @Mock
    private ClientRequestIdService clientRequestIdService;
    @Mock
    private ProductionOperationMapper productionOperationMapper;
    @Mock
    private ProductionRouteTemplateMapper productionRouteTemplateMapper;
    @Mock
    private ProductionCraftMapper productionCraftMapper;
    @Mock
    private ProductionRouteSignalMapper productionRouteSignalMapper;
    @Mock
    private ProductionRoutingVersionMapper routingVersionMapper;
    @Mock
    private ProductionOperationPriceVersionMapper priceVersionMapper;
    @Mock
    private ProductionOperationQtyClient operationQtyClient;
    @Mock
    private OrderService orderService;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        // 断言 LambdaQueryWrapper.getSqlSegment() 需要 TableInfo 缓存（Standalone 单测无 MapperScan 缓存，
        // 同 ProductionOperationQueryServiceTest 的既有做法）
        com.baomidou.mybatisplus.core.MybatisConfiguration conf =
                new com.baomidou.mybatisplus.core.MybatisConfiguration();
        org.apache.ibatis.builder.MapperBuilderAssistant assistant =
                new org.apache.ibatis.builder.MapperBuilderAssistant(conf, "");
        com.baomidou.mybatisplus.core.metadata.TableInfoHelper.initTableInfo(
                assistant, ProductionOperationPosition.class);
        com.baomidou.mybatisplus.core.metadata.TableInfoHelper.initTableInfo(
                assistant, ProductionRouteRule.class);
        ProductionService service = new ProductionService(
                processingOrderMapper, positionOperationMapper, workLogMapper, orderMapper,
                orderItemMapper, clientRequestIdService);
        ProductionOperationQueryService queryService = new ProductionOperationQueryService(
                productionOperationMapper, productionRouteTemplateMapper, productionRouteRuleMapper,
                productionOperationPositionMapper, productionCraftMapper, productionRouteSignalMapper);
        ProcessingOrderService processingOrderService = new ProcessingOrderService(
                processingOrderMapper, orderMapper, orderItemMapper, processingItemMapper,
                orderService, objectMapper, service, queryService, operationQtyClient);
        ProductionOperationCommandService commandService = new ProductionOperationCommandService(
                productionOperationMapper, priceVersionMapper, queryService);
        ProductionRoutingCommandService routingCommandService = new ProductionRoutingCommandService(
                productionRouteTemplateMapper, routingVersionMapper, productionOperationMapper,
                productionRouteSignalMapper, queryService);
        ProductionController controller = new ProductionController(service, queryService, commandService,
                routingCommandService, processingOrderService, orderService);
        // 新读面（issue #4500）：真实服务（只 mock 两张新表的 Mapper）
        ReflectionTestUtils.setField(controller, "productionRoutingReadService",
                new ProductionRoutingReadService(productionOperationPositionMapper, productionRouteRuleMapper));
        mockMvc = MockMvcBuilders.standaloneSetup(controller)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ── 夹具 ──

    /** 部位价目行（V71 口径：`applicable=false` 的行单价落 NULL）。 */
    private ProductionOperationPosition position(String logical, String pos, String price, boolean applicable) {
        return ProductionOperationPosition.builder()
                .id("opp-" + logical + "-" + pos).tenantId(TENANT).logicalName(logical).position(pos)
                .unitPrice(price == null ? null : new BigDecimal(price))
                .applicable(applicable).status("active").deleted(0).build();
    }

    private ProductionRouteRule rule(String id, String kind, String trigger, String pos, String action,
                                     String operation, String after, int priority) {
        return ProductionRouteRule.builder()
                .id(id).tenantId(TENANT).triggerKind(kind).triggerValue(trigger).position(pos)
                .action(action).operation(operation).afterOperation(after).priority(priority)
                .status("active").deleted(0).build();
    }

    // ── 判据 1：端点存在 + 形状 + 信封 ──

    @Test
    @DisplayName("GET /operation-positions ⇒ {success,data:[{operation,position,unit_price,applicable}]}，"
            + "乱序入库也按 (operation, position) 返回")
    void operationPositionsReturnsMatrixInStableOrder() throws Exception {
        // 故意乱序（三边 在 精裁 之前、帘头 在 布帘 之前）—— 排序由服务层显式承担
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of(
                position("三边", "帘头", "0.40", true),
                position("精裁", "纱帘", "0.40", true),
                position("精裁", "布帘", "0.40", true)));

        mockMvc.perform(get("/api/admin/production/operation-positions"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.length()").value(3))
                .andExpect(jsonPath("$.data[0].operation").value("三边"))
                .andExpect(jsonPath("$.data[0].position").value("帘头"))
                .andExpect(jsonPath("$.data[1].operation").value("精裁"))
                .andExpect(jsonPath("$.data[1].position").value("布帘"))
                .andExpect(jsonPath("$.data[2].operation").value("精裁"))
                .andExpect(jsonPath("$.data[2].position").value("纱帘"))
                // 键集逐字（issue #4500 冻结）：不多不少
                .andExpect(jsonPath("$.data[0].length()").value(4))
                .andExpect(jsonPath("$.data[0].unit_price").value(0.40))
                .andExpect(jsonPath("$.data[0].applicable").value(true));
    }

    @Test
    @DisplayName("GET /route-rules ⇒ 9 键逐字，乱序入库也按 (priority, id) 返回（同 priority 按 id）")
    void routeRulesReturnsRulesInPriorityThenIdOrder() throws Exception {
        when(productionRouteRuleMapper.selectList(any())).thenReturn(List.of(
                rule("rr-v70-26", "option", "防翘扣", null, "insert", "防翘扣", "三边", 260),
                rule("rr-v70-03", "craft", "打孔", null, "insert", "打孔", "三边", 30),
                rule("rr-v70-02", "craft", "韩褶", "布帘", "insert", "上车布", "韩褶", 20),
                rule("rr-v70-01", "craft", "韩褶", null, "insert", "韩褶", "三边", 20)));

        mockMvc.perform(get("/api/admin/production/route-rules"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.length()").value(4))
                // (priority, id)：20 档两条按 id 升序（rr-v70-01 先于 rr-v70-02），再 30、260
                .andExpect(jsonPath("$.data[0].id").value("rr-v70-01"))
                .andExpect(jsonPath("$.data[1].id").value("rr-v70-02"))
                .andExpect(jsonPath("$.data[2].id").value("rr-v70-03"))
                .andExpect(jsonPath("$.data[3].id").value("rr-v70-26"))
                // 键集逐字（issue #4500 冻结）：不多不少（9 个）
                .andExpect(jsonPath("$.data[0].length()").value(9))
                .andExpect(jsonPath("$.data[0].trigger_kind").value("craft"))
                .andExpect(jsonPath("$.data[0].trigger_value").value("韩褶"))
                .andExpect(jsonPath("$.data[0].position").isEmpty())
                .andExpect(jsonPath("$.data[0].action").value("insert"))
                .andExpect(jsonPath("$.data[0].operation").value("韩褶"))
                .andExpect(jsonPath("$.data[0].after_operation").value("三边"))
                .andExpect(jsonPath("$.data[0].priority").value(20))
                .andExpect(jsonPath("$.data[0].status").value("active"));
    }

    @Test
    @DisplayName("「不做」与「没定价」在响应里**可区分**：applicable=false + unit_price=null 原样返回（不丢行、不填 0）")
    void operationPositionsKeepsNotApplicableRowsVerbatim() throws Exception {
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of(
                position("熨烫", "纱帘", null, false),
                position("熨烫", "布帘", "0.35", true)));

        String body = mockMvc.perform(get("/api/admin/production/operation-positions"))
                .andExpect(status().isOk())
                .andReturn().getResponse()
                .getContentAsString(java.nio.charset.StandardCharsets.UTF_8);
        Map<?, ?> data = (Map<?, ?>) objectMapper.readValue(body, Map.class);
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> rows = (List<Map<String, Object>>) data.get("data");
        assertThat(rows).hasSize(2);
        assertThat(rows.get(0).get("operation")).isEqualTo("熨烫");
        assertThat(rows.get(0).get("position")).isEqualTo("布帘");
        assertThat(rows.get(0).get("unit_price")).isEqualTo(0.35);
        assertThat(rows.get(0).get("applicable")).isEqualTo(true);
        assertThat(rows.get(1).get("position")).isEqualTo("纱帘");
        assertThat(rows.get(1).get("applicable")).isEqualTo(false);
        assertThat(rows.get(1)).containsKey("unit_price");
        assertThat(rows.get(1).get("unit_price")).isNull();
    }

    // ── 判据 2：权限与租户隔离 ──

    @Test
    @DisplayName("两个端点都声明 processing:manage（类级 order:list 会被方法级覆盖）")
    void endpointsDeclareManagePermission() throws Exception {
        for (String name : List.of("operationPositions", "routeRules")) {
            Method method = ProductionController.class.getMethod(name);
            RequirePermission ann = method.getAnnotation(RequirePermission.class);
            assertThat(ann).as("%s 必须声明方法级 @RequirePermission", name).isNotNull();
            assertThat(ann.value())
                    .as("%s 的权限必须是 processing:manage（价目与规则是生产配置面）", name)
                    .isEqualTo("processing:manage");
        }
    }

    @Test
    @DisplayName("租户隔离压在 SQL 条件里（tenant_id + deleted=0 + status=active；规则另按 action 过滤）")
    void queriesAreTenantScopedInSql() throws Exception {
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of());
        when(productionRouteRuleMapper.selectList(any())).thenReturn(List.of());

        mockMvc.perform(get("/api/admin/production/operation-positions")).andExpect(status().isOk());
        mockMvc.perform(get("/api/admin/production/route-rules")).andExpect(status().isOk());

        @SuppressWarnings("unchecked")
        ArgumentCaptor<com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper<ProductionOperationPosition>>
                positionCaptor = ArgumentCaptor.forClass(
                com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper.class);
        verify(productionOperationPositionMapper).selectList(positionCaptor.capture());
        assertThat(positionCaptor.getValue().getSqlSegment())
                .as("部位价目只按 租户/软删/停用 过滤（额外值过滤 ⇒ 矩阵少格）")
                .contains("tenant_id").contains("deleted").contains("status");

        @SuppressWarnings("unchecked")
        ArgumentCaptor<com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper<ProductionRouteRule>>
                ruleCaptor = ArgumentCaptor.forClass(
                com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper.class);
        verify(productionRouteRuleMapper).selectList(ruleCaptor.capture());
        assertThat(ruleCaptor.getValue().getSqlSegment())
                .as("规则只按 租户/软删/停用 + action IN (insert,remove) 过滤")
                .contains("tenant_id").contains("deleted").contains("status")
                .contains("action").contains("IN");
    }
}
