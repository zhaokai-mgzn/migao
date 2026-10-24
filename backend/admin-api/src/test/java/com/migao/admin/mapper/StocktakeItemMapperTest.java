// case_ids: STK-001
package com.migao.admin.mapper;

import com.migao.admin.entity.StocktakeItem;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.nio.file.Files;
import java.nio.file.Path;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 盘点明细 Mapper 的最小契约（issue #7373 段 2）。
 *
 * <p>主判据在 {@link StocktakeMapperTest}（字段⊆列 / 账面快照非空 / 同仓唯一进行中）；
 * 本文件只补两件：① Mapper 无旁路 SQL；② 明细行的**唯一性靠索引**（同一次盘点同批次只一行），
 * 不在 SQL 里各写一套去重。</p>
 */
@DisplayName("盘点明细 Mapper：无旁路 SQL + 同批次唯一靠索引")
class StocktakeItemMapperTest {

    private static final Path SCHEMA = Path.of("src/main/resources/db/init/schema.sql");

    @Test
    @DisplayName("Mapper 只继承 BaseMapper")
    void mapperHasNoCustomSql() {
        long declared = java.util.Arrays.stream(StocktakeItemMapper.class.getDeclaredMethods())
                .filter(m -> !m.isSynthetic()).count();
        assertThat(declared).isZero();
    }

    @Test
    @DisplayName("同一次盘点同批次只一行：写在部分唯一索引里")
    void batchUniquenessIsAConstraint() throws Exception {
        String sql = Files.readString(SCHEMA);
        assertThat(sql).contains("uk_stocktake_items_batch");
    }

    @Test
    @DisplayName("实体与建库列对齐（抽查四个关键列，全量对齐由 StocktakeMapperTest 守）")
    void keyColumnsPresent() throws Exception {
        String sql = Files.readString(SCHEMA);
        assertThat(sql).contains("book_qty", "counted_qty", "diff_qty", "stocktake_id");
        assertThat(StocktakeItem.class.getDeclaredFields()).isNotEmpty();
    }
}
