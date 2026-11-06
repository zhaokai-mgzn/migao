package com.migao.admin.service;

import com.migao.admin.entity.Order;

import java.util.List;
import java.util.Map;

import static com.migao.admin.service.ProcessingOrderService.ORDER_KIND_OUTBOUND;
import static com.migao.admin.service.ProcessingOrderService.ORDER_KIND_PROCESSING;
import static com.migao.admin.service.ProcessingOrderService.SNAPSHOT_ORDER_REQUIRED_DELIVERY_DATE;
import static com.migao.admin.service.ProcessingOrderService.SNAPSHOT_ORDER_URGENT;
import static com.migao.admin.service.ProcessingOrderService.isFabricSaleLine;

/**
 * 加工单**订单级事实盖章**单元（issue #8770「生成族」一档，从 {@link ProcessingOrderService} **纯搬运**）。
 *
 * <p><b>单一职责</b>：把**订单级**（header，非行级）事实固化进加工单快照的每一行 ——
 * ① {@link #deriveOrderKind}：单据类型判定（快照每一行 {@code saleForm=布料} ⇒ 出库作业单，
 * 否则加工单）；② {@link #stampOrderUrgency}：订单级加急 / 客户要求到货日。
 * 二者都在 {@code prepare()} 里、**加工单 insert 之前**盖章 —— 快照是加工单的**固化真相**，
 * 事后补不回来（与 {@link ProcessingOrderCuttingStamp} 那条时机纪律同源）。</p>
 *
 * <p><b>为什么与排料结果分成两个单元</b>：两组盖章的**输入事实不同**（订单级 vs 排料结果），
 * 调用时机也不同（{@code prepare} 前段 / {@code commit} 后段）⇒ 分开后各自只有一组依赖，
 * 读改一处不必同时防另一组的语义。本单元**零状态、零 DB**（纯函数）。</p>
 *
 * <p><b>搬运口径</b>：方法体、注释、异常语义**一字未改**。改动只有三类，逐条可复算：
 * ① {@code deriveOrderKind} 的可见性由 {@code private} 放宽到**同包可见**（门面留 3 行同名委托，
 * 因此全部既有调用点、DTO / 迁移注释里的 {@code ProcessingOrderService.deriveOrderKind} 引用
 * **一字未改**）；② 两个快照键常量 {@code SNAPSHOT_ORDER_URGENT} /
 * {@code SNAPSHOT_ORDER_REQUIRED_DELIVERY_DATE} 按「公共常量留在门面」的口径**不搬**，
 * 只由 {@code private} 放宽到**同包可见**（否则本单元读不到），引用经
 * {@code import static} 落地 ⇒ 方法体里那两行**逐字未改**；
 * ③ 本单元无日志语句 ⇒ 日志器无需搬迁（与前面几档不同，这里没有 {@code @Slf4j} 可搬）。</p>
 *
 * <p><b>为什么没有 {@code Owner} 窄接口</b>：本组只调门面的 {@code public static}
 * （{@code isFabricSaleLine}）与两个常量，**没有一处回调门面的实例状态** ⇒ 加一层回调门面只会
 * 变成一个零实现的空壳（同族单元里 {@code ProcessingOrderReadFace.Owner} 是因为单号解析 / 域名
 * 是门面的实例事实才必需）。调用面由门面 1~3 行委托保持**一字未改**。</p>
 */
final class ProcessingOrderHeaderStamp {

    private ProcessingOrderHeaderStamp() {
    }

    /** 搬运自门面；**行为契约的权威注释仍在** {@code ProcessingOrderService#stampOrderUrgency}。 */
    static void stampOrderUrgency(List<Map<String, Object>> snapshot, Order order) {
        if (snapshot.isEmpty() || order == null) {
            return;
        }
        boolean urgent = Boolean.TRUE.equals(order.getIsUrgent());
        String date = order.getRequiredDeliveryDate() == null
                ? null : order.getRequiredDeliveryDate().toString();
        for (Map<String, Object> row : snapshot) {
            row.put(SNAPSHOT_ORDER_URGENT, urgent);
            if (date != null) {
                row.put(SNAPSHOT_ORDER_REQUIRED_DELIVERY_DATE, date);
            }
        }
    }

    /** 搬运自门面；**行为契约的权威注释仍在** {@code ProcessingOrderService#deriveOrderKind}。 */
    static String deriveOrderKind(List<Map<String, Object>> snapshot) {
        if (snapshot == null || snapshot.isEmpty()) {
            return ORDER_KIND_PROCESSING;
        }
        for (Map<String, Object> row : snapshot) {
            // 判据委托给唯一实现点（issue #7222）：显式 saleForm 优先，缺键按布料专属事实兜底。
            if (!isFabricSaleLine(row)) {
                return ORDER_KIND_PROCESSING;
            }
        }
        return ORDER_KIND_OUTBOUND;
    }
}
