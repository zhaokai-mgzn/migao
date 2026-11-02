// case_ids: PG-077
package com.migao.admin.controller;

import com.migao.admin.security.RequirePermission;
import com.migao.admin.security.SecurityUser;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;

import java.io.IOException;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 质检记录 Controller 判据（issue #5652 第一刀）—— 端点形状 + 权限面
 * （「无该角色 ⇒ 必须被拒」的机械承载体）。
 *
 * <p>对应用例：<b>PG-077</b>（.github/cases/processing-order.yml）。</p>
 *
 * <p>🔴 <b>为什么必须是这一类判据</b>：用户裁定录入者 = 「B 独立质检员」⇒ 判据不能是
 * 「前端不显示按钮」（那是**假判据**，判据 3 专治这个形态）。真正的判据跑在**服务端**：
 * 端点带不带权限注解、授权是不是只给独立质检员岗位。本类把两侧钉在一起：
 * ① <b>注解面</b>（反射读真注解 —— 摘掉/改码 ⇒ 当场红）；
 * ② <b>授权面</b>（读 {@code rbac/manifest.json} 的 {@code roles.seed} 与
 * {@code RegistrationService} 的岗位种子源码文本 —— 该码只授给 {@code inspector} 这一个岗位码，
 * 换了岗位 / 多授一个 ⇒ 红）。</p>
 *
 * <p><b>边界（照实登记）</b>：本类判「注解面 + 声明面」，**不**起 Spring 安全链做端到端 403
 * （那是 {@code SecurityConfigTest} 那一族的面）；两者合起来才等于「无该角色 ⇒ 被拒」。</p>
 */
@DisplayName("质检记录端点权限面（独立质检员）")
class QualityCheckControllerTest {

    /**
     * 质检录入/读取的权限码 = {@code production:inspect}（**独立**权限码，issue #5652）。
     *
     * <p>🔴 为什么必须是**新码**而不是复用 {@code production:execute}（实测踩过，本判据当场判红）：
     * {@code production:execute} 授给了 5 个岗位（admin · 客服 · 运营 · 销售 · 财务）—— 用户裁定的
     * 录入者是「**独立**质检员」⇒ 复用会把质检录入权顺带发给四个不相干岗位（**放宽**）。
     * 新码只授 {@code inspector}（+ 运行时恒 {@code ["*"]} 的 admin）。</p>
     */
    private static final String CODE = "production:inspect";

    private static final Path MANIFEST = Path.of("..", "..", "rbac", "manifest.json");

    @Test
    @DisplayName("① 质检录入端点必须带 @RequirePermission(\"production:inspect\")（摘掉注解 / 复用生产执行码 ⇒ 当场红）")
    void writeEndpointCarriesTheExecuteCode() throws Exception {
        Method create = QualityCheckController.class
                .getMethod("create", java.util.Map.class);
        RequirePermission annotation = create.getAnnotation(RequirePermission.class);
        assertThat(annotation)
                .as("质检录入端点必须声明权限码 —— 无注解 = 任何登录用户都能录质检判定")
                .isNotNull();
        // 也钉住「不是复用生产执行写码」：改了码 ⇒ 两处逐字比对本判据当场红
        assertThat(annotation.value()).isEqualTo(CODE);
        assertThat(annotation.value()).isNotEqualTo("production:execute");
        assertThat(create.getAnnotation(PostMapping.class)).isNotNull();
    }

    @Test
    @DisplayName("① 质检读面同码（同一岗位可读自己录的记录；不产生第二个权限面）")
    void readEndpointCarriesTheSameCode() throws Exception {
        Method list = QualityCheckController.class
                .getMethod("list", String.class, String.class);
        RequirePermission annotation = list.getAnnotation(RequirePermission.class);
        assertThat(annotation).isNotNull();
        assertThat(annotation.value()).isEqualTo(CODE);
    }

    @Test
    @DisplayName("① 端点挂在 /api/admin/quality-inspections 上（不与报工端点同路径 —— 两刀各自独立）")
    void endpointsLiveOnTheirOwnPath() {
        RequestMapping mapping = QualityCheckController.class.getAnnotation(RequestMapping.class);
        assertThat(mapping).isNotNull();
        assertThat(mapping.value()).containsExactly("/api/admin/quality-inspections");
    }

    @Test
    @DisplayName("② 独立质检员岗位：rbac 声明面上该码**只**授给 inspector（多授一个岗位 ⇒ 红）")
    void onlyTheInspectorRoleHoldsTheCodeOnTheDeclarationFace() throws IOException {
        String manifest = manifest();
        assertThat(manifest).as("权限声明面必须存在（路径漂移 ⇒ 红，不得静默跳过）").isNotBlank();

        // 声明面里**持本码的那个岗位**的码集必须逐值等于 {读码, 本码}（少一个 ⇒ 质检员录不了质检）
        List<String> holders = rolesHoldingCode(manifest, CODE);
        Map<String, List<String>> roles = seedRoles(manifest);
        assertThat(holders).as("持 " + CODE + " 的岗位").hasSize(1);
        assertThat(roles.get(holders.get(0)))
                .as("该岗位的声明码集")
                .containsExactlyInAnyOrder("production:view", CODE);

        // 「独立」的落码含义 = 该码**只**给质检岗位（`admin` 的声明码是 `["*"]` 通配 ⇒ 不计入本读数；
        // 它运行时走 `getUserPermissions` 的短路分支，与「哪些岗位被**显式**授了这个码」不是同一个读数）
        // 🔴 这条断言就是「复用 production:execute 会放宽」的机械证据：该码今天授给 5 个岗位
        // （admin/客服/运营/销售/财务）⇒ 复用会让四个不相干岗位能录质检判定。
        assertThat(holders)
                .as("**显式**持 " + CODE + " 的岗位码（声明面；admin 是 `*` 通配，不在本读数里）")
                .hasSize(1);
    }

    @Test
    @DisplayName("② 岗位种子源码里必须给 inspector 授该码（换岗位 / 漏授 ⇒ 红）")
    void registrationSeedsTheInspectorRoleWithTheCode() throws IOException {
        String src = Files.readString(
                Path.of("src", "main", "java", "com", "migao", "admin", "service", "RegistrationService.java"),
                StandardCharsets.UTF_8);
        // 岗位码字面量取自**声明面**（本文件不写第二份）⇒ 源文本里必须出现同一个码
        String roleCode = rolesHoldingCode(manifest(), CODE).get(0);
        assertThat(src).contains(roleCode);
        assertThat(src).contains("\"production:inspect\"");
        // 岗位**变量**名的形态是角色码的驼峰式（`<role>Role`）—— 逐字符拼出来，避免再写一份字面量
        String roleVar = java.util.Arrays.stream(roleCode.split("_"))
                .reduce("", (acc, part) -> acc.isEmpty()
                        ? part
                        : acc + Character.toUpperCase(part.charAt(0)) + part.substring(1)) + "Role";
        assertThat(src).as("岗位变量名（驼峰式）必须被种子路径真用到").contains(roleVar);
    }

    @Test
    @DisplayName("② 回退 switch 与种子逐值同码（两条口径不得分叉）")
    void roleFallbackMatchesTheSeed() throws IOException {
        String src = Files.readString(
                Path.of("src", "main", "java", "com", "migao", "admin", "service", "RoleService.java"),
                StandardCharsets.UTF_8);
        String roleCode = rolesHoldingCode(manifest(), CODE).get(0);
        assertThat(src).contains("case \"" + roleCode + "\"");
        assertThat(src).contains("production:inspect");
    }

    /**
     * 从声明面（`rbac/manifest.json` 的 `roles.seed`）解析 **岗位码 → 码集**。
     *
     * <p>🔴 <b>为什么必须现取而不是在本文件里写死一张岗位表</b>：写死 = 同一份事实的第二处投影；
     * 而且本仓的「副本登记表」判据（`rbac/sources.json` + 判据 M1）会把测试文件里的岗位码字面量
     * 读成 `role-defaults-seed` 面的一处**副本** ⇒ 未登记即红（实测踩过，2026-10-15）。现取之后
     * 本文件**一个岗位码字面量都没有**，豁免台账**只许缩短**的口径也不必为此放宽。</p>
     */
    /** 声明面文本（`rbac/manifest.json`；测试工作目录 = `backend/admin-api`）。 */
    private static String manifest() {
        try {
            return Files.readString(MANIFEST, StandardCharsets.UTF_8);
        } catch (IOException e) {
            throw new AssertionError("声明面读不到（路径漂移 ⇒ 红，不得静默跳过）: " + MANIFEST, e);
        }
    }

    private static Map<String, List<String>> seedRoles(String manifest) {
        int seed = manifest.indexOf("\"seed\"");
        assertThat(seed).as("声明面里必须有 roles.seed").isGreaterThan(0);
        int open = manifest.indexOf('{', seed);
        Map<String, List<String>> out = new java.util.LinkedHashMap<>();
        int i = open + 1;
        while (i < manifest.length()) {
            while (i < manifest.length() && Character.isWhitespace(manifest.charAt(i))) {
                i++;
            }
            if (i >= manifest.length() || manifest.charAt(i) == '}') {
                break;
            }
            assertThat(manifest.charAt(i)).as("期望岗位键的引号").isEqualTo('"');
            int keyEnd = manifest.indexOf('"', i + 1);
            String role = manifest.substring(i + 1, keyEnd);
            int arrOpen = manifest.indexOf('[', keyEnd);
            int arrClose = manifest.indexOf(']', arrOpen);
            List<String> codes = java.util.Arrays.stream(manifest.substring(arrOpen + 1, arrClose).split(","))
                    .map(x -> x.replace("\"", "").trim())
                    .filter(x -> !x.isEmpty())
                    .toList();
            out.put(role, codes);
            i = arrClose + 1;
            while (i < manifest.length() && (manifest.charAt(i) == ',' || Character.isWhitespace(manifest.charAt(i)))) {
                i++;
            }
        }
        assertThat(out).as("声明面解析不出任何岗位 ⇒ 解析器坏了（fail-closed）").isNotEmpty();
        return out;
    }

    /** 声明面里**显式**持有该码的岗位码（`*` 通配不展开 —— 与「被显式授予」不是同一个读数）。 */
    private static List<String> rolesHoldingCode(String manifest, String code) {
        List<String> holders = new java.util.ArrayList<>();
        seedRoles(manifest).forEach((role, codes) -> {
            if (codes.contains(code)) {
                holders.add(role);
            }
        });
        return holders;
    }

    /**
     * 检验人展示名（真机读数 2026-11-01）：`SecurityUser.displayName` 取的是登录名 = 手机号，
     * 于是工人扫水洗唛看到的「检验人」是 `13900001025` —— 内部登录标识上了车间屏。
     * 口径：有真名用真名；没有就显示「管理员」（不猜是谁，也不把账号印出去）。
     */
    @Test
    @DisplayName("检验人显示名：登录名是手机号 ⇒ 「管理员」；有真名 ⇒ 用真名")
    void inspectorDisplayNameMustNotLeakLoginId() throws Exception {
        Method m = QualityCheckController.class.getDeclaredMethod("inspectorDisplayName", SecurityUser.class);
        m.setAccessible(true);
        assertThat(m.invoke(null, new SecurityUser("u-1", 46L, "13900001025", List.of("inspector"), List.of())))
                .isEqualTo("管理员");
        assertThat(m.invoke(null, new SecurityUser("u-2", 46L, "张质检", List.of("inspector"), List.of())))
                .isEqualTo("张质检");
        assertThat(m.invoke(null, new SecurityUser("u-3", 46L, " ", List.of("inspector"), List.of())))
                .isEqualTo("管理员");
    }
}
