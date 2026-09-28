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
import com.migao.admin.time.BusinessClock;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.BeanUtils;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.math.RoundingMode;
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
 * 故草稿态完全不动库存，过账是**一次性、不可重复**的状态迁移
 * （幂等闸 = 条件更新 CAS + 行锁，见 {@link #post}；issue #5148 前的「读 status → 判 draft → 写」
 * 只是状态机、**没有**并发闸 —— 双击会库存加两次）。</p>
 *
 * <p><b>幂等（issue #5148）</b>：① 过账 = 条件更新原子闸（同一张单只许一次 draft→posted）；
 * ② 建单 = 可选的运行级幂等键 {@code import_run_id}（V117 部分唯一索引）⇒ 同一份导入重跑
 * 返回**同一张单**，不建第二张（否则两张都过账 = 库存加两次）。</p>
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

    /** 业务时钟（issue #3802）：业务「今天」的唯一来源。Spring 注入单例；**不扫描 @Component 的切片上下文**
     * （@WebMvcTest / ApplicationContextRunner）与直接 new 构造的既有单测没有该 bean ⇒ required=false +
     * 默认实例（同为 +08 口径，行为一致），不因引入时钟让任何既有上下文启动失败（实测 OssEmptyConfigContextTest）。 */
    @Autowired(required = false)
    private BusinessClock businessClock = new BusinessClock();

    private final InboundOrderMapper inboundOrderMapper;
    private final InboundOrderItemMapper inboundOrderItemMapper;
    private final InboundOrderQueryMapper inboundOrderQueryMapper;
    private final StockBatchMapper stockBatchMapper;
    private final ProductSkuMapper productSkuMapper;
    private final ProductMapper productMapper;
    private final StockLedgerService stockLedgerService;

    /**
     * 池化事件通知点（issue #5182）：过账**既有业务完成之后**追加的一句 fail-soft 通知
     * —— 新批次入库 = 可用余量变化 ⇒ 池里原本凑不满的组合可能就凑得满了。
     *
     * <p>字段注入 + {@code required = false} + 调用侧 {@code notifySafely}
     * （{@code null} ⇒ 跳过并留痕）：**过账语义与异常语义逐字不变**（公告口径见
     * {@code ProcessingOrderService.stockBatchConsumptionService}）。</p>
     */
    @Autowired(required = false)
    private PoolChangeNotifier poolChangeNotifier;

    // ============================================================ 建单

    /**
     * 建单（草稿态，**不动库存**）。
     *
     * <p>批次号**此时不生成** —— 它代表「真的收货了」，只在过账时写（见 {@link #post}）。</p>
     *
     * <p><b>幂等（issue #5148 GAP-02）</b>：带 {@code importRunId} 时，同一
     * {@code (tenantId, importRunId)} 只建一张单 —— 已存在则直接返回那一张（不建第二张；
     * 两张草稿都过账 = 库存加两次）。判据在 DB：部分唯一索引
     * {@code uk_inbound_orders_tenant_import_run (tenant_id, import_run_id)
     * WHERE import_run_id IS NOT NULL AND deleted = 0}（V117）——
     * 「先查后插」之间有窗口，唯一索引才是**原子**的那道保证。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public InboundOrderResponse create(InboundOrderCreateRequest req, Long tenantId, String operator) {
        Validated validated = validateRequest(req, tenantId);
        List<InboundOrderCreateRequest.Item> items = validated.items();
        String source = validated.source();
        String importRunId = trimToNull(req.getImportRunId());

        // 运行级幂等：同一份导入重跑 ⇒ 返回**同一张**单（不建第二张）
        if (importRunId != null) {
            InboundOrder existing = findImportRun(tenantId, importRunId);
            if (existing != null) {
                log.info("同一导入运行已建过单，直接返回既有单据（不建第二张）: tenant={}, importRunId={}, inboundNo={}",
                        tenantId, importRunId, existing.getInboundNo());
                return detail(existing.getId(), tenantId);
            }
        }

        InboundOrder order = InboundOrder.builder()
                .tenantId(tenantId)
                .inboundNo(nextFreeInboundNo(tenantId))
                .supplier(trimToNull(req.getSupplier()))
                .supplierDocNo(trimToNull(req.getSupplierDocNo()))
                .warehouse(trimToNull(req.getWarehouse()))
                .inboundDate(req.getInboundDate() != null ? req.getInboundDate() : businessClock.today())
                .status(InboundOrder.STATUS_DRAFT)
                .totalAmount(BigDecimal.ZERO)
                .source(source)
                .importRunId(importRunId)
                .remark(req.getRemark())
                .createdBy(operator)
                .build();
        try {
            inboundOrderMapper.insert(order);
        } catch (DuplicateKeyException e) {
            // 并发同键（两份请求同时走到这里）：唯一索引是原子判据，只有一个能落库。
            // 唯一索引的冲突会让 PG 的**当前事务进入 aborted 状态**（后续查询全失败）⇒
            // 不能在本事务里再去回读那张单，只能 fail-closed 让调用方重查（重查即命中幂等分支）。
            log.warn("入库单建单撞唯一索引（并发同键或同号）: tenant={}, importRunId={}, inboundNo={}",
                    tenantId, importRunId, order.getInboundNo());
            // 唯一索引有两个（单号 / 运行标识）⇒ 文案两义都覆盖，不把冲突来源说死
            String subject = importRunId != null ? "运行标识 " + importRunId : "单号 " + order.getInboundNo();
            throw BusinessException.conflict(
                    "入库单未创建：同一单号或同一份导入（" + subject + "）刚刚已被创建",
                    "请刷新列表查看既有单据；重复提交不会建出第二张单（库存不会加两次）");
        }

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
                    // 旧系统批次号（V118 / issue #5153）：**外部事实**，原样透传 —— 与 batch_no
                    // （服务端生成的系统号）两列两义，永不互相赋值（V111 明令不得互相冒充）
                    .legacyBatchNo(item.getLegacyBatchNo())
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
     * 过账：**抢过账权（原子闸）** → **自动生成批次号** → **自动加库存** → 落库存台账 → 按移动加权平均重算成本。
     *
     * <p>状态迁移 {@code draft → posted} 是**幂等闸**：已过账的单再调一次会被拒（不会二次加库存）。
     * 整个方法在一个事务里，任一行失败 ⇒ 全部回滚（不留下「加了半个单」的库存）。</p>
     *
     * <p><b>并发闸 = 条件更新（CAS）+ PG 行锁</b>（issue #5148）：{@code UPDATE … SET status='posted'
     * WHERE id=? AND tenant_id=? AND status='draft' AND deleted=0}，按**影响行数**判是否抢到过账权。
     * 为什么是它而不是「先读 status 判 draft 再写」：读-判-写之间有窗口，双击/并发会让两个请求
     * **都**通过判断 ⇒ 各自加一遍库存（改前的形态，改后由本闸挡住）；条件更新的判断与写入是
     * **同一条语句**，PG 对命中行加行锁并持有到事务结束 ⇒ 后到的那个要么阻塞到前者提交、
     * 要么看到 0 行受影响。**闸必须在任何库存写入之前**：放到最后写状态时，两个并发请求
     * 早已各加完一遍库存（互斥发生在伤害之后 = 没有闸）。</p>
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

        List<String> batchNos = new ArrayList<>(lines.size());
        OffsetDateTime now = OffsetDateTime.now();

        // ⓪ 抢过账权：条件更新（CAS），判断与写入同一条语句 + PG 行锁 ⇒ 并发/双击只有一个能进来。
        //    放在明细校验之后（无效请求不占行锁）、库存写入之前（互斥必须发生在伤害之前）
        if (inboundOrderMapper.markPosted(order.getId(), tenantId, operator, now) == 0) {
            // 抢不到：并发的另一个请求刚过账成功（也可能刚被作废）⇒ 回读真实状态，给准确的文案
            InboundOrder fresh = inboundOrderMapper.selectById(order.getId());
            throw BusinessException.conflict(
                    "入库单当前状态为「" + statusLabel(fresh != null ? fresh.getStatus() : order.getStatus())
                            + "」，只有草稿可以过账",
                    "已过账的入库单不得重复过账（库存只加一次）；如需冲销请另开单据");
        }
        order.setStatus(InboundOrder.STATUS_POSTED);
        order.setPostedAt(now);
        order.setPostedBy(operator);

        for (InboundOrderItem line : lines) {
            ProductSku sku = productSkuMapper.selectById(line.getSkuId());
            if (sku == null) {
                throw BusinessException.validationError(
                        "明细行引用的 SKU 已不存在（货号 " + line.getSkuCode() + "），请删除该行后重新提交");
            }
            // issue #5063（V115）：库存列与入库行数量同为 NUMERIC(12,1) ⇒ 全程 BigDecimal
            // （改前 `int beforeQty = sku.getStock()` / `int quantity = line.getQuantity()`
            //  在入库量是 60.5 米时根本走不到这里 —— 校验阶段就显式拒绝了；本单把两侧一起放开）
            BigDecimal beforeQty = StockQuantity.orZero(sku != null ? sku.getStock() : null);
            BigDecimal beforeAvg = sku.getAvgCost();
            BigDecimal quantity = StockQuantity.orZero(line.getQuantity());
            BigDecimal unitCost = line.getUnitCost();
            BigDecimal afterAvg = movingAverage(beforeQty, beforeAvg, quantity, unitCost);
            BigDecimal afterQty = beforeQty.add(quantity);

            // ① 批次号**逐行生成**（一个 SKU 行 = 一个批次，V111 裁定）：整单共用一个号时，
            //    第 2 行插 stock_batches 会撞 uk_stock_batches_no = UNIQUE (tenant_id, batch_no)
            //    ⇒ 整个事务回滚（≥2 行的入库单必然过账失败，issue #5141）
            String batchNo = nextFreeBatchNo(tenantId);
            batchNos.add(batchNo);

            // ② 加库存 + 写均价/成本金额/最近批次号（一条 SQL 内完成，避免「加了数量没写成本」的中间态）
            //    均价用本服务算出的 afterAvg（与下面台账里的 avg_cost_after **同源同值**）
            productSkuMapper.receiveStock(sku.getId(), quantity, afterAvg, batchNo);

            // ③ 落库存台账（reason=inbound；成本快照一并落，使「库存/成本为什么变了」在同一张账上可对账）
            stockLedgerService.record(tenantId, line.getProductId(), sku.getId(), sku.getSkuCode(),
                    beforeQty, afterQty, StockLedger.REASON_INBOUND, order.getInboundNo(),
                    "入库单过账" + (line.getDyeLot() != null ? "（缸号 " + line.getDyeLot() + "）" : ""),
                    unitCost, beforeAvg, afterAvg);

            // ④ 批次台账（缸号随批次可见；批次行不可改，冲销走新单据）
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
                    // 旧系统批次号（V118 / issue #5153）：明细行 → 批次行**透传**。建单与过账是两次
                    // 请求 ⇒ 明细行不落这一列，建单时填的旧号在过账那一刻就丢了
                    .legacyBatchNo(line.getLegacyBatchNo())
                    .rollLengthM(line.getRollLengthM())
                    .supplier(order.getSupplier())
                    .warehouse(order.getWarehouse())
                    .receivedDate(order.getInboundDate())
                    .remark(line.getRemark())
                    .build());

            // ⑤ 行上回写批次号（草稿态为 NULL；过账后才有 —— 批次号 = 「真的收货了」）
            InboundOrderItem patch = new InboundOrderItem();
            patch.setId(line.getId());
            patch.setBatchNo(batchNo);
            inboundOrderItemMapper.updateById(patch);

            syncProductStock(line.getProductId());
        }

        log.info("入库单已过账: tenant={}, inboundNo={}, batchNos={}, items={}, total={}, operator={}",
                tenantId, order.getInboundNo(), batchNos, lines.size(), order.getTotalAmount(), operator);
        // 🔴 事件驱动自动成批（issue #5182 挂载点 ②）：**既有过账全部完成之后**追加的
        // fail-soft 通知点（过账语义、事务边界、异常语义逐字不变）。
        PoolChangeNotifier.notifySafely(poolChangeNotifier, tenantId,
                PoolChangeNotifier.TRIGGER_INBOUND_POSTED);
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
    public List<InboundBatchView> batches(Long skuId, String dyeLot, String inboundNo,
                                          String legacyBatchNo, Long tenantId) {
        LambdaQueryWrapper<StockBatch> wrapper = new LambdaQueryWrapper<StockBatch>()
                .eq(StockBatch::getTenantId, tenantId)
                .eq(skuId != null, StockBatch::getSkuId, skuId)
                .eq(StringUtils.hasText(dyeLot), StockBatch::getDyeLot, dyeLot)
                .eq(StringUtils.hasText(inboundNo), StockBatch::getInboundNo, inboundNo)
                // 按**旧系统批次号**查回来（V118 / issue #5153）——期初登记进来的批次要「能被看见」：
                // 迁移期最常见的问法是「旧系统里那个号在 MIGAO 里是哪一批、还剩多少」
                .eq(StringUtils.hasText(legacyBatchNo), StockBatch::getLegacyBatchNo, legacyBatchNo)
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
     * <p>单据来源在这里一并归一（{@link #normalizeSource}）并随 {@link Validated} 带出：明细行的
     * 「旧系统批次号只在期初建账时可填」这条判据**依赖它**，而来源口径全仓只有
     * {@code normalizeSource} 一处（不在这里再写第二遍取值集合）。</p>
     *
     * @return 校验通过的明细行 + 各行 SKU（原样返回，避免调用方再查一次库）+ 归一后的单据来源
     */
    private Validated validateRequest(InboundOrderCreateRequest req, Long tenantId) {
        if (req == null || req.getItems() == null || req.getItems().isEmpty()) {
            throw BusinessException.validationError("入库单至少要有 1 行明细");
        }
        String source = normalizeSource(req.getSource());
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
            // 数量/单价判据**只有一处**（requireItemNumbers）：建单与批量建账导入共用同一条口径
            item.setQuantity(requireItemNumbers(item.getQuantity(), item.getUnitCost(),
                    "商品明细第 " + idx + " 项的数量", "商品明细第 " + idx + " 项的入库单价"));
            item.setLegacyBatchNo(legacyBatchNoOf(item.getLegacyBatchNo(), source, idx));
            Map<Long, ProductSku> skuById = skuCache.computeIfAbsent(item.getProductId(), this::skusOfProduct);
            if (!skuById.containsKey(item.getSkuId())) {
                // SKU 与商品不匹配 = 串行/越权写入：必须挡住（否则库存会加到别的货号上）
                throw BusinessException.validationError(
                        "商品明细第 " + idx + " 项的 SKU 不属于该商品（或不存在），请重新选择");
            }
            items.add(item);
            skuByIdAll.put(item.getSkuId(), skuById.get(item.getSkuId()));
        }
        return new Validated(items, skuByIdAll, source);
    }

    /**
     * 单行**数值准入** —— 全仓**唯一一处**（下限、粒度、单价三条口径都在这里）。
     *
     * <p>建单（{@link #validateRequest}）与期初建账的 Excel 批量导入
     * （{@link OpeningRegisterImportService}）**共用**本方法：两处各写一遍必然漂移
     * （一处收 0.5、另一处拒 0.5，用户看到的是「同一个数有时能填有时不能」）。</p>
     *
     * <h3>下限：{@code > 0} 米（issue #5153，GAP-12 —— 放宽的是「≥1 米」这条）</h3>
     * 用户痛点逐字：「当前企业剩余了**大量的 0.5 米左右**的批次布料」，而改前的
     * {@code quantity ≥ 1} 让这些批次**连登记都进不来**（尾料被系统挡在门外 = 看不见 = 假真值）。
     * 尾部米数是**实物事实**，拒绝它等于让系统说谎。
     *
     * <p>🔴 <b>下限与粒度是同一个判据的两半，不是两条口径</b>：{@code > 0} 加上
     * 「最多 1 位小数」（{@link StockQuantity#requireOneDecimal}）⇒ 合法值恒
     * {@code ≥ 0.1} 米。所以全仓**不需要也不得**再写一个 {@code 0.1} 的字面量下限
     * （写了就是第二处口径，迟早在某条路径上漂移）。</p>
     *
     * <h3>粒度：仍是最多 1 位小数（**没有**因为放宽下限而放宽）</h3>
     * 超 1 位小数（如 {@code 2.755}）⇒ **显式拒绝**，绝不静默取整 ——
     * {@code stock_batches.quantity} 是 {@code NUMERIC(12,1)}，PG 对超 scale 的写入会
     * **静默四舍五入且不报错**，所以 fail-closed 只能在应用层本方法里完成。
     *
     * <h3>🔴 不得改用它做归一</h3>
     * 归一**只能**用 {@link StockQuantity#requireOneDecimal} 一族（库存类输入口径：拒绝非法值）。
     * **不得**换成 {@link StockQuantity#toStockScaleByCeiling}（**订单侧**口径：向上进位，模拟裁床
     * 用料）—— 用在批次余量上每条最多虚增 {@code +0.099m} = **系统性虚增资产**
     * （#5149 §3.6.2 的显式禁令；用户裁定「不能损失客户」）。
     *
     * @return 归一后的数量（去尾零的合法值：{@code 2.70} → {@code 2.7}、{@code 10.00} → {@code 10}）
     */
    static BigDecimal requireItemNumbers(BigDecimal quantity, BigDecimal unitCost,
                                         String quantityLabel, String unitCostLabel) {
        BigDecimal qty = StockQuantity.orZero(quantity);
        if (qty.signum() <= 0) {
            throw BusinessException.validationError(
                    quantityLabel + "必须大于 0 米（按米入库；库存按 0.1 米粒度记账，"
                            + "0.5 米的尾料可如实登记）");
        }
        BigDecimal normalized = StockQuantity.requireOneDecimal(qty, quantityLabel);
        if (unitCost != null && unitCost.compareTo(BigDecimal.ZERO) <= 0) {
            throw BusinessException.validationError(unitCostLabel + "必须大于 0（不记单价请留空）");
        }
        return normalized;
    }

    /**
     * 旧系统批次号准入（V118 / issue #5153）：**只在期初建账（{@code source=opening}）时可填**。
     *
     * <p>为什么必须在语义层挡住：{@code legacy_batch_no} 与 {@code batch_no}（服务端生成的
     * {@code PC-yyyyMMdd-NNNN}）是**两列两义**，V111 明令不得互相冒充（{@code dye_lot} 亦然）。
     * 采购收货的批次号由服务端生成，没有「旧系统批次号」这个事实 —— 放行它只会让两列的含义
     * 在数据里混起来（事后无法区分哪个号是系统发的）。</p>
     */
    private static String legacyBatchNoOf(String raw, String source, int idx) {
        String value = trimToNull(raw);
        if (value == null) {
            return null;
        }
        if (!InboundOrder.SOURCE_OPENING.equals(source)) {
            throw BusinessException.validationError(
                    "商品明细第 " + idx + " 项填了旧系统批次号，但本单来源是「采购收货」—— "
                            + "旧系统批次号只在期初建账（source=opening）时可填"
                            + "（系统批次号与旧系统批次号不得互相冒充）");
        }
        return value;
    }

    /**
     * 校验结果：明细行 + 各行的 SKU 实体 + 归一后的单据来源。
     *
     * <p>把 SKU 一起带出来，是为了让建单路径**不重复查库**（校验阶段本就必须读到 SKU
     * 才能判「SKU 属于该商品」）—— 重复查一次不仅多一次 IO，还多一个「两次读到的 SKU
     * 不是同一个」的窗口。</p>
     */
    private record Validated(List<InboundOrderCreateRequest.Item> items, Map<Long, ProductSku> skuById,
                             String source) {}

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
     * 前缀 + 日期 + 序号。序号是进程内原子计数器（降低同秒碰撞），实际取号走
     * {@link #nextFreeInboundNo}（查库占用 + 重试），**DB 唯一索引兜底防重号**
     * （同 {@code ProcessingOrderService.generateOrderNo} 的既有口径）。</p>
     */
    private String generateInboundNo() {
        return "RK-" + businessClock.today().format(DATE_FMT) + "-"
                + String.format("%04d", INBOUND_SEQ.incrementAndGet() % 10_000);
    }

    /**
     * 取一个**库内未被占用**的入库单号（租户内）。
     *
     * <p>为什么不能只靠原子计数器：计数器是**进程内**的，服务重启 / 换副本后从 0 开始 ⇒ 当天已用过的
     * {@code RK-<今天>-0001} 会被再次生成，撞唯一索引 ⇒ **建单直接失败**（用户只看到「建单失败」，
     * 看不出是重号）。单号是要印在单据上、要对账的标识，不能靠「重启得够少」。</p>
     *
     * <p>重试上限 20 次（远超「同一天重启 20 次且每次都恰好撞上」的实际情况）；耗尽则显式抛错 ——
     * 不静默用一个可能重复的号。</p>
     *
     * <p><b>边界（如实登记）</b>：查占用与插入之间仍有窗口 ⇒ 两个**同时**建单的进程理论上可选中同号，
     * 此时由唯一索引挡下（后到者收到明确失败，不会静默重号）；单一进程内计数器单调递增，
     * 该窗口只在多副本/重启瞬间存在。</p>
     */
    private String nextFreeInboundNo(Long tenantId) {
        for (int i = 0; i < 20; i++) {
            String candidate = generateInboundNo();
            boolean taken = inboundOrderMapper.exists(new LambdaQueryWrapper<InboundOrder>()
                    .eq(InboundOrder::getTenantId, tenantId)
                    .eq(InboundOrder::getInboundNo, candidate));
            if (!taken) {
                return candidate;
            }
            log.warn("入库单号已被占用，重新生成: tenant={}, candidate={}", tenantId, candidate);
        }
        throw new BusinessException("INBOUND_NO_EXHAUSTED",
                "入库单号连续 20 次生成失败（当天号段疑似被占满），请稍后重试或联系管理员", 409);
    }

    /** 该运行标识在本租户下**已建的**入库单（软删行不算：V117 的部分唯一索引带 {@code deleted = 0} 谓词） */
    private InboundOrder findImportRun(Long tenantId, String importRunId) {
        return inboundOrderMapper.selectOne(new LambdaQueryWrapper<InboundOrder>()
                .eq(InboundOrder::getTenantId, tenantId)
                .eq(InboundOrder::getImportRunId, importRunId)
                .last("LIMIT 1"));
    }

    /**
     * 单据来源归一：缺失 ⇒ {@code purchase}（V111 时期只有采购收货这一种来源）；取值只许
     * {@code purchase} / {@code opening}（与 V117 的 {@code ck_inbound_orders_source} 同口径，
     * 应用层先拒是为了给出可行动文案，而不是把 DB 的 23514 透传成 500）。
     */
    private static String normalizeSource(String source) {
        if (!StringUtils.hasText(source)) {
            return InboundOrder.SOURCE_PURCHASE;
        }
        String value = source.trim();
        if (!InboundOrder.SOURCE_PURCHASE.equals(value) && !InboundOrder.SOURCE_OPENING.equals(value)) {
            throw BusinessException.validationError(
                    "单据来源只支持 purchase（采购收货）/ opening（期初建账），收到：" + source);
        }
        return value;
    }

    /**
     * 批次号：{@code PC-yyyyMMdd-NNNN}（{@code PC} = 批次拼音首字母，与 JG/AS/FIN/RK 不撞前缀）。
     *
     * <p><b>一个 SKU 行 = 一个批次</b>（V111 文件头的用户裁定）：每次调用生成一个号，
     * 由 {@link #post} 在明细行循环内**逐行**取 —— 同一 SKU 的两行若缸号不同，本就是两批。</p>
     */
    private String generateBatchNo() {
        return "PC-" + businessClock.today().format(DATE_FMT) + "-"
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
    static BigDecimal movingAverage(BigDecimal beforeQty, BigDecimal beforeAvg,
                                    BigDecimal quantity, BigDecimal unitCost) {
        BigDecimal qtyBefore = StockQuantity.orZero(beforeQty);
        BigDecimal qtyIn = StockQuantity.orZero(quantity);
        if (unitCost == null) {
            return beforeAvg;
        }
        if (qtyBefore.signum() <= 0 || beforeAvg == null) {
            return unitCost;
        }
        BigDecimal beforeValue = beforeAvg.multiply(qtyBefore);
        BigDecimal inValue = unitCost.multiply(qtyIn);
        return beforeValue.add(inValue)
                .divide(qtyBefore.add(qtyIn), 4, RoundingMode.HALF_UP);
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
        // issue #5063（V115）：派生列按 SKU 汇总必须保精度（改前 mapToInt 会把 60.5 截成 60）
        BigDecimal total = StockQuantity.sum(
                skus.stream().map(ProductSku::getStock).collect(java.util.stream.Collectors.toList()));
        Product patch = new Product();
        patch.setId(productId);
        patch.setStock(total);
        productMapper.updateById(patch);
    }

    private static BigDecimal amountOf(BigDecimal quantity, BigDecimal unitCost) {
        return unitCost == null ? null : unitCost.multiply(StockQuantity.orZero(quantity));
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
