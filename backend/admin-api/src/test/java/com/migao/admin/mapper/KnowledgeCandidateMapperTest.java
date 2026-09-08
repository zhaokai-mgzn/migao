package com.migao.admin.mapper;

// case_ids: API-014

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.baomidou.mybatisplus.core.metadata.TableFieldInfo;
import com.baomidou.mybatisplus.core.metadata.TableInfo;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.migao.admin.entity.KnowledgeCandidate;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.stream.Collectors;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * KnowledgeCandidateMapper 验证测试（LLM WIKI 板块 P1，issue #3051）
 * 提炼候选数据模型：实体字段 ↔ knowledge_candidates 列名一一映射；Mapper 继承 BaseMapper。
 */
@DisplayName("KnowledgeCandidateMapper 验证")
class KnowledgeCandidateMapperTest {

    @BeforeAll
    static void initTableInfo() {
        MybatisConfiguration configuration = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(configuration, "");
        TableInfoHelper.initTableInfo(assistant, KnowledgeCandidate.class);
    }

    @Test
    @DisplayName("继承 BaseMapper — 标准 CRUD 由租户拦截器覆盖")
    void extendsBaseMapper_standardCrudCoveredByInterceptor() {
        assertThat(BaseMapper.class.isAssignableFrom(KnowledgeCandidateMapper.class))
                .as("KnowledgeCandidateMapper should extend BaseMapper<KnowledgeCandidate>")
                .isTrue();
    }

    @Test
    @DisplayName("表名与主键 — knowledge_candidates / id")
    void tableNameAndKey() {
        TableInfo info = TableInfoHelper.getTableInfo(KnowledgeCandidate.class);
        assertThat(info).isNotNull();
        assertThat(info.getTableName()).isEqualTo("knowledge_candidates");
        assertThat(info.getKeyColumn()).isEqualTo("id");
    }

    @Test
    @DisplayName("字段映射 — 候选知识卡片核心字段全部映射到列（契约 API-014）")
    void fieldColumnMapping() {
        TableInfo info = TableInfoHelper.getTableInfo(KnowledgeCandidate.class);
        assertThat(info).isNotNull();

        java.util.Map<String, String> columns = info.getFieldList().stream()
                .collect(Collectors.toMap(TableFieldInfo::getProperty, TableFieldInfo::getColumn));

        // 提炼候选数据模型核心字段（V35 迁移列名）
        assertThat(columns.get("tenantId")).isEqualTo("tenant_id");
        assertThat(columns.get("sourceType")).isEqualTo("source_type");
        assertThat(columns.get("sourceRef")).isEqualTo("source_ref");
        assertThat(columns.get("suggestedTitle")).isEqualTo("suggested_title");
        assertThat(columns.get("suggestedAnswer")).isEqualTo("suggested_answer");
        assertThat(columns.get("suggestedCategory")).isEqualTo("suggested_category");
        assertThat(columns.get("suggestedKeywords")).isEqualTo("suggested_keywords");
        assertThat(columns.get("confidence")).isEqualTo("confidence");
        assertThat(columns.get("evidence")).isEqualTo("evidence");
        assertThat(columns.get("status")).isEqualTo("status");
        assertThat(columns.get("statusNote")).isEqualTo("status_note");
        assertThat(columns.get("reviewedBy")).isEqualTo("reviewed_by");
        assertThat(columns.get("reviewedAt")).isEqualTo("reviewed_at");
        assertThat(columns.get("createdAt")).isEqualTo("created_at");
    }
}
