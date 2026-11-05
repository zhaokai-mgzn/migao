package com.migao.admin.waybill;

import com.migao.admin.exception.BusinessException;

/**
 * 「该承运商未接入这项能力」—— <b>422 + 可行动文案</b>（issue #8698）。
 *
 * <p>它承载口径文档 §8「失败分类」里的第一类**未配置**：不是「服务不可用」这种笼统话术
 * （那种文案会让商家反复点 = 重复计费），而是**明确告诉他下一步做什么** ——
 * 手填单号 / 去设置页换承运商。</p>
 *
 * <p>🔴 本异常是 {@link WaybillProvider} 的 default 方法**唯一**的「未实现」出口：
 * 抛它，不返回 {@code null} / 空对象（理由见 {@link WaybillProvider} 类注释）。</p>
 */
public class WaybillUnsupportedException extends BusinessException {

    /** 错误码：承运商未接入该能力（前端据此渲染「手填」而不是「重试」）。 */
    public static final String CODE = "WAYBILL_UNSUPPORTED";

    private WaybillUnsupportedException(String message, String suggestion) {
        super(CODE, message, 422, suggestion);
    }

    /** provider 侧的「未实现」出口（{@link WaybillProvider} 的三个 default 方法共用）。 */
    public static WaybillUnsupportedException of(String carrierCode, String ability) {
        return new WaybillUnsupportedException(
                "承运商「" + displayOf(carrierCode) + "」尚未接入" + ability,
                "请改用手填单号（发货页的「快递单号」输入框）；或在「企业基础设置 → 物流取号」切换到已接入的承运商。");
    }

    /** 租户当前承运商没有取号能力时，在服务层兜底抛出（= manual 兜底的口径）。 */
    public static WaybillUnsupportedException manualFallback(String carrierDisplayName) {
        return new WaybillUnsupportedException(
                "承运商「" + carrierDisplayName + "」未接入取号，本次按手填单号处理",
                "请在手填「快递单号」后点「确认发货」；如需自动取号，请联系我们开通（该承运商的取号能力尚未上线）。");
    }

    /** carrier code → 人话（未知 code 原样回显，不编一个名字）。 */
    private static String displayOf(String carrierCode) {
        Carrier registered = CarrierCatalogue.find(carrierCode);
        return registered != null ? registered.displayName() : String.valueOf(carrierCode);
    }
}
