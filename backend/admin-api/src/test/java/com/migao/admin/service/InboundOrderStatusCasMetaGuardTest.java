// case_ids: MC-100

package com.migao.admin.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
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
import java.util.stream.Collectors;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 🧱 <b>类级元守卫（issue #6928）：入库单状态迁移的写路径必须落到 SQL 谓词（CAS），未登记即红</b>。
 *
 * <h2>为什么需要它（只修一处 = 没修）</h2>
 * 实例判据（{@code InboundOrderCancelRaceRealDbTest}）只保证 {@code InboundOrderService#cancel}
 * 这**一个**入口在并发下与 {@code #post} 互斥。而 #6928 的真实教训是
 * <b>「同一个状态迁移权上有两个写面，只有一个带 CAS」</b>：{@code #post} 走条件更新（{@code markPosted}），
 * {@code #cancel} 走「先读 status 判 draft、再 {@code updateById}（WHERE 仅主键 ⇒ 无谓词）」⇒ 两者
 * 不互斥，窗口里 post 抢到过账权并提交（库存 +N、台账 1 行），cancel 随后把该单覆写成 cancelled
 * —— 库存与入库台账静默留存（账实不符、无任何 4xx）。下一个人在**同文件新加一条状态迁移写路径**、
 * 或给 mapper 加一条**无谓词**的状态写 SQL，没有任何东西会红 ⇒ 本守卫把「写路径清单 + 谓词完整性」
 * 钉成机械判据。
 *
 * <h2>判据（每条都会红）</h2>
 * <ol>
 *   <li><b>扫描器非空跑自证</b>：现取「写 {@code inbound_orders.status} 的 mapper SQL」必须包含
 *       {@code markPosted} 与 {@code markCancelled}；现取「service 里写状态列的调用点」必须包含
 *       {@code post} 与 {@code cancel}。候选集为空 / 少了核心对象 ⇒ 先红
 *       （形态被改名不是「通过」，而是「判据失明」）。</li>
 *   <li><b>mapper 状态写 SQL 必须带完整谓词</b>：凡在 SET 侧写 {@code status} 的手写 {@code @Update}
 *       SQL，必须同时含 {@code tenant_id} 参数、{@code status = 'draft'} 谓词、{@code deleted = 0}
 *       —— 少任何一条 ⇒ 红（退回「无谓词写」= 本单的病根）。</li>
 *   <li><b>service 写路径未登记即红</b>：任何方法体里出现「写状态列的调用」（{@code inboundOrderMapper.updateById(}
 *       或 {@code inboundOrderMapper.mark*(}）都不许「没人认领」—— 要么登记进 {@code service_write_paths}
 *       （= 状态迁移，必须兑现 CAS 收口锚），要么登记进 {@code non_status_writers}（= 明示「它不写 status 列」，
 *       闸由判据 3b 承担）⇒ 两个名单都没有 ⇒ 红。</li>
 *   <li><b>「非状态写」这条豁免不许自己长大</b>（issue #6956）：{@code non_status_writers} 里的每个名额
 *       必须**仍不写** {@code status} 列（{@code setStatus(} / {@code .set(…::getStatus} / 该 mapper 的状态写面），
 *       名额数 ≤ {@code non_status_writers_baseline}（**只许缩短**）⇒ 往这些方法里塞一条状态迁移
 *       ⇒ 当场红（否则「豁免」就是「下一个 #6928」的入口）。</li>
 *   <li><b>台账不许给不存在的对象盖章</b>：每条 {@code entries[]} / {@code service_write_paths[]} 的
 *       {@code method} 必须仍能在现取候选集里找到（改名 / 删除 ⇒ 红）。</li>
 *   <li><b>登记未被兑现即红</b>：{@code evidence} = {@code <仓库相对路径>::<可检索文本>}，
 *       左侧文件必须存在、右侧必须在该文件里<b>逐字出现</b> ⇒ 防「给不存在的保护盖章」
 *       （摘掉 CAS 调用 / 方法改名 ⇒ 红）。</li>
 *   <li><b>豁免台账只许缩短</b>：{@code unverified} 必须是冻结基线 {@code unverified_baseline}
 *       的<b>子集</b>（新增豁免 ⇒ 红）；条数<b>现取</b>（不写死在测试代码里，读数打印在断言消息上）。</li>
 *   <li><b>判别力自证</b>：用<b>合成语料</b>在内存里跑与真实源码<b>同一套</b>判定本体 ——
 *       「无谓词状态写」「缺 {@code deleted=0}」「缺 tenant 谓词」「未登记写路径」「台账未兑现」
 *       五种坏形态各自判红，合规语料判绿。没有这条，「判据恒绿」与「判据有效」在结果列上长得一样。</li>
 * </ol>
 *
 * <h2>🔴 射程盲洞修复（issue #6956 · 洞 A）</h2>
 * <p>本守卫原先的取方法体实现要求「签名**在同一行**收尾（{@code ") {"}）」——
 * 于是 {@code InboundOrderService#create(InboundOrderCreateRequest, Long, String, String)}
 * 这种<b>签名跨两行</b>的方法<b>整个方法体从未被收集</b>（实测：现取候选集恒为 {@code [post, cancel]}，
 * 而该方法体里的 {@code inboundOrderMapper.updateById(order)} 没有任何东西看着它）。
 * 修法 = 取块前先把**类体顶层的多行签名归一成一行**（只看括号是否配对，不靠「一行收尾」），
 * 并在判据 8 里补一条**单变量对照语料**（同一语义、只增一个换行 ⇒ 修前看不见、修后看得见且判红）。
 * ❗ 判据 3 因此**新增了对象**（{@code create} 现被收集），它按判据 3b 的口径登记为
 * {@code non_status_writers}（它写的是同一行的非状态列，不构成状态迁移写面）——**这不是往豁免里塞条目**，
 * 而是把「谁在写、写什么」登记清楚；豁免名额数被 {@code non_status_writers_baseline} 冻结（只许缩短）。</p>
 *
 * <p>⚠️ 本判据读<b>源码文本</b>（不做 AST）—— 本仓既有形态（{@code OrderAutoCompleteSqlGuardTest} /
 * {@code StockDeductionAndLedgerAtomicityMetaGuardTest} 同款）。代价：它只能证明「这几个字在方法体里」；
 * <b>行为面由真库并发判据承担</b>：{@code InboundOrderCancelRaceRealDbTest}（#6928）与
 * {@code InboundPostConcurrentRealDbTest}（#6237）—— 三者缺一不可
 * （{@code migao-dev-flow} §28.2：判据本体绿 ≠ 接线在）。</p>
 *
 * <p><b>未固化项（如实登记，不粉饰）</b>：见台账 {@code coverage_boundary} ——
 * ① 形态判据换措辞可绕过（真实防线仍是各自的实例判据）；② 射程只到
 * {@code InboundOrderService} + {@code InboundOrderMapper} 这一对文件（别的租户数据类型的
 * 状态迁移不在本表射程）；③ 判不了「拿 {@code updateById} 改**非状态**列」（那不是本表的对象）；
 * ④ 本守卫<b>不</b>跑被它引用的那条真库判据（否则「未登记即红」会退化成全量套件再跑一遍）；
 * ⑤ 本守卫<b>不改</b>任何门禁的通过条件、不新增豁免。</p>
 */
@DisplayName("🧱 类级元守卫（#6928）：入库单状态迁移写路径必须落到 SQL 谓词（未登记即红 + 豁免只许缩短）")
class InboundOrderStatusCasMetaGuardTest {

    /** 模块根（Surefire 的工作目录 = {@code backend/admin-api}）；台账里的引用一律是**仓库相对全路径**。 */
    private static final String MODULE = "backend/admin-api";
    private static final String MAIN = MODULE + "/src/main/java/com/migao/admin";
    private static final String MAPPER_FILE = MAIN + "/mapper/InboundOrderMapper.java";
    private static final String SERVICE_FILE = MAIN + "/service/InboundOrderService.java";
    private static final String LEDGER_PATH =
            MODULE + "/src/test/resources/inbound-order-status-cas-ledger.json";

    // ── 形态（与台账 scan 段的声明逐字对应）

    /** 手写 update 注解的**取块**（到配对的 `)` 为止；SQL 自带括号 ⇒ 先取块再剥 Java 语法）。 */
    private static final Pattern UPDATE_ANNOTATION =
            Pattern.compile("@Update\\s*\\(((?:[^()]|\\([^()]*\\))*)\\)");
    /** 写面表名。 */
    private static final String TABLE = "inbound_orders";
    /** 「状态列写」的两种调用形态。 */
    private static final Pattern INBOUND_UPDATE_BY_ID =
            Pattern.compile("inboundOrderMapper\\.updateById\\(");
    /** 该 mapper 的手写状态迁移写面（现取，不写死）：`inboundOrderMapper.markXxx(`。 */
    private static final Pattern MAPPER_CAS_CALL = Pattern.compile("inboundOrderMapper\\.(mark\\w+)\\(");
    /** 实体侧的状态列写（{@code order.setStatus(…)} / {@code .set(InboundOrder::getStatus, …)}）。 */
    private static final Pattern INBOUND_STATUS_SETTER =
            Pattern.compile("setStatus\\s*\\(|\\.set\\(\\s*InboundOrder\\w*::getStatus\\s*,");
    /** 谓词 / 参数要求（issue #6928 的口径）。 */
    private static final Pattern TENANT_PARAM =
            Pattern.compile("#\\{\\s*tenantI?d\\s*\\}", Pattern.CASE_INSENSITIVE);
    private static final Pattern DRAFT_PREDICATE =
            Pattern.compile("status\\s*=\\s*'draft'", Pattern.CASE_INSENSITIVE);
    private static final Pattern DELETED_PREDICATE =
            Pattern.compile("deleted\\s*=\\s*0", Pattern.CASE_INSENSITIVE);
    /** 方法体收尾形态（`… ) {`）：签名**可跨行** ⇒ 取块前先归一成一行（见 {@link #signatureBlockEnd}）。 */
    private static final String BODY_OPEN = ") {";
    /** 签名归一：起始行的形态 = 恰 4 空格缩进 + 以**修饰符**开头（`if (` 之类控制结构天然落选）。 */
    private static final Pattern MEMBER_HEAD_START = Pattern.compile(
            "^ {4}(?:public|private|protected|static|final|default|synchronized|abstract|native|strictfp)\\b");
    /** 类体顶层的缩进（4 空格）；嵌套块（控制结构 / lambda）更深 ⇒ 靠它把方法从体内区分出来。 */
    private static final String MEMBER_INDENT = "    ";
    /** Java 控制结构关键字：`if (…) {` 在行形态上与「方法 + 体」同形，靠名字排除。 */
    private static final Set<String> CONTROL_KEYWORDS = Set.of(
            "if", "for", "while", "switch", "catch", "synchronized", "try", "do", "else", "return");

    private static final ObjectMapper JSON = new ObjectMapper();

    // ────────────────────────────────────────────── 判据 1~6：真语料

    @Test
    @DisplayName("扫描器非空跑自证：现取写 status 的 mapper SQL 与 service 写路径必须包含核心对象")
    void scannersAreNotBlind() throws IOException {
        List<String> mapperMethods = mapperStatusWrites(mapperText()).stream().map(MapperWrite::method).toList();
        List<String> servicePaths = serviceStatusWritePaths(serviceText());

        System.out.println("[READING MC-100 扫描器] 写 status 的 mapper 方法=" + mapperMethods
                + " service 写路径=" + servicePaths);
        assertThat(mapperMethods)
                .as("扫描器必须现取到写 status 的 mapper 手写 SQL（返回空集 = 判据失明，不是通过）")
                .contains("markPosted", "markCancelled");
        assertThat(servicePaths)
                .as("扫描器必须现取到 service 里写状态列的调用点（返回空集 = 判据失明，不是通过）")
                .contains("post", "cancel");
        // 🔴 冻结锚（issue #6956 · 洞 A）：换行签名的 `create` 必须进现取集 ——
        //    它过去**从未被收集**（「签名必须同一行收尾」）；把它钉成锚对象 ⇒ 归一化退化即红，
        //    而不是「悄悄少收集一个方法，结果列上看着像通过」。
        assertThat(servicePaths)
                .as("换行签名的 create 必须在现取集里（它是洞 A 的冻结锚对象；少了它 = 归一化失效）")
                .contains("create");
    }

    @Test
    @DisplayName("mapper 状态写 SQL 必须带完整谓词（tenant_id + status='draft' + deleted=0）")
    void everyStatusWriteCarriesTheFullPredicate() throws IOException {
        List<MapperWrite> writes = mapperStatusWrites(mapperText());
        List<String> offenders = new ArrayList<>();
        for (MapperWrite w : writes) {
            List<String> missing = new ArrayList<>();
            if (!TENANT_PARAM.matcher(w.sql()).find()) {
                missing.add("tenant_id 参数");
            }
            // 默认谓词 = status='draft'；台账条目可**显式声明**自己的状态谓词
            // （V196 / issue #7750：成品入库单建单即过账 ⇒ 作废谓词是 status='posted'）。
            String expected = declaredStatusPredicates().getOrDefault(w.method(), DRAFT_PREDICATE.pattern());
            if (!Pattern.compile(expected, Pattern.CASE_INSENSITIVE).matcher(w.sql()).find()) {
                missing.add("status 谓词（期望 " + expected + "）");
            }
            if (!DELETED_PREDICATE.matcher(w.sql()).find()) {
                missing.add("deleted=0 谓词");
            }
            if (!missing.isEmpty()) {
                offenders.add(w.method() + " 缺 " + missing);
            }
        }
        System.out.println("[READING MC-100 谓词] 状态写面="
                + writes.stream().map(MapperWrite::method).toList() + " 违规=" + offenders);
        assertThat(offenders).as("状态迁移的写必须把判断与写入压进同一条语句（无谓词写 = #6928 的病根）")
                .isEmpty();
    }

    @Test
    @DisplayName("service 写路径未登记即红 + 非状态写豁免不许自己长大 + 台账不许盖章 + 豁免只许缩短")
    void serviceWritePathsAreRegisteredAndLedgerIsFaithful() throws IOException {
        JsonNode ledger = ledger();
        Map<String, MethodBody> candidates = new LinkedHashMap<>();
        for (MethodBody m : serviceStatusWriteCandidates(serviceText())) {
            candidates.put(m.name(), m);
        }
        List<String> servicePaths = List.copyOf(candidates.keySet());

        // 名单一：状态迁移写路径（必须兑现 CAS 收口锚）
        Map<String, String> registered = new LinkedHashMap<>();
        for (JsonNode e : ledger.get("service_write_paths")) {
            registered.put(e.get("method").asText(), e.get("call_anchor").asText());
        }
        Set<String> registeredBare = registered.keySet().stream()
                .map(InboundOrderStatusCasMetaGuardTest::bareMethod)
                .collect(Collectors.toCollection(LinkedHashSet::new));
        // 名单二：**非状态写**豁免（明示「它不写 status 列」；名额被冻结基线锁住，只许缩短）
        Set<String> nonStatus = new LinkedHashSet<>();
        for (JsonNode n : ledger.get("non_status_writers")) {
            nonStatus.add(bareMethod(n.get("method").asText()));
        }
        int nonStatusBaseline = ledger.get("non_status_writers_baseline").asInt();

        List<String> unregistered = servicePaths.stream()
                .filter(p -> !registeredBare.contains(p) && !nonStatus.contains(p)).toList();
        List<String> ghosts = registeredBare.stream()
                .filter(r -> !servicePaths.contains(r)).toList();
        // 🔴 豁免不许自己长大：① 名额数 ≤ 冻结基线；② 每个名额必须**仍不写** status 列。
        List<String> nonStatusOffenders = nonStatus.stream()
                .filter(n -> candidates.containsKey(n) && bodyWritesStatusColumn(candidates.get(n).body()))
                .map(n -> n + " 已经写 status 列（不再是「非状态写」）")
                .toList();
        List<String> nonStatusGhosts = nonStatus.stream()
                .filter(n -> !candidates.containsKey(n)).toList();
        int unverified = ledger.get("unverified").size();
        int baseline = ledger.get("unverified_baseline").asInt();

        System.out.println("[READING MC-100 台账] 现取写路径=" + servicePaths + " 已登记=" + registered
                + " 非状态写豁免=" + nonStatus + "(基线 " + nonStatusBaseline + ")"
                + " 未登记=" + unregistered + " 幽灵条目=" + ghosts
                + " 豁免越界=" + nonStatusOffenders + " 豁免幽灵=" + nonStatusGhosts
                + " 豁免=" + unverified + "(基线 " + baseline + ")");
        assertThat(unregistered)
                .as("新增写路径必须登记进台账（状态迁移 ⇒ service_write_paths；非状态写 ⇒ non_status_writers）"
                        + " —— 两个名单都没有就是「下一个 #6928」")
                .isEmpty();
        assertThat(ghosts).as("台账不许给不存在的写路径盖章（改名 / 删除 ⇒ 红）").isEmpty();
        assertThat(nonStatus)
                .as("non_status_writers 只许缩短（新增名额必须走 issue + 说清它为什么不写 status 列）")
                .hasSizeLessThanOrEqualTo(nonStatusBaseline);
        assertThat(nonStatusOffenders)
                .as("non_status_writers 里的方法**已经写 status 列** ⇒ 它不再是「非状态写」："
                        + "必须改登记为状态迁移写路径（带 CAS 收口锚）—— 这正是「豁免变成下一个 #6928」的形态")
                .isEmpty();
        assertThat(nonStatusGhosts).as("non_status_writers 不许有幽灵条目（改名 / 删除 ⇒ 红）").isEmpty();
        assertThat(unverified).as("豁免台账只许缩短（新增豁免必须走 issue + 重启条件）")
                .isLessThanOrEqualTo(baseline);

        // ⑤ 写面级禁止锚（issue #6956）：已收编但**只许写非状态列**的写面，不得出现状态迁移锚。
        Map<String, String> forbidden = new LinkedHashMap<>();
        for (JsonNode e : ledger.get("non_status_writers")) {
            if (e.hasNonNull("status_write_forbidden")) {
                forbidden.put(e.get("method").asText(), e.get("status_write_forbidden").asText());
            }
        }
        List<String> forbiddenHit = forbidden.entrySet().stream()
                .filter(f -> candidates.containsKey(bareMethod(f.getKey()))
                        && candidates.get(bareMethod(f.getKey())).body().contains(f.getValue()))
                .map(f -> f.getKey() + " 出现 " + f.getValue())
                .toList();
        System.out.println("[READING MC-100 写面禁止锚] " + forbidden + " 命中=" + forbiddenHit);
        assertThat(forbiddenHit)
                .as("已收编的「非状态写」写面出现状态迁移锚 ⇒ 必须判红（它必须改登记为状态迁移写路径）")
                .isEmpty();
    }

    @Test
    @DisplayName("登记未被兑现即红：每条 evidence 锚必须在它声称的文件里逐字出现")
    void everyEvidenceAnchorIsLive() throws IOException {
        JsonNode ledger = ledger();
        Path root = repoRoot();
        List<String> broken = new ArrayList<>();
        for (String section : List.of("entries", "service_write_paths", "non_status_writers")) {
            for (JsonNode e : ledger.get(section)) {
                String anchor = e.get("evidence").asText();
                int sep = anchor.indexOf("::");
                String label = section + " " + e.get("method").asText();
                if (sep <= 0) {
                    broken.add(label + " evidence 形态不是 <path>::<anchor>：" + anchor);
                    continue;
                }
                Path file = root.resolve(anchor.substring(0, sep));
                String symbol = anchor.substring(sep + 2);
                if (!Files.exists(file)) {
                    broken.add(label + " 左侧文件不存在：" + anchor.substring(0, sep));
                } else if (!Files.readString(file, StandardCharsets.UTF_8).contains(symbol)) {
                    broken.add(label + " 右侧锚在文件里找不到：" + symbol);
                }
            }
        }
        System.out.println("[READING MC-100 兑现] 断链=" + broken);
        assertThat(broken).as("evidence 必须逐字兑现（摘掉 CAS 调用 / 方法改名 ⇒ 当场红）").isEmpty();
    }

    @Test
    @DisplayName("状态迁移写路径不得使用无谓词 updateById（必须走条件更新 CAS）")
    void noStatusWritePathUsesUnconditionalUpdateById() throws IOException {
        Set<String> registered = new LinkedHashSet<>();
        for (JsonNode e : ledger().get("service_write_paths")) {
            registered.add(bareMethod(e.get("method").asText()));
        }
        List<String> offenders = serviceStatusWriteCandidates(serviceText()).stream()
                .filter(m -> registered.contains(m.name()))
                .filter(m -> INBOUND_UPDATE_BY_ID.matcher(m.body()).find())
                .map(MethodBody::name)
                .toList();
        System.out.println("[READING MC-100 无谓词写] 现取候选方法=" + serviceStatusWritePaths(serviceText())
                + " 状态迁移写路径=" + registered + " 违规=" + offenders);
        assertThat(offenders)
                .as("状态迁移的写必须带谓词（#6928 的病根就是 cancel 用了无谓词 updateById）")
                .isEmpty();
    }

    // ────────────────────────────────────────────── 判据 7：合成语料判别力自证

    @Test
    @DisplayName("判别力自证（合成语料）：五种坏形态各自判红、合规语料判绿、换行签名不逃逸")
    void guardHasDiscriminatingPower() {
        // 合规：与真源码同形的两条 CAS + 两条调用点
        String goodMapper = mapperCorpus(
                "int markPosted(@Param(\"id\") String id);",
                "UPDATE inbound_orders SET status = 'posted', posted_at = #{postedAt}, posted_by = #{operator}, "
                        + "updated_at = NOW() WHERE id = #{id} AND tenant_id = #{tenantId} "
                        + "AND status = 'draft' AND deleted = 0",
                "int markCancelled(@Param(\"id\") String id);",
                "UPDATE inbound_orders SET status = 'cancelled', cancelled_at = #{cancelledAt}, "
                        + "cancelled_by = #{operator}, cancelled_reason = #{reason}, updated_at = NOW() "
                        + "WHERE id = #{id} AND tenant_id = #{tenantId} AND status = 'draft' AND deleted = 0");
        String goodService = serviceCorpus("post",
                "inboundOrderMapper.markPosted(order.getId(), tenantId, operator, now);")
                + serviceCorpus("cancel",
                "inboundOrderMapper.markCancelled(order.getId(), tenantId, operator, reason, now);");
        Map<String, String> registered = new LinkedHashMap<>();
        registered.put("post", "inboundOrderMapper.markPosted(");
        registered.put("cancel", "inboundOrderMapper.markCancelled(");

        assertThat(problems(goodMapper, goodService, registered, List.of()))
                .as("合规语料判绿（否则本守卫是恒红噪声）").isEmpty();

        // 坏形态 ①：无谓词状态写（= #6928 的病根本体）
        assertThat(problems(mapperCorpus("int markCancelled(@Param(\"id\") String id);",
                        "UPDATE inbound_orders SET status = 'cancelled' WHERE id = #{id}"),
                goodService, registered, List.of()))
                .as("无谓词状态写必须判红").isNotEmpty();

        // 坏形态 ②：缺 deleted = 0（软删的单也能被写）
        assertThat(problems(mapperCorpus("int markPosted(@Param(\"id\") String id);",
                        "UPDATE inbound_orders SET status = 'posted' WHERE id = #{id} AND tenant_id = #{tenantId} "
                                + "AND status = 'draft'"),
                goodService, registered, List.of()))
                .as("缺 deleted=0 必须判红").isNotEmpty();

        // 坏形态 ③：缺 tenant 谓词（跨租户可写）
        assertThat(problems(mapperCorpus("int markPosted(@Param(\"id\") String id);",
                        "UPDATE inbound_orders SET status = 'posted' WHERE id = #{id} AND status = 'draft' "
                                + "AND deleted = 0"),
                goodService, registered, List.of()))
                .as("缺 tenant 谓词必须判红").isNotEmpty();

        // 坏形态 ④：service 新加一条未登记的状态写路径
        assertThat(problems(goodMapper, goodService + serviceCorpus("reopen",
                        "inboundOrderMapper.updateById(order);"), registered, List.of()))
                .as("未登记的状态迁移写路径必须判红（这就是「只修一处」的复发形态）").isNotEmpty();

        // 坏形态 ④b：最隐蔽的一种 —— **锚串留着**（`if (false && …markCancelled(…)`），
        //            真正落库的换成无谓词 updateById ⇒ 必须仍然判红（实证：只判锚会被它骗过去）
        String anchorKeptButUnconditional = goodService.replace(
                "inboundOrderMapper.markCancelled(",
                "inboundOrderMapper.markCancelled(") + serviceCorpus("cancel2",
                "if (false && inboundOrderMapper.markCancelled(id, 1L, \"op\", \"r\", null) == 0) { }\n"
                        + "        inboundOrderMapper.updateById(order);");
        assertThat(problems(goodMapper, anchorKeptButUnconditional, registered, List.of()))
                .as("锚还在但真正落库的是无谓词 updateById ⇒ 必须判红（判据的主张本体是 CAS，不是锚）")
                .isNotEmpty();

        // 坏形态 ⑤：台账未兑现（CAS 调用被摘掉 / 改名）
        assertThat(problems(goodMapper,
                        goodService.replace("inboundOrderMapper.markCancelled(",
                                "inboundOrderMapper.someOtherWrite("), registered, List.of()))
                .as("台账锚被摘掉必须判红").isNotEmpty();

        // 坏形态 ⑥：非状态写豁免自己长大 —— 被登记为 non_status 的方法里塞进一条状态迁移
        assertThat(problems(goodMapper, goodService + serviceCorpus("create",
                        "inboundOrderMapper.updateById(order);\n        order.setStatus(\"posted\");"),
                registered, List.of("create")))
                .as("non_status_writers 里的方法**开始写 status 列** ⇒ 必须判红"
                        + "（豁免变成「下一个 #6928」的入口）").isNotEmpty();

        // 坏形态 ⑦：已收编的「非状态写」写面（真台账里的 create）被塞进状态迁移 ⇒ 禁止锚命中。
        //   ⚠️ 这条语料必须**自带被登记的 post/cancel**（否则「台账给不存在的写路径盖章」会先红，
        //      红的原因就不是我们想证的那条了 —— 判据的「判红可归因」在这里同样适用）。
        Map<String, String> registeredWithCreate = new LinkedHashMap<>(registered);
        registeredWithCreate.put("create", "inboundOrderMapper.updateById(order);");
        assertThat(problems(goodMapper, goodService + serviceCorpus("create",
                        "inboundOrderMapper.updateById(order);\n        order.setStatus(\"posted\");"),
                registeredWithCreate, List.of(), Map.of("create", "order.setStatus(")))
                .as("status_write_forbidden 锚命中 ⇒ 必须判红（收编后仍不许变成状态迁移）").isNotEmpty();

        // 🔴 反转对照（issue #6956 · 洞 A 的核心交付）：**同一语义、只增一个换行** ——
        //    旧实现要求「签名在同一行收尾」⇒ 这个方法的整个方法体从未被收集（判绿）；
        //    归一化后必须看得见，且「未登记即红」当场生效。
        String wrappedSignatureService = multilineSignatureCorpus("create",
                "inboundOrderMapper.updateById(order);");
        System.out.println("[READING MC-100 换行签名语料] 现取=" + serviceStatusWritePaths(wrappedSignatureService)
                + " 问题清单=" + problems(goodMapper, wrappedSignatureService, registered, List.of()));
        assertThat("create")
                .as("换行签名的方法必须被收集（修前：现取集=[post, cancel] —— 没有它）")
                .isIn(serviceStatusWritePaths(wrappedSignatureService));
        assertThat(problems(goodMapper, goodService + wrappedSignatureService, registered, List.of()))
                .as("换行签名 + 未登记的状态写 ⇒ 必须判红（修前：现取集里没有它 ⇒ 这条读数恒为「无问题」）")
                .isNotEmpty();

        // 对照：换行签名 + 只写非状态列（登记为 non_status 豁免）⇒ 不红
        //      （证明「换行签名 + 未登记」那条判红来自「写状态列」，而非「换行」本身）
        assertThat(problems(goodMapper, goodService + multilineSignatureCorpus("create",
                        "inboundOrderMapper.updateById(order);"), registered, List.of("create")))
                .as("换行签名本身不是罪：只写非状态列且已登记为 non_status ⇒ 不红").isEmpty();

        // 反向对照：只改注释 ⇒ 不红
        assertThat(problems(goodMapper,
                        "// 注释里提一句 inboundOrderMapper.updateById(order)\n" + goodService, registered, List.of()))
                .as("只加注释不得判红（否则守卫被自己的文案喂红）").isEmpty();
    }

    // ────────────────────────────────────────────── 判定本体（真源码与合成语料共用）

    /**
     * 一次判定：返回问题清单（空 = 合规）。真源码与合成语料走**同一套**判定本体。
     *
     * <p>{@code registered} 的键 = 状态迁移写路径的方法名（可带 {@code <类>#} 前缀），值 = 该路径必须**逐字出现**
     * 的调用锚（如 {@code inboundOrderMapper.markCancelled(}）。「以 `markXxx` 收口」这条主张只有在
     * 锚真的在方法体里时才成立 —— 退回无谓词 {@code updateById} ⇒ 锚消失 ⇒ 当场红。</p>
     *
     * <p>{@code nonStatus} = **非状态写**豁免名单（方法名）：明示「它进现取集，但它不写 {@code status} 列」。
     * 判据不许它自己长大 —— 名单里的方法一旦出现状态列写（{@code setStatus} / {@code .set(…::getStatus} /
     * {@code inboundOrderMapper.updateById(} 或 {@code mark*}）⇒ 当场红（issue #6956 的洞 A 修法带来的
     * 新对象 {@code create} 就走这条登记，而不是「往豁免里塞条目把红变绿」）。</p>
     */
    private static List<String> problems(String mapperText, String serviceText,
                                         Map<String, String> registered, List<String> nonStatus) {
        return problems(mapperText, serviceText, registered, nonStatus, Map.of());
    }

    /**
     * 判定本体（全参）：{@code statusWriteForbidden} 的键 = 写面方法名，值 = **本方法内不得出现**的
     * 状态写锚（如 {@code order.setStatus(}）—— 给「已收编但仍只许写非状态列」的写面（issue #6956 的
     * {@code InboundOrderService#create}）用：往它里面加状态迁移 ⇒ 当场红。
     */
    private static List<String> problems(String mapperText, String serviceText,
                                         Map<String, String> registered, List<String> nonStatus,
                                         Map<String, String> statusWriteForbidden) {
        List<String> problems = new ArrayList<>();
        for (MapperWrite w : mapperStatusWrites(mapperText)) {
            if (!TENANT_PARAM.matcher(w.sql()).find()
                    || !DRAFT_PREDICATE.matcher(w.sql()).find()
                    || !DELETED_PREDICATE.matcher(w.sql()).find()) {
                problems.add("mapper 状态写缺谓词: " + w.method());
            }
        }
        Set<String> nonStatusBare = nonStatus.stream()
                .map(InboundOrderStatusCasMetaGuardTest::bareMethod)
                .collect(Collectors.toSet());
        Map<String, MethodBody> candidates = new LinkedHashMap<>();
        for (MethodBody m : serviceStatusWriteCandidates(serviceText)) {
            candidates.put(m.name(), m);
        }
        Set<String> registeredNames = registered.keySet().stream()
                .map(InboundOrderStatusCasMetaGuardTest::bareMethod)
                .collect(Collectors.toSet());
        for (Map.Entry<String, MethodBody> e : candidates.entrySet()) {
            String name = e.getKey();
            if (nonStatusBare.contains(name)) {
                // 非状态写豁免：只验「它仍不写状态列」。写了 ⇒ 它必须改登记为状态迁移写路径。
                if (bodyWritesStatusColumn(e.getValue().body())) {
                    problems.add("non_status_writers 里的 " + name + " 已经写 status 列"
                            + "（必须改登记为状态迁移写路径并兑现 CAS 收口锚）");
                }
                continue;
            }
            if (!registeredNames.contains(name)) {
                problems.add("service 未登记的状态写路径: " + name);
            }
            // 🔴 本守卫的**主张本体**：状态迁移必须走条件更新（CAS）。
            //    无谓词 updateById 即使「同时也调了 markXxx」也必须红 —— 否则只要把调用留着、
            //    真正落库的换成 updateById，判据就会被一句 `if (false && …)` 骗过去（实证过）。
            if (INBOUND_UPDATE_BY_ID.matcher(e.getValue().body()).find()) {
                problems.add("状态写路径里出现了无谓词 updateById（必须走 CAS）: " + name);
            }
        }
        for (Map.Entry<String, String> r : registered.entrySet()) {
            MethodBody body = candidates.get(bareMethod(r.getKey()));
            if (body == null) {
                problems.add("台账给不存在的写路径盖章: " + r.getKey());
            } else if (r.getValue() != null && !body.body().contains(r.getValue())) {
                problems.add("写路径未兑现：主张的 " + r.getKey() + " 收口锚不在方法体里（" + r.getValue() + "）");
            }
        }
        // 🔴 已收编的「非状态写」写面：不许自己变成状态迁移（issue #6956 · 洞 A 的新对象 create 走这条）
        for (Map.Entry<String, String> f : statusWriteForbidden.entrySet()) {
            MethodBody body = candidates.get(bareMethod(f.getKey()));
            if (body == null) {
                problems.add("台账给不存在的写面盖章（禁止清单）: " + f.getKey());
            } else if (f.getValue() != null && body.body().contains(f.getValue())) {
                problems.add("写面 " + f.getKey() + " 出现了状态迁移（" + f.getValue()
                        + "）—— 它必须改登记为状态迁移写路径并兑现 CAS 收口锚");
            }
        }
        return problems;
    }

    /** 台账里的写路径形态是 {@code <类>#<方法>} ⇒ 与现取的方法名比较前先归一。 */
    private static String bareMethod(String name) {
        int hash = name.indexOf('#');
        return hash < 0 ? name : name.substring(hash + 1);
    }

    /**
     * 方法体里是否**写 {@code status} 列**（现取，两种形态）：① 实体侧 setter
     * （{@code setStatus(…)} / {@code .set(InboundOrder::getStatus, …)}）；
     * ② 该 mapper 的状态写面（{@code markXxx(…)} 或 {@code updateById(…)} —— 后者是**保守**取法：
     * 过近似会把「只改非状态列的 {@code updateById}」也算进来，所以它只用来判**豁免越界**，
     * 不用来判「状态迁移」（后者看登记名单）。</p>
     */
    private static boolean bodyWritesStatusColumn(String methodBody) {
        return INBOUND_STATUS_SETTER.matcher(methodBody).find();
    }

    /** 现取：mapper 里**在 SET 侧写 {@code status}** 的手写 SQL（方法名 + SQL 文本）。 */
    private static List<MapperWrite> mapperStatusWrites(String mapperText) {
        List<MapperWrite> out = new ArrayList<>();
        Matcher m = UPDATE_ANNOTATION.matcher(mapperText);
        while (m.find()) {
            String sql = toSql(m.group(1));
            String upper = sql.toUpperCase();
            if (!upper.contains("UPDATE " + TABLE.toUpperCase()) || !writesStatusColumn(sql)) {
                continue;
            }
            out.add(new MapperWrite(methodAfter(mapperText, m.end()), sql));
        }
        return out;
    }

    /** 把 Java 注解值（可能跨行、由多个字符串字面量 `+` 拼接）还原成一行 SQL。 */
    private static String toSql(String annotationValue) {
        return annotationValue.replace("\"", "").replace("+", " ").replaceAll("\\s+", " ").trim();
    }

    /** SET 侧是否写 {@code status}（只看 {@code SET … WHERE} 之间的片段，避免被 WHERE 里的 status 谓词骗到）。 */
    private static boolean writesStatusColumn(String sql) {
        String upper = sql.toUpperCase();
        int set = upper.indexOf(" SET ");
        int where = upper.indexOf(" WHERE ");
        String setClause = upper.substring(set < 0 ? 0 : set, where < 0 ? upper.length() : where);
        return Pattern.compile("(^|,|\\s)STATUS\\s*=").matcher(setClause).find();
    }

    /**
     * **签名归一（issue #6956 · 洞 A）**：若 {@code i} 是类体顶层的一个**多行签名**起点，
     * 返回该签名收尾行的下标（{@code ") {"} 所在行）；否则返回 {@code i}。
     *
     * <p>旧实现只看「这一行里同时出现 {@code (} 与 {@code ") {"}」⇒ 签名跨行的方法<b>整个方法体
     * 从未被收集</b>（实证：{@code InboundOrderService#create(…, String forcedSource)} 的
     * {@code updateById} 没有任何东西看着它）。这里只做一件朴素的事：从**类体顶层、且以修饰符开头**
     * 的行起，把括号数没配平的行并进来，直到括号配平 —— 不依赖「一行收尾」这个脆形态。</p>
     *
     * <p>为什么「以修饰符开头」是必需的前置：控制结构（{@code if (…)} / {@code for (…)}）在行形态上
     * 与方法头同形，而本归一化**只允许在顶层签名起点触发**；方法体内（深度 &gt; 1）的条件多行
     * 不会被并进来（那些本来就在已收集的方法体里，不需要归一）。</p>
     */
    private static int signatureBlockEnd(List<String> lines, int i) {
        String first = lines.get(i);
        if (!MEMBER_HEAD_START.matcher(first).find() || !first.contains("(")) {
            return i;
        }
        if (first.contains(BODY_OPEN)) {
            return i;
        }
        int parens = countOf(first, '(') - countOf(first, ')');
        for (int j = i + 1; j < lines.size() && parens > 0; j++) {
            parens += countOf(lines.get(j), '(') - countOf(lines.get(j), ')');
            if (parens <= 0) {
                return lines.get(j).contains(BODY_OPEN) ? j : i;
            }
        }
        return i;
    }

    private static int countOf(String s, char c) {
        int n = 0;
        for (int i = 0; i < s.length(); i++) {
            if (s.charAt(i) == c) {
                n++;
            }
        }
        return n;
    }

    /**
     * 现取：{@code service} 文本里「类体顶层的方法 + 其方法体」。
     *
     * <p>⚠️ 实现口径（本判据踩过的坑，写在这里免得下一个人再踩）：**逐行扫描 + 花括号深度**，
     * 不靠「缩进 + 标识符 + 一对复杂正则」——后者曾把整个判据变成**静默失明**（候选集恒为空，
     * 而空集在结果列上看着像「通过」）。行扫描只看三条朴素事实：① 深度 == 1（类体顶层）；
     * ② 行首恰为 4 空格缩进（8/12 ⇒ 控制结构 / lambda）；③ 归一后的签名行含 {@code ") {"}
     * 且不是注释 / 注解行。名字取「第一个 `(` 之前的最后一段」。</p>
     *
     * <p>🔴 **签名可跨行**（issue #6956 · 洞 A）：③ 里的「归一后的签名行」由
     * {@link #signatureBlockEnd} 把多行签名并成一行后再判 —— 否则「签名跨行」= 整条写路径隐身。</p>
     */
    private static List<MethodBody> membersWithBody(String text) {
        List<MethodBody> out = new ArrayList<>();
        List<String> lines = List.of(text.replace("\r", "").split("\n", -1));
        // ① 签名归一：把类体顶层的多行签名并成一个「签名行」（issue #6956 · 洞 A），
        //    同时记下每个签名行覆盖的原始行区间 —— 正文从区间末尾的下一行起。
        Map<String, Integer> heads = new LinkedHashMap<>();   // 归一后的签名行 -> 原始收尾行
        int i = 0;
        while (i < lines.size()) {
            int end = signatureBlockEnd(lines, i);
            String effective = end == i ? lines.get(i) : String.join(" ", lines.subList(i, end + 1));
            String trimmed = effective.strip();
            boolean signatureLine = lines.get(i).startsWith(MEMBER_INDENT)
                    && !lines.get(i).startsWith(MEMBER_INDENT + " ")
                    && trimmed.contains(BODY_OPEN) && trimmed.contains("(")
                    && !trimmed.startsWith("*") && !trimmed.startsWith("//") && !trimmed.startsWith("@");
            if (signatureLine) {
                String head = trimmed.substring(0, trimmed.indexOf('('));
                int sp = head.lastIndexOf(' ');
                String candidate = (sp < 0 ? head : head.substring(sp + 1)).strip();
                if (!candidate.isEmpty() && !CONTROL_KEYWORDS.contains(candidate)) {
                    heads.put(candidate + "@" + i, end);
                }
            }
            i = end + 1;
        }
        // ② 花括号深度：类体顶层（depth 1 → 2）进入方法体，回到 1 结束 ⇒ 取 [签名收尾+1, 结束行) 的原文。
        int depth = 0;
        int start = -1;
        String name = null;
        int signatureEnd = -1;
        for (int k = 0; k < lines.size(); k++) {
            if (depth == 1) {
                for (Map.Entry<String, Integer> h : heads.entrySet()) {
                    if (h.getValue() == k) {
                        name = h.getKey().substring(0, h.getKey().lastIndexOf('@'));
                        signatureEnd = h.getValue();
                        start = k;
                        break;
                    }
                }
            }
            String line = lines.get(k);
            for (int p = 0; p < line.length(); p++) {
                char ch = line.charAt(p);
                if (ch == '{') {
                    depth++;
                } else if (ch == '}') {
                    depth--;
                    if (depth == 1 && start >= 0) {
                        StringBuilder body = new StringBuilder();
                        for (int b = signatureEnd + 1; b < k; b++) {
                            body.append(lines.get(b)).append('\n');
                        }
                        out.add(new MethodBody(name, body.toString()));
                        start = -1;
                        name = null;
                        signatureEnd = -1;
                    }
                }
            }
        }
        return out;
    }

    /** 现取：service 里**出现状态列写**的方法（方法名 + 方法体）。 */
    private static List<MethodBody> serviceStatusWriteCandidates(String serviceText) {
        List<MethodBody> out = new ArrayList<>();
        for (MethodBody m : membersWithBody(serviceText)) {
            if (INBOUND_UPDATE_BY_ID.matcher(m.body()).find() || MAPPER_CAS_CALL.matcher(m.body()).find()) {
                out.add(m);
            }
        }
        return out;
    }

    /** 现取：候选方法名清单（读数用）。 */
    private static List<String> serviceStatusWritePaths(String serviceText) {
        return serviceStatusWriteCandidates(serviceText).stream().map(MethodBody::name).toList();
    }

    private static String methodAfter(String text, int from) {
        Matcher m = Pattern.compile("\\s+(\\w+)\\s*\\(").matcher(text.substring(from));
        return m.find() ? m.group(1) : "<unknown>";
    }

    private record MapperWrite(String method, String sql) {
    }

    private record MethodBody(String name, String body) {
    }

    // ────────────────────────────────────────────── 语料构造（合成判据用）

    /** 合成 mapper 语料：`(方法签名, SQL)` 交替传入。 */
    private static String mapperCorpus(String... signatureAndSqlPairs) {
        StringBuilder sb = new StringBuilder("public interface X {\n");
        for (int i = 0; i + 1 < signatureAndSqlPairs.length; i += 2) {
            sb.append("    @Update(\"").append(signatureAndSqlPairs[i + 1]).append("\")\n")
                    .append("    ").append(signatureAndSqlPairs[i]).append("\n");
        }
        return sb.append("}\n").toString();
    }

    private static String serviceCorpus(String method, String methodBody) {
        return "public class X {\n    public void " + method + "(String id) {\n        "
                + methodBody + "\n    }\n}\n";
    }

    /**
     * 合成 service 方法 —— **签名跨两行**（洞 A 的病灶形态，逐字抄真源码
     * {@code InboundOrderService#create(InboundOrderCreateRequest req, Long tenantId, String operator,}
     * {@code String forcedSource)} 的断行位置）。
     */
    private static String multilineSignatureCorpus(String method, String methodBody) {
        return "public class X {\n    public void " + method + "(String id,\n"
                + "                        String second) {\n        "
                + methodBody + "\n    }\n}\n";
    }

    // ────────────────────────────────────────────── 语料读取

    private static String mapperText() throws IOException {
        return Files.readString(repoRoot().resolve(MAPPER_FILE), StandardCharsets.UTF_8);
    }

    private static String serviceText() throws IOException {
        return Files.readString(repoRoot().resolve(SERVICE_FILE), StandardCharsets.UTF_8);
    }

    /** 台账里**显式声明**的状态谓词（方法短名 → 正则）；未声明 ⇒ 默认 `status='draft'`。 */
    private static Map<String, String> declaredStatusPredicates() {
        Map<String, String> out = new LinkedHashMap<>();
        try {
            for (JsonNode e : ledger().get("entries")) {
                if (e.hasNonNull("status_predicate")) {
                    String method = e.get("method").asText();
                    out.put(method.substring(method.lastIndexOf('#') + 1),
                            e.get("status_predicate").asText());
                }
            }
        } catch (IOException e) {
            throw new java.io.UncheckedIOException(e);
        }
        return out;
    }

    private static JsonNode ledger() throws IOException {
        return JSON.readTree(Files.readString(repoRoot().resolve(LEDGER_PATH), StandardCharsets.UTF_8));
    }

    /** 仓根（Surefire 的工作目录 = {@code backend/admin-api}，向上找到台账所在层）。 */
    private static Path repoRoot() {
        Path root = Paths.get(System.getProperty("user.dir")).toAbsolutePath();
        while (root != null && !Files.exists(root.resolve(LEDGER_PATH))) {
            root = root.getParent();
        }
        assertThat(root).as("必须能定位 " + LEDGER_PATH).isNotNull();
        return root;
    }
}
