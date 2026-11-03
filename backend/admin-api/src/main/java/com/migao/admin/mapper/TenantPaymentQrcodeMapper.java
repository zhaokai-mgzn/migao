package com.migao.admin.mapper;

import com.migao.admin.entity.TenantPaymentQrcode;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

/**
 * 企业收款二维码 Mapper（V48，issue #3990）
 *
 * <p><b>issue #7255</b>：收款码是**按 {@code (tenant_id, payment_type)} 幂等**的资源（对外是
 * {@code PUT /settings/payment-qrcodes/{type}}），而写面原先是「{@code selectOne} 判空 → {@code insert}」
 * —— 并发下两个请求都判「不存在」⇒ 都插 ⇒ 第二个撞部分唯一索引
 * {@code uk_payment_qrcode_tenant_type} ⇒ {@code DuplicateKeyException} 冒泡成 <b>500</b>。
 * 现在写面收敛到下面这一条**原子 upsert**（冲突在语句内部消解，不抛、不重试）。</p>
 */
@Mapper
public interface TenantPaymentQrcodeMapper extends BaseMapper<TenantPaymentQrcode> {

    /**
     * 按 {@code (tenant_id, payment_type)} **原子的**「有则更新、无则插入」（issue #7255）。
     *
     * <p>⚠️ {@code ON CONFLICT} 的目标必须带**索引谓词** {@code WHERE deleted = 0}：本表的唯一性由
     * **部分**唯一索引承担（V48 / V206），PG 的冲突推断要求谓词匹配 —— 同族先例见
     * {@code UserRoleMapper#insertIfAbsent}。</p>
     *
     * <p>更新侧用 {@code COALESCE(EXCLUDED.…) } 保留调用方「没传就不覆盖」的既有语义
     * （原实现只在 {@code body} 里给了 {@code payeeName} / {@code remark} 时才 set）。</p>
     *
     * @return 影响行数（插入或更新都是 1；PG 的 upsert 不区分二者）
     */
    @Insert("INSERT INTO tenant_payment_qrcodes "
            + "(id, tenant_id, payment_type, image_url, payee_name, remark, status, created_at, updated_at, deleted) "
            + "VALUES (#{q.id}, #{q.tenantId}, #{q.paymentType}, #{q.imageUrl}, #{q.payeeName}, #{q.remark}, "
            + "'active', NOW(), NOW(), 0) "
            + "ON CONFLICT (tenant_id, payment_type) WHERE deleted = 0 "
            + "DO UPDATE SET image_url = EXCLUDED.image_url, "
            + "payee_name = COALESCE(EXCLUDED.payee_name, tenant_payment_qrcodes.payee_name), "
            + "remark = COALESCE(EXCLUDED.remark, tenant_payment_qrcodes.remark), "
            + "updated_at = NOW()")
    int upsertActive(@Param("q") TenantPaymentQrcode qrcode);
}
