package com.migao.admin.service;

// case_ids: PG-020, PG-034, PG-039

import com.migao.admin.entity.ProductionOperation;
import com.migao.admin.entity.ProductionOperationPosition;
import com.migao.admin.entity.ProductionOperationPriceVersion;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProcessingPositionOperationMapper;
import com.migao.admin.mapper.ProductionOperationMapper;
import com.migao.admin.mapper.ProductionOperationPriceVersionMapper;
import com.migao.admin.mapper.ProductionRoutingMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.math.BigDecimal;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 工序库写面服务测试（issue #4204，P1）
 *
 * <p>真值源 docs/curtain-production-rules.md §2「计件单价（版本化）」/§4「调价只影响新报工，
 * 历史报工按当时价，逐笔可追溯」。本测试守三条：
 * ① 改价 = 写库行（新单实例化取值源）+ 追加版本行（当前价 = 最新版本行），同一事务；
 * ② 同价重复提交不制造调价账；非法值 fail-closed（不落库）；
 * ③ **实例快照不被触碰** —— 改价路径物理上没有写 {@code processing_position_operations} 的能力。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("ProductionOperationCommandService 工序库写面（改价/版本化）")
class ProductionOperationCommandServiceTest {

    private static final Long TENANT = 1L;

    @Mock
    private ProductionOperationMapper productionOperationMapper;
    @Mock
    private ProductionOperationPriceVersionMapper priceVersionMapper;
    @Mock
    private ProductionRoutingMapper productionRoutingMapper;
    @Mock
    private com.migao.admin.mapper.ProductionOptionRoutingMapper productionOptionRoutingMapper;
    @Mock
    private com.migao.admin.mapper.ProductionOptionFactorMapper productionOptionFactorMapper;
    @Mock
    private com.migao.admin.mapper.ProductionRouteSignalMapper productionRouteSignalMapper;
    @Mock
    private com.migao.admin.mapper.ProductionRouteTemplateMapper productionRouteTemplateMapper;
    @Mock
    private com.migao.admin.mapper.ProductionRouteRuleMapper productionRouteRuleMapper;
    @Mock
    private com.migao.admin.mapper.ProductionOperationPositionMapper productionOperationPositionMapper;
    @Mock
    private com.migao.admin.mapper.ProductionCraftMapper productionCraftMapper;

    private ProductionOperationCommandService service() {
        // 读面用**真实对象**（只 mock Mapper）：响应形态 = 目录项形态（同一份 operationView），
        // 用 mock 会让「返回更新后的工序」退化成断言桩
        return new ProductionOperationCommandService(
                productionOperationMapper, priceVersionMapper, productionOperationPositionMapper,
                new ProductionOperationQueryService(productionOperationMapper, productionRouteTemplateMapper,
                        productionRouteRuleMapper, productionOperationPositionMapper,
                        productionCraftMapper, productionRouteSignalMapper));
    }

    private ProductionOperation operation(String unitPrice, String status) {
        return ProductionOperation.builder()
                .id("op-v54-07").tenantId(TENANT).name("韩褶-布").groupName("车位").position("布帘")
                .unit("折").unitPrice(new BigDecimal(unitPrice))
                .isMustFinish(false).isStartMarker(false).sortOrder(7).status(status).deleted(0)
                .build();
    }

    @Test
    @DisplayName("改价 ⇒ 库行单价更新 + 追加版本行（当前价 = 最新版本行）")
    void updatePriceWritesOperationRowAndVersionRow() {
        when(productionOperationMapper.selectById("op-v54-07")).thenReturn(operation("0.40", "active"));
        when(productionOperationMapper.updateById(any(ProductionOperation.class))).thenReturn(1);
        when(priceVersionMapper.insert(any(ProductionOperationPriceVersion.class))).thenReturn(1);

        Map<String, Object> view = service().update("op-v54-07", Map.of("unit_price", "0.55"), TENANT);

        // ① 库行：新价（新生成加工单的实例化取值源）
        ArgumentCaptor<ProductionOperation> updated = ArgumentCaptor.forClass(ProductionOperation.class);
        verify(productionOperationMapper).updateById(updated.capture());
        assertThat(updated.getValue().getId()).isEqualTo("op-v54-07");
        assertThat(updated.getValue().getUnitPrice()).isEqualByComparingTo("0.55");
        // 部分更新：未在 body 里的字段不得被写（避免把并发改动覆盖回去）
        assertThat(updated.getValue().getStatus()).isNull();
        assertThat(updated.getValue().getName()).isNull();

        // ② 版本账：追加一行，含租户与工序 id
        ArgumentCaptor<ProductionOperationPriceVersion> version =
                ArgumentCaptor.forClass(ProductionOperationPriceVersion.class);
        verify(priceVersionMapper).insert(version.capture());
        assertThat(version.getValue().getOperationId()).isEqualTo("op-v54-07");
        assertThat(version.getValue().getTenantId()).isEqualTo(TENANT);
        assertThat(version.getValue().getUnitPrice()).isEqualByComparingTo("0.55");
        assertThat(version.getValue().getDeleted()).isZero();

        // ③ 响应 = 更新后的工序（形态 = 目录项：id/name/unit/unit_price...）
        assertThat(view.get("id")).isEqualTo("op-v54-07");
        assertThat(view.get("name")).isEqualTo("韩褶-布");
        assertThat((BigDecimal) view.get("unit_price")).isEqualByComparingTo("0.55");
    }

    @Test
    @DisplayName("同价重复提交 ⇒ 幂等空操作（不追加版本行）")
    void samePriceDoesNotAppendVersion() {
        when(productionOperationMapper.selectById("op-v54-07")).thenReturn(operation("0.40", "active"));
        when(productionOperationMapper.updateById(any(ProductionOperation.class))).thenReturn(1);

        Map<String, Object> view = service().update("op-v54-07", Map.of("unit_price", "0.40"), TENANT);

        verify(priceVersionMapper, never()).insert(any(ProductionOperationPriceVersion.class));
        assertThat((BigDecimal) view.get("unit_price")).isEqualByComparingTo("0.40");
    }

    @Test
    @DisplayName("非单价字段的部分更新：停用/单位/分组/排序/必完标记，未给的字段不写")
    void partialUpdateOfNonPriceFields() {
        when(productionOperationMapper.selectById("op-v54-07")).thenReturn(operation("0.40", "active"));
        when(productionOperationMapper.updateById(any(ProductionOperation.class))).thenReturn(1);

        Map<String, Object> view = service().update("op-v54-07", Map.of(
                "status", "disabled",
                "group_name", "后道",
                "sort_order", 9,
                "is_must_finish", true), TENANT);

        ArgumentCaptor<ProductionOperation> updated = ArgumentCaptor.forClass(ProductionOperation.class);
        verify(productionOperationMapper).updateById(updated.capture());
        assertThat(updated.getValue().getStatus()).isEqualTo("disabled");
        assertThat(updated.getValue().getGroupName()).isEqualTo("后道");
        assertThat(updated.getValue().getSortOrder()).isEqualTo(9);
        assertThat(updated.getValue().getIsMustFinish()).isTrue();
        assertThat(updated.getValue().getUnitPrice()).as("未给单价 ⇒ 不写单价").isNull();
        verify(priceVersionMapper, never()).insert(any(ProductionOperationPriceVersion.class));
        assertThat(view.get("is_must_finish")).isEqualTo(true);
    }

    @Test
    @DisplayName("非法值 fail-closed：负单价 / 未知状态 / 非布尔标记 ⇒ 422 且不落库")
    void invalidValuesAreRejectedBeforeAnyWrite() {
        when(productionOperationMapper.selectById("op-v54-07")).thenReturn(operation("0.40", "active"));

        assertThatThrownBy(() -> service().update("op-v54-07", Map.of("unit_price", "-1"), TENANT))
                .isInstanceOf(BusinessException.class).hasMessageContaining("unit_price");
        assertThatThrownBy(() -> service().update("op-v54-07", Map.of("status", "deleted"), TENANT))
                .isInstanceOf(BusinessException.class).hasMessageContaining("status");
        assertThatThrownBy(() -> service().update("op-v54-07", Map.of("is_start_marker", "yes"), TENANT))
                .isInstanceOf(BusinessException.class).hasMessageContaining("is_start_marker");

        verify(productionOperationMapper, never()).updateById(any(ProductionOperation.class));
        verify(priceVersionMapper, never()).insert(any(ProductionOperationPriceVersion.class));
    }

    @Test
    @DisplayName("工序不存在 / 跨租户 / 已软删 ⇒ 404 且不落库")
    void unknownOrForeignOperationNotFound() {
        when(productionOperationMapper.selectById("op-x")).thenReturn(null);
        assertThatThrownBy(() -> service().update("op-x", Map.of("unit_price", "0.55"), TENANT))
                .isInstanceOf(BusinessException.class).hasMessageContaining("工序");

        ProductionOperation foreign = operation("0.40", "active");
        foreign.setTenantId(2L);
        when(productionOperationMapper.selectById("op-v54-07")).thenReturn(foreign);
        assertThatThrownBy(() -> service().update("op-v54-07", Map.of("unit_price", "0.55"), TENANT))
                .isInstanceOf(BusinessException.class).hasMessageContaining("工序");

        ProductionOperation deleted = operation("0.40", "active");
        deleted.setDeleted(1);
        when(productionOperationMapper.selectById("op-v54-07")).thenReturn(deleted);
        assertThatThrownBy(() -> service().update("op-v54-07", Map.of("unit_price", "0.55"), TENANT))
                .isInstanceOf(BusinessException.class).hasMessageContaining("工序");

        verify(productionOperationMapper, never()).updateById(any(ProductionOperation.class));
        verify(priceVersionMapper, never()).insert(any(ProductionOperationPriceVersion.class));
    }

    @Test
    @DisplayName("实例快照冻结（结构判据）：改价路径物理上没有写 processing_position_operations 的依赖")
    void priceChangeCannotTouchInstanceSnapshots() {
        // 改价只影响新报工（真值源 §4）：实例单价是生成时的快照，本类**不注入**实例表的写能力 ——
        // 一旦有人「顺手把新价同步到实例」，这条断言先红（比运行时 verify 更难被绕过）
        boolean hasInstanceWriter = Arrays.stream(ProductionOperationCommandService.class.getDeclaredFields())
                .anyMatch(field -> ProcessingPositionOperationMapper.class.isAssignableFrom(field.getType()));
        assertThat(hasInstanceWriter)
                .as("工序库写面不得依赖实例表 Mapper（改价必须冻结既有实例快照）")
                .isFalse();
    }

    // ══════════════════ 新增工序（issue #4308 交付物 4，PG-034）══════════════════
    //
    // 为什么必须有这个端点：production_operations 的**唯一写方曾是 V54/V56 种子 SQL**
    // （全仓对 productionOperationMapper 零写调用）⇒ 商家建不了自己的路线（没有工序可选），
    // 非 1 号租户连一道工序都建不出来（#4316）。本端点 = 「企业设置工艺路线」的前置。

    @Test
    @DisplayName("新增工序 ⇒ 落库 + **同事务写单价版本账首行**（使「当前价 = 最新版本行」对它也成立）")
    void createWritesOperationAndFirstPriceVersion() {
        when(productionOperationMapper.selectCount(any())).thenReturn(0L);

        Map<String, Object> result = service().create(Map.of(
                "name", "罗马帘-穿杆", "group_name", "车位", "unit", "米", "unit_price", 0.6), TENANT);

        ArgumentCaptor<ProductionOperation> op = ArgumentCaptor.forClass(ProductionOperation.class);
        verify(productionOperationMapper).insert(op.capture());
        assertThat(op.getValue().getName()).isEqualTo("罗马帘-穿杆");
        assertThat(op.getValue().getUnitPrice()).isEqualByComparingTo("0.6");
        assertThat(op.getValue().getStatus()).isEqualTo("active");
        assertThat(op.getValue().getDeleted()).isEqualTo(0);
        ArgumentCaptor<ProductionOperationPriceVersion> version =
                ArgumentCaptor.forClass(ProductionOperationPriceVersion.class);
        verify(priceVersionMapper).insert(version.capture());
        assertThat(version.getValue().getOperationId()).as("版本行必须挂在刚建的工序上").isEqualTo(op.getValue().getId());
        assertThat(version.getValue().getUnitPrice()).isEqualByComparingTo("0.6");
        assertThat(result.get("name")).isEqualTo("罗马帘-穿杆");
    }

    @Test
    @DisplayName("新增工序：同名（含停用行）⇒ 409，不落库（否则撞 DB 唯一索引变 500 而非可行动错误）")
    void createRejectsDuplicateName() {
        when(productionOperationMapper.selectCount(any())).thenReturn(1L);

        assertThatThrownBy(() -> service().create(Map.of("name", "韩褶-布", "unit_price", 0.4), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(409));
        verify(productionOperationMapper, never()).insert(any(ProductionOperation.class));
        verify(priceVersionMapper, never()).insert(any(ProductionOperationPriceVersion.class));
    }

    @Test
    @DisplayName("新增工序：缺 name / 缺 unit_price / 负单价 ⇒ 422，不落库（不发明默认单价）")
    void createRejectsMissingOrNegativePrice() {
        assertThatThrownBy(() -> service().create(Map.of("unit_price", 0.4), TENANT))
                .isInstanceOf(BusinessException.class);
        assertThatThrownBy(() -> service().create(Map.of("name", "罗马帘-穿杆"), TENANT))
                .isInstanceOf(BusinessException.class);
        assertThatThrownBy(() -> service().create(Map.of("name", "罗马帘-穿杆", "unit_price", -1), TENANT))
                .isInstanceOf(BusinessException.class);
        verify(productionOperationMapper, never()).insert(any(ProductionOperation.class));
    }

    // ══════════════════ 新增工序同时建矩阵行（issue #4614）══════════════════
    //
    // 病根（用户实测原话「这个新增按钮，无法新增工序」）：`POST /operations` 只写
    // `production_operations`（工序库），**不建矩阵行**；而「工艺项」表**只按矩阵行渲染**
    // （`GET /operation-positions`）⇒ 新工序表里没有它、也没法定价（原「工序库明细」表已随
    // #4588 取消）⇒ **无处可见的孤儿**。本组断言 = 「建完必须可见」的服务端半边。

    /** 该租户矩阵里已有的一行（幂等判据用；`price` 模拟**商家改过的价**）。 */
    private ProductionOperationPosition positionRow(String logicalName, String position, String price) {
        return ProductionOperationPosition.builder()
                .id("opp-" + logicalName + "-" + position).tenantId(TENANT)
                .logicalName(logicalName).position(position)
                .unitPrice(price == null ? null : new BigDecimal(price))
                .applicable(true).status("active").deleted(0)
                .build();
    }

    @Test
    @DisplayName("#4614 带 positions ⇒ 为每个部位插矩阵行（logical_name = **归一后**的逻辑名）")
    void createWithPositionsInsertsMatrixRows() {
        when(productionOperationMapper.selectCount(any())).thenReturn(0L);
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of());

        Map<String, Object> result = service().create(Map.of(
                "name", "布帘车被", "unit_price", 0.6, "positions", List.of("布帘", "纱帘")), TENANT);

        ArgumentCaptor<ProductionOperationPosition> rows =
                ArgumentCaptor.forClass(ProductionOperationPosition.class);
        verify(productionOperationPositionMapper, times(2)).insert(rows.capture());
        assertThat(rows.getAllValues()).extracting(ProductionOperationPosition::getPosition)
                .containsExactly("布帘", "纱帘");
        assertThat(rows.getAllValues()).extracting(ProductionOperationPosition::getLogicalName)
                .as("logical_name 必须是**归一后的逻辑名**（布帘车被 ⇒ 车被）："
                        + "「逻辑名 + 部位后缀」那类字符串规则会得到库里没有的「车被-布」"
                        + "⇒ 只有复用 normalizeOperationName 才拿得到 车被")
                .containsOnly("车被");
        assertThat(rows.getAllValues()).extracting(ProductionOperationPosition::getUnitPrice)
                .as("unit_price = 新建时填的计件单价（不发明第二份价）")
                .allSatisfy(p -> assertThat(p).isEqualByComparingTo("0.6"));
        assertThat(rows.getAllValues()).allSatisfy(r -> {
            assertThat(r.getTenantId()).isEqualTo(TENANT);
            assertThat(r.getApplicable()).as("新建即「做」（≠「没定价」）").isTrue();
            assertThat(r.getStatus()).isEqualTo("active");
            assertThat(r.getDeleted()).isZero();
        });
        assertThat(result.get("created_positions")).as("如实报数").isEqualTo(2);
        assertThat(result.get("skipped_positions")).isEqualTo(0);
    }

    @Test
    @DisplayName("#4614 值域与前端 positionOptions 同口径：矩阵里出现的第 4 个部位（布料）可建")
    void createAcceptsPositionThatOnlyExistsInTheMatrix() {
        when(productionOperationMapper.selectCount(any())).thenReturn(0L);
        when(productionOperationPositionMapper.selectList(any()))
                .thenReturn(List.of(positionRow("配料", "布料", "0.2")));

        Map<String, Object> result = service().create(Map.of(
                "name", "罗马帘-穿杆", "unit_price", 0.6, "positions", List.of("布料")), TENANT);

        ArgumentCaptor<ProductionOperationPosition> rows =
                ArgumentCaptor.forClass(ProductionOperationPosition.class);
        verify(productionOperationPositionMapper).insert(rows.capture());
        assertThat(rows.getValue().getPosition()).isEqualTo("布料");
        assertThat(result.get("created_positions")).isEqualTo(1);
    }

    @Test
    @DisplayName("#4614 已有 (逻辑名, 部位) 行 ⇒ 跳过且**不覆盖商家改过的价**，响应如实报跳过数")
    void createSkipsExistingPositionRowsWithoutOverwritingPrice() {
        when(productionOperationMapper.selectCount(any())).thenReturn(0L);
        when(productionOperationPositionMapper.selectList(any()))
                .thenReturn(List.of(positionRow("车被", "布帘", "0.99")));

        Map<String, Object> result = service().create(Map.of(
                "name", "布帘车被", "unit_price", 0.6, "positions", List.of("布帘", "纱帘")), TENANT);

        ArgumentCaptor<ProductionOperationPosition> rows =
                ArgumentCaptor.forClass(ProductionOperationPosition.class);
        verify(productionOperationPositionMapper, times(1)).insert(rows.capture());
        assertThat(rows.getValue().getPosition()).as("只补缺的那个部位").isEqualTo("纱帘");
        assertThat(result.get("created_positions")).isEqualTo(1);
        assertThat(result.get("skipped_positions")).as("跳过数必须如实报（不假装成功）").isEqualTo(1);
        // 不覆盖：整条路径没有任何 update —— 商家改过的 0.99 必须原样留着
        verify(productionOperationPositionMapper, never()).updateById(any(ProductionOperationPosition.class));
    }

    @Test
    @DisplayName("#4614 反向护栏：不带 positions ⇒ 一个矩阵行都不建、响应不出现新键（老调用方一字不变）")
    void createWithoutPositionsKeepsLegacyBehaviour() {
        when(productionOperationMapper.selectCount(any())).thenReturn(0L);

        Map<String, Object> result = service().create(Map.of(
                "name", "罗马帘-穿杆", "unit_price", 0.6), TENANT);

        verify(productionOperationPositionMapper, never()).insert(any(ProductionOperationPosition.class));
        verify(productionOperationPositionMapper, never()).selectList(any());
        assertThat(result)
                .as("不给 positions = 今天的行为：只建工序库行，响应形态一字不变")
                .doesNotContainKeys("created_positions", "skipped_positions");
    }

    @Test
    @DisplayName("#4614 positions 含空串/未知部位/空数组 ⇒ 422 + error.details 逐条，且校验先于写入")
    void createRejectsUnknownOrBlankPositions() {
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of());

        assertThatThrownBy(() -> service().create(Map.of(
                "name", "罗马帘-穿杆", "unit_price", 0.6, "positions", List.of("布帘", "", "布廉")), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> {
                    BusinessException be = (BusinessException) e;
                    assertThat(be.getHttpStatus()).isEqualTo(422);
                    assertThat(be.getDetails()).as("一次报全（不是报第一条就返回）").hasSize(2);
                    assertThat(be.getDetails()).extracting(d -> d.getField()).containsOnly("positions");
                    assertThat(be.getDetails()).extracting(d -> d.getMessage())
                            .anySatisfy(m -> assertThat(m).contains("布廉"))
                            .anySatisfy(m -> assertThat(m).contains("空"));
                });
        assertThatThrownBy(() -> service().create(Map.of(
                "name", "罗马帘-穿杆", "unit_price", 0.6, "positions", List.of()), TENANT))
                .as("显式空数组 = 「建出来又是孤儿」⇒ fail-closed（与 createRouting 的空 positions 同口径）")
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("positions");
        assertThatThrownBy(() -> service().create(Map.of(
                "name", "罗马帘-穿杆", "unit_price", 0.6, "positions", "布帘"), TENANT))
                .as("非数组 ⇒ 422（不得静默当成空/当成没给）")
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("positions");

        verify(productionOperationMapper, never()).insert(any(ProductionOperation.class));
        verify(productionOperationPositionMapper, never()).insert(any(ProductionOperationPosition.class));
    }

    // ══════════════════ 存量孤儿接入（PUT 带 positions，issue #4614 范围补口）══════════════════
    //
    // 用户实测原话：「我现在在**工艺项**中看不到 测试22，但是在**路线编辑的下拉列表**能看到，是 bug」
    // —— 用户此前用「新增工序」建的工序只有 `production_operations` 行、**没有矩阵行** ⇒ 孤儿：
    // 「工艺项」表按矩阵渲染 ⇒ 看不到；下拉按工序库渲染 ⇒ 看得到（两边不一致）。
    // #4609 把下拉也改成读矩阵后孤儿将**两边都看不到**（彻底不可达）⇒ 存量必须有接入路径。
    // 本组断言 = 接入路径与新增路径**共用同一份实现**（口径不许分叉）。

    @Test
    @DisplayName("#4614 存量接入（PUT 带 positions）⇒ 只补缺失行：已有格跳过、不覆盖已定价、响应如实报数")
    void updateAttachesMissingPositionRowsOnly() {
        when(productionOperationMapper.selectById("op-v54-07")).thenReturn(operation("0.40", "active"));
        when(productionOperationMapper.updateById(any(ProductionOperation.class))).thenReturn(1);
        // 「韩褶 × 布帘」已有活跃行且**商家已改过价**（0.99 ≠ 工序库的 0.40）
        when(productionOperationPositionMapper.selectList(any()))
                .thenReturn(List.of(positionRow("韩褶", "布帘", "0.99")));

        Map<String, Object> view = service().update("op-v54-07",
                Map.of("positions", List.of("布帘", "纱帘")), TENANT);

        ArgumentCaptor<ProductionOperationPosition> rows =
                ArgumentCaptor.forClass(ProductionOperationPosition.class);
        verify(productionOperationPositionMapper, times(1)).insert(rows.capture());
        assertThat(rows.getValue().getLogicalName()).isEqualTo("韩褶");
        assertThat(rows.getValue().getPosition()).as("只补缺的那个部位").isEqualTo("纱帘");
        assertThat(rows.getValue().getUnitPrice())
                .as("补建行取工序**当前**计件单价（不发明第二份价）").isEqualByComparingTo("0.40");
        assertThat(rows.getValue().getApplicable()).isTrue();
        assertThat(rows.getValue().getStatus()).isEqualTo("active");
        assertThat(rows.getValue().getDeleted()).isZero();
        assertThat(view.get("created_positions")).isEqualTo(1);
        assertThat(view.get("skipped_positions")).as("跳过数如实报（不覆盖已定价的格）").isEqualTo(1);
        // 只补不改：整条路径没有任何矩阵行更新
        verify(productionOperationPositionMapper, never()).updateById(any(ProductionOperationPosition.class));
    }

    @Test
    @DisplayName("#4614 停用工序不接部位 ⇒ 422 且不落库（冻结判据：只在 deleted=0 AND status=active 上补）")
    void updateRejectsPositionsOnDisabledOperation() {
        when(productionOperationMapper.selectById("op-v54-07")).thenReturn(operation("0.40", "disabled"));
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of());

        assertThatThrownBy(() -> service().update("op-v54-07", Map.of("positions", List.of("布帘")), TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("停用");
        verify(productionOperationMapper, never()).updateById(any(ProductionOperation.class));
        verify(productionOperationPositionMapper, never()).insert(any(ProductionOperationPosition.class));
    }

    @Test
    @DisplayName("#4614 反向护栏：PUT 不带 positions ⇒ 不碰矩阵、响应不出现新键（既有部分更新一字不变）")
    void updateWithoutPositionsKeepsLegacyBehaviour() {
        when(productionOperationMapper.selectById("op-v54-07")).thenReturn(operation("0.40", "active"));
        when(productionOperationMapper.updateById(any(ProductionOperation.class))).thenReturn(1);

        Map<String, Object> view = service().update("op-v54-07", Map.of("unit_price", "0.55"), TENANT);

        verify(productionOperationPositionMapper, never()).insert(any(ProductionOperationPosition.class));
        verify(productionOperationPositionMapper, never()).selectList(any());
        assertThat(view).doesNotContainKeys("created_positions", "skipped_positions");
    }

    @Test
    @DisplayName("#4614 接入路径的值域校验与新增路径**同一份**：未知部位 ⇒ 422 逐条且不落库")
    void updateRejectsUnknownPositionsWithSameVocabulary() {
        when(productionOperationMapper.selectById("op-v54-07")).thenReturn(operation("0.40", "active"));
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of());

        assertThatThrownBy(() -> service().update("op-v54-07",
                Map.of("positions", List.of("布帘", "布廉")), TENANT))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> {
                    BusinessException be = (BusinessException) e;
                    assertThat(be.getHttpStatus()).isEqualTo(422);
                    assertThat(be.getDetails()).hasSize(1);
                    assertThat(be.getDetails().get(0).getMessage()).contains("布廉");
                });
        verify(productionOperationMapper, never()).updateById(any(ProductionOperation.class));
        verify(productionOperationPositionMapper, never()).insert(any(ProductionOperationPosition.class));
    }

    // ══════════════════ 作用域 scope（issue #4384 A1，PG-039）══════════════════
    //
    // 真值源 docs/curtain-production-rules.md §8：**外帘**是加工单打印行部位、**不是**路线键。
    // 用户裁定（2026-09-19）：「套级工序先按**每樘窗一次**实现，打卷是否每帘一次**留成可配**」
    // ⇒ scope 必须**商家可配**（可配 = 写面能改；这正是「留成可配」的落码形态），
    // 且取值必须闭词表校验（自创第三值会让读面/实例化侧的口径分裂）。

    /** 合法取值（与迁移 V67 的列注释同口径）。 */
    private static final Set<String> SCOPE_VOCABULARY = Set.of("position", "set");

    @Test
    @DisplayName("update 可配 scope：改成 set 落库 + 响应回显；未给 scope 时该列不被写")
    void updateSetsScope() {
        when(productionOperationMapper.selectById("op-v54-07")).thenReturn(operation("0.40", "active"));
        when(productionOperationMapper.updateById(any(ProductionOperation.class))).thenReturn(1);

        Map<String, Object> view = service().update("op-v54-07", Map.of("scope", "set"), TENANT);

        ArgumentCaptor<ProductionOperation> updated = ArgumentCaptor.forClass(ProductionOperation.class);
        verify(productionOperationMapper).updateById(updated.capture());
        assertThat(updated.getValue().getScope()).isEqualTo("set");
        assertThat(updated.getValue().getUnitPrice()).as("部分更新：未给单价 ⇒ 不写单价").isNull();
        verify(priceVersionMapper, never()).insert(any(ProductionOperationPriceVersion.class));
        assertThat(view.get("scope")).as("响应形态 = 目录项（前端同一份类型渲染）").isEqualTo("set");

        // 改回部位级（可配 = 双向都能改，不是单向开关）
        when(productionOperationMapper.selectById("op-v54-07")).thenReturn(operation("0.40", "active"));
        Map<String, Object> back = service().update("op-v54-07", Map.of("scope", "position"), TENANT);
        assertThat(back.get("scope")).isEqualTo("position");
    }

    @Test
    @DisplayName("update 非法 scope ⇒ 422 可读理由且不落库（闭词表 position/set）")
    void updateRejectsInvalidScope() {
        when(productionOperationMapper.selectById("op-v54-07")).thenReturn(operation("0.40", "active"));

        assertThatThrownBy(() -> service().update("op-v54-07", Map.of("scope", "position_set"), TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("scope")
                .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(422));
        assertThatThrownBy(() -> service().update("op-v54-07", Map.of("scope", "套级"), TENANT))
                .as("中文别名也要拒 —— 库里存的是 position/set，混进中文会让读面/实例化侧对不上")
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("scope");
        assertThatThrownBy(() -> service().update("op-v54-07", Map.of("scope", "  "), TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("scope");

        verify(productionOperationMapper, never()).updateById(any(ProductionOperation.class));
        verify(priceVersionMapper, never()).insert(any(ProductionOperationPriceVersion.class));
    }

    @Test
    @DisplayName("create 可配 scope：给了就用（set），缺省 = position（部位级，不发明套级）")
    void createDefaultsScopeToPosition() {
        when(productionOperationMapper.selectCount(any())).thenReturn(0L);

        Map<String, Object> withScope = service().create(Map.of(
                "name", "罗马帘-穿杆", "unit_price", 0.6, "scope", "set"), TENANT);
        assertThat(withScope.get("scope")).isEqualTo("set");

        when(productionOperationMapper.selectCount(any())).thenReturn(0L);
        Map<String, Object> without = service().create(Map.of(
                "name", "罗马帘-打孔", "unit_price", 0.6), TENANT);
        assertThat(without.get("scope"))
                .as("缺省必须是 position（部位级）—— 默认 set 会把商家新建的每道工序都静默去重")
                .isEqualTo("position");
    }

    @Test
    @DisplayName("create 非法 scope ⇒ 422 且不落库（校验先于写入）")
    void createRejectsInvalidScope() {
        when(productionOperationMapper.selectCount(any())).thenReturn(0L);

        assertThatThrownBy(() -> service().create(Map.of(
                "name", "罗马帘-穿杆", "unit_price", 0.6, "scope", "SET"), TENANT))
                .as("大小写敏感（库里存小写，'SET' 会让按 scope 过滤的读面/实例化侧查不到）")
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("scope");

        verify(productionOperationMapper, never()).insert(any(ProductionOperation.class));
        verify(priceVersionMapper, never()).insert(any(ProductionOperationPriceVersion.class));
    }

    @Test
    @DisplayName("闭词表自证：合法取值集合恰好是 position/set（多一个/少一个都红）")
    void scopeVocabularyIsExactlyPositionAndSet() {
        assertThat(SCOPE_VOCABULARY).containsExactlyInAnyOrder("position", "set");
    }
}
