package com.migao.admin.dto;

import jakarta.validation.constraints.*;
import lombok.Data;

import java.util.List;
import java.util.Map;

/**
 * 加工项创建请求 DTO
 */
@Data
public class ProcessingItemCreateRequest {

    /**
     * 加工项名称
     */
    @NotBlank(message = "加工项名称不能为空")
    @Size(max = 20, message = "加工项名称不能超过20个字符")
    private String name;

    /**
     * 分类ID
     */
    @NotBlank(message = "分类ID不能为空")
    private String categoryId;

    /**
     * 加工数量单位（issue #4882）：语义 = 「**加工数量**的单位」，默认 {@code 米}
     * —— 加工项目录已无单价与计价方式（用户裁定），它不再是「计价单位」。
     */
    private String unit = "米";

    /**
     * 最小数量
     */
    private Integer minQuantity = 1;

    /**
     * 最大数量
     */
    private Integer maxQuantity = 999;

    /**
     * 描述
     */
    private String description;

    /**
     * 加工选项（如打孔：纳米圈/四爪钩/韩式S钩）
     */
    private List<Map<String, Object>> options;

    /**
     * 加工天数
     */
    private Integer processingDays = 1;

    /**
     * AI推荐
     */
    private Boolean aiRecommended = true;

    /**
     * **显式声明的工艺**（V78，issue #4452）：该加工项代表哪个工艺（韩褶/打孔/穿杆/平幔…）。
     *
     * <p>它是路线键「工艺」维的**受控来源** —— 加工项目录是商家可自定义的业务数据，
     * 让判据去猜**名字**就是「名词解释」（商家每加一个自定义名就多一分静默错配）。
     * 可空：留空 = 没声明（该维按缺维处理，`route_source` 显式标注，不猜）。</p>
     */
    @Size(max = 16, message = "工艺名不能超过16个字符")
    private String craftHint;

    /**
     * 状态：active（启用）、inactive（禁用）
     */
    private String status = "active";
}
