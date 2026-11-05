package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 物流取号的**租户级配置**（issue #8698；口径文档 §3-5 / 分期 P0）。对应表：{@code tenant_logistics_configs}。
 *
 * <p><b>它回答一个问题</b>：这家店的发货默认走哪家承运商（{@code carrier_code}）。
 * {@code null} / 缺行 ⇒ <b>全 manual</b>（今天的手填能力）—— 不做开租播种、不编默认承运商
 * （与 {@code craft_calc_configs} / {@code cutting_height_configs} 的「缺行 = 用默认值」同款口径）。</p>
 *
 * <p>⚠️ 本表**只存承运商选择**，不存任何凭据：密钥面口径见口径文档 §3-4
 * 「承运商凭据只进服务端、按租户存；前端产物里不得出现任何承运商密钥」——
 * P0 没有任何凭据（没接第三方），P1 接入时凭据列必须**不进**任何下发给浏览器的响应
 * （判据 {@code tests/unit_ci_workflows/test_waybill_p0_guards.py} 有静态 grep 兜底）。</p>
 */
@Data
@Builder(toBuilder = true)
@NoArgsConstructor
@AllArgsConstructor
@TableName("tenant_logistics_configs")
public class TenantLogisticsConfig {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    /** 承运商 code（{@code CarrierCatalogue} 的登记行 / {@code manual}）；{@code null} ⇒ 全 manual。 */
    private String carrierCode;

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;

    private Integer deleted;
}
