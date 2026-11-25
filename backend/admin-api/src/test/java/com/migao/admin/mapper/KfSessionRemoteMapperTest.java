// case_ids: KF-011
package com.migao.admin.mapper;

import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
import org.apache.ibatis.annotations.Insert;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;

import static org.assertj.core.api.Assertions.assertThat;

class KfSessionRemoteMapperTest {

    @Test
    @DisplayName("当前段唯一：并发建会话用部分索引冲突静默忽略")
    void insertIgnore() throws Exception {
        Method m = KfSessionRemoteMapper.class.getMethod("insertIgnore",
                String.class, Long.class, String.class, String.class);
        String sql = String.join(" ", m.getAnnotation(Insert.class).value());
        assertThat(sql).contains("INSERT INTO kf_session_remote")
                .contains("ON CONFLICT (open_kfid, external_userid) WHERE closed_at IS NULL DO NOTHING");
        assertThat(m.getAnnotation(InterceptorIgnore.class).tenantLine()).isEqualTo("true");
    }
}
