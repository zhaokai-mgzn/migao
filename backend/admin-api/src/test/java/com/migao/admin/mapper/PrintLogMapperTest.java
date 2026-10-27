// case_ids: OR-071
package com.migao.admin.mapper;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.migao.admin.dto.PrintLogSummary;
import com.migao.admin.entity.PrintLog;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * PrintLogMapper 契约测试（V201，issue #7902 打印流水）。
 *
 * <h3>三源收敛（只写实体不写迁移 / 迁移不同步建库脚本 ⇒ 新建库缺表、存量库缺列、端点 500）</h3>
 * <p>Java 实体 ↔ 迁移 {@code V201__create_print_logs.sql} ↔ bootstrap
 * {@code backend/admin-api/src/main/resources/db/init/schema.sql}。</p>
 *
 * <h3>本类额外钉住的四条（都只有「读源码 / 读注解」能判）</h3>
 * <ol>
 *   <li><b>append-only 结构面</b>：本 mapper 只有两条 {@code @Select}（+ BaseMapper 的 insert），
 *       **没有**任何 UPDATE / DELETE —— 打印流水是事实记录，打错了是「再打一次」，不是抹掉历史；</li>
 *   <li><b>三个闭集合与表 CHECK 逐字一致</b>：实体常量是代码侧唯一来源、CHECK 是数据库侧唯一来源，
 *       漂移就是「代码以为能提交、库里拒」；</li>
 *   <li><b>汇总只算成功发起的打印</b>：{@code selectPrintSummary} 带 {@code status = 'fired'}
 *       （失败的那次纸没有出来，算进「已打印」会让商家重打一次才发现）；</li>
 *   <li><b>两条 SQL 都显式带 tenant_id</b>（租户插件会再注入一次同值条件，冗余但让「这段 SQL 单独
 *       拿出来看也是租户隔离的」）。</li>
 * </ol>
 */
@DisplayName("PrintLogMapper：实体↔迁移↔建库脚本 + append-only + 闭集合一致")
class PrintLogMapperTest {

    /** 模块相对路径（surefire 的 workdir = admin-api 模块根；CI 与本机同口径）。 */
    private static final String SCHEMA = "src/main/resources/db/init/schema.sql";
    private static final String MIGRATION = "src/main/resources/db/migration/V201__create_print_logs.sql";
    private static final String TABLE = "print_logs";

    @Test
    @DisplayName("实体映射 print_logs；主键 = ASSIGN_UUID（与迁移的 VARCHAR(36) 对齐）")
    void entityMapsToTable() {
        TableName tableName = PrintLog.class.getAnnotation(TableName.class);
        assertThat(tableName).as("实体必须标注 @TableName").isNotNull();
        assertThat(tableName.value()).isEqualTo(TABLE);

        // ⚠️ 按**字段名**取（getDeclaredFields 的顺序不是语言规范）：首个声明是常量池，不是主键
        java.lang.reflect.Field idField;
        try {
            idField = PrintLog.class.getDeclaredField("id");
        } catch (NoSuchFieldException e) {
            throw new AssertionError("PrintLog 缺 id 字段", e);
        }
        TableId tableId = idField.getAnnotation(TableId.class);
        assertThat(tableId).as("id 必须是主键").isNotNull();
        assertThat(tableId.type()).isEqualTo(IdType.ASSIGN_UUID);
    }

    @Test
    @DisplayName("实体每个字段都在建库脚本里有对应列（少一列 = 新建库插入 500）")
    void everyEntityFieldHasAColumn() throws Exception {
        assertThat(MapperColumnAssertions.columnsOf(TABLE)).isNotEmpty();
        MapperColumnAssertions.assertEveryEntityFieldHasColumn(PrintLog.class, TABLE);
    }

    @Test
    @DisplayName("流水必备列在场（谁 / 何时 / 哪种单据 / 几张 / 结果）—— 少任何一列这张表就答不了它该答的问题")
    void auditColumnsArePresent() throws Exception {
        assertThat(MapperColumnAssertions.columnsOf(TABLE)).contains(
                "tenant_id", "order_id", "order_no",
                "doc_type", "doc_title", "processing_order_id", "processing_order_no",
                "media_id", "sheets", "channel",
                "batch_id", "batch_index", "batch_size",
                "order_status", "status", "fail_reason",
                "operator_id", "operator_name", "client_ip", "user_agent",
                "created_at");
    }

    @Test
    @DisplayName("🔴 三个闭集合：Java 常量 ↔ 表 CHECK ↔ 建库脚本 逐值一致")
    void closedSetsMatchCheckConstraints() throws Exception {
        String migration = Files.readString(dbFile(MIGRATION));
        String bootstrap = Files.readString(dbFile(SCHEMA));
        for (String source : List.of("Java", "迁移", "建库脚本")) {
            String text = "Java".equals(source) ? String.join(",", PrintLog.DOC_TYPES)
                    : ("迁移".equals(source) ? migration : bootstrap);
            for (String docType : PrintLog.DOC_TYPES) {
                if ("Java".equals(source)) {
                    assertThat(PrintLog.isKnownDocType(docType)).isTrue();
                } else {
                    assertThat(text).as("%s 必须列出 doc_type=%s", source, docType)
                            .contains("'" + docType + "'");
                }
            }
            for (String channel : PrintLog.CHANNELS) {
                if ("Java".equals(source)) {
                    assertThat(PrintLog.isKnownChannel(channel)).isTrue();
                } else {
                    assertThat(text).as("%s 必须列出 channel=%s", source, channel)
                            .contains("'" + channel + "'");
                }
            }
            for (String status : PrintLog.STATUSES) {
                if ("Java".equals(source)) {
                    assertThat(PrintLog.isKnownStatus(status)).isTrue();
                } else {
                    assertThat(text).as("%s 必须列出 status=%s", source, status)
                            .contains("'" + status + "'");
                }
            }
        }
        // 未知值一律不许通过（闭集合是 fail-closed，不是「非空即可」）
        assertThat(PrintLog.isKnownDocType("receipt")).isFalse();
        assertThat(PrintLog.isKnownChannel("usb")).isFalse();
        assertThat(PrintLog.isKnownStatus("printed")).isFalse();
    }

    @Test
    @DisplayName("🔴 append-only：本 mapper 只有两条 @Select，没有任何 update/delete 语句")
    void theMapperIsAppendOnly() {
        List<String> declared = Arrays.stream(PrintLogMapper.class.getDeclaredMethods())
                .filter(method -> !method.isSynthetic())
                .map(Method::getName)
                .toList();
        assertThat(declared).containsExactlyInAnyOrder("selectByOrder", "selectPrintSummary");
        for (Method method : PrintLogMapper.class.getDeclaredMethods()) {
            assertThat(method.isAnnotationPresent(org.apache.ibatis.annotations.Select.class))
                    .as("%s 必须是只读 @Select", method.getName())
                    .isTrue();
        }
    }

    @Test
    @DisplayName("🔴 汇总只算 fired 且带 tenant_id；详情按时间倒序（时间轴）")
    void theSummaryQueryCountsOnlyFiredPrints() {
        String summary = selectSqlOf("selectPrintSummary");
        assertThat(summary).contains("status = 'fired'");
        assertThat(summary).contains("tenant_id = #{tenantId}");
        assertThat(summary).contains("MAX(created_at) AS printed_at");
        assertThat(summary).contains("COUNT(*) AS print_count");
        assertThat(summary).contains("string_agg(DISTINCT doc_type, ',') AS doc_types");
        assertThat(summary).contains("GROUP BY order_id");

        String detail = selectSqlOf("selectByOrder");
        assertThat(detail).contains("tenant_id = #{tenantId}");
        assertThat(detail).contains("ORDER BY created_at DESC");
        assertThat(detail).contains("LIMIT #{limit}");
    }

    /**
     * 解析资源文件（两种工作目录都试：surefire 的 workdir = 模块根；IDE / 仓库根直跑时上一级）。
     * 找不到 ⇒ **抛错**（判据不许静默空跑）。
     */
    private static Path dbFile(String moduleRelative) {
        for (Path base : List.of(Path.of(""), Path.of(".."))) {
            Path candidate = base.resolve(moduleRelative);
            if (Files.isRegularFile(candidate)) {
                return candidate;
            }
        }
        throw new AssertionError("找不到资源文件 " + moduleRelative + " —— 本判据不得空跑（两种工作目录都试过）");
    }

    /** 按**方法名**取 {@code @Select} 的 SQL（不用方法数组下标：反射顺序不是语言规范）。 */
    private static String selectSqlOf(String methodName) {
        for (Method method : PrintLogMapper.class.getDeclaredMethods()) {
            if (method.getName().equals(methodName)) {
                org.apache.ibatis.annotations.Select select =
                        method.getAnnotation(org.apache.ibatis.annotations.Select.class);
                if (select == null) {
                    throw new AssertionError(methodName + " 不是 @Select（只读面才有 SQL 判据）");
                }
                return String.join(" ", select.value());
            }
        }
        throw new AssertionError("PrintLogMapper 缺方法 " + methodName);
    }

    @Test
    @DisplayName("汇总投影 DTO 的 docTypes 去重排序；空值 ⇒ 空列表（不是 null）")
    void summaryDocTypesAreNormalized() {
        PrintLogSummary summary = PrintLogSummary.builder()
                .orderId("order-1")
                .docTypes("sales,processing,sales")
                .printCount(3)
                .build();
        assertThat(summary.printedDocTypes()).containsExactly("processing", "sales");

        assertThat(PrintLogSummary.builder().docTypes(null).build().printedDocTypes()).isEmpty();
        assertThat(PrintLogSummary.builder().docTypes(" ").build().printedDocTypes()).isEmpty();
        assertThat(PrintLogSummary.builder().docTypes("fired,,").build().printedDocTypes())
                .containsExactly("fired");
    }
}
