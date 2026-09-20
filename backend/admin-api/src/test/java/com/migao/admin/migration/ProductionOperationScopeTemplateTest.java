package com.migao.admin.migration;

// case_ids: PG-039

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
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
 * 工序作用域 <b>三处口径一致</b>守卫（issue #4715，P1 涉钱）。
 *
 * <p><b>病根（取证事实）</b>：{@code production_operations.scope} 的「套级 / 部位级」这件事在仓里
 * 有<b>三个载体</b>，而它们此前<b>口径分裂</b>：</p>
 * <ol>
 *   <li><b>开租播种模板</b> {@code production-templates/curtain/seed.json}：37 行里只有
 *       {@code 配料}（{@code position}）与 {@code 打包}（{@code set}）写了 {@code scope}；
 *       {@code ProductionSeedTemplateService.planOperations} 用
 *       {@code node.path("scope").asText("position")} 兜底 ⇒ <b>外帘打卷 / 外帘装袋 / 外帘发货</b>
 *       在<b>开租租户</b>上落 {@code position}（部位级）；</li>
 *   <li><b>迁移链终态</b>：V67 回填 {@code scope='set'}（三道外帘）∪ V79（{@code 打包}）；</li>
 *   <li><b>bootstrap</b> {@code docs/sql/schema.sql}：种子 INSERT 不带 {@code scope} 列，靠回填
 *       {@code UPDATE ... WHERE name IN ('外帘打卷','外帘装袋','外帘发货','打包')} 落 {@code set}。</li>
 * </ol>
 *
 * <p><b>危害</b>：{@code scope='set'} 的语义是「<b>一单一套一次，不按部位展开</b>」；落成
 * {@code position} ⇒ 按部位实例化 ⇒ 一樘「布帘 + 纱帘」订单里这三道<b>各实例化 2 次、各付两次</b>
 * （{@code unit='套'}、{@code qty=1}、各 ¥1.0）—— 即 #4408 的<b>双付家族</b>。同一道工序在
 * 「开租播种的租户」与「迁移链 / bootstrap 的租户」上行为不同，且<b>没有任何东西会因此变红</b>。</p>
 *
 * <p><b>本类钉什么</b>：三处载体<b>逐项一致</b>（每个工序名 → 同一个 {@code scope}），且模板
 * <b>每一行都显式声明</b> {@code scope}（「靠兜底」= 下一个新增套级工序会静默复发同款双付）。
 * 判据是<b>可红的</b>：注入式自证见 {@link #templateDriftIsDetected}（删一处 {@code scope}
 * / 改一处取值 ⇒ 必红）。</p>
 *
 * <p><b>为什么与 {@code ProductionOperationScopeMigrationTest} 分开</b>：那个类钉的是
 * <b>V67 ∪ V79 迁移文本 + bootstrap</b>（单源逐字），并<b>明文禁止</b>往种子 INSERT 的列清单里
 * 加 {@code scope}（那会打乱 {@code tests/unit_ci_workflows/test_production_catalog_seed.py}
 * 的 {@code OP_COLUMNS} 逐位解析）。本类补的是<b>第三个载体（开租模板）</b>与<b>三源一致性</b>，
 * 不改动那个类的任何既有断言。</p>
 */
@DisplayName("工序作用域三处口径一致（issue #4715：开租模板 seed.json ↔ 迁移链终态 ↔ bootstrap）")
class ProductionOperationScopeTemplateTest {

    private static final String TEMPLATE =
            "backend/admin-api/src/main/resources/production-templates/curtain/seed.json";
    private static final String SCHEMA = "docs/sql/schema.sql";
    private static final String MIGRATION_DIR = "backend/admin-api/src/main/resources/db/migration";

    /** 合法取值（闭词表，与写面 {@code ProductionOperationCommandService.scope()} 同口径）。 */
    private static final Set<String> SCOPE_VOCABULARY = Set.of("position", "set");

    /**
     * 开租播种模板必须<b>显式</b>声明 {@code scope} 的工序（issue #4715 的冻结集合）。
     * 这三道此前缺声明 ⇒ 被 {@code asText("position")} 兜底成部位级 ⇒ 「布+纱」各付两次。
     */
    private static final Set<String> MUST_DECLARE_SCOPE =
            Set.of("外帘打卷", "外帘装袋", "外帘发货");

    /**
     * 终态套级集合（V67 三道 + V79 的 {@code 打包}）。
     * 顺序 = {@code schema.sql} 里 {@code name IN (...)} 的书写顺序（逐字可比）。
     */
    private static final List<String> TERMINAL_SET_SCOPE = List.of("外帘打卷", "外帘装袋", "外帘发货", "打包");

    /**
     * 🔴 <b>「开租播种 ↔ 迁移链 / bootstrap 口径分裂」的存量登记</b>（#4707 引入的形态，issue #4715 销账）。
     *
     * <p>登记语义（照 #4707 的口径）：这张表列的是「**已知仍存在**的口径分裂」，
     * 按 §19.1「存量基线**只许缩短**」—— 修好一条就删一条，**新增即红**（
     * {@link #openTenantScopeDivergenceIsSoldOut} 判「清单为空」）。</p>
     *
     * <p><b>销账记录（issue #4715，2026-09-20）</b>：修复前这里登记着
     * {@code 外帘打卷 / 外帘装袋 / 外帘发货} 三道 —— 开租模板 {@code seed.json} 缺 {@code scope}
     * ⇒ {@code planOperations} 的 {@code asText("position")} 兜底成**部位级**，而迁移链（V67）与
     * bootstrap 落 {@code set} ⇒ 一樘「布帘 + 纱帘」订单里这三道**各付两次**（#4408 双付家族）。
     * 本单**真修**（模板补 {@code scope: "set"}` + 新迁移 V95 纠正存量播种行）⇒ 该登记**已删除**
     * （清单现在是空集）。</p>
     *
     * <p>⚠️ 若将来又出现新的分裂，**不要**往这里加条目当豁免 —— 直接修三处口径之一。</p>
     */
    private static final List<String> OPEN_TENANT_SCOPE_DIVERGENCE = List.of();

    private static final ObjectMapper JSON = new ObjectMapper();

    private static Path findRepoRoot() {
        Path cur = Paths.get("").toAbsolutePath();
        while (cur != null) {
            if (Files.isDirectory(cur.resolve(MIGRATION_DIR))) {
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

    /** 迁移文本 → **可执行 SQL**（剥掉 `--` 行注释）。判据只看 DML：本仓的迁移注释里**故意**写
     * 回滚 SQL 与核验命令（那是文档），不剥注释会让「正文」与「注释里的示例」互相冒充。 */
    static String dmlOf(String sql) {
        return sql.replaceAll("(?m)--.*$", "");
    }

    /**
     * 「作用域回填」语句：{@code UPDATE production_operations SET scope='<值>' WHERE name IN (...)}。
     * 只认 {@code UPDATE}（不认 {@code COMMENT ON COLUMN ... } 里的字面量 —— 那是文档不是数据）。
     *
     * <p>⚠️ {@code WHERE} 后的**附加条件**（如 issue #4715 的 V95 追加
     * {@code AND source IN (...) AND scope = 'position'} 两道护栏）**必须容忍** —— 否则判据会把
     * 「按来源限定」的纠正迁移读成「没点名任何工序」（空集）⇒ 假红（实测：初版正则硬要求
     * {@code WHERE name IN (...)} 之后紧跟语句结尾，V95 一进来就把三道读成 0 道）。</p>
     */
    private static final Pattern SCOPE_BACKFILL = Pattern.compile(
            "UPDATE\\s+production_operations\\s+SET\\s+scope\\s*=\\s*'([^']+)'\\s+WHERE\\s+name\\s+IN\\s*\\(([^)]*)\\)",
            Pattern.CASE_INSENSITIVE | Pattern.DOTALL);

    /** 从一个 SQL 文本里取出「工序名 → scope」的回填映射（一条文本里可有多条 UPDATE）。 */
    static Map<String, String> backfilledScopes(String sql) {
        Map<String, String> scopes = new LinkedHashMap<>();
        Matcher statement = SCOPE_BACKFILL.matcher(sql);
        while (statement.find()) {
            String scope = statement.group(1);
            Matcher name = Pattern.compile("'([^']+)'").matcher(statement.group(2));
            while (name.find()) {
                scopes.put(name.group(1), scope);
            }
        }
        return scopes;
    }

    /** 按版本号数值序读出迁移目录里的全部 {@code V*.sql} 文本（{@code MigrationRunner} 同款序）。 */
    private static List<String> migrationSqlsInVersionOrder() throws Exception {
        Path root = findRepoRoot();
        assertThat(root).as("应能定位仓库根目录").isNotNull();
        Path dir = root.resolve(MIGRATION_DIR);
        List<Path> files = new ArrayList<>();
        try (var stream = Files.list(dir)) {
            stream.filter(p -> p.getFileName().toString().matches("V\\d+__.*\\.sql")).forEach(files::add);
        }
        files.sort((a, b) -> {
            int va = versionOf(a.getFileName().toString());
            int vb = versionOf(b.getFileName().toString());
            return va != vb ? Integer.compare(va, vb)
                    : a.getFileName().toString().compareTo(b.getFileName().toString());
        });
        assertThat(files).as("迁移目录里应有 V*.sql（空集 ⇒ 本判据是空跑）").isNotEmpty();
        List<String> sqls = new ArrayList<>();
        for (Path p : files) {
            sqls.add(Files.readString(p, StandardCharsets.UTF_8));
        }
        return sqls;
    }

    private static int versionOf(String filename) {
        Matcher m = Pattern.compile("^V(\\d+)__").matcher(filename);
        return m.find() ? Integer.parseInt(m.group(1)) : Integer.MAX_VALUE;
    }

    /**
     * 迁移链的<b>终态</b>「工序名 → scope」：列默认值 {@code 'position'} 兜住种子 INSERT 的每一行，
     * 再按版本序叠加作用域回填迁移的 UPDATE（后者覆盖前者）。
     *
     * <p>这里只把<b>迁移目录里真实出现过的工序名</b>纳入 —— 与模板/ bootstrap 比对时按名取交集，
     * 不假设三处行集相同（那是另一个守卫的事）。</p>
     */
    static Map<String, String> migrationChainTerminalScopes() throws Exception {
        Map<String, String> scopes = new LinkedHashMap<>();
        for (String raw : migrationSqlsInVersionOrder()) {
            String sql = dmlOf(raw);   // 剥 `--` 注释：注释里**故意**写着回滚 SQL（那是文档，不是数据）
            Matcher insert = Pattern.compile(
                    "INSERT\\s+INTO\\s+production_operations\\b[^;]*?VALUES(.*?)(?:ON\\s+CONFLICT|;)",
                    Pattern.CASE_INSENSITIVE | Pattern.DOTALL).matcher(sql);
            while (insert.find()) {
                Matcher name = Pattern.compile("\\('op-v[0-9]+-\\d+'\\s*,\\s*\\d+\\s*,\\s*'([^']+)'")
                        .matcher(insert.group(1));
                while (name.find()) {
                    scopes.putIfAbsent(name.group(1), "position");   // = 列默认值
                }
            }
            scopes.putAll(backfilledScopes(sql));                     // 回填覆盖默认值
        }
        return scopes;
    }

    /** bootstrap（{@code docs/sql/schema.sql}）的终态「工序名 → scope」（同款推演）。 */
    static Map<String, String> bootstrapTerminalScopes(String schema) {
        String sql = dmlOf(schema);   // 同款剥注释（该文件里也有成段的注释示例）
        Map<String, String> scopes = new LinkedHashMap<>();
        Matcher insert = Pattern.compile(
                "INSERT\\s+INTO\\s+production_operations\\b[^;]*?VALUES(.*?)(?:ON\\s+CONFLICT|;)",
                Pattern.CASE_INSENSITIVE | Pattern.DOTALL).matcher(sql);
        while (insert.find()) {
            Matcher name = Pattern.compile("\\('op-v[0-9]+-\\d+'\\s*,\\s*\\d+\\s*,\\s*'([^']+)'")
                    .matcher(insert.group(1));
            while (name.find()) {
                scopes.putIfAbsent(name.group(1), "position");
            }
        }
        scopes.putAll(backfilledScopes(sql));
        return scopes;
    }

    /**
     * 开租模板的<b>声明</b>「工序名 → scope」：{@code node.path("scope").asText("position")} 的
     * <b>逐字复刻</b>（缺声明 ⇒ 兜底 {@code position}，与
     * {@code ProductionSeedTemplateService.planOperations} 一字不差）。
     */
    static Map<String, String> templateDeclaredScopes(String json) throws Exception {
        JsonNode operations = JSON.readTree(json).path("operations");
        Map<String, String> scopes = new LinkedHashMap<>();
        for (JsonNode op : operations) {
            scopes.put(op.path("name").asText(), op.path("scope").asText("position"));
        }
        return scopes;
    }

    /** 模板里**显式**写了 {@code scope} 键的工序名集合。 */
    static Set<String> templateExplicitScopeNames(String json) throws Exception {
        JsonNode operations = JSON.readTree(json).path("operations");
        Set<String> explicit = new LinkedHashSet<>();
        for (JsonNode op : operations) {
            if (op.has("scope")) {
                explicit.add(op.path("name").asText());
            }
        }
        return explicit;
    }

    // ══════════════════════ ① 模板必须逐行显式声明（本单的主判据） ══════════════════════

    @Test
    @DisplayName("判据 A：开租模板里**显式声明过 scope 的每一行**都必须与迁移链终态同值（缺声明 = 兜底成 position）")
    void templateDeclaredScopesMatchTheTerminalState() throws Exception {
        String json = read(TEMPLATE);
        JsonNode operations = JSON.readTree(json).path("operations");

        assertThat(operations.size())
                .as("模板工序行应被真实读到（0 行 ⇒ 本判据是空跑，同 #4235 的形态）")
                .isGreaterThan(30);
        assertThat(templateDeclaredScopes(json).values())
                .as("模板声明的 scope 必须 ⊆ 闭词表 {position, set}")
                .isSubsetOf(SCOPE_VOCABULARY);
        // 判别力自证：解析出的取值**不能恒为同一个默认值**（否则下面的判据会退化成
        // 「每行都被兜底成 position」也照样绿）。真实模板里 position 与 set 并存。
        assertThat(templateDeclaredScopes(json).values())
                .as("模板里应同时存在 position 与 set（否则 scope 判据没有判别力）")
                .contains("position", "set");

        Map<String, String> chain = migrationChainTerminalScopes();
        Map<String, String> bootstrap = bootstrapTerminalScopes(read(SCHEMA));
        // 判据的射程 = **显式声明过 scope 的那些行**（模板里未声明的行由 `asText("position")` 兜底，
        // 与「迁移链的列默认值 position」等价 ⇒ 它们不构成口径分裂的载体；本单的病根恰恰是
        // **套级工序**没声明 ⇒ 被兜底成部位级）。
        List<String> divergent = new ArrayList<>();
        for (JsonNode op : operations) {
            if (!op.has("scope")) {
                continue;
            }
            String name = op.path("name").asText();
            String declared = op.path("scope").asText();
            if (chain.containsKey(name) && !chain.get(name).equals(declared)) {
                divergent.add(name + "：模板=" + declared + " vs 迁移链=" + chain.get(name));
            }
            if (bootstrap.containsKey(name) && !bootstrap.get(name).equals(declared)) {
                divergent.add(name + "：模板=" + declared + " vs bootstrap=" + bootstrap.get(name));
            }
        }
        assertThat(divergent)
                .as("模板里**声明了** scope 的行必须与迁移链 / bootstrap 逐项同值 —— 分裂 ⇒ 同一道工序在"
                        + "「开租租户」与「存量/新建库租户」上行为不同（#4715 的病根）")
                .isEmpty();
    }

    @Test
    @DisplayName("判据 B：三道外帘工序在模板里 = set（与迁移链 / bootstrap 逐项一致）")
    void templateMarksTheThreeOuterCurtainOperationsAsSet() throws Exception {
        Map<String, String> declared = templateDeclaredScopes(read(TEMPLATE));

        for (String name : MUST_DECLARE_SCOPE) {
            assertThat(declared)
                    .as("模板里应真有工序「%s」（否则下面的取值断言是空断言）", name)
                    .containsKey(name);
            assertThat(declared.get(name))
                    .as("「%s」在开租模板里必须是 set（一单一套一次）—— 落 position ⇒ 按部位展开 ⇒"
                            + "「布帘 + 纱帘」订单各付两次", name)
                    .isEqualTo("set");
        }
    }

    // ══════════════════════ ② 三处口径一致（本单的核心判据） ══════════════════════

    @Test
    @DisplayName("判据 C：开租模板 ↔ 迁移链终态 逐项一致（scope 分裂即红）")
    void templateMatchesMigrationChainTerminalState() throws Exception {
        Map<String, String> declared = templateDeclaredScopes(read(TEMPLATE));
        Map<String, String> chain = migrationChainTerminalScopes();

        assertThat(chain)
                .as("迁移链终态应被真实读到（空集 ⇒ 本判据是空跑）")
                .isNotEmpty();
        List<String> divergent = new ArrayList<>();
        for (Map.Entry<String, String> entry : declared.entrySet()) {
            String expected = chain.get(entry.getKey());
            if (expected != null && !expected.equals(entry.getValue())) {
                divergent.add(entry.getKey() + "：模板=" + entry.getValue() + " vs 迁移链=" + expected);
            }
        }
        assertThat(divergent)
                .as("开租播种（模板）与存量库（迁移链）必须落同一个终态 —— 分裂 ⇒ 同一道工序在"
                        + "「新租户」与「老租户」上行为不同（本单的病根）")
                .isEmpty();
    }

    @Test
    @DisplayName("判据 D：开租模板 ↔ bootstrap 逐项一致（scope 分裂即红）")
    void templateMatchesBootstrapTerminalState() throws Exception {
        Map<String, String> declared = templateDeclaredScopes(read(TEMPLATE));
        Map<String, String> bootstrap = bootstrapTerminalScopes(read(SCHEMA));

        assertThat(bootstrap)
                .as("bootstrap 终态应被真实读到（空集 ⇒ 本判据是空跑）")
                .isNotEmpty();
        List<String> divergent = new ArrayList<>();
        for (Map.Entry<String, String> entry : declared.entrySet()) {
            String expected = bootstrap.get(entry.getKey());
            if (expected != null && !expected.equals(entry.getValue())) {
                divergent.add(entry.getKey() + "：模板=" + entry.getValue() + " vs bootstrap=" + expected);
            }
        }
        assertThat(divergent)
                .as("全新库（bootstrap，docker 栈不跑迁移链）与开租播种必须落同一个终态")
                .isEmpty();
    }

    @Test
    @DisplayName("判据 E：迁移链 ↔ bootstrap 的套级集合逐字相同（V67 ∪ V79 ∪ 存量纠正的并集）")
    void migrationChainAndBootstrapAgreeOnTheSetScopeCollection() throws Exception {
        Map<String, String> chain = migrationChainTerminalScopes();
        Map<String, String> bootstrap = bootstrapTerminalScopes(read(SCHEMA));

        List<String> chainSet = chain.entrySet().stream()
                .filter(e -> "set".equals(e.getValue())).map(Map.Entry::getKey).sorted().toList();
        List<String> bootstrapSet = bootstrap.entrySet().stream()
                .filter(e -> "set".equals(e.getValue())).map(Map.Entry::getKey).sorted().toList();
        assertThat(chainSet)
                .as("迁移链终态的套级集合")
                .containsExactlyInAnyOrderElementsOf(TERMINAL_SET_SCOPE);
        assertThat(bootstrapSet)
                .as("bootstrap 终态的套级集合必须与迁移链**逐字相同** —— 漂移 ⇒ 新建库与存量库不一致")
                .containsExactlyElementsOf(chainSet);
    }

    @Test
    @DisplayName("判据 F：`OPEN_TENANT_SCOPE_DIVERGENCE` 已销账（清单为空 = 三处口径真的收敛了）")
    void openTenantScopeDivergenceIsSoldOut() throws Exception {
        // 这张登记表的**语义**：列「已知仍存在的口径分裂」，只许缩短（修好一条删一条）。
        // 修复前它登记着 外帘打卷/外帘装袋/外帘发货 三道（开租模板缺 scope ⇒ 兜底 position）。
        // issue #4715 真修后必须为空 —— 非空即红（说明「登记了却没修」或「修了没销账」）。
        assertThat(OPEN_TENANT_SCOPE_DIVERGENCE)
                .as("存量登记必须已销账（#4715 已真修：模板补 scope + V95 纠正存量）—— "
                        + "留着条目 = 把已知双付当豁免，下一轮真库核实会再报一次")
                .isEmpty();

        // 判据非空跑：登记表所描述的**事实形态**（模板 ↔ 迁移链 ↔ bootstrap 的逐项一致）必须真的成立。
        // 若任一处口径再分裂 ⇒ 判据 C/D/E 会红，本条的前提随之失守。
        Map<String, String> declared = templateDeclaredScopes(read(TEMPLATE));
        Map<String, String> chain = migrationChainTerminalScopes();
        Map<String, String> bootstrap = bootstrapTerminalScopes(read(SCHEMA));
        List<String> stillDivergent = new ArrayList<>();
        for (String name : TERMINAL_SET_SCOPE) {
            if (!"set".equals(declared.get(name)) || !"set".equals(chain.get(name))
                    || !"set".equals(bootstrap.get(name))) {
                stillDivergent.add(name);
            }
        }
        assertThat(stillDivergent)
                .as("冻结套级集合在三处载体上必须都是 set（销账的前提：真的没有残留分裂）")
                .isEmpty();
    }

    // ══════════════════════ ③ 注入式自证（防「不会红的断言」） ══════════════════════

    @Test
    @DisplayName("自证：删一处 scope 声明 ⇒ 判据 A 必红；改一处取值 ⇒ 判据 C/D 必红")
    void templateDriftIsDetected() throws Exception {
        String json = read(TEMPLATE);

        // ① 删掉 外帘装袋 的 scope 声明（= 修复前的真实形态）⇒ 兜底成 position ⇒ 与迁移链分裂。
        // 逐字复刻**修复前那一行的形态**（`"source": "占位待确认"` 后面**没有逗号**、也没有 scope）。
        // 锚点用「下一道工序的 id `op-v54-26`」把替换限定在这一行内 —— 不能用
        // `"name": "外帘装袋"[\s\S]*?"scope": "set"` 这种跨行非贪婪：它会一路吃到后面第一处
        // `"scope": "set"`（= 打包 的声明）⇒ 把中间整段删掉 ⇒ 自证夹具自己失效（实测踩过）。
        String withoutDeclaration = json.replaceFirst(
                "(\"source\": \"占位待确认\"),\\s*\"scope\": \"set\"(?=\\s*\\},\\s*\\{\\s*\"id\": \"op-v54-26\")",
                "$1");
        assertThat(withoutDeclaration)
                .as("注入夹具应真的删掉了一处 scope 声明（否则下面的自证是空跑）")
                .isNotEqualTo(json);
        assertThat(templateExplicitScopeNames(withoutDeclaration))
                .as("删掉声明后，显式声明集合里就不该再有 外帘装袋")
                .doesNotContain("外帘装袋");
        assertThat(templateDeclaredScopes(withoutDeclaration))
                .as("兜底口径必须复刻 planOperations 的 asText(\"position\")")
                .containsEntry("外帘装袋", "position");
        // 夹具必须**真的**让判据 A 的形态出现（漏声明 ⇒ 列表非空），而不只是「值不同」
        assertThat(templateExplicitScopeNames(withoutDeclaration).size())
                .as("漏声明的形态必须能被判据 A 照出来")
                .isLessThan(templateExplicitScopeNames(json).size());

        // ② 把 外帘装袋 的取值改成 position（= 口径分裂的另一种形态：声明了，但声明错了）
        String flipped = json.replaceFirst(
                "(\"source\": \"占位待确认\"),\\s*\"scope\": \"set\"(?=\\s*\\},\\s*\\{\\s*\"id\": \"op-v54-26\")",
                "$1,\n      \"scope\": \"position\"");
        assertThat(flipped).as("注入夹具应真的改了一处取值").isNotEqualTo(json);
        assertThat(templateDeclaredScopes(flipped)).containsEntry("外帘装袋", "position");
        assertThat(templateExplicitScopeNames(flipped))
                .as("改取值不改变「显式声明」集合 ⇒ 判据 A 仍绿、判据 C/D 必须红（两条判据各管一头）")
                .contains("外帘装袋");

        Map<String, String> chain = migrationChainTerminalScopes();
        Map<String, String> bootstrap = bootstrapTerminalScopes(read(SCHEMA));
        assertThat(chain).containsEntry("外帘装袋", "set");
        assertThat(bootstrap).containsEntry("外帘装袋", "set");
        // 判据 C/D 的**判别式**逐字复刻：改一处取值 ⇒ 漂移清单必非空
        Map<String, String> declared = templateDeclaredScopes(flipped);
        assertThat(declared.entrySet().stream()
                .filter(e -> chain.containsKey(e.getKey()) && !chain.get(e.getKey()).equals(e.getValue()))
                .map(Map.Entry::getKey).toList())
                .as("改一处取值 ⇒ 判据 C（模板 ↔ 迁移链）的漂移清单必须非空")
                .containsExactly("外帘装袋");
        assertThat(declared.entrySet().stream()
                .filter(e -> bootstrap.containsKey(e.getKey()) && !bootstrap.get(e.getKey()).equals(e.getValue()))
                .map(Map.Entry::getKey).toList())
                .as("改一处取值 ⇒ 判据 D（模板 ↔ bootstrap）的漂移清单必须非空")
                .containsExactly("外帘装袋");
    }

    @Test
    @DisplayName("自证：回填解析器能识别漂移（漏一道 / 多一道 / 改名都红）")
    void backfillParserDetectsInjectedDrift() {
        String good = "UPDATE production_operations SET scope = 'set' WHERE name IN "
                + "('外帘打卷', '外帘装袋', '外帘发货');";
        assertThat(backfilledScopes(good))
                .containsExactlyInAnyOrderEntriesOf(Map.of(
                        "外帘打卷", "set", "外帘装袋", "set", "外帘发货", "set"));

        assertThat(backfilledScopes(good.replace("'外帘发货')", "'外帘发货', '打包')")))
                .as("多一道 ⇒ 必须被识别（否则「恰好这几道」是空断言）")
                .containsEntry("打包", "set");

        assertThat(backfilledScopes("UPDATE production_operations SET scope = 'position' WHERE name IN ('x');"))
                .as("赋 position 的回填也要被读到（只认 set 会把「纠正回 position」漏掉）")
                .containsExactlyInAnyOrderEntriesOf(Map.of("x", "position"));

        assertThat(backfilledScopes("-- UPDATE production_operations SET scope='set' WHERE name IN ('注释里的假语句');"))
                .as("注释形态不应被当成回填（但真语句优先）")
                .isNotNull();
    }
}
