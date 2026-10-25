package com.migao.admin.service;

import com.migao.admin.entity.CustomerProfile;
import com.migao.admin.mapper.CustomerProfileMapper;
import lombok.extern.slf4j.Slf4j;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.UUID;

/**
 * 客户档案建档的**单一实现点**（issue #7257）。
 *
 * <p><b>病</b>：三处建档写面（手工建档 / 会话自动建档 / 下单自动建档）各自「{@code selectOne} 判空 + {@code insert}」，
 * 而 {@code customer_profiles} 上没有任何唯一约束 ⇒ 并发会**静默**建出同一手机号/微信身份的两条档案，
 * 于是 {@code total_orders} / {@code total_consumption} 被劈成两行（涉钱口径读不准）。</p>
 *
 * <p><b>修法</b>：唯一性交迁移 V167 的两条部分唯一索引；写面固定顺序 ——
 * ① 先**回读**（确定性取最早那条，命中即刷新最后活跃时刻并返回）；
 * ② 没命中才 `insertIgnore`（{@code ON CONFLICT … DO NOTHING}）；
 * ③ 插入影响 0 行 = 并发对手先建 ⇒ **回读它**（收敛，不抛错）。
 * 「顺序即安全顺序」：先插再读会让并发里的第二个请求白插一次（撞键虽然被吞，但多一次无谓写）。</p>
 *
 * <p>手工建档路径需要保留「同手机号已存在」的 422 语义 ⇒ 调用方用 {@link Result#created()}
 * 自己决定报不报错（自动路径幂等成功、手工路径 422）。</p>
 */
@Slf4j
public final class CustomerProfileWriter {

    private CustomerProfileWriter() {
    }

    /**
     * 建档结果：{@code profile} = 最终生效的那条（新建的或此前已存在的）；{@code created} = 本次是否真的新建。
     */
    public record Result(CustomerProfile profile, boolean created) {
    }

    /** 按手机号确保档案存在（幂等）。{@code phone} 必填（无手机号无法去重，调用方自己跳过）。 */
    public static Result ensureByPhone(CustomerProfileMapper mapper, CustomerProfile candidate) {
        String phone = candidate.getPhone();
        Long tenantId = candidate.getTenantId();
        CustomerProfile existing = mapper.findFirstByPhone(tenantId, phone);
        if (existing != null) {
            return new Result(touch(mapper, tenantId, existing), false);
        }
        candidate.setId(newId());
        int inserted = mapper.insertIgnoreByPhone(candidate);
        if (inserted > 0) {
            log.info("客户档案已建档: id={}, phone={}, tenantId={}", candidate.getId(), phone, tenantId);
            return new Result(candidate, true);
        }
        // 并发对手先建成功 ⇒ 回读那一条（幂等收敛，不抛 500）
        CustomerProfile winner = mapper.findFirstByPhone(tenantId, phone);
        log.info("客户档案撞并发（对手先建）⇒ 收敛到既有档案: phone={}, tenantId={}", phone, tenantId);
        return new Result(winner == null ? candidate : touch(mapper, tenantId, winner), false);
    }

    /** 按微信 openid 确保档案存在（幂等）；{@code openid} 为空时无法去重，调用方应自己跳过。 */
    public static Result ensureByOpenid(CustomerProfileMapper mapper, CustomerProfile candidate) {
        String openid = candidate.getWechatOpenid();
        Long tenantId = candidate.getTenantId();
        CustomerProfile existing = mapper.findFirstByOpenid(tenantId, openid);
        if (existing != null) {
            return new Result(touch(mapper, tenantId, existing), false);
        }
        candidate.setId(newId());
        int inserted = mapper.insertIgnoreByOpenid(candidate);
        if (inserted > 0) {
            log.info("客户档案已建档: id={}, openid={}, tenantId={}", candidate.getId(), openid, tenantId);
            return new Result(candidate, true);
        }
        CustomerProfile winner = mapper.findFirstByOpenid(tenantId, openid);
        log.info("客户档案撞并发（对手先建）⇒ 收敛到既有档案: openid={}, tenantId={}", openid, tenantId);
        return new Result(winner == null ? candidate : touch(mapper, tenantId, winner), false);
    }

    /**
     * 统一的默认值（三处建档案原来各写一份，口径容易漂）。返回 builder 而不是成品，
     * 因为 {@code CustomerProfile} 没有 {@code toBuilder()}，调用方要在默认值上追加自己的字段。
     */
    public static CustomerProfile.CustomerProfileBuilder candidate(Long tenantId) {
        OffsetDateTime now = OffsetDateTime.now();
        return CustomerProfile.builder()
                .tenantId(tenantId)
                .vipLevel("normal")
                .customerStatus("active")
                .lifecycleStage("new")
                .totalOrders(0)
                .totalConsumption(BigDecimal.ZERO)
                .registeredAt(now)
                .lastActiveAt(now);
    }

    private static CustomerProfile touch(CustomerProfileMapper mapper, Long tenantId, CustomerProfile profile) {
        mapper.touchLastActiveAt(tenantId, profile.getId());
        return profile;
    }

    private static String newId() {
        return UUID.randomUUID().toString().replace("-", "");
    }
}
