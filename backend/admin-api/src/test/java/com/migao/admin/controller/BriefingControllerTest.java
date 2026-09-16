// case_ids: DA-001, DA-002, ST-001

package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.entity.DailyBriefing;
import com.migao.admin.service.DailyBriefingService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.time.LocalDate;
import java.util.HashMap;
import java.util.Map;

import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/**
 * BriefingController 单元测试（智能每日经营简报，issue #3468）
 * 验证：今日简报查询 / 配置读写（企业开关）/ 手动生成触发。
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("BriefingController 智能每日简报接口测试")
class BriefingControllerTest {

    private MockMvc mockMvc;
    private final ObjectMapper objectMapper = new ObjectMapper();

    @Mock
    private DailyBriefingService dailyBriefingService;

    @InjectMocks
    private BriefingController briefingController;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(1L);
        mockMvc = MockMvcBuilders.standaloneSetup(briefingController)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    @Nested
    @DisplayName("GET /api/admin/briefing/today")
    class GetToday {

        @Test
        @DisplayName("已生成 → 返回内容 + generated=true")
        void generated() throws Exception {
            DailyBriefing briefing = DailyBriefing.builder()
                    .tenantId(1L)
                    .bizDate(LocalDate.now())
                    .verifyStatus("verified")
                    .content(Map.of("summary", "昨日经营平稳"))
                    .build();
            when(dailyBriefingService.getTodayBriefing(eq(1L))).thenReturn(briefing);

            mockMvc.perform(get("/api/admin/briefing/today"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true))
                    .andExpect(jsonPath("$.data.generated").value(true))
                    .andExpect(jsonPath("$.data.verifyStatus").value("verified"))
                    .andExpect(jsonPath("$.data.content.summary").value("昨日经营平稳"));
        }

        @Test
        @DisplayName("未生成 → generated=false + content=null（不展示假数据）")
        void notGenerated() throws Exception {
            when(dailyBriefingService.getTodayBriefing(eq(1L))).thenReturn(null);

            mockMvc.perform(get("/api/admin/briefing/today"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true))
                    .andExpect(jsonPath("$.data.generated").value(false));
        }
    }

    @Nested
    @DisplayName("GET/PUT /api/admin/briefing/config")
    class Config {

        @Test
        @DisplayName("读取配置 → 返回开关 + 生成时刻")
        void getConfig() throws Exception {
            Map<String, Object> config = new HashMap<>();
            config.put("enabled", true);
            config.put("generateTime", "06:00");
            when(dailyBriefingService.getConfig(eq(1L))).thenReturn(config);

            mockMvc.perform(get("/api/admin/briefing/config"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.enabled").value(true))
                    .andExpect(jsonPath("$.data.generateTime").value("06:00"));
        }

        @Test
        @DisplayName("更新配置（开启）→ 返回新配置")
        void updateConfigEnabled() throws Exception {
            Map<String, Object> body = Map.of("enabled", true, "generateTime", "07:30");
            Map<String, Object> config = new HashMap<>();
            config.put("enabled", true);
            config.put("generateTime", "07:30");
            when(dailyBriefingService.updateConfig(eq(1L), eq(true), eq("07:30"))).thenReturn(config);

            mockMvc.perform(put("/api/admin/briefing/config")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content(objectMapper.writeValueAsString(body)))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.enabled").value(true))
                    .andExpect(jsonPath("$.data.generateTime").value("07:30"));
        }

        @Test
        @DisplayName("更新配置（关闭）→ 熔断返回 enabled=false")
        void updateConfigDisabled() throws Exception {
            Map<String, Object> body = Map.of("enabled", false);
            Map<String, Object> config = new HashMap<>();
            config.put("enabled", false);
            config.put("generateTime", "06:00");
            when(dailyBriefingService.updateConfig(eq(1L), eq(false), isNull())).thenReturn(config);

            mockMvc.perform(put("/api/admin/briefing/config")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content(objectMapper.writeValueAsString(body)))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.enabled").value(false));
        }
    }

    @Nested
    @DisplayName("POST /api/admin/briefing/generate")
    class Generate {

        @Test
        @DisplayName("手动生成成功 → generated=true")
        void generateSuccess() throws Exception {
            DailyBriefing briefing = DailyBriefing.builder()
                    .tenantId(1L)
                    .bizDate(LocalDate.now())
                    .verifyStatus("verified")
                    .content(Map.of("summary", "今日简报"))
                    .build();
            when(dailyBriefingService.generateForTenant(eq(1L))).thenReturn(briefing);

            mockMvc.perform(post("/api/admin/briefing/generate"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.generated").value(true))
                    .andExpect(jsonPath("$.data.verifyStatus").value("verified"));
        }

        @Test
        @DisplayName("开关关闭 → generated=false + reason=BRIEFING_DISABLED")
        void generateDisabled() throws Exception {
            when(dailyBriefingService.generateForTenant(eq(1L))).thenReturn(null);

            mockMvc.perform(post("/api/admin/briefing/generate"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.generated").value(false))
                    .andExpect(jsonPath("$.data.reason").value("BRIEFING_DISABLED"));
        }
    }
}
