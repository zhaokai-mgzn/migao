package com.migao.admin.service;

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
 * 真库判据的 PG 装配再复制一份，两份拷贝就会各自演化（本仓已有三份同源拷贝，第三份起就该收口）。
 * 本机没有 PG 二进制 ⇒ {@link #start()} 返回 {@code null}，由调用方 {@code Assumptions.abort}
 * 显式跳过（「没跑」必须长得像「没跑」，不是通过）。</p>
 */
    // ────────────────────────────────────────────── 一次性 PG 集群

    /** 一次性 PG 集群（{@code initdb} + {@code pg_ctl}；随机端口、跑完即停、不留残留）。 */
final class PgCluster {

    private static final List<String> BIN_DIRS = List.of(
            "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/usr/lib/postgresql/16/bin",
            "/usr/lib/postgresql/15/bin", "/usr/lib/postgresql/14/bin");

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
        List<String> candidates = new ArrayList<>(BIN_DIRS);
        String path = System.getenv("PATH");
        if (path != null) {
            candidates.addAll(0, List.of(path.split(":")));
        }
        for (String dir : candidates) {
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
