package com.migao.admin.service;

// case_ids: PG-032, PG-033

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.entity.ProductionOperation;
import com.migao.admin.entity.ProductionOperationPriceVersion;
import com.migao.admin.entity.ProductionRouteSignal;
import com.migao.admin.entity.ProductionRouteTemplate;
import com.migao.admin.entity.ProductionRouting;
import com.migao.admin.entity.ProductionRoutingVersion;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProductionCraftMapper;
import com.migao.admin.mapper.ProductionOperationMapper;
import com.migao.admin.mapper.ProductionOperationPositionMapper;
import com.migao.admin.mapper.ProductionOperationPriceVersionMapper;
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
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 工艺路线 / 信号映射**写面**护栏（issue #4308 交付物 2/3，P1）
 *
 * <h2>为什么每条护栏都要有红证</h2>
 * 路线是**计件工资**（Σ 报工数量 × 工序单价）与**完工判定**（必完工序全绿）的唯一输入，
 * 工序的 {@code unit} 还决定应做数量读哪个算料键 ⇒ 一条坏路线**直接算错工人工资**。
 * 五条护栏（空序列 / 引用不存在的工序 / 重复工序 / 至少一道必完工序 / seq 归一化 1..N）
 * 与「每次变更落版本账」缺任何一条，坏数据都能静默落库。
 *
 * <h2>错误形状（冻结契约）</h2>
 * 护栏失败 = HTTP **422** + {@code error.details:[{field,message}]} **逐条**理由
 * （复用既有信封字段，不新造；{@code message} 只做一句话摘要）—— 前端「逐条展示」有据可依。
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("工艺路线/信号写面护栏（issue #4308）")
class ProductionRoutingCommandServiceTest {

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
    private ProductionOperationPriceVersionMapper priceVersionMapper;

    private ProductionRoutingCommandService service;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        // 读面用**真实对象**（只 mock Mapper）：写面响应形态 = 路线/信号展示形态（同一份
        // routingView / signalView），用 mock 会让「返回更新后的路线」退化成断言桩。
        service = new ProductionRoutingCommandService(
                productionRouteTemplateMapper, productionRoutingVersionMapper, productionOperationMapper,
                productionRouteSignalMapper,
                new ProductionOperationQueryService(productionOperationMapper, productionRouteTemplateMapper,
                        productionRouteRuleMapper, productionOperationPositionMapper,
                        productionCraftMapper, productionRouteSignalMapper));
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ── 夹具 ──────────────────────────────────────────────────────────────

    private static ProductionOperation op(String name, boolean mustFinish) {
        return ProductionOperation.builder().id("op-" + name).tenantId(TENANT).name(name)
                .groupName("车位").unit("米").unitPrice(new BigDecimal("0.4"))
                .isMustFinish(mustFinish).isStartMarker(false).sortOrder(1)
                .status("active").deleted(0).build();
    }

    /** 工序库：精裁-布(必完) / 布三边 / 韩褶-布 / 外帘装袋(必完) / 外帘发货。 */
    private void stubLibrary() {
        when(productionOperationMapper.selectList(any())).thenReturn(List.of(
                op("精裁-布", true), op("布三边", false), op("韩褶-布", false),
                op("外帘装袋", true), op("外帘发货", false)));
    }

    private static ProductionRouteTemplate routing(String id, String name, boolean isDefault,
                                                   List<String> mainline) {
        return ProductionRouteTemplate.builder().id(id).tenantId(TENANT).name(name)
                .isDefault(isDefault).positions(List.of("布帘", "纱帘", "帘头"))
                .mainline(mainline).status("active").deleted(0).build();
    }

    private static Map<String, Object> body(Object... kv) {
        Map<String, Object> map = new LinkedHashMap<>();
        for (int i = 0; i < kv.length; i += 2) {
            map.put(String.valueOf(kv[i]), kv[i + 1]);
        }
        return map;
    }

    private static List<String> detailFields(BusinessException e) {
        return e.getDetails() == null ? List.of()
                : e.getDetails().stream().map(ApiResponse.ErrorDetail::getField).toList();
    }

    // ══════════ 判据：路线写面护栏（PG-032；P2b / issue #4459 改模板表）══════════

    @Test
    @DisplayName("护栏 1：空主线拒（422 + mainline 逐条理由）")
    void emptyMainlineIsRejected() {
        when(productionRouteTemplateMapper.selectById("rt-1"))
                .thenReturn(routing("rt-1", "路线甲", false, List.of("布三边")));
        stubLibrary();

        assertThatThrownBy(() -> service.updateRouting("rt-1", body("mainline", List.of()), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> {
                    BusinessException be = (BusinessException) e;
                    assertThat(be.getHttpStatus()).as("护栏失败统一 422").isEqualTo(422);
                    assertThat(detailFields(be)).contains("mainline");
                });
        verify(productionRouteTemplateMapper, never()).updateById(any(ProductionRouteTemplate.class));
        verify(productionRoutingVersionMapper, never()).insert(any(ProductionRoutingVersion.class));
    }

    @Test
    @DisplayName("护栏 2：引用工序库中不存在的工序拒（指名是哪一道）")
    void unknownOperationIsRejected() {
        when(productionRouteTemplateMapper.selectById("rt-1"))
                .thenReturn(routing("rt-1", "路线甲", false, List.of("布三边")));
        stubLibrary();

        assertThatThrownBy(() -> service.updateRouting("rt-1",
                body("mainline", List.of("布三边", "库里没有的工序", "外帘装袋")), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(detailFields((BusinessException) e)).contains("mainline[1]"));
        verify(productionRouteTemplateMapper, never()).updateById(any(ProductionRouteTemplate.class));
    }

    @Test
    @DisplayName("护栏 3：重复工序拒（同工序两次 ⇒ 工人按两遍单价拿钱）")
    void duplicateOperationIsRejected() {
        when(productionRouteTemplateMapper.selectById("rt-1"))
                .thenReturn(routing("rt-1", "路线甲", false, List.of("布三边")));
        stubLibrary();

        assertThatThrownBy(() -> service.updateRouting("rt-1",
                body("mainline", List.of("布三边", "外帘装袋", "布三边")), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(detailFields((BusinessException) e)).contains("mainline[2]"));
        verify(productionRouteTemplateMapper, never()).updateById(any(ProductionRouteTemplate.class));
    }

    @Test
    @DisplayName("护栏 3b（issue #4520）：**混合写法**的同一道工序也拒 —— `精裁` 与 `精裁-布` 是一道工序")
    void duplicateOperationAcrossNotationsIsRejected() {
        // ⚠️ 这条是 issue #4520 的直接产物：判重键曾是**原始字符串**，于是
        // `["精裁", …, "精裁-布"]` 被放行 ⇒ 实例化出两道 `精裁` ⇒ **工人按两遍单价拿钱**。
        // 归一口径复用 P2b 的 normalizeOperationName（变体名 → 逻辑名），不另存映射表。
        when(productionRouteTemplateMapper.selectById("rt-1"))
                .thenReturn(routing("rt-1", "路线甲", false, List.of("精裁-布")));
        stubLibrary();

        assertThatThrownBy(() -> service.updateRouting("rt-1",
                body("mainline", List.of("精裁", "外帘装袋", "精裁-布")), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(detailFields((BusinessException) e)).contains("mainline[2]"));
        verify(productionRouteTemplateMapper, never()).updateById(any(ProductionRouteTemplate.class));
    }

    @Test
    @DisplayName("护栏 3c（issue #4520）：**不得误伤** —— 不同逻辑工序的变体名并存要放行")
    void differentLogicalOperationsAreNotFalsePositives() {
        // `精裁-布`（→精裁）与 `韩褶-布`（→韩褶）是**不同**工序 ⇒ 必须放行。
        // 没有这条，一个「把所有变体名都当成同一个」的过度归一实现会静默通过。
        when(productionRouteTemplateMapper.selectById("rt-1"))
                .thenReturn(routing("rt-1", "路线甲", false, List.of("精裁-布")));
        stubLibrary();

        assertThatCode(() -> service.updateRouting("rt-1",
                body("mainline", List.of("精裁-布", "韩褶-布", "外帘装袋")), TENANT))
                .doesNotThrowAnyException();
    }

    @Test
    @DisplayName("护栏 4：至少一道必完工序（否则完工判定永远不成立 ⇒ 这张单永远完不了工）")
    void mainlineWithoutMustFinishOperationIsRejected() {
        when(productionRouteTemplateMapper.selectById("rt-1"))
                .thenReturn(routing("rt-1", "路线甲", false, List.of("布三边")));
        stubLibrary();

        assertThatThrownBy(() -> service.updateRouting("rt-1",
                body("mainline", List.of("布三边", "韩褶-布", "外帘发货")), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(detailFields((BusinessException) e)).contains("must_finish"));
        verify(productionRouteTemplateMapper, never()).updateById(any(ProductionRouteTemplate.class));
    }

    @Test
    @DisplayName("护栏 5：合法主线 ⇒ 逐位回读 + **落版本账**（序列真的变了才写）")
    void validMainlineIsVersioned() {
        when(productionRouteTemplateMapper.selectById("rt-1"))
                .thenReturn(routing("rt-1", "路线甲", false, List.of("布三边")));
        stubLibrary();

        Map<String, Object> result = service.updateRouting("rt-1",
                body("mainline", List.of("布三边", "韩褶-布", "外帘装袋")), TENANT);

        assertThat(result.get("mainline")).asString().isEqualTo(List.of("布三边", "韩褶-布", "外帘装袋").toString());
        ArgumentCaptor<ProductionRoutingVersion> version = ArgumentCaptor.forClass(ProductionRoutingVersion.class);
        verify(productionRoutingVersionMapper).insert(version.capture());
        assertThat(version.getValue().getRoutingId()).isEqualTo("rt-1");
        assertThat(version.getValue().getOperationCount()).as("版本账记工序道数").isEqualTo(3);
        assertThat(version.getValue().getOperations())
                .as("版本账存的是**变更后**的有序序列").isEqualTo(List.of("布三边", "韩褶-布", "外帘装袋"));
    }

    @Test
    @DisplayName("同主线重复提交 = 幂等空操作（不追加无意义的版本行，沿用单价版本账口径）")
    void sameMainlineIsIdempotentNoop() {
        when(productionRouteTemplateMapper.selectById("rt-1"))
                .thenReturn(routing("rt-1", "路线甲", false, List.of("布三边", "外帘装袋")));
        stubLibrary();

        service.updateRouting("rt-1", body("mainline", List.of("布三边", "外帘装袋")), TENANT);

        verify(productionRouteTemplateMapper).updateById(any(ProductionRouteTemplate.class));
        verify(productionRoutingVersionMapper, never()).insert(any(ProductionRoutingVersion.class));
    }

    @Test
    @DisplayName("改名**只改 name**：不给 mainline 就不动序列（改一个名字不该顺带重写计件工资的输入）")
    void renameOnlyChangesName() {
        when(productionRouteTemplateMapper.selectById("rt-1"))
                .thenReturn(routing("rt-1", "旧名", false, List.of("布三边", "外帘装袋")));
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of(
                routing("rt-1", "旧名", false, List.of("布三边", "外帘装袋"))));

        Map<String, Object> result = service.updateRouting("rt-1", body("name", "新名"), TENANT);

        assertThat(result.get("name")).isEqualTo("新名");
        assertThat(result.get("mainline")).as("序列必须一字不动").asString().isEqualTo(List.of("布三边", "外帘装袋").toString());
        verify(productionRoutingVersionMapper, never()).insert(any(ProductionRoutingVersion.class));
    }

    @Test
    @DisplayName("同租户活跃路线不得重名 ⇒ 409（否则撞 DB 唯一索引变 500）")
    void renameToExistingNameIsConflict() {
        when(productionRouteTemplateMapper.selectById("rt-1"))
                .thenReturn(routing("rt-1", "路线甲", false, List.of("布三边")));
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of(
                routing("rt-1", "路线甲", false, List.of("布三边")),
                routing("rt-2", "路线乙", false, List.of("外帘装袋"))));

        assertThatThrownBy(() -> service.updateRouting("rt-1", body("name", "路线乙"), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(409));
    }

    @Test
    @DisplayName("is_default 恰一条：置 true 时把既有默认**同事务降级**（否则撞部分唯一索引变 500）")
    void settingDefaultDemotesTheCurrentDefault() {
        when(productionRouteTemplateMapper.selectById("rt-2"))
                .thenReturn(routing("rt-2", "路线乙", false, List.of("外帘装袋")));
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of(
                routing("rt-1", "路线甲", true, List.of("布三边")),
                routing("rt-2", "路线乙", false, List.of("外帘装袋"))));

        Map<String, Object> result = service.updateRouting("rt-2", body("is_default", true), TENANT);

        assertThat(result.get("is_default")).isEqualTo(true);
        ArgumentCaptor<ProductionRouteTemplate> updated =
                ArgumentCaptor.forClass(ProductionRouteTemplate.class);
        verify(productionRouteTemplateMapper, org.mockito.Mockito.atLeast(2)).updateById(updated.capture());
        assertThat(updated.getAllValues())
                .as("必须有一次是把**既有默认**（rt-1）降级为 false")
                .anySatisfy(t -> {
                    assertThat(t.getId()).isEqualTo("rt-1");
                    assertThat(t.getIsDefault()).isEqualTo(false);
                });
    }

    @Test
    @DisplayName("is_default:false ⇒ 422（取消默认会让该租户零默认 ⇒ 缺信号订单建单全部 fail-closed）")
    void clearingDefaultIsRejected() {
        when(productionRouteTemplateMapper.selectById("rt-1"))
                .thenReturn(routing("rt-1", "路线甲", true, List.of("布三边")));

        assertThatThrownBy(() -> service.updateRouting("rt-1", body("is_default", false), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> {
                    assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(422);
                    assertThat(detailFields((BusinessException) e)).contains("is_default");
                });
        verify(productionRouteTemplateMapper, never()).updateById(any(ProductionRouteTemplate.class));
    }

    @Test
    @DisplayName("停用默认路线 ⇒ 422（停用它等于把租户变成零默认）")
    void disablingDefaultIsRejected() {
        when(productionRouteTemplateMapper.selectById("rt-1"))
                .thenReturn(routing("rt-1", "路线甲", true, List.of("布三边")));

        assertThatThrownBy(() -> service.updateRouting("rt-1", body("status", "disabled"), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(detailFields((BusinessException) e)).contains("status"));
    }

    @Test
    @DisplayName("删默认路线 ⇒ 422（删了就是零默认 ⇒ 建单全 fail-closed）")
    void deletingDefaultIsRejected() {
        when(productionRouteTemplateMapper.selectById("rt-1"))
                .thenReturn(routing("rt-1", "路线甲", true, List.of("布三边")));
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of(
                routing("rt-1", "路线甲", true, List.of("布三边")),
                routing("rt-2", "路线乙", false, List.of("外帘装袋"))));

        assertThatThrownBy(() -> service.deleteRouting("rt-1", TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> {
                    assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(422);
                    assertThat(detailFields((BusinessException) e)).contains("is_default");
                });
        verify(productionRouteTemplateMapper, never()).updateById(any(ProductionRouteTemplate.class));
    }

    @Test
    @DisplayName("删最后一条路线 ⇒ 422（删了没有任何路线可用 ⇒ 一张加工单也生成不了）")
    void deletingTheLastRouteIsRejected() {
        when(productionRouteTemplateMapper.selectById("rt-1"))
                .thenReturn(routing("rt-1", "路线甲", false, List.of("布三边")));
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of(
                routing("rt-1", "路线甲", false, List.of("布三边"))));

        assertThatThrownBy(() -> service.deleteRouting("rt-1", TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(detailFields((BusinessException) e)).contains("id"));
    }

    @Test
    @DisplayName("删非默认路线 = **软删**（deleted=1：谁在何时删掉哪条路线是排查错配的唯一证据）")
    void deletingNonDefaultIsSoftDelete() {
        when(productionRouteTemplateMapper.selectById("rt-2"))
                .thenReturn(routing("rt-2", "路线乙", false, List.of("外帘装袋")));
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of(
                routing("rt-1", "路线甲", true, List.of("布三边")),
                routing("rt-2", "路线乙", false, List.of("外帘装袋"))));

        Map<String, Object> result = service.deleteRouting("rt-2", TENANT);

        assertThat(result.get("deleted")).isEqualTo(true);
        ArgumentCaptor<ProductionRouteTemplate> updated =
                ArgumentCaptor.forClass(ProductionRouteTemplate.class);
        verify(productionRouteTemplateMapper).updateById(updated.capture());
        assertThat(updated.getValue().getDeleted()).isEqualTo(1);
    }

    @Test
    @DisplayName("跨租户 / 不存在的路线 ⇒ 404（不泄漏别的租户的路线存在性）")
    void unknownRoutingIsNotFound() {
        when(productionRouteTemplateMapper.selectById("rt-x")).thenReturn(null);
        assertThatThrownBy(() -> service.updateRouting("rt-x", body("mainline", List.of("布三边")), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(404));
    }

    // ══════════════════ 判据：新建路线（PG-032）══════════════════

    @Test
    @DisplayName("新建路线：mainline 缺省 = 初版空主线；响应与 GET /routings 单项同构；落首行版本账")
    void createRoutingAllowsEmptyInitialMainline() {
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of());

        Map<String, Object> result = service.createRouting(
                body("name", "罗马帘专用路线"), TENANT);

        assertThat(result.get("name")).isEqualTo("罗马帘专用路线");
        assertThat((List<?>) result.get("mainline")).isEmpty();
        assertThat(result.get("positions")).as("缺省 = 适用三部位").asString().isEqualTo(List.of("布帘", "纱帘", "帘头").toString());
        assertThat(result.get("is_default")).as("缺省 = 不是默认（不抢既有默认）").isEqualTo(false);
        ArgumentCaptor<ProductionRouteTemplate> inserted =
                ArgumentCaptor.forClass(ProductionRouteTemplate.class);
        verify(productionRouteTemplateMapper).insert(inserted.capture());
        assertThat(inserted.getValue().getStatus()).isEqualTo("active");
        assertThat(inserted.getValue().getDeleted()).isEqualTo(0);
        verify(productionRoutingVersionMapper).insert(any(ProductionRoutingVersion.class));
    }

    @Test
    @DisplayName("新建路线：同租户活跃路线重名（含停用行）⇒ 409（否则撞 DB 唯一索引变 500）")
    void createRoutingRejectsDuplicateName() {
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of(
                routing("rt-1", "路线甲", false, List.of("布三边"))));

        assertThatThrownBy(() -> service.createRouting(body("name", "路线甲"), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(409));
        verify(productionRouteTemplateMapper, never()).insert(any(ProductionRouteTemplate.class));
    }

    @Test
    @DisplayName("新建默认路线：把既有默认同事务降级（恰一条默认的不变式）")
    void createDefaultRoutingDemotesExistingDefault() {
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of(
                routing("rt-1", "路线甲", true, List.of("布三边"))));

        Map<String, Object> result = service.createRouting(
                body("name", "路线乙", "is_default", true), TENANT);

        assertThat(result.get("is_default")).isEqualTo(true);
        ArgumentCaptor<ProductionRouteTemplate> updated =
                ArgumentCaptor.forClass(ProductionRouteTemplate.class);
        verify(productionRouteTemplateMapper).updateById(updated.capture());
        assertThat(updated.getValue().getId()).isEqualTo("rt-1");
        assertThat(updated.getValue().getIsDefault()).isEqualTo(false);
    }

    // ══════════════════ 判据：信号映射写面（PG-033）══════════════════

    @Test
    @DisplayName("新增信号：两维都不给 ⇒ 422 逐条理由（死数据不得落库）；给一维即可")
    void createSignalRequiresAtLeastOneTarget() {
        assertThatThrownBy(() -> service.createSignal(body("signal", "罗马帘"), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(detailFields((BusinessException) e)).contains("curtain_type"));
        verify(productionRouteSignalMapper, never()).insert(any(ProductionRouteSignal.class));
    }

    @Test
    @DisplayName("新增信号：priority 缺省 = 该用途内最大 + 1（与「顺序即优先级」同口径）")
    void createSignalAssignsNextPriorityWithinPurpose() {
        when(productionRouteSignalMapper.selectList(any())).thenReturn(List.of(
                signal("s1", "帘头", "帘头", null, 1),
                signal("s2", "纱", "纱帘", null, 2),
                signal("s3", "韩褶", null, "韩褶", 1)));

        Map<String, Object> result = service.createSignal(
                body("signal", "罗马帘", "curtain_type", "罗马帘"), TENANT);

        assertThat(result.get("priority")).as("帘种用途内最大是 2 ⇒ 新行取 3（工艺行的 1 不算）").isEqualTo(3);
        assertThat(result.get("curtain_type")).isEqualTo("罗马帘");
        assertThat(result.get("craft")).isNull();
    }

    @Test
    @DisplayName("新增信号：同信号同用途重复 ⇒ 409；跨用途允许（「帘头」两行是设计）")
    void createSignalRejectsSamePurposeDuplicateButAllowsCrossPurpose() {
        when(productionRouteSignalMapper.selectList(any()))
                .thenReturn(List.of(signal("s1", "帘头", "帘头", null, 1)));

        assertThatThrownBy(() -> service.createSignal(
                body("signal", "帘头", "curtain_type", "纱帘"), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(409));

        // 跨用途（工艺侧）不撞：既有行是帘种行
        Map<String, Object> ok = service.createSignal(body("signal", "帘头", "craft", "平幔"), TENANT);
        assertThat(ok.get("craft")).isEqualTo("平幔");
    }

    @Test
    @DisplayName("新增信号：同用途 priority 撞档 ⇒ 422（撞档时「谁先命中」由内部 id 决定，对商家不可预测）")
    void createSignalRejectsPriorityCollisionWithinPurpose() {
        when(productionRouteSignalMapper.selectList(any())).thenReturn(List.of(
                signal("s1", "帘头", "帘头", null, 1),
                signal("s2", "纱", "纱帘", null, 2)));

        assertThatThrownBy(() -> service.createSignal(
                body("signal", "罗马帘", "curtain_type", "罗马帘", "priority", 1), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(detailFields((BusinessException) e)).contains("priority"));
        verify(productionRouteSignalMapper, never()).insert(any(ProductionRouteSignal.class));
    }

    @Test
    @DisplayName("改信号：把两维都清空 ⇒ 422（不得把一行变成死数据）；删信号 = 软删（deleted=1）")
    void updateAndDeleteSignalGuards() {
        ProductionRouteSignal row = signal("s1", "帘头", "帘头", null, 1);
        when(productionRouteSignalMapper.selectById("s1")).thenReturn(row);
        // lenient：本用例先撞「两维都清空」护栏（在唯一性校验之前就抛）⇒ 备而不用的桩是噪音
        lenient().when(productionRouteSignalMapper.selectList(any())).thenReturn(List.of(row));

        assertThatThrownBy(() -> service.updateSignal("s1",
                body("curtain_type", "", "craft", ""), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(detailFields((BusinessException) e)).contains("curtain_type"));

        Map<String, Object> deleted = service.deleteSignal("s1", TENANT);
        assertThat(deleted.get("deleted")).isEqualTo(true);
        ArgumentCaptor<ProductionRouteSignal> updated = ArgumentCaptor.forClass(ProductionRouteSignal.class);
        verify(productionRouteSignalMapper).updateById(updated.capture());
        assertThat(updated.getValue().getDeleted()).as("软删：谁在何时删掉哪条映射是排查错配的唯一证据").isEqualTo(1);
    }

    private static ProductionRouteSignal signal(String id, String keyword, String curtainType,
                                                String craft, int priority) {
        return ProductionRouteSignal.builder().id(id).tenantId(TENANT).signal(keyword)
                .curtainType(curtainType).craft(craft).priority(priority)
                .status("active").deleted(0).build();
    }
}
