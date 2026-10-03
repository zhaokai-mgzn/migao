// case_ids: PG-020, PG-039, PG-055
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
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

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
 *   <li><b>不变式：写完 {@code applicable=true} 的格必须解析得到变体工序</b>（issue #4798）：
 *       判据 = 实例化侧**同一个** {@code variantNameOf}（解析序：变体表 → 帘头回落布帘 →
 *       裸逻辑名 → {@code null}）；解析不到 ⇒ 422 + {@code details} 且**不落库**。
 *       去掉护栏 ⇒ 写库成功（红），而 {@code ProcessingOrderService.buildRoute} 会把它记进
 *       {@code missing_operations} ⇒ 下单 **422 整单中止**（「配好了、用不了」）。</li>
 *   <li><b>写面可写键 = 显式枚举，词表外一律 422</b>（issue #6127）：未知 / 不可写键收到即拒
 *       （与合法价同传 ⇒ 整份拒绝），且**写库前**拦截；打靶面取**读面真键集**，不手抄词表。</li>
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
        // 🔴 issue #4937 / O1：写面只写 `unit_price` 一列（`applicable` 退场）
        when(productionOperationPositionMapper.updateUnitPrice(
                any(), any(), any(), any())).thenReturn(1);
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

        verify(productionOperationPositionMapper).updateUnitPrice(
                eq(ROW_ID), eq(TENANT), eq(new BigDecimal("0.55")), any());
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


    // ── 判据 2：三态（不做 / 未定价 / 显式 null）──



    @Test
    @DisplayName("显式 unit_price=null ⇒ 改回「未定价」（**≠ 0 元**）且留痕")
    void explicitNullPriceMeansUnpriced() {
        when(productionOperationPositionMapper.selectById(ROW_ID)).thenReturn(row("0.40", true, 0));
        stubUpdateSucceeds();
        stubCatalog();

        Map<String, Object> result = service().update(ROW_ID, body("unit_price", null), TENANT);

        verify(productionOperationPositionMapper).updateUnitPrice(
                eq(ROW_ID), eq(TENANT), eq(null), any());
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
        stubCatalog();   // 本用例只判价：让这一格可解析，避免 #4798 的不变式多报一条 detail
        when(productionOperationPositionMapper.selectById(ROW_ID)).thenReturn(row("0.40", true, 0));

        assertThatThrownBy(() -> service().update(ROW_ID, body("unit_price", "-1"), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> {
                    BusinessException ex = (BusinessException) e;
                    assertThat(ex.getHttpStatus()).isEqualTo(422);
                    assertThat(ex.getDetails()).singleElement()
                            .satisfies(d -> assertThat(d.getField()).isEqualTo("unit_price"));
                });
        verify(productionOperationPositionMapper, never()).updateUnitPrice(
                any(), any(), any(), any());
        verify(priceVersionMapper, never()).insert(any(ProductionOperationPositionPriceVersion.class));
    }

    @Test
    @DisplayName("超两位小数 ⇒ 422 + error.details（不接受静默四舍五入）且不落库")
    void tooManyDecimalsRejectedWithDetails() {
        stubCatalog();   // 同 negativePriceRejectedWithDetails：本用例只判价
        when(productionOperationPositionMapper.selectById(ROW_ID)).thenReturn(row("0.40", true, 0));

        assertThatThrownBy(() -> service().update(ROW_ID, body("unit_price", "0.555"), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> {
                    BusinessException ex = (BusinessException) e;
                    assertThat(ex.getHttpStatus()).isEqualTo(422);
                    assertThat(ex.getDetails()).singleElement()
                            .satisfies(d -> assertThat(d.getField()).isEqualTo("unit_price"));
                });
        verify(productionOperationPositionMapper, never()).updateUnitPrice(
                any(), any(), any(), any());
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

        verify(productionOperationPositionMapper, never()).updateUnitPrice(
                any(), any(), any(), any());
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

    // ── 判据 5（issue #4798）：写面不得允许「实例化必然拒绝」的配置 ──
    //
    // 不变式：写完**结果态** applicable=true 的格，必须能解析出变体工序（`variantNameOf`）。
    // 红证：去掉护栏后本组用例得「Expected BusinessException but nothing was thrown」（写库成功），
    // 而实例化侧那条路径是 fail-closed 422（ProcessingOrderService 的既有用例覆盖）。

    /** 工序库：**没有** `三边` 的任何变体（`布三边` 缺失）⇒ 该格解析不到变体。 */
    private void stubCatalogWithoutSandbian() {
        when(productionOperationMapper.selectList(any())).thenReturn(List.of(
                ProductionOperation.builder().id("op-zhijian").tenantId(TENANT).name("质检")
                        .groupName("后道").unit("套").unitPrice(new BigDecimal("1.50"))
                        .scope("position").isMustFinish(false).isStartMarker(false).sortOrder(2)
                        .status("active").deleted(0).build()));
    }

    private ProductionOperationPosition rowAt(String logicalName, String position,
                                              String price, boolean applicable) {
        ProductionOperationPosition r = row(price, applicable, 0);
        r.setId("opp-" + logicalName + "-" + position);
        r.setLogicalName(logicalName);
        r.setPosition(position);
        return r;
    }







    @Test
    @DisplayName("🔴 issue #4937 / O1：收到 `applicable` 字段 ⇒ 422 + 可行动 hint（**拒绝**，不静默忽略）")
    void applicableFieldIsRejectedWithAnActionableHint() {
        ProductionOperationPosition row = ProductionOperationPosition.builder()
                .id("opp-三边-布帘").tenantId(TENANT).logicalName("三边").position("布帘")
                .unitPrice(new BigDecimal("0.40")).applicable(true)
                .status("active").deleted(0).build();
        when(productionOperationPositionMapper.selectById("opp-三边-布帘")).thenReturn(row);

        assertThatThrownBy(() -> service().update("opp-三边-布帘",
                Map.of("applicable", false), TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("未通过校验")
                .satisfies(e -> assertThat(((BusinessException) e).getDetails())
                        .as("必须点名 `applicable` 并给出可行动 hint（静默 no-op 是本仓最忌的形态）")
                        .anySatisfy(d -> {
                            assertThat(d.getField()).isEqualTo("applicable");
                            assertThat(d.getMessage())
                                    .contains("部位适用性已退场")
                                    .contains("只传 unit_price");
                        }));
        verify(productionOperationPositionMapper, never())
                .updateUnitPrice(any(), any(), any(), any());
    }

    @Test
    @DisplayName("🔴 issue #4937 / O1：`applicable` 与 `unit_price` 同时传 ⇒ 整份拒绝（价也不落库）")
    void applicableFieldRejectsTheWholeRequest() {
        ProductionOperationPosition row = ProductionOperationPosition.builder()
                .id("opp-三边-布帘").tenantId(TENANT).logicalName("三边").position("布帘")
                .unitPrice(new BigDecimal("0.40")).applicable(true)
                .status("active").deleted(0).build();
        when(productionOperationPositionMapper.selectById("opp-三边-布帘")).thenReturn(row);

        assertThatThrownBy(() -> service().update("opp-三边-布帘",
                Map.of("unit_price", "0.55", "applicable", true), TENANT))
                .isInstanceOf(BusinessException.class);
        verify(productionOperationPositionMapper, never())
                .updateUnitPrice(any(), any(), any(), any());
    }

    // ── 判据 6（issue #6127）：写面可写键集合**是显式枚举的**，词表外一律 422 且**写库前**拦截 ──
    //
    // 病（改前实测，验收线 ③ 横切扫描 W3）：`PUT /operation-positions/{id}` body `{"position":"纱帘"}`
    // ⇒ **HTTP 200**，字段级 diff 只有 `updated_at` 变 —— 未知键被**静默忽略**，商家以为改了部位归属，
    // 实际什么都没发生；而同一端点对已退场的 `applicable` 却是 422（同系统两套口径）。
    // 红证（注入式，见 PR body）：把 `update` 里的键词表校验摘掉 ⇒ 本组用例得
    // 「Expected BusinessException but nothing was thrown」且 `updateUnitPrice` 被调用（= 真落库）。

    @Test
    @DisplayName("🔴 issue #6127：未知键 `position` ⇒ 422 点名该键 + 给出合法键，且**写库前**拦截")
    void unknownKeysAreRejectedBeforeAnyWrite() {
        when(productionOperationPositionMapper.selectById(ROW_ID)).thenReturn(row("0.40", true, 0));
        // ⚠️ 让「写成功」这条路**真的可达**：护栏一旦被摘掉，本用例的读数就是**没有异常** =
        //    静默 no-op（而不是被别的分支以 404 挡住）—— 红证读数才与线上形态同源。
        stubUpdateSucceeds();

        assertThatThrownBy(() -> service().update(ROW_ID, body("position", "纱帘"), TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("未通过校验")
                .satisfies(e -> {
                    BusinessException be = (BusinessException) e;
                    assertThat(be.getHttpStatus())
                            .as("未知键必须 422（改前是 200 静默 no-op）").isEqualTo(422);
                    assertThat(be.getDetails())
                            .as("逐键点名 + 可行动（哪些键可写）")
                            .anySatisfy(d -> {
                                assertThat(d.getField()).isEqualTo("position");
                                assertThat(d.getMessage())
                                        .contains("不是部位价目写面的可写键")
                                        .contains("unit_price");
                            });
                });
        // 🔴 关键读数：**写库前**拦截 —— 改价与版本账一行都不落（不只看状态码）
        verify(productionOperationPositionMapper, never())
                .updateUnitPrice(any(), any(), any(), any());
        verify(priceVersionMapper, never())
                .insert(any(ProductionOperationPositionPriceVersion.class));
    }

    @Test
    @DisplayName("🔴 issue #6127：未知键与合法价**同传** ⇒ 整份拒绝（价也不落库，不留半完成态）")
    void unknownKeyRejectsTheWholeRequest() {
        when(productionOperationPositionMapper.selectById(ROW_ID)).thenReturn(row("0.40", true, 0));
        stubUpdateSucceeds();   // 同 unknownKeysAreRejectedBeforeAnyWrite：让「写成功」真可达

        assertThatThrownBy(() -> service().update(ROW_ID,
                body("unit_price", "0.55", "position", "纱帘"), TENANT))
                .isInstanceOf(BusinessException.class);
        verify(productionOperationPositionMapper, never())
                .updateUnitPrice(any(), any(), any(), any());
        verify(priceVersionMapper, never())
                .insert(any(ProductionOperationPositionPriceVersion.class));
    }

    @Test
    @DisplayName("🔴 issue #6127 · 类级：可写键 = **显式枚举**，**词表外每一个键**都 422（不是只钉 `position`）")
    void everyKeyOutsideTheExplicitVocabularyIsRejected() {
        // ① 词表必须**显式枚举**且当前契约只收 `unit_price` —— 有人把它放宽成通配 / 直通 ⇒ 本行红
        assertThat(ProductionOperationPositionCommandService.WRITABLE_KEYS)
                .as("写面可写键集合必须是显式枚举（放宽 = 静默面重新打开）")
                .containsExactly("unit_price");

        when(productionOperationPositionMapper.selectById(ROW_ID)).thenReturn(row("0.40", true, 0));
        stubUpdateSucceeds();
        stubCatalog();
        // ② 打靶面**取自被测系统自己的读面**（不是手抄一份词表）：`GET /operation-positions` 的单行
        //    是调用方唯一能看到的「字段名证据」⇒ 回传那些键就是最可能的误用形态。读面若新增键，
        //    它自动进打靶面（手抄一份必然漂移）。
        Set<String> nonWritable = new LinkedHashSet<>(
                service().update(ROW_ID, body("unit_price", "0.40"), TENANT).keySet());
        assertThat(nonWritable).as("读面单行 10 键（issue #4622 口径）").hasSize(10);
        nonWritable.removeAll(ProductionOperationPositionCommandService.WRITABLE_KEYS);
        // ③ 再补实体列名与**合法键的拼错** —— 「下次换个拼错的键又静默」这条路径也要被拦
        nonWritable.addAll(List.of("unit_prcie", "logical_name", "tenant_id", "status", "deleted",
                "created_at", "updated_at", "logicalName", "unitPrice"));
        assertThat(nonWritable)
                .as("打靶面必须覆盖读面**每一个**非可写键（空面 = 空断言）")
                .contains("position", "applicable", "id", "operation", "group", "scope",
                        "unit", "is_must_finish", "variant_operation_id");

        // 上面那次合法改价调过一次 updateUnitPrice ⇒ 先清记录：下面判的是**拒绝路径一次都没写**
        org.mockito.Mockito.clearInvocations(productionOperationPositionMapper, priceVersionMapper);
        for (String key : nonWritable) {
            assertThatThrownBy(() -> service().update(ROW_ID, body(key, "纱帘"), TENANT))
                    .as("词表外的键 `%s` 必须 422，不得静默 no-op", key)
                    .isInstanceOf(BusinessException.class)
                    .satisfies(e -> assertThat(((BusinessException) e).getDetails())
                            .as("`%s` 必须被逐键点名", key)
                            .anySatisfy(d -> assertThat(d.getField()).isEqualTo(key)));
        }
        verify(productionOperationPositionMapper, never())
                .updateUnitPrice(any(), any(), any(), any());
        verify(priceVersionMapper, never())
                .insert(any(ProductionOperationPositionPriceVersion.class));
    }
}
