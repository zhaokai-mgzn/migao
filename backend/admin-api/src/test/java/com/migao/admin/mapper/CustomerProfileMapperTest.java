// case_ids: MIG-006

package com.migao.admin.mapper;

import com.migao.admin.entity.CustomerProfile;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Select;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 客户迁移 SQL 契约（issue #8295）：幂等键必须真的进 SQL，而不是只写在 Java 注释里。
 *
 * <p>unit 测试不连真库（真库由 V196 + schema integrity 守）；本类守的是「注解里的 SQL 文本」：
 * 列清单、租户谓词、批量 foreach、ON CONFLICT。改 SQL 时若把 external_id 或 tenant_id 漏掉，
 * 这里先红，避免到真库才发现重复建/跨租户可见。</p>
 */
class CustomerProfileMapperTest {

    @Test
    void migrationInsertWritesExternalIdAndCanonicalColumnsIdempotently() throws Exception {
        Method method = CustomerProfileMapper.class.getMethod(
                "insertIgnoreByExternalId", CustomerProfile.class, String.class);
        String sql = String.join(" ", method.getAnnotation(Insert.class).value());

        assertThat(sql)
                .contains("external_id")
                .contains("default_receiver_address")
                .contains("region_province")
                .contains("ON CONFLICT DO NOTHING");
    }

    @Test
    void externalIdLookupsAreTenantScoped() throws Exception {
        Method byId = CustomerProfileMapper.class.getMethod("findFirstByExternalId", Long.class, String.class);
        String byIdSql = String.join(" ", byId.getAnnotation(Select.class).value());
        assertThat(byIdSql).contains("tenant_id = #{tenantId}").contains("external_id = #{externalId}");

        Method batch = CustomerProfileMapper.class.getMethod(
                "findKeysByExternalIds", Long.class, List.class);
        String batchSql = String.join(" ", batch.getAnnotation(Select.class).value());
        assertThat(batchSql)
                .contains("tenant_id = #{tenantId}")
                .contains("external_id IN")
                .contains("<foreach");
    }
}
