// case_ids: AU-014
package com.migao.admin.service;

import com.migao.admin.exception.BusinessException;
import com.migao.admin.security.JwtTokenProvider;
import io.jsonwebtoken.Claims;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.core.io.DefaultResourceLoader;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.Date;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 扫码即登录票据（issue #7825）判据。
 *
 * <p>覆盖三类「会红」的口径：</p>
 * <ol>
 *   <li><b>类型隔离</b>（真签名）：access / refresh / qr 三种 token 互相都换不成对方 ——
 *       {@link JwtTokenProvider#isQrLoginTicket} 只认 {@code qr_login}；票据本身也过不了
 *       {@code JwtAuthenticationFilter}（它只认 access）与 {@code /api/auth/refresh}（只认 refresh）；</li>
 *   <li><b>单次有效</b>：兑换即吊销 jti，第二次兑换必 401；</li>
 *   <li><b>fail-closed</b>：吊销状态不可判定（Redis 不可用）⇒ 503，绝不静默放行（issue #4866 口径）。</li>
 * </ol>
 *
 * <p>红证形态：把 {@code consume} 里的 {@code isQrLoginTicket} 判断删掉 ⇒
 * {@link #consume_accessTokenIsRejected()} 红；把 {@code revokeToken} 那行删掉 ⇒
 * {@link #consume_secondTimeIsRejected()} 红（第二次反而成功）；把 {@code revoked == null} 的 503 改成放行 ⇒
 * {@link #consume_revocationUnavailable_failsClosed()} 红。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("扫码即登录票据（issue #7825）")
class QrLoginTicketTest {

    private static final String TICKET = "qr-ticket";
    private static final String JTI = "jti-qr-1";

    @Mock
    private JwtTokenProvider jwtTokenProvider;

    @Mock
    private AuthService authService;

    @Mock
    private Claims claims;

    @InjectMocks
    private QrLoginTicketService qrLoginTicketService;

    /** 真实 RSA 签名的 provider（与 JwtTokenProviderTest 同一套 classpath 密钥）。 */
    private static JwtTokenProvider realProvider() {
        JwtTokenProvider provider = new JwtTokenProvider(new DefaultResourceLoader());
        ReflectionTestUtils.setField(provider, "privateKeyPath", "classpath:rsa/private.pem");
        ReflectionTestUtils.setField(provider, "publicKeyPath", "classpath:rsa/public.pem");
        ReflectionTestUtils.setField(provider, "accessTokenExpiration", 7200L);
        ReflectionTestUtils.setField(provider, "refreshTokenExpiration", 2592000L);
        ReflectionTestUtils.setField(provider, "qrLoginTicketExpiration", 120L);
        provider.init();
        return provider;
    }

    // ==================== 类型隔离（真签名） ====================

    @Test
    @DisplayName("三种令牌互不可用：qr 不是 access/refresh，access/refresh 也不是 qr（双向）")
    void tokenTypesAreMutuallyExclusive() {
        JwtTokenProvider provider = realProvider();
        String access = provider.generateAccessToken("u1", 1L, "13800000000",
                List.of("admin"), List.of("order:view"), false);
        String refresh = provider.generateRefreshToken("u1", 1L);
        String ticket = provider.generateQrLoginTicket("u1", 1L);

        assertThat(provider.validateToken(ticket)).as("票据本身是**有效签名**的 JWT").isTrue();
        assertThat(provider.isQrLoginTicket(ticket)).isTrue();
        assertThat(provider.isAccessToken(ticket)).as("票据不能当 access token").isFalse();
        assertThat(provider.isRefreshToken(ticket)).as("票据不能当 refresh token").isFalse();

        assertThat(provider.isQrLoginTicket(access)).as("access token 不能当票据").isFalse();
        assertThat(provider.isQrLoginTicket(refresh)).as("refresh token 不能当票据").isFalse();
    }

    @Test
    @DisplayName("票据有效期 = 120 秒（配置 jwt.qr-login-ticket-expiration）")
    void ticketLifetimeIs120Seconds() {
        JwtTokenProvider provider = realProvider();
        String ticket = provider.generateQrLoginTicket("u1", 1L);
        long remainingMillis = provider.getExpirationDate(ticket).getTime() - System.currentTimeMillis();
        assertThat(remainingMillis).isBetween(100_000L, 130_000L);
    }

    // ==================== 签发 ====================

    @Test
    @DisplayName("签发：无用户 ⇒ 401（签发端点必须已登录）")
    void issue_withoutUser_rejected() {
        assertThatThrownBy(() -> qrLoginTicketService.issue("", 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("请先登录");
    }

    @Test
    @DisplayName("签发：返回票据 + 有效期（前端据此倒计时）")
    void issue_returnsTicketAndExpiry() {
        when(jwtTokenProvider.generateQrLoginTicket("u1", 1L)).thenReturn(TICKET);
        when(jwtTokenProvider.getQrLoginTicketExpiration()).thenReturn(120L);

        QrLoginTicketService.Ticket ticket = qrLoginTicketService.issue("u1", 1L);

        assertThat(ticket.ticket()).isEqualTo(TICKET);
        assertThat(ticket.expiresIn()).isEqualTo(120L);
    }

    // ==================== 兑换 ====================

    @Test
    @DisplayName("兑换：票据有效 ⇒ 返回身份并**吊销 jti**（单次有效）")
    void consume_validTicket_returnsIdentityAndRevokes() {
        givenValidTicket();

        QrLoginTicketService.Identity identity = qrLoginTicketService.consume(TICKET);

        assertThat(identity.userId()).isEqualTo("u1");
        assertThat(identity.tenantId()).isEqualTo(9L);
        verify(authService, times(1)).revokeToken(eq(JTI), anyLong());
    }

    @Test
    @DisplayName("兑换：第二次必 401（票据是一次性持有凭证）")
    void consume_secondTimeIsRejected() {
        givenValidTicket();
        when(authService.isTokenRevoked(JTI)).thenReturn(false, true);

        qrLoginTicketService.consume(TICKET);

        assertThatThrownBy(() -> qrLoginTicketService.consume(TICKET))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining(AuthService.QR_TICKET_INVALID_MESSAGE);
    }

    @Test
    @DisplayName("兑换：access token 当票据用 ⇒ 401（类型不对，不区分细节）")
    void consume_accessTokenIsRejected() {
        when(jwtTokenProvider.validateToken(TICKET)).thenReturn(true);
        when(jwtTokenProvider.isQrLoginTicket(TICKET)).thenReturn(false);

        assertThatThrownBy(() -> qrLoginTicketService.consume(TICKET))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining(AuthService.QR_TICKET_INVALID_MESSAGE);
        verify(authService, times(0)).revokeToken(eq(JTI), anyLong());
    }

    @Test
    @DisplayName("兑换：过期/伪造票据 ⇒ 401")
    void consume_expiredTicketIsRejected() {
        when(jwtTokenProvider.validateToken(TICKET)).thenReturn(false);

        assertThatThrownBy(() -> qrLoginTicketService.consume(TICKET))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining(AuthService.QR_TICKET_INVALID_MESSAGE);
    }

    @Test
    @DisplayName("兑换：吊销状态不可判定（Redis 不可用）⇒ 503 fail-closed，绝不放行")
    void consume_revocationUnavailable_failsClosed() {
        givenValidTicket();
        when(authService.isTokenRevoked(JTI)).thenReturn(null);

        assertThatThrownBy(() -> qrLoginTicketService.consume(TICKET))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("fail-closed");
        verify(authService, times(0)).revokeToken(eq(JTI), anyLong());
    }

    private void givenValidTicket() {
        when(jwtTokenProvider.validateToken(TICKET)).thenReturn(true);
        when(jwtTokenProvider.isQrLoginTicket(TICKET)).thenReturn(true);
        when(jwtTokenProvider.getClaimsFromToken(TICKET)).thenReturn(claims);
        when(claims.getId()).thenReturn(JTI);
        when(claims.getExpiration()).thenReturn(new Date(System.currentTimeMillis() + 60_000L));
        when(claims.get(JwtTokenProvider.CLAIM_USER_ID, String.class)).thenReturn("u1");
        when(claims.get(JwtTokenProvider.CLAIM_TENANT_ID)).thenReturn(9L);
        when(authService.isTokenRevoked(JTI)).thenReturn(false);
    }
}
