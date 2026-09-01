package com.migao.admin.service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.dto.RegistrationRequest;
import com.migao.admin.dto.RegistrationResponse;
import com.migao.admin.entity.Tenant;
import com.migao.admin.entity.TenantApplication;
import com.migao.admin.entity.User;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.entity.Permission;
import com.migao.admin.entity.Role;
import com.migao.admin.mapper.PermissionMapper;
import com.migao.admin.mapper.RoleMapper;
import com.migao.admin.mapper.TenantApplicationMapper;
import com.migao.admin.mapper.TenantMapper;
import com.migao.admin.mapper.UserMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.security.SecureRandom;
import java.text.Normalizer;
import java.time.Duration;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.time.OffsetDateTime;
import java.time.temporal.ChronoUnit;
import java.util.List;

/**
 * 企业入驻申请服务（AI 自动甄别版）
 *
 * 流程：提交申请 → 短信验证 → 频率/重复防护 → 落库 → 调用 ai-agent-service
 * AI 合规甄别（规则层 + 大模型层）→ 合法合规无敏感信息自动通过（创建租户+管理员），
 * 否则自动驳回（记录驳回原因与风险标记）。
 *
 * 防护面（防同一公司/手机号/IP 重复提交等攻击）：
 * 1. 蜜罐字段：隐藏字段被填充 → 判定自动化脚本，静默忽略不落库
 * 2. 频率限制：每手机号每日提交上限、每 IP 每小时提交上限（Redis 计数）
 * 3. 手机号查重：pending/approved 拦截；AI 驳回后 24h 冷却（system 降级驳回不冷却）
 * 4. 企业名称查重：规范化名称（去空格/括号/后缀）精确匹配，pending/approved 拦截
 *
 * 降级语义：AI 甄别服务不可达 → fail-closed 系统繁忙驳回（review_source=system），
 * 绝不在甄别服务不可用时放行；该驳回不进入 24h 冷却，用户可稍后重试。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class RegistrationService {

    private final TenantApplicationMapper applicationMapper;
    private final TenantMapper tenantMapper;
    private final UserService userService;
    private final SmsService smsService;
    private final UserMapper userMapper;
    private final RoleMapper roleMapper;
    private final PermissionMapper permissionMapper;
    private final RegistrationReviewClient reviewClient;
    private final StringRedisTemplate redisTemplate;

    private static final SecureRandom RANDOM = new SecureRandom();
    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    // ===== 防重复/防刷阈值（可审计常量） =====
    private static final long PHONE_DAILY_SUBMIT_LIMIT = 3;    // 每手机号每日提交上限
    private static final long IP_HOURLY_SUBMIT_LIMIT = 5;      // 每 IP 每小时提交上限
    private static final long REJECTED_COOLDOWN_HOURS = 24;    // AI 驳回后冷却时长
    private static final List<String> PENDING_OR_APPROVED = List.of("pending", "approved");

    // ===== 甄别来源常量 =====
    // 注：AI/系统自动审核的 reviewed_by 传 null（该列有 FK REFERENCES users(id)，
    // 审核来源由 review_source 列记录：ai / system / manual）。
    private static final String REVIEW_SOURCE_AI = "ai";
    private static final String REVIEW_SOURCE_SYSTEM = "system";

    // ===== Redis key 前缀 =====
    private static final String REG_PHONE_KEY = "reg:submit:phone:";
    private static final String REG_IP_KEY = "reg:submit:ip:";

    // ==================== 提交申请（AI 自动甄别） ====================

    /**
     * 提交企业入驻申请并自动完成 AI 甄别开通/驳回
     *
     * @param dto      入驻申请请求
     * @param clientIp 客户端 IP（频率限制用）
     * @return 申请结果（status: approved / rejected）
     */
    @Transactional(rollbackFor = Exception.class)
    public RegistrationResponse submitApplication(RegistrationRequest dto, String clientIp) {
        log.info("提交企业入驻申请: companyName={}, phone={}, ip={}",
                dto.getCompanyName(), dto.getPhone(), clientIp);

        // 0. 蜜罐：隐藏字段被填充 → 疑似自动化脚本，静默返回成功但不落库、不调 AI
        if (StringUtils.hasText(dto.getWebsite())) {
            log.warn("入驻申请命中蜜罐字段（疑似自动化脚本），已忽略: phone={}, ip={}", dto.getPhone(), clientIp);
            return RegistrationResponse.builder()
                    .applicationId(0L)
                    .status("pending")
                    .message("申请已提交，请耐心等待")
                    .build();
        }

        // 1. 校验短信验证码
        boolean verified = smsService.verifyCode(dto.getPhone(), dto.getSmsCode());
        if (!verified) {
            throw BusinessException.validationError("短信验证码错误或已过期");
        }

        // 2. 频率限制（Redis 防刷）
        checkRateLimits(dto.getPhone(), clientIp);

        // 3. 重复提交防护（手机号 + 企业名称）
        checkPhoneDuplicates(dto.getPhone());
        checkCompanyDuplicates(dto.getCompanyName());

        // 4. 落库（先落 pending，AI 甄别后置为终态）
        TenantApplication application = TenantApplication.builder()
                .companyName(dto.getCompanyName().trim())
                .companyNameNorm(normalizeCompanyName(dto.getCompanyName()))
                .contactName(dto.getContactName().trim())
                .phone(dto.getPhone())
                .businessLicenseUrl(dto.getBusinessLicenseUrl())
                .industry(dto.getIndustry())
                .address(dto.getAddress())
                .description(dto.getDescription())
                .status("pending")
                .build();
        applicationMapper.insert(application);
        log.info("企业入驻申请已落库: applicationId={}", application.getId());

        // 5. 调用 AI 合规甄别（ai-agent-service：规则层 + 大模型层）
        RegistrationReviewClient.ReviewVerdict verdict = reviewClient.review(dto);

        // 6. 甄别通过 → 自动开通（创建租户 + 管理员 + 默认角色权限）
        if (verdict != null && "approve".equals(verdict.decision())) {
            log.info("AI 甄别通过，自动开通入驻: applicationId={}", application.getId());
            approveApplication(application.getId(), null,
                    ApplicationReview.of(verdict, REVIEW_SOURCE_AI));
            return RegistrationResponse.builder()
                    .applicationId(application.getId())
                    .status("approved")
                    .message("AI 甄别通过，欢迎入驻米高平台")
                    .build();
        }

        // 7. 甄别驳回 → 自动驳回（记录 AI 驳回原因与风险标记）
        if (verdict != null && "reject".equals(verdict.decision())) {
            String reason = StringUtils.hasText(verdict.reason())
                    ? verdict.reason()
                    : "申请资料不符合入驻要求";
            log.info("AI 甄别驳回: applicationId={}, reason={}", application.getId(), reason);
            rejectApplication(application.getId(), null, reason,
                    ApplicationReview.of(verdict, REVIEW_SOURCE_AI));
            return RegistrationResponse.builder()
                    .applicationId(application.getId())
                    .status("rejected")
                    .message("AI 甄别未通过")
                    .rejectReason(reason)
                    .build();
        }

        // 8. AI 服务不可达 → fail-closed：系统繁忙驳回（不进入 24h 冷却，可稍后重试）
        log.error("AI 甄别服务不可用（reviewClient 返回 null），fail-closed 拒绝: applicationId={}",
                application.getId());
        String busyReason = "入驻审核系统繁忙，请稍后重试";
        rejectApplication(application.getId(), null, busyReason,
                ApplicationReview.builder()
                        .source(REVIEW_SOURCE_SYSTEM)
                        .summary("AI 甄别服务不可用，系统兜底拒绝")
                        .build());
        return RegistrationResponse.builder()
                .applicationId(application.getId())
                .status("rejected")
                .message("系统繁忙")
                .rejectReason(busyReason)
                .build();
    }

    // ==================== 防刷/防重复 ====================

    /**
     * 频率限制：手机号每日提交上限 + IP 每小时提交上限（Redis 原子计数）
     */
    private void checkRateLimits(String phone, String clientIp) {
        // 手机号每日上限
        String phoneKey = REG_PHONE_KEY + phone;
        Long phoneCount = redisTemplate.opsForValue().increment(phoneKey);
        if (phoneCount != null && phoneCount == 1) {
            Duration ttl = Duration.between(LocalDateTime.now(),
                    LocalDate.now().plusDays(1).atTime(LocalTime.MIDNIGHT));
            redisTemplate.expire(phoneKey, ttl);
        }
        if (phoneCount != null && phoneCount > PHONE_DAILY_SUBMIT_LIMIT) {
            throw BusinessException.validationError("提交过于频繁，请明日再试");
        }

        // IP 每小时上限
        String safeIp = StringUtils.hasText(clientIp) ? clientIp : "unknown";
        String ipKey = REG_IP_KEY + safeIp;
        Long ipCount = redisTemplate.opsForValue().increment(ipKey);
        if (ipCount != null && ipCount == 1) {
            redisTemplate.expire(ipKey, Duration.ofHours(1));
        }
        if (ipCount != null && ipCount > IP_HOURLY_SUBMIT_LIMIT) {
            throw BusinessException.validationError("提交过于频繁，请稍后重试");
        }
    }

    /**
     * 手机号查重：pending/approved 拦截；AI 驳回后 24h 冷却（system 降级驳回不冷却）
     */
    private void checkPhoneDuplicates(String phone) {
        LambdaQueryWrapper<TenantApplication> pendingWrapper = new LambdaQueryWrapper<>();
        pendingWrapper.eq(TenantApplication::getPhone, phone)
                .in(TenantApplication::getStatus, PENDING_OR_APPROVED);
        if (applicationMapper.selectCount(pendingWrapper) > 0) {
            throw BusinessException.validationError("该手机号已有入驻申请，请勿重复提交");
        }

        LambdaQueryWrapper<TenantApplication> rejectedWrapper = new LambdaQueryWrapper<>();
        rejectedWrapper.eq(TenantApplication::getPhone, phone)
                .eq(TenantApplication::getStatus, "rejected")
                .orderByDesc(TenantApplication::getReviewedAt)
                .last("LIMIT 1");
        TenantApplication lastRejected = applicationMapper.selectOne(rejectedWrapper);
        if (isAiRejectionInCooldown(lastRejected)) {
            throw BusinessException.validationError(cooldownMessage(lastRejected.getReviewedAt()));
        }
    }

    /**
     * 企业名称查重：规范化名称（去空格/括号/后缀）精确匹配，
     * pending/approved 拦截；AI 驳回后 24h 冷却
     */
    private void checkCompanyDuplicates(String companyName) {
        String norm = normalizeCompanyName(companyName);
        if (!StringUtils.hasText(norm)) {
            throw BusinessException.validationError("企业名称格式不合法");
        }

        LambdaQueryWrapper<TenantApplication> activeWrapper = new LambdaQueryWrapper<>();
        activeWrapper.eq(TenantApplication::getCompanyNameNorm, norm)
                .in(TenantApplication::getStatus, PENDING_OR_APPROVED);
        if (applicationMapper.selectCount(activeWrapper) > 0) {
            throw BusinessException.validationError("该企业已有入驻申请，请勿重复提交");
        }

        LambdaQueryWrapper<TenantApplication> rejectedWrapper = new LambdaQueryWrapper<>();
        rejectedWrapper.eq(TenantApplication::getCompanyNameNorm, norm)
                .eq(TenantApplication::getStatus, "rejected")
                .orderByDesc(TenantApplication::getReviewedAt)
                .last("LIMIT 1");
        TenantApplication lastRejected = applicationMapper.selectOne(rejectedWrapper);
        if (isAiRejectionInCooldown(lastRejected)) {
            throw BusinessException.validationError(cooldownMessage(lastRejected.getReviewedAt()));
        }
    }

    /**
     * AI 驳回且处于冷却期？（system 降级驳回 / 超时驳回不冷却，允许立即重试）
     */
    private boolean isAiRejectionInCooldown(TenantApplication lastRejected) {
        if (lastRejected == null || lastRejected.getReviewedAt() == null) {
            return false;
        }
        if (REVIEW_SOURCE_SYSTEM.equals(lastRejected.getReviewSource())) {
            return false;
        }
        return lastRejected.getReviewedAt()
                .isAfter(OffsetDateTime.now().minusHours(REJECTED_COOLDOWN_HOURS));
    }

    private String cooldownMessage(OffsetDateTime reviewedAt) {
        long elapsedHours = Math.max(0, ChronoUnit.HOURS.between(reviewedAt, OffsetDateTime.now()));
        long leftHours = Math.max(1, REJECTED_COOLDOWN_HOURS - elapsedHours);
        return "该申请已被驳回，请约 " + leftHours + " 小时后重新提交";
    }

    /**
     * 企业名称规范化：NFKC 全角→半角，去空白/括号/连字符，迭代去除企业后缀
     * 用于「同一家公司不同写法/不同手机号重复提交」的精确识别
     */
    static String normalizeCompanyName(String name) {
        if (name == null) {
            return "";
        }
        String s = Normalizer.normalize(name.trim().toLowerCase(), Normalizer.Form.NFKC);
        s = s.replaceAll("[\\s　（）()【】\\[\\]\\-—_·.,。]", "");
        String prev;
        do {
            prev = s;
            s = s.replaceAll("(股份有限公司|有限责任公司|有限公司|公司|集团|股份)$", "");
        } while (!s.equals(prev));
        return s;
    }

    // ==================== 超管查询 ====================

    /**
     * 分页查询入驻申请列表（超管使用）
     *
     * @param status 状态筛选（可选）
     * @param page   页码
     * @param size   每页大小
     * @return 分页结果
     */
    public PageResponse<TenantApplication> getApplications(String status, int page, int size) {
        LambdaQueryWrapper<TenantApplication> wrapper = new LambdaQueryWrapper<>();

        if (StringUtils.hasText(status)) {
            wrapper.eq(TenantApplication::getStatus, status);
        }

        wrapper.orderByDesc(TenantApplication::getCreatedAt);

        Page<TenantApplication> appPage = new Page<>(page, size);
        Page<TenantApplication> resultPage = applicationMapper.selectPage(appPage, wrapper);

        return PageResponse.of(resultPage.getTotal(), resultPage.getCurrent(), resultPage.getSize(), resultPage.getRecords());
    }

    /**
     * 查询申请详情
     *
     * @param id 申请ID
     * @return 申请实体
     */
    public TenantApplication getApplicationDetail(Long id) {
        TenantApplication application = applicationMapper.selectById(id);
        if (application == null) {
            throw BusinessException.notFound("入驻申请");
        }
        return application;
    }

    // ==================== 审批操作 ====================

    /**
     * 审批通过（人工兜底 API 入口）
     * 自动创建租户 + 管理员用户 + 分配角色
     *
     * @param id         申请ID
     * @param reviewerId 审核人用户ID
     */
    @Transactional(rollbackFor = Exception.class)
    public void approveApplication(Long id, String reviewerId) {
        approveApplication(id, reviewerId, null);
    }

    /**
     * 审批通过（内部，AI 自动开通时携带甄别元数据）
     *
     * @param id         申请ID
     * @param reviewerId 审核人标识（ai / 超管 userId）
     * @param review     甄别元数据（reviewSource/riskFlags/summary），可为 null
     */
    @Transactional(rollbackFor = Exception.class)
    public void approveApplication(Long id, String reviewerId, ApplicationReview review) {
        log.info("审批通过入驻申请: id={}, reviewerId={}", id, reviewerId);

        // 1. 查找并校验申请
        TenantApplication application = getApplicationDetail(id);
        if (!"pending".equals(application.getStatus())) {
            throw BusinessException.validationError("该申请已被处理，当前状态: " + application.getStatus());
        }

        // 2. 创建新租户
        String tenantCode = generateTenantCode(application.getCompanyName());
        Tenant tenant = Tenant.builder()
                .name(application.getCompanyName())
                .code(tenantCode)
                .industry(application.getIndustry())
                .status("active")
                .build();
        tenantMapper.insert(tenant);
        log.info("创建租户成功: tenantId={}, code={}", tenant.getId(), tenantCode);

        // 2.5 为新租户初始化默认角色和权限
        initializeDefaultRolesAndPermissions(tenant.getId());

        // 3. 创建管理员用户（需要设置租户上下文以通过多租户拦截器）
        Long previousTenantId = TenantContext.getTenantId();
        try {
            TenantContext.setTenantId(tenant.getId());

            // 生成随机初始密码（主要通过短信验证码登录，密码仅作备用）
            String initialPassword = generateRandomPassword();
            User adminUser = userService.createUser(
                    application.getPhone(),
                    initialPassword,
                    application.getContactName(),
                    "admin",
                    "管理员",
                    null,
                    tenant.getId()
            );
            log.info("创建企业管理员成功: userId={}, phone={}", adminUser.getId(), application.getPhone());
        } finally {
            // 恢复之前的租户上下文
            if (previousTenantId != null) {
                TenantContext.setTenantId(previousTenantId);
            } else {
                TenantContext.clear();
            }
        }

        // 4. 更新申请状态
        application.setStatus("approved");
        application.setReviewedBy(reviewerId);
        application.setReviewedAt(OffsetDateTime.now());
        applyReviewMeta(application, review);
        applicationMapper.updateById(application);

        log.info("入驻申请审批通过: applicationId={}, tenantId={}", id, tenant.getId());
    }

    /**
     * 驳回申请（人工兜底 API 入口）
     *
     * @param id         申请ID
     * @param reviewerId 审核人用户ID
     * @param reason     驳回原因
     */
    @Transactional(rollbackFor = Exception.class)
    public void rejectApplication(Long id, String reviewerId, String reason) {
        rejectApplication(id, reviewerId, reason, null);
    }

    /**
     * 驳回申请（内部，AI 自动驳回时携带甄别元数据）
     */
    @Transactional(rollbackFor = Exception.class)
    public void rejectApplication(Long id, String reviewerId, String reason, ApplicationReview review) {
        log.info("驳回入驻申请: id={}, reviewerId={}, reason={}", id, reviewerId, reason);

        TenantApplication application = getApplicationDetail(id);
        if (!"pending".equals(application.getStatus())) {
            throw BusinessException.validationError("该申请已被处理，当前状态: " + application.getStatus());
        }

        application.setStatus("rejected");
        application.setReviewedBy(reviewerId);
        application.setRejectReason(reason);
        application.setReviewedAt(OffsetDateTime.now());
        applyReviewMeta(application, review);
        applicationMapper.updateById(application);

        log.info("入驻申请已驳回: applicationId={}", id);
    }

    /**
     * 写入甄别元数据（reviewSource / riskFlags / reviewSummary）
     */
    private void applyReviewMeta(TenantApplication application, ApplicationReview review) {
        if (review == null) {
            return;
        }
        application.setReviewSource(review.source());
        application.setRiskFlags(review.riskFlagsJson());
        application.setReviewSummary(review.summary());
    }

    // ==================== 内部辅助方法 ====================

    /**
     * 根据企业名称生成唯一的租户编码
     * 格式：tenant_ + 时间戳后6位 + 随机4位
     */
    private String generateTenantCode(String companyName) {
        long timestamp = System.currentTimeMillis();
        int random = RANDOM.nextInt(10000);
        return String.format("tenant_%06d%04d", timestamp % 1000000, random);
    }

    /**
     * 为新租户初始化默认角色和权限
     *
     * @param tenantId 新租户ID
     */
    private void initializeDefaultRolesAndPermissions(Long tenantId) {
        log.info("初始化新租户默认角色和权限: tenantId={}", tenantId);

        // 创建默认角色
        Role adminRole = Role.builder()
                .tenantId(tenantId)
                .name("企业管理员")
                .code("admin")
                .description("企业入驻后的默认管理员角色，拥有全部管理权限")
                .status("active")
                .build();
        roleMapper.insert(adminRole);

        Role operatorRole = Role.builder()
                .tenantId(tenantId)
                .name("运营人员")
                .code("operator")
                .description("负责日常运营管理")
                .status("active")
                .build();
        roleMapper.insert(operatorRole);

        Role csRole = Role.builder()
                .tenantId(tenantId)
                .name("客服人员")
                .code("customer_service")
                .description("负责客户服务与咨询")
                .status("active")
                .build();
        roleMapper.insert(csRole);

        // 创建默认权限
        String[][] defaultPermissions = {
                {"仪表板查看", "dashboard:view", "dashboard", "view", "查看数据概览"},
                {"商品管理", "product:manage", "product", "manage", "管理商品"},
                {"加工管理", "processing:manage", "processing", "manage", "管理加工项"},
                {"知识库管理", "knowledge:manage", "knowledge", "manage", "管理知识库"},
                {"系统管理", "system:manage", "system", "manage", "管理系统设置"}
        };

        for (String[] perm : defaultPermissions) {
            Permission permission = Permission.builder()
                    .tenantId(tenantId)
                    .name(perm[0])
                    .code(perm[1])
                    .resourceType(perm[2])
                    .action(perm[3])
                    .description(perm[4])
                    .status("active")
                    .build();
            permissionMapper.insert(permission);
        }

        log.info("新租户默认角色和权限初始化完成: tenantId={}, roles=3, permissions={}", tenantId, defaultPermissions.length);
    }

    /**
     * 生成随机初始密码（12位，含大小写字母和数字）
     */
    private String generateRandomPassword() {
        String chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789";
        StringBuilder sb = new StringBuilder(12);
        for (int i = 0; i < 12; i++) {
            sb.append(chars.charAt(RANDOM.nextInt(chars.length())));
        }
        return sb.toString();
    }

    /**
     * AI 甄别元数据（落库到 tenant_applications 的 review_* 列）
     */
    public record ApplicationReview(String source, String riskFlagsJson, String summary) {

        static ApplicationReview of(RegistrationReviewClient.ReviewVerdict verdict, String source) {
            String flagsJson = null;
            if (verdict.riskFlags() != null && !verdict.riskFlags().isEmpty()) {
                try {
                    flagsJson = OBJECT_MAPPER.writeValueAsString(verdict.riskFlags());
                } catch (JsonProcessingException e) {
                    log.warn("序列化风险标记失败: {}", e.getMessage());
                }
            }
            return new ApplicationReview(source, flagsJson, verdict.summary());
        }

        static Builder builder() {
            return new Builder();
        }

        static final class Builder {
            private String source;
            private String riskFlagsJson;
            private String summary;

            Builder source(String source) {
                this.source = source;
                return this;
            }

            Builder riskFlagsJson(String riskFlagsJson) {
                this.riskFlagsJson = riskFlagsJson;
                return this;
            }

            Builder summary(String summary) {
                this.summary = summary;
                return this;
            }

            ApplicationReview build() {
                return new ApplicationReview(source, riskFlagsJson, summary);
            }
        }
    }
}
