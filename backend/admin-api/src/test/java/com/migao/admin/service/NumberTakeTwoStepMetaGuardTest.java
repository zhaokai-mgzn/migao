// case_ids: OR-075

package com.migao.admin.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
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
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 🧱 <b>类级元守卫（issue #6266）：取号类写面不许「先查占用、再（在别处）落库」—— 未登记即红</b>。
 *
 * <h2>为什么需要它（只修一处 = 没修）</h2>
 * 实例判据（{@code InboundNoTakeRaceRealDbTest}）只保证 {@code InboundOrderService#insertWithFreshInboundNo}
 * 这**一个**入口在并发下号不重、单不丢。而 #6266 / #6248 的真实教训是
 * <b>「判占用」与「占用」被分在两条语句里</b>：先 {@code exists(..)} 判假 ⇒ 返回候选 ⇒ <b>之后</b>才 insert。
 * 该窗口在多实例 / 重启下可被利用（两边的进程内计数器从同一位置起步 ⇒ 同一候选 ⇒ 两边 exists 都为假）
 * ⇒ 后到的 insert 撞唯一索引 ⇒ 用户侧 409（入库，一单没建成）或 500（出库 / 批次）。下一个人在**同族写面**
 * （出库单号 / 加工单号 / 新单据类型）再写一份同样的两步形态，没有任何东西会红 ⇒ 本守卫把这类写面钉成
 * 机械判据：**候选集 ⇄ 台账双向相等**、豁免**只许缩短**、已改成原子占号的那几处留**兑付锚**（锚被删 ⇒ 红）。
 *
 * <h2>判据（每条都会红）</h2>
 * <ol>
 *   <li><b>扫描器非空跑自证</b>：把出库单号**改前**的两步形态拼回 {@code OutboundOrderService} 的真文件文本
 *       ⇒ 必须被扫到；不拼 ⇒ 现取集合必须为空（「看不见」不是「通过」，而是「判据失明」；
 *       issue #8490 起入库 / 出库 / 批次三处取号写面已全部原子化，真语料里不再有活样本）。</li>
 *   <li><b>未登记即红</b>：现取到的每个两步取号写面必须出现在台账 {@code unverified}（带理由 + 跟踪单 + 重启条件）。</li>
 *   <li><b>台账不许给不存在的对象盖章</b>：{@code unverified} 每条必须仍能在现取集合里找到（修好后请删条目
 *       并下调 {@code unverified_baseline}）。</li>
 *   <li><b>豁免只许缩短</b>：条数 ≤ {@code unverified_baseline}（镜像常量见 {@link #UNVERIFIED_BASELINE_MIRROR}），
 *       且每条三要素非空 ⇒ 防「把未知写成已解决」。</li>
 *   <li><b>兑付锚</b>：{@code atomic_sites} 非空，且每条 {@code anchor} 必须在所列文件里<b>逐字出现</b>
 *       —— 把 {@code ON CONFLICT … DO NOTHING} 删掉 / 改回两步形态 ⇒ 红。</li>
 *   <li><b>判别力自证</b>：四类坏形态（未登记 / 台账盖章幽灵 / 豁免超基线 / 锚被删）在<b>合成语料</b>上各自判红，
 *       合规语料判绿 —— 没有这条，「判据恒绿」与「判据有效」看起来一样。</li>
 * </ol>
 *
 * <h2>未固化项（如实登记，不粉饰）</h2>
 * 见台账 {@code coverage_boundary}：形态判据不做 AST 解析（换措辞可绕过：包一层 {@code exists} / XML mapper /
 * 用 {@code count(*)} 判占用都不在面内）；射程只到 {@code service/*.java}；本表只保证「原子占号 SQL 在场」，
 * **不保证它的语义对不对**（谓词是否匹配索引、耗尽是否 fail-closed）—— 那由真库判据承担。
 */
@DisplayName("🧱 类级元守卫（#6266）：取号类写面不许两步（exists → 之后 insert）—— 未登记即红")
class NumberTakeTwoStepMetaGuardTest {

    /** 判别力自证用的临时根（兑付锚「被回退」在真文件上做，不靠内存假装）。 */
    @TempDir
    Path tempDir;

    private static final String MODULE = "backend/admin-api";
    private static final String SERVICE_DIR = MODULE + "/src/main/java/com/migao/admin/service";
    private static final String LEDGER_PATH = MODULE + "/src/test/resources/number-take-two-step-ledger.json";

    /** 台账 {@code unverified_baseline} 的镜像（「条数只许缩短」的第二把锁：放宽要同时改两处）。 */
    private static final int UNVERIFIED_BASELINE_MIRROR = 0;

    /**
     * 两步取号的**形态**：方法体里出现 {@code .exists(} 且其参数里带业务号 getter（{@code ::getXxxNo}）。
     *
     * <p>为什么盯着这两个记号：改前的病根正是「先 {@code exists(...getXxxNo)} 判假 ⇒ 返回候选」——
     * 合法形态在**一条语句**里占号（{@code ON CONFLICT} / CAS 条件更新），压根不需要先查一次。</p>
     */
    private static final Pattern TWO_STEP =
            Pattern.compile("\\.exists\\s*\\([\\s\\S]{0,800}?::get\\w*No\\b");

    /**
     * 判据① 的**注入语料**（issue #8490）：出库单号**改前**的两步形态（原样）。
     *
     * <p>三处取号写面全部改成原子占号之后，「现取集合为空」既可能是「真干净」也可能是「扫描器失明」
     * —— 两者在断言上长得一样。所以判据① 把这段旧形态**拼在真文件文本后面**：拼上必须被扫到、
     * 不拼必须空集，两个方向都钉住（{@code migao-dev-flow} §28.2.1 的注入式自证）。</p>
     */
    private static final String REVERTED_TWO_STEP_CORPUS =
            "\n    private String nextFreeOutboundNo(Long tenantId) {\n"
                    + "        for (int i = 0; i < 20; i++) {\n"
                    + "            String candidate = generateOutboundNo();\n"
                    + "            boolean taken = outboundOrderMapper.exists(new LambdaQueryWrapper<OutboundOrder>()\n"
                    + "                    .eq(OutboundOrder::getTenantId, tenantId)\n"
                    + "                    .eq(OutboundOrder::getOutboundNo, candidate));\n"
                    + "            if (!taken) {\n"
                    + "                return candidate;\n"
                    + "            }\n"
                    + "        }\n"
                    + "        return null;\n"
                    + "    }\n";

    /** 类体顶层的方法声明（修饰符串 + 返回类型 + 名字 + 参数表），用于按花括号深度切方法体。 */
    private static final Pattern METHOD_SIG = Pattern.compile(
            "(?m)^    (?:@[\\w.]+(?:\\([^)]*\\))?\\s*)*"
                    + "(?:(?:public|private|protected|static|final|synchronized|default|abstract)\\s+)+"
                    + "[\\w<>\\[\\],.?\\s]+?\\s(\\w+)\\s*\\((?:[^;{])*?\\)\\s*(?:throws [\\w.,\\s]+)?\\{");

    /** 现取到的一个「两步取号」写面。 */
    private record Candidate(String path, String method, String body) {
        String key() {
            return path + "#" + method;
        }
    }

    // ────────────────────────────────────────────── 判据 1~3：现取集合 ⇄ 台账 双向相等

    @Test
    @DisplayName("① 现取集合 ⇄ 台账 双向相等（未登记即红 / 台账盖章不存在即红），且扫描器**非空跑**")
    void liveTwoStepSitesMustMatchTheLedgerExactly() throws IOException {
        Path root = repoRoot();
        List<Candidate> live = scanServiceDir(root.resolve(SERVICE_DIR));
        Ledger ledger = loadLedger(root.resolve(LEDGER_PATH));

        System.out.println("[READING #6266 守卫① 现取两步取号写面] " + live.stream().map(Candidate::key).toList()
                + " · 台账 unverified=" + ledger.unverifiedKeys() + " · atomic_sites=" + ledger.atomicKeys());

        // 判据 1（扫描器非空跑自证，issue #8490 改锚）：现取集合已空（入库 / 出库 / 批次三处取号写面
        // 全部改成原子占号）⇒ 对**真语料**做双向自证：把旧的两步形态拼回真文件文本 ⇒ 必须被扫到；
        // 不拼 ⇒ 必须扫不到。否则「空集」与「扫描器失明」在断言上长得一样。
        String outboundService = Files.readString(
                root.resolve(SERVICE_DIR).resolve("OutboundOrderService.java"), StandardCharsets.UTF_8);
        assertThat(scanSource("OutboundOrderService.java", outboundService))
                .as("真语料不许再出现两步取号形态（issue #8490 修好后现取集合必须为空）").isEmpty();
        assertThat(scanSource("OutboundOrderService.java", outboundService + REVERTED_TWO_STEP_CORPUS))
                .as("把旧的两步形态拼回真文件文本必须被扫到（看不见 = 判据失明，不是「通过」）")
                .anyMatch(c -> c.method().equals("nextFreeOutboundNo"));

        // 判据 2 + 3：双向相等
        assertThat(judgeTwoStepSites(live, ledger))
                .as("取号类写面不许停在三步形态上「没人认领」，台账也不许给不存在的对象盖章"
                        + "（出口：改成原子占号，或登记进 " + LEDGER_PATH + " 的 unverified）")
                .isEmpty();
    }

    // ────────────────────────────────────────────── 判据 4：豁免只许缩短 + 三要素

    @Test
    @DisplayName("② 豁免条数只许缩短（≤ 镜像基线）+ 每条必须写明理由 / 跟踪单 / 重启条件")
    void exemptionsOnlyShrinkAndMustCarryRestartConditions() throws IOException {
        Ledger ledger = loadLedger(repoRoot().resolve(LEDGER_PATH));
        System.out.println("[READING #6266 守卫② 豁免条数] " + ledger.unverified().size()
                + " / 基线 " + ledger.unverifiedBaseline() + "（镜像 " + UNVERIFIED_BASELINE_MIRROR + "）");

        assertThat(judgeExemptions(ledger)).as("豁免台账只许缩短（修好一条就删一条并下调 baseline），"
                + "且每条必须写明 why / issue / restart_condition").isEmpty();
    }

    // ────────────────────────────────────────────── 判据 5：兑付锚（原子占号 SQL 必须在场）

    @Test
    @DisplayName("③ 兑付锚：atomic_sites 非空且每条 anchor 在所列文件里**逐字**出现（删掉修复 ⇒ 红）")
    void atomicClaimSitesMustBePresentAndAnchorsLiteral() throws IOException {
        Path root = repoRoot();
        Ledger ledger = loadLedger(root.resolve(LEDGER_PATH));
        List<String> anchors = new ArrayList<>(ledger.atomicKeys());
        System.out.println("[READING #6266 守卫③ 兑付锚] " + anchors);

        assertThat(anchors).as("atomic_sites 不许为空（把修复删了还留着台账 = 这张表在自说自话）")
                .isNotEmpty();
        assertThat(judgeAnchors(ledger, root)).as("每条兑付锚必须在所列文件里逐字出现"
                + "（ON CONFLICT … DO NOTHING 被删 / 改名 ⇒ 当场红）").isEmpty();
    }

    // ────────────────────────────────────────────── 判据 6：判别力自证（合成语料）

    @Test
    @DisplayName("④ 判别力自证：四类坏形态（未登记 / 盖章幽灵 / 豁免超基线 / 锚被删）各自判红，合规语料判绿")
    void scanningPowerSelfProof() throws IOException {
        Path root = repoRoot();
        Ledger real = loadLedger(root.resolve(LEDGER_PATH));
        List<Candidate> realLive = scanServiceDir(root.resolve(SERVICE_DIR));

        // 形态识别：两步形态必须被扫到；原子占号形态必须扫不到（否则判据对「已修好的写法」也红 = 误杀）
        String twoStepCorpus = "\n    private String nextFreeDemoNo(Long tenantId) {\n"
                + "        boolean taken = demoMapper.exists(new LambdaQueryWrapper<Demo>()\n"
                + "                .eq(Demo::getTenantId, tenantId)\n"
                + "                .eq(Demo::getDemoNo, candidate));\n"
                + "        return taken ? null : candidate;\n"
                + "    }\n";
        String atomicCorpus = "\n    private void insertWithFreshNo(Demo demo) {\n"
                + "        demoMapper.insertIgnoreDemoNoConflict(demo);\n"
                + "    }\n";
        assertThat(scanSource("DemoService.java", twoStepCorpus)).as("两步形态必须被扫到（否则守卫半盲）").hasSize(1);
        assertThat(scanSource("DemoService.java", atomicCorpus)).as("原子占号形态不许被扫到（否则守卫误杀修复面）")
                .isEmpty();

        // ① 未登记：现取集合多一个候选 ⇒ 红，且**具名**
        List<Candidate> unregistered = new ArrayList<>(realLive);
        unregistered.add(new Candidate("backend/admin-api/src/main/java/com/migao/admin/service/DemoService.java",
                "nextFreeDemoNo", twoStepCorpus));
        assertThat(judgeTwoStepSites(unregistered, real))
                .as("未登记的取号写面必须判红（否则下一个人照抄两步形态没人拦）")
                .anyMatch(v -> v.contains("未登记") && v.contains("DemoService.java#nextFreeDemoNo"));

        // ② 台账盖章幽灵：现取集合为空 + 台账仍有一条 ⇒ 红（修好后不删条目 = 红）
        //    ⚠️ 用**合成**条目，不用真台账里残留的那条：豁免已清零（issue #8490 修完）之后，
        //    拿它当语料会让这条自证在「全部修好」那一刻自己崩掉（IndexOutOfBoundsException）——
        //    自证必须与真台账的当前存量解耦。
        Ledger ghostLedger = new Ledger(real.unverifiedBaseline(), List.of(ghostExemption()), real.atomicSites());
        assertThat(judgeTwoStepSites(List.of(), ghostLedger))
                .as("台账里的条目在现取集合里消失必须判红（修好后请删条目并下调 baseline）")
                .anyMatch(v -> v.contains("台账盖章不存在"));

        // ③ 豁免超基线：条数 +1 ⇒ 红
        Ledger grown = new Ledger(real.unverifiedBaseline(), append(real.unverified(), ghostExemption()),
                real.atomicSites());
        assertThat(judgeExemptions(grown))
                .as("往豁免里塞条目把红变绿必须判红（豁免只许缩短）").isNotEmpty();

        // ④ 兑付锚被回退：**文件里**那条 ON CONFLICT 被删（同一套 judgeAnchors，真文件真锚）
        String anchor = "ON CONFLICT (tenant_id, demo_no) WHERE deleted = 0 DO NOTHING";
        Path demoMapper = tempDir.resolve("DemoMapper.java");
        Files.writeString(demoMapper, "int insert() { /* " + anchor + " */ }");
        Ledger withDemo = new Ledger(1, List.of(), List.of(new ObjectMapper().readTree(
                "{\"path\":\"" + demoMapper.toString().replace("\\", "/") + "\",\"anchor\":\""
                        + anchor + "\"}")));
        assertThat(judgeAnchors(withDemo, root)).as("锚在场（负控）：不许误红").isEmpty();
        Files.writeString(demoMapper, "int insert() { /* 退回两步形态 */ }");
        assertThat(judgeAnchors(withDemo, root))
                .as("文件里把 ON CONFLICT … DO NOTHING 删掉（= 修复被回退）必须判红").isNotEmpty();

        // ⑤ 合规语料 ⇒ 绿（负控：守卫不许被自己的文案喂红）
        assertThat(judgeTwoStepSites(realLive, real)).as("真实台账 + 真实现取集合必须判绿").isEmpty();
        assertThat(judgeExemptions(real)).as("真实台账的豁免口径必须判绿").isEmpty();
        assertThat(judgeAnchors(real, root)).as("真实兑付锚必须判绿").isEmpty();
    }

    // ────────────────────────────────────────────── 判定本体（真语料与合成语料**同一套**）

    /** 判据 2+3：现取集合 ⇄ 台账双向相等。返回违规清单（空 = 绿）。 */
    private static List<String> judgeTwoStepSites(List<Candidate> live, Ledger ledger) {
        List<String> bad = new ArrayList<>();
        for (Candidate c : live) {
            if (!ledger.unverifiedKeys().contains(c.key())) {
                bad.add("未登记的两步取号写面: " + c.key()
                        + "（出口：改成一条语句占号 ON CONFLICT … DO NOTHING，或在台账 unverified 登记理由 + 跟踪单 + 重启条件）");
            }
        }
        for (String key : ledger.unverifiedKeys()) {
            if (live.stream().noneMatch(c -> c.key().equals(key))) {
                bad.add("台账盖章不存在: " + key + "（它已不在现取集合里 ⇒ 修好后请删条目并下调 unverified_baseline）");
            }
        }
        return bad;
    }

    /** 判据 4：豁免只许缩短 + 三要素非空。返回违规清单（空 = 绿）。 */
    private static List<String> judgeExemptions(Ledger ledger) {
        List<String> bad = new ArrayList<>();
        int count = ledger.unverified().size();
        if (count > UNVERIFIED_BASELINE_MIRROR) {
            bad.add("豁免条数上涨: " + count + " > 基线 " + UNVERIFIED_BASELINE_MIRROR
                    + "（只许缩短；新增豁免不是出口，「改成原子占号」才是）");
        }
        if (count > ledger.unverifiedBaseline()) {
            bad.add("豁免条数超过台账 baseline: " + count + " > " + ledger.unverifiedBaseline());
        }
        for (JsonNode n : ledger.unverified()) {
            for (String field : List.of("why", "issue", "restart_condition")) {
                if (n.path(field).asText("").isBlank()) {
                    bad.add("豁免缺 " + field + ": " + n.path("path").asText("?") + "#" + n.path("method").asText("?")
                            + "（防「把未知写成已解决」）");
                }
            }
        }
        return bad;
    }

    /** 判据 5：兑付锚非空 + 每条 anchor 逐字出现在所列文件里。返回违规清单（空 = 绿）。 */
    private static List<String> judgeAnchors(Ledger ledger, Path root) throws IOException {
        List<String> bad = new ArrayList<>();
        if (ledger.atomicSites().isEmpty()) {
            bad.add("atomic_sites 为空（这张表在自说自话：修复不在场）");
        }
        for (JsonNode site : ledger.atomicSites()) {
            String path = site.path("path").asText("");
            String anchor = site.path("anchor").asText("");
            if (path.isBlank() || anchor.isBlank()) {
                bad.add("兑付锚缺 path / anchor: " + site);
                continue;
            }
            Path file = root.resolve(path);
            if (!Files.exists(file)) {
                bad.add("兑付锚指向不存在的文件: " + path);
                continue;
            }
            if (!Files.readString(file, StandardCharsets.UTF_8).contains(anchor)) {
                bad.add("兑付锚未兑现: " + path + " 里找不到 `" + anchor + "`（修复被回退 / 改名？）");
            }
        }
        return bad;
    }

    // ────────────────────────────────────────────── 扫描

    private static List<Candidate> scanServiceDir(Path serviceDir) throws IOException {
        List<Candidate> out = new ArrayList<>();
        try (Stream<Path> files = Files.walk(serviceDir)) {
            for (Path f : files.filter(p -> p.toString().endsWith(".java")).sorted().toList()) {
                String rel = repoRoot().relativize(f).toString();
                out.addAll(scanSource(rel, Files.readString(f, StandardCharsets.UTF_8)));
            }
        }
        return out;
    }

    private static List<Candidate> scanSource(String relPath, String source) {
        List<Candidate> out = new ArrayList<>();
        for (Method m : methodBodies(source)) {
            if (TWO_STEP.matcher(m.body()).find()) {
                out.add(new Candidate(relPath, m.name(), m.body()));
            }
        }
        return out;
    }

    /** 按花括号深度切方法体（签名可跨行）。 */
    private static List<Method> methodBodies(String source) {
        List<Method> out = new ArrayList<>();
        Matcher m = METHOD_SIG.matcher(source);
        int from = 0;
        while (m.find(from)) {
            int open = m.end() - 1;
            int depth = 0;
            int i = open;
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
            out.add(new Method(m.group(1), source.substring(open, Math.min(i + 1, source.length()))));
            from = Math.min(i + 1, source.length());
        }
        return out;
    }

    private record Method(String name, String body) {
    }

    // ────────────────────────────────────────────── 台账

    private record Ledger(int unverifiedBaseline, List<JsonNode> unverified, List<JsonNode> atomicSites) {
        Set<String> unverifiedKeys() {
            Set<String> keys = new LinkedHashSet<>();
            for (JsonNode n : unverified) {
                keys.add(n.path("path").asText("") + "#" + n.path("method").asText(""));
            }
            return keys;
        }

        Set<String> atomicKeys() {
            Set<String> keys = new LinkedHashSet<>();
            for (JsonNode n : atomicSites) {
                keys.add(n.path("path").asText("") + "::" + n.path("anchor").asText(""));
            }
            return keys;
        }
    }

    private static Ledger loadLedger(Path file) throws IOException {
        JsonNode root = new ObjectMapper().readTree(Files.readString(file, StandardCharsets.UTF_8));
        List<JsonNode> unverified = new ArrayList<>();
        root.path("unverified").forEach(unverified::add);
        List<JsonNode> atomic = new ArrayList<>();
        root.path("atomic_sites").forEach(atomic::add);
        return new Ledger(root.path("unverified_baseline").asInt(0), unverified, atomic);
    }

    private static List<JsonNode> append(List<JsonNode> nodes, JsonNode extra) {
        List<JsonNode> out = new ArrayList<>(nodes);
        out.add(extra);
        return out;
    }

    /** 合成一条「已登记」的豁免条目（判别力自证用；**不依赖**真台账当前是否还有豁免）。 */
    private static JsonNode ghostExemption() throws IOException {
        return new ObjectMapper().readTree("{\"path\":\"backend/admin-api/src/main/java/com/migao/admin/service/"
                + "GhostService.java\",\"method\":\"nextFreeGhostNo\",\"why\":\"判别力自证\","
                + "\"issue\":\"#0\",\"restart_condition\":\"合成语料，不指向真文件\"}");
    }

    private static Path repoRoot() {
        Path root = Paths.get(System.getProperty("user.dir")).toAbsolutePath();
        while (root != null && !Files.exists(root.resolve(SERVICE_DIR))) {
            root = root.getParent();
        }
        assertThat(root).as("必须能定位仓库根（" + SERVICE_DIR + "）").isNotNull();
        return root;
    }
}
