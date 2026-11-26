package com.migao.admin.mapper;

import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

@Mapper
public interface KfInboxMapper {

    /** msg_signature 唯一：重复回调静默忽略（返回 0），但调用方仍要置 dirty。 */
    @InterceptorIgnore(tenantLine = "true")
    @Insert("INSERT INTO kf_inbox (msg_signature, corp_id, tenant_id, open_kfid, payload, status) "
            + "VALUES (#{msgSignature}, #{corpId}, #{tenantId}, #{openKfid}, CAST(#{payload} AS jsonb), 'pending') "
            + "ON CONFLICT (msg_signature) DO NOTHING")
    int insertIgnore(@Param("msgSignature") String msgSignature,
                     @Param("corpId") String corpId,
                     @Param("tenantId") Long tenantId,
                     @Param("openKfid") String openKfid,
                     @Param("payload") String payload);
}
