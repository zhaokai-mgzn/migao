package com.migao.admin.mapper;

// case_ids: API-013

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.baomidou.mybatisplus.core.metadata.TableFieldInfo;
import com.baomidou.mybatisplus.core.metadata.TableInfo;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.migao.admin.entity.KnowledgeCard;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.stream.Collectors;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * KnowledgeCardMapper 验证测试（LLM WIKI 板块 P1，issue #3051）
 * 知识卡片数据模型：实体字段 ↔ knowledge_cards 列名一一映射；Mapper 继承 BaseMapper，
 * 标准 CRUD 由 TenantLineInnerInterceptor 自动注入租户过滤。
 */
@DisplayName("KnowledgeCardMapper 验证")
class KnowledgeCardMapperTest {

    @BeforeAll
    static void initTableInfo() {
        // 纯单测环境需手动初始化 MP 实体元数据（否则 TableInfo 无法解析列名）
        MybatisConfiguration configuration = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(configuration, "");
        TableInfoHelper.initTableInfo(assistant, KnowledgeCard.class);
    }

    @Test
    @DisplayName("继承 BaseMapper — 标准 CRUD 由租户拦截器覆盖")
    void extendsBaseMapper_standardCrudCoveredByInterceptor() {
        assertThat(BaseMapper.class.isAssignableFrom(KnowledgeCardMapper.class))
                .as("KnowledgeCardMapper should extend BaseMapper<KnowledgeCard>")
                .isTrue();
    }

    @Test
    @DisplayName("表名与主键 — knowledge_cards / id")
    void tableNameAndKey() {
        TableInfo info = TableInfoHelper.getTableInfo(KnowledgeCard.class);
        assertThat(info).isNotNull();
        assertThat(info.getTableName()).isEqualTo("knowledge_cards");
        assertThat(info.getKeyColumn()).isEqualTo("id");
    }

    @Test
    @DisplayName("字段映射 — 知识卡片核心字段全部映射到列（契约 API-013）")
    void fieldColumnMapping() {
        TableInfo info = TableInfoHelper.getTableInfo(KnowledgeCard.class);
        assertThat(info).isNotNull();

        java.util.Map<String, String> columns = info.getFieldList().stream()
                .collect(Collectors.toMap(TableFieldInfo::getProperty, TableFieldInfo::getColumn));

        // 知识卡片数据模型核心字段（V35 迁移列名）
        assertThat(columns.get("tenantId")).isEqualTo("tenant_id");
        assertThat(columns.get("title")).isEqualTo("title");
        assertThat(columns.get("category")).isEqualTo("category");
        assertThat(columns.get("industry")).isEqualTo("industry");
        assertThat(columns.get("sourceType")).isEqualTo("source_type");
        assertThat(columns.get("sourceRef")).isEqualTo("source_ref");
        assertThat(columns.get("question")).isEqualTo("question");
        assertThat(columns.get("answer")).isEqualTo("answer");
        assertThat(columns.get("keywords")).isEqualTo("keywords");
        assertThat(columns.get("applyProducts")).isEqualTo("apply_products");
        assertThat(columns.get("variables")).isEqualTo("variables");
        assertThat(columns.get("status")).isEqualTo("status");
        assertThat(columns.get("version")).isEqualTo("version");
        assertThat(columns.get("reviewNote")).isEqualTo("review_note");
        assertThat(columns.get("reviewedBy")).isEqualTo("reviewed_by");
        assertThat(columns.get("reviewedAt")).isEqualTo("reviewed_at");
        assertThat(columns.get("createdAt")).isEqualTo("created_at");
        assertThat(columns.get("updatedAt")).isEqualTo("updated_at");
        assertThat(columns.get("deleted")).isEqualTo("deleted");
    }
}
