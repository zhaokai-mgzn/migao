package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.dto.WarehouseLocationCreateRequest;
import com.migao.admin.dto.WarehouseLocationUpdateRequest;
import com.migao.admin.dto.WarehouseLocationView;
import com.migao.admin.entity.Warehouse;
import com.migao.admin.entity.WarehouseLocation;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.FinishedGoodsStockMapper;
import com.migao.admin.mapper.WarehouseLocationMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.OffsetDateTime;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Objects;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * 仓位（V196，issue #7750）—— 成品仓的货位分配与档案管理（issue #7785）。
 *
 * <h3>分配口径（一句话：区域 A 内最小空闲号）</h3>
 * <p>先复用**已释放**的仓位（发货/撤销打包后释放），都占满才按序号新增
 * （{@code A-01}、{@code A-02}…）—— 不按「总数取最大」也不按「随机」：
 * 前者会一进一出就涨号、仓位上永远只增不减；后者让仓管没法按号找货。</p>
 *
 * <h3>并发（为什么「找空闲」和「占位」是两步）</h3>
 * <p>「找空闲」只是**推荐**：两个打包请求可能同时算出同一个空闲号。真正的互斥在
 * {@code finished_goods_stock} 的局部唯一索引（{@code (tenant_id, bin_code) WHERE status='in_stock'}）——
 * 插入由 {@code FinishedGoodsStockMapper#claimInStock} 的 {@code ON CONFLICT DO NOTHING} 原子完成，
 * 抢不到（返回 {@code null}）就回来换下一个空闲号。**本类不做占位**，只给候选。</p>
 *
 * <h3>档案管理（issue #7785，出库单页「仓位管理」）</h3>
 * <ul>
 *   <li><b>新建</b>：仓位号统一大写（{@code a-01} = {@code A-01}），只允许字母 / 数字 / 短横线 / 下划线；
 *       成品仓不存在时自动建（与打包同一 {@code ensureFinishedWarehouse}）—— 商家可以先把货架建好；</li>
 *   <li><b>占用判定</b>：只看 {@code finished_goods_stock} 的 {@code in_stock} 行（按 {@code bin_code} 关联），
 *       仓位表上**不存**「占用」标志列：那会是第二份真相，发货 / 撤销漏改一次就永久占位；</li>
 *   <li><b>占用中禁止改号 / 删除</b>：在库行与已贴标签认的都是这个号（{@code bin_code} 快照）；
 *       区域名 / 备注 / 停用不受影响；</li>
 *   <li><b>停用</b>：不再参与自动分配（分配查询只看 {@code status='active'}），已占用库存不受影响，可重新启用；</li>
 *   <li><b>删除</b>：软删（历史单据保留 {@code bin_code} 快照），仅空闲仓位可删。</li>
 * </ul>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class WarehouseLocationService {

    /** 成品仓默认区域（新号段在这里顺延）。 */
    public static final String DEFAULT_ZONE_CODE = "A";
    /** 默认区域名称（展示用）。 */
    public static final String DEFAULT_ZONE_NAME = "成品区";

    /** 启用（参与自动分配）。 */
    public static final String STATUS_ACTIVE = "active";
    /** 停用（不参与自动分配；已占用库存不受影响）。 */
    public static final String STATUS_INACTIVE = "inactive";

    /** 找候选仓位的尝试上限（每次「找 → 占」失败都换下一个候选；正常 1 次内命中）。 */
    private static final int ALLOCATE_ATTEMPTS = 8;

    /** 仓位号形态（统一大写后校验）：`A-01` / `B_02` 都合法，中文 / 空格 / 冒号不合法。 */
    private static final Pattern BIN_CODE_PATTERN = Pattern.compile("^[A-Z0-9][A-Z0-9_-]{0,31}$");
    /** 区域编码形态（最多 16 位，与列宽一致）。 */
    private static final Pattern ZONE_CODE_PATTERN = Pattern.compile("^[A-Z0-9][A-Z0-9_-]{0,15}$");
    private static final int ZONE_NAME_MAX_LENGTH = 32;
    private static final int REMARK_MAX_LENGTH = 255;

    private final WarehouseLocationMapper locationMapper;
    private final FinishedGoodsStockMapper stockMapper;
    private final WarehouseService warehouseService;

    // ============================================================ 分配（打包入库）

    /**
     * 取一个**候选**空闲仓位（已存在的最小空闲号；全占满 ⇒ 建下一个号并返回）。
     *
     * <p>「空闲」= 没有任何 {@code in_stock} 成品占着它（由 {@code WarehouseLocationMapper} 的
     * {@code NOT EXISTS} 判定）—— 仓位表上**没有**单独的「占用」列：那会是第二份真相，
     * 发货/撤销漏改一次就永久占位。</p>
     */
    public WarehouseLocation nextFreeBin(Long tenantId, Long warehouseId) {
        for (int attempt = 0; attempt < ALLOCATE_ATTEMPTS; attempt++) {
            WarehouseLocation free = locationMapper.selectFirstFreeBin(tenantId, warehouseId);
            if (free != null) {
                return free;
            }
            int next = locationMapper.countBinsInZone(tenantId, warehouseId, DEFAULT_ZONE_CODE) + 1;
            String code = String.format(Locale.ROOT, "%s-%02d", DEFAULT_ZONE_CODE, next);
            // 原子占号：同号已存在 ⇒ 0 行（不抛异常，事务仍可用），下一轮重算
            locationMapper.claimBin(tenantId, warehouseId, DEFAULT_ZONE_CODE, DEFAULT_ZONE_NAME, code);
            WarehouseLocation created = locationMapper.selectByBinCode(tenantId, code);
            if (created != null) {
                return created;
            }
        }
        throw BusinessException.conflict("成品仓位分配失败（连续 " + ALLOCATE_ATTEMPTS + " 次占号冲突）",
                "请重试；重复提交不会让同一个仓位放两件成品");
    }

    // ============================================================ 档案读面（出库单页「仓位管理」）

    /**
     * 仓位档案清单（按仓位号排序）。
     *
     * @param includeInactive 是否包含停用仓位（管理模式要看到并重新启用它们；默认只给可分配的 active）
     */
    public List<WarehouseLocationView> listView(Long tenantId, Long warehouseId, boolean includeInactive) {
        List<WarehouseLocation> rows = locationMapper.selectList(new LambdaQueryWrapper<WarehouseLocation>()
                .eq(WarehouseLocation::getTenantId, tenantId)
                .eq(warehouseId != null, WarehouseLocation::getWarehouseId, warehouseId)
                .eq(!includeInactive, WarehouseLocation::getStatus, STATUS_ACTIVE)
                .orderByAsc(WarehouseLocation::getBinCode));
        // 一次查全租户的在库仓位号（不按 500 行截断，否则第 501 件在库会让对应仓位显示成「空闲」）
        Set<String> occupied = new HashSet<>(stockMapper.selectOccupiedBinCodes(tenantId));
        return rows.stream().map(row -> toView(row, occupied.contains(row.getBinCode()))).toList();
    }

    // ============================================================ 档案写面

    /**
     * 新建仓位。仓位号租户内唯一（DB 唯一索引兜底）；成品仓不存在时自动建（写操作建前置，
     * **不是** GET 的副作用 —— 读面仍然只读）。
     */
    @Transactional
    public WarehouseLocationView create(WarehouseLocationCreateRequest request, Long tenantId) {
        // 先校验再建仓：非法输入不该留下一个「只有仓、没有仓位」的副作用
        String binCode = normalizeBinCode(request.getBinCode());
        String zoneCode = normalizeZoneCode(request.getZoneCode());
        String zoneName = normalizeZoneName(request.getZoneName());
        String remark = normalizeRemark(request.getRemark());
        Warehouse warehouse = warehouseService.ensureFinishedWarehouse(tenantId);

        WarehouseLocation location = new WarehouseLocation();
        location.setTenantId(tenantId);
        location.setWarehouseId(warehouse.getId());
        location.setZoneCode(zoneCode);
        location.setZoneName(zoneName);
        location.setBinCode(binCode);
        location.setStatus(STATUS_ACTIVE);
        location.setRemark(remark);
        OffsetDateTime now = OffsetDateTime.now();
        location.setCreatedAt(now);
        location.setUpdatedAt(now);
        try {
            locationMapper.insert(location);
        } catch (DuplicateKeyException duplicate) {
            // 唯一索引撞车 ⇒ 可读冲突，不是 5xx（与 WarehouseService#create 同一处置）
            throw BusinessException.validationError("仓位号 " + binCode + " 已存在，请换一个号");
        }
        log.info("[仓位] 新建 | tenant={} bin={} warehouse={}", tenantId, binCode, warehouse.getId());
        return toView(location, false);
    }

    /**
     * 编辑仓位：仓位号 / 区域 / 备注 / 状态（null = 不改）。
     *
     * <p>占用中（有 {@code in_stock} 成品）⇒ **禁止改号**：在库行与已贴标签都认这个号。
     * 区域名 / 备注 / 停用仍可改（停用只影响后续分配）。</p>
     */
    @Transactional
    public WarehouseLocationView update(Long id, WarehouseLocationUpdateRequest request, Long tenantId) {
        WarehouseLocation location = requireOwned(id, tenantId);
        boolean occupied = isOccupied(tenantId, location.getBinCode());
        if (request.getBinCode() != null) {
            String newCode = normalizeBinCode(request.getBinCode());
            if (!newCode.equals(location.getBinCode())) {
                if (occupied) {
                    throw BusinessException.conflict(
                            "仓位 " + location.getBinCode() + " 上有在库成品，不能改仓位号",
                            "先发货或撤销打包释放仓位后再改号");
                }
                location.setBinCode(newCode);
            }
        }
        if (request.getZoneCode() != null) {
            location.setZoneCode(normalizeZoneCode(request.getZoneCode()));
        }
        if (request.getZoneName() != null) {
            location.setZoneName(normalizeZoneName(request.getZoneName()));
        }
        if (request.getRemark() != null) {
            location.setRemark(normalizeRemark(request.getRemark()));
        }
        if (request.getStatus() != null) {
            location.setStatus(normalizeStatus(request.getStatus()));
        }
        location.setUpdatedAt(OffsetDateTime.now());
        try {
            locationMapper.updateById(location);
        } catch (DuplicateKeyException duplicate) {
            throw BusinessException.validationError("仓位号 " + location.getBinCode() + " 已存在，请换一个号");
        }
        log.info("[仓位] 编辑 | tenant={} bin={} status={}", tenantId, location.getBinCode(), location.getStatus());
        return toView(location, isOccupied(tenantId, location.getBinCode()));
    }

    /** 删除仓位（软删；历史单据的 {@code bin_code} 快照不受影响）。占用中 ⇒ 409。 */
    @Transactional
    public void delete(Long id, Long tenantId) {
        WarehouseLocation location = requireOwned(id, tenantId);
        if (isOccupied(tenantId, location.getBinCode())) {
            throw BusinessException.conflict(
                    "仓位 " + location.getBinCode() + " 上有在库成品，不能删除",
                    "先发货或撤销打包释放仓位后再删除；历史单据会保留仓位号快照");
        }
        locationMapper.deleteById(location.getId());
        log.info("[仓位] 删除 | tenant={} bin={}", tenantId, location.getBinCode());
    }

    // ============================================================ 内部

    /** 按 id + 租户取仓位；跨租户一律当「不存在」（不泄露存在性）。 */
    private WarehouseLocation requireOwned(Long id, Long tenantId) {
        WarehouseLocation location = locationMapper.selectById(id);
        if (location == null || !Objects.equals(location.getTenantId(), tenantId)) {
            throw BusinessException.notFound("仓位");
        }
        return location;
    }

    private boolean isOccupied(Long tenantId, String binCode) {
        return stockMapper.countInStockByBinCode(tenantId, binCode) > 0;
    }

    private static WarehouseLocationView toView(WarehouseLocation location, boolean occupied) {
        WarehouseLocationView view = new WarehouseLocationView();
        view.setId(location.getId());
        view.setWarehouseId(location.getWarehouseId());
        view.setZoneCode(location.getZoneCode());
        view.setZoneName(location.getZoneName());
        view.setBinCode(location.getBinCode());
        view.setStatus(location.getStatus());
        view.setRemark(location.getRemark());
        view.setOccupied(occupied);
        view.setCreatedAt(location.getCreatedAt());
        return view;
    }

    private static String normalizeBinCode(String raw) {
        String code = raw == null ? "" : raw.trim().toUpperCase(Locale.ROOT);
        if (code.isEmpty()) {
            throw BusinessException.validationError("仓位号不能为空");
        }
        if (!BIN_CODE_PATTERN.matcher(code).matches()) {
            throw BusinessException.validationError("仓位号只能包含字母、数字、短横线或下划线（如 A-01）");
        }
        return code;
    }

    private static String normalizeZoneCode(String raw) {
        String code = raw == null || raw.isBlank()
                ? DEFAULT_ZONE_CODE
                : raw.trim().toUpperCase(Locale.ROOT);
        if (!ZONE_CODE_PATTERN.matcher(code).matches()) {
            throw BusinessException.validationError("区域编码只能包含字母、数字、短横线或下划线");
        }
        return code;
    }

    private static String normalizeZoneName(String raw) {
        String name = raw == null || raw.isBlank() ? DEFAULT_ZONE_NAME : raw.trim();
        if (name.length() > ZONE_NAME_MAX_LENGTH) {
            throw BusinessException.validationError("区域名称最多 " + ZONE_NAME_MAX_LENGTH + " 个字");
        }
        return name;
    }

    private static String normalizeRemark(String raw) {
        if (raw == null) {
            return null;
        }
        String remark = raw.trim();
        if (remark.isEmpty()) {
            return null;
        }
        if (remark.length() > REMARK_MAX_LENGTH) {
            throw BusinessException.validationError("备注最多 " + REMARK_MAX_LENGTH + " 个字");
        }
        return remark;
    }

    private static String normalizeStatus(String raw) {
        String status = raw.trim();
        if (!STATUS_ACTIVE.equals(status) && !STATUS_INACTIVE.equals(status)) {
            throw BusinessException.validationError("仓位状态只能是 active / inactive");
        }
        return status;
    }
}
