package com.migao.admin.service;

import org.junit.jupiter.api.Assertions;
import org.junit.jupiter.api.Assumptions;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

import javax.sql.DataSource;
import java.io.IOException;
import java.net.ServerSocket;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 一次性真 PG 集群（{@code initdb} + {@code pg_ctl}；随机端口、跑完即停、不留残留）。
 *
 * <p>从 #5158 的 {@code BatchConsumptionCuttingPlanRealDbTest} 里提出来**共用**（issue #5167）：
 * 真库判据的 PG 装配再复制一份，两份拷贝就会各自演化（本仓已有三份同源拷贝，第三份起就该收口）。</p>
 *
 * <p><b>真库判据的唯一入口是 {@link #startOrAbort()}</b>（issue #5192）—— 拿不到集群时按环境标记
 * 二选一，把「本机开发友好」与「CI fail-closed」同时满足：未设 {@link #REQUIRE_REALDB_ENV} ⇒
 * {@link Assumptions#abort(String)} 显式跳过（「没跑」必须长得像「没跑」，本机 {@code mvnw test}
 * 不该因为没装 PG 就红）；设了标记 ⇒ {@link Assertions#fail(String)} 判**红** ——
 * 「缺 PG」与「通过」在 CI 结果列上**不许长得一样**（否则判据静默腐烂、且没有任何东西会变红）。</p>
 *
 * <p>为什么 CI 必须 fail-closed：{@code admin-api-test} job **没有 {@code services:}**、也不装 PG
 * （真库判据各自跑一次性集群，要的是**二进制**而非服务），二进制全靠 {@code ubuntu-latest} 镜像
 * **恰好自带**（{@link #BIN_DIRS} 里那几条 Debian 绝对路径）。镜像换代 / 换 runner / 自建 runner
 * ⇒ 命中失败 ⇒ 没有标记时全体真库判据**静默 skip 成绿**。</p>
 */
final class PgCluster {

    private static final List<String> BIN_DIRS = List.of(
            "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/usr/lib/postgresql/16/bin",
            "/usr/lib/postgresql/15/bin", "/usr/lib/postgresql/14/bin");

    /** 缺 PG 二进制时是否**必须判红**（CI 的 {@code admin-api-test} job 注入 {@code =1}）。 */
    static final String REQUIRE_REALDB_ENV = "MIGAO_REQUIRE_REALDB";

    /**
     * PG 二进制搜索路径的**测试专用**覆盖孔（红证 A 需要它，issue #5192）：
     * {@code -Dmigao.pg.bin.dirs=<dir>[:<dir>…]}；<b>生产 / CI 一律不设，默认行为一字不变</b>。
     *
     * <p>设了就**整体替换**候选目录集（**连 {@code PATH} 一起替换** —— 本机 PG 通常就在
     * {@code PATH} 里，只换 {@link #BIN_DIRS} 的话「指向空目录」复现不出「找不到 PG」，红证会是假绿）。
     * 指向空目录即可复现「CI 上命中失败」，从而分别验证 {@link #startOrAbort()} 的两条分支。</p>
     *
     * <p>它**造不出静默绿**：CI 注入了 {@link #REQUIRE_REALDB_ENV}，即便有人把候选集指空，
     * 结果也是**红** —— 这正是 fail-closed 的语义。</p>
     */
    static final String BIN_DIRS_OVERRIDE_PROPERTY = "migao.pg.bin.dirs";

    private final Path dataDir;
    private final Path sockDir;
    private final Path logFile;
    private final int port;
    private final String binDir;

    private PgCluster(String binDir, Path dataDir, Path sockDir, Path logFile, int port) {
        this.binDir = binDir;
        this.dataDir = dataDir;
        this.sockDir = sockDir;
        this.logFile = logFile;
        this.port = port;
    }

    /**
     * **真库判据的唯一入口**（issue #5192）：{@link #start()} 成功 ⇒ 返回集群；拿不到 PG 二进制
     * ⇒ 未设 {@link #REQUIRE_REALDB_ENV} 时 {@link Assumptions#abort(String)}（本机显式跳过），
     * 设了则 {@link Assertions#fail(String)}（CI fail-closed —— 不许 skip 冒充通过）。
     */
    static PgCluster startOrAbort() throws Exception {
        PgCluster cluster = start();
        if (cluster != null) {
            return cluster;
        }
        if (requireRealDb()) {
            // 失败信息里带上候选目录：便于事后判断是「镜像换代」还是「搜索路径变了」。
            Assertions.fail("缺 PG 二进制（initdb/pg_ctl）⇒ 真库判据**无法执行**；"
                    + REQUIRE_REALDB_ENV + " 已设 ⇒ 本判据判 FAIL（不是 skip，issue #5192）。"
                    + "已查找的候选目录 = " + binSearchDirs()
                    + "（CI 面见 .github/workflows/pr-check.yml 的 `Assert PostgreSQL binaries exist` 前置断言）");
        }
        Assumptions.abort("本机没有 PG 二进制（initdb/pg_ctl）⇒ 真库判据**未跑**（不是通过）");
        // Assumptions.abort 必抛 TestAbortedException；此 return 只为满足编译器。
        return null;
    }

    /** 标记语义：设了且不是 {@code 0}/{@code false} ⇒ 要求真库（空值不算设，防 `MIGAO_REQUIRE_REALDB=` 被读成「已要求」）。 */
    private static boolean requireRealDb() {
        String flag = System.getenv(REQUIRE_REALDB_ENV);
        return flag != null && !flag.isBlank()
                && !"0".equals(flag) && !"false".equalsIgnoreCase(flag);
    }

    static PgCluster start() throws Exception {
        String binDir = findBinDir();
        if (binDir == null) {
            return null;
        }
        Path base = Files.createTempDirectory("migao-pg");
        Path dataDir = base.resolve("data");
        Path sockDir = Files.createTempDirectory("pg5158"); // socket 路径有 ~104 字节上限
        Path logFile = base.resolve("pg.log");
        int port = freePort();
        run(binDir, List.of("initdb", "-D", dataDir.toString(), "-U", "postgres", "-A", "trust"));
        run(binDir, List.of("pg_ctl", "-D", dataDir.toString(), "-l", logFile.toString(), "-o",
                "-p " + port + " -c listen_addresses=127.0.0.1 -k " + sockDir, "start"));
        return new PgCluster(binDir, dataDir, sockDir, logFile, port);
    }

    DataSource dataSource() {
        DriverManagerDataSource ds = new DriverManagerDataSource(
                "jdbc:postgresql://127.0.0.1:" + port + "/postgres?stringtype=unspecified",
                "postgres", "");
        ds.setDriverClassName("org.postgresql.Driver");
        return ds;
    }

    void stop() {
        try {
            run(binDir, List.of("pg_ctl", "-D", dataDir.toString(), "-m", "immediate", "stop"));
        } catch (Exception ignored) {
            // 停机失败不影响判据；临时目录随后清理
        }
        deleteRecursively(sockDir);
        deleteRecursively(dataDir.getParent());
    }

    private static String findBinDir() {
        for (String dir : binSearchDirs()) {
            if (dir.isBlank()) {
                continue;
            }
            Path initdb = Paths.get(dir, "initdb");
            Path pgCtl = Paths.get(dir, "pg_ctl");
            if (Files.isExecutable(initdb) && Files.isExecutable(pgCtl)) {
                return dir;
            }
        }
        return null;
    }

    /**
     * 候选目录：默认 = {@link #BIN_DIRS} + {@code PATH}（与提取时**一字不变**）；
     * 设了 {@link #BIN_DIRS_OVERRIDE_PROPERTY}（**测试专用**）⇒ 整体替换、**连 {@code PATH} 一起**。
     */
    private static List<String> binSearchDirs() {
        String override = System.getProperty(BIN_DIRS_OVERRIDE_PROPERTY);
        if (override != null) {
            return Stream.of(override.split(":")).filter(dir -> !dir.isBlank()).toList();
        }
        List<String> candidates = new ArrayList<>(BIN_DIRS);
        String path = System.getenv("PATH");
        if (path != null) {
            candidates.addAll(0, List.of(path.split(":")));
        }
        return candidates;
    }

    private static int freePort() throws IOException {
        try (ServerSocket socket = new ServerSocket(0)) {
            return socket.getLocalPort();
        }
    }

    private static void run(String binDir, List<String> args) throws Exception {
        List<String> command = new ArrayList<>(args);
        command.set(0, Paths.get(binDir, args.get(0)).toString());
        Process process = new ProcessBuilder(command).redirectErrorStream(true).start();
        String output = new String(process.getInputStream().readAllBytes());
        int exit = process.waitFor();
        assertThat(exit).as("`" + String.join(" ", args) + "` 必须成功（PG 临时集群）：\n" + output)
                .isZero();
    }

    private static void deleteRecursively(Path dir) {
        if (dir == null || !Files.exists(dir)) {
            return;
        }
        try (Stream<Path> walk = Files.walk(dir)) {
            walk.sorted(Comparator.reverseOrder()).forEach(p -> {
                try {
                    Files.deleteIfExists(p);
                } catch (IOException ignored) {
                    // 尽力而为
                }
            });
        } catch (IOException ignored) {
            // 尽力而为
        }
    }
}
