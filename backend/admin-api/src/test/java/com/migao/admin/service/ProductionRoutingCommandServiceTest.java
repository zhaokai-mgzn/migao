package com.migao.admin.service;

// case_ids: PG-031, PG-032

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.entity.ProductionOperation;
import com.migao.admin.entity.ProductionOperationPriceVersion;
import com.migao.admin.entity.ProductionRouteSignal;
import com.migao.admin.entity.ProductionRouting;
import com.migao.admin.entity.ProductionRoutingVersion;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProductionOperationMapper;
import com.migao.admin.mapper.ProductionOperationPriceVersionMapper;
import com.migao.admin.mapper.ProductionRouteSignalMapper;
import com.migao.admin.mapper.ProductionRoutingMapper;
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
    private ProductionRoutingMapper productionRoutingMapper;
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
                productionRoutingMapper, productionRoutingVersionMapper, productionOperationMapper,
                productionRouteSignalMapper,
                new ProductionOperationQueryService(productionOperationMapper, null, null, null,
                        productionRouteSignalMapper));
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

    private static ProductionRouting routing(String id, String curtainType, String craft, List<String> ops) {
        return ProductionRouting.builder().id(id).tenantId(TENANT).curtainType(curtainType).craft(craft)
                .operations(ops).status("active").deleted(0).build();
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

    // ══════════════════ 判据：改序列五条护栏（PG-031）══════════════════

    @Test
    @DisplayName("护栏 1：空序列拒（422 + operations 逐条理由）")
    void emptySequenceIsRejected() {
        when(productionRoutingMapper.selectById("rt-1")).thenReturn(routing("rt-1", "布帘", "韩褶", List.of("布三边")));
        stubLibrary();

        assertThatThrownBy(() -> service.updateRouting("rt-1", body("operations", List.of()), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> {
                    BusinessException be = (BusinessException) e;
                    assertThat(be.getHttpStatus()).as("护栏失败统一 422").isEqualTo(422);
                    assertThat(detailFields(be)).contains("operations");
                });
        verify(productionRoutingMapper, never()).updateById(any(ProductionRouting.class));
        verify(productionRoutingVersionMapper, never()).insert(any(ProductionRoutingVersion.class));
    }

    @Test
    @DisplayName("护栏 2：引用工序库中不存在的工序拒（指名是哪一道）")
    void unknownOperationIsRejected() {
        when(productionRoutingMapper.selectById("rt-1")).thenReturn(routing("rt-1", "布帘", "韩褶", List.of("布三边")));
        stubLibrary();

        assertThatThrownBy(() -> service.updateRouting("rt-1",
                body("operations", List.of("布三边", "库里没有的工序", "外帘装袋")), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(detailFields((BusinessException) e)).contains("operations[1]"));
        verify(productionRoutingMapper, never()).updateById(any(ProductionRouting.class));
    }

    @Test
    @DisplayName("护栏 3：重复工序拒（同工序两次 ⇒ 工人按两遍单价拿钱）")
    void duplicateOperationIsRejected() {
        when(productionRoutingMapper.selectById("rt-1")).thenReturn(routing("rt-1", "布帘", "韩褶", List.of("布三边")));
        stubLibrary();

        assertThatThrownBy(() -> service.updateRouting("rt-1",
                body("operations", List.of("布三边", "外帘装袋", "布三边")), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(detailFields((BusinessException) e)).contains("operations[2]"));
        verify(productionRoutingMapper, never()).updateById(any(ProductionRouting.class));
    }

    @Test
    @DisplayName("护栏 4：至少一道必完工序（否则完工判定永远不成立 ⇒ 这张单永远完不了工）")
    void sequenceWithoutMustFinishOperationIsRejected() {
        when(productionRoutingMapper.selectById("rt-1")).thenReturn(routing("rt-1", "布帘", "韩褶", List.of("布三边")));
        stubLibrary();

        assertThatThrownBy(() -> service.updateRouting("rt-1",
                body("operations", List.of("布三边", "韩褶-布", "外帘发货")), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(detailFields((BusinessException) e)).contains("must_finish"));
        verify(productionRoutingMapper, never()).updateById(any(ProductionRouting.class));
    }

    @Test
    @DisplayName("护栏 5：合法序列 ⇒ seq 归一化为 1..N（存有序数组 + 响应逐位回读）且**落版本账**")
    void validSequenceIsNormalizedAndVersioned() {
        ProductionRouting existing = routing("rt-1", "布帘", "韩褶", List.of("布三边"));
        when(productionRoutingMapper.selectById("rt-1")).thenReturn(existing);
        stubLibrary();

        Map<String, Object> result = service.updateRouting("rt-1",
                body("operations", List.of("布三边", "韩褶-布", "外帘装袋")), TENANT);

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> steps = (List<Map<String, Object>>) result.get("operations");
        assertThat(steps).extracting((Map<String, Object> s) -> s.get("seq")).containsExactly(1, 2, 3);
        assertThat(steps).extracting((Map<String, Object> s) -> s.get("operation"))
                .containsExactly("布三边", "韩褶-布", "外帘装袋");
        assertThat(result.get("operation_count")).isEqualTo(3);

        ArgumentCaptor<ProductionRoutingVersion> version = ArgumentCaptor.forClass(ProductionRoutingVersion.class);
        verify(productionRoutingVersionMapper).insert(version.capture());
        assertThat(version.getValue().getRoutingId()).isEqualTo("rt-1");
        assertThat(version.getValue().getCurtainType()).isEqualTo("布帘");
        assertThat(version.getValue().getCraft()).isEqualTo("韩褶");
        assertThat(version.getValue().getOperationCount()).as("版本账记工序道数（对账少解析一次 JSON）").isEqualTo(3);
        assertThat(version.getValue().getOperations())
                .as("版本账存的是**变更后**的有序序列（seq = 下标 + 1，不单独存）")
                .isEqualTo(List.of("布三边", "韩褶-布", "外帘装袋"));
    }

    @Test
    @DisplayName("同序列重复提交 = 幂等空操作（不追加无意义的版本行，沿用单价版本账口径）")
    void sameSequenceIsIdempotentNoop() {
        when(productionRoutingMapper.selectById("rt-1"))
                .thenReturn(routing("rt-1", "布帘", "韩褶", List.of("布三边", "外帘装袋")));
        stubLibrary();

        service.updateRouting("rt-1", body("operations", List.of("布三边", "外帘装袋")), TENANT);

        verify(productionRoutingMapper).updateById(any(ProductionRouting.class));
        verify(productionRoutingVersionMapper, never()).insert(any(ProductionRoutingVersion.class));
    }

    @Test
    @DisplayName("跨租户 / 不存在的路线 ⇒ 404（不泄漏别的租户的路线存在性）")
    void unknownRoutingIsNotFound() {
        when(productionRoutingMapper.selectById("rt-x")).thenReturn(null);
        assertThatThrownBy(() -> service.updateRouting("rt-x", body("operations", List.of("布三边")), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(404));
    }

    // ══════════════════ 判据：新建路线（PG-031）══════════════════

    @Test
    @DisplayName("新建路线：operations 缺省 = 初版空序列；响应与 GET /routings 单项同构；落首行版本账")
    void createRoutingAllowsEmptyInitialSequence() {
        when(productionRoutingMapper.selectList(any())).thenReturn(List.of());
        when(productionOperationMapper.selectList(any())).thenReturn(List.of());

        Map<String, Object> result = service.createRouting(
                body("curtain_type", "罗马帘", "craft", "韩褶"), TENANT);

        assertThat(result.get("curtain_type")).isEqualTo("罗马帘");
        assertThat(result.get("craft")).isEqualTo("韩褶");
        assertThat(result.get("operation_count")).isEqualTo(0);
        assertThat(result.get("operations")).isEqualTo(List.of());
        ArgumentCaptor<ProductionRouting> inserted = ArgumentCaptor.forClass(ProductionRouting.class);
        verify(productionRoutingMapper).insert(inserted.capture());
        assertThat(inserted.getValue().getStatus()).isEqualTo("active");
        assertThat(inserted.getValue().getDeleted()).isEqualTo(0);
        verify(productionRoutingVersionMapper).insert(any(ProductionRoutingVersion.class));
    }

    @Test
    @DisplayName("新建路线：同「部位×工艺」已存在（含停用行）⇒ 409（否则撞 DB 唯一索引变 500）")
    void createRoutingRejectsDuplicateKey() {
        when(productionRoutingMapper.selectList(any()))
                .thenReturn(List.of(routing("rt-1", "布帘", "韩褶", List.of("布三边"))));

        assertThatThrownBy(() -> service.createRouting(body("curtain_type", "布帘", "craft", "韩褶"), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(409));
        verify(productionRoutingMapper, never()).insert(any(ProductionRouting.class));
    }

    // ══════════════════ 判据：信号映射写面（PG-032）══════════════════

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
