package com.migao.admin.mapper;

import com.migao.admin.entity.TenantPaymentQrcode;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;

/**
 * 企业收款二维码 Mapper（V48，issue #3990）
 */
@Mapper
public interface TenantPaymentQrcodeMapper extends BaseMapper<TenantPaymentQrcode> {
}
