// case_ids: MC-106

package com.migao.admin.service;

import com.fasterxml.jackson.core.JsonProcessingException;
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
 * 🧱 <b>类级元守卫（issue #6962 P5 首批）：三处「读-判-写无谓词」并发缺陷的写面必须落到 SQL 谓词（CAS），未登记即红</b>。
 *
 * <h2>为什么需要它（只修一处 = 没修 —— 铁律 8 / {@code migao-dev-flow} §23）</h2>
 * 实例判据（{@code ConcurrentQuotaAdoptDeleteCas6962RealDbTest}，**同批的兄弟包**）只保证
 * <b>那几条入口</b>在真库并发下拿得准。而 #6962 的真实教训是「<b>同一份状态迁移权上有多个写面，
 * 每个写面都是「先读判、再 {@code updateById}(WHERE 仅主键)」</b>」：
 * <ul>
 *   <li><b>P5-①</b> {@code AgentSessionService#assignSession}：先 {@code selectById} 判
 *       {@code status='waiting'}、再 {@code updateById(session)} ⇒ 同一 {@code sessionId} 并发分配
 *       <b>两个请求都成功</b>（后写者覆盖 {@code employee_id}）；同一个员工的额度是「各自读计数
 *       ⇒ 各自判未超额」⇒ {@code max_concurrent_sessions} 被突破。
 *       修后 = {@code markAssignedIfWaiting}（CAS）+ {@code lockEmployeeForQuota}({@code FOR UPDATE})
 *       + {@code countActiveSessions}（锁内现取计数）。</li>
 *   <li><b>P5-②</b> {@code KnowledgeCandidateService#adoptInternal} / {@code #reject}：先 {@code getOwned}
 *       读出 {@code pending}、再整实体 {@code updateById} ⇒ 并发双采纳<b>各插一张卡</b>；
 *       「采纳 × 拒绝」两个都成功、终态由后写者决定。修后 = {@code markReviewedIfPending}（CAS）
 *       并<b>先抢到卡位再插卡</b>。</li>
 *   <li><b>P5-③</b> {@code ProductionRoutingCommandService#deleteRouting} / {@code #deleteRouteRule}：
 *       落库语句只有 {@code .eq(id)} ⇒ ① 缺 tenant 限定（跨租户误删）② 无 {@code deleted = 0}
 *       且不判影响行数（「0 行当成功」）。修后 = {@code markDeletedByIdAndTenant}（谓词
 *       {@code id + tenant_id + deleted = 0}）+ 影响行数为 0 ⇒ 409。</li>
 * </ul>
 * 下一个人在<b>同族文件</b>新加一条无谓词的状态写路径、或给 mapper 加一条无谓词 SQL，
 * 没有任何东西会红 ⇒ 本守卫把「写面清单 + 谓词完整性 + 登记兑现」钉成机械判据。
 *
 * <h2>射程（五条 mapper + 三条 service，横跨三个族）</h2>
 * {@code AgentSessionMapper} / {@code KnowledgeCandidateMapper} / {@code ProductionRouteTemplateMapper} /
 * {@code ProductionRouteRuleMapper} + {@code AgentSessionService} / {@code KnowledgeCandidateService} /
 * {@code ProductionRoutingCommandService}。
 *
 * <p>⚠️ <b>本批的实证陷阱（写进判据，不许再犯）</b>：模板上写惯了 {@code deleted = 0}，但
 * {@code knowledge_candidates} 表<b>根本没有 {@code deleted} 列</b>（{@code db/init/schema.sql} 自证，
 * 列止于 {@code reviewed_by}）⇒ 对它是「<b>{@code deleted} 谓词必须缺席</b>」—— 有人「顺手补上」
 * {@code deleted = 0} 就是列不存在、SQL 当场报错。本守卫对这一族单独设「禁令」而不是复用模板。</p>
 *
 * <h2>判据（每条都会红 —— 红证逐条见 {@code printsTheExactJudgementMessage…} 与
 * {@code guardHasDiscriminatingPower}）</h2>
 * <ol>
 *   <li><b>扫描器非空跑自证</b>：现取写守卫列的手写 {@code @Update} SQL 必须含三条 CAS 方法名；
 *       现取三条 service 的写路径必须含 {@code assignSession} / {@code adoptInternal} / {@code reject} /
 *       {@code deleteRouting} / {@code deleteRouteRule}。空集 = <b>判据失明</b>，不是「通过」。</li>
 *   <li><b>mapper 谓词完整性</b>：{@code agent_sessions} 的状态写 SQL 要 tenant 参数 + {@code status}
 *       谓词 + {@code deleted = 0}；{@code knowledge_candidates} 要 tenant 参数 + {@code status} 谓词
 *       且 {@code deleted} 谓词<b>必须缺席</b>；两条 route 表的 {@code deleted} 写 SQL 要
 *       {@code id} + tenant 参数 + {@code deleted = 0}（SET 侧写 {@code deleted} 是允许的）。</li>
 *   <li><b>无谓词写即红（判据本体）</b>：守卫方法体里不得出现守卫 mapper 的 {@code updateById(}。
 *       <b>实证过的隐蔽形态</b>：锚串留着（{@code if (false && …markAssignedIfWaiting(…) }）而真正落库
 *       换成 {@code updateById} ⇒ 仍判红并具名。两条 route 的软删走 {@code LambdaUpdateWrapper}
 *       <b>方法体</b>（不是 {@code @Update} 注解）⇒ 单独一条判据。</li>
 *   <li><b>未登记即红 + 台账不许给不存在的对象盖章</b>：现取的每个写路径必须逐条在册；台账里多出来的
 *       条目（改名 / 删方法）也红。</li>
 *   <li><b>登记未被兑现即红</b>：每条 {@code evidence} = {@code <仓库相对全路径>::<可检索文本>}，
 *       左侧文件必须存在、右侧必须<b>逐字出现</b>（摘掉 CAS 调用 / 改名 ⇒ 红）。</li>
 *   <li><b>插卡次序</b>：{@code adoptInternal} 里 {@code knowledgeCardMapper.insert(} 必须出现在
 *       {@code markReviewedIfPending(} 之后、且在其 {@code == 0} 冲突回滚之后（文字序判定）。次序反了 ⇒ 红。</li>
 *   <li><b>豁免台账只许缩短 + 不许空转</b>：{@code unverified} 必须是冻结基线 {@code unverified_baseline}
 *       的子集（新增豁免 ⇒ 红）；条数<b>现取</b>（读在断言消息上）；{@code entries} /
 *       {@code service_write_paths} 为空 ⇒ 红（fail-closed）。</li>
 *   <li><b>判别力自证</b>：用<b>合成语料</b>跑与真实源码<b>同一套</b>判定本体 —— 八种坏形态各自判红
 *       （含「锚留而落库无谓词」「台账多出一条不存在的登记」「给本无该列的表补 {@code deleted = 0}」），
 *       合规语料判绿，<b>只加注释不红</b>。没有这条，「判据恒绿」与「判据有效」在结果列上长得一样。</li>
 * </ol>
 *
 * <p>⚠️ 本判据读<b>源码文本</b>（不做 AST）—— 本仓既有形态（MC-100
 * {@code InboundOrderStatusCasMetaGuardTest} / MC-104 {@code ProcessingOrderStatusCasMetaGuardTest}
 * 同款）。代价：它只能证明「这几个字在方法体里」，换措辞可绕过；<b>行为面由真库并发判据承担</b>：
 * {@code ConcurrentQuotaAdoptDeleteCas6962RealDbTest}（#6962，**兄弟包的文件，本包不创建也不运行**）——
 * 两者缺一不可（{@code migao-dev-flow} §28.2：判据本体绿 ≠ 接线在）。</p>
 *
 * <p>⛔ <b>与 MC-100（入库单）/ MC-104（加工单状态）/ PG-075（工序删除权）互不重叠</b>：各守自己的族，
 * 既不互为副本、也互不重判（判据与台账都是各自独立的）。</p>
 *
 * <p><b>未固化项（如实登记，不粉饰）</b>：见台账 {@code coverage_boundary} ——
 * ① 形态判据换措辞可绕过（真实防线仍是实例判据）；② 射程只到上述八条文件；
 * ③ 判不了「拿 {@code updateById} 改**非守卫列**」（那不是本判据的对象）；
 * ④ 本守卫<b>不</b>跑被它引用的那条真库判据（否则「未登记即红」会退化成全量套件再跑一遍）；
 * ⑤ 本守卫<b>不改</b>任何门禁的通过条件、不新增豁免。</p>
 */
@DisplayName("🧱 类级元守卫（#6962 P5 首批）：会话分配/候选处置/路线软删写面必须落到 SQL 谓词（未登记即红 + 豁免只许缩短）")
class ConcurrencyCasBatch6962MetaGuardTest {

    /** 模块根（Surefire 的工作目录 = {@code backend/admin-api}）；台账里的引用一律是**仓库相对全路径**。 */
    private static final String MODULE = "backend/admin-api";
    private static final String MAIN = MODULE + "/src/main/java/com/migao/admin";
    private static final String SCHEMA = MODULE + "/src/main/resources/db/init/schema.sql";
    private static final String LEDGER_PATH = MODULE + "/src/test/resources/concurrency-cas-batch-6962-ledger.json";

    // ── 射程（文件一律写全路径；台账 / 读数 / 红证三处共用同一批常量，免得两处各写一份）

    private static final String AGENT_SESSION_MAPPER = MAIN + "/mapper/AgentSessionMapper.java";
    private static final String KNOWLEDGE_CANDIDATE_MAPPER = MAIN + "/mapper/KnowledgeCandidateMapper.java";
    private static final String ROUTE_TEMPLATE_MAPPER = MAIN + "/mapper/ProductionRouteTemplateMapper.java";
    private static final String ROUTE_RULE_MAPPER = MAIN + "/mapper/ProductionRouteRuleMapper.java";
    private static final String AGENT_SESSION_SERVICE = MAIN + "/service/AgentSessionService.java";
    private static final String KNOWLEDGE_CANDIDATE_SERVICE = MAIN + "/service/KnowledgeCandidateService.java";
    private static final String ROUTING_COMMAND_SERVICE = MAIN + "/service/ProductionRoutingCommandService.java";

    private static final List<String> SCANNED_FILES = List.of(
            AGENT_SESSION_MAPPER, KNOWLEDGE_CANDIDATE_MAPPER, ROUTE_TEMPLATE_MAPPER, ROUTE_RULE_MAPPER,
            AGENT_SESSION_SERVICE, KNOWLEDGE_CANDIDATE_SERVICE, ROUTING_COMMAND_SERVICE, SCHEMA, LEDGER_PATH);

    // ── 形态标记

    /** 手写 SQL 注解的**取块**（到配对的 `)` 为止；SQL 自带括号 ⇒ 先取块再剥 Java 语法）。 */
    private static final Pattern SQL_ANNOTATION =
            Pattern.compile("@(?:Update|Delete|Insert)\\s*\\(((?:[^()]|\\([^()]*\\))*)\\)");
    /** 块内真正的 SQL 起始（跳过任何 MyBatis `@Update` 的 `<script>` 前缀）。 */
    private static final Pattern SQL_START =
            Pattern.compile("(?i)\\b(UPDATE|INSERT\\s+INTO|DELETE\\s+FROM)\\b");
    /** 谓词 / 参数要求（issue #6962 的口径）。 */
    private static final Pattern TENANT_PARAM =
            Pattern.compile("#\\{\\s*tenantI?d\\s*\\}", Pattern.CASE_INSENSITIVE);
    /**
     * 查询构造器写面上的 **id 条件**。形态可以是**方法引用**（`LambdaUpdateWrapper.eq(X::getId, id)`
     * —— 本批 route mapper 的真实形态）也可以是调用（`X.getId()`）。⚠️ 只认 `getId(` 会把真实形态
     * 判成「缺 id 条件」= 恒红噪声（本判据实测踩过：`::getId,` 不含 `getId(`）。
     */
    private static final Pattern ID_CONDITION =
            Pattern.compile("getId\\s*(::)?\\s*[,(]", Pattern.CASE_INSENSITIVE);
    /** 查询构造器写面上的 tenant 条件（同上：`X::getTenantId, y` 与 `X.getTenantId(y)` 都算）。 */
    private static final Pattern TENANT_CONDITION =
            Pattern.compile("getTenantId\\s*(::)?\\s*[,(]", Pattern.CASE_INSENSITIVE);
    /** 查询构造器写面上的「未软删」条件：真实形态是**方法引用** `X::getDeleted, 0`。 */
    private static final Pattern DELETED_ZERO_WRAPPER =
            Pattern.compile("getDeleted\\s*,\\s*0", Pattern.CASE_INSENSITIVE);
    /** 状态列谓词（参数化 `status = #{status}` / 字面量 `status = 'pending'` / `status IN (…)`）。 */
    private static final Pattern STATUS_PREDICATE =
            Pattern.compile("status\\s*(=\\s*(#\\{|')|IN\\s*\\()", Pattern.CASE_INSENSITIVE);
    /** `deleted` 的 SET 侧赋值（值本身是**写什么**，与「必须有 `deleted = 0` 谓词」无关）。 */
    private static final Pattern DELETED_ASSIGN = Pattern.compile("(?:^|,)\\s*deleted\\s*=", Pattern.CASE_INSENSITIVE);
    /** `deleted = <值>`（含比较）；用于「禁令：谓词里不得出现 deleted」的取证。 */
    private static final Pattern DELETED_ANY = Pattern.compile("deleted\\s*=", Pattern.CASE_INSENSITIVE);
    /** `deleted = 0`（谓词）。 */
    private static final Pattern DELETED_ZERO = Pattern.compile("deleted\\s*=\\s*0", Pattern.CASE_INSENSITIVE);
    /**
     * **无谓词写**的形态（本单病根）：整实体回写 / 只按 id 的条件更新。组 1 = mapper 变量名；
     * 组 2 = 命中的动词（{@code updateById} / {@code update(null,} / {@code update(}），非空即「无谓词」。
     */
    private static final Pattern UNCONDITIONAL_WRITE = Pattern.compile(
            "(\\w*Mapper)\\.(updateById|update\\s*\\(\\s*null\\s*,|update)\\s*\\(",
            Pattern.CASE_INSENSITIVE);
    /** 块内「方法头 + 方法名」定位（`int markXxx(`）。 */
    private static final Pattern NAMED_MEMBER = Pattern.compile("([A-Za-z_$][\\w$]*)\\s*\\(");
    /** Java 控制结构关键字：`if (…) {` 在行形态上与「方法 + 体」同形，靠名字排除。 */
    private static final Set<String> CONTROL_KEYWORDS = Set.of(
            "if", "for", "while", "switch", "catch", "synchronized", "try", "do", "else", "return", "new");

    private static final ObjectMapper JSON = new ObjectMapper();

    // ────────────────────────────────────────────── 守卫列表（写死「该表该列该谓词」，判据本体只解读它）

    /** 两条 route 表：软删落库在 **mapper 的 default 方法**里 ⇒ 不走「service 侧 mapper 别名」那条取块。 */    private static final Set<String> ROUTE_MAPPER_FILES = Set.of(ROUTE_TEMPLATE_MAPPER, ROUTE_RULE_MAPPER);

    /** 一条**列级谓词要求**：{@code mustBePresent=true} ⇒ 必须出现；{@code false} ⇒ 出现即红（禁令）。 */
    private record ColumnPredicate(String label, boolean mustBePresent, String token, Pattern marker) {
    }

    private static final String WHERE = "where";
    private static final String ALL = "all";

    /**
     * 一族：mapper 文件 + 表名 + 守卫列 + 手写 SQL 的谓词要求 + **条件更新方法体**的要求
     * （{@code guardedMethods} = 必须现取到的条件更新方法名；{@code methodPredicates} = 这些方法体必须带的条件）。
     */
    private record MapperGroup(String file, String table, Pattern guardedSetColumn,
                               List<ColumnPredicate> updatePredicates, Set<String> guardedMethods,
                               List<ColumnPredicate> methodPredicates) {
    }

    private static ColumnPredicate need(String label, String token, Pattern marker) {
        return new ColumnPredicate(label, true, token, marker);
    }

    private static ColumnPredicate banInWhere(String label) {
        return new ColumnPredicate(label, false, WHERE, DELETED_ANY);
    }

    private static final List<MapperGroup> GROUPS = List.of(
            // P5-① 会话分配：`agent_sessions.status` 的写必须 tenant + status 谓词 + deleted = 0
            new MapperGroup(AGENT_SESSION_MAPPER, "agent_sessions", Pattern.compile("status\\s*=", Pattern.CASE_INSENSITIVE),
                    List.of(need("tenant_id 参数", ALL, TENANT_PARAM),
                            need("WHERE 侧 status 谓词", WHERE, STATUS_PREDICATE),
                            need("deleted = 0 谓词", WHERE, DELETED_ZERO)),
                    Set.of(), List.of()),
            // P5-② 候选处置：`knowledge_candidates.status` 的写**必须没有** deleted 谓词（本表无该列）
            new MapperGroup(KNOWLEDGE_CANDIDATE_MAPPER, "knowledge_candidates",
                    Pattern.compile("status\\s*=", Pattern.CASE_INSENSITIVE),
                    List.of(need("tenant_id 参数", ALL, TENANT_PARAM),
                            need("WHERE 侧 status 谓词", WHERE, STATUS_PREDICATE),
                            banInWhere("本表**没有** deleted 列 ⇒ 谓词里不得出现 deleted（写了就是列不存在）")),
                    Set.of(), List.of()),
            // P5-③ 路线软删：SET 侧写 deleted ⇒ WHERE 必须 tenant + deleted = 0（软删落库在 mapper 的 default 方法里）
            new MapperGroup(ROUTE_TEMPLATE_MAPPER, "production_route_templates",
                    Pattern.compile("deleted\\s*=", Pattern.CASE_INSENSITIVE),
                    List.of(need("tenant_id 参数", ALL, TENANT_PARAM),
                            need("WHERE 侧 deleted = 0 谓词", WHERE, DELETED_ZERO)),
                    Set.of("markDeletedByIdAndTenant"),
                    List.of(need("id 条件（`::getId`）", ALL, ID_CONDITION),
                            need("tenant 条件（`::getTenantId`）", ALL, TENANT_CONDITION),
                            need("deleted = 0 条件（`::getDeleted, 0`）", ALL, DELETED_ZERO_WRAPPER))),
            // P5-③ 条件工序规则：同口径
            new MapperGroup(ROUTE_RULE_MAPPER, "production_route_rules",
                    Pattern.compile("deleted\\s*=", Pattern.CASE_INSENSITIVE),
                    List.of(need("tenant_id 参数", ALL, TENANT_PARAM),
                            need("WHERE 侧 deleted = 0 谓词", WHERE, DELETED_ZERO)),
                    Set.of("markDeletedByIdAndTenant"),
                    List.of(need("id 条件（`::getId`）", ALL, ID_CONDITION),
                            need("tenant 条件（`::getTenantId`）", ALL, TENANT_CONDITION),
                            need("deleted = 0 条件（`::getDeleted, 0`）", ALL, DELETED_ZERO_WRAPPER))));

    /**
     * 当前写面必须能现取到这些方法（少一个 = 形态改名 / 判据失明，不是「通过」）。
     *
     * <p>⚠️ **登记与豁免的唯一真值源 = 台账**（不是本文件里的常量）：这样「本批未修的写面」
     * （{@code AgentSessionService#sendMessage} / {@code #endSession} 仍是谓词缺失的
     * {@code updateById}，见台账里 <b>本批未修</b> 两条）可以由台账**具名登记**，而不是靠在判据里
     * 写死一张豁免名单 —— 而「具名登记」这件事本身就被本判据逐条核对（锚必须逐字兑现）。</p>
     */
    private static final Set<String> REQUIRED_SERVICE_METHODS =
            Set.of("assignSession", "adoptInternal", "reject", "deleteRouting", "deleteRouteRule");

    // ────────────────────────────────────────────── 判据 1~4：真语料

    @Test
    @DisplayName("扫描器非空跑自证：现取的 mapper CAS 方法与三条 service 写路径必须含核心对象")
    void scannersAreNotBlind() throws IOException {
        Corpus real = realCorpus();
        List<String> sqlWrites = new ArrayList<>();
        List<String> guardedBodies = new ArrayList<>();
        List<String> missing = new ArrayList<>();
        for (MapperGroup g : GROUPS) {
            sqlWrites.addAll(sqlCandidates(real.text(g.file()), g).stream().map(SqlCandidate::method).toList());
            guardedBodies.addAll(methodCandidates(real.text(g.file()), g, missing).stream()
                    .map(MethodCandidate::method).toList());
        }
        List<String> servicePaths = serviceWritePaths(real);

        System.out.println("[READING MC-106 扫描器] 手写 SQL 写面=" + sqlWrites
                + " 条件更新方法体=" + guardedBodies + " 取不到=" + missing + " service 写路径=" + servicePaths);
        assertThat(missing).as("守卫的条件更新方法体必须被现取到（取不到 = 形态改名 / 判据失明，不是「通过」）")
                .isEmpty();
        assertThat(sqlWrites)
                .as("扫描器必须现取到写守卫列的手写 SQL（返回空集 = 判据失明，不是通过）")
                .contains("markAssignedIfWaiting", "markReviewedIfPending");
        assertThat(guardedBodies)
                .as("扫描器必须现取到两条 route mapper 的**条件更新方法体**（软删走 LambdaUpdateWrapper，不是 @Update）")
                .contains("markDeletedByIdAndTenant");
        assertThat(servicePaths)
                .as("扫描器必须现取到三条 service 的写路径（少 = 判据失明 / 形态改名，不是通过）")
                .containsAll(REQUIRED_SERVICE_METHODS);
    }

    @Test
    @DisplayName("mapper 谓词完整性：手写 SQL 谓词齐备 + 本无 deleted 列的表不得出现 deleted 谓词 + 构造器写面谓词齐备")
    void everyMapperWriteCarriesTheRequiredPredicate() throws IOException {
        Corpus real = realCorpus();
        List<String> offenders = new ArrayList<>();
        for (MapperGroup g : GROUPS) {
            offenders.addAll(sqlProblems(real.text(g.file()), g, g.file()));
            offenders.addAll(methodProblems(real.text(g.file()), g, g.file()));
        }
        System.out.println("[READING MC-106 谓词] 违规=" + offenders);
        assertThat(offenders).as("写面必须把判断与写入压进同一条语句 / 同一个条件更新（缺谓词 = #6962 的病根）")
                .isEmpty();
    }

    @Test
    @DisplayName("无谓词写即红：主张 CAS 收口的写路径里不得出现守卫 mapper 的 updateById（含「锚留着、落库换掉」）")
    void noGuardedWritePathUsesUnconditionalUpdateById() throws IOException {
        Corpus real = realCorpus();
        List<String> offenders = new ArrayList<>();
        List<String> declaredUnwired = new ArrayList<>();
        List<String> cas = casAnchors();
        for (PathBinding p : ledgerBindings(real)) {
            String file = serviceFileOf(real, p);
            String body = file.isEmpty() ? null : methodBody(real.text(file), p.method());
            if (body == null) {
                offenders.add(p.label() + "（台账登记的写路径在源码里找不到）");
                continue;
            }
            boolean unguarded = writeProblems(file, new MethodBody(p.method(), body)).stream()
                    .anyMatch(WriteProblem::unconditional);
            if (!unguarded) {
                continue;
            }
            if (cas.stream().anyMatch(a -> p.anchor().contains(a))) {
                offenders.add(p.label() + "（主张 CAS 收口，方法体里却是无谓词 " + p.anchor() + "）");
            } else {
                // 台账**具名登记为本批未修**（锚逐字就是那句无谓词写）⇒ 绿但可见，不算违规
                declaredUnwired.add(p.label() + "（本批未修，台账已具名登记）");
            }
        }
        System.out.println("[READING MC-106 无谓词写] 现取写路径=" + serviceWritePaths(real)
                + " 主张 CAS 却无谓词=" + offenders + " 台账登记未修=" + declaredUnwired);
        assertThat(offenders)
                .as("守卫状态写必须带谓词（#6962 的病根就是这些方法用了无谓词 updateById）")
                .isEmpty();
    }

    @Test
    @DisplayName("插卡次序：adoptInternal 里 knowledgeCardMapper.insert( 必须晚于 markReviewedIfPending( 与其 == 0 冲突回滚")
    void cardInsertHappensAfterTheCasWins() throws IOException {
        String body = methodBody(realCorpus().text(KNOWLEDGE_CANDIDATE_SERVICE), "adoptInternal");
        assertThat(body).as("扫描器必须现取到 adoptInternal 的方法体（取不到 = 判据失明，不是通过）").isNotNull();
        System.out.println("[READING MC-106 次序] adoptInternal 撞上 CAS 的次序判定="
                + orderingProblems("KnowledgeCandidateService#adoptInternal", body, KNOWLEDGE_CANDIDATE_SERVICE));
        assertThat(orderingProblems("KnowledgeCandidateService#adoptInternal", body, KNOWLEDGE_CANDIDATE_SERVICE))
                .as("并发双采纳「各插一张卡」的根治 = **先抢到卡位再插卡**：insert 必须晚于 CAS 与它的 == 0 判定")
                .isEmpty();
    }

    @Test
    @DisplayName("未登记即红 + 台账不许给不存在的对象盖章 + 登记未被兑现即红 + 豁免只许缩短 + 不许空转")
    void serviceWritePathsAreRegisteredAndLedgerIsFaithful() throws IOException {
        Corpus real = realCorpus();
        List<String> servicePaths = serviceWritePaths(real);
        List<String> problems = registrationProblems(real);

        int unverified = real.ledger().get("unverified").size();
        int baseline = real.ledger().get("unverified_baseline").asInt();
        int entries = real.ledger().get("entries").size();
        int writePaths = real.ledger().get("service_write_paths").size();

        System.out.println("[READING MC-106 台账] 现取写路径=" + servicePaths
                + " mapper 条目=" + entries + " service 写路径条目=" + writePaths
                + " 豁免=" + unverified + "(基线 " + baseline + ")");
        assertThat(problems).as("写路径必须逐条登记且登记的锚必须逐字兑现（未登记 = 「下一个 #6962」）").isEmpty();
        assertThat(entries).as("台账不许空转：mapper 条目为 0 ⇒ 红（「空」不等于「全部合规」）；现取 count=%d", entries)
                .isPositive();
        assertThat(writePaths).as("台账不许空转：service 写路径为 0 ⇒ 红；现取 count=%d", writePaths).isPositive();
        assertThat(unverified)
                .as("豁免台账只许缩短（新增豁免必须走 issue + 重启条件）；现取 unverified=%d 基线=%d", unverified, baseline)
                .isLessThanOrEqualTo(baseline);
    }

    @Test
    @DisplayName("schema 自证：knowledge_candidates 真没有 deleted 列（本批的陷阱），另两张被守卫的软删表真有")
    void schemaFactsArePinned() throws IOException {
        String schema = realCorpus().text(SCHEMA);
        Set<String> candidateCols = columnsOf(schema, "knowledge_candidates");
        Set<String> sessionCols = columnsOf(schema, "agent_sessions");
        Set<String> templateCols = columnsOf(schema, "production_route_templates");
        Set<String> ruleCols = columnsOf(schema, "production_route_rules");
        Set<String> employeeCols = columnsOf(schema, "agent_employees");

        System.out.println("[READING MC-106 schema] knowledge_candidates=" + candidateCols
                + " agent_sessions=" + sessionCols + " agent_employees=" + employeeCols);
        assertThat(candidateCols).as("必须能现取到 knowledge_candidates 的列（空 = 判据失明）").isNotEmpty();
        assertThat(sessionCols).as("必须能现取到 agent_sessions 的列（空 = 判据失明）").isNotEmpty();
        assertThat(candidateCols).as("本批判据 2 的前提：knowledge_candidates **没有** deleted 列（写了就是列不存在）")
                .doesNotContain("deleted");
        assertThat(candidateCols).as("本表用 status 承担软删语义 ⇒ 必须有 status 列").contains("status");
        assertThat(sessionCols).as("agent_sessions 的状态写要求 deleted = 0 ⇒ 该列必须真的存在").contains("deleted", "status");
        assertThat(templateCols).as("路线模板软删要求 deleted = 0 ⇒ 该列必须真的存在").contains("deleted");
        assertThat(ruleCols).as("条件工序规则软删要求 deleted = 0 ⇒ 该列必须真的存在").contains("deleted");
        assertThat(employeeCols).as("额度上限列必须存在（FOR UPDATE + 现取计数的口径依赖它）").contains("max_concurrent_sessions");
    }

    // ────────────────────────────────────────────── 判据 8：判别力自证（合成语料，内存里跑）

    @Test
    @DisplayName("判别力自证（合成语料）：八种坏形态各自判红、合规语料判绿、只改注释不红")
    void guardHasDiscriminatingPower() throws JsonProcessingException {
        Func<Map<String, String>, List<String>> judge = files -> corpusProblems(
                new Corpus(files, JSON.readTree(files.getOrDefault(LEDGER_PATH, syntheticLedger()))));

        Map<String, String> good = new LinkedHashMap<>(syntheticCorpus());
        assertThat(judge.apply(good)).as("合规语料判绿（否则本守卫是恒红噪声）").isEmpty();

        // ① 无谓词状态写（= #6962 的病根本体）：把 WHERE 侧的条件整段抽掉，只留主键
        assertThat(judge.apply(mutate(good, AGENT_SESSION_MAPPER,
                "WHERE id = #{id} AND tenant_id = #{tenantId} AND status = 'waiting' AND deleted = 0",
                "WHERE id = #{id}")))
                .as("无谓词状态写必须判红").isNotEmpty();

        // ② 缺 tenant 谓词（跨租户可写）
        assertThat(judge.apply(mutate(mutate(good, AGENT_SESSION_MAPPER,
                "WHERE id = #{id} AND tenant_id = #{tenantId} AND status = 'waiting' AND deleted = 0",
                "WHERE id = #{id} AND status = 'waiting' AND deleted = 0"),
                AGENT_SESSION_MAPPER, ", @Param(\"tenantId\") Long tenantId", "")))
                .as("缺 tenant 谓词必须判红（跨租户可写）").isNotEmpty();

        // ②b 谓词文本还在、但**绑定没了**（`#{tenantId}` 没有任何 `@Param("tenantId")` 兑现它）
        assertThat(judge.apply(mutate(good, AGENT_SESSION_MAPPER,
                ", @Param(\"tenantId\") Long tenantId", "")))
                .as("谓词参数没有 @Param 绑定必须判红（SQL 里的 #{tenantId} 会解析不到 ⇒ 运行期报错）").isNotEmpty();

        // ③ 缺 WHERE 侧 status 谓词（只有 SET 侧赋值 = 无条件迁移）
        assertThat(judge.apply(mutate(good, KNOWLEDGE_CANDIDATE_MAPPER,
                "AND status = 'pending'</script>", "</script>")))
                .as("缺 WHERE 侧状态谓词必须判红").isNotEmpty();

        // ④ 给**本无该列**的表补 deleted = 0（本批的实证陷阱：模板写惯了，这里写了就是列不存在）
        assertThat(judge.apply(mutate(good, KNOWLEDGE_CANDIDATE_MAPPER,
                "AND status = 'pending'</script>", "AND status = 'pending' AND deleted = 0</script>")))
                .as("knowledge_candidates 上出现 deleted 谓词必须判红（该表没有这一列）").isNotEmpty();

        // ⑤ route 表条件更新丢掉 deleted = 0（已软删的行也会被再删一次）
        assertThat(judge.apply(mutate(good, ROUTE_TEMPLATE_MAPPER,
                ".eq(ProductionRouteTemplate::getDeleted, 0)\n", "")))
                .as("route 表条件更新缺 deleted = 0 必须判红").isNotEmpty();

        // ⑤b route 表条件更新丢掉 tenant 限定（跨租户误删）
        assertThat(judge.apply(mutate(good, ROUTE_RULE_MAPPER,
                ".eq(ProductionRouteRule::getTenantId, tenantId)\n", "")))
                .as("route 表条件更新缺 tenant 限定必须判红").isNotEmpty();

        // ⑥ 无谓词整实体回写（route 表：0 行当成功 + 跨租户 + 覆盖整行）
        assertThat(judge.apply(mutate(good, ROUTING_COMMAND_SERVICE,
                "        if (productionRouteTemplateMapper.markDeletedByIdAndTenant(id, tenantId) == 0) {",
                "        productionRouteTemplateMapper.updateById(template);\n"
                        + "        if (productionRouteTemplateMapper.markDeletedByIdAndTenant(id, tenantId) == 0) {")))
                .as("route 软删退回无谓词 updateById 必须判红").isNotEmpty();

        // ⑦ 未登记的新写路径（= 「只修一处」的复发形态）
        assertThat(judge.apply(mutate(good, AGENT_SESSION_SERVICE,
                "    public void assignSession(String id) {",
                "    public void forceAssign(String id) {\n"
                        + "        agentSessionMapper.updateById(session);\n    }\n\n"
                        + "    public void assignSession(String id) {")))
                .as("未登记的状态写路径必须判红（这就是「只修一处」的复发形态）").isNotEmpty();

        // ⑦b 最隐蔽的一种 —— **锚串留着**（`if (false && …markAssignedIfWaiting(…)`），
        //     真正落库的换成无谓词 updateById ⇒ 必须仍然判红（只判锚会被它骗过去）
        assertThat(judge.apply(mutate(good, AGENT_SESSION_SERVICE,
                "        agentSessionMapper.markAssignedIfWaiting(id, tenantId);",
                "        if (false && agentSessionMapper.markAssignedIfWaiting(id, tenantId) == 0) { }\n"
                        + "        agentSessionMapper.updateById(session);")))
                .as("锚还在但真正落库的是无谓词 updateById ⇒ 必须判红（判据的主张本体是 CAS，不是锚）")
                .isNotEmpty();

        // ⑧ 台账未兑现（CAS 调用被摘掉 / 改名）
        assertThat(judge.apply(mutate(good, KNOWLEDGE_CANDIDATE_SERVICE,
                "knowledgeCandidateMapper.markReviewedIfPending(", "knowledgeCandidateMapper.someOtherWrite(")))
                .as("台账锚被摘掉必须判红").isNotEmpty();

        // ⑧b 台账给不存在的写路径盖章（现取集合里没有它）
        assertThat(judge.apply(mutate(good, LEDGER_PATH,
                "\"method\": \"AgentSessionService#assignSession\"",
                "\"method\": \"AgentSessionService#ghostAssign\"")))
                .as("台账不许给不存在的写路径盖章（改名 / 删除 ⇒ 红）").isNotEmpty();

        // ⑨ 插卡次序反转（先插卡、后抢卡位 = 并发双采纳各插一张）
        assertThat(judge.apply(swapInsertBeforeCas(good)))
                .as("insert 早于 CAS 必须判红（「先抢到卡位再插卡」是 #6962 P5-② 的主张本体）").isNotEmpty();

        // ⑩ 豁免台账新增一条（只在合成语料里做，绝不改真台账）
        assertThat(judge.apply(mutate(good, LEDGER_PATH,
                "\"unverified\": []", "\"unverified\": [\"someone-new\"]")))
                .as("新增豁免必须判红（豁免台账只许缩短）").isNotEmpty();

        // ⑪ 台账空转（条目清零）
        assertThat(judge.apply(mutate(good, LEDGER_PATH, "\"entries\": [", "\"entries\": [ ].subList(0,0) == null ? [ : [")))
                .as("台账条目空转必须判红（fail-closed：「空」不等于「全部合规」）").isNotEmpty();

        // 反向对照：只加注释 ⇒ 不红
        assertThat(judge.apply(mutate(good, AGENT_SESSION_SERVICE,
                "    public void assignSession(String id) {",
                "    // 注释里提一句 agentSessionMapper.updateById(session)\n"
                        + "    public void assignSession(String id) {")))
                .as("只加注释不得判红（否则守卫被自己的文案喂红）").isEmpty();

        // 🔴 扫描器鲁棒性自证：**跨行签名**（收尾 `) {` 在续行上）—— 只认「签名行含 `) {`」会把整个方法跳过
        assertThat(judge.apply(mutate(good, AGENT_SESSION_SERVICE,
                "    public void assignSession(String id) {",
                "    public void assignSession(String id,\n                               Long tenantId) {")))
                .as("跨行签名必须仍被扫到（否则整个方法被静默跳过 ⇒ 后面的写路径全部漏判）").isEmpty();
        assertThat(judge.apply(mutate(mutate(good, AGENT_SESSION_SERVICE,
                "    public void assignSession(String id) {",
                "    public void assignSession(String id,\n                               Long tenantId) {"),
                AGENT_SESSION_SERVICE, "        agentSessionMapper.markAssignedIfWaiting(id, tenantId);",
                "        agentSessionMapper.updateById(session);")))
                .as("跨行签名的方法里落库换成无谓词 updateById ⇒ 必须判红（证明它真的被扫到了）").isNotEmpty();

        // 🔴 javadoc 里的**孤立 `{`** 不得让花括号深度错位（真实文件里就有被截断的代码片段）
        assertThat(judge.apply(mutate(good, AGENT_SESSION_SERVICE,
                "    public void assignSession(String id) {",
                "    /** 例：{@code route = [op for op in route} 半个花括号 */\n"
                        + "    public void assignSession(String id) {")))
                .as("注释里的孤立 `{` 不得让深度错位（否则深度下沉、后续方法全部扫不到）").isEmpty();
    }

    // ────────────────────────────────────────────── 判据 3 的红证报告：把真语料逐条变异，逐条打印判定消息

    /**
     * <b>红证报告</b>（断言版）：把**真语料**在内存里逐条变异，跑同一套判定本体 —— 每条变异都必须判红，
     * 且把判定消息<b>逐字打印</b>。为什么要有它：AssertJ 的 {@code as(…)} 消息只在**失败时**才可见，
     * 而红证需要「现在是绿的，但注入这个变异后会红成什么样」这句原话 —— 本方法给的就是那句话。
     *
     * <p>真实文本的变异一律发生在**内存副本**上（绝不改工作树）。它兼作<b>变异自证</b>：每条变异先断言
     * 「变异真的生效了」（{@code replace} 必须命中），否则「注入没生效」会被误读成「判据没红」
     * （{@code migao-dev-flow} §23 G8：变异注入先自证生效）。</p>
     *
     * <p>⚠️ <b>台账里两条「本批未修」的写面是刻意绿的</b>（{@code AgentSessionService#sendMessage} /
     * {@code #endSession} 仍是谓词缺失的 {@code updateById}）：#6962 P5 只做三处高风险点，它们由台账
     * <b>具名登记 + 重启条件</b>负责「可见」，而不是靠本判据把它们藏起来。本报告里把「把这句无谓词写
     * 换成 CAS 调用」当作变异 ⇒ 台账锚当场对不上 ⇒ 判红（正是「台账与源码不许不一致」的红证）。</p>
     */
    @Test
    @DisplayName("红证报告：真语料逐条变异 ⇒ 逐条判红并逐字打印判定消息（变异先自证生效）")
    void printsTheExactJudgementMessageForEveryInjectedMutation() throws IOException {
        Corpus real = realCorpus();
        System.out.println("[PROOF MC-106 基线] 合规真语料 problems=" + corpusProblems(real));
        assertThat(corpusProblems(real)).as("真语料基线必须是空的（否则红证报告无从谈起）").isEmpty();

        int proven = 0;
        for (String[] inj : REAL_MUTATIONS) {
            Corpus broken = mutateCorpus(real, inj[0], inj[1], inj[2], true);
            List<String> problems = corpusProblems(broken);
            System.out.println("[PROOF MC-106 变异] " + ownerOf(inj[0]) + " :: " + inj[3]
                    + "\n    ⇒ " + problems);
            assertThat(problems).as("变异「%s」必须判红（否则这条判据是空断言）", inj[3]).isNotEmpty();
            proven++;
        }
        System.out.println("[PROOF MC-106 计数] 判红的变异条数=" + proven);
        assertThat(proven).as("红证条数不许为 0").isPositive();
    }

    /** 真语料上的红证变异表：{file, from, to, 标题}。 */
    private static final List<String[]> REAL_MUTATIONS = List.of(
            new String[]{AGENT_SESSION_MAPPER,
                    "WHERE id = #{id} AND tenant_id = #{tenantId} AND status = 'waiting' AND deleted = 0",
                    "WHERE id = #{id} AND tenant_id = #{tenantId} AND status = 'waiting'",
                    "会话分配 CAS 丢掉 deleted = 0 ⇒ 已软删的会话也能被抢"},
            new String[]{AGENT_SESSION_MAPPER,
                    "WHERE id = #{id} AND tenant_id = #{tenantId} AND status = 'waiting' AND deleted = 0",
                    "WHERE id = #{id} AND tenant_id = #{tenantId} AND deleted = 0",
                    "会话分配 CAS 丢掉 status = 'waiting' 谓词 ⇒ 已结束的会话也能被抢"},
            new String[]{AGENT_SESSION_MAPPER,
                    "WHERE id = #{id} AND tenant_id = #{tenantId} AND status = 'waiting' AND deleted = 0",
                    "WHERE id = #{id} AND tenant_id = #{tenantId} AND deleted = 0",
                    "会话分配 CAS 丢掉 status='waiting' ⇒ 无条件迁移（本单病根）"},
            new String[]{KNOWLEDGE_CANDIDATE_MAPPER,
                    "WHERE id = #{id} AND tenant_id = #{tenantId} AND status = 'pending'</script>",
                    "WHERE id = #{id} AND tenant_id = #{tenantId} AND status = 'pending' AND deleted = 0</script>",
                    "候选处置 CAS 给**本无 deleted 列**的表补上 deleted = 0（本批实证陷阱）"},
            new String[]{KNOWLEDGE_CANDIDATE_MAPPER,
                    "AND status = 'pending'</script>", "</script>",
                    "候选处置 CAS 丢掉 status='pending' ⇒ 已处置的候选可被二次处置"},
            new String[]{ROUTE_TEMPLATE_MAPPER,
                    ".eq(ProductionRouteTemplate::getDeleted, 0)\n                .set(",
                    ".set(",
                    "路线模板软删丢掉 deleted = 0 条件 ⇒ 已软删的行也会被再删一次"},
            new String[]{ROUTE_RULE_MAPPER,
                    ".eq(ProductionRouteRule::getTenantId, tenantId)\n", "",
                    "条件工序规则软删丢掉 tenant 限定 ⇒ 跨租户误删"},
            new String[]{ROUTING_COMMAND_SERVICE,
                    "if (productionRouteTemplateMapper.markDeletedByIdAndTenant(id, tenantId) == 0) {",
                    "productionRouteTemplateMapper.updateById(template);\n"
                            + "        if (productionRouteTemplateMapper.markDeletedByIdAndTenant(id, tenantId) == 0) {",
                    "路线软删退回整实体 updateById（锚留着、落库无谓词）"},
            new String[]{ROUTING_COMMAND_SERVICE,
                    "if (productionRouteTemplateMapper.markDeletedByIdAndTenant(id, tenantId) == 0) {",
                    "if (productionRouteTemplateMapper.markDeletedByIdAndTenant(id, 999L) == 0) {",
                    "路线软删换成别人的 tenantId ⇒ 台账锚不再逐字兑现"},
            new String[]{ROUTING_COMMAND_SERVICE,
                    "if (productionRouteRuleMapper.markDeletedByIdAndTenant(id, tenantId) == 0) {",
                    "if (productionRouteRuleMapper.markDeletedByIdAndTenant(id, tenantId) > -1) {",
                    "规则软删不再判影响行数（0 行当成功）⇒ 锚不再兑现"},
            new String[]{KNOWLEDGE_CANDIDATE_SERVICE,
                    "knowledgeCandidateMapper.markReviewedIfPending(",
                    "knowledgeCandidateMapper.someOtherWrite(",
                    "候选处置的 CAS 调用被改名 ⇒ 台账锚不再兑现"},
            new String[]{KNOWLEDGE_CANDIDATE_SERVICE,
                    "        int affected = knowledgeCandidateMapper.markReviewedIfPending(",
                    "        knowledgeCardMapper.insert(card);\n"
                            + "        int affected = knowledgeCandidateMapper.markReviewedIfPending(",
                    "插卡被挪到抢卡位之前（次序反转 ⇒ 并发双采纳各插一张卡）"},
            new String[]{AGENT_SESSION_SERVICE,
                    "        if (agentSessionMapper.markAssignedIfWaiting(sessionId, tenantId, employeeId, now) == 0) {",
                    "        if (false && agentSessionMapper.markAssignedIfWaiting(sessionId, tenantId, employeeId, now) == 0) { }\n"
                            + "        agentSessionMapper.updateById(session);",
                    "会话分配「锚留着、落库换 updateById」（#6928/#6962 实证过的隐蔽形态）"},
            new String[]{AGENT_SESSION_SERVICE,
                    "        if (agentSessionMapper.markAssignedIfWaiting(sessionId, tenantId, employeeId, now) == 0) {",
                    "        if (agentSessionMapper.markAssignedIfWaiting(sessionId, 999L, employeeId, now) == 0) {",
                    "会话分配 CAS 换成别人的 tenantId ⇒ 台账锚不再逐字兑现"},
            // 🔴 台账两条「本批未修」写面的**重启条件**红证：谁把 sendMessage 改成 CAS 却不更新台账 ⇒ 红
            new String[]{AGENT_SESSION_SERVICE,
                    "            agentSessionMapper.updateById(update);",
                    "            agentSessionMapper.markAssignedIfWaiting(sessionId, TenantContext.getTenantId(), update.getEmployeeId(), update.getStartedAt());",
                    "sendMessage 真的改成 CAS 了、台账锚却没跟着更新 ⇒ 红（台账不许与源码不一致）"},
            new String[]{AGENT_SESSION_MAPPER,
                    ", @Param(\"tenantId\") Long tenantId", "",
                    "CAS 谓词里的 #{tenantId} 没有任何 @Param 绑定 ⇒ 台账/谓词完整性判据必须红"},
            new String[]{LEDGER_PATH,
                    "\"method\": \"AgentSessionService#assignSession\"",
                    "\"method\": \"AgentSessionService#ghostAssign\"",
                    "台账给不存在的写路径盖章（改名 / 删除）"},
            new String[]{LEDGER_PATH,
                    "\"unverified\": []", "\"unverified\": [\"someone-new\"]",
                    "新增豁免（豁免台账只许缩短）"},
            new String[]{LEDGER_PATH,
                    "\"call_anchor\": \"agentSessionMapper.markAssignedIfWaiting(sessionId, tenantId\"",
                    "\"call_anchor\": \"agentSessionMapper.markAssignedIfWaiting(sessionId, tenantId)\"" +
                            "",
                    "台账 call_anchor 被改坏（补一个 `)` ⇒ 方法体里逐字找不到）⇒ 程序化登记未兑现"});

    // ────────────────────────────────────────────── 判定本体（真语料与合成语料共用同一套）

    /** 一个虚拟仓库快照：文件文本 + 台账。真语料与合成语料都走它。 */
    private record Corpus(Map<String, String> files, JsonNode ledger) {

        String text(String path) {
            return files.getOrDefault(path, "");
        }
    }

    /** 跑一遍判定本体：返回问题清单（空 = 合规）。真语料与合成语料走**同一套**。 */
    private static List<String> corpusProblems(Corpus c) {
        List<String> problems = new ArrayList<>();
        for (MapperGroup g : GROUPS) {
            problems.addAll(sqlProblems(c.text(g.file()), g, g.file()));
            problems.addAll(bindingProblems(c.text(g.file()), g, g.file()));
            problems.addAll(methodProblems(c.text(g.file()), g, g.file()));
        }
        problems.addAll(serviceWritePathProblems(c));
        problems.addAll(registrationProblems(c));
        problems.addAll(insertOrderingProblems(c));
        return problems;
    }
    // ── 泛型：写面

    /** mapper 里的手写 SQL 写面（方法名 + SQL）。 */
    private record SqlCandidate(String method, String sql) {
    }

    /** mapper 里条件更新**方法体**的写面（方法名 + 体）。 */
    private record MethodCandidate(String method, String body) {
    }

    /** 一次判定：合成 / 真源码共用的谓词检查（手写 SQL 侧）。 */
    private static List<String> sqlProblems(String mapperText, MapperGroup g, String label) {
        List<String> problems = new ArrayList<>();
        for (SqlCandidate c : sqlCandidates(mapperText, g)) {
            String where = whereClause(c.sql());
            for (ColumnPredicate p : g.updatePredicates()) {
                String region = WHERE.equals(p.token()) ? where : c.sql();
                boolean present = p.marker().matcher(region).find();
                if (p.mustBePresent() && !present) {
                    problems.add(ownerOf(label) + "#" + c.method() + " 缺 " + p.label());
                } else if (!p.mustBePresent() && present) {
                    problems.add(ownerOf(label) + "#" + c.method() + " 出现禁令形态：" + p.label());
                }
            }
        }
        return problems;
    }

    /** 一次判定：合成 / 真源码共用的谓词检查（条件更新方法体侧）。 */
    private static List<String> methodProblems(String mapperText, MapperGroup g, String label) {
        List<String> problems = new ArrayList<>();
        if (g.methodPredicates().isEmpty()) {
            return problems;
        }
        for (MethodCandidate c : methodCandidates(mapperText, g, problems)) {
            for (ColumnPredicate p : g.methodPredicates()) {
                if (!p.marker().matcher(c.body()).find()) {
                    problems.add(ownerOf(label) + "#" + c.method() + " 缺 " + p.label());
                }
            }
        }
        return problems;
    }

    /** 现取：mapper 里**在 SET 侧写守卫列**的手写 SQL（方法名 + SQL）。 */
    private static List<SqlCandidate> sqlCandidates(String mapperText, MapperGroup g) {
        List<SqlCandidate> out = new ArrayList<>();
        Map<String, String> byOwner = new LinkedHashMap<>();
        for (MapperGroup other : GROUPS) {
            byOwner.put(ownerOf(other.file()), mapperText);
        }
        Matcher m = SQL_ANNOTATION.matcher(mapperText);
        while (m.find()) {
            String sql = toSql(m.group(1));
            String upper = sql.toUpperCase();
            if (!upper.contains("UPDATE " + g.table().toUpperCase()) || !writesGuardedColumn(sql, g)) {
                continue;
            }
            out.add(new SqlCandidate(namedMemberAfter(mapperText, m.end()), sql));
        }
        return out;
    }

    /** 现取：mapper 里守卫列的**条件更新方法体**（`LambdaUpdateWrapper` 形态；`body` 已剥注释/字面量）。 */
    private static List<MethodCandidate> methodCandidates(String mapperText, MapperGroup g, List<String> missingOut) {
        List<MethodCandidate> out = new ArrayList<>();
        Map<String, String> bodies = new LinkedHashMap<>();
        for (MethodBody m : membersWithBody(mapperText)) {
            bodies.put(m.name(), m.body());
        }
        for (String required : g.guardedMethods()) {
            if (!bodies.containsKey(required)) {
                missingOut.add(ownerOf(g.file()) + " 里取不到条件更新方法 " + required
                        + "（形态改名 / 扫描器失明，不是「通过」）");
                continue;
            }
            out.add(new MethodCandidate(required, bodies.get(required)));
        }
        return out;
    }

    /** SET 侧是否写守卫列（只看 `SET … WHERE` 之间，免得被 WHERE 里的谓词骗到）。 */
    private static boolean writesGuardedColumn(String sql, MapperGroup g) {
        String upper = sql.toUpperCase();
        int set = upper.indexOf(" SET ");
        int where = upper.indexOf(" WHERE ");
        String setClause = sql.substring(set < 0 ? 0 : set, where < 0 ? sql.length() : where);
        return g.guardedSetColumn().matcher(setClause).find();
    }

    /** WHERE 侧片段（谓词判定只看它 —— 免得被 SET 侧的赋值骗过去）。 */
    private static String whereClause(String sql) {
        Matcher m = Pattern.compile("(?i)\\bWHERE\\b").matcher(sql);
        return m.find() ? sql.substring(m.end()) : "";
    }

    /**
     * 块内真正的 SQL：丢掉 MyBatis 的 `<script>` 外壳，从第一个 SQL 动词起取到块尾。
     * 为什么必须丢：`markReviewedIfPending` 的 {@code <script>} 里有 `<choose><when …>` **括号**，
     * 只按「配对括号」取块的写法会把注解值截断在 `test='note != null'` 的 `)` 上（本判据实测）。
     */
    private static String toSql(String annotationValue) {
        String flat = annotationValue.replace("\"", "").replace("+", " ").replace("\n", " ").replaceAll("\\s+", " ");
        Matcher m = SQL_START.matcher(flat);
        return (m.find() ? flat.substring(m.start()) : flat).trim();
    }

    /**
     * 数据绑定完整性：SQL 里引用的每一个 {@code #{param}} 都必须在该 `@Update` 方法的
     * `@Param("param")` 声明里兑现。
     *
     * <p>为什么必须有这一条：{@code tenant_id = #{tenantId}} 这几个字**在 SQL 文本里出现**不等于
     * 它真被绑上了 —— 摘掉参数声明后 SQL 依然「含 tenant 谓词」，但运行期解析不到参数 ⇒ 报错 / 或落在
     * 别的占位上。只查文本的判据会被这种形态骗过去（本判据实测补的这条）。</p>
     */
    private static List<String> bindingProblems(String mapperText, MapperGroup g, String label) {
        List<String> problems = new ArrayList<>();
        Matcher m = SQL_ANNOTATION.matcher(mapperText);
        while (m.find()) {
            String sql = toSql(m.group(1));
            if (!sql.toUpperCase().contains("UPDATE " + g.table().toUpperCase())) {
                continue;
            }
            String member = namedMemberAfter(mapperText, m.end());
            Matcher pm = Pattern.compile("#\\{\\s*([A-Za-z_$][\\w$]*)\\s*\\}").matcher(sql);
            Set<String> declared = declaredParams(mapperText, m.end());
            while (pm.find()) {
                if (!declared.contains(pm.group(1))) {
                    problems.add(ownerOf(label) + "#" + member + " 的 SQL 引用 #{" + pm.group(1)
                            + "} 却没有 @Param(\"" + pm.group(1) + "\") 绑定");
                }
            }
        }
        return problems;
    }

    /** 现取 {@code @Update` 方法签名里的 `@Param("…")` 名字（到该方法的 `{` 或 `;` 为止）。 */
    private static Set<String> declaredParams(String mapperText, int from) {
        int end = mapperText.length();
        for (int i = from; i < mapperText.length(); i++) {
            char c = mapperText.charAt(i);
            if (c == '{' || c == ';') {
                end = i;
                break;
            }
        }
        Set<String> out = new LinkedHashSet<>();
        Matcher pm = Pattern.compile("@Param\\(\\s*\"([A-Za-z_$][\\w$]*)\"\\s*\\)")
                .matcher(mapperText.substring(from, end));
        while (pm.find()) {
            out.add(pm.group(1));
        }
        return out;
    }

    /** SQL 之后的下一个「名字 + `(`」= 方法名（`update` 这类模块方法会被真实方法名覆盖）。 */
    private static String namedMemberAfter(String text, int from) {
        Matcher m = NAMED_MEMBER.matcher(text.substring(from));
        return m.find() ? m.group(1) : "<unknown>";
    }

    /** 现取：类体顶层的「方法名 + 方法体」（{@code body} 已剥注释/字面量，**不得再剥一次**）。 */
    private static List<MethodBody> membersWithBody(String text) {
        String clean = stripCommentsAndStrings(text);
        List<MethodBody> out = new ArrayList<>();
        int depth = 0;
        String pending = null;
        String name = null;
        StringBuilder body = null;
        for (String raw : clean.replace("\r", "").split("\n", -1)) {
            String trimmed = raw.strip();
            if (body == null && depth == 1
                    && raw.startsWith("    ") && !raw.startsWith("     ")
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
     * 现取：{@code text} 里 {@code method} 的**方法体**（跨行签名也能取到；取不到返回 {@code null}）。
     *
     * <p>⚠️ 本判据**初版实测**踩到的失明形态：`assignSession` / `updateStatus` 这类签名收尾的
     * {@code ") {"} 落在**续行**上 —— 只认「签名行含 `) {`」的写法会把整个方法跳过，而它的闭合花括号
     * 照样把深度减 1 ⇒ 深度从此下沉一级 ⇒ 后面所有方法全部扫不到。{@link #membersWithBody} 用的是
     * 「待定签名状态机」：见到「类体顶层 + 4 空格缩进 + `(` + 非注释/注解」先登记名字，到第一个
     * 不深于类体的 `{` 才正式开体。</p>
     */
    private static String methodBody(String text, String method) {
        for (MethodBody b : membersWithBody(text)) {
            if (method.equals(b.name())) {
                return b.body();
            }
        }
        return null;
    }

    /**
     * 剥掉块注释 / 行注释 / 字符串字面量 / 文本块（**保留行结构**：非换行字符变空格，换行原样留下）。
     *
     * <p>⚠️ <b>本判据实测踩到的坑（写在这里免得下一个人再踩）</b>：本方法<b>不是幂等的</b> ——
     * 剥完的结果里，原本的注释只剩下一片空白，若此时**再剥一次**，代码里任何一处**孤立的 `//`**
     * （例如除以「可能为负的除数」那种数学表达式，或路径样式文本）都会被当成行注释起始
     * ⇒ 它**后面整段代码被静默吃掉** ⇒ 写路径候选集凭空少掉几个（本判据初版就是这样：`assignSession`
     * 明明有 {@code markAssignedIfWaiting(} 却被读成「不含任何守卫 mapper 写」）。
     * ⇒ <b>纪律：全文件剥一次（{@link #membersWithBody}），方法体一律用剥好的那份，不再剥第二次。</b>
     * （{@code guardHasDiscriminatingPower} 的「只加注释不红」用例顺带守住这条：注释里的
     * `agentSessionMapper.updateById(session)` 不得被算成真写面。）</p>
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

    // ── 现取：service 写路径

    /** 一条 service 写路径的问题读数：{@code unconditional=true} ⇒ 方法体里有守卫 mapper 的无谓词写。 */
    private record WriteProblem(String method, boolean unconditional, String message) {
    }

    /** 现取：三条 service 里「守卫状态列写」的方法名清单（报读与台账对账都用它）。 */
    private static List<String> serviceWritePaths(Corpus c) {
        Set<String> out = new LinkedHashSet<>();
        for (String file : List.of(AGENT_SESSION_SERVICE, KNOWLEDGE_CANDIDATE_SERVICE, ROUTING_COMMAND_SERVICE)) {
            for (MethodBody m : membersWithBody(c.text(file))) {
                if (!writeProblems(file, m).isEmpty()) {
                    out.add(m.name());
                }
            }
        }
        // ⚠️ 本判据实测订正（别退回）：两张 route 表的软删落库在 **mapper 的 default 方法**里
        // （service 侧只有 `markDeletedByIdAndTenant(id, tenantId) == 0` 一处判断）⇒ **不**经
        // mapperBelongsTo 的模式通道；`reject` 同因（走 markReviewedIfPending）。若只按模式现取，
        // 这三条登记过的路径会从「现取集合」里凭空消失 ⇒ 判据 1 与台账两侧都对不上（那是**判据失明**，
        // 不是源码有病）。⇒ 口径 = 模式通道 ∪ 台账登记：模式通道发现**未登记**的野生写路径，
        // 台账侧保证**已登记**的不会消失，两边各管一半。
        for (PathBinding p : ledgerBindings(c)) {
            out.add(p.method());
        }
        return new ArrayList<>(out);
    }

    /**
     * 一个方法是不是「守卫列写路径」：方法体里的某个 `xxxMapper.` 调用属于该文件守卫的 mapper
     * （{@code body} 已剥注释/字面量 ⇒ **不得再剥一次**，见 {@link #stripCommentsAndStrings}）。
     */
    private static List<WriteProblem> writeProblems(String file, MethodBody m) {
        return writeProblems(file, m, false);
    }

    /**
     * 同上；{@code includeRoute=true} 时把两条 route mapper 也算进来 —— 只给
     * {@link #serviceWritePathProblems} 用：那里判的是**登记兑现**（台账里已有的那几条），
     * 而 {@link #serviceWritePaths} 的「现取写路径清单」必须排除 route mapper，
     * 否则 {@code ProductionRoutingCommandService} 里别的 {@code updateById} 写面会被误判进来。
     */
    private static List<WriteProblem> writeProblems(String file, MethodBody m, boolean includeRoute) {
        List<WriteProblem> out = new ArrayList<>();
        Matcher matcher = UNCONDITIONAL_WRITE.matcher(m.body());
        while (matcher.find()) {
            String mapperVar = matcher.group(1);
            if (!mapperBelongsTo(file, mapperVar, includeRoute)) {
                continue;
            }
            boolean unconditional = matcher.group(2) != null;
            out.add(new WriteProblem(m.name(), unconditional,
                    (unconditional ? "无谓词写（整实体回写 / 只按 id 的条件更新）" : "守卫 mapper 的写")
                            + "：" + ownerOf(file) + "#" + m.name() + " 里的 " + mapperVar + "."));
        }
        return out;
    }

    /**
     * mapper 变量名是否属于该 service 文件守卫的 mapper（大小写不敏感的子串判定）。
     *
     * <p>⚠️ 两条 route 表**不在**这里：它们的软删走「mapper 的 default 方法 + `LambdaUpdateWrapper`」，
     * 落库语句在 **mapper** 里（不在 service 里）⇒ service 侧只有 {@code markDeletedByIdAndTenant(id, tenantId) == 0}
     * 这一处判断，由 {@link #serviceWritePathProblems} 单独判。若把 route 也算进来，会把
     * {@code ProductionRoutingCommandService} 里别的写面误判成本判据的对象（那是**过度**取块 = 假红）。</p>
     */
    private static boolean mapperBelongsTo(String file, String mapperVar) {
        return mapperBelongsTo(file, mapperVar, false);
    }

    private static boolean mapperBelongsTo(String file, String mapperVar, boolean includeRoute) {
        for (MapperGroup g : GROUPS) {
            if (!includeRoute && ROUTE_MAPPER_FILES.contains(g.file())) {
                continue;
            }
            if (mapperVar.toLowerCase().contains(ownerOf(g.file()).toLowerCase())) {
                return true;
            }
        }
        return false;
    }

    // ── 登记 / 兑现 / 台账（登记与豁免的唯一真值源 = 台账）

    /** 台账 {@code service_write_paths} 的一条绑定：登了哪个写路径、它主张的收口锚是什么。 */
    private record PathBinding(String file, String method, String anchor, String label) {
    }

    /**
     * 从台账现取写路径绑定（{@code method} = {@code <类>#<方法>}，{@code call_anchor} = 必须逐字出现的锚，
     * {@code file} = 该路径所在源文件）。台账是「登记」与「本批未修豁免」的**唯一真值源**
     * ⇒ 本判据里没有第二张豁免名单。
     */
    private static List<PathBinding> ledgerBindings(Corpus c) {
        List<PathBinding> out = new ArrayList<>();
        for (JsonNode e : c.ledger().path("service_write_paths")) {
            out.add(new PathBinding(e.path("file").asText(""), bareMethod(e.path("method").asText()),
                    e.path("call_anchor").asText(""), e.path("method").asText()));
        }
        return out;
    }

    /** 判据 3：CAS 收口锚的清单（现取自 {@link #GROUPS} 的 {@code guardedMethods}）⇒ 守卫范畴由它界定。 */
    private static List<String> casAnchors() {
        List<String> out = new ArrayList<>();
        for (MapperGroup g : GROUPS) {
            String mapperVar = Character.toLowerCase(ownerOf(g.file()).charAt(0)) + ownerOf(g.file()).substring(1);
            for (String m : g.guardedMethods()) {
                out.add(mapperVar + "." + m + "(");
            }
        }
        return out;
    }

    /** 写路径所在源文件：台账的 {@code file} 字段优先；缺失（合成语料）时按方法名在三条 service 里现找。 */
    private static String serviceFileOf(Corpus c, PathBinding p) {
        if (!p.file().isEmpty() && c.files().containsKey(p.file())) {
            return p.file();
        }
        for (String file : List.of(AGENT_SESSION_SERVICE, KNOWLEDGE_CANDIDATE_SERVICE, ROUTING_COMMAND_SERVICE)) {
            if (methodBody(c.text(file), p.method()) != null) {
                return file;
            }
        }
        return "";
    }

    /**
     * 判据 3 的判定本体（登记兑现 + 豁免可见）：每个**登记的写面**都要过这一关 ——
     * ① 方法必须在源码里（改名 / 删除 ⇒ 红）；② 登记的 {@code call_anchor} 必须**逐字**出现在方法体里
     * （摘掉 CAS 调用 ⇒ 红 —— 这条与 `evidence` 是两套独立取数：一个是**程序化**的 {@code call_anchor}，
     * 一个是**证据串**，各自都要兑现）；③ 方法体里出现守卫 mapper 的无谓词写（{@code updateById} /
     * 只按 id 的 {@code update}）时：若该条登记的主张是 <b>CAS 收口</b> ⇒ **红**（主张被推翻）；
     * 若该条登记**明说未修**（锚逐字就是那句无谓词写）⇒ **绿但可见**（#6962 P5 只做三处高风险点，
     * 台账对此具名登记 + 重启条件；这正是本守卫要的「可见」，不是「掩盖」）。
     */
    private static List<String> serviceWritePathProblems(Corpus c) {
        List<String> problems = new ArrayList<>();
        List<String> cas = casAnchors();
        for (PathBinding p : ledgerBindings(c)) {
            String file = serviceFileOf(c, p);
            String body = file.isEmpty() ? null : methodBody(c.text(file), p.method());
            if (body == null) {
                problems.add("台账登记的写路径在源码里找不到（改名 / 删除 ⇒ 红）: " + p.label());
                continue;
            }
            String anchor = p.anchor();
            if (anchor.isEmpty() || !body.contains(anchor)) {
                problems.add("登记未兑现：程序化 call_anchor 在方法体里找不到: " + p.label() + "（" + anchor + "）");
            }
            boolean casAnchored = cas.stream().anyMatch(a -> anchor.contains(a));
            boolean unguarded = writeProblems(file, new MethodBody(p.method(), body), true).stream()
                    .anyMatch(WriteProblem::unconditional);
            if (unguarded && casAnchored) {
                problems.add("登记主张 CAS 收口、方法体里却有守卫 mapper 的无谓词写（updateById / 只按 id）: " + p.label());
            }
            if (unguarded && !anchor.isEmpty() && !UNCONDITIONAL_WRITE.matcher(anchor).find()) {
                problems.add("台账登记的是「未修（无谓词写）」、锚却不是那句无谓词写 ⇒ 台账与源码已经对不上"
                        + "（要么把锚更新成真实的收口点，要么把它换成 CAS 锚并真的改代码）: " + p.label());
            }
        }
        return problems;
    }

    private static List<String> registrationProblems(Corpus c) {
        JsonNode ledger = c.ledger();
        if (ledger == null || ledger.isMissingNode() || ledger.path("service_write_paths").isMissingNode()) {
            return List.of("台账读不到 / 缺 service_write_paths（合成语料忘了给 / 文件被删 ⇒ fail-closed）");
        }
        List<String> problems = new ArrayList<>();

        // ① 未登记即红：现取到的每个写路径都必须在册
        Set<String> registered = ledgerBindings(c).stream().map(PathBinding::method).collect(Collectors.toSet());
        for (String path : serviceWritePaths(c)) {
            if (!registered.contains(path)) {
                problems.add("service 未登记的状态写路径: " + path);
            }
        }

        // ② 台账不许给不存在的对象盖章 + 登记的锚必须逐字兑现
        List<String> live = serviceWritePaths(c);
        for (PathBinding p : ledgerBindings(c)) {
            String file = serviceFileOf(c, p);
            String body = file.isEmpty() ? null : methodBody(c.text(file), p.method());
            if (body == null) {
                problems.add("台账给不存在的写路径盖章: " + p.label());
            } else if (p.anchor().isEmpty() || !body.contains(p.anchor())) {
                problems.add("写路径未兑现：主张的收口锚不在方法体里: " + p.label() + "（" + p.anchor() + "）");
            }
        }
        problems.addAll(evidenceProblems(c));

        // ③ 不许空转（fail-closed）
        int entries = ledger.path("entries").size();
        int writePaths = ledger.path("service_write_paths").size();
        if (entries <= 0) {
            problems.add("台账不许空转：entries 为 0 ⇒ 红（「空」不等于「全部合规」）");
        }
        if (writePaths <= 0) {
            problems.add("台账不许空转：service_write_paths 为 0 ⇒ 红（「空」不等于「全部合规」）");
        }

        // ④ 豁免只许缩短
        int unverified = ledger.path("unverified").size();
        int baseline = ledger.path("unverified_baseline").asInt(-1);
        if (baseline < 0) {
            problems.add("台账缺 unverified_baseline（豁免基线必须冻结，否则「只许缩短」无从判定）");
        } else if (unverified > baseline) {
            problems.add("豁免台账只许缩短：unverified=" + unverified + " > 基线=" + baseline);
        }
        return problems;
    }

    /** 判据 5：每条 {@code evidence} = {@code <仓库相对全路径>::<可检索文本>}，右侧必须逐字出现。 */
    private static List<String> evidenceProblems(Corpus c) {
        List<String> problems = new ArrayList<>();
        for (String section : List.of("entries")) {
            for (JsonNode e : c.ledger().path(section)) {
                String label = section + " " + e.path("method").asText();
                String anchor = e.path("evidence").asText("");
                int sep = anchor.indexOf("::");
                if (sep <= 0) {
                    problems.add(label + " evidence 形态不是 <path>::<anchor>：" + anchor);
                    continue;
                }
                String file = anchor.substring(0, sep);
                String symbol = anchor.substring(sep + 2);
                if (!c.files().containsKey(file)) {
                    problems.add(label + " 左侧文件不存在或不在射程内：" + file);
                } else if (!c.text(file).contains(symbol)) {
                    problems.add(label + " 右侧锚在文件里找不到（未兑现）：" + symbol);
                }
            }
        }
        return problems;
    }

    /** 台账键 / 读数键的形态是 {@code <类>#<方法>} ⇒ 参与匹配的一律是 {@code #} **之后**那一段。 */
    private static String bareMethod(String name) {
        int hash = name.indexOf('#');
        return hash < 0 ? name : name.substring(hash + 1);
    }

    // ── 判据 6：插卡次序

    private static List<String> insertOrderingProblems(Corpus c) {
        String body = methodBody(c.text(KNOWLEDGE_CANDIDATE_SERVICE), "adoptInternal");
        if (body == null) {
            return List.of("KnowledgeCandidateService#adoptInternal 方法体取不到（判据失明，不是通过）");
        }
        return orderingProblems("KnowledgeCandidateService#adoptInternal", body, KNOWLEDGE_CANDIDATE_SERVICE);
    }

    /**
     * 文字序判定：{@code knowledgeCardMapper.insert(} 必须< b>晚于</b> CAS 调用与它的 {@code == 0} 冲突回滚。
     * 次序反了（先插卡、后抢卡位）⇒ 并发双采纳各插一张卡 = #6962 P5-② 的病根。
     */
    private static List<String> orderingProblems(String label, String body, String file) {
        int cas = body.indexOf("knowledgeCandidateMapper.markReviewedIfPending(");
        int insert = body.indexOf("knowledgeCardMapper.insert(");
        List<String> problems = new ArrayList<>();
        if (cas < 0) {
            problems.add(label + " 找不到抢卡位调用（判据失明，不是通过）");
        }
        if (insert < 0) {
            problems.add(label + " 找不到插卡调用（判据失明，不是通过）");
        }
        if (cas < 0 || insert < 0) {
            return problems;
        }
        if (insert < cas) {
            problems.add(label + " 插卡早于抢卡位 ⇒ 并发双采纳会各插一张卡（次序必须反过来）");
        }
        int after = body.indexOf(")", cas);
        int conflict = after < 0 ? -1 : body.indexOf("== 0", after);
        if (conflict < 0) {
            problems.add(label + " 抢卡位之后不见 `== 0` 冲突判定 ⇒ 0 行当成功（fail-closed 缺失）");
        } else if (insert < conflict) {
            problems.add(label + " 插卡早于抢卡位的 `== 0` 冲突回滚 ⇒ 落败者也插了卡");
        }
        return problems;
    }

    // ── schema 列事实（列级判据的前提，自证不靠猜）

    /** 现取 {@code CREATE TABLE <table> (…)} 里的列名（小写）。 */
    private static Set<String> columnsOf(String schema, String table) {
        Set<String> out = new LinkedHashSet<>();
        int start = -1;
        for (String line : schema.replace("\r", "").split("\n", -1)) {
            if (start < 0) {
                Matcher m = Pattern.compile("(?i)CREATE\\s+TABLE\\s+(?:IF\\s+NOT\\s+EXISTS\\s+)?" + table + "\\s*\\(")
                        .matcher(line);
                if (m.find()) {
                    start = 0;
                }
                continue;
            }
            if (line.strip().startsWith(")")) {
                break;
            }
            Matcher col = Pattern.compile("^\\s*([a-z_][a-z0-9_]*)\\s").matcher(line);
            if (col.find()) {
                out.add(col.group(1).toLowerCase());
            }
        }
        if (start < 0) {
            return Set.of();
        }
        // 列名里混进了约束关键字（PRIMARY KEY / UNIQUE 等行）⇒ 剔掉
        Set<String> keywords = Set.of("primary", "unique", "foreign", "constraint", "check");
        out.removeAll(keywords);
        return out;
    }

    // ────────────────────────────────────────────── 语料构造（合成判据用）

    /**
     * 合成语料：与真源码**同形**的三族（CAS SQL + 条件更新方法体 + 三条 service 写路径）。
     * 用文本块拼 —— 真源码里也可能出现文本块 ⇒ 顺带覆盖 `stripCommentsAndStrings` 的文本块分支。
     */
    private static Map<String, String> syntheticCorpus() {
        Map<String, String> files = new LinkedHashMap<>();
        files.put(AGENT_SESSION_MAPPER, """
                public interface AgentSessionMapper {
                    @Update("UPDATE agent_sessions SET employee_id = #{employeeId}, status = 'active' "
                            + "WHERE id = #{id} AND tenant_id = #{tenantId} AND status = 'waiting' AND deleted = 0")
                    int markAssignedIfWaiting(@Param("id") String id, @Param("tenantId") Long tenantId,
                                              @Param("employeeId") String employeeId);
                }
                """);
        files.put(KNOWLEDGE_CANDIDATE_MAPPER, """
                public interface KnowledgeCandidateMapper {
                    @Update("<script>UPDATE knowledge_candidates SET status = #{status}, "
                            + "reviewed_by = #{reviewedBy} "
                            + "WHERE id = #{id} AND tenant_id = #{tenantId} AND status = 'pending'</script>")
                    int markReviewedIfPending(@Param("id") String id, @Param("tenantId") Long tenantId,
                                              @Param("status") String status,
                                              @Param("reviewedBy") String reviewedBy);
                }
                """);
        files.put(ROUTE_TEMPLATE_MAPPER, """
                public interface ProductionRouteTemplateMapper {
                    default int markDeletedByIdAndTenant(String id, Long tenantId) {
                        return update(null, new LambdaUpdateWrapper<ProductionRouteTemplate>()
                                .eq(ProductionRouteTemplate::getId, id)
                                .eq(ProductionRouteTemplate::getTenantId, tenantId)
                                .eq(ProductionRouteTemplate::getDeleted, 0)
                                .set(ProductionRouteTemplate::getDeleted, 1));
                    }
                }
                """);
        files.put(ROUTE_RULE_MAPPER, """
                public interface ProductionRouteRuleMapper {
                    default int markDeletedByIdAndTenant(String id, Long tenantId) {
                        return update(null, new LambdaUpdateWrapper<ProductionRouteRule>()
                                .eq(ProductionRouteRule::getId, id)
                                .eq(ProductionRouteRule::getTenantId, tenantId)
                                .eq(ProductionRouteRule::getDeleted, 0)
                                .set(ProductionRouteRule::getDeleted, 1));
                    }
                }
                """);
        files.put(AGENT_SESSION_SERVICE, """
                public class AgentSessionService {
                    public void assignSession(String id) {
                        agentSessionMapper.markAssignedIfWaiting(id, tenantId);
                    }
                }
                """);
        files.put(KNOWLEDGE_CANDIDATE_SERVICE, """
                public class KnowledgeCandidateService {
                    private KnowledgeCard adoptInternal(String id) {
                        int affected = knowledgeCandidateMapper.markReviewedIfPending(id, tenantId);
                        if (affected == 0) {
                            throw conflictOnStaleStatus(id, "采纳");
                        }
                        KnowledgeCard card = build();
                        knowledgeCardMapper.insert(card);
                        return card;
                    }

                    public void reject(String id) {
                        knowledgeCandidateMapper.markReviewedIfPending(id, tenantId);
                    }
                }
                """);
        files.put(ROUTING_COMMAND_SERVICE, """
                public class ProductionRoutingCommandService {
                    public Map<String, Object> deleteRouting(String id, Long tenantId) {
                        if (productionRouteTemplateMapper.markDeletedByIdAndTenant(id, tenantId) == 0) {
                            throw conflict();
                        }
                        return result();
                    }

                    public Map<String, Object> deleteRouteRule(String id, Long tenantId) {
                        if (productionRouteRuleMapper.markDeletedByIdAndTenant(id, tenantId) == 0) {
                            throw conflict();
                        }
                        return result();
                    }
                }
                """);
        return files;
    }

    /** 待下发台账的合成 JSON（与真台账逐字同形；**不**写进工作树）。 */
    private static String syntheticLedger() {
        return """
                {
                  "entries": [
                    {"method": "AgentSessionMapper#markAssignedIfWaiting",
                     "evidence": "%s::int markAssignedIfWaiting("},
                    {"method": "KnowledgeCandidateMapper#markReviewedIfPending",
                     "evidence": "%s::int markReviewedIfPending("},
                    {"method": "ProductionRouteTemplateMapper#markDeletedByIdAndTenant",
                     "evidence": "%s::default int markDeletedByIdAndTenant("},
                    {"method": "ProductionRouteRuleMapper#markDeletedByIdAndTenant",
                     "evidence": "%s::default int markDeletedByIdAndTenant("}
                  ],
                  "service_write_paths": [
                    {"method": "AgentSessionService#assignSession",
                     "file": "%s",
                     "call_anchor": "agentSessionMapper.markAssignedIfWaiting(",
                     "evidence": "%s::agentSessionMapper.markAssignedIfWaiting("},
                    {"method": "KnowledgeCandidateService#adoptInternal",
                     "file": "%s",
                     "call_anchor": "knowledgeCandidateMapper.markReviewedIfPending(",
                     "evidence": "%s::knowledgeCandidateMapper.markReviewedIfPending("},
                    {"method": "KnowledgeCandidateService#reject",
                     "file": "%s",
                     "call_anchor": "knowledgeCandidateMapper.markReviewedIfPending(",
                     "evidence": "%s::knowledgeCandidateMapper.markReviewedIfPending("},
                    {"method": "ProductionRoutingCommandService#deleteRouting",
                     "file": "%s",
                     "call_anchor": "productionRouteTemplateMapper.markDeletedByIdAndTenant(id, tenantId) == 0",
                     "evidence": "%s::productionRouteTemplateMapper.markDeletedByIdAndTenant(id, tenantId) == 0"},
                    {"method": "ProductionRoutingCommandService#deleteRouteRule",
                     "file": "%s",
                     "call_anchor": "productionRouteRuleMapper.markDeletedByIdAndTenant(id, tenantId) == 0",
                     "evidence": "%s::productionRouteRuleMapper.markDeletedByIdAndTenant(id, tenantId) == 0"}
                  ],
                  "unverified_baseline": 0,
                  "unverified": []
                }
                """.formatted(AGENT_SESSION_MAPPER, KNOWLEDGE_CANDIDATE_MAPPER, ROUTE_TEMPLATE_MAPPER, ROUTE_RULE_MAPPER,
                AGENT_SESSION_SERVICE, AGENT_SESSION_SERVICE,
                KNOWLEDGE_CANDIDATE_SERVICE, KNOWLEDGE_CANDIDATE_SERVICE,
                KNOWLEDGE_CANDIDATE_SERVICE, KNOWLEDGE_CANDIDATE_SERVICE,
                ROUTING_COMMAND_SERVICE, ROUTING_COMMAND_SERVICE,
                ROUTING_COMMAND_SERVICE, ROUTING_COMMAND_SERVICE);
    }

    /** 次序反转的合成变异：把插卡挪到抢卡位之前（去掉原位置的插卡）。 */
    private static Map<String, String> swapInsertBeforeCas(Map<String, String> files) {
        String text = files.get(KNOWLEDGE_CANDIDATE_SERVICE)
                .replace("        knowledgeCardMapper.insert(card);\n", "")
                .replace("        int affected = knowledgeCandidateMapper.markReviewedIfPending(id, tenantId);",
                        "        knowledgeCardMapper.insert(build());\n"
                                + "        int affected = knowledgeCandidateMapper.markReviewedIfPending(id, tenantId);");
        Map<String, String> out = new LinkedHashMap<>(files);
        out.put(KNOWLEDGE_CANDIDATE_SERVICE, text);
        return out;
    }

    /** 不可变地替换语料里一条文本（**必须命中**，否则返回原样 —— 真语料侧另有「变异自证」）。 */
    private static Map<String, String> mutate(Map<String, String> files, String file, String from, String to) {
        Map<String, String> out = new LinkedHashMap<>(files);
        out.put(file, out.getOrDefault(file, "").replace(from, to));
        return out;
    }

    /** 不可变地替换真语料里一条文本；{@code assertInjected=true} 时先断言变异真的生效（变异自证）。 */
    private static Corpus mutateCorpus(Corpus c, String file, String from, String to, boolean assertInjected) {
        String original = c.text(file);
        String mutated = original.replace(from, to);
        if (assertInjected) {
            assertThat(mutated).as("变异自证：`%s` 在 %s 里必须命中（否则「没红」会被误读成判据有效）", from, file)
                    .isNotEqualTo(original);
        }
        Map<String, String> files = new LinkedHashMap<>(c.files());
        files.put(file, mutated);
        // 🔴 台账文本被变异 ⇒ 台账根节点必须重解析：否则「给不存在的写路径盖章」「新增豁免」
        // 这类变异只是改了字符串、判定读的还是旧节点 ⇒ 恒绿的空断言（本单判别力自证抓到的形态）。
        JsonNode ledger = LEDGER_PATH.equals(file) ? reparseLedger(mutated) : c.ledger();
        return new Corpus(files, ledger);
    }

    /** 台账文本 → 判定用的根节点（变异后必须重解析；解析失败按 fail-closed 交给调用方断言）。 */
    private static JsonNode reparseLedger(String text) {
        try {
            return JSON.readTree(text);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("变异后的台账不是合法 JSON（变异本身写坏了）", e);
        }
    }

    /** 极简函数接口（JDK 的 {@code Function} 也行，这里只为读数可读性）。 */
    private interface Func<T, R> {
        R apply(T t) throws JsonProcessingException;
    }

    // ────────────────────────────────────────────── 语料读取

    /** 从工作树读真语料（源文件 + 台账）。 */
    private static Corpus realCorpus() throws IOException {
        Path root = repoRoot();
        Map<String, String> files = new LinkedHashMap<>();
        for (String file : SCANNED_FILES) {
            Path p = root.resolve(file);
            files.put(file, Files.exists(p) ? Files.readString(p, StandardCharsets.UTF_8) : "");
        }
        JsonNode ledger = JSON.readTree(files.get(LEDGER_PATH));
        return new Corpus(files, ledger);
    }

    private static String srcText(String file) throws IOException {
        return realCorpus().text(file);
    }

    private static String ownerOf(String file) {
        String base = file.substring(file.lastIndexOf('/') + 1);
        return base.endsWith(".java") ? base.substring(0, base.length() - 5) : base;
    }

    private record MethodBody(String name, String body) {
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
