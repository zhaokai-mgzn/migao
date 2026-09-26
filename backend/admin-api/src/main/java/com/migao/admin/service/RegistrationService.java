package com.migao.admin.service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.IndustryCodes;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.dto.RegistrationRequest;
import com.migao.admin.dto.RegistrationResponse;
import com.migao.admin.entity.Tenant;
import com.migao.admin.entity.TenantApplication;
import com.migao.admin.entity.User;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.support.LoginIdentifiers;
import com.migao.admin.entity.Permission;
import com.migao.admin.entity.Role;
import com.migao.admin.entity.RolePermission;
import com.migao.admin.mapper.PermissionMapper;
import com.migao.admin.mapper.RoleMapper;
import com.migao.admin.mapper.RolePermissionMapper;
import com.migao.admin.mapper.TenantApplicationMapper;
import com.migao.admin.mapper.TenantMapper;
import com.migao.admin.mapper.UserMapper;
import com.migao.admin.time.BusinessClock;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.security.SecureRandom;
import java.text.Normalizer;
import java.time.Duration;
import java.time.LocalTime;
import java.time.OffsetDateTime;
import java.time.temporal.ChronoUnit;
import java.util.Collection;
import java.util.List;
import java.util.Map;

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

    /** 业务时钟（issue #3802）：业务「今天」的唯一来源。Spring 注入单例；**不扫描 @Component 的切片上下文**
     * （@WebMvcTest / ApplicationContextRunner）与直接 new 构造的既有单测没有该 bean ⇒ required=false +
     * 默认实例（同为 +08 口径，行为一致），不因引入时钟让任何既有上下文启动失败（实测 OssEmptyConfigContextTest）。 */
    @Autowired(required = false)
    private BusinessClock businessClock = new BusinessClock();

    private final TenantApplicationMapper applicationMapper;
    private final TenantMapper tenantMapper;
    private final UserService userService;
    private final SmsService smsService;
    private final UserMapper userMapper;
    private final RoleMapper roleMapper;
    private final PermissionMapper permissionMapper;
    private final RolePermissionMapper rolePermissionMapper;
    private final RegistrationReviewClient reviewClient;
    private final StringRedisTemplate redisTemplate;
    /**
     * 行业生产种子模板（issue #4361 交付物 3）：开租建租户后按 {@code industry} 套用
     * —— 修掉 #4316「非 1 号租户工序库/路线库为空 ⇒ 建单 fail-closed 422」。
     */
    private final ProductionSeedTemplateService productionSeedTemplateService;

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
            Duration ttl = Duration.between(businessClock.now(),
                    businessClock.today().plusDays(1).atTime(LocalTime.MIDNIGHT));
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
                // 行业**归一为受控 code**（issue #4361 交付物 1）：申请单里是自由文本
                // （注册页 type="text"），而「开租按行业套用生产模板」要求它能当模板键
                // ⇒ 不归一 = 同一行业四种写法里三种取不到模板（静默落空库）。
                .industry(IndustryCodes.normalize(application.getIndustry()))
                .status("active")
                .build();
        tenantMapper.insert(tenant);
        log.info("创建租户成功: tenantId={}, code={}, industry={}",
                tenant.getId(), tenantCode, tenant.getIndustry());

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

            // 3.5 按行业套用生产种子模板（issue #4361 交付物 3；收口 #4316）
            // 不做这件事的后果（#4316 取证）：种子只种 tenant_id = 1 ⇒ 新租户工序库/路线库为空
            // ⇒ resolveRoute 两次都不命中 ⇒ 抛 ERR_ROUTING_NOT_FOUND（422）⇒ **一张加工单也生成不了**。
            applyProductionSeedTemplate(tenant);
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
     * 按行业套用生产种子模板（issue #4361 交付物 3；收口 #4316）。
     *
     * <p><b>失败语义：捕获 + 记录 + 可补套 —— 不让开租整体回滚</b>（本单按最少代码选定的
     * 显式语义，理由如下）：</p>
     * <ul>
     *   <li><b>为什么不让它回滚</b>：本方法跑在 {@code approveApplication} 的
     *       {@code @Transactional} 里。种子套用失败若上抛，会把**已建好的租户、默认角色权限、
     *       管理员用户**一起回滚 ⇒ 客户拿不到账号、申请单仍停在 pending ⇒ 比「工序库为空」严重得多
     *       （后者只是建不了单，且有补救路径）。「开租可用」优先于「种子齐全」。</li>
     *   <li><b>为什么不是静默吞掉</b>：捕获后打 {@code error} 日志（点名 tenantId + industry +
     *       异常），且套用是**幂等**的 ⇒ 运营/商家可随时经
     *       {@code POST /api/admin/production/seed-templates/curtain/apply} 补套，
     *       重试不会产生第二份。</li>
     *   <li><b>{@code other} 行业不是异常</b>：{@code applyTemplate} 会返回
     *       {@code applied=false} + 原因并自己记 warn，本方法照常放行（这是正常业务分支）。</li>
     * </ul>
     */
    private void applyProductionSeedTemplate(Tenant tenant) {
        try {
            Map<String, Object> applied = productionSeedTemplateService
                    .applyTemplate(tenant.getId(), tenant.getIndustry());
            log.info("开租套用生产种子模板: tenantId={}, industry={}, applied={}, operations={}, "
                            + "routings={}, skipped={}, reason={}",
                    tenant.getId(), tenant.getIndustry(), applied.get("applied"),
                    applied.get("created_operations"), applied.get("created_routings"),
                    applied.get("skipped"), applied.get("reason"));
        } catch (RuntimeException e) {
            // 显式降级：开租成功但种子未套用（可补套）。**不要**把异常吞掉不说 ——
            // 这条 error 日志是「库里工序为空」与「有人知道为什么」之间的唯一联系。
            log.error("开租套用生产种子模板失败（租户已建、可经 "
                            + "POST /api/admin/production/seed-templates/curtain/apply 补套）: "
                            + "tenantId={}, industry={}",
                    tenant.getId(), tenant.getIndustry(), e);
        }
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
     * 为新租户生成**可读、合规、唯一**的默认企业编码（issue #5485）。
     *
     * <p>淘汰的旧形态：{@code tenant_%06d%04d}（时间戳拼随机数）—— 它含下划线，
     * **不满足**登录标识对企业编码的格式 {@code ^[a-z0-9][a-z0-9-]{1,31}$}，
     * 而且既不可读也不可改。新形态 = {@code <企业名 slug>-<4 位随机>}
     * （如 {@code acme-fabric-3k9z}；纯中文企业名 slug 退化为 {@code shop}），
     * 管理员之后可在「企业基础信息」里自行设置。</p>
     *
     * <p><b>唯一性</b>：先查库（{@code tenants.code} 全局查重）+ 重试；最终兜底是数据库
     * {@code UNIQUE(tenants.code)}。⚠️ 并发下的取舍如实登记：同时有两个请求落到同一候选值时，
     * 唯一约束会让**后到的那次注册整体失败**（事务已中止，PG 里不能在事务内重试），
     * 而不是静默撞号 —— fail-closed，管理员重试即可。9 位随机（36^4 ≈ 168 万）叠加
     * 查重使该概率可忽略。</p>
     */
    private String generateTenantCode(String companyName) {
        for (int attempt = 0; attempt < 10; attempt++) {
            String candidate = LoginIdentifiers.defaultTenantCode(companyName, RANDOM);
            LambdaQueryWrapper<Tenant> wrapper = new LambdaQueryWrapper<>();
            wrapper.eq(Tenant::getCode, candidate);
            if (tenantMapper.selectCount(wrapper) == 0) {
                return candidate;
            }
            log.warn("默认企业编码候选已被占用，重试: attempt={}", attempt);
        }
        throw new BusinessException("TENANT_CODE_EXHAUSTED", "企业编码生成失败，请重试", 500);
    }

    /**
     * 为新租户初始化默认岗位（五岗）和权限
     *
     * 岗位=角色体系（#2969）：每个岗位在 roles 表落一条记录，role_permissions 即岗位默认权限。
     * 创建员工时选岗位 → 前端预填该岗位默认权限 → 保存为员工个人权限快照。
     */
    private void initializeDefaultRolesAndPermissions(Long tenantId) {
        log.info("初始化新租户默认岗位和权限: tenantId={}", tenantId);

        // 创建默认岗位（五岗：管理员/客服/运营/销售/财务）
        Role adminRole = Role.builder()
                .tenantId(tenantId)
                .name("管理员")
                .code("admin")
                .description("拥有全部管理权限")
                .status("active")
                .build();
        roleMapper.insert(adminRole);

        Role csRole = Role.builder()
                .tenantId(tenantId)
                .name("客服")
                .code("customer_service")
                .description("负责客户服务与咨询")
                .status("active")
                .build();
        roleMapper.insert(csRole);

        Role operatorRole = Role.builder()
                .tenantId(tenantId)
                .name("运营")
                .code("operator")
                .description("负责日常运营管理")
                .status("active")
                .build();
        roleMapper.insert(operatorRole);

        Role salesRole = Role.builder()
                .tenantId(tenantId)
                .name("销售")
                .code("sales")
                .description("负责销售业务")
                .status("active")
                .build();
        roleMapper.insert(salesRole);

        Role financeRole = Role.builder()
                .tenantId(tenantId)
                .name("财务")
                .code("finance")
                .description("负责财务对账")
                .status("active")
                .build();
        roleMapper.insert(financeRole);

        // 创建默认权限目录（RBAC 修复：与代码 @RequirePermission / 前端菜单树 / 内置角色映射
        // 全量对齐——此前仅 5 条大类码，角色管理页无法授予 order:list / employee:create 等细粒度码，
        // 自定义角色形同虚设。product:manage 保留兼容旧 role_permissions 引用）
        String[][] defaultPermissions = {
                {"仪表板查看", "dashboard:view", "dashboard", "view", "查看数据概览"},
                {"商品管理", "product:manage", "product", "manage", "管理商品(旧大类码，兼容)"},
                {"商品列表", "product:list", "product", "list", "查看商品列表"},
                {"新增商品", "product:create", "product", "create", "新增/编辑/上下架商品"},
                {"商品分类", "product:category", "product", "category", "管理商品分类"},
                // 商品分类**读**码（issue #5291）：分类读端点（`CategoryController.getCategoryTree`）
                // 与只读工具 `category_manage` 同批改挂本码 —— 此前读端点在类级 `product:category` 上
                // ⇒ 只读工具不得不持**写**码（例外表 10 条之一）。写面仍是 `product:category`。
                {"商品分类查看", "product:category:view", "product", "view", "查看商品分类"},
                {"加工管理", "processing:manage", "processing", "manage", "管理加工项"},
                {"加工单查看", "processing:view", "processing-order", "view", "查看加工单"},
                {"加工单操作", "processing:update", "processing-order", "update", "生成/发加工/取消加工单"},
                // 生产域**读**码（issue #5291）：生产看板 / 加工项管理 / 工艺配置 / 计件工资四个侧边栏
                // 节点、四个页面的读端点、以及 8 个只读工具同批改挂本码（写面仍是 `processing:manage`）。
                {"生产查看", "production:view", "production", "view", "查看生产看板/加工项/工艺配置/计件"},
                // 入库单（V111，issue #5034）：与 V111 迁移的存量租户权限补齐**同源同码**
                {"入库单查看", "inbound:view", "inbound-order", "view", "查看入库单/批次"},
                {"入库单操作", "inbound:create", "inbound-order", "create", "建单/过账/作废入库单"},
                {"知识库管理", "knowledge:manage", "knowledge", "manage", "管理知识库"},
                // 知识库查看（issue #5246）：知识库的**读**码。此前读（列表/搜索/待确认队列/模板）
                // 与写（增删改/发布/归档/采纳/提炼）共用 knowledge:manage ⇒ 只想看看知识卡片的
                // 客服/运营必须被授予写权才进得去。本次按读写拆开：读 = knowledge:view，写仍 = knowledge:manage。
                {"知识库查看", "knowledge:view", "knowledge", "view", "查看知识卡片"},
                {"订单列表", "order:list", "order", "list", "查看订单列表"},
                {"订单详情", "order:detail", "order", "detail", "查看订单详情"},
                // 订单写码（issue #5246 追加单）：把「改订单」从读码 order:list 上摘下来 ——
                // 此前状态/物流/支付/取消/备注/跟进/删除全挂在 order:list 上 ⇒ **只读持有者拿到写能力**
                // （表单路径与 agent 路径同一形态）。order:create 与 order:update 分列：
                // 建单与改单是两种授权粒度（先下单 vs 改既有单）。
                {"订单操作", "order:update", "order", "update", "改订单状态/物流/备注/跟进/取消"},
                {"新增订单", "order:create", "order", "create", "创建订单"},
                {"订单退款", "order:refund", "order", "refund", "处理退款/售后工单"},
                // 售后查看（issue #5246）：售后工单的**读**码。此前工单列表/详情与建单/改状态
                // 同用 order:refund，而 order:refund 是**处理退款**（写）语义 ⇒ 拆出读码后
                // 「能看工单」与「能退款/建单」成为两件事（侧边栏节点也改用本码，见 config/menu.ts）。
                {"售后查看", "after_sales:view", "after-sales", "view", "查看售后工单"},
                {"客户管理", "customer:view", "customer", "view", "查看客户"},
                // 客户写码（issue #5246 追加单）：编辑/删除客户与标签此前挂在读码 customer:view 上。
                {"客户维护", "customer:create", "customer", "create", "编辑/删除客户与标签"},
                {"财务对账", "finance:view", "finance", "view", "查看财务流水/对账"},
                // 财务写码（issue #5246 追加单）：登记收支流水此前挂在读码 finance:view 上
                // ⇒ 「能看账」等于「能记账」。
                {"财务操作", "finance:create", "finance", "create", "登记收支流水"},
                {"会话监控", "agent:session", "agent", "session", "米宝对话/会话监控/在线接待"},
                // 会话写码（issue #5246 追加单）：转接/结束/发消息此前挂在读码 agent:session 上
                // ⇒ 只看会话的人能替客服转接与发言。
                {"会话操作", "agent:session:manage", "agent", "manage", "转接/结束会话/发消息"},
                {"员工列表", "employee:list", "employee", "list", "查看员工列表"},
                {"新增员工", "employee:create", "employee", "create", "新增/编辑/删除员工"},
                // 岗位权限**读**码（issue #5291）：权限目录读端点（`AdminPermissionController`）与只读
                // 工具 `role_manage` 同批改挂本码；「岗位权限」侧边栏节点也改用本码。写面仍是 `system:manage`。
                {"岗位权限查看", "system:view", "system", "view", "查看岗位与权限目录"},
                {"系统管理", "system:manage", "system", "manage", "企业信息/岗位权限/系统设置"}
        };

        Map<String, Permission> permissionByCode = new java.util.HashMap<>();
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
            permissionByCode.put(perm[1], permission);
        }

        // 岗位默认权限（role_permissions 预置）：
        // 管理员=全部；客服=会话+客户+订单查看+售后/知识库查看；运营=看板/订单/商品/加工/客户/财务/会话/员工列表；
        // 销售=看板/商品/订单查看/客户；财务=看板/订单查看/财务。
        // issue #5246：客服与运营加授两个**读**码（after_sales:view / knowledge:view）——
        // 两者本就是售后工单与知识库的日常使用方，此前因读写同码只能靠 order:refund / knowledge:manage
        // 才能看到菜单（= 顺带拿到写权）⇒ 本次给读码即恢复「看得见」，写权不再被动外溢。
        // issue #5246 追加单（写码落地）：**有意收窄**——写码只给「岗位职责本来就包含它」的岗位，
        // 且逐项登记（不多授一个）：
        //   · operator（运营）：order:update / order:create / customer:create / finance:create /
        //     agent:session:manage —— 运营本就是「改单、建单、维护客户、记账、转接会话」的执行方；
        //   · finance（财务）：finance:create —— 只有**登记流水**是财务本职（其余写码不给）；
        //   · customer_service（客服）：agent:session:manage —— 客服本就是转接/结束会话的**唯一**执行方
        //     （此前它靠 agent:session 这个**读**码就能转接，正是本次要关掉的口子）。
        //   · sales：**一个写码都不给**（有意：销售的动线是看，改单/记账归运营与财务）。
        // 收窄方向可复算：`git diff` 里 finance/sales 列表**没有新增任何码**。
        attachDefaultPermissions(tenantId, adminRole, permissionByCode.keySet(), permissionByCode);
        attachDefaultPermissions(tenantId, csRole, List.of(
                "dashboard:view", "order:list", "order:detail", "customer:view", "agent:session",
                "processing:view", "inbound:view", "after_sales:view", "knowledge:view",
                "agent:session:manage"), permissionByCode);
        attachDefaultPermissions(tenantId, operatorRole, List.of(
                "dashboard:view", "order:list", "order:detail", "order:refund",
                "product:list", "product:create", "product:category", "product:category:view",
                // issue #5291：operator 是原持 `product:category` / `processing:manage` 的岗位
                // ⇒ 同批回填三个域读码中的两个（第三个 `system:view` **不给** —— 它属 admin 专属，
                //   多授 = 让运营看见「岗位权限」页并读到权限目录，属**放宽**，本单不做）。
                "processing:manage", "production:view",
                "processing:view", "processing:update", "inbound:view", "inbound:create",
                "customer:view", "finance:view", "agent:session", "employee:list",
                "after_sales:view", "knowledge:view",
                "order:update", "order:create", "customer:create", "finance:create",
                "agent:session:manage"), permissionByCode);
        attachDefaultPermissions(tenantId, salesRole, List.of(
                "dashboard:view", "product:list", "order:list", "order:detail", "customer:view",
                "processing:view", "inbound:view"), permissionByCode);
        attachDefaultPermissions(tenantId, financeRole, List.of(
                "dashboard:view", "order:list", "order:detail", "finance:view",
                "processing:view", "inbound:view", "finance:create"), permissionByCode);

        log.info("新租户默认岗位和权限初始化完成: tenantId={}, roles=5, permissions={}", tenantId, defaultPermissions.length);
    }

    /**
     * 为岗位（角色）关联默认权限，落库 role_permissions。
     * 管理员岗位也预置全部权限码（岗位权限页回显「全部权限」、员工弹窗选管理员岗位全选），
     * 运行时 getUserPermissions 对 admin 仍特判返回 ["*"]。
     */
    private void attachDefaultPermissions(Long tenantId, Role role, Collection<String> permissionCodes,
                                          Map<String, Permission> permissionByCode) {
        for (String code : permissionCodes) {
            Permission permission = permissionByCode.get(code);
            if (permission == null) {
                continue; // 权限目录演进防御：跳过不存在的码
            }
            RolePermission rp = RolePermission.builder()
                    .tenantId(tenantId)
                    .roleId(role.getId())
                    .permissionId(permission.getId())
                    .build();
            rolePermissionMapper.insert(rp);
        }
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
