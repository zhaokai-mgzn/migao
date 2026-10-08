// case_ids: API-023
package com.migao.admin.service;

import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.Role;
import com.migao.admin.entity.User;
import com.migao.admin.entity.UserRole;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.RoleMapper;
import com.migao.admin.mapper.UserMapper;
import com.migao.admin.mapper.UserRoleMapper;
import com.migao.admin.security.PermissionInterceptor;
import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.io.File;
import java.io.IOException;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
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

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 建号缺省角色的 <b>fail-closed</b>（issue #5987）：实例判据 + 类级元守卫。
 *
 * <h2>为什么需要类级元守卫（只修一处 = 没修）</h2>
 * issue #5987 的病是「<b>两处</b> fail-open 默认」：控制器 {@code String role = "operator"} 与
 * 服务实体构建处的 {@code .role(role != null ? role : "operator")}。只堵一处 ⇒ 另一处照样把
 * 「没传岗位」静默变成运营级 26 码（含 {@code order:create} / {@code inbound:create} /
 * {@code finance:create} / {@code order:refund}）。⇒ 必须让「把缺省做成有写权限的角色」这种形态
 * <b>未登记即红</b>：本类扫描 {@code src/main/java} 里所有 {@code .role(<字面量>)} /
 * {@code .role(x != null ? x : "字面量")} 的赋值点，与台账 {@link #ROLE_LITERAL_LEDGER} 双向相等。
 *
 * <h2>判据（每条都会红）</h2>
 * <ol>
 *   <li><b>服务侧 fail-closed（实例）</b>：{@code role} 为空/空白 ⇒ 400 {@code BusinessException}，
 *       且 {@code userMapper.insert} <b>一次都没发生</b>（"返回了错误" ≠ "没写进去"）。</li>
 *   <li><b>授权语义必须由调用方声明（实例对照）</b>：显式 {@code role=operator} ⇒ 成功落库，
 *       写入行的 role/position 逐字等于调用方声明值（证明判据 1 不是「整条链路坏了」）。</li>
 *   <li><b>台账：「缺省角色字面量」赋值点双向相等，未登记即红</b>：扫描结果 ⇄
 *       {@link #ROLE_LITERAL_LEDGER}（台账有而扫描没有 = 陈旧条目 ⇒ 红；扫描有而台账没有 =
 *       新增授权/缺省字面量 ⇒ 红）。台账<b>只许缩短</b>：条数必须等于常量 {@link #LEDGER_SIZE}
 *       （现取，新增须在同一 diff 显式抬高并说明理由）。</li>
 *   <li><b>建号缺省位不得出现写权限默认（类级语义判据）</b>：两个建号入口源码里，
 *       含 {@code .position(...)} 的语句不得出现写权限角色字面量。</li>
 *   <li><b>扫描器自证（红证）</b>：用合成语料证明判别力 —— 旧形态 {@code .role(x != null ? x : "operator")}
 *       必须被判为缺省、{@code .role("super_admin")} 必须被判为授权字面量、
 *       {@code .role(user.getRole())} 与 {@code .role(anyToString(map.get("role")))} 必须<b>不</b>被判
 *       （否则全仓 {@code .role(} 都是命中，判据退化成噪音）。</li>
 * </ol>
 *
 * <p><b>未固化项（如实登记，不粉饰）</b>：① 扫描形态 = 「声明行 + 单行/跨行 {@code .role(...)} 赋值」，
 * 不做 AST ⇒ 绕开形态的写法（拆成 {@code String r = ...; builder.role(r);}）本守卫看不见，
 * 真实防线仍是判据 1 的行为面；② 台账里的 {@code AuthService} 条目是<b>在建用户的上下文里显式赋角色</b>
 * （注册超管 / C 端客户），不是「缺省兜底」，登记只为让新增字面量必须被人看见；
 * ③ 判据 4 只扫描两个建号入口文件，不覆盖别的授权写面（那是 #4104 元守卫的射程）。</p>
 */
@DisplayName("类级元守卫（#5987）：建号缺省角色必须 fail-closed，缺省字面量未登记即红")
class EmployeeGrantDefaultRoleMetaGuardTest {

    /** 扫描目标（Surefire 的工作目录 = 模块根 {@code backend/admin-api}）。 */
    private static final String MAIN_JAVA_ROOT = "src/main/java";

    /** 两个建号入口源码（判据 4）。 */
    private static final String CONTROLLER_SOURCE =
            "src/main/java/com/migao/admin/controller/AdminUserController.java";
    private static final String SERVICE_SOURCE =
            "src/main/java/com/migao/admin/service/UserService.java";

    /** 缺省兜底形态：语句**开头**即 `.role(<标识符> != null ? <标识符> : "<字面量>")`（可跨行 / 多空格）。 */
    private static final Pattern NULL_FALLBACK = Pattern.compile(
            "^\\.role\\(\\s*([A-Za-z_$][\\w$]*)\\s*!=\\s*null\\s*\\?\\s*\\1\\s*:\\s*\"([^\"]*)\"");

    /** 授权字面量形态：语句**开头**即 `.role("<字面量>"`（取值形态 `.role(user.getRole())` 不得命中）。 */
    private static final Pattern LITERAL_ARG = Pattern.compile("^\\.role\\(\\s*\"[^\"]*\"");

    /** 含写权限语义的角色名（不得成为任何「建号缺省」的默认值）。 */
    private static final Pattern WRITE_CAPABLE_ROLE = Pattern.compile(
            "\"(admin|super_admin|operator|product_manager|finance|sales|manager)\"");

    /**
     * 台账：「{@code .role(<字面量>)} / {@code .role(x != null ? x : "字面量")}」赋值点
     * （仓库相对路径::表达式）。<b>只许缩短</b>（条数 = {@link #LEDGER_SIZE}，现取比较）；
     * 新增条目 = 新增授权/缺省字面量，必须在同一 diff 显式抬高本常量并说明理由（评审可见）。
     */
    private static final Set<String> ROLE_LITERAL_LEDGER = Set.of(
            // 创建平台超管（短信身份，tenantId = -1）时显式赋角色
            "backend/admin-api/src/main/java/com/migao/admin/service/AuthService.java::"
                    + ".role(\"super_admin\") .identityType(\"sms\") .roles(roles) .tenantId(-1L) "
                    + ".tenantName(\"观星台平台管理\") .build()) .accessToken(accessToken) .refreshToken(null) "
                    + ".expiresIn(jwtTokenProvider.getAccessTokenExpiration()) .build()",
            // C 端客户账号（注册即 customer）
            "backend/admin-api/src/main/java/com/migao/admin/service/AuthService.java::"
                    + ".role(\"customer\") .status(\"active\") .build()",
            // 创建平台超管（账号密码身份，tenantId = -1）时显式赋角色
            "backend/admin-api/src/main/java/com/migao/admin/service/AuthService.java::"
                    + ".role(\"super_admin\") .identityType(\"account\") .roles(roles) .tenantId(-1L) "
                    + ".tenantName(\"观星台平台管理\") .build()) .accessToken(newAccessToken) "
                    + ".refreshToken(newRefreshToken) .expiresIn(jwtTokenProvider.getAccessTokenExpiration()) .build()");

    /** 台账条数（现取，禁止「新增即静默」）。 */
    private static final int LEDGER_SIZE = 3;

    private UserMapper userMapper;
    private RoleMapper roleMapper;
    private UserRoleMapper userRoleMapper;
    private UserService userService;

    @BeforeEach
    void setUp() {
        // 初始化 MyBatis-Plus lambda 缓存（LambdaQueryWrapper 解析 User::getXxx 需要 TableInfo）
        MybatisConfiguration configuration = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(configuration, "");
        TableInfoHelper.initTableInfo(assistant, User.class);
        TableInfoHelper.initTableInfo(assistant, Role.class);
        TableInfoHelper.initTableInfo(assistant, UserRole.class);

        userMapper = mock(UserMapper.class);
        roleMapper = mock(RoleMapper.class);
        userRoleMapper = mock(UserRoleMapper.class);
        RoleService gateRoleService = mock(RoleService.class);
        when(gateRoleService.getUserPermissions(any())).thenReturn(List.of());
        userService = new UserService(userMapper, roleMapper, userRoleMapper,
                new PermissionInterceptor(gateRoleService));
        TenantContext.setTenantId(1L);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ======================== 实例判据：服务侧 fail-closed ========================

    @Test
    @DisplayName("🔴 role 为空/空白 ⇒ 400 且 userMapper.insert 一次都没发生（修前会落库 role=operator）")
    void blankRoleIsRejectedAndNothingPersisted() {
        assertThatThrownBy(() -> userService.createUser("13800138000", "Init1234", "没角色", null, "运营",
                null, 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("岗位");

        assertThatThrownBy(() -> userService.createUser("13800138001", "Init1234", "空角色", "   ", "运营",
                null, 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("岗位");

        // 「返回了 400」≠「没写进去」：两种形态都必须一行都不落库
        verify(userMapper, never()).insert(any(User.class));
    }

    @Test
    @DisplayName("对照：显式 role=operator ⇒ 成功落库，写入行的 role/position 逐字等于调用方声明")
    void explicitRoleStillPersists() {
        when(userMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(null);
        when(userMapper.insert(any(User.class))).thenAnswer(invocation -> {
            User u = invocation.getArgument(0);
            u.setId("user-op");
            return 1;
        });

        User created = userService.createUser("13800138002", "Init1234", "运营小王", "operator", null, null, 1L);

        assertThat(created.getRole()).isEqualTo("operator");
        // position 未传 ⇒ 回退角色名（既有契约 employee-role.position-fallback）
        assertThat(created.getPosition()).isEqualTo("operator");

        ArgumentCaptor<User> captor = ArgumentCaptor.forClass(User.class);
        verify(userMapper).insert(captor.capture());
        assertThat(captor.getValue().getRole()).isEqualTo("operator");
        assertThat(captor.getValue().getPosition()).isEqualTo("operator");
    }

    // ======================== 类级元守卫：缺省字面量台账 ========================

    @Test
    @DisplayName("台账：缺省/授权角色字面量赋值点 ⇄ 扫描结果双向相等（未登记即红，台账只许缩短）")
    void roleLiteralSitesMatchLedger() throws IOException {
        Map<String, String> sites = observedRoleLiteralSites();
        Set<String> observed = new LinkedHashSet<>(sites.keySet());

        // ① 扫描结果 ⊆ 台账（新增字面量 ⇒ 红）
        assertThat(observed)
                .as("扫描到未登记的缺省/授权角色字面量赋值点 ⇒ 新增必须登记并说明理由；实测 = %s", sites)
                .isSubsetOf(ROLE_LITERAL_LEDGER);
        // ② 台账 ⊆ 扫描结果（陈旧条目 ⇒ 红，台账只许缩短）
        assertThat(ROLE_LITERAL_LEDGER)
                .as("台账里有已不存在的条目（陈旧）⇒ 删掉台账条目，不要留着盖章")
                .isSubsetOf(observed);
        // ③ 条数现取（禁止「新增即静默」）
        assertThat(ROLE_LITERAL_LEDGER).hasSize(LEDGER_SIZE);
    }

    @Test
    @DisplayName("建号缺省位不得出现写权限默认：两个入口里含 .position(...) 的语句不含写权限角色字面量")
    void positionDefaultsNeverFallBackToWriteCapableRole() throws IOException {
        for (String source : List.of(CONTROLLER_SOURCE, SERVICE_SOURCE)) {
            String text = Files.readString(Paths.get(source));
            for (String statement : roleStatements(text)) {
                if (!statement.contains(".position(")) {
                    continue;
                }
                Matcher m = WRITE_CAPABLE_ROLE.matcher(statement);
                boolean hit = m.find();
                assertThat(hit)
                        .as("岗位/角色的缺省表达式里出现写权限角色字面量 %s ⇒ 缺省 = 提权（issue #5987）。语句：%s",
                                hit ? m.group(1) : "?", normalize(statement))
                        .isFalse();
            }
        }
    }

    @Test
    @DisplayName("扫描器自证：缺省形态/授权字面量判红，取值形态不误报")
    void scannerDiscriminativePower() {
        // 正向：旧的 fail-open 默认必须被判成「缺省字面量」（否则本守卫对病灶失明）
        assertThat(detectRoleLiteralForm("x = User.builder().role(role != null ? role : \"operator\").build();"))
                .as("缺省形态必须命中").isEqualTo("FALLBACK");
        // 正向：显式授权字面量必须命中（新增即须登记）
        assertThat(detectRoleLiteralForm("u = User.builder().role(\"super_admin\").build();"))
                .as("授权字面量必须命中").isEqualTo("LITERAL");
        // 反向：取值/上下文赋值不得命中（否则全仓 `.role(` 都是命中，判据退化成噪音）
        assertThat(detectRoleLiteralForm("u = User.builder().role(user.getRole()).build();"))
                .as("取值形态不得命中").isNull();
        assertThat(detectRoleLiteralForm("u = User.builder().role(anyToString(map.get(\"role\"))).build();"))
                .as("map 取值（字面量是 key 不是角色）不得命中").isNull();
        assertThat(detectRoleLiteralForm("u = User.builder().role(role != null ? role : variable).build();"))
                .as("非字面量默认不得命中").isNull();
        // 注释掩码自证：注释里出现的旧形态不得被当代码（否则本文件自己的说明文字会让判据恒红）
        assertThat(roleStatements("// 旧形态 .role(role != null ? role : \"operator\") 已删\nString x = null;"))
                .as("注释里的示例不得进扫描面").isEqualTo(List.of());
    }

    @Test
    @DisplayName("自证：台账常量与扫描实现确实被本类引用（反射读一次，防空跑绿）")
    void ledgerConstantIsReachable() throws Exception {
        Field field = EmployeeGrantDefaultRoleMetaGuardTest.class.getDeclaredField("ROLE_LITERAL_LEDGER");
        field.setAccessible(true);
        assertThat((Set<?>) field.get(null)).hasSize(LEDGER_SIZE);

        Method method = EmployeeGrantDefaultRoleMetaGuardTest.class.getDeclaredMethod("observedRoleLiteralSites");
        method.setAccessible(true);
        assertThat(method.invoke(null)).isNotNull();

        // 扫描面必须可达（否则「扫描为空 = 台账为空」会变成空跑绿）
        assertThat(Files.isDirectory(Paths.get(MAIN_JAVA_ROOT)))
                .as("扫描根 %s 不存在 ⇒ Surefire 工作目录不对，判据会空跑", MAIN_JAVA_ROOT).isTrue();
        assertThat(roleStatements(Files.readString(Paths.get(SERVICE_SOURCE))))
                .as("扫描器对 UserService 必须至少看到一次 .role( 赋值").isNotEmpty();
    }

    // ======================== 扫描器实现 ========================

    /** 扫描 {@code src/main/java} 下的角色字面量赋值点：{@code 仓库相对路径::表达式} → 形态。 */
    private static Map<String, String> observedRoleLiteralSites() throws IOException {
        Map<String, String> found = new LinkedHashMap<>();
        try (var stream = Files.walk(Paths.get(MAIN_JAVA_ROOT))) {
            for (Path file : stream.filter(p -> p.toString().endsWith(".java")).sorted().toList()) {
                String text = Files.readString(file);
                for (String statement : roleStatements(text)) {
                    String form = detectRoleLiteralForm(statement);
                    if (form != null) {
                        found.put(relative(file) + "::" + normalize(statement), form);
                    }
                }
            }
        }
        return found;
    }

    /**
     * 切出以 {@code .role(} 开头的语句（到 {@code ;} 为止，跨行拼接）；注释先掩掉（注释里的旧形态不是代码）。
     * 结果**从 {@code .role(} 起**，故 {@code detectRoleLiteralForm} 的形态正则可以锚在段首。
     */
    private static List<String> roleStatements(String javaSource) {
        String code = maskComments(javaSource);
        List<String> statements = new ArrayList<>();
        int from = 0;
        while (true) {
            int at = code.indexOf(".role(", from);
            if (at < 0) {
                return statements;
            }
            int end = code.indexOf(';', at);
            statements.add(code.substring(at, end < 0 ? code.length() : end).trim());
            from = at + 1;
        }
    }

    /** 行注释与块注释一律替换成等长空白（保留偏移；避免注释里的示例文本被当代码扫到）。 */
    private static String maskComments(String javaSource) {
        StringBuilder out = new StringBuilder(javaSource.length());
        int i = 0;
        while (i < javaSource.length()) {
            if (javaSource.startsWith("//", i)) {
                int end = javaSource.indexOf('\n', i);
                end = end < 0 ? javaSource.length() : end;
                out.append(" ".repeat(end - i));
                i = end;
            } else if (javaSource.startsWith("/*", i)) {
                int end = javaSource.indexOf("*/", i + 2);
                end = end < 0 ? javaSource.length() : end + 2;
                out.append(" ".repeat(end - i));
                i = end;
            } else {
                out.append(javaSource.charAt(i));
                i++;
            }
        }
        return out.toString();
    }

    /** 形态判别：{@code FALLBACK}（缺省兜底）/ {@code LITERAL}（显式授权字面量）/ {@code null}（取值，不命中）。 */
    private static String detectRoleLiteralForm(String statement) {
        int at = statement.indexOf(".role(");
        if (at < 0) {
            return null;
        }
        String call = statement.substring(at);
        if (NULL_FALLBACK.matcher(call).find()) {
            return "FALLBACK";
        }
        return LITERAL_ARG.matcher(call).find() ? "LITERAL" : null;
    }

    private static String relative(Path file) {
        return file.toAbsolutePath().normalize().toString()
                .replace(File.separatorChar, '/')
                .replaceAll(".*/backend/admin-api/", "backend/admin-api/");
    }

    private static String normalize(String statement) {
        return statement.replaceAll("\\s+", " ").trim();
    }
}
