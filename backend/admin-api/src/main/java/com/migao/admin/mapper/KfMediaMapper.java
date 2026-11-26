package com.migao.admin.mapper;

import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface KfMediaMapper {

    /**
     * 入站媒体归档行（issue #9200）。`(direction, media_id)` 唯一 ⇒ 重复投递**不产生重复行**
     * （ON CONFLICT DO NOTHING；返回 0 = 已存在）。
     */
    @InterceptorIgnore(tenantLine = "true")
    @Insert("INSERT INTO kf_media (tenant_id, open_kfid, media_id, direction, mime, size_bytes, storage_key) "
            + "VALUES (#{tenantId}, #{openKfid}, #{mediaId}, 'in', #{mime}, #{sizeBytes}, #{storageKey}) "
            + "ON CONFLICT (direction, media_id) DO NOTHING")
    int insertInbound(@Param("tenantId") Long tenantId,
                      @Param("openKfid") String openKfid,
                      @Param("mediaId") String mediaId,
                      @Param("mime") String mime,
                      @Param("sizeBytes") Long sizeBytes,
                      @Param("storageKey") String storageKey);

    /** 已归档则直接返回归档路径（同一 media_id 重复投递不再下载）。 */
    @InterceptorIgnore(tenantLine = "true")
    @Select("SELECT storage_key FROM kf_media WHERE direction = 'in' AND media_id = #{mediaId} LIMIT 1")
    String selectInboundStorageKey(@Param("mediaId") String mediaId);
}
