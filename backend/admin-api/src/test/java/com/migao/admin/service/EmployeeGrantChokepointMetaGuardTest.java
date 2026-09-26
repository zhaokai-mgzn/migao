// case_ids: HR-002, HR-004, DF-007
package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
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
 * 🧱 <b>类级元守卫（issue #4104）：「员工管理的授权写面」不得出现绕过 ⊆ 门禁的第二个入口</b>。
 *
 * <h2>为什么需要它（只修一处 = 没修）</h2>
 * 实例判据（{@code EmployeePermissionGrantGateTest}）只保证 {@code createUser} / {@code updateUser}
 * <b>这两个入口</b>拒绝越权授予。下一个人在同一条链路里新加一个「直接写 {@code users.role} /
 * {@code users.permissions}」的公开方法（或把某处的门禁调用删掉）照样没人拦 ——
 * 这正是 issue #4104 第 2 节的形态：**校验存在，但不在所有写面上**。
 *
 * <h2>判据（每条都会红）</h2>
 * <ol>
 *   <li><b>授权写面普查（未登记即红）</b>：{@code UserService} 里**公开**且带 {@code permissions}
 *       参数的方法名集合，必须**恰好等于**台账 {@link #GRANT_WRITE_SURFACE}
 *       （新增写面 ⇒ 红；台账里留了已删除的名字 ⇒ 也红）。普查为空时**先红**（非空跑自证：
 *       参数被改名 ⇒ 不是静默通过，而是"扫描器失明"当场暴露）。</li>
 *   <li><b>门禁调用点数 = 现取台账</b>：源码里以 ⊆ 门禁调用**开头**的行数必须等于
 *       {@link #GUARD_CALL_SITES} —— 少了 ⇒ 某个写面丢了门禁；多了 ⇒ 新增写面，必须在同一 diff
 *       显式抬高本常量并说明理由（评审可见）。</li>
 *   <li><b>每个写面至少有一个重载体内调用门禁</b>（委派型重载由被委派者兜住 —— 但必须有兜住的那一个）。</li>
 *   <li><b>写授权字段的每一处都落在有门禁的方法体内</b>：源码里所有 {@code setRole(} /
 *       {@code .role(} / {@code setPermissions(} / {@code .permissions(} 都必须出现在某个
 *       带 ⊆ 门禁的方法体内（新增一处裸写 ⇒ 红）。</li>
 *   <li><b>扫描器自证（红证）</b>：用**合成语料**证明扫描器有判别力 —— 未加固的写面会被判
 *       "没有门禁"，加固过的会被判"有门禁"。没有这条，「判据恒绿」与「判据有效」在输出上分不开。</li>
 *   <li><b>门禁体内真的有 ⊆ 断言</b>：判据 2/3/4 只管「写面调了门禁」，管不了「门禁被掏空」
 *       （把 {@code assertGrantable} 那一行删掉、只留保留角色/通配码两条）⇒ 本判据钉住
 *       门禁体内那一次**真正的**委托调用（删掉 ⇒ 红；变成两处 ⇒ 也要显式抬台账）。</li>
 *   <li><b>测试侧替身纪律</b>：以 {@code UserService} 为被测对象的测试类必须声明门禁替身 ——
 *       否则 {@code @InjectMocks} 会把新依赖注成 {@code null}，运行时 **NPE 级联**
 *       （2026-09-26 实测：漏声明 ⇒ 全模块 18 条红，且红的样子像"测试坏了"而不是"漏了替身"）。</li>
 *   <li><b>目标侧写面普查 + 台账</b>（issue #4104 的另一半）：针对**既有账号**的写方法
 *       （改资料 / 改密 / 重置 / 停用 / 启用 / 删除）每一个都必须过目标侧 ⊆ 门禁，
 *       调用点数与台账**现取**（新增写面必须显式抬高；少了 ⇒ 有写面丢门禁）。</li>
 *   <li><b>角色→码映射只许一份真值</b>：`switch (roleCode)` 式的角色→权限码映射在全仓
 *       `src/main/java` 里只允许存在于 {@code RoleService} —— 第二份必然漂移
 *       （#4104 §4 的 {@code knowledge_editor} 两处不一致即由此而来；本次已删掉
 *       {@code PermissionService.getPermissionsByRole} 这份零调用方的死码）。</li>
 * </ol>
 *
 * <p><b>未固化项（如实登记，不粉饰）</b>：① 射程 = {@code UserService} 这一个文件的公开写面
 * （不做 AST 解析，只认「声明行 + 方法窗口 + 文本标记」这一形态 ⇒ 换措辞绕过扫描器的写法本判据看不见，
 * 真实防线仍是实例判据的行为面）；② {@code RoleService.assignPermissions}（岗位 ↔ 权限码写面）
 * 不在本守卫射程 —— 它由 {@code system:manage} 把守、且属「角色定义」面而非「员工授权」面，
 * 已在 PR 说明中登记为未固化项；③ 「谁能改比自己权限高的账号（重置密码 / 停用 / 删除）」
 * 属**目标侧**护栏，是另一条判据面，本 PR 未实装、已登记。</p>
 */
@DisplayName("类级元守卫（#4104）：员工授权写面的 ⊆ 门禁不得被绕过（未登记即红 + 台账只许显式抬高）")
class EmployeeGrantChokepointMetaGuardTest {

    /** 扫描目标（Surefire 的工作目录 = 模块根 {@code backend/admin-api}）。 */
    private static final String USER_SERVICE_SOURCE = "src/main/java/com/migao/admin/service/UserService.java";

    /** 测试源码根（判据7）。 */
    private static final Path TEST_JAVA_ROOT = Paths.get("src/test/java");

    /** 判据7 的入口特征：被测对象是 {@code UserService} 的测试类。 */
    private static final Pattern INJECTED_USER_SERVICE =
            Pattern.compile("@InjectMocks\\s+private\\s+UserService\\s");

    /** 门禁替身的类型名（判据7：声明了它，{@code @InjectMocks} 才不会注 null）。 */
    private static final String PERMISSION_INTERCEPTOR_TYPE = "PermissionInterceptor";

    /** ⊆ 门禁的调用入口（{@code PermissionInterceptor#assertGrantable} 的服务侧封装）。 */
    private static final String GUARD_CALL = "assertAssignableRoleAndPermissions(";

    /** ⊆ 断言本体（服务侧对 {@code PermissionInterceptor#assertGrantable} 的委托）。 */
    private static final String SUBSET_DELEGATION = "permissionInterceptor.assertGrantable(";

    /** 目标侧 ⊆ 门禁的调用入口（针对**既有账号**的写面；带接收者，故匹配用 contains）。 */
    private static final String TARGET_GUARD_CALL = "permissionInterceptor.assertManagesTarget(";

    /**
     * 目标侧写面台账（**现取**，只许缩短或显式改名）：接受 {@code String userId}
     * **且真的写账号**（{@code updateById} / {@code deleteById}）的公开方法。
     * 当前 6 个 —— 每个都必须过目标侧 ⊆ 门禁（issue #4104 的另一半）。
     */
    private static final Set<String> TARGET_WRITE_SURFACE = Set.of(
            "updateUser", "changePassword", "resetPassword", "deleteUser", "disableUser", "enableUser");

    /** 目标侧 ⊆ 门禁的调用点数（**现取**，只许显式抬高）：当前 6 处（每个写面一处）。 */
    private static final int TARGET_GUARD_CALL_SITES = 6;

    /** 角色 → 权限码映射的**唯一真值**文件（判据9）。 */
    private static final String ROLE_CODE_MAP_SOURCE = "RoleService.java";

    /** 角色→码映射的文本指纹（`switch (roleCode) { case "x" -> ... }`）。 */
    private static final String ROLE_CASE_FINGERPRINT = "case \"operator\" ->";

    /** 主源码根（判据9 普查面）。 */
    private static final Path MAIN_JAVA_ROOT = Paths.get("src/main/java");

    /** 门禁本体（判据10）：两条 ⊆ 断言的实现文件。 */
    private static final String INTERCEPTOR_SOURCE =
            "src/main/java/com/migao/admin/security/PermissionInterceptor.java";

    /**
     * 授权写面台账（**现取**，只许缩短或显式改名）：接受 {@code permissions} 参数的公开方法名。
     * 当前 2 个：{@code createUser} / {@code updateUser}（各自的委派型重载共用同一个名字）。
     */
    private static final Set<String> GRANT_WRITE_SURFACE = Set.of("createUser", "updateUser");

    /**
     * ⊆ 门禁的调用点数（**现取**，只许显式抬高）：当前 2 处 ——
     * {@code createUser}（9 参主体）与 {@code updateUser}（8 参主体）各一处。
     */
    private static final int GUARD_CALL_SITES = 2;

    /** 授权字段的写入形态（{@code users.role} / {@code users.permissions}）。 */
    private static final List<String> AUTHZ_FIELD_WRITES = List.of(
            "setRole(", ".role(", "setPermissions(", ".permissions(");

    /** 方法声明行：4 空格缩进的 {@code public ... name(}（javadoc / 字符串里的同名文本不会命中）。 */
    private static final Pattern METHOD_DECL =
            Pattern.compile("(?m)^ {4}public[ \\t]+[\\w<>\\[\\],. ]+?[ \\t]+(\\w+)[ \\t]*\\(");

    @Test
    @DisplayName("🔴 判据1 授权写面普查：新写面未登记 ⇒ 红；台账留了已删除的名字 ⇒ 也红；普查为空 ⇒ 先红（非空跑自证）")
    void grantWriteSurfaceCensusIsLiveAndExact() {
        Set<String> census = methodWindows(readUserServiceSource()).stream()
                .filter(window -> window.header().contains("permissions"))
                .map(MethodWindow::name)
                .collect(Collectors.toCollection(LinkedHashSet::new));

        assertThat(census)
                .as("扫描器失明自证：若 params 改名/方法被搬走，这里会变空而不是静默通过")
                .isNotEmpty();
        assertThat(census)
                .as("授权写面台账（新增写面必须登记；写面已消失则同 PR 改小台账）")
                .isEqualTo(GRANT_WRITE_SURFACE);
    }

    @Test
    @DisplayName("🔴 判据2 门禁调用点数 = 现取台账（少了 ⇒ 写面丢门禁；多了 ⇒ 新增写面须显式抬台账）")
    void guardCallSitesMatchLedger() {
        long calls = readUserServiceSource().lines()
                .map(String::trim)
                .filter(line -> line.startsWith(GUARD_CALL))
                .count();

        assertThat(calls)
                .as("⊆ 门禁调用点数（台账 GUARD_CALL_SITES=%d；新增授权写面必须在同一 diff 抬高并说明）",
                        GUARD_CALL_SITES)
                .isEqualTo(GUARD_CALL_SITES);
    }

    @Test
    @DisplayName("🔴 判据3 每个授权写面至少要有一个重载体内调用 ⊆ 门禁")
    void everyGrantWriteMethodHasGuardedOverload() {
        List<MethodWindow> windows = methodWindows(readUserServiceSource());

        for (String writeSurface : GRANT_WRITE_SURFACE) {
            long guarded = windows.stream()
                    .filter(window -> window.name().equals(writeSurface))
                    .filter(window -> window.body().contains(GUARD_CALL))
                    .count();
            assertThat(guarded)
                    .as("%s 的某个重载体内必须调用 ⊆ 门禁（委派型重载由被委派者兜住）", writeSurface)
                    .isGreaterThan(0L);
        }
    }

    @Test
    @DisplayName("🔴 判据4 写 users.role / users.permissions 的每一处都必须落在有 ⊆ 门禁的方法体内")
    void everyAuthzFieldWriteIsInsideAGuardedWindow() {
        int checkedWrites = 0;
        for (MethodWindow window : methodWindows(readUserServiceSource())) {
            for (String marker : AUTHZ_FIELD_WRITES) {
                if (window.body().contains(marker)) {
                    checkedWrites++;
                    assertThat(window.body())
                            .as("方法 %s 写了授权字段（命中 %s）却没有 ⊆ 门禁 —— 新增授权写面必须过门禁", window.name(), marker)
                            .contains(GUARD_CALL);
                }
            }
        }
        assertThat(checkedWrites)
                .as("非空跑自证：必须真的扫到写授权字段的语句（标记被改名 ⇒ 这里先红）")
                .isPositive();
    }

    @Test
    @DisplayName("🔴 判据8 目标侧写面普查 + 台账：每个针对既有账号的写方法都必须过 ⊆ 门禁（未登记即红）")
    void targetSideWriteSurfaceIsGated() {
        String source = readUserServiceSource();
        List<MethodWindow> windows = methodWindows(source);

        Set<String> census = windows.stream()
                .filter(window -> window.header().contains("String userId"))
                .filter(window -> window.body().contains("userMapper.updateById(")
                        || window.body().contains("userMapper.deleteById("))
                .map(MethodWindow::name)
                .collect(Collectors.toCollection(LinkedHashSet::new));

        assertThat(census)
                .as("普查非空自证：方法被改名/搬走 ⇒ 这里先红，而不是静默通过")
                .isNotEmpty();
        assertThat(census)
                .as("目标侧写面台账（新增写账号的公开方法必须登记；写面消失则同 PR 改小台账）")
                .isEqualTo(TARGET_WRITE_SURFACE);

        long calls = source.lines()
                .map(String::trim)
                .filter(line -> !line.startsWith("//"))
                .filter(line -> line.contains(TARGET_GUARD_CALL))
                .count();
        assertThat(calls)
                .as("目标侧 ⊆ 门禁调用点数（台账 TARGET_GUARD_CALL_SITES=%d；新增写面须在同一 diff 抬高）",
                        TARGET_GUARD_CALL_SITES)
                .isEqualTo(TARGET_GUARD_CALL_SITES);

        for (String writeSurface : TARGET_WRITE_SURFACE) {
            long guarded = windows.stream()
                    .filter(window -> window.name().equals(writeSurface))
                    .filter(window -> window.body().contains(TARGET_GUARD_CALL))
                    .count();
            assertThat(guarded)
                    .as("%s 的某个重载体内必须调用目标侧 ⊆ 门禁（委派型重载由被委派者兜住）", writeSurface)
                    .isGreaterThan(0L);
        }
    }

    @Test
    @DisplayName("🔴 判据9 角色→权限码映射只许有一份真值（第二份映射 = 漂移源，未登记即红）")
    void roleCodeMappingHasSingleSource() throws IOException {
        Map<String, String> sources = new LinkedHashMap<>();
        try (var paths = Files.walk(MAIN_JAVA_ROOT)) {
            for (Path path : paths.filter(p -> p.toString().endsWith(".java")).toList()) {
                sources.put(path.getFileName().toString(), Files.readString(path));
            }
        }

        assertThat(roleCodeMapHolders(sources))
                .as("非空跑自证：普查面必须真的包含那份映射（`%s`）", ROLE_CODE_MAP_SOURCE)
                .contains(ROLE_CODE_MAP_SOURCE);
        assertThat(roleCodeMapHolders(sources))
                .as("角色→码映射只许一处真值 —— 第二份必然漂移（#4104 §4 的 `knowledge_editor` 两处不一致就是这么来的）")
                .containsExactly(ROLE_CODE_MAP_SOURCE);
    }

    @Test
    @DisplayName("🔴 判据10 门禁本体：两条 ⊆ 断言都必须真的拒绝，且比较只有一份实现（掏空 / 复制 ⇒ 红）")
    void interceptorBodiesRejectAndShareOneComparison() {
        String source = readSource(INTERCEPTOR_SOURCE);

        assertThat(source)
                .as("两条命令式断言都必须在（授予侧 / 目标侧）")
                .contains("public void assertGrantable(")
                .contains("public void assertManagesTarget(");
        assertThat(countLinesContaining(source, "throw BusinessException.permissionEscalationDenied("))
                .as("授予侧门禁必须真的拒绝（注释掉那行 throw ⇒ 红）")
                .isEqualTo(1L);
        assertThat(countLinesContaining(source, "throw BusinessException.permissionOutrankDenied("))
                .as("目标侧门禁必须真的拒绝（注释掉那行 throw ⇒ 红）")
                .isEqualTo(1L);
        assertThat(countLinesContaining(source, "own().contains("))
                .as("比较原语只许一份（`codesBeyondOwn`）—— 第二处内联比较就是**第二份授权实现**（#4148 口径禁止）")
                .isEqualTo(1L);
    }

    @Test
    @DisplayName("🔴 判据9 自证（红证）：合成语料里出现第二份角色→码映射必须被判红")
    void roleCodeMapScannerFlagsSecondMapping() {
        Map<String, String> singleSource = Map.of(ROLE_CODE_MAP_SOURCE, "case \"operator\" -> List.of();");
        Map<String, String> drifted = new LinkedHashMap<>(singleSource);
        drifted.put("PermissionService.java", "switch (roleCode) { case \"operator\" -> List.of(); }");

        assertThat(roleCodeMapHolders(singleSource)).containsExactly(ROLE_CODE_MAP_SOURCE);
        assertThat(roleCodeMapHolders(drifted))
                .as("第二份映射必须被扫出来（否则本判据是空断言）")
                .containsExactly("PermissionService.java", ROLE_CODE_MAP_SOURCE);
    }

    @Test
    @DisplayName("🔴 判据7 以 UserService 为被测对象的测试类必须声明门禁替身（否则 @InjectMocks 注入 null ⇒ NPE 级联）")
    void userServiceTestsDeclarePermissionInterceptorStub() throws IOException {
        List<String> offenders = new ArrayList<>();
        int scanned = 0;
        try (var paths = Files.walk(TEST_JAVA_ROOT)) {
            for (Path path : paths.filter(p -> p.toString().endsWith(".java")).toList()) {
                String text = Files.readString(path);
                if (!INJECTED_USER_SERVICE.matcher(text).find()) {
                    continue;
                }
                scanned++;
                if (!text.contains(PERMISSION_INTERCEPTOR_TYPE)) {
                    offenders.add(path.toString());
                }
            }
        }

        assertThat(scanned)
                .as("非空跑自证：必须真的扫到以 UserService 为被测对象的测试类（扫描面缩小 ⇒ 这里先红）")
                .isPositive();
        assertThat(offenders)
                .as("这些测试类用了 @InjectMocks UserService 却没声明 %s ⇒ 运行时 NPE 级联"
                        + "（补 `@Mock private PermissionInterceptor permissionInterceptor;`）",
                        PERMISSION_INTERCEPTOR_TYPE)
                .isEmpty();
    }

    @Test
    @DisplayName("🔴 判据6 门禁体内必须真的有 ⊆ 断言委托（把门禁掏空 —— 只留保留角色/通配码两条 ⇒ 红）")
    void guardBodyDelegatesToSubsetAssertion() {
        List<String> realDelegations = readUserServiceSource().lines()
                .filter(line -> line.contains(SUBSET_DELEGATION))
                .filter(line -> !line.trim().startsWith("//"))
                .filter(line -> !line.trim().startsWith("*"))
                .toList();

        assertThat(realDelegations)
                .as("门禁方法体内必须有真正的 %s 调用（删掉 ⇒ 红；出现第二处 ⇒ 同 PR 显式抬高本判据）",
                        SUBSET_DELEGATION)
                .hasSize(1);
    }

    @Test
    @DisplayName("🔴 判据5 扫描器自证（红证）：未加固的合成写面必须被判「没有门禁」")
    void scannerFlagsUngatedWriteInSyntheticCorpus() {
        String unguarded = """
                public class FakeService {
                    public User createUser(String role, String permissions) {
                        return null;
                    }
                }
                """;
        String guarded = """
                public class FakeService {
                    public User createUser(String role, String permissions) {
                        assertAssignableRoleAndPermissions(role, permissions, tenantId);
                        return null;
                    }
                }
                """;

        List<MethodWindow> unguardedWindows = methodWindows(unguarded);
        assertThat(unguardedWindows).as("合成语料里的方法必须被扫到（扫描器不是恒空）").hasSize(1);
        assertThat(unguardedWindows.get(0).body())
                .as("未加固 ⇒ 必须判「没有门禁」（否则本判据是空断言）")
                .doesNotContain(GUARD_CALL);
        assertThat(methodWindows(guarded).get(0).body())
                .as("加固过 ⇒ 必须判「有门禁」（否则扫描器恒红，同样是坏判据）")
                .contains(GUARD_CALL);
    }

    // ======================== helpers ========================

    /** 一个「方法窗口」：从 4 空格缩进的 {@code public} 声明行起，到下一个同级声明行（或文件尾）止。 */
    private record MethodWindow(String name, String body) {
        /** 声明头 = 窗口里第一个 {@code {} 之前的部分（参数表在里面）。 */
        String header() {
            int brace = body.indexOf('{');
            return brace < 0 ? body : body.substring(0, brace);
        }
    }

    private static String readUserServiceSource() {
        return readSource(USER_SERVICE_SOURCE);
    }

    /** 读一份仓库相对路径的源码；不存在 ⇒ 红（路径写错不是静默通过）。 */
    private static String readSource(String relativePath) {
        Path path = Paths.get(relativePath);
        assertThat(Files.exists(path))
                .as("扫描目标必须存在（路径写错 ⇒ 不是静默通过）: %s", path.toAbsolutePath())
                .isTrue();
        try {
            return Files.readString(path);
        } catch (IOException e) {
            throw new IllegalStateException("读取 " + path.toAbsolutePath() + " 失败", e);
        }
    }

    /** 含该片段的**非注释**行数（注释里的提及不算实现）。 */
    private static long countLinesContaining(String source, String needle) {
        return source.lines()
                .map(String::trim)
                .filter(line -> !line.startsWith("//") && !line.startsWith("*") && !line.startsWith("/*"))
                .filter(line -> line.contains(needle))
                .count();
    }

    /** 角色→码映射的持有者（判据9）：语料里含映射指纹的文件名（升序）。 */
    private static List<String> roleCodeMapHolders(Map<String, String> sources) {
        return sources.entrySet().stream()
                .filter(entry -> entry.getValue().contains(ROLE_CASE_FINGERPRINT))
                .map(Map.Entry::getKey)
                .sorted()
                .toList();
    }

    private static List<MethodWindow> methodWindows(String source) {
        Matcher matcher = METHOD_DECL.matcher(source);
        List<Integer> starts = new ArrayList<>();
        List<String> names = new ArrayList<>();
        while (matcher.find()) {
            starts.add(matcher.start());
            names.add(matcher.group(1));
        }
        List<MethodWindow> windows = new ArrayList<>();
        for (int i = 0; i < starts.size(); i++) {
            int end = i + 1 < starts.size() ? starts.get(i + 1) : source.length();
            windows.add(new MethodWindow(names.get(i), source.substring(starts.get(i), end)));
        }
        return windows;
    }
}
