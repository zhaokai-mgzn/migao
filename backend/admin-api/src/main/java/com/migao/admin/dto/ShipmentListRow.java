package com.migao.admin.dto;

import lombok.Data;

import java.time.OffsetDateTime;
import java.util.Map;

/**
 * 发货单**列表**行（issue #5939）—— 大菜单「仓储与物料 ▸ 发货单」的第一屏读面。
 *
 * <p><b>它答什么</b>：「这个租户发过哪些货、谁经手、发了多少」—— 此前只能先知道是哪张订单、
 * 再进订单详情才看得到（{@code GET /api/admin/orders/{id}/shipments} 是**按单**读面）。
 * 发货单是**流水型单据**（像入库单一样要能按单号/订单号/客户检索），所以列表是它的正经入口。</p>
 *
 * <p>字段名与 {@code OrderShipmentQueryMapper.selectListRows} 的 SELECT 别名一一对应
 * （MyBatis 按列别名映射到属性名；别名写错 ⇒ 字段**静默为 null**，判据见
 * {@code OrderShipmentQueryMapperTest.aliasesMatchDtoProperties}）。</p>
 */
@Data
public class ShipmentListRow {

    private String id;

    /** 发货单号（人可读，纸面/对账用；{@code FH-yyyyMMddHHmmss-XXXX} 形态由写面生成）。 */
    private String shipmentNo;

    private String orderId;

    /** 订单号（下单时那串；与 {@code shipmentNo} 是两个号，页面两列都给）。 */
    private String orderNo;

    /** 客户名（取自 {@code orders.customer_name} —— 连接条件带租户维，不跨租户取数）。 */
    private String customerName;

    /** 来源：{@code worker_photo}（工人拍照）/ {@code worker}（工人手工）/ {@code admin}（商家侧）。 */
    private String source;

    /** 打包时间；未打包 ⇒ null（**不填当前时间**：那是编造事实）。 */
    private OffsetDateTime packedAt;

    /** 发货时间；还没发货 ⇒ null（列表按 {@code shipped_at → packed_at → created_at} 回退排序）。 */
    private OffsetDateTime shippedAt;

    /** 发货人（纸面「经手人」同一真值）；存量/未采集 ⇒ null，页面显示「-」。 */
    private String shippedByWorkerName;

    private String trackingNo;

    private String logisticsCompany;

    /** 实发明细**行数**（聚合；软删行不计 —— 与「实发数量」同处 {@code deleted = 0} 之下）。 */
    private Integer itemCount;

    /**
     * 实发汇总 —— 与按单读面 {@code readShipment} 的 {@code shipped_totals} **同一份口径**
     * （{@code OrderShipmentService.totals()}）：{@code set_count} / {@code roll_count} / {@code by_unit}。
     *
     * <p>🔴 **不在这里另算一套**：实发数量的唯一 owner 是 {@code order_shipment_items} +
     * 那份汇总实现；列表只是它的第二个消费面（判据：
     * {@code AdminShipmentListReadTest.shippedTotalsComeFromTheSameProjection}）。</p>
     */
    private Map<String, Object> shippedTotals;
}
