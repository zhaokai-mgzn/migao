// case_ids: DA-032

package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableFieldInfo;
import com.baomidou.mybatisplus.core.metadata.TableInfo;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.migao.admin.entity.BriefingAction;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * {@link BriefingActionMapper} 映射一致性（issue #8260）。
 *
 * <p>裸 {@code BaseMapper} 没有自定义 SQL 可测，所以这里钉**真正会坏的那件事**：
 * 实体的字段 ↔ 列名 ↔ {@code V204} 迁移的三方一致。改字段名、改列名、加列忘了写迁移
 * （或反过来）—— 生产上表现为「查不到 / 插入报列不存在」，而单测通常一片绿。
 * 这条判据让它在 PR 上就红。</p>
 */
@DisplayName("决策采纳记录 Mapper 映射一致性（issue #8260）")
class BriefingActionMapperTest {

    private static final Path MIGRATION =
            Path.of("src/main/resources/db/migration/V204__create_briefing_actions.sql");

    private TableInfo tableInfo() {
        MybatisConfiguration conf = new MybatisConfiguration();
        return TableInfoHelper.initTableInfo(new MapperBuilderAssistant(conf, ""), BriefingAction.class);
    }

    @Test
    @DisplayName("表名与主键")
    void table_name_and_key() {
        TableInfo info = tableInfo();

        assertThat(info.getTableName()).isEqualTo("briefing_actions");
        assertThat(info.getKeyProperty()).isEqualTo("id");
        assertThat(info.getKeyColumn()).isEqualTo("id");
    }

    @Test
    @DisplayName("每个字段都有对应列，且列名**全部**在 V204 迁移里（加字段忘写迁移 ⇒ 红）")
    void every_column_exists_in_the_migration() throws Exception {
        List<String> columns = tableInfo().getFieldList().stream()
                .map(TableFieldInfo::getColumn)
                .toList();
        String sql = Files.readString(MIGRATION);

        assertThat(columns).contains(
                "tenant_id", "biz_date", "item_kind", "item_key",
                "action", "actor_id", "created_at", "updated_at");
        for (String column : columns) {
            assertThat(sql)
                    .as("实体字段映射到列 %s，但 V204 迁移里没有它 —— 上线会报「列不存在」", column)
                    .contains(column);
        }
    }

    @Test
    @DisplayName("bootstrap schema.sql 与迁移终态同步（新建库路径不跑迁移链）")
    void bootstrap_schema_has_the_same_table() throws Exception {
        String bootstrap = Files.readString(Path.of("src/main/resources/db/init/schema.sql"));

        assertThat(bootstrap).contains("CREATE TABLE IF NOT EXISTS briefing_actions");
        assertThat(bootstrap).contains("uk_briefing_actions_item");
    }
}
