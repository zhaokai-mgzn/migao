// case_ids: MC-139
package com.migao.admin.config;

import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.exception.BusinessException;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.slf4j.LoggerFactory;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 实例判据（issue #6957）：**商家看到的编号 = 服务端日志里那个编号 = 响应头那个编号**。
 *
 * <h3>病（改前，durable 读数）</h3>
 * <p>{@code frontend/admin-web/src/lib/request.ts} 的失败分支只 toast {@code message}；
 * 而服务端的 {@code requestId} 是**构造响应体时现生成**的、**从不进日志** ⇒ 商家说
 * 「我点了没反应」时，客服拿不到任何可反查的串（截图里连编号都没有，日志里也没有对应关系）。</p>
 *
 * <h3>本判据守什么</h3>
 * <ol>
 *   <li><b>5xx</b>：响应体的 {@code requestId} 非空，且与响应头 {@code X-Request-Id}
 *       <b>以及</b> {@code GlobalExceptionHandler} 打的那行 error 日志里的 id <b>逐字相同</b>；</li>
 *   <li><b>可预期的 4xx 业务错</b>（{@code VALIDATION_ERROR}）：同样三处同值；</li>
 *   <li><b>上游传入的 id 被复用</b>：跨服务串联时不能换号；</li>
 *   <li><b>不合法上游 id 不采信</b>（换新号，且不把它写进响应/日志）；</li>
 *   <li><b>反向对照</b>：没挂过滤器时信封仍有 id（有值 ≠ 三处同值）—— 这一条防「判据 1 靠
 *       'requestId 非空' 蒙混过关」。</li>
 * </ol>
 *
 * <h3>红证（注入式，读数见 PR body）</h3>
 * <p>① 把 {@link RequestIdFilter} 里的 {@code RequestId.bind(...)} 摘掉 ⇒ 判据 1/2/3 红
 * （响应头有号，而响应体/日志是另生成的号）；② 把 {@code ApiResponse} 构造函数的
 * {@code RequestId.current()} 改回现生成 ⇒ 同样红。</p>
 */
class RequestIdTraceabilityTest {

    private MockMvc mockMvc;
    private ListAppender<ILoggingEvent> appender;
    private Logger handlerLogger;

    @BeforeEach
    void setUp() {
        mockMvc = MockMvcBuilders.standaloneSetup(new BoomController())
                .setControllerAdvice(new GlobalExceptionHandler())
                .addFilters(new RequestIdFilter())
                .build();
        appender = new ListAppender<>();
        appender.start();
        handlerLogger = (Logger) LoggerFactory.getLogger(GlobalExceptionHandler.class);
        handlerLogger.setLevel(Level.WARN);
        handlerLogger.addAppender(appender);
    }

    @AfterEach
    void tearDown() {
        handlerLogger.detachAppender(appender);
        appender.stop();
    }

    @Test
    @DisplayName("5xx：响应体 requestId = 响应头 = 日志里那行（三处同值）")
    void fiveXxCarriesTheSameRequestIdInBodyHeaderAndLog() throws Exception {
        mockMvc.perform(get("/boom").header(RequestId.HEADER, "trace-6957-fivexx"))
                .andExpect(status().isInternalServerError())
                .andExpect(header().string(RequestId.HEADER, "trace-6957-fivexx"))
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.code").value("INTERNAL_ERROR"))
                .andExpect(jsonPath("$.requestId").value("trace-6957-fivexx"));

        assertThat(singleLogLine())
                .as("500 的日志行必须带同一个 requestId（客服据此反查）")
                .contains("requestId=trace-6957-fivexx")
                .contains("/boom");
    }

    @Test
    @DisplayName("可预期的 4xx 业务错：同样三处同值")
    void expectedBusinessErrorCarriesTheSameRequestId() throws Exception {
        mockMvc.perform(get("/business").header(RequestId.HEADER, "trace-6957-fourxx"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(header().string(RequestId.HEADER, "trace-6957-fourxx"))
                .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"))
                .andExpect(jsonPath("$.requestId").value("trace-6957-fourxx"));
    }

    @Test
    @DisplayName("上游没传 id ⇒ 服务端生成一个，响应体/响应头/日志仍是同一个")
    void generatedRequestIdIsStableAcrossBodyHeaderAndLog() throws Exception {
        MvcResult result = mockMvc.perform(get("/boom"))
                .andExpect(status().isInternalServerError())
                .andExpect(header().exists(RequestId.HEADER))
                .andReturn();
        String body = result.getResponse().getContentAsString();
        String headerId = result.getResponse().getHeader(RequestId.HEADER);

        assertThat(headerId).as("生成的 id 形状与改前一致（req_ + 16 位十六进制）")
                .matches("req_[0-9a-f]{16}");
        assertThat(body).contains("\"requestId\":\"" + headerId + "\"");
        assertThat(singleLogLine()).contains("requestId=" + headerId);
    }

    @Test
    @DisplayName("不合法上游 id 不采信：换新号，且不把它写进响应或日志")
    void invalidIncomingRequestIdIsReplaced() throws Exception {
        String injected = "bad id with spaces";
        String body = mockMvc.perform(get("/boom").header(RequestId.HEADER, injected))
                .andExpect(status().isInternalServerError())
                .andReturn().getResponse().getContentAsString();

        assertThat(body).doesNotContain(injected);
        assertThat(singleLogLine()).doesNotContain(injected);
    }

    @Test
    @DisplayName("反向对照：没有过滤器时信封仍有 id（有值 ≠ 三处同值）")
    void withoutTheFilterTheEnvelopeStillCarriesAGeneratedId() {
        ApiResponse<Void> response = ApiResponse.error("INTERNAL_ERROR", "服务器内部错误");
        assertThat(response.getRequestId()).matches("req_[0-9a-f]{16}");
    }

    private String singleLogLine() {
        List<ILoggingEvent> events = appender.list;
        assertThat(events).as("GlobalExceptionHandler 必须留下一条错误事件").isNotEmpty();
        return events.get(events.size() - 1).getFormattedMessage();
    }

    /** 两个出口：500（未预期异常）与 422（可预期的业务错）。 */
    @RestController
    static class BoomController {

        @GetMapping("/boom")
        String boom() {
            // 刻意用**没有具名分支**的异常 ⇒ 落 GlobalExceptionHandler 的兜底 500
            // （IllegalStateException 有具名分支，会变 400 —— 那不是本判据要的形态）
            throw new RuntimeException("boom-6957");
        }

        @GetMapping("/business")
        String business() {
            throw BusinessException.validationError("参数不合法（6957）");
        }
    }
}
