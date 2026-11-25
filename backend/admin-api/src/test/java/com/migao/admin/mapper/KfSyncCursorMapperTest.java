// case_ids: KF-008
package com.migao.admin.mapper;

import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
import org.apache.ibatis.annotations.Insert;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;

import static org.assertj.core.api.Assertions.assertThat;

class KfSyncCursorMapperTest {

    @Test
    @DisplayName("dirty 置位是 upsert：重复回调也刷新 dirty_at")
    void markDirty() throws Exception {
        Method m = KfSyncCursorMapper.class.getMethod("markDirty", Long.class, String.class);
        String sql = String.join(" ", m.getAnnotation(Insert.class).value());
        assertThat(sql).contains("INSERT INTO kf_sync_cursor")
                .contains("ON CONFLICT (tenant_id, open_kfid)")
                .contains("dirty_at = NOW()");
        assertThat(m.getAnnotation(InterceptorIgnore.class).tenantLine()).isEqualTo("true");
    }
}
