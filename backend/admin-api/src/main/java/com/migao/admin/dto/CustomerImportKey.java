package com.migao.admin.dto;

import lombok.Data;

/**
 * 迁移预览/提交用的客户幂等键投影（issue #8295）。
 *
 * <p>只取 {@code external_id + id}，不把整行客户 PII 读进内存；预览只需要判断“这行是新建还是已存在”，
 * 更新时只需要既有行 id。</p>
 */
@Data
public class CustomerImportKey {

    private String externalId;

    private String id;
}
