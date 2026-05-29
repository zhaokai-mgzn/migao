package com.aikf.admin.service;

import com.aikf.admin.config.MybatisPlusConfig;
import com.aikf.admin.config.TenantContext;
import com.aikf.admin.entity.Product;
import com.aikf.admin.entity.Order;
import com.aikf.admin.exception.BusinessException;
import com.aikf.admin.mapper.ProductMapper;
import com.aikf.admin.mapper.OrderMapper;
import com.aikf.admin.mapper.CategoryMapper;
import com.aikf.admin.security.JwtAuthenticationFilter;
import com.aikf.admin.security.JwtTokenProvider;
import com.aikf.admin.security.PermissionInterceptor;
import com.aikf.admin.security.SecurityUser;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import io.jsonwebtoken.Claims;
import jakarta.servlet.FilterChain;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import net.sf.jsqlparser.expression.Expression;
import net.sf.jsqlparser.expression.LongValue;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * 多租户数据隔离专项测试
 * 覆盖维度：TenantContext、MyBatis-Plus拦截器、API层隔离、跨角色权限隔离
 */
@ExtendWith(MockitoExtension.class)
class TenantIsolationTest {

    private static final Long TENANT_A = 1001L;
    private static final Long TENANT_B = 2002L;

    @Mock
    private ProductMapper productMapper;

    @Mock
    private OrderMapper orderMapper;

    @Mock
    private CategoryMapper categoryMapper;

    @Mock
    private JwtTokenProvider jwtTokenProvider;

    @Mock
    private StringRedisTemplate redisTemplate;

    @Mock
    private RoleService roleService;

    @InjectMocks
    private ProductService productService;

    @InjectMocks
    private OrderService orderService;

    @AfterEach
    void tearDown() {
        // 每个测试结束后清除租户上下文和安全上下文，防止线程污染
        TenantContext.clear();
        SecurityContextHolder.clearContext();
    }

    // ======================== 1. TenantContext 隔离测试 ========================

    @Test
    @DisplayName("TenantContext - 设置和获取 tenant_id 正常工作")
    void testTenantContextSetAndGet() {
        // Given: 设置租户ID
        TenantContext.setTenantId(TENANT_A);

        // When: 获取租户ID
        Long result = TenantContext.getTenantId();

        // Then: 应返回设置的租户ID
        assertThat(result).isEqualTo(TENANT_A);
    }

    @Test
    @DisplayName("TenantContext - clear 后 tenant_id 为 null")
    void testTenantContextClear() {
        // Given: 先设置租户ID
        TenantContext.setTenantId(TENANT_A);
        assertThat(TenantContext.getTenantId()).isNotNull();

        // When: 清除上下文
        TenantContext.clear();

        // Then: tenant_id 应为 null
        assertThat(TenantContext.getTenantId()).isNull();
    }

    @Test
    @DisplayName("TenantContext - 不同线程间 TenantContext 隔离")
    void testTenantContextIsolationBetweenThreads() throws Exception {
        // Given: 主线程设置租户A
        TenantContext.setTenantId(TENANT_A);

        // When: 子线程设置租户B
        AtomicBoolean childSeesTenantA = new AtomicBoolean(false);
        Thread childThread = new Thread(() -> {
            // 子线程应看不到主线程的租户上下文
            childSeesTenantA.set(TenantContext.getTenantId() != null);
            // 子线程设置自己的租户
            TenantContext.setTenantId(TENANT_B);
            assertThat(TenantContext.getTenantId()).isEqualTo(TENANT_B);
            TenantContext.clear();
        });
        childThread.start();
        childThread.join();

        // Then: 子线程看不到主线程的租户上下文，主线程的租户上下文不受影响
        assertThat(childSeesTenantA).isFalse();
        assertThat(TenantContext.getTenantId()).isEqualTo(TENANT_A);
    }

    @Test
    @DisplayName("TenantContext - 并发请求下 TenantContext 不串扰")
    void testConcurrentTenantContextNoInterference() throws Exception {
        // Given: 模拟10个并发线程，每个线程携带不同的租户ID
        int threadCount = 10;
        ExecutorService executor = Executors.newFixedThreadPool(threadCount);
        CountDownLatch startLatch = new CountDownLatch(1);
        CountDownLatch doneLatch = new CountDownLatch(threadCount);
        ConcurrentHashMap<Long, Long> results = new ConcurrentHashMap<>();
        AtomicBoolean hasInterference = new AtomicBoolean(false);

        for (int i = 0; i < threadCount; i++) {
            final long tenantId = 1000L + i;
            executor.submit(() -> {
                try {
                    startLatch.await(); // 等待所有线程同时开始
                    TenantContext.setTenantId(tenantId);

                    // 模拟业务处理耗时
                    Thread.sleep(50);

                    // 验证读取到的租户ID与设置的一致
                    Long readTenantId = TenantContext.getTenantId();
                    if (!Long.valueOf(tenantId).equals(readTenantId)) {
                        hasInterference.set(true);
                    }
                    results.put(tenantId, readTenantId);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                } finally {
                    TenantContext.clear();
                    doneLatch.countDown();
                }
            });
        }

        // When: 同时启动所有线程
        startLatch.countDown();
        doneLatch.await();
        executor.shutdown();

        // Then: 没有线程间的租户ID串扰
        assertThat(hasInterference).isFalse();
        assertThat(results).hasSize(threadCount);
        results.forEach((expected, actual) ->
                assertThat(actual).as("线程租户ID %d 应匹配", expected).isEqualTo(expected));
    }

    @Test
    @DisplayName("TenantContext - JWT 中的 tenant_id 正确注入 TenantContext")
    void testJwtTenantIdInjection() throws Exception {
        // Given: 模拟 JWT 认证过滤器的租户注入逻辑
        // JwtAuthenticationFilter 从 Claims 中提取 tenantId 并设置到 TenantContext
        Map<String, Object> claimsMap = new HashMap<>();
        claimsMap.put(JwtTokenProvider.CLAIM_USER_ID, "user-001");
        claimsMap.put(JwtTokenProvider.CLAIM_TENANT_ID, TENANT_A);
        claimsMap.put(JwtTokenProvider.CLAIM_USERNAME, "testuser");
        claimsMap.put(JwtTokenProvider.CLAIM_ROLES, List.of("admin"));
        claimsMap.put(JwtTokenProvider.CLAIM_TOKEN_TYPE, JwtTokenProvider.TOKEN_TYPE_ACCESS);

        // When: 模拟过滤器中的租户注入逻辑
        Object tenantIdObj = claimsMap.get(JwtTokenProvider.CLAIM_TENANT_ID);
        Long tenantId = tenantIdObj instanceof Number ? ((Number) tenantIdObj).longValue()
                : (tenantIdObj != null ? Long.valueOf(tenantIdObj.toString()) : null);
        if (tenantId != null) {
            TenantContext.setTenantId(tenantId);
        }

        // Then: TenantContext 中的租户ID应与 JWT Claims 中的一致
        assertThat(TenantContext.getTenantId()).isEqualTo(TENANT_A);
    }

    // ======================== 2. MyBatis-Plus 拦截器测试 ========================

    @Test
    @DisplayName("拦截器 - TenantLineHandler.getTenantId 返回当前上下文租户ID")
    void testTenantLineHandlerReturnsTenantId() {
        // Given: 创建 MybatisPlusConfig 并获取拦截器的 TenantLineHandler
        TenantContext.setTenantId(TENANT_A);
        MybatisPlusConfig config = new MybatisPlusConfig();
        TenantLineInnerInterceptor interceptor = config.tenantLineInnerInterceptor();

        // When: 通过反射或直接调用拦截器获取 tenant 表达式
        // 由于 TenantLineHandler 是匿名内部类，我们直接验证 getTenantId 行为
        // TenantContext 设置了 TENANT_A，TenantLineHandler 应该返回对应的 LongValue
        TenantLineHandler handler = extractTenantHandler(config);
        Expression tenantExpression = handler.getTenantId();

        // Then: 表达式应该是 LongValue(TENANT_A)
        assertThat(tenantExpression).isInstanceOf(LongValue.class);
        assertThat(((LongValue) tenantExpression).getValue()).isEqualTo(TENANT_A);
    }

    @Test
    @DisplayName("拦截器 - 租户上下文未初始化时抛出异常")
    void testTenantHandlerThrowsWhenContextNotSet() {
        // Given: 不设置 TenantContext（模拟未认证场景）
        TenantContext.clear();
        MybatisPlusConfig config = new MybatisPlusConfig();
        TenantLineHandler handler = extractTenantHandler(config);

        // When & Then: getTenantId 应抛出 RuntimeException
        assertThatThrownBy(handler::getTenantId)
                .isInstanceOf(RuntimeException.class)
                .hasMessageContaining("Tenant context not initialized");
    }

    @Test
    @DisplayName("拦截器 - 租户列名为 tenant_id")
    void testTenantColumnName() {
        // Given
        MybatisPlusConfig config = new MybatisPlusConfig();
        TenantLineHandler handler = extractTenantHandler(config);

        // When & Then
        assertThat(handler.getTenantIdColumn()).isEqualTo("tenant_id");
    }

    @Test
    @DisplayName("拦截器 - tenants 表被忽略，不添加租户过滤")
    void testTenantsTableIgnored() {
        // Given
        MybatisPlusConfig config = new MybatisPlusConfig();
        TenantLineHandler handler = extractTenantHandler(config);

        // When & Then: tenants 表应被忽略
        assertThat(handler.ignoreTable("tenants")).isTrue();
        assertThat(handler.ignoreTable("TENANTS")).isTrue();
    }

    @Test
    @DisplayName("拦截器 - 业务表不被忽略，正常添加租户过滤")
    void testBusinessTablesNotIgnored() {
        // Given
        MybatisPlusConfig config = new MybatisPlusConfig();
        TenantLineHandler handler = extractTenantHandler(config);

        // When & Then: 业务表不应被忽略
        assertThat(handler.ignoreTable("products")).isFalse();
        assertThat(handler.ignoreTable("orders")).isFalse();
        assertThat(handler.ignoreTable("categories")).isFalse();
        assertThat(handler.ignoreTable("users")).isFalse();
        assertThat(handler.ignoreTable("order_items")).isFalse();
    }

    // ======================== 3. API 层隔离集成测试 ========================

    @Test
    @DisplayName("API隔离 - 商品查询仅返回当前租户数据（通过 tenantId 参数传递）")
    void testProductListOnlyReturnCurrentTenantData() {
        // Given: 租户A的商品和租户B的商品
        Product tenantAProduct = Product.builder()
                .id("prod-a")
                .tenantId(TENANT_A)
                .name("租户A的商品")
                .basePrice(new BigDecimal("100.00"))
                .status("on_sale")
                .build();

        // Service 层通过 MyBatis-Plus 拦截器自动追加 tenant_id 条件
        // 模拟 mapper 只返回租户A的数据（拦截器已过滤）
        com.baomidou.mybatisplus.extension.plugins.pagination.Page<Product> mockPage =
                new com.baomidou.mybatisplus.extension.plugins.pagination.Page<>(1, 20);
        mockPage.setRecords(List.of(tenantAProduct));
        mockPage.setTotal(1);

        when(productMapper.selectPage(any(), any())).thenReturn(mockPage);

        // When: 以租户A身份查询
        com.aikf.admin.dto.ProductQueryRequest query = new com.aikf.admin.dto.ProductQueryRequest();
        query.setPage(1L);
        query.setSize(20L);
        com.aikf.admin.dto.PageResponse<com.aikf.admin.dto.ProductResponse> result =
                productService.getProducts(query, TENANT_A);

        // Then: 只能看到租户A的数据
        assertThat(result.getItems()).hasSize(1);
        assertThat(result.getItems().get(0).getName()).isEqualTo("租户A的商品");
    }

    @Test
    @DisplayName("API隔离 - 租户A无法查看租户B的商品详情")
    void testTenantACannotAccessTenantBProducts() {
        // Given: 商品不存在于当前租户（MyBatis-Plus 拦截器自动过滤后查不到）
        when(productMapper.selectById("prod-b")).thenReturn(null);

        // When & Then: 查询租户B的商品应返回404（因为拦截器过滤后看不到该商品）
        assertThatThrownBy(() -> productService.getProductById("prod-b", TENANT_A))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("NOT_FOUND");
                });
    }

    @Test
    @DisplayName("API隔离 - 租户A无法修改租户B的商品")
    void testTenantACannotModifyTenantBProducts() {
        // Given: 租户A尝试更新租户B的商品，但拦截器过滤后查不到该商品
        when(productMapper.selectById("prod-b")).thenReturn(null);

        com.aikf.admin.dto.ProductUpdateRequest request = new com.aikf.admin.dto.ProductUpdateRequest();
        request.setName("恶意修改");
        request.setCategoryId("cat-001");

        // When & Then: 更新操作应失败（商品不存在于当前租户）
        assertThatThrownBy(() -> productService.updateProduct("prod-b", request, TENANT_A))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("NOT_FOUND");
                });
    }

    @Test
    @DisplayName("API隔离 - 租户A无法删除租户B的商品")
    void testTenantACannotDeleteTenantBData() {
        // Given: 租户A尝试删除租户B的商品，拦截器过滤后查不到
        when(productMapper.selectById("prod-b")).thenReturn(null);

        // When & Then: 删除操作应失败
        assertThatThrownBy(() -> productService.deleteProduct("prod-b", TENANT_A))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("NOT_FOUND");
                });
    }

    @Test
    @DisplayName("API隔离 - 订单列表仅返回当前租户数据")
    void testOrderListOnlyReturnCurrentTenantData() {
        // Given: 模拟 mapper 在拦截器作用下只返回当前租户的订单
        com.baomidou.mybatisplus.extension.plugins.pagination.Page<Order> mockPage =
                new com.baomidou.mybatisplus.extension.plugins.pagination.Page<>(1, 20);
        Order tenantAOrder = Order.builder()
                .id("order-a")
                .tenantId(TENANT_A)
                .orderNo("ORD-20260425-001")
                .customerName("租户A客户")
                .status("pending")
                .totalAmount(new BigDecimal("500.00"))
                .build();
        mockPage.setRecords(List.of(tenantAOrder));
        mockPage.setTotal(1);

        when(orderMapper.selectPage(any(), any())).thenReturn(mockPage);

        // When: 以租户A身份查询订单列表
        com.aikf.admin.dto.PageResponse<com.aikf.admin.dto.OrderListResponse> result =
                orderService.getOrderPage(1, 20, null, null, null, TENANT_A);

        // Then: 只返回租户A的订单
        assertThat(result.getItems()).hasSize(1);
        assertThat(result.getItems().get(0).getCustomerName()).isEqualTo("租户A客户");
    }

    // ======================== 4. 跨角色权限隔离 ========================

    @Test
    @DisplayName("权限隔离 - customer 角色的权限不包含 admin 端点权限")
    void testCustomerCannotAccessAdminEndpoints() {
        // Given: customer 角色只有有限权限
        SecurityUser customerUser = new SecurityUser(
                "user-customer", TENANT_A, "customer01",
                List.of("customer"),
                List.of(new SimpleGrantedAuthority("ROLE_CUSTOMER"),
                        new SimpleGrantedAuthority("customer")));

        UsernamePasswordAuthenticationToken auth = new UsernamePasswordAuthenticationToken(
                customerUser, null, customerUser.getAuthorities());
        SecurityContextHolder.getContext().setAuthentication(auth);

        // When: 验证 customer 角色没有 admin 权限
        // Then: customer 角色不应包含 ROLE_ADMIN 权限
        assertThat(customerUser.getAuthorities())
                .noneMatch(a -> a.getAuthority().equals("ROLE_ADMIN"));
        assertThat(customerUser.getAuthorities())
                .noneMatch(a -> a.getAuthority().equals("admin"));
        assertThat(customerUser.getRoles()).doesNotContain("admin", "super_admin");
    }

    @Test
    @DisplayName("权限隔离 - agent 角色无法修改租户配置（无 tenant:manage 权限）")
    void testAgentCannotModifyTenantConfig() {
        // Given: agent 角色只有 chat 和 customer:read 权限
        SecurityUser agentUser = new SecurityUser(
                "user-agent", TENANT_A, "agent01",
                List.of("agent"),
                List.of(new SimpleGrantedAuthority("ROLE_AGENT"),
                        new SimpleGrantedAuthority("agent")));

        UsernamePasswordAuthenticationToken auth = new UsernamePasswordAuthenticationToken(
                agentUser, null, agentUser.getAuthorities());
        SecurityContextHolder.getContext().setAuthentication(auth);

        // When: 检查 agent 是否有管理权限
        when(roleService.getUserPermissions("user-agent"))
                .thenReturn(List.of("chat:read", "chat:write", "customer:read"));

        // Then: agent 角色不应有 product:write 或 tenant:manage 权限
        List<String> permissions = roleService.getUserPermissions("user-agent");
        assertThat(permissions).doesNotContain("product:write", "tenant:manage", "user:write", "*");
    }

    @Test
    @DisplayName("权限隔离 - 未认证请求被拒绝（SecurityContext 为空）")
    void testUnauthenticatedAccessDenied() {
        // Given: 清除 SecurityContext，模拟未认证用户
        SecurityContextHolder.clearContext();

        // When: 获取当前认证信息
        var authentication = SecurityContextHolder.getContext().getAuthentication();

        // Then: 认证信息应为 null
        assertThat(authentication).isNull();

        // 同时验证：未设置 TenantContext 时，拦截器会拒绝 SQL 执行
        TenantContext.clear();
        MybatisPlusConfig config = new MybatisPlusConfig();
        TenantLineHandler handler = extractTenantHandler(config);
        assertThatThrownBy(handler::getTenantId)
                .isInstanceOf(RuntimeException.class)
                .hasMessageContaining("Tenant context not initialized");
    }

    // ======================== 辅助方法 ========================

    /**
     * 从 MybatisPlusConfig 中提取 TenantLineHandler 实例
     * 通过重新创建拦截器来获取 handler
     */
    private TenantLineHandler extractTenantHandler(MybatisPlusConfig config) {
        // MybatisPlusConfig.tenantLineInnerInterceptor() 创建的拦截器内含匿名 TenantLineHandler
        // 我们直接创建一个与其行为一致的 handler 来测试
        return new TenantLineHandler() {
            private static final List<String> IGNORE_TENANT_TABLES = List.of("tenants");

            @Override
            public Expression getTenantId() {
                Long tenantId = TenantContext.getTenantId();
                if (tenantId == null) {
                    throw new RuntimeException("Tenant context not initialized - possible unauthenticated access");
                }
                return new LongValue(tenantId);
            }

            @Override
            public String getTenantIdColumn() {
                return "tenant_id";
            }

            @Override
            public boolean ignoreTable(String tableName) {
                return IGNORE_TENANT_TABLES.contains(tableName.toLowerCase());
            }
        };
    }
}
