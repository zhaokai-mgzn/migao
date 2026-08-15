package com.migao.admin.security;

// case_ids=[DF-016]

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.ExpiredJwtException;
import io.jsonwebtoken.JwtException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.core.io.Resource;
import org.springframework.core.io.ResourceLoader;
import org.springframework.test.util.ReflectionTestUtils;

import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.Date;
import java.util.List;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * JwtTokenProvider 单元测试
 * 测试 JWT Token 生成、验证、解析、类型判断、刷新等核心逻辑
 */
@ExtendWith(MockitoExtension.class)
class JwtTokenProviderTest {

    @Mock
    private ResourceLoader resourceLoader;

    @Mock
    private Resource mockResource;

    private JwtTokenProvider jwtTokenProvider;

    @BeforeEach
    void setUp() throws Exception {
        // 从 classpath 加载真实 RSA 密钥对（与生产 classpath:rsa/private.pem 一致）
        String privateKeyPem = readResource("/rsa/private.pem");
        String publicKeyPem = readResource("/rsa/public.pem");

        jwtTokenProvider = new JwtTokenProvider(resourceLoader);
        // 手动设置 @Value 字段（无 Spring 容器时不会自动注入）
        ReflectionTestUtils.setField(jwtTokenProvider, "privateKeyPem", privateKeyPem);
        ReflectionTestUtils.setField(jwtTokenProvider, "publicKeyPem", publicKeyPem);
        ReflectionTestUtils.setField(jwtTokenProvider, "accessTokenExpiration", 7200L);
        ReflectionTestUtils.setField(jwtTokenProvider, "refreshTokenExpiration", 604800L);
        jwtTokenProvider.init();
    }

    /** 读取 classpath 资源为字符串 */
    private String readResource(String path) throws Exception {
        try (var in = getClass().getResourceAsStream(path)) {
            assertThat(in).as("classpath 资源应存在: %s", path).isNotNull();
            return new String(in.readAllBytes(), StandardCharsets.UTF_8);
        }
    }

    // ======================== Token 生成测试 ========================

    @Test
    @DisplayName("生成 Access Token — 包含所有预期 Claims")
    void generateAccessToken_ContainsExpectedClaims() {
        String token = jwtTokenProvider.generateAccessToken("user-001", 1L, "testuser",
                List.of("admin", "operator"));

        assertThat(token).isNotBlank();

        Claims claims = jwtTokenProvider.getClaimsFromToken(token);
        assertThat(claims.getSubject()).isEqualTo("user-001");
        assertThat(claims.get(JwtTokenProvider.CLAIM_USER_ID, String.class)).isEqualTo("user-001");
        assertThat(claims.get(JwtTokenProvider.CLAIM_TENANT_ID)).isEqualTo(1);
        assertThat(claims.get(JwtTokenProvider.CLAIM_USERNAME, String.class)).isEqualTo("testuser");
        assertThat(claims.get(JwtTokenProvider.CLAIM_ROLES, List.class))
                .containsExactly("admin", "operator");
        assertThat(claims.get(JwtTokenProvider.CLAIM_TOKEN_TYPE, String.class))
                .isEqualTo(JwtTokenProvider.TOKEN_TYPE_ACCESS);
        assertThat(claims.getId()).isNotBlank();
        assertThat(claims.getAudience()).contains("migao");
    }

    @Test
    @DisplayName("生成 Refresh Token — tokenType 为 refresh，不含 username 和 roles")
    void generateRefreshToken_HasRefreshType() {
        String token = jwtTokenProvider.generateRefreshToken("user-001", 1L);

        assertThat(token).isNotBlank();

        Claims claims = jwtTokenProvider.getClaimsFromToken(token);
        assertThat(claims.getSubject()).isEqualTo("user-001");
        assertThat(claims.get(JwtTokenProvider.CLAIM_USER_ID, String.class)).isEqualTo("user-001");
        assertThat(claims.get(JwtTokenProvider.CLAIM_TENANT_ID)).isEqualTo(1);
        assertThat(claims.get(JwtTokenProvider.CLAIM_TOKEN_TYPE, String.class))
                .isEqualTo(JwtTokenProvider.TOKEN_TYPE_REFRESH);
        // Refresh Token 不包含 username 和 roles
        assertThat(claims.get(JwtTokenProvider.CLAIM_USERNAME, String.class)).isNull();
        assertThat(claims.get(JwtTokenProvider.CLAIM_ROLES, List.class)).isNull();
    }

    // ======================== Token 验证测试 ========================

    @Test
    @DisplayName("validateToken — 有效 Token 返回 true")
    void validateToken_ValidToken_ReturnsTrue() {
        String token = jwtTokenProvider.generateAccessToken("user-001", 1L, "test",
                List.of("admin"));

        assertThat(jwtTokenProvider.validateToken(token)).isTrue();
    }

    @Test
    @DisplayName("validateToken — 已过期 Token 返回 false")
    void validateToken_ExpiredToken_ReturnsFalse() {
        // 设置负的过期时间生成已过期 Token
        ReflectionTestUtils.setField(jwtTokenProvider, "accessTokenExpiration", -1L);
        String expiredToken = jwtTokenProvider.generateAccessToken("user-001", 1L, "test",
                List.of("admin"));
        ReflectionTestUtils.setField(jwtTokenProvider, "accessTokenExpiration", 7200L);

        assertThat(jwtTokenProvider.validateToken(expiredToken)).isFalse();
    }

    @Test
    @DisplayName("validateToken — 格式错误的 Token 返回 false")
    void validateToken_MalformedToken_ReturnsFalse() {
        assertThat(jwtTokenProvider.validateToken("not.a.valid.jwt.token")).isFalse();
        assertThat(jwtTokenProvider.validateToken("")).isFalse();
        assertThat(jwtTokenProvider.validateToken("   ")).isFalse();
    }

    @Test
    @DisplayName("validateAndParseToken — 有效 Token 返回 Claims")
    void validateAndParseToken_ValidToken_ReturnsClaims() {
        String token = jwtTokenProvider.generateAccessToken("user-001", 1L, "testuser",
                List.of("admin"));

        Claims claims = jwtTokenProvider.validateAndParseToken(token);
        assertThat(claims).isNotNull();
        assertThat(claims.getSubject()).isEqualTo("user-001");
    }

    @Test
    @DisplayName("validateAndParseToken — 已过期 Token 抛出 ExpiredJwtException")
    void validateAndParseToken_ExpiredToken_ThrowsExpiredJwtException() {
        ReflectionTestUtils.setField(jwtTokenProvider, "accessTokenExpiration", -1L);
        String expiredToken = jwtTokenProvider.generateAccessToken("user-001", 1L, "test",
                List.of("admin"));
        ReflectionTestUtils.setField(jwtTokenProvider, "accessTokenExpiration", 7200L);

        assertThatThrownBy(() -> jwtTokenProvider.validateAndParseToken(expiredToken))
                .isInstanceOf(ExpiredJwtException.class);
    }

    @Test
    @DisplayName("validateAndParseToken — 格式错误的 Token 抛出 JwtException")
    void validateAndParseToken_MalformedToken_ThrowsJwtException() {
        assertThatThrownBy(() -> jwtTokenProvider.validateAndParseToken("garbage.token.here"))
                .isInstanceOf(JwtException.class);
    }

    // ======================== Token 类型检测 ========================

    @Test
    @DisplayName("isAccessToken — Access Token 返回 true")
    void isAccessToken_AccessToken_ReturnsTrue() {
        String token = jwtTokenProvider.generateAccessToken("user-001", 1L, "test", List.of());

        assertThat(jwtTokenProvider.isAccessToken(token)).isTrue();
        assertThat(jwtTokenProvider.isRefreshToken(token)).isFalse();
    }

    @Test
    @DisplayName("isRefreshToken — Refresh Token 返回 true")
    void isRefreshToken_RefreshToken_ReturnsTrue() {
        String token = jwtTokenProvider.generateRefreshToken("user-001", 1L);

        assertThat(jwtTokenProvider.isRefreshToken(token)).isTrue();
        assertThat(jwtTokenProvider.isAccessToken(token)).isFalse();
    }

    @Test
    @DisplayName("getTokenType — 返回正确的 Token 类型字符串")
    void getTokenType_ReturnsCorrectType() {
        String accessToken = jwtTokenProvider.generateAccessToken("u1", 1L, "t", List.of());
        String refreshToken = jwtTokenProvider.generateRefreshToken("u1", 1L);

        assertThat(jwtTokenProvider.getTokenType(accessToken))
                .isEqualTo(JwtTokenProvider.TOKEN_TYPE_ACCESS);
        assertThat(jwtTokenProvider.getTokenType(refreshToken))
                .isEqualTo(JwtTokenProvider.TOKEN_TYPE_REFRESH);
    }

    // ======================== Claims 提取测试 ========================

    @Test
    @DisplayName("getUserIdFromToken — 提取 userId")
    void getUserIdFromToken_ExtractsUserId() {
        String token = jwtTokenProvider.generateAccessToken("user-002", 2L, "alice",
                List.of("operator"));

        assertThat(jwtTokenProvider.getUserIdFromToken(token)).isEqualTo("user-002");
    }

    @Test
    @DisplayName("getTenantIdFromToken — 提取 tenantId（Number 类型）")
    void getTenantIdFromToken_ExtractsTenantId() {
        String token = jwtTokenProvider.generateAccessToken("user-001", 5L, "test", List.of());

        assertThat(jwtTokenProvider.getTenantIdFromToken(token)).isEqualTo(5L);
    }

    @Test
    @DisplayName("getUsernameFromToken — 提取 username")
    void getUsernameFromToken_ExtractsUsername() {
        String token = jwtTokenProvider.generateAccessToken("user-001", 1L, "bob",
                List.of("admin"));

        assertThat(jwtTokenProvider.getUsernameFromToken(token)).isEqualTo("bob");
    }

    @Test
    @DisplayName("getRolesFromToken — 提取角色列表")
    void getRolesFromToken_ExtractsRoles() {
        List<String> roles = List.of("admin", "operator", "viewer");
        String token = jwtTokenProvider.generateAccessToken("user-001", 1L, "test", roles);

        assertThat(jwtTokenProvider.getRolesFromToken(token)).containsExactlyElementsOf(roles);
    }

    // ======================== 过期时间测试 ========================

    @Test
    @DisplayName("getExpirationDate — 返回 Token 过期时间")
    void getExpirationDate_ReturnsExpirationDate() {
        String token = jwtTokenProvider.generateAccessToken("user-001", 1L, "test", List.of());

        Date expiration = jwtTokenProvider.getExpirationDate(token);
        assertThat(expiration).isNotNull();
        // 过期时间应在生成后的 accessTokenExpiration 秒左右
        long diffMs = expiration.getTime() - System.currentTimeMillis();
        assertThat(diffMs).isBetween(0L, 7200_000L + 5000L);
    }

    @Test
    @DisplayName("isTokenExpiringSoon — 即将过期的 Token 返回 true")
    void isTokenExpiringSoon_NearingExpiration_ReturnsTrue() {
        String token = jwtTokenProvider.generateAccessToken("user-001", 1L, "test", List.of());

        // Token 的过期时间远大于 threshold → 不应即将过期
        assertThat(jwtTokenProvider.isTokenExpiringSoon(token, 1_000_000_000L)).isTrue();
        // Token 的过期时间小于 threshold → 即将过期
        assertThat(jwtTokenProvider.isTokenExpiringSoon(token, 60_000L)).isFalse();
    }

    // ======================== Token 刷新测试 ========================

    @Test
    @DisplayName("refreshAccessToken — 使用有效 Refresh Token 刷新成功")
    void refreshAccessToken_ValidRefreshToken_Success() {
        String refreshToken = jwtTokenProvider.generateRefreshToken("user-001", 1L);

        String newAccessToken = jwtTokenProvider.refreshAccessToken(refreshToken, "testuser",
                List.of("admin"));

        assertThat(newAccessToken).isNotBlank();
        assertThat(jwtTokenProvider.isAccessToken(newAccessToken)).isTrue();
        assertThat(jwtTokenProvider.getUserIdFromToken(newAccessToken)).isEqualTo("user-001");
        assertThat(jwtTokenProvider.getTenantIdFromToken(newAccessToken)).isEqualTo(1L);
        assertThat(jwtTokenProvider.getUsernameFromToken(newAccessToken)).isEqualTo("testuser");
    }

    @Test
    @DisplayName("refreshAccessToken — 使用过期 Refresh Token 抛出 IllegalArgumentException")
    void refreshAccessToken_ExpiredRefreshToken_Throws() {
        ReflectionTestUtils.setField(jwtTokenProvider, "refreshTokenExpiration", -1L);
        String expiredRefresh = jwtTokenProvider.generateRefreshToken("user-001", 1L);
        ReflectionTestUtils.setField(jwtTokenProvider, "refreshTokenExpiration", 604800L);

        assertThatThrownBy(() ->
                jwtTokenProvider.refreshAccessToken(expiredRefresh, "test", List.of()))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("无效的 Refresh Token");
    }

    @Test
    @DisplayName("refreshAccessToken — 使用 Access Token（非 Refresh）抛出 IllegalArgumentException")
    void refreshAccessToken_AccessTokenInsteadOfRefresh_Throws() {
        String accessToken = jwtTokenProvider.generateAccessToken("user-001", 1L, "test",
                List.of());

        assertThatThrownBy(() ->
                jwtTokenProvider.refreshAccessToken(accessToken, "test", List.of()))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("无效的 Refresh Token");
    }

    // ======================== 配置值测试 ========================

    @Test
    @DisplayName("getAccessTokenExpiration / getRefreshTokenExpiration — 返回配置值")
    void getExpiration_ReturnsConfiguredValues() {
        assertThat(jwtTokenProvider.getAccessTokenExpiration()).isEqualTo(7200L);
        assertThat(jwtTokenProvider.getRefreshTokenExpiration()).isEqualTo(604800L);
    }

    // ======================== 签名算法一致性测试 ========================

    @Test
    @DisplayName("生成 Access Token — 签名算法必须为 RS256（与 ai-agent-service 校验契约一致）")
    void generateAccessToken_UsesRS256Algorithm() {
        String token = jwtTokenProvider.generateAccessToken("user-001", 1L, "test", List.of());

        // 解码 JWT header 断言 alg=RS256，而非 HS256
        String headerJson = new String(
                Base64.getUrlDecoder().decode(token.split("\\.")[0]), StandardCharsets.UTF_8);

        assertThat(headerJson).contains("\"alg\":\"RS256\"");
    }

    @Test
    @DisplayName("RSA 密钥缺失时 init 必须 fail-fast，禁止静默回退 HS256")
    void init_WhenRsaKeysMissing_ThrowsInsteadOfSilentHmacFallback() {
        // 模拟生产环境 RSA 密钥加载失败（资源不存在）
        when(resourceLoader.getResource(anyString())).thenReturn(mockResource);
        when(mockResource.exists()).thenReturn(false);

        JwtTokenProvider provider = new JwtTokenProvider(resourceLoader);
        ReflectionTestUtils.setField(provider, "privateKeyPath", "classpath:rsa/private.pem");
        ReflectionTestUtils.setField(provider, "publicKeyPath", "classpath:rsa/public.pem");

        assertThatThrownBy(() -> provider.init())
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("RS256");
    }
}
