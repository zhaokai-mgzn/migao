package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.KnowledgeDocument;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.exception.GlobalExceptionHandler;
import com.migao.admin.mapper.KnowledgeDocumentMapper;
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
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
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

    @InjectMocks
    private KnowledgeController knowledgeController;

    @BeforeEach
    void setUp() {
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

            verify(knowledgeDocumentMapper).deleteById("doc-1");
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

            verify(knowledgeDocumentMapper, never()).deleteById(any());
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

            verify(knowledgeDocumentMapper).updateById(any(KnowledgeDocument.class));
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

            verify(knowledgeDocumentMapper, never()).updateById(any());
        }
    }
}
