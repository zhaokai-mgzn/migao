package com.migao.admin.controller;
// case_ids: DF-009, API-011

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.KnowledgeDocument;
import com.migao.admin.entity.KnowledgeSyncHistory;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.mapper.KnowledgeDocumentMapper;
import com.migao.admin.mapper.KnowledgeSyncHistoryMapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/**
 * KnowledgeController 安全回归测试
 * 验证跨租户访问（IDOR）防护
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("KnowledgeController 租户隔离测试")
class KnowledgeControllerTest {

    private MockMvc mockMvc;
    private final ObjectMapper objectMapper = new ObjectMapper();

    @Mock
    private KnowledgeDocumentMapper knowledgeDocumentMapper;

    @Mock
    private KnowledgeSyncHistoryMapper knowledgeSyncHistoryMapper;

    @InjectMocks
    private KnowledgeController knowledgeController;

    @BeforeEach
    void setUp() {
        // 纯 MockMvc 环境需手动初始化 MP 实体元数据（否则 LambdaQueryWrapper 无法解析列名）
        com.baomidou.mybatisplus.core.MybatisConfiguration configuration =
                new com.baomidou.mybatisplus.core.MybatisConfiguration();
        org.apache.ibatis.builder.MapperBuilderAssistant assistant =
                new org.apache.ibatis.builder.MapperBuilderAssistant(configuration, "");
        TableInfoHelper.initTableInfo(assistant, KnowledgeDocument.class);
        TableInfoHelper.initTableInfo(assistant, KnowledgeSyncHistory.class);

        mockMvc = MockMvcBuilders.standaloneSetup(knowledgeController)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
        TenantContext.setTenantId(1L);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ============ deleteDocument IDOR tests ============

    @Nested
    @DisplayName("DELETE /documents/{id}")
    class DeleteDocument {

        @Test
        @DisplayName("删除自己租户的文档 → 200")
        void deleteOwnTenantDocument() throws Exception {
            KnowledgeDocument doc = KnowledgeDocument.builder()
                    .id("doc-1")
                    .tenantId(1L)
                    .title("test")
                    .build();
            when(knowledgeDocumentMapper.selectById("doc-1")).thenReturn(doc);

            mockMvc.perform(delete("/api/admin/knowledge/documents/doc-1"))
                    .andExpect(status().isOk());
        }

        @Test
        @DisplayName("删除其他租户的文档 → 404（禁止跨租户）")
        void deleteOtherTenantDocument() throws Exception {
            KnowledgeDocument doc = KnowledgeDocument.builder()
                    .id("doc-2")
                    .tenantId(999L)  // 不同的租户
                    .title("other-tenant-doc")
                    .build();
            when(knowledgeDocumentMapper.selectById("doc-2")).thenReturn(doc);

            mockMvc.perform(delete("/api/admin/knowledge/documents/doc-2"))
                    .andExpect(status().isNotFound());

        }

        @Test
        @DisplayName("文档不存在 → 404")
        void deleteNonExistentDocument() throws Exception {
            when(knowledgeDocumentMapper.selectById("doc-none")).thenReturn(null);

            mockMvc.perform(delete("/api/admin/knowledge/documents/doc-none"))
                    .andExpect(status().isNotFound());
        }
    }

    // ============ resyncDocument IDOR tests ============

    @Nested
    @DisplayName("POST /documents/{id}/embed")
    class ResyncDocument {

        @Test
        @DisplayName("重新同步自己租户的文档 → 200")
        void resyncOwnTenantDocument() throws Exception {
            KnowledgeDocument doc = KnowledgeDocument.builder()
                    .id("doc-1")
                    .tenantId(1L)
                    .embeddingStatus("completed")
                    .build();
            when(knowledgeDocumentMapper.selectById("doc-1")).thenReturn(doc);

            mockMvc.perform(post("/api/admin/knowledge/documents/doc-1/embed"))
                    .andExpect(status().isOk());
        }

        @Test
        @DisplayName("重新同步其他租户的文档 → 404（禁止跨租户）")
        void resyncOtherTenantDocument() throws Exception {
            KnowledgeDocument doc = KnowledgeDocument.builder()
                    .id("doc-2")
                    .tenantId(999L)
                    .embeddingStatus("completed")
                    .build();
            when(knowledgeDocumentMapper.selectById("doc-2")).thenReturn(doc);

            mockMvc.perform(post("/api/admin/knowledge/documents/doc-2/embed"))
                    .andExpect(status().isNotFound());

            // 跨租户被拒，不得写入同步历史
            verify(knowledgeSyncHistoryMapper, never()).insert(any(KnowledgeSyncHistory.class));
        }

        @Test
        @DisplayName("重新同步写入同步历史记录（API-011：knowledge_sync_history 闭环）")
        void resyncWritesSyncHistory() throws Exception {
            KnowledgeDocument doc = KnowledgeDocument.builder()
                    .id("doc-1")
                    .tenantId(1L)
                    .embeddingStatus("completed")
                    .build();
            when(knowledgeDocumentMapper.selectById("doc-1")).thenReturn(doc);

            mockMvc.perform(post("/api/admin/knowledge/documents/doc-1/embed"))
                    .andExpect(status().isOk());

            ArgumentCaptor<KnowledgeSyncHistory> captor = ArgumentCaptor.forClass(KnowledgeSyncHistory.class);
            verify(knowledgeSyncHistoryMapper).insert(captor.capture());
            KnowledgeSyncHistory h = captor.getValue();
            assertThat(h.getTenantId()).isEqualTo(1L);
            assertThat(h.getSyncType()).isEqualTo("single");
            assertThat(h.getSourceType()).isEqualTo("manual");
            assertThat(h.getSourceIds()).isEqualTo(java.util.List.of("doc-1"));
            assertThat(h.getStatus()).isEqualTo("processing");
            assertThat(h.getTotalCount()).isEqualTo(1);
        }
    }

    // ============ sync-history 分页列表（API-011）============

    @Nested
    @DisplayName("GET /sync-history")
    class SyncHistory {

        @Test
        @DisplayName("分页返回同步历史（created_at 倒序 + tenant 隔离）")
        void listSyncHistory() throws Exception {
            KnowledgeSyncHistory h = KnowledgeSyncHistory.builder()
                    .id("hist-1")
                    .tenantId(1L)
                    .syncType("single")
                    .status("processing")
                    .build();
            com.baomidou.mybatisplus.extension.plugins.pagination.Page<KnowledgeSyncHistory> historyPage =
                    new com.baomidou.mybatisplus.extension.plugins.pagination.Page<>(1, 20);
            historyPage.setRecords(java.util.List.of(h));
            historyPage.setTotal(1);
            when(knowledgeSyncHistoryMapper.selectPage(any(), any())).thenReturn(historyPage);

            mockMvc.perform(get("/api/admin/knowledge/sync-history"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.items[0].id").value("hist-1"))
                    .andExpect(jsonPath("$.data.items[0].syncType").value("single"))
                    .andExpect(jsonPath("$.data.total").value(1));

            ArgumentCaptor<LambdaQueryWrapper<KnowledgeSyncHistory>> captor =
                    ArgumentCaptor.forClass(LambdaQueryWrapper.class);
            verify(knowledgeSyncHistoryMapper).selectPage(any(), captor.capture());
            String sql = captor.getValue().getCustomSqlSegment();
            assertThat(sql).contains("tenant_id").contains("created_at");
        }

        @Test
        @DisplayName("无历史记录返回空列表")
        void listSyncHistoryEmpty() throws Exception {
            com.baomidou.mybatisplus.extension.plugins.pagination.Page<KnowledgeSyncHistory> historyPage =
                    new com.baomidou.mybatisplus.extension.plugins.pagination.Page<>(1, 20);
            historyPage.setRecords(java.util.List.of());
            historyPage.setTotal(0);
            when(knowledgeSyncHistoryMapper.selectPage(any(), any())).thenReturn(historyPage);

            mockMvc.perform(get("/api/admin/knowledge/sync-history"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.items").isEmpty())
                    .andExpect(jsonPath("$.data.total").value(0));
        }
    }

    // ============ test-search 跨租户过滤回归（审计 07 P1-6）============

    @Nested
    @DisplayName("POST /test-search")
    class TestSearch {

        @Test
        @DisplayName("标题/内容 OR 条件必须包裹在括号内，防止绕过租户过滤（DF-009）")
        void searchKeepsTenantFilterWithOrNested() throws Exception {
            when(knowledgeDocumentMapper.selectList(any())).thenReturn(java.util.List.of());

            mockMvc.perform(post("/api/admin/knowledge/test-search")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("{\"query\":\"窗帘\"}"))
                    .andExpect(status().isOk());

            ArgumentCaptor<LambdaQueryWrapper<KnowledgeDocument>> captor =
                    ArgumentCaptor.forClass(LambdaQueryWrapper.class);
            verify(knowledgeDocumentMapper).selectList(captor.capture());
            String sql = captor.getValue().getCustomSqlSegment();

            // OR 必须嵌套：...(title LIKE ? OR content LIKE ?)...，而不是 (tenant AND title) OR content 逃逸租户过滤
            assertThat(sql)
                    .as("租户过滤必须与 OR 条件同括号：%s", sql)
                    .matches(".*\\(title LIKE .* OR content LIKE .*\\).*");
        }

        @Test
        @DisplayName("搜索仍保留 tenant_id 与 is_active 过滤条件")
        void searchKeepsTenantAndActiveFilter() throws Exception {
            when(knowledgeDocumentMapper.selectList(any())).thenReturn(java.util.List.of());

            mockMvc.perform(post("/api/admin/knowledge/test-search")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("{\"query\":\"窗帘\"}"))
                    .andExpect(status().isOk());

            ArgumentCaptor<LambdaQueryWrapper<KnowledgeDocument>> captor =
                    ArgumentCaptor.forClass(LambdaQueryWrapper.class);
            verify(knowledgeDocumentMapper).selectList(captor.capture());
            String sql = captor.getValue().getCustomSqlSegment();

            assertThat(sql).contains("tenant_id").contains("is_active");
        }
    }
}
