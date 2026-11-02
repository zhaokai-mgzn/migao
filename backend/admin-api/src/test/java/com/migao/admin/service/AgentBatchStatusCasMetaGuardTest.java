// case_ids: PR-028

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
 * 🧱 <b>类级元守卫（issue #6960）：Agent 批次状态迁移的写路径必须落到 SQL 谓词（CAS），未登记即红</b>。
 *
 * <h2>为什么需要它（只修一处 = 没修）</h2>
 * 实例判据（{@code AgentBatchStatusRaceRealDbTest}）只保证 {@code AgentBatchService#execute} /
 * {@code #revert} 这**两个**入口在并发下互斥。而 #6960 的真实教训是
 * <b>「同一份状态迁移权上的写面都不带 CAS」</b>：两者都是「先读批次判状态、
 * 再 {@code batchMapper.updateById(batch)}（WHERE 仅主键 ⇒ 无谓词）」⇒ 并发读-判-写窗口里两个请求
 * 都能 apply **一轮**（对同一批商品**重复 apply**，无任何 4xx）。下一个人在**同文件新加一条状态迁移写路径**、
 * 或给 mapper 加一条**无谓词**的状态写 SQL，没有任何东西会红 ⇒ 本守卫把「写路径清单 + 谓词完整性」
 * 钉成机械判据。
 *
 * <h2>判据（每条都会红）</h2>
 * <ol>
 *   <li><b>扫描器非空跑自证</b>：现取「写 {@code agent_batches.status} 的 mapper SQL」必须包含
 *       {@code markExecuting} 与 {@code markReverting}；现取「service 里写状态列的调用点」必须包含
 *       {@code claimForExecute} / {@code claimForRevert} / {@code runBatch} / {@code runRevert}
 *       （#8283 把同步入口拆成「抢权 + 后台执行」两半，真正写状态列的是这两半）。候选集为空 / 少了核心对象 ⇒ 先红
 *       （形态被改名不是「通过」，而是「判据失明」）。</li>
 *   <li><b>mapper 状态写 SQL 必须带完整谓词</b>：凡在 SET 侧写 {@code status} 的手写 {@code @Update}
 *       SQL，必须同时含 {@code tenant_id} 参数、来源态谓词（{@code status = '<当前态>'} 或
 *       {@code status IN (…)}，且**不得**写成 {@code status = #{…}}）、{@code deleted = 0}（⚠️ 本表**没有**这一列 ⇒ 这一条对本表为**不适用**，见 {@code carriesDeletedPredicate}）
 *       —— 少任何一条 ⇒ 红（退回「无谓词写」= 本单的病根）。</li>
 *   <li><b>service 写路径未登记即红</b>：任何方法体里出现「写状态列的调用」（{@code batchMapper.updateById(}
 *       或 {@code batchMapper.mark*(}）却不登记 ⇒ 红。</li>
 *   <li><b>台账不许给不存在的对象盖章</b>：每条 {@code entries[]} / {@code service_write_paths[]} 的
 *       {@code method} 必须仍能在现取候选集里找到（改名 / 删除 ⇒ 红）。</li>
 *   <li><b>登记未被兑现即红</b>：{@code evidence} = {@code <仓库相对路径>::<可检索文本>}，
 *       左侧文件必须存在、右侧必须在该文件里<b>逐字出现</b> ⇒ 防「给不存在的保护盖章」
 *       （摘掉 CAS 调用 / 方法改名 ⇒ 红）。</li>
 *   <li><b>豁免台账只许缩短</b>：{@code unverified} 必须是冻结基线 {@code unverified_baseline}
 *       的<b>子集</b>（新增豁免 ⇒ 红）；条数<b>现取</b>（不写死在测试代码里，读数打印在断言消息上）。</li>
 *   <li><b>判别力自证</b>：用<b>合成语料</b>在内存里跑与真实源码<b>同一套</b>判定本体 ——
 *       「去谓词（无 WHERE 条件）」「去 tenant 谓词」「来源态写成参数（谓词空转）」「谓词里写了本表不存在的
 *       {@code deleted} 列（会直接 SQL 报错）」「未登记写路径」「台账未兑现」六种坏形态各自判红，合规语料判绿。
 *       没有这条，「判据恒绿」与「判据有效」在结果列上长得一样。</li>
 * </ol>
 *
 * <p>⚠️ 本判据读<b>源码文本</b>（不做 AST）—— 本仓既有形态（{@code InboundOrderStatusCasMetaGuardTest} /
 * {@code ProductionOperationDeleteCasMetaGuardTest} 同款）。代价：它只能证明「这几个字在方法体里」；
 * <b>行为面由真库并发判据承担</b>：{@code AgentBatchStatusRaceRealDbTest}（#6960）—— 两者缺一不可
 * （{@code migao-dev-flow} §28.2：判据本体绿 ≠ 接线在）。</p>
 *
 * <p><b>未固化项（如实登记，不粉饰）</b>：见台账 {@code coverage_boundary} ——
 * ① 形态判据换措辞可绕过（真实防线仍是实例判据）；② 射程只到
 * {@code AgentBatchService} + {@code AgentBatchMapper} 这一对文件；③ 判不了「拿 {@code updateById}
 * 改**非状态**列」（那不是本表的对象）；③b **本单有意不加方法级 {@code @Transactional}**（类注释取舍 ②③）⇒
 * 本表主张的是「准入闸 = 单条语句的 CAS」，不主张事务边界；④ 本守卫<b>不</b>跑被它引用的那条真库判据；
 * ⑤ 本守卫<b>不改</b>任何门禁的通过条件、不新增豁免。</p>
 */
@DisplayName("🧱 类级元守卫（#6960）：Agent 批次状态迁移写路径必须落到 SQL 谓词（未登记即红 + 豁免只许缩短）")
class AgentBatchStatusCasMetaGuardTest {

    /** 模块根（Surefire 的工作目录 = {@code backend/admin-api}）；台账里的引用一律是**仓库相对全路径**。 */
    private static final String MODULE = "backend/admin-api";
    private static final String MAIN = MODULE + "/src/main/java/com/migao/admin";
    private static final String MAPPER_FILE = MAIN + "/mapper/AgentBatchMapper.java";
    private static final String SERVICE_FILE = MAIN + "/service/AgentBatchService.java";
    private static final String LEDGER_PATH = MODULE + "/src/test/resources/agent-batch-status-cas-ledger.json";

    // ── 形态（与台账 scan 段的声明逐字对应）

    /** 手写 update 注解的**取块**（到配对的 `)` 为止；SQL 自带括号 ⇒ 先取块再剥 Java 语法）。 */
    private static final Pattern UPDATE_ANNOTATION =
            Pattern.compile("@Update\\s*\\(((?:[^()]|\\([^()]*\\))*)\\)");
    /** 写面表名。 */
    private static final String TABLE = "agent_batches";
    /** 「状态列写」的两种调用形态。 */
    private static final Pattern SERVICE_UPDATE_BY_ID = Pattern.compile("batchMapper\\.updateById\\(");
    /** 该 mapper 的手写状态迁移写面（现取，不写死）：`batchMapper.markXxx(`。 */
    private static final Pattern MAPPER_CAS_CALL = Pattern.compile("batchMapper\\.(mark\\w+)\\(");
    /** 谓词 / 参数要求（issue #6960 的口径）。 */
    private static final Pattern TENANT_PARAM =
            Pattern.compile("#\\{\\s*tenantI?d\\s*\\}", Pattern.CASE_INSENSITIVE);
    /** 来源态谓词：`status = 'available'`（字面量）或 `status IN (…)`（值由服务层传参）。 */
    private static final Pattern SOURCE_STATUS_PREDICATE = Pattern.compile(
            "status\\s*(=\\s*'|IN\\s*\\()", Pattern.CASE_INSENSITIVE);
    /** 空转谓词：`status = #{…}` —— 参数为 null 时 WHERE 退化成「无条件」（判据当场失效）。 */
    private static final Pattern STATUS_PARAM_PREDICATE =
            Pattern.compile("status\\s*=\\s*#\\{", Pattern.CASE_INSENSITIVE);
    /** 「受影响行数 0 ⇒ 拒绝」的判定形态（与 {@code ProductionOperationDeleteCasMetaGuardTest} 同款）。 */
    private static final Pattern ROW_COUNT_CHECK = Pattern.compile("==\\s*0\\s*\\)");
    /** CAS 调用后多远内必须出现行数判定（够长以容纳多行实参，够短以不被远端的无关 `== 0` 骗过）。 */
    private static final int ROW_COUNT_WINDOW = 300;

    private static final Pattern DELETED_PREDICATE =
            Pattern.compile("deleted\\s*=\\s*0", Pattern.CASE_INSENSITIVE);
    /** 方法体收尾形态（`… ) {`）：真方法的长签名可跨行 ⇒ 判「签名行」时只看「出现 `) {`」。 */
    private static final String BODY_OPEN = ") {";
    /** 类体顶层的缩进（4 空格）；嵌套块（控制结构 / lambda）更深 ⇒ 靠它把方法从体内区分出来。 */
    private static final String MEMBER_INDENT = "    ";
    /** Java 控制结构关键字：`if (…) {` 在行形态上与「方法 + 体」同形，靠名字排除。 */
    private static final Set<String> CONTROL_KEYWORDS = Set.of(
            "if", "for", "while", "switch", "catch", "synchronized", "try", "do", "else", "return");

    /**
     * 本表**有没有** {@code deleted} 列（issue #6960 的硬前提，逐字核对 {@code schema.sql}）：
     * {@code agent_batches} 的 DDL 里**没有**这一列 ⇒ 谓词里出现 {@code deleted = 0} 会直接 SQL 报错，
     * 本表判它**必须有**就是照抄模板照出来的假判据。故该条对本表 = 不适用，改为判「不许出现」。
     */
    private static final boolean CARRIES_DELETED_COLUMN = false;

    private static final ObjectMapper JSON = new ObjectMapper();

    // ────────────────────────────────────────────── 判据 1~6：真语料

    @Test
    @DisplayName("扫描器非空跑自证：现取写 status 的 mapper SQL 与 service 写路径必须包含核心对象")
    void scannersAreNotBlind() throws IOException {
        List<String> mapperMethods = mapperStatusWrites(mapperText()).stream().map(MapperWrite::method).toList();
        List<String> servicePaths = serviceStatusWritePaths(serviceText());

        System.out.println("[READING PR-028 扫描器] 写 status 的 mapper 方法=" + mapperMethods
                + " service 写路径=" + servicePaths);
        assertThat(mapperMethods)
                .as("扫描器必须现取到写 status 的 mapper 手写 SQL（返回空集 = 判据失明，不是通过）")
                .contains("markExecuting", "markReverting");
        assertThat(servicePaths)
                .as("扫描器必须现取到 service 里写状态列的调用点（返回空集 = 判据失明，不是通过）")
                .contains("claimForExecute", "claimForRevert", "runBatch", "runRevert");
    }

    @Test
    @DisplayName("mapper 状态写 SQL 必须带完整谓词（tenant_id + 来源态 + deleted=0，且来源态不得是参数）")
    void everyStatusWriteCarriesTheFullPredicate() throws IOException {
        List<MapperWrite> writes = mapperStatusWrites(mapperText());
        List<String> offenders = new ArrayList<>();
        for (MapperWrite w : writes) {
            List<String> missing = new ArrayList<>();
            if (!TENANT_PARAM.matcher(w.sql()).find()) {
                missing.add("tenant_id 参数");
            }
            if (!SOURCE_STATUS_PREDICATE.matcher(w.sql()).find()
                    || STATUS_PARAM_PREDICATE.matcher(w.sql()).find()) {
                missing.add("来源态谓词（status = '<字面量>' 或 status IN (…)；参数化 = 空转）");
            }
            if (CARRIES_DELETED_COLUMN != DELETED_PREDICATE.matcher(w.sql()).find()) {
                missing.add(CARRIES_DELETED_COLUMN
                        ? "deleted=0 谓词"
                        : "谓词里出现了本表**不存在**的 deleted 列（会直接 SQL 报错）");
            }
            if (!missing.isEmpty()) {
                offenders.add(w.method() + " 缺 " + missing);
            }
        }
        System.out.println("[READING PR-028 谓词] 状态写面="
                + writes.stream().map(MapperWrite::method).toList() + " 违规=" + offenders);
        assertThat(offenders).as("状态迁移的写必须把判断与写入压进同一条语句（无谓词写 = #6960 的病根）")
                .isEmpty();
    }

    @Test
    @DisplayName("service 写路径未登记即红 + 台账不许给不存在的对象盖章 + 豁免只许缩短")
    void serviceWritePathsAreRegisteredAndLedgerIsFaithful() throws IOException {
        JsonNode ledger = ledger();
        List<String> servicePaths = serviceStatusWritePaths(serviceText());
        Map<String, String> registered = new LinkedHashMap<>();
        for (JsonNode e : ledger.get("service_write_paths")) {
            registered.put(e.get("method").asText(), e.get("call_anchor").asText());
        }
        Set<String> registeredBare = registered.keySet().stream()
                .map(AgentBatchStatusCasMetaGuardTest::bareMethod)
                .collect(Collectors.toCollection(LinkedHashSet::new));
        List<String> unregistered = servicePaths.stream().filter(p -> !registeredBare.contains(p)).toList();
        List<String> ghosts = registeredBare.stream().filter(r -> !servicePaths.contains(r)).toList();
        int unverified = ledger.get("unverified").size();
        int baseline = ledger.get("unverified_baseline").asInt();

        System.out.println("[READING PR-028 台账] 现取写路径=" + servicePaths + " 已登记=" + registered
                + " 未登记=" + unregistered + " 幽灵条目=" + ghosts
                + " 豁免=" + unverified + "(基线 " + baseline + ")");
        assertThat(unregistered)
                .as("新增状态迁移写路径必须登记进台账 —— 未登记就是「下一个 #6960」").isEmpty();
        assertThat(ghosts).as("台账不许给不存在的写路径盖章（改名 / 删除 ⇒ 红）").isEmpty();
        assertThat(unverified).as("豁免台账只许缩短（新增豁免必须走 issue + 重启条件）")
                .isLessThanOrEqualTo(baseline);
    }

    @Test
    @DisplayName("登记未被兑现即红：每条 evidence 锚必须在它声称的文件里逐字出现")
    void everyEvidenceAnchorIsLive() throws IOException {
        JsonNode ledger = ledger();
        Path root = repoRoot();
        List<String> broken = new ArrayList<>();
        for (String section : List.of("entries", "service_write_paths")) {
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
        System.out.println("[READING PR-028 兑现] 断链=" + broken);
        assertThat(broken).as("evidence 必须逐字兑现（摘掉 CAS 调用 / 方法改名 ⇒ 当场红）").isEmpty();
    }

    @Test
    @DisplayName("状态迁移写路径必须至少有一次条件更新（CAS）；整条路径零 CAS ⇒ 红")
    void noStatusWritePathUsesUnconditionalUpdateById() throws IOException {
        List<String> offenders = new ArrayList<>();
        for (MethodBody m : serviceStatusWriteCandidates(serviceText())) {
            offenders.addAll(casProblems(m.body(), m.name()));
        }
        System.out.println("[READING PR-028 无谓词写] 现取候选方法=" + serviceStatusWritePaths(serviceText())
                + " 违规=" + offenders);
        assertThat(offenders)
                .as("状态迁移的写路径必须**至少有一次** CAS 收口；整条路径零 CAS = #6960 的病根")
                .isEmpty();
    }

    // ────────────────────────────────────────────── 判据 7：合成语料判别力自证

    @Test
    @DisplayName("判别力自证（合成语料）：八种坏形态各自判红、合规语料判绿")
    void guardHasDiscriminatingPower() {
        // 合规：与真源码同形的两条 CAS + 两条调用点（没有 deleted 列 ⇒ 谓词里也不写它）
        String goodMapper = mapperCorpus(
                "int markExecuting(@Param(\"id\") String id);",
                "UPDATE agent_batches SET status = 'executing' "
                        + "WHERE id = #{id} AND tenant_id = #{tenantId} AND status = 'preview'",
                "int markReverting(@Param(\"id\") String id);",
                "UPDATE agent_batches SET status = 'executing' "
                        + "WHERE id = #{id} AND tenant_id = #{tenantId} AND status IN (#{a}, #{b})");
        String goodService = serviceCorpus("execute",
                "if (batchMapper.markExecuting(batchId, tenantId) == 0) { throw conflict(); }")
                + serviceCorpus("revert",
                "if (batchMapper.markReverting(batchId, tenantId, STATUS_DONE, STATUS_PARTIAL) == 0) { throw conflict(); }");
        Map<String, String> registered = new LinkedHashMap<>();
        registered.put("execute", "batchMapper.markExecuting(");
        registered.put("revert", "batchMapper.markReverting(");

        assertThat(problems(goodMapper, goodService, registered))
                .as("合规语料判绿（否则本守卫是恒红噪声）").isEmpty();

        // 坏形态 ①：无谓词状态写（= #6960 的病根本体）
        assertThat(problems(mapperCorpus("int markExecuting(@Param(\"id\") String id);",
                        "UPDATE agent_batches SET status = 'executing' WHERE id = #{id}"),
                goodService, registered))
                .as("无谓词状态写必须判红").isNotEmpty();

        // 坏形态 ②：谓词里写了本表**不存在**的 deleted 列（照抄模板的形态 ⇒ SQL 直接报错）
        assertThat(problems(mapperCorpus("int markExecuting(@Param(\"id\") String id);",
                        "UPDATE agent_batches SET status = 'executing' WHERE id = #{id} "
                                + "AND tenant_id = #{tenantId} AND status = 'preview' AND deleted = 0"),
                goodService, registered))
                .as("谓词里出现本表不存在的列必须判红（本仓出过「模板写了 deleted=0 但该表没有这一列」）")
                .isNotEmpty();

        // 坏形态 ③：缺 tenant 谓词（跨租户可写）
        assertThat(problems(mapperCorpus("int markExecuting(@Param(\"id\") String id);",
                        "UPDATE agent_batches SET status = 'executing' WHERE id = #{id} "
                                + "AND status = 'preview'"),
                goodService, registered))
                .as("缺 tenant 谓词必须判红").isNotEmpty();

        // 坏形态 ④：来源态写成参数（谓词空转 ⇒ 传 null 就是无条件写）
        assertThat(problems(mapperCorpus("int markExecuting(@Param(\"id\") String id);",
                        "UPDATE agent_batches SET status = 'executing' WHERE id = #{id} "
                                + "AND tenant_id = #{tenantId} AND status = #{expectedStatus}"),
                goodService, registered))
                .as("来源态谓词参数化（空转）必须判红").isNotEmpty();

        // 坏形态 ⑤：service 新加一条未登记的状态写路径
        assertThat(problems(goodMapper, goodService + serviceCorpus("retry",
                        "batchMapper.updateById(batch);"), registered))
                .as("未登记的状态迁移写路径必须判红（这就是「只修一处」的复发形态）").isNotEmpty();

        // 坏形态 ⑥：台账未兑现（CAS 调用被摘掉 / 改名）
        assertThat(problems(goodMapper,
                        goodService.replace("batchMapper.markReverting(", "batchMapper.someOtherWrite("),
                        registered))
                .as("台账锚被摘掉必须判红").isNotEmpty();


        // 坏形态 ⑦：只留 CAS 调用、**不判影响行数**（谓词白写 = #6960 的病根之一）
        assertThat(problems(goodMapper,
                        serviceCorpus("execute", "batchMapper.markExecuting(batchId, tenantId);"), registered))
                .as("CAS 调用不判 `== 0` 必须判红（只看调用存在 = 谓词白写）").isNotEmpty();

        // 坏形态 ⑧：判定被包进**不可达条件**（`if (false && …)`）—— 锚还在，判定其实不生效
        assertThat(problems(goodMapper, serviceCorpus("execute",
                        "if (false && batchMapper.markExecuting(batchId, tenantId) == 0) { throw conflict(); }"),
                        registered))
                .as("把行数判定塞进不可达条件必须判红（判据的主张本体是判定生效，不是锚存在）").isNotEmpty();

        // 反向对照：只改注释 ⇒ 不红
        assertThat(problems(goodMapper,
                        "// 注释里提一句 batchMapper.updateById(batch)\n" + goodService, registered))
                .as("只加注释不得判红（否则守卫被自己的文案喂红）").isEmpty();
    }

    // ────────────────────────────────────────────── 判定本体（真源码与合成语料共用）

    /**
     * 状态写路径的**两条断言**（真源码与合成语料共用）：
     * <ol>
     *   <li><b>准入必须走 CAS 且必须看影响行数</b>：每一个 {@code <mapper>.mark*(} 调用后面
     *       <b>300 字符内</b>必须出现 {@code == 0)}（= 「受影响行数 0 ⇒ 拒绝」的判定）。
     *       只留调用不判 0 行 = 谓词白写（#6960 的病根之一）；把判定包进
     *       {@code if (false && …)} 这类不可达条件也在这里当场红。</li>
     *   <li><b>整条路径零 CAS ⇒ 红</b>：方法体里出现 {@code updateById(} 却**没有任何** {@code mark*(}
     *       收口 = 本单修前的形态（终态 / 计数的 {@code updateById} 是正常的：
     *       那些值要等逐条结果才知道，没法塞进一条 {@code markXxx}）。</li>
     * </ol>
     *
     * <p>⚠️ 纯文本形态判据（无 AST）⇒ 它证明「这几个字在方法体的窗口内」，**不**证明运行期语义
     * （行为面由各自的真库并发判据承担）。保守方向：宁可红在形态上。</p>
     */
    private static List<String> casProblems(String body, String pathName) {
        List<String> problems = new ArrayList<>();
        Matcher claim = MAPPER_CAS_CALL.matcher(body);
        while (claim.find()) {
            int windowEnd = Math.min(body.length(), claim.end() + ROW_COUNT_WINDOW);
            if (!ROW_COUNT_CHECK.matcher(body.substring(claim.end(), windowEnd)).find()) {
                problems.add("CAS 调用没判影响行数（" + pathName + " 的 " + claim.group(1)
                        + " 后 " + ROW_COUNT_WINDOW + " 字符内没有 `== 0)`）");
            }
        }
        if (SERVICE_UPDATE_BY_ID.matcher(body).find() && !MAPPER_CAS_CALL.matcher(body).find()) {
            problems.add("状态写路径一次 CAS 都没走（准入必须走条件更新）: " + pathName);
        }
        return problems;
    }

    /**
     * 一次判定：返回问题清单（空 = 合规）。真源码与合成语料走**同一套**判定本体。
     *
     * <p>{@code registered} 的键 = 写路径的方法名（可带 {@code <类>#} 前缀），值 = 该路径必须**逐字出现**
     * 的调用锚（如 {@code batchMapper.markExecuting(}）。「以 `markXxx` 收口」这条主张只有在
     * 锚真的在方法体里时才成立 —— 退回无谓词 {@code updateById} ⇒ 锚消失 ⇒ 当场红。</p>
     */
    private static List<String> problems(String mapperText, String serviceText,
                                         Map<String, String> registered) {
        List<String> problems = new ArrayList<>();
        for (MapperWrite w : mapperStatusWrites(mapperText)) {
            if (!TENANT_PARAM.matcher(w.sql()).find()
                    || !SOURCE_STATUS_PREDICATE.matcher(w.sql()).find()
                    || STATUS_PARAM_PREDICATE.matcher(w.sql()).find()
                    || CARRIES_DELETED_COLUMN != DELETED_PREDICATE.matcher(w.sql()).find()) {
                problems.add("mapper 状态写缺谓词: " + w.method());
            }
        }
        Map<String, MethodBody> candidates = new LinkedHashMap<>();
        for (MethodBody m : serviceStatusWriteCandidates(serviceText)) {
            candidates.put(m.name(), m);
        }
        Set<String> registeredNames = registered.keySet().stream()
                .map(AgentBatchStatusCasMetaGuardTest::bareMethod)
                .collect(Collectors.toSet());
        for (Map.Entry<String, MethodBody> e : candidates.entrySet()) {
            if (!registeredNames.contains(e.getKey())) {
                problems.add("service 未登记的状态写路径: " + e.getKey());
            }
            // 🔴 本守卫的**主张本体**：准入必须走 CAS，且**必须看影响行数**（见 casProblems）
            problems.addAll(casProblems(e.getValue().body(), e.getKey()));
        }
        for (Map.Entry<String, String> r : registered.entrySet()) {
            MethodBody body = candidates.get(bareMethod(r.getKey()));
            if (body == null) {
                problems.add("台账给不存在的写路径盖章: " + r.getKey());
            } else if (r.getValue() != null && !body.body().contains(r.getValue())) {
                problems.add("写路径未兑现：主张的 " + r.getKey() + " 收口锚不在方法体里（" + r.getValue() + "）");
            }
        }
        return problems;
    }

    /** 台账里的写路径形态是 {@code <类>#<方法>} ⇒ 与现取的方法名比较前先归一。 */
    private static String bareMethod(String name) {
        int hash = name.indexOf('#');
        return hash < 0 ? name : name.substring(hash + 1);
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
     * 方法签名（**逻辑行**上匹配）：`<4 空格缩进><返回类型…> <小写名>(<非空参数，可跨物理行>) {`。
     *
     * <p>⚠️ 本判据踩过三个坑，逐条写在这里（形态判据最怕的不是判红，是**静默失明**）：</p>
     * <ol>
     *   <li><b>不能靠「花括号深度」认方法</b>：源文件 javadoc 里大量出现内联 {@code {@code …}} 标签
     *       （如 {@code {@code recovered_meters/unit_cost/amount}}）—— 那是**花括号**，会让逐字符深度
     *       计数错位 ⇒ 候选集静默少方法（实测：`recover` 被整个吞掉，而结果列上看着像「通过」）。</li>
     *   <li><b>不能要求签名在一行内</b>：参数跨行（`public X recover(Long tenantId, Long remnantId,` +
     *       续行 `String orderItemId, String orderNo, String itemKey) {`）在仓里到处都是。</li>
     *   <li><b>必须排除控制结构</b>：`if (…) {` 与「方法 + 体」在行形态上同形，靠名字（小写开头）
     *       加关键字白名单排除。</li>
     * </ol>
     * <p>⇒ 先用 {@link #logicalLines} 把「括号未闭合的续行」并成逻辑行，再用签名正则认方法；
     * 方法体 = 该逻辑行起、到花括号归零为止（在**逻辑行**上计数，注释里的花括号不参与）。</p>
     */
    private static final Pattern METHOD_SIGNATURE = Pattern.compile(
            "^ {4}(?:[A-Za-z_$][\\w.$<>,\\[\\]\\s]*?\\s)?([a-z]\\w*)\\s*\\([^;{}]*\\)"
                    + "\\s*(?:throws\\s+[\\w.,\\s]+)?\\{\\s*$");

    /**
     * 把物理行并成**逻辑行**：括号未闭合时把下一行续上（换行折成空格），并**保留下标对齐**
     * （续行位置填空串）⇒ 后续方法体收集仍按「逻辑行」推进，编号不会错位。
     *
     * <p>签名跨行只发生在圆括号内，而注释 / 字符串里的圆括号已由调用方
     * （{@link #stripCommentsAndStrings}）抹平。</p>
     */
    private static List<String> logicalLines(String text) {
        List<String> out = new ArrayList<>();
        String pending = null;
        int balance = 0;
        for (String raw : stripCommentsAndStrings(text).replace("\r", "").split("\n", -1)) {
            if (pending == null) {
                pending = raw;
            } else {
                pending = pending + " " + raw.strip();
            }
            balance += raw.length() - raw.replace("(", "").length();
            balance -= raw.length() - raw.replace(")", "").length();
            if (balance > 0) {
                out.add("");
                continue;
            }
            balance = 0;
            out.add(pending);
            pending = null;
        }
        if (pending != null) {
            out.add(pending);
        }
        return out;
    }

    /**
     * 抹掉注释与字符串字面量（**保留行结构**：注释 / 字符串内的换行照数，内容换成等长空白）。
     *
     * <p>注释里的圆括号 / 花括号必须先抹掉，否则 {@link #logicalLines} 的括号平衡与签名匹配都会被
     * javadoc 影响（实测：{@code {@code …}} 标签里的花括号曾把 {@code RemnantService#recover}
     * 整个吞出候选集）。</p>
     */
    private static String stripCommentsAndStrings(String text) {
        StringBuilder out = new StringBuilder(text.length());
        int i = 0;
        int n = text.length();
        while (i < n) {
            char c = text.charAt(i);
            if (c == '/' && i + 1 < n && text.charAt(i + 1) == '/') {
                while (i < n && text.charAt(i) != '\n') {
                    out.append(' ');
                    i++;
                }
            } else if (c == '/' && i + 1 < n && text.charAt(i + 1) == '*') {
                out.append("  ");
                i += 2;
                while (i < n && !(text.charAt(i) == '*' && i + 1 < n && text.charAt(i + 1) == '/')) {
                    out.append(text.charAt(i) == '\n' ? '\n' : ' ');
                    i++;
                }
                if (i < n) {
                    out.append("  ");
                    i += 2;
                }
            } else if (c == '"') {
                out.append(' ');
                i++;
                while (i < n && text.charAt(i) != '"') {
                    if (text.charAt(i) == '\\' && i + 1 < n) {
                        out.append("  ");
                        i += 2;
                        continue;
                    }
                    out.append(text.charAt(i) == '\n' ? '\n' : ' ');
                    i++;
                }
                if (i < n) {
                    out.append(' ');
                    i++;
                }
            } else {
                out.append(c);
                i++;
            }
        }
        return out.toString();
    }

    /**
     * 现取：{@code service} 文本里「方法 + 其方法体」（逻辑行版；口径见 {@link #METHOD_SIGNATURE}）。
     */
    private static List<MethodBody> membersWithBody(String text) {
        List<String> lines = logicalLines(text);
        List<MethodBody> out = new ArrayList<>();
        int i = 0;
        while (i < lines.size()) {
            Matcher m = METHOD_SIGNATURE.matcher(lines.get(i));
            String name = m.matches() && !CONTROL_KEYWORDS.contains(m.group(1)) ? m.group(1) : null;
            if (name == null) {
                i++;
                continue;
            }
            StringBuilder body = new StringBuilder();
            int depth = 0;
            int j = i;
            while (j < lines.size()) {
                String line = lines.get(j);
                body.append(line).append('\n');
                depth += line.length() - line.replace("{", "").length();
                depth -= line.length() - line.replace("}", "").length();
                if (depth <= 0) {
                    break;
                }
                j++;
            }
            out.add(new MethodBody(name, body.toString()));
            i = j + 1;
        }
        return out;
    }

    /** 现取：service 里**出现状态列写**的方法（方法名 + 方法体）。 */
    private static List<MethodBody> serviceStatusWriteCandidates(String serviceText) {
        List<MethodBody> out = new ArrayList<>();
        for (MethodBody m : membersWithBody(serviceText)) {
            if (SERVICE_UPDATE_BY_ID.matcher(m.body()).find() || MAPPER_CAS_CALL.matcher(m.body()).find()) {
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
