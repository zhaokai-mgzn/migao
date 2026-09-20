// case_ids: PG-018, PG-035, PG-039, PG-054
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
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

/**
 * 工艺项**两层分区 + 交付环节一列价**（issue #4676 = 设计
 * {@code docs/design/public-operations-and-craft-ui.md} §4.2 / §4.5 方案 A）。
 *
 * <p>被测 = {@link ProductionRoutingReadService#operationLayers(Long)}。判据五条，各自**注入式可红**：</p>
 * <ol>
 *   <li><b>分区判据是既有 {@code scope}</b>（{@code 'set'} ⇒ delivery；其余 ⇒ operations，含 {@code null}
 *       的安全方向）—— 换成「有没有矩阵格」即红（#4674 形态：交付工序整行消失）；</li>
 *   <li><b>一列价 = 显式聚合规则</b>：全同 ⇒ {@code priced}；有 {@code NULL} ⇒ {@code unpriced}
 *       （<b>未定价 ≠ ¥0.00</b>，**不回落工序库行价** —— 设计 F4：工序库行价是 {@code NOT NULL DEFAULT 0}）；</li>
 *   <li><b>各部位不同价 ⇒ 不静默取第一个</b>（{@code multiple_prices} + {@code different_price_count}，
 *       设计 B7）；</li>
 *   <li><b>交付行的存活与矩阵格数无关</b>（只剩一格仍是 delivery 行；**零格也有行**，价态
 *       {@code no_applicable_position}）—— 设计 F1 红线：一列价**不得**用「删格」实现
 *       （删格 ⇒ 该部位单里静默消失 ⇒ 少一道活、少一笔计件钱）。🔴 **行来源 = 工序库的
 *       {@code scope='set'} 行，不是矩阵行**（issue #4729 修正 = 独立验收 #4677 的 P1-2：
 *       改前遍历 {@code operationPositions()} 只读矩阵表 ⇒ 零格工序在 delivery 段一行都没有）；</li>
 *   <li><b>键集/键序冻结</b>：{@code operations} 段与 {@code GET /operation-positions} 同形（10 键），
 *       {@code delivery} 段 9 键。</li>
 * </ol>
 *
 * <p>值层面的「分区判据确实来自库里带出的 {@code scope}」由
 * {@code tests/unit_ci_workflows/test_routing_read_endpoints.py} 静态钉住；本类判的是**服务层语义**。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("工艺项两层分区 + 交付环节一列价（issue #4676）")
class ProductionOperationLayersTest {

    private static final Long TENANT = 1L;

    @Mock
    private ProductionOperationPositionMapper productionOperationPositionMapper;
    @Mock
    private ProductionRouteRuleMapper productionRouteRuleMapper;
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

    private ProductionOperation operation(String id, String name, String group, String unit,
                                          String scope, boolean mustFinish) {
        return ProductionOperation.builder()
                .id(id).tenantId(TENANT).name(name).groupName(group).unit(unit)
                .unitPrice(BigDecimal.ZERO).scope(scope).isMustFinish(mustFinish)
                .isStartMarker(false).sortOrder(1).status("active").deleted(0).build();
    }

    /** 交付工序的工序库行（`scope='set'` = 一列价那一层的**唯一**判据来源）。 */
    private void stubPackingCatalog() {
        when(productionOperationMapper.selectList(any())).thenReturn(List.of(
                operation("op-dabao", "打包", "后道", "套", "set", false),
                operation("op-dajuan", "外帘打卷", "后道", "套", "set", false),
                operation("op-zhuangdai", "外帘装袋", "后道", "套", "set", false)));
    }

    private static Map<String, Object> deliveryRow(Map<String, Object> layers, String operation) {
        return ((List<Map<String, Object>>) layers.get("delivery")).stream()
                .filter(r -> operation.equals(r.get("operation"))).findFirst().orElseThrow();
    }

    // ── 判据 1：分区判据 = 既有 scope ──

    @Test
    @DisplayName("分区：scope='set' ⇒ delivery（一列价）；scope 缺省/null ⇒ operations（安全方向）")
    void layersPartitionByExistingScope() {
        stubPackingCatalog();
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of(
                position("打包", "布帘", null, true),
                position("打包", "纱帘", null, true),
                position("外帘打卷", "布帘", "1.00", true),
                // 变体查不到 ⇒ scope=null ⇒ 必须落 `operations`（缺省按 position = 安全方向）
                position("裁剪", "布料", null, true)));

        Map<String, Object> layers = service().operationLayers(TENANT);

        assertThat(layers.keySet()).containsExactly("operations", "delivery");
        // 交付段 = 工序库里 `scope='set'` 的**三道**（含**零矩阵格**的 `外帘装袋` —— issue #4729），
        // 顺序 = 归一后的逻辑工序名（与矩阵行键同一把尺；中文按码位比较，与环境 collation 无关）：
        // `外帘打卷`（卷 U+5377）< `外帘装袋`（袋 U+888B）< `打包`。
        assertThat((List<Map<String, Object>>) layers.get("delivery"))
                .extracting(r -> r.get("operation")).containsExactly("外帘打卷", "外帘装袋", "打包");
        assertThat((List<Map<String, Object>>) layers.get("operations"))
                .extracting(r -> r.get("operation") + "/" + r.get("position"))
                .containsExactly("裁剪/布料");
    }

    // ── 判据 2/3：一列价的显式规则 ──

    @Test
    @DisplayName("一列价：各部位同价 ⇒ priced + 该价；键集 9 个且 unit/必完取自工序库")
    void deliveryPriceIsOneColumnWhenAllPositionsAgree() {
        stubPackingCatalog();
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of(
                position("外帘打卷", "布帘", "1.00", true),
                position("外帘打卷", "纱帘", "1.00", true),
                position("外帘打卷", "帘头", "1.00", true)));

        Map<String, Object> row = deliveryRow(service().operationLayers(TENANT), "外帘打卷");

        assertThat(row.keySet()).containsExactly("operation", "scope", "unit", "group",
                "is_must_finish", "price", "price_state", "different_price_count",
                "applicable_positions");
        assertThat(row.get("scope")).isEqualTo("set");
        assertThat(row.get("price_state")).isEqualTo("priced");
        assertThat(row.get("price")).isEqualTo(new BigDecimal("1.00"));
        assertThat(row.get("different_price_count")).isEqualTo(0);
        assertThat(row.get("unit")).isEqualTo("套");
        assertThat(row.get("group")).isEqualTo("后道");
        assertThat(row.get("applicable_positions")).isEqualTo(List.of("布帘", "帘头", "纱帘"));
    }

    @Test
    @DisplayName("🔴 一列价：任一适用格未定价 ⇒ unpriced + price=null（**未定价 ≠ ¥0.00**，不回落工序库行价）")
    void deliveryPriceIsUnpricedWhenAnyApplicableCellHasNoPrice() {
        stubPackingCatalog();
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of(
                position("打包", "布帘", null, true),
                position("打包", "纱帘", null, true),
                position("打包", "帘头", null, true),
                position("打包", "布料", null, true)));

        Map<String, Object> row = deliveryRow(service().operationLayers(TENANT), "打包");

        assertThat(row.get("price_state")).isEqualTo("unpriced");
        // 设计 F4：工序库行价是 `NOT NULL DEFAULT 0` ⇒ 一旦「回落工序库价」，
        // 这里会变成 0（= 工人白干）。本断言就是那条红线的机械形态。
        assertThat(row.get("price")).isNull();
        assertThat(row.get("different_price_count")).isEqualTo(0);
    }

    @Test
    @DisplayName("一列价：各部位不同价 ⇒ multiple_prices + 计数（**不静默取第一个**，设计 B7）")
    void deliveryPriceIsNotSilentlyTheFirstWhenPositionsDiffer() {
        stubPackingCatalog();
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of(
                position("外帘打卷", "布帘", "1.00", true),
                position("外帘打卷", "纱帘", "1.50", true),
                position("外帘打卷", "帘头", "1.50", true)));

        Map<String, Object> row = deliveryRow(service().operationLayers(TENANT), "外帘打卷");

        assertThat(row.get("price_state")).isEqualTo("multiple_prices");
        assertThat(row.get("price")).isNull();
        assertThat(row.get("different_price_count")).isEqualTo(2);
    }

    @Test
    @DisplayName("一列价：`applicable=FALSE` 的格不参与取值（明确不做 ≠ 未定价）")
    void deliveryPriceIgnoresNotApplicableCells() {
        stubPackingCatalog();
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of(
                position("外帘打卷", "布帘", "1.00", true),
                position("外帘打卷", "纱帘", "9.99", false),
                position("外帘打卷", "布料", null, false)));

        Map<String, Object> row = deliveryRow(service().operationLayers(TENANT), "外帘打卷");

        assertThat(row.get("price_state")).isEqualTo("priced");
        assertThat(row.get("price")).isEqualTo(new BigDecimal("1.00"));
        assertThat(row.get("applicable_positions")).isEqualTo(List.of("布帘"));
    }

    // ── 判据 4：交付行的存活与矩阵格数无关（F1 红线）──

    @Test
    @DisplayName("🔴 F1：交付工序只剩一格（另一道**一格都没有**）时**仍有 delivery 行** —— 一列价绝不用「删格」实现")
    void deliveryRowSurvivesWhenOnlyOnePositionHasACell() {
        stubPackingCatalog();
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of(
                position("打包", "布帘", null, true),
                position("外帘装袋", "布帘", null, false)));

        Map<String, Object> layers = service().operationLayers(TENANT);

        assertThat((List<Map<String, Object>>) layers.get("delivery"))
                .extracting(r -> r.get("operation")).containsExactly("外帘打卷", "外帘装袋", "打包");
        // 零个适用格也**不消失**（只是 `no_applicable_position`）—— 换成「按格分区」这里会少一行。
        Map<String, Object> empty = deliveryRow(layers, "外帘装袋");
        assertThat(empty.get("price_state")).isEqualTo("no_applicable_position");
        assertThat(empty.get("applicable_positions")).isEqualTo(List.of());
    }

    // ── 判据 4′：🔴 **真·零矩阵格**（issue #4729 = 独立验收 #4677 的 P1-2）──

    @Test
    @DisplayName("🔴 零矩阵格：`scope='set'` 的工序**一个格都没有** ⇒ 仍有 delivery 行 + "
            + "`no_applicable_position`（**行来源 = 工序库，不是矩阵行**）")
    void deliveryRowExistsWhenOperationHasNoMatrixCellsAtAll() {
        stubPackingCatalog();
        // 矩阵里**只有**部位级工序的格：三道套级工序（打包 / 外帘打卷 / 外帘装袋）**一格都没有**。
        // 改前（行来源 = `operationPositions()` = 只读矩阵表）⇒ delivery 段**一行都没有**（红证）。
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of(
                position("裁剪", "布料", "7.00", true)));

        Map<String, Object> layers = service().operationLayers(TENANT);

        // 零格工序**照样各有一行**（判据是工序库行的 `scope`，不是「有没有格」）
        assertThat((List<Map<String, Object>>) layers.get("delivery"))
                .extracting(r -> r.get("operation")).containsExactly("外帘打卷", "外帘装袋", "打包");
        // 零格 ⇒ 4 态之一 `no_applicable_position`（**语义一字不改**：不假装 ¥0.00、不假装未定价）
        for (String operation : List.of("打包", "外帘打卷", "外帘装袋")) {
            Map<String, Object> row = deliveryRow(layers, operation);
            assertThat(row.get("price_state")).isEqualTo("no_applicable_position");
            assertThat(row.get("price")).isNull();
            assertThat(row.get("different_price_count")).isEqualTo(0);
            assertThat(row.get("applicable_positions")).isEqualTo(List.of());
            // 行尾元数据回落**工序库行**（否则零格行的单位 / 分组全空 = 界面上多一列 `—`）
            assertThat(row.get("unit")).isEqualTo("套");
            assertThat(row.get("group")).isEqualTo("后道");
            assertThat(row.get("scope")).isEqualTo("set");
        }
        // 零格工序**不得**同时出现在 `operations` 段（两段并集 = 全集，不重不漏）
        assertThat((List<Map<String, Object>>) layers.get("operations"))
                .extracting(r -> r.get("operation")).containsExactly("裁剪");
    }

    @Test
    @DisplayName("套级工序的格仍在 ⇒ 该格**参与**一列价聚合；非套级格落 `operations` 段（两段不重不漏）")
    void deliveryCellsStillFeedTheAggregate() {
        stubPackingCatalog();
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of(
                position("裁剪", "布料", "7.00", true),
                position("打包", "布帘", "1.50", true)));

        Map<String, Object> layers = service().operationLayers(TENANT);

        assertThat((List<Map<String, Object>>) layers.get("operations"))
                .extracting(r -> r.get("operation")).containsExactly("裁剪");
        Map<String, Object> packing = deliveryRow(layers, "打包");
        assertThat(packing.get("price_state")).isEqualTo("priced");
        assertThat(packing.get("price")).isEqualTo(new BigDecimal("1.50"));
        assertThat(packing.get("applicable_positions")).isEqualTo(List.of("布帘"));
    }

    @Test
    @DisplayName("交付段顺序 = **归一后的逻辑工序名**（不依赖 DB collation / 与矩阵行键同一把尺）")
    void deliverySectionIsOrderedByLogicalOperationName() {
        stubPackingCatalog();
        // 格故意给**乱序**（矩阵读面自己会排序）⇒ 交付段顺序只由工序名定
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of(
                position("打包", "纱帘", "1.50", true),
                position("打包", "布帘", "1.50", true),
                position("外帘打卷", "布帘", "1.00", true)));

        Map<String, Object> layers = service().operationLayers(TENANT);

        assertThat((List<Map<String, Object>>) layers.get("delivery"))
                .extracting(r -> r.get("operation")).containsExactly("外帘打卷", "外帘装袋", "打包");
        // 行内 `applicable_positions` 仍是矩阵读面的 `(operation, position)` 稳定序
        assertThat(deliveryRow(layers, "打包").get("applicable_positions"))
                .isEqualTo(List.of("布帘", "纱帘"));
    }

    // ── 判据 5：与既有端点同形 ──

    @Test
    @DisplayName("operations 段与 GET /operation-positions **同形**（同一份 10 键，不另写整形点）")
    void operationsSectionIsShapeIdenticalToOperationPositions() {
        stubPackingCatalog();
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of(
                position("打包", "布帘", null, true),
                position("裁剪", "布料", null, true)));

        ProductionRoutingReadService service = service();
        Map<String, Object> layers = service.operationLayers(TENANT);

        // ⚠️ 期望值按**交付工序名集合**（`scope='set'` 的工序库行）过滤 —— **不是**按格的 `scope`：
        // 格上查不到变体时 `scope=null`（安全方向 ⇒ 落工序层），两把尺在这里必须一致。
        List<Map<String, Object>> expected = service.operationPositions(TENANT).stream()
                .filter(r -> !List.of("打包", "外帘打卷", "外帘装袋").contains(r.get("operation"))).toList();
        assertThat(expected).hasSize(1);
        assertThat((List<Map<String, Object>>) layers.get("operations")).isEqualTo(expected);
    }
}
