package com.migao.admin.dto;

import com.fasterxml.jackson.annotation.JsonFormat;
import lombok.Data;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;

/**
 * 加工项响应 DTO
 */
@Data
public class ProcessingItemResponse {

    /**
     * 加工项ID
     */
    private String id;

    /**
     * 加工项名称
     */
    private String name;

    /**
     * 分类ID
     */
    private String categoryId;

    /**
     * 分类名称
     */
    private String categoryName;

    /**
     * 加工数量单位（issue #4882）：语义 = 「**加工数量**的单位」，默认 {@code 米}。
     */
    private String unit;

    /**
     * 最小数量
     */
    private Integer minQuantity;

    /**
     * 最大数量
     */
    private Integer maxQuantity;

    /**
     * 描述
     */
    private String description;

    /**
     * 加工选项
     */
    private List<Map<String, Object>> options;

    /**
     * 加工天数
     */
    private Integer processingDays;

    /**
     * AI推荐
     */
    private Boolean aiRecommended;

    /**
     * **显式声明的工艺**（V78，issue #4452）：路线键「工艺」维的受控来源；{@code null} = 没声明。
     */
    private String craftHint;

    /**
     * 状态
     */
    private String status;

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
}
