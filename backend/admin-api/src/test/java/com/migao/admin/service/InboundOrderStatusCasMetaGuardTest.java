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
    /**
     * 取方法体的两种实现 —— 只为**对账**（判据 {@code blindSpotReconciliationHasTeeth}）而并存：
     * <ul>
     *   <li>{@link #membersWithBodyRaw} = 本守卫 <b>issue #6956 修前</b>的取块实现（逐行 + 花括号深度，
     *       <b>不剥注释 / 字符串</b>）。它在这里<b>不是</b>被测实现，而是<b>负控</b>：它必须在坏形态语料上
     *       当场暴露盲区 —— 否则「对账治具有没有牙」这件事本身就不可判（会退化成恒绿）。</li>
     *   <li>{@link #membersWithBody} = 修后实现：<b>先剥注释与字符串字面量，再做 balanced-brace 扫描</b>。</li>
     * </ul>
     * <p>形态①（跨行签名）已由 <b>PR #6967</b> 修在 main 上（冻结锚 = {@code scannersAreNotBlind} 里的
     * {@code create} 断言），本包<b>不动</b>它；本包治的是<b>形态②</b>（注释 / 字符串里的括号让深度计数器
     * 错位），两个方向都覆盖 —— <b>深度多算</b> ⇒ 其后整段方法<b>扫不到</b>；<b>深度提前归位</b> ⇒
     * 方法在候选集里但 <b>body 被截断</b>（「收错了」比「没收到」更坏：判据会<b>基于错误的 body 判绿</b>）。</p>
     */
    private static final boolean RAW_SCANNER = false;
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
            if (!DRAFT_PREDICATE.matcher(w.sql()).find()) {
                missing.add("status='draft' 谓词");
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

    // ────────────────────────────────────────────── 判据 9：盲区对账（issue #6956 第二部分）

    /**
     * 🔴 <b>本包的核心治具：对账「看不见 / 看错了」的对象</b>（issue #6956 第二部分）。
     *
     * <p>为什么单靠「候选集非空」不够：「漏一条」还能靠对账发现，「<b>一整块不可见</b>」连对账都不知道
     * 要查什么 —— 所以这里把「扫描器候选集」与「<b>按朴素签名正则独立现取的方法名全集</b>」逐条对比，
     * <b>打印并判红差集</b>。差集非空 = 病。</p>
     *
     * <p>覆盖形态②的三个真向量（②的修法是「先剥注释与字符串，再做 balanced-brace 扫描」）：</p>
     * <ol>
     *   <li><b>注释里的孤立 {@code &#123;}</b> ⇒ 深度多算 ⇒ 其后整段方法<b>扫不到</b>；</li>
     *   <li><b>字符串字面量里的 {@code &#123;} / {@code &#125;}</b>（{@code "{"} / 正则 / 文本块）⇒ 同上；</li>
     *   <li><b>注释里的孤立 {@code &#125;}</b> ⇒ 深度<b>提前</b>回到 1 ⇒ 方法<b>在候选集里但 body 被截断</b>
     *       —— 「收错了」比「没收到」更坏（判据会<b>基于错误的 body 判绿</b>）。</li>
     * </ol>
     * <p>形态①（跨行签名）<b>已由 PR #6967 修在 main 上</b>，本包不动它 —— 它的冻结锚与反转对照语料
     * （{@code guardHasDiscriminatingPower} 里那两条 {@code wrappedSignatureService}）继续当回归门。</p>
     */
    @Test
    @DisplayName("盲区对账：注释 / 字符串里的括号不得让其后方法隐形或 body 被截断（差集非空即红）")
    void blindSpotReconciliationHasTeeth() {
        // 合规基线：干净语料必须**零差集**（否则下面三格的判红可能只是噪声）
        String cleanService = serviceCorpus("post", "inboundOrderMapper.markPosted(id);")
                + serviceCorpus("cancel", "inboundOrderMapper.markCancelled(id);");
        System.out.println("[READING MC-100 对账 基线] 差集=" + reconciliation(cleanService));
        assertThat(reconciliation(cleanService))
                .as("干净语料不得有差集（对账不许把正常语料喂红）").isEmpty();

        // ── 向量 1：注释里的孤立 `{` ⇒ 深度多算 ⇒ 其后方法整段扫不到
        String commentBrace = serviceCorpus("updateStatus", "inboundOrderMapper.markStatusIfFrom(id);")
                + orphanOpenBraceCommentCorpus("reopen", "inboundOrderMapper.updateById(order);");
        System.out.println("[READING MC-100 对账 向量1 注释孤立花括号] 修前可见="
                + serviceStatusWritePaths(commentBrace, true) + " 修后可见="
                + serviceStatusWritePaths(commentBrace) + " 差集=" + reconciliation(commentBrace));
        assertThat(serviceStatusWritePaths(commentBrace, true))
                .as("负控自证生效：修前取法必须在向量1上**看不见** reopen（否则对账的判红没有牙）")
                .doesNotContain("reopen");
        assertThat(serviceStatusWritePaths(commentBrace))
                .as("修后必须看得见 reopen（注释里的孤立 `{` 不得让其后方法隐形）")
                .contains("reopen");
        assertThat(reconciliation(commentBrace))
                .as("🔴 对账差集非空 ⇒ 必须判红：reopen 在「看不见的对象」清单里")
                .isNotEmpty();

        // ── 向量 2：字符串字面量里的 `{` / `}` ⇒ 同族失明
        String stringBrace = serviceCorpus("updateStatus",
                "String fragment = \"a{b\";\ninboundOrderMapper.markStatusIfFrom(id);")
                + serviceCorpus("reopen", "inboundOrderMapper.updateById(order);");
        System.out.println("[READING MC-100 对账 向量2 字符串字面量花括号] 修前可见="
                + serviceStatusWritePaths(stringBrace, true) + " 修后可见="
                + serviceStatusWritePaths(stringBrace) + " 差集=" + reconciliation(stringBrace));
        assertThat(serviceStatusWritePaths(stringBrace, true))
                .as("负控自证生效：修前取法必须在向量2上**看不见** reopen").doesNotContain("reopen");
        assertThat(serviceStatusWritePaths(stringBrace))
                .as("修后必须看得见 reopen（字符串字面量里的 `{` 不得让其后方法隐形）")
                .contains("reopen");
        assertThat(reconciliation(stringBrace)).as("🔴 差集非空 ⇒ 判红").isNotEmpty();

        // ── 向量 3（**更坏**）：注释里的孤立 `}` 出现在**方法体第一行** ⇒ 深度提前归位 ⇒
        //    **方法名在候选集里，但 body 被截断成空壳** ⇒ 判据**基于错误的 body 判绿**。
        String truncatedBody = truncatedBodyCorpus("updateStatus",
                "inboundOrderMapper.updateById(order);");
        Map<String, String> seenBody = new LinkedHashMap<>();
        for (MethodBody m : membersWithBody(truncatedBody)) {
            seenBody.put(m.name(), m.body());
        }
        System.out.println("[READING MC-100 对账 向量3 注释孤立闭花括号⇒body被截断] 修前候选="
                + serviceStatusWritePaths(truncatedBody, true) + " 修后候选="
                + serviceStatusWritePaths(truncatedBody) + " 修后方法体="
                + seenBody.getOrDefault("updateStatus", "<无>").replace("\n", "\\n")
                + " 差集=" + reconciliation(truncatedBody));
        assertThat(serviceStatusWritePaths(truncatedBody, true))
                .as("负控自证生效：修前取法在向量3上**看得见** updateStatus 这个方法名，但它的 body 被截断成"
                        + "空壳 ⇒ 该写点不在候选集里 —— 所以「方法不见了」这条判据在这里**抓不到它**，"
                        + "这正是它比「扫不到」更坏的原因")
                .doesNotContain("updateStatus");
        assertThat(serviceStatusWritePaths(truncatedBody))
                .as("修后必须把 updateStatus 收进候选集（它真的有状态写）")
                .contains("updateStatus");
        assertThat(seenBody.getOrDefault("updateStatus", ""))
                .as("修后 updateStatus 的 body 必须逐字含它真正的写点（不是被截断的空壳）")
                .contains("inboundOrderMapper.updateById(");
        assertThat(reconciliation(truncatedBody))
                .as("🔴 对账差集非空 ⇒ 判红（报出「看不见的写路径」；body 被截断的形态由此被抓住）")
                .isNotEmpty();

        // ── 差集必须**有牙**（不误杀 + 真报错）：
        //   ① 干净语料 ⇒ 差集为空（不是恒非空）；
        //   ② 向量3 那份语料 ⇒ 差集**非空且具名** —— 证明「看错了 body」这条对账真的在比对 body，
        //      而不是被文案喂红。
        assertThat(reconciliation(cleanService))
                .as("干净语料 ⇒ 对账必须为空（差集不是恒非空）").isEmpty();
        assertThat(reconciliation(truncatedBody))
                .as("向量3 的 body 被截断 ⇒ 对账必须非空且具名报出被看错的对象")
                .anySatisfy(p -> assertThat(p).contains("看错了 body").contains("updateStatus"));
    }

    /**
     * 现取：候选方法名清单（读数用）。{@code raw} = 走**修前**取块实现（负控 / 对账用）。
     */
    private static List<String> serviceStatusWritePaths(String serviceText, boolean raw) {
        List<MethodBody> members = raw ? membersWithBodyRaw(serviceText) : membersWithBody(serviceText);
        List<String> out = new ArrayList<>();
        for (MethodBody m : members) {
            if (INBOUND_UPDATE_BY_ID.matcher(m.body()).find() || MAPPER_CAS_CALL.matcher(m.body()).find()) {
                out.add(m.name());
            }
        }
        return out;
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
     * 现取：{@code service} 文本里「类体顶层的方法 + 其方法体」。
     *
     * <p>⚠️ 实现口径（本判据踩过的坑，写在这里免得下一个人再踩）：**逐行扫描 + 花括号深度**，
     * 不靠「缩进 + 标识符 + 一对复杂正则」——后者曾把整个判据变成**静默失明**（候选集恒为空，
     * 而空集在结果列上看着像「通过」）。行扫描只看三条朴素事实：① 深度 == 1（类体顶层）；
     * ② 行首恰为 4 空格缩进（8/12 ⇒ 控制结构 / lambda）；③ 行内含 {@code ") {"} 且不是注释 / 注解行。
     * 名字取「第一个 `(` 之前的最后一段」。</p>
     *
     * <p>🔴 <b>签名可跨行</b>（issue #6956 · 洞 A，<b>已由 PR #6967 修在 main 上</b>）：用
     * <b>待定签名状态机</b> —— 见到「类体顶层 + 4 空格缩进 + `(` + 非注释 / 注解」先登记名字，
     * 到<b>第一个不深于类体的 `{`</b> 才正式开体、从该花括号之后开始收正文。
     * 本包<b>不动</b>这条（{@code create} 的冻结锚与反转对照语料继续当回归门）。</p>
     *
     * <p>🔴 <b>本包治的是形态②：注释 / 字符串字面量里的括号让深度计数器错位</b>（issue #6956 第二部分）。
     * 旧实现逐字符数 <code>&#123;</code> / <code>&#125;</code> 而<b>不剥注释 / 字符串</b> ⇒ 三个真向量：
     * ① 注释里孤立 <code>&#123;</code> ⇒ 深度多算 ⇒ <b>其后整段方法扫不到</b>；
     * ② 字符串字面量里的 <code>&#123;</code> / <code>&#125;</code>（{@code "{"} / 正则 / 文本块）⇒ 同上；
     * ③ 注释里孤立 <code>&#125;</code> ⇒ 深度<b>提前</b>回到 1 ⇒ 方法<b>在候选集里但 body 被截断</b>
     * （「收错了」比「没收到」更坏：判据会<b>基于错误的 body 判绿</b>）。
     * ⇒ 修法：<b>先剥注释与字符串（保留行结构），再做 balanced-brace 扫描</b>
     * （{@link #stripCommentsAndStrings}）。判别力由 {@code blindSpotReconciliationHasTeeth} 的
     * 三条坏形态语料 + 与 {@link #RAW_SCANNER} 负控的<b>对账</b>自证。</p>
     */
    private static List<MethodBody> membersWithBody(String text) {
        return membersWithBody(text, RAW_SCANNER);
    }

    /**
     * 取块的**唯一实现**，`raw` 只选「要不要先剥注释 / 字符串」—— 让**负控**与**被测实现**共用同一段
     * 状态机代码（避免负控变成「另一个手抄的近似物」而让对账的结论不成立）。
     */
    private static List<MethodBody> membersWithBody(String text, boolean skipStrip) {
        String clean = skipStrip ? text.replace("\r", "") : stripCommentsAndStrings(text);
        List<MethodBody> out = new ArrayList<>();
        int depth = 0;
        String name = null;
        String pending = null;
        StringBuilder body = null;
        for (String raw : clean.replace("\r", "").split("\n", -1)) {
            String trimmed = raw.strip();
            if (body == null && depth == 1
                    && raw.startsWith(MEMBER_INDENT) && !raw.startsWith(MEMBER_INDENT + " ")
                    && trimmed.contains("(")
                    && !trimmed.startsWith("*") && !trimmed.startsWith("//") && !trimmed.startsWith("@")) {
                String head = trimmed.substring(0, trimmed.indexOf('('));
                int sp = head.lastIndexOf(' ');
                String candidate = (sp < 0 ? head : head.substring(sp + 1)).strip();
                if (!candidate.isEmpty() && !CONTROL_KEYWORDS.contains(candidate)) {
                    pending = candidate;
                }
            }
            boolean activated = false;
            for (int i = 0; i < raw.length(); i++) {
                char ch = raw.charAt(i);
                if (ch == '{') {
                    depth++;
                    if (body == null && pending != null && depth == 2) {
                        name = pending;
                        pending = null;
                        body = new StringBuilder();
                        activated = true;
                    }
                } else if (ch == '}') {
                    depth--;
                    if (depth == 1 && body != null) {
                        out.add(new MethodBody(name, body.toString()));
                        body = null;
                        name = null;
                    }
                }
            }
            if (body != null && !activated) {
                body.append(raw).append('\n');
            }
        }
        return out;
    }

    /**
     * 剥掉块注释 / 行注释 / 字符串字面量 / 文本块（**保留行结构**：非换行字符变空格，换行原样留下）。
     *
     * <p>为什么必须剥（本包的核心）：花括号深度扫描要的只是「<b>真代码</b>里的括号」。注释 / 字符串里的
     * 半个括号（如 {@code // 形如 &#123;} 或 {@code "{"}）会让计数器整体错位 ⇒ 后续方法全部扫不到，
     * 或者更坏：<b>提前归位 ⇒ body 被截断而判据照绿</b>（issue #6956 第二部分的本体）。</p>
     *
     * <p>为什么不直接上 AST / JavaParser：本仓既有形态是「读源码文本」，加解析器依赖会扩大本单的
     * 改动面与启动成本；一个手写剥壳足够覆盖「注释 / 字面量里的括号」这一族
     * （判别力由合成语料的负控对账自证）。</p>
     */
    static String stripCommentsAndStrings(String src) {
        StringBuilder out = new StringBuilder(src.length());
        int i = 0;
        int n = src.length();
        while (i < n) {
            char c = src.charAt(i);
            if (src.startsWith("/*", i)) {
                int j = src.indexOf("*/", i + 2);
                j = j < 0 ? n : j + 2;
                appendBlanks(out, src, i, j);
                i = j;
            } else if (src.startsWith("//", i)) {
                int j = src.indexOf('\n', i);
                j = j < 0 ? n : j;
                appendBlanks(out, src, i, j);
                i = j;
            } else if (src.startsWith("\"\"\"", i)) {
                int j = src.indexOf("\"\"\"", i + 3);
                j = j < 0 ? n : j + 3;
                appendBlanks(out, src, i, j);
                i = j;
            } else if (c == '"' || c == '\'') {
                int j = i + 1;
                while (j < n) {
                    if (src.charAt(j) == '\\') {
                        j += 2;
                        continue;
                    }
                    if (src.charAt(j) == c) {
                        j++;
                        break;
                    }
                    j++;
                }
                appendBlanks(out, src, i, Math.min(j, n));
                i = Math.min(j, n);
            } else {
                out.append(c);
                i++;
            }
        }
        return out.toString();
    }

    /** 把 {@code [from, to)} 逐字符写成空格，**换行原样保留**（行结构与缩进判定都依赖它）。 */
    private static void appendBlanks(StringBuilder out, String src, int from, int to) {
        for (int k = from; k < to; k++) {
            out.append(src.charAt(k) == '\n' ? '\n' : ' ');
        }
    }

    /**
     * 「看不见 / 看错了」的对账（本包的核心治具 —— issue #6956 第二部分）。
     *
     * <p>口径：<b>同一份文本、两套独立取块</b> —— ① 被测实现（剥壳 + $0 深度，{@link #membersWithBody}）；
     * ② <b>两套朴素取法</b>：按「签名形态正则」现取**方法名全集**（{@link #declaredMethodNames}，
     * 它<b>完全不依赖花括号深度</b>）+ 修前的原始取块实现（{@link #RAW_SCANNER} 负控）。</p>
     *
     * <p>报出两类差集：<b>① 看不见</b> = 签名正则现取到、被测实现却没给出方法体；
     * <b>② 看错了</b> = 两边都给出同名方法，但<b>方法体逐字不同</b>（形态②的「提前归位 ⇒ body 被截断」）
     * —— 「看不见的对象才是本单的病」，而「收错了」比「没收到」更坏（判据会基于错误的 body 判绿）。
     * 差集非空 ⇒ 判据 {@code blindSpotReconciliationHasTeeth} 当场红。</p>
     */
    private static List<String> reconciliation(String serviceText) {
        List<String> problems = new ArrayList<>();
        Map<String, String> seen = new LinkedHashMap<>();
        for (MethodBody m : membersWithBody(serviceText)) {
            seen.put(m.name(), m.body());
        }
        for (String declaredName : declaredMethodNames(serviceText)) {
            if (!seen.containsKey(declaredName)) {
                problems.add("看不见的方法: " + declaredName + "（签名正则现取到了，扫器没给出方法体）");
            }
        }
        Map<String, String> raw = new LinkedHashMap<>();
        for (MethodBody m : membersWithBodyRaw(serviceText)) {
            raw.put(m.name(), m.body());
        }
        for (Map.Entry<String, String> e : raw.entrySet()) {
            if (seen.containsKey(e.getKey()) && !seen.get(e.getKey()).equals(e.getValue())) {
                problems.add("看错了 body: " + e.getKey() + "（修前取法给的是被截断的错 body）");
            }
        }
        // 🔴 差集的**主方向**：被测实现（修后）看得见、修前取法看不见的写路径 = 「看不见的对象」。
        //    本单的病就是**这个方向的差**（修前那一侧少看见一个整块），所以必须报它、且非空即红。
        Set<String> rawPaths = new LinkedHashSet<>(serviceStatusWritePaths(serviceText, true));
        for (String p : serviceStatusWritePaths(serviceText, false)) {
            if (!rawPaths.contains(p)) {
                problems.add("看不见的写路径: " + p + "（修后候选里在、修前取法整块扫不到 —— 本单的病）");
            }
        }
        return problems;
    }

    /** 对账用的**另一套**「方法名全集」现取 —— 按签名形态正则，**不依赖花括号深度**。 */
    private static List<String> declaredMethodNames(String text) {
        List<String> out = new ArrayList<>();
        for (String raw : stripCommentsAndStrings(text).replace("\r", "").split("\n", -1)) {
            String trimmed = raw.strip();
            if (raw.startsWith(MEMBER_INDENT) && !raw.startsWith(MEMBER_INDENT + " ")
                    && trimmed.contains("(") && !trimmed.startsWith("@")) {
                String head = trimmed.substring(0, trimmed.indexOf('('));
                int sp = head.lastIndexOf(' ');
                String candidate = (sp < 0 ? head : head.substring(sp + 1)).strip();
                if (!candidate.isEmpty() && !CONTROL_KEYWORDS.contains(candidate)
                        && Character.isLowerCase(candidate.charAt(0))) {
                    out.add(candidate);
                }
            }
        }
        return out;
    }

    /** 修前的取块实现（issue #6956 第二部分修前形态）—— **只在负控 / 对账里用**。 */
    private static List<MethodBody> membersWithBodyRaw(String text) {
        return membersWithBody(text, true);
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

    /**
     * 形态② · 向量 1 的合成语料：**注入方法之前**先来一行含孤立 {@code &#123;} 的注释
     * （如 {@code // 形如 { }），其后是被注入的方法。
     */
    private static String orphanOpenBraceCommentCorpus(String method, String methodBody) {
        return "public class Y {\n"
                + "    // 形如 {\n"
                + "    public void " + method + "(String id) {\n"
                + "        " + methodBody + "\n"
                + "    }\n}\n";
    }

    /**
     * 形态② · 向量 3 的合成语料（<b>「收错了」</b>）：含孤立 {@code &#125;} 的注释落在**方法体第一行** ⇒
     * 不剥注释的深度计数器<b>提前</b>归位 ⇒ 取到的 body 是**空壳**（方法名进了候选集，判据却基于错误的
     * body 判绿）。⚠️ 这条形态是**实测确定**的（写成「签名行之前」的注释只会让修前取法连方法名都丢掉，
     * 那是「扫不到」而不是「收错了」—— 两种都坏，但要分开钉）。
     */
    private static String truncatedBodyCorpus(String method, String methodBody) {
        return "public class Z {\n"
                + "    public void " + method + "(String id) {\n"
                + "        // 收尾 } 说明\n"
                + "        " + methodBody + "\n"
                + "    }\n}\n";
    }

    // ────────────────────────────────────────────── 语料读取

    private static String mapperText() throws IOException {
        return Files.readString(repoRoot().resolve(MAPPER_FILE), StandardCharsets.UTF_8);
    }

    private static String serviceText() throws IOException {
        return Files.readString(repoRoot().resolve(SERVICE_FILE), StandardCharsets.UTF_8);
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
