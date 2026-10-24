// case_ids: WH-002
package com.migao.admin.service;

import com.migao.admin.entity.Warehouse;
import com.migao.admin.mapper.WarehouseMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.dao.DuplicateKeyException;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 默认主仓播种（issue #7592）——「开箱就有仓可选」这一条链的四个面。
 *
 * <h2>病灶</h2>
 * `warehouses` 表在现网是 0 行（开租不种、商家面也没有建仓入口）⇒ 盘点单「出盘点任务」的仓库
 * 下拉只有占位项，一张盘点单也出不了。播种本身很简单，贵的部分是**幂等**与**不误伤**：
 *
 * <ol>
 *   <li><b>空仓租户</b> ⇒ 种一个（code/name 来自单一来源 {@link OnboardingInitialData}，
 *       `store` 类型、`is_default`）—— 种出来的值错了，盘点会挂到一个不存在的仓上；</li>
 *   <li><b>已有仓</b> ⇒ 幂等跳过，绝不种第二个（会撞 `uk_warehouses_single_default`，
 *       把商家自己设的默认仓挤掉）；</li>
 *   <li><b>并发入驻</b> ⇒ 唯一索引冲突映射成 0（不是 5xx —— 那会把整个开租事务打回滚）；</li>
 *   <li><b>后置条件探针</b>读的是行数：0 行 = 盘点没有仓可选（这是入驻 fail-closed 的依据）。</li>
 * </ol>
 *
 * <p>落库与真外键（`stocktakes.warehouse_id REFERENCES warehouses(id)`）由真库判据承担：
 * {@code NewTenantOnboardingCategoryRealDbTest#onboardingSeedsDefaultCategoryAndFirstProductSucceeds}。</p>
 */
@DisplayName("默认主仓播种：空仓种一个 / 已有仓幂等跳过 / 并发撞唯一索引不报错")
class WarehouseSeedServiceTest {

    private WarehouseMapper warehouseMapper;
    private WarehouseSeedService service;

    @BeforeEach
    void setUp() {
        warehouseMapper = mock(WarehouseMapper.class);
        service = new WarehouseSeedService(warehouseMapper);
    }

    @Test
    @DisplayName("空仓 ⇒ 种一个默认主仓（值来自单一来源、store 类型、is_default = true）")
    void seedsWhenTenantHasNoWarehouse() {
        when(warehouseMapper.selectCount(any())).thenReturn(0L);

        assertThat(service.seedDefaultWarehouse(42L)).isEqualTo(1);

        ArgumentCaptor<Warehouse> captor = ArgumentCaptor.forClass(Warehouse.class);
        verify(warehouseMapper).insert(captor.capture());
        Warehouse saved = captor.getValue();
        assertThat(saved.getTenantId()).as("租户只从入参来（不猜、不跨租户）").isEqualTo(42L);
        assertThat(saved.getCode()).isEqualTo(OnboardingInitialData.DEFAULT_WAREHOUSE_CODE);
        assertThat(saved.getName()).isEqualTo(OnboardingInitialData.DEFAULT_WAREHOUSE_NAME);
        assertThat(saved.getWarehouseType()).isEqualTo(Warehouse.TYPE_STORE);
        assertThat(saved.getIsDefault()).as("默认仓：出任务时不再让商家在多个仓里猜").isTrue();
        assertThat(saved.getStatus()).isEqualTo("active");
    }

    @Test
    @DisplayName("已有仓 ⇒ 幂等跳过（不种第二个、不挤掉商家自设的默认仓）")
    void skipsWhenTenantAlreadyHasWarehouse() {
        when(warehouseMapper.selectCount(any())).thenReturn(2L);

        assertThat(service.seedDefaultWarehouse(42L)).isZero();
        verify(warehouseMapper, never()).insert(any(Warehouse.class));
    }

    @Test
    @DisplayName("并发入驻撞唯一索引 ⇒ 幂等 0（不是 5xx，不把开租打回滚）")
    void duplicateKeyIsIdempotent() {
        when(warehouseMapper.selectCount(any())).thenReturn(0L);
        when(warehouseMapper.insert(any(Warehouse.class)))
                .thenThrow(new DuplicateKeyException("uk_warehouses_single_default"));

        assertThat(service.seedDefaultWarehouse(42L)).isZero();
    }

    @Test
    @DisplayName("后置条件探针：读的是行数（0 行 = 盘点没有仓可选）")
    void countWarehousesReadsRows() {
        when(warehouseMapper.selectCount(any())).thenReturn(1L);
        assertThat(service.countWarehouses(42L)).isEqualTo(1L);
    }
}
