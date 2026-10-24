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
 * 类级元守卫（issue #7256，铁律 8）：`user_roles` 的写面**只许**经由 {@link UserRoleWriter}。
 *
 * <p>为什么需要它：实例判据证明"当前这两个调用方"是对的；但只要有人再写一处
 * 「{@code selectOne} 判重 + 裸 {@code insert}」（本单修之前就是这个形状），
 * 全表唯一键 × 逻辑删除那个坑会**原样回来**，而它的症状是 500 —— 单元测试不会替你抓到。</p>
 *
 * <p>判据：生产源码里除 {@link UserRoleWriter} 与 mapper 自身外，**不得**出现
 * {@code userRoleMapper.insert(} / {@code userRoleMapper.insertIfAbsent(} /
 * {@code userRoleMapper.reviveSoftDeleted(}。新增写面要让判据红 —— 这是设计目的，不是障碍。</p>
 */
@DisplayName("7256 类级守卫：user_roles 写面必须走单一实现点")
class UserRoleWritePathMetaGuardTest {

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
    @DisplayName("🔴 只有 UserRoleWriter 允许直接调 user_roles 的写方法")
    void onlyWriterTouchesUserRoleWrites() throws IOException {
        List<String> offenders = new ArrayList<>();
        try (Stream<Path> files = Files.walk(MAIN_JAVA)) {
            for (Path p : files.filter(p -> p.toString().endsWith(".java")).toList()) {
                String name = p.getFileName().toString();
                if (name.equals("UserRoleWriter.java") || name.equals("UserRoleMapper.java")) {
                    continue;
                }
                String code = Files.readString(p, StandardCharsets.UTF_8);
                if (code.contains("userRoleMapper.insert(")
                        || code.contains("userRoleMapper.insertIfAbsent(")
                        || code.contains("userRoleMapper.reviveSoftDeleted(")) {
                    offenders.add(p.getFileName().toString());
                }
            }
        }
        assertThat(offenders)
                .as("这些文件绕过了 UserRoleWriter（写面必须单一实现点）：%s", offenders)
                .isEmpty();
    }

    @Test
    @DisplayName("🔴 写面里不得再用「selectOne 判重 + 裸 insert」的读改写形态")
    void noReadModifyWriteOnUserRoles() throws IOException {
        String writer = Files.readString(
                MAIN_JAVA.resolve("com/migao/admin/service/UserRoleWriter.java"), StandardCharsets.UTF_8);
        assertThat(writer).as("写面必须靠条件写（复活/ON CONFLICT），不靠「先查后插」")
                .doesNotContain("selectOne(");
        assertThat(writer).as("写面必须调用条件插入 insertIfAbsent").contains("insertIfAbsent(");
        assertThat(writer).as("写面必须先尝试复活软删行").contains("reviveSoftDeleted(");
    }
}
