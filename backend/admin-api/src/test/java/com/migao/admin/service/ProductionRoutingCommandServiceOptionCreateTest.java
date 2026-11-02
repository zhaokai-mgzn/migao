package com.migao.admin.service;

// case_ids: PG-032, PG-033, PG-053, PG-100

import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.ProductionOperation;
import com.migao.admin.entity.ProductionRouteRule;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProcessingItemMapper;
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
 * ③ 把 {@code setScale(2, UNNECESSARY)} 换成 {@code round} ⇒ {@link #threeDecimalPriceIsRejected} 红；
 * ④ 把「目标工序在规则生效的**每个部位**上都解析得到」判据删掉（issue #6428）⇒
 * {@link #positionLimitedRuleWithoutVariantOnItsPositionIsRejected} 与
 * {@link #unlimitedRuleWithoutVariantOnEveryPositionIsRejected} 红（422 变 200、insert 被调用）；
 * 把 {@code ProductionOperationQueryService#variantNameOf} 改成恒返回逻辑名（护栏退化成空断言）⇒
 * 同两条 + {@link #variantResolutionIsPositionSensitive} 红（**这两条走真实实现，不是 mock 桩**）。
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
    @Mock
    private ProcessingItemMapper processingItemMapper;

    private ProductionRoutingCommandService service;
    /**
     * 读面用**真实对象**（只 mock Mapper）：{@code variantNameOf} 是「工序 × 部位 → 变体名」的
     * **唯一实现**（issue #6428 的写面判据与实例化侧共用）——mock 掉它 = 判据退化成空断言。
     */
    private ProductionOperationQueryService queryService;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        queryService = new ProductionOperationQueryService(
                productionOperationMapper, productionRouteTemplateMapper, productionRouteRuleMapper,
                productionOperationPositionMapper, productionCraftMapper, productionRouteSignalMapper);
        service = new ProductionRoutingCommandService(
                productionRouteTemplateMapper, productionRoutingVersionMapper, productionOperationMapper,
                queryService, productionRouteRuleMapper, processingItemMapper);
        // 工序库：4 道（**变体名**口径 —— 库里存的是「三边/精裁」这类裸逻辑名与「精裁-布」变体名）。
        // `花边-布` 是 #6420 的实证形态：**有布帘库行、没有纱帘库行**（`花边-纱`）——
        // 规则一旦在纱帘上生效，`variantNameOf("花边","纱帘",catalog)` = null ⇒ 整单 fail-closed。
        lenient().when(productionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-1", "三边"), op("op-2", "精裁-布"), op("op-3", "外帘打卷"),
                op("op-4", "花边-布")));
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
    @DisplayName("PG-032 目标工序 / 锚点传**变体名** ⇒ 落库与回显都是**逻辑名**（精裁-布 → 精裁，issue #4643）")
    void acceptsVariantOperationName() {
        Map<String, Object> result = service.createOptionRule(
                // 限定布帘（issue #6428）：库里有「精裁-布」、没有「精裁-纱」⇒ 不限部位会被 422
                body("trigger_value", "接高", "operation", "精裁-布", "after_operation", "精裁-布",
                        "position", "布帘"), TENANT);

        ProductionRouteRule row = inserted();
        // 改前实测：operation/after_operation 落的是变体名「精裁-布」⇒ GET /route-rules 回传变体名、
        // 规则表与删除确认文案上屏两套工序名（红证）。
        assertThat(row.getOperation()).isEqualTo("精裁");
        assertThat(row.getAfterOperation()).isEqualTo("精裁");
        assertThat(result).containsEntry("operation", "精裁").containsEntry("after_operation", "精裁");
    }

    @Test
    @DisplayName("PG-032 归一**幂等**：未登记的自定义工序名（外帘打卷）落库等于自身 —— 不误改商家自建工序")
    void customOperationNameIsStoredVerbatim() {
        service.createOptionRule(body("trigger_value", "接高", "operation", "外帘打卷"), TENANT);

        assertThat(inserted().getOperation()).isEqualTo("外帘打卷");
    }

    @Test
    @DisplayName("PG-032 重复预检按**归一后**比对：存量变体名行（精裁-布）+ 新建逻辑名（精裁）⇒ 409，不落第二条重复规则")
    void duplicateAgainstLegacyVariantRowIsConflict() {
        List<ProductionRouteRule> rows = new ArrayList<>();
        rows.add(existingRule("rr-1", "接高", "精裁-布"));
        lenient().when(productionRouteRuleMapper.selectList(any())).thenReturn(rows);

        assertThatThrownBy(() -> service.createOptionRule(
                // 限定布帘（issue #6428）：不限部位会先被「部位可解析性」判据 422，走不到重复预检
                body("trigger_value", "接高", "operation", "精裁", "position", "布帘"), TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("已存在");
        verify(productionRouteRuleMapper, never()).insert(any(ProductionRouteRule.class));
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
                    // 通用化后一句话摘要改为「条件工序规则校验未通过」，**逐条理由**仍在 details 里
                    // （判据是「逐条可读」，不是「摘要里含某个词」—— 旧断言写死了摘要措辞）
                    assertThat(e.getDetails().get(0).getMessage()).contains("工序库里没有");
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

    // ══════════════════ PG-053（issue #4616）：创建端点**通用化** —— craft / processing_item ══════════════════
    //
    // 用户裁定：「现在的问题是**没有入口往条件工序规则中添加新的工艺和加工项**」。
    // 改前 `createOptionRule` 把 `triggerKind("option")` **写死** ⇒ craft / processing_item 规则
    // 无法通过界面添加（库里现有 craft 10 条 + processing_item 3 条全是迁移种下的）⇒
    // 商家新增一个工艺/加工项后**无法**让它在订单里插/删工序 ⇒ 该订单**静默少工序**。
    //
    // 红证（注入式，实测）：① 把 `triggerKind` 写回常量 "option" ⇒
    // `craftRuleIsCreatedWithCraftTriggerKind` 红（断言 `trigger_kind='craft'`）；
    // ② 去掉「触发值必须在对应词表里」分支 ⇒ `craftTriggerValueOutsideVocabularyIsRejected` +
    // `processingItemTriggerValueOutsideCatalogIsRejected` 两条红（不再 422，且 insert 会被调用）；
    // ③ 去掉「对客单价只属于 option」分支 ⇒ `craftRuleWithCustomerPriceIsRejected` 红；
    // ④ 把「缺 trigger_kind ⇒ option」改成必填 ⇒ `missingTriggerKindStillDefaultsToOption` 红
    // （**反向护栏**：老调用方/老 bundle 行为一字不变）。

    /** 活跃工艺词表桩（craft 触发值的取值域）。 */
    private void stubCrafts(String... names) {
        List<com.migao.admin.entity.ProductionCraft> rows = new ArrayList<>();
        for (String name : names) {
            rows.add(com.migao.admin.entity.ProductionCraft.builder()
                    .id("pc-" + name).tenantId(TENANT).name(name).isDefault(false)
                    .status("active").deleted(0).build());
        }
        lenient().when(productionCraftMapper.selectList(any())).thenReturn(rows);
    }

    /** 加工项目录桩（processing_item 触发值的取值域；触发键 = 加工项名，**精确相等**）。 */
    private void stubProcessingItems(String... names) {
        List<com.migao.admin.entity.ProcessingItem> rows = new ArrayList<>();
        for (String name : names) {
            rows.add(com.migao.admin.entity.ProcessingItem.builder()
                    .id("pi-" + name).tenantId(TENANT).name(name).status("active").deleted(0).build());
        }
        lenient().when(processingItemMapper.selectList(any())).thenReturn(rows);
    }

    // ══════════════════ PG-053 / #4962：**部位维**（第 4 档 trigger_kind='position'）══════════════════
    //
    // 用户裁定（2026-09-21 逐字）：「如果有一些工序只能布帘有或者纱帘有，可以在适用条件上设置」
    // ⇒ 「什么时候」加第 4 维「部位」。
    // 病根（本单修复前）：部位限定被 #4937 / O2 整块退场 + 闭词表不含 `position`
    // ⇒ 界面上选得动、提交必 `23514 check_violation`（500）；写一个不在词表里的部位
    // 则会落一条**永不生效**的规则（黑洞）。
    //
    // 红证（注入式）：
    //   ① 把 `TRIGGER_KINDS` 里的 `"position"` 去掉 ⇒ `positionRuleIsCreatedWithPositionTriggerKind` 红；
    //   ② 去掉 `POSITION_LIMIT_VOCABULARY` 那一段校验 ⇒ `positionTriggerValueOutsideVocabularyIsRejected` 红
    //      （不再抛 422，且 insert 会被调用）；
    //   ③ 去掉「镜像进 `position` 列」那两行 ⇒ `positionRuleMirrorsTriggerValueIntoPositionColumn` 红
    //      （实例化侧的唯一判据是 `position` 列 ⇒ 规则永不生效）。

    @Test
    @DisplayName("PG-053 / #4962 建部位维规则：trigger_kind='position' + 值取自部位闭词表 + 镜像进 position 列")
    void positionRuleIsCreatedWithPositionTriggerKind() {
        Map<String, Object> result = service.createRouteRule(
                body("trigger_kind", "position", "trigger_value", "布帘", "operation", "三边",
                        "after_operation", "精裁"),
                TENANT);

        ProductionRouteRule row = inserted();
        assertThat(row.getTriggerKind()).isEqualTo("position");
        assertThat(row.getTriggerValue()).isEqualTo("布帘");
        assertThat(row.getPosition()).as("部位维触发必须**镜像**进 position 列（实例化侧的唯一判据）")
                .isEqualTo("布帘");
        assertThat(row.getCustomerUnitPrice()).as("部位维行不按套计价 ⇒ 对客单价必须为空").isNull();
        assertThat(result).containsEntry("trigger_kind", "position")
                .containsEntry("trigger_value", "布帘")
                .containsEntry("position", "布帘");
    }

    @Test
    @DisplayName("PG-053 / #4962 部位闭词表**含第 4 个部位 `布料`**（不得硬编码成三值）")
    void positionVocabularyCarriesTheFourthPosition() {
        assertThat(ProductionOperationQueryService.POSITION_LIMIT_VOCABULARY)
                .containsExactly("布帘", "纱帘", "帘头", "布料");
        Map<String, Object> result = service.createRouteRule(
                body("trigger_kind", "position", "trigger_value", "布料", "operation", "三边"), TENANT);
        assertThat(result).containsEntry("position", "布料");
    }

    @Test
    @DisplayName("PG-053 / #4962 部位值不在闭词表 ⇒ 422 逐条理由（点名全表），且**一个字节都不写**")
    void positionTriggerValueOutsideVocabularyIsRejected() {
        assertThatThrownBy(() -> service.createRouteRule(
                body("trigger_kind", "position", "trigger_value", "罗马帘", "operation", "三边"), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(thrown -> {
                    BusinessException e = (BusinessException) thrown;
                    assertThat(e.getHttpStatus()).isEqualTo(422);
                    assertThat(e.getDetails()).extracting("field").contains("trigger_value");
                    assertThat(e.getDetails().get(0).getMessage())
                            .as("可行动理由必须点名闭词表全表（含第 4 个部位）")
                            .contains("布帘").contains("纱帘").contains("帘头").contains("布料");
                });
        verify(productionRouteRuleMapper, never()).insert(any(ProductionRouteRule.class));
    }

    @Test
    @DisplayName("PG-053 / #4962 body 的 `position` 键同样过闭词表（craft 档也能限部位）")
    void explicitPositionKeyIsValidatedAgainstTheVocabulary() {
        stubCrafts("韩褶");
        Map<String, Object> ok = service.createRouteRule(
                body("trigger_kind", "craft", "trigger_value", "韩褶", "position", "纱帘",
                        "operation", "三边"),
                TENANT);
        assertThat(ok).containsEntry("position", "纱帘");
        assertThat(inserted().getPosition()).isEqualTo("纱帘");

        assertThatThrownBy(() -> service.createRouteRule(
                body("trigger_kind", "craft", "trigger_value", "韩褶", "position", "通用",
                        "operation", "三边"),
                TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(thrown -> assertThat(((BusinessException) thrown).getDetails())
                        .extracting("field").contains("position"));
    }

    @Test
    @DisplayName("PG-053 / #4962 部位维规则的 `position` 与 `trigger_value` 不一致 ⇒ 422（不静默取其一）")
    void positionAndTriggerValueMismatchIsRejected() {
        assertThatThrownBy(() -> service.createRouteRule(
                body("trigger_kind", "position", "trigger_value", "布帘", "position", "纱帘",
                        "operation", "三边"),
                TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(thrown -> assertThat(((BusinessException) thrown).getDetails())
                        .extracting("field").contains("position"));
        verify(productionRouteRuleMapper, never()).insert(any(ProductionRouteRule.class));
    }

    @Test
    @DisplayName("PG-053 / #4962 省略 / 空 `position` = **不限部位**（落 NULL，不落默认部位）")
    void blankPositionMeansUnlimited() {
        stubCrafts("韩褶");
        Map<String, Object> result = service.createRouteRule(
                body("trigger_kind", "craft", "trigger_value", "韩褶", "operation", "三边"), TENANT);
        assertThat(inserted().getPosition()).as("省略 = 不限部位 ⇒ NULL").isNull();
        assertThat(result).containsEntry("position", null);
        assertThat(result).containsKey("position");
    }

    @Test
    @DisplayName("PG-053 建 craft 规则：trigger_kind='craft' 落库、触发值取自活跃工艺词表、无对客单价")
    void craftRuleIsCreatedWithCraftTriggerKind() {
        stubCrafts("罗马帘", "韩褶", "打孔");

        Map<String, Object> result = service.createRouteRule(
                body("trigger_kind", "craft", "trigger_value", "罗马帘", "operation", "三边",
                        "after_operation", "精裁", "priority", "300"),
                TENANT);

        ProductionRouteRule row = inserted();
        assertThat(row.getTriggerKind()).isEqualTo("craft");
        assertThat(row.getTriggerValue()).isEqualTo("罗马帘");
        assertThat(row.getAction()).isEqualTo("insert");
        assertThat(row.getOperation()).isEqualTo("三边");
        assertThat(row.getAfterOperation()).isEqualTo("精裁");
        assertThat(row.getCustomerUnitPrice()).as("craft 行不按套计价 ⇒ 对客单价必须为空").isNull();
        assertThat(result).containsEntry("trigger_kind", "craft")
                .containsEntry("trigger_value", "罗马帘")
                .containsEntry("action", "insert");
    }

    @Test
    @DisplayName("PG-053 建 processing_item 规则：trigger_kind='processing_item' 落库、触发值取自加工项目录")
    void processingItemRuleIsCreatedWithProcessingItemTriggerKind() {
        stubProcessingItems("花边", "扣环", "拼接");

        service.createRouteRule(
                body("trigger_kind", "processing_item", "trigger_value", "拼接", "operation", "三边"), TENANT);

        ProductionRouteRule row = inserted();
        assertThat(row.getTriggerKind()).isEqualTo("processing_item");
        assertThat(row.getTriggerValue()).isEqualTo("拼接");
        assertThat(row.getCustomerUnitPrice()).isNull();
    }

    @Test
    @DisplayName("PG-053 缺 trigger_kind ⇒ **仍按 option 建**（反向护栏：老调用方/老 bundle 一字不变）")
    void missingTriggerKindStillDefaultsToOption() {
        service.createRouteRule(body("trigger_value", "加流苏", "operation", "三边"), TENANT);

        assertThat(inserted().getTriggerKind()).isEqualTo("option");
    }

    @Test
    @DisplayName("PG-053 触发值不在工艺词表 ⇒ 422 逐条理由，且**一个字节都不写**")
    void craftTriggerValueOutsideVocabularyIsRejected() {
        stubCrafts("韩褶", "打孔");

        assertThatThrownBy(() -> service.createRouteRule(
                body("trigger_kind", "craft", "trigger_value", "罗马帘", "operation", "三边"), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(thrown -> {
                    BusinessException e = (BusinessException) thrown;
                    assertThat(e.getHttpStatus()).isEqualTo(422);
                    assertThat(e.getDetails()).extracting("field").containsExactly("trigger_value");
                    assertThat(e.getDetails().get(0).getMessage()).contains("已有的活跃工艺");
                });
        verify(productionRouteRuleMapper, never()).insert(any(ProductionRouteRule.class));
    }

    @Test
    @DisplayName("PG-053 触发值不在加工项目录 ⇒ 422 逐条理由（触发键精确相等，目录里没有就永不命中）")
    void processingItemTriggerValueOutsideCatalogIsRejected() {
        stubProcessingItems("花边", "扣环");

        assertThatThrownBy(() -> service.createRouteRule(
                body("trigger_kind", "processing_item", "trigger_value", "拼接", "operation", "三边"), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(thrown -> {
                    BusinessException e = (BusinessException) thrown;
                    assertThat(e.getHttpStatus()).isEqualTo(422);
                    assertThat(e.getDetails()).extracting("field").containsExactly("trigger_value");
                    assertThat(e.getDetails().get(0).getMessage()).contains("加工项目录");
                });
        verify(productionRouteRuleMapper, never()).insert(any(ProductionRouteRule.class));
    }

    @Test
    @DisplayName("PG-053 craft / 加工项带 customer_unit_price ⇒ 422（两套账不互读，不许放宽）")
    void craftRuleWithCustomerPriceIsRejected() {
        stubCrafts("罗马帘");

        assertThatThrownBy(() -> service.createRouteRule(
                body("trigger_kind", "craft", "trigger_value", "罗马帘", "operation", "三边",
                        "customer_unit_price", "5.00"),
                TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(thrown -> {
                    BusinessException e = (BusinessException) thrown;
                    assertThat(e.getHttpStatus()).isEqualTo(422);
                    assertThat(e.getDetails()).extracting("field").containsExactly("customer_unit_price");
                });
        verify(productionRouteRuleMapper, never()).insert(any(ProductionRouteRule.class));
    }

    @Test
    @DisplayName("PG-053 trigger_kind='shaped'（结构预留、无种子行）⇒ 422，不落一行没人消费的规则")
    void shapedTriggerKindIsRejected() {
        assertThatThrownBy(() -> service.createRouteRule(
                body("trigger_kind", "shaped", "trigger_value", "定型", "operation", "三边"), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(thrown -> {
                    BusinessException e = (BusinessException) thrown;
                    assertThat(e.getHttpStatus()).isEqualTo(422);
                    assertThat(e.getDetails()).extracting("field").containsExactly("trigger_kind");
                });
        verify(productionRouteRuleMapper, never()).insert(any(ProductionRouteRule.class));
    }

    @Test
    @DisplayName("PG-053 action='remove' ⇒ 落 remove 行（不再写死 insert）；带锚点 ⇒ 422")
    void removeActionIsAcceptedAndAnchorIsRejected() {
        stubCrafts("打孔");

        service.createRouteRule(
                body("trigger_kind", "craft", "trigger_value", "打孔", "action", "remove",
                        "operation", "三边"),
                TENANT);
        assertThat(inserted().getAction()).isEqualTo("remove");
        assertThat(inserted().getAfterOperation()).isNull();

        assertThatThrownBy(() -> service.createRouteRule(
                body("trigger_kind", "craft", "trigger_value", "打孔", "action", "remove",
                        "operation", "三边", "after_operation", "外帘打卷"),
                TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(thrown -> assertThat(((BusinessException) thrown).getDetails())
                        .extracting("field").containsExactly("after_operation"));
    }

    @Test
    @DisplayName("PG-053 多条违规**一次报全**（触发值 + 对客单价 + 目标工序三条同时给）")
    void allViolationsAreReportedAtOnce() {
        stubCrafts("韩褶");

        assertThatThrownBy(() -> service.createRouteRule(
                body("trigger_kind", "craft", "trigger_value", "罗马帘", "operation", "不存在的工序",
                        "customer_unit_price", "5.00"),
                TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(thrown -> assertThat(((BusinessException) thrown).getDetails())
                        .extracting("field")
                        .containsExactly("trigger_value", "customer_unit_price", "operation"));
    }

    @Test
    @DisplayName("PG-053 同一条 craft 规则重复 ⇒ 409（唯一键按 kind + 触发值 + 动作 + 目标工序）")
    void duplicateCraftRuleIsConflict() {
        stubCrafts("罗马帘");
        List<ProductionRouteRule> rows = new ArrayList<>();
        rows.add(ProductionRouteRule.builder().id("rr-craft-1").tenantId(TENANT).triggerKind("craft")
                .triggerValue("罗马帘").action("insert").operation("三边").priority(300)
                .status("active").createdAt(OffsetDateTime.now()).updatedAt(OffsetDateTime.now())
                .deleted(0).build());
        lenient().when(productionRouteRuleMapper.selectList(any())).thenReturn(rows);

        assertThatThrownBy(() -> service.createRouteRule(
                body("trigger_kind", "craft", "trigger_value", "罗马帘", "operation", "三边"), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(thrown -> {
                    BusinessException e = (BusinessException) thrown;
                    assertThat(e.getHttpStatus()).isEqualTo(409);
                    assertThat(e.getMessage()).contains("已存在");
                });
        verify(productionRouteRuleMapper, never()).insert(any(ProductionRouteRule.class));
    }

    // ══════════ PG-100 / #6428：目标工序必须在规则**生效的每个部位**上解析得到 ══════════
    //
    // 病（#6420 实证）：写面只校验「工序库里有这道工序」（存在性），而实例化按 **工序 × 部位** 取变体名
    // （`variantNameOf`）——「花边」只有布帘库行（`花边-布`）时，一条**不限部位**的规则照样存得下，
    // 一直到有**纱帘单**命中它，才在**生产环节**整单 fail-closed（租户 25：纱帘单 22/22 全挂）。
    // 本组把「写面与实例化侧同一份解析判据」钉住（红证见类 javadoc ④）。

    @Test
    @DisplayName("PG-100 / #6428 规则限定「纱帘」但库里只有「花边-布」⇒ 422：具名值 + 部位 + 去哪儿配，一个字节都不写")
    void positionLimitedRuleWithoutVariantOnItsPositionIsRejected() {
        assertThatThrownBy(() -> service.createOptionRule(
                body("trigger_value", "加花边", "operation", "花边", "position", "纱帘"), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(thrown -> {
                    BusinessException e = (BusinessException) thrown;
                    assertThat(e.getHttpStatus()).isEqualTo(422);
                    assertThat(e.getCode()).isEqualTo("VALIDATION_ERROR");
                    assertThat(e.getDetails()).extracting("field").containsExactly("operation");
                    assertThat(e.getDetails().get(0).getMessage())
                            .as("可行动理由必须点名「哪个值 + 哪个部位 + 去哪儿配」，且与运行期同词（无法实例化工序）")
                            .contains("花边").contains("纱帘")
                            // 页面坐标按**当前 IA**（#6580 起「工艺配置」菜单项已撤，配置面在「企业基础设置」页内；
                            // 判据 = test_removed_page_copy_guard，服务端文案里出现已移除页面名即红）
                            .contains("企业基础设置").contains("工序与部位单价")
                            .contains("无法实例化工序");
                });
        verify(productionRouteRuleMapper, never()).insert(any(ProductionRouteRule.class));
    }

    @Test
    @DisplayName("PG-100 / #6428 **不限部位**的规则把「花边」用到没有该变体的纱帘 ⇒ 422（#6420 的写面闸）")
    void unlimitedRuleWithoutVariantOnEveryPositionIsRejected() {
        assertThatThrownBy(() -> service.createOptionRule(
                body("trigger_value", "加花边", "operation", "花边"), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(thrown -> {
                    BusinessException e = (BusinessException) thrown;
                    assertThat(e.getHttpStatus()).isEqualTo(422);
                    assertThat(e.getDetails()).extracting("field").containsExactly("operation");
                    assertThat(e.getDetails().get(0).getMessage())
                            .as("#6420 的形态：不限部位 ⇒ 必须在写面拦下，而不是等纱帘单命中才炸")
                            .contains("不限部位").contains("纱帘").contains("花边");
                });
        verify(productionRouteRuleMapper, never()).insert(any(ProductionRouteRule.class));
    }

    @Test
    @DisplayName("PG-100 / #6428 负控：限定到**有该变体**的部位（布帘）⇒ 照常落库（不是「一律拒花边」）")
    void positionLimitedRuleWithVariantIsAccepted() {
        Map<String, Object> result = service.createOptionRule(
                body("trigger_value", "加花边", "operation", "花边", "position", "布帘"), TENANT);

        ProductionRouteRule row = inserted();
        assertThat(row.getOperation()).isEqualTo("花边");
        assertThat(row.getPosition()).isEqualTo("布帘");
        assertThat(result).containsEntry("operation", "花边").containsEntry("position", "布帘");
    }

    @Test
    @DisplayName("PG-100 / #6428 帘头格走**显式帘头条目**（花边 × 帘头 → 花边-布）⇒ 限定帘头同样落库")
    void headPositionResolvesThroughTheExplicitHeadEntry() {
        service.createOptionRule(
                body("trigger_value", "加花边", "operation", "花边", "position", "帘头"), TENANT);

        assertThat(inserted().getPosition()).isEqualTo("帘头");
    }

    @Test
    @DisplayName("PG-100 / #6428 边界：部位无关的裸名行（外帘打卷）在任何部位都解析得到 ⇒ 不限部位照常落库")
    void bareOperationResolvesOnEveryPosition() {
        service.createOptionRule(body("trigger_value", "加流苏", "operation", "外帘打卷"), TENANT);

        assertThat(inserted().getOperation()).isEqualTo("外帘打卷");
        assertThat(inserted().getPosition()).isNull();
    }

    @Test
    @DisplayName("PG-100 / #6428 边界：action='remove' **不做变体解析**（只按逻辑名从序列删）⇒ 不判部位")
    void removeRuleIsNotJudgedByPositionResolution() {
        stubCrafts("打孔");
        service.createRouteRule(
                body("trigger_kind", "craft", "trigger_value", "打孔", "action", "remove",
                        "operation", "花边", "position", "纱帘"),
                TENANT);

        assertThat(inserted().getAction()).isEqualTo("remove");
        assertThat(inserted().getOperation()).isEqualTo("花边");
    }

    @Test
    @DisplayName("PG-100 / #6428 生效部位按**产品形态**分派：非 sales_form 规则不套用到布料单 ⇒ 理由里不点布料")
    void nonSalesFormRuleIsNotJudgedOnFabricPosition() {
        assertThatThrownBy(() -> service.createOptionRule(
                body("trigger_value", "加花边", "operation", "花边"), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(thrown -> assertThat(((BusinessException) thrown).getDetails().get(0).getMessage())
                        // 实例化侧：布料单只吃 sales_form 规则（`buildRoute` 的形态分派）⇒「花边」
                        // 在布料部位解析不到**不会**发生（这条规则根本不在布料单上生效）——
                        // 判据若把布料算进来就会误报
                        .contains("纱帘").doesNotContain("布料"));
    }

    @Test
    @DisplayName("PG-100 / #6428 sales_form 规则只吃布料单 ⇒ 目标工序在布料解析不到照样 422")
    void salesFormRuleIsJudgedOnFabricPosition() {
        assertThatThrownBy(() -> service.createRouteRule(
                body("trigger_kind", "sales_form", "trigger_value", "full_roll", "operation", "花边"),
                TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(thrown -> assertThat(((BusinessException) thrown).getDetails().get(0).getMessage())
                        .contains("布料"));
        verify(productionRouteRuleMapper, never()).insert(any(ProductionRouteRule.class));
    }

    @Test
    @DisplayName("PG-100 / #6428 判别力自证：variantNameOf 部位敏感（恒返回逻辑名 ⇒ 两条 422 用例与本条红）")
    void variantResolutionIsPositionSensitive() {
        Map<String, Map<String, Object>> catalog = queryService.operationsByName(TENANT);
        // 有布帘库行 ⇒ 解析得到（不是「一律 null」的假护栏）
        assertThat(queryService.variantNameOf("花边", "布帘", catalog)).isEqualTo("花边-布");
        // 帘头走显式帘头条目（issue #4777），同样解析得到
        assertThat(queryService.variantNameOf("花边", "帘头", catalog)).isEqualTo("花边-布");
        // 纱帘没有 `花边-纱` ⇒ **必须**是 null —— 写面 422 的唯一依据（恒真 = 空断言）
        assertThat(queryService.variantNameOf("花边", "纱帘", catalog)).isNull();
        // 部位无关的裸名行（打包 / 质检 同形态）在任何部位都解析得到 —— #6428 的边界：
        // 护栏**不得**把这类工序判成非法
        assertThat(queryService.variantNameOf("外帘打卷", "布帘", catalog)).isEqualTo("外帘打卷");
        assertThat(queryService.variantNameOf("外帘打卷", "纱帘", catalog)).isEqualTo("外帘打卷");
        assertThat(queryService.variantNameOf("外帘打卷", "帘头", catalog)).isEqualTo("外帘打卷");
    }
}
