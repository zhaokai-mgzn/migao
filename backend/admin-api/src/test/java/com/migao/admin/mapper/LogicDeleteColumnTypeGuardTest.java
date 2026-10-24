// case_ids: OPS-001
package com.migao.admin.mapper;

import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.lang.reflect.Field;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * **类级元守卫**（issue #7373 复盘）：`deleted` 列的 SQL 类型必须与实体的逻辑删语义一致。
 *
 * <h3>要治的缺陷（云上真实发生过）</h3>
 * <p>全局配置是 `logic-not-delete-value: 0` ⇒ 自动追加 `deleted = 0`。若有表的列是 **BOOLEAN**，
 * PostgreSQL 直接报 `操作符不存在: boolean = integer` ⇒ 整个读面 500（云上「采购单加载失败」就是这条）。
 * 而单元测试把 Mapper 全 mock 掉，一条都测不出来 —— 只有真库、或这条**扫源码 + 扫描建库脚本**的元守卫能抓。</p>
 *
 * <h3>判据</h3>
 * <ol>
 *   <li>扫全部实体：`deleted` 字段带 {@code @TableLogic} 的，按 {@code @TableName} 找到建库脚本里的列类型；</li>
 *   <li>列是 {@code BOOLEAN} ⇒ 必须显式 {@code @TableLogic(value = "false", delval = "true")}；</li>
 *   <li>列是 {@code INTEGER} ⇒ 必须用全局默认（不得写布尔值，否则反向出现 `integer = boolean`）。</li>
 * </ol>
 *
 * <p>红证方向：把 {@code PurchaseOrder.deleted} 的 {@code @TableLogic(value = "false", delval = "true")}
 * 去掉 ⇒ 本类当场红（那正是云上 500 的形态）。</p>
 */
@DisplayName("逻辑删列类型元守卫：BOOLEAN 列必须用布尔 TableLogic，INTEGER 列必须用默认整数")
class LogicDeleteColumnTypeGuardTest {

    private static final Path ENTITY_DIR = Path.of("src/main/java/com/migao/admin/entity");
    private static final Path SCHEMA = Path.of("src/main/resources/db/init/schema.sql");

    @Test
    @DisplayName("🔴 每个带 @TableLogic 的 deleted 字段，其列类型的语义必须与注解一致")
    void logicDeleteAnnotationMatchesColumnType() throws Exception {
        String schema = Files.readString(SCHEMA);
        List<String> problems = new ArrayList<>();
        int checked = 0;

        for (Path file : entityFiles()) {
            String source = Files.readString(file);
            if (!source.contains("@TableLogic")) {
                continue;
            }
            Matcher table = Pattern.compile("@TableName\\((?:value\\s*=\\s*)?\"(\\w+)\"").matcher(source);
            if (!table.find()) {
                continue;
            }
            String tableName = table.group(1);
            String columnType = columnType(schema, tableName, "deleted");
            if (columnType == null) {
                continue;   // 该表没有 deleted 列（或不在此建库脚本里）⇒ 不在本判据射程
            }
            boolean booleanAnnotation = source.contains("@TableLogic(value = \"false\", delval = \"true\")");
            checked++;
            if (columnType.equalsIgnoreCase("boolean") && !booleanAnnotation) {
                problems.add(String.format(
                        "%s：列 deleted 是 BOOLEAN，但注解用的是全局整数默认（会生成 deleted = 0 ⇒ "
                                + "PG 报 `boolean = integer`，读面 500）", tableName));
            }
            if (!columnType.equalsIgnoreCase("boolean") && booleanAnnotation) {
                problems.add(String.format(
                        "%s：列 deleted 是 %s，但注解写的是布尔值（会生成 deleted = false ⇒ `integer = boolean`）",
                        tableName, columnType));
            }
        }

        assertThat(checked).as("扫到的实体数不能为 0（否则本判据空转）").isPositive();
        assertThat(problems).as("逻辑删语义与列类型的漂移：%s", problems).isEmpty();
    }

    @Test
    @DisplayName("前提自证：建库脚本里确实存在 BOOLEAN 的 deleted 列（否则上条判据永远绿）")
    void booleanDeletedColumnsStillExist() throws Exception {
        String schema = Files.readString(SCHEMA);
        assertThat(schema).as("若本仓已把 deleted 统一成 INTEGER，本元守卫可以退场（连同注释一起删）")
                .contains("deleted BOOLEAN");
    }

    private static List<Path> entityFiles() throws IOException {
        try (Stream<Path> stream = Files.list(ENTITY_DIR)) {
            return stream.filter(p -> p.getFileName().toString().endsWith(".java")).toList();
        }
    }

    /** 从建库脚本里取某表某列的类型（不手抄列清单：库改了这里自动跟上）。 */
    private static String columnType(String schema, String table, String column) {
        Matcher block = Pattern.compile(
                "CREATE TABLE IF NOT EXISTS " + table + " \\(([\\s\\S]*?)\\n\\);").matcher(schema);
        if (!block.find()) {
            return null;
        }
        Matcher col = Pattern.compile("^\\s{4}" + column + "\\s+([A-Za-z]+)", Pattern.MULTILINE)
                .matcher(block.group(1));
        return col.find() ? col.group(1) : null;
    }
}
