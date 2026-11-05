package com.migao.admin.waybill;

import org.springframework.stereotype.Component;

/**
 * 手填单号 provider —— **今天唯一的能力实现**，也是「未接入承运商」的兜底形态
 * （issue #8698；口径文档 §3-3 / §3-5「未接入的承运商自动退回 manual」）。
 *
 * <p><b>它为什么存在</b>：没有它，「未接入」就只剩一条分支语句；有了它，兜底是一条
 * **与真实 provider 同形的实现**：能力位全 false、{@link #create} 走接口 default 抛
 * {@link WaybillUnsupportedException}。⇒ 判据可以钉「manual 路径**不产生任何外呼**」
 * （它没有任何 HTTP 客户端 / 没有注入任何第三方依赖，结构上就调不出去）。</p>
 *
 * <p>🔴 <b>不做任何外呼、不落任何库、不碰订单</b>：手填的语义就是「商家自己在发货页填单号」，
 * 取号端点走到这里只允许**报错并给出行动出口**，不允许静默成功（静默成功 = 编一个单号）。</p>
 */
@Component
public class ManualWaybillProvider implements WaybillProvider {

    @Override
    public String carrierCode() {
        return CarrierCatalogue.MANUAL_CODE;
    }

    @Override
    public boolean canCreate() {
        return false;
    }

    @Override
    public boolean canCancel() {
        return false;
    }

    @Override
    public boolean canTrack() {
        return false;
    }
}
