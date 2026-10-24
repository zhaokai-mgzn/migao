package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.dto.WarehouseCreateRequest;
import com.migao.admin.entity.Warehouse;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.WarehouseMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

/**
 * 仓库（issue #7373，P1-1 段 1）：建仓 / 列仓 / 默认仓。
 *
 * <p>「同租户只能有一个默认仓」由**部分唯一索引**兜住：服务层先把旧的默认仓取消，再设新的；
 * 并发下唯一索引会拦下第二个 —— 那种情况映射成可读 409，不是 5xx。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class WarehouseService {

    private final WarehouseMapper warehouseMapper;

    /** 列表（默认仓排最前，便于上屏）。 */
    public List<Warehouse> list() {
        return warehouseMapper.selectList(new LambdaQueryWrapper<Warehouse>()
                .orderByDesc(Warehouse::getIsDefault)
                .orderByAsc(Warehouse::getCode));
    }

    /** 建仓（编码同租户唯一；`isDefault` 为真时把旧的默认仓取消）。 */
    @Transactional
    public Warehouse create(WarehouseCreateRequest request, Long tenantId) {
        if (request.getCode() == null || request.getCode().isBlank()) {
            throw BusinessException.validationError("仓编码不能为空");
        }
        if (request.getName() == null || request.getName().isBlank()) {
            throw BusinessException.validationError("仓名称不能为空");
        }
        String type = request.getWarehouseType() == null ? Warehouse.TYPE_STORE : request.getWarehouseType();
        if (!List.of(Warehouse.TYPE_STORE, Warehouse.TYPE_PROCESSING).contains(type)) {
            throw BusinessException.validationError("仓库类型必须是 store 或 processing");
        }
        boolean asDefault = Boolean.TRUE.equals(request.getIsDefault());
        if (asDefault) {
            clearExistingDefault(tenantId);
        }
        Warehouse warehouse = new Warehouse();
        warehouse.setTenantId(tenantId);
        warehouse.setCode(request.getCode().trim());
        warehouse.setName(request.getName().trim());
        warehouse.setWarehouseType(type);
        warehouse.setIsDefault(asDefault);
        warehouse.setStatus("active");
        warehouse.setRemark(request.getRemark());
        try {
            warehouseMapper.insert(warehouse);
        } catch (DuplicateKeyException duplicate) {
            // 编码撞车 或 并发建了两个默认仓（两个部分唯一索引都走这里）⇒ 可读冲突，不是 5xx
            throw BusinessException.validationError("仓编码已存在，或并发设置了第二个默认仓，请刷新后重试");
        }
        log.info("[warehouse] 建仓 | tenant={} code={} default={}", tenantId, warehouse.getCode(), asDefault);
        return warehouse;
    }

    /** 默认仓（没有则 null —— 段 1 不自动建，缺省由调用方明说）。 */
    public Warehouse defaultWarehouse(Long tenantId) {
        List<Warehouse> rows = warehouseMapper.selectList(new LambdaQueryWrapper<Warehouse>()
                .eq(Warehouse::getTenantId, tenantId)
                .eq(Warehouse::getIsDefault, true));
        return rows.isEmpty() ? null : rows.get(0);
    }

    /** 必填校验：单据要落仓时必须能定位到仓。 */
    public Warehouse require(Long warehouseId) {
        Warehouse warehouse = warehouseMapper.selectById(warehouseId);
        if (warehouse == null) {
            throw BusinessException.notFound("仓库");
        }
        return warehouse;
    }

    private void clearExistingDefault(Long tenantId) {
        for (Warehouse existing : warehouseMapper.selectList(new LambdaQueryWrapper<Warehouse>()
                .eq(Warehouse::getTenantId, tenantId)
                .eq(Warehouse::getIsDefault, true))) {
            existing.setIsDefault(false);
            warehouseMapper.updateById(existing);
        }
    }
}
