package com.migao.admin.migration;

// case_ids: PG-023

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 特殊选项两张表的迁移契约 + **三源防漂移**（V59，issue #4230 Java 侧 v1a）
 *
 * <p>守四条会被下一位验收者重开的判据：</p>
 * <ol>
 *   <li><b>真值源逐行相等</b>：V59 的 {@code production_option_routings} 种子 ↔
 *       {@code docs/sql/schema.sql} 的终态 ↔ ai-agent {@code routing.py::SPECIAL_OPTION_ROUTINGS}
 *       **三源逐行逐值**相等（沿用 V54/V56 的既有防漂移范式）。「忘了映射」与「本来就不计件」
 *       此前在数据上长得一模一样（都是 {@code .get(opt) → None} 的静默黑洞）—— 本判据让
 *       改名/改值/加减选项立刻变红。</li>
 *   <li><b>不计件选项不得落表</b>：{@code NON_PIECEWORK_OPTIONS}（余料带回(布)/(纱)）在真值源里是
 *       **显式登记的「不计件」**；落进本表会变成「有映射但系数 1」，两种语义又混成一种。</li>
 *   <li><b>系数档位照搬</b>：{@code OPTION_FACTOR_SCOPES} 的每个档（选项/工序限定/系数）逐值落表；
 *       v1 只有「一分二 ⇒ ×1.7 / 该部位全部工序（operation_name IS NULL）」一个**实证**档 ——
 *       §2.4 的逐工序细算档是**纯推算**，不拿推算值覆盖实证值 ⇒ 不得出现在种子里。</li>
 *   <li><b>结构判据</b>：{@code operation_name} 可空（NULL = 该部位全部工序）但唯一性用
 *       <b>表达式索引</b>（{@code COALESCE(operation_name,'')}）—— NULL 在普通唯一索引里互不相等，
 *       不加 COALESCE 就能插进多行「同选项同平摊档」⇒ 系数取值不确定（静默失真）。</li>
 * </ol>
 *
 * <p>红证（实现前）：V59 迁移与两张表/两个实体都不存在 ⇒ 本文件编译失败（找不到符号）；
 * 把种子里任一行改值 ⇒ 判据 1 逐行比对红。</p>
 */
@DisplayName("特殊选项迁移契约 + 三源防漂移（V59，issue #4230）")
class ProductionOptionRoutingMigrationTest {

    private static final String MIGRATION =
            "backend/admin-api/src/main/resources/db/migration/V59__create_production_option_tables.sql";
    private static final String SCHEMA = "docs/sql/schema.sql";
    private static final String ROUTING_PY =
            "backend/ai-agent-service/app/production/routing.py";

    private static Path repoRoot() {
        Path cur = Paths.get("").toAbsolutePath();
        while (cur != null) {
            if (Files.isDirectory(cur.resolve("backend/admin-api/src/main/resources/db/migration"))) {
                return cur;
            }
            cur = cur.getParent();
        }
        throw new IllegalStateException("找不到仓库根目录");
    }

    private static String read(String relative) throws Exception {
        return Files.readString(repoRoot().resolve(relative), StandardCharsets.UTF_8);
    }

    // ── 真值源解析（routing.py 的 SPECIAL_OPTION_ROUTINGS / OPTION_FACTOR_SCOPES）────────

    /** 从 python 源码里截取 `NAME = { ... }` 的块（到行首 `}` 为止）。 */
    private static String pythonBlock(String source, String name) {
        int at = source.indexOf(name + ": Dict");
        if (at < 0) {
            at = source.indexOf(name + " = {");
        }
        assertThat(at).as("routing.py 里应有 %s 定义", name).isGreaterThanOrEqualTo(0);
        int open = source.indexOf('{', at);
        int depth = 0;
        for (int i = open; i < source.length(); i++) {
            char c = source.charAt(i);
            if (c == '{') {
                depth++;
            } else if (c == '}') {
                depth--;
                if (depth == 0) {
                    return source.substring(open, i + 1);
                }
            }
        }
        throw new IllegalStateException(name + " 块未闭合");
    }

    /** `"选项": {"operation": "工序", "after": "锚点"}` → 有序 Map（保序 = 真值源字典序）。 */
    private static Map<String, String[]> truthRoutings() throws Exception {
        String block = pythonBlock(read(ROUTING_PY), "SPECIAL_OPTION_ROUTINGS");
        Map<String, String[]> rows = new LinkedHashMap<>();
        Matcher m = Pattern.compile(
                "\"([^\"]+)\"\\s*:\\s*\\{\\s*\"operation\"\\s*:\\s*\"([^\"]+)\"\\s*,\\s*"
                        + "\"after\"\\s*:\\s*\"([^\"]+)\"\\s*\\}").matcher(block);
        while (m.find()) {
            rows.put(m.group(1), new String[]{m.group(2), m.group(3)});
        }
        return rows;
    }

    /** `"选项": [{"factor": 1.7, "operation_name": None, ...}]` → (选项, 工序限定, 系数) 列表。 */
    private static List<String[]> truthFactorScopes() throws Exception {
        String block = pythonBlock(read(ROUTING_PY), "OPTION_FACTOR_SCOPES");
        List<String[]> rows = new ArrayList<>();
        Matcher m = Pattern.compile(
                "\"([^\"]+)\"\\s*:\\s*\\[(.*?)\\]", Pattern.DOTALL).matcher(block);
        while (m.find()) {
            String option = m.group(1);
            Matcher scope = Pattern.compile(
                    "\\{\\s*\"factor\"\\s*:\\s*([0-9.]+)\\s*,\\s*\"operation_name\"\\s*:\\s*"
                            + "(None|\"([^\"]*)\")").matcher(m.group(2));
            while (scope.find()) {
                rows.add(new String[]{option, scope.group(3), scope.group(1)});
            }
        }
        return rows;
    }

    private static Set<String> truthNonPiecework() throws Exception {
        String source = read(ROUTING_PY);
        // 必须匹配**赋值**形态：`NON_PIECEWORK_OPTIONS` 这个名字在模块注释里先出现过若干次，
        // 用裸 indexOf 会命中注释 ⇒ 解析出别的花括号块（实测会把「拼1次」当成不计件项 = 假红）。
        Matcher assign = Pattern.compile(
                "NON_PIECEWORK_OPTIONS\\s*=\\s*frozenset\\(\\s*\\{([^}]*)\\}").matcher(source);
        assertThat(assign.find()).as("routing.py 应有 NON_PIECEWORK_OPTIONS = frozenset({...})").isTrue();
        Set<String> names = new LinkedHashSet<>();
        Matcher m = Pattern.compile("\"([^\"]+)\"").matcher(assign.group(1));
        while (m.find()) {
            names.add(m.group(1));
        }
        return names;
    }

    // ── SQL 种子解析（迁移与 bootstrap 两份都要逐行相等）────────────────────────────

    /** 解析 `INSERT INTO <table> (cols) VALUES (...), (...);` 的 VALUES 行（去掉引号与空白）。 */
    private static List<List<String>> seedRows(String sql, String table) {
        int at = sql.indexOf("INSERT INTO " + table);
        assertThat(at).as("%s 应有 %s 的种子 INSERT", table, table).isGreaterThanOrEqualTo(0);
        int values = sql.indexOf("VALUES", at);
        int end = sql.indexOf("ON CONFLICT", values);
        String body = sql.substring(values + "VALUES".length(), end);
        List<List<String>> rows = new ArrayList<>();
        Matcher m = Pattern.compile("\\(([^)]*)\\)", Pattern.DOTALL).matcher(body);
        while (m.find()) {
            List<String> cells = new ArrayList<>();
            for (String cell : m.group(1).split(",")) {
                String value = cell.trim();
                if (value.startsWith("'") && value.endsWith("'")) {
                    value = value.substring(1, value.length() - 1);
                }
                cells.add(value);
            }
            rows.add(cells);
        }
        return rows;
    }

    /** 选项 → (工序, 锚点, sort_order)：从种子行里按列名取值。 */
    private static Map<String, String[]> sqlRoutings(String sql) {
        List<List<String>> rows = seedRows(sql, "production_option_routings");
        Map<String, String[]> byOption = new LinkedHashMap<>();
        for (List<String> row : rows) {
            // 列序：id, tenant_id, option_name, operation_name, after_operation, sort_order, status
            byOption.put(row.get(2), new String[]{row.get(3), row.get(4), row.get(5)});
        }
        return byOption;
    }

    private static List<String[]> sqlFactorScopes(String sql) {
        List<String[]> rows = new ArrayList<>();
        for (List<String> row : seedRows(sql, "production_option_factors")) {
            // 列序：id, tenant_id, option_name, operation_name, factor, source
            rows.add(new String[]{row.get(2), "NULL".equals(row.get(3)) ? null : row.get(3), row.get(4)});
        }
        return rows;
    }

    // ── 判据 ─────────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("判据 1：迁移种子 ↔ bootstrap 终态 ↔ routing.py SPECIAL_OPTION_ROUTINGS 三源逐行相等")
    void seedMatchesTruthSourceAndBootstrap() throws Exception {
        Map<String, String[]> truth = truthRoutings();
        assertThat(truth).as("自检：真值源解析必须非空（否则本判据空转 = 假绿）").isNotEmpty();

        Map<String, String[]> migration = sqlRoutings(read(MIGRATION));
        Map<String, String[]> bootstrap = sqlRoutings(read(SCHEMA));

        assertThat(migration.keySet()).as("迁移种子必须与真值源**同一批选项**（改名/加减即红）")
                .containsExactlyInAnyOrderElementsOf(truth.keySet());
        assertThat(bootstrap.keySet()).as("bootstrap 终态必须与迁移同批").containsExactlyInAnyOrderElementsOf(truth.keySet());

        int order = 1;
        for (Map.Entry<String, String[]> entry : truth.entrySet()) {
            String option = entry.getKey();
            String[] expected = entry.getValue();
            for (Map<String, String[]> source : List.of(migration, bootstrap)) {
                assertThat(source.get(option)[0]).as("「%s」的条件工序", option).isEqualTo(expected[0]);
                assertThat(source.get(option)[1]).as("「%s」的锚点工序", option).isEqualTo(expected[1]);
            }
            assertThat(migration.get(option)[2]).as("「%s」的 sort_order = 真值源字典序", option)
                    .isEqualTo(String.valueOf(order++));
        }
    }

    @Test
    @DisplayName("判据 2：不计件选项（NON_PIECEWORK_OPTIONS）不得落进两张表")
    void nonPieceworkOptionsAreNotSeeded() throws Exception {
        Set<String> nonPiecework = truthNonPiecework();
        assertThat(nonPiecework).as("自检：真值源必须显式登记不计件项（否则判据空转）").isNotEmpty();

        for (String sql : List.of(read(MIGRATION), read(SCHEMA))) {
            for (String option : nonPiecework) {
                assertThat(sqlRoutings(sql)).as("「%s」是显式登记的「不计件」⇒ 不得落条件工序表", option)
                        .doesNotContainKey(option);
                assertThat(sqlFactorScopes(sql)).as("「%s」不得落系数表", option)
                        .noneSatisfy(row -> assertThat(row[0]).isEqualTo(option));
            }
        }
    }

    @Test
    @DisplayName("判据 3：系数档位逐值照搬（v1 只有「一分二 ⇒ ×1.7 / 全部工序」这个实证档）")
    void factorScopesMatchTruthSource() throws Exception {
        List<String[]> truth = truthFactorScopes();
        assertThat(truth).as("自检：真值源解析必须非空").isNotEmpty();

        for (String sql : List.of(read(MIGRATION), read(SCHEMA))) {
            List<String[]> rows = sqlFactorScopes(sql);
            assertThat(rows).as("系数行数必须与真值源档数相等").hasSameSizeAs(truth);
            for (int i = 0; i < truth.size(); i++) {
                assertThat(rows.get(i)[0]).as("选项名").isEqualTo(truth.get(i)[0]);
                assertThat(rows.get(i)[1]).as("工序限定（None ⇒ SQL NULL = 该部位全部工序）")
                        .isEqualTo(truth.get(i)[1]);
                assertThat(new java.math.BigDecimal(rows.get(i)[2])).as("系数逐值相等（不自行另定值）")
                        .isEqualByComparingTo(truth.get(i)[2]);
            }
        }
        // §2.4 的逐工序细算档（车位 ×2.0 / 后道 ×1.0 / 裁剪 ×1.2）是**纯推算** ⇒ 不得出现在种子里。
        // 判据只看**解析出的种子行**（不看注释文本：注释里引用这些数字是为了说明"为什么不种"）。
        for (String sql : List.of(read(MIGRATION), read(SCHEMA))) {
            assertThat(sqlFactorScopes(sql)).as("v1 只种「一分二」一个实证档；逐工序细算档是推算值，不种")
                    .allSatisfy(row -> assertThat(new java.math.BigDecimal(row[2]))
                            .isEqualByComparingTo("1.7"));
        }
    }

    @Test
    @DisplayName("判据 4：结构 —— operation_name 可空 + 唯一性走 COALESCE 表达式索引 + 三源列齐备")
    void tableShapeGuardsNullFlatScope() throws Exception {
        String migration = read(MIGRATION);
        String schema = read(SCHEMA);

        for (String sql : List.of(migration, schema)) {
            int at = sql.indexOf("CREATE TABLE IF NOT EXISTS production_option_factors");
            assertThat(at).as("两张表都必须建出").isGreaterThanOrEqualTo(0);
            String body = sql.substring(sql.indexOf('(', at), sql.indexOf("\n);", at));
            assertThat(Pattern.compile("(?m)^\\s*operation_name\\s+VARCHAR\\(64\\),").matcher(body).find())
                    .as("operation_name 必须**可空**（NULL = 该部位全部工序的平摊档）")
                    .isTrue();
            assertThat(body).as("列齐备：选项/工序/系数/来源").contains("option_name").contains("factor")
                    .contains("source");
        }
        assertThat(migration).as("唯一性必须用 COALESCE 表达式索引（否则多行同平摊档 ⇒ 取值不确定）")
                .contains("COALESCE(operation_name, '')");
        // 三源列名收敛（Java 实体字段 ↔ 迁移列）
        String routingEntity = read("backend/admin-api/src/main/java/com/migao/admin/entity/ProductionOptionRouting.java");
        String factorEntity = read("backend/admin-api/src/main/java/com/migao/admin/entity/ProductionOptionFactor.java");
        assertThat(routingEntity).contains("private String optionName;").contains("private String operationName;")
                .contains("private String afterOperation;").contains("private Integer sortOrder;");
        assertThat(factorEntity).contains("private String optionName;").contains("private String operationName;")
                .contains("private BigDecimal factor;").contains("private String source;");
    }
}
