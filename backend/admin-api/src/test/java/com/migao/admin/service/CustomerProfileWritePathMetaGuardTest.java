// case_ids: OR-045
package com.migao.admin.service;

import com.migao.admin.entity.CustomerProfile;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import java.io.IOException;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Set;
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

    // ==================== issue #7711：同一人双档案（身份收敛）====================

    @Test
    @DisplayName("🔴 登录建档必须把 users.phone 一并传下去（只凭 openid 认人 ⇒ 代录下单那条永远认不回）")
    void loginProfileCreationCarriesPhone() throws IOException {
        Path auth = MAIN_JAVA.resolve("com/migao/admin/service/AuthService.java");
        String code = stripComments(Files.readString(auth, StandardCharsets.UTF_8));
        List<String> offenders = new ArrayList<>();
        int calls = 0;
        int index = 0;
        while ((index = code.indexOf("createFromSession(", index)) >= 0) {
            int open = code.indexOf('(', index);
            List<String> args = callArguments(code, open);
            calls++;
            if (args.size() != 5 || args.get(4).isBlank() || "null".equals(args.get(4))) {
                offenders.add("createFromSession(" + String.join(", ", args) + ")");
            }
            index = open + 1;
        }
        assertThat(calls).as("扫描没命中任何调用点 ⇒ 本判据空转（判红）").isPositive();
        assertThat(offenders).as("登录建档必须带手机号（users.phone），只凭 openid 会给同一个人建第二条档案：%s",
                offenders).isEmpty();
    }

    @Test
    @DisplayName("🔴 建档只能经过身份收敛服务（自行调 Writer 的 ensureBy* ⇒ 双档案回来）")
    void profileCreationGoesThroughIdentityConvergence() throws IOException {
        Set<String> allowed = Set.of(
                "CustomerProfileWriter.java",      // 写面本体
                "CustomerProfileIdentityService.java", // 唯一收敛实现点
                "CustomerService.java");           // 手工建档（同手机号 422 语义）走 Writer
        List<String> offenders = new ArrayList<>();
        try (Stream<Path> files = Files.walk(MAIN_JAVA)) {
            for (Path p : files.filter(p -> p.toString().endsWith(".java")).toList()) {
                if (allowed.contains(p.getFileName().toString())) {
                    continue;
                }
                String code = stripComments(Files.readString(p, StandardCharsets.UTF_8));
                if (code.contains("CustomerProfileWriter.ensureByPhone(")
                        || code.contains("CustomerProfileWriter.ensureByOpenid(")) {
                    offenders.add(p.getFileName().toString());
                }
            }
        }
        assertThat(offenders).as("这些文件绕过了身份收敛服务（issue #7711）：%s", offenders).isEmpty();
    }

    @Test
    @DisplayName("🔴 档案写面必须跑独立事务（否则「失败不影响建单/登录」是假护栏）")
    void profileWritesRunInTheirOwnTransaction() throws Exception {
        Method ensure = CustomerProfileIdentityService.class.getMethod("ensure",
                Long.class, String.class, String.class,
                CustomerProfileIdentityService.ProfileSeed.class, boolean.class);
        Method fill = CustomerProfileIdentityService.class.getMethod("fillOrderContact",
                CustomerProfile.class, Long.class, String.class, String.class,
                String.class, String.class, String.class);
        for (Method method : List.of(ensure, fill)) {
            Transactional tx = method.getAnnotation(Transactional.class);
            assertThat(tx).as("%s 必须带 @Transactional", method.getName()).isNotNull();
            assertThat(tx.propagation())
                    .as("%s 必须是 REQUIRES_NEW —— 参加调用方事务时，异常会把外层标 rollback-only ⇒ "
                            + "「建档失败不影响建单」变成「建单整单失败」", method.getName())
                    .isEqualTo(Propagation.REQUIRES_NEW);
        }
        // 编排入口自己也不许开事务（开了就仍会毒化外层）
        for (String name : List.of("createFromOrder", "createFromSession", "convergeIdentity")) {
            boolean hasTx = Arrays.stream(CustomerService.class.getDeclaredMethods())
                    .filter(m -> m.getName().equals(name))
                    .anyMatch(m -> m.getAnnotation(Transactional.class) != null);
            assertThat(hasTx).as("CustomerService#%s 不得带 @Transactional（写在下层独立事务里）", name).isFalse();
        }
    }

    /** 剥注释：注释掉的调用不得被当成真实调用点（否则判据永远不会红）。 */
    private static String stripComments(String src) {
        return src.replaceAll("(?s)/\\*.*?\\*/", "").replaceAll("(?<!:)//[^\n]*", "");
    }

    /** 取调用括号内的顶层实参（逗号按括号深度切分；不依赖格式化换行）。 */
    private static List<String> callArguments(String code, int openParen) {
        List<String> args = new ArrayList<>();
        StringBuilder current = new StringBuilder();
        int depth = 0;
        for (int i = openParen; i < code.length(); i++) {
            char c = code.charAt(i);
            if (c == '(') {
                depth++;
                if (depth == 1) {
                    continue;
                }
            } else if (c == ')') {
                depth--;
                if (depth == 0) {
                    args.add(current.toString().trim());
                    return args;
                }
            } else if (c == ',' && depth == 1) {
                args.add(current.toString().trim());
                current.setLength(0);
                continue;
            }
            if (depth >= 1) {
                current.append(c);
            }
        }
        return args;
    }
}
