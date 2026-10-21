// case_ids: WH-001
package com.migao.admin.service;

import com.migao.admin.dto.WarehouseCreateRequest;
import com.migao.admin.entity.Warehouse;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.WarehouseMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

/**
 * 仓库（issue #7373 段 1）—— 「同租户只能有一个默认仓」与编码唯一。
 *
 * <p>默认仓由服务层「先取消旧默认、再设新的」+ 数据库**部分唯一索引**双保险：
 * 并发下第二个默认仓会被索引拦下并映射成可读冲突（不是 5xx）。</p>
 */
@DisplayName("仓库：建仓校验 / 默认仓切换 / 编码冲突")
class WarehouseServiceTest {

    private WarehouseMapper warehouseMapper;
    private WarehouseService service;

    @BeforeEach
    void setUp() {
        warehouseMapper = Mockito.mock(WarehouseMapper.class);
        service = new WarehouseService(warehouseMapper);
        when(warehouseMapper.selectList(any())).thenReturn(List.of());
    }

    private static WarehouseCreateRequest request(String code, String name, Boolean asDefault, String type) {
        WarehouseCreateRequest req = new WarehouseCreateRequest();
        req.setCode(code);
        req.setName(name);
        req.setIsDefault(asDefault);
        req.setWarehouseType(type);
        return req;
    }

    @Test
    @DisplayName("建仓：默认 store 类型 + 带上租户（租户只从上下文来）")
    void createDefaultsToStoreType() {
        Warehouse created = service.create(request("WH-A", "门店仓", null, null), 1L);

        assertThat(created.getWarehouseType()).isEqualTo(Warehouse.TYPE_STORE);
        assertThat(created.getTenantId()).isEqualTo(1L);
        assertThat(created.getStatus()).isEqualTo("active");
        Mockito.verify(warehouseMapper).insert(any(Warehouse.class));
    }

    @Test
    @DisplayName("未知类型 ⇒ 拒（类型是封闭集合，不靠前端自觉）")
    void unknownTypeRejected() {
        assertThatThrownBy(() -> service.create(request("WH-A", "门店仓", null, "shelf"), 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("仓库类型");
    }

    @Test
    @DisplayName("编码/名称必填")
    void codeAndNameRequired() {
        assertThatThrownBy(() -> service.create(request("  ", "门店仓", null, null), 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("仓编码");
        assertThatThrownBy(() -> service.create(request("WH-A", "", null, null), 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("仓名称");
    }

    @Test
    @DisplayName("设默认仓时把旧的默认仓取消（同租户只能有一个默认）")
    void settingDefaultClearsPrevious() {
        Warehouse old = new Warehouse();
        old.setId(9L);
        old.setTenantId(1L);
        old.setCode("WH-OLD");
        old.setIsDefault(true);
        when(warehouseMapper.selectList(any())).thenReturn(List.of(old));

        service.create(request("WH-NEW", "新默认仓", true, null), 1L);

        assertThat(old.getIsDefault()).as("旧默认仓必须被取消").isFalse();
        Mockito.verify(warehouseMapper).updateById(org.mockito.ArgumentMatchers.<Warehouse>any());
    }

    @Test
    @DisplayName("编码撞车 ⇒ 可读冲突（不是 5xx）")
    void duplicateCodeIsReadableConflict() {
        when(warehouseMapper.insert(any(Warehouse.class)))
                .thenThrow(new org.springframework.dao.DuplicateKeyException("uk_warehouses_code"));

        assertThatThrownBy(() -> service.create(request("WH-A", "门店仓", null, null), 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("仓编码已存在");
    }
}
