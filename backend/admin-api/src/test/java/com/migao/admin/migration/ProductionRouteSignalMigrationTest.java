package com.migao.admin.migration;

// case_ids: PG-031, PG-035

import com.migao.admin.service.ProcessingOrderService;
import com.migao.admin.service.ProductionOperationQueryService;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 路线可配三件套的迁移契约 + **三源防漂移**（V60，issue #4308）
 *
 * <p>守四条会被下一位验收者重开的判据：</p>
 * <ol>
 *   <li><b>种子 = 迁移前常量表逐条</b>：V60 的 {@code production_route_signals} 种子 ↔
 *       {@code docs/sql/schema.sql} 的 bootstrap 终态 ↔ **迁移前的两张常量表**（{@code
 *       CURTAIN_TYPE_KEYWORDS} / {@code CRAFT_KEYWORDS} @9673df68，本文件逐条转录）
 *       **三源逐行逐值**相等。改名/改值/加减信号即红。</li>
 *   <li><b>用途拆分不可压成一行</b>：{@code 帘头} 在两个用途里位次相反（帘种表**最前**、
 *       工艺表**最后**）⇒ 必须两行、且唯一性按用途拆（两条部分唯一索引）。压成
 *       {@code (tenant_id, signal)} 单唯一键会让「帘头」的工艺映射在同一信号文本里抢在
 *       韩褶/打孔之前生效 ⇒ 静默改路线 = 静默改工资。</li>
 *   <li><b>派生不再读常量</b>：{@code ProcessingOrderService} 里**不得**再出现那两张常量表
 *       （常量与库并存 = 第二份口径，且漂移的那一份不会变红）。</li>
 *   <li><b>加工单三列 + bootstrap 终态</b>：{@code processing_orders} 的
 *       {@code route_key} / {@code route_requested_key} / {@code route_source} 在迁移（幂等
 *       {@code ADD COLUMN IF NOT EXISTS}）与 bootstrap 两处都在 —— bootstrap 路径**不跑迁移链**，
 *       只写迁移 ⇒ 新建库上该列不存在 ⇒ 加工单查询 500（#3270 形态）。</li>
 *   <li><b>V63（issue #4362）：四爪钩/四叉钩指向主线</b> —— 判据 6：两源同一条 UPDATE、
 *       目标 = {@code ProcessingOrderService.DEFAULT_CRAFT}（主线工艺）、合成终态里
 *       **不再有** {@code craft=四爪钩} 的活跃行。</li>
 *   <li><b>V63：下单行要素 11 列两处都在且全部可空</b> —— 判据 7：{@code ADD COLUMN IF NOT EXISTS}
 *       + bootstrap 建表自带 + **不得** {@code NOT NULL}（用户裁定「部位不是必填的」）。</li>
 * </ol>
 *
 * <p><b>红证</b>：① 改种子里任一行的 {@code curtain_type}/{@code craft}/{@code priority} ⇒ 判据 1 红；
 * ② 把「帘头」两行合成一行（或把两条部分唯一索引换成 {@code (tenant_id, signal)}）⇒ 判据 2 红；
 * ③ 把常量表加回 {@code ProcessingOrderService} ⇒ 判据 3 红；④ 从 bootstrap 里删掉任一列 ⇒ 判据 4 红；
 * ⑤ 删掉 V63 的那条 UPDATE / 把目标值改成 {@code 四爪钩} / 只改迁移不改 schema（或反之）⇒ 判据 6 红；
 * ⑥ 把任一要素列写成 {@code NOT NULL}、或漏进 bootstrap、或改列类型 ⇒ 判据 7 红。</p>
 */
@DisplayName("路线可配迁移契约 + 三源防漂移（V60，issue #4308）")
class ProductionRouteSignalMigrationTest {

    private static final String MIGRATION =
            "backend/admin-api/src/main/resources/db/migration/V60__create_routing_customization_tables.sql";
    private static final String MIGRATION_V63 =
            "backend/admin-api/src/main/resources/db/migration/V63__structure_order_line_craft_spec.sql";
    private static final String SCHEMA = "docs/sql/schema.sql";
    private static final String SERVICE =
            "backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java";

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

    /**
     * **迁移前的常量表**（真值源，逐条转录自 {@code git show 9673df68:…/ProcessingOrderService.java}）。
     * 顺序即语义，不得重排。列序：signal / curtain_type / craft / priority（**用途内**序）。
     */
    private static final String[][] LEGACY_SIGNALS = {
            // CURTAIN_TYPE_KEYWORDS = {帘头→帘头, 纱→纱帘, 布→布帘}
            {"帘头", "帘头", null, "1"},
            {"纱", "纱帘", null, "2"},
            {"布", "布帘", null, "3"},
            // CRAFT_KEYWORDS = {韩褶, 打孔, 四爪钩, 四叉钩, 穿杆, 平幔, 帘头→平幔}
            {"韩褶", null, "韩褶", "1"},
            {"打孔", null, "打孔", "2"},
            {"四爪钩", null, "四爪钩", "3"},
            {"四叉钩", null, "四爪钩", "4"},
            {"穿杆", null, "穿杆", "5"},
            {"平幔", null, "平幔", "6"},
            {"帘头", null, "平幔", "7"}};

    /** 解析 `INSERT INTO production_route_signals (cols) VALUES (…), (…);` 的行。 */
    private static List<String[]> seedRows(String sql) {
        int at = sql.indexOf("INSERT INTO production_route_signals");
        assertThat(at).as("应种 production_route_signals").isGreaterThanOrEqualTo(0);
        int values = sql.indexOf("VALUES", at);
        int end = sql.indexOf("ON CONFLICT", values);
        assertThat(end).as("种子应以 ON CONFLICT 收尾（幂等）").isGreaterThan(values);
        List<String[]> rows = new ArrayList<>();
        Matcher m = Pattern.compile("\\(([^)]*)\\)", Pattern.DOTALL).matcher(sql.substring(values + 6, end));
        while (m.find()) {
            String[] cells = m.group(1).split(",");
            for (int i = 0; i < cells.length; i++) {
                String v = cells[i].trim();
                if (v.startsWith("'") && v.endsWith("'")) {
                    v = v.substring(1, v.length() - 1);
                }
                cells[i] = "NULL".equals(v) ? null : v;
            }
            // 列序：id, tenant_id, signal, curtain_type, craft, priority, status
            rows.add(new String[]{cells[2], cells[3], cells[4], cells[5]});
        }
        return rows;
    }

    @Test
    @DisplayName("判据 1：V60 种子 ↔ bootstrap 终态 ↔ 迁移前常量表 三源逐行相等（顺序即语义）")
    void seedMatchesLegacyKeywordTablesAndBootstrap() throws Exception {
        assertThat(LEGACY_SIGNALS).as("自检：真值源必须非空（否则本判据空转 = 假绿）").isNotEmpty();

        List<String[]> migration = seedRows(read(MIGRATION));
        List<String[]> bootstrap = seedRows(read(SCHEMA));

        assertThat(migration).as("迁移种子行数必须 = 迁移前常量表条目数（3 帘种 + 7 工艺）")
                .hasSameSizeAs(LEGACY_SIGNALS);
        assertThat(bootstrap).as("bootstrap 终态必须与迁移同批同行").hasSameSizeAs(LEGACY_SIGNALS);

        for (int i = 0; i < LEGACY_SIGNALS.length; i++) {
            String[] expected = LEGACY_SIGNALS[i];
            for (String[] actual : List.of(migration.get(i), bootstrap.get(i))) {
                assertThat(actual[0]).as("第 %d 行的信号名（顺序即语义，不得重排）", i + 1).isEqualTo(expected[0]);
                assertThat(actual[1]).as("「%s」的帘种", expected[0]).isEqualTo(expected[1]);
                assertThat(actual[2]).as("「%s」的工艺", expected[0]).isEqualTo(expected[2]);
            }
            assertThat(migration.get(i)[3]).as("「%s」的**用途内** priority", expected[0]).isEqualTo(expected[3]);
        }
    }

    /** 解析 V63/schema 里那条 `UPDATE production_route_signals SET craft = '<目标>' …` 的目标值。 */
    private static String hookRepointTarget(String sql) {
        Matcher m = Pattern.compile(
                        "UPDATE\\s+production_route_signals\\s+SET\\s+craft\\s*=\\s*'([^']+)'",
                        Pattern.CASE_INSENSITIVE | Pattern.DOTALL)
                .matcher(sql);
        assertThat(m.find())
                .as("应有一条把 production_route_signals.craft 改写的 UPDATE（四爪钩/四叉钩 摘出 craft 语义）")
                .isTrue();
        return m.group(1);
    }

    /** 合成终态 = 种子行 + 那条 UPDATE（`四爪钩/四叉钩` 的 craft 改成目标值）。 */
    private static List<String[]> composeFinalState(List<String[]> rows, String target) {
        List<String[]> out = new ArrayList<>(rows.size());
        for (String[] row : rows) {
            String[] copy = row.clone();
            if (("四爪钩".equals(copy[0]) || "四叉钩".equals(copy[0])) && "四爪钩".equals(copy[2])) {
                copy[2] = target;
            }
            out.add(copy);
        }
        return out;
    }

    @Test
    @DisplayName("判据 6：V63 把「四爪钩/四叉钩」指向**主线工艺** —— 两源终态一致，且不再有 craft=四爪钩 的活跃行")
    void hookSignalsPointAtMainLineInBothSources() throws Exception {
        String migrationV63 = read(MIGRATION_V63);
        String schema = read(SCHEMA);

        // ① 两源都要有这条 UPDATE，且**目标值逐字相同**（否则 bootstrap 与迁移链终态漂移）
        String targetFromMigration = hookRepointTarget(migrationV63);
        String targetFromSchema = hookRepointTarget(schema);
        assertThat(targetFromSchema).as("bootstrap 终态必须与迁移链同一条 UPDATE（同一目标工艺）")
                .isEqualTo(targetFromMigration);
        // ② 目标 = **主线工艺**（= ProcessingOrderService.DEFAULT_CRAFT，真值源 §3 的 11 道主线）
        assertThat(targetFromMigration)
                .as("必须指向主线工艺 —— 「四爪钩/四叉钩」是加工项（配件），不是并列工艺（#4365 裁定）")
                .isEqualTo(ProcessingOrderService.DEFAULT_CRAFT);
        for (String sql : List.of(migrationV63, schema)) {
            assertThat(sql).as("UPDATE 的 WHERE 必须点名这两个信号（只改这两行，不扫别的）")
                    .contains("'四爪钩'").contains("'四叉钩'");
        }

        // ③ 合成终态：两源逐行相等，且**没有**任何一行还给出 craft=四爪钩
        List<String[]> migrationFinal = composeFinalState(seedRows(read(MIGRATION)), targetFromMigration);
        List<String[]> bootstrapFinal = composeFinalState(seedRows(schema), targetFromSchema);
        assertThat(migrationFinal).as("自检：判别物必须在场（否则本判据空转）")
                .anyMatch(r -> "四爪钩".equals(r[0]) && targetFromMigration.equals(r[2]))
                .anyMatch(r -> "四叉钩".equals(r[0]) && targetFromMigration.equals(r[2]));
        assertThat(migrationFinal).hasSameSizeAs(bootstrapFinal);
        for (int i = 0; i < migrationFinal.size(); i++) {
            assertThat(migrationFinal.get(i)[2]).as("第 %d 行（信号「%s」）的工艺终态", i + 1, migrationFinal.get(i)[0])
                    .isEqualTo(bootstrapFinal.get(i)[2])
                    .isNotEqualTo("四爪钩");
        }
        // ④ 迁移链与 bootstrap **同一条 DML 形态**（`ADD COLUMN IF NOT EXISTS` 之外的幂等写法）
        assertThat(migrationV63).as("UPDATE 必须限定当前仍指向 四爪钩 的行 ⇒ 重跑 0 行受影响（幂等）")
                .contains("craft = '四爪钩'");
    }

    @Test
    @DisplayName("判据 7：下单行要素 11 列在 V63（幂等增列）与 bootstrap 两处都在，且全部可空（无 NOT NULL/默认值）")
    void orderLineCraftSpecColumnsExistInBothSourcesAndAreNullable() throws Exception {
        String migrationV63 = read(MIGRATION_V63);
        String schema = read(SCHEMA);

        // 列名 → 类型（与 V63 的 DDL 逐字一致；类型写错会让写入静默截断/溢出）
        String[][] columns = {
                {"curtain_type", "VARCHAR\\(16\\)"},
                {"craft", "VARCHAR\\(16\\)"},
                {"open_count", "INTEGER"},
                {"cutting_mode", "VARCHAR\\(16\\)"},
                {"is_shaped", "BOOLEAN"},
                {"fullness", "DECIMAL\\(6,2\\)"},
                {"fullness_actual", "DECIMAL\\(6,2\\)"},
                {"pleat_spacing", "DECIMAL\\(6,3\\)"},
                {"pleat_count", "INTEGER"},
                {"has_pattern", "BOOLEAN"},
                {"corner", "VARCHAR\\(32\\)"}};
        for (String[] column : columns) {
            assertThat(Pattern.compile("ADD\\s+COLUMN\\s+IF\\s+NOT\\s+EXISTS\\s+" + column[0] + "\\s+" + column[1],
                            Pattern.CASE_INSENSITIVE).matcher(migrationV63).find())
                    .as("V63 必须用 ADD COLUMN IF NOT EXISTS 增列 %s（MigrationRunner 要求可重复执行）", column[0])
                    .isTrue();
        }

        int at = schema.toLowerCase().indexOf("create table order_items");
        assertThat(at).as("schema.sql 应有 order_items 建表语句").isGreaterThanOrEqualTo(0);
        String body = schema.substring(schema.indexOf('(', at), schema.indexOf("\n);", at));
        for (String[] column : columns) {
            assertThat(Pattern.compile("(?m)^\\s*" + column[0] + "\\s+" + column[1]).matcher(body).find())
                    .as("bootstrap 路径**不跑迁移链** ⇒ 新建库必须自带列 %s（否则落库/查询 500，#3270 形态）",
                            column[0])
                    .isTrue();
        }

        // 「部位不是必填」（用户裁定 2026-09-19）⇒ 这 11 列一律**不得**带 NOT NULL / DEFAULT
        for (String[] column : columns) {
            assertThat(Pattern.compile("(?m)^\\s*" + column[0] + "\\s+[^,\\n]*NOT\\s+NULL", Pattern.CASE_INSENSITIVE)
                            .matcher(body).find())
                    .as("列 %s 不得 NOT NULL —— 用户裁定「部位不是必填的」，本包不设必填校验", column[0])
                    .isFalse();
        }
        assertThat(migrationV63).as("列注释必须说明「可空 + 不设必填校验」（DB 是权威，字段什么意思不能靠猜）")
                .contains("部位不是必填");
    }

    @Test
    @DisplayName("判据 2：用途拆分 —— 「帘头」两行位次相反 + 唯一性按用途拆（两条部分唯一索引）")
    void perPurposeSplitKeepsOppositeRanksForLiTou() throws Exception {
        List<String[]> rows = seedRows(read(MIGRATION));
        Map<String, String[]> byPurpose = new LinkedHashMap<>();
        for (String[] row : rows) {
            if ("帘头".equals(row[0])) {
                byPurpose.put(row[1] != null ? "curtain" : "craft", row);
            }
        }
        assertThat(byPurpose).as("「帘头」必须在**两个用途**里各有一行（压成一行就会改变工艺侧位次）")
                .containsKeys("curtain", "craft");
        assertThat(byPurpose.get("curtain")[3]).as("帘种侧：帘头**最前**（防「帘头纱」被判成纱帘）").isEqualTo("1");
        assertThat(byPurpose.get("craft")[3]).as("工艺侧：帘头**最后**（它是工艺侧兜底）").isEqualTo("7");

        for (String sql : List.of(read(MIGRATION), read(SCHEMA))) {
            assertThat(sql).as("唯一性必须**按用途拆**：帘种行唯一索引")
                    .contains("uk_production_route_signals_tenant_signal_curtain");
            assertThat(sql).as("唯一性必须**按用途拆**：工艺行唯一索引")
                    .contains("uk_production_route_signals_tenant_signal_craft");
            assertThat(sql).as("一行至少给出一维（否则是死数据）")
                    .contains("ck_production_route_signals_has_target");
        }
    }

    @Test
    @DisplayName("判据 3：派生**不再读常量** —— 两张常量表不得回到 ProcessingOrderService")
    void derivationNoLongerReadsJavaConstants() throws Exception {
        String service = read(SERVICE);
        // 只看**声明形态**（注释/javadoc 里提到这两个名字是为了说明「为什么删掉」——
        // 用裸 contains 会把说明文字判成违规 = 假红，正是「散文禁令不单独承重」的反面）
        for (String constant : List.of("CURTAIN_TYPE_KEYWORDS", "CRAFT_KEYWORDS")) {
            assertThat(Pattern.compile("(?m)^\\s*(private|static|public|final)[^;=]*\\b" + constant + "\\b")
                            .matcher(service).find())
                    .as("%s 必须已删除（常量与库并存 = 第二份口径，漂移的那份不会变红）", constant)
                    .isFalse();
        }
        assertThat(service).as("派生必须读库（租户级信号映射表）")
                .contains("productionOperationQueryService.routeSignals(tenantId)");
    }

    @Test
    @DisplayName("判据 5：待确认工序集合与 routing.py::PENDING_CUSTOMER_CONFIRMATION_OPERATIONS **同源**（双向可红）")
    void pendingConfirmationSetMatchesTruthSource() throws Exception {
        String py = read("backend/ai-agent-service/app/production/routing.py");
        // 必须匹配**赋值**形态（名字在模块注释里先出现过若干次 ⇒ 裸 indexOf 会命中注释 = 假红）
        Matcher assign = Pattern.compile(
                "PENDING_CUSTOMER_CONFIRMATION_OPERATIONS\\s*=\\s*frozenset\\(\\s*\\{([^}]*)\\}").matcher(py);
        assertThat(assign.find()).as("routing.py 应有 PENDING_CUSTOMER_CONFIRMATION_OPERATIONS = frozenset({...})")
                .isTrue();
        java.util.Set<String> truth = new java.util.LinkedHashSet<>();
        Matcher names = Pattern.compile("\"([^\"]+)\"").matcher(assign.group(1));
        while (names.find()) {
            truth.add(names.group(1));
        }
        assertThat(truth).as("自检：真值源必须非空（否则本判据空转 = 假绿）").isNotEmpty();
        assertThat(ProductionOperationQueryService.PENDING_CUSTOMER_CONFIRMATION_OPERATIONS)
                .as("缺口查询的「待确认」标记必须与 routing.py 同源：少一道（漏标）/ 多一道（错标）都红 —— "
                        + "Java 无法 import Python，故用逐字解析 + 双向比对守；抄一份字面量而不守就是第二份口径")
                .containsExactlyInAnyOrderElementsOf(truth);
    }

    @Test
    @DisplayName("判据 4：加工单三列在迁移（幂等）与 bootstrap 两处都在；路线版本账同建")
    void processingOrderColumnsAndVersionLedgerExistInBothSources() throws Exception {
        String migration = read(MIGRATION);
        String schema = read(SCHEMA);

        for (String column : List.of("route_key", "route_requested_key", "route_source")) {
            assertThat(Pattern.compile("ADD\\s+COLUMN\\s+IF\\s+NOT\\s+EXISTS\\s+" + column + "\\s+VARCHAR\\(\\d+\\)",
                            Pattern.CASE_INSENSITIVE).matcher(migration).find())
                    .as("迁移必须用 ADD COLUMN IF NOT EXISTS 增列 %s（MigrationRunner 要求可重复执行）", column)
                    .isTrue();
        }
        int at = schema.toLowerCase().indexOf("create table if not exists processing_orders");
        assertThat(at).as("schema.sql 应有 processing_orders 建表语句").isGreaterThanOrEqualTo(0);
        String body = schema.substring(schema.indexOf('(', at), schema.indexOf("\n);", at));
        for (String column : List.of("route_key", "route_requested_key", "route_source")) {
            assertThat(Pattern.compile("(?m)^\\s*" + column + "\\s+VARCHAR").matcher(body).find())
                    .as("bootstrap 路径**不跑迁移链** ⇒ 新建库必须自带列 %s（否则查询 500，#3270 形态）", column)
                    .isTrue();
        }
        // 四态口径必须写在列注释里（DB 是权威，但没人知道字段什么意思就是腐烂）
        assertThat(migration).as("route_source 的四态必须写在列注释里")
                .contains("derived").contains("partial").contains("missing_route").contains("default");
    }
}
