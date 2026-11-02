package com.migao.admin.dto;

import java.util.List;

/**
 * 客户主数据迁移的一个 canonical 字段（issue #8295）。
 *
 * <p>这是页面、AI 映射、服务端校验共用的**字段真值清单**：AI 只允许返回这里出现过的 key；
 * 服务端按 key 取值落库，不信任 AI 返回的任意字段名。</p>
 *
 * @param key       canonical key（落库/映射 JSON 的键）
 * @param label     页面/AI prompt 用的中文名
 * @param required  是否必填
 * @param type      string / enum
 * @param aliases   旧 ERP 表头常见同义词（确定性兜底 + AI prompt 上下文）
 */
public record CustomerImportField(
        String key,
        String label,
        boolean required,
        String type,
        List<String> aliases
) {
}
