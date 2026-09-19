package com.migao.admin.service;

// case_ids: PG-032, PG-033

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.entity.ProductionOperation;
import com.migao.admin.entity.ProductionOperationPriceVersion;
import com.migao.admin.entity.ProductionRouteRule;
import com.migao.admin.entity.ProductionRouteTemplate;
import com.migao.admin.entity.ProductionRouting;
import com.migao.admin.entity.ProductionRoutingVersion;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProductionCraftMapper;
import com.migao.admin.mapper.ProductionOperationMapper;
import com.migao.admin.mapper.ProductionOperationPositionMapper;
import com.migao.admin.mapper.ProductionOperationPriceVersionMapper;
import com.migao.admin.mapper.ProductionRouteRuleMapper;
import com.migao.admin.mapper.ProductionRouteSignalMapper;
import com.migao.admin.mapper.ProductionRouteTemplateMapper;
import com.migao.admin.mapper.ProductionRoutingVersionMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.apache.ibatis.builder.MapperBuilderAssistant;

import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 工艺路线 / 信号映射**写面**护栏（issue #4308 交付物 2/3，P1）
 *
 * <h2>为什么每条护栏都要有红证</h2>
 * 路线是**计件工资**（Σ 报工数量 × 工序单价）与**完工判定**（必完工序全绿）的唯一输入，
 * 工序的 {@code unit} 还决定应做数量读哪个算料键 ⇒ 一条坏路线**直接算错工人工资**。
 * 五条护栏（空序列 / 引用不存在的工序 / 重复工序 / 至少一道必完工序 / seq 归一化 1..N）
 * 与「每次变更落版本账」缺任何一条，坏数据都能静默落库。
 *
 * <h2>错误形状（冻结契约）</h2>
 * 护栏失败 = HTTP **422** + {@code error.details:[{field,message}]} **逐条**理由
 * （复用既有信封字段，不新造；{@code message} 只做一句话摘要）—— 前端「逐条展示」有据可依。
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("工艺路线/信号写面护栏（issue #4308）")
class ProductionRoutingCommandServiceTest {

    private static final Long TENANT = 1L;

    @Mock
    private ProductionRouteTemplateMapper productionRouteTemplateMapper;
    @Mock
    private ProductionRouteRuleMapper productionRouteRuleMapper;
    @Mock
    private ProductionOperationPositionMapper productionOperationPositionMapper;
    @Mock
    private ProductionCraftMapper productionCraftMapper;
    @Mock
    private ProductionRoutingVersionMapper productionRoutingVersionMapper;
    @Mock
    private ProductionOperationMapper productionOperationMapper;
    /** 信号映射表（issue #4452 起**只**给读面 `ProductionOperationQueryService` 用；写面已退役）。 */
    @Mock
    private ProductionRouteSignalMapper productionRouteSignalMapper;
    @Mock
    private ProductionOperationPriceVersionMapper priceVersionMapper;

    private ProductionRoutingCommandService service;

    @BeforeAll
    static void primeMybatisPlusLambdaCache() {
        // `LambdaUpdateWrapper.set(...)` 会**立即**求值列名（不像 LambdaQueryWrapper 的 eq 那样延迟到渲染 SQL）
        // ⇒ Standalone / Mockito 单测没有 MapperScan 建立的 TableInfo 缓存时会抛
        // 「can not find lambda cache for this entity」。软删写形态（issue #4608）走 LambdaUpdateWrapper，
        // 故在此初始化缓存（同 ProductionRoutingReadControllerTest / ProductionOperationQueryServiceTest 的既有做法）。
        MybatisConfiguration configuration = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(configuration, "");
        TableInfoHelper.initTableInfo(assistant, ProductionRouteTemplate.class);
        TableInfoHelper.initTableInfo(assistant, ProductionRouteRule.class);
    }

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        // 读面用**真实对象**（只 mock Mapper）：写面响应形态 = 路线展示形态（同一份 routingView），
        // 用 mock 会让「返回更新后的路线」退化成断言桩。
        service = new ProductionRoutingCommandService(
                productionRouteTemplateMapper, productionRoutingVersionMapper, productionOperationMapper,
                new ProductionOperationQueryService(productionOperationMapper, productionRouteTemplateMapper,
                        productionRouteRuleMapper, productionOperationPositionMapper,
                        productionCraftMapper, productionRouteSignalMapper),
                productionRouteRuleMapper);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ── 夹具 ──────────────────────────────────────────────────────────────

    private static ProductionOperation op(String name, boolean mustFinish) {
        return ProductionOperation.builder().id("op-" + name).tenantId(TENANT).name(name)
                .groupName("车位").unit("米").unitPrice(new BigDecimal("0.4"))
                .isMustFinish(mustFinish).isStartMarker(false).sortOrder(1)
                .status("active").deleted(0).build();
    }

    /** 工序库：精裁-布(必完) / 布三边 / 韩褶-布 / 外帘装袋(必完) / 外帘发货。 */
    private void stubLibrary() {
        when(productionOperationMapper.selectList(any())).thenReturn(List.of(
                op("精裁-布", true), op("布三边", false), op("韩褶-布", false),
                op("外帘装袋", true), op("外帘发货", false)));
    }

    private static ProductionRouteTemplate routing(String id, String name, boolean isDefault,
                                                   List<String> mainline) {
        return ProductionRouteTemplate.builder().id(id).tenantId(TENANT).name(name)
                .isDefault(isDefault).positions(List.of("布帘", "纱帘", "帘头"))
                .mainline(mainline).status("active").deleted(0).build();
    }

    private static Map<String, Object> body(Object... kv) {
        Map<String, Object> map = new LinkedHashMap<>();
        for (int i = 0; i < kv.length; i += 2) {
            map.put(String.valueOf(kv[i]), kv[i + 1]);
        }
        return map;
    }

    private static List<String> detailFields(BusinessException e) {
        return e.getDetails() == null ? List.of()
                : e.getDetails().stream().map(ApiResponse.ErrorDetail::getField).toList();
    }

    // ══════════ 特殊选项对客单价（元/套，issue #4567）══════════

    @Test
    @DisplayName("特殊选项定价：合法写 ⇒ 只写对客价那一列（不碰 factor）")
    void optionCustomerPriceIsWrittenOnItsOwnColumn() {
        when(productionRouteRuleMapper.selectById("rr-opt-1")).thenReturn(optionRule("rr-opt-1"));

        Map<String, Object> result =
                service.updateRuleCustomerUnitPrice("rr-opt-1", body("customer_unit_price", "6.00"), TENANT);

        assertThat(result.get("id")).isEqualTo("rr-opt-1");
        assertThat(result.get("trigger_kind")).isEqualTo("option");
        // 值按 NUMERIC(12,2) 规范化后回显
        assertThat((BigDecimal) result.get("customer_unit_price")).isEqualByComparingTo("6.00");
        // 注入：改成实体 updateById 整行回写 ⇒ 会顺带写 factor / trigger_value 等列，断言红
        verify(productionRouteRuleMapper).updateCustomerUnitPrice("rr-opt-1", TENANT, new BigDecimal("6.00"));
        verify(productionRouteRuleMapper, never()).updateById(any(ProductionRouteRule.class));
    }

    @Test
    @DisplayName("特殊选项定价：null / 空串 ⇒ 显式改回**未定价**（写 null，不是 0）")
    void blankCustomerPriceClearsToUnpriced() {
        when(productionRouteRuleMapper.selectById("rr-opt-1")).thenReturn(optionRule("rr-opt-1"));

        service.updateRuleCustomerUnitPrice("rr-opt-1", body("customer_unit_price", null), TENANT);
        service.updateRuleCustomerUnitPrice("rr-opt-1", body("customer_unit_price", "  "), TENANT);

        // 注入：把空串当 0 元写 ⇒ 断言红（未定价 ≠ 0 元）
        verify(productionRouteRuleMapper, org.mockito.Mockito.times(2))
                .updateCustomerUnitPrice("rr-opt-1", TENANT, null);
    }

    @Test
    @DisplayName("特殊选项定价：非 option 行（工艺变体）⇒ 422，**一个字节都不写**")
    void craftRuleCannotBePriced() {
        when(productionRouteRuleMapper.selectById("rr-craft-1"))
                .thenReturn(optionRule("rr-craft-1").toBuilder().triggerKind("craft").build());

        assertThatThrownBy(() ->
                service.updateRuleCustomerUnitPrice("rr-craft-1", body("customer_unit_price", "6.00"), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> {
                    BusinessException be = (BusinessException) e;
                    assertThat(be.getHttpStatus()).as("工艺变体按套收费 ⇒ 422").isEqualTo(422);
                    assertThat(detailFields(be)).contains("trigger_kind");
                });
        verify(productionRouteRuleMapper, never()).updateCustomerUnitPrice(any(), any(), any());
    }

    @Test
    @DisplayName("特殊选项定价：负数 / 非数值 / 三位小数 ⇒ 422，且**不静默四舍五入**")
    void invalidCustomerPriceIsRejected() {
        when(productionRouteRuleMapper.selectById("rr-opt-1")).thenReturn(optionRule("rr-opt-1"));

        for (Object bad : List.of("-1", "abc", "6.005")) {
            assertThatThrownBy(() ->
                    service.updateRuleCustomerUnitPrice("rr-opt-1", body("customer_unit_price", bad), TENANT))
                    .as("非法单价 %s 必须 422", bad)
                    .isInstanceOf(BusinessException.class)
                    .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(422));
        }
        verify(productionRouteRuleMapper, never()).updateCustomerUnitPrice(any(), any(), any());
    }

    @Test
    @DisplayName("特殊选项定价：行不存在 / 非本租户 / 已软删 ⇒ 404")
    void unknownRuleIsNotFound() {
        when(productionRouteRuleMapper.selectById("nope")).thenReturn(null);
        when(productionRouteRuleMapper.selectById("rr-other"))
                .thenReturn(optionRule("rr-other").toBuilder().tenantId(999L).build());
        when(productionRouteRuleMapper.selectById("rr-deleted"))
                .thenReturn(optionRule("rr-deleted").toBuilder().deleted(1).build());

        for (String id : List.of("nope", "rr-other", "rr-deleted")) {
            assertThatThrownBy(() ->
                    service.updateRuleCustomerUnitPrice(id, body("customer_unit_price", "6.00"), TENANT))
                    .as("%s 必须 404", id)
                    .isInstanceOf(BusinessException.class)
                    .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(404));
        }
        verify(productionRouteRuleMapper, never()).updateCustomerUnitPrice(any(), any(), any());
    }

    private static ProductionRouteRule optionRule(String id) {
        return ProductionRouteRule.builder().id(id).tenantId(TENANT)
                .triggerKind("option").triggerValue("拼2次").position(null)
                .action("insert").operation("拼缝").afterOperation(null).priority(210)
                .status("active").deleted(0).build();
    }

    // ══════════ 判据：路线写面护栏（PG-032；P2b / issue #4459 改模板表）══════════

    @Test
    @DisplayName("护栏 1：空主线拒（422 + mainline 逐条理由）")
    void emptyMainlineIsRejected() {
        when(productionRouteTemplateMapper.selectById("rt-1"))
                .thenReturn(routing("rt-1", "路线甲", false, List.of("布三边")));
        stubLibrary();

        assertThatThrownBy(() -> service.updateRouting("rt-1", body("mainline", List.of()), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> {
                    BusinessException be = (BusinessException) e;
                    assertThat(be.getHttpStatus()).as("护栏失败统一 422").isEqualTo(422);
                    assertThat(detailFields(be)).contains("mainline");
                });
        verify(productionRouteTemplateMapper, never()).updateById(any(ProductionRouteTemplate.class));
        verify(productionRoutingVersionMapper, never()).insert(any(ProductionRoutingVersion.class));
    }

    @Test
    @DisplayName("护栏 2：引用工序库中不存在的工序拒（指名是哪一道）")
    void unknownOperationIsRejected() {
        when(productionRouteTemplateMapper.selectById("rt-1"))
                .thenReturn(routing("rt-1", "路线甲", false, List.of("布三边")));
        stubLibrary();

        assertThatThrownBy(() -> service.updateRouting("rt-1",
                body("mainline", List.of("布三边", "库里没有的工序", "外帘装袋")), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(detailFields((BusinessException) e)).contains("mainline[1]"));
        verify(productionRouteTemplateMapper, never()).updateById(any(ProductionRouteTemplate.class));
    }

    @Test
    @DisplayName("护栏 3：重复工序拒（同工序两次 ⇒ 工人按两遍单价拿钱）")
    void duplicateOperationIsRejected() {
        when(productionRouteTemplateMapper.selectById("rt-1"))
                .thenReturn(routing("rt-1", "路线甲", false, List.of("布三边")));
        stubLibrary();

        assertThatThrownBy(() -> service.updateRouting("rt-1",
                body("mainline", List.of("布三边", "外帘装袋", "布三边")), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(detailFields((BusinessException) e)).contains("mainline[2]"));
        verify(productionRouteTemplateMapper, never()).updateById(any(ProductionRouteTemplate.class));
    }

    @Test
    @DisplayName("护栏 3b（issue #4520）：**混合写法**的同一道工序也拒 —— `精裁` 与 `精裁-布` 是一道工序")
    void duplicateOperationAcrossNotationsIsRejected() {
        // ⚠️ 这条是 issue #4520 的直接产物：判重键曾是**原始字符串**，于是
        // `["精裁", …, "精裁-布"]` 被放行 ⇒ 实例化出两道 `精裁` ⇒ **工人按两遍单价拿钱**。
        // 归一口径复用 P2b 的 normalizeOperationName（变体名 → 逻辑名），不另存映射表。
        when(productionRouteTemplateMapper.selectById("rt-1"))
                .thenReturn(routing("rt-1", "路线甲", false, List.of("精裁-布")));
        stubLibrary();

        assertThatThrownBy(() -> service.updateRouting("rt-1",
                body("mainline", List.of("精裁", "外帘装袋", "精裁-布")), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(detailFields((BusinessException) e)).contains("mainline[2]"));
        verify(productionRouteTemplateMapper, never()).updateById(any(ProductionRouteTemplate.class));
    }

    @Test
    @DisplayName("护栏 3c（issue #4520）：**不得误伤** —— 不同逻辑工序的变体名并存要放行")
    void differentLogicalOperationsAreNotFalsePositives() {
        // `精裁-布`（→精裁）与 `韩褶-布`（→韩褶）是**不同**工序 ⇒ 必须放行。
        // 没有这条，一个「把所有变体名都当成同一个」的过度归一实现会静默通过。
        when(productionRouteTemplateMapper.selectById("rt-1"))
                .thenReturn(routing("rt-1", "路线甲", false, List.of("精裁-布")));
        stubLibrary();

        assertThatCode(() -> service.updateRouting("rt-1",
                body("mainline", List.of("精裁-布", "韩褶-布", "外帘装袋")), TENANT))
                .doesNotThrowAnyException();
    }

    @Test
    @DisplayName("护栏 4：至少一道必完工序（否则完工判定永远不成立 ⇒ 这张单永远完不了工）")
    void mainlineWithoutMustFinishOperationIsRejected() {
        when(productionRouteTemplateMapper.selectById("rt-1"))
                .thenReturn(routing("rt-1", "路线甲", false, List.of("布三边")));
        stubLibrary();

        assertThatThrownBy(() -> service.updateRouting("rt-1",
                body("mainline", List.of("布三边", "韩褶-布", "外帘发货")), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(detailFields((BusinessException) e)).contains("must_finish"));
        verify(productionRouteTemplateMapper, never()).updateById(any(ProductionRouteTemplate.class));
    }

    @Test
    @DisplayName("护栏 5：合法主线 ⇒ 逐位回读 + **落版本账**（序列真的变了才写）")
    void validMainlineIsVersioned() {
        when(productionRouteTemplateMapper.selectById("rt-1"))
                .thenReturn(routing("rt-1", "路线甲", false, List.of("布三边")));
        stubLibrary();

        Map<String, Object> result = service.updateRouting("rt-1",
                body("mainline", List.of("布三边", "韩褶-布", "外帘装袋")), TENANT);

        assertThat(result.get("mainline")).asString().isEqualTo(List.of("布三边", "韩褶-布", "外帘装袋").toString());
        ArgumentCaptor<ProductionRoutingVersion> version = ArgumentCaptor.forClass(ProductionRoutingVersion.class);
        verify(productionRoutingVersionMapper).insert(version.capture());
        assertThat(version.getValue().getRoutingId())
                .as("版本账挂的是**新结构**路线行 id（production_route_templates.id）").isEqualTo("rt-1");
        assertThat(version.getValue().getOperationCount()).as("版本账记工序道数").isEqualTo(3);
        assertThat(version.getValue().getOperations())
                .as("版本账存的是**变更后**的有序序列").isEqualTo(List.of("布三边", "韩褶-布", "外帘装袋"));
        // ⚠️ 旧模型两列（部位/工艺）**必须为 null**：新模型没有这一维（工艺已降为规则触发键），
        //    而 V60 的两列是 NOT NULL ⇒ 传了非 null 反而会掩盖「写面还在按旧形状写」。
        // ⚠️ 但**本 mock 单测看不见 DB 约束拒绝**（admin-api 无 testcontainers/H2）——
        //    「表形状必须允许这两列为 null 且 FK 指向新表」由 L0 静态判据守：
        //    tests/unit_ci_workflows/test_routing_version_ledger_shape.py（issue #4581）。
        assertThat(version.getValue().getCurtainType())
                .as("旧模型遗留列：新行不写（列只为历史行保留）").isNull();
        assertThat(version.getValue().getCraft())
                .as("旧模型遗留列：新行不写（列只为历史行保留）").isNull();
    }

    @Test
    @DisplayName("同主线重复提交 = 幂等空操作（不追加无意义的版本行，沿用单价版本账口径）")
    void sameMainlineIsIdempotentNoop() {
        when(productionRouteTemplateMapper.selectById("rt-1"))
                .thenReturn(routing("rt-1", "路线甲", false, List.of("布三边", "外帘装袋")));
        stubLibrary();

        service.updateRouting("rt-1", body("mainline", List.of("布三边", "外帘装袋")), TENANT);

        verify(productionRouteTemplateMapper).updateById(any(ProductionRouteTemplate.class));
        verify(productionRoutingVersionMapper, never()).insert(any(ProductionRoutingVersion.class));
    }

    @Test
    @DisplayName("改名**只改 name**：不给 mainline 就不动序列（改一个名字不该顺带重写计件工资的输入）")
    void renameOnlyChangesName() {
        when(productionRouteTemplateMapper.selectById("rt-1"))
                .thenReturn(routing("rt-1", "旧名", false, List.of("布三边", "外帘装袋")));
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of(
                routing("rt-1", "旧名", false, List.of("布三边", "外帘装袋"))));

        Map<String, Object> result = service.updateRouting("rt-1", body("name", "新名"), TENANT);

        assertThat(result.get("name")).isEqualTo("新名");
        assertThat(result.get("mainline")).as("序列必须一字不动").asString().isEqualTo(List.of("布三边", "外帘装袋").toString());
        verify(productionRoutingVersionMapper, never()).insert(any(ProductionRoutingVersion.class));
    }

    @Test
    @DisplayName("同租户活跃路线不得重名 ⇒ 409（否则撞 DB 唯一索引变 500）")
    void renameToExistingNameIsConflict() {
        when(productionRouteTemplateMapper.selectById("rt-1"))
                .thenReturn(routing("rt-1", "路线甲", false, List.of("布三边")));
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of(
                routing("rt-1", "路线甲", false, List.of("布三边")),
                routing("rt-2", "路线乙", false, List.of("外帘装袋"))));

        assertThatThrownBy(() -> service.updateRouting("rt-1", body("name", "路线乙"), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(409));
    }

    @Test
    @DisplayName("is_default 恰一条：置 true 时把既有默认**同事务降级**（否则撞部分唯一索引变 500）")
    void settingDefaultDemotesTheCurrentDefault() {
        when(productionRouteTemplateMapper.selectById("rt-2"))
                .thenReturn(routing("rt-2", "路线乙", false, List.of("外帘装袋")));
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of(
                routing("rt-1", "路线甲", true, List.of("布三边")),
                routing("rt-2", "路线乙", false, List.of("外帘装袋"))));

        Map<String, Object> result = service.updateRouting("rt-2", body("is_default", true), TENANT);

        assertThat(result.get("is_default")).isEqualTo(true);
        ArgumentCaptor<ProductionRouteTemplate> updated =
                ArgumentCaptor.forClass(ProductionRouteTemplate.class);
        verify(productionRouteTemplateMapper, org.mockito.Mockito.atLeast(2)).updateById(updated.capture());
        assertThat(updated.getAllValues())
                .as("必须有一次是把**既有默认**（rt-1）降级为 false")
                .anySatisfy(t -> {
                    assertThat(t.getId()).isEqualTo("rt-1");
                    assertThat(t.getIsDefault()).isEqualTo(false);
                });
    }

    @Test
    @DisplayName("is_default:false ⇒ 422（取消默认会让该租户零默认 ⇒ 缺信号订单建单全部 fail-closed）")
    void clearingDefaultIsRejected() {
        when(productionRouteTemplateMapper.selectById("rt-1"))
                .thenReturn(routing("rt-1", "路线甲", true, List.of("布三边")));

        assertThatThrownBy(() -> service.updateRouting("rt-1", body("is_default", false), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> {
                    assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(422);
                    assertThat(detailFields((BusinessException) e)).contains("is_default");
                });
        verify(productionRouteTemplateMapper, never()).updateById(any(ProductionRouteTemplate.class));
    }

    @Test
    @DisplayName("停用默认路线 ⇒ 422（停用它等于把租户变成零默认）")
    void disablingDefaultIsRejected() {
        when(productionRouteTemplateMapper.selectById("rt-1"))
                .thenReturn(routing("rt-1", "路线甲", true, List.of("布三边")));

        assertThatThrownBy(() -> service.updateRouting("rt-1", body("status", "disabled"), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(detailFields((BusinessException) e)).contains("status"));
    }

    @Test
    @DisplayName("删默认路线 ⇒ 422（删了就是零默认 ⇒ 建单全 fail-closed）")
    void deletingDefaultIsRejected() {
        when(productionRouteTemplateMapper.selectById("rt-1"))
                .thenReturn(routing("rt-1", "路线甲", true, List.of("布三边")));
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of(
                routing("rt-1", "路线甲", true, List.of("布三边")),
                routing("rt-2", "路线乙", false, List.of("外帘装袋"))));

        assertThatThrownBy(() -> service.deleteRouting("rt-1", TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> {
                    assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(422);
                    assertThat(detailFields((BusinessException) e)).contains("is_default");
                });
        verify(productionRouteTemplateMapper, never()).updateById(any(ProductionRouteTemplate.class));
    }

    @Test
    @DisplayName("删最后一条路线 ⇒ 422（删了没有任何路线可用 ⇒ 一张加工单也生成不了）")
    void deletingTheLastRouteIsRejected() {
        when(productionRouteTemplateMapper.selectById("rt-1"))
                .thenReturn(routing("rt-1", "路线甲", false, List.of("布三边")));
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of(
                routing("rt-1", "路线甲", false, List.of("布三边"))));

        assertThatThrownBy(() -> service.deleteRouting("rt-1", TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(detailFields((BusinessException) e)).contains("id"));
    }

    @Test
    @DisplayName("删非默认路线 = **软删**（deleted=1：谁在何时删掉哪条路线是排查错配的唯一证据）")
    void deletingNonDefaultIsSoftDelete() {
        when(productionRouteTemplateMapper.selectById("rt-2"))
                .thenReturn(routing("rt-2", "路线乙", false, List.of("外帘装袋")));
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of(
                routing("rt-1", "路线甲", true, List.of("布三边")),
                routing("rt-2", "路线乙", false, List.of("外帘装袋"))));

        Map<String, Object> result = service.deleteRouting("rt-2", TENANT);

        assertThat(result.get("deleted")).isEqualTo(true);
        // ⚠️ 断言**调用形态**（不是「塞进实体的值」，issue #4608）：MP 全局逻辑删除会把 deleted
        // 从 updateById 的 SET 子句里剔除 ⇒ 只有显式写列（update(null, LambdaUpdateWrapper)）
        // 才真落库。改回 `setDeleted(1); updateById(...)` ⇒ 本用例红（旧写法断言的是实体里的值，
        // 所以「服务端报成功、数据还在」也能绿 —— 那正是本单要消灭的假绿）。
        ArgumentCaptor<LambdaUpdateWrapper> wrapper = ArgumentCaptor.forClass(LambdaUpdateWrapper.class);
        verify(productionRouteTemplateMapper).update(isNull(), wrapper.capture());
        verify(productionRouteTemplateMapper, never()).updateById(any(ProductionRouteTemplate.class));
        assertThat(wrapper.getValue().getSqlSet())
                .as("显式 SET 必须含 deleted 与 updated_at（updated_at = 「什么时候删的」唯一证据）")
                .contains("deleted")
                .contains("updated_at");
    }

    @Test
    @DisplayName("跨租户 / 不存在的路线 ⇒ 404（不泄漏别的租户的路线存在性）")
    void unknownRoutingIsNotFound() {
        when(productionRouteTemplateMapper.selectById("rt-x")).thenReturn(null);
        assertThatThrownBy(() -> service.updateRouting("rt-x", body("mainline", List.of("布三边")), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(404));
    }

    // ══════════════════ 判据：新建路线（PG-032）══════════════════

    @Test
    @DisplayName("新建路线：mainline 缺省 = 初版空主线；响应与 GET /routings 单项同构；落首行版本账")
    void createRoutingAllowsEmptyInitialMainline() {
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of());

        Map<String, Object> result = service.createRouting(
                body("name", "罗马帘专用路线"), TENANT);

        assertThat(result.get("name")).isEqualTo("罗马帘专用路线");
        assertThat((List<?>) result.get("mainline")).isEmpty();
        assertThat(result.get("positions")).as("缺省 = 适用三部位").asString().isEqualTo(List.of("布帘", "纱帘", "帘头").toString());
        assertThat(result.get("is_default")).as("缺省 = 不是默认（不抢既有默认）").isEqualTo(false);
        ArgumentCaptor<ProductionRouteTemplate> inserted =
                ArgumentCaptor.forClass(ProductionRouteTemplate.class);
        verify(productionRouteTemplateMapper).insert(inserted.capture());
        assertThat(inserted.getValue().getStatus()).isEqualTo("active");
        assertThat(inserted.getValue().getDeleted()).isEqualTo(0);
        // 落首行版本账：**钉住 payload**（不是只 verify「调了 insert」——那正是本单「空跑绿」的形态）。
        // ⚠️ 本 mock 单测看不见 DB 约束拒绝（admin-api 无 testcontainers/H2）⇒ 表形状由 L0 静态判据守：
        //    tests/unit_ci_workflows/test_routing_version_ledger_shape.py（issue #4581）。
        ArgumentCaptor<ProductionRoutingVersion> firstVersion =
                ArgumentCaptor.forClass(ProductionRoutingVersion.class);
        verify(productionRoutingVersionMapper).insert(firstVersion.capture());
        assertThat(firstVersion.getValue().getRoutingId())
                .as("版本账挂的是新建的路线模板 id（= production_route_templates.id，不是旧表 id）")
                .isEqualTo(inserted.getValue().getId());
        assertThat(firstVersion.getValue().getOperations())
                .as("初版空主线 ⇒ 版本账存空序列").isEqualTo(List.of());
        assertThat(firstVersion.getValue().getOperationCount()).as("空主线 ⇒ 0 道").isEqualTo(0);
        assertThat(firstVersion.getValue().getCurtainType())
                .as("旧模型遗留列：新行不写").isNull();
        assertThat(firstVersion.getValue().getCraft())
                .as("旧模型遗留列：新行不写").isNull();
    }

    @Test
    @DisplayName("新建路线：同租户活跃路线重名（含停用行）⇒ 409（否则撞 DB 唯一索引变 500）")
    void createRoutingRejectsDuplicateName() {
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of(
                routing("rt-1", "路线甲", false, List.of("布三边"))));

        assertThatThrownBy(() -> service.createRouting(body("name", "路线甲"), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(409));
        verify(productionRouteTemplateMapper, never()).insert(any(ProductionRouteTemplate.class));
    }

    @Test
    @DisplayName("新建默认路线：把既有默认同事务降级（恰一条默认的不变式）")
    void createDefaultRoutingDemotesExistingDefault() {
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of(
                routing("rt-1", "路线甲", true, List.of("布三边"))));

        Map<String, Object> result = service.createRouting(
                body("name", "路线乙", "is_default", true), TENANT);

        assertThat(result.get("is_default")).isEqualTo(true);
        ArgumentCaptor<ProductionRouteTemplate> updated =
                ArgumentCaptor.forClass(ProductionRouteTemplate.class);
        verify(productionRouteTemplateMapper).updateById(updated.capture());
        assertThat(updated.getValue().getId()).isEqualTo("rt-1");
        assertThat(updated.getValue().getIsDefault()).isEqualTo(false);
    }
    // ══════════ 判据：信号映射写面**已退役**（PG-033；issue #4452）══════════

    /**
     * 三个写面方法（{@code createSignal} / {@code updateSignal} / {@code deleteSignal}）
     * **必须已从服务类删除**：让商家继续往「存量单兜底表」里加行，只会让已经不该被读的判据继续增长。
     *
     * <p><b>红证</b>：把任一方法加回 {@code ProductionRoutingCommandService} ⇒ 本用例红
     * （方法存在 ⇒ 写面还有入口，只是控制器暂时没暴露）。</p>
     */
    @Test
    @DisplayName("#4452 信号映射写面已退役：服务类不得再有 createSignal / updateSignal / deleteSignal")
    void signalWriteSurfaceIsRetired() {
        assertThat(java.util.Arrays.stream(ProductionRoutingCommandService.class.getDeclaredMethods())
                .map(java.lang.reflect.Method::getName))
                .as("信号映射写面已退役（issue #4452）—— 表降级为存量单兜底，读面暂留、写面退场")
                .doesNotContain("createSignal", "updateSignal", "deleteSignal");
    }

    // ══════════ 判据：软删条件工序规则（PG-032；issue #4587 ④）══════════

    private static ProductionRouteRule rule(String id, int deleted) {
        return ProductionRouteRule.builder()
                .id(id).tenantId(TENANT).triggerKind("option").triggerValue("拼2次")
                .action("insert").operation("拼2次").afterOperation("三边").priority(210)
                .status("active").deleted(deleted).build();
    }

    /**
     * 软删（{@code deleted=1}，**不物理删**）：规则只影响「插/删一道工序」，删错了重加即可 ⇒
     * **无硬护栏**；但仍留痕 —— 「谁在什么时候删掉了哪条规则」是排查工序顺序错的唯一线索。
     *
     * <p><b>断言的是调用形态，不是实体里的值</b>（issue #4608）：MP 全局逻辑删除会把
     * {@code deleted} 从 {@code updateById} 的 SET 子句里剔除 ⇒ 「实体里塞了 1」与「DB 写了 1」
     * 是两件事。改回 {@code setDeleted(1); updateById(...)}（或改成 {@code deleteById}）⇒ 本用例红。</p>
     */
    @Test
    @DisplayName("软删规则 ⇒ 200 {id,deleted:true} 且**显式写列** deleted=1 + updated_at（不走 updateById）")
    void deleteRouteRuleSoftDeletes() {
        when(productionRouteRuleMapper.selectById("rr-1")).thenReturn(rule("rr-1", 0));

        Map<String, Object> result = service.deleteRouteRule("rr-1", TENANT);

        ArgumentCaptor<LambdaUpdateWrapper> wrapper = ArgumentCaptor.forClass(LambdaUpdateWrapper.class);
        verify(productionRouteRuleMapper).update(isNull(), wrapper.capture());
        verify(productionRouteRuleMapper, never()).updateById(any(ProductionRouteRule.class));
        assertThat(wrapper.getValue().getSqlSet())
                .as("显式 SET 必须含 deleted 与 updated_at（不是只「调了 update」）")
                .contains("deleted")
                .contains("updated_at");
        verify(productionRouteRuleMapper, never()).deleteById(any(String.class));
        assertThat(result.get("id")).isEqualTo("rr-1");
        assertThat(result.get("deleted")).isEqualTo(true);
    }

    /**
     * 不存在 / 跨租户 / 已软删 ⇒ <b>404</b>（与 {@code PUT /route-rules/{id}/customer-unit-price}
     * 同口径：已软删的行不该再被写面寻址）。
     *
     * <p><b>红证</b>：去掉 {@code deleted != 0} 分支（幂等当成功）⇒ 「已软删 ⇒ 404」断言红。</p>
     */
    @Test
    @DisplayName("删规则：不存在 / 跨租户 / 已软删 ⇒ 404（且不写库）")
    void deleteRouteRuleRejectsMissingForeignAndDeleted() {
        when(productionRouteRuleMapper.selectById("nope")).thenReturn(null);
        assertThatThrownBy(() -> service.deleteRouteRule("nope", TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(404));

        ProductionRouteRule foreign = rule("rr-1", 0);
        foreign.setTenantId(99L);
        when(productionRouteRuleMapper.selectById("rr-1")).thenReturn(foreign);
        assertThatThrownBy(() -> service.deleteRouteRule("rr-1", TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(404));

        when(productionRouteRuleMapper.selectById("rr-1")).thenReturn(rule("rr-1", 1));
        assertThatThrownBy(() -> service.deleteRouteRule("rr-1", TENANT))
                .as("已软删 ⇒ 404（不是幂等 200）—— 写面不再寻址已退场的行")
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(404));

        verify(productionRouteRuleMapper, never()).updateById(any(ProductionRouteRule.class));
        verify(productionRouteRuleMapper, never()).update(isNull(), any());
    }
}