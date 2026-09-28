// case_ids: PG-018
// ⚠️ 用例关联（如实登记）：PG-018 = 生产域后端契约族（同 ProductionTodoServiceTest 的口径）。
// **未固化项**：本守卫的专属行为用例需另开一包改 `.github/cases/**`（本轮由并行包独占写面）。
package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * <b>类级元守卫</b>：「卡在哪」的判据只有一份，聚合层只许透传（issue #5641）。
 *
 * <p>缺陷本体不是「某一行写错」，而是<b>同一真值有两处投影</b>：{@code ProductionTodoService}
 * 完全可以在自己这里再算一次「等了多久」、再比一次阈值 —— 那样第一版看起来也对，
 * 但两处口径从此各自漂移，而<b>没有任何东西会因此变红</b>
 * （本仓登记过的复发族：craft-display 三份副本 issue #4393；§17.3 ③）。</p>
 *
 * <h2>判据（4 条，各自带自证）</h2>
 * <ol>
 *   <li>{@link #aggregationSurfaceIsExactlyTheRegisteredFiles()}：聚合层扫描面 = 恰好
 *       {@code *TodoService.java} 这一个文件 —— <b>新增一个待办聚合服务 ⇒ 未登记即红</b>，
 *       必须回来把它登记进禁则面（这就是「豁免台账只许缩短」的同款形态）；</li>
 *   <li>{@link #scanSurfaceIsNotEmpty()}：扫描面非空 + <b>反向对照</b>（必须真的读到透传那两处）
 *       —— 防「文件路径写错 ⇒ 禁则退化成空断言」；</li>
 *   <li>{@link #aggregationLayerOnlyPassesTheStuckJudgmentThrough()}：聚合层源码不得出现
 *       「算时长 / 读阈值字段 / 写死阈值常量」三类写法；</li>
 *   <li>{@link #rulesHaveDiscriminatingPower()}：每条禁则必须命中一个已知坏样本
 *       —— 防 needle 写错后守卫静默变成空断言（形态同 {@code BusinessClockSourceGuardTest}）。</li>
 * </ol>
 *
 * <p><b>红证实测</b>（见 PR body）：往聚合层注入一句 {@code Duration.ofHours(4)}
 * ⇒ 第 3 条判据必红。</p>
 */
class ProductionTodoAggregationSourceGuardTest {

    /** 聚合层源文件根（Maven 的测试工作目录 = 模块根，故为相对路径）。 */
    private static final Path MAIN_JAVA = Path.of("src/main/java");

    /** 已登记的聚合层文件（唯一一份；新增即红 —— 台账只许缩短）。 */
    private static final String REGISTERED_AGGREGATION_FILE =
            "src/main/java/com/migao/admin/service/ProductionTodoService.java";

    /** 一条禁则 = 一个 needle + 为什么它是缺陷。 */
    private record Rule(String name, String needle, String why) {
    }

    private static final List<Rule> FORBIDDEN = List.of(
            new Rule("自己算等待时长（Duration）", "Duration",
                    "「等了多久」只有 ProductionStuckPointService 能算（它取前道 done_at，"
                            + "没用会被任何更新污染的 updated_at）"),
            new Rule("自己算等待时长（ChronoUnit）", "ChronoUnit",
                    "同上：聚合层只许读判据服务算好的 stalled_hours"),
            new Rule("读卡点服务的阈值字段", "waitThresholdHours",
                    "阈值是判据服务的 @Value 配置项，聚合层只许**透传** threshold_hours / threshold_source"),
            new Rule("写死卡点阈值常量", "DEFAULT_WAIT_THRESHOLD_HOURS",
                    "写死常量 = 第二份阈值 ⇒「阈值从哪来」不再可解释"));

    private static String aggregationSource() throws Exception {
        return Files.readString(Path.of(REGISTERED_AGGREGATION_FILE), StandardCharsets.UTF_8);
    }

    @Test
    @DisplayName("聚合层扫描面 = 恰好已登记的那一个文件（新增待办聚合服务 ⇒ 未登记即红）")
    void aggregationSurfaceIsExactlyTheRegisteredFiles() throws Exception {
        List<String> found;
        try (Stream<Path> stream = Files.walk(MAIN_JAVA)) {
            found = stream.filter(path -> path.getFileName().toString().endsWith("TodoService.java"))
                    .map(Path::toString)
                    .sorted()
                    .toList();
        }
        assertThat(found)
                .as("新增/改名待办聚合服务必须同步登记进本守卫的禁则面（否则新文件不受判据约束）")
                .containsExactly(REGISTERED_AGGREGATION_FILE);
    }

    @Test
    @DisplayName("扫描面非空 + 反向对照：真的读到了透传那两处（否则禁则是空断言）")
    void scanSurfaceIsNotEmpty() throws Exception {
        String source = aggregationSource();

        assertThat(source).as("聚合层源码：%s", REGISTERED_AGGREGATION_FILE).hasSizeGreaterThan(1000);
        assertThat(source)
                .as("正向对照：聚合层必须**真的**在透传卡点判据（缺一 ⇒ 下面的禁则是在扫一份不相干的文件）")
                .contains("stuckPointService.report(")
                .contains("stalled_hours")
                .contains("threshold_source");
    }

    @Test
    @DisplayName("🔴 聚合层不得自己算等待时长 / 不得另设阈值（同一真值两处投影的入口）")
    void aggregationLayerOnlyPassesTheStuckJudgmentThrough() throws Exception {
        String source = aggregationSource();
        for (Rule rule : FORBIDDEN) {
            assertThat(source)
                    .as("禁则「%s」（needle = %s）：%s", rule.name(), rule.needle(), rule.why())
                    .doesNotContain(rule.needle());
        }
    }

    @Test
    @DisplayName("每条禁则都命中一个已知坏样本（防 needle 写错 ⇒ 守卫退化成空断言）")
    void rulesHaveDiscriminatingPower() {
        List<String> badSamples = List.of(
                "double h = Duration.between(pred, now).toMillis() / 3_600_000.0;",
                "long m = ChronoUnit.HOURS.between(pred, now);",
                "view.put(\"threshold_hours\", waitThresholdHours);",
                "view.put(\"threshold_hours\", DEFAULT_WAIT_THRESHOLD_HOURS);");

        for (Rule rule : FORBIDDEN) {
            assertThat(badSamples.stream().filter(sample -> sample.contains(rule.needle())).count())
                    .as("禁则「%s」必须能命中至少一个坏样本（否则它拦不住任何东西）", rule.name())
                    .isPositive();
        }
    }
}
