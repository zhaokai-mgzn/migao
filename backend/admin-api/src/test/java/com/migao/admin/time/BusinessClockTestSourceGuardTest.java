// case_ids: MC-022
package com.migao.admin.time;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 驻留守卫（<b>测试侧</b>）：业务「今天」在 {@code src/test/java} 里也只能有一个来源
 * （{@link BusinessClock}）—— issue #5651 收口时的实测缺陷。
 *
 * <h2>缺陷本体（实测，不是推断）</h2>
 *
 * <p>生产侧早就有单点时钟（issue #3802：{@code BusinessClock}，业务日固定
 * {@code Asia/Shanghai}），且有 {@link BusinessClockSourceGuardTest} 守 {@code src/main}。
 * <b>但测试侧没有任何守卫</b>，于是 5 条断言用裸 {@code LocalDate.now()} 取「今天」——</p>
 *
 * <ul>
 *   <li>CI runner 的 <b>JVM 默认时区 = UTC</b>，生产的业务日 = <b>+08</b>；
 *       两者在 <b>UTC 16:00–24:00（北京 00:00–08:00）差一天</b> ⇒ 每天红 8 小时；</li>
 *   <li>实测读数（required 检查 {@code admin-api unit tests}）：job 36280962072 跑在
 *       {@code 2026-09-26T23:58Z–00:00Z}，断言给出
 *       {@code expected: 2026-09-26 but was: 2026-09-27}（另两处 {@code -3/-4}、{@code 1/0}）；
 *       同一份代码在 UTC 00:00–16:00 窗口内**全绿**（本地 23:53Z 也是绿的 —— 本机 JVM 默认时区
 *       = +08，两侧恰好同区 ⇒ 「本地绿、CI 红」）。</li>
 *   <li>⇒ 这不是「某行写错」，而是<b>同一概念在测试侧又长出一份口径</b>，且<a>没有任何东西会因此变红</a>。</li>
 * </ul>
 *
 * <h2>判据（每条都有红证）</h2>
 * <ol>
 *   <li>{@link #testSourcesReadBusinessTimeOnlyViaBusinessClock()}：{@code src/test/java} 里
 *       不得出现下表的「时间口径」写法（**剥注释后**判定，见下）；</li>
 *   <li>{@link #ledgerOnlyShrinks()}：存量走<b>文件 × 规则</b>台账，条数**冻结**——
 *       新命中即红、超数即红、台账里的条目不再命中也要红（必须销账）；</li>
 *   <li>{@link #theClassesFixedByThisChangeAreClean()}：本单修掉的三个测试类**在扫描面内**
 *       且命中数为 **0**（实例判据；只登记「扫描面非空」是不够的 —— 那证明不了覆盖到它们）；</li>
 *   <li>{@link #scanSurfaceIsNotEmpty()}：扫描面必须真的有文件（路径漂移 ⇒ 判红，不是空跑通过）；</li>
 *   <li>{@link #rulesHaveDiscriminatingPower()}：每条禁则必须能命中一个「已知坏样本」；</li>
 *   <li>{@link #detectsInjectedViolationInIsolatedTree(Path)}：把违规样本放进隔离目录，
 *       扫描器必须逐条报出（且不碰真源树）。</li>
 * </ol>
 *
 * <h2>⚠️ 两条实测陷阱（本类自己踩过）</h2>
 * <ol>
 *   <li><b>必须剥注释</b>：修好的三个类的说明注释里就写着 {@code LocalDate.now()}
 *       （解释「为什么不许用」）—— 按原文扫描会把解释性注释读成违规
 *       （`migao-dev-flow` §23.4 T2：判据被自己的文案喂红）；</li>
 *   <li><b>判据语料必须排除判据自身</b>（§23.8 B1）：{@link BusinessClockSourceGuardTest}
 *       与<b>本文件</b>里，禁则的 needle 本身就是字面量（{@code "LocalDate.now("}）⇒ 扫描它们
 *       等于把守卫自己的规则表数成违规。故两者按<b>具名排除</b>处理（不是计数豁免）。</li>
 * </ol>
 *
 * <h2>为什么不是「给 surefire 设 -Duser.timezone=Asia/Shanghai」</h2>
 * <p>那个配置面确实能一处改全仓，但它<b>把墙钟留在判据里</b>：测试仍旧读「现在」，
 * 只是让两侧的<b>时区</b>偶然一致 ⇒ ① 跨业务日零点（+08 00:00）仍有窄竞态；
 * ② 在 IDE / 其它 runner 里跑，口径又不同（判据随环境漂移）；③ 存量 40 处隐患继续隐身。
 * 本单选择<b>逐测试注入生产侧同一只时钟</b>：判据的来源从「JVM 默认时区」换成「业务时钟」，
 * 与 runner 时区无关，且存量以台账显形（只许缩短）。</p>
 *
 * <p><b>边界（如实登记）</b>：本守卫只禁「无参 now() / 业务时区字面量」这五种可机械判定的形态；
 * <b>硬编码绝对日期</b>（{@code LocalDate.of(2026, 10, 1)}）不在禁列 —— 它只有在「当业务日基准用」
 * 时才是炸弹，而「纯数据」（如格式化断言）与它静态不可区分；那部分只做<b>普查</b>不做门禁
 * （同 {@code time_flaky_guard} 的形态 B 处置：把「为什么不假红」变成可复现读数）。</p>
 */
class BusinessClockTestSourceGuardTest {

    /** 一条禁则 = needle + 为什么它是缺陷（与 {@link BusinessClockSourceGuardTest} 同一组语义）。 */
    private record Rule(String name, String needle, String why) {
    }

    private static final List<Rule> FORBIDDEN = List.of(
            new Rule("无参 LocalDate.now()", "LocalDate.now(",
                    "取 JVM 默认时区（生产容器 / CI runner = UTC）⇒ 与业务日（+08）在 UTC 16:00–24:00 差一天"),
            new Rule("无参 LocalDateTime.now()", "LocalDateTime.now(",
                    "同上；与 +08 日零点相减算 TTL 时差 8 小时"),
            new Rule("无参 LocalTime.now()", "LocalTime.now(",
                    "同上（业务日/营业时段的比较基准）"),
            new Rule("业务时区字面量", "\"Asia/Shanghai\"",
                    "时区真值只许出现在 BusinessClock 一处（测试里再写一份 = 两处口径，迟早分叉）"),
            new Rule("ZoneId.of 业务时区", "ZoneId.of(\"Asia/Shanghai\")",
                    "同上（用 BusinessClock.BUSINESS_ZONE）"));

    /**
     * 判据语料里**排除**的文件（具名，带理由）—— 排除的是「守卫自己的 needle 字面量」，
     * <b>不是</b>「这些文件的违规豁免」（它们自己有没有违规，由各自的门禁管）。
     */
    private static final Map<String, String> SELF_EXCLUDED = Map.of(
            "com/migao/admin/time/BusinessClockSourceGuardTest.java",
            "src/main 侧守卫：类里就是这五条 needle 的字面量（规则表被数成违规 = §23.8 B1）",
            "com/migao/admin/time/BusinessClockTestSourceGuardTest.java",
            "本文件（测试侧守卫）：同上，且台账/红证样本里也有 needle 字面量");

    /**
     * 存量台账（键 = {@code <相对 src/test/java 的路径>|<规则名>}，值 = 该文件里允许出现的次数）。
     *
     * <p>🔴 <b>只许缩短</b>：① 不在台账里的新命中 ⇒ 红；② 计数超出 ⇒ 红；
     * ③ 台账里记着、现在<b>不再命中</b>的条目 ⇒ 红（必须销账）。
     * ⚠️ 计数是<b>现取</b>的读数，不写死历史数字；每次销账都要先跑
     * {@code python3 -c …} 或本类失败信息里的现取清单。</p>
     *
     * <p><b>修法（全部同一招）</b>：把 {@code LocalDate.now()} 换成注入的
     * {@code BusinessClock}（{@code @Spy private BusinessClock businessClock = new BusinessClock();}
     * + {@code @InjectMocks} 会注入进被测服务）⇒ 夹具与生产同源同区。
     * 本单已按此修掉三个类（见 {@link #theClassesFixedByThisChangeAreClean()}）。</p>
     */
    private static final Map<String, Integer> LEDGER = Map.ofEntries(
            Map.entry("com/migao/admin/controller/BriefingControllerTest.java|无参 LocalDate.now()", 2),
            Map.entry("com/migao/admin/controller/BusinessFlowIntegrationTest.java|无参 LocalDateTime.now()", 1),
            Map.entry("com/migao/admin/controller/UploadControllerTest.java|无参 LocalDateTime.now()", 1),
            Map.entry("com/migao/admin/service/AutoBatchDispatchTest.java|无参 LocalDate.now()", 13),
            Map.entry("com/migao/admin/service/AutoBatchDueScanRealDbTest.java|无参 LocalDate.now()", 4),
            Map.entry("com/migao/admin/service/AutoBatchDueScanServiceTest.java|无参 LocalDate.now()", 9),
            Map.entry("com/migao/admin/service/AutoBatchMountPointTest.java|无参 LocalDate.now()", 2),
            Map.entry("com/migao/admin/service/DailyBriefingServiceTest.java|无参 LocalDate.now()", 2),
            Map.entry("com/migao/admin/service/DailyBriefingServiceTest.java|业务时区字面量", 1),
            Map.entry("com/migao/admin/service/DailyBriefingServiceTest.java|ZoneId.of 业务时区", 1),
            Map.entry("com/migao/admin/time/BusinessClockTest.java|无参 LocalDate.now()", 2),
            Map.entry("com/migao/admin/time/BusinessClockTest.java|业务时区字面量", 1),
            Map.entry("com/migao/admin/time/BusinessClockTest.java|ZoneId.of 业务时区", 1));

    /** 本单修掉的三个测试类（实例判据：必须在扫描面内且命中为 0）。 */
    private static final List<String> FIXED_BY_THIS_CHANGE = List.of(
            "com/migao/admin/service/PoolBoardUrgencyTest.java",
            "com/migao/admin/service/InboundOrderServiceTest.java",
            "com/migao/admin/service/ProcessingOrderServiceTest.java");

    // ── 扫描器（纯函数，便于注入式红证）────────────────────────────────────────

    /** 剥掉 `//` 与 `/* *\/` 注释（字符串字面量内不剥——needle 本身可能就在字符串里）。 */
    static String stripComments(String src) {
        StringBuilder out = new StringBuilder(src.length());
        int i = 0;
        int n = src.length();
        while (i < n) {
            if (src.startsWith("/*", i)) {
                int j = src.indexOf("*/", i + 2);
                i = (j < 0) ? n : j + 2;
                continue;
            }
            if (src.startsWith("//", i)) {
                int j = src.indexOf('\n', i);
                i = (j < 0) ? n : j;
                continue;
            }
            out.append(src.charAt(i));
            i++;
        }
        return out.toString();
    }

    /** 一次扫描的结果：命中（键 = 文件|规则名 → 次数）+ 扫到的文件数。 */
    private record Scan(Map<String, Integer> hits, int files) {
    }

    private static Scan scan(Path root) throws IOException {
        Map<String, Integer> hits = new LinkedHashMap<>();
        int files = 0;
        try (Stream<Path> walk = Files.walk(root)) {
            for (Path file : walk.filter(p -> p.toString().endsWith(".java")).sorted().toList()) {
                files++;
                String rel = root.relativize(file).toString().replace('\\', '/');
                if (SELF_EXCLUDED.containsKey(rel)) {
                    continue;
                }
                String code = stripComments(Files.readString(file, StandardCharsets.UTF_8));
                for (Rule rule : FORBIDDEN) {
                    int count = countOccurrences(code, rule.needle());
                    if (count > 0) {
                        hits.merge(rel + "|" + rule.name(), count, Integer::sum);
                    }
                }
            }
        }
        return new Scan(hits, files);
    }

    private static int countOccurrences(String haystack, String needle) {
        int count = 0;
        int idx = haystack.indexOf(needle);
        while (idx >= 0) {
            count++;
            idx = haystack.indexOf(needle, idx + needle.length());
        }
        return count;
    }

    /** 台账对账：返回**问题清单**（空 = 干净）。纯函数 ⇒ 注入式红证可反复调用。 */
    private static List<String> reconcile(Map<String, Integer> hits, Map<String, Integer> ledger) {
        List<String> problems = new ArrayList<>();
        for (Map.Entry<String, Integer> hit : hits.entrySet()) {
            Integer allowed = ledger.get(hit.getKey());
            if (allowed == null) {
                problems.add("未登记的新命中：" + hit.getKey() + " ×" + hit.getValue()
                        + "（修法：改用注入的 BusinessClock —— 见类注释「修法」）");
            } else if (hit.getValue() > allowed) {
                problems.add("超出台账：" + hit.getKey() + " 实际 ×" + hit.getValue()
                        + " > 允许 ×" + allowed + "（台账只许缩短）");
            }
        }
        for (Map.Entry<String, Integer> entry : ledger.entrySet()) {
            if (!hits.containsKey(entry.getKey())) {
                problems.add("台账残留（现在已不再命中，必须销账）：" + entry.getKey());
            }
        }
        return problems;
    }

    private static Path testRoot() {
        List<Path> candidates = List.of(
                Path.of("src/test/java"),
                Path.of("backend/admin-api/src/test/java"));
        for (Path candidate : candidates) {
            if (Files.isDirectory(candidate)) {
                return candidate;
            }
        }
        throw new AssertionError("找不到 test 源根（candidates=" + candidates + "，cwd="
                + Path.of("").toAbsolutePath() + "）—— 路径漂移不得静默跳过（红）");
    }

    // ── 判据 ────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("测试侧的业务时间读取点不得新增（src/test/java 里除台账外一律判红）")
    void testSourcesReadBusinessTimeOnlyViaBusinessClock() throws IOException {
        Scan scan = scan(testRoot());
        List<String> problems = reconcile(scan.hits(), LEDGER);
        assertThat(problems)
                .as("测试侧出现了**新的**业务时间口径（issue #5651 收口实测：裸 now() 与 +08 业务日"
                        + "在 UTC 16:00–24:00 差一天 ⇒ required 检查每天红 8 小时）。"
                        + "修法 = 注入生产侧同一只 BusinessClock（见类注释）")
                .isEmpty();
        assertThat(scan.files())
                .as("扫到的测试源文件数（现取读数，不写死历史数字）")
                .isGreaterThan(100);
    }

    @Test
    @DisplayName("台账只许缩短：✔未登记即红 ✔超数即红 ✔不再命中即红（必须销账）")
    void ledgerOnlyShrinks() {
        assertThat(reconcile(Map.of("a|无参 LocalDate.now()", 1), Map.of()))
                .as("未登记的新命中必须判红")
                .hasSize(1);
        assertThat(reconcile(Map.of("a|无参 LocalDate.now()", 3), Map.of("a|无参 LocalDate.now()", 2)))
                .as("超出台账必须判红")
                .hasSize(1);
        assertThat(reconcile(Map.of(), Map.of("a|无参 LocalDate.now()", 1)))
                .as("台账残留（不再命中）必须判红 ⇒ 存量只能缩短")
                .hasSize(1);
        assertThat(reconcile(Map.of("a|无参 LocalDate.now()", 1), Map.of("a|无参 LocalDate.now()", 1)))
                .as("命中 == 台账 ⇒ 干净（否则台账退化成恒红）")
                .isEmpty();
    }

    @Test
    @DisplayName("🔴 本单修掉的三个测试类：在扫描面内、且命中为 0（实例判据）")
    void theClassesFixedByThisChangeAreClean() throws IOException {
        Scan scan = scan(testRoot());
        for (String rel : FIXED_BY_THIS_CHANGE) {
            assertThat(Files.isRegularFile(testRoot().resolve(rel)))
                    .as("受管文件必须存在（路径漂移不得静默跳过）：" + rel)
                    .isTrue();
            List<String> hits = scan.hits().entrySet().stream()
                    .filter(e -> e.getKey().startsWith(rel + "|"))
                    .map(Map.Entry::getKey)
                    .toList();
            assertThat(hits)
                    .as(rel + " 仍在用 JVM 默认时区取业务日（CI 的 UTC runner 上，"
                            + "UTC 16:00–24:00 必红 —— 2026-09-26T23:59Z 实测）")
                    .isEmpty();
        }
    }

    @Test
    @DisplayName("每条禁则都能命中一个「已知坏样本」（防 needle 写错后守卫变空断言）")
    void rulesHaveDiscriminatingPower() {
        String bad = """
                class Bad {
                    LocalDate a = LocalDate.now();
                    LocalDateTime b = LocalDateTime.now();
                    LocalTime c = LocalTime.now();
                    String d = "Asia/Shanghai";
                    ZoneId e = ZoneId.of("Asia/Shanghai");
                }
                """;
        String code = stripComments(bad);
        for (Rule rule : FORBIDDEN) {
            assertThat(countOccurrences(code, rule.needle()))
                    .as("禁则「" + rule.name() + "」在坏样本上命中 0 次 ⇒ needle 写错了（守卫是空断言）")
                    .isGreaterThan(0);
        }
        assertThat(stripComments("// LocalDate.now()\n/* LocalTime.now() */\n"))
                .as("注释里的提及不得被读成违规（§23.4 T2：判据被自己的文案喂红）")
                .doesNotContain("now(");
    }

    @Test
    @DisplayName("隔离目录注入违规 ⇒ 扫描器逐条报出（守卫自身判别力自证，不碰真源树）")
    void detectsInjectedViolationInIsolatedTree(@TempDir Path tempDir) throws IOException {
        Path sample = tempDir.resolve("com/migao/admin/service/InjectedSampleTest.java");
        Files.createDirectories(sample.getParent());
        Files.writeString(sample, """
                package com.migao.admin.service;
                class InjectedSampleTest {
                    void t() {
                        java.time.LocalDate today = java.time.LocalDate.now();
                    }
                }
                """, StandardCharsets.UTF_8);

        Scan scan = scan(tempDir);
        assertThat(scan.hits())
                .as("隔离目录里的裸 LocalDate.now() 必须被逐条报出（且命中键带文件名）")
                .containsKey("com/migao/admin/service/InjectedSampleTest.java|无参 LocalDate.now()");
        assertThat(reconcile(scan.hits(), Map.of()))
                .as("未登记的注入命中 ⇒ 对账必须判红")
                .hasSize(1);
    }
}
