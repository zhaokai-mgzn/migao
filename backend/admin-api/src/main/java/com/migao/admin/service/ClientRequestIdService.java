package com.migao.admin.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.exception.BusinessException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * 写请求幂等键（issue #4037，F19）—— 去重 / 结果回放 / 占位释放的**单一实现**。
 *
 * <p>背景：ai-agent 工具超时 30s、HTTP 客户端超时 25s ⇒「服务端已落库、客户端报失败」
 * 的窗口客观存在；LLM 重试同一写请求 ⇒ 重复下单 = 直接资金损失。修法 = 调用方在写请求上带
 * {@link #HEADER}，服务端按 {@code (tenant_id, client_request_id)} 去重：
 * 首次请求正常执行并把结果快照落库，同键再次到达 ⇒ **不再执行，直接回放上次成功结果**
 * （顾客/LLM 看到同一订单号/工单号）。</p>
 *
 * <p>四个操作（订单与售后两条写路径复用同一份实现）：</p>
 * <ol>
 *   <li>{@link #claim} —— 原子占位：{@code INSERT ... ON CONFLICT DO NOTHING}，按**影响行数**
 *       判首次。<b>不用「捕获唯一约束异常」探测冲突</b>：PG 里唯一约束冲突会让当前事务进入
 *       aborted 状态，后续查询全失败。</li>
 *   <li>{@link #replay} —— 读回 {@code response_payload}（JSONB）并反序列化成 DTO。
 *       **只回放「已完成」的记录**：占位存在但 payload 为空（首次执行在飞或已失败）
 *       ⇒ 抛 {@link BusinessException}（fail-closed + suggestion），**不得**返回空 DTO。</li>
 *   <li>{@link #complete} —— 执行成功后写入结果快照（{@code UPDATE ... SET response_payload = ?::jsonb}）。</li>
 *   <li>{@link #discard} —— 执行失败时删除占位行；否则**一次失败会把该键永久占死**，
 *       之后所有重试都被误判为「重复」，真正的下单请求反而永远进不来。</li>
 * </ol>
 *
 * <p>向后兼容（硬约束）：幂等键缺失/空白 ⇒ 全部方法 no-op（{@code claim} 返回 true、
 * {@code replay} 返回 {@code Optional.empty()}、{@code complete}/{@code discard} 不发 SQL）
 * —— 老客户端不得因为服务端升级而报错。</p>
 *
 * <p>实现用 {@link JdbcTemplate}：本类只有 4 条定式 SQL、无实体映射需求，
 * 用 MyBatis Mapper 会多出接口 + XML + entity 三份样板（最少代码阶梯：复用已装依赖）。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ClientRequestIdService {

    /** 幂等键请求头名（单一事实源：Controller 与调用方都用它，避免两处字面量漂移） */
    public static final String HEADER = "X-Client-Request-Id";

    /** 与 client_request_keys.client_request_id VARCHAR(128) 同口径（超长直接拒绝，别把 DB 报错透传成 500） */
    private static final int MAX_KEY_LENGTH = 128;

    /**
     * 「占位但无结果」的陈旧阈值（分钟）：超过它仍未写出快照的占位行在**下一次受理时**被回收。
     *
     * <p>为什么必须有 —— 售后路径的占位不在建单事务内（接线在 Controller，见
     * {@code AgentAfterSalesController}）：若「占位已提交 → 进程崩溃/被 kill → complete 未执行」，
     * 会留下 {@code response_payload IS NULL} 的**永久占位**，该键之后所有重试都被 fail-closed 409
     * 挡住且**永不自愈**（响亮但需要人工清理）。订单路径无此问题（占位与建单同事务，崩溃即整体回滚）。
     * 30 分钟远大于 HTTP 客户端 25s / 工具 30s 的重试窗，不会误伤"正在处理中"的真实请求。</p>
     */
    private static final int STALE_PLACEHOLDER_MINUTES = 30;

    /**
     * 延迟获取 {@code JdbcTemplate}（**不是**直接注入）：与 {@code MigrationRunner} 同一取舍 ——
     * 无 DataSource 的测试上下文（{@code SecurityConfigTest} 显式 exclude 了
     * DataSourceAutoConfiguration / MybatisPlusAutoConfiguration / RedisAutoConfiguration）
     * 里没有这个 Bean，直接构造注入会让**整个应用上下文起不来**（13 条既有安全测试当场红）。
     * 拿不到 ⇒ 幂等降级为 no-op 并把原因说清：不是"静默失效"，是"该上下文里没有 DB 可用"。
     */
    private final ObjectProvider<JdbcTemplate> jdbcProvider;
    private final ObjectMapper objectMapper;

    /** 取 JdbcTemplate；不可用（无 DataSource 上下文）返回 null，调用方据此 no-op */
    private JdbcTemplate jdbc() {
        return jdbcProvider == null ? null : jdbcProvider.getIfAvailable();
    }

    /** 幂等键缺失、或本上下文没有 DB ⇒ 本次不做去重（降级要留痕，不静默） */
    private boolean cannotDedupe(String key, String reason) {
        if (key != null) {
            log.warn("[幂等] {}：本次不做去重，重复提交可能重复落库（clientRequestId={}）", reason, key);
        }
        return true;
    }

    /**
     * 原子占位：首次请求返回 true（可执行），同键重复返回 false（不得再执行）。
     *
     * @param endpoint 受理端点标识（诊断用；同键跨端点复用会在表里留下可查证据）
     * @return true = 本请求是首次（或未带幂等键，按首次处理）；false = 同键已被受理过
     */
    public boolean claim(Long tenantId, String clientRequestId, String endpoint) {
        String key = normalize(clientRequestId);
        if (key == null) {
            return true; // 无幂等键 ⇒ 首执（老调用方路径不变）
        }
        JdbcTemplate jdbcTemplate = jdbc();
        if (jdbcTemplate == null) {
            return cannotDedupe(key, "本上下文无 JdbcTemplate（无 DataSource）");
        }
        // 顺手回收陈旧占位（跑在每次受理写请求时，零额外任务；见 STALE_PLACEHOLDER_MINUTES）
        reclaimStale(jdbcTemplate, tenantId);
        int rows = jdbcTemplate.update(
                "INSERT INTO client_request_keys (tenant_id, client_request_id, endpoint) "
                        + "VALUES (?, ?, ?) "
                        + "ON CONFLICT (tenant_id, client_request_id) DO NOTHING",
                tenantId, key, endpoint);
        if (rows == 0) {
            log.info("[幂等] 同键重复请求：跳过执行，回放首次结果 tenantId={}, clientRequestId={}, endpoint={}",
                    tenantId, key, endpoint);
            return false;
        }
        return true;
    }

    /**
     * 回放首次成功的结果快照。
     *
     * <p>无幂等键 ⇒ {@code Optional.empty()}（no-op，调用方走原路径）。
     * <b>有键但无可回放内容（占位在飞/已失败/快照损坏）⇒ 抛异常</b>，绝不返回空结果：
     * 静默返回空 DTO 会让调用方以为「下单成功」—— 那正是 R5 禁止新增的静默失效形态。</p>
     */
    public <T> Optional<T> replay(Long tenantId, String clientRequestId, Class<T> type) {
        String key = normalize(clientRequestId);
        if (key == null) {
            return Optional.empty();
        }
        JdbcTemplate jdbcTemplate = jdbc();
        if (jdbcTemplate == null) {
            // 无 DB ⇒ 无从回放，也**不该**静默当成"首次"（那会重复执行）：fail-closed
            throw new BusinessException("IDEMPOTENCY_STORE_UNAVAILABLE",
                    "幂等存储不可用（本上下文没有 JdbcTemplate），为避免重复执行已拒绝本次请求（clientRequestId=" + key + "）",
                    503,
                    "请稍后重试；若持续失败请联系技术支持（本上下文缺少 DataSource 配置）");
        }
        List<Map<String, Object>> rows = jdbcTemplate.queryForList(
                "SELECT response_payload::text AS payload FROM client_request_keys "
                        + "WHERE tenant_id = ? AND client_request_id = ?",
                tenantId, key);
        Object payload = rows.isEmpty() ? null : rows.get(0).get("payload");
        if (payload == null || !StringUtils.hasText(String.valueOf(payload))) {
            // 占位在但无结果：首次执行仍在飞或已失败 ⇒ fail-closed（不返回空结果、不再执行）
            throw inProgress(key);
        }
        try {
            return Optional.of(replayedMarker(objectMapper.readValue(String.valueOf(payload), type)));
        } catch (Exception e) {
            log.error("[幂等] 结果快照反序列化失败: clientRequestId={}", key, e);
            throw new BusinessException("REPLAY_FAILED",
                    "同一 X-Client-Request-Id（" + key + "）的结果快照无法解析，为避免重复执行已拒绝本次请求",
                    500,
                    "请勿重复提交；请稍后用查询工具（order_query / 售后查询）确认结果，"
                            + "确需重试请联系技术支持清理该幂等键");
        }
    }

    /**
     * 给回放结果打上「这是回放、没有新落库」的标记（键名 {@code replayed}，取值 true）。
     *
     * <p>为什么必须有：不加标记时调用方**分不出**「首次执行成功」与「同键回放」——
     * ai-agent 侧就无法告知顾客/模型"这笔订单此前已创建、没有重复下单"，
     * 一次重试会被播报成两张订单（观察性缺陷）。</p>
     *
     * <p>为什么要**反序列化后回填**而不是"只在快照 JSON 里塞个键"：标记字段必须真实存在于
     * 响应 DTO 上（两个 DTO 已加 {@code @JsonInclude(NON_NULL) Boolean replayed}）。
     * 只在 JSON 里塞键时，Jackson 反序列化回 DTO 会把它**静默丢掉**（DTO 无该字段，且已声明
     * {@code ignoreUnknown=true}）⇒ 响应里永远不出现，判据只剩一条专门写的断言 ——
     * 正是 R5「标记算出来了、然后被无声丢弃」的形态（本地实测：断言当场红）。</p>
     */
    @SuppressWarnings("unchecked")
    private <T> T replayedMarker(T value) {
        Map<String, Object> tree = objectMapper.convertValue(value, Map.class);
        tree.put("replayed", Boolean.TRUE);
        return (T) objectMapper.convertValue(tree, value.getClass());
    }

    /** 执行成功后写入结果快照（同键后续请求回放它）。无幂等键 ⇒ no-op。 */
    public void complete(Long tenantId, String clientRequestId, Object payload) {
        String key = normalize(clientRequestId);
        if (key == null) {
            return;
        }
        JdbcTemplate jdbcTemplate = jdbc();
        if (jdbcTemplate == null) {
            cannotDedupe(key, "本上下文无 JdbcTemplate（无 DataSource），结果快照未落库");
            return;
        }
        String json;
        try {
            json = objectMapper.writeValueAsString(payload);
        } catch (Exception e) {
            // 不静默：写不出快照就必须让本次执行失败（否则同键重试会被 fail-closed 永久拦住且无解释）
            log.error("[幂等] 结果快照序列化失败: clientRequestId={}", key, e);
            throw new BusinessException("REPLAY_SNAPSHOT_FAILED",
                    "幂等结果快照序列化失败，为避免「执行成功却无法回放」已回滚本次请求（clientRequestId=" + key + "）",
                    500,
                    "请重试；若持续失败请联系技术支持");
        }
        jdbcTemplate.update(
                "UPDATE client_request_keys SET response_payload = ?::jsonb "
                        + "WHERE tenant_id = ? AND client_request_id = ?",
                json, tenantId, key);
    }

    /**
     * 执行失败时释放占位（删除该键的行）。无幂等键 ⇒ no-op。
     *
     * @return 实际删除的行数（0 = 本来就没有占位行）
     */
    public int discard(Long tenantId, String clientRequestId) {
        String key = normalize(clientRequestId);
        if (key == null) {
            return 0;
        }
        JdbcTemplate jdbcTemplate = jdbc();
        if (jdbcTemplate == null) {
            return 0;
        }
        int rows = jdbcTemplate.update(
                "DELETE FROM client_request_keys WHERE tenant_id = ? AND client_request_id = ?",
                tenantId, key);
        log.info("[幂等] 释放占位: tenantId={}, clientRequestId={}, rows={}", tenantId, key, rows);
        return rows;
    }

    /**
     * 回收本租户的**陈旧占位**（{@code response_payload IS NULL} 且超过阈值）—— 自愈机制。
     *
     * <p>删除即"重新可受理"：该键随后的请求会被当成首次执行（不再永久 409）。
     * 失败只记日志不抛：回收是**尽力而为**的运维动作，不得因为清理失败而挡住正常写请求。</p>
     */
    private void reclaimStale(JdbcTemplate jdbcTemplate, Long tenantId) {
        try {
            int rows = jdbcTemplate.update(
                    "DELETE FROM client_request_keys "
                            + "WHERE tenant_id = ? AND response_payload IS NULL "
                            + "AND created_at < NOW() - make_interval(mins => ?)",
                    tenantId, STALE_PLACEHOLDER_MINUTES);
            if (rows > 0) {
                log.warn("[幂等] 回收陈旧占位 {} 行（占位超过 {} 分钟仍无结果，多为执行中崩溃）: tenantId={}",
                        rows, STALE_PLACEHOLDER_MINUTES, tenantId);
            }
        } catch (Exception e) {
            log.warn("[幂等] 陈旧占位回收失败（非致命，不影响本次受理）: tenantId={}, error={}",
                    tenantId, e.getMessage());
        }
    }

    /** 「已受理但无结果」的统一 fail-closed 异常（带可行动 suggestion） */
    private BusinessException inProgress(String key) {
        return new BusinessException("REQUEST_IN_PROGRESS",
                "同一 X-Client-Request-Id（" + key + "）的请求已受理但尚无结果，本次未重复执行、也未返回空结果（请勿重复提交）",
                409,
                "该请求可能仍在处理中：请勿重复提交（换新幂等键重试同样会造成重复下单/重复建单）；"
                        + "请稍后用查询工具确认结果");
    }

    /**
     * 归一化幂等键：缺失/空白 ⇒ null（调用方据此走 no-op 分支）。
     * 超长直接拒绝 —— 别让 {@code varchar(128)} 的 DB 报错以 500 形态冒到调用方。
     */
    private String normalize(String clientRequestId) {
        if (!StringUtils.hasText(clientRequestId)) {
            return null;
        }
        String key = clientRequestId.trim();
        if (key.length() > MAX_KEY_LENGTH) {
            throw BusinessException.validationError(
                    "X-Client-Request-Id 超长（" + key.length() + " > " + MAX_KEY_LENGTH + "），拒绝受理");
        }
        return key;
    }
}