// case_ids: OR-076
package com.migao.admin.controller;

import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.OutboundOrderView;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.service.OutboundOrderService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 出库建单的**端点级回执契约**（issue #8490；配套服务级真库判据 {@code OutboundNoTakeRaceRealDbTest}）。
 *
 * <h3>为什么要有它（#6318 的病：服务级绿、端点级红）</h3>
 * 原子占号（{@code ON CONFLICT … DO NOTHING}）把冲突消解在 <b>mapper</b> 里 ⇒ 用户看到的契约**不在那一层**：
 * 状态码与错误码由 {@link GlobalExceptionHandler} 决定。服务级判据只证「服务方法不抛异常 / 回 409」，
 * 而「异常 → HTTP 状态」这一段走偏时，<b>服务级照旧全绿、端点仍是 500</b>。
 *
 * <h3>本类钉住三件事（每件都会红）</h3>
 * <ol>
 *   <li><b>正常回执</b>：号归我 ⇒ {@code 200} + 回执体里就是**最终落库的那个单号**（不是候选）；</li>
 *   <li><b>号段耗尽</b>：{@code OUTBOUND_NO_EXHAUSTED} ⇒ {@code 409} + 具名错误码（不是 500）；</li>
 *   <li><b>改前形态的红证</b>：裸 {@code insert} 撞唯一索引（{@code DuplicateKeyException}）⇒
 *       {@code 500 INTERNAL_ERROR} —— 这正是本单要消掉的那条路径（唯一/非唯一约束违例在
 *       {@code GlobalExceptionHandler} 里刻意只收外键、其余交兜底 500）。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("出库建单端点回执（issue #8490）：200 / 409 / 改前 500 的三面")
class OutboundOrderEndpointReceiptTest {

    private static final String BODY = "{\"items\":[{\"skuId\":11,\"quantity\":1.5}]}";

    @Mock private OutboundOrderService outboundOrderService;

    @InjectMocks private OutboundOrderController controller;

    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(7L);
        // 真异常映射（GlobalExceptionHandler）必须在场：本类的全部断言都是「异常 → HTTP」这一段。
        mockMvc = MockMvcBuilders.standaloneSetup(controller)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    private static OutboundOrderView view(String outboundNo) {
        OutboundOrderView view = new OutboundOrderView();
        view.setOutboundNo(outboundNo);
        view.setStatus("posted");
        return view;
    }

    @Test
    @DisplayName("号归我 ⇒ 200，且回执体里就是最终单号（不是候选）")
    void successfulCreateReturnsTheAssignedNumber() throws Exception {
        when(outboundOrderService.createAndPost(any(), anyLong(), anyString()))
                .thenReturn(view("CK-20261103-0001"));

        mockMvc.perform(post("/api/admin/outbound-orders")
                        .contentType(MediaType.APPLICATION_JSON).content(BODY))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.outboundNo").value("CK-20261103-0001"));
    }

    @Test
    @DisplayName("🔴 号段耗尽 ⇒ 409 + 具名 OUTBOUND_NO_EXHAUSTED（不许变成 500）")
    void exhaustedNumbersSurfaceAsNamed409Not500() throws Exception {
        when(outboundOrderService.createAndPost(any(), anyLong(), anyString()))
                .thenThrow(new BusinessException("OUTBOUND_NO_EXHAUSTED",
                        "出库单号连续 20 次生成失败（当天号段疑似被占满），请稍后重试或联系管理员", 409));

        mockMvc.perform(post("/api/admin/outbound-orders")
                        .contentType(MediaType.APPLICATION_JSON).content(BODY))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.code").value("OUTBOUND_NO_EXHAUSTED"));
    }

    @Test
    @DisplayName("🔴 改前形态的红证：裸 insert 撞唯一索引 ⇒ 端点 500 INTERNAL_ERROR")
    void naiveInsertWouldTurnTheEndpointIntoFiveHundreds() throws Exception {
        // 改前：exists 判假 ⇒ 裸 insert ⇒ 撞 uk_outbound_orders_no ⇒ DuplicateKeyException 直抛。
        // 这条断言钉住「为什么必须修」：该异常在全局处理器里落到兜底 ⇒ 用户侧 500。
        when(outboundOrderService.createAndPost(any(), anyLong(), anyString()))
                .thenThrow(new DuplicateKeyException(
                        "duplicate key value violates unique constraint \"uk_outbound_orders_no\""));

        mockMvc.perform(post("/api/admin/outbound-orders")
                        .contentType(MediaType.APPLICATION_JSON).content(BODY))
                .andExpect(status().isInternalServerError())
                .andExpect(jsonPath("$.error.code").value("INTERNAL_ERROR"))
                .andExpect(jsonPath("$.error.message").value("服务器内部错误"));
    }
}
