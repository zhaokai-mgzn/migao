// case_ids: PG-018
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.entity.ProductionOperation;
import com.migao.admin.entity.ProductionRouting;
import com.migao.admin.mapper.ProductionOperationMapper;
import com.migao.admin.mapper.ProductionRoutingMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 工序库 / 工艺路线只读消费者测试（issue #4116 P0-2）。
 *
 * <p>背景（取证事实）：`production_operations` / `production_routings` 自 V49 建表起
 * **零消费者、零种子** ⇒ 商家无配置入口、库里无数据、§3 工艺路线在 DB 层不可查不可展示。
 * 本包补 V54 种子 + 本只读消费者，让工艺路线可被查询/展示。</p>
 *
 * <p>锁三条：① 读的是**库**（按 tenant_id + deleted=0 + status=active 过滤，租户隔离/停用不可漏）；
 * ② 展示形态按**分组→排序位**稳定（工序目录）与**部位×工艺→有序工序序列**（路线）；
 * ③ 无消费者问不到的别名：路线里每道工序带上库口径单位/单价（缺则该工序在库中不存在 ⇒ null，不猜）。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("ProductionOperationQueryService 工序库/工艺路线只读消费者")
class ProductionOperationQueryServiceTest {

    private static final Long TENANT = 1L;

    @Mock
    private ProductionOperationMapper productionOperationMapper;
    @Mock
    private ProductionRoutingMapper productionRoutingMapper;
    @Mock
    private com.migao.admin.mapper.ProductionOptionRoutingMapper productionOptionRoutingMapper;
    @Mock
    private com.migao.admin.mapper.ProductionOptionFactorMapper productionOptionFactorMapper;
    @Mock
    private com.migao.admin.mapper.ProductionRouteSignalMapper productionRouteSignalMapper;

    private ProductionOperationQueryService service() {
        return new ProductionOperationQueryService(productionOperationMapper, productionRoutingMapper,
                productionOptionRoutingMapper, productionOptionFactorMapper, productionRouteSignalMapper);
    }

    /**
     * 初始化 MyBatis-Plus 的 TableInfo 缓存（同 OrderIdempotencyTest / ProcessingOrderServiceTest 的既有做法）：
     * 断言 `LambdaQueryWrapper.getSqlSegment()` 需要它 —— 否则报
     * 「MybatisPlus can not find lambda cache for this entity」（Standalone 单测无 MapperScan 缓存）。
     */
    @org.junit.jupiter.api.BeforeEach
    void initTableInfoCache() {
        com.baomidou.mybatisplus.core.MybatisConfiguration conf =
                new com.baomidou.mybatisplus.core.MybatisConfiguration();
        org.apache.ibatis.builder.MapperBuilderAssistant assistant =
                new org.apache.ibatis.builder.MapperBuilderAssistant(conf, "");
        com.baomidou.mybatisplus.core.metadata.TableInfoHelper.initTableInfo(assistant, ProductionOperation.class);
        com.baomidou.mybatisplus.core.metadata.TableInfoHelper.initTableInfo(assistant, ProductionRouting.class);
    }

    private ProductionOperation op(String id, String name, String group, String position,
                                   String unit, String price, boolean mustFinish, boolean startMarker,
                                   int sortOrder) {
        return ProductionOperation.builder()
                .id(id).tenantId(TENANT).name(name).groupName(group).position(position).unit(unit)
                .unitPrice(new BigDecimal(price)).isMustFinish(mustFinish).isStartMarker(startMarker)
                .sortOrder(sortOrder).status("active").deleted(0).build();
    }

    private ProductionRouting routing(String id, String curtainType, String craft, List<String> operations) {
        return ProductionRouting.builder()
                .id(id).tenantId(TENANT).curtainType(curtainType).craft(craft)
                .operations(operations).status("active").deleted(0).build();
    }

    @Test
    @DisplayName("工序目录：按分组聚合，组内保留库给的排序（sort_order 升序）")
    void catalogGroupsOperationsByGroup() {
        when(productionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-v54-01", "精裁-布", "裁剪", "布帘", "米", "0.40", false, true, 1),
                op("op-v54-02", "精裁-纱", "裁剪", "纱帘", "米", "0.40", false, true, 2),
                op("op-v54-07", "韩褶-布", "车位", "布帘", "折", "0.40", false, false, 7),
                op("op-v54-25", "外帘装袋", "后道", "外帘", "套", "1.00", true, false, 25)));

        Map<String, Object> result = service().catalog(TENANT);

        assertThat(result.get("total")).isEqualTo(4);
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> groups = (List<Map<String, Object>>) result.get("groups");
        assertThat(groups).extracting(g -> g.get("group")).containsExactly("裁剪", "车位", "后道");

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> tailoring = (List<Map<String, Object>>) groups.get(0).get("operations");
        assertThat(tailoring).extracting(o -> o.get("name")).containsExactly("精裁-布", "精裁-纱");
        assertThat(tailoring.get(0).get("unit")).isEqualTo("米");
        assertThat((BigDecimal) tailoring.get(0).get("unit_price")).isEqualByComparingTo("0.40");
        assertThat(tailoring.get(0).get("is_start_marker")).isEqualTo(true);
        assertThat(tailoring.get(0).get("is_must_finish")).isEqualTo(false);

        // 组内排序/停用/软删/租户隔离都压在 SQL 条件里（不是内存过滤）
        ArgumentCaptor<LambdaQueryWrapper<ProductionOperation>> captor =
                ArgumentCaptor.forClass(LambdaQueryWrapper.class);
        verify(productionOperationMapper).selectList(captor.capture());
        assertThat(captor.getValue().getSqlSegment())
                .as("只读消费者必须按 tenant_id + deleted=0 + status=active 过滤")
                .contains("tenant_id").contains("deleted").contains("status");
    }

    @Test
    @DisplayName("工序目录为空（库未种子/全停用）⇒ total=0 且 groups 空数组，不是错误态")
    void catalogWithoutSeedReturnsEmptyGroups() {
        when(productionOperationMapper.selectList(any())).thenReturn(List.of());

        Map<String, Object> result = service().catalog(TENANT);

        assertThat(result.get("total")).isEqualTo(0);
        assertThat((List<?>) result.get("groups")).isEmpty();
    }

    @Test
    @DisplayName("工艺路线：部位×工艺 → 有序工序序列，序号从 1 起且与 JSONB 顺序一致")
    void routingsKeepOrderedSequence() {
        when(productionRoutingMapper.selectList(any())).thenReturn(List.of(
                routing("rt-v54-01", "布帘", "韩褶", List.of("精裁-布", "布三边", "韩褶-布")),
                routing("rt-v54-05", "纱帘", "韩褶", List.of("精裁-纱", "纱三边", "韩褶-纱"))));
        when(productionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-v54-01", "精裁-布", "裁剪", "布帘", "米", "0.40", false, true, 1),
                op("op-v54-05", "布三边", "车位", null, "米", "0.40", false, false, 5),
                op("op-v54-07", "韩褶-布", "车位", "布帘", "折", "0.40", false, false, 7),
                op("op-v54-02", "精裁-纱", "裁剪", "纱帘", "米", "0.40", false, true, 2),
                op("op-v54-06", "纱三边", "车位", null, "米", "0.40", false, false, 6),
                op("op-v54-08", "韩褶-纱", "车位", "纱帘", "折", "0.40", false, false, 8)));

        Map<String, Object> result = service().routings(TENANT);

        assertThat(result.get("total")).isEqualTo(2);
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> items = (List<Map<String, Object>>) result.get("routings");
        assertThat(items.get(0).get("curtain_type")).isEqualTo("布帘");
        assertThat(items.get(0).get("craft")).isEqualTo("韩褶");
        assertThat(items.get(0).get("operation_count")).isEqualTo(3);

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> steps = (List<Map<String, Object>>) items.get(0).get("operations");
        // 顺序 = 路线数组顺序（路线是**有序**序列，排序不是展示细节而是语义）
        assertThat(steps).extracting(s -> s.get("operation")).containsExactly("精裁-布", "布三边", "韩褶-布");
        assertThat(steps).extracting(s -> s.get("seq")).containsExactly(1, 2, 3);
        // 每道工序带库口径单位/单价（展示 + 校验用）
        assertThat(steps.get(2).get("unit")).isEqualTo("折");
        assertThat((BigDecimal) steps.get(2).get("unit_price")).isEqualByComparingTo("0.40");
        assertThat(steps.get(0).get("is_start_marker")).isEqualTo(true);
    }

    @Test
    @DisplayName("路线引用库里不存在的工序 ⇒ 该步的库口径字段为 null（不猜、不用默认值顶替）")
    void routingStepWithoutCatalogEntryIsNull() {
        when(productionRoutingMapper.selectList(any())).thenReturn(List.of(
                routing("rt-x", "布帘", "韩褶", List.of("精裁-布", "幽灵工序"))));
        when(productionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-v54-01", "精裁-布", "裁剪", "布帘", "米", "0.40", false, true, 1)));

        Map<String, Object> result = service().routings(TENANT);

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> items = (List<Map<String, Object>>) result.get("routings");
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> steps = (List<Map<String, Object>>) items.get(0).get("operations");
        assertThat(steps.get(1).get("operation")).isEqualTo("幽灵工序");
        assertThat(steps.get(1).get("unit")).isNull();
        assertThat(steps.get(1).get("unit_price")).isNull();
        assertThat(steps.get(1).get("is_must_finish")).isEqualTo(false);
    }

    @Test
    @DisplayName("JSONB 反序列化非 List 形态（脏数据）⇒ 序列为空而不是抛错（展示层不得被单条脏数据打挂）")
    void routingWithMalformedOperationsDoesNotThrow() {
        when(productionRoutingMapper.selectList(any())).thenReturn(List.of(
                routing("rt-bad", "布帘", "韩褶", null)));
        when(productionOperationMapper.selectList(any())).thenReturn(List.of());

        Map<String, Object> result = service().routings(TENANT);

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> items = (List<Map<String, Object>>) result.get("routings");
        assertThat(items.get(0).get("operation_count")).isEqualTo(0);
        assertThat((List<?>) items.get(0).get("operations")).isEmpty();
    }

    @Test
    @DisplayName("只读边界：两个方法都只走 SELECT（无 insert/update/delete 调用）")
    void queryServiceIsReadOnly() {
        when(productionOperationMapper.selectList(any())).thenReturn(List.of());
        when(productionRoutingMapper.selectList(any())).thenReturn(List.of());

        service().catalog(TENANT);
        service().routings(TENANT);

        verify(productionOperationMapper, org.mockito.Mockito.never()).insert(any(ProductionOperation.class));
        verify(productionOperationMapper, org.mockito.Mockito.never()).deleteById(any(String.class));
        verify(productionRoutingMapper, org.mockito.Mockito.never()).insert(any(ProductionRouting.class));
        verify(productionRoutingMapper, org.mockito.Mockito.never()).deleteById(any(String.class));
    }

    // ── findRouting / routingKeys：实例化的工序来源（issue #4116 切库）────────

    @Test
    @DisplayName("findRouting 命中：seq 从 1 起、顺序 = 路线数组顺序，单位/单价/必完标记逐字取库")
    void findRoutingResolvesStepsVerbatimFromLibrary() {
        when(productionRoutingMapper.selectList(any())).thenReturn(List.of(
                routing("rt-v54-01", "布帘", "韩褶", List.of("精裁-布", "韩褶-布", "外帘装袋"))));
        when(productionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-v54-01", "精裁-布", "裁剪", "布帘", "米", "0.40", false, true, 1),
                op("op-v54-07", "韩褶-布", "车位", "布帘", "折", "0.40", false, false, 7),
                op("op-v54-25", "外帘装袋", "后道", "外帘", "套", "1.00", true, false, 25)));

        Map<String, Object> route = service().findRouting(TENANT, "布帘", "韩褶");

        assertThat(route).isNotNull();
        assertThat(route.get("curtain_type")).isEqualTo("布帘");
        assertThat(route.get("craft")).isEqualTo("韩褶");
        assertThat(route.get("operation_count")).isEqualTo(3);
        assertThat((List<?>) route.get("missing_operations")).isEmpty();

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> steps = (List<Map<String, Object>>) route.get("operations");
        assertThat(steps).extracting(s -> s.get("operation")).containsExactly("精裁-布", "韩褶-布", "外帘装袋");
        assertThat(steps).extracting(s -> s.get("seq")).containsExactly(1, 2, 3);
        assertThat(steps.get(1).get("unit")).isEqualTo("折");
        assertThat((BigDecimal) steps.get(1).get("unit_price")).isEqualByComparingTo("0.40");
        assertThat(steps.get(2).get("is_must_finish")).isEqualTo(true);
        assertThat(steps.get(0).get("is_start_marker")).isEqualTo(true);
    }

    @Test
    @DisplayName("findRouting 未命中：返回 null（兜底到默认路线是调用方的策略，不是库的语义）")
    void findRoutingReturnsNullWhenAbsent() {
        when(productionRoutingMapper.selectList(any())).thenReturn(List.of(
                routing("rt-v54-05", "纱帘", "韩褶", List.of("精裁-纱"))));

        assertThat(service().findRouting(TENANT, "帘头", "平幔")).isNull();
    }

    @Test
    @DisplayName("findRouting 缺工序：不静默补默认值，而是指名登记进 missing_operations（由调用方 fail-closed）")
    void findRoutingReportsMissingOperationsInsteadOfGuessing() {
        when(productionRoutingMapper.selectList(any())).thenReturn(List.of(
                routing("rt-x", "布帘", "韩褶", List.of("精裁-布", "幽灵工序", "外帘发货"))));
        when(productionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-v54-01", "精裁-布", "裁剪", "布帘", "米", "0.40", false, true, 1),
                op("op-v54-27", "外帘发货", "后道", "外帘", "套", "1.00", false, false, 27)));

        Map<String, Object> route = service().findRouting(TENANT, "布帘", "韩褶");

        assertThat(route).isNotNull();
        assertThat(String.valueOf(route.get("missing_operations"))).isEqualTo("[幽灵工序]");
        // 序号仍按路线位次（缺工序不跳号 —— 跳号会让实例与路线错位）
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> steps = (List<Map<String, Object>>) route.get("operations");
        assertThat(steps).extracting(s -> s.get("seq")).containsExactly(1, 2, 3);
        assertThat(steps.get(1).get("unit")).isNull();
        assertThat(steps.get(2).get("unit")).isEqualTo("套");
    }

    @Test
    @DisplayName("findRouting 空路线（脏数据 / 运营清空）：operations 为空且不抛（由调用方 fail-closed）")
    void findRoutingWithEmptyRouteIsNotAnError() {
        when(productionRoutingMapper.selectList(any())).thenReturn(List.of(
                routing("rt-empty", "布帘", "韩褶", List.of())));

        Map<String, Object> route = service().findRouting(TENANT, "布帘", "韩褶");

        assertThat(route).isNotNull();
        assertThat(route.get("operation_count")).isEqualTo(0);
        assertThat((List<?>) route.get("missing_operations")).isEmpty();
    }

    @Test
    @DisplayName("routingKeys：列出库中现有路线键（部位→工艺序），失败提示据此做到可行动")
    void routingKeysListAvailableRoutes() {
        when(productionRoutingMapper.selectList(any())).thenReturn(List.of(
                routing("rt-v54-01", "布帘", "韩褶", List.of("精裁-布")),
                routing("rt-v54-02", "布帘", "打孔", List.of("精裁-布")),
                routing("rt-v54-05", "纱帘", "韩褶", List.of("精裁-纱"))));

        assertThat(service().routingKeys(TENANT)).containsExactly("布帘×韩褶", "布帘×打孔", "纱帘×韩褶");
    }

    @Test
    @DisplayName("只读边界：findRouting / routingKeys 同样只走 SELECT")
    void findRoutingIsReadOnly() {
        when(productionRoutingMapper.selectList(any())).thenReturn(List.of());
        when(productionOperationMapper.selectList(any())).thenReturn(List.of());

        service().findRouting(TENANT, "布帘", "韩褶");
        service().routingKeys(TENANT);

        verify(productionOperationMapper, org.mockito.Mockito.never()).insert(any(ProductionOperation.class));
        verify(productionOperationMapper, org.mockito.Mockito.never()).updateById(any(ProductionOperation.class));
        verify(productionRoutingMapper, org.mockito.Mockito.never()).insert(any(ProductionRouting.class));
        verify(productionRoutingMapper, org.mockito.Mockito.never()).updateById(any(ProductionRouting.class));
    }
}