package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.dto.InboundBatchView;
import com.migao.admin.dto.InboundOrderCreateRequest;
import com.migao.admin.dto.InboundOrderLine;
import com.migao.admin.dto.InboundOrderResponse;
import com.migao.admin.dto.NotificationEvent;
import com.migao.admin.entity.FinishedGoodsStock;
import com.migao.admin.entity.InboundOrder;
import com.migao.admin.entity.InboundOrderItem;
import com.migao.admin.entity.ProcessingOrderSet;
import com.migao.admin.entity.ProcessingSetPartToken;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.Product;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.entity.StockBatch;
import com.migao.admin.entity.StockLedger;
import com.migao.admin.entity.WarehouseLocation;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.InboundOrderItemMapper;
import com.migao.admin.mapper.InboundOrderMapper;
import com.migao.admin.mapper.InboundOrderQueryMapper;
import com.migao.admin.mapper.FinishedGoodsStockMapper;
import com.migao.admin.mapper.ProcessingOrderSetMapper;
import com.migao.admin.mapper.ProcessingSetPartTokenMapper;
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
@RequiredArgsConstructor(onConstructor_ = @Autowired)
public class InboundOrderService {

    private static final DateTimeFormatter DATE_FMT = DateTimeFormatter.ofPattern("yyyyMMdd");

    /** 入库单号序号（RK-yyyyMMdd-NNNN）；DB 唯一索引兜底防重号，同 ProcessingOrderService 口径 */
    private static final AtomicInteger INBOUND_SEQ = new AtomicInteger(0);
    /** 批次号序号（PC-yyyyMMdd-NNNN） */
    private static final AtomicInteger BATCH_SEQ = new AtomicInteger(0);

    /** 成品仓位分配的尝试上限（每次「找空闲 → 占位」失败都换下一个候选；正常 1 次内命中）。 */
    private static final int FINISHED_BIN_ATTEMPTS = 8;

    /** 列表一次最多返回的单据数（同族页面口径；入库单是流水型单据，不做深分页） */
    private static final int LIST_LIMIT = 200;
    /** 批次查询一次最多返回的行数 */
    /**
     * **V196 形态的构造器**（保留给既有单测与旧装配）：两个 V197 依赖传 null。
     *
     * <p>为什么保留：本仓有多处**直接 new** 的切片测试（真库竞态 / Controller 切片）在建这个服务，
     * 新增字段会让它们一次性全部编译失败 —— 而它们与本单的「套 × 部位」粒度无关。
     * 生产装配走 Lombok 的全参构造器（两个依赖都在容器里），不会走到这里。</p>
     */
    public InboundOrderService(InboundOrderMapper inboundOrderMapper,
                               InboundOrderItemMapper inboundOrderItemMapper,
                               InboundOrderQueryMapper inboundOrderQueryMapper,
                               StockBatchMapper stockBatchMapper,
                               ProductSkuMapper productSkuMapper,
                               ProductMapper productMapper,
                               StockLedgerService stockLedgerService,
                               WarehouseLocationService warehouseLocationService,
                               FinishedGoodsStockMapper finishedGoodsStockMapper) {
        this(inboundOrderMapper, inboundOrderItemMapper, inboundOrderQueryMapper, stockBatchMapper,
                productSkuMapper, productMapper, stockLedgerService, warehouseLocationService,
                finishedGoodsStockMapper, null, null);
    }

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
    /** 成品仓库位（V196）：成品单过账时分配仓位号（布料单用不到它）。 */
    private final WarehouseLocationService warehouseLocationService;
    /** 成品在库（V196）：成品单过账的唯一写入方（一行 = 一个订单行 + 一个仓位）。 */
    private final FinishedGoodsStockMapper finishedGoodsStockMapper;
    /** 部位码（V197 / issue #7762）：成品入库按「套 × 部位」逐行，行上带 set_id 时回读 token 行 */
    private final ProcessingSetPartTokenMapper setPartTokenMapper;
    /** 套（V197）：标签「第 N 套」的 set_index 来源 */
    private final ProcessingOrderSetMapper processingOrderSetMapper;

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

    /**
     * 站内信（issue #7524）：入库是本仓**唯一**改库存/成本/台账的时点，
     * 改前它一条通知都不发 —— 过账后除了操作人没人知道库存变了。
     *
     * <p>与 {@link #poolChangeNotifier} 同款：字段注入 + {@code required = false} +
     * 调用侧 fail-soft（{@code null} 或异常 ⇒ 跳过/留痕）——**过账事实不因通知失败而回滚**。</p>
     */
    @Autowired(required = false)
    private NotificationService notificationService;

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
        return create(req, tenantId, operator, null);
    }

    /**
     * 建单（草稿态，**不动库存**）—— 带**服务端强制来源**的重载（issue #6812）。
     *
     * <p>工人拍照入库走这条：{@code forcedSource = photo} ⇒ 明细行「数量」按**卷数**记账
     * （入库米数 = 卷数 × 每卷米数）。为什么强制而不让客户端传：单位口径一旦能被请求体左右，
     * 同一张表就会同时存在两种读法 —— 而这正是本轮要消灭的东西。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public InboundOrderResponse create(InboundOrderCreateRequest req, Long tenantId, String operator,
                                       String forcedSource) {
        Validated validated = validateRequest(req, tenantId, forcedSource);
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

        String supplierText = trimToNull(req.getSupplier());
        InboundOrder order = InboundOrder.builder()
                .tenantId(tenantId)
                .inboundNo(nextFreeInboundNo(tenantId))
                .supplier(supplierText)
                .supplierId(resolveSupplierId(tenantId, req.getSupplierId(), supplierText))
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
                    // 行金额按**入库米数**算（issue #7709）：校验阶段已把 quantity 换算成米数
                    // （按卷录入 = 卷数 × 卷长），这里只做乘法 —— 不在这里第二次换算
                    .amount(amountOf(item.getQuantity(), item.getUnitCost()))
                    .dyeLot(trimToNull(item.getDyeLot()))
                    // 旧系统批次号（V118 / issue #5153）：**外部事实**，原样透传 —— 与 batch_no
                    // （服务端生成的系统号）两列两义，永不互相赋值（V111 明令不得互相冒充）
                    .legacyBatchNo(item.getLegacyBatchNo())
                    .rollLengthM(item.getRollLengthM())
                    .rollCount(item.getRollCount())
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

    /**
     * 成品单过账：逐行分配仓位 + 原子占位写入 {@code finished_goods_stock}。
     *
     * <p>占位走 {@code ON CONFLICT DO NOTHING}（{@code FinishedGoodsStockMapper#claimInStock}）：
     * 唯一冲突不会把事务打成 aborted，抢不到就换下一个空闲仓位（并发打包的互斥点是
     * {@code uk_finished_goods_bin_in_stock}，不是服务层的判空）。</p>
     */
    private void postFinishedLines(InboundOrder order, List<InboundOrderItem> lines, Long tenantId) {
        Long warehouseId = order.getWarehouseId();
        if (warehouseId == null) {
            throw BusinessException.validationError("成品入库单缺少成品仓，无法分配仓位");
        }
        for (InboundOrderItem line : lines) {
            if (!StringUtils.hasText(line.getOrderItemId())) {
                throw BusinessException.validationError("成品入库单的明细行缺少订单行引用，无法分配仓位");
            }
            boolean claimed = false;
            for (int attempt = 0; attempt < FINISHED_BIN_ATTEMPTS && !claimed; attempt++) {
                WarehouseLocation bin = warehouseLocationService.nextFreeBin(tenantId, warehouseId);
                // 套 × 部位（V197）：标签要「第 N 套 / 共 M 套」与短码 ⇒ 从部位码行回读，
                // 不信任调用方传进来的重复字段（单一来源 = processing_set_part_tokens）。
                ProcessingSetPartToken tokenRow = line.getSetId() == null
                        ? null
                        : setPartTokenMapper.selectOne(new LambdaQueryWrapper<ProcessingSetPartToken>()
                        .eq(ProcessingSetPartToken::getTenantId, tenantId)
                        .eq(ProcessingSetPartToken::getSetId, line.getSetId())
                        .eq(ProcessingSetPartToken::getOrderItemId, line.getOrderItemId())
                        .eq(ProcessingSetPartToken::getDeleted, 0)
                        .last("LIMIT 1"));
                Integer setIndex = null;
                if (line.getSetId() != null) {
                    ProcessingOrderSet setRow = processingOrderSetMapper.selectById(line.getSetId());
                    setIndex = setRow == null ? null : setRow.getSetIndex();
                }
                BigDecimal qty = line.getQuantity() == null ? BigDecimal.ONE : line.getQuantity();
                // 遗留（订单行粒度）走 11 参重载：与 V196 的调用形态逐字相同（既有判据按它验参数）
                Long stockId = line.getSetId() == null
                        ? finishedGoodsStockMapper.claimInStock(
                        tenantId, warehouseId, bin.getId(), bin.getBinCode(),
                        line.getOrderId(), line.getOrderNo(), line.getOrderItemId(),
                        line.getProductId(), line.getProductName(), qty, order.getId())
                        : finishedGoodsStockMapper.claimInStock(
                        tenantId, warehouseId, bin.getId(), bin.getBinCode(),
                        line.getOrderId(), line.getOrderNo(), line.getOrderItemId(),
                        line.getProductId(), line.getProductName(), qty, order.getId(),
                        line.getSetId(), line.getSetNo(), setIndex,
                        tokenRow == null ? null : tokenRow.getId(),
                        tokenRow == null ? null : tokenRow.getShortCode());
                if (stockId != null) {
                    InboundOrderItem patch = new InboundOrderItem();
                    patch.setId(line.getId());
                    patch.setLocationId(bin.getId());
                    patch.setBinCode(bin.getBinCode());
                    patch.setUnit(FinishedGoodsStock.UNIT_SET);
                    inboundOrderItemMapper.updateById(patch);
                    claimed = true;
                }
            }
            if (!claimed) {
                throw BusinessException.conflict("成品仓位分配失败（连续 " + FINISHED_BIN_ATTEMPTS + " 次占位冲突）",
                        "请重试；同一个仓位不会被两件成品同时占用");
            }
        }
    }

    // ============================================================ 建单即过账（V196）

    /**
     * **建单即过账**（V196 / issue #7750，用户 2026-10-25 逐字「做成入库即过账，不要单独再点击过账了」）。
     *
     * <p>商家建入库单 = 建单 + 过账**一次请求内**完成：草稿态不再出现在商家流程里
     * （「先存草稿、核对、再点过账」那两步只增加一次「忘了点」的机会，而不会让库存更准）。
     * 工人拍照入库仍走 {@link #create} 的草稿路径 —— 那张草稿是**识别结果**、不是待办
     * （确认后才过账，见 {@code WorkerInboundService}）；过账端点保留给它。</p>
     *
     * <p>事务口径：本方法整体一个事务 ⇒ 建单成功而过账失败时**不会留下**一张孤立草稿
     * （改前「建单 200 + 过账失败」会让列表里多一张永远没人点的草稿）。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public InboundOrderResponse createAndPost(InboundOrderCreateRequest req, Long tenantId, String operator) {
        InboundOrderResponse created = create(req, tenantId, operator);
        return post(created.getId(), tenantId, operator);
    }

    /**
     * **成品打包入库**（V196）：由 {@code FinishedGoodsService#receiveOnPack} 在**打包动作**的事务里调用。
     *
     * <p>单据形态与布料单一致（同表、同号段、同状态机），区别只在过账语义：
     * {@code biz_category=finished} ⇒ 过账时**分配仓位**并写 {@code finished_goods_stock}，
     * 不碰 SKU 米数库存、不建批次、不算移动加权成本。</p>
     *
     * <p>🔴 数量恒为 1（一件成品 = 一个订单行）：订单行的 {@code quantity} 是**计价数量**
     * （per_meter 是米数、per_area 是 ㎡），拿它当件数会把「8.4 ㎡」记成 8 件。
     * 一个订单行对应一件要打包/发走的成品 —— 这也是仓位的载体（见 {@link FinishedGoodsStock}）。</p>
     *
     * @return 已过账的入库单（明细行带分配好的 {@code binCode}）
     */
    @Transactional(rollbackFor = Exception.class)
    public InboundOrderResponse receiveFinishedGoods(Long tenantId, Order order, List<OrderItem> items,
                                                     Long warehouseId, String warehouseText, String operator) {
        if (items == null || items.isEmpty()) {
            throw BusinessException.validationError("订单没有成品行，无法生成成品入库单");
        }
        InboundOrder doc = InboundOrder.builder()
                .tenantId(tenantId)
                .inboundNo(nextFreeInboundNo(tenantId))
                .warehouse(warehouseText)
                .warehouseId(warehouseId)
                .inboundDate(businessClock.today())
                .status(InboundOrder.STATUS_DRAFT)
                .totalAmount(BigDecimal.ZERO)
                .source(InboundOrder.SOURCE_PACKING)
                .bizCategory(InboundOrder.BIZ_FINISHED)
                .remark("成品打包入库（订单 " + order.getOrderNo() + "）")
                .createdBy(operator)
                .build();
        // 变量名刻意不叫 `item`：`OrderRollAllocationAuthorityTest` 按「本文件里有没有
        // `OrderItem <名>` 声明」判定写面归属，同名会让别处的 `item.setRollCount(...)`
        // 被误判成在写 OrderItem 实体（成品入库路径只读订单行、不写整卷两列）。
        List<InboundOrderItem> lines = new ArrayList<>();
        for (OrderItem orderItem : items) {
            lines.add(InboundOrderItem.builder()
                    .tenantId(tenantId)
                    .productId(orderItem.getProductId())
                    .productName(orderItem.getProductName())
                    .orderId(order.getId())
                    .orderNo(order.getOrderNo())
                    .orderItemId(orderItem.getId())
                    .quantity(BigDecimal.ONE)
                    .unit(FinishedGoodsStock.UNIT_SET)
                    .remark("打包")
                    .build());
        }
        return receiveFinishedGoodsLines(tenantId, order, lines, warehouseId, warehouseText, operator);
    }

    /**
     * **成品入库（按调用方给的逐行原型建单 + 过账）**（V197 / issue #7762）。
     *
     * <p>与 {@link #receiveFinishedGoods(Long, Order, List, Long, String, String)} 的差别只在
     * 「行从哪来」：本重载由 {@code FinishedGoodsService} 按**套 × 部位**逐 token 组装
     * （一行 = 一张水洗唛 = 一个仓位），并已在原型上填好 {@code set_id / set_no / short_code}。
     * 单据本身仍是同一张表、同一号段、同一状态机（建单即过账）。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public InboundOrderResponse receiveFinishedGoodsLines(Long tenantId, Order order,
                                                          List<InboundOrderItem> lines,
                                                          Long warehouseId, String warehouseText,
                                                          String operator) {
        if (lines == null || lines.isEmpty()) {
            throw BusinessException.validationError("订单没有成品行，无法生成成品入库单");
        }
        InboundOrder doc = InboundOrder.builder()
                .tenantId(tenantId)
                .inboundNo(nextFreeInboundNo(tenantId))
                .warehouse(warehouseText)
                .warehouseId(warehouseId)
                .inboundDate(businessClock.today())
                .status(InboundOrder.STATUS_DRAFT)
                .totalAmount(BigDecimal.ZERO)
                .source(InboundOrder.SOURCE_PACKING)
                .bizCategory(InboundOrder.BIZ_FINISHED)
                .remark("成品打包入库（订单 " + order.getOrderNo() + "）")
                .createdBy(operator)
                .build();
        inboundOrderMapper.insert(doc);
        for (InboundOrderItem line : lines) {
            line.setTenantId(tenantId);
            line.setInboundOrderId(doc.getId());
            inboundOrderItemMapper.insert(line);
        }
        return post(doc.getId(), tenantId, operator);
    }

    /**
     * <b>测试探针</b>（issue #6928，生产恒为 {@code 0}）：在 {@link #cancel} 的「读-判」之后、
     * 「写」之前暂停指定毫秒。
     *
     * <p><b>为什么需要它</b>：窗口注入是竞态类缺陷的**唯一可信证据**形态
     * （{@code migao-dev-flow} §28.1）—— 判据要在「注入 ⇒ 必红 / 撤回 ⇒ 复绿」两侧各跑一次。
     * 窗口本身只有微秒级，不注入就只能靠碰运气（HTTP 层 20 轮实测只命中 3 轮），判据会退化成 flake。</p>
     *
     * <p><b>为什么放在这里而不是只放测试侧</b>：窗口在服务方法体内，测试侧无法在「已判定仍为草稿、
     * 尚未落库」那一刻插进一段延时（除非用 {@code mock()} 替换真 mapper —— 那会把唯一的 DB 原子
     * 判据换成 mock 的恒真返回，判据当场失去意义）。故留这条窄缝，且只在包内可见
     * （{@code InboundOrderCancelRaceRealDbTest} 与生产同类同包）。</p>
     */
    static void setCancelProbePauseMillisForTest(long millis) {
        CANCEL_PROBE_PAUSE_MILLIS = millis;
    }

    /** 测试探针时长（默认 0 = 不暂停）；见 {@link #setCancelProbePauseMillisForTest}。 */
    private static volatile long CANCEL_PROBE_PAUSE_MILLIS = 0L;

    /** 探针**正在**暂停窗口内的信号（测试用它把两个线程钉在确定的时序上）。 */
    private static volatile boolean cancelProbePaused = false;

    /** 测试观察点：探针是否已进入暂停窗口；生产不读。 */
    static boolean cancelProbePausedForTest() {
        return cancelProbePaused;
    }

    /** 进入窗口 ⇒ 置位 → 停 → 清位（测试在「已置位 / 未清位」之间把 post 走完）。 */
    private static void pauseCancelForProbe(long millis) {
        cancelProbePaused = true;
        try {
            Thread.sleep(millis);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
        cancelProbePaused = false;
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
        // atomic-ledger: true —— 台账的 before/after 取自 receiveStock 的 RETURNING（见 StockChange 类注释）
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
        BigDecimal totalMeters = BigDecimal.ZERO;
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

        // 成品单（V196）：过账 = 分配仓位 + 写成品在库；**不碰** SKU 米数库存/批次/移动加权成本。
        // 分支放在 CAS 之后：两条路径共用同一道「只过一次账」的闸。
        if (InboundOrder.BIZ_FINISHED.equals(order.getBizCategory())) {
            postFinishedLines(order, lines, tenantId);
            log.info("成品入库单已过账: tenant={}, inboundNo={}, items={}, operator={}",
                    tenantId, order.getInboundNo(), lines.size(), operator);
            return detail(order.getId(), tenantId);
        }

        for (InboundOrderItem line : lines) {
            ProductSku sku = productSkuMapper.selectById(line.getSkuId());
            if (sku == null) {
                throw BusinessException.validationError(
                        "明细行引用的 SKU 已不存在（货号 " + line.getSkuCode() + "），请删除该行后重新提交");
            }
            // issue #5063（V115）：库存列与入库行数量同为 NUMERIC(12,1) ⇒ 全程 BigDecimal
            // （改前 `int beforeQty = sku.getStock()` / `int quantity = line.getQuantity()`
            //  在入库量是 60.5 米时根本走不到这里 —— 校验阶段就显式拒绝了；本单把两侧一起放开）
            // 🔴 入库米数 = 库存/批次/台账/成本的**唯一换算源**（issue #7709）：新行建单时已把
            //    卷数 × 卷长 算进 quantity；只有「本改动之前建的拍照草稿」quantity 还是卷数（读面兼容）。
            BigDecimal meters = storedMeters(order.getSource(), line.getQuantity(), line.getRollLengthM(),
                    line.getRollCount());
            totalMeters = totalMeters.add(meters);
            BigDecimal unitCost = line.getUnitCost();

            // ① 批次台账 + **原子取号**（issue #6248）：一个 SKU 行 = 一个批次（V111 裁定）——
            //    整单共用一个号时，第 2 行插 stock_batches 会撞 uk_stock_batches_no
            //    = UNIQUE (tenant_id, batch_no) ⇒ 整个事务回滚（≥2 行的入库单必然过账失败，#5141）。
            //    ⚠️ 取号与占用必须是**一条语句**（`update(` = 候选随行插入 + ON CONFLICT DO NOTHING）：
            //    改前「exists 判假 ⇒ 返回候选 ⇒ **之后**才 insert」的窗口在多实例 / 重启下可被利用
            //    （两实例的进程内计数器从同一位置起步 ⇒ 同一候选 ⇒ 两边 exists 都为假）
            //    ⇒ 后到的 insert 撞唯一索引抛 DuplicateKeyException ⇒ 用户侧 500。
            //    ⇒ 候选必须先落库、后使用：号归不归我由唯一索引在插入那一刻裁（受影响行数 1/0）。
            StockBatch batch = StockBatch.builder()
                    .tenantId(tenantId)
                    .productId(line.getProductId())
                    .skuId(sku.getId())
                    .skuCode(sku.getSkuCode())
                    .inboundOrderId(order.getId())
                    .inboundItemId(line.getId())
                    .inboundNo(order.getInboundNo())
                    .quantity(meters)
                    .unitCost(unitCost)
                    .amount(amountOf(meters, unitCost))
                    .dyeLot(line.getDyeLot())
                    // 旧系统批次号（V118 / issue #5153）：明细行 → 批次行**透传**。建单与过账是两次
                    // 请求 ⇒ 明细行不落这一列，建单时填的旧号在过账那一刻就丢了
                    .legacyBatchNo(line.getLegacyBatchNo())
                    .rollLengthM(line.getRollLengthM())
                    .supplier(order.getSupplier())
                    .warehouse(order.getWarehouse())
                    .receivedDate(order.getInboundDate())
                    .remark(line.getRemark())
                    .build();
            //    取号循环**留在本方法体内**（issue #6248）：这道闸 = 本方法里那次 `update(`
            //    （受影响行数 1 = 号归我、0 = 刚被抢 ⇒ 换候选重来），与 `uk_stock_batches_no`
            //    在同一事务内完成；台账 `after-sales-sideeffect-concurrency-ledger.json` 把它连同
            //    过账 CAS 一起登记为 `InboundOrderService#post` 的并发保护。
            String batchNo = null;
            for (int attempt = 0; attempt < BATCH_NO_ATTEMPTS && batchNo == null; attempt++) {
                String candidate = generateBatchNo();
                batch.setBatchNo(candidate);
                // 测试探针（issue #6248）：把「候选已定 → 交给 DB 裁」之间的窗口拉长（生产恒为 0，
                // 无分支成本），用于证明「读-判-写」窗口可被利用；见 BatchNoTakeRaceRealDbTest。
                if (BATCH_NO_PROBE_PAUSE_MILLIS > 0) {
                    try {
                        Thread.sleep(BATCH_NO_PROBE_PAUSE_MILLIS);
                    } catch (InterruptedException e) {
                        Thread.currentThread().interrupt();
                        throw BusinessException.conflict("批次号取号被中断，请重试",
                                "过账未完成，单据仍是草稿；请重新发起过账");
                    }
                }
                if (stockBatchMapper.update(batch) == 1) {
                    batchNo = candidate;
                } else {
                    log.warn("批次号刚被占用，重新生成: tenant={}, candidate={}", tenantId, candidate);
                }
            }
            if (batchNo == null) {
                throw new BusinessException("BATCH_NO_EXHAUSTED",
                        "批次号连续 " + BATCH_NO_ATTEMPTS + " 次生成失败（当天号段疑似被占满或与库内已用号重叠），"
                                + "请稍后重试或联系管理员", 409);
            }
            batchNos.add(batchNo);

            // ② 加库存 + 写均价/成本金额/最近批次号（一条 SQL 内完成，避免「加了数量没写成本」的中间态）
            //    + **同时取回变更前/后的库存**（issue #6300）：这两个值来自这条 SQL 的 RETURNING，
            //    与改动发生在同一行锁下 ⇒ 两张同 SKU 的草稿单并发过账时，台账两行不会「同基」。
            //    均价仍用本服务算出的 afterAvg（与下面台账里的 avg_cost_after **同源同值**）。
            BigDecimal beforeAvg = sku.getAvgCost();
            StockChange change = StockChange.from(productSkuMapper.receiveStock(sku.getId(), meters,
                    movingAverage(StockQuantity.orZero(sku.getStock()), beforeAvg, meters, unitCost), batchNo,
                    tenantId));
            if (change == null) {
                throw BusinessException.validationError(
                        "SKU 库存行在过账过程中被删除（货号 " + line.getSkuCode() + "），本次过账已中止，请重新过账");
            }
            BigDecimal beforeQty = change.beforeQuantity();
            BigDecimal afterQty = change.afterQuantity();
            // 均价按**权威的**变更前库存重算（与落库那条 SQL 里算 cost_amount 用的是同一个数）：
            // 并发下 sku.getStock() 可能是别人改之前的旧快照，用它算会让台账 avg_cost_after 与
            // SKU 上的 avg_cost 不一致（只在事后对账时看得见的账实不符）。
            BigDecimal afterAvg = movingAverage(beforeQty, beforeAvg, meters, unitCost);

            // ③ 落库存台账（reason=inbound；成本快照一并落，使「库存/成本为什么变了」在同一张账上可对账）
            stockLedgerService.record(tenantId, line.getProductId(), sku.getId(), sku.getSkuCode(),
                    beforeQty, afterQty, StockLedger.REASON_INBOUND, order.getInboundNo(),
                    "入库单过账" + (line.getDyeLot() != null ? "（缸号 " + line.getDyeLot() + "）" : ""),
                    unitCost, beforeAvg, afterAvg);

            // ④ 行上回写批次号（草稿态为 NULL；过账后才有 —— 批次号 = 「真的收货了」）
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

        // 入库过账 → 站内信（issue #7524）：单号可点、供应商/行数/米数/金额/操作人一次说清。
        // 与上面同口径：**既有过账全部完成之后**的 fail-soft 追加，不改任何过账语义。
        Map<String, String> postedVars = new HashMap<>();
        postedVars.put("inboundNo", order.getInboundNo());
        postedVars.put("supplier", order.getSupplier() == null ? "" : order.getSupplier());
        postedVars.put("lineCount", String.valueOf(lines.size()));
        postedVars.put("totalMeters", totalMeters.stripTrailingZeros().toPlainString());
        postedVars.put("amount", order.getTotalAmount() == null ? "0" : order.getTotalAmount().toPlainString());
        postedVars.put("operator", operator == null ? "" : operator);
        notifyInboundEvent(order, "inbound_posted", "info", postedVars);
        return detail(order.getId(), tenantId);
    }

    // ============================================================ 作废

    /**
     * 作废（仅草稿可作废）。
     *
     * <p>已过账的单**不得**作废：库存已进台账，作废等于「悄悄把库存改回去且不留新凭据」。
     * 冲销必须另开单据（留痕）。</p>
     *
     * <p><b>并发闸 = 条件更新（CAS），与 {@link #post} 同款</b>（issue #6928）：状态迁移
     * {@code draft → cancelled} 走 {@link InboundOrderMapper#markCancelled}（{@code WHERE id=? AND
     * tenant_id=? AND status='draft' AND deleted=0}），按**影响行数**判是否抢到作废权。
     * 为什么不能是「先读 status 判 draft，再 {@code updateById} 写」：{@code #post} 与 {@code #cancel}
     * 争同一份迁移权，而 {@code updateById} 的 WHERE 只有主键 ⇒ 两个写面**不互斥** ——
     * 窗口里 {@code #post} 提交了过账（库存 +N、台账 1 行），{@code #cancel} 随后**无条件**把该单
     * 覆写成 {@code cancelled}，留下「已作废的单改了库存、还留着入库台账」的账实不符且无任何 4xx
     * （生产复现读数 3/20）。条件更新的判断与写入是同一条语句，PG 对命中行加行锁并持有到事务结束
     * ⇒ 后到者要么阻塞到前者提交、要么看到 0 行受影响。闸在**任何库存写入之前**（与 {@code #post} 同口径）。</p>
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
        // 测试探针（issue #6928）：放大「读-判」与「写」之间的窗口（生产恒为 0）。与 #post 的
        // 取号探针同款：窗口只有微秒级，不注入就只能靠碰运气（HTTP 层 20 轮只命中 3 轮），判据会退化成 flake。
        if (CANCEL_PROBE_PAUSE_MILLIS > 0) {
            pauseCancelForProbe(CANCEL_PROBE_PAUSE_MILLIS);
        }
        OffsetDateTime now = OffsetDateTime.now();
        // ⓪ 抢作废权：条件更新（CAS），判断与写入同一条语句 + PG 行锁 ⇒ 与 #post 的过账 CAS 互斥
        if (inboundOrderMapper.markCancelled(order.getId(), tenantId, operator, reason, now) == 0) {
            // 抢不到：并发的另一个请求刚过账（也可能刚作废）⇒ 回读真实状态，给准确的文案
            InboundOrder fresh = inboundOrderMapper.selectById(order.getId());
            throw BusinessException.conflict(
                    "入库单当前状态为「" + statusLabel(fresh != null ? fresh.getStatus() : order.getStatus())
                            + "」，只有草稿可以作废",
                    "已过账的入库单库存已进台账，冲销请另开单据（不原地改历史）");
        }
        order.setStatus(InboundOrder.STATUS_CANCELLED);
        order.setCancelledAt(now);
        order.setCancelledBy(operator);
        order.setCancelledReason(reason);
        log.info("入库单已作废: tenant={}, inboundNo={}, operator={}, reason={}",
                tenantId, order.getInboundNo(), operator, reason);

        // 作废 → 站内信（issue #7524）：warn 级 —— 「单据没进库存」这件事必须让负责的人看见
        Map<String, String> cancelledVars = new HashMap<>();
        cancelledVars.put("inboundNo", order.getInboundNo());
        cancelledVars.put("reason", reason == null ? "" : reason);
        cancelledVars.put("operator", operator == null ? "" : operator);
        notifyInboundEvent(order, "inbound_cancelled", "warn", cancelledVars);
        return detail(order.getId(), tenantId);
    }

    /**
     * **撤销打包时冲销成品入库单**（V196）：{@code posted → cancelled}（仅 {@code biz_category=finished}）。
     *
     * <p>与成品在库行的释放**同事务**（调用方 {@code FinishedGoodsService#reverseOnUnpack} 是
     * {@code @Transactional}）：要么「单作废 + 仓位释放」都发生，要么都不发生。
     * 返回 0 行 = 该单已不是 posted（重复撤销 / 并发）—— 调用方按幂等处理，不报错。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public int cancelFinishedPosting(String inboundOrderId, Long tenantId, String operator, String reason) {
        int rows = inboundOrderMapper.markFinishedCancelled(inboundOrderId, tenantId, operator, reason,
                OffsetDateTime.now());
        if (rows > 0) {
            log.info("成品入库单已冲销（撤销打包）: tenant={}, inboundOrderId={}, operator={}, reason={}",
                    tenantId, inboundOrderId, operator, reason);
        }
        return rows;
    }

    // ============================================================ 只读

    /**
     * 列表（关键词匹配 单号/供应商/送货单号；状态与业务类别精确匹配；按入库日期倒序）。
     *
     * <p>{@code bizCategory}（V196 / issue #7794）：{@code fabric} 原料仓入库 / {@code finished}
     * 成品仓入库 —— 页面两个视图的分界；缺省 = 不过滤（向后兼容：既有调用点与站内信深链行为不变）。</p>
     */
    public List<InboundOrderLine> list(String keyword, String status, String bizCategory, Long tenantId) {
        String category = trimToNull(bizCategory);
        // 未知取值**显式拒绝**：静默当「不过滤」会让成品单继续混进原料仓列表（正是本单要修的形态），
        // 静默当「空」又会让列表凭空少一批单 —— 两种都不如报错（可读提示 + 让商家刷新重试）。
        if (category != null
                && !InboundOrder.BIZ_FABRIC.equals(category)
                && !InboundOrder.BIZ_FINISHED.equals(category)) {
            throw BusinessException.validationError("入库单类别只支持 fabric / finished；请刷新页面后重试");
        }
        return inboundOrderQueryMapper.selectOrderLines(tenantId, trimToNull(keyword), trimToNull(status),
                category, LIST_LIMIT);
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
            // 入库米数（issue #7709）：入库单明细、批次余量、库存流水必须说同一个米数 ⇒ 由服务端算好下发，
            // 前端不自己聚合/换算（历史拍照行也按这里还原成米数）
            item.setMeters(storedMeters(order.getSource(), line.getQuantity(), line.getRollLengthM(),
                    line.getRollCount()));
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
    private Validated validateRequest(InboundOrderCreateRequest req, Long tenantId, String forcedSource) {
        if (req == null || req.getItems() == null || req.getItems().isEmpty()) {
            throw BusinessException.validationError("入库单至少要有 1 行明细");
        }
        // 来源口径：**只有**服务端强制值（工人拍照链）能给出 photo；请求体里的 source 仍只认
        // purchase / opening（客户端无法自称「拍照单」⇒ 「数量 = 卷数」这条单位口径不可被伪造）
        String source = forcedSource != null ? forcedSource : normalizeSource(req.getSource());
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
            // 🔴 入库米数 = **卷数 × 卷长**（issue #7709）—— 全仓唯一换算点 = metersOfRolls。
            //    卷数从哪来：photo 单（issue #6812）的「数量」格本来就是卷数；其余来源由前端「卷数」
            //    列显式给出（rollCount）。**有卷数时客户端的 quantity 一律不采信**：改前的换算发生在
            //    客户端（#7646 的前端自乘），客户端不乘就把「1 卷 × 70 米」记成 1 米
            //    （RK-20261024-0001 实测：批次/台账/库存全链 1 米，下单报「仅剩 1.0 米」）。
            boolean byRolls = InboundOrder.SOURCE_PHOTO.equals(source) || item.getRollCount() != null;
            if (byRolls) {
                BigDecimal rollCount = requireRollCount(
                        InboundOrder.SOURCE_PHOTO.equals(source)
                                ? item.getQuantity()
                                : new BigDecimal(item.getRollCount()),
                        "商品明细第 " + idx + " 项的卷数");
                BigDecimal rollLengthM = requireRollLength(item.getRollLengthM(),
                        "商品明细第 " + idx + " 项的卷长");
                item.setRollCount(rollCount.intValueExact());
                item.setRollLengthM(rollLengthM);
                item.setQuantity(metersOfRolls(rollCount, rollLengthM));
                // 单价的「> 0」与按米录入同口径（requireItemNumbers 那一条不能因为换了录入方式而失守）
                requireUnitCostPositive(item.getUnitCost(), "商品明细第 " + idx + " 项的入库单价");
            } else {
                // 数量/单价判据**只有一处**（requireItemNumbers）：建单与批量建账导入共用同一条口径
                item.setQuantity(requireItemNumbers(item.getQuantity(), item.getUnitCost(),
                        "商品明细第 " + idx + " 项的数量", "商品明细第 " + idx + " 项的入库单价"));
            }
            // 单价小数位准入（issue #6228）：`inbound_order_items.unit_cost` / `stock_batches.unit_cost`
            // 是 NUMERIC(·,2)，超 2 位有效小数会被 PG 静默四舍五入（占成本、算均价都按被改掉的值）。
            // 判在**本入口**（校验阶段，早于任何写）；`null` = 不记单价 ⇒ 原样透传（不归一成 0）。
            item.setUnitCost(MoneyScale.requireTwoDecimalsOrNull(item.getUnitCost(),
                    "商品明细第 " + idx + " 项的入库单价"));
            // 金额精度准入（issue #6228）：行金额是**计算值**（"积"）—— 单价 2 位小数 × 数量 1 位小数
            // 可出 3 位小数（`1.5 × 0.01 = 0.015`），而列是 NUMERIC(·,2) ⇒ 逐行显式拒绝。
            // 判在本方法（= 校验阶段，`create()` 的第一条语句）⇒ 拒绝对**任何写**之前。
            MoneyScale.requireTwoDecimalsOrNull(amountOf(item.getQuantity(), item.getUnitCost()),
                    "商品明细第 " + idx + " 项的入库金额（" + (byRolls ? "卷数 × 卷长 × 单价" : "数量 × 单价") + "）");
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
     * 单行**数值准入** —— 全仓**唯一一处**（下限、粒度、单价 &gt; 0 三条口径都在这里）。
     *
     * <p>单价的**小数位**准入（issue #6228）不在本方法内，而在两个调用方的**入口**：
     * 建单见 {@code validateRequest}、期初导入见 {@code OpeningRegisterImportService.parseRow}
     * —— 两处都在「任何写之前」判，且各自把拒绝落到本入口的错误载体上
     * （建单 = 422；导入 = 该行标红，不中断整份报告）。</p>
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
        requireUnitCostPositive(unitCost, unitCostLabel);
        return normalized;
    }

    /**
     * 明细行的**入库米数** —— 库存 / 批次 / 台账 / 成本的**唯一换算源**（issue #7709）。
     *
     * <p>卷数 × 卷长。米数按 <b>0.1 米粒度</b> fail-closed（{@link StockQuantity#requireOneDecimal}）：
     * 「3 卷 × 0.33 米」这种乘出来不是 0.1 整数倍的组合**显式拒绝**，不静默取整。</p>
     */
    static BigDecimal metersOfRolls(BigDecimal rollCount, BigDecimal rollLengthM) {
        return StockQuantity.requireOneDecimal(
                StockQuantity.orZero(rollCount).multiply(StockQuantity.orZero(rollLengthM)), "入库米数");
    }

    /**
     * 明细行**已落库的入库米数** —— 读面（单据详情 / 卷标打印）与本处的写面共用一条口径。
     *
     * <p>有 {@code roll_count} ⇒ 明细行的 {@code quantity} 已经是服务端算好的米数，原样返回；
     * 没有卷数且 {@code source=photo} ⇒ 那是**本改动之前**的拍照行（当时 {@code quantity} 存的是卷数，
     * 用户 2026-10-25 裁定「历史不动」⇒ 不回填、读面兼容），乘卷长还原米数；
     * 其余（采购 / 期初，含历史行）⇒ {@code quantity} 本身就是米数（#5034）。</p>
     */
    static BigDecimal storedMeters(String source, BigDecimal quantity, BigDecimal rollLengthM, Integer rollCount) {
        BigDecimal meters = StockQuantity.orZero(quantity);
        if (rollCount == null && InboundOrder.SOURCE_PHOTO.equals(source)
                && rollLengthM != null && rollLengthM.signum() > 0) {
            meters = meters.multiply(rollLengthM);
        }
        return StockQuantity.requireOneDecimal(meters, "入库米数");
    }

    /** 单价准入：可空（未记单价），给了必须 {@code > 0}（不记单价请留空，不写 0）。 */
    private static void requireUnitCostPositive(BigDecimal unitCost, String label) {
        if (unitCost != null && unitCost.signum() <= 0) {
            throw BusinessException.validationError(label + "必须大于 0（不记单价请留空）");
        }
    }

    /** 卷数准入：**正整数** —— 半卷不成卷；散米 / 尾料按米录入（不填卷数，数量填米数）。 */
    private static BigDecimal requireRollCount(BigDecimal rollCount, String label) {
        BigDecimal count = StockQuantity.orZero(rollCount);
        if (count.signum() <= 0 || count.stripTrailingZeros().scale() > 0) {
            throw BusinessException.validationError(
                    label + "必须是正整数（收到 " + count.toPlainString() + "）：按卷入库按「卷数 × 每卷米数」记账；"
                            + "散米 / 尾料请按米录入（卷数留空，数量填米数）");
        }
        return count;
    }

    /** 卷长准入：&gt; 0 且最多 2 位小数（列 = {@code roll_length_m NUMERIC(8,2)}）。 */
    private static BigDecimal requireRollLength(BigDecimal rollLengthM, String label) {
        if (rollLengthM == null) {
            throw BusinessException.validationError(
                    label + "不能为空：按卷入库按「卷数 × 每卷米数」记账（填了卷数就要填每卷多少米）");
        }
        BigDecimal len = rollLengthM.stripTrailingZeros();
        if (len.signum() <= 0 || len.scale() > 2) {
            throw BusinessException.validationError(
                    label + "必须大于 0 且最多 2 位小数（每卷米数，收到 " + rollLengthM.toPlainString() + "）");
        }
        return len;
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

    /**
     * 解析供应商档案引用（issue #7369 段 2，用户 2026-10-20 裁定 **A 口径**）。
     *
     * <h3>三条分支（逐条有判据）</h3>
     * <ol>
     *   <li><b>显式给了 {@code supplierId}</b> ⇒ 必须是本租户、未软删、**在用**的档案：
     *       跨租户/不存在 ⇒ 422「供应商档案不存在」；停用 ⇒ 422「已停用，不能收货」。
     *       <b>不猜、不兜底</b>：档案状态是商家自己的决定，系统不替它放宽。</li>
     *   <li><b>没给、但文本能精确匹配到唯一一家</b> ⇒ 自动补上（省掉一次手工选择；
     *       这也是历史行回填用的同一把尺子）。</li>
     *   <li><b>都没成</b>（无文本 / 匹配不上 / 同名多家 = 歧义）⇒ **留 NULL**，进「待指派」清单。
     *       绝不按模糊匹配猜一家 —— 猜错等于把两家的账并成一家，不可逆。</li>
     * </ol>
     */
    // 包私有（非 private）仅为可直接判据：它只碰 inboundOrderMapper，不需要起整个建单流程。
    String resolveSupplierId(Long tenantId, String requestedId, String supplierText) {
        String explicitId = trimToNull(requestedId);
        if (explicitId != null) {
            String status = inboundOrderMapper.selectSupplierStatusInTenant(tenantId, explicitId);
            if (status == null) {
                throw BusinessException.validationError("供应商档案不存在或不属于当前租户：" + explicitId);
            }
            if (SupplierService.STATUS_INACTIVE.equals(status)) {
                throw BusinessException.validationError(
                        "供应商已停用，不能用于新建入库单：若要继续收货，请先在「供应商」页启用它");
            }
            return explicitId;
        }
        if (supplierText == null) {
            return null;
        }
        List<String> matched = inboundOrderMapper.selectSupplierIdsByExactName(tenantId, supplierText);
        // 唯一匹配才自动补；0 家 = 未建档、多家 = 同名歧义 ⇒ 都留 NULL（人工出口 = 待指派清单）
        return matched.size() == 1 ? matched.get(0) : null;
    }

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
     * 单据来源归一（**请求体这一侧**）：缺失 ⇒ {@code purchase}；取值只许 {@code purchase} / {@code opening}
     * （与 {@code ck_inbound_orders_source} 同口径，应用层先拒是为了给出可行动文案，
     * 而不是把 DB 的 23514 透传成 500）。
     *
     * <p>{@code photo}（issue #6812，V153）**不经过本方法** —— 它只能由服务端强制给出
     * （{@code create(req, tenant, operator, forcedSource)} 的 4 参重载，调用方 =
     * {@code WorkerInboundService#createDraft}）。请求体里写 {@code source=photo} 一律按
     * 「不支持的来源」拒绝 ⇒ 客户端无法把一张单自称成「数量 = 卷数」的口径。</p>
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
     * 批次号取号的**重试上限**（issue #6248）：候选号在写入那一刻被别的事务抢走（受影响行数 0）
     * ⇒ 换候选重来；连续 {@value} 次全被抢 ⇒ 显式抛 {@code BATCH_NO_EXHAUSTED}(409)，
     * <b>不静默用一个可能重复的号</b>。
     *
     * <p>为什么是 20（同族口径，见 {@code InboundOrderService#nextFreeInboundNo}）：远超
     * 「同一天重启 20 次且每次都恰好撞上」的实际情况。<b>已知代价</b>（如实登记）：当天已用号 ≥ 20 时
     * 重启后的第一批过账会被显式拒绝（回 409、零副作用），而不是静默重号 —— 判据见
     * {@code BatchNoTakeRaceRealDbTest} 判据 ③。</p>
     */
    private static final int BATCH_NO_ATTEMPTS = 20;

    /**
     * <b>测试探针</b>（issue #6248，生产恒为 {@code 0}）：在「候选已定 → 交给 DB 判占用」之间暂停
     * 指定毫秒。
     *
     * <p><b>为什么需要它</b>：窗口注入是竞态类缺陷的<b>唯一可信证据</b>形态
     * （{@code migao-dev-flow} §28.1：跑绿不是证据、必须注入放大 + 双向对照）——判据要在
     * 「注入 ⇒ 必红 / 撤回 ⇒ 复绿」两侧各跑一次。窗口本身只有微秒级，不注入就只能靠碰运气，
     * 判据会退化成 flake。</p>
     *
     * <p><b>为什么放在这里而不是只放测试侧</b>：窗口在 {@link #post} 的取号循环里，测试侧
     * 无法在「候选已定、尚未落库」那一刻插进一段延时（除非用 {@code mock()} 替换真 mapper ——
     * 那会把唯一的 DB 原子判据换成 mock 的恒真返回，判据当场失去意义）。故留这条窄缝，
     * 且只在包内可见（{@code BatchNoTakeRaceRealDbTest} 与生产同类同包）。</p>
     */
    static void setBatchNoProbePauseMillisForTest(long millis) {
        BATCH_NO_PROBE_PAUSE_MILLIS = millis;
    }

    /** 测试探针时长（默认 0 = 不暂停）；见 {@link #setBatchNoProbePauseMillisForTest}。 */
    private static volatile long BATCH_NO_PROBE_PAUSE_MILLIS = 0L;

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
        // 纯计算（**唯一积计算点**）：建单 / 过账 / 期初建账三条路径都只经这里。
        // 🔴 精度准入**不在这里**，而在校验阶段 `validateRequest`（那是任何写之前的位置）——
        // 放这里会让"拒绝"发生在草稿单 insert 之后（@Transactional 虽会回滚，但判据面上
        // 「超精度 ⇒ 零写入」就不成立了，见 issue #6228 的实例判据）。
        return unitCost == null ? null : unitCost.multiply(StockQuantity.orZero(quantity));
    }

    /**
     * 入库事件站内信（issue #7524）。
     *
     * <p><b>fail-soft 的边界写清</b>：通知是「事实之后的追加」，不是事实的一部分 ——
     * 未注入（既有单测 / 切片上下文）或发送异常都只留痕，**绝不**把已经提交的库存/台账回滚，
     * 也不改调用方的返回值（异常在 catch 内消化，方法签名不带 {@code throws}）。</p>
     *
     * <p>幂等由 {@link NotificationEvent#getBizId()} 参与的去重键保证（服务层先查 + 唯一索引兜底）
     * —— 过账/作废都是 CAS 幂等闸，重放不会产生第二条站内信。</p>
     */
    private void notifyInboundEvent(InboundOrder order, String eventType, String severity,
                                    Map<String, String> vars) {
        if (notificationService == null) {
            return;
        }
        try {
            NotificationEvent event = NotificationEvent.builder()
                    .bizType("inbound_order")
                    .bizId(order.getId())
                    .bizNo(order.getInboundNo())
                    // 落地页 = 入库单列表 + 单号搜索（列表页读 keyword 查询参数，issue #7524）
                    .targetPath("/inbound-orders?keyword=" + order.getInboundNo())
                    .severity(severity)
                    .occurredAt(OffsetDateTime.now())
                    .build();
            notificationService.triggerForTenantAdmins(order.getTenantId(), eventType, vars, event);
        } catch (Exception e) {
            log.warn("入库通知发送失败（已忽略，不影响单据事实）: tenant={}, inboundNo={}, eventType={}, error={}",
                    order.getTenantId(), order.getInboundNo(), eventType, e.getMessage());
        }
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
