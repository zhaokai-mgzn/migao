package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.dto.InboundBatchView;
import com.migao.admin.dto.InboundOrderCreateRequest;
import com.migao.admin.dto.InboundOrderLine;
import com.migao.admin.dto.InboundOrderResponse;
import com.migao.admin.entity.InboundOrder;
import com.migao.admin.entity.InboundOrderItem;
import com.migao.admin.entity.Product;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.entity.StockBatch;
import com.migao.admin.entity.StockLedger;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.InboundOrderItemMapper;
import com.migao.admin.mapper.InboundOrderMapper;
import com.migao.admin.mapper.InboundOrderQueryMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import com.migao.admin.mapper.StockBatchMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.BeanUtils;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * 入库单服务（V111，issue #5034）—— 商品布料入库的标准能力。
 *
 * <p><b>三件标准能力</b>：① 建单（草稿，不动库存）；② 过账（<b>自动生成批次号</b> +
 * <b>自动加库存</b> + 落库存台账 + 按<b>移动加权平均</b>算成本）；③ 作废（仅草稿）。</p>
 *
 * <p><b>批次粒度 = 入库单行</b>（用户裁定 2026-09-23）：缸号的行业粒度本就是「一批布」
 * （docs/curtain-selling-method-industry-research.md §1），卷级会要求「库存 = 卷集合求和」
 * 的模型升级，而卷长是区间值（同文件 §8.2 末明确不建议硬折算）。</p>
 *
 * <p><b>为什么过账而不是建单就加库存</b>：仓库实际形态是「先按送货单录单、点数核对完再过账」。
 * 若建单即加库存，录错一行就得反向出库去冲 —— 而库存是资金级数据，冲销必须留痕。
 * 故草稿态完全不动库存，过账是**一次性、不可重复**的状态迁移（幂等闸 = 状态机 + 行锁）。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class InboundOrderService {

    private static final DateTimeFormatter DATE_FMT = DateTimeFormatter.ofPattern("yyyyMMdd");

    /** 入库单号序号（RK-yyyyMMdd-NNNN）；DB 唯一索引兜底防重号，同 ProcessingOrderService 口径 */
    private static final AtomicInteger INBOUND_SEQ = new AtomicInteger(0);
    /** 批次号序号（PC-yyyyMMdd-NNNN） */
    private static final AtomicInteger BATCH_SEQ = new AtomicInteger(0);

    /** 列表一次最多返回的单据数（同族页面口径；入库单是流水型单据，不做深分页） */
    private static final int LIST_LIMIT = 200;
    /** 批次查询一次最多返回的行数 */
    private static final int BATCH_LIMIT = 200;

    private final InboundOrderMapper inboundOrderMapper;
    private final InboundOrderItemMapper inboundOrderItemMapper;
    private final InboundOrderQueryMapper inboundOrderQueryMapper;
    private final StockBatchMapper stockBatchMapper;
    private final ProductSkuMapper productSkuMapper;
    private final ProductMapper productMapper;
    private final StockLedgerService stockLedgerService;

    // ============================================================ 建单

    /**
     * 建单（草稿态，**不动库存**）。
     *
     * <p>批次号**此时不生成** —— 它代表「真的收货了」，只在过账时写（见 {@link #post}）。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public InboundOrderResponse create(InboundOrderCreateRequest req, Long tenantId, String operator) {
        Validated validated = validateRequest(req, tenantId);
        List<InboundOrderCreateRequest.Item> items = validated.items();

        InboundOrder order = InboundOrder.builder()
                .tenantId(tenantId)
                .inboundNo(generateInboundNo())
                .supplier(trimToNull(req.getSupplier()))
                .supplierDocNo(trimToNull(req.getSupplierDocNo()))
                .warehouse(trimToNull(req.getWarehouse()))
                .inboundDate(req.getInboundDate() != null ? req.getInboundDate() : LocalDate.now())
                .status(InboundOrder.STATUS_DRAFT)
                .totalAmount(BigDecimal.ZERO)
                .remark(req.getRemark())
                .createdBy(operator)
                .build();
        inboundOrderMapper.insert(order);

        BigDecimal total = BigDecimal.ZERO;
        for (InboundOrderCreateRequest.Item item : items) {
            // 复用校验阶段已读到的 SKU（同一次请求里不重复查库）
            ProductSku sku = validated.skuById().get(item.getSkuId());
            InboundOrderItem line = InboundOrderItem.builder()
                    .tenantId(tenantId)
                    .inboundOrderId(order.getId())
                    .skuId(sku.getId())
                    .productId(item.getProductId())
                    // 快照：入库时点的货号/颜色/门幅 —— 事后改商品不影响历史单
                    .skuCode(sku.getSkuCode())
                    .colorName(sku.getColorName())
                    .doorWidth(sku.getDoorWidth())
                    .quantity(item.getQuantity())
                    .unitCost(item.getUnitCost())
                    .amount(amountOf(item.getQuantity(), item.getUnitCost()))
                    .dyeLot(trimToNull(item.getDyeLot()))
                    .rollLengthM(item.getRollLengthM())
                    .remark(item.getRemark())
                    .build();
            inboundOrderItemMapper.insert(line);
            total = total.add(line.getAmount() != null ? line.getAmount() : BigDecimal.ZERO);
        }

        order.setTotalAmount(total);
        inboundOrderMapper.updateById(order);

        log.info("入库单已建（草稿，未动库存）: tenant={}, inboundNo={}, items={}, total={}, operator={}",
                tenantId, order.getInboundNo(), items.size(), total, operator);
        return detail(order.getId(), tenantId);
    }

    // ============================================================ 过账（核心）

    /**
     * 过账：**自动生成批次号** → **自动加库存** → 落库存台账 → 按移动加权平均重算成本。
     *
     * <p>状态迁移 {@code draft → posted} 是**幂等闸**：已过账的单再调一次会被拒（不会二次加库存）。
     * 整个方法在一个事务里，任一行失败 ⇒ 全部回滚（不留下「加了半个单」的库存）。</p>
     *
     * <p>成本口径：{@code after = (before_qty * before_avg + in_qty * unit_cost) / (before_qty + in_qty)}；
     * {@code before_qty = 0} 或 {@code before_avg} 未知 ⇒ {@code after = unit_cost}；
     * 行未记单价（{@code unitCost == null}）⇒ **只加数量，均价保持原值**（未记单价的入库不得
     * 把已有均价抹掉，也不得凭空造一个）。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public InboundOrderResponse post(String rawId, Long tenantId, String operator) {
        InboundOrder order = resolveOrder(rawId, tenantId);
        if (order == null) {
            throw BusinessException.notFound("入库单");
        }
        if (!InboundOrder.STATUS_DRAFT.equals(order.getStatus())) {
            // 幂等闸：只有草稿能过账。已过账 = 库存已加过，再放行就是**重复入库**（超卖的反面：虚增库存）
            throw BusinessException.conflict(
                    "入库单当前状态为「" + statusLabel(order.getStatus()) + "」，只有草稿可以过账",
                    "已过账的入库单不得重复过账（库存只加一次）；如需冲销请另开单据");
        }

        List<InboundOrderItem> lines = itemMapperList(order.getId(), tenantId);
        if (lines.isEmpty()) {
            throw BusinessException.validationError("入库单没有明细行，无法过账");
        }

        String batchNo = nextFreeBatchNo(tenantId);
        OffsetDateTime now = OffsetDateTime.now();

        for (InboundOrderItem line : lines) {
            ProductSku sku = productSkuMapper.selectById(line.getSkuId());
            if (sku == null) {
                throw BusinessException.validationError(
                        "明细行引用的 SKU 已不存在（货号 " + line.getSkuCode() + "），请删除该行后重新提交");
            }
            int beforeQty = sku.getStock() != null ? sku.getStock() : 0;
            BigDecimal beforeAvg = sku.getAvgCost();
            int quantity = line.getQuantity();
            BigDecimal unitCost = line.getUnitCost();
            BigDecimal afterAvg = movingAverage(beforeQty, beforeAvg, quantity, unitCost);
            int afterQty = beforeQty + quantity;

            // ① 加库存 + 写均价/成本金额/最近批次号（一条 SQL 内完成，避免「加了数量没写成本」的中间态）
            //    均价用本服务算出的 afterAvg（与下面台账里的 avg_cost_after **同源同值**）
            productSkuMapper.receiveStock(sku.getId(), quantity, afterAvg, batchNo);

            // ② 落库存台账（reason=inbound；成本快照一并落，使「库存/成本为什么变了」在同一张账上可对账）
            stockLedgerService.record(tenantId, line.getProductId(), sku.getId(), sku.getSkuCode(),
                    beforeQty, afterQty, StockLedger.REASON_INBOUND, order.getInboundNo(),
                    "入库单过账" + (line.getDyeLot() != null ? "（缸号 " + line.getDyeLot() + "）" : ""),
                    unitCost, beforeAvg, afterAvg);

            // ③ 批次台账（缸号随批次可见；批次行不可改，冲销走新单据）
            stockBatchMapper.insert(StockBatch.builder()
                    .tenantId(tenantId)
                    .batchNo(batchNo)
                    .productId(line.getProductId())
                    .skuId(sku.getId())
                    .skuCode(sku.getSkuCode())
                    .inboundOrderId(order.getId())
                    .inboundItemId(line.getId())
                    .inboundNo(order.getInboundNo())
                    .quantity(quantity)
                    .unitCost(unitCost)
                    .amount(amountOf(quantity, unitCost))
                    .dyeLot(line.getDyeLot())
                    .rollLengthM(line.getRollLengthM())
                    .supplier(order.getSupplier())
                    .warehouse(order.getWarehouse())
                    .receivedDate(order.getInboundDate())
                    .remark(line.getRemark())
                    .build());

            // ④ 行上回写批次号（草稿态为 NULL；过账后才有 —— 批次号 = 「真的收货了」）
            InboundOrderItem patch = new InboundOrderItem();
            patch.setId(line.getId());
            patch.setBatchNo(batchNo);
            inboundOrderItemMapper.updateById(patch);

            syncProductStock(line.getProductId());
        }

        order.setStatus(InboundOrder.STATUS_POSTED);
        order.setPostedAt(now);
        order.setPostedBy(operator);
        inboundOrderMapper.updateById(order);

        log.info("入库单已过账: tenant={}, inboundNo={}, batchNo={}, items={}, total={}, operator={}",
                tenantId, order.getInboundNo(), batchNo, lines.size(), order.getTotalAmount(), operator);
        return detail(order.getId(), tenantId);
    }

    // ============================================================ 作废

    /**
     * 作废（仅草稿可作废）。
     *
     * <p>已过账的单**不得**作废：库存已进台账，作废等于「悄悄把库存改回去且不留新凭据」。
     * 冲销必须另开单据（留痕）。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public InboundOrderResponse cancel(String rawId, String reason, Long tenantId, String operator) {
        InboundOrder order = resolveOrder(rawId, tenantId);
        if (order == null) {
            throw BusinessException.notFound("入库单");
        }
        if (!InboundOrder.STATUS_DRAFT.equals(order.getStatus())) {
            throw BusinessException.conflict(
                    "入库单当前状态为「" + statusLabel(order.getStatus()) + "」，只有草稿可以作废",
                    "已过账的入库单库存已进台账，冲销请另开单据（不原地改历史）");
        }
        order.setStatus(InboundOrder.STATUS_CANCELLED);
        order.setCancelledAt(OffsetDateTime.now());
        order.setCancelledBy(operator);
        order.setCancelledReason(reason);
        inboundOrderMapper.updateById(order);
        log.info("入库单已作废: tenant={}, inboundNo={}, operator={}, reason={}",
                tenantId, order.getInboundNo(), operator, reason);
        return detail(order.getId(), tenantId);
    }

    // ============================================================ 只读

    /** 列表（关键词匹配 单号/供应商/送货单号；状态精确匹配；按入库日期倒序） */
    public List<InboundOrderLine> list(String keyword, String status, Long tenantId) {
        return inboundOrderQueryMapper.selectOrderLines(tenantId, trimToNull(keyword), trimToNull(status), LIST_LIMIT);
    }

    /** 详情（单号 / UUID / 前缀 均可作为 id） */
    public InboundOrderResponse detail(String rawId, Long tenantId) {
        InboundOrder order = resolveOrder(rawId, tenantId);
        if (order == null) {
            throw BusinessException.notFound("入库单");
        }
        InboundOrderResponse resp = new InboundOrderResponse();
        BeanUtils.copyProperties(order, resp);
        List<InboundOrderResponse.Item> items = new ArrayList<>();
        for (InboundOrderItem line : itemMapperList(order.getId(), tenantId)) {
            InboundOrderResponse.Item item = new InboundOrderResponse.Item();
            BeanUtils.copyProperties(line, item);
            items.add(item);
        }
        resp.setItems(items);
        return resp;
    }

    /**
     * 批次查询（只读）：按 skuId / 缸号 / 来源入库单号过滤，最新在前。
     *
     * <p>**全部条件都限定 tenant_id**（跨租户读 = 数据泄漏，不是过滤问题）。</p>
     */
    public List<InboundBatchView> batches(Long skuId, String dyeLot, String inboundNo, Long tenantId) {
        LambdaQueryWrapper<StockBatch> wrapper = new LambdaQueryWrapper<StockBatch>()
                .eq(StockBatch::getTenantId, tenantId)
                .eq(skuId != null, StockBatch::getSkuId, skuId)
                .eq(StringUtils.hasText(dyeLot), StockBatch::getDyeLot, dyeLot)
                .eq(StringUtils.hasText(inboundNo), StockBatch::getInboundNo, inboundNo)
                .orderByDesc(StockBatch::getId)
                .last("LIMIT " + BATCH_LIMIT);
        List<InboundBatchView> views = new ArrayList<>();
        for (StockBatch batch : stockBatchMapper.selectList(wrapper)) {
            InboundBatchView view = new InboundBatchView();
            BeanUtils.copyProperties(batch, view);
            views.add(view);
        }
        return views;
    }

    // ============================================================ 校验

    /**
     * 校验请求（不靠注解 —— Agent/程序化调用不经过 Bean Validation，同 OrderService 口径）。
     *
     * @return 校验通过的明细行 + 各行 SKU（原样返回，避免调用方再查一次库）
     */
    private Validated validateRequest(InboundOrderCreateRequest req, Long tenantId) {
        if (req == null || req.getItems() == null || req.getItems().isEmpty()) {
            throw BusinessException.validationError("入库单至少要有 1 行明细");
        }
        // 按商品缓存 SKU：同一商品多行时不重复查库
        Map<String, Map<Long, ProductSku>> skuCache = new HashMap<>();
        List<InboundOrderCreateRequest.Item> items = new ArrayList<>();
        Map<Long, ProductSku> skuByIdAll = new LinkedHashMap<>();
        int idx = 0;
        for (InboundOrderCreateRequest.Item item : req.getItems()) {
            idx++;
            if (item == null || !StringUtils.hasText(item.getProductId())) {
                throw BusinessException.validationError("商品明细第 " + idx + " 项缺少商品");
            }
            if (item.getSkuId() == null) {
                throw BusinessException.validationError("商品明细第 " + idx + " 项缺少 SKU");
            }
            if (item.getQuantity() == null || item.getQuantity() < 1) {
                // 数量是 INTEGER：非整数米（如 60.5 米）本单不支持 —— 显式拒绝，**不静默取整**
                // （静默取整 = 账面与实物不符且无人发现；库存米数小数化是独立改动）
                throw BusinessException.validationError("商品明细第 " + idx + " 项的数量必须是 ≥1 的整数（按米入库暂不支持小数米）");
            }
            if (item.getUnitCost() != null && item.getUnitCost().compareTo(BigDecimal.ZERO) <= 0) {
                throw BusinessException.validationError("商品明细第 " + idx + " 项的入库单价必须大于 0（不记单价请留空）");
            }
            Map<Long, ProductSku> skuById = skuCache.computeIfAbsent(item.getProductId(), this::skusOfProduct);
            if (!skuById.containsKey(item.getSkuId())) {
                // SKU 与商品不匹配 = 串行/越权写入：必须挡住（否则库存会加到别的货号上）
                throw BusinessException.validationError(
                        "商品明细第 " + idx + " 项的 SKU 不属于该商品（或不存在），请重新选择");
            }
            items.add(item);
            skuByIdAll.put(item.getSkuId(), skuById.get(item.getSkuId()));
        }
        return new Validated(items, skuByIdAll);
    }

    /**
     * 校验结果：明细行 + 各行的 SKU 实体。
     *
     * <p>把 SKU 一起带出来，是为了让建单路径**不重复查库**（校验阶段本就必须读到 SKU
     * 才能判「SKU 属于该商品」）—— 重复查一次不仅多一次 IO，还多一个「两次读到的 SKU
     * 不是同一个」的窗口。</p>
     */
    private record Validated(List<InboundOrderCreateRequest.Item> items, Map<Long, ProductSku> skuById) {}

    /** 该商品在本租户下的全部 SKU（id → 实体） */
    private Map<Long, ProductSku> skusOfProduct(String productId) {
        Product product = productMapper.selectById(productId);
        if (product == null) {
            throw BusinessException.validationError("商品不存在：" + productId);
        }
        List<ProductSku> skus = productSkuMapper.selectList(
                new LambdaQueryWrapper<ProductSku>().eq(ProductSku::getProductId, productId));
        Map<Long, ProductSku> map = new LinkedHashMap<>();
        for (ProductSku sku : skus) {
            map.put(sku.getId(), sku);
        }
        return map;
    }

    // ============================================================ 内部工具

    /**
     * 解析入库单：支持 UUID / 入库单号 / 单号前缀。
     * 匹配优先级：UUID 完整匹配 → UUID 前缀 → 单号精确匹配（同 ProcessingOrderService 口径）。
     */
    private InboundOrder resolveOrder(String rawId, Long tenantId) {
        if (!StringUtils.hasText(rawId)) {
            return null;
        }
        InboundOrder byId = inboundOrderMapper.selectOne(new LambdaQueryWrapper<InboundOrder>()
                .eq(InboundOrder::getId, rawId)
                .eq(InboundOrder::getTenantId, tenantId)
                .last("LIMIT 1"));
        if (byId != null) {
            return byId;
        }
        List<InboundOrder> byPrefix = inboundOrderMapper.selectList(new LambdaQueryWrapper<InboundOrder>()
                .eq(InboundOrder::getTenantId, tenantId)
                .likeRight(InboundOrder::getId, rawId)
                .last("LIMIT 2"));
        if (byPrefix.size() == 1) {
            return byPrefix.get(0);
        }
        return inboundOrderMapper.selectOne(new LambdaQueryWrapper<InboundOrder>()
                .eq(InboundOrder::getTenantId, tenantId)
                .eq(InboundOrder::getInboundNo, rawId)
                .last("LIMIT 1"));
    }

    private List<InboundOrderItem> itemMapperList(String orderId, Long tenantId) {
        return inboundOrderItemMapper.selectList(new LambdaQueryWrapper<InboundOrderItem>()
                .eq(InboundOrderItem::getInboundOrderId, orderId)
                .eq(InboundOrderItem::getTenantId, tenantId)
                .orderByAsc(InboundOrderItem::getId));
    }

    /**
     * 入库单号：{@code RK-yyyyMMdd-NNNN}。
     *
     * <p>与订单号（17 位数字）、加工单号 {@code JG-yyyyMMdd-NNNN}、售后单号 {@code AS-*} 同族：
     * 前缀 + 日期 + 序号。序号是进程内原子计数器（降低同秒碰撞），**DB 唯一索引兜底防重号**
     * （同 {@code ProcessingOrderService.generateOrderNo} 的既有口径）。</p>
     */
    private String generateInboundNo() {
        return "RK-" + LocalDate.now().format(DATE_FMT) + "-"
                + String.format("%04d", INBOUND_SEQ.incrementAndGet() % 10_000);
    }

    /**
     * 批次号：{@code PC-yyyyMMdd-NNNN}（{@code PC} = 批次拼音首字母，与 JG/AS/FIN/RK 不撞前缀）。
     *
     * <p><b>一次过账一个批次号</b>（批次 = 入库单行，用户裁定）：整张单的明细行共享同一批次号 ——
     * 同一张送货单上的同一缸布本就是一批，逐行各编一个号反而会让「同批」在库里看不出来。</p>
     */
    private String generateBatchNo() {
        return "PC-" + LocalDate.now().format(DATE_FMT) + "-"
                + String.format("%04d", BATCH_SEQ.incrementAndGet() % 10_000);
    }

    /**
     * 取一个**库内未被占用**的批次号（租户内）。
     *
     * <p>为什么不能只靠原子计数器：计数器是**进程内**的，服务重启后从 0 开始 ⇒ 当天已用过
     * 的 {@code PC-<今天>-0001} 会被再次生成，撞 {@code uk_stock_batches_no} 唯一索引
     * ⇒ **整张单过账失败**（事务回滚）。批次号是印在卷标上的追溯标识，不能靠「重启得够少」。</p>
     *
     * <p>重试上限 20 次（远超「同一天重启 20 次且每次都恰好撞上」的实际情况）；
     * 耗尽则显式抛错 —— 不静默用一个可能重复的号。</p>
     */
    private String nextFreeBatchNo(Long tenantId) {
        for (int i = 0; i < 20; i++) {
            String candidate = generateBatchNo();
            boolean taken = stockBatchMapper.exists(new LambdaQueryWrapper<StockBatch>()
                    .eq(StockBatch::getTenantId, tenantId)
                    .eq(StockBatch::getBatchNo, candidate));
            if (!taken) {
                return candidate;
            }
            log.warn("批次号已被占用，重新生成: tenant={}, candidate={}", tenantId, candidate);
        }
        throw new BusinessException("BATCH_NO_EXHAUSTED",
                "批次号连续 20 次生成失败（当天号段疑似被占满），请稍后重试或联系管理员", 409);
    }

    /**
     * 移动加权平均：{@code (before_qty * before_avg + in_qty * unit_cost) / (before_qty + in_qty)}。
     *
     * <ul>
     *   <li>未记单价（{@code unitCost == null}）⇒ 返回 {@code beforeAvg}（**保持原值**，
     *       不因「这批没记价」把已有均价抹掉）；</li>
     *   <li>变更前无库存或均价未知 ⇒ 返回 {@code unitCost}（首次入库的均价就是进价）。</li>
     * </ul>
     *
     * @return 变更后的均价；无任何成本信息时为 {@code null}（**不用 0 冒充「成本为零」**）
     */
    static BigDecimal movingAverage(int beforeQty, BigDecimal beforeAvg, int quantity, BigDecimal unitCost) {
        if (unitCost == null) {
            return beforeAvg;
        }
        if (beforeQty <= 0 || beforeAvg == null) {
            return unitCost;
        }
        BigDecimal beforeValue = beforeAvg.multiply(BigDecimal.valueOf(beforeQty));
        BigDecimal inValue = unitCost.multiply(BigDecimal.valueOf(quantity));
        return beforeValue.add(inValue)
                .divide(BigDecimal.valueOf((long) beforeQty + quantity), 4, RoundingMode.HALF_UP);
    }

    /**
     * 商品级库存是**派生值**（issue #4038：{@code product_skus.stock} 是权威、{@code products.stock} 是派生）
     * ⇒ 入库改的是 SKU，商品级列按 SKU 汇总回写。
     *
     * <p>只在该商品**有 SKU 记录**时回写（无 SKU 的商品该列是唯一现存信息，
     * 回写成 {@code SUM(空) = 0} 会把有值的库存抹掉 —— issue #4038 的 R2 负例）。</p>
     */
    private void syncProductStock(String productId) {
        List<ProductSku> skus = productSkuMapper.selectList(
                new LambdaQueryWrapper<ProductSku>()
                        .eq(ProductSku::getProductId, productId)
                        .select(ProductSku::getStock));
        if (skus == null || skus.isEmpty()) {
            return;
        }
        int total = skus.stream().mapToInt(s -> s.getStock() != null ? s.getStock() : 0).sum();
        Product patch = new Product();
        patch.setId(productId);
        patch.setStock(total);
        productMapper.updateById(patch);
    }

    private static BigDecimal amountOf(Integer quantity, BigDecimal unitCost) {
        return unitCost == null ? null : unitCost.multiply(BigDecimal.valueOf(quantity));
    }

    private static String trimToNull(String s) {
        return StringUtils.hasText(s) ? s.trim() : null;
    }

    private static String statusLabel(String status) {
        return switch (status == null ? "" : status) {
            case InboundOrder.STATUS_DRAFT -> "草稿";
            case InboundOrder.STATUS_POSTED -> "已过账";
            case InboundOrder.STATUS_CANCELLED -> "已作废";
            default -> status;
        };
    }
}
