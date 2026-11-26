// case_ids: KF-028
package com.migao.admin.mapper;

import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Select;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * kf_media 归档行的 SQL 契约（issue #9200）。
 *
 * <p>两件事必须钉在注解里（否则会在生产上静默走偏）：① 幂等靠 `(direction, media_id)` 唯一 +
 * `ON CONFLICT DO NOTHING`；② 这两条查询都跨租户上下文（worker 线程），必须 `InterceptorIgnore`。</p>
 */
class KfMediaMapperTest {

    @Test
    @DisplayName("入站归档：唯一键幂等 + 忽略租户拦截")
    void insertInbound() throws Exception {
        Method m = KfMediaMapper.class.getMethod("insertInbound",
                Long.class, String.class, String.class, String.class, Long.class, String.class);
        String sql = String.join(" ", m.getAnnotation(Insert.class).value());
        assertThat(sql).contains("INSERT INTO kf_media")
                .contains("'in'")
                .contains("ON CONFLICT (direction, media_id) DO NOTHING");
        assertThat(m.getAnnotation(InterceptorIgnore.class).tenantLine()).isEqualTo("true");
    }

    @Test
    @DisplayName("重复投递查询只看入站方向（出站同 media_id 不得串味）")
    void selectInboundStorageKey() throws Exception {
        Method m = KfMediaMapper.class.getMethod("selectInboundStorageKey", String.class);
        String sql = String.join(" ", m.getAnnotation(Select.class).value());
        assertThat(sql).contains("storage_key")
                .contains("direction = 'in'")
                .contains("media_id = #{mediaId}");
        assertThat(m.getAnnotation(InterceptorIgnore.class).tenantLine()).isEqualTo("true");
    }
}
