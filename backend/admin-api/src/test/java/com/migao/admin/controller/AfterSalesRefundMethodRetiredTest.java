// case_ids: AS-015
package com.migao.admin.controller;

import com.migao.admin.dto.AfterSalesDetailResponse;
import com.migao.admin.dto.AfterSalesListResponse;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.entity.AfterSalesTicket;
import com.migao.admin.service.AfterSalesTicketService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.test.web.servlet.MockMvc;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.math.BigDecimal;
import java.util.List;
import java.util.stream.Collectors;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 售后响应**不再携带** {@code refundMethod}（issue #6224，用户 2026-10-03 裁定「退款方式 不用记」⇒ 选项 2 下线）。
 *
 * <h2>修的是什么</h2>
 * {@code refundMethod} 是**零生产者字段**：DB 列 {@code after_sales_tickets.refund_method} 全仓**零写点**
 * （无 INSERT / UPDATE / 无 setter 实参写入），只有「实体 getter → 响应 DTO setter」的**直通**
 * ⇒ 详情 / 列表响应里它**恒不出现**（{@code NON_NULL}），前端 {@code types} 却声明了它
 * ⇒ 前后端都以为「有这么一个可读字段」，实际永远是空。
 *
 * <h2>两条判据（缺一条就漏一族）</h2>
 * <ol>
 *   <li><b>判据 1（形状，加回去即红）</b>：三个 Java 载体（实体 + 两个响应 DTO）上**不得**再出现
 *       {@code refundMethod} 字段 / {@code getRefundMethod} / {@code setRefundMethod}。
 *       反射判据与 Jackson 的 null 策略**无关** ⇒ 把字段加回去 ⇒ **当场红**（这是本判据的判别力所在）。</li>
 *   <li><b>判据 2（线上响应，键不存在而不是值为 null）</b>：真走一次
 *       {@code GET /api/admin/after-sales}（列表）与 {@code GET /api/admin/after-sales/{id}}（详情）
 *       ⇒ 响应体里**不得出现** {@code refundMethod} 键；同时给出**正对照**
 *       （{@code ticketNo} / {@code refundAmount} 在），证明「读到的是那份真响应」而不是空壳。</li>
 * </ol>
 *
 * <h2>射程边界（照实登记，§19.1）</h2>
 * <ul>
 *   <li>MockMvc 走 {@code standaloneSetup} ⇒ 用的是**默认** Jackson（**会**序列化 null），比线上
 *       （{@code spring.jackson.default-property-inclusion: non_null}）**更严**：线上恒不出现的键，
 *       在这里只要字段存在就会以 {@code "refundMethod":null} 现身 ⇒ 判据 2 不会因为「值恰好是 null」而假绿。</li>
 *   <li>判据 1 只认**本仓这三个载体**；「别的响应 DTO 是否也有零生产者字段」由类级元守卫
 *       {@code com.migao.admin.contract.FrontendUnionFieldProducerMetaGuardTest} 承担（前置类型须是联合类型）。</li>
 *   <li>本判据**不**断言 DB 列被删 —— 列无写者无读者即无害，删列是破坏性迁移，**不在本包内**（见 PR body 边界段）。</li>
 * </ul>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("售后响应不再携带 refundMethod（issue #6224）")
class AfterSalesRefundMethodRetiredTest extends BaseControllerTest {

    private static final String BASE = "/api/admin/after-sales";
    private static final String TICKET_ID = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6";
    private static final String GONE_FIELD = "refundMethod";

    @Mock
    private AfterSalesTicketService afterSalesTicketService;

    @InjectMocks
    private AfterSalesController afterSalesController;

    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        mockMvc = buildMockMvc(afterSalesController);
    }

    @Test
    @DisplayName("判据 1：实体 + 两个响应 DTO 上都没有 refundMethod 字段/getter/setter（加回去即红）")
    void refundMethodIsGoneFromEveryJavaCarrier() {
        for (Class<?> carrier : List.of(
                AfterSalesTicket.class, AfterSalesListResponse.class, AfterSalesDetailResponse.class)) {
            List<String> fields = Stream.of(carrier.getDeclaredFields())
                    .map(Field::getName).collect(Collectors.toList());
            List<String> methods = Stream.of(carrier.getDeclaredMethods())
                    .map(Method::getName).collect(Collectors.toList());

            assertThat(fields)
                    .as("%s 上仍有 refundMethod 字段（issue #6224 要求下线）", carrier.getSimpleName())
                    .doesNotContain(GONE_FIELD);
            assertThat(methods)
                    .as("%s 上仍有 getRefundMethod / setRefundMethod（issue #6224 要求下线）", carrier.getSimpleName())
                    .doesNotContain("getRefundMethod", "setRefundMethod");
        }
    }

    @Test
    @DisplayName("判据 2a：列表响应体里没有 refundMethod 键（正对照：同一份响应里 ticketNo / refundAmount 在）")
    void listResponseCarriesNoRefundMethodKey() throws Exception {
        AfterSalesListResponse item = new AfterSalesListResponse();
        item.setId(TICKET_ID);
        item.setTicketNo("AS20261003001");
        item.setTicketType("return");
        item.setStatus("processing");
        item.setRefundAmount(new BigDecimal("299.00"));

        when(afterSalesTicketService.getTicketPage(
                anyLong(), anyLong(), any(), any(), any(), anyBoolean(), any()))
                .thenReturn(PageResponse.of(1L, 1L, 20L, List.of(item)));

        String body = mockMvc.perform(get(BASE))
                .andExpect(status().isOk())
                // 正对照：确认读到的是那份真响应（否则「键不出现」是空断言）
                .andExpect(jsonPath("$.data.items[0].ticketNo").value("AS20261003001"))
                .andExpect(jsonPath("$.data.items[0].refundAmount").value(299.00))
                .andReturn().getResponse().getContentAsString();

        assertThat(body)
                .as("列表响应里出现了 refundMethod 键 —— 该字段已裁定下线（issue #6224）")
                .doesNotContain(GONE_FIELD);
    }

    @Test
    @DisplayName("判据 2b：详情响应体里没有 refundMethod 键（正对照：同一份响应里 ticketNo / refundAmount 在）")
    void detailResponseCarriesNoRefundMethodKey() throws Exception {
        AfterSalesDetailResponse detail = new AfterSalesDetailResponse();
        detail.setId(TICKET_ID);
        detail.setTicketNo("AS20261003002");
        detail.setTicketType("return");
        detail.setStatus("processing");
        detail.setRefundAmount(new BigDecimal("299.00"));

        when(afterSalesTicketService.getTicketById(TICKET_ID)).thenReturn(detail);

        String body = mockMvc.perform(get(BASE + "/" + TICKET_ID))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.ticketNo").value("AS20261003002"))
                .andExpect(jsonPath("$.data.refundAmount").value(299.00))
                .andExpect(jsonPath("$.data.refundMethod").doesNotExist())
                .andReturn().getResponse().getContentAsString();

        assertThat(body)
                .as("详情响应里出现了 refundMethod 键 —— 该字段已裁定下线（issue #6224）")
                .doesNotContain(GONE_FIELD);
    }
}
