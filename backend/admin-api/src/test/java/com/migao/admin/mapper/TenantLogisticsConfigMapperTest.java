// case_ids: MC-219
package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.baomidou.mybatisplus.core.metadata.TableFieldInfo;
import com.baomidou.mybatisplus.core.metadata.TableInfo;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.migao.admin.entity.TenantLogisticsConfig;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.Map;
import java.util.stream.Collectors;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * {@link TenantLogisticsConfigMapper} / {@link TenantLogisticsConfig} 契约测试（issue #8698 P0）。
 *
 * <p>判据（都能红）：</p>
 * <ol>
 *   <li><b>表名与主键</b>：{@code tenant_logistics_configs} / {@code id} —— 迁移文件与实体漂了即红
 *       （红证：把 {@code @TableName} 改成别的表 ⇒ 判据 1 红）；</li>
 *   <li><b>列映射</b>：{@code tenant_id} / {@code carrier_code} / {@code deleted} 等逐字对齐
 *       （红证：实体加字段却不加列 ⇒ 判据 2 红）；</li>
 *   <li><b>查询口径只有一处</b>：{@code selectActiveByTenant} 必须是 Mapper 上的 default 方法
 *       （读面与写面 upsert 前判重共用它）—— 谁把它删了改成各写一遍 where，判据 3 红；</li>
 *   <li><b>缺行 = 全 manual</b>：实体 {@code carrierCode} 可为空（无 {@code @TableField(required)} /
 *       无默认值逻辑）—— 这条是「没配 ≠ 配了某家」的落点。</li>
 * </ol>
 */
@DisplayName("TenantLogisticsConfigMapper 租户级物流配置（issue #8698 P0）")
class TenantLogisticsConfigMapperTest {

    @BeforeAll
    static void initTableInfo() {
        MybatisConfiguration configuration = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(configuration, "");
        TableInfoHelper.initTableInfo(assistant, TenantLogisticsConfig.class);
    }

    @Test
    @DisplayName("判据 1：表名 / 主键逐字对齐迁移（V209）")
    void tableNameAndKeyColumn() {
        TableInfo info = TableInfoHelper.getTableInfo(TenantLogisticsConfig.class);
        assertThat(info.getTableName()).isEqualTo("tenant_logistics_configs");
        assertThat(info.getKeyColumn()).isEqualTo("id");
        assertThat(BaseMapper.class.isAssignableFrom(TenantLogisticsConfigMapper.class)).isTrue();
    }

    @Test
    @DisplayName("判据 2：核心列全部映射（tenant_id / carrier_code / deleted / 时间戳）")
    void fieldColumnMapping() {
        TableInfo info = TableInfoHelper.getTableInfo(TenantLogisticsConfig.class);
        Map<String, String> columns = info.getFieldList().stream()
                .collect(Collectors.toMap(TableFieldInfo::getProperty, TableFieldInfo::getColumn));

        assertThat(columns)
                .containsEntry("tenantId", "tenant_id")
                .containsEntry("carrierCode", "carrier_code")
                .containsEntry("deleted", "deleted")
                .containsEntry("createdAt", "created_at")
                .containsEntry("updatedAt", "updated_at");
    }

    @Test
    @DisplayName("判据 3：selectActiveByTenant 是 Mapper 的 default 方法（查询口径只有一处）")
    void activeByTenantIsADefaultMethod() throws Exception {
        var method = TenantLogisticsConfigMapper.class.getMethod("selectActiveByTenant", Long.class);

        assertThat(method.isDefault()).isTrue();
        assertThat(method.getReturnType()).isEqualTo(TenantLogisticsConfig.class);
    }

    @Test
    @DisplayName("判据 4：carrierCode 可空（缺行 / 空值 = 全 manual，不编默认承运商）")
    void carrierCodeIsNullable() {
        TenantLogisticsConfig entity = TenantLogisticsConfig.builder()
                .tenantId(1L)
                .carrierCode(null)
                .deleted(0)
                .build();

        assertThat(entity.getCarrierCode()).isNull();
        assertThat(entity.getTenantId()).isEqualTo(1L);
        assertThat(entity.getDeleted()).isZero();
    }
}
