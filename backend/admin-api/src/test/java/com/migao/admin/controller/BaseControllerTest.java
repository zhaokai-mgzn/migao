package com.migao.admin.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.config.TenantContext;
import com.migao.admin.security.SecurityUser;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.List;

import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * Controller 测试基类 — 提供 TenantContext / SecurityContext / MockMvc 公共初始化。
 *
 * 使用方式：
 * <pre>
 * class XxxControllerTest extends BaseControllerTest {
 *     &#64;Mock private XxxService xxxService;
 *     &#64;InjectMocks private XxxController xxxController;
 *
 *     &#64;BeforeEach
 *     void setUp() {
 *         super.setUp();              // 公共初始化
 *         mockMvc = buildMockMvc(xxxController); // MockMvc
 *     }
 * }
 * </pre>
 */
@MockitoSettings(strictness = Strictness.LENIENT)
public abstract class BaseControllerTest {

    protected static final Long TEST_TENANT_ID = 1L;
    protected static final String TEST_USER_ID = "user-test-001";

    protected final ObjectMapper objectMapper = new ObjectMapper()
            .registerModule(new JavaTimeModule());

    /**
     * 公共 setUp：设置 TenantContext + 管理员认证。
     * 子类必须在 @BeforeEach 中调用 super.setUp()。
     */
    @BeforeEach
    void baseSetUp() {
        TenantContext.setTenantId(TEST_TENANT_ID);
        setAdminUser();
    }

    /**
     * 公共 tearDown：清理 TenantContext + SecurityContext。
     * 子类必须在 @AfterEach 中调用 super.tearDown()。
     */
    @AfterEach
    void baseTearDown() {
        TenantContext.clear();
        SecurityContextHolder.clearContext();
    }

    /**
     * 构建 standalone MockMvc，挂载 GlobalExceptionHandler。
     */
    protected MockMvc buildMockMvc(Object controller) {
        return MockMvcBuilders.standaloneSetup(controller)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    /**
     * 设置管理员认证信息到 SecurityContext。
     */
    protected void setAdminUser() {
        SecurityUser user = new SecurityUser(
                TEST_USER_ID, TEST_TENANT_ID, "admin-phone",
                List.of("admin"),
                List.of(new SimpleGrantedAuthority("ROLE_admin"))
        );
        Authentication auth = mock(Authentication.class);
        when(auth.isAuthenticated()).thenReturn(true);
        when(auth.getPrincipal()).thenReturn(user);
        SecurityContextHolder.getContext().setAuthentication(auth);
    }

    /**
     * 设置操作员认证信息。
     */
    protected void setOperatorUser() {
        SecurityUser user = new SecurityUser(
                "user-operator", TEST_TENANT_ID, "operator-phone",
                List.of("operator"),
                List.of(new SimpleGrantedAuthority("ROLE_operator"))
        );
        Authentication auth = mock(Authentication.class);
        when(auth.isAuthenticated()).thenReturn(true);
        when(auth.getPrincipal()).thenReturn(user);
        SecurityContextHolder.getContext().setAuthentication(auth);
    }
}
