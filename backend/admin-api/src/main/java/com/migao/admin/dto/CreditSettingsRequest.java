package com.migao.admin.dto;

import lombok.Data;

import java.math.BigDecimal;

/**
 * 授信设置请求（issue #7370）。
 *
 * <p>与客户档案 PUT 分开的原因：档案更新是「非空才覆盖」，而授信**需要能清空**
 * （停用授信 ⇒ 两个字段都置 NULL）。本请求的字段允许为 {@code null}，语义是**显式置空**。
 */
@Data
public class CreditSettingsRequest {

    /** 授信额度：null = 停用授信；0 = 启用但零额度；正数 = 额度 */
    private BigDecimal creditLimit;

    /** 账期天数：null = 未设置；0 = 现结；正数 = 账期 */
    private Integer paymentTermsDays;
}
