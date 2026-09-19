package com.migao.admin.service;

// case_ids: PG-032, PG-033

import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.ProductionOperation;
import com.migao.admin.entity.ProductionRouteRule;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProductionCraftMapper;
import com.migao.admin.mapper.ProductionOperationMapper;
import com.migao.admin.mapper.ProductionOperationPositionMapper;
import com.migao.admin.mapper.ProductionRouteRuleMapper;
import com.migao.admin.mapper.ProductionRouteSignalMapper;
import com.migao.admin.mapper.ProductionRouteTemplateMapper;
import com.migao.admin.mapper.ProductionRoutingVersionMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;

/**
 * **特殊选项写面**（issue #4570）：新建一条「特殊选项 → 插某道工序」的规则（对客单价，元/套）。
 *
 * <h2>为什么这条写面必须有护栏</h2>
 * 用户裁定「你只要能**新增工序项**就行了，并可以**设置为特殊选项或者工序**，也**支持设置单价**」——
 * 新增能力一开，坏数据就能从**界面**进来（此前规则表只有读面 + 改单价）：
 * <ul>
 *   <li>目标工序**不在工序库里** ⇒ 规则命中后 {@code insertAfterLogical} 找不到锚点/工序，
 *       这道工序永远插不进来 = **黑洞**（商家以为配了、加工单上没有）；</li>
 *   <li>同名重复 ⇒ 撞 DB 唯一索引 {@code uk_production_route_rules_tenant_trigger_operation}，
 *       报一句 SQL 错（不可行动）；</li>
 *   <li>单价三位小数 ⇒ 静默四舍五入 = **改了钱且无人知道**（列是 {@code NUMERIC(12,2)}）。</li>
 * </ul>
 *
 * <h2>红证（不会红的断言 = 空断言）</h2>
 * ① 把「目标工序存在」校验删掉 ⇒ {@link #unknownOperationIsRejectedAndNothingIsWritten} 红
 * （不再抛 422，且 insert 会被调用）；② 把重复预检删掉 ⇒ {@link #duplicateOptionIsConflict} 红；
 * ③ 把 {@code setScale(2, UNNECESSARY)} 换成 {@code round} ⇒ {@link #threeDecimalPriceIsRejected} 红。
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("特殊选项写面（issue #4570）：新建 + 护栏")
class ProductionRoutingCommandServiceOptionCreateTest {

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
    @Mock
    private ProductionRouteSignalMapper productionRouteSignalMapper;

    private ProductionRoutingCommandService service;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        service = new ProductionRoutingCommandService(
                productionRouteTemplateMapper, productionRoutingVersionMapper, productionOperationMapper,
                new ProductionOperationQueryService(productionOperationMapper, productionRouteTemplateMapper,
                        productionRouteRuleMapper, productionOperationPositionMapper,
                        productionCraftMapper, productionRouteSignalMapper),
                productionRouteRuleMapper);
        // 工序库：3 道（**变体名**口径 —— 库里存的是「三边/精裁」这类裸逻辑名与「精裁-布」变体名）
        lenient().when(productionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-1", "三边"), op("op-2", "精裁-布"), op("op-3", "外帘打卷")));
        // 规则表：默认空（无重复）
        lenient().when(productionRouteRuleMapper.selectList(any())).thenReturn(new ArrayList<>());
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    private static ProductionOperation op(String id, String name) {
        return ProductionOperation.builder().id(id).tenantId(TENANT).name(name)
                .groupName("车位").unit("米").unitPrice(new BigDecimal("0.40"))
                .isMustFinish(false).isStartMarker(false).sortOrder(1)
                .status("active").deleted(0).build();
    }

    private static ProductionRouteRule existingRule(String id, String trigger, String operation) {
        return ProductionRouteRule.builder().id(id).tenantId(TENANT).triggerKind("option")
                .triggerValue(trigger).action("insert").operation(operation).priority(260)
                .status("active").createdAt(OffsetDateTime.now()).updatedAt(OffsetDateTime.now())
                .deleted(0).build();
    }

    private static Map<String, Object> body(Object... kv) {
        Map<String, Object> map = new LinkedHashMap<>();
        for (int i = 0; i + 1 < kv.length; i += 2) {
            map.put(String.valueOf(kv[i]), kv[i + 1]);
        }
        return map;
    }

    private ProductionRouteRule inserted() {
        ArgumentCaptor<ProductionRouteRule> captor = ArgumentCaptor.forClass(ProductionRouteRule.class);
        verify(productionRouteRuleMapper).insert(captor.capture());
        return captor.getValue();
    }

    // ── 正常路径 ──────────────────────────────────────────────────────────

    @Test
    @DisplayName("PG-032 新建特殊选项：trigger_kind=option / action=insert / 目标工序逻辑名 / 元每套原样落库")
    void createsOptionRuleWithCustomerPrice() {
        Map<String, Object> result = service.createOptionRule(
                body("trigger_value", "加流苏", "operation", "三边",
                        "after_operation", "三边", "customer_unit_price", "5.00"),
                TENANT);

        ProductionRouteRule row = inserted();
        assertThat(row.getTriggerKind()).isEqualTo("option");
        assertThat(row.getAction()).isEqualTo("insert");
        assertThat(row.getTriggerValue()).isEqualTo("加流苏");
        assertThat(row.getOperation()).isEqualTo("三边");
        assertThat(row.getAfterOperation()).isEqualTo("三边");
        assertThat(row.getCustomerUnitPrice()).isEqualByComparingTo("5.00");
        assertThat(row.getStatus()).isEqualTo("active");
        assertThat(row.getDeleted()).isEqualTo(0);
        assertThat(row.getTenantId()).isEqualTo(TENANT);
        // 优先级缺省 = 本租户现有最大 + 10（规则表空 ⇒ 10），保证「排在最后生效」
        assertThat(row.getPriority()).isEqualTo(10);
        assertThat(result).containsEntry("trigger_value", "加流苏")
                .containsEntry("operation", "三边")
                .containsEntry("customer_unit_price", new BigDecimal("5.00"));
    }

    @Test
    @DisplayName("PG-032 目标工序也接受**变体名**（精裁-布 归一后 = 精裁 在库中）")
    void acceptsVariantOperationName() {
        service.createOptionRule(
                body("trigger_value", "接高", "operation", "精裁-布"), TENANT);

        assertThat(inserted().getOperation()).isEqualTo("精裁-布");
    }

    @Test
    @DisplayName("PG-032 单价留空 = **未定价**（≠ 0 元）：落 null，不落 0")
    void blankPriceMeansUnpriced() {
        service.createOptionRule(body("trigger_value", "加流苏", "operation", "三边"), TENANT);

        assertThat(inserted().getCustomerUnitPrice()).isNull();
    }

    @Test
    @DisplayName("PG-032 显式优先级原样落库（不被「最大值 + 10」覆盖）")
    void explicitPriorityWins() {
        service.createOptionRule(
                body("trigger_value", "加流苏", "operation", "三边", "priority", "999"), TENANT);

        assertThat(inserted().getPriority()).isEqualTo(999);
    }

    // ── 护栏 ──────────────────────────────────────────────────────────────

    @Test
    @DisplayName("PG-032 目标工序不在工序库 ⇒ 422 逐条理由，且**一个字节都不写**")
    void unknownOperationIsRejectedAndNothingIsWritten() {
        assertThatThrownBy(() -> service.createOptionRule(
                body("trigger_value", "加流苏", "operation", "不存在的工序"), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(thrown -> {
                    BusinessException e = (BusinessException) thrown;
                    assertThat(e.getHttpStatus()).isEqualTo(422);
                    assertThat(e.getDetails()).extracting("field").containsExactly("operation");
                    assertThat(e.getMessage()).contains("不在工序库里");
                });
        verify(productionRouteRuleMapper, never()).insert(any(ProductionRouteRule.class));
    }

    @Test
    @DisplayName("PG-032 锚点工序不在工序库 ⇒ 422（落到末尾与商家预期不符）")
    void unknownAnchorIsRejected() {
        assertThatThrownBy(() -> service.createOptionRule(
                body("trigger_value", "加流苏", "operation", "三边", "after_operation", "没有这道"), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(thrown -> assertThat(((BusinessException) thrown).getDetails())
                        .extracting("field").containsExactly("after_operation"));
        verify(productionRouteRuleMapper, never()).insert(any(ProductionRouteRule.class));
    }

    @Test
    @DisplayName("PG-032 同一条「特殊选项 → 插某工序」已存在 ⇒ 409（对齐 DB 唯一索引）")
    void duplicateOptionIsConflict() {
        List<ProductionRouteRule> rows = new ArrayList<>();
        rows.add(existingRule("rr-1", "加流苏", "三边"));
        lenient().when(productionRouteRuleMapper.selectList(any())).thenReturn(rows);

        assertThatThrownBy(() -> service.createOptionRule(
                body("trigger_value", "加流苏", "operation", "三边"), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(thrown -> {
                    BusinessException e = (BusinessException) thrown;
                    assertThat(e.getHttpStatus()).isEqualTo(409);
                    assertThat(e.getMessage()).contains("已存在");
                });
        verify(productionRouteRuleMapper, never()).insert(any(ProductionRouteRule.class));
    }

    @Test
    @DisplayName("PG-032 名称缺失 / 空白 ⇒ 422")
    void blankNameIsRejected() {
        assertThatThrownBy(() -> service.createOptionRule(
                body("trigger_value", "   ", "operation", "三边"), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(thrown -> assertThat(((BusinessException) thrown).getHttpStatus()).isEqualTo(422));
    }

    @Test
    @DisplayName("PG-032 单价三位小数 ⇒ 422（**不静默四舍五入**：列是 NUMERIC(12,2)）")
    void threeDecimalPriceIsRejected() {
        assertThatThrownBy(() -> service.createOptionRule(
                body("trigger_value", "加流苏", "operation", "三边", "customer_unit_price", "6.005"), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(thrown -> assertThat(((BusinessException) thrown).getDetails())
                        .extracting("field").containsExactly("customer_unit_price"));
        verify(productionRouteRuleMapper, never()).insert(any(ProductionRouteRule.class));
    }

    @Test
    @DisplayName("PG-032 单价为负 ⇒ 422")
    void negativePriceIsRejected() {
        assertThatThrownBy(() -> service.createOptionRule(
                body("trigger_value", "加流苏", "operation", "三边", "customer_unit_price", "-1"), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(thrown -> assertThat(((BusinessException) thrown).getHttpStatus()).isEqualTo(422));
    }
}
