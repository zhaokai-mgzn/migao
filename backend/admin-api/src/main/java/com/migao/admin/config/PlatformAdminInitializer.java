package com.migao.admin.config;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.entity.PlatformAdmin;
import com.migao.admin.mapper.PlatformAdminMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.CommandLineRunner;
import org.springframework.stereotype.Component;

/**
 * 平台管理员初始化器
 * 应用启动时自动创建默认超管账号（如不存在）。
 *
 * 通过环境变量 PLATFORM_ADMIN_PHONE 配置手机号，未配置则跳过初始化。
 *
 * 安全说明：
 * - 本项目使用 SMS 短信验证码登录（密码登录已禁用），因此不设置 password_hash。
 * - 在 dev 环境短信验证码为旁路固定值，生产环境使用阿里云 SMS 真实验证码。
 * - 仅当手机号通过 SMS 验证后，系统才会签发 JWT Token。
 */
@Slf4j
@Component
public class PlatformAdminInitializer implements CommandLineRunner {

    private final PlatformAdminMapper platformAdminMapper;

    @Value("${platform.admin.phone:#{null}}")
    private String adminPhone;

    @Value("${platform.admin.nickname:平台管理员}")
    private String adminNickname;

    public PlatformAdminInitializer(PlatformAdminMapper platformAdminMapper) {
        this.platformAdminMapper = platformAdminMapper;
    }

    @Override
    public void run(String... args) {
        if (adminPhone == null || adminPhone.isBlank()) {
            log.info("未配置 platform.admin.phone，跳过平台管理员初始化");
            return;
        }

        try {
            PlatformAdmin existing = platformAdminMapper.selectOne(
                    new LambdaQueryWrapper<PlatformAdmin>()
                            .eq(PlatformAdmin::getPhone, adminPhone)
            );
            if (existing != null) {
                log.info("平台管理员已存在: phone={}***", maskPhone(adminPhone));
                return;
            }

            // 不设置密码 — 本项目仅使用 SMS 短信验证码登录
            PlatformAdmin admin = PlatformAdmin.builder()
                    .id("super-admin-001")
                    .phone(adminPhone)
                    .nickname(adminNickname)
                    .status("active")
                    .build();
            platformAdminMapper.insert(admin);
            log.info("✅ 已创建平台管理员: phone={}*** nickname={}", maskPhone(adminPhone), adminNickname);
        } catch (Exception e) {
            log.warn("平台管理员初始化跳过（表可能尚未创建）: {}", e.getMessage());
        }
    }

    /**
     * 手机号脱敏：保留前 3 位，其余用 *** 替换
     */
    private static String maskPhone(String phone) {
        if (phone == null || phone.length() <= 3) {
            return "***";
        }
        return phone.substring(0, 3) + "***";
    }
}
