// case_ids: AS-012

package com.migao.admin.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.TreeSet;
import java.util.function.Function;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 🧱 <b>类级元守卫（issue #6220）：同一事务里的多个副作用，必须逐个登记并发保护</b>。
 *
 * <h2>为什么需要它（只修一处 = 没修）</h2>
 * 实例判据（{@code AfterSalesConcurrentResolveRealDbTest}，case AS-011）只保证
 * {@code updateTicketStatus} 这<b>一个</b>入口在并发下恰一个赢家。而 #6220 的真实教训是
 * <b>「只保护了其中一个副作用」</b>：同一事务里 {@code linkRefundToOrderAndFinance} 有 DB 原子条件更新
 * （正对照：并发下 {@code refundOver=false}），{@code maybeRestockOnReturn} 零保护
 * ⇒ 并发数 = 回补次数（实测 98→106、台账 4 行、时间线 5 行）。
 * 下一个人在<b>别的方法</b>里写下同样的形态（状态写 + 多个副作用，只保护其中一个）照样没人拦。
 *
 * <h2>判据（每条都会红）</h2>
 * <ol>
 *   <li><b>扫描器非空跑自证</b>：现取候选集为空 ⇒ 先红（参数被改名 / 形态变了不是「通过」，而是「判据失明」）。</li>
 *   <li><b>未登记即红</b>：{@code src/main/java/com/migao/admin/service/*.java} 里满足
 *       「{@code @Transactional} ∧ 体内有 {@code setStatus(} ∧ ≥2 处副作用调用」的方法，
 *       每一个必须出现在台账 {@code entries}（已保护）或 {@code unverified}（豁免 + 理由）里。</li>
 *   <li><b>台账不许给不存在的对象盖章</b>：台账里的每个方法名必须仍能在现取候选集里找到（改名 / 删除 ⇒ 红）。</li>
 *   <li><b>登记未被兑现即红</b>：{@code entries[].evidence} = {@code <仓库相对路径>::<文本锚>}，
 *       左侧文件必须存在、右侧必须在该文件里<b>逐字出现</b> ⇒ 防「给不存在的保护盖章」。</li>
 *   <li><b>本单的钉</b>：{@code AfterSalesTicketService#updateTicketStatus} 必须以
 *       {@code verdict=guarded} 在册、evidence 指向条件更新谓词、且写明 {@code case_ids}；
 *       把条件更新退回无条件 {@code updateById} ⇒ 第 4 条与本条同时红。</li>
 *   <li><b>豁免台账只许缩短</b>：{@code unverified} 必须是冻结基线 {@code unverified_baseline} 的<b>子集</b>
 *       （新增豁免 ⇒ 红）；条数<b>现取</b>（不写死在测试代码里，读数打印在断言消息上）。</li>
 *   <li><b>豁免必须写明理由</b>：每条 {@code unverified} 的 {@code reason} / {@code issue} /
 *       {@code restart_condition} 三样非空 ⇒ 防「把未知写成已解决」。</li>
 *   <li><b>判别力自证</b>：用<b>合成语料</b>在内存里跑同一套判定 —— 未登记 / 台账未兑现 / 新增豁免 /
 *       扫描器失明四种坏形态各自判红，合规语料判绿。没有这条，「判据恒绿」与「判据有效」看起来一样。</li>
 * </ol>
 *
 * <p><b>未固化项（如实登记，不粉饰）</b>：见台账的 {@code coverage_boundary} ——
 * ① 形态判据不做 AST 解析（换措辞可绕过；真实防线仍是各自的实例判据）；
 * ② 本守卫只保证「登记存在且兑现」，<b>不保证</b> {@code entries} 里声称的保护真的有效；
 * ③ 9 条 {@code unverified} 是**本单未核验**的诚实登记（其中 {@code InboundOrderService#post}（重复建库存批次）
 * 与 {@code ProductionOperationCommandService#update}（追加价格版本）标为**疑似同类形态**，
 * 已在 PR body 登记为观察项）；④ 本守卫**不改**任何门禁的通过条件、不新增豁免。</p>
 */
@DisplayName("🧱 类级元守卫（#6220）：同一事务内多副作用方法必须逐个登记并发保护（未登记即红 + 豁免只许缩短）")
class AfterSalesSideEffectConcurrencyMetaGuardTest {

    /** 模块根（Surefire 的工作目录 = {@code backend/admin-api}）；台账里的引用一律是**仓库相对全路径**。 */
    private static final String MODULE = "backend/admin-api";
    private static final String SERVICE_DIR = MODULE + "/src/main/java/com/migao/admin/service";
    private static final String LEDGER_PATH = MODULE + "/src/test/resources/after-sales-sideeffect-concurrency-ledger.json";

    /** 本单的核心对象：它必须在册（否则说明扫描器已失明）。 */
    private static final String TARGET_METHOD = "AfterSalesTicketService#updateTicketStatus";

    /** 条件更新的兑现锚（第 5 条判据）：退回无条件 updateById ⇒ 它在源码里消失 ⇒ 红。 */
    private static final String CONDITIONAL_UPDATE_ANCHOR = ".eq(\"status\", currentStatus)";

    private static final Pattern TRANSACTIONAL = Pattern.compile("@Transactional");
    private static final Pattern STATUS_WRITE = Pattern.compile("setStatus\\(");
    private static final Pattern SIDE_EFFECT = Pattern.compile(
            "(?i)\\b\\w*(?:Mapper|Service)\\.(?:insert|updateById|update|delete|deleteById|save"
                    + "|restoreStock|deductStock)\\s*\\(");
    private static final Pattern METHOD_NAME = Pattern.compile("(\\w+)\\s*\\(");

    // ────────────────────────────────────────────── 判据 1~7：真语料

    @Test
    @DisplayName("未登记即红：service 包内「@Transactional + setStatus + ≥2 副作用」的方法必须全部登记")
    void everyMultiSideEffectStatusTransitionIsRegistered() throws IOException {
        Path root = repoRoot();
        Set<String> live = scanPackage(root.resolve(SERVICE_DIR));
        Ledger ledger = loadLedger(root.resolve(LEDGER_PATH));
        List<String> violations = violations(live, ledger, p -> readOrNull(root.resolve(p)));

        // 条数**现取**（不写死在断言里）：豁免只许缩短这条判据的数就在这行读数上
        System.out.println("[#6220 类级守卫] 现取候选=" + live.size()
                + " 已保护=" + ledger.entries().size()
                + " 豁免=" + ledger.unverified().size()
                + " 豁免基线=" + ledger.baseline().size()
                + " 候选=" + live);
        assertThat(violations)
                .as("同一事务内的多个副作用必须逐个登记并发保护（未登记 / 未兑现 / 新增豁免 ⇒ 红）")
                .isEmpty();
        assertThat(live).as("本守卫的核心对象必须在场（形态被改名 ⇒ 判据失明要当场暴露，不是静默通过）")
                .contains(TARGET_METHOD);
    }

    @Test
    @DisplayName("判别力自证：四种坏形态在合成语料上各自判红；合规语料不红")
    void guardHasDiscriminatingPower() {
        // 合规形态：状态写 + 条件更新谓词 + 第二个副作用（**在册且兑现**）
        String goodSource = """
                package com.migao.admin.service;
                class Demo {
                    @Transactional
                    public void resolve(String id) {
                        ticket.setStatus("resolved");
                        transition.eq("status", currentStatus);
                        ticketMapper.update(ticket, transition);
                        timelineMapper.insert(row);
                    }
                }
                """;
        // 坏形态：状态写 + **无条件** updateById + 第二个副作用（= #6220 的原始形态）
        String badSource = """
                package com.migao.admin.service;
                class Demo {
                    @Transactional
                    public void resolve(String id) {
                        ticket.setStatus("resolved");
                        ticketMapper.updateById(ticket);
                        timelineMapper.insert(row);
                    }
                }
                """;
        // 对照：不写状态的方法（不该被拖进这份台账）
        String unrelatedSource = """
                package com.migao.admin.service;
                class Demo {
                    @Transactional
                    public void touch(String id) {
                        ticketMapper.updateById(ticket);
                        timelineMapper.insert(row);
                    }
                }
                """;

        Set<String> goodLive = scan("Demo", goodSource);
        Set<String> badLive = scan("Demo", badSource);
        assertThat(goodLive).as("形态判据必须认得出「状态写 + ≥2 副作用」").containsExactly("Demo#resolve");
        assertThat(badLive).as("同一形态的坏写法也必须进候选集").containsExactly("Demo#resolve");
        assertThat(scan("Demo", unrelatedSource)).as("对照：没有 setStatus 的方法不进候选集（避免把无关事务方法拖进台账）")
                .isEmpty();

        Function<String, String> sources = p -> switch (p) {
            case "backend/admin-api/src/main/java/com/migao/admin/service/Demo.java" -> badSource;
            case "backend/admin-api/src/main/java/com/migao/admin/service/Good.java" -> goodSource;
            default -> readOrNull(repoRoot().resolve(p)); // 真实文件（本单的钉要用到）
        };

        // 坏形态 ①：未登记 ⇒ 红
        Ledger empty = new Ledger(List.of(), List.of(), Set.of());
        assertThat(violations(badLive, empty, sources)).as("未登记即红")
                .anySatisfy(v -> assertThat(v).contains("未登记").contains("Demo#resolve"));

        // 坏形态 ②：台账未兑现（evidence 锚在源码里不存在）⇒ 红
        Ledger unfulfilled = new Ledger(
                List.of(new Entry("Demo#resolve", "guarded",
                        "backend/admin-api/src/main/java/com/migao/admin/service/Demo.java::.eq(\"status\", currentStatus)",
                        List.of("AS-011"))),
                List.of(), Set.of());
        assertThat(violations(badLive, unfulfilled, sources)).as("登记未被兑现即红")
                .anySatisfy(v -> assertThat(v).contains("登记未被兑现").contains("Demo#resolve"));

        // 坏形态 ③：新增豁免（不在冻结基线里）⇒ 红
        Ledger newExemption = new Ledger(List.of(),
                List.of(new Unverified("Demo#resolve", "理由", "#6220", "重启条件")), Set.of());
        assertThat(violations(badLive, newExemption, sources)).as("豁免只许缩短：新增豁免即红")
                .anySatisfy(v -> assertThat(v).contains("豁免只许缩短").contains("Demo#resolve"));

        // 坏形态 ④：豁免缺理由 ⇒ 红
        Ledger noReason = new Ledger(List.of(),
                List.of(new Unverified("Demo#resolve", "", "#6220", "")), Set.of("Demo#resolve"));
        assertThat(violations(badLive, noReason, sources)).as("豁免必须写明理由 / 重启条件")
                .anySatisfy(v -> assertThat(v).contains("豁免未写明"));

        // 坏形态 ⑤：扫描器失明（候选集为空）⇒ 红，而不是「通过」
        assertThat(violations(Set.of(), empty, sources)).as("空跑必须判红（扫描器失明 ≠ 通过）")
                .anySatisfy(v -> assertThat(v).contains("扫描器"));

        // 正向对照：合规语料（在册 + 兑现）⇒ 不红
        // 正向对照：合规语料（在册 + 兑现）⇒ 不红。合成候选集里也要带上「本单的钉」那个真对象，
        // 否则会触发「台账给不存在的对象盖章」——那条对真实语料是对的，对合成语料要先把它凑齐。
        Set<String> compliantLive = new TreeSet<>(goodLive);
        compliantLive.add(TARGET_METHOD);
        Ledger compliant = new Ledger(
                List.of(new Entry("Demo#resolve", "guarded",
                                "backend/admin-api/src/main/java/com/migao/admin/service/Good.java::.eq(\"status\", currentStatus)",
                                List.of("AS-011")),
                        // 「本单的钉」对任何台账都生效 ⇒ 合成语料也要把核心对象带上（真文件 + 真锚）
                        new Entry(TARGET_METHOD, "guarded",
                                "backend/admin-api/src/main/java/com/migao/admin/service/AfterSalesTicketService.java::"
                                        + CONDITIONAL_UPDATE_ANCHOR, List.of("AS-011"))),
                List.of(), Set.of());
        assertThat(violations(compliantLive, compliant, sources)).as("合规语料必须判绿（否则守卫会喂红一切）").isEmpty();

        // 反向对照：把条件更新退回无条件 updateById（= 摘掉兑现锚）⇒ 必须是红
        Ledger anchorRemoved = new Ledger(
                List.of(new Entry("Demo#resolve", "guarded",
                                "backend/admin-api/src/main/java/com/migao/admin/service/Good.java::.eq(\"status\", currentStatus)",
                                List.of("AS-011")),
                        new Entry(TARGET_METHOD, "guarded",
                                "backend/admin-api/src/main/java/com/migao/admin/service/AfterSalesTicketService.java::"
                                        + ".updateById(ticket)",
                                List.of("AS-011"))),
                List.of(), Set.of());
        assertThat(violations(compliantLive, anchorRemoved, sources))
                .as("把条件更新摘回无条件覆盖 ⇒ 兑现锚找不到 / 钉子不成立 ⇒ 必红")
                .anySatisfy(v -> assertThat(v).contains("登记未被兑现").contains(TARGET_METHOD));
    }

    // ────────────────────────────────────────────── 判据本体（纯函数，便于自证）

    /** 扫描一个 service 文件：返回 {@code <SimpleClassName>#<methodName>} 候选集。 */
    static Set<String> scan(String fileName, String source) {
        Set<String> candidates = new TreeSet<>();
        Matcher transactional = TRANSACTIONAL.matcher(source);
        while (transactional.find()) {
            int brace = source.indexOf('{', transactional.end());
            if (brace < 0) {
                continue;
            }
            String signature = source.substring(transactional.end(), brace).replaceAll("\\s+", " ").trim();
            if (!signature.contains("(")) {
                continue; // 类级 / 字段上的注解，不是方法
            }
            int depth = 0;
            int i = brace;
            for (; i < source.length(); i++) {
                char c = source.charAt(i);
                if (c == '{') {
                    depth++;
                } else if (c == '}') {
                    depth--;
                    if (depth == 0) {
                        break;
                    }
                }
            }
            String body = source.substring(brace, Math.min(i + 1, source.length()));
            if (!STATUS_WRITE.matcher(body).find()) {
                continue;
            }
            Matcher sideEffects = SIDE_EFFECT.matcher(body);
            int count = 0;
            while (sideEffects.find()) {
                count++;
            }
            if (count < 2) {
                continue;
            }
            Matcher name = METHOD_NAME.matcher(signature);
            candidates.add(fileName + "#" + (name.find() ? name.group(1) : "?"));
        }
        return candidates;
    }

    private static Set<String> scanPackage(Path serviceDir) throws IOException {
        assertThat(Files.isDirectory(serviceDir)).as("扫描根必须存在: %s", serviceDir).isTrue();
        Set<String> candidates = new LinkedHashSet<>();
        try (Stream<Path> files = Files.list(serviceDir)) {
            for (Path file : files.filter(p -> p.getFileName().toString().endsWith(".java")).sorted().toList()) {
                String name = file.getFileName().toString().replace(".java", "");
                candidates.addAll(scan(name, Files.readString(file)));
            }
        }
        return candidates;
    }

    /** 判定本体：返回违规清单（空 = 通过）。 */
    static List<String> violations(Set<String> live, Ledger ledger, Function<String, String> sourceOf) {
        List<String> violations = new ArrayList<>();
        if (live.isEmpty()) {
            violations.add("扫描器没扫到任何候选方法 ⇒ 判据失明，**不是通过**（形态改名 / 扫描根变了）");
        }
        if (ledger.entries().isEmpty()) {
            violations.add("台账 entries 为空 ⇒ 空转（fail-closed：没有一条被保护的关系是要出事的）");
        }
        Set<String> registered = new LinkedHashSet<>();
        for (Entry e : ledger.entries()) {
            registered.add(e.method());
        }
        for (Unverified u : ledger.unverified()) {
            registered.add(u.method());
        }
        for (String method : live) {
            if (!registered.contains(method)) {
                violations.add("未登记：" + method + " —— 同一事务里的多副作用方法必须登记并发保护或写明豁免（issue #6220）");
            }
        }
        for (String method : registered) {
            if (!live.contains(method)) {
                violations.add("台账给不存在的对象盖章：" + method + " —— 现取候选里没有它（改名 / 删除后必须同步台账）");
            }
        }
        for (Entry e : ledger.entries()) {
            int sep = e.evidence() == null ? -1 : e.evidence().indexOf("::");
            if (sep < 0) {
                violations.add("登记未被兑现：" + e.method() + " 的 evidence 不是 `<仓库相对路径>::<文本锚>` 形态");
                continue;
            }
            String path = e.evidence().substring(0, sep);
            String anchor = e.evidence().substring(sep + 2);
            String source = sourceOf.apply(path);
            if (source == null) {
                violations.add("登记未被兑现：" + e.method() + " 的 evidence 指向不存在的文件 " + path);
            } else if (!source.contains(anchor)) {
                violations.add("登记未被兑现：" + e.method() + " 的 evidence 锚在 " + path + " 里逐字找不到：`" + anchor + "`"
                        + "（保护被摘掉 / 措辞改了 ⇒ 台账必须同步，不许留着一枚假章）");
            }
            if (e.caseIds() == null || e.caseIds().isEmpty()) {
                violations.add("登记的条目缺 case_ids：" + e.method() + "（受保护也必须能被用例面追踪）");
            }
        }
        for (Unverified u : ledger.unverified()) {
            if (isBlank(u.reason()) || isBlank(u.issue()) || isBlank(u.restart())) {
                violations.add("豁免未写明理由 / 关联单 / 重启条件：" + u.method()
                        + "（「有意不做」必须能被下一次会话读到）");
            }
            if (!ledger.baseline().contains(u.method())) {
                violations.add("豁免只许缩短：新增豁免 " + u.method() + " 未在 unverified_baseline 里（要豁免必须显式改基线并说明理由）");
            }
        }
        // 本单的钉：核心方法的保护必须**在册且兑现**（退回无条件 updateById ⇒ 这里红 + evidence 锚缺失也红）
        Entry target = ledger.entries().stream().filter(e -> TARGET_METHOD.equals(e.method())).findFirst().orElse(null);
        if (target == null) {
            violations.add("本单的核心对象不在 entries 里：" + TARGET_METHOD + "（issue #6220 的实例判据 = AS-011）；"
                    + "entries 现取 = " + ledger.entries().stream().map(Entry::method).toList());
        } else {
            if (!"guarded".equals(target.verdict())) {
                violations.add(TARGET_METHOD + " 的 verdict 必须是 guarded（当前 = " + target.verdict() + "）");
            }
            if (target.evidence() == null || !target.evidence().contains(CONDITIONAL_UPDATE_ANCHOR)) {
                violations.add(TARGET_METHOD + " 的 evidence 必须指向条件更新谓词 `" + CONDITIONAL_UPDATE_ANCHOR
                        + "`（退回无条件 updateById ⇒ 红）");
            }
        }
        return violations;
    }

    // ────────────────────────────────────────────── 台账装配

    /** 已保护条目 */
    record Entry(String method, String verdict, String evidence, List<String> caseIds) {
    }

    /** 豁免条目（本单未核验 / 有意不做） */
    record Unverified(String method, String reason, String issue, String restart) {
    }

    record Ledger(List<Entry> entries, List<Unverified> unverified, Set<String> baseline) {
    }

    static Ledger loadLedger(Path path) throws IOException {
        assertThat(Files.exists(path)).as("台账必须存在: %s", path).isTrue();
        JsonNode root = new ObjectMapper().readTree(Files.readString(path));
        List<Entry> entries = new ArrayList<>();
        for (JsonNode node : root.path("entries")) {
            List<String> caseIds = new ArrayList<>();
            node.path("case_ids").forEach(id -> caseIds.add(id.asText()));
            entries.add(new Entry(node.path("method").asText(), node.path("verdict").asText(),
                    node.path("evidence").asText(null), caseIds));
        }
        List<Unverified> unverified = new ArrayList<>();
        for (JsonNode node : root.path("unverified")) {
            unverified.add(new Unverified(node.path("method").asText(), node.path("reason").asText(""),
                    node.path("issue").asText(""), node.path("restart_condition").asText("")));
        }
        Set<String> baseline = new LinkedHashSet<>();
        root.path("unverified_baseline").forEach(n -> baseline.add(n.asText()));
        return new Ledger(entries, unverified, baseline);
    }

    private static boolean isBlank(String s) {
        return s == null || s.isBlank();
    }

    private static String readOrNull(Path path) {
        try {
            return Files.exists(path) ? Files.readString(path) : null;
        } catch (IOException e) {
            return null;
        }
    }

    static Path repoRoot() {
        Path root = Paths.get(System.getProperty("user.dir")).toAbsolutePath();
        while (root != null && !Files.exists(root.resolve(SERVICE_DIR))) {
            root = root.getParent();
        }
        assertThat(root).as("必须能定位仓库根（" + SERVICE_DIR + "）").isNotNull();
        return root;
    }
}
