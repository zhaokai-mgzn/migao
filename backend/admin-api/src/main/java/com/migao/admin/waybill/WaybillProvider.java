package com.migao.admin.waybill;

/**
 * 物流取号（电子面单）**能力抽象**（issue #8698 P0；口径源
 * {@code docs/logistics-waybill-api-research.md} §3-5）。
 *
 * <p><b>它是什么</b>：一家承运商（或一家聚合平台）的**取号 / 查询 / 取消**能力入口。
 * 实现类按承运商各注册一个 Spring Bean；{@link CarrierRegistry} 把它们与
 * {@link CarrierCatalogue} 的登记行合成对外的能力位。</p>
 *
 * <p>🔴 <b>未实现的能力必须抛「不支持」，不许返回假数据</b>（本接口的 default 方法就是这件事的实现）：
 * 返回 {@code null} / 空串 / 空轨迹会让上层把「没这个能力」画成「查了但没结果」——
 * 商家据此反复重试，而每一次重试都可能是**一次计费调用**（同族教训：笼统「服务不可用」
 * 让商家反复点 = 重复计费，见口径文档 §8「失败分类」）。</p>
 *
 * <p><b>P0 今天只有 {@link ManualWaybillProvider} 一个实现</b>（= 今天的手填单号能力）：
 * 真实第三方（聚合平台 / 直连快递）是 P1/P1′，依赖账号与沙箱，本单**有意不接**。</p>
 *
 * <p>⚠️ <b>能力位与声明位是两件事</b>：本接口的 {@code can*} 是**实际实现**，
 * {@link CarrierCatalogue} 的能力位是**产品声明**。{@link CarrierRegistry} 取两者的**交集**
 * 作为对 UI 生效的能力位（声明了但没实现 ⇒ 对 UI 是「不能」，而不是「声称能做」），
 * 判据 {@code CarrierRegistryTest} 逐条钉住。</p>
 */
public interface WaybillProvider {

    /** 承运商 code（逐字 = {@link CarrierCatalogue} 的登记行 code）。 */
    String carrierCode();

    /** 本实现**真的**能取号（false ⇒ 上层退回手填，不发任何外呼）。 */
    boolean canCreate();

    /** 本实现**真的**能取消运单（P4 才做闭环；今天恒 false）。 */
    boolean canCancel();

    /** 本实现**真的**能查轨迹。 */
    boolean canTrack();

    /**
     * 取号（下单取电子面单号）。未实现 ⇒ {@link WaybillUnsupportedException}。
     *
     * <p>实现方**不得**改订单状态：取号 ≠ 发货（口径文档 §3-2）。订单仍「待发货」，
     * 必须人点「确认发货」走既有的 {@code POST /api/admin/production/orders/{orderId}/ship}。</p>
     */
    default WaybillCreateResult create(WaybillCreateRequest request) {
        throw WaybillUnsupportedException.of(carrierCode(), "取号");
    }

    /** 查询轨迹。未实现 ⇒ {@link WaybillUnsupportedException}。 */
    default WaybillTrackResult track(String trackingNo) {
        throw WaybillUnsupportedException.of(carrierCode(), "轨迹查询");
    }

    /** 取消运单。未实现 ⇒ {@link WaybillUnsupportedException}。 */
    default void cancel(String waybillNo) {
        throw WaybillUnsupportedException.of(carrierCode(), "取消运单");
    }
}
