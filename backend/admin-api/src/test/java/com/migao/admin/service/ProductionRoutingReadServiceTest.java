// case_ids: PG-018, PG-035
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.migao.admin.entity.ProductionOperation;
import com.migao.admin.entity.ProductionOperationPosition;
import com.migao.admin.entity.ProductionRouteRule;
import com.migao.admin.mapper.ProcessingItemMapper;
import com.migao.admin.mapper.ProductionCraftMapper;
import com.migao.admin.mapper.ProductionOperationMapper;
import com.migao.admin.mapper.ProductionOperationPositionMapper;
import com.migao.admin.mapper.ProductionRouteRuleMapper;
import com.migao.admin.mapper.ProductionRouteSignalMapper;
import com.migao.admin.mapper.ProductionRouteTemplateMapper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * {@link ProductionRoutingReadService} 的语义判据（issue #4500 = 母单 #4423 的 P2c）。
 *
 * <p>判据三条，各自**注入式可红**：</p>
 * <ol>
 *   <li><b>顺序确定性</b>：mocked mapper 返回**乱序**行 ⇒ 输出必须是 {@code (operation, position)} /
 *       {@code (priority, id)} 序。去掉比较器 ⇒ 红（返回乱序）。</li>
 *   <li><b>逐字取库（不写死、不换算）</b>：单价 / applicable / 锚点 / 触发键都跟着库行变
 *       （写死常量或做换算 ⇒ 断言不跟着变 ⇒ 红）。</li>
 *   <li><b>行过滤只有 租户/软删/停用（+ 规则表 action）</b>：断言落在 SQL 条件上
 *       —— 加一条值过滤（如 {@code applicable=true}）会让矩阵少格。</li>
 * </ol>
 *
 * <p>与 Python 侧守卫的分工：值层面的「84 格 / 26 条 ↔ {@code routing.py} 真值源」在
 * {@code tests/unit_ci_workflows/test_routing_read_endpoints.py}（Java 无法 import Python）；
 * 本类判的是**服务层行为**。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("ProductionRoutingReadService 新模型只读面（部位价目矩阵 / 规则区）")
class ProductionRoutingReadServiceTest {

    private static final Long TENANT = 1L;

    @Mock
    private ProductionOperationPositionMapper productionOperationPositionMapper;
    @Mock
    private ProductionRouteRuleMapper productionRouteRuleMapper;
    /** 工序库（变体名元数据来源，issue #4587 ①）：读面经 {@code ProductionOperationQueryService} 取。 */
    @Mock
    private ProductionOperationMapper productionOperationMapper;
    @Mock
    private ProductionRouteTemplateMapper productionRouteTemplateMapper;
    @Mock
    private ProductionCraftMapper productionCraftMapper;
    @Mock
    private ProcessingItemMapper processingItemMapper;
    @Mock
    private ProductionRouteSignalMapper productionRouteSignalMapper;

    private ProductionRoutingReadService service() {
        ProductionOperationQueryService queryService = new ProductionOperationQueryService(
                productionOperationMapper, productionRouteTemplateMapper, productionRouteRuleMapper,
                productionOperationPositionMapper, productionCraftMapper, productionRouteSignalMapper);
        return new ProductionRoutingReadService(productionOperationPositionMapper,
                productionRouteRuleMapper, queryService, processingItemMapper);
    }

    /**
     * 初始化 MyBatis-Plus 的 TableInfo 缓存（同 {@code ProductionOperationQueryServiceTest} 的既有做法）：
     * 断言 {@code LambdaQueryWrapper.getSqlSegment()} 需要它，否则报
     * 「MybatisPlus can not find lambda cache for this entity」。
     */
    @BeforeEach
    void initTableInfoCache() {
        MybatisConfiguration conf = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(conf, "");
        TableInfoHelper.initTableInfo(assistant, ProductionOperationPosition.class);
        TableInfoHelper.initTableInfo(assistant, ProductionRouteRule.class);
        TableInfoHelper.initTableInfo(assistant, ProductionOperation.class);
    }

    // ── 夹具 ──

    private ProductionOperationPosition position(String logical, String pos, String price, boolean applicable) {
        return ProductionOperationPosition.builder()
                .id("opp-" + logical + "-" + pos).tenantId(TENANT).logicalName(logical).position(pos)
                .unitPrice(price == null ? null : new BigDecimal(price))
                .applicable(applicable).status("active").deleted(0).build();
    }

    /** 工序库行（变体名元数据；`id` 是 ① 的 `variant_operation_id` 来源）。 */
    private ProductionOperation operation(String id, String name, String group, String unit,
                                          String unitPrice, String scope, boolean mustFinish) {
        return ProductionOperation.builder()
                .id(id).tenantId(TENANT).name(name).groupName(group).unit(unit)
                .unitPrice(new BigDecimal(unitPrice)).scope(scope).isMustFinish(mustFinish)
                .isStartMarker(false).sortOrder(1).status("active").deleted(0).build();
    }

    private ProductionRouteRule rule(String id, String kind, String trigger, String pos, String action,
                                     String operation, String after, int priority) {
        return rule(id, kind, trigger, pos, action, operation, after, priority, null);
    }

    private ProductionRouteRule rule(String id, String kind, String trigger, String pos, String action,
                                     String operation, String after, int priority, String customerUnitPrice) {
        return ProductionRouteRule.builder()
                .id(id).tenantId(TENANT).triggerKind(kind).triggerValue(trigger).position(pos)
                .action(action).operation(operation).afterOperation(after).priority(priority)
                .customerUnitPrice(customerUnitPrice == null ? null : new BigDecimal(customerUnitPrice))
                .status("active").deleted(0).build();
    }

    // ── 判据 1：顺序确定性（乱序入库 ⇒ 稳定输出）──

    @Test
    @DisplayName("部位价目：乱序入库 ⇒ 按 (operation, position) 输出（去掉比较器即红）")
    void operationPositionsSortsByOperationThenPosition() {
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of(
                position("韩褶", "布帘", "0.40", true),
                position("精裁", "纱帘", "0.40", true),
                position("三边", "帘头", "0.40", true),
                position("精裁", "布帘", "0.40", true)));

        List<Map<String, Object>> rows = service().operationPositions(TENANT);

        assertThat(rows).extracting(r -> r.get("operation") + "/" + r.get("position"))
                .containsExactly("三边/帘头", "精裁/布帘", "精裁/纱帘", "韩褶/布帘");
    }

    @Test
    @DisplayName("规则：乱序入库 ⇒ 按 (priority, id) 输出（同 priority 按 id —— priority 撞档时顺序必须可预测）")
    void routeRulesSortsByPriorityThenId() {
        when(productionRouteRuleMapper.selectList(any())).thenReturn(List.of(
                rule("rr-v70-26", "option", "防翘扣", null, "insert", "防翘扣", "三边", 260),
                rule("rr-v70-02", "craft", "韩褶", "布帘", "insert", "上车布", "韩褶", 20),
                rule("rr-v70-01", "craft", "韩褶", null, "insert", "韩褶", "三边", 20),
                rule("rr-v70-11", "option", "拼1次", null, "insert", "拼1次", "三边", 110)));

        List<Map<String, Object>> rows = service().routeRules(TENANT);

        assertThat(rows).extracting(r -> r.get("id"))
                .containsExactly("rr-v70-01", "rr-v70-02", "rr-v70-11", "rr-v70-26");
    }

    // ── 判据 2：逐字取库（注入式）──

    @Test
    @DisplayName("部位价目：单价/applicable 逐字取库；applicable=false 的格 unit_price=null 且**不丢行**")
    void operationPositionsCarriesPriceAndApplicabilityVerbatim() {
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of(
                position("熨烫", "布帘", "0.35", true),
                position("熨烫", "纱帘", null, false),
                position("熨烫", "帘头", "0.42", false)));

        List<Map<String, Object>> rows = service().operationPositions(TENANT);

        assertThat(rows).hasSize(3);
        assertThat(rows).extracting(r -> r.get("position")).containsExactly("布帘", "帘头", "纱帘");
        assertThat((BigDecimal) rows.get(0).get("unit_price")).isEqualByComparingTo("0.35");
        assertThat(rows.get(0).get("applicable")).isEqualTo(true);
        // 「明确不做」= applicable false：价可以是 null（不报价），也可以有价（历史价保留）
        assertThat(rows.get(1).get("applicable")).isEqualTo(false);
        assertThat((BigDecimal) rows.get(1).get("unit_price")).isEqualByComparingTo("0.42");
        assertThat(rows.get(2).get("applicable")).isEqualTo(false);
        assertThat(rows.get(2)).containsKey("unit_price");
        assertThat(rows.get(2).get("unit_price")).isNull();
    }

    @Test
    @DisplayName("部位价目：operation = logical_name（**逻辑名**，不是工序库里的旧名 精裁-布）")
    void operationPositionsUsesLogicalNameAsOperationKey() {
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of(
                position("精裁", "布帘", "0.40", true)));

        List<Map<String, Object>> rows = service().operationPositions(TENANT);

        assertThat(rows.get(0).get("operation")).isEqualTo("精裁");
        assertThat(rows.get(0)).doesNotContainKey("logical_name");
        // issue #4622：**10 键**（原 11 键去掉 `variant_name` —— 变体名不再进 web 可见的响应）
        assertThat(rows.get(0)).doesNotContainKey("variant_name");
        assertThat(rows.get(0).keySet())
                .containsExactly("id", "operation", "position", "unit_price", "applicable",
                        "variant_operation_id", "unit", "group", "scope",
                        "is_must_finish");
    }

    // ── 判据 2b：逻辑名 ↔ 变体工序映射（issue #4587 ①，母单 #4586 的「中间那座桥」）──

    @Test
    @DisplayName("部位价目：5 新键 = 该格实际落到工人端那道工序的元数据（复用 variantNameOf，不另写推导）")
    void operationPositionsCarriesVariantMetadata() {
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of(
                position("三边", "布帘", "0.40", true)));
        when(productionOperationMapper.selectList(any())).thenReturn(List.of(
                operation("op-busandbian", "布三边", "车位", "米", "0.40", "position", false)));

        Map<String, Object> row = service().operationPositions(TENANT).get(0);

        assertThat(row.get("variant_operation_id")).isEqualTo("op-busandbian");
        // issue #4622：变体名**不进响应**（红证：改前此处 `row.get("variant_name")` == "布三边"）
        assertThat(row).doesNotContainKey("variant_name");
        assertThat(row.get("unit")).isEqualTo("米");
        assertThat(row.get("group")).isEqualTo("车位");
        assertThat(row.get("scope")).isEqualTo("position");
        assertThat(row.get("is_must_finish")).isEqualTo(false);
    }

    @Test
    @DisplayName("部位价目：帘头回落布帘变体（三边 × 帘头 ⇒ 布帘那道变体，与实例化同一口径）")
    void operationPositionsFallsBackToClothVariantForCurtainHead() {
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of(
                position("三边", "帘头", "0.40", true)));
        when(productionOperationMapper.selectList(any())).thenReturn(List.of(
                operation("op-busandbian", "布三边", "车位", "米", "0.40", "position", false)));

        Map<String, Object> row = service().operationPositions(TENANT).get(0);

        // 「帘头历史上复用布帘变体（V54 帘头×平幔 逐字引用 布三边）」这层映射由**寻址键**证明
        assertThat(row.get("variant_operation_id")).as("帘头回落复用布帘那道变体").isEqualTo("op-busandbian");
        assertThat(row).doesNotContainKey("variant_name");
    }

    @Test
    @DisplayName("部位价目：库里没有该变体 ⇒ 5 键全 null（logo条 × 纱帘 —— 不猜、不拼名字）")
    void operationPositionsLeavesVariantKeysNullWhenNoVariant() {
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of(
                position("logo条", "纱帘", null, false)));
        when(productionOperationMapper.selectList(any())).thenReturn(List.of(
                operation("op-logob", "logo条-布", "车位", "米", "0.60", "position", false)));

        Map<String, Object> row = service().operationPositions(TENANT).get(0);

        assertThat(row).containsKeys("variant_operation_id", "unit", "group",
                "scope", "is_must_finish");
        assertThat(row).doesNotContainKey("variant_name");
        assertThat(row.get("variant_operation_id")).isNull();
        assertThat(row.get("unit")).isNull();
        assertThat(row.get("group")).isNull();
        assertThat(row.get("scope")).isNull();
        assertThat(row.get("is_must_finish")).isNull();
    }

    @Test
    @DisplayName("部位价目：部位无关的工序回落裸逻辑名（外帘打卷 × 布帘 ⇒ 外帘打卷，一格多部位）")
    void operationPositionsFallsBackToBareLogicalName() {
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of(
                position("外帘打卷", "布帘", "1.00", true)));
        when(productionOperationMapper.selectList(any())).thenReturn(List.of(
                operation("op-dajuan", "外帘打卷", "后道", "套", "1.00", "set", false)));

        Map<String, Object> row = service().operationPositions(TENANT).get(0);

        // 部位无关工序的变体名 == 逻辑名；issue #4622 起**名字不进响应**，映射由寻址键证明
        assertThat(row.get("variant_operation_id")).isEqualTo("op-dajuan");
        assertThat(row).doesNotContainKey("variant_name");
        assertThat(row.get("scope")).isEqualTo("set");
    }

    @Test
    @DisplayName("规则：10 键逐字（含 null 的 position/after_operation 保留为 null，不省略键）")
    void routeRulesCarriesTenKeysVerbatim() {
        when(productionRouteRuleMapper.selectList(any())).thenReturn(List.of(
                rule("rr-v70-02", "craft", "韩褶", "布帘", "insert", "上车布", "韩褶", 20),
                rule("rr-v70-05", "craft", "四爪钩", null, "remove", "定型", null, 50)));

        List<Map<String, Object>> rows = service().routeRules(TENANT);

        assertThat(rows).hasSize(2);
        Map<String, Object> insert = rows.get(0);
        assertThat(insert.keySet()).containsExactly("id", "trigger_kind", "trigger_value", "position",
                "action", "operation", "after_operation", "priority", "status", "customer_unit_price");
        assertThat(insert.get("trigger_value")).isEqualTo("韩褶");
        assertThat(insert.get("position")).isEqualTo("布帘");
        assertThat(insert.get("after_operation")).isEqualTo("韩褶");
        assertThat(insert.get("priority")).isEqualTo(20);
        Map<String, Object> remove = rows.get(1);
        assertThat(remove.get("action")).isEqualTo("remove");
        assertThat(remove).containsKey("position");
        assertThat(remove.get("position")).isNull();
        assertThat(remove).containsKey("after_operation");
        assertThat(remove.get("after_operation")).isNull();
    }

    @Test
    @DisplayName("规则：存量**变体名**行（旧前端写进来的 精裁-布）⇒ 读面归一为逻辑名（issue #4643，读时不写库）")
    void routeRulesNormalizesLegacyVariantNames() {
        when(productionRouteRuleMapper.selectList(any())).thenReturn(List.of(
                rule("rr-legacy-1", "craft", "韩褶", "布帘", "insert", "精裁-布", "精裁-布", 20),
                rule("rr-legacy-2", "option", "防翘扣", null, "insert", "测试22", null, 210)));

        List<Map<String, Object>> rows = service().routeRules(TENANT);

        // ① 变体名 ⇒ 逻辑名（写面管不住存量行；读面兜住 ⇒ 规则表 / 删除确认文案不再上屏「精裁-布」）
        Map<String, Object> legacy = rowOf(rows, "韩褶");
        assertThat(legacy.get("operation")).isEqualTo("精裁");
        assertThat(legacy.get("after_operation")).isEqualTo("精裁");
        // ② 未登记的自定义名 / null 锚点：归一后等于自身 / 仍是 null（不凭空造名、不省略键）
        Map<String, Object> custom = rowOf(rows, "防翘扣");
        assertThat(custom.get("operation")).isEqualTo("测试22");
        assertThat(custom).containsKey("after_operation");
        assertThat(custom.get("after_operation")).isNull();
        // ③ 键集一字不动（10 键：归一不新增也不删键）—— 前端口径不受影响
        assertThat(legacy.keySet()).containsExactly("id", "trigger_kind", "trigger_value", "position",
                "action", "operation", "after_operation", "priority", "status", "customer_unit_price");
    }

    @Test
    @DisplayName("单价：option 行原样透出（元/套）；未定价行是 null（**不填 0**）；工艺变体行不取价")
    void routeRulesCarriesCustomerUnitPriceVerbatim() {
        when(productionRouteRuleMapper.selectList(any())).thenReturn(List.of(
                rule("rr-v70-21", "option", "拼2次", null, "insert", "拼缝", null, 210, "12.50"),
                rule("rr-v70-22", "option", "防翘扣", null, "insert", "防翘扣", "三边", 220),
                rule("rr-v70-02", "craft", "韩褶", "布帘", "insert", "上车布", "韩褶", 20, "99.00")));

        List<Map<String, Object>> rows = service().routeRules(TENANT);

        // ⚠️ 输出顺序 = (priority, id) ⇒ 按 trigger_value 取行，**不**按入库序取下标
        Map<String, Object> priced = rowOf(rows, "拼2次");
        Map<String, Object> unpriced = rowOf(rows, "防翘扣");
        Map<String, Object> craft = rowOf(rows, "韩褶");

        // ① 特殊选项 · 有价 ⇒ 原样透出（元/套，BigDecimal 不转 double）
        assertThat(priced.get("customer_unit_price")).isEqualTo(new BigDecimal("12.50"));
        // ② 特殊选项 · 未定价 ⇒ **null**（不是 0 —— 未定价 ≠ 0 元）
        assertThat(unpriced).containsKey("customer_unit_price");
        assertThat(unpriced.get("customer_unit_price")).isNull();
        // ③ 工艺变体：服务层**不做取价/回退** ⇒ 库里写什么就透什么（渲染成「—」是前端口径）
        assertThat(craft.get("customer_unit_price")).isEqualTo(new BigDecimal("99.00"));
    }

    private static Map<String, Object> rowOf(List<Map<String, Object>> rows, String triggerValue) {
        return rows.stream()
                .filter(r -> triggerValue.equals(r.get("trigger_value")))
                .findFirst()
                .orElseThrow(() -> new AssertionError("规则区缺 trigger_value=" + triggerValue + " 的行"));
    }

    // ── 判据 3：行过滤只有 租户/软删/停用（+ 规则表 action）──

    @Test
    @DisplayName("部位价目：只按 租户 + 软删 + 停用 过滤（额外值过滤 ⇒ 矩阵少格）")
    void operationPositionsFiltersOnlyTenantDeletedStatus() {
        when(productionOperationPositionMapper.selectList(any())).thenReturn(new ArrayList<>());

        service().operationPositions(TENANT);

        @SuppressWarnings("unchecked")
        ArgumentCaptor<LambdaQueryWrapper<ProductionOperationPosition>> captor =
                ArgumentCaptor.forClass(LambdaQueryWrapper.class);
        verify(productionOperationPositionMapper).selectList(captor.capture());
        assertThat(captor.getValue().getSqlSegment())
                .contains("tenant_id").contains("deleted").contains("status")
                .doesNotContain("applicable").doesNotContain("unit_price");
    }

    @Test
    @DisplayName("规则：租户 + 软删 + 停用 + action IN ('insert','remove')（系数档不在本端点）")
    void routeRulesFiltersOnlyTenantDeletedStatusAndRouteActions() {
        when(productionRouteRuleMapper.selectList(any())).thenReturn(new ArrayList<>());

        service().routeRules(TENANT);

        @SuppressWarnings("unchecked")
        ArgumentCaptor<LambdaQueryWrapper<ProductionRouteRule>> captor =
                ArgumentCaptor.forClass(LambdaQueryWrapper.class);
        verify(productionRouteRuleMapper).selectList(captor.capture());
        assertThat(captor.getValue().getSqlSegment())
                .contains("tenant_id").contains("deleted").contains("status")
                .contains("action").contains("IN");
        assertThat(captor.getValue().getParamNameValuePairs().values())
                .as("action 过滤值 = insert/remove（不含 factor 计件系数档）")
                .contains("insert", "remove").doesNotContain("factor");
    }

    @Test
    @DisplayName("空库 ⇒ 空数组（不是错误态）：新租户未播种时前端渲染空态")
    void emptyLibraryReturnsEmptyList() {
        when(productionOperationPositionMapper.selectList(any())).thenReturn(null);
        when(productionRouteRuleMapper.selectList(any())).thenReturn(null);

        assertThat(service().operationPositions(TENANT)).isEmpty();
        assertThat(service().routeRules(TENANT)).isEmpty();
    }
}
