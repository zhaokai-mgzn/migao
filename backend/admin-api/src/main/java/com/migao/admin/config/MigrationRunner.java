package com.migao.admin.config;

import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.CommandLineRunner;
import org.springframework.core.io.Resource;
import org.springframework.core.io.support.ResourcePatternResolver;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.ConnectException;
import java.net.SocketTimeoutException;
import java.net.UnknownHostException;
import java.nio.charset.StandardCharsets;
import java.sql.SQLException;
import java.sql.SQLTransientConnectionException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

/**
 * 极简 DB 迁移器 — 替代 Flyway。
 *
 * 启动时扫描 db/migration/V*__xxx.sql，按**版本号数值**排序，
 * 跳过已执行的文件，执行新的 migration。
 * 通过 schema_migrations 表追踪执行历史。
 *
 * ⚠️ **建库只有一份脚本（issue #5243）**：历史迁移链（V1 … V114）已**整链归档**到
 * `backend/admin-api/src/main/resources/db/migration-archive/`，`db/migration/` 此后**只放未来的增量迁移**。
 * 于是「空库怎么建出终态」不再由迁移链承担，而由**基线**承担 ——
 * `db/init/schema.sql`（配置键 `migao.migration.init-script`，台账键 = 文件名 `schema.sql`）。
 * 三条语义：台账已有该键 ⇒ 跳过；库非空 ⇒ **只记账不执行**；库为空 ⇒ 执行后记账。
 * 见 {@link #applyBaseline}。这也让「一份建库脚本」同时进了 Docker 构建上下文
 * （`Dockerfile` 只 `COPY src`）与 runner 的 classpath。
 *
 * 所有 SQL 文件必须幂等（IF NOT EXISTS / ON CONFLICT DO NOTHING）。
 *
 * ⚠️ 两条硬约束（issue #3270 CI 实证，两者叠加曾让 schema 与代码长期脱节）：
 *   1. **必须按版本号数值排序**，不能按文件名字典序 —— 字典序下 `V5` 排在 `V40` 之后、
 *      `V2` 排在 `V19` 之后（本类注释曾误写成「V1 &lt; V2 &lt; … &lt; V30」）。
 *   2. **单条迁移失败不得中断其余迁移** —— 但"一律只记 ERROR"**并非总是对的**（见下条），
 *      而让整条链停下会让 V28 之后的 V29–V41 与单数字的 V5–V9 **全部不执行**，
 *      于是 `orders.actual_amount` 之类的列永远缺失 → admin-api 查询 500 →
 *      ai-agent 工具「服务暂时不可用」→ 熔断 → 评测被污染。
 *      **例外（issue #4241）**：**连接类**失败不算「单条迁移失败」，见下条 —— 它必须 fail-closed。
 *
 * ⚠️ **失败分两类（issue #4241 实测）**：判据是**失败的性质**，不是失败发生在哪一步。
 *   - **连接类**（`CannotGetJdbcConnectionException` / `SQLTransientConnectionException` / 连接超时等，
 *     见 {@link #isConnectionFailure}）：库抖动是**暂时**的 ⇒ 有限次退避重试；重试耗尽
 *     **抛错让应用启动失败**（`MigrationConnectionFailureException`）。
 *     旧行为是 fail-open：`ensureHistoryTable` 拿不到连接 ⇒ 整轮迁移被外层 catch 吞掉、
 *     **一条都不跑**，而 `/actuator/health` 照报 UP ⇒ 新迁移没落库、业务端点随机 500
 *     （实测改工序单价 500「relation "production_operation_price_versions" does not exist」，
 *     DB 恢复后**重启一次即好**），且启动后永不重试 ⇒ 抖动窗口过去也不会自愈。
 *   - **内容类**（SQL 语法/约束，即 `execute` 抛的 `DataAccessException` 子类）：维持既有语义
 *     **逐字不变**（跳过该条 + 继续其余 + 记账 + ERROR，见下条），**不重试、不拒启动**。
 *
 * ⚠️ **失败分级（issue #3714）**：bootstrap-first 评测栈上，`KNOWN_BENIGN_LEGACY` 里那几条
 * 已诊断的**历史非幂等**迁移**每次起栈必失败**（目标态已由 `backend/admin-api/src/main/resources/db/init/schema.sql` 建出，
 * 失败真因是"目标已存在"而非"对象缺失"）。旧实现对它们一律打 ERROR +
 * 「请立即修复并在修复后重跑」—— 一句**必然为假**的行动指令（无物可修、重跑必复现）。
 * 长期后果是**真失败与永久噪音同形** → 归因层失效（本仓库自认的最大失败模式）。
 * ⇒ 命中该集合者降级为 INFO、并在汇总行**单独计数**；**未命中的真失败照旧 ERROR + 非零计数**。
 * 决不静默：只有已诊断的存量降级。该集合与 Python 侧登记表的对应关系由 L0 测试锁死（见其注释）。
 *
 * ⚠️ **两条护栏（issue #4991）** —— 「命中文件名即降级」会把**同一文件的新病灶**一起吞掉
 * （本仓最大的失败模式：真失败与永久噪音同形、归因层失效）。故：
 *   1. **登记必须有据**：每条必须写明**目标态由谁达成**（`schema.sql` 或补偿迁移裸版本号 `V&lt;n&gt;`），
 *      由 L0 测试核该补偿迁移**真实存在于迁移链**且**晚于**被补偿者。
 *   2. **判定按「文件名 + 错误签名」**：签名 = `&lt;SQLSTATE&gt;` 或 `&lt;SQLSTATE&gt;:&lt;标识符子串&gt;`，
 *      子串一律取**标识符**（约束名/列名）—— PG 文案随 `lc_messages` 本地化，标识符不随语言变。
 *      在册但错因不符 ⇒ **按真失败处理**（ERROR + 真失败计数 + 日志点名「错因与登记不符」）。
 *
 * 使用 ObjectProvider 延迟获取 JdbcTemplate，确保在无 DataSource 的测试
 * 上下文中（如 SecurityConfigTest）不会因缺少 Bean 而启动失败。
 */
@Slf4j
@Component
public class MigrationRunner implements CommandLineRunner {

    private final ObjectProvider<JdbcTemplate> jdbcProvider;
    private final ResourcePatternResolver resolver;

    /**
     * 最近一轮迁移的**可观测结果**（issue #4517）。
     *
     * <p>⚠️ 为什么需要它：本仓对**非连接类**失败是「跳过这一条、继续跑后面的」（:185，#3270 的刻意权衡），
     * 于是「迁移全过」与「有迁移被跳过」在**部署期不可区分** —— 应用照常 UP、探活 200、部署 success，
     * 而故障面后移到业务 500。本会话已**三次**因此付出代价（#4501 的 V74 / #4514 的 V72 /
     * 由 V72 引发的「云上生成加工单对所有订单 500」）。</p>
     *
     * <p>⚠️ 语义边界：这里**只暴露事实**，**不参与**健康判定（见 {@link MigrationHealthIndicator}）——
     * 让健康检查 DOWN 会把「历史非幂等迁移每次起栈必失败」变成「整个环境打挂」，
     * 那是比原问题更糟的故障（{@code KNOWN_BENIGN_LEGACY} 那几条正是这种）。</p>
     */
    private volatile List<String> lastFailed = List.of();
    private volatile int lastFailedRealCount = 0;
    private volatile int lastFailedBenignCount = 0;
    private volatile int lastSkippedByLedger = 0;

    @Value("${migao.migration.locations:classpath:db/migration/*.sql}")
    private String migrationPattern;

    /**
     * **基线初始化脚本**（唯一的一份建库脚本，issue #5243）。
     *
     * <p>本仓曾有四代 SQL 资产（`docs/sql/schema_full.sql` / `docs/sql/migrations/V2026*` /
     * `docs/sql/00*.sql` / 迁移链）。现在**只有一份**建库脚本，且它必须在 admin-api 的
     * **classpath** 内 —— 这样它既进 Docker 构建上下文（`Dockerfile` 只 `COPY src`，
     * 模块外的文件在镜像构建时**根本不可见**），又能被本 runner 读到（此前它在 `docs/sql/`，
     * 两者都够不着）。</p>
     *
     * <p>台账键 = 该资源的**文件名**（如 `schema.sql`）—— 与迁移同一种记账粒度（按文件名）。</p>
     */
    @Value("${migao.migration.init-script:classpath:db/init/schema.sql}")
    private String initScriptLocation;

    /**
     * 判「库**已经有** schema」的哨兵表。
     *
     * <p>`tenants` 自最早一批迁移起就存在，任何有业务的库都必然有它。用它区分
     * 「空库（要建）」与「存量库（**绝不重放**建库脚本）」—— 重放建库脚本会往活库上
     * 灌终态种子，是比「少建一张表」严重得多的故障。</p>
     */
    private static final String BASELINE_PROBE_TABLE = "tenants";

    /**
     * 连接类失败的重试上限（含首次尝试）。连接抖动是**暂时**的，重试能自愈；
     * 上限则保证「持续连不上」不会把启动无限挂死。
     * 默认 5 次 + 退避（2s/4s/8s/10s）⇒ 最坏 ~24s 后 fail-closed。
     */
    @Value("${migao.migration.connect-retry.max-attempts:5}")
    private int maxConnectAttempts = 5;

    /** 连接类失败首次重试前的退避毫秒数（逐次翻倍，封顶 {@link #MAX_BACKOFF_MS}）。 */
    @Value("${migao.migration.connect-retry.backoff-ms:2000}")
    private long connectRetryBackoffMs = 2000;

    /** 退避封顶（防指数退避把启动拖长）。 */
    private static final long MAX_BACKOFF_MS = 10_000L;

    public MigrationRunner(ObjectProvider<JdbcTemplate> jdbcProvider, ResourcePatternResolver resolver) {
        this.jdbcProvider = jdbcProvider;
        this.resolver = resolver;
    }

    @Override
    public void run(String... args) {
        JdbcTemplate jdbc = jdbcProvider.getIfAvailable();
        if (jdbc == null) {
            log.info("⏭️  DataSource 不可用，跳过 DB 迁移（测试环境正常）");
            return;
        }

        for (int attempt = 1; ; attempt++) {
            try {
                migrate(jdbc);
                return;
            } catch (Exception e) {
                if (!isConnectionFailure(e)) {
                    // 既有语义**逐字不变**（issue #3714/#3615 口径）：内容类失败不抛异常，允许应用继续启动
                    log.error("❌ 迁移失败", e);
                    return;
                }
                if (attempt >= maxConnectAttempts) {
                    // fail-closed（issue #4241）：拿不到连接时**绝不能**让应用以 healthy 状态起来服务 ——
                    // 那会让 /actuator/health 谎报 UP、把故障面后移到业务 500
                    // （实测：一条迁移都没跑 ⇒ 改工序单价 500「relation ... does not exist」，重启即好），
                    // 且启动后永不重试 ⇒ 抖动窗口过去也不会自愈。
                    // 抛错 = 启动失败 = 编排/部署层能看见的信号（Spring 记 `Application run failed`
                    // 并把异常抛给 main ⇒ 进程非 0 退出，`docker compose up --wait` 直接失败）。
                    log.error("❌ 迁移失败（连接类）：已尝试 {} 次仍拿不到 DB 连接 —— 拒绝以「schema 未知」状态启动",
                            attempt, e);
                    throw new MigrationConnectionFailureException(
                            "数据库迁移失败（连接类失败，重试 " + attempt + " 次耗尽）—— 拒绝启动", e);
                }
                long backoffMs = Math.min(connectRetryBackoffMs << (attempt - 1), MAX_BACKOFF_MS);
                log.warn("⚠️ 迁移失败（连接类，第 {}/{} 次尝试）：{} —— {}ms 后退避重试",
                        attempt, maxConnectAttempts, rootCause(e), backoffMs);
                try {
                    Thread.sleep(backoffMs);
                } catch (InterruptedException ie) {
                    Thread.currentThread().interrupt();
                    throw new MigrationConnectionFailureException("迁移重试等待被中断 —— 拒绝启动", ie);
                }
            }
        }
    }

    /**
     * 跑**一轮**迁移。可安全重入（连接类失败重试即「从中断处续跑」）：
     * 已记账的迁移在下一轮被 `applied.contains` 跳过，不会重复执行。
     */
    private void migrate(JdbcTemplate jdbc) throws Exception {
        ensureHistoryTable(jdbc);
        List<Failure> failed = new ArrayList<>();
        applyBaseline(jdbc, failed);
        Resource[] resources = resolver.getResources(migrationPattern);
        // 按文件名升序执行（V1 < V2 < ... < V30）：getResources 的返回顺序
        // 取决于 classpath 扫描（JAR 内 zip 遍历序），曾实测返回逆序——
        // 若依赖该顺序，V29 重建表会在 V30 种子之后执行，导致种子被 DROP 清空。
        Arrays.sort(resources, Comparator.comparing(Resource::getFilename,
                Comparator.nullsLast(MIGRATION_ORDER)));
        List<String> applied = getAppliedMigrations(jdbc);

        for (Resource r : resources) {
            String filename = r.getFilename();
            if (filename == null) continue;
            if (applied.contains(filename)) continue;

            log.info("🔄 执行迁移: {}", filename);
            try {
                String sql = readResource(r);
                jdbc.execute(sql);
                recordMigration(jdbc, filename);
                log.info("✅ 迁移完成: {}", filename);
            } catch (Exception e) {
                // 连接类失败**不是**「这条迁移坏」：此刻整条链都拿不到连接，逐条吞掉只会把
                // 「一条都没跑」记成「N 条迁移失败」并让应用照常 UP（issue #4241 的同族形态）。
                // ⇒ 交给外层有限退避重试；重试耗尽即 fail-closed 拒绝启动。
                if (isConnectionFailure(e)) {
                    throw e;
                }
                // 单条失败**只跳过这一条**，继续跑后面的 —— 一条坏迁移不得冻结整个 schema。
                // 实测（issue #3270）：V28 失败后整链中断，V29–V41 与 V5–V9 全未执行，
                // 于是 orders.actual_amount 等列永远缺失、admin-api 500、
                // 评测被熔断污染，而日志里只有一行 ERROR，没人发现。
                failed.add(new Failure(filename, e));
                BenignLegacy benign = KNOWN_BENIGN_LEGACY.get(filename);
                if (benign != null && matchesAnySignature(e, benign.signatures())) {
                    log.info("ℹ️ 迁移失败（已知存量非幂等，目标态已达成，无需修复）: {} — {}",
                            filename, benign.reason());
                } else if (benign != null) {
                    // 护栏②（issue #4991）：在册但**错因不符** ⇒ 按真失败处理。
                    log.error("❌ 迁移失败（已跳过，继续执行其余迁移）—— ⚠️ 该文件在「已知存量非幂等」"
                                    + "登记册里，但本次错因与登记的签名 {} 不符 ⇒ **按真失败处理**，"
                                    + "请核这是不是新病灶: {}",
                            benign.signatures(), filename, e);
                } else {
                    log.error("❌ 迁移失败（已跳过，继续执行其余迁移）: {}", filename, e);
                }
            }
        }
        reportFailures(failed);
        // 落可观测状态（issue #4517）—— 供 /actuator/health 的 details 暴露
        long benignCount = failed.stream().filter(MigrationRunner::isBenign).count();
        this.lastFailed = failed.stream().map(Failure::filename).toList();
        this.lastFailedBenignCount = (int) benignCount;
        this.lastFailedRealCount = failed.size() - (int) benignCount;
        this.lastSkippedByLedger = applied.size();
    }

    /**
     * **基线**：唯一的那份建库脚本（issue #5243）。语义四条，缺一即事故：
     *
     * <ol>
     *   <li><b>台账已有该键 ⇒ 整段跳过</b>（幂等；普通迁移扫描照跑）。</li>
     *   <li><b>台账无该键 ∧ 库非空 ⇒ 只记账、不执行</b>（存量库绝不重放建库脚本）。</li>
     *   <li><b>台账无该键 ∧ 库为空 ⇒ 执行后记账</b>（空库 = 建出终态的唯一路径；
     *       迁移链已归档，空库没有第二条路）。</li>
     *   <li><b>失败分级与既有语义逐字相同</b>：连接类 ⇒ 抛给外层退避重试 / 重试耗尽 fail-closed；
     *       内容类 ⇒ 记入失败清单 + ERROR，**不拒绝启动**（同 #3615/#3270 的刻意权衡）。</li>
     * </ol>
     *
     * <p>执行形态与迁移逐一相同：整份文件文本一次 {@code jdbc.execute(...)}
     * （PG 扩展查询下多语句走单一隐式事务，任一句失败即整份回滚）。</p>
     */
    private void applyBaseline(JdbcTemplate jdbc, List<Failure> failed) throws Exception {
        Resource resource = resolver.getResource(initScriptLocation);
        String key = resource.getFilename() == null ? initScriptLocation : resource.getFilename();

        if (!resource.exists()) {
            failed.add(new Failure(key, new IllegalStateException(
                    "基线初始化脚本不存在: " + initScriptLocation)));
            log.error("❌ 基线初始化脚本不存在: {}（未执行任何建库 SQL —— 空库上 schema 会缺失；"
                    + "未来增量迁移照常扫描）", initScriptLocation);
            return;
        }

        if (getAppliedMigrations(jdbc).contains(key)) {
            log.info("⏭️ 跳过基线 {}：台账已有该键（幂等）", key);
            return;
        }

        if (databaseHasSchema(jdbc)) {
            // 🔴 关键分支：存量库上**只记账、绝不执行** —— 重放建库脚本会往活库灌终态种子。
            recordMigration(jdbc, key);
            log.info("⏭️ 跳过基线 {}：库中已存在哨兵表 {} ⇒ 判为存量库，只记账不执行",
                    key, BASELINE_PROBE_TABLE);
            return;
        }

        log.info("🔄 执行基线 {}（空库 ⇒ 建出终态）", key);
        try {
            String sql = readResource(resource);
            jdbc.execute(sql);
            recordMigration(jdbc, key);
            log.info("✅ 基线完成: {}", key);
        } catch (Exception e) {
            if (isConnectionFailure(e)) {
                throw e;  // 连接类不是「这份脚本坏」⇒ 交给外层退避重试 / fail-closed（#4241）
            }
            failed.add(new Failure(key, e));
            log.error("❌ 基线失败（空库上建库未成功，schema 可能缺失）: {}", key, e);
        }
    }

    /**
     * 库里是否已经有 schema（哨兵表 {@link #BASELINE_PROBE_TABLE} 是否存在）。
     *
     * <p>用 `information_schema` 而非 `to_regclass`：后者的可见性受 `search_path` 影响，
     * 判「不可见」时返回 null —— 那会让**存量库被误判成空库 ⇒ 重放建库脚本**（危险方向）。
     * `information_schema` 不匹配 search_path 时只会**多**认（判成「有 schema」），
     * 那是安全方向（跳过执行）。</p>
     *
     * <p>⚠️ 本方法**不吞异常**：连不上就该冒泡成连接类失败，走既有 fail-closed 通道。</p>
     */
    private boolean databaseHasSchema(JdbcTemplate jdbc) {
        Boolean present = jdbc.queryForObject(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = ?)",
                Boolean.class, BASELINE_PROBE_TABLE);
        return Boolean.TRUE.equals(present);
    }

    /** 最近一轮**失败**的迁移文件名（含已知存量非幂等那几条）—— 只读、供探针消费。 */
    public List<String> getLastFailedMigrations() {
        return lastFailed;
    }

    /** 最近一轮失败里**真正需要修**的条数（排除 {@code KNOWN_BENIGN_LEGACY}）。 */
    public int getLastFailedRealCount() {
        return lastFailedRealCount;
    }

    /** 最近一轮失败里属**已知存量非幂等**的条数（目标态已达成，重跑亦复现；见 #3714 / #4991）。 */
    public int getLastFailedBenignCount() {
        return lastFailedBenignCount;
    }

    /** 本轮按台账**已应用**（跳过）的迁移数 —— 与失败数一起看才能判断「跑没跑」。 */
    public int getLastSkippedByLedger() {
        return lastSkippedByLedger;
    }

    /**
     * 是否**连接类**失败（而非迁移内容/SQL 有错）—— 决定走「重试 + fail-closed」还是维持 #3615 跳过语义。
     *
     * 判据取**整条 cause 链**（驱动层异常总被 Spring 包一层）：
     *   - `DataAccessResourceFailureException` 家族（实测 `CannotGetJdbcConnectionException`：
     *     「Failed to obtain JDBC Connection」，Spring 对驱动层连不上/认证失败的统一翻法）
     *     与 `SQLTransientConnectionException`（连接池拿不到连接）；
     *   - 网络层：`ConnectException`（连不上）、`SocketTimeoutException`（连接超时）、
     *     `UnknownHostException`（域名解析失败）—— 实测形态
     *     `PSQLException: 尝试连线已失败。` + `Caused by: java.net.ConnectException`。
     *
     * ⚠️ **不得**把 `DataAccessException` 一律算连接类：那会把 #3615 已裁定的内容类失败
     * （SQL 语法/约束）也拿去重试、并最终拒绝启动 —— 一条坏迁移冻结整个 schema，
     * 正是 #3270 的原始病灶。
     */
    static boolean isConnectionFailure(Throwable e) {
        for (Throwable t = e; t != null; t = t.getCause()) {
            if (t instanceof DataAccessResourceFailureException
                    || t instanceof SQLTransientConnectionException
                    || t instanceof ConnectException
                    || t instanceof SocketTimeoutException
                    || t instanceof UnknownHostException) {
                return true;
            }
            if (t.getCause() == t) {
                break;
            }
        }
        return false;
    }

    /** 最内层原因 —— 重试日志用一行说清真因（如「PSQLException: 尝试连线已失败。」）。 */
    private static Throwable rootCause(Throwable e) {
        Throwable t = e;
        while (t.getCause() != null && t.getCause() != t) {
            t = t.getCause();
        }
        return t;
    }

    /**
     * 连接类失败重试耗尽 —— **拒绝以「schema 未知」状态启动**（issue #4241）。
     *
     * 为什么选「抛异常让启动失败」而不是「照常启动 + health 报 DOWN」：编排/部署层只认
     * **启动成功与否**，health 是应用自己报的（实测它谎报过 UP）；runner 抛出的异常由 Spring
     * 记为 `Application run failed` 并原样抛给 main（实测 Spring Boot 3.3.9，**不**再包一层
     * `Failed to execute CommandLineRunner`）⇒ 进程非 0 退出 ⇒ `docker compose up --wait` 直接失败。
     */
    static class MigrationConnectionFailureException extends IllegalStateException {
        MigrationConnectionFailureException(String message, Throwable cause) {
            super(message, cause);
        }
    }

    /**
     * 本次失败的汇总行 —— **真失败与已知存量分开计数、分开级别**（issue #3714）。
     *
     * ⚠️ 为什么必须分开（本仓库核心痛点是「归因层是最大失败模式」）：bootstrap-first 评测栈
     * 上在册的存量迁移**每次起栈必失败**，若一律打 ERROR + 「请立即修复并在修复后重跑」——
     * 那是一句**必然为假**的行动指令（无物可修、重跑必复现）→ 告警疲劳 → 真 schema 不一致
     * 与永久噪音**长得一模一样**，真失败被淹没。
     *
     * ⚠️ 决不静默：未知失败照旧 ERROR + 非零计数 + 行动指令；只有**已诊断的存量**降级。
     */
    private void reportFailures(List<Failure> failed) {
        List<String> benign = failed.stream().filter(MigrationRunner::isBenign)
                .map(Failure::filename).toList();
        List<String> real = failed.stream().filter(f -> !isBenign(f))
                .map(Failure::filename).toList();

        if (!benign.isEmpty()) {
            log.info("ℹ️ 本次有 {} 条迁移失败属**已知存量非幂等**（目标态已达成 —— 由 backend/admin-api/src/main/resources/db/init/schema.sql "
                            + "引导或由登记的补偿迁移补齐；无需修复、重跑亦会复现；见 #3615/#3714 / #4991）：{}",
                    benign.size(), benign);
        }
        if (!real.isEmpty()) {
            log.error("❌ 本次有 {} 条迁移失败，schema 可能与代码不一致（请立即修复并在修复后重跑）：{}",
                    real.size(), real);
        }
    }

    // ── 已知良性存量迁移（单一事实源，与 Python 侧同测；见下）──

    /**
     * 一条**已诊断的存量失败**的完整判据（issue #4991 起）。
     *
     * @param terminalStateBy 目标态**由谁达成**：`schema.sql`（bootstrap 终态）或裸版本号 `V<n>`
     *                        （补偿迁移）。⚠️ **只写裸版本号、绝不写完整文件名** —— Python 侧解析器
     *                        把标记区间内所有 `V{n}__x.sql` 形态的字面量当作**键**，写进字段/理由会让
     *                        键集合虚假膨胀（解析器对此 fail-closed）。
     * @param signatures      **期望错误签名**，形如 `<SQLSTATE>` 或 `<SQLSTATE>:<标识符子串>`；
     *                        **至少一条**（空 = 退化成「只按文件名降级」，护栏②失效）。
     *                        子串一律取**标识符**（约束名 / 列名）—— PG 的文案随 `lc_messages`
     *                        本地化（`已经存在` / `does not exist`），标识符不随语言变。
     * @param reason          人读理由（含 issue 号与证据）。
     */
    record BenignLegacy(String terminalStateBy, List<String> signatures, String reason) {}

    /** 一轮里的一条失败：文件名 + 原始异常（签名判定要用原始异常，不能只留文件名）。 */
    record Failure(String filename, Throwable cause) {}

    /**
     * 已诊断的**历史非幂等 / 已补偿**迁移 → 判据（目标态由谁达成 + 期望错误签名 + 理由）。
     *
     * <p>命中 = **文件名在册 ∧ 失败原因与登记的签名相符**（两条都要，缺一即护栏失效）。命中即降级
     * 为 INFO 并单独计数，**不**触发「请立即修复并在修复后重跑」。</p>
     *
     * <p>为什么这些是良性的（**逐条有据，不是「猜」**）：</p>
     * <ul>
     *   <li>`V37`/`V42`/`V44`（#3615/#3714）：bootstrap-first 库由 `backend/admin-api/src/main/resources/db/init/schema.sql` 建出**终态**，
     *       失败真因是「目标已存在」而非「对象缺失」（`ALTER ... IF EXISTS` 只守卫源对象；
     *       PG 不支持 `CREATE POLICY IF NOT EXISTS`）。</li>
     *   <li>`V74`（#4501）：载体①打在不存在的列上（`processing_info` 在 `order_items`，不在 `orders`）
     *       ⇒ 整份单事务回滚；目标态由**补偿迁移 `V75`** 达成。</li>
     *   <li>`V72`（#4514）：引用不存在的列 `f.sort_order` ⇒ 整份回滚；目标态由**补偿迁移 `V76`** 达成。</li>
     *   <li>`V79`（#4685）：按租户派生块的 `unit_price` 整列 NULL 被推断成 `text` ⇒ 整份回滚
     *       （bootstrap 路径上则是 `production_operations_pkey` 重复 —— `op-v79-01` 在 schema.sql 里
     *       是 `deleted = 1`，部分唯一索引不覆盖它）；目标态由**补偿迁移 `V89`** 达成。</li>
     *   <li>`V40`：`ON CONFLICT (id)` 没覆盖 `roles` 的 `(tenant_id, code)` 唯一键 ⇒ 种子行已存在时报
     *       重复键（bootstrap 路径上它**反而成功**，因 schema.sql 种的是同一批 id）。</li>
     * </ul>
     *
     * <p>⚠️ 为什么**不修**这 4 条（#4991 的用户裁定）：它们都是**已发布**迁移（`V72`/`V74`/`V79` 另被
     * `tests/unit_ci_workflows/migration_fingerprints.json` 逐字节 sha256 冻结），且目标态**已由
     * 补偿迁移达成**；重写 = 走 `/danger-ack rewrite-migration` + 重算账本 + 重跑全链，收益近零、
     * 且与 `V75`/`V76`/`V89` 逻辑重复。</p>
     *
     * <p>⚠️ **单一事实源（#3701 教训：同一判据两份实现 ⇒ 必然漂移）**：本表是唯一权威，
     * Python 侧 `tests/unit_ci_workflows/test_migration_idempotency.py::BENIGN_LEGACY_FAILURES`
     * **只镜像键集合**（内容一律从本文件解析），由该文件的 `TestKnownBenignLegacyRegistry`
     * （L0，秒级零依赖）锁死 —— 多一条 = 真失败被当噪音吞掉；少一条 = 哨兵兜底失效。
     * 两边必须**同步增删**。</p>
     *
     * <p>⚠️ **本集合只能变短**：一旦某条被新迁移补齐 / 存量被裁决修好，两边同时销账。
     * **新增迁移一律不得进本表**（前向防护：新迁移必须自带幂等守卫）。</p>
     *
     * <p>⚠️ 解析契约（勿改形状）：`MIGAO_BENIGN_LEGACY_*` 起止标记之间，每条必须写成
     * `"&lt;文件名&gt;", new BenignLegacy("&lt;目标态由谁达成&gt;", List.of("&lt;签名&gt;"…), "&lt;理由&gt;")`。
     * 该标记在**全文件内必须恰好各出现一次**（本注释不能写出标记原文，否则计数为 2 → 测试 fail-closed 报红）。</p>
     */
    // MIGAO_BENIGN_LEGACY_BEGIN
    static final Map<String, BenignLegacy> KNOWN_BENIGN_LEGACY = Map.ofEntries(
            Map.entry("V37__rename_knowledge_entries_to_cards.sql",
                    new BenignLegacy("schema.sql", List.of("42P07:knowledge_cards"),
                            "表/索引改名目标已存在（ALTER ... IF EXISTS 只守卫源）；终态由 schema.sql 引导达成（见 #3615/#3714）")),
            Map.entry("V42__reconcile_knowledge_table_name.sql",
                    new BenignLegacy("schema.sql", List.of("42P07:idx_knowledge_cards_tenant"),
                            "索引改名目标已存在（干净 bootstrap 顺序下靠 V37 的 DROP TABLE 连带删源索引而侥幸通过）；终态已达成（见 #3615/#3714）")),
            Map.entry("V44__create_daily_briefings.sql",
                    new BenignLegacy("schema.sql", List.of("42710:tenant_isolation_daily_briefings"),
                            "裸 CREATE POLICY，而 schema.sql 已建同名策略 tenant_isolation_daily_briefings（PG 不支持 CREATE POLICY IF NOT EXISTS）；终态已达成（见 #3615/#3714）")),
            Map.entry("V40__seed_default_tenant_and_roles.sql",
                    new BenignLegacy("schema.sql", List.of("23505:roles_tenant_id_code_key"),
                            "ON CONFLICT (id) 没覆盖 roles 的 (tenant_id, code) 唯一键 ⇒ 种子行已存在时报重复键；终态 = tenant 1 + 四岗角色，schema.sql 已种同一批（见 #4991）")),
            Map.entry("V72__switch_routing_model_consumers.sql",
                    new BenignLegacy("V76", List.of("42703:f.sort_order"),
                            "引用不存在的列 f.sort_order（production_option_factors 自 V59 建表起就没有该列）⇒ 整份回滚；目标态由补偿迁移 V76 达成（见 #4514）")),
            Map.entry("V74__backfill_legacy_special_option_names.sql",
                    new BenignLegacy("V75", List.of("42703:processing_info"),
                            "载体①打在不存在的列上（processing_info 在 order_items，不在 orders）⇒ 整份回滚；目标态由补偿迁移 V75 达成（见 #4501）")),
            Map.entry("V79__seed_fabric_route_and_packing_operation.sql",
                    new BenignLegacy("V89", List.of("42804:unit_price", "23505:production_operations_pkey"),
                            "按租户派生块的 unit_price 整列 NULL 被推断成 text ⇒ 整份回滚；bootstrap 路径上是 op-v79-01 的 pkey 重复（schema.sql 里它是软删态，部分唯一索引不覆盖）⇒ 目标态由补偿迁移 V89 达成（见 #4685）")));
    // MIGAO_BENIGN_LEGACY_END

    /** 是否为**已诊断的存量失败**（文件名在册 ∧ 错因与登记签名相符）—— 唯一实现点（#4991 护栏②）。 */
    static boolean isKnownBenignLegacy(String filename, Throwable cause) {
        BenignLegacy benign = filename == null ? null : KNOWN_BENIGN_LEGACY.get(filename);
        return benign != null && matchesAnySignature(cause, benign.signatures());
    }

    /** 一轮失败里该条是否良性（`reportFailures` 与可观测计数共用）。 */
    private static boolean isBenign(Failure failure) {
        return isKnownBenignLegacy(failure.filename(), failure.cause());
    }

    /**
     * 失败原因链是否命中任一条期望签名（issue #4991 护栏②）。
     *
     * <p>判据取**整条 cause 链**（驱动层异常总被 Spring 包一层：`BadSqlGrammarException` →
     * `PSQLException`）：SQLSTATE 收集自链上所有 `SQLException`，文本取链上全部 message 拼接。</p>
     *
     * <p>签名 `"&lt;SQLSTATE&gt;"` 只比 state；`"&lt;SQLSTATE&gt;:&lt;子串&gt;"` 还要文本含该子串。
     * **空签名列表一律不命中**（防「退化成只按文件名降级」）。</p>
     */
    static boolean matchesAnySignature(Throwable cause, List<String> signatures) {
        if (cause == null || signatures == null || signatures.isEmpty()) {
            return false;
        }
        Set<String> states = new HashSet<>();
        StringBuilder text = new StringBuilder();
        for (Throwable t = cause; t != null; t = t.getCause()) {
            if (t instanceof SQLException se && se.getSQLState() != null) {
                states.add(se.getSQLState());
            }
            if (t.getMessage() != null) {
                text.append(t.getMessage()).append('\n');
            }
            if (t.getCause() == t) {
                break;
            }
        }
        String haystack = text.toString();
        for (String signature : signatures) {
            int colon = signature.indexOf(':');
            String state = colon < 0 ? signature : signature.substring(0, colon);
            String needle = colon < 0 ? "" : signature.substring(colon + 1);
            if (states.contains(state) && (needle.isEmpty() || haystack.contains(needle))) {
                return true;
            }
        }
        return false;
    }

    // ── 版本号排序（单一事实源，测试也用同一比较器）──

    /** V{n}__desc.sql 里的 n；无法解析返回 -1（排到最后，不得静默插队到中间） */
    private static final Pattern VERSION_RE = Pattern.compile("^V(\\d+)__");

    /**
     * 迁移执行顺序：按版本号**数值**升序；无法解析版本号的文件**排到最后**
     * （同段按文件名）。
     *
     * ⚠️ 不能直接 `comparingInt(versionOf)`：无法解析时 versionOf 返回 -1，
     * 会让"垃圾文件名"排到**最前面**（首版即此 bug，被单测 `unparsableNamesSortLast` 抓出）。
     * 故把 -1 映射为最大值：不可解析的宁可最后跑，也不许插队到中间。
     */
    public static final Comparator<String> MIGRATION_ORDER =
            Comparator.comparingInt(MigrationRunner::sortKey)
                    .thenComparing(Comparator.nullsLast(String::compareTo));

    /** 排序键：可解析 → 版本号；不可解析 → Integer.MAX_VALUE（排最后） */
    private static int sortKey(String filename) {
        int v = versionOf(filename);
        return v < 0 ? Integer.MAX_VALUE : v;
    }

    /** 解析迁移文件名里的版本号；无法解析返回 -1 */
    public static int versionOf(String filename) {
        if (filename == null) {
            return -1;
        }
        Matcher m = VERSION_RE.matcher(filename);
        if (!m.find()) {
            return -1;
        }
        try {
            return Integer.parseInt(m.group(1));
        } catch (NumberFormatException e) {
            return -1;
        }
    }

    /** 按执行顺序排序（测试用；与 run() 使用同一比较器） */
    public static List<String> sortMigrationNames(List<String> names) {
        List<String> copy = new ArrayList<>(names);
        copy.sort(MIGRATION_ORDER);
        return copy;
    }

    /** 列出 classpath 下 db/migration/*.sql 的文件名（测试用） */
    public static List<String> listMigrationNames() {
        try {
            Resource[] resources = new org.springframework.core.io.support.PathMatchingResourcePatternResolver()
                    .getResources("classpath:db/migration/*.sql");
            List<String> names = new ArrayList<>();
            for (Resource r : resources) {
                if (r.getFilename() != null) {
                    names.add(r.getFilename());
                }
            }
            return names;
        } catch (Exception e) {
            throw new IllegalStateException("无法列举迁移文件", e);
        }
    }

    private void ensureHistoryTable(JdbcTemplate jdbc) {
        jdbc.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version VARCHAR(255) PRIMARY KEY,
                applied_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """);
    }

    private List<String> getAppliedMigrations(JdbcTemplate jdbc) {
        try {
            return jdbc.queryForList("SELECT version FROM schema_migrations", String.class);
        } catch (Exception e) {
            return List.of();
        }
    }

    private String readResource(Resource resource) {
        try (BufferedReader reader = new BufferedReader(
                new InputStreamReader(resource.getInputStream(), StandardCharsets.UTF_8))) {
            return reader.lines().collect(Collectors.joining("\n"));
        } catch (Exception e) {
            throw new RuntimeException("无法读取 migration: " + resource.getFilename(), e);
        }
    }

    private void recordMigration(JdbcTemplate jdbc, String filename) {
        jdbc.update("INSERT INTO schema_migrations (version) VALUES (?)", filename);
    }
}
