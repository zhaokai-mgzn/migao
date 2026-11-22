package com.migao.admin.dto;

import com.fasterxml.jackson.annotation.JsonFormat;
import com.fasterxml.jackson.annotation.JsonGetter;
import lombok.Data;

import java.time.OffsetDateTime;
import java.util.List;

/**
 * 分类响应 DTO
 */
@Data
public class CategoryResponse {

    /**
     * 分类ID
     */
    private String id;

    /**
     * 分类名称
     */
    private String name;

    /**
     * 父分类ID
     */
    private String parentId;

    /**
     * 层级
     */
    private Integer level;

    /**
     * 排序号（DB 列 sort_order；JSON 字段名 sortOrder —— 与 entity 同名字段/仓库既有 camelCase 风格一致）
     *
     * <p>issue #9007：此前该字段被 {@code @JsonProperty("sort")} 改名为 {@code sort}，导致
     * 全字段冒烟 / 已记录的生产响应夹具里按 {@code sortOrder} 读不到排序值（列表与创建响应都缺）。
     */
    private Integer sortOrder;

    /**
     * 图标
     */
    private String icon;

    /**
     * 状态
     */
    private String status;

    /**
     * 子分类列表
     */
    private List<CategoryResponse> children;

    /**
     * 创建时间
     */
    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private OffsetDateTime createdAt;

    /**
     * 更新时间
     */
    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private OffsetDateTime updatedAt;

    /**
     * {@code sort} 兼容别名（只出现在序列化结果里，与 {@link #sortOrder} 同值）。
     *
     * <p>issue #2755 曾把本字段的 JSON 名改成 {@code sort} 以对齐当时的 admin-web 读面；
     * issue #9007 把主名改回 {@code sortOrder}，但**不删** {@code sort} —— 已发布客户端
     * （admin-web `Category.sort`、e2e 夹具、第三方调用方）仍按旧名读，删字段是破坏性变更。
     */
    @JsonGetter("sort")
    public Integer getSortAlias() {
        return sortOrder;
    }
}
