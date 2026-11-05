package com.migao.admin.waybill;

import com.migao.admin.exception.BusinessException;

import java.math.BigDecimal;
import java.util.Map;

/**
 * 取号请求（issue #8698）。
 *
 * <p><b>三个数据前置**本单不修**，但取号路径必须 fail-closed</b>（口径文档 §6 / 本单「硬约束 2」）：
 * 收货地址今天只有 {@code orders.customer_address} 单列 TEXT（无省/市/区），
 * 所以这里**只做形态校验、不做地址解析** —— 空 / 过短 / 只有「某省」这类脏地址一律 422，
 * <b>绝不拿脏地址下单</b>（面单打歪比报错贵：一次错误取号可能已经计费，还留下一张要作废的运单）。</p>
 *
 * <p>⚠️ 重量与件数缺省由页面给（口径 §6-2：给默认值且页面可改，**不进商品主数据**）；
 * 寄件人档案今天是「经手人姓名」而非寄件人信息（§6-3）⇒ 本单不带寄件人字段，留给 P1。</p>
 *
 * @param orderId         订单号（仅用于审计 / 幂等键；**本类不读写订单状态**）
 * @param receiverName    收货人
 * @param receiverPhone   收货电话
 * @param receiverAddress 收货地址（自由文本；fail-closed 校验见 {@link #assertCreatable()}）
 * @param packageCount    包裹件数（缺省 1）
 * @param weightKg        重量 kg（缺省 1.0）
 */
public record WaybillCreateRequest(
        String orderId,
        String receiverName,
        String receiverPhone,
        String receiverAddress,
        Integer packageCount,
        BigDecimal weightKg) {

    /** 地址最短可接受长度（低于它基本可以断定是「只填了省」或占位符）。 */
    public static final int MIN_ADDRESS_LENGTH = 6;

    /** 从请求体解析（缺键 ⇒ null，由 {@link #assertCreatable()} 判；**不在这里补默认值**）。 */
    public static WaybillCreateRequest from(String orderId, Map<String, Object> body) {
        Map<String, Object> safe = body == null ? Map.of() : body;
        return new WaybillCreateRequest(
                orderId,
                text(safe.get("receiverName")),
                text(safe.get("receiverPhone")),
                text(safe.get("receiverAddress")),
                integer(safe.get("packageCount")),
                decimal(safe.get("weightKg")));
    }

    /**
     * fail-closed 校验：不完整 ⇒ **422 + 可行动文案**，且必须发生在调用 provider **之前**。
     *
     * <p>每个失败点都要说清「缺什么、去哪补」，不是笼统「参数错误」——
     * 商家在发货页看到的话术要能直接动作。</p>
     */
    public void assertCreatable() {
        String address = receiverAddress == null ? "" : receiverAddress.trim();
        if (address.isEmpty()) {
            throw new BusinessException("WAYBILL_ADDRESS_MISSING",
                    "收货地址为空，无法自动取号",
                    422,
                    "请先在订单里补全收货地址（省/市/区 + 街道门牌），或改用手填单号发货。");
        }
        if (address.length() < MIN_ADDRESS_LENGTH) {
            throw new BusinessException("WAYBILL_ADDRESS_INCOMPLETE",
                    "收货地址过短，无法自动取号（当前：" + address + "）",
                    422,
                    "请把地址补全到「省/市/区 + 街道门牌」后再取号；补不齐就用手填单号。");
        }
        if (receiverName == null || receiverName.trim().isEmpty()) {
            throw new BusinessException("WAYBILL_RECEIVER_MISSING",
                    "收货人为空，无法自动取号", 422, "请在订单里补上收货人姓名。");
        }
        if (receiverPhone == null || receiverPhone.trim().isEmpty()) {
            throw new BusinessException("WAYBILL_PHONE_MISSING",
                    "收货电话为空，无法自动取号", 422, "请在订单里补上收货电话（快递必须能联系到收件人）。");
        }
        if (packageCount != null && packageCount <= 0) {
            throw BusinessException.validationError("包裹件数必须大于 0（当前：" + packageCount + "）");
        }
        if (weightKg != null && weightKg.signum() <= 0) {
            throw BusinessException.validationError("重量必须大于 0（当前：" + weightKg + " kg）");
        }
    }

    private static String text(Object value) {
        return value == null ? null : String.valueOf(value);
    }

    private static Integer integer(Object value) {
        if (value == null || String.valueOf(value).isBlank()) {
            return null;
        }
        return Integer.valueOf(String.valueOf(value).trim());
    }

    private static BigDecimal decimal(Object value) {
        if (value == null || String.valueOf(value).isBlank()) {
            return null;
        }
        return new BigDecimal(String.valueOf(value).trim());
    }
}
