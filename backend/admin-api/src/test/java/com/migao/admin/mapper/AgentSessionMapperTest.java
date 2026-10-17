package com.migao.admin.mapper;

// case_ids: AG-013

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.migao.admin.entity.AgentSession;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * AgentSessionMapper 验证（issue #6962 P5-①）。
 *
 * <p>会话分配权的收口是一个**手写 SQL 的条件更新**：
 * {@code markAssignedIfWaiting} 必须同时带 `tenant_id` / `status = 'waiting'` / `deleted = 0` 三个前驱态谓词，
 * 并按**受影响行数**判赢家。谓词少一个就是「并发分配两个 200」或「跨租户可写」——
 * 这两类都是线上真实发生过的形态，且**编译期看不出来**（SQL 是字符串），所以钉在这里。</p>
 *
 * <p>为什么这条判据在本文件（而不是只靠 {@code ConcurrencyCasBatch6962MetaGuardTest}）：
 * 类级元守卫管的是「台账是否兑现」，它读的是锚；本文件直接读**这个 mapper 自己的 SQL 文本**，
 * 是「就算台账/守卫被改成恒绿，这条 SQL 本身也必须带着谓词」的第二道独立读数。</p>
 */
@DisplayName("AgentSessionMapper 验证（#6962 会话分配 CAS）")
class AgentSessionMapperTest {

    private static final Path SOURCE = Path.of(
            "src/main/java/com/migao/admin/mapper/AgentSessionMapper.java");

    @BeforeAll
    static void initTableInfo() {
        MybatisConfiguration configuration = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(configuration, "");
        TableInfoHelper.initTableInfo(assistant, AgentSession.class);
    }

    @Test
    @DisplayName("继承 BaseMapper — 标准 CRUD 由租户拦截器覆盖")
    void extendsBaseMapper_standardCrudCoveredByInterceptor() {
        assertThat(BaseMapper.class.isAssignableFrom(AgentSessionMapper.class))
                .as("AgentSessionMapper 应继承 BaseMapper<AgentSession>")
                .isTrue();
    }

    @Test
    @DisplayName("会话分配权的写面是 CAS：方法存在、返回 int（受影响行数）、参数含 tenantId + 前置态")
    void assignCasMethodTakesTenantAndReturnsAffectedRows() throws NoSuchMethodException {
        Method cas = AgentSessionMapper.class.getMethod("markAssignedIfWaiting",
                String.class, Long.class, String.class, java.time.OffsetDateTime.class);
        assertThat(cas.getReturnType())
                .as("必须返回 int（受影响行数）—— 返回 void/boolean 就没法判「谁抢到了」")
                .isEqualTo(int.class);

        String signature = cas.toString();
        assertThat(signature).as("必须带租户维度（跨租户可写 = 事故）").contains("Long");
        assertThat(signature).as("必须带前置状态（并发只许一个赢家）").contains("String");
    }

    @Test
    @DisplayName("SQL 谓词逐条在场：tenant_id + status='waiting' + deleted=0，且 status 只出现在 WHERE 侧")
    void sqlCarriesEveryPredicate() throws IOException {
        String src = Files.readString(SOURCE, StandardCharsets.UTF_8);
        Matcher m = Pattern.compile("@Update\\(([^;]*?)\\)\\s*\\n\\s*int markAssignedIfWaiting")
                .matcher(src);
        assertThat(m.find()).as("找不到 markAssignedIfWaiting 的 @Update SQL（改名 / 挪走 ⇒ 判据要同步）").isTrue();
        String sql = m.group(1).replaceAll("\\s+", " ");

        assertThat(sql).as("SET 侧必须写新状态").contains("status");
        assertThat(sql).as("必须有 tenant_id 谓词").contains("tenant_id = #{tenantId}");
        assertThat(sql).as("必须有前置状态谓词（否则已结束的会话也能被抢）").contains("status = 'waiting'");
        assertThat(sql).as("必须有未软删谓词").contains("deleted = 0");
        assertThat(sql).as("WHERE 子句必须在（整实体现写 = 本单病根）").containsIgnoringCase("WHERE");
        assertThat(sql.toUpperCase())
                .as("SET 侧不得出现 status = #{…} 之外的状态赋值形态（把条件写进 SET 等于没条件）")
                .doesNotContain("WHERE STATUS");
    }
}
