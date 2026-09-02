package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.entity.User;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.UserMapper;
import lombok.Data;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

/**
 * 小程序客户「微信授权手机号」绑定服务。
 *
 * 业务闭环（商户代录历史订单归属）：
 * 1. 小程序前端 open-type=getPhoneNumber 让用户授权 → 拿到动态 code
 * 2. 本服务用 code 调微信换号（WechatService.getPhoneNumber）拿真实手机号
 * 3. 写 users.phone（绑定到当前用户）
 * 4. 回填名下订单：orders.user_id IS NULL AND customer_phone=该号 → 绑定到本人
 *    （V23 一次性回填 SQL 的运行时等价物——商户代录/历史订单据此归属）
 *
 * 安全约束：
 * - 手机号必须通过微信官方换号接口取得（不信任前端直传，防伪绑他人号码）
 * - 同租户内手机号只能绑定一个账号（防两个微信账号抢同一商户客户）
 * - 回填只动 user_id 为空的订单（已归属他人的订单不动）
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class MiniPhoneBindService {

    private final WechatService wechatService;
    private final UserMapper userMapper;
    private final OrderService orderService;

    /**
     * 手机号绑定结果
     */
    @Data
    public static class BindResult {
        /** 已绑定的纯手机号 */
        private String phone;
        /** 本次回填的订单数 */
        private int boundOrders;
    }

    /**
     * 绑定微信授权手机号并回填名下历史订单。
     *
     * @param userId   当前登录用户 ID（JWT 认证）
     * @param tenantId 当前租户 ID
     * @param code     前端 getPhoneNumber 授权返回的动态 code
     * @return 绑定结果
     */
    @Transactional(rollbackFor = Exception.class)
    public BindResult bind(String userId, Long tenantId, String code) {
        // 1. 用户存在性校验
        if (!StringUtils.hasText(userId) || "internal-service".equals(userId)) {
            throw BusinessException.authFailed("缺少用户标识，无法绑定手机号");
        }
        User user = userMapper.selectById(userId);
        if (user == null || user.getDeleted() != null && user.getDeleted() == 1) {
            throw BusinessException.authFailed("用户不存在或已注销");
        }
        if (user.getTenantId() != null && !user.getTenantId().equals(tenantId)) {
            throw BusinessException.authFailed("用户与租户不匹配");
        }

        // 2. 微信换号（mock/真实双模式，由 WechatService 处理）
        if (!StringUtils.hasText(code)) {
            throw BusinessException.validationError("手机号授权 code 不能为空");
        }
        WechatService.PhoneNumberResult phoneResult = wechatService.getPhoneNumber(code);
        String purePhone = phoneResult != null ? phoneResult.getPurePhoneNumber() : null;
        if (!StringUtils.hasText(purePhone) || !purePhone.matches("^1[3-9]\\d{9}$")) {
            throw BusinessException.validationError("微信返回的手机号无效，请重新授权");
        }

        // 3. 同租户手机号唯一性：已绑定给其他用户 → 拒绝（本人重复绑定幂等放行）
        String myPhone = user.getPhone();
        boolean occupiedByOther;
        if (purePhone.equals(myPhone)) {
            occupiedByOther = false;  // 本人已绑定同一号 → 幂等
        } else {
            Long samePhoneCount = userMapper.selectCount(new LambdaQueryWrapper<User>()
                    .eq(User::getPhone, purePhone));
            occupiedByOther = samePhoneCount != null && samePhoneCount > 0;
        }
        if (occupiedByOther) {
            log.warn("[bind-phone] 拒绝：手机号已被同租户其他用户绑定 tenantId={}, userId={}",
                    tenantId, userId);
            throw BusinessException.validationError("该手机号已被绑定，请使用本人的微信手机号");
        }

        // 4. 写入 users.phone
        if (!purePhone.equals(myPhone)) {
            user.setPhone(purePhone);
            userMapper.updateById(user);
            log.info("[bind-phone] 绑定手机号: userId={}, tenantId={}, phone={}****{}",
                    userId, tenantId, purePhone.substring(0, 3), purePhone.substring(7));
        }

        // 5. 回填名下历史订单（user_id 为空 + customer_phone=该号 → 归属本人）
        int bound = orderService.bindOrdersToUser(tenantId, userId, purePhone);

        BindResult result = new BindResult();
        result.setPhone(purePhone);
        result.setBoundOrders(bound);
        return result;
    }
}
