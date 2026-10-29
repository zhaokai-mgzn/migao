package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.dto.BinStockCount;
import com.migao.admin.dto.WarehouseLocationBatchCreateRequest;
import com.migao.admin.dto.WarehouseLocationBatchCreateResult;
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
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

/**
 * 仓位（V196，issue #7750）—— 成品仓的货位分配与档案管理（issue #7785 / #7791）。
 *
 * <h3>分配口径（V198 / issue #7791：水位最低且未满；issue #8103：同单同仓）</h3>
 * <p>水位 = 该仓在库件数 / 区域容量（默认 10 件/仓）。打包过账时选**水位最低且未满**的 active 仓位，
 * 同水位按仓位号（{@code A-01} 优先）；本区所有仓位都满 ⇒ 按序号新建下一个号（沿用 V196 的顺延）。
 * 水位只从 {@code finished_goods_stock} 的在库行派生 —— 仓位表上没有计数字段（第二份真相）。</p>
 *
 * <p>🔴 **同单同仓**（issue #8103，用户 2026-10-29 新规则）：同一订单的成品入库**固定落在该订单
 * 已在库的仓位** —— 即使该仓已达到 / 超过容量也继续放（容量只约束「新订单首件选仓」）。
 * 入口 = {@link #binForOrder}；同单并发由 PG advisory 事务锁按订单串行。</p>
 *
 * <p>为什么不再「取最小空闲号」：一仓一件时所有空闲仓等价，最小号只是最省事的确定性；
 * 允许一仓多件后，最小号会把 A-01 填满才用 A-02，正是用户要避免的。按水位分配让货均匀落在
 * 现有货架上（同水位再按号，仓管仍能按号找货）。</p>
 *
 * <h3>并发（容量闸门）</h3>
 * <p>{@link WarehouseLocationMapper#selectBestBinForAllocation} 在候选仓位行上
 * {@code SELECT … FOR UPDATE}；调用方（{@code InboundOrderService} 的过账事务）在同一事务内
 * 拿到行锁后才 insert。并发过账会阻塞并在提交后重判 {@code count < capacity} ⇒ 不会把同一仓位
 * 塞过容量。**本方法必须在事务内调用**（自动提交下锁立即释放，闸门失效）。</p>
 *
 * <h3>档案管理（issue #7785 / #7791）</h3>
 * <ul>
 *   <li><b>新建 / 批量新建</b>：仓位号统一大写；成品仓不存在时自动建；批量按数字区间生成，
 *       已存在的幂等跳过；</li>
 *   <li><b>容量按区域统一</b>：同一区域所有仓位共用 capacity（默认 10，1~999）；改一个仓的容量
 *       会同步本区所有仓；</li>
 *   <li><b>占用中禁止改号 / 删除</b>：在库行与已贴标签认的都是这个号；区域名 / 备注 / 容量 / 停用仍可改；</li>
 *   <li><b>停用</b>：不再参与自动分配，已占用库存不受影响；</li>
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

    /** 每仓默认容量（件）。 */
    public static final int DEFAULT_CAPACITY = 10;
    /** 容量上限（件）。 */
    public static final int MAX_CAPACITY = 999;
    /** 单次批量建号上限（个）。 */
    public static final int MAX_BATCH_SIZE = 500;
    /** 批量建号的最大编号（A-9999）。 */
    public static final int MAX_BIN_NUMBER = 9999;

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
     * 取一个**水位最低且未满**的候选仓位；本区全满 ⇒ 建下一个号并返回。
     *
     * <p>「未满」= 在库件数 &lt; capacity；「在库件数」由 {@code finished_goods_stock} 的在库行派生。
     * 候选行由 Mapper 的 {@code FOR UPDATE} 锁住（须在过账事务内调用），并发不会超容量。</p>
     */
    public WarehouseLocation nextFreeBin(Long tenantId, Long warehouseId) {
        for (int attempt = 0; attempt < ALLOCATE_ATTEMPTS; attempt++) {
            WarehouseLocation best = locationMapper.selectBestBinForAllocation(tenantId, warehouseId);
            if (best != null) {
                // 🔴 行锁已拿到，再复核一次在库件数：并发方可能在我们等锁期间把该仓填满；
                // 查询里的 count < capacity 只是推荐过滤，**这里才是容量闸门**。
                int inStock = stockMapper.countInStockByBinCode(tenantId, best.getBinCode());
                int capacity = best.getCapacity() == null ? DEFAULT_CAPACITY : best.getCapacity();
                if (inStock < capacity) {
                    return best;
                }
                continue;
            }
            int capacity = zoneCapacityOrDefault(tenantId, warehouseId, DEFAULT_ZONE_CODE);
            int next = locationMapper.countBinsInZone(tenantId, warehouseId, DEFAULT_ZONE_CODE) + 1;
            String code = codeFor(DEFAULT_ZONE_CODE, next);
            // 原子占号：同号已存在 ⇒ 0 行（不抛异常，事务仍可用），下一轮重新选（会带容量校验）
            locationMapper.claimBin(tenantId, warehouseId, DEFAULT_ZONE_CODE, DEFAULT_ZONE_NAME, code, capacity);
            // 不直接返回刚插入的行：下一轮的 selectBestBinForAllocation 会拿行锁并复核容量
            // （并发下刚建的号可能已被别人填满；直接返回会把「已满」当候选）。
        }
        throw BusinessException.conflict("成品仓位分配失败（连续 " + ALLOCATE_ATTEMPTS + " 次占号冲突）",
                "请重试；同一个仓位不会被两件成品同时占用");
    }

    /**
     * 打包入库取仓位（issue #8103「同单同仓」）：该订单**已有在库仓位** ⇒ 直接复用它（**不再看容量**）；
     * 没有 ⇒ 按 V198 水位规则选一个未满的仓（本区全满才顺延新建号）。
     *
     * <p>用户口径（2026-10-29 逐字）：「打包入库成品的时候，一个订单内的商品入库到同一仓位」
     * 「即使仓位满了也要入库到相同仓位，这个是新规则」⇒ 容量**只约束新订单的首件选仓**；
     * 同单追加允许把仓位放到超过容量（水位显示可为 {@code 2 / 1}，管理面叫「超容」）。
     * 现场按单找货只跑一个货位 —— 这是本规则要换来的东西。</p>
     *
     * <p>并发：{@code lockAllocationForOrder} 先按订单排队，再读「该单已有仓位」⇒ 后到的事务
     * 看到的是前者已提交的事实，不会各自挑一个不同的空仓。**必须在事务内调用**（调用方
     * {@code InboundOrderService} 的过账事务满足这一点）。</p>
     */
    public WarehouseLocation binForOrder(Long tenantId, Long warehouseId, String orderId) {
        if (orderId == null || orderId.isBlank()) {
            // 没有订单引用就没有「同单」可言（正常路径调用方已校验非空）
            return nextFreeBin(tenantId, warehouseId);
        }
        locationMapper.lockAllocationForOrder(tenantId + ":" + orderId);
        WarehouseLocation existing = locationMapper.selectInStockBinByOrder(tenantId, warehouseId, orderId);
        return existing != null ? existing : nextFreeBin(tenantId, warehouseId);
    }

    // ============================================================ 档案读面（出库单页「仓位管理」）

    /**
     * 仓位档案清单（按仓位号排序；带水位 = 在库件数 / capacity）。
     *
     * @param includeInactive 是否包含停用仓位（管理模式要看到并重新启用它们；默认只给可分配的 active）
     */
    public List<WarehouseLocationView> listView(Long tenantId, Long warehouseId, boolean includeInactive) {
        List<WarehouseLocation> rows = locationMapper.selectList(new LambdaQueryWrapper<WarehouseLocation>()
                .eq(WarehouseLocation::getTenantId, tenantId)
                .eq(warehouseId != null, WarehouseLocation::getWarehouseId, warehouseId)
                .eq(!includeInactive, WarehouseLocation::getStatus, STATUS_ACTIVE)
                .orderByAsc(WarehouseLocation::getBinCode));
        // 一次查全租户每个仓位的在库件数（GROUP BY，不搬整行、不受 500 行截断影响）
        Map<String, Integer> counts = stockMapper.selectInStockCounts(tenantId).stream()
                .filter(row -> row.getBinCode() != null)
                .collect(Collectors.toMap(BinStockCount::getBinCode,
                        row -> row.getInStockCount() == null ? 0 : row.getInStockCount(),
                        Integer::sum));
        return rows.stream().map(row -> toView(row, counts.getOrDefault(row.getBinCode(), 0))).toList();
    }

    // ============================================================ 档案写面

    /**
     * 新建仓位。仓位号租户内唯一（DB 唯一索引兜底）；成品仓不存在时自动建（写操作建前置，
     * **不是** GET 的副作用）。容量缺省沿用本区现有容量，新区域缺省 10 件。
     */
    @Transactional
    public WarehouseLocationView create(WarehouseLocationCreateRequest request, Long tenantId) {
        // 先校验再建仓：非法输入不该留下一个「只有仓、没有仓位」的副作用
        String binCode = normalizeBinCode(request.getBinCode());
        String zoneCode = normalizeZoneCode(request.getZoneCode());
        String zoneName = normalizeZoneName(request.getZoneName());
        String remark = normalizeRemark(request.getRemark());
        Integer requested = request.getCapacity() == null ? null : checkCapacity(request.getCapacity());
        Warehouse warehouse = warehouseService.ensureFinishedWarehouse(tenantId);
        Integer existing = locationMapper.selectZoneCapacity(tenantId, warehouse.getId(), zoneCode);
        boolean zoneHasCapacity = existing != null && existing > 0;
        int capacity = requested != null ? requested
                : (zoneHasCapacity ? existing : DEFAULT_CAPACITY);

        WarehouseLocation location = new WarehouseLocation();
        location.setTenantId(tenantId);
        location.setWarehouseId(warehouse.getId());
        location.setZoneCode(zoneCode);
        location.setZoneName(zoneName);
        location.setBinCode(binCode);
        location.setStatus(STATUS_ACTIVE);
        location.setCapacity(capacity);
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
        if (zoneHasCapacity && existing != capacity) {
            // 容量按区域统一：新建时给了不同的容量 ⇒ 本区已有仓位一起改
            locationMapper.updateCapacityByZone(tenantId, warehouse.getId(), zoneCode, capacity);
        }
        log.info("[仓位] 新建 | tenant={} bin={} warehouse={} capacity={}",
                tenantId, binCode, warehouse.getId(), capacity);
        return toView(location, 0);
    }

    /**
     * 编辑仓位：仓位号 / 区域 / 备注 / 状态 / 容量（null = 不改）。
     *
     * <p>占用中（有 {@code in_stock} 成品）⇒ **禁止改号**：在库行与已贴标签都认这个号。
     * 容量 / 区域名 / 备注 / 停用仍可改；改容量会同步本区所有仓位（容量按区域统一）。</p>
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
        Integer requested = request.getCapacity() == null ? null : checkCapacity(request.getCapacity());
        if (requested != null) {
            location.setCapacity(requested);
        } else if (request.getZoneCode() != null) {
            // 改区域但没给容量 ⇒ 跟随新区域的现有容量（否则同一区域会出现两种容量，破坏「区域统一」）
            Integer newZoneCapacity = locationMapper.selectZoneCapacity(
                    tenantId, location.getWarehouseId(), location.getZoneCode());
            if (newZoneCapacity != null && newZoneCapacity > 0) {
                location.setCapacity(newZoneCapacity);
            }
        }
        location.setUpdatedAt(OffsetDateTime.now());
        try {
            locationMapper.updateById(location);
        } catch (DuplicateKeyException duplicate) {
            throw BusinessException.validationError("仓位号 " + location.getBinCode() + " 已存在，请换一个号");
        }
        if (requested != null) {
            // 容量按区域统一：改一个仓的容量 ⇒ 本区所有仓一起改（应用在更新后的区域上）
            locationMapper.updateCapacityByZone(
                    tenantId, location.getWarehouseId(), location.getZoneCode(), requested);
        }
        log.info("[仓位] 编辑 | tenant={} bin={} status={} capacity={}",
                tenantId, location.getBinCode(), location.getStatus(), location.getCapacity());
        return toView(location, stockMapper.countInStockByBinCode(tenantId, location.getBinCode()));
    }

    /**
     * 批量新建仓位（issue #7791）：按数字区间生成 {@code A-01}…{@code A-20}。
     *
     * <p>幂等：已存在的仓位号自动跳过（{@code claimBin} 的 {@code ON CONFLICT DO NOTHING}），
     * 返回新建 / 跳过计数；重复提交同一批次不会报错。容量按区域统一（给了不同的容量 ⇒ 本区一起改）。</p>
     */
    @Transactional
    public WarehouseLocationBatchCreateResult batchCreate(WarehouseLocationBatchCreateRequest request,
                                                          Long tenantId) {
        String zoneCode = normalizeZoneCode(request.getZoneCode());
        String zoneName = normalizeZoneName(request.getZoneName());
        int from = checkBinNumber("起始编号", request.getNumberFrom());
        int to = checkBinNumber("结束编号", request.getNumberTo());
        if (to < from) {
            throw BusinessException.validationError("结束编号不能小于起始编号");
        }
        int total = to - from + 1;
        if (total > MAX_BATCH_SIZE) {
            throw BusinessException.validationError("单次最多创建 " + MAX_BATCH_SIZE + " 个仓位");
        }
        Integer requested = request.getCapacity() == null ? null : checkCapacity(request.getCapacity());
        Warehouse warehouse = warehouseService.ensureFinishedWarehouse(tenantId);
        Integer existing = locationMapper.selectZoneCapacity(tenantId, warehouse.getId(), zoneCode);
        boolean zoneHasCapacity = existing != null && existing > 0;
        int capacity = requested != null ? requested
                : (zoneHasCapacity ? existing : DEFAULT_CAPACITY);

        int created = 0;
        for (int n = from; n <= to; n++) {
            created += locationMapper.claimBin(tenantId, warehouse.getId(), zoneCode, zoneName,
                    codeFor(zoneCode, n), capacity);
        }
        if (zoneHasCapacity && existing != capacity) {
            locationMapper.updateCapacityByZone(tenantId, warehouse.getId(), zoneCode, capacity);
        }
        int skipped = total - created;
        log.info("[仓位] 批量新建 | tenant={} zone={} from={} to={} created={} skipped={} capacity={}",
                tenantId, zoneCode, from, to, created, skipped, capacity);
        return new WarehouseLocationBatchCreateResult(
                created, skipped, codeFor(zoneCode, from), codeFor(zoneCode, to), capacity);
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
        int deleted = locationMapper.deleteById(location.getId());
        if (deleted == 0) {
            // 并发双删：另一请求刚删掉 ⇒ 本次按 404 回报，不把「没删到」谎报成成功（#6956）。
            throw BusinessException.notFound("仓位", "可能刚被其他人删除，刷新后再试");
        }
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

    private int zoneCapacityOrDefault(Long tenantId, Long warehouseId, String zoneCode) {
        Integer existing = locationMapper.selectZoneCapacity(tenantId, warehouseId, zoneCode);
        return existing == null || existing <= 0 ? DEFAULT_CAPACITY : existing;
    }

    private static String codeFor(String zoneCode, int n) {
        return String.format(Locale.ROOT, "%s-%02d", zoneCode, n);
    }

    private static int checkBinNumber(String field, Integer raw) {
        if (raw == null) {
            throw BusinessException.validationError(field + "不能为空");
        }
        if (raw < 1 || raw > MAX_BIN_NUMBER) {
            throw BusinessException.validationError(field + "只能是 1~" + MAX_BIN_NUMBER);
        }
        return raw;
    }

    private static int checkCapacity(int raw) {
        if (raw < 1 || raw > MAX_CAPACITY) {
            throw BusinessException.validationError("每仓容量只能是 1~" + MAX_CAPACITY + " 件");
        }
        return raw;
    }

    private static WarehouseLocationView toView(WarehouseLocation location, int inStockCount) {
        WarehouseLocationView view = new WarehouseLocationView();
        view.setId(location.getId());
        view.setWarehouseId(location.getWarehouseId());
        view.setZoneCode(location.getZoneCode());
        view.setZoneName(location.getZoneName());
        view.setBinCode(location.getBinCode());
        view.setStatus(location.getStatus());
        view.setCapacity(location.getCapacity() == null ? DEFAULT_CAPACITY : location.getCapacity());
        view.setInStockCount(inStockCount);
        view.setRemark(location.getRemark());
        view.setOccupied(inStockCount > 0);
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
