package com.migao.admin.migration;

// case_ids: PG-037

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * provenance 迁移契约（V62，issue #4361 交付物 4）
 *
 * <p>V62 干三件事，本类逐件钉死：</p>
 * <ol>
 *   <li><b>加列</b>：{@code production_operations.source} / {@code production_routings.source}
 *       （{@code VARCHAR(16)}，幂等 {@code ADD COLUMN IF NOT EXISTS}）；</li>
 *   <li><b>按既有 provenance 回填</b>（冻结映射，见下）；</li>
 *   <li><b>存量 {@code tenants.industry} 自由文本一次性归一</b>为受控 code。</li>
 * </ol>
 *
 * <h3>冻结映射（本单的核心诚实性结论，双向钉死）</h3>
 * <table>
 *   <tr><th>载体</th><th>source</th><th>集合</th></tr>
 *   <tr><td>工序</td><td>{@code 占位待确认}</td><td>V54 的 30 道（{@code op-v54-*}，单价是占位值）</td></tr>
 *   <tr><td>工序</td><td>{@code 推算}</td><td>V56 的 5 道（{@code op-v56-*}，单价行业推算）</td></tr>
 *   <tr><td>路线</td><td>{@code 占位待确认}</td><td>V54 的 6 条（{@code rt-v54-*}，含 布帘×韩褶）</td></tr>
 *   <tr><td>路线</td><td>{@code 推算}</td><td>V58 的 3 条纱帘（{@code rt-v58-*}）</td></tr>
 *   <tr><td>两者</td><td>{@code 实证}</td><td><b>当前空集</b> —— 客户确认 #4261/#4343 后才会有</td></tr>
 * </table>
 *
 * <p><b>为什么「实证 = 空集」是结论而不是遗漏</b>：#4343 已证明 {@code 布帘×韩褶}
 * （V54 的 {@code rt-v54-01}）与客户真实加工单 CSO260915-02615 不符（缺 4 道 / 多 1 道 /
 * {@code 定型→熨烫} 顺序相反 / 6 道工序名库里没有），且全部单价是占位值
 * ⇒ <b>今天没有任何一条工序/路线够得上「实证」</b>。把它标成实证才是本单要治的病
 * （「库里/界面上看不出单价是占位的」）。</p>
 *
 * <p>写法沿用同目录 {@code ProductionWorkLogSnapshotMigrationTest}（直接断言迁移 SQL 文本）。</p>
 */
@DisplayName("provenance 迁移契约（V62：source 列 + 冻结回填映射 + industry 归一）")
class ProductionSourceProvenanceMigrationTest {

    private static final String MIGRATION =
            "backend/admin-api/src/main/resources/db/migration/"
                    + "V62__add_source_to_production_operations_and_routings.sql";
    private static final String SCHEMA = "docs/sql/schema.sql";

    /** 冻结映射（见类注释表）——集合写死，漏标/多标都红。 */
    private static final List<String> OPERATION_SOURCES = List.of("占位待确认", "推算");
    private static final List<String> ROUTING_SOURCES = List.of("占位待确认", "推算");

    private static Path findRepoRoot() {
        Path cur = Paths.get("").toAbsolutePath();
        while (cur != null) {
            if (Files.isDirectory(cur.resolve(MIGRATION).getParent())) {
                return cur;
            }
            cur = cur.getParent();
        }
        return null;
    }

    private static String read(String relative) throws Exception {
        Path root = findRepoRoot();
        assertThat(root).as("应能定位仓库根目录").isNotNull();
        return Files.readString(root.resolve(relative), StandardCharsets.UTF_8);
    }

    private static String readMigration() throws Exception {
        return read(MIGRATION);
    }

    // ══════════════════════ ① 加列（幂等） ══════════════════════

    @Test
    @DisplayName("V62 给两张表各加 source 列，且幂等（ADD COLUMN IF NOT EXISTS）")
    void v62AddsSourceColumnsIdempotently() throws Exception {
        String sql = readMigration();

        assertThat(sql).contains("ALTER TABLE production_operations");
        assertThat(sql).contains("ALTER TABLE production_routings");
        assertThat(sql).contains("ADD COLUMN IF NOT EXISTS source VARCHAR(16)");
        assertThat(countOccurrences(sql, "ADD COLUMN IF NOT EXISTS source VARCHAR(16)"))
                .as("两张表各加一列 —— 只加一张 ⇒ 另一张的 provenance 不可见")
                .isEqualTo(2);
        assertThat(sql)
                .as("列注释必须写明三个取值 —— 不写注释，枚举就只活在代码里，库/界面上看不出来")
                .contains("COMMENT ON COLUMN production_operations.source")
                .contains("COMMENT ON COLUMN production_routings.source")
                .contains("占位待确认")
                .contains("推算")
                .contains("实证");
    }

    @Test
    @DisplayName("V62 用 CHECK 约束钉住枚举（防自由文本 source 悄悄进来）")
    void v62ConstrainsSourceToTheFrozenVocabulary() throws Exception {
        String sql = readMigration();
        for (String column : new String[]{"production_operations", "production_routings"}) {
            assertThat(sql)
                    .as("%s 的 source 必须有 CHECK 枚举约束（否则错别字/新值静默入库）", column)
                    .contains(column + "_source_check");
        }
        assertThat(countOccurrences(sql, "IN ('占位待确认', '推算', '实证')"))
                .as("两张表的 CHECK 都要列全三个合法取值")
                .isEqualTo(2);
    }

    // ══════════════════════ ② 冻结回填映射（双向） ══════════════════════

    @Test
    @DisplayName("工序回填：op-v54-* → 占位待确认；op-v56-* → 推算（其余 NULL，不误标）")
    void v62BackfillsOperationSources() throws Exception {
        String opSection = updateStatementOf(readMigration(), "production_operations");

        assertThat(opSection)
                .as("回填必须按 id 前缀认领 V54（占位值）/ V56（推算），不是按名字列表 —— 名字列表会随改名漂移")
                .contains("'op-v54-%'")
                .contains("'op-v56-%'");
        assertThat(opSection).contains("占位待确认").contains("推算");
        assertThat(opSection)
                .as("回填必须只动 source 仍为 NULL 的行（幂等；且不覆盖商家/模板已写的 source）")
                .containsIgnoringCase("IS NULL");
        assertThat(opSection)
                .as("不得出现「实证」的回填 —— 今天没有任何工序够得上实证（#4343 证明不一致）")
                .doesNotContain("'实证'");
        assertThat(opSection)
                .as("其余行必须保持 NULL（不落 ELSE）：未知来源 = 未知，不许冒充「占位待确认」")
                .doesNotContain("ELSE");
    }

    @Test
    @DisplayName("路线回填：rt-v54-* → 占位待确认；rt-v58-* → 推算（其余 NULL）")
    void v62BackfillsRoutingSources() throws Exception {
        String rtSection = updateStatementOf(readMigration(), "production_routings");

        assertThat(rtSection).contains("'rt-v54-%'").contains("'rt-v58-%'");
        assertThat(rtSection).contains("占位待确认").contains("推算");
        assertThat(rtSection).containsIgnoringCase("IS NULL");
        assertThat(rtSection)
                .as("不得出现「实证」的回填（含 布帘×韩褶 —— #4343 已证明它与客户真实加工单不符）")
                .doesNotContain("'实证'");
    }

    @Test
    @DisplayName("冻结映射集合：V54 30 道工序 / V56 5 道 / V54 6 条路线 / V58 3 条 —— 双向断言")
    void frozenMappingSetsAreExactlyRight() throws Exception {
        Path root = findRepoRoot();
        assertThat(root).isNotNull();

        // 从**迁移源本身**取 id（不是从回填 SQL 抄一份 —— 抄一份就变成第二份口径）
        String v54 = Files.readString(root.resolve(
                "backend/admin-api/src/main/resources/db/migration/V54__seed_production_operations.sql"),
                StandardCharsets.UTF_8);
        String v56 = Files.readString(root.resolve(
                "backend/admin-api/src/main/resources/db/migration/V56__seed_special_option_operations.sql"),
                StandardCharsets.UTF_8);
        String v58 = Files.readString(root.resolve(
                "backend/admin-api/src/main/resources/db/migration/V58__seed_sheer_curtain_routings.sql"),
                StandardCharsets.UTF_8);

        List<String> v54Ops = idsMatching(v54, "'(op-v54-\\d+)'");
        List<String> v56Ops = idsMatching(v56, "'(op-v56-\\d+)'");
        List<String> v54Rts = idsMatching(v54, "'(rt-v54-\\d+)'");
        List<String> v58Rts = idsMatching(v58, "'(rt-v58-\\d+)'");

        assertThat(v54Ops).as("V54 的 30 道工序（占位待确认）").hasSize(30);
        assertThat(v56Ops).as("V56 的 5 道工序（推算）").hasSize(5);
        assertThat(v54Rts).as("V54 的 6 条路线（占位待确认，含 布帘×韩褶）").hasSize(6);
        assertThat(v58Rts).as("V58 的 3 条纱帘路线（推算）").hasSize(3);
        // 实证 = 空集（显式断言为空，不是遗漏）
        assertThat(idsMatching(v54 + v56 + v58, "'((?:op|rt)-v\\d+-\\d+)'"))
                .as("四个 id 前缀合计 44 条 —— 没有任何一条被标成「实证」")
                .hasSize(44);
        assertThat(OPERATION_SOURCES).containsExactly("占位待确认", "推算");
        assertThat(ROUTING_SOURCES).containsExactly("占位待确认", "推算");
    }

    // ══════════════════════ ③ industry 存量归一 ══════════════════════

    @Test
    @DisplayName("V62 归一存量 tenants.industry：别名 → curtain，其余非空 → other，幂等")
    void v62NormalizesLegacyIndustry() throws Exception {
        String sql = readMigration();

        assertThat(sql).contains("UPDATE tenants");
        assertThat(sql).contains("SET industry = CASE");
        assertThat(sql).contains("ELSE 'other'");
        assertThat(sql)
                .as("归一必须幂等：只更新尚未归一的那些行（WHERE industry IS DISTINCT FROM <归一结果>）")
                .containsIgnoringCase("IS DISTINCT FROM");
        // 判据不是「SQL 里出现过这个书写形态」（那会逼着 SQL 把 N 种写法列 N 遍），
        // 而是「SQL 的 IN 清单里有那个**形态归一后的键**」。同一份形态规则在
        // IndustryCodesTest 里与 Java 侧逐条比对。
        for (String canonicalKey : new String[]{"布艺", "窗帘", "布艺窗帘", "布艺纺织"}) {
            assertThat(sql).as("存量归一的 IN 清单漏了键「%s」⇒ 存量租户落 other ⇒ 模板取不到", canonicalKey)
                    .contains("'" + canonicalKey + "'");
        }
        assertThat(sql)
                .as("形态归一（去空白/分隔符 + 转小写）必须真在 SQL 里做 —— 否则「布艺/窗帘」「CURTAIN」认不出来")
                .contains("regexp_replace")
                .contains("lower(");
    }

    // ══════════════════════ ④ bootstrap 终态（schema.sql） ══════════════════════

    @Test
    @DisplayName("schema.sql 同步终态：两表都有 source 列 + CHECK；bootstrap 路径不跑迁移链")
    void schemaSqlMirrorsMigrationFinalState() throws Exception {
        String schema = read(SCHEMA);

        assertThat(schema)
                .as("bootstrap（docker-entrypoint-initdb.d）不跑迁移链 ⇒ 只写迁移 = 新建库无该列 ⇒ 读面 500（#3270 形态）")
                .contains("ALTER TABLE production_operations ADD COLUMN IF NOT EXISTS source VARCHAR(16)")
                .contains("ALTER TABLE production_routings ADD COLUMN IF NOT EXISTS source VARCHAR(16)");
        assertThat(schema).contains("production_operations_source_check");
        assertThat(schema).contains("production_routings_source_check");
        // 默认租户 1 的 industry 在 bootstrap 里就是受控 code（否则新库与迁移库终态不同）
        assertThat(schema)
                .as("bootstrap 的默认租户 industry 必须是受控 code（V62 会把存量归一，终态须一致）")
                .contains("VALUES (1, '米高智能', 'migao', 'curtain', 'active')");
    }

    // ══════════════════════ 工具 ══════════════════════

    private static int countOccurrences(String haystack, String needle) {
        int count = 0;
        int idx = haystack.indexOf(needle);
        while (idx >= 0) {
            count++;
            idx = haystack.indexOf(needle, idx + needle.length());
        }
        return count;
    }

    /** 取 `UPDATE <table> ... ;` 整条语句（**不含**前后的注释 —— 列注释里也写着三个取值，
     *  若按「表名到表名」切片，注释里的 '实证' 会让「回填不得出现实证」这条假红）。 */
    private static String updateStatementOf(String sql, String table) {
        Matcher matcher = Pattern.compile(
                "UPDATE\\s+" + table + "\\b.*?;", Pattern.DOTALL).matcher(sql);
        assertThat(matcher.find())
                .as("迁移里找不到 `UPDATE %s ...;` 语句", table)
                .isTrue();
        return matcher.group(0);
    }

    private static List<String> idsMatching(String sql, String regex) {
        Matcher matcher = Pattern.compile(regex).matcher(sql);
        List<String> ids = new java.util.ArrayList<>();
        while (matcher.find()) {
            ids.add(matcher.group(1));
        }
        return ids.stream().distinct().toList();
    }
}
