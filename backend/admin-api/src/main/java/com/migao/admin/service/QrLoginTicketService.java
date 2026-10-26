package com.migao.admin.service;

import com.migao.admin.exception.BusinessException;
import com.migao.admin.security.JwtTokenProvider;
import io.jsonwebtoken.Claims;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

/**
 * 「扫码即登录」票据（issue #7825）。
 *
 * <p>解决的形态：顶栏「手机端」二维码（issue #7198）原来只是**裸入口** `<B端H5地址>`，
 * 换一台没有登录态的浏览器 / App 扫码必然停在登录页，只能重新输「用户名@企业编码 + 密码」。
 * 现在 PC 侧（已登录）签发一张 **120 秒、单次有效** 的票据，二维码带上它；
 * 手机 H5 启动时兑换成**自己的** 30 天会话（与密码登录同一套收尾）。</p>
 *
 * <h3>安全口径（每条都有判据，见 `QrLoginTicketTest`）</h3>
 * <ul>
 *   <li><b>类型隔离</b>：票据是 {@link JwtTokenProvider#TOKEN_TYPE_QR_LOGIN} —— access token 当票据用、
 *       票据当 access token 用、票据当 refresh 用，三个方向都拒绝；</li>
 *   <li><b>单次有效</b>：兑换即把 jti 写进**既有**吊销名单（{@code token:blacklist:*}），
 *       复用 {@link AuthService#isTokenRevoked} / {@link AuthService#revokeToken}，
 *       不新造第二套黑名单；Redis 不可用 ⇒ **fail-closed**（与刷新同一口径，issue #4866）；</li>
 *   <li><b>不外泄细节</b>：过期 / 已用 / 类型不符统一一句
 *       {@link AuthService#QR_TICKET_INVALID_MESSAGE}；</li>
 *   <li><b>票据≠会话</b>：票据不含角色/权限；兑换时按数据库当前值重算
 *       （{@link AuthService#loginByQrTicket}）。</li>
 * </ul>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class QrLoginTicketService {

    private final JwtTokenProvider jwtTokenProvider;
    private final AuthService authService;

    /**
     * 签发一张票据（调用方必须**已认证** —— 见 `SecurityConfig`：`/api/auth/qr/ticket` 不在放行名单里）。
     *
     * @param userId   当前登录用户
     * @param tenantId 当前登录租户
     * @return 票据 + 有效期（秒）
     */
    public Ticket issue(String userId, Long tenantId) {
        if (!StringUtils.hasText(userId)) {
            throw BusinessException.authFailed("请先登录后再生成手机端二维码");
        }
        String ticket = jwtTokenProvider.generateQrLoginTicket(userId, tenantId);
        return new Ticket(ticket, jwtTokenProvider.getQrLoginTicketExpiration());
    }

    /**
     * 校验并**消费**一张票据（单次有效：成功即吊销 jti）。
     *
     * @param ticket 二维码里的票据
     * @return 票据指向的身份（用户 + 租户）
     * @throws BusinessException 票据无效/过期/已使用 ⇒ 401；吊销状态不可判定 ⇒ 503（fail-closed）
     */
    public Identity consume(String ticket) {
        if (!StringUtils.hasText(ticket)
                || !jwtTokenProvider.validateToken(ticket)
                || !jwtTokenProvider.isQrLoginTicket(ticket)) {
            throw BusinessException.authFailed(AuthService.QR_TICKET_INVALID_MESSAGE);
        }

        Claims claims = jwtTokenProvider.getClaimsFromToken(ticket);
        String jti = claims.getId();
        Boolean revoked = jti == null ? Boolean.FALSE : authService.isTokenRevoked(jti);
        if (revoked == null) {
            throw new BusinessException("AUTH_UNAVAILABLE",
                    "吊销状态不可判定（Redis 不可用），已按 fail-closed 拒绝本次扫码登录", 503);
        }
        if (Boolean.TRUE.equals(revoked)) {
            throw BusinessException.authFailed(AuthService.QR_TICKET_INVALID_MESSAGE);
        }

        // 兑换即吊销：票据在 120 秒窗口内也只能用一次（截图/转发泄漏的窗口到此为止）
        if (jti != null && claims.getExpiration() != null) {
            authService.revokeToken(jti, claims.getExpiration().getTime() - System.currentTimeMillis());
        }

        String userId = claims.get(JwtTokenProvider.CLAIM_USER_ID, String.class);
        if (!StringUtils.hasText(userId)) {
            throw BusinessException.authFailed(AuthService.QR_TICKET_INVALID_MESSAGE);
        }
        log.info("扫码登录票据已兑换: userId={}, jti={}", userId, jti);
        return new Identity(userId, tenantIdOf(claims));
    }

    /** 租户 claim 可能是 Integer / Long / String（Jackson 反序列化形态随数值大小变）⇒ 统一成 Long。 */
    private static Long tenantIdOf(Claims claims) {
        Object raw = claims.get(JwtTokenProvider.CLAIM_TENANT_ID);
        if (raw == null) {
            return null;
        }
        if (raw instanceof Number number) {
            return number.longValue();
        }
        try {
            return Long.valueOf(String.valueOf(raw));
        } catch (NumberFormatException e) {
            return null;
        }
    }

    /** 签发的票据（有效期给前端做倒计时，不参与鉴权） */
    public record Ticket(String ticket, long expiresIn) {}

    /** 票据指向的身份（角色/权限在兑换时按数据库当前值重算） */
    public record Identity(String userId, Long tenantId) {}
}
