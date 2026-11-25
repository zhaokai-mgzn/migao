package com.migao.admin.mapper;

import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.KfChannel;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

public interface KfChannelMapper extends BaseMapper<KfChannel> {

    /**
     * 回调里没有 TenantContext（企业微信不可能是登录态）⇒ 显式忽略租户拦截，
     * 用 corp_id + open_kfid 反查渠道，再由渠道行拿到 tenant_id。
     */
    @InterceptorIgnore(tenantLine = "true")
    @Select("SELECT * FROM kf_channels WHERE corp_id = #{corpId} AND open_kfid = #{openKfid} LIMIT 1")
    KfChannel selectByCorpAndOpenKfid(@Param("corpId") String corpId, @Param("openKfid") String openKfid);
}
