package com.migao.admin.security;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.ExpiredJwtException;
import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.io.Decoders;
import io.jsonwebtoken.security.Keys;
import jakarta.annotation.PostConstruct;
import lombok.Getter;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.Resource;
import org.springframework.core.io.ResourceLoader;
import org.springframework.stereotype.Component;

import javax.crypto.SecretKey;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.security.Key;
import java.security.KeyFactory;
import java.security.PrivateKey;
import java.security.PublicKey;
import java.security.spec.PKCS8EncodedKeySpec;
import java.security.spec.X509EncodedKeySpec;
import java.time.Instant;
import java.util.Date;
import java.util.List;
import java.util.UUID;
import java.util.stream.Collectors;

/**
 * JWT Token 提供者
 * 支持 RS256 (RSA) 和 HS256 (HMAC-SHA256) 两种算法
 * 优先使用 RS256，如果密钥文件不存在则回退到 HS256
 */
@Slf4j
@Component
public class JwtTokenProvider {

    @Value("${jwt.private-key:classpath:rsa/private.pem}")
    private String privateKeyPath;

    @Value("${jwt.public-key:classpath:rsa/public.pem}")
    private String publicKeyPath;

    /**
     * PEM 内容直接注入（优先级高于文件路径）
     * 设置后将跳过 classpath 文件加载，用于生产环境密钥管理
     */
    @Value("${jwt.private-key-pem:#{null}}")
    private String privateKeyPem;

    @Value("${jwt.public-key-pem:#{null}}")
    private String publicKeyPem;

    @Value("${jwt.access-token-expiration:7200}")
    @Getter
    private long accessTokenExpiration;

    @Value("${jwt.refresh-token-expiration:604800}")
    @Getter
    private long refreshTokenExpiration;

    private final ResourceLoader resourceLoader;

    private PrivateKey rsaPrivateKey;
    private PublicKey rsaPublicKey;
    private SecretKey hmacKey;
    private boolean useRsa = false;

    // JWT Claims 常量
    public static final String CLAIM_USER_ID = "userId";
    public static final String CLAIM_TENANT_ID = "tenantId";
    public static final String CLAIM_USERNAME = "username";
    public static final String CLAIM_ROLES = "roles";
    public static final String CLAIM_PERMISSIONS = "permissions";
    public static final String CLAIM_TOKEN_TYPE = "tokenType";
    public static final String TOKEN_TYPE_ACCESS = "access";
    public static final String TOKEN_TYPE_REFRESH = "refresh";

    public JwtTokenProvider(ResourceLoader resourceLoader) {
        this.resourceLoader = resourceLoader;
    }

    @PostConstruct
    public void init() {
        try {
            // 尝试加载 RSA 密钥
            loadRsaKeys();
            useRsa = (rsaPrivateKey != null && rsaPublicKey != null);
            if (useRsa) {
                log.info("JWT 使用 RS256 (RSA) 算法");
            } else {
                log.warn("RSA 密钥加载失败，回退到 HS256 (HMAC-SHA256) 算法");
                initHmacKey();
            }
        } catch (Exception e) {
            log.error("加载 RSA 密钥失败，回退到 HS256 算法: {}", e.getMessage());
            initHmacKey();
        }
    }

    /**
     * 加载 RSA 密钥
     * 优先级: 环境变量 PEM 内容 > classpath 文件
     */
    private void loadRsaKeys() {
        try {
            // 优先从环境变量加载 PEM 内容（生产环境推荐方式）
            if (privateKeyPem != null && !privateKeyPem.isEmpty()
                    && publicKeyPem != null && !publicKeyPem.isEmpty()) {
                rsaPrivateKey = loadPrivateKey(privateKeyPem);
                rsaPublicKey = loadPublicKey(publicKeyPem);
                log.info("RSA 密钥已从环境变量 PEM 内容加载");
                return;
            }

            // 回退到 classpath 文件加载（仅用于本地开发）
            Resource privateResource = resourceLoader.getResource(privateKeyPath);
            if (privateResource.exists()) {
                String privateKeyContent = readKeyContent(privateResource);
                if (privateKeyContent != null && !privateKeyContent.isEmpty()) {
                    rsaPrivateKey = loadPrivateKey(privateKeyContent);
                }
            }

            Resource publicResource = resourceLoader.getResource(publicKeyPath);
            if (publicResource.exists()) {
                String publicKeyContent = readKeyContent(publicResource);
                if (publicKeyContent != null && !publicKeyContent.isEmpty()) {
                    rsaPublicKey = loadPublicKey(publicKeyContent);
                }
            }
        } catch (Exception e) {
            log.warn("RSA 密钥加载失败: {}", e.getMessage());
        }
    }

    /**
     * 读取密钥文件内容
     */
    private String readKeyContent(Resource resource) throws Exception {
        try (BufferedReader reader = new BufferedReader(
                new InputStreamReader(resource.getInputStream(), StandardCharsets.UTF_8))) {
            return reader.lines().collect(Collectors.joining("\n"));
        }
    }

    /**
     * 加载 RSA 私钥
     */
    private PrivateKey loadPrivateKey(String keyContent) throws Exception {
        String privateKeyPEM = keyContent
                .replace("-----BEGIN PRIVATE KEY-----", "")
                .replace("-----END PRIVATE KEY-----", "")
                .replaceAll("\\s", "");

        byte[] encoded = Decoders.BASE64.decode(privateKeyPEM);
        PKCS8EncodedKeySpec keySpec = new PKCS8EncodedKeySpec(encoded);
        KeyFactory keyFactory = KeyFactory.getInstance("RSA");
        return keyFactory.generatePrivate(keySpec);
    }

    /**
     * 加载 RSA 公钥
     */
    private PublicKey loadPublicKey(String keyContent) throws Exception {
        String publicKeyPEM = keyContent
                .replace("-----BEGIN PUBLIC KEY-----", "")
                .replace("-----END PUBLIC KEY-----", "")
                .replaceAll("\\s", "");

        byte[] encoded = Decoders.BASE64.decode(publicKeyPEM);
        X509EncodedKeySpec keySpec = new X509EncodedKeySpec(encoded);
        KeyFactory keyFactory = KeyFactory.getInstance("RSA");
        return keyFactory.generatePublic(keySpec);
    }

    /**
     * 初始化 HMAC 密钥
     */
    private void initHmacKey() {
        // 生成随机密钥或使用固定密钥（生产环境应使用配置）
        String secret = UUID.randomUUID().toString() + UUID.randomUUID().toString();
        hmacKey = Keys.hmacShaKeyFor(secret.getBytes(StandardCharsets.UTF_8));
        log.info("JWT 使用 HS256 (HMAC-SHA256) 算法，已生成随机密钥");
    }

    /**
     * 获取签名密钥
     */
    private Key getSigningKey() {
        return useRsa ? rsaPrivateKey : hmacKey;
    }

    /**
     * 获取验证密钥
     */
    private Key getValidationKey() {
        return useRsa ? rsaPublicKey : hmacKey;
    }

    /**
     * 签发 Access Token
     *
     * @param userId   用户ID
     * @param tenantId 租户ID
     * @param username 用户名
     * @param roles    角色列表
     * @return JWT Token
     */
    public String generateAccessToken(String userId, Long tenantId, String username, List<String> roles) {
        return generateAccessToken(userId, tenantId, username, roles, List.of());
    }

    /**
     * 签发 Access Token（含细粒度权限）
     */
    public String generateAccessToken(String userId, Long tenantId, String username, List<String> roles, List<String> permissions) {
        Instant now = Instant.now();
        Instant expiration = now.plusSeconds(accessTokenExpiration);

        return Jwts.builder()
                .subject(userId)
                .claim(CLAIM_USER_ID, userId)
                .claim(CLAIM_TENANT_ID, tenantId)
                .claim(CLAIM_USERNAME, username)
                .claim(CLAIM_ROLES, roles)
                .claim(CLAIM_PERMISSIONS, permissions)
                .claim(CLAIM_TOKEN_TYPE, TOKEN_TYPE_ACCESS)
                .issuedAt(Date.from(now))
                .expiration(Date.from(expiration))
                .id(UUID.randomUUID().toString())
                .audience()
                    .add("migao")
                    .and()
                .signWith(getSigningKey())
                .compact();
    }

    /**
     * 签发 Refresh Token
     *
     * @param userId   用户ID
     * @param tenantId 租户ID
     * @return JWT Token
     */
    public String generateRefreshToken(String userId, Long tenantId) {
        Instant now = Instant.now();
        Instant expiration = now.plusSeconds(refreshTokenExpiration);

        return Jwts.builder()
                .subject(userId)
                .claim(CLAIM_USER_ID, userId)
                .claim(CLAIM_TENANT_ID, tenantId)
                .claim(CLAIM_TOKEN_TYPE, TOKEN_TYPE_REFRESH)
                .issuedAt(Date.from(now))
                .expiration(Date.from(expiration))
                .id(UUID.randomUUID().toString())
                .audience()
                    .add("migao")
                    .and()
                .signWith(getSigningKey())
                .compact();
    }

    /**
     * 验证并解析 Token
     *
     * @param token JWT Token
     * @return Claims
     */
    public Claims validateAndParseToken(String token) {
        try {
            var parserBuilder = Jwts.parser();
            if (useRsa) {
                return parserBuilder
                        .verifyWith(rsaPublicKey)
                        .build()
                        .parseSignedClaims(token)
                        .getPayload();
            } else {
                return parserBuilder
                        .verifyWith(hmacKey)
                        .build()
                        .parseSignedClaims(token)
                        .getPayload();
            }
        } catch (ExpiredJwtException e) {
            log.warn("JWT Token 已过期");
            throw e;
        } catch (JwtException e) {
            log.warn("JWT Token 验证失败: {}", e.getMessage());
            throw e;
        }
    }

    /**
     * 获取用于解析器的验证密钥
     */
    private SecretKey getValidationKeyForParser() {
        if (useRsa) {
            // RSA 使用公钥验证，但 JJWT 的 verifyWith 需要 SecretKey
            // 所以我们使用 parser 的 setSigningKey 方法
            return null;
        }
        return hmacKey;
    }

    /**
     * 验证 Token 是否有效
     *
     * @param token JWT Token
     * @return 是否有效
     */
    public boolean validateToken(String token) {
        try {
            validateAndParseToken(token);
            return true;
        } catch (ExpiredJwtException e) {
            log.debug("JWT Token 已过期");
            return false;
        } catch (JwtException | IllegalArgumentException e) {
            log.warn("JWT Token 验证失败: {}", e.getMessage());
            return false;
        }
    }

    /**
     * 从 Token 中提取 Claims
     *
     * @param token JWT Token
     * @return Claims
     */
    public Claims getClaimsFromToken(String token) {
        return validateAndParseToken(token);
    }

    /**
     * 从 Token 中提取用户ID
     *
     * @param token JWT Token
     * @return 用户ID
     */
    public String getUserIdFromToken(String token) {
        Claims claims = getClaimsFromToken(token);
        return claims.get(CLAIM_USER_ID, String.class);
    }

    /**
     * 从 Token 中提取租户ID
     *
     * @param token JWT Token
     * @return 租户ID
     */
    public Long getTenantIdFromToken(String token) {
        Claims claims = getClaimsFromToken(token);
        Object tenantIdObj = claims.get(CLAIM_TENANT_ID);
        if (tenantIdObj instanceof Number) {
            return ((Number) tenantIdObj).longValue();
        }
        return tenantIdObj != null ? Long.valueOf(tenantIdObj.toString()) : null;
    }

    /**
     * 从 Token 中提取用户名
     *
     * @param token JWT Token
     * @return 用户名
     */
    public String getUsernameFromToken(String token) {
        Claims claims = getClaimsFromToken(token);
        return claims.get(CLAIM_USERNAME, String.class);
    }

    /**
     * 从 Token 中提取角色列表
     *
     * @param token JWT Token
     * @return 角色列表
     */
    @SuppressWarnings("unchecked")
    public List<String> getRolesFromToken(String token) {
        Claims claims = getClaimsFromToken(token);
        return claims.get(CLAIM_ROLES, List.class);
    }

    /**
     * 从 Token 中提取 Token 类型
     *
     * @param token JWT Token
     * @return Token 类型
     */
    public String getTokenType(String token) {
        Claims claims = getClaimsFromToken(token);
        return claims.get(CLAIM_TOKEN_TYPE, String.class);
    }

    /**
     * 判断 Token 是否为 Access Token
     *
     * @param token JWT Token
     * @return 是否为 Access Token
     */
    public boolean isAccessToken(String token) {
        return TOKEN_TYPE_ACCESS.equals(getTokenType(token));
    }

    /**
     * 判断 Token 是否为 Refresh Token
     *
     * @param token JWT Token
     * @return 是否为 Refresh Token
     */
    public boolean isRefreshToken(String token) {
        return TOKEN_TYPE_REFRESH.equals(getTokenType(token));
    }

    /**
     * 获取 Token 过期时间（毫秒）
     *
     * @param token JWT Token
     * @return 过期时间
     */
    public Date getExpirationDate(String token) {
        Claims claims = getClaimsFromToken(token);
        return claims.getExpiration();
    }

    /**
     * 检查 Token 是否即将过期
     *
     * @param token       JWT Token
     * @param thresholdMs 阈值（毫秒）
     * @return 是否即将过期
     */
    public boolean isTokenExpiringSoon(String token, long thresholdMs) {
        Date expiration = getExpirationDate(token);
        return (expiration.getTime() - System.currentTimeMillis()) < thresholdMs;
    }

    /**
     * 刷新 Access Token
     *
     * @param refreshToken Refresh Token
     * @param username     用户名
     * @param roles        角色列表
     * @return 新的 Access Token
     */
    public String refreshAccessToken(String refreshToken, String username, List<String> roles) {
        if (!validateToken(refreshToken) || !isRefreshToken(refreshToken)) {
            throw new IllegalArgumentException("无效的 Refresh Token");
        }

        Claims claims = getClaimsFromToken(refreshToken);
        String userId = claims.get(CLAIM_USER_ID, String.class);
        Object tenantIdObj = claims.get(CLAIM_TENANT_ID);
        Long tenantId = tenantIdObj instanceof Number ? ((Number) tenantIdObj).longValue() : Long.valueOf(tenantIdObj.toString());

        return generateAccessToken(userId, tenantId, username, roles);
    }
}
