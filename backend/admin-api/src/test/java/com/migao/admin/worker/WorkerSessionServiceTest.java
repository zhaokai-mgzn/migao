// case_ids: PG-018, BM-001, BM-005, DF-017
package com.migao.admin.worker;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.migao.admin.entity.User;
import com.migao.admin.entity.WorkerSession;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.UserMapper;
import com.migao.admin.mapper.WorkerSessionMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;

import java.time.OffsetDateTime;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 工人登录态语义测试（issue #4733）。
 *
 * <p>红证形态（每条都能红）：</p>
 * <ul>
 *   <li><b>工人无法登录</b>（改前**无此路径** —— 全仓 grep 零命中「工人 session」；
 *       本测试在改前的 {@code origin/main} 上连编译都过不了：{@code WorkerSessionService} 不存在）；</li>
 *   <li><b>闲置超时后提交 ⇒ 必须被拒</b>（改前无登录态 ⇒ 不存在「闲置」概念，必然放行）；</li>
 *   <li><b>快速切换后旧 session 立即失效</b>（W2）。</li>
 * </ul>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("工人登录态：工号+PIN 登录 / 服务端解身份 / 闲置登出 / 快速切换")
class WorkerSessionServiceTest {

    private static final Long TENANT = 1L;
    private static final String WORKER_NO = "W001";
    private static final String PIN = "246810";
    private static final String WORKER_ID = "worker-zhang";

    @Mock
    private WorkerSessionMapper workerSessionMapper;
    @Mock
    private UserMapper userMapper;

    private final PasswordEncoder passwordEncoder = new BCryptPasswordEncoder();

    private WorkerSessionService service;

    @BeforeEach
    void setUp() {
        service = new WorkerSessionService(workerSessionMapper, userMapper, passwordEncoder);
    }

    // ============================================================ ① 工人登录（改前无此路径）

    @Test
    @DisplayName("工号 + PIN 正确 ⇒ 签发工人 session（返回 session_id/工号/姓名/闲置分钟数）")
    void loginWithWorkerNoAndPinIssuesWorkerSession() {
        when(userMapper.selectOne(any(Wrapper.class))).thenReturn(worker(WORKER_NO, PIN, "active"));

        Map<String, Object> payload = service.login(TENANT, WORKER_NO, PIN, "PAD-车间-01");

        assertThat(payload.get("session_id")).as("session 载体 = 不可猜的 id").isNotNull();
        assertThat(String.valueOf(payload.get("session_id"))).isNotEmpty();
        assertThat(payload.get("worker_id")).isEqualTo(WORKER_ID);
        assertThat(payload.get("worker_no")).isEqualTo(WORKER_NO);
        assertThat(payload.get("worker_name")).isEqualTo("张三");
        assertThat(payload.get("idle_minutes")).isEqualTo(WorkerSessionService.DEFAULT_IDLE_MINUTES);

        ArgumentCaptor<WorkerSession> captor = ArgumentCaptor.forClass(WorkerSession.class);
        verify(workerSessionMapper).insert(captor.capture());
        WorkerSession session = captor.getValue();
        assertThat(session.getWorkerId()).isEqualTo(WORKER_ID);
        assertThat(session.getDeviceLabel()).isEqualTo("PAD-车间-01");
        assertThat(session.getIdleExpiresAt()).as("闲置过期由服务端算").isAfter(OffsetDateTime.now());
        assertThat(session.getEndedAt()).isNull();
    }

    @Test
    @DisplayName("PIN 错误 ⇒ 401，且**不建会话**（不静默放行）")
    void loginWithWrongPinRejected() {
        when(userMapper.selectOne(any(Wrapper.class))).thenReturn(worker(WORKER_NO, PIN, "active"));

        assertThatThrownBy(() -> service.login(TENANT, WORKER_NO, "000000", null))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(401));
        verify(workerSessionMapper, never()).insert(any(WorkerSession.class));
    }

    @Test
    @DisplayName("非工人档案（worker_no 为 NULL / 查不到）⇒ 401：**工人与商家账号彻底分离**，商家账号登不进来")
    void loginRejectsNonWorkerAccount() {
        when(userMapper.selectOne(any(Wrapper.class))).thenReturn(null);

        assertThatThrownBy(() -> service.login(TENANT, "admin-001", PIN, null))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(401));
        verify(workerSessionMapper, never()).insert(any(WorkerSession.class));
    }

    @Test
    @DisplayName("无租户 ⇒ 401（不静默落入默认租户）")
    void loginWithoutTenantRejected() {
        assertThatThrownBy(() -> service.login(null, WORKER_NO, PIN, null))
                .isInstanceOf(BusinessException.class);
    }

    // ============================================================ ② 服务端解身份（W1）

    @Test
    @DisplayName("有效 session ⇒ 身份来自服务端（server_session），并顺延闲置过期")
    void resolveIdentityFromSession() {
        when(workerSessionMapper.selectActiveById("sess-1")).thenReturn(activeSession("sess-1"));

        WorkerIdentity identity = service.resolveIdentity("sess-1");

        assertThat(identity.workerId()).isEqualTo(WORKER_ID);
        assertThat(identity.workerName()).isEqualTo("张三");
        assertThat(identity.source()).isEqualTo(WorkerIdentity.SOURCE_SERVER_SESSION);
        assertThat(identity.sessionId()).isEqualTo("sess-1");
        assertThat(identity.fromSession()).isTrue();
        verify(workerSessionMapper).touch(eq("sess-1"), any(), any());
    }

    @Test
    @DisplayName("无 sessionId ⇒ resolveIdentity 抛 401（权威形态）；resolveIdentityOrNull 返回 null（过滤器形态）")
    void resolveIdentityWithoutSessionIdIsRejected() {
        assertThatThrownBy(() -> service.resolveIdentity("")).isInstanceOf(BusinessException.class);
        assertThatThrownBy(() -> service.resolveIdentity(null)).isInstanceOf(BusinessException.class);
        // 过滤器层要的是「能不能认证」，不能把异常抛进过滤链（那会变成 500 而不是 401）
        assertThat(service.resolveIdentityOrNull("")).isNull();
        assertThat(service.resolveIdentityOrNull(null)).isNull();
    }

    // ============================================================ ③ 闲置超时（W3）

    @Test
    @DisplayName("🔴 闲置超时后提交 ⇒ 必须被拒（401）且会话落 idle 结束原因（不静默续期、不按上一个人记账）")
    void expiredIdleSessionRejectedAndEnded() {
        WorkerSession expired = activeSession("sess-old");
        expired.setIdleExpiresAt(OffsetDateTime.now().minusMinutes(1));
        when(workerSessionMapper.selectActiveById("sess-old")).thenReturn(expired);

        assertThatThrownBy(() -> service.resolveIdentity("sess-old"))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> {
                    assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(401);
                    assertThat(((BusinessException) e).getCode()).isEqualTo("AUTH_FAILED");
                });
        verify(workerSessionMapper).endSession(eq("sess-old"), any(), eq("idle"));
        verify(workerSessionMapper, never()).touch(anyString(), any(), any());
    }

    @Test
    @DisplayName("已结束/不存在的 session ⇒ 401（切换后旧 id 不得复活）")
    void endedSessionRejected() {
        when(workerSessionMapper.selectActiveById("sess-gone")).thenReturn(null);

        assertThatThrownBy(() -> service.resolveIdentity("sess-gone"))
                .isInstanceOf(BusinessException.class);
    }

    // ============================================================ ④ 快速切换（W2）

    @Test
    @DisplayName("快速切换工人：旧 session 立即结束（end_reason=switched）+ 新 session 签发")
    void switchWorkerEndsOldSessionAndIssuesNewOne() {
        when(userMapper.selectOne(any(Wrapper.class))).thenReturn(worker("W002", PIN, "active"));

        Map<String, Object> payload = service.switchWorker(TENANT, "sess-old", "W002", PIN, null);

        verify(workerSessionMapper).endSession(eq("sess-old"), any(), eq("switched"));
        assertThat(payload.get("session_id")).isNotEqualTo("sess-old");
        assertThat(payload.get("worker_no")).isEqualTo("W002");
    }

    @Test
    @DisplayName("主动登出：幂等（end_reason=logout；空 sessionId 不报错）")
    void logoutIsIdempotent() {
        service.logout("sess-1");
        verify(workerSessionMapper).endSession(eq("sess-1"), any(), eq("logout"));

        service.logout(null); // 不抛
    }

    // ============================================================ ⑤ 共用 PAD 显示面（W2 显示）

    @Test
    @DisplayName("「当前工人：张三」的数据来自**服务端 session**（不是前端 state）")
    void currentWorkerComesFromServerSession() {
        when(workerSessionMapper.selectActiveById("sess-1")).thenReturn(activeSession("sess-1"));

        Map<String, Object> payload = service.currentWorker("sess-1");

        assertThat(payload.get("worker_name")).isEqualTo("张三");
        assertThat(payload.get("worker_no")).isEqualTo(WORKER_NO);
        assertThat(payload.get("session_id")).isEqualTo("sess-1");
        assertThat(payload.get("idle_minutes")).isEqualTo(WorkerSessionService.DEFAULT_IDLE_MINUTES);
    }

    @Test
    @DisplayName("闲置超时可配区间 5~60：越界回落默认 15（不静默接受非法配置）")
    void idleMinutesOutOfRangeFallsBackToDefault() {
        org.springframework.test.util.ReflectionTestUtils.setField(service, "idleMinutes", 1);
        assertThat(service.effectiveIdleMinutes()).isEqualTo(WorkerSessionService.DEFAULT_IDLE_MINUTES);

        org.springframework.test.util.ReflectionTestUtils.setField(service, "idleMinutes", 600);
        assertThat(service.effectiveIdleMinutes()).isEqualTo(WorkerSessionService.DEFAULT_IDLE_MINUTES);

        org.springframework.test.util.ReflectionTestUtils.setField(service, "idleMinutes", 30);
        assertThat(service.effectiveIdleMinutes()).isEqualTo(30);
    }

    // ============================================================ 夹具

    private User worker(String workerNo, String rawPin, String status) {
        User user = new User();
        user.setId(WORKER_ID);
        user.setTenantId(TENANT);
        user.setNickname("张三");
        user.setRole(WorkerSessionService.WORKER_ROLE);
        user.setWorkerNo(workerNo);
        user.setStatus(status);
        user.setPasswordHash(passwordEncoder.encode(rawPin));
        user.setDeleted(0);
        return user;
    }

    private WorkerSession activeSession(String id) {
        OffsetDateTime now = OffsetDateTime.now();
        return WorkerSession.builder()
                .id(id).tenantId(TENANT).workerId(WORKER_ID).workerNo(WORKER_NO).workerName("张三")
                .startedAt(now).lastSeenAt(now).idleExpiresAt(now.plusMinutes(15))
                .createdAt(now).updatedAt(now).deleted(0)
                .build();
    }
}
