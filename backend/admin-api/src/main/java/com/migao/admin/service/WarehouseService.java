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

    /** 成品仓编码（V196 自动建的唯一缺省值；商家自建同码时自动顺延 CP2/CP3）。 */
    public static final String FINISHED_WAREHOUSE_CODE = "CP";
    /** 成品仓名称。 */
    public static final String FINISHED_WAREHOUSE_NAME = "成品仓";
    /** 原料仓编码（成品仓之外给商家参考的建仓缺省值；本服务不自动建原料仓）。 */
    public static final String MATERIAL_WAREHOUSE_CODE = "MAIN";

    /**
     * **成品仓（找不到就建一个）** —— 打包入库的前置条件（V196 / issue #7750）。
     *
     * <p>为什么要「找或建」而不是要求商家先建：打包是车间动作，工人不该因为「仓库档案没建」
     * 被打断（与 #7592「开租即种默认主仓」同一条产品口径）。建仓是幂等的：
     * 已存在 type=finished 的仓 ⇒ 直接用它；没有 ⇒ 用 {@link #FINISHED_WAREHOUSE_CODE} 占号，
     * 同号被占则顺延（{@code CP2}、{@code CP3}…）。</p>
     *
     * <p>并发安全：占号走 {@code ON CONFLICT DO NOTHING}（唯一冲突不会把事务打成 aborted），
     * 抢不到就回读「已有 type=finished 的仓」—— 两个首次打包请求只会建出一个仓。</p>
     */
    @Transactional
    public Warehouse ensureFinishedWarehouse(Long tenantId) {
        for (int attempt = 0; attempt < 5; attempt++) {
            Warehouse existing = firstOfType(tenantId, Warehouse.TYPE_FINISHED);
            if (existing != null) {
                return existing;
            }
            String code = FINISHED_WAREHOUSE_CODE;
            int suffix = 1;
            while (codeTaken(tenantId, code)) {
                code = FINISHED_WAREHOUSE_CODE + (++suffix);
            }
            warehouseMapper.claimWarehouse(tenantId, code, FINISHED_WAREHOUSE_NAME,
                    Warehouse.TYPE_FINISHED, "成品帘打包入库自动建仓（issue #7750）");
            Warehouse created = firstOfType(tenantId, Warehouse.TYPE_FINISHED);
            if (created != null) {
                log.info("[warehouse] 成品仓就绪 | tenant={} code={}", tenantId, created.getCode());
                return created;
            }
        }
        throw BusinessException.conflict("成品仓创建失败（并发占号）", "请重试；重复提交不会建出第二个成品仓");
    }

    /** 某类型的第一个仓（按 id 升序；单租户单成品仓由调用方口径保证）。 */
    public Warehouse firstOfType(Long tenantId, String warehouseType) {
        List<Warehouse> rows = warehouseMapper.selectList(new LambdaQueryWrapper<Warehouse>()
                .eq(Warehouse::getTenantId, tenantId)
                .eq(Warehouse::getWarehouseType, warehouseType)
                .eq(Warehouse::getStatus, "active")
                .orderByAsc(Warehouse::getId)
                .last("LIMIT 1"));
        return rows.isEmpty() ? null : rows.get(0);
    }

    private boolean codeTaken(Long tenantId, String code) {
        return warehouseMapper.exists(new LambdaQueryWrapper<Warehouse>()
                .eq(Warehouse::getTenantId, tenantId)
                .eq(Warehouse::getCode, code));
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
        if (!Warehouse.TYPES.contains(type)) {
            // 合法集 = 实体常量（与表 CHECK 同一份），不在这里再抄一遍字面量
            throw BusinessException.validationError("仓库类型必须是 " + String.join(" / ", Warehouse.TYPES));
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
