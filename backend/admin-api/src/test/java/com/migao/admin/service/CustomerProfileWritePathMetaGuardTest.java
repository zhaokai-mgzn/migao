// case_ids: OR-045
package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 类级元守卫（issue #7257，铁律 8）：`customer_profiles` 的**建行**写面只许经由 {@link CustomerProfileWriter}，
 * 且读侧不得再用 {@code selectOne}（历史重复行会抛 {@code TooManyResultsException} ⇒ 500）。
 *
 * <p>为什么要它：实例判据证明"当前三处"是对的；只要有人再写一处「selectOne 判空 + insert」，
 * 静默双档案会原样回来，而它的症状是**涉钱口径读不准**（不是 500，没有便宜的红）。</p>
 */
@DisplayName("7257 类级守卫：客户档案建行写面必须走单一实现点 + 读侧不用 selectOne")
class CustomerProfileWritePathMetaGuardTest {

    private static final Path MAIN_JAVA = moduleRoot().resolve("src/main/java");

    private static Path moduleRoot() {
        Path cwd = Paths.get("").toAbsolutePath();
        for (Path candidate : new Path[]{cwd, cwd.resolve("backend/admin-api"), cwd.getParent()}) {
            if (candidate != null && Files.exists(candidate.resolve("src/main/java/com/migao/admin"))) {
                return candidate;
            }
        }
        return cwd;
    }

    @Test
    @DisplayName("🔴 只有 CustomerProfileWriter 允许调 customer_profiles 的建行方法")
    void onlyWriterTouchesProfileInserts() throws IOException {
        List<String> offenders = new ArrayList<>();
        try (Stream<Path> files = Files.walk(MAIN_JAVA)) {
            for (Path p : files.filter(p -> p.toString().endsWith(".java")).toList()) {
                String name = p.getFileName().toString();
                if (name.equals("CustomerProfileWriter.java") || name.equals("CustomerProfileMapper.java")) {
                    continue;
                }
                String code = Files.readString(p, StandardCharsets.UTF_8);
                if (code.contains("customerProfileMapper.insert(")
                        || code.contains("customerProfileMapper.insertIgnoreByPhone(")
                        || code.contains("customerProfileMapper.insertIgnoreByOpenid(")) {
                    offenders.add(name);
                }
            }
        }
        assertThat(offenders).as("这些文件绕过了 CustomerProfileWriter：%s", offenders).isEmpty();
    }

    @Test
    @DisplayName("🔴 读侧不得用 selectOne（历史重复行会让它抛 TooManyResultsException）")
    void customerProfileReadsDoNotUseSelectOne() throws IOException {
        List<String> offenders = new ArrayList<>();
        try (Stream<Path> files = Files.walk(MAIN_JAVA)) {
            for (Path p : files.filter(p -> p.toString().endsWith(".java")).toList()) {
                String code = Files.readString(p, StandardCharsets.UTF_8);
                for (String line : code.split("\n")) {
                    if (line.contains("customerProfileMapper.selectOne(")) {
                        offenders.add(p.getFileName().toString());
                        break;
                    }
                }
            }
        }
        assertThat(offenders).as("这些文件仍在用 selectOne 读客户档案：%s（改用 findFirstBy*/selectList）", offenders).isEmpty();
    }
}
