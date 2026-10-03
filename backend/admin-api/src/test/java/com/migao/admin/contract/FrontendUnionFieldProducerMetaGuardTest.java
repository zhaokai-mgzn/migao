// case_ids: MC-076
package com.migao.admin.contract;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.TreeSet;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 「**前端 types 里声明、后端零生产者**」字段族的类级元守卫（issue #6224，铁律 8）。
 *
 * <h2>为什么需要它（只修一处 = 没修）</h2>
 * 本包的实例缺陷是 {@code AfterSalesTicket.refundMethod}：前端类型声明了它、后端响应 DTO 也有它，
 * 但**全仓没有任何写点**（DB 列无 INSERT/UPDATE、无 setter 实参写入，只有「实体 getter → DTO setter」直通）
 * ⇒ 线上恒不下发、前端以为能读到。**同一形态**在别的字段上照样成立，而没有任何东西会红。
 * 本守卫把「凡声明在前端类型里的**联合类型**字段，必须有后端生产者、否则登记」变成机械判据。
 *
 * <h2>发现规则（自动，不靠人记）</h2>
 * <ol>
 *   <li><b>语料</b>：{@code frontend/admin-web/src/types/index.ts} 里 {@code export interface} 内部、
 *       类型为**字符串字面量并集**（{@code 'a' | 'b' | …}，可选或必填都算）的字段 ⇒ 现取 **19** 个。</li>
 *   <li><b>生产者判定</b>（任一命中即「有生产者」）：
 *       <ul>
 *         <li>P1 Java setter 写入：{@code .set<Field>(<实参>)}，且实参**不是** {@code x.get<Field>()} —— 
 *             后者是**直通**（DTO 回显实体），不是生产；这正是 refundMethod 修前的形态。</li>
 *         <li>P2 请求侧声明：{@code *Request.java} / {@code *Params.java} 里的同名字段（生产者 = 客户端）。</li>
 *         <li>P3 线上键字面量：Java 里出现 {@code "<字段名>"}（Map 型响应 / 注解改名 / SQL 别名）。</li>
 *         <li>P4 SQL 写入：{@code INSERT INTO} / {@code UPDATE} 语句里出现该列名。</li>
 *         <li>P5 ai-agent 写入：{@code backend/ai-agent-service/app/**} 里该名出现在字典键 / 赋值位。</li>
 *       </ul></li>
 * </ol>
 * ⇒ 有人在前端类型里新增一个「没有任何后端生产者」的联合类型字段 ⇒ **当场红并具名**（判据 5）。
 * 现取读数：语料 **19** / 零生产者 **2**（本包落库时，判据 1 现场打印）。
 *
 * <h2>台账两态（每条 = 字段 :: 类别 :: why）</h2>
 * <ul>
 *   <li>{@code FRONTEND_ONLY} —— 该字段的生产者**就是前端自己**（表单状态 / 派生化），后端本就不该下发；</li>
 *   <li>{@code BACKEND_ABSENT_DEBT} —— 后端**恒不下发**而前端**有消费者**（或本应下发）⇒ 缺口，
 *       必须带**跟进 issue 号**，且台账条数**只许缩短**。</li>
 * </ul>
 *
 * <h2>红证（判别力自证，判据 3~11）</h2>
 * 真语料注入（把 {@code refundMethod} 加回 types）⇒ 具名红（判据 3，证明本守卫真能抓住本包修的那个字段）；
 * 内存注入：未登记新字段 / 幽灵条目（字段已删或已获得生产者）/ 债务不带跟单号 / 豁免不写理由 /
 * 台账长过冻结上限 / 扫描面为空（空跑）⇒ 各自判红；同一夹具不注入 ⇒ 不报（判据 4，反向对照）。
 *
 * <h2>边界（照实登记，§19.1）</h2>
 * <ul>
 *   <li>射程 = {@code types/index.ts} 里**字符串字面量并集**的字段。**不覆盖**：非联合类型字段
 *       （{@code string} / {@code number} / 对象）、{@code types/} 之外的 TS 文件、mini-app、运行时动态键。</li>
 *   <li>「有生产者」判定含**宽松项 P3**（Java 里出现 {@code "<字段名>"} 字面量即算）⇒ 名字越通用
 *       （{@code status} / {@code key}）越容易被宽松项兜成「有生产者」。这是**刻意**的取舍：
 *       宁可漏（假绿）不可误（把合规字段判红、逼人往台账里塞），代价是**射程小于字面**。</li>
 *   <li>P1 的「直通 vs 生产」只看**实参文本**形态，判不了「实参虽然长得像 getter 但其实是别的东西」这类语义；
 *       P5 的字典键判定同理是文本面。</li>
 *   <li>本守卫**不跑**被它点名的测试；判不了「那段代码真的会执行」—— 结构面（声明在不在 / 写点在不在）是它保证的全部。</li>
 *   <li>「{@code FRONTEND_ONLY} / {@code BACKEND_ABSENT_DEBT} 的归类」是**人读 + 代码证据**的判定（每条 why 里给锚点），
 *       不是机械推断 ⇒ 评审可逐条质疑（这是本守卫最软的一环，与同类台账同族）。</li>
 *   <li>「只许缩短」的机械半边 = {@code 台账条数 ≤ FROZEN_BASELINE}；**判不了**「有人把冻结上限改大」
 *       —— 那落在 diff 评审里。</li>
 * </ul>
 */
@DisplayName("前端联合类型字段「零生产者」· 类级元守卫（issue #6224）")
class FrontendUnionFieldProducerMetaGuardTest {

    /** 仓根（相对 admin-api 模块目录 —— mvn / surefire 的工作目录）。 */
    private static final Path REPO = Paths.get("../..");
    private static final Path TYPES_FILE = REPO.resolve("frontend/admin-web/src/types/index.ts");
    private static final Path JAVA_MAIN = Paths.get("src/main/java");
    private static final Path RES_MAIN = Paths.get("src/main/resources");
    private static final Path AGENT_APP = REPO.resolve("backend/ai-agent-service/app");

    private static final Pattern INTERFACE_DECL = Pattern.compile("^\\s*export interface (\\w+)");
    private static final Pattern UNION_FIELD = Pattern.compile(
            "^\\s{2}(\\w+)\\??:\\s*((?:'[^']*'\\s*\\|\\s*)*'[^']*')\\s*$");
    private static final Pattern LINE_COMMENT = Pattern.compile("\\s//.*$");

    /**
     * 台账**冻结上限**（只许缩短）：本包落库时的现取条数（判据 12 现场复核）。
     * 🔴 将来**只许改小**；改大 = 把新缺口塞进豁免（评审可见，判据 11 会给出具名读数）。
     */
    private static final int FROZEN_BASELINE = 2;

    // ════════════════════════════ 台账（本包现取读数）════════════════════════════

    /** 台账类别（封闭枚举）。 */
    enum Kind {
        /** 生产者就是前端自己（表单状态 / 派生化），后端本就不该下发。 */
        FRONTEND_ONLY,
        /** 后端恒不下发而前端有消费者（或本应下发）—— 缺口，须带跟进 issue 号。 */
        BACKEND_ABSENT_DEBT
    }

    /** 台账条目：字段 :: 类别 :: 理由（理由必须能给锚点，不许空口说「不是缺口」）。 */
    record Entry(String field, Kind kind, String why) {
    }

    private static Entry entry(String field, Kind kind, String why) {
        return new Entry(field, kind, why);
    }

    /**
     * **零生产者字段台账**（本包现取读数 = 2 条）。
     *
     * <p>读法：该字段在前端 types 里声明，而 {@code discover} 的 P1~P5 生产者判定全部未命中 ⇒ 它必须在这里。</p>
     */
    static List<Entry> registry() {
        return List.of(
                entry("LogisticsFormData.shippingMethod", Kind.FRONTEND_ONLY,
                        "前端发货表单的**状态**字段（`orders/[id]/ship/ShipOrder.tsx` 的 useState；"
                                + "`components/orders/LogisticsForm.tsx` 置 'logistics'）—— 生产者 = 用户在前端的单选，"
                                + "`lib/data-adapter.ts` 同口径注明「shippingMethod 不下发（后端不需要）」⇒ 零生产者是**设计**"),
                entry("LogisticsInfo.shippingMethod", Kind.BACKEND_ABSENT_DEBT,
                        "🔴 后端**恒不下发**（`dto/OrderDetailResponse.java` 的内部类 LogisticsInfo 无此字段；"
                                + "admin-api `src/main` 全仓 grep `shippingMethod|shipping_method` = 0 命中），"
                                + "而前端**有消费者**：`app/(dashboard)/orders/[id]/OrderDetail.tsx` 用它派生装运表单初值 "
                                + "`order.logistics?.shippingMethod === 'none' ? 'none' : 'logistics'` ⇒ 字段恒 undefined ⇒ 恒判成 'logistics'。"
                                + "与 refundMethod **同族**（声明在 types、零生产者、且会被读取），但修法要先裁业务口径"
                                + "（「无需物流」是否要持久化 / 回显）⇒ 交人工裁定，跟单 #6239")
        );
    }

    // ════════════════════════════ 判据 1~2（真实树）════════════════════════════

    @Test
    @DisplayName("判据 1：现取扫描 + 台账双向对齐（未登记即红 / 幽灵条目即红 / 条数只许缩短）")
    void everyZeroProducerFieldIsRegisteredAndBacked() throws IOException {
        Reading reading = discover(TYPES_FILE, loadSources());
        List<String> violations = validate(reading.corpus(), reading.zeroProducer(), registry());

        System.out.println("[#6224 元守卫] 现取：联合类型字段 " + reading.corpus().size()
                + " 个；零生产者 " + reading.zeroProducer().size() + " 个 " + reading.zeroProducer()
                + "；台账 " + registry().size() + " 条（冻结上限 " + FROZEN_BASELINE + "）");
        reading.zeroProducer().forEach(f -> System.out.println("[#6224 元守卫]   " + f));

        assertThat(violations)
                .as("零生产者字段台账有 %d 条违规（未登记 / 幽灵条目 / 缺理由 / 债务缺跟单号 / 台账增长）",
                        violations.size())
                .isEmpty();
    }

    @Test
    @DisplayName("判据 2：扫描面非空（扫不到 = 空跑，必须红）")
    void scanSurfaceIsNotEmpty() throws IOException {
        assertThat(discover(TYPES_FILE, loadSources()).corpus())
                .as("联合类型字段扫描规则失效（或 types 单一源被改名/搬走）⇒ 守卫会静默空跑")
                .isNotEmpty();
    }

    // ════════════════════════════ 判据 3~11：判别力自证 ════════════════════════════

    @Test
    @DisplayName("判据 3：真语料注入 —— 把 refundMethod 加回 types ⇒ 具名判红（本守卫真能抓住本包修的那个字段）")
    void redproof_realCorpusCatchesRefundMethod() throws IOException {
        Reading reading = discover(TYPES_FILE, loadSources());
        Set<String> corpus = new TreeSet<>(reading.corpus());
        Set<String> zero = new TreeSet<>(reading.zeroProducer());
        corpus.add("AfterSalesTicket.refundMethod");
        zero.add("AfterSalesTicket.refundMethod");

        assertThat(validate(corpus, zero, registry()))
                .anySatisfy(v -> assertThat(v)
                        .contains("UNREGISTERED")
                        .contains("AfterSalesTicket.refundMethod"));
    }

    @Test
    @DisplayName("判据 4：夹具不注入 ⇒ 零违规（反向对照：证明红由注入引起，不是夹具本身红）")
    void cleanFixture_hasNoViolation() {
        assertThat(validate(cleanCorpus(), cleanZeroProducer(), cleanRegistry())).isEmpty();
    }

    @Test
    @DisplayName("判据 5：新增零生产者字段**未登记** ⇒ 具名红")
    void redproof_unregisteredNewField() {
        Set<String> zero = new TreeSet<>(cleanZeroProducer());
        zero.add("Demo.mode");

        assertThat(validate(cleanCorpus(), zero, cleanRegistry()))
                .anySatisfy(v -> assertThat(v).contains("UNREGISTERED").contains("Demo.mode"));
    }

    @Test
    @DisplayName("判据 6：幽灵条目（字段已从 types 删掉）⇒ 红")
    void redproof_ghostEntryFieldVanished() {
        Set<String> corpus = new TreeSet<>(cleanCorpus());
        corpus.remove("Demo.status");
        Set<String> zero = new TreeSet<>(cleanZeroProducer());
        zero.remove("Demo.status");

        assertThat(validate(corpus, zero, cleanRegistry()))
                .anySatisfy(v -> assertThat(v)
                        .contains("STALE-LEDGER")
                        .contains("已不在前端 types 里")
                        .contains("Demo.status"));
    }

    @Test
    @DisplayName("判据 7：条目已获得生产者（缺口已修却还挂在台账）⇒ 红（只许缩短）")
    void redproof_staleEntryAfterProducerAppears() {
        assertThat(validate(cleanCorpus(), new TreeSet<>(), cleanRegistry()))
                .anySatisfy(v -> assertThat(v).contains("STALE-LEDGER").contains("已有后端生产者"));
    }

    @Test
    @DisplayName("判据 8：债务条目不带跟进 issue 号 ⇒ 红（豁免必须可追）")
    void redproof_debtWithoutIssueReference() {
        List<Entry> registry = List.of(
                entry("Demo.status", Kind.BACKEND_ABSENT_DEBT, "后端不下发，但没写跟单号"));

        assertThat(validate(cleanCorpus(), cleanZeroProducer(), registry))
                .anySatisfy(v -> assertThat(v).contains("DEBT-WITHOUT-ISSUE").contains("Demo.status"));
    }

    @Test
    @DisplayName("判据 9：豁免不写理由 ⇒ 红（不许空口说「不是缺口」）")
    void redproof_exemptionWithoutReason() {
        List<Entry> registry = List.of(entry("Demo.status", Kind.FRONTEND_ONLY, " "));

        assertThat(validate(cleanCorpus(), cleanZeroProducer(), registry))
                .anySatisfy(v -> assertThat(v).contains("EXEMPT-WITHOUT-REASON").contains("Demo.status"));
    }

    @Test
    @DisplayName("判据 10：台账条数**长过冻结上限** ⇒ 红（只许缩短）")
    void redproof_baselineGrew() {
        List<Entry> registry = new ArrayList<>();
        Set<String> corpus = new TreeSet<>();
        Set<String> zero = new TreeSet<>();
        for (int i = 0; i <= FROZEN_BASELINE; i++) {
            registry.add(entry("Demo.f" + i, Kind.FRONTEND_ONLY, "前端表单状态"));
            corpus.add("Demo.f" + i);
            zero.add("Demo.f" + i);
        }

        assertThat(validate(corpus, zero, registry))
                .anySatisfy(v -> assertThat(v).contains("BASELINE-GREW"));
    }

    @Test
    @DisplayName("判据 11：扫描面为空（发现规则失效）⇒ fail-closed 红")
    void redproof_emptyScanFailsClosed() {
        assertThat(validate(new TreeSet<>(), new TreeSet<>(), cleanRegistry()))
                .anySatisfy(v -> assertThat(v).contains("SCAN-EMPTY"));
    }

    @Test
    @DisplayName("判据 12：现取台账条数 ≤ 冻结上限（只许缩短；读数现场打印）")
    void liveBaselineDoesNotExceedFrozenBaseline() {
        assertThat(registry().size())
                .as("台账条数现取 = %d（冻结上限 %d，只许缩短）", registry().size(), FROZEN_BASELINE)
                .isLessThanOrEqualTo(FROZEN_BASELINE);
    }

    // ════════════════════════════ 夹具（纯内存，可注入）════════════════════════════

    private static Set<String> cleanCorpus() {
        return new TreeSet<>(Set.of("Demo.status", "Demo.kind"));
    }

    private static Set<String> cleanZeroProducer() {
        return new TreeSet<>(Set.of("Demo.status"));
    }

    private static List<Entry> cleanRegistry() {
        return List.of(entry("Demo.status", Kind.FRONTEND_ONLY, "前端表单状态（生产者 = 用户输入）"));
    }

    // ════════════════════════════ 发现 + 校验（纯函数，便于内存注入）════════════════

    /** 一次现取读数：语料（全部联合类型字段）与该语料里的零生产者子集。 */
    record Reading(Set<String> corpus, Set<String> zeroProducer) {
    }

    /** 后端源文件的一条读数（文本 + 它属于哪类判定面）。 */
    private record Src(String path, String text, boolean java, boolean sql, boolean python, boolean requestDto) {
    }

    /**
     * 现取：扫前端 types 的语料，再逐字段跑生产者判定。
     *
     * <p>types 单一源不在 / 读不到 ⇒ {@code assertThat(...).isTrue()} 直接**红**（fail-closed），
     * 绝不允许退化成「扫不到 ⇒ 通过」。</p>
     */
    static Reading discover(Path typesFile, List<Src> sources) throws IOException {
        assertThat(Files.isRegularFile(typesFile))
                .as("前端类型单一源不在：%s ⇒ 扫描面失效（fail-closed，不许空跑成绿）", typesFile)
                .isTrue();
        Set<String> corpus = scanTypes(Files.readString(typesFile));
        Set<String> zero = new TreeSet<>();
        for (String spec : corpus) {
            String field = spec.substring(spec.indexOf('.') + 1);
            if (!isProduced(field, sources)) {
                zero.add(spec);
            }
        }
        return new Reading(corpus, zero);
    }

    /** 语料扫描：{@code export interface} 内的**字符串字面量并集**字段名（`接口名.字段名`）。 */
    static Set<String> scanTypes(String source) {
        Set<String> fields = new TreeSet<>();
        String current = null;
        for (String raw : source.split("\n", -1)) {
            Matcher decl = INTERFACE_DECL.matcher(raw);
            if (decl.find()) {
                current = decl.group(1);
                continue;
            }
            if (current == null) {
                continue;
            }
            Matcher field = UNION_FIELD.matcher(LINE_COMMENT.matcher(raw).replaceFirst(""));
            if (field.matches()) {
                fields.add(current + "." + field.group(1));
            }
        }
        return fields;
    }

    /** 生产者判定（P1~P5，任一命中即「有生产者」）。 */
    static boolean isProduced(String field, List<Src> sources) {
        String pascal = pascal(field);
        String camel = camel(field);
        // P1：setter 写入（排除 `x.setFoo(y.getFoo())` 这种**直通**）
        Pattern setter = Pattern.compile("\\.set" + pascal + "\\s*\\(([^;]*?)\\)\\s*;");
        Pattern passthrough = Pattern.compile("^\\s*[\\w.]*\\.get" + pascal + "\\(\\)\\s*$");
        // P2：请求侧声明（生产者 = 客户端）
        Pattern requestDecl = Pattern.compile(
                "private\\s+[\\w<>,.\\[\\]]+\\s+(?:" + field + "|" + camel + ")\\s*(?:=[^;]*)?;");
        // P3：线上键字面量（Map 型响应 / 注解改名 / SQL 别名）
        Pattern literal = Pattern.compile("\"" + field + "\"");
        // P4：SQL 写入
        Pattern sqlWrite = Pattern.compile("(?is)(INSERT\\s+INTO|UPDATE)\\b[^;]{0,400}?\\b" + field + "\\b");
        // P5：ai-agent 侧的字典键 / 赋值位
        Pattern pythonWrite = Pattern.compile("[\"']" + field + "[\"']\\s*[:=,]|\\b" + field + "\\s*[:=]");

        for (Src s : sources) {
            if (s.java()) {
                Matcher m = setter.matcher(s.text());
                while (m.find()) {
                    if (!passthrough.matcher(m.group(1)).matches()) {
                        return true;
                    }
                }
                if (s.requestDto() && requestDecl.matcher(s.text()).find()) {
                    return true;
                }
                if (literal.matcher(s.text()).find()) {
                    return true;
                }
            } else if (s.sql()) {
                if (sqlWrite.matcher(s.text()).find()) {
                    return true;
                }
            } else if (s.python()) {
                if (pythonWrite.matcher(s.text()).find()) {
                    return true;
                }
            }
        }
        return false;
    }

    /** 台账校验（纯函数，便于内存注入红证）：返回**违规清单**（空 = 通过）。 */
    static List<String> validate(Set<String> corpus, Set<String> zeroProducer, List<Entry> registry) {
        List<String> violations = new ArrayList<>();
        if (corpus.isEmpty()) {
            violations.add("SCAN-EMPTY：扫描面没扫到任何联合类型字段 ⇒ 守卫在空跑（fail-closed）");
            return violations;
        }

        Set<String> registered = new TreeSet<>();
        for (Entry e : registry) {
            registered.add(e.field());
        }

        // ① 未登记即红
        for (String field : zeroProducer) {
            if (!registered.contains(field)) {
                violations.add("UNREGISTERED：前端 types 声明了该字段、后端零生产者，且未登记台账 ⇒ " + field);
            }
        }

        // ② 台账不许空转（幽灵条目：字段没了 / 缺口已修）
        for (Entry e : registry) {
            if (zeroProducer.contains(e.field())) {
                continue;
            }
            if (!corpus.contains(e.field())) {
                violations.add("STALE-LEDGER：登记的字段已不在前端 types 里（字段被删/改名 ⇒ 同步台账）⇒ " + e.field());
            } else {
                violations.add("STALE-LEDGER：登记的字段**已有后端生产者**（缺口已修 ⇒ 从台账删掉这条）⇒ " + e.field());
            }
        }

        // ③ 豁免必须给理由；债务必须可追
        for (Entry e : registry) {
            if (e.why() == null || e.why().isBlank()) {
                violations.add("EXEMPT-WITHOUT-REASON：台账条目必须写理由 ⇒ " + e.field());
            }
            if (e.kind() == Kind.BACKEND_ABSENT_DEBT && !e.why().matches("(?s).*#\\d{3,}.*")) {
                violations.add("DEBT-WITHOUT-ISSUE：登记为债务必须带跟进 issue 号 ⇒ " + e.field());
            }
        }

        // ④ 只许缩短（条数现取）
        if (registry.size() > FROZEN_BASELINE) {
            violations.add("BASELINE-GREW：台账条数现取 = " + registry.size() + "，冻结上限 = " + FROZEN_BASELINE
                    + "（只许缩短；新增零生产者字段请修字段或补生产者，不要塞进台账）");
        }
        return violations;
    }

    // ════════════════════════════ 读源 ════════════════════════════

    static List<Src> loadSources() throws IOException {
        List<Src> sources = new ArrayList<>();
        for (Path p : files(JAVA_MAIN, ".java")) {
            String name = p.getFileName().toString();
            sources.add(new Src(p.toString(), Files.readString(p), true, false, false,
                    name.endsWith("Request.java") || name.endsWith("Params.java")));
        }
        for (Path p : files(RES_MAIN, ".sql", ".xml")) {
            sources.add(new Src(p.toString(), Files.readString(p), false, true, false, false));
        }
        for (Path p : files(AGENT_APP, ".py")) {
            sources.add(new Src(p.toString(), Files.readString(p), false, false, true, false));
        }
        return sources;
    }

    private static List<Path> files(Path root, String... suffixes) throws IOException {
        if (!Files.isDirectory(root)) {
            return List.of();
        }
        try (Stream<Path> walk = Files.walk(root)) {
            return walk.filter(Files::isRegularFile)
                    .filter(p -> {
                        String s = p.toString();
                        for (String suffix : suffixes) {
                            if (s.endsWith(suffix)) {
                                return true;
                            }
                        }
                        return false;
                    })
                    .sorted()
                    .toList();
        }
    }

    static String camel(String field) {
        String[] parts = field.split("_");
        StringBuilder sb = new StringBuilder(parts[0]);
        for (int i = 1; i < parts.length; i++) {
            sb.append(Character.toUpperCase(parts[i].charAt(0))).append(parts[i].substring(1));
        }
        return sb.toString();
    }

    static String pascal(String field) {
        String c = camel(field);
        return Character.toUpperCase(c.charAt(0)) + c.substring(1);
    }
}
