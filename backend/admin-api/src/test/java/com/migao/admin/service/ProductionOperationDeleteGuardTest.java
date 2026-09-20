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
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
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
 *
 * <h2>issue #4665：一键「设为不做并删除」+ 级联软删矩阵行（用户实测两轮）</h2>
 * <ol>
 *   <li><b>一键</b>（用户原话「无法删除，而且没有地方设置做于不做」）：{@code detachPositions=true}
 *       ⇒ 同一事务里先把命中的矩阵格设为 {@code applicable=false}（价清空）再软删 —— 删除的前置
 *       系统自己做，不再拆给商家两步。护栏①主线 / ②规则**照样拦**（主线涉及车间顺序，必须人工确认），
 *       且**先判护栏、后摘格** ⇒ 被拦时一格都不摘。</li>
 *   <li><b>级联软删</b>（用户第二轮「**依然删不干净**」）：工序软删后矩阵行若还在，读面
 *       （只看 {@code deleted=0}）照旧返回它 ⇒ 工艺项表格里那一行**照旧显示**。故删除必须在
 *       同一事务里把属于该工序的矩阵行（判据与护栏③**同一份** {@code variantNameOf} 命中集）
 *       也软删；写形态**显式写列**（{@code softDelete}：{@code deleted=1} + {@code updated_at}，
 *       不走 {@code updateById} —— MP 会剔除该字段 ⇒ 静默 no-op，issue #4608）；级联写失败 ⇒
 *       <b>fail-closed</b> 422（单测断言「抛 + 工序行不写」）。</li>
 * </ol>
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
        // issue #4665 C：已设「不做」的格**照样级联软删**（否则它会留在工艺项表格里 = 删不干净）
        when(productionOperationPositionMapper.softDelete(any(), any(), any())).thenReturn(1);
        when(productionOperationMapper.update(isNull(), any())).thenReturn(1);

        Map<String, Object> result = service().delete(OP_ID, TENANT);

        assertThat(result.get("deleted")).isEqualTo(true);
        verify(productionOperationPositionMapper).softDelete(eq("opp-三边-布帘"), eq(TENANT), any());
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
     * issue #4642（P2-1）：护栏文案**不得**泄漏库口径变体名。
     *
     * <p>前端 {@code routings/page.tsx} 的 {@code variant-delete-reasons} 把
     * {@code error.details[].message} **逐条原样渲染** ⇒ 文案里写 {@code 布三边} 就等于把变体名
     * 送上商家屏（与 P1 同一条泄漏路径，只是走 422 而不是 200）。文案改用同函数里**已有**的
     * {@code logicalName}；「到底是哪条库行」的辨识度由**部位集合/分组**补足。</p>
     *
     * <p>本用例**只动 message 的显示口径**：三条护栏的判据（主线/规则/矩阵）与 field 一字不变。</p>
     */
    @Test
    @DisplayName("#4642 三条护栏的 message 只用**逻辑名**（三边）—— 变体名（布三边）不得上屏")
    void guardMessagesNeverLeakTheLibraryVariantName() {
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
                .satisfies(e -> {
                    BusinessException ex = (BusinessException) e;
                    assertThat(ex.getDetails()).hasSize(3);
                    // 正口径：每条理由都用逻辑名（可行动 = 商家认得的那道工序）
                    assertThat(ex.getDetails()).allSatisfy(d -> assertThat(d.getMessage())
                            .as("护栏文案必须用逻辑名「三边」").contains("三边"));
                    // 反向护栏：变体名**不得**出现在任何一条理由里（前端逐条渲染这些 message）
                    assertThat(ex.getDetails()).allSatisfy(d -> assertThat(d.getMessage())
                            .as("库口径变体名「布三边」泄漏回 web 面（前端 variant-delete-reasons 逐条渲染）")
                            .doesNotContain("布三边"));
                });
    }

    // ── 一键「设为不做并删除」（issue #4665）──

    /**
     * issue #4665 A：删除的前置（把相关格设为不做）**系统自己做** ——
     * {@code detachPositions=true} ⇒ 同一事务里先摘格（{@code applicable=false} + 价清空）再软删。
     *
     * <p>红证（改前）：{@code delete(String, Long, boolean)} 不存在 ⇒ 本用例编译失败/红；
     * 且改前商家必须手工两步（先去矩阵格设不做，再回来删）。</p>
     */
    @Test
    @DisplayName("#4665 一键摘格：detachPositions=true ⇒ 两个命中格 applicable=false + 价清空，然后仍删工序")
    void detachPositionsTurnsCellsOffThenDeletes() {
        when(productionOperationMapper.selectById(OP_ID)).thenReturn(operation(0));
        stubCatalog();
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of());
        when(productionRouteRuleMapper.selectList(any())).thenReturn(List.of());
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of(
                position("三边", "布帘", true),
                position("三边", "帘头", true)));
        when(productionOperationPositionMapper.updatePriceAndApplicable(
                any(), any(), any(), any(), any())).thenReturn(1);
        when(productionOperationPositionMapper.softDelete(any(), any(), any())).thenReturn(1);
        when(productionOperationMapper.update(isNull(), any())).thenReturn(1);

        Map<String, Object> result = service().delete(OP_ID, TENANT, true);

        // ① 每个命中格都写「不做」（**遍历全部命中格**，不是只看一格）
        ArgumentCaptor<String> ids = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<BigDecimal> prices = ArgumentCaptor.forClass(BigDecimal.class);
        ArgumentCaptor<Boolean> applicables = ArgumentCaptor.forClass(Boolean.class);
        verify(productionOperationPositionMapper, org.mockito.Mockito.times(2))
                .updatePriceAndApplicable(ids.capture(), any(), prices.capture(), applicables.capture(), any());
        assertThat(ids.getAllValues()).containsExactlyInAnyOrder("opp-三边-布帘", "opp-三边-帘头");
        assertThat(applicables.getAllValues()).as("必须写 applicable=false").containsOnly(false);
        assertThat(prices.getAllValues()).as("不做 ⇒ 价强制清空（≠ 0 元）").containsOnlyNulls();

        // ② 然后真的软删（不是「只摘格不删」）
        verify(productionOperationMapper).update(isNull(), any());
        assertThat(result.get("deleted")).isEqualTo(true);
        assertThat(result.get("detached_positions")).as("如实报数：摘了几个格").isEqualTo(2);
    }

    /**
     * 反向护栏（issue #4665 明确要求）：**主线那一条不得被这个按钮绕过**。
     *
     * <p>主线涉及车间顺序，必须人工确认 —— {@code detachPositions=true} 时护栏①照样拦，
     * 且**一格都不许被摘**（拦下时不得留下副作用）。</p>
     */
    @Test
    @DisplayName("#4665 反向护栏：主线命中 ⇒ detachPositions=true **也被拦**，且一格都不摘")
    void detachPositionsDoesNotBypassMainlineGuard() {
        when(productionOperationMapper.selectById(OP_ID)).thenReturn(operation(0));
        stubCatalog();
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of(
                routing("窗帘工序路线（默认）", List.of("精裁", "三边"))));
        when(productionRouteRuleMapper.selectList(any())).thenReturn(List.of());
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of(
                position("三边", "布帘", true)));

        assertThatThrownBy(() -> service().delete(OP_ID, TENANT, true))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> {
                    BusinessException ex = (BusinessException) e;
                    assertThat(ex.getHttpStatus()).isEqualTo(422);
                    assertThat(detailFields(ex)).contains("routing");
                    assertThat(detailFields(ex))
                            .as("矩阵格那一条已被一键满足 ⇒ 只剩主线/规则那几条")
                            .doesNotContain("operation_position");
                });
        // 拦下 ⇒ **没有任何副作用**（既不摘格也不删）
        verify(productionOperationPositionMapper, never())
                .updatePriceAndApplicable(any(), any(), any(), any(), any());
        verify(productionOperationPositionMapper, never()).softDelete(any(), any(), any());
        verify(productionOperationMapper, never()).update(isNull(), any());
    }

    /**
     * 反向护栏：不带 {@code detachPositions}（既有调用方 / 老 bundle）⇒ 行为**一字不变**
     * —— 矩阵格仍是硬护栏（这是「不放宽护栏」的反向证明）。
     */
    @Test
    @DisplayName("#4665 反向护栏：不传 detachPositions ⇒ 矩阵格仍是硬护栏（既有行为不变）")
    void withoutDetachFlagTheMatrixGuardStillRejects() {
        when(productionOperationMapper.selectById(OP_ID)).thenReturn(operation(0));
        stubCatalog();
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of());
        when(productionRouteRuleMapper.selectList(any())).thenReturn(List.of());
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of(
                position("三边", "布帘", true)));

        assertThatThrownBy(() -> service().delete(OP_ID, TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(detailFields((BusinessException) e))
                        .containsExactly("operation_position"));
        verify(productionOperationPositionMapper, never())
                .updatePriceAndApplicable(any(), any(), any(), any(), any());
        verify(productionOperationPositionMapper, never()).softDelete(any(), any(), any());
    }

    // ── 级联软删矩阵行（issue #4665 C：删工序要「删干净」）──

    /**
     * 红证（用户实测形态）：改前工序软删了、**矩阵行还在** ⇒ 工艺项表格里那一行照旧显示
     * （读面只看 {@code deleted=0}）⇒ 「依然删不干净」。
     *
     * <p>本用例钉住：删除必须**同一事务级联软删**该工序的矩阵行 —— 判据与护栏③同源
     * （{@code variantNameOf} 命中，含**帘头回落布帘变体**与「一格多部位」），写形态显式写列。</p>
     */
    @Test
    @DisplayName("#4665 C 级联软删：属于该工序的矩阵行逐行 deleted=1 + updated_at（设过不做的格也删）")
    void deleteCascadesSoftDeleteToItsMatrixRows() {
        when(productionOperationMapper.selectById(OP_ID)).thenReturn(operation(0));
        stubCatalog();
        stubNothingReferencing();
        // 一格已「不做」——**照样要删**（否则设过不做的格会留在工艺项表格里 = 用户实测「删不干净」）
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of(
                position("三边", "布帘", false)));
        when(productionOperationPositionMapper.softDelete(any(), any(), any())).thenReturn(1);
        when(productionOperationMapper.update(isNull(), any())).thenReturn(1);

        Map<String, Object> result = service().delete(OP_ID, TENANT);

        ArgumentCaptor<OffsetDateTime> stamps = ArgumentCaptor.forClass(OffsetDateTime.class);
        verify(productionOperationPositionMapper).softDelete(eq("opp-三边-布帘"), eq(TENANT), stamps.capture());
        assertThat(stamps.getValue()).as("审计：必须留 updated_at（谁在什么时候删的）").isNotNull();
        assertThat(result.get("deleted_positions")).isEqualTo(1);
        // 工序行本身也照旧软删（显式写列）
        verify(productionOperationMapper).update(isNull(), any());
    }

    /**
     * 「遍历**全部**命中格」：{@code 帘头} 回落 {@code 布帘} 变体（{@code 三边 × 帘头} 与
     * {@code 三边 × 布帘} 都指向 {@code 布三边}）⇒ 两行都要级联软删（只看一格 ⇒ 另一格留在表格里）。
     */
    @Test
    @DisplayName("#4665 C 级联软删遍历全部命中格：帘头回落布帘变体 ⇒ 两行都删（只看一格会漏）")
    void deleteCascadesEveryMatchingCellIncludingCurtainHeadFallback() {
        when(productionOperationMapper.selectById(OP_ID)).thenReturn(operation(0));
        stubCatalog();
        stubNothingReferencing();
        // 一格已「不做」、一格仍是「做」——两行**都要**级联软删（只看一格 ⇒ 另一格留在表格里）
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of(
                position("三边", "布帘", false),
                position("三边", "帘头", true)));
        when(productionOperationPositionMapper.updatePriceAndApplicable(
                any(), any(), any(), any(), any())).thenReturn(1);
        when(productionOperationPositionMapper.softDelete(any(), any(), any())).thenReturn(1);
        when(productionOperationMapper.update(isNull(), any())).thenReturn(1);

        // 一键（detachPositions=true）⇒ 那一格「做」先被摘掉，再连两行一起软删
        Map<String, Object> result = service().delete(OP_ID, TENANT, true);

        ArgumentCaptor<String> ids = ArgumentCaptor.forClass(String.class);
        verify(productionOperationPositionMapper, org.mockito.Mockito.times(2))
                .softDelete(ids.capture(), any(), any());
        assertThat(ids.getAllValues()).containsExactlyInAnyOrder("opp-三边-布帘", "opp-三边-帘头");
        assertThat(result.get("deleted_positions")).isEqualTo(2);
    }

    /**
     * **一次事务**：矩阵行删除失败（并发下已被别人删掉 / 写失败）⇒ 工序**不得**被删。
     *
     * <p>服务层靠 fail-closed 抛 422 让 {@code @Transactional} 回滚（单测里断言「抛 + 工序行没写」）。
     * 不留「工序删了、行还在」的半完成态 —— 那正是用户实测的「删不干净」。</p>
     */
    @Test
    @DisplayName("#4665 C 一次事务：矩阵行删除失败 ⇒ fail-closed（工序行不写、不静默半完成）")
    void cascadeFailureFailsClosedBeforeDeletingTheOperation() {
        when(productionOperationMapper.selectById(OP_ID)).thenReturn(operation(0));
        stubCatalog();
        stubNothingReferencing();
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of(
                position("三边", "布帘", true)));
        // 0 = 行不存在 / 非本租户 / 已软删 ⇒ 必须 fail-closed
        when(productionOperationPositionMapper.softDelete(any(), any(), any())).thenReturn(0);

        assertThatThrownBy(() -> service().delete(OP_ID, TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(422));
        // 工序行**不得**被写（回滚的落点是「什么都没发生」）
        verify(productionOperationMapper, never()).update(isNull(), any());
    }

    /**
     * 反向护栏（#4608 同族）：级联软删**不得**写成 {@code setDeleted(1); updateById(...)} ——
     * MP 全局逻辑删除会把该字段从 SET 里剔除 ⇒ 静默 no-op。断言**调用形态**：
     * 走 {@code softDelete}（显式写列），且**从不** {@code updateById}。
     */
    @Test
    @DisplayName("#4665 C 反向护栏：级联走显式写列的 softDelete，不走 updateById（#4608 静默 no-op）")
    void cascadeNeverUsesUpdateById() {
        when(productionOperationMapper.selectById(OP_ID)).thenReturn(operation(0));
        stubCatalog();
        stubNothingReferencing();
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of(
                position("三边", "布帘", false)));
        when(productionOperationPositionMapper.softDelete(any(), any(), any())).thenReturn(1);
        when(productionOperationMapper.update(isNull(), any())).thenReturn(1);

        service().delete(OP_ID, TENANT);

        verify(productionOperationPositionMapper, never())
                .updateById(any(ProductionOperationPosition.class));
        verify(productionOperationPositionMapper, never()).deleteById(any(String.class));
        verify(productionOperationPositionMapper).softDelete(eq("opp-三边-布帘"), eq(TENANT), any());
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
