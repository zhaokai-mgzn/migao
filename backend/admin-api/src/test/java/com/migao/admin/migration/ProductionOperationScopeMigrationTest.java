package com.migao.admin.migration;

// case_ids: PG-039

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 工序作用域迁移契约（V67，issue #4384 A1 判据 1）
 *
 * <p><b>病根（取证事实）</b>：真值源 {@code docs/curtain-production-rules.md} §8 明写
 * 「<b>外帘</b>是加工单打印行部位，<b>不是</b>路线键」，但 V54/V58 种子里
 * {@code 外帘打卷} / {@code 外帘装袋} / {@code 外帘发货} 的 {@code position='外帘'}
 * 却<b>逐条出现在每一条部位路线</b>里（含纱帘路线）⇒ 一樘「布 + 纱」时这 3 道各实例化
 * <b>2 次</b>（{@code unit='套'}、{@code qty=1}）⇒ 打卷/装袋/发货 <b>各 ¥1.0 双付</b>。
 * 用户裁定（2026-09-19）：<b>套级工序先按「每樘窗一次」实现</b>，打卷是否每帘一次<b>留成可配</b>。</p>
 *
 * <p>V67 只做<b>工序库侧（A1）</b>三件事，本类逐件钉死：</p>
 * <ol>
 *   <li><b>加列</b>：{@code production_operations.scope VARCHAR(16) NOT NULL DEFAULT 'position'}
 *       （幂等 {@code ADD COLUMN IF NOT EXISTS}）；</li>
 *   <li><b>列注释</b>：写明 {@code position} = 部位级 / {@code set} = 套级（<b>每樘窗一次</b>）语义与 issue 号；</li>
 *   <li><b>幂等回填</b>：{@code UPDATE ... SET scope='set' WHERE name IN ('外帘打卷','外帘装袋','外帘发货')}。</li>
 * </ol>
 *
 * <p><b>本类不交付什么（如实登记，避免把半截当完整交付）</b>：A2（{@code ProcessingOrderService}
 * 里套级工序按 {@code craftLineId} 组去重）<b>不在本包</b> —— 它依赖包 D（#4387 布行与纱行同组）
 * 先合入，且与 D 同文件。A2 未落地时「去重生效」无从谈起，硬写 = 空断言。</p>
 *
 * <p>写法沿用同目录 {@code ProductionSourceProvenanceMigrationTest}（直接断言迁移 SQL 文本 +
 * 解析器自证防空断言）。</p>
 */
@DisplayName("工序作用域迁移契约（V67：scope 列 + 列注释 + 冻结回填三道外帘工序 = 套级）")
class ProductionOperationScopeMigrationTest {

    private static final String MIGRATION =
            "backend/admin-api/src/main/resources/db/migration/"
                    + "V67__add_scope_to_production_operations.sql";
    private static final String SCHEMA = "docs/sql/schema.sql";
    private static final String SEED_V54 =
            "backend/admin-api/src/main/resources/db/migration/V54__seed_production_operations.sql";
    private static final String SEED_V56 =
            "backend/admin-api/src/main/resources/db/migration/V56__seed_special_option_operations.sql";

    /**
     * 冻结集合（issue #4384 用户裁定）：**恰好**这三道是套级（每樘窗一次）。
     * 集合写死 —— 漏标（少一道）或多标（把部位级工序也标成套级）都红。
     */
    private static final List<String> SET_SCOPE_OPERATIONS =
            List.of("外帘打卷", "外帘装袋", "外帘发货");

    /** 合法取值（闭词表，与写面 {@code ProductionOperationCommandService} 的校验同口径）。 */
    private static final Set<String> SCOPE_VOCABULARY = Set.of("position", "set");

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

    // ══════════════════════ 解析器（纯函数，便于注入式自证） ══════════════════════

    private static final Pattern SET_SCOPE_UPDATE = Pattern.compile(
            "UPDATE\\s+production_operations\\s+SET\\s+scope\\s*=\\s*'set'\\s+WHERE\\s+name\\s+IN\\s*\\(([^)]*)\\)",
            Pattern.CASE_INSENSITIVE | Pattern.DOTALL);

    /** 从 `UPDATE ... SET scope='set' WHERE name IN (...)` 里取出被标成套级的工序名（**冻结集合的机械代理**）。 */
    static List<String> setScopeOperationNames(String sql) {
        Matcher matcher = SET_SCOPE_UPDATE.matcher(sql);
        if (!matcher.find()) {
            return List.of();
        }
        List<String> names = new ArrayList<>();
        Matcher name = Pattern.compile("'([^']+)'").matcher(matcher.group(1));
        while (name.find()) {
            names.add(name.group(1));
        }
        return names;
    }

    /** 从种子迁移里取出 `('op-v5X-NN', 1, '工序名', ...)` 的工序名（按书写序）。 */
    static List<String> seedOperationNames(String sql) {
        List<String> names = new ArrayList<>();
        Matcher matcher = Pattern.compile("\\('op-v5[0-9]-\\d+'\\s*,\\s*\\d+\\s*,\\s*'([^']+)'").matcher(sql);
        while (matcher.find()) {
            names.add(matcher.group(1));
        }
        return names;
    }

    /** 迁移里所有被赋给 `scope` 的字面量（用于闭词表断言）。 */
    static Set<String> assignedScopeLiterals(String sql) {
        Set<String> values = new LinkedHashSet<>();
        Matcher matcher = Pattern.compile("scope\\s*=\\s*'([^']*)'", Pattern.CASE_INSENSITIVE).matcher(sql);
        while (matcher.find()) {
            values.add(matcher.group(1));
        }
        return values;
    }

    // ══════════════════════ ① 加列（幂等） ══════════════════════

    @Test
    @DisplayName("判据 1a：V67 给 production_operations 加 scope 列，NOT NULL DEFAULT 'position'，且幂等")
    void v67AddsScopeColumnIdempotently() throws Exception {
        String sql = read(MIGRATION);

        assertThat(sql)
                .as("必须是幂等加列（MigrationRunner 要求所有迁移可重复执行）")
                .contains("ALTER TABLE production_operations")
                .contains("ADD COLUMN IF NOT EXISTS scope VARCHAR(16) NOT NULL DEFAULT 'position'");
        assertThat(sql)
                .as("默认值必须是 position（部位级）—— 默认 set 会把全部存量工序误判成套级")
                .contains("DEFAULT 'position'");
    }

    @Test
    @DisplayName("判据 1b：列注释写明 position=部位级 / set=套级（每樘窗一次）+ issue 号")
    void v67DocumentsScopeSemantics() throws Exception {
        String sql = read(MIGRATION);

        assertThat(sql)
                .as("不写注释，枚举就只活在代码里，库/界面上看不出来（同 V62 source 列的口径）")
                .contains("COMMENT ON COLUMN production_operations.scope")
                .contains("position")
                .contains("set")
                .contains("每樘窗")
                .contains("4384");
    }

    // ══════════════════════ ② 冻结回填（恰好三道） ══════════════════════

    @Test
    @DisplayName("判据 1c：回填恰好把 外帘打卷/外帘装袋/外帘发货 标成 set（漏标/多标都红）")
    void v67MarksExactlyTheThreeOuterCurtainOperationsAsSet() throws Exception {
        String sql = read(MIGRATION);

        assertThat(setScopeOperationNames(sql))
                .as("冻结集合 = issue #4384 裁定的三道套级工序；漏一道 ⇒ 该道仍双付，多一道 ⇒ 部位级工序被误去重")
                .containsExactlyElementsOf(SET_SCOPE_OPERATIONS);
    }

    @Test
    @DisplayName("判据 1d：终态 = 三道 set，其余全部 position（由 V54 ∪ V56 真实种子行名推演）")
    void finalScopeStateIsSetForExactlyThreeAndPositionForTheRest() throws Exception {
        List<String> seeded = new ArrayList<>(seedOperationNames(read(SEED_V54)));
        seeded.addAll(seedOperationNames(read(SEED_V56)));

        assertThat(seeded)
                .as("应能从 V54 ∪ V56 解析出全部种子工序名（解析失败 ⇒ 本判据是空跑）")
                .hasSizeGreaterThan(30);
        assertThat(seeded)
                .as("回填点名的三道必须在种子里真实存在 —— 否则那条 UPDATE 是空操作（静默失效）")
                .containsAll(SET_SCOPE_OPERATIONS);

        List<String> setScoped = setScopeOperationNames(read(MIGRATION));
        // 终态推演：先 DEFAULT 'position' 兜住所有行，再按回填把三道改成 'set'
        List<String> asSet = seeded.stream().filter(setScoped::contains).distinct().toList();
        List<String> asPosition = seeded.stream().filter(n -> !setScoped.contains(n)).distinct().toList();

        assertThat(asSet)
                .as("终态里 scope='set' 的工序必须恰好是那三道")
                .containsExactlyInAnyOrderElementsOf(SET_SCOPE_OPERATIONS);
        assertThat(asPosition)
                .as("其余工序必须由 DEFAULT 'position' 兜住（不能靠漏标留在未定义态）")
                .isNotEmpty()
                .doesNotContainAnyElementsOf(SET_SCOPE_OPERATIONS);
        assertThat(asSet.size() + asPosition.size())
                .as("两道集合应恰好覆盖全部种子工序（无重复、无遗漏）")
                .isEqualTo((int) seeded.stream().distinct().count());
    }

    @Test
    @DisplayName("判据 1e：scope 只被赋过闭词表内的值（position / set）")
    void scopeVocabularyIsClosed() throws Exception {
        assertThat(assignedScopeLiterals(read(MIGRATION)))
                .as("迁移里赋给 scope 的字面量必须 ⊆ {position, set}（自创第三值 ⇒ 读面/写面口径分裂）")
                .isNotEmpty()
                .isSubsetOf(SCOPE_VOCABULARY);
    }

    // ══════════════════════ ③ bootstrap 终态镜像 ══════════════════════

    @Test
    @DisplayName("判据 1f：docs/sql/schema.sql 同步 V67 终态（列 + 注释 + 回填）")
    void schemaSqlMirrorsMigrationFinalState() throws Exception {
        String schema = read(SCHEMA);

        assertThat(schema)
                .as("bootstrap 路径**不跑迁移链** ⇒ 只写迁移 = 新建库无该列（同 #3270 形态）")
                .contains("ADD COLUMN IF NOT EXISTS scope VARCHAR(16) NOT NULL DEFAULT 'position'")
                .contains("COMMENT ON COLUMN production_operations.scope");
        assertThat(setScopeOperationNames(schema))
                .as("bootstrap 终态的回填必须与迁移逐字同集合（两份口径漂移 ⇒ 新建库与存量库不一致）")
                .containsExactlyElementsOf(SET_SCOPE_OPERATIONS);
    }

    @Test
    @DisplayName("判据 1g：种子 INSERT 不新增 scope 列（三源逐字比对守卫的列序不得被打乱）")
    void seedInsertKeepsItsColumnList() throws Exception {
        for (String source : new String[]{MIGRATION, SCHEMA}) {
            assertThat(read(source))
                    .as("%s：种子 INSERT 的列清单保持 11 列（scope 由 DEFAULT 兜住）—— "
                            + "往 INSERT 列清单里塞新列会让 tests/unit_ci_workflows/test_production_catalog_seed.py "
                            + "的 OP_COLUMNS 逐位解析错位（那是守卫口径，不为变绿而改）", source)
                    .doesNotContain("is_start_marker, sort_order, status, scope")
                    .doesNotContain("sort_order, status, scope)");
        }
    }

    // ══════════════════════ ④ 注入式自证（防「不会红的断言」） ══════════════════════

    @Test
    @DisplayName("自证：解析器能识别漂移（多一道 / 少一道 / 改名都红）")
    void parserDetectsInjectedDrift() {
        String good = "UPDATE production_operations SET scope = 'set' WHERE name IN "
                + "('外帘打卷', '外帘装袋', '外帘发货');";
        assertThat(setScopeOperationNames(good)).containsExactlyElementsOf(SET_SCOPE_OPERATIONS);

        String extra = good.replace("'外帘发货')", "'外帘发货', '韩褶-布')");
        assertThat(setScopeOperationNames(extra))
                .as("多标一道部位级工序 ⇒ 必须被识别（否则「恰好三道」是空断言）")
                .isNotEqualTo(SET_SCOPE_OPERATIONS)
                .contains("韩褶-布");

        String renamed = good.replace("'外帘装袋'", "'外帘包装'");
        assertThat(setScopeOperationNames(renamed))
                .as("改名 ⇒ 必须被识别（否则改名后回填静默落空也不红）")
                .doesNotContain("外帘装袋");

        assertThat(setScopeOperationNames("UPDATE production_operations SET scope = 'position' WHERE name = 'x';"))
                .as("没有 SET scope='set' 段 ⇒ 空集合（而不是误报）")
                .isEmpty();
    }

    @Test
    @DisplayName("自证：种子解析器与字面量解析器都能识别漂移")
    void seedAndLiteralParsersDetectInjectedDrift() {
        String seed = "INSERT INTO production_operations VALUES\n"
                + "  ('op-v54-24', 1, '外帘打卷', '后道', '外帘', '套', 1.0, FALSE, FALSE, 24, 'active'),\n"
                + "  ('op-v56-01', 1, '绑带-纱', '其他', NULL, '套', 0.5, FALSE, FALSE, 31, 'active')\n"
                + "ON CONFLICT (tenant_id, name) WHERE deleted = 0 DO NOTHING;";
        assertThat(seedOperationNames(seed)).containsExactly("外帘打卷", "绑带-纱");
        assertThat(seedOperationNames(seed.replace("'外帘打卷'", "'外帘卷帘'")))
                .as("种子改名 ⇒ 解析结果跟着变（否则终态推演读的是过期真值）")
                .containsExactly("外帘卷帘", "绑带-纱");

        assertThat(assignedScopeLiterals("SET scope = 'set' WHERE x; SET scope='bogus';"))
                .containsExactlyInAnyOrder("set", "bogus");
    }
}
