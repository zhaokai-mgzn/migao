// case_ids: PG-020, PG-035
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.entity.ProductionOperation;
import com.migao.admin.entity.ProductionOperationPosition;
import com.migao.admin.entity.ProductionRouteRule;
import com.migao.admin.entity.ProductionRouteTemplate;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProductionCraftMapper;
import com.migao.admin.mapper.ProductionOperationMapper;
import com.migao.admin.mapper.ProductionOperationPositionMapper;
import com.migao.admin.mapper.ProductionOperationPriceVersionMapper;
import com.migao.admin.mapper.ProductionRouteRuleMapper;
import com.migao.admin.mapper.ProductionRouteSignalMapper;
import com.migao.admin.mapper.ProductionRouteTemplateMapper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeAll;
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
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 工序**软删**三条护栏（issue #4587 ③ = 母单 #4586 包A）。
 *
 * <h2>为什么每条护栏都要能红</h2>
 * 工序被删掉而引用还在 ⇒ 那些引用变成**悬空**：路线主线里少一道（车间漏工序）、
 * 规则命中后插不进来（规则变黑洞）、矩阵格指向不存在的变体（读面 5 键静默全 null
 * ⇒ 前端显示「—」而商家以为价还在）。三条护栏缺任何一条，坏数据都能静默落库。
 *
 * <h2>两条容易写错的口径（本测试逐条钉住）</h2>
 * <ol>
 *   <li><b>逻辑名或变体名都要命中</b>：主线/规则存**逻辑名**（{@code 三边}），
 *       而工序库存**变体名**（{@code 布三边}）—— 只比一种写法 ⇒ 护栏形同不存在；</li>
 *   <li><b>护栏 3 必须遍历全部命中格</b>：{@code 帘头} 会回落 {@code 布帘} 变体
 *       （{@code 三边 × 帘头} 与 {@code 三边 × 布帘} 都指向 {@code 布三边}），
 *       部位无关的工序（{@code 外帘打卷}）更是**一格多部位** ⇒ 只看一格 = 漏报。</li>
 * </ol>
 *
 * <p>另两条：护栏**一次报全**（不是报第一条就返回）；已软删 ⇒ <b>200 幂等 no-op</b>（不报 404）。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("工序软删三条护栏（issue #4587 ③）")
class ProductionOperationDeleteGuardTest {

    private static final Long TENANT = 1L;
    private static final String OP_ID = "op-busandbian";

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

    @BeforeAll
    static void primeMybatisPlusLambdaCache() {
        // `LambdaUpdateWrapper.set(...)` 会**立即**求值列名（不像 LambdaQueryWrapper 的 eq 那样延迟到渲染 SQL）
        // ⇒ Standalone / Mockito 单测没有 MapperScan 建立的 TableInfo 缓存时会抛
        // 「can not find lambda cache for this entity」。软删写形态（issue #4608）走 LambdaUpdateWrapper，
        // 故在此初始化缓存（同 ProductionRoutingReadControllerTest / ProductionOperationQueryServiceTest 的既有做法）。
        MybatisConfiguration configuration = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(configuration, "");
        TableInfoHelper.initTableInfo(assistant, ProductionOperation.class);
    }

    private ProductionOperationCommandService service() {
        return new ProductionOperationCommandService(productionOperationMapper, priceVersionMapper,
                productionOperationPositionMapper,
                new ProductionOperationQueryService(productionOperationMapper,
                        productionRouteTemplateMapper, productionRouteRuleMapper,
                        productionOperationPositionMapper, productionCraftMapper,
                        productionRouteSignalMapper));
    }

    // ── 夹具 ──

    /** 被删的工序：库中名 = 变体名 {@code 布三边}（逻辑名 = {@code 三边}）。 */
    private ProductionOperation operation(int deleted) {
        return ProductionOperation.builder()
                .id(OP_ID).tenantId(TENANT).name("布三边").groupName("车位").unit("米")
                .unitPrice(new BigDecimal("0.40")).scope("position").isMustFinish(false)
                .isStartMarker(false).sortOrder(1).status("active").deleted(deleted).build();
    }

    private ProductionRouteTemplate routing(String name, List<String> mainline) {
        return ProductionRouteTemplate.builder()
                .id("rt-" + name).tenantId(TENANT).name(name).isDefault(false)
                .positions(List.of("布帘", "帘头")).mainline(mainline).status("active").deleted(0)
                .build();
    }

    private ProductionRouteRule rule(String id, String operation, String afterOperation) {
        return ProductionRouteRule.builder()
                .id(id).tenantId(TENANT).triggerKind("craft").triggerValue("韩褶")
                .action("insert").operation(operation).afterOperation(afterOperation)
                .priority(20).status("active").deleted(0).build();
    }

    private ProductionOperationPosition position(String logical, String pos, boolean applicable) {
        return ProductionOperationPosition.builder()
                .id("opp-" + logical + "-" + pos).tenantId(TENANT).logicalName(logical).position(pos)
                .unitPrice(new BigDecimal("0.40")).applicable(applicable).status("active").deleted(0)
                .build();
    }

    /** 工序库（`variantNameOf` 的解析源）：`布三边` 在库 ⇒ `三边 × 布帘` / `三边 × 帘头` 都解析到它。 */
    private void stubCatalog() {
        when(productionOperationMapper.selectList(any())).thenReturn(List.of(operation(0)));
    }

    private static List<String> detailFields(BusinessException e) {
        return e.getDetails() == null ? List.of()
                : e.getDetails().stream().map(ApiResponse.ErrorDetail::getField).toList();
    }

    private void stubNothingReferencing() {
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of());
        when(productionRouteRuleMapper.selectList(any())).thenReturn(List.of());
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of());
    }

    // ── 护栏 ①：活跃路线主线（逻辑名或变体名）──

    @Test
    @DisplayName("护栏①：被活跃路线主线按**逻辑名**命中 ⇒ 422 且理由里给出路线名")
    void guard1RejectsWhenMainlineReferencesByLogicalName() {
        when(productionOperationMapper.selectById(OP_ID)).thenReturn(operation(0));
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of(
                routing("窗帘工序路线（默认）", List.of("精裁", "三边", "车被"))));
        when(productionRouteRuleMapper.selectList(any())).thenReturn(List.of());
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of());

        assertThatThrownBy(() -> service().delete(OP_ID, TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> {
                    BusinessException ex = (BusinessException) e;
                    assertThat(ex.getHttpStatus()).isEqualTo(422);
                    assertThat(detailFields(ex)).contains("routing");
                    assertThat(ex.getDetails()).anySatisfy(d -> assertThat(d.getMessage())
                            .as("理由必须**可行动**：说出是哪条路线").contains("窗帘工序路线（默认）"));
                });
        verify(productionOperationMapper, never()).updateById(any(ProductionOperation.class));
    }

    @Test
    @DisplayName("护栏①：被活跃路线主线按**变体名**命中 ⇒ 同样拒（主线里两种写法都收）")
    void guard1RejectsWhenMainlineReferencesByVariantName() {
        when(productionOperationMapper.selectById(OP_ID)).thenReturn(operation(0));
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of(
                routing("路线甲", List.of("精裁", "布三边"))));
        when(productionRouteRuleMapper.selectList(any())).thenReturn(List.of());
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of());

        assertThatThrownBy(() -> service().delete(OP_ID, TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(detailFields((BusinessException) e)).contains("routing"));
    }

    // ── 护栏 ②：活跃规则（operation 或 after_operation）──

    @Test
    @DisplayName("护栏②：被活跃规则的 operation 命中 ⇒ 422 且理由里给出触发名")
    void guard2RejectsWhenRuleTargetsTheOperation() {
        when(productionOperationMapper.selectById(OP_ID)).thenReturn(operation(0));
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of());
        when(productionRouteRuleMapper.selectList(any())).thenReturn(List.of(
                rule("rr-1", "三边", "韩褶")));
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of());

        assertThatThrownBy(() -> service().delete(OP_ID, TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> {
                    BusinessException ex = (BusinessException) e;
                    assertThat(ex.getHttpStatus()).isEqualTo(422);
                    assertThat(detailFields(ex)).contains("route_rule");
                    assertThat(ex.getDetails()).anySatisfy(d -> assertThat(d.getMessage())
                            .as("理由必须**可行动**：说出是哪个触发（工艺/选项）").contains("韩褶"));
                });
    }

    @Test
    @DisplayName("护栏②：被活跃规则的 after_operation（锚点）命中 ⇒ 同样拒（只查 operation 会漏）")
    void guard2RejectsWhenRuleUsesTheOperationAsAnchor() {
        when(productionOperationMapper.selectById(OP_ID)).thenReturn(operation(0));
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of());
        when(productionRouteRuleMapper.selectList(any())).thenReturn(List.of(
                rule("rr-2", "上车布", "三边")));
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of());

        assertThatThrownBy(() -> service().delete(OP_ID, TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(detailFields((BusinessException) e)).contains("route_rule"));
    }

    // ── 护栏 ③：矩阵行（遍历全部命中格）──

    @Test
    @DisplayName("护栏③：被矩阵行引用（applicable=true）⇒ 422 且理由里给出部位")
    void guard3RejectsWhenMatrixCellIsApplicable() {
        when(productionOperationMapper.selectById(OP_ID)).thenReturn(operation(0));
        stubCatalog();
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of());
        when(productionRouteRuleMapper.selectList(any())).thenReturn(List.of());
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of(
                position("三边", "布帘", true)));

        assertThatThrownBy(() -> service().delete(OP_ID, TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> {
                    BusinessException ex = (BusinessException) e;
                    assertThat(ex.getHttpStatus()).isEqualTo(422);
                    assertThat(detailFields(ex)).contains("operation_position");
                    assertThat(ex.getDetails()).anySatisfy(d -> assertThat(d.getMessage())
                            .as("理由必须**可行动**：说出是哪个部位").contains("布帘"));
                });
    }

    @Test
    @DisplayName("护栏③：**遍历全部命中格** —— 帘头回落布帘变体 ⇒ 两格都报（只看一格会漏）")
    void guard3WalksEveryMatchingCellIncludingCurtainHeadFallback() {
        when(productionOperationMapper.selectById(OP_ID)).thenReturn(operation(0));
        stubCatalog();
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of());
        when(productionRouteRuleMapper.selectList(any())).thenReturn(List.of());
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of(
                position("三边", "布帘", true),
                position("三边", "帘头", true)));

        assertThatThrownBy(() -> service().delete(OP_ID, TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> {
                    BusinessException ex = (BusinessException) e;
                    assertThat(detailFields(ex)).containsOnly("operation_position", "operation_position");
                    assertThat(ex.getDetails()).anySatisfy(d -> assertThat(d.getMessage()).contains("布帘"));
                    assertThat(ex.getDetails()).anySatisfy(d -> assertThat(d.getMessage())
                            .as("帘头格也回落同一变体 ⇒ 必须一并报出（只看一格 ⇒ 删完这里悬空）")
                            .contains("帘头"));
                });
    }

    @Test
    @DisplayName("护栏③：格存在但 applicable=false（明确不做）⇒ **不算引用**，可删")
    void guard3IgnoresNotApplicableCells() {
        when(productionOperationMapper.selectById(OP_ID)).thenReturn(operation(0));
        stubCatalog();
        stubNothingReferencing();
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of(
                position("三边", "布帘", false)));
        when(productionOperationMapper.update(isNull(), any())).thenReturn(1);

        Map<String, Object> result = service().delete(OP_ID, TENANT);

        assertThat(result.get("deleted")).isEqualTo(true);
    }

    // ── 一次报全 / 幂等 / 404 ──

    @Test
    @DisplayName("三条护栏**一次报全**（不是报第一条就返回）")
    void allThreeGuardsAreReportedAtOnce() {
        when(productionOperationMapper.selectById(OP_ID)).thenReturn(operation(0));
        stubCatalog();
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of(
                routing("路线甲", List.of("三边"))));
        when(productionRouteRuleMapper.selectList(any())).thenReturn(List.of(
                rule("rr-1", "三边", null)));
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of(
                position("三边", "布帘", true)));

        assertThatThrownBy(() -> service().delete(OP_ID, TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(detailFields((BusinessException) e))
                        .containsExactlyInAnyOrder("routing", "route_rule", "operation_position"));
    }

    /**
     * ⚠️ 断言**调用形态**（不是「塞进实体的值」，issue #4608）：MP 全局逻辑删除会把 {@code deleted}
     * 从 {@code updateById} 的 SET 子句里剔除 ⇒ 只有显式写列（{@code update(null, LambdaUpdateWrapper)}）
     * 才真落库；旧写法（{@code op.setDeleted(1); updateById(op);}）断言的是实体里的值，
     * 所以「服务端报成功、数据还在」也能绿。改回旧写法 ⇒ 本用例红。
     */
    @Test
    @DisplayName("无引用 ⇒ 软删**显式写列** deleted=1 + updated_at（不走 updateById）")
    void softDeletesWhenNoReference() {
        when(productionOperationMapper.selectById(OP_ID)).thenReturn(operation(0));
        stubCatalog();
        stubNothingReferencing();
        when(productionOperationMapper.update(isNull(), any())).thenReturn(1);

        Map<String, Object> result = service().delete(OP_ID, TENANT);

        ArgumentCaptor<LambdaUpdateWrapper> wrapper = ArgumentCaptor.forClass(LambdaUpdateWrapper.class);
        verify(productionOperationMapper).update(isNull(), wrapper.capture());
        verify(productionOperationMapper, never()).updateById(any(ProductionOperation.class));
        assertThat(wrapper.getValue().getSqlSet())
                .as("显式 SET 必须含 deleted 与 updated_at（不是只「调了 update」）")
                .contains("deleted")
                .contains("updated_at");
        verify(productionOperationMapper, never()).deleteById(any(String.class));
        assertThat(result.get("id")).isEqualTo(OP_ID);
        assertThat(result.get("deleted")).isEqualTo(true);
    }

    @Test
    @DisplayName("已软删 ⇒ 200 幂等 no-op（不报 404、不再写库）")
    void alreadyDeletedIsIdempotentNoop() {
        when(productionOperationMapper.selectById(OP_ID)).thenReturn(operation(1));

        Map<String, Object> result = service().delete(OP_ID, TENANT);

        assertThat(result.get("deleted")).isEqualTo(true);
        verify(productionOperationMapper, never()).updateById(any(ProductionOperation.class));
        verify(productionOperationMapper, never()).update(isNull(), any());
    }

    @Test
    @DisplayName("不存在 / 跨租户 ⇒ 404（且不写库）")
    void missingOrForeignIs404() {
        when(productionOperationMapper.selectById("nope")).thenReturn(null);
        assertThatThrownBy(() -> service().delete("nope", TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(404));

        ProductionOperation foreign = operation(0);
        foreign.setTenantId(99L);
        when(productionOperationMapper.selectById(OP_ID)).thenReturn(foreign);
        assertThatThrownBy(() -> service().delete(OP_ID, TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(404));

        verify(productionOperationMapper, never()).updateById(any(ProductionOperation.class));
        verify(productionOperationMapper, never()).update(isNull(), any());
    }
}
