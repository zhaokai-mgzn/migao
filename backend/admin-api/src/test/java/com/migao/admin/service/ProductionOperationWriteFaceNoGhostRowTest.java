// case_ids: PG-020
package com.migao.admin.service;

import com.migao.admin.entity.ProductionOperation;
import com.migao.admin.entity.ProductionOperationPosition;
import com.migao.admin.entity.ProductionOperationPriceVersion;
import com.migao.admin.mapper.ProductionCraftMapper;
import com.migao.admin.mapper.ProductionOperationMapper;
import com.migao.admin.mapper.ProductionOperationPositionMapper;
import com.migao.admin.mapper.ProductionOperationPriceVersionMapper;
import com.migao.admin.mapper.ProductionRouteRuleMapper;
import com.migao.admin.mapper.ProductionRouteSignalMapper;
import com.migao.admin.mapper.ProductionRouteTemplateMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 工序设置**写面**（{@code PUT /api/admin/production/operations/{id}}）**不得凭空新建价目行**
 * （issue #6126，P1）。
 *
 * <p><b>病根</b>：{@link ProductionOperationCommandService#update} 在 body **不含</b> {@code positions} 时
 * 也按「取价来源列」（{@code 布帘}）兜底**新建**一行 {@code production_operation_positions}
 * —— 于是连 body 为 **`{}`**（键数 0）的一次写面调用、或只改 {@code scope} 的一次保存，
 * 都会在这个工序的价目行集合里**凭空多出一行 {@code position=布帘}**（只增不减：
 * 软删也只软删，孤儿行累积）。实测（租户 20）：只有 {@code 通用} 一行的工序 8 道；
 * 同一会话内 {@code 打包} 的软删 {@code 布帘} 孤儿行 6 → 9 → 13。</p>
 *
 * <p><b>与 issue #6102 的分工</b>：{@code #6102} 修的是「**新行的价取错**」⇒ 有效价被静默改写
 * （判据见 {@link ProductionOperationSavePriceDriftTest}）；本单修的是「**新行本就不该被创建**」
 * —— 两道判据各自成立、互补不重叠。</p>
 *
 * <p><b>本类钉住的类级不变量（判据 4）</b>：任何工序设置写面调用之后，该工序的
 * <b>价目行集合</b>与<b>有效价</b>都必须逐字不变 —— <b>除非</b>该次写面**显式**带
 * {@code positions}（建缺失行）或 {@code unit_price}（改价）。
 * 参数化覆盖**多道工序**（不是只钉 {@code 打包}），且「零变化」用三条独立读数合取：
 * ① 无任何矩阵行 insert/updateById；② 该工序读面
 * （{@link ProductionOperationQueryService#collapseToLogical}）折出的行逐字段相同；
 * ③ 有效价逐字相同。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("工序写面不凭空建价目行（issue #6126）：价目行集合与有效价逐字不变")
class ProductionOperationWriteFaceNoGhostRowTest {

    private static final Long TENANT = 1L;
    private static final String OP_ID = "op-6126";
    /** 工序库行价（与既有价目行价刻意不同 ⇒ 若仍兜底建行，多出来的那一行必被看见）。 */
    private static final String LIBRARY_PRICE = "0.60";
    /** 生产环境实测的商家改价（形态 B）。 */
    private static final String MERCHANT_PRICE = "0.77";
    private static final String SOURCE_POSITION = ProductionOperationQueryService.COLLAPSE_PRICE_SOURCE_POSITION;

    @Mock
    private ProductionOperationMapper productionOperationMapper;
    @Mock
    private ProductionOperationPriceVersionMapper priceVersionMapper;
    @Mock
    private ProductionOperationPositionMapper productionOperationPositionMapper;
    @Mock
    private ProductionRouteTemplateMapper productionRouteTemplateMapper;
    @Mock
    private ProductionRouteRuleMapper productionRouteRuleMapper;
    @Mock
    private ProductionCraftMapper productionCraftMapper;
    @Mock
    private ProductionRouteSignalMapper productionRouteSignalMapper;

    /** 读面用**真实对象**（只 mock Mapper）—— 判据要的「有效价」是读面同一份收敛折出来的。 */
    private ProductionOperationCommandService service() {
        return new ProductionOperationCommandService(
                productionOperationMapper, priceVersionMapper, productionOperationPositionMapper,
                new ProductionOperationQueryService(productionOperationMapper, productionRouteTemplateMapper,
                        productionRouteRuleMapper, productionOperationPositionMapper,
                        productionCraftMapper, productionRouteSignalMapper));
    }

    private ProductionOperation operation(String name) {
        return ProductionOperation.builder()
                .id(OP_ID).tenantId(TENANT).name(name).groupName("车位").position("布帘")
                .unit("米").unitPrice(new BigDecimal(LIBRARY_PRICE))
                .isMustFinish(false).isStartMarker(false).sortOrder(1).status("active").deleted(0)
                .build();
    }

    private ProductionOperationPosition matrixRow(String logicalName, String position, String price) {
        return ProductionOperationPosition.builder()
                .id("opp-" + logicalName + "-" + position).tenantId(TENANT)
                .logicalName(logicalName).position(position)
                .unitPrice(price == null ? null : new BigDecimal(price))
                .applicable(true).status("active").deleted(0)
                .build();
    }

    /**
     * 该逻辑工序「**只有 {@code 通用} 一行**」—— 复现步骤 1 的必须显式构造的前置
     * （{@code attachPositions} 只补**不存在**的那一列；矩阵里已有 {@code 布帘} 行 ⇒ 幂等跳过 ⇒ 判据**假绿**）。
     * 另混入另一道工序（{@code 配料}）的行，证明读数按逻辑工序隔离、不是「表里第一行」。
     */
    private List<ProductionOperationPosition> onlyGenericRowMatrix(String logicalName, String price) {
        return List.of(matrixRow(logicalName, "通用", price), matrixRow("配料", "布料", "0.20"));
    }

    /** 读面折出的该逻辑工序那一行（逐字段留证用）。 */
    private List<ProductionOperationPosition> collapsed(String logicalName,
                                                        List<ProductionOperationPosition> rows) {
        return ProductionOperationQueryService.collapseToLogical(rows).stream()
                .filter(row -> logicalName.equals(row.getLogicalName()))
                .collect(Collectors.toList());
    }

    private String effectivePrice(String logicalName, List<ProductionOperationPosition> rows) {
        List<ProductionOperationPosition> collapsed = collapsed(logicalName, rows);
        return collapsed.isEmpty() || collapsed.get(0).getUnitPrice() == null
                ? "NULL(未定价)" : collapsed.get(0).getUnitPrice().toPlainString();
    }

    /** 判据 1/2 的调用形态：body 的键数 0 或只含与价目无关的键（**可多个**，参数化）。 */
    static Stream<Arguments> priceIrrelevantBodies() {
        return Stream.of(
                Arguments.of("{}（键数 0）", Map.of()),
                Arguments.of("{scope}", Map.of("scope", "set")),
                Arguments.of("{scope,group_name,unit,sort_order,is_start_marker,status}",
                        Map.of("scope", "set", "group_name", "车位", "unit", "米",
                                "sort_order", 3, "is_start_marker", false, "status", "active")));
    }

    /** 类级固化（判据 4）：**多道工序**，含未定价与已改价两类既有行。 */
    static Stream<Arguments> operations() {
        return Stream.of(
                Arguments.of("打包", (String) null),
                Arguments.of("韩褶-布", MERCHANT_PRICE),
                Arguments.of("外帘装袋", (String) null));
    }

    // ══════════ 判据 1（最锋利）+ 判据 2：body 不含价目键 ⇒ 价目行集合 / 有效价零变化 ══════════

    @ParameterizedTest(name = "「{0}」+ body {1} ⇒ 价目行集合与有效价逐字不变")
    @MethodSource("operationsWithIrrelevantBodies")
    @DisplayName("判据 1+2+4：body 不含 positions/unit_price（含空 `{}`）⇒ 该工序价目行集合与有效价零变化")
    void writeFaceWithoutPriceKeysLeavesMatrixAndEffectivePriceUntouched(String operationName,
                                                                        String bodyLabel,
                                                                        Map<String, Object> body) {
        String logicalName = ProductionOperationQueryService.logicalOperationName(operationName);
        List<ProductionOperationPosition> before = onlyGenericRowMatrix(logicalName, null);
        when(productionOperationMapper.selectById(OP_ID)).thenReturn(operation(operationName));
        when(productionOperationMapper.updateById(any(ProductionOperation.class))).thenReturn(1);
        when(productionOperationPositionMapper.selectList(any())).thenReturn(before);
        List<ProductionOperationPosition> collapsedBefore = collapsed(logicalName, before);
        String priceBefore = effectivePrice(logicalName, before);

        Map<String, Object> view = service().update(OP_ID, body, TENANT);

        // ① 价目行集合零变化：整条路径没有任何矩阵行写入（凭空新建 = insert；覆盖既有价 = updateById）
        verify(productionOperationPositionMapper, never()).insert(any(ProductionOperationPosition.class));
        verify(productionOperationPositionMapper, never()).updateById(any(ProductionOperationPosition.class));
        // ② 读面折出的行逐字段相同（含 deleted 标记；不是「只看价」）
        assertThat(collapsed(logicalName, before))
                .as("写面后该工序读面折出的价目行必须逐字段不变（凭空多一行 = issue #6126）")
                .isEqualTo(collapsedBefore);
        assertThat(collapsedBefore)
                .as("夹具前置必须成立：该工序**只有 `通用` 一行**（否则幂等跳过会假绿）")
                .hasSize(1);
        assertThat(collapsedBefore.get(0).getPosition()).isEqualTo("通用");
        assertThat(collapsedBefore.get(0).getDeleted()).isZero();
        // ③ 有效价逐字相同（读面 / 派工实例真正消费的那个值）
        assertThat(effectivePrice(logicalName, before))
                .as("保存一次设置后该工序有效价必须逐字不变（改前：凭空冒出 `%s` 行 ⇒ 未定价被盖成 %s）",
                        SOURCE_POSITION, LIBRARY_PRICE)
                .isEqualTo(priceBefore);
        // ④ 响应不得再报「建了几行」—— 没建行就没有可报的数
        assertThat(view).doesNotContainKeys("created_positions", "skipped_positions");
    }

    static Stream<Arguments> operationsWithIrrelevantBodies() {
        List<Arguments> out = new ArrayList<>();
        for (Arguments operation : operations().toList()) {
            for (Arguments bodyCase : priceIrrelevantBodies().toList()) {
                Object[] bodyArgs = bodyCase.get();
                out.add(Arguments.of(operation.get()[0], bodyArgs[0], bodyArgs[1]));
            }
        }
        return out.stream();
    }

    // ══════════ 判据 3-①：显式带 unit_price ⇒ 改价照旧生效，但仍不建价目行 ══════════

    @Test
    @DisplayName("判据 3-①：显式带 unit_price ⇒ 工序库价按明示值生效，价目行集合仍零变化")
    void explicitUnitPriceWinsWithoutCreatingRows() {
        when(productionOperationMapper.selectById(OP_ID)).thenReturn(operation("韩褶-布"));
        when(productionOperationMapper.updateById(any(ProductionOperation.class))).thenReturn(1);
        when(priceVersionMapper.insert(any(ProductionOperationPriceVersion.class))).thenReturn(1);
        when(productionOperationPositionMapper.selectList(any()))
                .thenReturn(onlyGenericRowMatrix("韩褶", MERCHANT_PRICE));

        service().update(OP_ID, Map.of("unit_price", "1.25"), TENANT);

        ArgumentCaptor<ProductionOperation> updated = ArgumentCaptor.forClass(ProductionOperation.class);
        verify(productionOperationMapper).updateById(updated.capture());
        assertThat(updated.getValue().getUnitPrice())
                .as("显式改价必须按明示值生效（不得「为了不建行」把显式改价也吃掉）")
                .isEqualByComparingTo("1.25");
        verify(priceVersionMapper).insert(any(ProductionOperationPriceVersion.class));
        verify(productionOperationPositionMapper, never()).insert(any(ProductionOperationPosition.class));
        verify(productionOperationPositionMapper, never()).updateById(any(ProductionOperationPosition.class));
    }

    // ══════════ 判据 3-②：create 路径的兜底建行行为保持不变 ══════════

    @Test
    @DisplayName("判据 3-②：create 新工序省略 positions ⇒ 兜底建那一行（既有行为勿改）")
    void createStillEnsuresTheFallbackRow() {
        when(productionOperationMapper.selectCount(any())).thenReturn(0L);
        when(productionOperationPositionMapper.selectList(any()))
                .thenReturn(List.of(matrixRow("配料", "布料", "0.20")));
        when(priceVersionMapper.insert(any(ProductionOperationPriceVersion.class))).thenReturn(1);

        Map<String, Object> view = service().create(Map.of("name", "罗马帘穿杆", "unit_price", LIBRARY_PRICE), TENANT);

        ArgumentCaptor<ProductionOperationPosition> rows =
                ArgumentCaptor.forClass(ProductionOperationPosition.class);
        verify(productionOperationPositionMapper).insert(rows.capture());
        assertThat(rows.getValue().getPosition())
                .as("新建工序的兜底列 = 收敛的取价来源列（issue #4883 / #4614 的既有行为）")
                .isEqualTo(SOURCE_POSITION);
        assertThat(rows.getValue().getUnitPrice())
                .as("新建工序没有任何既有行 ⇒ 兜底价 = 本次填的工序库价（issue #6102 明令勿改）")
                .isEqualByComparingTo(LIBRARY_PRICE);
        assertThat(view.get("created_positions")).isEqualTo(1);
        assertThat(view.get("skipped_positions")).isEqualTo(0);
    }

    // ══════════ 判据 3：显式带 positions ⇒ 仍按传入值只补缺失行（对接 #4614 存量接入）══════════

    @Test
    @DisplayName("判据 3：显式带 positions ⇒ 仍只补缺失行（存量孤儿接入路径不回归，与 create 共用实现）")
    void explicitPositionsStillAttachesMissingRowsOnly() {
        when(productionOperationMapper.selectById(OP_ID)).thenReturn(operation("韩褶-布"));
        when(productionOperationMapper.updateById(any(ProductionOperation.class))).thenReturn(1);
        when(productionOperationPositionMapper.selectList(any()))
                .thenReturn(List.of(matrixRow("韩褶", "通用", MERCHANT_PRICE)));

        Map<String, Object> view = service().update(OP_ID, Map.of("positions", List.of("布帘", "纱帘")), TENANT);

        ArgumentCaptor<ProductionOperationPosition> rows =
                ArgumentCaptor.forClass(ProductionOperationPosition.class);
        verify(productionOperationPositionMapper, org.mockito.Mockito.times(2)).insert(rows.capture());
        assertThat(rows.getAllValues()).extracting(ProductionOperationPosition::getPosition)
                .as("显式 positions 是**唯一**允许建行的写面形态；补的是缺失的列").containsExactly("布帘", "纱帘");
        assertThat(rows.getAllValues()).allSatisfy(row ->
                assertThat(row.getUnitPrice())
                        .as("补建行取该逻辑工序的既有有效价（issue #6102）—— 不是工序库价 %s", LIBRARY_PRICE)
                        .isEqualByComparingTo(MERCHANT_PRICE));
        assertThat(view.get("created_positions")).isEqualTo(2);
        assertThat(view.get("skipped_positions")).isEqualTo(0);
        verify(productionOperationPositionMapper, never()).updateById(any(ProductionOperationPosition.class));
    }

    // ══════════ 「只增不减」的另一半：写面绝不软删 / 改写既有行 ══════════

    @Test
    @DisplayName("判据 4：写面绝不删除/改写既有价目行（含软删标记）—— 价目行集合只可能因显式 positions 变大")
    void writeFaceNeverSoftDeletesOrRewritesRows() {
        String logicalName = "打包";
        List<ProductionOperationPosition> before = new ArrayList<>(onlyGenericRowMatrix(logicalName, MERCHANT_PRICE));
        when(productionOperationMapper.selectById(OP_ID)).thenReturn(operation(logicalName));
        when(productionOperationMapper.updateById(any(ProductionOperation.class))).thenReturn(1);
        when(productionOperationPositionMapper.selectList(any())).thenReturn(before);

        service().update(OP_ID, Map.of("status", "active"), TENANT);

        verify(productionOperationPositionMapper, never()).deleteById(any(String.class));
        verify(productionOperationPositionMapper, never()).updateById(any(ProductionOperationPosition.class));
        verify(productionOperationPositionMapper, never()).insert(any(ProductionOperationPosition.class));
        assertThat(before).extracting(ProductionOperationPosition::getDeleted).containsExactly(0, 0);
        assertThat(effectivePrice(logicalName, before))
                .as("有效价逐字不变").isEqualTo(MERCHANT_PRICE);
    }
}
