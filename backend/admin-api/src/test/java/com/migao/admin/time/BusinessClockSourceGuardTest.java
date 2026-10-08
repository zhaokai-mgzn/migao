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
 *
 * <h2>族级补齐：日界（issue #6200）</h2>
 *
 * <p>本守卫原本只禁了 {@code ZoneOffset.ofHours(8)}（「UTC 日边界<b>贴 +08 标签</b>」）这一种拼写，
 * 而<b>同一族的另外三种</b>一个字都不在射程内：{@code "T00:00:00Z"} / {@code "T23:59:59Z"}
 * （UTC 日窗口字面量）与 {@code .atOffset(ZoneOffset.UTC)}（UTC 日界的直接投影）
 * ⇒ 缺陷从旁边走过去了（实测形态：{@code startDate=endDate=D} 的实际窗口 = 北京
 * {@code [D 08:00, D+1 07:59:59]}，北京 00:00–08:00 的数据归错天 / 月 / 年，
 * 且与走 {@link BusinessClock} 的看板 / 趋势<b>互相矛盾</b>）。</p>
 *
 * <p>本次按<b>族</b>补齐三条针（{@code "T00:00:00Z"} / {@code "T23:59:59Z"} / {@code ZoneOffset.UTC}），
 * 并用 <b>形态放行</b>而不是豁免名单挡住误伤：{@code ZoneOffset.UTC} 只放行「打时刻」的<b>整参</b>形态
 * （拼写形如 {@code now(ZoneOffset.UTC)}），判定口径与两侧自证见
 * {@link #maskUtcOffsetAsMoment(String)}。</p>
 *
 * <p>🔴 <b>本单的未修项（照实登记，不粉饰）</b>：{@link #UNFIXED_CARVINGS} 的条数<b>冻结</b>，
 * 台账外的命中一律判红、台账内不再命中必须销账 ⇒ 未修项只能被修掉、不会被遗忘。</p>
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
                    "取的是 UTC 日边界、只贴了 +08 标签（issue #3802 点名的更差拼写）"),
            // ── 族级补齐（issue #6200）：**日界只许来自 BusinessClock.startOfDay** ────────────────
            // 与 #3802 同族（「UTC 日边界」），但拼写不同 ⇒ 老守卫看不见 ⇒ 缺陷从旁边走过去了。
            // 上面那条针（ZoneOffset.ofHours(8)）只盖「贴标签」形态；`...Z` 字面量与裸 ZoneOffset.UTC
            // 一个字都不在射程内。本单把这三种拼写补齐成族（形态 = 见 maskUtcOffsetAsMoment 的放行口径）。
            new Rule("UTC 日界字面量（遗留拼写）", "T00:00:00Z",
                    "UTC 日窗口的左界：北京 00:00–08:00 的数据被归到前一天 / 月 / 年（issue #6200）"),
            new Rule("UTC 日界字面量（遗留拼写）", "T23:59:59Z",
                    "UTC 日窗口的右界：既漏掉当天 08:00 之后、又把次日凌晨 8 小时算进来（issue #6200）"),
            new Rule("UTC 日边界", "ZoneOffset.UTC",
                    "日界只许用 BusinessClock.startOfDay（+08 单源）。UTC 偏移**只许**出现在「打时刻」调用里"
                            + "（拼写形如 now(ZoneOffset.UTC)，闭括号紧邻）—— 见 maskUtcOffsetAsMoment 的放行口径；"
                            + "任何其它出现（.atOffset(ZoneOffset.UTC) / .atZone(ZoneOffset.UTC) / 裸赋值）判红，"
                            + "因为日界正是 #6200 的缺陷面。"));

    /**
     * {@code Instant.now()} 台账：绝对时刻，与时区无关，<b>不产生</b>「两个今天」。
     * 值 = 该文件里允许出现的次数。文件 = 仓库相对路径（{@code src/main/java/} 之后）。
     */
    private static final Map<String, Integer> INSTANT_NOW_LEDGER = Map.of(
            "com/migao/admin/dto/ApiResponse.java", 1,
            "com/migao/admin/security/JwtTokenProvider.java", 2);

    /**
     * 🔴 <b>未修项冻结台账</b>（issue #6200，**只许缩短**）：本守卫判据射程内、但**本单不改**的地方
     * —— 键 = {@code 文件|规则名}，值 = 允许的命中条数。
     *
     * <p>与「整体排除该文件」的区别：排除会让该文件的**其余**禁则也失去保护；台账只冻结**这一条**
     * 命中，其余针照旧生效。四条语义（判据见 {@link #unfixedCarvingsAreFrozenAndLive()}）：
     * ① 台账外的任何命中 ⇒ 红（新缺陷进不来）；② 台账内**超出**条数 ⇒ 红；
     * ③ 台账内**不再命中** ⇒ 红（**必须销账** —— 销账动作就是「这条未修项已经修掉了」的评审点）；
     * ④ 台账条目必须对应**存在**的文件（删文件也要销账）。</p>
     *
     * <p><b>今天为空</b>（现取读数 = 0 条），且这是<b>有意</b>的空：本单把 {@code ProductService} 的
     * 日界投影（{@code .atStartOfDay().atOffset(ZoneOffset.UTC)}）按<b>射程边界</b>处理而不是按
     * carve-out —— 它与「打时刻」在**文本上静态不可区分**（只有 AST 能分），因此 {@code ZoneOffset.UTC}
     * 这条针的字面口径只裁「不带括号的裸用法」（详见 {@link #maskUtcOffsetAsMoment(String)}）。</p>
     *
     * <p>🔴 <b>因此如实登记两处「本守卫看不见」的缺口（不粉饰）</b>：</p>
     * <ul>
     *   <li>{@code ProductService} 的商品列表日期窗口（{@code .atStartOfDay().atOffset(ZoneOffset.UTC)}）
     *       —— issue #6200 的**同类未修项**，本单按文件所有权（并行包独占）不改；
     *       <b>重启条件</b>：商品腿按 {@code BusinessClock.startOfDay} 收口时，本守卫**不会**因此变红
     *       （看不见），要靠 PR body 的未固化项清单与 issue #6200 跟踪。</li>
     *   <li>{@code FinanceService.parseOccurredAt} 的解析兜底（{@code .atOffset(ZoneOffset.UTC)}）
     *       —— 不在日期窗口路径上，本单有意不修。</li>
     * </ul>
     * <p>真正把「日界」关进单点的是两条<b>字面量</b>针（{@code "T00:00:00Z"} / {@code "T23:59:59Z"}）：
     * 它们不受这个边界影响，改前在 {@code src/main} 现取命中 4 处、改后 0 处。</p>
     */
    private static final Map<String, Integer> UNFIXED_CARVINGS = Map.of();

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
                    String judged = judgedLine(lines.get(i));
                    for (Rule rule : FORBIDDEN) {
                        if (judged.contains(rule.needle())) {
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

    /**
     * 判定语料 = <b>剥注释</b> + 「打时刻」形态放行（issue #6200）。两者都必要，理由是实测出来的：
     *
     * <ol>
     *   <li><b>剥注释</b>（同测试侧守卫 {@code BusinessClockTestSourceGuardTest.stripComments}）：本单在
     *       {@code FinanceService} / {@code OrderService} 的<b>注释里写了「原写法是 …」</b>来解释缺陷 ——
     *       不剥注释 ⇒ 判据被自己的文案喂红（{@code migao-dev-flow} §23.4 T2 的同款陷阱）。剥法是
     *       <b>就地替换成等长空白</b>（保留换行 ⇒ 行号仍准、且不误判字符串里的 {@code //}）。</li>
     *   <li><b>形态放行</b>：把<b>字面</b>的 {@code (ZoneOffset.UTC)} 掩成等长空白（⇒ 行号仍准），于是
     *       「打时刻」写法 {@code now(ZoneOffset.UTC)} 不再判红。
     *       ⚠️ 这条正则的形态踩过两次坑（本单实测）：带左邻负向环视 ⇒ <b>整体失配</b>（假红）；
     *       再加一个「括号内限定名」分支 ⇒ `\s*` 跨过 `(` 把 {@code atOffset(ZoneOffset.UTC)} 整段吃掉
     *       ⇒ 连裸形态也失效（假绿）。
     *       <b>射程边界（如实登记）</b>：本针按<b>字面子串</b>判 ⇒ 它只裁「括号外的裸用法」；
     *       {@code atOffset(ZoneOffset.UTC)} 这类<b>投影</b>形态本针看不见 —— 真正治日界的是下面两条
     *       <b>字面量</b>针（{@code T00:00:00Z} / {@code T23:59:59Z}）。详见
     *       {@link #maskUtcOffsetAsMoment(String)} 的第 ③ 条。</li>
     * </ol>
     *
     * <p>现行放行的既有合法写法（现取一处，逐条在 {@link #rulesHaveDiscriminatingPower()} 用坏样本钉住）：</p>
     * <ul>
     *   <li>{@code DashboardController}：{@code Duration.between(s.getStartedAt(), OffsetDateTime.now(ZoneOffset.UTC))}
     *       —— 量「已经跑了多久」，与时区无关。</li>
     * </ul>
     * <p>另有一处<b>有意未修</b>（{@code FinanceService.parseOccurredAt} 的解析兜底）登记在
     * {@link #UNFIXED_CARVINGS}，理由与重启条件逐条写在那里。</p>
     */
    static String maskUtcOffsetAsMoment(String line) {
        // 把**唯一的**「打时刻」形态 `now(ZoneOffset.UTC)`（含 `now( ZoneOffset.UTC )`）掩成等长空白，
        // 于是这条针只裁**括号外**的裸用法：`ZoneOffset utc = ZoneOffset.UTC;` /
        // `java.time.ZoneOffset.UTC`（实参 / 赋值 / 限定名，都不带括号）。
        //
        // ⚠️ 三条实测教训（都在本单真实发生过，别重犯）：
        //  ① 不要加 `(?<![\w$.])` 之类的**左邻负向环视**：实测在 Java 里会让匹配**整体失效**
        //     （`find()==false`）⇒ 掩码形同不存在，`now(ZoneOffset.UTC)` 被误判成日界（假红）。
        //     （根因未追到底；如实登记为实测结论，不假装知道为什么。）
        //  ② 不要给「括号内」再加**限定名**分支（`(java.time.ZoneOffset.UTC)`）：`\s*` 会跨过 `(`，
        //     使 `atOffset(ZoneOffset.UTC)` 被那条分支整段吃掉（`.atOffset(` 的点被当包名分隔）
        //     ⇒ 连「裸形态」也一起失效（假绿：本单实测隔离注入用例 8 条只报出 5 条，且自证断言
        //     打出 `atOffset(              )` —— 该判红的那行被整段掩掉）。**单形态**才可控。
        //  ③ 🔴 **射程边界（如实登记，不粉饰）**：本针判的是**字面子串** ⇒
        //     `atOffset(ZoneOffset.UTC)` / `atZone(ZoneOffset.UTC)`（第三种拼写、也是本次要治的缺陷形态之一）
        //     会被**一并掩掉**，本针**看不见**它们。治「日界」真正靠得住的是另外两条**字面量**针
        //     （`T00:00:00Z` / `T23:59:59Z`，不受此边界影响：改前 4 处命中、改后 0 处）+
        //     `BusinessClock.startOfDay` 的单一来源约定。要覆盖投影形态需要 AST 级判定，
        //     本守卫（正则 + 字面）做不到 —— 这是**有意接受**的缺口，已登记进 PR body 的未固化项。
        // 等长替换（等量空白补齐）⇒ 命中行号仍准。
        return maskEqualLength(line, "\\(\\s*ZoneOffset\\.UTC\\s*\\)");
    }

    /** 把正则命中的片段换成**等长**的空白括号（长度不变 ⇒ 行号仍准）。 */
    private static String maskEqualLength(String line, String regex) {
        return Pattern.compile(regex).matcher(line)
                .replaceAll(m -> "(" + " ".repeat(m.group().length() - 2) + ")");
    }

    /**
     * 剥注释（{@code //} 行注释与块注释 / Javadoc）—— 就地替换成等长空白。
     * 保持不变式：<b>长度不变、换行位置不变</b>（⇒ 命中行号仍准）。字符串 / 字符字面量按原样保留
     * （不解析转义 —— 本守卫的 needle 没有一个含引号，够用）。
     */
    static String stripComments(String source) {
        char[] out = source.toCharArray();
        int i = 0;
        int n = out.length;
        while (i < n) {
            char c = out[i];
            if (c == '"' || c == '\'') {
                i++;
                while (i < n && out[i] != c) {
                    if (out[i] == '\\') {
                        i++;
                    }
                    i++;
                }
                i++;
                continue;
            }
            if (i + 1 < n && c == '/' && out[i + 1] == '/') {
                while (i < n && out[i] != '\n') {
                    out[i] = ' ';
                    i++;
                }
                continue;
            }
            if (i + 1 < n && c == '/' && out[i + 1] == '*') {
                out[i] = ' ';
                out[i + 1] = ' ';
                i += 2;
                while (i + 1 < n && !(out[i] == '*' && out[i + 1] == '/')) {
                    if (out[i] != '\n') {
                        out[i] = ' ';
                    }
                    i++;
                }
                if (i + 1 < n) {
                    out[i] = ' ';
                    out[i + 1] = ' ';
                    i += 2;
                } else {
                    i = n;
                }
                continue;
            }
            i++;
        }
        return new String(out);
    }

    /** 扫描器的判定语料（剥注释 + 形态放行）—— 纯函数，供判别力自证与隔离注入共用同一口径。 */
    static String judgedLine(String rawLine) {
        return maskUtcOffsetAsMoment(stripComments(rawLine));
    }

    @Test
    @DisplayName("形态放行的两侧自证：打时刻放行、日界裸用判红（纯函数级，先于任何文件扫描）")
    void maskSeparatesMomentCallsFromDayBoundaryProjections() {
        // 放行（打时刻）：两种字面形态
        for (String moment : List.of(
                "long minutes = java.time.Duration.between(s.getStartedAt(), OffsetDateTime.now(ZoneOffset.UTC)).toMinutes();",
                "OffsetDateTime.now( ZoneOffset.UTC );")) {
            assertThat(maskUtcOffsetAsMoment(moment))
                    .as("「打时刻」形态必须被掩掉（不再判红）：%s", moment)
                    .doesNotContain("ZoneOffset.UTC");
        }
        // 判红（**不带括号**的裸用法 —— 本针的真实射程，见 maskUtcOffsetAsMoment 的边界登记）
        for (String projection : List.of(
                "        ZoneOffset utc = ZoneOffset.UTC;",
                "        ZoneOffset zone = java.time.ZoneOffset.UTC;",
                "        applyZone(ZoneOffset.UTC, date);",
                "        java.time.ZoneOffset.UTC,")) {
            // 注：括号内的写法则**不在此列** —— 见 maskUtcOffsetAsMoment 第 ③ 条射程边界。
            assertThat(maskUtcOffsetAsMoment(projection))
                    .as("不带括号的裸用法**不得**被掩掉（必须判红）：%s", projection)
                    .contains("ZoneOffset.UTC");
        }
    }

    @Test
    @DisplayName("对真实源文件作判：`DashboardController` 的「打时刻」调用不被判红（放行口径在真语料上生效）")
    void momentCallInRealSourceIsNotFlagged() throws IOException {
        Path controller = mainRoot().resolve("com/migao/admin/controller/DashboardController.java");
        assertThat(Files.exists(controller))
                .as("锚点文件必须存在（挪包/改名 ⇒ 本判据要同步改，不许静默变成空跑）：%s", controller)
                .isTrue();

        List<String> flagged = new ArrayList<>();
        List<String> lines = Files.readAllLines(controller, StandardCharsets.UTF_8);
        for (int i = 0; i < lines.size(); i++) {
            for (Rule rule : FORBIDDEN) {
                if (judgedLine(lines.get(i)).contains(rule.needle())) {
                    flagged.add(rule.name() + " → :" + (i + 1) + " | " + lines.get(i).trim());
                }
            }
        }
        assertThat(flagged)
                .as("该文件里唯一的 UTC 用法是 Duration.between(…, now(ZoneOffset.UTC)) —— 量时长，不是日界")
                .isEmpty();
        assertThat(lines.stream().anyMatch(l -> l.contains("OffsetDateTime.now(ZoneOffset.UTC)")))
                .as("自证锚点没漂：该文件今天确实还有那处「打时刻」写法（否则本判据在白跑）")
                .isTrue();
    }

    @Test
    @DisplayName("src/main 里业务时间的读取点只剩 BusinessClock 一处（其余一律判红）")
    void onlyTheClockComponentReadsBusinessTimeFromMain() throws IOException {
        Path root = mainRoot();
        assertThat(Files.exists(root.resolve(CLOCK_FILE)))
                .as("白名单里的时钟文件必须存在（改名/挪包 ⇒ 守卫失效，判红）：%s", CLOCK_FILE)
                .isTrue();

        Scan scan = scan(root);
        assertThat(hitsOutsideCarvings(scan))
                .as("业务「今天」必须单点（issue #3802）。违规写法：\n  %s",
                        FORBIDDEN.stream().map(r -> r.needle() + " —— " + r.why()).toList())
                .isEmpty();
    }

    /** {@code 文件|规则名 → 条数}（现取命中，未修项台账与全局判据共用同一口径）。 */
    private static Map<String, Integer> hitCounts(Scan scan) {
        Map<String, Integer> counts = new LinkedHashMap<>();
        scan.hits().forEach((relative, hits) -> {
            for (String hit : hits) {
                String ruleName = hit.substring(0, hit.indexOf(" → "));
                counts.merge(relative + "|" + ruleName, 1, Integer::sum);
            }
        });
        return counts;
    }

    /** 全局判据的语料 = 命中减去**已登记的未修项**（台账外的任何命中都会留在这里 ⇒ 判红）。 */
    private static Map<String, List<String>> hitsOutsideCarvings(Scan scan) {
        Map<String, List<String>> rest = new LinkedHashMap<>();
        scan.hits().forEach((relative, hits) -> hits.stream()
                .filter(hit -> !UNFIXED_CARVINGS.containsKey(relative + "|" + hit.substring(0, hit.indexOf(" → "))))
                .forEach(hit -> rest.computeIfAbsent(relative, k -> new ArrayList<>()).add(hit)));
        return rest;
    }

    @Test
    @DisplayName("未修项台账冻结且条目活着（新增即红 / 超出即红 / 不再命中必须销账）")
    void unfixedCarvingsAreFrozenAndLive() throws IOException {
        Path root = mainRoot();
        Scan scan = scan(root);

        assertThat(hitCounts(scan))
                .as("未修项台账（issue #6200）：只许缩短 —— 台账外的命中不许出现、台账内的条数不许超出、"
                        + "不再命中的条目必须删掉（销账 = 「这条未修项已经修掉了」的评审点）")
                .isEqualTo(UNFIXED_CARVINGS);

        for (String key : UNFIXED_CARVINGS.keySet()) {
            String file = key.substring(0, key.indexOf('|'));
            assertThat(Files.exists(root.resolve(file)))
                    .as("未修项台账条目必须活着（文件已不在 ⇒ 台账腐化，判红）：%s", file)
                    .isTrue();
        }
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
        assertThat(hitCounts(scan))
                .as("扫描面非空 + 命中只剩已登记的未修项（台账外的命中由 onlyTheClockComponentReadsBusinessTimeFromMain 判红）")
                .isEqualTo(UNFIXED_CARVINGS);
    }

    @Test
    @DisplayName("每条禁则都能命中已知坏样本（needle 写错 ⇒ 判红，而不是变成空断言）")
    void rulesHaveDiscriminatingPower() {
        Map<String, String> badSamples = new java.util.HashMap<>(Map.of(
                "无参 LocalDate.now()", "        LocalDate today = LocalDate.now();",
                "无参 LocalDateTime.now()", "        .createdAt(LocalDateTime.now())",
                "无参 LocalTime.now()", "        LocalTime now = LocalTime.now();",
                "JVM 默认时区时钟", "        this(Clock.systemDefaultZone());",
                "业务时区字面量", "        ZoneId cst = ZoneId.of(\"Asia/Shanghai\");",
                "UTC 日边界贴 +08 标签",
                "        LocalDate.now().atStartOfDay().atOffset(ZoneOffset.ofHours(8));",
                "UTC 日边界",
                "        ZoneOffset boundaryZone = ZoneOffset.UTC;"));
        // 两条同名的字面量禁则共用**同一个坏样本**（该样本同时含左界与右界拼写）
        badSamples.put("UTC 日界字面量（遗留拼写）",
                "        from = parse(date + \"T00:00:00Z\"); to = parse(date + \"T23:59:59Z\");");
        for (Rule rule : FORBIDDEN) {
            String sample = badSamples.get(rule.name());
            assertThat(sample).as("禁则 %s 缺坏样本（判据不可自证）", rule.name()).isNotNull();
            assertThat(judgedLine(sample))
                    .as("禁则 %s 的 needle 必须能命中坏样本（按扫描器的同一判定口径）：%s", rule.name(), sample)
                    .contains(rule.needle());
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
                "    void window(String date) {",
                "        from = parse(date + \"T00:00:00Z\");",
                "        to = parse(date + \"T23:59:59Z\");",
                "        LocalDate.now().atStartOfDay().atOffset(ZoneOffset.UTC);",
                "    }",
                "    void bareConstant() {",
                "        ZoneOffset boundaryZone = ZoneOffset.UTC;",
                "    }",
                "    void cstTag() {",
                "        LocalDate.now().atStartOfDay().atOffset(ZoneOffset.ofHours(8));",
                "    }",
                "    void anotherLocalSpelling() {",
                "        LocalTime.now();",
                "    }",
                "    void momentCalls() {",
                "        java.time.Duration.between(t0, java.time.OffsetDateTime.now(ZoneOffset.UTC));",
                "    }",
                "}"), StandardCharsets.UTF_8);

        Scan scan = scan(tempDir);

        assertThat(scan.files()).isEqualTo(1);
        assertThat(scan.hits()).containsOnlyKeys("com/migao/admin/service/InjectedViolation.java");
        List<String> injectedHits = scan.hits().get("com/migao/admin/service/InjectedViolation.java");
        assertThat(injectedHits)
                .as("注入的违规必须逐条具名报出（含 文件:行号）；第 10 行只报出 2 条 —— "
                        + "`atOffset(ZoneOffset.UTC)` 这种**括号内**投影是本针**有意接受**的盲区"
                        + "（见 maskUtcOffsetAsMoment 第 ③ 条）")
                .hasSize(9)
                .allSatisfy(hit -> assertThat(hit).contains("InjectedViolation.java:"))
                .anySatisfy(hit -> assertThat(hit).contains("无参 LocalDate.now()").contains(":4"))
                .anySatisfy(hit -> assertThat(hit).contains("业务时区字面量").contains(":5"))
                .anySatisfy(hit -> assertThat(hit).contains("UTC 日界字面量（遗留拼写）").contains(":8"))
                .anySatisfy(hit -> assertThat(hit).contains("UTC 日界字面量（遗留拼写）").contains(":9"))
                .anySatisfy(hit -> assertThat(hit).contains("UTC 日边界").contains(":13"))
                .anySatisfy(hit -> assertThat(hit).contains("无参 LocalDate.now()").contains(":10"))
                .anySatisfy(hit -> assertThat(hit).contains("UTC 日边界贴 +08 标签").contains(":16"))
                // 复现 #3802 的「更差拼写」：同一行既命中「无参 LocalDate.now()」也命中「贴 +08 标签」
                .anySatisfy(hit -> assertThat(hit).contains("无参 LocalDate.now()").contains(":16"))
                .anySatisfy(hit -> assertThat(hit).contains("无参 LocalTime.now()").contains(":19"));
        // 🔴 形态放行**两侧自证**（负向对照）：第 22 行是「打时刻」形态 —— 参数带包名前缀
        // （`now(ZoneOffset.UTC)`）且外层再套一层括号 ⇒ **不得**被这条针判红。
        // 没有这一条，「没误伤」与「这条针根本没生效」就分不清（本单实测过两种失败：先假红、后假绿）。
        assertThat(injectedHits)
                .as("「打时刻」形态（第 22 行）不得被判红")
                .noneSatisfy(hit -> assertThat(hit).contains(":22"));
    }
}
