package com.migao.admin.mapper;

import com.migao.admin.dto.CustomerImportKey;
import com.migao.admin.entity.CustomerProfile;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Result;
import org.apache.ibatis.annotations.ResultMap;
import org.apache.ibatis.annotations.Results;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.List;

/**
 * 客户档案 Mapper 接口
 *
 * <p><b>issue #7257</b>：三处建档写面原先是「{@code selectOne} 判空 → {@code insert}」的读改写，
 * 而本表**没有任何唯一约束** ⇒ 并发（下单自动建档 × 手工建档 × 接口重试）会静默写出同一手机号/微信身份的两条档案，
 * 消费总额与订单数被劈成两行。现在唯一性靠迁移 V167 的两条部分唯一索引兜底，
 * 写面统一走 {@code insertIgnore* + 撞键回读}（见 {@code CustomerProfileWriter}），不再用裸 {@code insert}。</p>
 *
 * <p>issue #8295（客户主数据迁移）追加 {@code external_id} 幂等键：同一
 * {@code (tenant_id, external_id)} 至多一行，重跑同一份 Excel 不重复建客户。</p>
 *
 * <p>🔴 手写 {@code @Select} 必须显式绑 {@code mybatis-plus_<实体>} 的 autoResultMap（#4865 同族口径）：
 * 否则 {@code tags} / {@code custom_fields}（JSONB）会以 JSON 字符串落到 {@code Object} 字段上，
 * 而 {@code instanceof} 判据会**静默为假**。</p>
 *
 * <p>🔴 读侧也收口：历史重复行存在时 {@code selectOne} 会抛 {@code TooManyResultsException}（500），
 * 故本接口只提供 {@code findFirst*}（{@code ORDER BY registered_at, id LIMIT 1}，确定性取最早那条）。</p>
 */
@Mapper
public interface CustomerProfileMapper extends BaseMapper<CustomerProfile> {

    /** 只刷新「最后活跃时刻」（条件写、只写这一列；不再整实体 {@code updateById} 回写）。 */
    @Update("UPDATE customer_profiles SET last_active_at = NOW() "
            + "WHERE id = #{id} AND tenant_id = #{tenantId}")
    int touchLastActiveAt(@Param("tenantId") Long tenantId, @Param("id") String id);

    /** 按手机号取最早的一条（历史重复行下不抛错，确定性取首条）。 */
    @ResultMap("mybatis-plus_CustomerProfile")
    @Select("SELECT * FROM customer_profiles WHERE tenant_id = #{tenantId} AND phone = #{phone} "
            + "ORDER BY registered_at, id LIMIT 1")
    CustomerProfile findFirstByPhone(@Param("tenantId") Long tenantId, @Param("phone") String phone);

    /** 按微信 openid 取最早的一条。 */
    @ResultMap("mybatis-plus_CustomerProfile")
    @Select("SELECT * FROM customer_profiles WHERE tenant_id = #{tenantId} AND wechat_openid = #{openid} "
            + "ORDER BY registered_at, id LIMIT 1")
    CustomerProfile findFirstByOpenid(@Param("tenantId") Long tenantId, @Param("openid") String openid);

    /** 按旧系统客户ID取最早的一条（issue #8295；外部 ID 是迁移幂等键）。 */
    @ResultMap("mybatis-plus_CustomerProfile")
    @Select("SELECT * FROM customer_profiles WHERE tenant_id = #{tenantId} AND external_id = #{externalId} "
            + "ORDER BY registered_at, id LIMIT 1")
    CustomerProfile findFirstByExternalId(@Param("tenantId") Long tenantId,
                                          @Param("externalId") String externalId);

    /**
     * 批量取 {@code external_id -> id}（迁移预览/提交用；不做 N+1 查询）。
     *
     * <p>调用方必须保证 {@code externalIds} 非空；分块由调用方负责。</p>
     */
    @Select("<script>SELECT id, external_id FROM customer_profiles "
            + "WHERE tenant_id = #{tenantId} AND external_id IN "
            + "<foreach collection='externalIds' item='eid' open='(' separator=',' close=')'>#{eid}</foreach>"
            + "</script>")
    @Results({
            @Result(column = "id", property = "id"),
            @Result(column = "external_id", property = "externalId")
    })
    List<CustomerImportKey> findKeysByExternalIds(@Param("tenantId") Long tenantId,
                                                  @Param("externalIds") List<String> externalIds);

    /**
     * 按手机号建档，**撞唯一键不插**（幂等 + 并发兜底）。
     *
     * <p>⚠️ 这里用**无目标**的 {@code ON CONFLICT DO NOTHING}（不写冲突目标）：本表有**两个**唯一索引
     * （手机号 / 微信身份），同一条插入可能同时撞两个 —— 若写死 {@code ON CONFLICT (tenant_id, phone)}，
     * 撞的是 **openid** 那条索引时 PG 仍会抛（本机实测就是这么红的）。无目标形态把"撞任意唯一键"都收敛成 0 行。</p>
     *
     * <p>本表**没有 deleted 列**、也不做逻辑删除 ⇒ 普通唯一索引即可；PG 的唯一索引不约束 NULL
     * ⇒ 没有手机号 / 没有 openid 的档案不会互相冲突（匿名档案可以多条）。</p>
     *
     * @return 1 = 本次插入；0 = 已存在（调用方回读那一条）
     */
    @Insert("INSERT INTO customer_profiles "
            + "(id, tenant_id, wechat_openid, wechat_nickname, phone, agent_notes, vip_level, customer_status, "
            + " lifecycle_stage, total_orders, total_consumption, source_channel, registered_at, last_active_at) "
            + "VALUES (#{p.id}, #{p.tenantId}, #{p.wechatOpenid}, #{p.wechatNickname}, #{p.phone}, #{p.agentNotes}, "
            + " #{p.vipLevel}, #{p.customerStatus}, #{p.lifecycleStage}, #{p.totalOrders}, #{p.totalConsumption}, "
            + " #{p.sourceChannel}, #{p.registeredAt}, #{p.lastActiveAt}) "
            + "ON CONFLICT DO NOTHING")
    int insertIgnoreByPhone(@Param("p") CustomerProfile profile);

    /** 按微信 openid 建档，撞唯一键不插（谓词见 {@link #insertIgnoreByPhone}）。 */
    @Insert("INSERT INTO customer_profiles "
            + "(id, tenant_id, wechat_openid, wechat_nickname, source_channel, vip_level, customer_status, "
            + " lifecycle_stage, total_orders, total_consumption, registered_at, last_active_at) "
            + "VALUES (#{p.id}, #{p.tenantId}, #{p.wechatOpenid}, #{p.wechatNickname}, #{p.sourceChannel}, "
            + " #{p.vipLevel}, #{p.customerStatus}, #{p.lifecycleStage}, #{p.totalOrders}, "
            + " #{p.totalConsumption}, #{p.registeredAt}, #{p.lastActiveAt}) "
            + "ON CONFLICT DO NOTHING")
    int insertIgnoreByOpenid(@Param("p") CustomerProfile profile);

    /**
     * 迁移建档：写全客户主数据 canonical 字段 + {@code external_id}（issue #8295）。
     *
     * <p>为什么不复用 {@link #insertIgnoreByPhone}：那条固定列清单只写会话/下单建档需要的 14 列，
     * 会把导入的地址、收货人、省市区静默丢掉；这里是独立的迁移写面，列清单显式可审计。</p>
     *
     * <p>无目标 {@code ON CONFLICT DO NOTHING}：同时覆盖 {@code external_id} / 手机号两个唯一键；
     * 调用方回读判断是并发命中还是手机号占用。</p>
     */
    @Insert("INSERT INTO customer_profiles "
            + "(id, tenant_id, external_id, wechat_nickname, phone, region_province, region_city, region_district, "
            + " agent_notes, vip_level, customer_status, lifecycle_stage, total_orders, total_consumption, "
            + " source_channel, default_receiver_name, default_receiver_phone, default_receiver_address, "
            + " registered_at, last_active_at) "
            + "VALUES (#{p.id}, #{p.tenantId}, #{externalId}, #{p.wechatNickname}, #{p.phone}, "
            + " #{p.regionProvince}, #{p.regionCity}, #{p.regionDistrict}, #{p.agentNotes}, #{p.vipLevel}, "
            + " #{p.customerStatus}, #{p.lifecycleStage}, #{p.totalOrders}, #{p.totalConsumption}, "
            + " #{p.sourceChannel}, #{p.defaultReceiverName}, #{p.defaultReceiverPhone}, "
            + " #{p.defaultReceiverAddress}, #{p.registeredAt}, #{p.lastActiveAt}) "
            + "ON CONFLICT DO NOTHING")
    int insertIgnoreByExternalId(@Param("p") CustomerProfile profile,
                                 @Param("externalId") String externalId);
}
