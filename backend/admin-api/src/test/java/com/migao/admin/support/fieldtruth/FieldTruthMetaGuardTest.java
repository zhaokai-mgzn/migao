// case_ids: CU-002

package com.migao.admin.support.fieldtruth;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.SortedMap;
import java.util.SortedSet;
import java.util.TreeSet;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * <b>类级元守卫</b>（issue #5362 / AGENTS.md 铁律 8「类级固化」）——
 * 让「字段在架、真值不在」这<b>一类</b>病进不来，而不只是修好 {@code customer_profiles} 这一张表。
 *
 * <p>三条判据（缺一条就退化成「只修了一个实例」）：
 * <ol>
 *   <li><b>注册表即作用域</b>：{@link FieldTruthRegistry} 里每一份声明都要过三条判据
 *       （完整性 / 写入点 / 遮蔽）—— 新表登记即自动受管，<b>不需要改判据代码</b>；</li>
 *   <li><b>判据不是 {@code CustomerProfile} 专用</b>：用<b>夹具注入的第二张表</b>
 *       （临时 Java 树 + 自带 schema + 自带遮蔽类）行使<b>同一份生产判据</b>，
 *       并逐条注入变异验证它在该表上同样会红（G7「红证要自证注入生效」）；</li>
 *   <li><b>未登记即红 + 只许缩短</b>：**同域表**（= 声明所在服务类注入的 Mapper 绑定表，从源码派生、不是手写清单）里「数值列有常量默认值 ∧ 源码无真值级写入点」的病征与
 *       {@link #UNREGISTERED_DEBT} 存量台账<b>逐条对账</b>：
 *       新增病征（未登记的同类风险）⇒ 红；台账条目已不再命中（已收口 / 判据变敏）⇒ 红，
 *       必须在同 PR 里删掉那条 —— <b>涨跌都红</b>，台账不会被静默冻结成永久豁免。
 * </ol>
 *
 * <p>🔴 <b>为什么必须成对</b>：实例判据只保证「这一张表现在是对的」；
 * 下一张表（新功能照抄 {@code CustomerProfile} 的写法）不会有任何东西拦着它 ——
 * 元守卫才是「这一类进不来」的那一半。
 */
class FieldTruthMetaGuardTest {

    /**
     * 同域存量台账（冻结于 2026-09-24，issue #5362）：**已确诊同款病征、但尚未做字段级声明**的表字段。
     *
     * <p>语义 = **未登记债**，不是「这些字段没有真值」的断言：条目只说明「该列是数值列、有常量默认值
     * （{@code DEFAULT 0}）、且源码里没有任何真值级写入点」⇒ 该 0 会被读成「量值为零」。
     * 逐条收口路径 = 为该表补一份 {@link FieldTruth.Declaration} + 一份遮蔽类
     * （判据与元守卫自动生效），**收口后必须在同 PR 删掉这里的对应条目**。
     *
     * <p>🔴 只许缩短：新增条目 ⇒ 判据红（同域未登记风险）。判据变敏导致命中变化同样 ⇒ 红，
     * 须在同 PR 重锚（与仓内其它台账同口径）。
     *
     * <p>⚠️ <b>范围限定在「同域表」是有意的</b>：全仓候选实测 37 处（数值列 + 常量默认值 +
     * 无真值级写入，见 {@code repoWideCandidateReading} 的存活读数），但判据的「常量 ⇒ 占位」分类
     * 无法区分「占位默认值」、「状态枚举常量」（如 {@code sessions.status} 写 {@code "active"}）
     * 与「{@code LambdaUpdateWrapper.set} 写入」⇒ 冻结全仓等于把**错误真相模型**写成永久豁免。
     * 其余域的同款风险**如实登记为未实装项**（§19.1），逐域收口另立。
     */
    private static final Set<String> UNREGISTERED_DEBT = Set.of(
            // 客户读面同域表（CustomerService 的 Mapper 绑定）：计数/统计列只有列默认值 0，无人计算
            "customer_tags.hitCount",
            "customer_segments.customerCount",
            "session_messages.tokenCount");

    // ==================== ① 注册表即作用域 ====================

    @Test
    @DisplayName("注册表里每份声明都必须过三条判据（新表登记即自动受管）")
    void everyRegisteredDeclarationPasses() {
        Map<Class<?>, FieldTruth.Declaration> registered = FieldTruthRegistry.all();
        int tables = registered.size();
        int fields = 0;
        int writeSites = 0;
        for (FieldTruth.Declaration decl : registered.values()) {
            Map<String, List<FieldTruthSourceScan.WriteSite>> sites =
                    FieldTruthSourceScan.writeSites(decl.entity(), decl.table());
            Set<String> masked = FieldTruthSourceScan.maskedFields(decl.entity().getSimpleName());
            fields += decl.declaredFields().size();
            writeSites += sites.values().stream().mapToInt(List::size).sum();
            assertThat(FieldTruthSourceScan.violations(decl, sites, masked))
                    .as("已登记的 %s 必须过判据（红 = 声明与源码/遮蔽清单漂移）", decl.table())
                    .isEmpty();
        }
        // 存活读数（G6：零动作也要出声 —— 「我没做事」与「我没跑」必须长得不一样）
        System.out.println("[field-truth] 已登记表=" + tables + " 声明字段=" + fields
                + " 写入点=" + writeSites + " 存量未登记债=" + UNREGISTERED_DEBT.size());
        assertThat(tables).as("注册表为空 ⇒ 元守卫空转").isNotEqualTo(0);
        assertThat(fields).as("声明字段数为 0 ⇒ 判据空转").isNotEqualTo(0);
        assertThat(writeSites).as("写入点扫描为 0 ⇒ 判据空转").isNotEqualTo(0);
    }

    @Test
    @DisplayName("注册表拒绝重复登记（两份声明静默分叉 = 判据失去唯一真值）")
    void registryRejectsDuplicateRegistration() {
        assertThatThrownBy(() -> FieldTruthRegistry.register(CustomerProfileFieldTruth.declaration()))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("已登记");
    }

    // ==================== ② 判据对任意一张表都成立（夹具注入） ====================

    /** 夹具实体（只用于夹具 Java 树；字段与树里的源码逐字对应）。 */
    static class FakeLedger {
        private String id;
        private Long tenantId;
        private Integer computedScore;
        private String label;
    }

    private static final String FAKE_ENTITY_SRC = String.join("\n",
            "package com.migao.admin.entity;",
            "import com.baomidou.mybatisplus.annotation.*;",
            "public class FakeLedger {",
            "    @TableId(type = IdType.ASSIGN_UUID)",
            "    private String id;",
            "    private Long tenantId;",
            "    private Integer computedScore;",
            "    private String label;",
            "}");

    private static final String FAKE_SCHEMA = String.join("\n",
            "CREATE TABLE fake_ledger (",
            "    id VARCHAR(64) PRIMARY KEY,",
            "    tenant_id BIGINT NOT NULL,",
            "    computed_score INTEGER DEFAULT 0,",
            "    label VARCHAR(32)",
            ");");

    private static String fakeService(String labelWrite) {
        return String.join("\n",
                "package com.migao.admin.service;",
                "import com.migao.admin.entity.FakeLedger;",
                "public class FakeLedgerService {",
                "    public void save(FakeLedger row, Long tenantId, String label) {",
                "        row.setTenantId(tenantId);",
                labelWrite,
                "    }",
                "}");
    }

    private static FieldTruth.Declaration fakeDeclaration(FieldTruth computedTruth, boolean withLabel) {
        Map<String, FieldTruth.Entry> fields = new LinkedHashMap<>();
        fields.put("id", new FieldTruth.Entry(FieldTruth.HAS_TRUTH, "夹具：@TableId(ASSIGN_UUID) 框架生成"));
        fields.put("tenantId", new FieldTruth.Entry(FieldTruth.HAS_TRUTH, "夹具：服务层 row.setTenantId(tenantId) 真值级写入"));
        fields.put("computedScore", new FieldTruth.Entry(computedTruth,
                "夹具：computed_score 列有常量默认值 0，源码零写入 ⇒ 声明无真值并遮蔽"));
        if (withLabel) {
            fields.put("label", new FieldTruth.Entry(FieldTruth.HAS_TRUTH, "夹具：服务层 row.setLabel(label) 真值级写入"));
        }
        return new FieldTruth.Declaration(FakeLedger.class, "fake_ledger", fields);
    }

    private record Fixture(Path javaRoot, Path resourcesRoot, Path schema, Path maskFile) {
    }

    private static Fixture fixture(Path root, String labelWrite) {
        return fixture(root, labelWrite, "        p.setComputedScore(null);");
    }

    /**
     * 铺一棵夹具 Java 树。
     *
     * <p>⚠️ <b>同一路径重写后必须换目录再扫</b>：源码按路径缓存，原地重写会读到旧内容
     * ⇒ 注入式红证假绿（G7「红证要自证注入生效」）。本文件用 {@code base/} 与 {@code injected/}
     * 两个**兄弟**目录（父子目录不行：扫描是递归的，注入物会被基线扫到）。
     */
    private static Fixture fixture(Path root, String labelWrite, String maskLine) {
        write(root.resolve("com/migao/admin/entity/FakeLedger.java"), FAKE_ENTITY_SRC);
        write(root.resolve("com/migao/admin/service/FakeLedgerService.java"), fakeService(labelWrite));
        Path schema = write(root.resolve("db/init/schema.sql"), FAKE_SCHEMA);
        Path mask = write(root.resolve("com/migao/admin/support/fieldtruth/FakeLedgerTruthMask.java"),
                String.join("\n",
                        "package com.migao.admin.support.fieldtruth;",
                        "public class FakeLedgerTruthMask {",
                        "    public static void apply(Object row) {",
                        "        com.migao.admin.entity.FakeLedger p = (com.migao.admin.entity.FakeLedger) row;",
                        maskLine,
                        "    }",
                        "}"));
        return new Fixture(root, root, schema, mask);
    }

    private static Path write(Path path, String content) {
        try {
            Files.createDirectories(path.getParent());
            Files.writeString(path, content, StandardCharsets.UTF_8);
            return path;
        } catch (IOException e) {
            throw new UncheckedIOException("夹具写入失败：" + path, e);
        }
    }

    private static List<String> fixtureViolations(Fixture fixture, FieldTruth.Declaration decl) {
        return FieldTruthSourceScan.violations(decl,
                FieldTruthSourceScan.writeSites(decl.entity(), decl.table(),
                        fixture.javaRoot(), fixture.resourcesRoot()),
                FieldTruthSourceScan.maskedFields(fixture.maskFile()));
    }

    @Test
    @DisplayName("夹具：同一份判据在另一张表上基线全绿（机制不是 CustomerProfile 专用）")
    void guardWorksOnAnotherTable(@TempDir Path root) {
        Fixture fixture = fixture(root, "        row.setLabel(label);");
        assertThat(fixtureViolations(fixture, fakeDeclaration(FieldTruth.NO_TRUTH, true)))
                .as("夹具基线本该全绿（若红，说明判据把 CustomerProfile 的名/表写死了）")
                .isEmpty();
    }

    @Test
    @DisplayName("夹具红证①：另一张表上「声明有真值但没有写入点」⇒ 变红")
    void fixtureTruthFieldWithoutWriteSiteTurnsRed(@TempDir Path root) {
        // 遮蔽清单同步去掉该字段（与改判后的声明自洽）⇒ 只剩「源码里没人写它」这一条判据
        Fixture fixture = fixture(root, "        row.setLabel(label);",
                "        // 注入：遮蔽清单里没有 computedScore");
        assertThat(fixtureViolations(fixture, fakeDeclaration(FieldTruth.HAS_TRUTH, true)))
                .as("把 computedScore 改判成有真值而源码里没人写它 ⇒ 判据必须在另一张表上同样变红")
                .hasSize(1)
                .allMatch(v -> v.startsWith("computedScore ") && v.contains("没有真值级写入点"));
    }

    @Test
    @DisplayName("夹具红证②：另一张表上删掉写入行 ⇒ 立刻变红（注入确实生效，G7）")
    void fixtureDeletedWriteSiteTurnsRed(@TempDir Path root) {
        Fixture baseline = fixture(root.resolve("base"), "        row.setLabel(label);");
        assertThat(fixtureViolations(baseline, fakeDeclaration(FieldTruth.NO_TRUTH, true)))
                .as("注入前必须绿（否则红证不可归因）")
                .isEmpty();

        // 注入落到**另一个兄弟目录**：源码按路径缓存，原地重写会读到旧内容 ⇒ 红证假绿
        Fixture withoutWrite = fixture(root.resolve("injected"),
                "        // row.setLabel(label);  ← 注入：抹掉写入点");
        assertThat(fixtureViolations(withoutWrite, fakeDeclaration(FieldTruth.NO_TRUTH, true)))
                .as("抹掉写入点后，声明「有真值」的 label 必须被判红（红证自证注入生效）")
                .anyMatch(v -> v.startsWith("label ") && v.contains("没有真值级写入点"));
    }

    @Test
    @DisplayName("夹具红证③：另一张表上漏登记字段 ⇒ 变红（未登记的新字段即红）")
    void fixtureUndeclaredFieldTurnsRed(@TempDir Path root) {
        Fixture fixture = fixture(root, "        row.setLabel(label);");
        assertThat(fixtureViolations(fixture, fakeDeclaration(FieldTruth.NO_TRUTH, false)))
                .as("夹具实体新增字段若没登记真值状态 ⇒ 必须点名（这就是「未登记即红」）")
                .anyMatch(v -> v.contains("未声明字段") && v.contains("label"));
    }

    @Test
    @DisplayName("夹具红证④：另一张表上「声明无真值但源码在写它」⇒ 变红")
    void fixtureNoTruthFieldWithWriteTurnsRed(@TempDir Path root) {
        Fixture fixture = fixture(root, "        row.setLabel(label);");
        FieldTruth.Declaration decl = fakeDeclaration(FieldTruth.NO_TRUTH, true);
        Map<String, FieldTruth.Entry> fields = new LinkedHashMap<>(decl.fields());
        fields.put("tenantId", new FieldTruth.Entry(FieldTruth.NO_TRUTH, "夹具注入：把有真值字段改判成无真值"));
        FieldTruth.Declaration flipped = new FieldTruth.Declaration(FakeLedger.class, "fake_ledger", fields);
        assertThat(fixtureViolations(fixture, flipped))
                .as("源码里确实在写它 ⇒ 改判成「无真值」必须变红")
                .anyMatch(v -> v.startsWith("tenantId ") && v.contains("存在真值级写入点"));
    }

    @Test
    @DisplayName("扫描器只认实体类型变量上的 setter（其它实体的同名字段不得串台）")
    void scannerOnlyCountsEntityReceivers(@TempDir Path root) {
        write(root.resolve("com/migao/admin/entity/FakeLedger.java"), FAKE_ENTITY_SRC);
        write(root.resolve("com/migao/admin/entity/OtherLedger.java"),
                "package com.migao.admin.entity;\npublic class OtherLedger {\n    private String label;\n}\n");
        write(root.resolve("com/migao/admin/service/Mixed.java"), String.join("\n",
                "package com.migao.admin.service;",
                "import com.migao.admin.entity.FakeLedger;",
                "import com.migao.admin.entity.OtherLedger;",
                "public class Mixed {",
                "    public void m(FakeLedger fake, OtherLedger other) {",
                "        other.setLabel(\"串台\");",
                "    }",
                "}"));
        Map<String, List<FieldTruthSourceScan.WriteSite>> sites =
                FieldTruthSourceScan.writeSites(FakeLedger.class, "fake_ledger", root, root);
        assertThat(sites.getOrDefault("label", List.of()))
                .as("别的实体上的 setLabel 不得算作 FakeLedger 的写入点（否则真值判定被放宽）")
                .isEmpty();
    }

    // ==================== ③ 未登记即红 + 只许缩短 ====================

    /**
     * 同域表 = 注册表声明所在服务类（{@code CustomerService}）注入的 Mapper 所绑定的实体表
     * —— **从源码派生**（{@code XxxMapper extends BaseMapper<Entity>} ⇒ 实体的 {@code @TableName}），
     * 不给第二份手写清单：给客户读面加表的人必然落在同一个服务类里 ⇒ 该表立刻进入对账面。
     */
    private static SortedSet<String> siblingTables() {
        String service = FieldTruthSourceScan.readSource(
                FieldTruthSourceScan.findSource("CustomerService.java", FieldTruthSourceScan.JAVA_MAIN));
        SortedMap<String, String> byTable = FieldTruthSourceScan.entitiesByTable();
        SortedSet<String> tables = new TreeSet<>();
        Matcher mapperField = Pattern.compile("(\\w+)Mapper\\s+\\w+\\s*;").matcher(service);
        while (mapperField.find()) {
            Path mapper = FieldTruthSourceScan.findSource(
                    mapperField.group(1) + "Mapper.java", FieldTruthSourceScan.JAVA_MAIN);
            if (mapper == null) {
                continue;
            }
            Matcher bound = Pattern.compile("BaseMapper<\\s*(\\w+)\\s*>")
                    .matcher(FieldTruthSourceScan.readSource(mapper));
            if (!bound.find()) {
                continue;
            }
            String entity = bound.group(1);
            byTable.forEach((table, fqn) -> {
                if (fqn.endsWith("." + entity)) {
                    tables.add(table);
                }
            });
        }
        return tables;
    }

    @Test
    @DisplayName("同域表逐条对账：未登记的新病征即红、已收口的条目必须删除（涨跌都红）")
    void siblingTablesMatchFrozenLedger() {
        Set<String> covered = new TreeSet<>();
        Set<String> registeredTables = new TreeSet<>();
        FieldTruthRegistry.all().values().forEach(decl -> {
            registeredTables.add(decl.table());
            covered.addAll(decl.noTruthFields());
        });

        SortedSet<String> siblings = siblingTables();
        SortedSet<String> found = new TreeSet<>();
        for (String table : siblings) {
            if (registeredTables.contains(table)) {
                continue;
            }
            String fqn = FieldTruthSourceScan.entitiesByTable().get(table);
            found.addAll(FieldTruthSourceScan.diseaseShape(FieldTruthSourceScan.entityClass(fqn), table,
                    covered, FieldTruthSourceScan.JAVA_MAIN, FieldTruthSourceScan.RESOURCES_MAIN,
                    FieldTruthSourceScan.SCHEMA));
        }
        SortedSet<String> undeclared = new TreeSet<>(found);
        undeclared.removeAll(UNREGISTERED_DEBT);
        SortedSet<String> stale = new TreeSet<>(UNREGISTERED_DEBT);
        stale.removeAll(found);

        // 存活读数（G6）+ 可行动清单（G3）
        System.out.println("[field-truth] 同域表=" + siblings + " 命中病征=" + found.size()
                + " 台账=" + UNREGISTERED_DEBT.size() + " 未登记=" + undeclared.size()
                + " 台账已不再命中=" + stale.size());
        undeclared.forEach(item -> System.out.println("[field-truth] 未登记的新病征： " + item));
        stale.forEach(item -> System.out.println("[field-truth] 台账已不再命中（须删除该条）： " + item));

        assertThat(siblings)
                .as("同域表派生不该为空（派生失败 ⇒ 对账面空转）")
                .contains("customer_profiles");
        assertThat(undeclared)
                .as("同域表出现「数值列有常量默认值 ∧ 源码无真值级写入点」的字段，却没做字段级真值声明 ⇒ "
                        + "商家/Agent 会把列默认值 0 当成「量值为零」。处置：为该表补 FieldTruth.Declaration + "
                        + "遮蔽类（判据自动生效）；本单范围外则在 UNREGISTERED_DEBT 登记（只许缩短）")
                .isEmpty();
        assertThat(stale)
                .as("台账条目已不再命中（该表已收口 / 判据变敏）⇒ 必须在同 PR 删除这些条目，"
                        + "否则台账被静默冻结成永久豁免（只许缩短）")
                .isEmpty();
    }

    @Test
    @DisplayName("全仓候选读数（**未冻结**成台账 —— 边界理由见 UNREGISTERED_DEBT 的注释）")
    void repoWideCandidateReading() {
        Set<String> covered = new TreeSet<>();
        FieldTruthRegistry.all().values().forEach(decl -> covered.addAll(decl.noTruthFields()));
        SortedSet<String> candidates = new TreeSet<>();
        SortedMap<String, String> entities = FieldTruthSourceScan.entitiesByTable();
        for (Map.Entry<String, String> entry : entities.entrySet()) {
            candidates.addAll(FieldTruthSourceScan.diseaseShape(
                    FieldTruthSourceScan.entityClass(entry.getValue()), entry.getKey(), covered,
                    FieldTruthSourceScan.JAVA_MAIN, FieldTruthSourceScan.RESOURCES_MAIN,
                    FieldTruthSourceScan.SCHEMA));
        }
        System.out.println("[field-truth] 全仓候选（数值列 + 常量默认值 + 无真值级写入，未冻结）= "
                + candidates.size() + " 处 / 实体 " + entities.size() + " 个");
        assertThat(entities.size()).as("实体枚举为空 ⇒ 扫描器空转").isGreaterThan(10);
        assertThat(candidates)
                .as("候选集为空 ⇒ 判据面已失效（本单的确诊形态是「列默认值被当成量值」）")
                .isNotEmpty();
    }
}