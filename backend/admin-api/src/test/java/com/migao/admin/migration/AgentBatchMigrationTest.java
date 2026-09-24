// case_ids: PR-051
package com.migao.admin.migration;

import com.migao.admin.entity.AgentBatch;
import com.migao.admin.entity.AgentBatchItem;
import com.migao.admin.mapper.AgentBatchItemMapper;
import com.migao.admin.mapper.AgentBatchMapper;
import com.migao.admin.service.AgentBatchService;
import com.baomidou.mybatisplus.annotation.TableName;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 批量更新的**批次资源**三源收敛契约（issue #5314 服务端包）。
 *
 * <p>三源 = ① 增量迁移 {@code db/migration/V127__create_agent_batches.sql}；
 * ② 建库脚本 {@code db/init/schema.sql}（新建库路径不跑历史迁移链 ⇒ 终态必须同步）；
 * ③ Java 实体 / Mapper。</p>
 *
 * <p>逐条钉死的原因（本仓反复踩过的形态）：只改一处 ⇒ <b>新建库缺表</b>（bootstrap 只跑
 * {@code schema.sql}）或 <b>存量库缺列</b>（迁移链才补）⇒ 运行时 500 → 工具熔断 → 评测被污染。
 * 判据的判别力由注入式红证承担：{@code scripts/product-batch-red-proof.py}。</p>
 *
 * <p>另钉一条**架构契约**：{@code old_value} 的载体是 {@code agent_batch_items}，
 * <b>不得</b>复用 {@code audit_logs} —— 审计是有界 fail-open（丢行允许），
 * 拿它当撤销依据 = 撤销会静默丢失依据。</p>
 */
@DisplayName("批量更新批次资源三源契约（V127 ↔ schema.sql ↔ 实体）")
class AgentBatchMigrationTest {

    private static final String LIVE_DIR =
            "backend/admin-api/src/main/resources/db/migration/";
    private static final String ARCHIVE_DIR =
            "backend/admin-api/src/main/resources/db/migration-archive/";
    private static final String MIGRATION_REL = LIVE_DIR + "V127__create_agent_batches.sql";
    private static final String SCHEMA_REL = "backend/admin-api/src/main/resources/db/init/schema.sql";

    /** 契约列（issue #5314 评论「### 表」，逐字）。 */
    private static final List<String> BATCH_COLUMNS = List.of(
            "id", "tenant_id", "batch_type", "status", "item_count", "success_count",
            "fail_count", "created_by", "created_at", "executed_at", "reverted_at");
    private static final List<String> ITEM_COLUMNS = List.of(
            "id", "batch_id", "resource_id", "field", "old_value", "new_value", "status", "error");

    private static Path root() {
        Path p = Paths.get("").toAbsolutePath();
        while (p != null && !Files.isDirectory(p.resolve("backend/admin-api"))) {
            p = p.getParent();
        }
        assertThat(p).as("找不到仓库根（backend/admin-api）").isNotNull();
        return p;
    }

    private static String read(String rel) throws Exception {
        return Files.readString(root().resolve(rel), StandardCharsets.UTF_8);
    }

    /**
     * 只留**可执行引用**：剥掉 `--` 行注释与**单引号字符串字面量**。
     *
     * <p>为什么单引号字面量也要剥：`COMMENT ON TABLE ... IS '... 不得改用 audit_logs ...'` 里的
     * 「提及」是**存进 DB 的文档**，不是数据通路；不剥它就等于禁止在注释文案里点名禁用对象
     * —— 那条纪律（本仓 issue #5286 同源）会逼着人把理由删掉。双引号标识符（`"audit_logs"`）
     * 与裸标识符照旧保留 ⇒ 真的数据通路一个都躲不掉。</p>
     */
    private static String sqlCode(String text) {
        String noComments = text.replaceAll("(?m)--.*$", " ");
        String noLiterals = noComments.replaceAll("'(?:[^']|'')*'", "''");
        return noLiterals;
    }

    private static String tableBody(String sql, String table) {
        Matcher m = Pattern.compile(
                "CREATE\\s+TABLE\\s+(?:IF\\s+NOT\\s+EXISTS\\s+)?" + table + "\\s*\\(([\\s\\S]*?)\\n\\)\\s*;",
                Pattern.CASE_INSENSITIVE).matcher(sqlCode(sql));
        assertThat(m.find()).as("找不到 %s 的 CREATE TABLE（或它不以 `\\n);` 收尾）", table).isTrue();
        return m.group(1);
    }

    private static List<String> liveMigrations() throws Exception {
        Path dir = root().resolve(LIVE_DIR);
        try (Stream<Path> s = Files.list(dir)) {
            List<String> names = new ArrayList<>();
            s.filter(f -> f.getFileName().toString().endsWith(".sql"))
                    .forEach(f -> names.add(f.getFileName().toString()));
            return names;
        }
    }

    @Nested
    @DisplayName("① 迁移文件本体")
    class Migration {

        @Test
        @DisplayName("V127 是活目录的**下一个**空闲号（不跳号/不与归档号重号，防同号乱序）")
        void versionIsNextFreeAndUnique() throws Exception {
            assertThat(Files.isRegularFile(root().resolve(MIGRATION_REL)))
                    .as("迁移文件必须在 %s", MIGRATION_REL).isTrue();

            int mine = 127;
            for (String name : liveMigrations()) {
                Matcher m = Pattern.compile("^V(\\d+)__").matcher(name);
                if (m.find() && name.startsWith("V127__")) {
                    continue;
                }
                assertThat(Integer.parseInt(m.group(1)))
                        .as("活目录里 %s 的版本号必须小于 V127（V127 是最新一条）", name)
                        .isLessThan(mine);
            }
            // 归档链（历史证据，逐字节冻结）里不得有同号
            try (Stream<Path> s = Files.list(root().resolve(ARCHIVE_DIR))) {
                assertThat(s.map(f -> f.getFileName().toString())
                        .filter(n -> n.startsWith("V127__")).toList())
                        .as("归档链已有同号 ⇒ 迁移顺序不确定（issue #3812 的形态）").isEmpty();
            }
        }

        @Test
        @DisplayName("两张表 + 契约列逐字齐备（agent_batches / agent_batch_items）")
        void declaresBothTablesWithContractColumns() throws Exception {
            String sql = read(MIGRATION_REL);
            String batches = tableBody(sql, "agent_batches");
            for (String col : BATCH_COLUMNS) {
                assertThat(batches).as("agent_batches 缺契约列 %s", col)
                        .containsPattern("(?m)^\\s*" + col + "\\s");
            }
            String items = tableBody(sql, "agent_batch_items");
            for (String col : ITEM_COLUMNS) {
                assertThat(items).as("agent_batch_items 缺契约列 %s", col)
                        .containsPattern("(?m)^\\s*" + col + "\\s");
            }
            assertThat(items).as("🔴 撤销的唯一依据必须持久化").contains("old_value");
            assertThat(items).as("new_value 同表落库（预览的 after 侧）").contains("new_value");
        }

        @Test
        @DisplayName("状态机与白名单由 DB 约束钉住（不是靠代码自觉）")
        void pinsStateMachineAndWhitelist() throws Exception {
            String sql = read(MIGRATION_REL);
            for (String status : List.of("preview", "executing", "done", "partial", "reverted", "revert_partial")) {
                assertThat(sql).as("批次状态机缺 %s", status).contains("'" + status + "'");
            }
            for (String type : List.of("product_price", "product_status")) {
                assertThat(sql).as("batch_type 白名单缺 %s", type).contains("'" + type + "'");
            }
            assertThat(sqlCode(sql)).as("CHECK 约束必须在**可执行 SQL**里，不是注释里")
                    .containsIgnoringCase("CHECK");
        }

        @Test
        @DisplayName("幂等 + 显式事务 + 租户列（TenantLineInnerInterceptor 会给每张非忽略表注入 tenant_id）")
        void isIdempotentTransactionalAndTenantScoped() throws Exception {
            String sql = sqlCode(read(MIGRATION_REL));
            assertThat(sql).contains("CREATE TABLE IF NOT EXISTS agent_batches");
            assertThat(sql).contains("CREATE TABLE IF NOT EXISTS agent_batch_items");
            assertThat(sql).contains("BEGIN;").contains("COMMIT;");
            assertThat(tableBody(read(MIGRATION_REL), "agent_batches")).contains("tenant_id");
            assertThat(tableBody(read(MIGRATION_REL), "agent_batch_items"))
                    .as("明细表同样要有 tenant_id —— 否则 MyBatis-Plus 租户插件注入的 WHERE 会打到不存在的列")
                    .contains("tenant_id");
        }

        @Test
        @DisplayName("🔴 不得复用 audit_logs 作为撤销依据（审计是有界 fail-open，丢行允许）")
        void doesNotReuseAuditLogs() throws Exception {
            assertThat(sqlCode(read(MIGRATION_REL)))
                    .as("迁移里不得出现 audit_logs（撤销依据必须自己持久化）")
                    .doesNotContain("audit_logs");
            assertThat(Stream.of(AgentBatchService.class.getDeclaredFields())
                    .map(Field::getType)
                    .map(Class::getSimpleName)
                    .toList())
                    .as("服务层的撤销依据不得来自审计（AuditLogService / AuditLogMapper）")
                    .noneMatch(n -> n.startsWith("AuditLog"));
        }
    }

    @Nested
    @DisplayName("② 建库脚本（bootstrap 终态）同步")
    class SchemaSql {

        @Test
        @DisplayName("schema.sql 建同两张表且列齐（新建库路径不跑历史迁移链）")
        void declaresSameTablesAndColumns() throws Exception {
            String sql = read(SCHEMA_REL);
            String batches = tableBody(sql, "agent_batches");
            for (String col : BATCH_COLUMNS) {
                assertThat(batches).as("schema.sql 的 agent_batches 缺 %s", col)
                        .containsPattern("(?m)^\\s*" + col + "\\s");
            }
            String items = tableBody(sql, "agent_batch_items");
            for (String col : ITEM_COLUMNS) {
                assertThat(items).as("schema.sql 的 agent_batch_items 缺 %s", col)
                        .containsPattern("(?m)^\\s*" + col + "\\s");
            }
        }

        @Test
        @DisplayName("schema.sql 给两张表加行级租户隔离策略（防双源漂移）")
        void declaresRowLevelSecurity() throws Exception {
            String sql = read(SCHEMA_REL);
            assertThat(sql).contains("tenant_isolation_agent_batches");
            assertThat(sql).contains("tenant_isolation_agent_batch_items");
            assertThat(sql).contains("ALTER TABLE agent_batches ENABLE ROW LEVEL SECURITY");
            assertThat(sql).contains("ALTER TABLE agent_batch_items ENABLE ROW LEVEL SECURITY");
        }
    }

    @Nested
    @DisplayName("③ 实体 / Mapper 与表收敛")
    class Entities {

        @Test
        @DisplayName("实体映射到契约表名，字段与列逐条对齐")
        void entitiesMapToContractTables() throws Exception {
            assertThat(AgentBatch.class.getAnnotation(TableName.class).value()).isEqualTo("agent_batches");
            assertThat(AgentBatchItem.class.getAnnotation(TableName.class).value()).isEqualTo("agent_batch_items");

            for (String field : List.of("id", "tenantId", "batchType", "status", "itemCount",
                    "successCount", "failCount", "createdBy", "createdAt", "executedAt", "revertedAt")) {
                assertThat(AgentBatch.class.getDeclaredField(field)).as("AgentBatch 缺字段 %s", field).isNotNull();
            }
            for (String field : List.of("id", "batchId", "resourceId", "field", "oldValue",
                    "newValue", "status", "error")) {
                assertThat(AgentBatchItem.class.getDeclaredField(field)).as("AgentBatchItem 缺字段 %s", field).isNotNull();
            }
        }

        @Test
        @DisplayName("Mapper 挂在实体上（BaseMapper 自动获得租户过滤）")
        void mappersAreBaseMappers() {
            assertThat(AgentBatchMapper.class.getInterfaces())
                    .anyMatch(i -> i.getSimpleName().equals("BaseMapper"));
            assertThat(AgentBatchItemMapper.class.getInterfaces())
                    .anyMatch(i -> i.getSimpleName().equals("BaseMapper"));
        }

        @Test
        @DisplayName("状态机/白名单常量只有一份（服务层单一事实源，禁止各处再写字面量）")
        void statusConstantsAreSingleSource() {
            assertThat(AgentBatchService.STATUS_PREVIEW).isEqualTo("preview");
            assertThat(AgentBatchService.STATUS_EXECUTING).isEqualTo("executing");
            assertThat(AgentBatchService.STATUS_DONE).isEqualTo("done");
            assertThat(AgentBatchService.STATUS_PARTIAL).isEqualTo("partial");
            assertThat(AgentBatchService.STATUS_REVERTED).isEqualTo("reverted");
            assertThat(AgentBatchService.STATUS_REVERT_PARTIAL).isEqualTo("revert_partial");
            assertThat(AgentBatchService.TYPE_PRODUCT_PRICE).isEqualTo("product_price");
            assertThat(AgentBatchService.TYPE_PRODUCT_STATUS).isEqualTo("product_status");
            assertThat(AgentBatchService.MAX_ITEMS).isEqualTo(50);
        }
    }
}