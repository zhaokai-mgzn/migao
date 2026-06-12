package com.migao.admin.service;

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
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.security.SecureRandom;
import java.time.OffsetDateTime;

/**
 * 企业入驻申请服务
 * 处理入驻申请提交、审批通过（自动创建租户+管理员）、驳回等
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

    private static final SecureRandom RANDOM = new SecureRandom();

    // ==================== 提交申请 ====================

    /**
     * 提交企业入驻申请
     *
     * @param dto 入驻申请请求
     * @return 申请结果
     */
    @Transactional(rollbackFor = Exception.class)
    public RegistrationResponse submitApplication(RegistrationRequest dto) {
        log.info("提交企业入驻申请: companyName={}, phone={}", dto.getCompanyName(), dto.getPhone());

        // 1. 校验短信验证码
        boolean verified = smsService.verifyCode(dto.getPhone(), dto.getSmsCode());
        if (!verified) {
            throw BusinessException.validationError("短信验证码错误或已过期");
        }

        // 2. 检查手机号是否已有待审批申请
        LambdaQueryWrapper<TenantApplication> pendingWrapper = new LambdaQueryWrapper<>();
        pendingWrapper.eq(TenantApplication::getPhone, dto.getPhone())
                .eq(TenantApplication::getStatus, "pending");
        TenantApplication existingPending = applicationMapper.selectOne(pendingWrapper);
        if (existingPending != null) {
            throw BusinessException.validationError("该手机号已有待审批的入驻申请，请耐心等待");
        }

        // 3. 检查手机号是否已注册为用户（任一租户下）
        LambdaQueryWrapper<User> userWrapper = new LambdaQueryWrapper<>();
        userWrapper.eq(User::getPhone, dto.getPhone())
                .eq(User::getRole, "admin")
                .eq(User::getDeleted, 0);
        // 查询用户时需要临时设置租户上下文（因为 users 表受多租户拦截器管控）
        // 但这里我们检查的是全局是否已注册为管理员，需要绕过多租户
        // 通过查 tenant_applications 已审批通过的记录来判断
        LambdaQueryWrapper<TenantApplication> approvedWrapper = new LambdaQueryWrapper<>();
        approvedWrapper.eq(TenantApplication::getPhone, dto.getPhone())
                .eq(TenantApplication::getStatus, "approved");
        TenantApplication existingApproved = applicationMapper.selectOne(approvedWrapper);
        if (existingApproved != null) {
            throw BusinessException.validationError("该手机号已完成入驻，请直接登录");
        }

        // 4. 保存申请
        TenantApplication application = TenantApplication.builder()
                .companyName(dto.getCompanyName())
                .contactName(dto.getContactName())
                .phone(dto.getPhone())
                .businessLicenseUrl(dto.getBusinessLicenseUrl())
                .industry(dto.getIndustry())
                .address(dto.getAddress())
                .description(dto.getDescription())
                .status("pending")
                .build();
        applicationMapper.insert(application);

        log.info("企业入驻申请已提交: applicationId={}", application.getId());

        return RegistrationResponse.builder()
                .applicationId(application.getId())
                .status("pending")
                .message("入驻申请已提交，我们将尽快审核")
                .build();
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
     * 审批通过
     * 自动创建租户 + 管理员用户 + 分配角色
     *
     * @param id         申请ID
     * @param reviewerId 审核人用户ID（超管的 userId，类型为 String 与 User.id 一致）
     */
    @Transactional(rollbackFor = Exception.class)
    public void approveApplication(Long id, String reviewerId) {
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
        applicationMapper.updateById(application);

        log.info("入驻申请审批通过: applicationId={}, tenantId={}", id, tenant.getId());
    }

    /**
     * 驳回申请
     *
     * @param id         申请ID
     * @param reviewerId 审核人用户ID
     * @param reason     驳回原因
     */
    @Transactional(rollbackFor = Exception.class)
    public void rejectApplication(Long id, String reviewerId, String reason) {
        log.info("驳回入驻申请: id={}, reviewerId={}, reason={}", id, reviewerId, reason);

        TenantApplication application = getApplicationDetail(id);
        if (!"pending".equals(application.getStatus())) {
            throw BusinessException.validationError("该申请已被处理，当前状态: " + application.getStatus());
        }

        application.setStatus("rejected");
        application.setReviewedBy(reviewerId);
        application.setRejectReason(reason);
        application.setReviewedAt(OffsetDateTime.now());
        applicationMapper.updateById(application);

        log.info("入驻申请已驳回: applicationId={}", id);
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
}
