// case_ids: MC-090

package com.migao.admin.config;

import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import com.migao.admin.dto.ApiResponse;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;

import jakarta.servlet.http.HttpServletRequest;

import java.lang.reflect.Method;
import java.sql.SQLException;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * 数据库**完整性约束违例**的归口与日志面契约（issue #6210）。
 *
 * <p><b>病（改前形态）</b>：{@code GlobalExceptionHandler} 没有 {@code DataIntegrityViolationException}
 * 分支 ⇒ 外键违例（Spring 把 PG 的 {@code SQLState 23503} 包成它）落兜底
 * {@code Exception} ⇒ 响应 <b>500</b>「服务器内部错误」，且兜底那一行的 {@code log.error(…, e)}
 * 把 <b>完整堆栈</b>打进日志 ⇒ 约束名 {@code agent_sessions_ai_session_id_fkey} 进日志。
 * 实证路径：转人工端点 {@code POST /api/admin/agent-sessions} 传不存在的 {@code aiSessionId}
 * （{@code agent_sessions.ai_session_id REFERENCES sessions(id)}）。</p>
 *
 * <p><b>本判据锁三样</b>（缺一即本修法失效）：</p>
 * <ol>
 *   <li><b>归口</b>：完整性违例 ⇒ <b>4xx</b>（本仓语义：{@code VALIDATION_ERROR} = 422），不落兜底 500；</li>
 *   <li><b>日志脱敏（单侧）</b>：这一类**不打完整堆栈** —— 事件的「格式化消息」与「异常链」里
 *       都不得出现约束名 / 表名；只留可数（{@code method/uri/tenant/kind}）的归因线索；</li>
 *   <li><b>日志不脱敏（另一侧，反向对照）</b>：**别的**未知异常仍须 <b>500</b> 且日志**仍带堆栈**
 *       —— 否则排障失去线索，等于把「过度归口」换成「另一种失败」。</li>
 * </ol>
 *
 * <p><b>测试手法</b>：直接调处理器 + logback {@code ListAppender} 捕获**真实日志事件**
 * （同 {@code MigrationRunnerLegacyNoiseTest}）—— 不断言「某方法被调用」，因为病灶就在日志形态上。
 * 异常用 {@link PlainSqlException} 替身（只覆写 {@code getSQLState()}），**未连真库**：
 * 真库面（MyBatis 的异常翻译链）不在本判据射程，见类级边界的如实登记。</p>
 */
@DisplayName("GlobalExceptionHandler 完整性约束违例归口 + 日志脱敏/不脱敏两侧（issue #6210）")
class GlobalExceptionHandlerDataIntegrityTest {

    /** 与 issue #6210 留档日志逐字相同的那个约束（见 acceptance/2026-10-03/agent-service-sweep）。 */
    private static final String FK_CONSTRAINT = "agent_sessions_ai_session_id_fkey";
    private static final String FK_TABLE = "agent_sessions";
    /** PG 的 SQLState（沿用 JDBC 标准码，取其字面值以免依赖驱动类）。 */
    private static final String FK_SQLSTATE = "23503";
    private static final String UNIQUE_SQLSTATE = "23505";

    private GlobalExceptionHandler handler;
    private Logger handlerLogger;
    private ListAppender<ILoggingEvent> logs;

    @BeforeEach
    void setUp() {
        handler = new GlobalExceptionHandler();
        // 只挂在本处理器自己的 logger 上 ⇒ 捕获的就是这些 handler 方法打出来的事件本身。
        handlerLogger = (Logger) LoggerFactory.getLogger(GlobalExceptionHandler.class);
        logs = new ListAppender<>();
        logs.start();
        handlerLogger.addAppender(logs);
        // logger 是 JVM 内的单例：同一次 surefire 里别的测试可能已经往它打过事件 ⇒ 先清空，
        // 否则「恰一条事件」会数到别人的事件（实测：同一轮 24 个测试共享这一个 logger）。
        logs.list.clear();
    }

    @AfterEach
    void tearDown() {
        handlerLogger.detachAppender(logs);
        logs.stop();
    }

    // ======================== 判据①：归口到 4xx（不是兜底 500） ========================

    @Test
    @DisplayName("外键违例（SQLState 23503）⇒ 422 VALIDATION_ERROR，不落兜底 500")
    void foreignKeyViolationMapsToClientErrorNotFiveHundred() {
        ResponseEntity<ApiResponse<Void>> response =
                handler.handleDataIntegrityViolationException(foreignKeyViolation(), request());

        assertThat(response.getStatusCode())
                .as("外键违例是客户端引用了不存在的行 ⇒ 必须 4xx；落兜底 500 即本单的病")
                .isEqualTo(HttpStatus.UNPROCESSABLE_ENTITY)
                .isNotEqualTo(HttpStatus.INTERNAL_SERVER_ERROR);

        ApiResponse<Void> body = response.getBody();
        assertThat(body).isNotNull();
        assertThat(body.isSuccess()).isFalse();
        assertThat(body.getError().getCode()).isEqualTo("VALIDATION_ERROR");
    }

    @Test
    @DisplayName("响应体不泄漏 schema：不含约束名 / 表名")
    void responseBodyDoesNotLeakConstraintOrTableName() {
        ResponseEntity<ApiResponse<Void>> response =
                handler.handleDataIntegrityViolationException(foreignKeyViolation(), request());

        String wire = String.valueOf(response.getBody().getError().getMessage());
        assertThat(wire)
                .as("响应体是第一泄漏面：约束名 / 表名 / SQLState 都不得出现")
                .doesNotContain(FK_CONSTRAINT)
                .doesNotContain(FK_TABLE);
    }

    // ======================== 判据②：日志脱敏（这一类不打堆栈） ========================

    @Test
    @DisplayName("外键违例的日志：无约束名 / 无表名 / 无堆栈，但有可数的归因线索")
    void foreignKeyViolationLogIsSanitizedAndStillAttributable() {
        handler.handleDataIntegrityViolationException(foreignKeyViolation(), agentSessionsRequest());

        ILoggingEvent event = singleEvent();
        String message = event.getFormattedMessage();
        assertThat(message)
                .as("日志是第一泄漏面（改前 = log.error(…, e) 打完整堆栈 ⇒ 约束名进日志）")
                .doesNotContain(FK_CONSTRAINT)
                .doesNotContain("ERROR: insert or update on table")
                .doesNotContain("at org.postgresql")
                .doesNotContain("at org.springframework.dao");
        assertThat(event.getThrowableProxy())
                .as("这一类不得带异常链 —— 约束名 / 表名都在原始异常消息里")
                .isNull();
        // 脱敏不等于静默：归因线索（端点坐标 + 约束类别）必须仍在，否则这类 4xx 在日志里失联
        assertThat(message)
                .contains("uri=/api/admin/agent-sessions")
                .contains("kind=FOREIGN_KEY");
    }

    // ======================== 判据③：反向对照（别的异常仍 500 且仍带堆栈） ========================

    @Test
    @DisplayName("反向对照：非约束类未知异常 ⇒ 仍 500，且日志仍带完整堆栈（防「一律不打堆栈」）")
    void unknownExceptionStillFiveHundredWithStackTrace() {
        // 用 mock 只借请求坐标（getName() 与 jakarta.servlet 的部署描述符语义冲突，mock 更干净）
        HttpServletRequest request = mock(HttpServletRequest.class);
        when(request.getMethod()).thenReturn("POST");
        when(request.getRequestURI()).thenReturn("/api/admin/agent-sessions");

        ResponseEntity<ApiResponse<Void>> response =
                handler.handleException(new RuntimeException("探针：非约束类未知异常"), request);

        assertThat(response.getStatusCode())
                .as("把兜底一起降成 4xx = 放宽门禁，且真故障会被报成用户输入错误")
                .isEqualTo(HttpStatus.INTERNAL_SERVER_ERROR);
        assertThat(response.getBody().getError().getCode()).isEqualTo("INTERNAL_ERROR");

        ILoggingEvent event = singleEvent();
        assertThat(event.getThrowableProxy())
                .as("500 的排障线索就是堆栈：摘掉它 = 另一种失败")
                .isNotNull();
        assertThat(event.getThrowableProxy().getClassName()).isEqualTo(RuntimeException.class.getName());
        assertThat(event.getThrowableProxy().getMessage()).isEqualTo("探针：非约束类未知异常");
        assertThat(event.getFormattedMessage()).contains("type=java.lang.RuntimeException");
    }

    @Test
    @DisplayName("类级元守卫 · 形态：@ExceptionHandler 台账里有 DB 完整性异常这一类，且归口 4xx")
    void handlerRegistryHasTheDatabaseIntegrityBranchMappedToClientError() {
        boolean declared = false;
        for (Method method : GlobalExceptionHandler.class.getDeclaredMethods()) {
            ExceptionHandler annotation = method.getAnnotation(ExceptionHandler.class);
            if (annotation == null) {
                continue;
            }
            for (Class<?> target : annotation.value()) {
                if (DataIntegrityViolationException.class.isAssignableFrom(target)) {
                    declared = true;
                }
            }
        }
        assertThat(declared)
                .as("归口必须**存在**：没有这条分支时这一类会落兜底 500（正是 #6210 的形态）")
                .isTrue();

        // 归口必须落在 4xx 分支：再跑一次并断言状态码族（防「登记了却仍返 500」）
        ResponseEntity<ApiResponse<Void>> response =
                handler.handleDataIntegrityViolationException(foreignKeyViolation(), request());
        assertThat(response.getStatusCode().value())
                .as("归口到 4xx 才是修好；只把异常登记进台账而仍返 5xx = 纸面修复")
                .isBetween(400, 499);
    }

    // ==================== 判据④：同族（唯一约束）**刻意不拦** —— 既有 5xx 契约不许由本单改 ====================

    @Test
    @DisplayName("同族反向对照：唯一约束违例（23505）**不劫持** ⇒ 仍 500 且仍带堆栈（保既有契约）")
    void uniqueViolationKeepsTheExistingFiveHundredContract() {
        DataIntegrityViolationException ex = withSqlState(UNIQUE_SQLSTATE,
                "ERROR: duplicate key value violates unique constraint \"uk_batch_consumption_stocktake\"");

        ResponseEntity<ApiResponse<Void>> response =
                handler.handleDataIntegrityViolationException(ex, request());

        // 既有契约（MerchantShipmentAtomicityTest / MerchantShipmentRouteTest）：建单写面注入唯一键失败
        // ⇒ **必须仍 5xx**（那两条判的是回滚，但状态码断言也在那儿）⇒ 本单射程刻意收到「外键」。
        assertThat(response.getStatusCode())
                .as("唯一 / 非空 / 检查约束违例是基础设施级失败 ⇒ 保持既有 500，不由本单改口径")
                .isEqualTo(HttpStatus.INTERNAL_SERVER_ERROR);
        assertThat(response.getBody().getError().getCode()).isEqualTo("INTERNAL_ERROR");

        ILoggingEvent event = lastEvent();
        assertThat(event.getFormattedMessage())
                .as("非外键路径的**日志形状**与原兜底逐字节相同（端点坐标 + type + msg）")
                .contains("系统异常: method=")
                .contains("type=org.springframework.dao.DataIntegrityViolationException");
        assertThat(event.getThrowableProxy())
                .as("仍带堆栈 ⇒ 排障线索不因本单受损")
                .isNotNull();
    }

    // ======================== 夹具 ========================

    /** 裸请求坐标替身（不 stub 任何方法 ⇒ 坐标记 {@code null}，不影响本判据的断言面）。 */
    private static HttpServletRequest request() {
        return mock(HttpServletRequest.class);
    }

    /** 带 issue #6210 实测端点坐标的请求替身（只 stub 本判据断言的那个坐标）。 */
    private static HttpServletRequest agentSessionsRequest() {
        HttpServletRequest request = mock(HttpServletRequest.class);
        when(request.getMethod()).thenReturn("POST");
        when(request.getRequestURI()).thenReturn("/api/admin/agent-sessions");
        return request;
    }

    private ILoggingEvent singleEvent() {
        assertThat(logs.list)
                .as("这一类必须在应用日志里留下**恰一条**事件（静默 = 另一侧的失败）")
                .hasSize(1);
        return logs.list.get(0);
    }

    /** 末条事件（非外键路径会先留一行 DEBUG 类别 + 一行兜底 ERROR ⇒ 取末条 = 兜底那条）。 */
    private ILoggingEvent lastEvent() {
        assertThat(logs.list).as("非外键路径也必须留下日志（兜底那条 ERROR）").isNotEmpty();
        return logs.list.get(logs.list.size() - 1);
    }

    private DataIntegrityViolationException foreignKeyViolation() {
        return withSqlState(FK_SQLSTATE, "ERROR: insert or update on table \"" + FK_TABLE
                + "\" violates foreign key constraint \"" + FK_CONSTRAINT + "\"");
    }

    private DataIntegrityViolationException withSqlState(String sqlState, String message) {
        return new DataIntegrityViolationException(message, new PlainSqlException(sqlState, message));
    }

    /**
     * {@code SQLException} 的替身：只覆写 {@code getSQLState()}。
     * （不用 {@code new SQLException(msg, sqlState)} —— 该构造自 Java 9 起 {@code @Deprecated}。）
     */
    private static final class PlainSqlException extends SQLException {
        private final String sqlState;

        private PlainSqlException(String sqlState, String message) {
            super(message);
            this.sqlState = sqlState;
        }

        @Override
        public String getSQLState() {
            return sqlState;
        }
    }
}
