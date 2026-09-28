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
     * @param currentUserDisplayName 新建且未显式给发货人时的兜底来源（延迟求值：更新路径**不调用**它，
     *                               否则「改一次运单号」就会把经手人换成当次操作人）
     */
    public static void upsert(OrderLogisticsMapper orderLogisticsMapper,
                              Long tenantId,
                              String orderId,
                              String logisticsCompany,
                              String trackingNo,
                              String shipperName,
                              Supplier<String> currentUserDisplayName) {
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
            if (latest.getStatus() == null) {
                latest.setStatus("in_transit");
            }
            orderLogisticsMapper.updateById(latest);
            log.info("更新物流信息成功: id={}, trackingNo={}", latest.getId(), trackingNo);
        }
    }
}
