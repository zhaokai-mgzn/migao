package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.dto.OutboundOrderCreateRequest;
import com.migao.admin.dto.OutboundOrderView;
import com.migao.admin.entity.FinishedGoodsStock;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OutboundOrder;
import com.migao.admin.entity.OutboundOrderItem;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.entity.StockLedger;
import com.migao.admin.entity.Warehouse;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OutboundOrderItemMapper;
import com.migao.admin.mapper.OutboundOrderMapper;
import com.migao.admin.mapper.OutboundOrderQueryMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import com.migao.admin.time.BusinessClock;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * 出库单服务（V196，issue #7750）—— 与入库单**对称**的那一半。
 *
 * <h3>两种出库，一套单据</h3>
 * <ul>
 *   <li><b>布料手工出库</b>（{@link OutboundOrder#SOURCE_MANUAL}）：商家建单即过账 ——
 *       原子扣 SKU 米数库存（{@code ProductSkuMapper#deductStock} 带「库存 ≥ 本单量」谓词，
 *       扣不动就是库存不足，整笔回滚）+ 落库存台账（{@code reason=outbound}）；</li>
 *   <li><b>成品发货出库</b>（{@link OutboundOrder#SOURCE_SHIP}）：由发货动作在同一事务里调用，
 *       把本单的 {@code finished_goods_stock} 在库行置为已发货（释放仓位）。</li>
 * </ul>
 *
 * <h3>为什么没有草稿态</h3>
 * <p>出库是**已经发生**的物理动作（货被拉走了才来登记）。留草稿只会多一个「谁忘了过账」的坑，
 * 而不会让库存更准（与「入库即过账」同一条产品口径）。DB CHECK 也把状态锁成
 * {@code posted} 一个取值 —— 不靠服务层自觉。</p>
 *
 * <h3>库存不足的判据在哪</h3>
 * <p>在<b>一条 SQL</b>里（{@code deductStock} 的 {@code WHERE ... AND COALESCE(stock,0) >= #{quantity} RETURNING}）：
 * 「先读库存再判断」在并发下会让两个出库单都通过判断，最后一个把库存扣成负数。
 * 受影响行数 0 = 库存不足 ⇒ 抛 422，整笔回滚（不落单据、不落台账）。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class OutboundOrderService {

    private static final DateTimeFormatter DATE_FMT = DateTimeFormatter.ofPattern("yyyyMMdd");

    /** 出库单号序号（CK-yyyyMMdd-NNNN）；**号归谁由 DB 唯一索引在插入那一刻裁**（issue #8490），计数器只降重叠 */
    private static final AtomicInteger OUTBOUND_SEQ = new AtomicInteger(0);

    /** 列表一次最多返回的单据数（同族页面口径） */
    private static final int LIST_LIMIT = 200;

    private final OutboundOrderMapper outboundOrderMapper;
    private final OutboundOrderItemMapper outboundOrderItemMapper;
    private final OutboundOrderQueryMapper outboundOrderQueryMapper;
    private final ProductSkuMapper productSkuMapper;
    private final StockLedgerService stockLedgerService;
    private final WarehouseService warehouseService;

    /** 业务时钟（issue #3802）：业务「今天」的唯一来源（同入库单的 required=false 口径）。 */
    @Autowired(required = false)
    private BusinessClock businessClock = new BusinessClock();

    // ============================================================ 建单即过账（布料）

    /**
     * 布料手工出库：**建单 = 过账**（扣库存 + 落台账 + 写单据，一个事务）。
     *
     * @throws BusinessException 任一 SKU 库存不足 / 数量非法 / SKU 不属于本租户 ⇒ 整笔回滚
     */
    @Transactional(rollbackFor = Exception.class)
    public OutboundOrderView createAndPost(OutboundOrderCreateRequest req, Long tenantId, String operator) {
        List<OutboundOrderCreateRequest.Item> items = req == null ? null : req.getItems();
        if (items == null || items.isEmpty()) {
            throw BusinessException.validationError("出库单至少要有一行明细");
        }
        Warehouse warehouse = resolveWarehouse(req.getWarehouseId(), tenantId);
        LocalDate date = req.getOutboundDate() != null ? req.getOutboundDate() : businessClock.today();

        OutboundOrder order = OutboundOrder.builder()
                .tenantId(tenantId)
                .bizCategory(OutboundOrder.BIZ_FABRIC)
                .source(OutboundOrder.SOURCE_MANUAL)
                .warehouseId(warehouse == null ? null : warehouse.getId())
                .warehouse(warehouse == null ? null : warehouse.getName())
                .outboundDate(date)
                .status(OutboundOrder.STATUS_POSTED)
                .totalAmount(BigDecimal.ZERO)
                .remark(trimToNull(req.getRemark()))
                .postedAt(OffsetDateTime.now())
                .postedBy(operator)
                .createdBy(operator)
                .build();
        insertWithFreshOutboundNo(order);

        BigDecimal total = BigDecimal.ZERO;
        List<OutboundOrderItem> lines = new ArrayList<>(items.size());
        for (OutboundOrderCreateRequest.Item input : items) {
            if (input.getSkuId() == null) {
                throw BusinessException.validationError("出库明细缺少 SKU");
            }
            BigDecimal qty = input.getQuantity();
            requireOneDecimal(qty);
            ProductSku sku = productSkuMapper.selectById(input.getSkuId());
            if (sku == null || !tenantId.equals(sku.getTenantId())) {
                throw BusinessException.validationError("出库明细引用的 SKU 不存在（skuId=" + input.getSkuId() + "）");
            }
            // 原子扣减：谓词里带「库存 ≥ 本单量」⇒ 扣成负数不可能；0 行 = 库存不足
            StockChange change = StockChange.from(productSkuMapper.deductStock(sku.getId(), qty, tenantId));
            if (change == null) {
                throw BusinessException.validationError(
                        "货号 " + sku.getSkuCode() + " 库存不足：本次出库 " + qty.stripTrailingZeros().toPlainString()
                                + " 米，" + "当前可用库存不足以支付该单（出库单未创建，库存未变动）");
            }
            BigDecimal unitCost = sku.getAvgCost();
            BigDecimal amount = unitCost == null ? null : unitCost.multiply(qty);
            // 落库存台账（reason=outbound）：before/after 来自同一条 SQL 的 RETURNING（issue #6300）
            stockLedgerService.record(tenantId, sku.getProductId(), sku.getId(), change.skuCode(),
                    change.beforeQuantity(), change.afterQuantity(),
                    StockLedger.REASON_OUTBOUND, order.getOutboundNo(), "出库单过账",
                    unitCost, unitCost, unitCost);

            OutboundOrderItem line = OutboundOrderItem.builder()
                    .tenantId(tenantId)
                    .outboundOrderId(order.getId())
                    .skuId(sku.getId())
                    .productId(sku.getProductId())
                    .skuCode(change.skuCode())
                    .quantity(qty)
                    .unit("m")
                    .unitCost(unitCost)
                    .amount(amount)
                    .remark(trimToNull(input.getRemark()))
                    .build();
            outboundOrderItemMapper.insert(line);
            lines.add(line);
            if (amount != null) {
                total = total.add(amount);
            }
        }

        order.setTotalAmount(total);
        outboundOrderMapper.updateById(order);
        log.info("[出库] 布料出库单已过账: tenant={}, outboundNo={}, items={}, total={}, operator={}",
                tenantId, order.getOutboundNo(), lines.size(), total, operator);
        return toView(order, lines);
    }

    // ============================================================ 成品发货出库（由发货动作调用）

    /**
     * 成品发货出库：为**在库的成品行**生成一张已过账的出库单（{@code source=ship}）。
     *
     * <p>调用方（{@code FinishedGoodsService#issueOnShip}）负责把在库行置为 shipped ——
     * 这里只写单据。为什么分成两步而不在一处做完：「货已出库」这件事的**唯一凭据**是单据，
     * 状态与单据必须在同一事务里成对出现（调用方与被调用方都在 {@code @Transactional} 里）。</p>
     *
     * @param rows 本单当前在库的成品行（为空 ⇒ 调用方不该调本方法）
     */
    /**
     * **扫水洗唛出库单**（V197 / issue #7762）：单行 = 一张水洗唛（套 × 部位）+ 仓位号。
     *
     * <p>与 {@link #createFinishedOutbound} 的区别只在「行从哪来」：发货出库一次带走整单所有在库行；
     * 扫唛出库只带走**被扫到的这一件**。单据形态、号段、已过账状态、金额留 NULL 的口径完全一致。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public OutboundOrder createScanOutbound(String orderNo, FinishedGoodsStock row, Warehouse warehouse,
                                            Long tenantId, String operator) {
        OutboundOrder doc = OutboundOrder.builder()
                .tenantId(tenantId)
                .bizCategory(OutboundOrder.BIZ_FINISHED)
                .source(OutboundOrder.SOURCE_SCAN)
                .warehouseId(warehouse == null ? null : warehouse.getId())
                .warehouse(warehouse == null ? null : warehouse.getName())
                .outboundDate(businessClock.today())
                .status(OutboundOrder.STATUS_POSTED)
                .totalAmount(BigDecimal.ZERO)
                .orderId(row.getOrderId())
                .orderNo(orderNo)
                .remark("扫水洗唛出库（仓位 " + row.getBinCode() + "）")
                .postedAt(OffsetDateTime.now())
                .postedBy(operator)
                .createdBy(operator)
                .build();
        insertWithFreshOutboundNo(doc);
        outboundOrderItemMapper.insert(OutboundOrderItem.builder()
                .tenantId(tenantId)
                .outboundOrderId(doc.getId())
                .productId(row.getProductId())
                .productName(row.getProductName())
                .orderId(row.getOrderId())
                .orderItemId(row.getOrderItemId())
                .locationId(row.getLocationId())
                .binCode(row.getBinCode())
                .quantity(row.getQuantity())
                .unit(row.getUnit())
                .remark("扫唛出库")
                .build());
        log.info("[出库] 扫水洗唛出库单已过账: tenant={}, outboundNo={}, orderNo={}, bin={}",
                tenantId, doc.getOutboundNo(), orderNo, row.getBinCode());
        return doc;
    }

    @Transactional(rollbackFor = Exception.class)
    public OutboundOrder createFinishedOutbound(Order order, List<FinishedGoodsStock> rows,
                                                Warehouse warehouse, Long tenantId, String operator) {
        OutboundOrder doc = OutboundOrder.builder()
                .tenantId(tenantId)
                .bizCategory(OutboundOrder.BIZ_FINISHED)
                .source(OutboundOrder.SOURCE_SHIP)
                .warehouseId(warehouse == null ? null : warehouse.getId())
                .warehouse(warehouse == null ? null : warehouse.getName())
                .outboundDate(businessClock.today())
                .status(OutboundOrder.STATUS_POSTED)
                .totalAmount(BigDecimal.ZERO)
                .orderId(order.getId())
                .orderNo(order.getOrderNo())
                .remark("成品发货出库（订单 " + order.getOrderNo() + "）")
                .postedAt(OffsetDateTime.now())
                .postedBy(operator)
                .createdBy(operator)
                .build();
        insertWithFreshOutboundNo(doc);

        for (FinishedGoodsStock row : rows) {
            OutboundOrderItem line = OutboundOrderItem.builder()
                    .tenantId(tenantId)
                    .outboundOrderId(doc.getId())
                    .productId(row.getProductId())
                    .productName(row.getProductName())
                    .orderId(row.getOrderId())
                    .orderItemId(row.getOrderItemId())
                    .locationId(row.getLocationId())
                    .binCode(row.getBinCode())
                    .quantity(row.getQuantity())
                    .unit(row.getUnit())
                    // 成品无成本口径（不伪造 0）：金额列留 NULL
                    .remark("发货")
                    .build();
            outboundOrderItemMapper.insert(line);
        }
        log.info("[出库] 成品出库单已过账: tenant={}, outboundNo={}, orderNo={}, bins={}, operator={}",
                tenantId, doc.getOutboundNo(), order.getOrderNo(),
                rows.stream().map(FinishedGoodsStock::getBinCode).toList(), operator);
        return doc;
    }

    // ============================================================ 只读

    /** 列表（关键词匹配 单号/仓库/订单号；类别精确匹配；按出库日期倒序） */
    public List<OutboundOrderView> list(String keyword, String bizCategory, Long tenantId) {
        return outboundOrderQueryMapper.selectOrderLines(tenantId, trimToNull(keyword), trimToNull(bizCategory), LIST_LIMIT);
    }

    /** 详情（单头 + 逐行明细） */
    public OutboundOrderView detail(String id, Long tenantId) {
        OutboundOrder order = outboundOrderMapper.selectOne(new LambdaQueryWrapper<OutboundOrder>()
                .eq(OutboundOrder::getId, id)
                .eq(OutboundOrder::getTenantId, tenantId));
        if (order == null) {
            throw BusinessException.notFound("出库单");
        }
        List<OutboundOrderItem> lines = outboundOrderItemMapper.selectList(
                new LambdaQueryWrapper<OutboundOrderItem>()
                        .eq(OutboundOrderItem::getTenantId, tenantId)
                        .eq(OutboundOrderItem::getOutboundOrderId, order.getId())
                        .orderByAsc(OutboundOrderItem::getId));
        return toView(order, lines);
    }

    // ============================================================ 内部

    private Warehouse resolveWarehouse(Long warehouseId, Long tenantId) {
        if (warehouseId != null) {
            Warehouse warehouse = warehouseService.require(warehouseId);
            if (!tenantId.equals(warehouse.getTenantId())) {
                throw BusinessException.notFound("仓库");
            }
            return warehouse;
        }
        return warehouseService.defaultWarehouse(tenantId);
    }

    /** 数量准入：&gt; 0 且最多 1 位小数（与 product_skus.stock 的 NUMERIC(12,1) 同粒度）。 */
    private void requireOneDecimal(BigDecimal qty) {
        if (qty == null || qty.signum() <= 0) {
            throw BusinessException.validationError("出库数量必须大于 0");
        }
        if (qty.stripTrailingZeros().scale() > 1) {
            throw BusinessException.validationError("出库数量最多 1 位小数（库存粒度 = 0.1 米）");
        }
    }

    private OutboundOrderView toView(OutboundOrder order, List<OutboundOrderItem> lines) {
        OutboundOrderView view = new OutboundOrderView();
        view.setId(order.getId());
        view.setOutboundNo(order.getOutboundNo());
        view.setBizCategory(order.getBizCategory());
        view.setSource(order.getSource());
        view.setWarehouseId(order.getWarehouseId());
        view.setWarehouse(order.getWarehouse());
        view.setOutboundDate(order.getOutboundDate());
        view.setStatus(order.getStatus());
        view.setTotalAmount(order.getTotalAmount());
        view.setOrderId(order.getOrderId());
        view.setOrderNo(order.getOrderNo());
        view.setRemark(order.getRemark());
        view.setPostedAt(order.getPostedAt());
        view.setPostedBy(order.getPostedBy());
        view.setCreatedAt(order.getCreatedAt());
        view.setItemCount(lines.size());
        view.setTotalQuantity(lines.stream().map(OutboundOrderItem::getQuantity)
                .filter(java.util.Objects::nonNull).reduce(BigDecimal.ZERO, BigDecimal::add));
        view.setItems(lines.stream().map(line -> {
            OutboundOrderView.Item item = new OutboundOrderView.Item();
            item.setId(line.getId());
            item.setSkuId(line.getSkuId());
            item.setSkuCode(line.getSkuCode());
            item.setProductName(line.getProductName());
            item.setOrderItemId(line.getOrderItemId());
            item.setLocationId(line.getLocationId());
            item.setBinCode(line.getBinCode());
            item.setQuantity(line.getQuantity());
            item.setUnit(line.getUnit());
            item.setUnitCost(line.getUnitCost());
            item.setAmount(line.getAmount());
            item.setRemark(line.getRemark());
            return item;
        }).toList());
        return view;
    }

    /**
     * 出库单号取号（CK-yyyyMMdd-NNNN）。
     *
     * <p>与入库单号（{@code RK-…}）、加工单号 {@code JG-…} 同族：前缀 + 日期 + 序号。序号是进程内原子
     * 计数器（降低同秒重叠），**号归不归我由 DB 唯一的单号索引在插入那一刻裁**
     * （{@link #insertWithFreshOutboundNo}；issue #8490）。</p>
     */
    private String generateOutboundNo() {
        return "CK-" + businessClock.today().format(DATE_FMT) + "-"
                + String.format("%04d", OUTBOUND_SEQ.incrementAndGet() % 10_000);
    }

    /**
     * 取号 + 落库的**重试上限**（issue #8490）：候选号在插入那一刻被别的事务抢走（受影响行数 0）
     * ⇒ 换候选重来；连续 {@value} 次全被抢 ⇒ 显式抛 {@code OUTBOUND_NO_EXHAUSTED}(409)，
     * <b>不静默用一个可能重复的号</b>。
     *
     * <p>为什么是 20（同族口径，见 {@code INBOUND_NO_ATTEMPTS} / {@code BATCH_NO_ATTEMPTS}）：远超
     * 「同一天重启 20 次且每次都恰好撞上」的实际情况。<b>已知代价</b>（如实登记）：当天已用号 ≥ 20 时
     * 重启后的第一批出库会被显式拒绝（回 409、零副作用），而不是静默重号 —— 判据见
     * {@code OutboundNoTakeRaceRealDbTest} 判据 ④。</p>
     */
    private static final int OUTBOUND_NO_ATTEMPTS = 20;

    /** 首次取号的测试候选（{@code null} = 不钉）；见 {@link #setOutboundNoProbeFirstCandidateForTest}。 */
    private static volatile String OUTBOUND_NO_PROBE_FIRST_CANDIDATE = null;

    /**
     * <b>测试探针</b>（issue #8490，生产恒为 {@code null}）：把**第一次**取号钉成给定候选。
     *
     * <p><b>为什么需要它</b>：本缺陷的可达形态是「两个实例（或重启后的新进程）从同一计数器位置起步
     * ⇒ 拿到**同一个**候选」，而 {@code OUTBOUND_SEQ} 是进程内的原子计数器 —— 同一 JVM 里两个线程
     * 天然拿到**不同**候选 ⇒ 不钉住候选就造不出「同号竞争」，判据会退化成碰运气的 flake
     * （{@code migao-dev-flow} §28.1：修前必须红）。语义与 {@code InboundOrderService} 的同名探针一致。</p>
     */
    static void setOutboundNoProbeFirstCandidateForTest(String candidate) {
        OUTBOUND_NO_PROBE_FIRST_CANDIDATE = candidate;
    }

    /**
     * 取号并落库（issue #8490）：把「判单号是否被占」与「占用它」并成**一条语句**
     * （{@code OutboundOrderMapper#insertIgnoreOutboundNoConflict} 的
     * {@code ON CONFLICT (tenant_id, outbound_no) WHERE deleted = 0 DO NOTHING}）；
     * 受影响行数 {@code 1} = 号归我（单据已落库）、{@code 0} = 号刚被抢走 ⇒ 换候选重来。
     *
     * <p><b>改前</b>（两步形态，本单的病）：{@code exists(tenant_id, outbound_no)} 判假 ⇒ 返回候选 ⇒
     * 调用方**之后**才 {@code insert(..)}，且那条 insert <b>没有任何 catch</b> ⇒ 窗口被利用时
     * {@code DuplicateKeyException} 直抛到全局处理器 ⇒ 用户侧 <b>500</b>（整笔回滚、零残行）。</p>
     *
     * <p>为什么不是「先 exists 查库、再 insert」：那两步之间的窗口在多实例 / 重启下可被利用
     * （两边 {@code exists} 都为假）。唯一索引在插入那一刻的判定才是原子的；{@code ON CONFLICT}
     * 把冲突变成「0 行」而不是异常 ⇒ 同一事务内换号重试安全（捕获 {@code DuplicateKeyException}
     * 则 PG 事务已坏，只能开新事务 —— 那会把单头提前提交、明细行失败就是半张单）。</p>
     *
     * <p>重试骨架在 {@link AtomicNoAllocator}（与入库建单取号**同一份实现**，不各写一份循环）。</p>
     */
    private void insertWithFreshOutboundNo(OutboundOrder order) {
        // 主键由服务端生成：手写 INSERT 不走 MyBatis-Plus 的 ASSIGN_UUID（与入库单同一批写面同口径）
        order.setId(UUID.randomUUID().toString().replace("-", ""));
        String taken = AtomicNoAllocator.take(OUTBOUND_NO_ATTEMPTS, "出库单号", order.getTenantId(),
                attempt -> attempt == 0 && OUTBOUND_NO_PROBE_FIRST_CANDIDATE != null
                        ? OUTBOUND_NO_PROBE_FIRST_CANDIDATE
                        : generateOutboundNo(),
                candidate -> {
                    order.setOutboundNo(candidate);
                    return outboundOrderMapper.insertIgnoreOutboundNoConflict(order) == 1;
                });
        if (taken == null) {
            throw new BusinessException("OUTBOUND_NO_EXHAUSTED",
                    "出库单号连续 " + OUTBOUND_NO_ATTEMPTS + " 次生成失败（当天号段疑似被占满），请稍后重试或联系管理员", 409);
        }
    }

    private static String trimToNull(String value) {
        if (!StringUtils.hasText(value)) {
            return null;
        }
        return value.trim();
    }
}
