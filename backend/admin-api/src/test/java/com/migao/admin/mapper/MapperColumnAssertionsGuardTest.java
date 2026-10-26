// case_ids: PG-056
package com.migao.admin.mapper;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 类级守卫（issue #7796）：「实体字段 ⊆ 建库列」这把尺子**只许有一份**。
 *
 * <h2>为什么实例判据拦不住</h2>
 * 改前 16 个 {@code *MapperTest} 各自复制了同一段「解析 {@code schema.sql} 的建库列 + 与实体字段比对」。
 * 复制体之间**会漂移**：PR #7793 给实体加只读投影字段（{@code @TableField(exist = false)}）时，
 * 只有当时被改到的那个文件过滤了 {@code exist = false}，其余 15 份立刻假红（首轮 CI 实测）。
 * 逐文件的 {@code everyEntityFieldHasAColumn} 只保证**今天**不漏列；本条保证**明天**不会有人再写第 2 份口径。
 *
 * <h2>判据（两条禁止形态，都对着源码文本判）</h2>
 * <ol>
 *   <li>自写的建库列解析器（{@code static Set<String> …} 那一行）—— 唯一出处必须是
 *       {@link MapperColumnAssertions}；</li>
 *   <li>判据消息「实体字段缺列」—— 出现即意味着有人手搓了第二份比对循环（判据消息是它的静态指纹）。</li>
 * </ol>
 *
 * <p>扫描面 = 本包下全部 {@code *MapperTest.java}；{@link MapperColumnAssertions} 与**本类**都不匹配该
 * 文件名形态（{@code …GuardTest.java}）⇒ **不需要**任何排除清单 —— 也就没有「豁免表」可以被悄悄放宽。</p>
 */
@DisplayName("类级守卫：实体列判据只剩一份（issue #7796）")
class MapperColumnAssertionsGuardTest {

    /** 模块相对路径（surefire 的 workdir = admin-api 模块根，与同包其它判据同口径）。 */
    private static final Path MAPPER_TESTS = Path.of("src/test/java/com/migao/admin/mapper");

    /** 自写的建库列解析器：{@code private} / 包级 / {@code public} 都算（调用点不匹配这条形态）。 */
    private static final Pattern SELF_WRITTEN_PARSER =
            Pattern.compile("\\bstatic\\s+Set<String>\\s+columnsOf\\s*\\(");

    /** 手搓「实体字段 ⊆ 列」比对的静态指纹 = 该判据的断言消息。 */
    private static final Pattern HAND_ROLLED_CRITERION = Pattern.compile("实体字段缺列");

    /** 扫描面下限 = 本单涉及的 16 个文件；扫不到 ⇒ 判据空跑，必须红。 */
    private static final int SCAN_FLOOR = 16;

    @Test
    @DisplayName("🔴 所有 *MapperTest 都不许自写 columnsOf 解析器 / 手搓实体列比对")
    void noMapperTestReimplementsTheColumnCriterion() throws Exception {
        List<String> scanned = mapperTestNames();
        assertThat(scanned.size())
                .as("判据扫描面不能为空（扫不到文件 ⇒ 空跑；目录 = %s）", MAPPER_TESTS.toAbsolutePath())
                .isGreaterThanOrEqualTo(SCAN_FLOOR);

        List<String> offenders = new ArrayList<>();
        for (String name : scanned) {
            offenders.addAll(violationsOf(name, Files.readString(MAPPER_TESTS.resolve(name))));
        }
        assertThat(offenders)
                .as("""
                        「实体字段 ⊆ 建库列」的判据只许有一份（MapperColumnAssertions）；以下文件自写了一份：
                          %s
                        复算：cd backend/admin-api && grep -rn 'Set<String> columnsOf(' \\
                              --include='*MapperTest.java' src/test/java/com/migao/admin/mapper
                        改法：删掉本地的 columnsOf / 比对循环，改调 MapperColumnAssertions.columnsOf(table)
                        与 MapperColumnAssertions.assertEveryEntityFieldHasColumn(entity, table)。""",
                        String.join("\n  ", offenders))
                .isEmpty();

        // 负断言不空跑：判据消息必须真的住在共享类里（否则「全仓都不出现」可以靠删掉判据得到）
        Path shared = MAPPER_TESTS.resolve("MapperColumnAssertions.java");
        assertThat(Files.exists(shared))
                .as("共享判据类必须在本包：%s", shared.toAbsolutePath()).isTrue();
        assertThat(Files.readString(shared))
                .as("判据消息的唯一出处（%s）", shared.getFileName()).contains("实体字段缺列");
    }

    @Test
    @DisplayName("注入式自证：自写判据的样例必红、合规样例必绿（本条不是空断言）")
    void theDetectorIsNotAnEmptyAssertion() {
        String handRolled = """
                class SampleMapperTest {
                    private static Set<String> columnsOf(String table) throws Exception {
                        return java.util.Set.of();
                    }
                }""";
        String compliant = """
                class SampleMapperTest {
                    void everyEntityFieldHasAColumn() {
                        MapperColumnAssertions.assertEveryEntityFieldHasColumn(Sample.class, "samples");
                    }
                }""";
        assertThat(violationsOf("SampleMapperTest.java", handRolled))
                .as("注入自写解析器 ⇒ 必须命中（否则本条是空断言）").isNotEmpty();
        assertThat(violationsOf("SampleMapperTest.java", compliant))
                .as("合规样例（只调共享判据）⇒ 不得命中").isEmpty();
    }

    /**
     * 一段源码里违禁形态的命中清单（{@code 文件名 → 形态}）。
     *
     * <p>抽成包级函数是为了让 {@link #theDetectorIsNotAnEmptyAssertion()} 能**注入**样例源码跑同一判定 ——
     * 判据自己也要有红证（§23 G3）。</p>
     */
    static List<String> violationsOf(String fileName, String source) {
        List<String> violations = new ArrayList<>();
        if (SELF_WRITTEN_PARSER.matcher(source).find()) {
            violations.add(fileName + " → 自写的建库列解析器（static Set<String> columnsOf(）");
        }
        if (HAND_ROLLED_CRITERION.matcher(source).find()) {
            violations.add(fileName + " → 手搓实体列比对（断言消息「实体字段缺列」）");
        }
        return violations;
    }

    /** 本包下全部 `*MapperTest.java` 的文件名（排序，便于消息稳定）。 */
    private static List<String> mapperTestNames() throws Exception {
        try (Stream<Path> files = Files.list(MAPPER_TESTS)) {
            return files.map(path -> path.getFileName().toString())
                    .filter(name -> name.endsWith("MapperTest.java"))
                    .sorted()
                    .toList();
        }
    }
}
