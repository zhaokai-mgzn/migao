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
 * 企业收款二维码（微信/支付宝）
 * 对应表：tenant_payment_qrcodes（V48，issue #3990）
 * 平台不经手资金：顾客扫码直接付给商家（二清规避）。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "tenant_payment_qrcodes", autoResultMap = true)
public class TenantPaymentQrcode {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    /** wechat 微信 / alipay 支付宝 */
    private String paymentType;

    /** 收款码图片地址 */
    private String imageUrl;

    /** 收款主体名称（展示用） */
    private String payeeName;

    private String remark;

    /** active / disabled */
    private String status;

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;

    private Integer deleted;
}
