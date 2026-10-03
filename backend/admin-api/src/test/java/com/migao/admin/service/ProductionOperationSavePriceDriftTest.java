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
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 保存一次工序设置**不得静默改写计件单价**（issue #6102，P1）。
 *
 * <p><b>病根（三段，逐字可核）</b>：</p>
 * <ol>
 *   <li>{@link ProductionOperationCommandService#update} 在 body 省略 {@code positions} 时按取价来源列
 *       兜底**新建**一行 {@code position='布帘'}，价取 {@code production_operations.unit_price}；</li>
 *   <li>取价 / 读面一律走 {@link ProductionOperationQueryService#collapseToLogical}，其选行
 *       <b>布帘列优先</b>（{@link ProductionOperationQueryService#COLLAPSE_PRICE_SOURCE_POSITION}）；</li>
 *   <li>种子期这些工序的价目行经 V104 塌缩后 {@code position='通用'} ⇒ 新冒出的 {@code 布帘}
 *       行**盖住**原 {@code 通用} 行 ⇒ 有效价被改。</li>
 * </ol>
 *
 * <p><b>两个实测形态（租户 20、云 dev RDS）</b>：A 未定价工序仅改 {@code scope} ⇒ 读面与派工实例价
 * 双双变 {@code 0}/{@code 0.00}；B 商家把「工艺项」价改成 {@code 0.77} 后再保存一次设置 ⇒
 * 双双回退成 {@code 0.00}（= 工序库价）。</p>
 *
 * <p><b>本类钉住的不变量</b>：{@code update()}（不含 {@code unit_price}）保存一次设置后，
 * 由 {@code collapseToLogical} 折出的**有效价逐字不变** —— 未定价仍未定价、X 仍是 X。
 * 判据逐条对应验收判据 1~4（形态 A / 形态 B 参数化 · 显式改价照旧生效 · 新建工序不回归 ·
 * 存量孤儿接入不回归）。<b>类级</b>：不是只钉「打包」这一道 —— {@link #savingSettingsKeepsEffectivePriceUnchanged}
 * 参数化覆盖多道工序（至少一道未定价、一道已改价）。</p>
 *
 * <p>🔴 <b>issue #6126 改判后的分工（本类只保留「取值来源」这一半）</b>：「{@code update} 省略
 * {@code positions} 时是否该建行」已判定为**不该建**（写面幂等，类级不变量与判据见
 * {@link ProductionOperationWriteFaceNoGhostRowTest}）⇒ 建行的**唯一**合法触发形态 = body 显式带
 * {@code positions}。本类的判据因此分两条腿：① 省略 {@code positions} ⇒ 零行变化（锁住 #6126）；
 * ② **显式**带 {@code positions} ⇒ 新建行取既有有效价（锁住 #6102 的取值来源，
 * 见 {@link #savingSettingsWithExplicitPositionsKeepsTheCreatedRowPrice}）。两条都保留 ——
 * 只留 ① 会把「取值来源」这条判据放过，只留 ② 就是 #6126 的假绿形态。</p>
 *
 * <p>⚠️ 本类**不**改 {@code collapseToLogical} 的选行语义（issue #6102 的修复要求；该函数由另一个包负责），
 * 只钉「兜底建行的取值来源」。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("工序保存不漂价（issue #6102）：兜底建行必须继承既有有效价")
class ProductionOperationSavePriceDriftTest {

    private static final Long TENANT = 1L;
    /** 工序库行价（与既有行价刻意不同 ⇒ 取错来源必红）。 */
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

    private ProductionOperationCommandService service() {
        // 读面用**真实对象**（只 mock Mapper）—— 判据要的「有效价」是 `collapseToLogical` 折出来的，
        // mock 掉它等于把被测对象换成断言桩。
        return new ProductionOperationCommandService(
                productionOperationMapper, priceVersionMapper, productionOperationPositionMapper,
                new ProductionOperationQueryService(productionOperationMapper, productionRouteTemplateMapper,
                        productionRouteRuleMapper, productionOperationPositionMapper,
                        productionCraftMapper, productionRouteSignalMapper));
    }

    /** 工序库行（`unit_price` = 工序库价）。⚠️ 夹具只覆盖本类用到的那几列，不复制全表。 */
    private ProductionOperation operation(String name) {
        return ProductionOperation.builder()
                .id("op-6102").tenantId(TENANT).name(name).groupName("车位").position("布帘")
                .unit("米").unitPrice(new BigDecimal(LIBRARY_PRICE))
                .isMustFinish(false).isStartMarker(false).sortOrder(1).status("active").deleted(0)
                .build();
    }

    /**
     * 一道**既有**价目行（种子期经 V104 塌缩后的形态：{@code position='通用'}，V97 之前的列值）。
     *
     * <p>{@code needPrice == null} ⇒ **未定价**（读面 NULL、派工实例价 NULL）—— 形态 A 的夹具；
     * 非 null ⇒ 商家在「工艺项」表里改过的价 —— 形态 B 的夹具。
     * 注意与工序库行价 {@value #LIBRARY_PRICE} 刻意不同：实现若取错来源，判据当场红。</p>
     */
    private ProductionOperationPosition existingRow(String logicalName, String position, String needPrice) {
        return ProductionOperationPosition.builder()
                .id("opp-" + logicalName + "-" + position).tenantId(TENANT)
                .logicalName(logicalName).position(position)
                .unitPrice(needPrice == null ? null : new BigDecimal(needPrice))
                .applicable(true).status("active").deleted(0)
                .build();
    }

    /** 「一次保存设置」 = 只改 scope、**body 不含 `unit_price`**（验收判据 1 的调用形态）。 */
    private Map<String, Object> scopeOnlyBody() {
        return Map.of("scope", "set");
    }

    /** 更新路径兜底新建的那一行（本类唯一会 insert 的矩阵行）。 */
    private ProductionOperationPosition capturedNewRow() {
        ArgumentCaptor<ProductionOperationPosition> rows =
                ArgumentCaptor.forClass(ProductionOperationPosition.class);
        verify(productionOperationPositionMapper).insert(rows.capture());
        return rows.getValue();
    }

    // ══════════ 验收判据 1（形态 A / 形态 B）+ 判据 4（类级固化，多道工序参数化）══════════
    //
    // 参数化 = 「类级固化」的载体：不是只钉「打包」这一道。两个参数集覆盖两类既有工序
    // （未定价 / 已改价），每一道都在**同一个** `update()`（不含 unit_price）下走过。

    static Stream<Arguments> operationsWithExistingEffectivePrice() {
        return Stream.of(
                Arguments.of("打包", (String) null),
                Arguments.of("韩褶-布", MERCHANT_PRICE),
                Arguments.of("外帘装袋", (String) null));
    }

    @ParameterizedTest(name = "「{0}」既有有效价 = {1} ⇒ 保存后逐字不变")
    @MethodSource("operationsWithExistingEffectivePrice")
    @DisplayName("判据 1 + 4：update()（不含 unit_price）后有效价逐字不变 —— 未定价仍未定价 / X 仍是 X（多道工序）")
    void savingSettingsKeepsEffectivePriceUnchanged(String operationName, String existingPrice) {
        ProductionOperation op = operation(operationName);
        when(productionOperationMapper.selectById("op-6102")).thenReturn(op);
        when(productionOperationMapper.updateById(any(ProductionOperation.class))).thenReturn(1);
        // 价目行与兜底建行都按**归一后的逻辑名**为键（`韩褶-布` ⇒ `韩褶`）—— 见 normalizeOperationName；
        // 另混入一道**其它**工序的行（`配料`），证明取值按逻辑工序隔离、不是「表里第一行」。
        String logicalName = ProductionOperationQueryService.logicalOperationName(operationName);
        // 种子期形态：该工序**只有一行**、position='通用'（V104 塌缩后的列值，≠ 取价来源列 `布帘`）
        List<ProductionOperationPosition> matrix = List.of(
                existingRow(logicalName, "通用", existingPrice),
                existingRow("配料", "布料", "0.20"));
        when(productionOperationPositionMapper.selectList(any())).thenReturn(matrix);
        // 「有效价」= 读面 / 实例化同一份收敛（collapseToLogical）折出来的那一个价
        BigDecimal effectiveBefore = ProductionOperationQueryService.collapseToLogical(matrix).stream()
                .filter(row -> logicalName.equals(row.getLogicalName()))
                .findFirst().orElseThrow().getUnitPrice();

        Map<String, Object> view = service().update("op-6102", scopeOnlyBody(), TENANT);

        // ① ⚠️ issue #6126 已改判：**body 不含 positions ⇒ 一个价目行都不建**（此前这里兜底新建
        //    `position='布帘'` 的那一行 ⇒「保存一次设置凭空多一行、只增不减」）。本判据因此
        //    **不再捕获新行**，改为正面钉住「零行变化」—— 类级不变量见
        //    ProductionOperationWriteFaceNoGhostRowTest。取值来源判据（#6102 的另一条腿）由下面
        //    `savingSettingsWithExplicitPositionsKeepsTheCreatedRowPrice` 在**显式传 positions** 下承接：
        //    建行这件事必须先由显式传参驱动，取值来源才谈得上对错。
        verify(productionOperationPositionMapper, never()).insert(any(ProductionOperationPosition.class));
        assertThat(view).doesNotContainKeys("created_positions", "skipped_positions");
        // ② 🔴 判据本体（#6102 的另一条腿）：有效价逐字不变 —— 未定价仍未定价、0.77 仍是 0.77
        assertThat(ProductionOperationQueryService.collapseToLogical(matrix).stream()
                .filter(row -> logicalName.equals(row.getLogicalName()))
                .findFirst().orElseThrow().getUnitPrice())
                .as("保存一次设置后，该逻辑工序的有效价必须逐字不变（改前：凭空冒出 `%s` 行 ⇒ "
                                + "未定价被盖成 %s / 0.77 被盖回 %s）",
                        SOURCE_POSITION, LIBRARY_PRICE, LIBRARY_PRICE)
                .isEqualTo(effectiveBefore);
        // ③ 没给 unit_price ⇒ 不得凭空产生调价账
        verify(priceVersionMapper, never()).insert(any(ProductionOperationPriceVersion.class));
        // ④ 只补不改的另一半：不得覆盖任何既有行（商家改过的价必须原样留着）
        verify(productionOperationPositionMapper, never()).updateById(any(ProductionOperationPosition.class));
    }

    // ══════════ 验收判据 1 的第二条腿（issue #6126 改判后）：显式 positions ⇒ 建行的**取值来源**不变 ══════════
    //
    // #6102 的「取值来源」判据必须留一条会红的腿 —— 它现在只在**显式带 positions**（建行的唯一合法
    // 触发形态）下成立：新行的价取「该逻辑工序既有行折出的有效价」，不是工序库价。

    @ParameterizedTest(name = "「{0}」既有有效价 = {1} ⇒ 显式 positions 建的新行同价")
    @MethodSource("operationsWithExistingEffectivePrice")
    @DisplayName("判据 1 第二条腿：显式带 positions 时，新建行取既有有效价（未定价仍未定价 / X 仍是 X）")
    void savingSettingsWithExplicitPositionsKeepsTheCreatedRowPrice(String operationName, String existingPrice) {
        when(productionOperationMapper.selectById("op-6102")).thenReturn(operation(operationName));
        when(productionOperationMapper.updateById(any(ProductionOperation.class))).thenReturn(1);
        String logicalName = ProductionOperationQueryService.logicalOperationName(operationName);
        List<ProductionOperationPosition> matrix = List.of(
                existingRow(logicalName, "通用", existingPrice),
                existingRow("配料", "布料", "0.20"));
        when(productionOperationPositionMapper.selectList(any())).thenReturn(matrix);
        BigDecimal effectiveBefore = ProductionOperationQueryService.collapseToLogical(matrix).stream()
                .filter(row -> logicalName.equals(row.getLogicalName()))
                .findFirst().orElseThrow().getUnitPrice();

        // 显式带 positions（= 商家/脚本主动要求建缺失列）；`布帘` 列尚不存在 ⇒ 必建一行
        service().update("op-6102",
                Map.of("unit_price", LIBRARY_PRICE, "positions", List.of(SOURCE_POSITION)), TENANT);

        ProductionOperationPosition created = capturedNewRow();
        assertThat(created.getPosition()).isEqualTo(SOURCE_POSITION);
        if (effectiveBefore == null) {
            assertThat(created.getUnitPrice())
                    .as("既有行未定价 ⇒ 新行**也必须未定价**（落工序库价 %s 就是把「未定价」变成"
                                    + "「真 %s 元」—— 工人白干且无人知道，与 #4696「价只选行、绝不回落」同口径）",
                            LIBRARY_PRICE, LIBRARY_PRICE)
                    .isNull();
        } else {
            assertThat(created.getUnitPrice())
                    .as("既有有效价 = %s（商家改过的价）⇒ 新行必须同价；落工序库价 %s 就是形态 B"
                                    + "「保存一次设置回退」的同一根因",
                            effectiveBefore.toPlainString(), LIBRARY_PRICE)
                    .isEqualByComparingTo(effectiveBefore);
        }
        List<ProductionOperationPosition> afterMatrix = new ArrayList<>(matrix);
        afterMatrix.add(created);
        assertThat(ProductionOperationQueryService.collapseToLogical(afterMatrix).stream()
                .filter(row -> logicalName.equals(row.getLogicalName()))
                .findFirst().orElseThrow().getUnitPrice())
                .as("建行之后有效价仍须逐字不变")
                .isEqualTo(effectiveBefore);
    }

    // ══════════ 验收判据 2（对照）：body 显式带 unit_price ⇒ 按明示值变 ══════════

    @Test
    @DisplayName("判据 2（对照）：update() 显式带 unit_price ⇒ 兜底行 + 版本账都按**明示值**走")
    void explicitUnitPriceStillWins() {
        when(productionOperationMapper.selectById("op-6102")).thenReturn(operation("韩褶-布"));
        when(productionOperationMapper.updateById(any(ProductionOperation.class))).thenReturn(1);
        when(priceVersionMapper.insert(any(ProductionOperationPriceVersion.class))).thenReturn(1);
        // 该逻辑工序**一个价目行都没有**（存量孤儿）⇒ 兜底建行没有「既有有效价」可继承，
        // 唯一可能被继承的就是本次**明示**的 unit_price
        when(productionOperationPositionMapper.selectList(any()))
                .thenReturn(List.of(existingRow("配料", "布料", "0.20")));

        // issue #6126：建行只由**显式** positions 触发 ⇒ 本判据显式带上它（`布帘` 列尚不存在 ⇒ 必建一行），
        // 这样「明示 unit_price → 新行取明示值」这条 #6102 判据仍然会红。
        service().update("op-6102",
                Map.of("unit_price", "1.25", "positions", List.of(SOURCE_POSITION)), TENANT);

        ProductionOperationPosition created = capturedNewRow();
        assertThat(created.getUnitPrice())
                .as("用户**明示**改价 ⇒ 兜底建行必须跟明示值（不能「为了不漂价」把显式改价也吃掉）")
                .isEqualByComparingTo("1.25");
        ArgumentCaptor<ProductionOperationPriceVersion> version =
                ArgumentCaptor.forClass(ProductionOperationPriceVersion.class);
        verify(priceVersionMapper).insert(version.capture());
        assertThat(version.getValue().getUnitPrice())
                .as("版本账（当前价 = 最新版本行）同样按明示值")
                .isEqualByComparingTo("1.25");
    }

    @Test
    @DisplayName("回归护栏：显式改价**不覆盖**商家已定价的既有行（只补不改），改价照旧落库 + 记账")
    void explicitUnitPriceStillDoesNotOverwriteExistingPricedRow() {
        when(productionOperationMapper.selectById("op-6102")).thenReturn(operation("韩褶-布"));
        when(productionOperationMapper.updateById(any(ProductionOperation.class))).thenReturn(1);
        when(priceVersionMapper.insert(any(ProductionOperationPriceVersion.class))).thenReturn(1);
        when(productionOperationPositionMapper.selectList(any()))
                .thenReturn(List.of(existingRow("韩褶", "通用", MERCHANT_PRICE)));

        // issue #6126：显式带 positions（`布帘` 列已存在 ⇒ 只跳过、不建行），改价仍照旧落库 + 记账
        service().update("op-6102",
                Map.of("unit_price", "1.25", "positions", List.of(SOURCE_POSITION)), TENANT);
        // 🔴 **如实登记的边界**（issue #6102 修复未覆盖、本判据也不放宽既有护栏）：已有价目行的工序
        // 走「只补不改」时，既有行**不会**被同步成明示新价（`attachPositions` 对已存在的
        // `(逻辑名, 通用)` 只跳过、从不 update）⇒ 这道工序留着旧价。本包**不**顺手改这条
        // 「只补不改」护栏（它是既有冻结契约，改动面远超本单）；此处把它**钉住**，
        // 避免「静默改价」被另一个方向的静默改价（覆盖商家已定价）替换掉。
        verify(productionOperationPositionMapper, never()).updateById(any(ProductionOperationPosition.class));
        ArgumentCaptor<ProductionOperation> updated = ArgumentCaptor.forClass(ProductionOperation.class);
        verify(productionOperationMapper).updateById(updated.capture());
        assertThat(updated.getValue().getUnitPrice())
                .as("工序库行按明示值改（新单实例化的取值源）").isEqualByComparingTo("1.25");
        verify(priceVersionMapper).insert(any(ProductionOperationPriceVersion.class));
    }

    // ══════════ 验收判据 3（对照）：新建工序 ⇒ 兜底行仍带工序库价（既有行为不回归）══════════

    @Test
    @DisplayName("判据 3（对照）：create() 新工序**没有任何既有行** ⇒ 兜底行仍取工序库价（既有正确行为勿改）")
    void createKeepsLibraryPriceOnTheFallbackRow() {
        when(productionOperationMapper.selectCount(any())).thenReturn(0L);
        // 该租户矩阵里有别的工序的行（证明「没有任何既有行」判的是**本逻辑工序**，不是整张表为空）
        when(productionOperationPositionMapper.selectList(any()))
                .thenReturn(List.of(existingRow("配料", "布料", "0.20")));
        when(priceVersionMapper.insert(any(ProductionOperationPriceVersion.class))).thenReturn(1);

        service().create(Map.of("name", "罗马帘穿杆", "unit_price", LIBRARY_PRICE), TENANT);

        ProductionOperationPosition created = capturedNewRow();
        assertThat(created.getUnitPrice())
                .as("新建工序的兜底行 = 本次填的计件单价（issue #6102 明令勿改的既有行为）")
                .isEqualByComparingTo(LIBRARY_PRICE);
    }

    // ══════════ 回归护栏（既有形态不回归）：存量孤儿接入 ══════════

    @Test
    @DisplayName("回归护栏：存量孤儿接入（显式 positions、该逻辑工序一行都没有）⇒ 退回工序库价，与 create 同口径")
    void legacyOrphanStillFallsBackToLibraryPrice() {
        when(productionOperationMapper.selectById("op-6102")).thenReturn(operation("罗马帘穿杆"));
        when(productionOperationMapper.updateById(any(ProductionOperation.class))).thenReturn(1);
        when(productionOperationPositionMapper.selectList(any()))
                .thenReturn(List.of(existingRow("韩褶", "通用", MERCHANT_PRICE)));

        // issue #6126：存量孤儿接入是**显式**动作（带 positions）；省略 positions 已不再建行
        service().update("op-6102", Map.of("positions", List.of(SOURCE_POSITION)), TENANT);

        assertThat(capturedNewRow().getUnitPrice())
                .as("该逻辑工序一行都没有（存量孤儿）⇒ 没有「既有有效价」可继承，退回工序库价；"
                        + "若这里也落 null，存量孤儿接入后计价会静默变成「未定价」")
                .isEqualByComparingTo(LIBRARY_PRICE);
    }
}
