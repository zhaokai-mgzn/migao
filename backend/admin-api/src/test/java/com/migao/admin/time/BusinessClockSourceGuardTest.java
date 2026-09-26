// case_ids: DA-001, DA-002, DA-004
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
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 驻留守卫：业务「今天」只能有一个来源（issue #3802）。
 *
 * <p>缺陷本体不是「某一行写错」，而是<b>同一概念有两处口径</b>且<b>没有任何东西会因此变红</b>
 * —— 修完 18 处之后，下一个人写一句无参 {@code LocalDate.now()} 依然能悄悄把它变回两套口径。
 * 本守卫把「口径唯一」变成每次跑测试都会执行的判据。</p>
 *
 * <h2>判据（全部枚举化，含各自的红证）</h2>
 * <ol>
 *   <li>{@link #onlyTheClockComponentReadsBusinessTimeFromMain()}：{@code src/main} 下除
 *       {@link #CLOCK_FILE} 外，不得出现下表的任一「时间口径」写法；</li>
 *   <li>{@link #instantNowLedgerIsFrozenAndLive()}：{@code Instant.now()} 属<b>绝对时刻</b>
 *       （与时区无关，产生不了「两个今天」）⇒ 用<b>文件级台账</b>豁免，条数冻结、条目必须活着
 *       （新增即红、删文件也红）；</li>
 *   <li>{@link #scanSurfaceIsNotEmpty()}：扫描面必须真的有文件（路径漂移 ⇒ 判红，不是空跑通过）；</li>
 *   <li>{@link #rulesHaveDiscriminatingPower()}：每条禁则必须能命中一个「已知坏样本」，
 *       防止把 needle 写错后守卫静默变成空断言；</li>
 *   <li>{@link #detectsInjectedViolationInIsolatedTree(Path)}：把违规样本放进隔离目录，
 *       扫描器必须逐条报出（守卫自身的判别力自证，且不碰 {@code src/main}）。</li>
 * </ol>
 *
 * <p><b>台账只许缩短</b>：{@link #INSTANT_NOW_LEDGER} 的条数是<b>冻结值</b>（现取，不写死历史数字），
 * 任何新增都需要在此登记 —— 登记动作本身就是「这里为什么可以」的评审点。</p>
 */
class BusinessClockSourceGuardTest {

    /** 唯一允许出现业务时区 / 时钟读取的源文件（仓库相对路径）。 */
    private static final String CLOCK_FILE = "com/migao/admin/time/BusinessClock.java";

    /** 一条禁则 = 一个 needle + 为什么它是缺陷。 */
    private record Rule(String name, String needle, String why) {
    }

    private static final List<Rule> FORBIDDEN = List.of(
            new Rule("无参 LocalDate.now()", "LocalDate.now(",
                    "取 JVM 默认时区（生产容器口径 = UTC）⇒ 与业务日差一天"),
            new Rule("无参 LocalDateTime.now()", "LocalDateTime.now(",
                    "同上；与 +08 日零点相减算 TTL 时差 8 小时"),
            new Rule("无参 LocalTime.now()", "LocalTime.now(",
                    "同上（营业时段/早晚判断会错 8 小时）"),
            new Rule("JVM 默认时区时钟", "Clock.system",
                    "Clock 必须由 BusinessClock 单点创建（systemDefaultZone/systemUTC 都是漂移源）"),
            new Rule("业务时区字面量", "\"Asia/Shanghai\"",
                    "时区字面量只许出现在 BusinessClock（否则又变成「两处口径」）"),
            new Rule("UTC 日边界贴 +08 标签", "ZoneOffset.ofHours(8)",
                    "取的是 UTC 日边界、只贴了 +08 标签（issue #3802 点名的更差拼写）"));

    /**
     * {@code Instant.now()} 台账：绝对时刻，与时区无关，<b>不产生</b>「两个今天」。
     * 值 = 该文件里允许出现的次数。文件 = 仓库相对路径（{@code src/main/java/} 之后）。
     */
    private static final Map<String, Integer> INSTANT_NOW_LEDGER = Map.of(
            "com/migao/admin/dto/ApiResponse.java", 1,
            "com/migao/admin/security/JwtTokenProvider.java", 2);

    private record Scan(int files, Map<String, List<String>> hits) {
    }

    /** main 源根：surefire 的工作目录是模块根；也容忍从仓库根跑（两种都找不到 ⇒ 判红，不空跑）。 */
    private static Path mainRoot() {
        List<Path> candidates = List.of(
                Path.of("src/main/java"),
                Path.of("backend/admin-api/src/main/java"));
        return candidates.stream().filter(Files::isDirectory).findFirst()
                .orElseThrow(() -> new AssertionError(
                        "找不到 main 源根（candidates=" + candidates + "，cwd=" + Path.of("").toAbsolutePath()
                                + "）—— 扫描面为空 = 守卫空跑，必须判红"));
    }

    private static Scan scan(Path root) throws IOException {
        Map<String, List<String>> hits = new LinkedHashMap<>();
        int files = 0;
        try (Stream<Path> walk = Files.walk(root)) {
            for (Path file : walk.filter(p -> p.toString().endsWith(".java")).toList()) {
                String relative = root.relativize(file).toString().replace('\\', '/');
                if (relative.equals(CLOCK_FILE)) {
                    continue;
                }
                files++;
                List<String> lines = Files.readAllLines(file, StandardCharsets.UTF_8);
                for (int i = 0; i < lines.size(); i++) {
                    for (Rule rule : FORBIDDEN) {
                        if (lines.get(i).contains(rule.needle())) {
                            hits.computeIfAbsent(relative, k -> new ArrayList<>())
                                    .add(rule.name() + " → " + relative + ":" + (i + 1)
                                            + " | " + lines.get(i).trim());
                        }
                    }
                }
            }
        }
        return new Scan(files, hits);
    }

    @Test
    @DisplayName("src/main 里业务时间的读取点只剩 BusinessClock 一处（其余一律判红）")
    void onlyTheClockComponentReadsBusinessTimeFromMain() throws IOException {
        Path root = mainRoot();
        assertThat(Files.exists(root.resolve(CLOCK_FILE)))
                .as("白名单里的时钟文件必须存在（改名/挪包 ⇒ 守卫失效，判红）：%s", CLOCK_FILE)
                .isTrue();

        Scan scan = scan(root);
        assertThat(scan.hits())
                .as("业务「今天」必须单点（issue #3802）。违规写法：\n  %s",
                        FORBIDDEN.stream().map(r -> r.needle() + " —— " + r.why()).toList())
                .isEmpty();
    }

    @Test
    @DisplayName("Instant.now() 台账冻结且条目活着（新增即红，删文件也红）")
    void instantNowLedgerIsFrozenAndLive() throws IOException {
        Path root = mainRoot();
        Map<String, Integer> actual = new LinkedHashMap<>();
        try (Stream<Path> walk = Files.walk(root)) {
            for (Path file : walk.filter(p -> p.toString().endsWith(".java")).toList()) {
                String relative = root.relativize(file).toString().replace('\\', '/');
                String text = Files.readString(file, StandardCharsets.UTF_8);
                Matcher matcher = Pattern.compile("Instant\\.now\\(\\)").matcher(text);
                int count = 0;
                while (matcher.find()) {
                    count++;
                }
                if (count > 0) {
                    actual.put(relative, count);
                }
            }
        }
        assertThat(actual)
                .as("Instant.now()（绝对时刻）台账：只许缩短 —— 新增点必须在本测试里登记并说明为什么它与业务日无关")
                .isEqualTo(INSTANT_NOW_LEDGER);
        for (String ledgered : INSTANT_NOW_LEDGER.keySet()) {
            assertThat(Files.exists(root.resolve(ledgered)))
                    .as("台账条目必须活着（文件已不在 ⇒ 台账腐化，判红）：%s", ledgered)
                    .isTrue();
        }
    }

    @Test
    @DisplayName("扫描面非空（路径漂移不许变成空跑通过）")
    void scanSurfaceIsNotEmpty() throws IOException {
        Scan scan = scan(mainRoot());
        assertThat(scan.files())
                .as("扫到的 src/main 源文件数（现取读数，不写死历史数字）")
                .isGreaterThan(100);
        assertThat(scan.hits()).isEmpty();
    }

    @Test
    @DisplayName("每条禁则都能命中已知坏样本（needle 写错 ⇒ 判红，而不是变成空断言）")
    void rulesHaveDiscriminatingPower() {
        Map<String, String> badSamples = Map.of(
                "无参 LocalDate.now()", "        LocalDate today = LocalDate.now();",
                "无参 LocalDateTime.now()", "        .createdAt(LocalDateTime.now())",
                "无参 LocalTime.now()", "        LocalTime now = LocalTime.now();",
                "JVM 默认时区时钟", "        this(Clock.systemDefaultZone());",
                "业务时区字面量", "        ZoneId cst = ZoneId.of(\"Asia/Shanghai\");",
                "UTC 日边界贴 +08 标签",
                "        LocalDate.now().atStartOfDay().atOffset(ZoneOffset.ofHours(8));");
        for (Rule rule : FORBIDDEN) {
            String sample = badSamples.get(rule.name());
            assertThat(sample).as("禁则 %s 缺坏样本（判据不可自证）", rule.name()).isNotNull();
            assertThat(sample.contains(rule.needle()))
                    .as("禁则 %s 的 needle 必须能命中坏样本：%s", rule.name(), sample)
                    .isTrue();
        }
    }

    @Test
    @DisplayName("隔离目录里的注入违规必须被逐条报出（守卫自身判别力自证）")
    void detectsInjectedViolationInIsolatedTree(@TempDir Path tempDir) throws IOException {
        Path injected = tempDir.resolve("com/migao/admin/service/InjectedViolation.java");
        Files.createDirectories(injected.getParent());
        Files.writeString(injected, String.join("\n",
                "package com.migao.admin.service;",
                "class InjectedViolation {",
                "    void today() {",
                "        java.time.LocalDate.now();",
                "        java.time.ZoneId.of(\"Asia/Shanghai\");",
                "    }",
                "}"), StandardCharsets.UTF_8);

        Scan scan = scan(tempDir);

        assertThat(scan.files()).isEqualTo(1);
        assertThat(scan.hits()).containsOnlyKeys("com/migao/admin/service/InjectedViolation.java");
        assertThat(scan.hits().get("com/migao/admin/service/InjectedViolation.java"))
                .as("注入的两条违规必须逐条具名报出（含 文件:行号）")
                .hasSize(2)
                .anySatisfy(hit -> assertThat(hit).contains("无参 LocalDate.now()").contains(":4"))
                .anySatisfy(hit -> assertThat(hit).contains("业务时区字面量").contains(":5"));
    }
}
