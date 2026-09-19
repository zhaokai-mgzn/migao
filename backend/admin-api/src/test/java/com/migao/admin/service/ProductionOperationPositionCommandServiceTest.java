// case_ids: PG-020, PG-039
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.migao.admin.entity.ProductionOperation;
import com.migao.admin.entity.ProductionOperationPosition;
import com.migao.admin.entity.ProductionOperationPositionPriceVersion;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProcessingItemMapper;
import com.migao.admin.mapper.ProductionCraftMapper;
import com.migao.admin.mapper.ProductionOperationMapper;
import com.migao.admin.mapper.ProductionOperationPositionMapper;
import com.migao.admin.mapper.ProductionOperationPositionPriceVersionMapper;
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
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 部位价目矩阵**写面**服务测试（issue #4587 ② = 母单 #4586 包A）。
 *
 * <p>真值源口径（用户裁定 2026-09-19）：「工序项当前的**计件单价**就是满足的，包工工资在计件工资
 * 体现，算法是**数量 × 计件单价**」⇒ 本屏的价 = <b>付工人</b>的计件单价；<b>对客</b>定价不在工序项
 * （基础加工费 = 加工项组合费用，特殊选项 = {@code route_rules.customer_unit_price}）。</p>
 *
 * <p>判据四条，各自**注入式可红**：</p>
 * <ol>
 *   <li><b>三态不混</b>：{@code applicable=false} ⇒ 价强制 NULL；{@code applicable=true} + 价 NULL
 *       = 「适用但未定价」（合法）；显式 {@code unit_price=null} = 改回未定价（**≠ 0 元**）；</li>
 *   <li><b>留痕只在真变价时</b>：价真的变了才追加 V86 账行；同价重复提交是幂等空操作
 *       （去掉「真的变了」判断 ⇒ 幂等用例红）；</li>
 *   <li><b>校验 fail-closed</b>：负价 / 超两位小数 / 非布尔 ⇒ 422 + {@code details} 且**不落库**
 *       （去掉任一分支 ⇒ 对应用例红）；</li>
 *   <li><b>响应与读面单行同构</b>：10 键，含 {@code id}（写面寻址键）与 5 键变体元数据
 *       （issue #4622 去掉 {@code variant_name}；去掉整形复用 ⇒ 键集断言红）。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("ProductionOperationPositionCommandService 部位价目矩阵写面（计件单价 / 做不做）")
class ProductionOperationPositionCommandServiceTest {

    private static final Long TENANT = 1L;
    private static final String ROW_ID = "opp-三边-布帘";

    @Mock
    private ProductionOperationPositionMapper productionOperationPositionMapper;
    @Mock
    private ProductionOperationPositionPriceVersionMapper priceVersionMapper;
    @Mock
    private ProductionOperationMapper productionOperationMapper;
    @Mock
    private ProductionRouteTemplateMapper productionRouteTemplateMapper;
    @Mock
    private ProductionRouteRuleMapper productionRouteRuleMapper;
    @Mock
    private ProductionCraftMapper productionCraftMapper;
    @Mock
    private ProcessingItemMapper processingItemMapper;
    @Mock
    private ProductionRouteSignalMapper productionRouteSignalMapper;

    /**
     * 初始化 MyBatis-Plus 的 TableInfo 缓存（同 {@code ProductionRoutingReadServiceTest} 的既有做法）：
     * 服务层构造 {@code LambdaQueryWrapper} 需要它，否则报
     * 「MybatisPlus can not find lambda cache for this entity」。
     */
    @BeforeEach
    void initTableInfoCache() {
        MybatisConfiguration conf = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(conf, "");
        TableInfoHelper.initTableInfo(assistant, ProductionOperationPosition.class);
        TableInfoHelper.initTableInfo(assistant, ProductionOperation.class);
    }

    private ProductionOperationPositionCommandService service() {
        // 读面用**真实对象**（只 mock Mapper）：响应形态 = 读面单行形态（同一份 positionView），
        // 用 mock 会让「返回更新后的矩阵格」退化成断言桩
        ProductionOperationQueryService queryService = new ProductionOperationQueryService(
                productionOperationMapper, productionRouteTemplateMapper, productionRouteRuleMapper,
                productionOperationPositionMapper, productionCraftMapper, productionRouteSignalMapper);
        return new ProductionOperationPositionCommandService(productionOperationPositionMapper,
                priceVersionMapper,
                new ProductionRoutingReadService(productionOperationPositionMapper,
                        productionRouteRuleMapper, queryService, processingItemMapper));
    }

    // ── 夹具 ──

    private ProductionOperationPosition row(String price, boolean applicable, int deleted) {
        return ProductionOperationPosition.builder()
                .id(ROW_ID).tenantId(TENANT).logicalName("三边").position("布帘")
                .unitPrice(price == null ? null : new BigDecimal(price))
                .applicable(applicable).status("active").deleted(deleted).build();
    }

    /** 工序库：`三边` 的布帘变体 = `布三边`（V54 种子逐字；帘头回落也用它）。 */
    private void stubCatalog() {
        when(productionOperationMapper.selectList(any())).thenReturn(List.of(
                ProductionOperation.builder().id("op-busandbian").tenantId(TENANT).name("布三边")
                        .groupName("车位").unit("米").unitPrice(new BigDecimal("0.40"))
                        .scope("position").isMustFinish(false).isStartMarker(false).sortOrder(1)
                        .status("active").deleted(0).build()));
    }

    private void stubUpdateSucceeds() {
        when(productionOperationPositionMapper.updatePriceAndApplicable(
                any(), any(), any(), any(), any())).thenReturn(1);
    }

    private Map<String, Object> body(Object... keyValues) {
        Map<String, Object> map = new LinkedHashMap<>();
        for (int i = 0; i < keyValues.length; i += 2) {
            map.put(String.valueOf(keyValues[i]), keyValues[i + 1]);
        }
        return map;
    }

    // ── 判据 1：改价 + 留痕 ──

    @Test
    @DisplayName("改价 ⇒ 写矩阵格 + 同事务追加 V86 账行（改价必须留痕）")
    void priceChangeWritesRowAndAppendsVersionRow() {
        when(productionOperationPositionMapper.selectById(ROW_ID)).thenReturn(row("0.40", true, 0));
        stubUpdateSucceeds();
        stubCatalog();

        Map<String, Object> result = service().update(ROW_ID, body("unit_price", "0.55"), TENANT);

        verify(productionOperationPositionMapper).updatePriceAndApplicable(
                eq(ROW_ID), eq(TENANT), eq(new BigDecimal("0.55")), eq(true), any());
        ArgumentCaptor<ProductionOperationPositionPriceVersion> captor =
                ArgumentCaptor.forClass(ProductionOperationPositionPriceVersion.class);
        verify(priceVersionMapper).insert(captor.capture());
        assertThat(captor.getValue().getPositionRowId()).isEqualTo(ROW_ID);
        assertThat(captor.getValue().getUnitPrice()).isEqualByComparingTo("0.55");
        assertThat(result.get("unit_price")).isEqualTo(new BigDecimal("0.55"));
    }

    @Test
    @DisplayName("同价重复提交 ⇒ 幂等空操作（**不**追加账行，账本不被无意义重复行淹没）")
    void samePriceDoesNotAppendVersionRow() {
        when(productionOperationPositionMapper.selectById(ROW_ID)).thenReturn(row("0.40", true, 0));
        stubUpdateSucceeds();
        stubCatalog();

        // 0.4 与 0.40 是同一个价（BigDecimal.equals 按 scale 比 ⇒ 用 equals 会误记一次调价）
        service().update(ROW_ID, body("unit_price", "0.4"), TENANT);

        verify(priceVersionMapper, never()).insert(any(ProductionOperationPositionPriceVersion.class));
    }

    @Test
    @DisplayName("只改「做不做」不改价 ⇒ 不追加账行（价没变）")
    void applicableOnlyChangeDoesNotAppendVersionRow() {
        when(productionOperationPositionMapper.selectById(ROW_ID)).thenReturn(row("0.40", true, 0));
        stubUpdateSucceeds();
        stubCatalog();

        service().update(ROW_ID, body("applicable", true), TENANT);

        verify(priceVersionMapper, never()).insert(any(ProductionOperationPositionPriceVersion.class));
    }

    // ── 判据 2：三态（不做 / 未定价 / 显式 null）──

    @Test
    @DisplayName("applicable=false ⇒ 价**强制落 NULL**（明确不做 ⇒ 不报价）且账行如实记 NULL（不填 0）")
    void applicableFalseForcesPriceToNull() {
        when(productionOperationPositionMapper.selectById(ROW_ID)).thenReturn(row("0.40", true, 0));
        stubUpdateSucceeds();
        stubCatalog();

        Map<String, Object> result = service().update(ROW_ID, body("applicable", false), TENANT);

        verify(productionOperationPositionMapper).updatePriceAndApplicable(
                eq(ROW_ID), eq(TENANT), eq(null), eq(false), any());
        ArgumentCaptor<ProductionOperationPositionPriceVersion> captor =
                ArgumentCaptor.forClass(ProductionOperationPositionPriceVersion.class);
        verify(priceVersionMapper).insert(captor.capture());
        assertThat(captor.getValue().getUnitPrice()).as("改回不做 ⇒ 价清空，账本记 NULL（≠ 0 元）").isNull();
        assertThat(result.get("applicable")).isEqualTo(false);
        assertThat(result).containsKey("unit_price");
        assertThat(result.get("unit_price")).isNull();
    }

    @Test
    @DisplayName("applicable=true + 价 null = 「适用但未定价」（**合法**状态，不是错误）")
    void applicableTrueWithoutPriceIsLegal() {
        when(productionOperationPositionMapper.selectById(ROW_ID)).thenReturn(row(null, false, 0));
        stubUpdateSucceeds();
        stubCatalog();

        Map<String, Object> result = service().update(ROW_ID, body("applicable", true), TENANT);

        verify(productionOperationPositionMapper).updatePriceAndApplicable(
                eq(ROW_ID), eq(TENANT), eq(null), eq(true), any());
        verify(priceVersionMapper, never()).insert(any(ProductionOperationPositionPriceVersion.class));
        assertThat(result.get("applicable")).isEqualTo(true);
        assertThat(result.get("unit_price")).isNull();
    }

    @Test
    @DisplayName("显式 unit_price=null ⇒ 改回「未定价」（**≠ 0 元**）且留痕")
    void explicitNullPriceMeansUnpriced() {
        when(productionOperationPositionMapper.selectById(ROW_ID)).thenReturn(row("0.40", true, 0));
        stubUpdateSucceeds();
        stubCatalog();

        Map<String, Object> result = service().update(ROW_ID, body("unit_price", null), TENANT);

        verify(productionOperationPositionMapper).updatePriceAndApplicable(
                eq(ROW_ID), eq(TENANT), eq(null), eq(true), any());
        ArgumentCaptor<ProductionOperationPositionPriceVersion> captor =
                ArgumentCaptor.forClass(ProductionOperationPositionPriceVersion.class);
        verify(priceVersionMapper).insert(captor.capture());
        assertThat(captor.getValue().getUnitPrice()).isNull();
        assertThat(result.get("unit_price")).isNull();
        assertThat(result.get("applicable")).as("只改价 ⇒ 做不做保持原值（部分更新）").isEqualTo(true);
    }

    // ── 判据 3：校验 fail-closed（422 + details，且不落库）──

    @Test
    @DisplayName("负价 ⇒ 422 + error.details（计件单价不能为负）且不落库")
    void negativePriceRejectedWithDetails() {
        when(productionOperationPositionMapper.selectById(ROW_ID)).thenReturn(row("0.40", true, 0));

        assertThatThrownBy(() -> service().update(ROW_ID, body("unit_price", "-1"), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> {
                    BusinessException ex = (BusinessException) e;
                    assertThat(ex.getHttpStatus()).isEqualTo(422);
                    assertThat(ex.getDetails()).singleElement()
                            .satisfies(d -> assertThat(d.getField()).isEqualTo("unit_price"));
                });
        verify(productionOperationPositionMapper, never()).updatePriceAndApplicable(
                any(), any(), any(), any(), any());
        verify(priceVersionMapper, never()).insert(any(ProductionOperationPositionPriceVersion.class));
    }

    @Test
    @DisplayName("超两位小数 ⇒ 422 + error.details（不接受静默四舍五入）且不落库")
    void tooManyDecimalsRejectedWithDetails() {
        when(productionOperationPositionMapper.selectById(ROW_ID)).thenReturn(row("0.40", true, 0));

        assertThatThrownBy(() -> service().update(ROW_ID, body("unit_price", "0.555"), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> {
                    BusinessException ex = (BusinessException) e;
                    assertThat(ex.getHttpStatus()).isEqualTo(422);
                    assertThat(ex.getDetails()).singleElement()
                            .satisfies(d -> assertThat(d.getField()).isEqualTo("unit_price"));
                });
        verify(productionOperationPositionMapper, never()).updatePriceAndApplicable(
                any(), any(), any(), any(), any());
    }

    @Test
    @DisplayName("applicable 非布尔 ⇒ 422 + error.details 且不落库")
    void nonBooleanApplicableRejectedWithDetails() {
        when(productionOperationPositionMapper.selectById(ROW_ID)).thenReturn(row("0.40", true, 0));

        assertThatThrownBy(() -> service().update(ROW_ID, body("applicable", "yes"), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> {
                    BusinessException ex = (BusinessException) e;
                    assertThat(ex.getHttpStatus()).isEqualTo(422);
                    assertThat(ex.getDetails()).singleElement()
                            .satisfies(d -> assertThat(d.getField()).isEqualTo("applicable"));
                });
        verify(productionOperationPositionMapper, never()).updatePriceAndApplicable(
                any(), any(), any(), any(), any());
    }

    // ── 判据 4：寻址与响应形态 ──

    @Test
    @DisplayName("行不存在 / 跨租户 / 已软删 ⇒ 404（不落库、不记账）")
    void missingForeignOrDeletedRowIs404() {
        when(productionOperationPositionMapper.selectById("nope")).thenReturn(null);
        assertThatThrownBy(() -> service().update("nope", body("unit_price", "1"), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(404));

        ProductionOperationPosition foreign = row("0.40", true, 0);
        foreign.setTenantId(99L);
        when(productionOperationPositionMapper.selectById(ROW_ID)).thenReturn(foreign);
        assertThatThrownBy(() -> service().update(ROW_ID, body("unit_price", "1"), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(404));

        when(productionOperationPositionMapper.selectById(ROW_ID)).thenReturn(row("0.40", true, 1));
        assertThatThrownBy(() -> service().update(ROW_ID, body("unit_price", "1"), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(404));

        verify(productionOperationPositionMapper, never()).updatePriceAndApplicable(
                any(), any(), any(), any(), any());
    }

    @Test
    @DisplayName("响应 = 读面**单行同构**（10 键：含 id 寻址键 + 5 键变体元数据；issue #4622 去掉变体名）")
    void responseShapeIsSameAsReadFace() {
        when(productionOperationPositionMapper.selectById(ROW_ID)).thenReturn(row("0.40", true, 0));
        stubUpdateSucceeds();
        stubCatalog();

        Map<String, Object> result = service().update(ROW_ID, body("unit_price", "0.55"), TENANT);

        assertThat(result.keySet()).containsExactly("id", "operation", "position", "unit_price",
                "applicable", "variant_operation_id", "unit", "group", "scope",
                "is_must_finish");
        assertThat(result.get("id")).isEqualTo(ROW_ID);
        assertThat(result.get("variant_operation_id")).isEqualTo("op-busandbian");
        // issue #4622：变体名**不进响应**（红证：改前此处断言 `variant_name` == "布三边"、键数 11）
        assertThat(result).doesNotContainKey("variant_name");
        assertThat(result.get("unit")).isEqualTo("米");
        assertThat(result.get("group")).isEqualTo("车位");
    }
}
