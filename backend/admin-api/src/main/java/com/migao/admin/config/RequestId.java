package com.migao.admin.config;

import jakarta.servlet.http.HttpServletRequest;
import org.slf4j.MDC;
import org.springframework.web.context.request.RequestAttributes;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

import java.util.UUID;
import java.util.regex.Pattern;

/**
 * 请求追踪 ID 的**唯一来源**（issue #6957）。
 *
 * <h3>病（改前，durable 读数）</h3>
 * <p>{@code ApiResponse} 的 {@code requestId} 是**构造响应体时现生成**的（{@code "req_" + UUID}）——
 * 同一请求里构造两个响应体会得到两个不同的 id，而且它**从不进日志**⇒ 响应里的 id 与
 * 服务端日志 / incident 之间**没有任何一条相同的串**。商家说「我点了没反应」时，
 * 客服拿着截图里的 {@code requestId} **反查不到**那条 incident（号线断了）。</p>
 *
 * <h3>口径（改后）</h3>
 * <ol>
 *   <li><b>每请求一个</b>：{@link RequestIdFilter} 在本请求进入 Servlet 链的最前面绑定一个 id
 *       （优先接受上游 {@value #HEADER}，合法才用，否则新生成）；</li>
 *   <li><b>三处同值</b>：请求属性（本类读它）、MDC（日志模式 {@code %X{requestId:-}} 读它）、
 *       响应头 {@value #HEADER}（前端与服务端对账读它）；</li>
 *   <li><b>响应体一律取它</b>：{@code ApiResponse} 的构造函数改成
 *       {@link #current()} ⇒ 5xx / 4xx 的业务错误信封里那个 id 与日志里那条**逐字相同**。</li>
 * </ol>
 *
 * <h3>为什么读请求属性优先于读 MDC</h3>
 * <p>Spring MVC 的错误分派（ERROR dispatch）发生在原请求的 {@code finally} 之后 ——
 * 那时 MDC 已被清掉，但请求属性还在。先读属性 ⇒ 错误分派里构造的信封仍带**同一个** id。</p>
 *
 * <h3>不可用于鉴权</h3>
 * <p>本 id 是**诊断坐标**，不是凭据：它由客户端可传（{@value #HEADER}），服务的任何授权判定
 * 都不得依赖它（合法字符集已收窄为 {@code [A-Za-z0-9._-]{8,64}}，只防日志注入与超长）。</p>
 */
public final class RequestId {

    /** 对账用的响应/请求头名（前端与服务端共用）。 */
    public static final String HEADER = "X-Request-Id";

    /** 日志 MDC 键（日志模式里以 {@code %X{requestId:-}} 呈现）。 */
    public static final String MDC_KEY = "requestId";

    /** 请求属性名（{@link #current()} 的第一读取点）。 */
    public static final String ATTRIBUTE = RequestId.class.getName() + ".id";

    /**
     * 接受的上游 id 形状：足够长到可读、足够短到不撑日志，且**只有** URL 安全字符
     * （排除 {@code \r\n} / 引号 / 空格 ⇒ 日志注入与 JSON 注入都进不来）。
     */
    private static final Pattern ACCEPTED = Pattern.compile("[A-Za-z0-9._-]{8,64}");

    private RequestId() {
    }

    /**
     * 当前请求的追踪 id（**永不返回空**）。
     *
     * <p>读取顺序：请求属性 → MDC → 现生成。最后一档是给**非 HTTP 面**（定时任务等）留的：
     * 那些上下文没有请求可归属，给一个新 id 比给 null 更安全（信封字段永不为空）。</p>
     */
    public static String current() {
        RequestAttributes attributes = RequestContextHolder.getRequestAttributes();
        if (attributes instanceof ServletRequestAttributes servlet) {
            Object bound = servlet.getRequest().getAttribute(ATTRIBUTE);
            if (bound instanceof String id && !id.isBlank()) {
                return id;
            }
        }
        String fromMdc = MDC.get(MDC_KEY);
        if (fromMdc != null && !fromMdc.isBlank()) {
            return fromMdc;
        }
        return generate();
    }

    /** 新生成一个 id（形状与改前的 {@code ApiResponse.generateRequestId()} 逐字相同）。 */
    public static String generate() {
        return "req_" + UUID.randomUUID().toString().replace("-", "").substring(0, 16);
    }

    /**
     * 入口侧取 id：上游传了**合法**的 {@value #HEADER} 就复用它（跨服务串联必需），否则新生成。
     *
     * <p>不合法（长度 / 字符集越界）**不报错、直接换新** —— 那是客户端/网关的问题，
     * 不该让一个诊断头把业务请求挡掉。</p>
     */
    public static String acceptOrGenerate(String incoming) {
        if (incoming != null) {
            String trimmed = incoming.trim();
            if (ACCEPTED.matcher(trimmed).matches()) {
                return trimmed;
            }
        }
        return generate();
    }

    /** 绑定到请求属性 + MDC（只由 {@link RequestIdFilter} 调用，全应用**一处**）。 */
    static void bind(String id, HttpServletRequest request) {
        request.setAttribute(ATTRIBUTE, id);
        MDC.put(MDC_KEY, id);
    }

    /** 解绑 MDC（请求属性**保留**：错误分派要用，见类 javadoc）。 */
    static void unbind() {
        MDC.remove(MDC_KEY);
    }
}
