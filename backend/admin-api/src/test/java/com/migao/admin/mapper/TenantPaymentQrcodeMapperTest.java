package com.migao.admin.mapper;

// case_ids: ST-011

import com.migao.admin.entity.TenantPaymentQrcode;
import com.baomidou.mybatisplus.annotation.TableName;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * TenantPaymentQrcodeMapper 契约测试（企业收款二维码，issue #3990，V48）
 * 验证：表映射 tenant_payment_qrcodes + 实体字段与迁移 V48 / schema.sql 收敛
 * （防「文档-代码状态漂移」，DailyBriefingMapperTest 同模式）。
 */
@DisplayName("TenantPaymentQrcodeMapper 表/字段契约")
class TenantPaymentQrcodeMapperTest {

    @Test
    @DisplayName("实体映射 tenant_payment_qrcodes 表")
    void entityMapsToTable() {
        TableName tableName = TenantPaymentQrcode.class.getAnnotation(TableName.class);
        assertThat(tableName).as("实体必须标注 @TableName").isNotNull();
        assertThat(tableName.value()).isEqualTo("tenant_payment_qrcodes");
    }

    @Test
    @DisplayName("实体字段与 V48 迁移列收敛")
    void entityFieldsMatchMigration() {
        List<String> fields = Arrays.stream(TenantPaymentQrcode.class.getDeclaredFields())
                .map(Field::getName)
                .toList();
        // V48 迁移列（驼峰 ↔ 下划线）：tenant_id/payment_type/image_url/payee_name/remark/status
        assertThat(fields).contains(
                "tenantId", "paymentType", "imageUrl", "payeeName", "remark", "status", "deleted"
        );
    }

    @Test
    @DisplayName("Mapper 继承 BaseMapper（CRUD 能力）")
    void mapperExtendsBaseMapper() {
        assertThat(com.baomidou.mybatisplus.core.mapper.BaseMapper.class
                .isAssignableFrom(TenantPaymentQrcodeMapper.class)).isTrue();
    }
}
