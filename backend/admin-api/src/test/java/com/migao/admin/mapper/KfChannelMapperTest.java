// case_ids: KF-006
package com.migao.admin.mapper;

import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
import org.apache.ibatis.annotations.Select;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;

import static org.assertj.core.api.Assertions.assertThat;

class KfChannelMapperTest {

    @Test
    @DisplayName("按 corp_id + open_kfid 反查，且显式忽略租户拦截")
    void selectByCorpAndOpenKfid() throws Exception {
        Method m = KfChannelMapper.class.getMethod("selectByCorpAndOpenKfid", String.class, String.class);
        assertThat(String.join(" ", m.getAnnotation(Select.class).value()))
                .contains("FROM kf_channels").contains("corp_id").contains("open_kfid");
        assertThat(m.getAnnotation(InterceptorIgnore.class).tenantLine()).isEqualTo("true");
    }
}
