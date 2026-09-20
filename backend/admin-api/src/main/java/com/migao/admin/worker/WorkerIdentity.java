package com.migao.admin.worker;

/**
 * 报工身份（issue #4733，设计 #4716 的 **W1**）。
 *
 * <p>🔴 唯一权威来源 = 工人 session（{@code worker_sessions}）：报工请求只带
 * {@code X-Worker-Session-Id}，{@code worker_id}/{@code worker_name} 由**服务端**从 session 解出，
 * <b>一律忽略 body 里的同名字段</b> —— 前端可被改，而 {@code production_work_logs.worker_id}
 * 是**工资凭证**（计件归属的唯一根）。</p>
 *
 * <p><b>兼容取舍（显式，不静默）</b>：无工人 session 时（商家侧报工 / 尚未升级的调用方）沿用既有
 * body 口径，但 {@link #source()} 被**显式标注**为 {@link #SOURCE_CLIENT_BODY} 并落
 * {@code worker_report_audits} ⇒ 「谁都能填」这件事在数据上**可见**，而不是继续静默。</p>
 *
 * @param workerId 工人 id（{@code users.id}）；无身份时为 {@code null}
 * @param workerName 工人姓名（{@code users.nickname}）；无身份时为 {@code null}
 * @param source 身份来源：{@link #SOURCE_SERVER_SESSION} / {@link #SOURCE_CLIENT_BODY}
 * @param sessionId 工人 session id（仅 {@link #SOURCE_SERVER_SESSION} 时有值）
 */
public record WorkerIdentity(String workerId, String workerName, String source, String sessionId) {

    /** 身份由服务端从工人 session 解出（**权威**，body 同名字段被忽略）。 */
    public static final String SOURCE_SERVER_SESSION = "server_session";

    /** 无工人 session：显式沿用既有 body 口径（商家侧报工），来源被标注。 */
    public static final String SOURCE_CLIENT_BODY = "client_body";

    /** 无工人 session 的显式降级：沿用既有 body 口径，并**标注**来源。 */
    public static WorkerIdentity fromClientBody(String workerId, String workerName) {
        return new WorkerIdentity(workerId, workerName, SOURCE_CLIENT_BODY, null);
    }

    /** 身份是否来自服务端 session（权威路径）。 */
    public boolean fromSession() {
        return SOURCE_SERVER_SESSION.equals(source);
    }
}
