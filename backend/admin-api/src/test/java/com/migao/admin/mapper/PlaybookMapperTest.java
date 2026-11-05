package com.migao.admin.mapper;

// case_ids: MC-230

import org.apache.ibatis.annotations.Update;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;
import java.time.OffsetDateTime;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 口径卡状态迁移 SQL 的**CAS 契约**判据（issue #8175）。
 *
 * <p>三条不可省的谓词，任何一条丢了都是「并发下静默错」而**功能测试照样绿**：</p>
 * <ol>
 *   <li>{@code state = <期望前态>}（不是只按主键）—— 少了它，两个审核人并发点都"成功"，
 *       审计里出现两条互相矛盾的迁移记录；</li>
 *   <li>{@code tenant_id = #{tenantId}}（显式写租户列，不依赖拦截器在场）—— 少了它，
 *       一次越权 id 就能停掉别家企业的口径；</li>
 *   <li>目标状态是**字面量** {@code 'active'} / {@code 'retired'}，且 {@code updated_at} 同批写。</li>
 * </ol>
 *
 * <p>这是**纯反射**判据（零 DB、零 Spring 上下文）：判的是写面本身，不是某次执行结果。
 * 红证：把 WHERE 里的 {@code state} 谓词删掉 ⇒ 本类必红。</p>
 */
@DisplayName("PlaybookMapper：状态迁移必须是带租户列与前态谓词的 CAS")
class PlaybookMapperTest {

    private static String sqlOf(String name) throws Exception {
        Method m = PlaybookMapper.class.getMethod(name, String.class, Long.class, String.class,
                OffsetDateTime.class);
        Update update = m.getAnnotation(Update.class);
        assertThat(update).isNotNull();
        return String.join("", update.value());
    }

    @Test
    @DisplayName("activate：draft → active，谓词含 tenant_id 与前态 state = 'draft'")
    void activateIsCasOnDraft() throws Exception {
        String sql = sqlOf("activateIfDraft");
        assertThat(sql).contains("SET state = 'active'");
        assertThat(sql).contains("WHERE id = #{id} AND tenant_id = #{tenantId} AND state = 'draft'");
        assertThat(sql).contains("activated_at = #{now}");
        assertThat(sql).contains("reviewed_by = #{reviewedBy}");
    }

    @Test
    @DisplayName("retire：active → retired，谓词含 tenant_id 与前态 state = 'active'")
    void retireIsCasOnActive() throws Exception {
        String sql = sqlOf("retireIfActive");
        assertThat(sql).contains("SET state = 'retired'");
        assertThat(sql).contains("WHERE id = #{id} AND tenant_id = #{tenantId} AND state = 'active'");
        assertThat(sql).contains("retired_at = #{now}");
    }

    @Test
    @DisplayName("两条迁移都不允许「只按主键」写（缺租户列即红）")
    void neitherTransitionUpdatesByPrimaryKeyOnly() throws Exception {
        for (String name : new String[]{"activateIfDraft", "retireIfActive"}) {
            String sql = sqlOf(name);
            assertThat(sql).contains("WHERE id = #{id} AND tenant_id = #{tenantId}");
            assertThat(sql).doesNotContain("WHERE id = #{id} AND state");
        }
    }
}
