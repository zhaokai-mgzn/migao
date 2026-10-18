package com.migao.admin.service;

import com.migao.admin.entity.OrderLogistics;
import com.migao.admin.mapper.OrderLogisticsMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.util.StringUtils;

import java.time.OffsetDateTime;
import java.util.function.Supplier;

/**
 * 订单物流写入（issue #3768 的判定本体，issue #5648 抽成**单一实现点**）。
 *
 * <p><b>为什么抽出来</b>：本单新增了第三条发货路（{@code OrderShipmentService}，工人可达面）。
 * 若在那边再写一份「存在则更新、否则新建」的物流写入，就是**两份物流口径** ——
 * 而这份口径里有两条踩过坑的规则（发货人只在新建时解析、更新时仅在显式传入才覆盖），
 * 复制它等于把坑复制一份。</p>
 *
 * <p>⇒ 本体搬到这里，{@link OrderService#upsertLogistics} 改为一行委托（调用点一字未动）。</p>
 */
@Slf4j
public final class OrderLogisticsWriter {

    private OrderLogisticsWriter() {
    }

    /**
     * 更新/创建订单物流信息：存在最新物流记录则更新，否则新建（{@code status=in_transit}）。
     *
     * <p>发货人（issue #3768）语义：新建时取
     * {@code hasText(shipperName) ? shipperName.trim() : currentUserDisplayName.get()}；
     * 更新时**仅**在显式传入非空时覆盖 —— 后续改运单号/纠错不等于换发货人，
     * 也不能因为「别人来改单号」就把经手人改成那个人，更不能为存量历史数据猜一个经手人。</p>
     *
     * <p><b>首次发货时刻（issue #6276）</b>：{@code shipped_at} = <b>首次发货时刻</b>
     * （用户 2026-10-10 裁定；「最近一次改物流时刻」那条口径已被否掉）⇒ 新建时写
     * {@code now()}；**更新时只在它为 null 时补**（取值 = 该行的 {@code created_at}），
     * 已有值逐字不动 —— 见
     * {@link OrderLogisticsMapper#backfillShippedAtIfAbsent}。</p>
     *
     * <p><b>发货方式 / 物流类型 / 发货人（issue #6983）</b>：这三列走 {@link ShippingDetails} 一次传入
     * —— 商家发货页的三个字段此前在**原子发货端点**上没有落点（端点 body 只读
     * {@code trackingNo} / {@code logisticsCompany}），于是「无需物流」与「发货人」会被静默丢掉。
     * 三条同一条规则：<b>新建时写入、更新时仅在显式传入非空时覆盖</b>。</p>
     *
     * @param currentUserDisplayName 新建且未显式给发货人时的兜底来源（延迟求值：更新路径**不调用**它，
     *                               否则「改一次运单号」就会把经手人换成当次操作人）
     */
    public static void upsert(OrderLogisticsMapper orderLogisticsMapper,
                              Long tenantId,
                              String orderId,
                              String logisticsCompany,
                              String trackingNo,
                              ShippingDetails details,
                              Supplier<String> currentUserDisplayName) {
        String shipperName = details == null ? null : details.shipperName();
        String logisticsType = details == null ? null : details.logisticsType();
        String shippingMethod = details == null ? null : details.shippingMethod();
        // 「显式才覆盖」：空串与 null 同义（本次请求没说这件事）⇒ 交给 SQL 的 NULLIF + COALESCE 保留原值
        String explicitShipper = StringUtils.hasText(shipperName) ? shipperName.trim() : null;
        String explicitType = StringUtils.hasText(logisticsType) ? logisticsType.trim() : null;
        String explicitMethod = StringUtils.hasText(shippingMethod) ? shippingMethod.trim() : null;

        // 🔴 先条件更新，影响行数就是「这一行当时是否存在」的**原子读数**（issue #7174）。
        // 原实现是「先 select 再看空不空，空则 insert」的读改写 —— 并发两次发货会双双读到空 ⇒ 双行。
        int updated = orderLogisticsMapper.updateShippingDetails(tenantId, orderId, logisticsCompany,
                trackingNo, explicitShipper, explicitType, explicitMethod);
        if (updated > 0) {
            log.info("更新物流信息成功: orderId={}, trackingNo={}, rows={}", orderId, trackingNo, updated);
            return;
        }

        OrderLogistics logistics = OrderLogistics.builder()
                .tenantId(tenantId)
                .orderId(orderId)
                .logisticsCompany(logisticsCompany)
                .trackingNo(trackingNo)
                .shipperName(StringUtils.hasText(explicitShipper)
                        ? explicitShipper
                        : currentUserDisplayName.get())
                .logisticsType(explicitType)
                .shippingMethod(explicitMethod)
                .status("in_transit")
                .shippedAt(OffsetDateTime.now())
                .build();
        try {
            orderLogisticsMapper.insert(logistics);
            log.info("创建物流信息成功: orderId={}, trackingNo={}, shipper={}",
                    orderId, trackingNo, logistics.getShipperName());
        } catch (RuntimeException race) {
            // 并发对手先建行成功（唯一索引 (tenant_id, order_id) WHERE deleted = 0 兜底）⇒
            // 本请求**退化为更新那一行**：同一订单最终恰好 1 行，调用方不感知冲突、也不报错。
            // ⚠️ 只吞「唯一约束冲突」这一种：别的写库异常必须原样抛出（否则真实故障会被静默吞掉）。
            // 为什么要自己判而不是只 catch DuplicateKeyException：异常类型取决于装配形态 ——
            // Spring 的 SqlSessionTemplate 会把它翻译成 DuplicateKeyException，而**直连 MyBatis**
            // （如真库判据的装配、或将来换装配方式）抛的是 PersistenceException 包着 PSQLException ⇒
            // 只看类型会在那种装配下漏接，退化成「404/500」而不是收敛。判 SQLState 是驱动无关的。
            if (!isUniqueViolation(race)) {
                throw race;
            }
            orderLogisticsMapper.updateShippingDetails(tenantId, orderId, logisticsCompany,
                    trackingNo, explicitShipper, explicitType, explicitMethod);
            log.info("创建物流信息撞并发（对手先建行）⇒ 已收敛为更新: orderId={}, trackingNo={}",
                    orderId, trackingNo);
        }
    }

    /** 唯一约束冲突判定（驱动无关）：Spring 的 DuplicateKeyException / 原生 SQLState 23505。 */
    private static boolean isUniqueViolation(Throwable error) {
        for (Throwable current = error; current != null; current = current.getCause()) {
            if (current instanceof DuplicateKeyException) {
                return true;
            }
            if (current instanceof java.sql.SQLException sql
                    && "23505".equals(sql.getSQLState())) {   // 23505 = unique_violation
                return true;
            }
            if (current.getCause() == current) {
                break;
            }
        }
        return false;
    }

    /**
     * 一次发货请求里**除运单号/承运商之外**的那些字段（issue #6983）。
     *
     * <p>为什么打包成一个参数：这三列同属「发货页采集、数据库有列、但原子端点此前没有落点」的
     * 同一族缺口；逐个加成三个形参会把 {@code upsert} 的签名推成 9 参，且漏传其中一个在编译期
     * **看不出来**（都会被读成 {@code null} = 「没采集」）—— 一个具名 record 让「传了哪几件事」
     * 在调用点可见。</p>
     *
     * <p>三个字段都允许为 {@code null} / 空串 = <b>本次请求没说这件事</b> ⇒ 不覆盖既有值
     * （与发货人同一条「显式才覆盖」口径）。取值白名单
     * （{@code shippingMethod ∈ {logistics, none}}）由端点 owner
     * {@code ProductionController.ship} 在**任何写之前** fail-closed 校验，本类不重复判。</p>
     *
     * @param shipperName    发货人（发货单纸面「经手人」，issue #3768）；空 ⇒ 新建时取当前登录人
     * @param logisticsType  物流类型：{@code express} 快递 / {@code logistics} 物流专线（issue #4419）
     * @param shippingMethod 发货方式：{@code logistics} 物流发货 / {@code none} 无需物流（issue #6239）
     */
    public record ShippingDetails(String shipperName, String logisticsType, String shippingMethod) {
    }
}
