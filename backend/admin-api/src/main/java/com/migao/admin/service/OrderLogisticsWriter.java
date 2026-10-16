package com.migao.admin.service;

import com.migao.admin.entity.OrderLogistics;
import com.migao.admin.mapper.OrderLogisticsMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.util.StringUtils;

import java.time.OffsetDateTime;
import java.util.List;
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
        List<OrderLogistics> existing = orderLogisticsMapper.selectByOrderId(orderId, tenantId);
        if (existing == null || existing.isEmpty()) {
            OrderLogistics logistics = OrderLogistics.builder()
                    .tenantId(tenantId)
                    .orderId(orderId)
                    .logisticsCompany(logisticsCompany)
                    .trackingNo(trackingNo)
                    .shipperName(StringUtils.hasText(shipperName)
                            ? shipperName.trim()
                            : currentUserDisplayName.get())
                    .logisticsType(details == null ? null : details.logisticsType())
                    .shippingMethod(details == null ? null : details.shippingMethod())
                    .status("in_transit")
                    .shippedAt(OffsetDateTime.now())
                    .build();
            orderLogisticsMapper.insert(logistics);
            log.info("创建物流信息成功: orderId={}, trackingNo={}, shipper={}",
                    orderId, trackingNo, logistics.getShipperName());
        } else {
            OrderLogistics latest = existing.get(0);
            latest.setLogisticsCompany(logisticsCompany);
            latest.setTrackingNo(trackingNo);
            // 仅显式传入才覆盖：兜底值属于「新建时的经手人」，不能用它改写已记录的发货人
            // （否则改一次运单号/agent 补一次单号就会把经手人换成当次操作人）
            if (StringUtils.hasText(shipperName)) {
                latest.setShipperName(shipperName.trim());
            }
            // 同一条「显式才覆盖」口径（issue #6983）：物流类型（express/logistics）与发货方式
            // （logistics/none）**只在显式传入非空时**覆盖 —— 缺席 = 本次请求没说这件事
            // ⇒ 保留原值（既不静默清空，也不替调用方猜一个）。
            if (details != null && StringUtils.hasText(details.logisticsType())) {
                latest.setLogisticsType(details.logisticsType().trim());
            }
            if (details != null && StringUtils.hasText(details.shippingMethod())) {
                latest.setShippingMethod(details.shippingMethod().trim());
            }
            if (latest.getStatus() == null) {
                latest.setStatus("in_transit");
            }
            // 🔴 首次发货时刻（issue #6276，用户裁定 2026-10-10）：本行**没有**首次发货时刻时补上，
            // 取值 = 该行自己的 created_at（= 建行那一刻 = 首次发货时刻，依据见 mapper 的注释）。
            // **已有值一律不覆盖**（改一次运单号 ≠ 改发货时刻），且补出来的值恒等于建行时刻。
            // ⚠️ 必须在 updateById **之前**：否则实体里读到的旧值会把刚补的盖回去。
            orderLogisticsMapper.backfillShippedAtIfAbsent(orderId, tenantId);
            orderLogisticsMapper.updateById(latest);
            log.info("更新物流信息成功: id={}, trackingNo={}", latest.getId(), trackingNo);
        }
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
