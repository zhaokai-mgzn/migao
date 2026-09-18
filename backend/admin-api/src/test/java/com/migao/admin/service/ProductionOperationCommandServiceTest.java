package com.migao.admin.service;

// case_ids: PG-020

import com.migao.admin.entity.ProductionOperation;
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
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
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

    private ProductionOperationCommandService service() {
        // 读面用**真实对象**（只 mock Mapper）：响应形态 = 目录项形态（同一份 operationView），
        // 用 mock 会让「返回更新后的工序」退化成断言桩
        return new ProductionOperationCommandService(
                productionOperationMapper, priceVersionMapper,
                new ProductionOperationQueryService(productionOperationMapper, productionRoutingMapper));
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
}
