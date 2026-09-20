// case_ids: PG-018, PG-035, PG-053, PG-055
package com.migao.admin.controller;

import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.ProductionOperation;
import com.migao.admin.entity.ProcessingItem;
import com.migao.admin.entity.ProductionOperationPosition;
import com.migao.admin.entity.ProductionOperationPositionPriceVersion;
import com.migao.admin.entity.ProductionRouteRule;
import com.migao.admin.entity.ProductionRouteTemplate;
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
import com.migao.admin.service.ProductionOperationPositionCommandService;
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
import org.springframework.http.MediaType;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.lang.reflect.Method;
import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
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
    /** 矩阵格**计件单价**版本账（V86，issue #4587 ②）。 */
    @Mock
    private com.migao.admin.mapper.ProductionOperationPositionPriceVersionMapper positionPriceVersionMapper;

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
        com.baomidou.mybatisplus.core.metadata.TableInfoHelper.initTableInfo(
                assistant, ProductionOperation.class);
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
                productionOperationMapper, priceVersionMapper, productionOperationPositionMapper, queryService);
        ProductionRoutingCommandService routingCommandService = new ProductionRoutingCommandService(
                productionRouteTemplateMapper, routingVersionMapper, productionOperationMapper,
                queryService, productionRouteRuleMapper, processingItemMapper);
        ProductionController controller = new ProductionController(service, queryService, commandService,
                routingCommandService, processingOrderService, orderService);
        // 新读面（issue #4500）+ 矩阵写面（issue #4587 ②）：真实服务（只 mock 底层 Mapper）
        ProductionRoutingReadService routingReadService = new ProductionRoutingReadService(
                productionOperationPositionMapper, productionRouteRuleMapper, queryService,
                processingItemMapper);
        ReflectionTestUtils.setField(controller, "productionRoutingReadService", routingReadService);
        ReflectionTestUtils.setField(controller, "productionOperationPositionCommandService",
                new ProductionOperationPositionCommandService(productionOperationPositionMapper,
                        positionPriceVersionMapper, routingReadService, queryService));
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
        return rule(id, kind, trigger, pos, action, operation, after, priority, null);
    }

    /** 工序库行（变体名元数据的来源，issue #4587 ①）。 */
    private ProductionOperation operation(String id, String name, String group, String unit,
                                          String unitPrice, String scope) {
        return ProductionOperation.builder()
                .id(id).tenantId(TENANT).name(name).groupName(group).unit(unit)
                .unitPrice(new BigDecimal(unitPrice)).scope(scope).isMustFinish(false)
                .isStartMarker(false).sortOrder(1).status("active").deleted(0).build();
    }

    private ProductionRouteRule rule(String id, String kind, String trigger, String pos, String action,
                                     String operation, String after, int priority, String customerUnitPrice) {
        return ProductionRouteRule.builder()
                .id(id).tenantId(TENANT).triggerKind(kind).triggerValue(trigger).position(pos)
                .action(action).operation(operation).afterOperation(after).priority(priority)
                .customerUnitPrice(customerUnitPrice == null ? null : new BigDecimal(customerUnitPrice))
                .status("active").deleted(0).build();
    }

    // ── 判据 1：端点存在 + 形状 + 信封 ──

    @Test
    @DisplayName("GET /operation-positions ⇒ {success,data:[10 键/行]}，乱序入库也按 (operation, position) 返回")
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
                // 键集逐字（issue #4500 冻结 4 键 + #4587 追加 id/变体元数据 − #4622 去掉变体名）：不多不少（10 个）
                .andExpect(jsonPath("$.data[0].length()").value(10))
                .andExpect(jsonPath("$.data[0].id").value("opp-三边-帘头"))
                .andExpect(jsonPath("$.data[0].unit_price").value(0.40))
                .andExpect(jsonPath("$.data[0].applicable").value(true));
    }

    @Test
    @DisplayName("GET /operation-positions：变体元数据（帘头回落布帘变体；**不含变体名**，查不到 ⇒ 5 键全 null）")
    void operationPositionsCarriesVariantMetadata() throws Exception {
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of(
                position("三边", "帘头", "0.40", true)));
        when(productionOperationMapper.selectList(any())).thenReturn(List.of(
                operation("op-busandbian", "布三边", "车位", "米", "0.40", "set")));

        mockMvc.perform(get("/api/admin/production/operation-positions"))
                .andExpect(status().isOk())
                // 帘头历史上复用**布帘**变体（V54 帘头×平幔 逐字引用 布三边）—— 由寻址键证明，与实例化同一口径
                .andExpect(jsonPath("$.data[0].variant_operation_id").value("op-busandbian"))
                // issue #4622（红证：改前这里断言的是 `variant_name` == "布三边"）：变体名**不进响应**
                .andExpect(jsonPath("$.data[0].variant_name").doesNotExist())
                .andExpect(jsonPath("$.data[0].unit").value("米"))
                .andExpect(jsonPath("$.data[0].group").value("车位"))
                .andExpect(jsonPath("$.data[0].scope").value("set"))
                .andExpect(jsonPath("$.data[0].is_must_finish").value(false));
    }

    @Test
    @DisplayName("GET /operation-positions：库里没有该变体 ⇒ 5 键**保留且全 null**（logo条 × 纱帘）")
    void operationPositionsKeepsVariantKeysNullWhenAbsent() throws Exception {
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of(
                position("logo条", "纱帘", null, false)));
        when(productionOperationMapper.selectList(any())).thenReturn(List.of(
                operation("op-logob", "logo条-布", "车位", "米", "0.60", "position")));

        mockMvc.perform(get("/api/admin/production/operation-positions"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data[0].length()").value(10))
                .andExpect(jsonPath("$.data[0].variant_operation_id").isEmpty())
                .andExpect(jsonPath("$.data[0].variant_name").doesNotExist())
                .andExpect(jsonPath("$.data[0].unit").isEmpty())
                .andExpect(jsonPath("$.data[0].group").isEmpty())
                .andExpect(jsonPath("$.data[0].scope").isEmpty())
                .andExpect(jsonPath("$.data[0].is_must_finish").isEmpty());
    }

    @Test
    @DisplayName("GET /route-rules ⇒ 10 键逐字，乱序入库也按 (priority, id) 返回（同 priority 按 id）")
    void routeRulesReturnsRulesInPriorityThenIdOrder() throws Exception {
        when(productionRouteRuleMapper.selectList(any())).thenReturn(List.of(
                rule("rr-v70-26", "option", "防翘扣", null, "insert", "防翘扣", "三边", 260, "15.00"),
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
                // 键集逐字（issue #4500 冻结 + #4567 追加 customer_unit_price）：不多不少（10 个）；
                // issue #4643 的读时归一**不新增也不删键**（`operation` / `after_operation` 只换值）
                .andExpect(jsonPath("$.data[0].length()").value(10))
                .andExpect(jsonPath("$.data[0].trigger_kind").value("craft"))
                .andExpect(jsonPath("$.data[0].trigger_value").value("韩褶"))
                .andExpect(jsonPath("$.data[0].position").isEmpty())
                .andExpect(jsonPath("$.data[0].action").value("insert"))
                .andExpect(jsonPath("$.data[0].operation").value("韩褶"))
                .andExpect(jsonPath("$.data[0].after_operation").value("三边"))
                .andExpect(jsonPath("$.data[0].priority").value(20))
                .andExpect(jsonPath("$.data[0].status").value("active"))
                // 未定价的工艺行 ⇒ **null**（不是 0 —— 未定价 ≠ 0 元）
                .andExpect(jsonPath("$.data[0].customer_unit_price").isEmpty())
                // 有价的特殊选项行 ⇒ 原样透出（元/套）
                .andExpect(jsonPath("$.data[3].customer_unit_price").value(15.00));
    }

    @Test
    @DisplayName("规则读面的 operation / after_operation 必须是**逻辑名**（存量变体名行 ⇒ 读时归一；"
            + "服务面同断言见 #4643 的 ProductionRoutingReadServiceTest，本条是 **HTTP 面**的兜底）")
    void routeRulesNormalizeLegacyVariantNamesOnRead() throws Exception {
        // 存量形态：规则表里存的是**库口径变体名**（写面过去只做「归一后存在性校验」、**落库存原文**）
        // ⇒ `routings/page.tsx` 的规则表与规则删除确认文案会把它直接渲染上屏
        // （本单 #4642 的 P2-3 豁免理由改真时点明的正是这条依赖）。
        when(productionRouteRuleMapper.selectList(any())).thenReturn(List.of(
                rule("rr-legacy-1", "craft", "韩褶", null, "insert", "布三边", "精裁-布", 10),
                // 反向护栏：合法自定义名（不在归一表里）归一后等于自身
                rule("rr-custom-1", "craft", "打孔", null, "insert", "测试22", null, 20)));

        mockMvc.perform(get("/api/admin/production/route-rules"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data[0].operation").value("三边"))
                .andExpect(jsonPath("$.data[0].after_operation").value("精裁"))
                .andExpect(jsonPath("$.data[1].operation").value("测试22"))
                // `after_operation` 为 null（追加末尾）⇒ 保持 null（不发明锚点）
                .andExpect(jsonPath("$.data[1].after_operation").isEmpty());
    }

    @Test
    @DisplayName("GET /route-rule-options ⇒ {crafts, processing_items} 取值域（issue #4616；规则创建弹窗用）")
    void routeRuleOptionsReturnsTriggerVocabulary() throws Exception {
        when(productionCraftMapper.selectList(any())).thenReturn(List.of(
                com.migao.admin.entity.ProductionCraft.builder().id("pc-1").tenantId(TENANT)
                        .name("罗马帘").isDefault(false).status("active").deleted(0).build(),
                com.migao.admin.entity.ProductionCraft.builder().id("pc-2").tenantId(TENANT)
                        .name("韩褶").isDefault(true).status("active").deleted(0).build()));
        when(processingItemMapper.selectList(any())).thenReturn(List.of(
                ProcessingItem.builder().id("pi-1").tenantId(TENANT).name("花边")
                        .status("active").deleted(0).build(),
                ProcessingItem.builder().id("pi-2").tenantId(TENANT).name("拼接")
                        .status("active").deleted(0).build()));

        mockMvc.perform(get("/api/admin/production/route-rule-options"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.crafts[0]").value("罗马帘"))
                .andExpect(jsonPath("$.data.crafts[1]").value("韩褶"))
                .andExpect(jsonPath("$.data.processing_items[0]").value("花边"))
                .andExpect(jsonPath("$.data.processing_items[1]").value("拼接"));
    }

    @Test
    @DisplayName("POST /route-rules（trigger_kind=craft）⇒ 200 + 落库 trigger_kind='craft'（issue #4616 通用化）")
    void createRouteRuleAcceptsCraftTriggerKind() throws Exception {
        when(productionCraftMapper.selectList(any())).thenReturn(List.of(
                com.migao.admin.entity.ProductionCraft.builder().id("pc-1").tenantId(TENANT)
                        .name("罗马帘").isDefault(false).status("active").deleted(0).build()));
        when(productionOperationMapper.selectList(any())).thenReturn(List.of(
                operation("op-1", "三边", "车位", "米", "0.4", "position")));
        when(productionRouteRuleMapper.selectList(any())).thenReturn(List.of());

        mockMvc.perform(post("/api/admin/production/route-rules")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"trigger_kind\":\"craft\",\"trigger_value\":\"罗马帘\","
                                + "\"operation\":\"三边\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.trigger_kind").value("craft"))
                .andExpect(jsonPath("$.data.trigger_value").value("罗马帘"))
                .andExpect(jsonPath("$.data.action").value("insert"));

        ArgumentCaptor<ProductionRouteRule> captor = ArgumentCaptor.forClass(ProductionRouteRule.class);
        verify(productionRouteRuleMapper).insert(captor.capture());
        assertThat(captor.getValue().getTriggerKind()).isEqualTo("craft");
        assertThat(captor.getValue().getCustomerUnitPrice()).isNull();
    }

    @Test
    @DisplayName("POST /route-rules：craft 带对客单价 ⇒ 422 + error.details 逐条（两套账不互读）")
    void createRouteRuleRejectsCustomerPriceOnCraft() throws Exception {
        when(productionCraftMapper.selectList(any())).thenReturn(List.of(
                com.migao.admin.entity.ProductionCraft.builder().id("pc-1").tenantId(TENANT)
                        .name("罗马帘").isDefault(false).status("active").deleted(0).build()));
        when(productionOperationMapper.selectList(any())).thenReturn(List.of(
                operation("op-1", "三边", "车位", "米", "0.4", "position")));

        mockMvc.perform(post("/api/admin/production/route-rules")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"trigger_kind\":\"craft\",\"trigger_value\":\"罗马帘\","
                                + "\"operation\":\"三边\",\"customer_unit_price\":\"5.00\"}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.details[0].field").value("customer_unit_price"))
                .andExpect(jsonPath("$.error.details[0].message").isNotEmpty());

        verify(productionRouteRuleMapper, never()).insert(any(ProductionRouteRule.class));
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

    @Test
    @DisplayName("PUT /route-rules/{id}/customer-unit-price ⇒ 200 + 逐条护栏（非 option 422 / 负数 422 / 三位小数 422）")
    void customerUnitPriceEndpointWritesOnlyOptionRules() throws Exception {
        when(productionRouteRuleMapper.selectById("rr-opt-1"))
                .thenReturn(rule("rr-opt-1", "option", "拼2次", null, "insert", "拼缝", null, 210));

        mockMvc.perform(put("/api/admin/production/route-rules/rr-opt-1/customer-unit-price")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"customer_unit_price\":\"6.00\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.trigger_kind").value("option"))
                .andExpect(jsonPath("$.data.customer_unit_price").value(6.00));

        // 非 option 行 ⇒ 422（只有特殊选项按套计价）
        when(productionRouteRuleMapper.selectById("rr-craft-1"))
                .thenReturn(rule("rr-craft-1", "craft", "韩褶", null, "insert", "韩褶", "三边", 20));
        mockMvc.perform(put("/api/admin/production/route-rules/rr-craft-1/customer-unit-price")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"customer_unit_price\":\"6.00\"}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.details[0].field").value("trigger_kind"));

        // 负数 / 三位小数 ⇒ 422 逐条理由（不静默四舍五入）
        for (String bad : new String[]{"-1", "6.005"}) {
            mockMvc.perform(put("/api/admin/production/route-rules/rr-opt-1/customer-unit-price")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("{\"customer_unit_price\":\"" + bad + "\"}"))
                    .andExpect(status().isUnprocessableEntity())
                    .andExpect(jsonPath("$.error.details[0].field").value("customer_unit_price"));
        }

        // 行不存在 ⇒ 404
        mockMvc.perform(put("/api/admin/production/route-rules/nope/customer-unit-price")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"customer_unit_price\":\"6.00\"}"))
                .andExpect(status().isNotFound());
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

    // ══════════════════ 矩阵格写面（issue #4587 ② = 母单 #4586 包A）══════════════════

    @Test
    @DisplayName("PUT /operation-positions/{id} ⇒ 200，改价留痕；不做 ⇒ 价清空；负价/三位小数 ⇒ 422 逐条")
    void updateOperationPositionEndpointSemantics() throws Exception {
        when(productionOperationPositionMapper.selectById("opp-三边-布帘"))
                .thenReturn(position("三边", "布帘", "0.40", true));
        when(productionOperationPositionMapper.updatePriceAndApplicable(
                any(), any(), any(), any(), any())).thenReturn(1);
        // 工序库有 `三边` 的布帘变体（issue #4798 起：写完 applicable=true 的格必须解析得到变体，
        // 否则 422 —— 本用例只改价，行本来就是「做」，故必须让这一格可解析）
        when(productionOperationMapper.selectList(any()))
                .thenReturn(List.of(operation("op-busandbian", "布三边", "车位", "米", "0.40", "position")));

        mockMvc.perform(put("/api/admin/production/operation-positions/opp-三边-布帘")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"unit_price\":0.55}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.id").value("opp-三边-布帘"))
                .andExpect(jsonPath("$.data.unit_price").value(0.55))
                // 响应 = 读面单行同构（issue #4622 起 10 键：去掉 `variant_name`）
                .andExpect(jsonPath("$.data.length()").value(10));
        verify(positionPriceVersionMapper).insert(any(ProductionOperationPositionPriceVersion.class));

        // 「明确不做」⇒ 价强制落 NULL（不报价），且仍留痕（价真的变了）
        mockMvc.perform(put("/api/admin/production/operation-positions/opp-三边-布帘")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"applicable\":false}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.applicable").value(false))
                .andExpect(jsonPath("$.data.unit_price").isEmpty());

        // 负价 / 超两位小数 ⇒ 422 + error.details 逐条
        for (String bad : new String[]{"-1", "0.555"}) {
            mockMvc.perform(put("/api/admin/production/operation-positions/opp-三边-布帘")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("{\"unit_price\":\"" + bad + "\"}"))
                    .andExpect(status().isUnprocessableEntity())
                    .andExpect(jsonPath("$.error.details[0].field").value("unit_price"));
        }

        // 行不存在 ⇒ 404
        mockMvc.perform(put("/api/admin/production/operation-positions/nope")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"unit_price\":0.55}"))
                .andExpect(status().isNotFound());
    }

    @Test
    @DisplayName("🔴 PUT /operation-positions/{id}：该部位解析不到变体工序 ⇒ 设为「做」422（issue #4798）")
    void updateOperationPositionRejectsUnresolvableApplicable() throws Exception {
        // 工序库里**没有** `三边` 的任何变体 ⇒ 这一格设为「做」后，实例化必然把它记进
        // missing_operations ⇒ 下单 422 整单中止。写面必须**同口径**拦下（改前：200 写库成功 = 红）
        when(productionOperationPositionMapper.selectById("opp-三边-布帘"))
                .thenReturn(position("三边", "布帘", null, false));
        when(productionOperationMapper.selectList(any())).thenReturn(List.of());

        mockMvc.perform(put("/api/admin/production/operation-positions/opp-三边-布帘")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"applicable\":true,\"unit_price\":0.50}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.details[0].field").value("applicable"));
        verify(productionOperationPositionMapper, never()).updatePriceAndApplicable(
                any(), any(), any(), any(), any());
    }

    @Test
    @DisplayName("矩阵写面端点声明 processing:manage（与 PUT /operations/{id} 同码）")
    void updateOperationPositionDeclaresManagePermission() throws Exception {
        Method method = ProductionController.class.getMethod("updateOperationPosition",
                String.class, Map.class);
        RequirePermission ann = method.getAnnotation(RequirePermission.class);
        assertThat(ann).as("矩阵格改价必须声明方法级 @RequirePermission").isNotNull();
        assertThat(ann.value()).isEqualTo("processing:manage");
    }

    @Test
    @DisplayName("DELETE /route-rules/{id} ⇒ 200 软删 {id,deleted:true}；不存在/已软删 ⇒ 404")
    void deleteRouteRuleEndpointSoftDeletes() throws Exception {
        when(productionRouteRuleMapper.selectById("rr-opt-1"))
                .thenReturn(rule("rr-opt-1", "option", "拼2次", null, "insert", "拼缝", null, 210));

        mockMvc.perform(delete("/api/admin/production/route-rules/rr-opt-1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.id").value("rr-opt-1"))
                .andExpect(jsonPath("$.data.deleted").value(true));
        ArgumentCaptor<LambdaUpdateWrapper> wrapper = ArgumentCaptor.forClass(LambdaUpdateWrapper.class);
        verify(productionRouteRuleMapper).update(isNull(), wrapper.capture());
        verify(productionRouteRuleMapper, never()).updateById(any(ProductionRouteRule.class));
        assertThat(wrapper.getValue().getSqlSet())
                .as("显式 SET 必须含 deleted 与 updated_at（issue #4608：updateById 会把 deleted 从 SET 剔除）")
                .contains("deleted")
                .contains("updated_at");

        mockMvc.perform(delete("/api/admin/production/route-rules/nope"))
                .andExpect(status().isNotFound());
    }

    @Test
    @DisplayName("DELETE /operations/{id} ⇒ 200 软删；三条护栏一次报全（422 + details 逐条）")
    void deleteOperationEndpointGuardsAndSoftDeletes() throws Exception {
        ProductionOperation beingDeleted = ProductionOperation.builder()
                .id("op-busandbian").tenantId(TENANT).name("布三边")
                .groupName("车位").unit("米").unitPrice(new BigDecimal("0.40"))
                .scope("position").isMustFinish(false).isStartMarker(false).sortOrder(1)
                .status("active").deleted(0).build();
        when(productionOperationMapper.selectById("op-busandbian")).thenReturn(beingDeleted);
        // 工序库（`variantNameOf` 的解析源）：`布三边` 在库 ⇒ `三边 × 布帘` / `三边 × 帘头` 都解析到它
        when(productionOperationMapper.selectList(any())).thenReturn(List.of(beingDeleted));
        // ① 活跃路线主线命中（主线存逻辑名 三边 ⇒ 变体名 布三边 也要能命中）
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of(
                ProductionRouteTemplate.builder().id("rt-1").tenantId(TENANT).name("窗帘工序路线（默认）")
                        .isDefault(true).positions(List.of("布帘")).mainline(List.of("三边", "车被"))
                        .status("active").deleted(0).build()));
        // ② 活跃规则命中（operation = 逻辑名）
        when(productionRouteRuleMapper.selectList(any())).thenReturn(List.of(
                rule("rr-1", "craft", "韩褶", "布帘", "insert", "三边", "韩褶", 20)));
        // ③ 矩阵行命中（**全部命中格**：帘头会回落布帘变体 ⇒ 两格都要报）
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of(
                position("三边", "布帘", "0.40", true),
                position("三边", "帘头", "0.40", true)));

        String body = mockMvc.perform(delete("/api/admin/production/operations/op-busandbian"))
                .andExpect(status().isUnprocessableEntity())
                .andReturn().getResponse()
                .getContentAsString(java.nio.charset.StandardCharsets.UTF_8);
        assertThat(body).contains("routing").contains("route_rule").contains("operation_position");
        assertThat(body).as("护栏 3 要遍历全部命中格（布帘 + 帘头回落），不是只看一格")
                .contains("布帘").contains("帘头");
        verify(productionOperationMapper, never()).updateById(any(ProductionOperation.class));

        // 三条都清干净 ⇒ 200 软删（deleted=1，不物理删）
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of());
        when(productionRouteRuleMapper.selectList(any())).thenReturn(List.of());
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of());
        mockMvc.perform(delete("/api/admin/production/operations/op-busandbian"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.deleted").value(true));
        ArgumentCaptor<LambdaUpdateWrapper> deleted = ArgumentCaptor.forClass(LambdaUpdateWrapper.class);
        verify(productionOperationMapper).update(isNull(), deleted.capture());
        verify(productionOperationMapper, never()).updateById(any(ProductionOperation.class));
        assertThat(deleted.getValue().getSqlSet())
                .as("显式 SET 必须含 deleted 与 updated_at（issue #4608：updateById 会把 deleted 从 SET 剔除）")
                .contains("deleted")
                .contains("updated_at");
    }

    @Test
    @DisplayName("DELETE /operations/{id} 已软删 ⇒ 200 幂等 no-op（不报 404）")
    void deleteOperationIsIdempotentWhenAlreadyDeleted() throws Exception {
        when(productionOperationMapper.selectById("op-busandbian")).thenReturn(
                ProductionOperation.builder().id("op-busandbian").tenantId(TENANT).name("布三边")
                        .status("active").deleted(1).build());

        mockMvc.perform(delete("/api/admin/production/operations/op-busandbian"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.deleted").value(true));
        verify(productionOperationMapper, never()).updateById(any(ProductionOperation.class));
        verify(productionOperationMapper, never()).update(isNull(), any());
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
