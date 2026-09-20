package com.migao.admin.worker;

import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.User;
import com.migao.admin.entity.WorkerSession;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.UserMapper;
import com.migao.admin.mapper.WorkerSessionMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.time.Duration;
import java.time.OffsetDateTime;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;

/**
 * 工人登录态服务（issue #4733）—— **计件归属的唯一根**。
 *
 * <p>四条纪律（每条都有对应断言，见 {@code WorkerSessionServiceTest}）：</p>
 * <ol>
 *   <li><b>身份只由服务端解</b>：{@link #resolveIdentity} 只认 {@code X-Worker-Session-Id}
 *       ⇒ 报工写库的 {@code worker_id}/{@code worker_name} 与 body 里的同名字段**无关**
 *       （设计 #4716 W1 的红证：body 传别人的 id ⇒ 仍记成登录者）。</li>
 *   <li><b>闲置超时由服务端算</b>：{@code idle_expires_at} 过期 ⇒ 401（**不静默续期**）
 *       —— 共用 PAD 上「上一个人走了没登出」不得把活记到上一个人头上（W3）。</li>
 *   <li><b>快速切换立即失效旧会话</b>：{@link #switchWorker} 结束旧 session（{@code switched}）
 *       ⇒ 旧 session id 再用 ⇒ 401（W2）。</li>
 *   <li><b>与商家账号彻底分离</b>：本服务只签发 {@code roles=["worker"]}、
 *       {@code permissions=[]} 的身份；session 只对 {@code /api/worker/**} 有效，
 *       工人 session **不得**进 {@code /api/admin/**}（W7，见 {@code SecurityConfig}）。</li>
 * </ol>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class WorkerSessionService {

    /** 工人角色码：`/api/admin/**` 拒绝集合里的那一项（与 SecurityConfig 同一字面量）。 */
    public static final String WORKER_ROLE = "worker";

    /** 工人 session 的请求头（与前端 `workerSession.ts` 逐字同名）。 */
    public static final String SESSION_HEADER = "X-Worker-Session-Id";

    /** 闲置超时默认值（分钟）：主会话裁定 R2 = 默认 15、可配 5~60。 */
    public static final int DEFAULT_IDLE_MINUTES = 15;

    /** 闲置超时可配区间下界（分钟）。 */
    public static final int MIN_IDLE_MINUTES = 5;

    /** 闲置超时可配区间上界（分钟）。 */
    public static final int MAX_IDLE_MINUTES = 60;

    private final WorkerSessionMapper workerSessionMapper;
    private final UserMapper userMapper;
    private final PasswordEncoder passwordEncoder;

    /** 租户级闲置超时（分钟）；越界值回落到默认并**打警告**（不静默接受非法配置）。 */
    @Value("${worker.session.idle-minutes:" + DEFAULT_IDLE_MINUTES + "}")
    private int idleMinutes = DEFAULT_IDLE_MINUTES;

    /**
     * 工号 + PIN 登录 ⇒ 签发工人 session。
     *
     * <p>失败形态**统一**为 401 且文案一致（工号不存在 / PIN 错误 / 非工人档案 / 已停用
     * 不给出可区分的答复）—— 否则登录端点变成「这个工号存不存在」的枚举器。</p>
     *
     * @param tenantId   租户（由域名/网关头解析；无租户 ⇒ 调用方已拒绝）
     * @param workerNo   工号
     * @param pin        PIN（明文，仅用于 BCrypt 比对，不落日志）
     * @param deviceLabel 设备标签（PAD-车间-01 之类，可空）
     */
    @Transactional
    public Map<String, Object> login(Long tenantId, String workerNo, String pin, String deviceLabel) {
        if (tenantId == null) {
            throw BusinessException.tenantInvalid();
        }
        if (!StringUtils.hasText(workerNo) || !StringUtils.hasText(pin)) {
            throw BusinessException.validationError("工号与 PIN 均不能为空");
        }
        User worker = findWorkerByNo(tenantId, workerNo.trim());
        if (worker == null || !StringUtils.hasText(worker.getPasswordHash())
                || !passwordEncoder.matches(pin, worker.getPasswordHash())) {
            log.warn("[工人登录] 失败：租户 {} 工号 {}（凭据不匹配或非工人档案）", tenantId, workerNo);
            throw BusinessException.authFailed("工号或 PIN 不正确");
        }
        if (!"active".equals(worker.getStatus())) {
            log.warn("[工人登录] 失败：工号 {} 档案非 active（status={}）", workerNo, worker.getStatus());
            throw BusinessException.authFailed("工号或 PIN 不正确");
        }
        WorkerSession session = createSession(tenantId, worker, deviceLabel);
        log.info("[工人登录] 成功：tenantId={}, workerNo={}, sessionId={}", tenantId, workerNo, session.getId());
        return sessionPayload(session);
    }

    /**
     * 解析报工身份（**服务端解身份**的唯一入口，设计 W1）。
     *
     * @param sessionId 请求头 {@link #SESSION_HEADER} 的取值（可空）
     * @return 工人身份；无 sessionId ⇒ 返回 {@code null}（调用方**显式**降级到 body 口径并标注来源）
     * @throws BusinessException 401 —— sessionId 存在但无效/已结束/已闲置过期（**不静默降级**）
     */
    public WorkerIdentity resolveIdentity(String sessionId) {
        WorkerIdentity identity = resolveIdentityOrNull(sessionId);
        if (identity == null) {
            throw BusinessException.authFailed(
                    "尚未登录工人身份或登录已失效，请重新用工号 + PIN 登录");
        }
        return identity;
    }

    /**
     * 解析报工身份（**不抛异常**的形态）：无效 / 已结束 / 已闲置超时一律返回 {@code null}。
     *
     * <p>给 {@link com.migao.admin.security.WorkerSessionFilter} 用 —— 过滤器层需要的是
     * 「能不能认证」，不能把异常抛进过滤链（那会变成 500 而不是 401）。控制器侧仍用
     * {@link #resolveIdentity} 拿可读文案。</p>
     */
    public WorkerIdentity resolveIdentityOrNull(String sessionId) {
        WorkerSession session = loadActiveSession(sessionId);
        if (session == null) {
            return null;
        }
        OffsetDateTime now = OffsetDateTime.now();
        if (session.getIdleExpiresAt() == null || !session.getIdleExpiresAt().isAfter(now)) {
            // 闲置超时：结束会话（留痕 idle）+ 拒绝 —— **绝不**静默续期、更不静默按上一个人记账
            workerSessionMapper.endSession(session.getId(), now, "idle");
            log.warn("[工人登录态] 闲置超时：sessionId={}, workerId={}", session.getId(), session.getWorkerId());
            return null;
        }
        workerSessionMapper.touch(session.getId(), now, now.plusMinutes(effectiveIdleMinutes()));
        return new WorkerIdentity(session.getWorkerId(), session.getWorkerName(),
                WorkerIdentity.SOURCE_SERVER_SESSION, session.getId());
    }

    /**
     * 读会话行 + **定租户**（issue #4864）—— 全仓唯一一处「租户由会话行解出」的实现。
     *
     * <p><b>为什么需要它</b>：改前 {@code worker_sessions} 的读取受租户拦截器管，而租户**正是**
     * 要从会话行里取的 ⇒ 循环（读行要租户、租户来自行）⇒ 拦截器抛
     * {@code Tenant context not initialized} ⇒ {@code /api/worker/**} 除 {@code /login} 外全部 401。
     * 破环口径 = 会话查找走**不受租户拦截器约束**的按主键查询
     * （{@code WorkerSessionMapper.selectActiveById} 的 {@code @InterceptorIgnore}，
     * 安全性论证见该处 javadoc），拿到行之后**才**把租户定下来。</p>
     *
     * <p>三条纪律（每条都有断言，见 {@code WorkerTenantCycleGuardTest}）：</p>
     * <ol>
     *   <li><b>租户只来自会话行</b>：{@code TenantContext} 只被设为 {@code session.getTenantId()}，
     *       请求里的任何东西（{@code Host} / {@code X-Tenant-Id} / body）都改不了它；</li>
     *   <li><b>请求已带租户时必须一致</b>（fail-closed）：线程上已有 {@code TenantContext}
     *       （商家 JWT / Service Token / 别的工人会话）且与会话租户不符 ⇒ 当无效会话拒绝。
     *       没有这条，「免租户查询」就会变成一条**换租户**的通道（A 租户的身份 + B 租户的
     *       session id ⇒ 在 B 租户上下文里执行）；</li>
     *   <li><b>先定租户、再做后续租户受管的写</b>：{@code endSession} / {@code touch} 仍带
     *       {@code tenant_id} 谓词（第二道闸），故租户必须在它们之前设好。</li>
     * </ol>
     *
     * @param sessionId 请求头 {@code X-Worker-Session-Id} 的取值（可空）
     * @return 会话行；空/不存在/已结束/租户不一致 ⇒ {@code null}（调用方 fail-closed 拒绝）
     */
    private WorkerSession loadActiveSession(String sessionId) {
        if (!StringUtils.hasText(sessionId)) {
            return null;
        }
        // ① 按主键直查：这条查询**不需要**租户条件 —— 租户正是它要解出来的东西。
        WorkerSession session = workerSessionMapper.selectActiveById(sessionId.trim());
        if (session == null) {
            log.debug("[工人登录态] session 不存在/已结束：{}", sessionId);
            return null;
        }
        // ② 请求已带租户上下文 ⇒ 会话必须同租户（否则「免租户查询」会变成换租户通道）
        Long requestTenant = TenantContext.getTenantId();
        if (requestTenant != null && !requestTenant.equals(session.getTenantId())) {
            log.warn("[工人登录态] 会话租户 {} 与请求租户 {} 不一致 ⇒ 拒绝：sessionId={}",
                    session.getTenantId(), requestTenant, session.getId());
            return null;
        }
        // ③ 读完行**才**能把租户定下来：此后本线程所有查询（touch/endSession/业务读面）恢复租户过滤
        TenantContext.setTenantId(session.getTenantId());
        return session;
    }

    /**
     * 快速切换工人（共用 PAD，设计 W2）：结束旧 session（{@code switched}）+ 建新 session。
     *
     * <p>旧 session **立即失效** ⇒ 用旧 id 报工必 401（否则会把活记到上一个人头上）。
     * 扫码上下文由前端保留（本方法不碰任何报工上下文）。</p>
     */
    @Transactional
    public Map<String, Object> switchWorker(Long tenantId, String currentSessionId,
                                            String workerNo, String pin, String deviceLabel) {
        if (StringUtils.hasText(currentSessionId)) {
            workerSessionMapper.endSession(currentSessionId.trim(), OffsetDateTime.now(), "switched");
        }
        return login(tenantId, workerNo, pin, deviceLabel);
    }

    /** 主动登出（幂等：重复登出不报错，也不改首次的结束原因）。 */
    @Transactional
    public void logout(String sessionId) {
        if (!StringUtils.hasText(sessionId)) {
            return;
        }
        workerSessionMapper.endSession(sessionId.trim(), OffsetDateTime.now(), "logout");
    }

    /** 当前工人信息（报工页页头「当前工人：张三」的数据来源 = **服务端 session**，不是前端 state）。 */
    public Map<String, Object> currentWorker(String sessionId) {
        // 与 resolveIdentity 走**同一处**读行/定租户（issue #4864）：否则这条端点会绕过
        // 「会话租户必须与请求租户一致」那条 fail-closed 判定。
        WorkerSession session = loadActiveSession(sessionId);
        if (session == null) {
            throw BusinessException.authFailed("工人登录已失效，请重新登录");
        }
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("worker_id", session.getWorkerId());
        payload.put("worker_no", session.getWorkerNo());
        payload.put("worker_name", session.getWorkerName());
        payload.put("session_id", session.getId());
        payload.put("device_label", session.getDeviceLabel());
        payload.put("idle_expires_at", session.getIdleExpiresAt() == null ? null
                : session.getIdleExpiresAt().toString());
        payload.put("idle_minutes", effectiveIdleMinutes());
        return payload;
    }

    /** 生效的闲置超时（分钟）：越界/非正数回落默认并打警告（配置非法不得静默生效）。 */
    public int effectiveIdleMinutes() {
        if (idleMinutes < MIN_IDLE_MINUTES || idleMinutes > MAX_IDLE_MINUTES) {
            log.warn("[工人登录态] 闲置超时配置 {} 分钟越界（允许 {}~{}），回落默认 {} 分钟",
                    idleMinutes, MIN_IDLE_MINUTES, MAX_IDLE_MINUTES, DEFAULT_IDLE_MINUTES);
            return DEFAULT_IDLE_MINUTES;
        }
        return idleMinutes;
    }

    /** 建会话行（PIN 校验已通过）。 */
    private WorkerSession createSession(Long tenantId, User worker, String deviceLabel) {
        OffsetDateTime now = OffsetDateTime.now();
        WorkerSession session = WorkerSession.builder()
                .id(UUID.randomUUID().toString().replace("-", ""))
                // tenant_id 由 TenantLineInnerInterceptor 按 TenantContext 注入（本方法调用前已设好），
                // 不在此硬编码 —— 两处都写会在 INSERT 上出现重复列
                .workerId(worker.getId())
                .workerNo(worker.getWorkerNo())
                .workerName(worker.getNickname())
                .deviceLabel(StringUtils.hasText(deviceLabel) ? deviceLabel.trim() : null)
                .startedAt(now)
                .lastSeenAt(now)
                .idleExpiresAt(now.plus(Duration.ofMinutes(effectiveIdleMinutes())))
                .createdAt(now)
                .updatedAt(now)
                .deleted(0)
                .build();
        workerSessionMapper.insert(session);
        return session;
    }

    /**
     * 按工号查工人档案（租户内）。
     *
     * <p>{@code worker_no IS NOT NULL} 是「只认工人档案」的机械保证：商家用户即使被误填工号
     * 也进不来（工人与商家账号彻底分离）。</p>
     */
    private User findWorkerByNo(Long tenantId, String workerNo) {
        Long previous = TenantContext.getTenantId();
        TenantContext.setTenantId(tenantId);
        try {
            return userMapper.selectOne(new com.baomidou.mybatisplus.core.conditions.query.QueryWrapper<User>()
                    .eq("worker_no", workerNo)
                    .isNotNull("worker_no")
                    .eq("deleted", 0)
                    .last("LIMIT 1"));
        } finally {
            // 恢复（不得把登录期的租户上下文泄漏给后续逻辑）
            if (previous == null) {
                TenantContext.clear();
            } else {
                TenantContext.setTenantId(previous);
            }
        }
    }

    private Map<String, Object> sessionPayload(WorkerSession session) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("session_id", session.getId());
        payload.put("worker_id", session.getWorkerId());
        payload.put("worker_no", session.getWorkerNo());
        payload.put("worker_name", session.getWorkerName());
        payload.put("idle_minutes", effectiveIdleMinutes());
        payload.put("idle_expires_at", session.getIdleExpiresAt().toString());
        return payload;
    }
}
