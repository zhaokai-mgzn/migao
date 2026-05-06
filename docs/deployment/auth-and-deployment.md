# 认证服务设计与阿里云部署

> 版本：v8.0（2 服务架构 + 公众号 OAuth + 客服员工工作台 + 自建 RAG + CRM 客户管理）  
> 日期：2026-04-12  
> 变更：认证合并到 admin-api；ai-chat + ai-admin 合并为 ai-agent；百炼知识库迁移至 DashVector 自建 RAG

---

## 1. 认证服务架构

### 1.1 服务职责

认证功能已合并到 admin-api（Java Spring Boot 3），统一部署到单个 SAE 应用：

```
admin-api/ (Java Spring Boot 3)
├── 认证模块
│   ├── 微信小程序登录（C 端）
│   ├── 微信公众号 OAuth 扫码登录（C 端，测试用）
│   ├── 客服员工登录（小程序 + PC H5）（新增）│   ├── 企业账号密码登录（管理端）
│   ├── JWT Token 生成与验证
│   └── 用户身份管理
├── 管理后台业务模块
│   ├── 商品管理
│   ├── 订单管理
│   ├── 租户管理
│   └── 租户 AI 配置管理（新增）
└── AI 网关模块（新增）
    └── 调用 ai-agent-service（HTTP/gRPC）
```

### 1.2 目录结构

```
admin-api/
├── src/main/java/com/ai_customer_service/
│   ├── auth/                          # 认证模块
│   │   ├── controller/
│   │   │   ├── MiniLoginController.java      # 微信小程序登录
│   │   │   ├── H5OAuthController.java        # 公众号 OAuth（新增）
│   │   │   ├── AgentAuthController.java      # 客服员工登录（新增）
│   │   │   ├── AccountLoginController.java   # 账号密码登录
│   │   │   └── AuthInternalController.java   # 内部 Token 验证
│   │   ├── service/
│   │   │   ├── AuthenticationService.java    # 统一认证服务
│   │   │   ├── WeChatMiniService.java        # 微信 code2Session
│   │   │   ├── WeChatH5Service.java          # 公众号 OAuth（新增）
│   │   │   ├── AgentEmployeeService.java     # 客服员工管理（新增）
│   │   │   └── JwtService.java               # RS256 JWT 签发/验证
│   │   ├── client/
│   │   │   └── WeChatApiClient.java          # 微信开放平台 HTTP 客户端
│   │   ├── config/
│   │   │   ├── WeChatMiniConfig.java         # 小程序 AppID/AppSecret
│   │   │   ├── WeChatH5Config.java           # 公众号 AppID/AppSecret（新增）
│   │   │   └── JwtConfig.java                # RS256 密钥配置
│   │   └── model/
│   │       ├── WeChatMiniLoginRequest.java
│   │       ├── WeChatH5OAuthRequest.java
│   │       ├── AgentEmployeeLoginRequest.java
│   │       └── AccountLoginRequest.java
│   ├── admin/                         # 管理后台业务模块
│   │   ├── controller/
│   │   │   ├── ProductController.java
│   │   │   ├── OrderController.java
│   │   │   └── TenantController.java
│   │   └── service/
│   │       ├── ProductService.java
│   │       ├── OrderService.java
│   │       └── TenantService.java
│   ├── common/                        # 公共模块
│   │   ├── config/
│   │   │   ├── RedisConfig.java
│   │   │   ├── DatabaseConfig.java
│   │   │   └── CorsConfig.java
│   │   ├── middleware/
│   │   │   ├── TenantIsolationFilter.java   # 租户隔离
│   │   │   ├── JwtAuthenticationFilter.java # JWT 认证
│   │   │   └── ReplayProtectionFilter.java  # 防重放
│   │   └── security/
│   │       ├── RateLimiter.java
│   │       └── InternalAuthVerifier.java    # 内部服务 HMAC 验证
│   └── AiCustomerServiceApplication.java
├── src/main/resources/
│   ├── application.yml
│   └── keys/
│       ├── private.pem              # RS256 私钥（仅 admin-api 持有）
│       └── public.pem               # RS256 公钥（分发给其他服务）
├── pom.xml
├── Dockerfile
└── .env.example
```

### 1.3 API 接口

```
# 微信小程序登录（C 端，公开接口）
POST /api/auth/mini/login          # { code, tenant_id } → { token, user }

# 微信公众号 OAuth（C 端，测试用，公开接口）
GET  /api/auth/h5/authorize        # { tenant_code, redirect_uri } → 302 跳转微信授权页
GET  /api/auth/h5/callback         # ?code=xxx&state=xxx → Set-Cookie + 302 跳转 H5 页

# 账号密码登录（管理端，公开接口）
POST /api/auth/account/login       # { phone, password, tenant_code } → Set-Cookie + { user }
POST /api/auth/account/logout      # 吊销 JWT + 清除 Cookie
POST /api/auth/account/refresh     # 刷新 Token

# 用户信息（需认证）
GET  /api/auth/me
PUT  /api/auth/me

# 租户 AI 配置管理（仅管理员，需认证）
GET    /api/admin/tenant/ai-config  # 获取当前租户 AI 配置
PUT    /api/admin/tenant/ai-config  # 更新 AI 配置（自我介绍、营业时间、转人工关键词等）

# 客服员工认证（新增）
POST   /api/auth/agent/invite       # 管理员邀请员工（仅管理员）
POST   /api/auth/agent/login        # 员工扫码登录（小程序）
GET    /api/auth/agent/h5/authorize # PC H5 扫码登录
PUT    /api/agent/status            # 设置在线/离线状态（员工）
GET    /api/agent/status            # 获取当前状态（员工）
GET    /api/agent/sessions          # 获取会话列表（员工）
POST   /api/agent/sessions/{id}/messages  # 发送消息（员工）
POST   /api/agent/sessions/{id}/end       # 结束会话（员工）

# 内部 Token 验证（仅 VPC 内网，不暴露公网）
POST /api/auth/internal/verify     # { token } → { valid, payload }

# 管理后台业务（需认证）
GET  /api/admin/products
GET  /api/admin/orders
POST /api/admin/tenants
...
```

> 多端共用同一套 JWT 和业务服务。详见 [多租户多端架构](./multi-tenant-multi-platform.md)。

### 1.4 登录安全机制

> **安全要求**：小程序登录必须实现 code 防重放（每个 code 只能使用一次），管理端账号密码登录需防暴力破解。

**小程序登录安全机制**：

```java
// src/main/java/com/ai_customer_service/auth/service/WeChatMiniService.java

@Service
@RequiredArgsConstructor
public class WeChatMiniService {
    
    private final StringRedisTemplate redisTemplate;
    private final WeChatApiClient weChatApiClient;
    
    /**
     * 校验 code 是否有效（防止重复使用）
     */
    public boolean validateCode(String code) {
        String codeKey = "wechat_mini:used_code:" + code;
        return Boolean.FALSE.equals(redisTemplate.hasKey(codeKey));
    }
    
    /**
     * 标记 code 已使用（5 分钟过期）
     */
    public void markCodeUsed(String code) {
        String codeKey = "wechat_mini:used_code:" + code;
        redisTemplate.opsForValue().set(codeKey, "1", Duration.ofMinutes(5));
    }
    
    /**
     * 微信小程序 code2Session
     */
    public WeChatMiniUser code2Session(String code) {
        WeChatSessionResponse resp = weChatApiClient.code2Session(code);
        if (resp.getErrcode() != null && resp.getErrcode() != 0) {
            throw new WeChatApiException("微信 code2Session 失败: " + resp.getErrmsg());
        }
        return WeChatMiniUser.builder()
                .openid(resp.getOpenid())
                .sessionKey(resp.getSessionKey())
                .unionid(resp.getUnionid())
                .build();
    }
}
```

**微信公众号 OAuth 服务（测试用）**：

```java
// src/main/java/com/ai_customer_service/auth/service/WeChatH5Service.java

@Service
@RequiredArgsConstructor
public class WeChatH5Service {
    
    private final WeChatApiClient weChatApiClient;
    
    /**
     * 构建 OAuth 授权跳转 URL
     * @param appId 公众号 AppID
     * @param redirectUri 授权回调地址（需在微信公众平台配置）
     * @param state 状态参数（含 tenant_code）
     */
    public String buildOAuthUrl(String appId, String redirectUri, String state) {
        return "https://open.weixin.qq.com/connect/oauth2/authorize"
                + "?appid=" + appId
                + "&redirect_uri=" + URLEncoder.encode(redirectUri, "UTF-8")
                + "&response_type=code"
                + "&scope=snsapi_userinfo"  // 需要用户授权获取昵称等信息
                + "&state=" + state
                + "#wechat_redirect";
    }
    
    /**
     * OAuth 回调处理：用 code 换取 access_token 和用户信息
     * @param code 微信授权回调返回的临时 code
     */
    public WeChatH5User getAccessToken(String code, String appId, String appSecret) {
        // 第一步：用 code 换取 access_token + openid
        WeChatTokenResponse tokenResp = weChatApiClient.oauthAccessToken(code, appId, appSecret);
        if (tokenResp.getErrcode() != null && tokenResp.getErrcode() != 0) {
            throw new WeChatApiException("微信 OAuth token 获取失败: " + tokenResp.getErrmsg());
        }
        
        // 第二步：用 access_token + openid 获取用户信息
        WeChatUserInfo userInfo = weChatApiClient.oauthUserInfo(
                tokenResp.getAccessToken(), tokenResp.getOpenid());
        
        return WeChatH5User.builder()
                .openid(tokenResp.getOpenid())
                .accessToken(tokenResp.getAccessToken())
                .unionid(tokenResp.getUnionid())
                .nickname(userInfo.getNickname())
                .headimgurl(userInfo.getHeadimgurl())
                .build();
    }
}
```

**客服员工登录认证（新增）**：

客服员工通过独立的小程序或 PC H5 登录，使用邀请码 + 微信授权绑定身份：

```java
// src/main/java/com/ai_customer_service/auth/controller/AgentAuthController.java

@RestController
@RequestMapping("/api/auth/agent")
@RequiredArgsConstructor
public class AgentAuthController {
    
    private final AgentEmployeeService agentEmployeeService;
    private final JwtService jwtService;
    
    /**
     * 管理员邀请员工：生成邀请码和二维码
     */
    @PostMapping("/invite")
    public ResponseEntity<?> inviteEmployee(@RequestBody InviteRequest req, 
                                            @AuthenticationPrincipal JwtUser admin) {
        AgentEmployee employee = agentEmployeeService.createEmployee(
                admin.getTenantId(), req.getName(), req.getPhone(), req.getRole());
        return ResponseEntity.ok(Map.of(
                "invite_code", employee.getInviteCode(),
                "invite_qr_url", employee.getInviteQrUrl(),
                "employee_id", employee.getId()
        ));
    }
    
    /**
     * 员工扫码登录（小程序）
     */
    @PostMapping("/login")
    public ResponseEntity<?> login(@RequestBody AgentEmployeeLoginRequest req, 
                                   HttpServletResponse response) {
        // 1. 验证邀请码有效性
        AgentEmployee employee = agentEmployeeService.validateInviteCode(req.getInviteCode());
        
        // 2. 用微信小程序 code 换取 openid
        WeChatMiniUser miniUser = weChatMiniService.code2Session(
                req.getWechatMiniCode(), employee.getTenantId());
        
        // 3. 绑定 openid 到员工账号（首次登录）
        agentEmployeeService.bindWeChat(employee.getId(), miniUser.getOpenid(), miniUser.getUnionid());
        
        // 4. 签发 JWT（role = "agent" 是 C 端身份类型；identity_type = "agent_wechat_mini" 是 user_identities 表的值）
        String token = jwtService.generateToken(
                employee.getUserId(), employee.getTenantId(), 
                "agent", Map.of("employee_id", employee.getId()));
        
        jwtService.setAuthCookie(response, token);
        return ResponseEntity.ok(Map.of(
                "employee", Map.of("id", employee.getId(), "name", employee.getName(), 
                                   "role", employee.getRole(), "status", employee.getStatus())
        ));
    }
    
    /**
     * 员工状态管理（在线/离线/忙碌）
     */
    @PutMapping("/status")
    public ResponseEntity<?> updateStatus(@RequestBody UpdateStatusRequest req,
                                          @AuthenticationPrincipal JwtUser user) {
        agentEmployeeService.updateStatus(user.getEmployeeId(), req.getStatus());
        return ResponseEntity.ok(Map.of("message", "状态已更新"));
    }
}
```

```java
// src/main/java/com/ai_customer_service/auth/service/AgentEmployeeService.java

@Service
@RequiredArgsConstructor
public class AgentEmployeeService {
    
    private final AgentEmployeeRepository repository;
    private final UserRepository userRepository;
    private final StringRedisTemplate redisTemplate;
    
    /**
     * 创建客服员工（生成唯一邀请码）
     */
    @Transactional
    public AgentEmployee createEmployee(String tenantId, String name, String phone, String role) {
        // 创建或查找关联用户
        User user = userRepository.findByPhoneAndTenantId(phone, tenantId)
                .orElseGet(() -> userRepository.createUser(phone, tenantId, "agent"));
        
        // 生成唯一邀请码
        String inviteCode;
        do {
            inviteCode = "INV_" + RandomStringUtils.randomAlphanumeric(8).toUpperCase();
        } while (repository.existsByInviteCode(inviteCode));
        
        AgentEmployee employee = new AgentEmployee();
        employee.setTenantId(tenantId);
        employee.setUserId(user.getId());
        employee.setName(name);
        employee.setPhone(phone);
        employee.setRole(role);
        employee.setInviteCode(inviteCode);
        employee.setInviteQrUrl("https://migaozn.com/q/" + inviteCode);
        
        return repository.save(employee);
    }
    
    /**
     * 验证邀请码
     */
    public AgentEmployee validateInviteCode(String inviteCode) {
        return repository.findByInviteCode(inviteCode)
                .orElseThrow(() -> new InvalidInviteCodeException("邀请码无效或已过期"));
    }
    
    /**
     * 绑定微信 openid 到员工账号
     */
    @Transactional
    public void bindWeChat(String employeeId, String openid, String unionid) {
        AgentEmployee employee = repository.findById(employeeId)
                .orElseThrow(() -> new EmployeeNotFoundException("员工不存在"));
        
        // 创建或更新 user_identity
        UserIdentity identity = new UserIdentity();
        identity.setUserId(employee.getUserId());
        identity.setTenantId(employee.getTenantId());
        identity.setIdentityType("agent_wechat_mini");
        identity.setExternalId(openid);
        identity.setExternalUnionId(unionid);
        
        userRepository.saveIdentity(identity);
    }
    
    /**
     * 更新员工状态（online / busy / offline）
     */
    @Transactional
    public void updateStatus(String employeeId, String status) {
        repository.updateStatus(employeeId, status);
        // 广播状态变更到 WebSocket 网关
        redisTemplate.convertAndSend("agent:status:change", 
                Map.of("employee_id", employeeId, "status", status));
    }
}
```

**租户小程序配置**：

```java
// src/main/java/com/ai_customer_service/common/config/TenantMiniProgramConfig.java

@Service
@RequiredArgsConstructor
public class TenantMiniProgramConfig {
    
    private final StringRedisTemplate redisTemplate;
    private final TenantMiniProgramRepository repository;
    
    /**
     * 获取租户的小程序 AppID/AppSecret（带缓存）
     */
    public TenantMiniProgram getTenantMiniProgram(String tenantId) {
        String cacheKey = "tenant:miniprogram:" + tenantId;
        String cached = redisTemplate.opsForValue().get(cacheKey);
        if (cached != null) {
            return parseFromCache(cached);
        }
        
        TenantMiniProgram config = repository.findByTenantId(tenantId)
                .orElseThrow(() -> new TenantNotFoundException("租户小程序配置不存在"));
        
        redisTemplate.opsForValue().set(cacheKey, serialize(config), Duration.ofMinutes(5));
        return config;
    }
}
```

### 1.5 微信开放平台 HTTP 客户端

```java
// src/main/java/com/ai_customer_service/auth/client/WeChatApiClient.java

@Component
@RequiredArgsConstructor
public class WeChatApiClient {
    
    private final RestTemplate restTemplate;
    
    @Value("${wechat.mini.appid}")
    private String appid;
    
    @Value("${wechat.mini.appsecret}")
    private String appsecret;
    
    private static final String BASE_URL = "https://api.weixin.qq.com";
    
    /**
     * 用小程序 code 换取 openid 和 session_key
     * @param code wx.login() 获取的临时登录凭证，5 分钟有效，只能使用一次
     */
    public WeChatSessionResponse code2Session(String code) {
        String url = BASE_URL + "/sns/jscode2session"
                + "?appid=" + appid
                + "&secret=" + appsecret
                + "&js_code=" + code
                + "&grant_type=authorization_code";
        
        return restTemplate.getForObject(url, WeChatSessionResponse.class);
    }
    
    /**
     * 获取用户手机号（需要用户授权）
     * @param accessToken 接口调用凭证
     * @param phoneCode 小程序端 wx.getPhoneNumber() 返回的 code
     */
    public PhoneNumberResponse getPhoneNumber(String accessToken, String phoneCode) {
        String url = BASE_URL + "/wxa/business/getuserphonenumber?access_token=" + accessToken;
        
        Map<String, String> body = Map.of("code", phoneCode);
        return restTemplate.postForObject(url, body, PhoneNumberResponse.class);
    }
}
```

### 1.6 统一认证服务

```java
// src/main/java/com/ai_customer_service/auth/service/AuthenticationService.java

@Service
@RequiredArgsConstructor
public class AuthenticationService {
    
    private final JwtService jwtService;
    private final WeChatMiniService weChatMiniService;
    private final UserRepository userRepository;
    private final TenantRepository tenantRepository;
    
    /**
     * 微信小程序登录
     */
    @Transactional
    public AuthResult authenticateWechatMini(String code, String tenantId) {
        // 1. 校验 code 是否已被使用（防重放）
        if (!weChatMiniService.validateCode(code)) {
            throw new AuthenticationException("登录凭证已使用，请重新登录");
        }
        
        // 2. 调用微信 code2Session 获取 openid
        WeChatMiniUser miniUser = weChatMiniService.code2Session(code);
        
        // 3. 标记 code 已使用（防止重复使用）
        weChatMiniService.markCodeUsed(code);
        
        // 4. 查找或创建用户
        User user = findOrCreateUser(
                "wechat_mini",
                miniUser.getOpenid(),
                miniUser.getUnionid(),
                tenantId
        );
        
        // 5. 生成 JWT
        String token = jwtService.generateToken(user);
        
        return new AuthResult(user, token);
    }
    
    /**
     * 微信公众号 OAuth 登录（测试用）
     */
    @Transactional
    public AuthResult authenticateWechatH5(String code, String tenantId) {
        // 1. 调用微信 OAuth 获取 access_token 和用户信息
        WeChatH5Config h5Config = weChatH5ConfigService.getConfigByTenantId(tenantId);
        WeChatH5User h5User = weChatH5Service.getAccessToken(
                code, h5Config.getAppId(), h5Config.getAppSecret());
        
        // 2. 查找或创建用户（通过 unionid 关联小程序用户）
        User user = findOrCreateUser(
                "wechat_h5",
                h5User.getOpenid(),
                h5User.getUnionid(),
                tenantId
        );
        
        // 3. 更新用户昵称和头像（如果 OAuth 返回了）
        if (h5User.getNickname() != null) {
            user.setNickname(h5User.getNickname());
        }
        if (h5User.getHeadimgurl() != null) {
            user.setAvatar(h5User.getHeadimgurl());
        }
        userRepository.save(user);
        
        // 4. 生成 JWT
        String token = jwtService.generateToken(user);
        
        return new AuthResult(user, token);
    }
    
    /**
     * 企业账号密码登录
     */
    @Transactional
    public AuthResult authenticateAccount(String phone, String password, String tenantCode) {
        Tenant tenant = tenantRepository.findByCode(tenantCode)
                .orElseThrow(() -> new AuthenticationException("租户不存在"));
        
        User user = userRepository.findByTenantIdAndPhone(tenant.getId(), phone)
                .orElseThrow(() -> new AuthenticationException("账号或密码错误"));
        
        if (!passwordEncoder.matches(password, user.getPasswordHash())) {
            throw new AuthenticationException("账号或密码错误");
        }
        
        String token = jwtService.generateToken(user);
        return new AuthResult(user, token);
    }
    
    /**
     * 查找或创建用户（支持 unionid 跨平台识别）
     */
    private User findOrCreateUser(String identityType, String externalId, 
                                   String unionid, String tenantId) {
        // 优先通过 unionid 查找（跨平台同用户）
        if (unionid != null) {
            Optional<User> existing = userRepository.findByUnionid(unionid);
            if (existing.isPresent()) return existing.get();
        }
        
        // 其次通过 openid 查找
        Optional<User> existing = userRepository
                .findByIdentityTypeAndExternalId(identityType, externalId);
        if (existing.isPresent()) return existing.get();
        
        // 创建新用户
        User newUser = User.builder()
                .identityType(identityType)
                .externalId(externalId)
                .unionid(unionid)
                .tenantId(tenantId)
                .nickname(externalId.length() > 16 ? externalId.substring(0, 16) : externalId)
                .role("customer")
                .build();
        
        return userRepository.save(newUser);
    }
}
```

### 1.7 JWT 服务（RS256 非对称签名）

```java
// src/main/java/com/ai_customer_service/auth/service/JwtService.java

@Service
public class JwtService {
    
    private final PrivateKey privateKey;
    private final PublicKey publicKey;
    
    public JwtService(@Value("${jwt.private-key-path}") String privateKeyPath,
                      @Value("${jwt.public-key-path}") String publicKeyPath) throws Exception {
        // 加载 RS256 私钥
        byte[] privateKeyBytes = Files.readAllBytes(Paths.get(privateKeyPath));
        this.privateKey = KeyFactory.getInstance("RSA")
                .generatePrivate(new PKCS8EncodedKeySpec(Base64.getDecoder()
                        .decode(new String(privateKeyBytes)
                                .replace("-----BEGIN PRIVATE KEY-----", "")
                                .replace("-----END PRIVATE KEY-----", "")
                                .replaceAll("\\s", ""))));
        
        // 加载 RS256 公钥
        byte[] publicKeyBytes = Files.readAllBytes(Paths.get(publicKeyPath));
        this.publicKey = KeyFactory.getInstance("RSA")
                .generatePublic(new X509EncodedKeySpec(Base64.getDecoder()
                        .decode(new String(publicKeyBytes)
                                .replace("-----BEGIN PUBLIC KEY-----", "")
                                .replace("-----END PUBLIC KEY-----", "")
                                .replaceAll("\\s", ""))));
    }
    
    /**
     * 生成 JWT Token
     * - 算法：RS256（非对称签名，私钥签发 / 公钥验证）
     * - 包含 iss, aud, jti 标准字段
     */
    public String generateToken(User user) {
        Date now = new Date();
        Date expiry = new Date(now.getTime() + user.getSessionTtl() * 1000L);
        
        return Jwts.builder()
                .setIssuer("admin-api")
                .setAudience("youke")
                .setSubject(user.getUserId())
                .claim("tenant_id", user.getTenantId())
                .claim("identity_type", user.getIdentityType())
                .claim("role", user.getRole())
                .setId(UUID.randomUUID().toString())
                .setIssuedAt(now)
                .setExpiration(expiry)
                .signWith(privateKey, SignatureAlgorithm.RS256)
                .compact();
    }
    
    /**
     * 验证 Token
     */
    public Claims verifyToken(String token) {
        try {
            return Jwts.parserBuilder()
                    .setSigningKey(publicKey)
                    .setAllowedClockSkewSeconds(30)
                    .build()
                    .parseClaimsJws(token)
                    .getBody();
        } catch (ExpiredJwtException e) {
            throw new AuthenticationException("Token 已过期");
        } catch (JwtException e) {
            throw new AuthenticationException("Token 无效");
        }
    }
}
```

---

## 2. 阿里云部署配置

### 2.1 微信小程序与域名配置

**微信小程序配置**：
1. 登录 [微信公众平台](https://mp.weixin.qq.com/) → 小程序
2. 开发管理 → 开发设置 → 获取 AppID 和 AppSecret
3. 服务器域名 → request 合法域名：`https://api.migaozn.com`
4. 如果需获取手机号：接口权限 → 开通"获取手机号"权限
5. 域名必须已 ICP 备案

### 2.2 API Gateway 路由配置

```yaml
# API Gateway 路由规则
# 注意：路由按优先级从高到低排列，具体路径必须在通配路径之前

# 认证接口（公开 — 不需要认证）
- path: /api/auth/mini/login
  method: POST
  backend: admin-api
  auth: false

- path: /api/auth/h5/authorize
  method: GET
  backend: admin-api
  auth: false

- path: /api/auth/h5/callback
  method: GET
  backend: admin-api
  auth: false

- path: /api/auth/account/login
  method: POST
  backend: admin-api
  auth: false

- path: /api/auth/account/refresh
  method: POST
  backend: admin-api
  auth: false

# 认证接口（需要认证）
- path: /api/auth/account/logout
  method: POST
  backend: admin-api
  auth: true

- path: /api/auth/me
  method: [GET, PUT]
  backend: admin-api
  auth: true

# 租户 AI 配置管理（仅管理员）
- path: /api/admin/tenant/ai-config
  method: [GET, PUT]
  backend: admin-api
  auth: true
  required_role: admin

# 内部接口（仅 VPC 内访问，API Gateway 不暴露）
# /api/auth/internal/* → 不配置公网路由

# AI Agent 服务（C 端对话 + 管理端 AI 助手，共用）
- path: /api/chat/*
  method: ALL
  backend: ai-agent-service
  auth: true

# AI 管理助手（必须在 /api/admin/* 之前，优先级更高）
- path: /api/admin/ai/*
  method: ALL
  backend: ai-agent-service
  auth: true

# Java 管理后端（通配兜底，含认证 + 管理业务 + AI 配置）
- path: /api/admin/*
  method: ALL
  backend: admin-api
  auth: true
```

### 2.3 SAE 环境变量

**admin-api 环境变量（含认证 + 管理业务）**：

```bash
# 数据库
DATABASE_URL=jdbc:postgresql://pgm-xxx.pg.rds.aliyuncs.com:5432/ai_customer_service
DB_USERNAME=app_user
DB_PASSWORD=your-db-password

# Redis（必须包含密码）
REDIS_HOST=r-xxx.redis.rds.aliyuncs.com
REDIS_PORT=6379
REDIS_PASSWORD=your-redis-password

# JWT RS256 密钥对（非对称签名）
JWT_PRIVATE_KEY_PATH=/app/keys/private.pem   # 仅 admin-api 持有
JWT_PUBLIC_KEY_PATH=/app/keys/public.pem     # 公钥分发给其他服务

# 内部服务认证密钥（HMAC 签名）
INTERNAL_SERVICE_SECRET=<GENERATE_WITH: openssl rand -hex 32>

# CORS 允许域名（逗号分隔）
CORS_ALLOWED_ORIGINS=https://admin.migaozn.com

# Cookie 域名
COOKIE_DOMAIN=.migaozn.com

# 微信小程序
WECHAT_MINI_APPID=wx-your-mini-app-id
WECHAT_MINI_APPSECRET=wx-your-mini-app-secret

# 服务配置
SERVICE_NAME=admin-api
SPRING_PROFILES_ACTIVE=production
LOG_LEVEL=INFO
```

**ai-agent-service 环境变量**：

```bash
# 数据库
DATABASE_URL=jdbc:postgresql://pgm-xxx.pg.rds.aliyuncs.com:5432/ai_customer_service

# Redis（必须包含密码）
REDIS_HOST=r-xxx.redis.rds.aliyuncs.com
REDIS_PORT=6379
REDIS_PASSWORD=your-redis-password

# 百炼
DASHSCOPE_API_KEY=sk-your-api-key

# 内部服务认证密钥（与 admin-api 共享）
INTERNAL_SERVICE_SECRET=<与 admin-api 相同>

# JWT 公钥路径（用于本地验证，可选）
JWT_PUBLIC_KEY_PATH=/app/keys/public.pem

# Hermes Agent
HERMES_AGENT_TYPE=customer_service
SERVICE_TYPE=chat
```

### 2.4 前端登录流程实现

> **安全要求**：管理后台的 JWT 通过 HttpOnly Cookie 传递，前端不直接接触 Token，防止 XSS 窃取。小程序端使用 `wx.setStorageSync` 存储 Token，请求时放入 Authorization Header。

**登录流程 — 微信小程序（C 端）**：

```
小程序端                   admin-api                        微信服务器
  │                              │                              │
  │ 1. wx.login() 获取 code      │                              │
  │ ────────────────────────────>│                              │
  │  POST /api/auth/mini/login   │                              │
  │  { code, tenant_id }         │                              │
  │                              │                              │
  │                              │ 2. code2Session              │
  │                              │ ────────────────────────────>│
  │                              │    返回 openid + session_key │
  │                              │ <────────────────────────────│
  │                              │                              │
  │                              │ 3. 创建/更新用户 → 生成 JWT  │
  │ <────────────────────────────│                              │
  │  { token: "jwt_xxx", user }  │                              │
  │                              │                              │
  │ 4. wx.setStorageSync('token')│
```

**登录流程 — 微信公众号 OAuth 扫码（C 端，测试用）**：

```
H5 浏览器                    admin-api                        微信服务器
  │                              │                              │
  │ 1. 扫描二维码 → 跳转授权     │                              │
  │ ────────────────────────────>│                              │
  │  GET /api/auth/h5/authorize  │                              │
  │  { tenant_code, redirect }   │                              │
  │                              │                              │
  │ 2. 302 跳转微信授权页        │                              │
  │ <────────────────────────────│                              │
  │  Location: open.weixin.qq... │                              │
  │                              │                              │
  │ 3. 用户确认授权               │                              │
  │ ────────────────────────────────────────────────────────────>│
  │                              │                              │
  │ 4. 微信回调携带 code          │                              │
  │ ────────────────────────────>│                              │
  │  GET /api/auth/h5/callback   │                              │
  │  ?code=xxx&state=xxx         │                              │
  │                              │ 5. OAuth access_token        │
  │                              │ ────────────────────────────>│
  │                              │    返回 openid + unionid     │
  │                              │    + userinfo                │
  │                              │ <────────────────────────────│
  │                              │                              │
  │                              │ 6. 创建/更新用户 → 生成 JWT  │
  │ <────────────────────────────│                              │
  │  Set-Cookie: access_token    │                              │
  │  302 跳转 H5 客服页          │                              │
```

**登录流程 — 管理后台浏览器（管理端）**：

```
浏览器                     admin-api                   企业数据库
  │                              │                              │
  │ 1. POST /account/login       │                              │
  │    { phone, password,        │                              │
  │      tenant_code }           │                              │
  │ ────────────────────────────>│                              │
  │                              │ 2. 验证账号密码              │
  │                              │ ────────────────────────────>│
  │                              │    返回 user                 │
  │                              │ <────────────────────────────│
  │                              │                              │
  │                              │ 3. 生成 RS256 JWT            │
  │ <────────────────────────────│                              │
  │    Set-Cookie: access_token  │                              │
  │    HttpOnly, Secure, Lax     │                              │
  │                              │                              │
  │ 4. 后续请求自动带 Cookie     │
```

**微信小程序端 - 登录**：

```javascript
// 小程序 app.js 或登录页
// 1. wx.login() 获取临时 code
const loginRes = await wx.login()
const code = loginRes.code

// 2. 调用后端登录接口
const res = await wx.request({
  url: 'https://api.migaozn.com/api/auth/mini/login',
  method: 'POST',
  data: {
    code: code,
    tenant_id: 'TENANT001'
  }
})

// 3. 保存 JWT Token
if (res.data.token) {
  wx.setStorageSync('token', res.data.token)
  // 跳转到对话页
  wx.switchTab({ url: '/pages/chat/index' })
}

// API 请求封装 — 自动携带 Token
async function apiRequest(url, options = {}) {
  const token = wx.getStorageSync('token')
  return wx.request({
    url: `https://api.migaozn.com${url}`,
    header: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    ...options
  })
}
```

**管理前端 - 账号密码登录**：

```typescript
// web/admin/lib/auth.ts

export async function loginWithAccount(phone: string, password: string, tenantCode: string) {
  const response = await fetch('/api/auth/account/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',   // 携带 Cookie
    body: JSON.stringify({ phone, password, tenant_code: tenantCode })
  });
  
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.message || '登录失败');
  }
  
  const { user } = await response.json();
  // Token 已通过 HttpOnly Cookie 设置，无需 localStorage
  
  return user;
}

// axios 拦截器 — 携带 Cookie
axios.defaults.withCredentials = true;
```

---

## 3. 安全加固

### 3.1 CORS 配置

> **原则**：仅允许已知前端域名，禁止 `*` 通配符。

```java
// src/main/java/com/ai_customer_service/common/config/CorsConfig.java

@Configuration
public class CorsConfig {
    
    @Value("${cors.allowed-origins}")
    private String[] allowedOrigins;
    
    @Bean
    public CorsFilter corsFilter() {
        CorsConfiguration config = new CorsConfiguration();
        config.setAllowedOriginPatterns(Arrays.asList(allowedOrigins));
        config.setAllowCredentials(true);
        config.setAllowedMethods(Arrays.asList("GET", "POST", "PUT", "DELETE"));
        config.setAllowedHeaders(Arrays.asList(
                "Content-Type",
                "Authorization",
                "X-Request-Timestamp",
                "X-Request-Nonce"
        ));
        config.setMaxAge(600L);
        
        UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource();
        source.registerCorsConfiguration("/**", config);
        return new CorsFilter(source);
    }
}
```

### 3.2 防重放攻击

> **安全变更**：`X-Request-Timestamp` 和 `X-Request-Nonce` 对认证接口为**必填**，而非可选。

```java
// src/main/java/com/ai_customer_service/common/middleware/ReplayProtectionFilter.java

@Component
public class ReplayProtectionFilter extends OncePerRequestFilter {
    
    private static final List<String> PROTECTED_PATHS = List.of("/api/auth/");
    private static final List<String> EXEMPT_PATHS = List.of("/health", "/api/auth/internal/");
    
    private final StringRedisTemplate redisTemplate;
    
    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response,
                                     FilterChain filterChain) throws ServletException, IOException {
        String path = request.getRequestURI();
        
        // 仅对认证接口启用
        if (PROTECTED_PATHS.stream().noneMatch(path::startsWith)) {
            filterChain.doFilter(request, response);
            return;
        }
        
        // 豁免内部接口
        if (EXEMPT_PATHS.stream().anyMatch(path::startsWith)) {
            filterChain.doFilter(request, response);
            return;
        }
        
        // 强制要求时间戳（必填）
        String timestamp = request.getHeader("X-Request-Timestamp");
        if (timestamp == null) {
            sendError(response, 400, "MISSING_TIMESTAMP", "缺少 X-Request-Timestamp");
            return;
        }
        
        try {
            Instant requestTime = Instant.parse(timestamp);
            if (Math.abs(Duration.between(requestTime, Instant.now()).getSeconds()) > 300) {
                sendError(response, 400, "REQUEST_EXPIRED", "请求已过期（超过5分钟）");
                return;
            }
        } catch (DateTimeParseException e) {
            sendError(response, 400, "INVALID_TIMESTAMP", "时间戳格式错误");
            return;
        }
        
        // 强制要求 nonce（必填）
        String nonce = request.getHeader("X-Request-Nonce");
        if (nonce == null) {
            sendError(response, 400, "MISSING_NONCE", "缺少 X-Request-Nonce");
            return;
        }
        
        String cacheKey = "nonce:" + nonce;
        if (Boolean.TRUE.equals(redisTemplate.hasKey(cacheKey))) {
            sendError(response, 400, "REPLAY_DETECTED", "重复请求");
            return;
        }
        redisTemplate.opsForValue().set(cacheKey, "1", Duration.ofMinutes(5));
        
        filterChain.doFilter(request, response);
    }
    
    private void sendError(HttpServletResponse response, int status, String error, String message)
            throws IOException {
        response.setStatus(status);
        response.setContentType("application/json");
        response.getWriter().write("{\"error\":\"" + error + "\",\"message\":\"" + message + "\"}");
    }
}
```

### 3.3 租户隔离过滤器

> **核心安全规则**：`tenant_id` 始终从 JWT 中获取，禁止通过请求头或请求参数覆盖。

```java
// src/main/java/com/ai_customer_service/common/middleware/TenantIsolationFilter.java

@Component
@Order(1)  // 在 JWT 认证之后执行
public class TenantIsolationFilter extends OncePerRequestFilter {
    
    private final JwtService jwtService;
    
    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response,
                                     FilterChain filterChain) throws ServletException, IOException {
        // 公开接口跳过
        if (isPublicPath(request.getRequestURI())) {
            filterChain.doFilter(request, response);
            return;
        }
        
        // 从 Authorization Header 或 Cookie 中提取 JWT
        String token = extractToken(request);
        if (token == null) {
            response.sendError(HttpServletResponse.SC_UNAUTHORIZED, "UNAUTHORIZED");
            return;
        }
        
        try {
            Claims claims = jwtService.verifyToken(token);
            
            // 注入到 request attribute（后续处理函数从这里读取）
            request.setAttribute("userId", claims.getSubject());
            request.setAttribute("tenantId", claims.get("tenant_id", String.class));
            request.setAttribute("role", claims.get("role", String.class));
            
            filterChain.doFilter(request, response);
        } catch (AuthenticationException e) {
            response.sendError(HttpServletResponse.SC_UNAUTHORIZED, e.getMessage());
        }
    }
    
    private String extractToken(HttpServletRequest request) {
        // 优先从 Authorization header 获取（小程序端）
        String authHeader = request.getHeader("Authorization");
        if (authHeader != null && authHeader.startsWith("Bearer ")) {
            return authHeader.substring(7);
        }
        
        // 其次从 Cookie 获取（管理后台）
        Cookie[] cookies = request.getCookies();
        if (cookies != null) {
            return Arrays.stream(cookies)
                    .filter(c -> "access_token".equals(c.getName()))
                    .findFirst()
                    .map(Cookie::getValue)
                    .orElse(null);
        }
        return null;
    }
    
    private boolean isPublicPath(String path) {
        return List.of(
                "/health",
                "/api/auth/mini/login",
                "/api/auth/account/login",
                "/api/auth/account/refresh"
        ).contains(path);
    }
}
```

**数据库查询示例（强制 tenant_id 过滤）**：

```java
// 所有查询必须带 tenant_id，确保租户隔离
@GetMapping("/api/admin/products")
public List<Product> getProducts(HttpServletRequest request) {
    String tenantId = (String) request.getAttribute("tenantId");  // 从 JWT 中获取，不可伪造
    return productService.findByTenantId(tenantId);
}
```

### 3.4 内部服务认证

> **用途**：ai-agent-service 调用 admin-api 的 `/api/auth/internal/verify` 接口时的身份校验。

```java
// src/main/java/com/ai_customer_service/common/security/InternalAuthVerifier.java

@Component
public class InternalAuthVerifier {
    
    @Value("${internal-service-secret}")
    private String sharedSecret;
    
    /**
     * 生成内部调用签名
     */
    public Map<String, String> generateSignature(String body) {
        String timestamp = String.valueOf(System.currentTimeMillis() / 1000);
        String message = timestamp + ":" + body;
        String signature = hmacSha256(message, sharedSecret);
        return Map.of("timestamp", timestamp, "signature", signature);
    }
    
    /**
     * 验证内部调用签名
     */
    public boolean verifySignature(String timestamp, String body, String signature) {
        // 检查时间窗口（30 秒内有效）
        long requestTime = Long.parseLong(timestamp);
        if (Math.abs(System.currentTimeMillis() / 1000 - requestTime) > 30) {
            return false;
        }
        
        String expected = hmacSha256(timestamp + ":" + body, sharedSecret);
        return MessageDigest.isEqual(expected.getBytes(), signature.getBytes());
    }
    
    private String hmacSha256(String message, String key) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(key.getBytes(), "HmacSHA256"));
            byte[] hash = mac.doFinal(message.getBytes());
            return bytesToHex(hash);
        } catch (Exception e) {
            throw new RuntimeException("HMAC 计算失败", e);
        }
    }
    
    private String bytesToHex(byte[] bytes) {
        StringBuilder sb = new StringBuilder();
        for (byte b : bytes) {
            sb.append(String.format("%02x", b));
        }
        return sb.toString();
    }
}
```

**内部接口验证示例**：

```java
// src/main/java/com/ai_customer_service/auth/controller/AuthInternalController.java

@RestController
@RequestMapping("/api/auth/internal")
public class AuthInternalController {
    
    private final JwtService jwtService;
    private final InternalAuthVerifier verifier;
    
    @PostMapping("/verify")
    public Map<String, Object> internalVerify(
            @RequestHeader("X-Internal-Timestamp") String timestamp,
            @RequestHeader("X-Internal-Signature") String signature,
            @RequestBody Map<String, String> body) {
        
        // 验证内部签名
        if (!verifier.verifySignature(timestamp, body.toString(), signature)) {
            throw new AccessDeniedException("FORBIDDEN");
        }
        
        // 验证 Token
        Claims claims = jwtService.verifyToken(body.get("token"));
        return Map.of(
                "valid", true,
                "payload", Map.of(
                        "sub", claims.getSubject(),
                        "tenant_id", claims.get("tenant_id"),
                        "role", claims.get("role")
                )
        );
    }
}
```

### 3.5 限流配置

```java
// src/main/java/com/ai_customer_service/common/security/RateLimiter.java

@Component
@RequiredArgsConstructor
public class RateLimiter {
    
    private final StringRedisTemplate redisTemplate;
    
    /**
     * 检查是否超过限流阈值
     */
    public boolean isAllowed(String key, int maxRequests, int windowSeconds) {
        String redisKey = "ratelimit:" + key;
        Long count = redisTemplate.opsForValue().increment(redisKey);
        if (count == 1) {
            redisTemplate.expire(redisKey, Duration.ofSeconds(windowSeconds));
        }
        return count <= maxRequests;
    }
}

// 在 Controller 中使用
@PostMapping("/api/auth/account/login")
public ResponseEntity<?> accountLogin(@RequestBody AccountLoginRequest request,
                                       HttpServletRequest httpRequest) {
    String clientIp = getClientIp(httpRequest);
    String key = "login:" + clientIp;
    
    if (!rateLimiter.isAllowed(key, 5, 60)) {  // 每分钟 5 次
        return ResponseEntity.status(429).body(Map.of(
                "error", "RATE_LIMITED",
                "message", "登录尝试过于频繁，请稍后再试"
        ));
    }
    
    // ... 正常登录逻辑
}
```

### 3.6 Token 吊销

```java
// src/main/java/com/ai_customer_service/auth/service/TokenRevocationService.java

@Service
@RequiredArgsConstructor
public class TokenRevocationService {
    
    private final StringRedisTemplate redisTemplate;
    
    /**
     * 吊销 Token（用于登出）
     */
    public void revokeToken(String jti, long ttlSeconds) {
        redisTemplate.opsForValue().set("token:blacklist:" + jti, "1",
                Duration.ofSeconds(ttlSeconds));
    }
    
    /**
     * 检查 Token 是否已吊销
     */
    public boolean isTokenRevoked(String jti) {
        return Boolean.TRUE.equals(redisTemplate.hasKey("token:blacklist:" + jti));
    }
}

// 登出端点
@PostMapping("/api/auth/account/logout")
public ResponseEntity<?> logout(HttpServletRequest request, HttpServletResponse response) {
    String token = extractToken(request);
    if (token != null) {
        try {
            Claims claims = jwtService.verifyToken(token);
            String jti = claims.getId();
            long ttl = claims.getExpiration().getTime() / 1000 - System.currentTimeMillis() / 1000;
            tokenRevocationService.revokeToken(jti, Math.max(ttl, 0));
        } catch (AuthenticationException ignored) {
            // Token 无效也清除 Cookie
        }
    }
    
    Cookie cookie = new Cookie("access_token", null);
    cookie.setPath("/api");
    cookie.setDomain(cookieDomain);
    cookie.setHttpOnly(true);
    cookie.setSecure(true);
    cookie.setMaxAge(0);
    response.addCookie(cookie);
    
    return ResponseEntity.ok(Map.of("success", true));
}
```

---

## 4. 部署检查清单

### 上线前检查

- [ ] 微信小程序 AppID/AppSecret 配置正确
- [ ] 小程序 request 合法域名已配置为 API Gateway 地址
- [ ] admin-api（含认证）部署到 SAE，环境变量配置正确
- [ ] API Gateway 路由配置完成（`/api/auth/mini/login` 不需要认证）
- [ ] RS256 密钥对已生成并挂载到 admin-api 容器
- [ ] JWT 公钥已分发到需要本地验证的服务（ai-agent-service）
- [ ] Redis 启用密码认证
- [ ] RDS 白名单仅允许 VPC 内 IP
- [ ] CORS 仅允许已知前端域名（禁止 `*`）
- [ ] INTERNAL_SERVICE_SECRET 已配置到所有服务
- [ ] HttpOnly Cookie 设置正确（管理后台，secure=true, samesite=Lax）
- [ ] 限流规则配置并测试
- [ ] 端到端小程序登录流程测试通过
- [ ] code 防重放机制测试通过（同一 code 不能使用两次）
- [ ] Token 刷新/销功能测试通过
- [ ] 租户隔离测试（用户 A 无法访问租户 B 数据）

---

## 5. 故障排查

| 问题 | 原因 | 解决方案 |
|------|------|---------|
| 小程序登录失败 | code2Session 返回错误 | 检查 AppID/AppSecret 配置 |
| code 已被使用 | code 重复提交 | 小程序端确保每次 wx.login() 使用新 code |
| JWT 验证失败 | 公私钥不匹配 | 检查 RS256 密钥对是否正确挂载 |
| Token 过期快 | session_ttl 配置错误 | 调整用户表 session_ttl 或环境变量 |
| 跨域错误 | CORS 配置 | 检查 CORS_ALLOWED_ORIGINS 是否包含前端域名 |
| 内部调用 403 | HMAC 签名不匹配 | 检查 INTERNAL_SERVICE_SECRET 是否一致 |
| Cookie 未携带 | SameSite/Domain 配置 | 检查 COOKIE_DOMAIN 和 secure 设置（管理后台）|
| 登录被限流 | 短时间多次尝试 | 等待限流窗口过期，或调整限流规则 |
| admin-api 启动失败 | RS256 密钥文件未找到 | 检查 JWT_PRIVATE_KEY_PATH 环境变量和文件挂载 |
