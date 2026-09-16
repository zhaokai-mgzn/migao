package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 租户实体类
 * 对应表：tenants
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "tenants", autoResultMap = true)
public class Tenant {

    /**
     * 生产库 tenants.id 为 GENERATED ALWAYS AS IDENTITY（PG18），
     * 必须用 AUTO 让数据库生成主键；ASSIGN_ID 会显式插入非 DEFAULT 值被 PG 拒绝
     * （云验收实测：AI 自动开通租户时报 cannot insert a non-DEFAULT value into column id）
     */
    @TableId(type = IdType.AUTO)
    private Long id;

    private String name;

    private String code;

    private String industry;

    private String status;

    /** 企业 Logo（OSS URL），用于管理后台品牌展示 */
    private String logo;

    /** 系统通知开关 */
    private Boolean notificationEnabled;

    /** 通知邮箱 */
    private String notificationEmail;

    /** 智能每日经营简报开关（默认 false，关闭=不生成+菜单隐藏+LLM 熔断，issue #3468） */
    private Boolean briefingEnabled;

    /** 简报每日生成时刻 HH:mm（默认 06:00，租户可自定义） */
    private String briefingGenerateTime;

    @TableField(typeHandler = com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler.class)
    private Object authConfig;

    @TableField(typeHandler = com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler.class)
    private Object bailianConfig;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;

    @TableLogic
    private Integer deleted;
}
