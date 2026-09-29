package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;
import org.apache.ibatis.type.JdbcType;

import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 工人端**页面开关**（V141，母单 #5161 —— 工人端页面/菜单权限的部分交付）。对应表：{@code worker_page_configs}。
 *
 * <p><b>它回答什么</b>：本租户的工人端 H5 / 车间一体机上出现哪些页面。</p>
 *
 * <p><b>缺行 = 默认全开</b>（读面 {@code source='default'}）：默认集合只在
 * {@link com.migao.admin.worker.WorkerPages} 一处；库里再种一份 = 第二份会漂的默认值。</p>
 *
 * <p>🔴 <b>本表与授权无关</b>：工人 session 的 {@code permissions} 恒为 {@code []}，
 * 工人可达面恒为 {@code /api/worker/**} —— 页面码<b>不得</b>进 {@code users.permissions}。
 * 本表只影响「页面上看不看得见」，不参与任何服务端授权判定。</p>
 *
 * <p><b>为什么用 JSONB</b>：页面集合是整份替换的配置（PUT 全量替换），没有按页查询 / 外键的需求
 * ⇒ 子表只带来 join 与「半份配置」的中间态。页面数是固定 4 个。</p>
 */
@Data
@Builder(toBuilder = true)
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "worker_page_configs", autoResultMap = true)
public class WorkerPageConfig {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    /** 页面键数组（闭词表见 {@code WorkerPages.ALL}），如 {@code ["report","order","cut_calc","shipment"]}。 */
    @TableField(typeHandler = JacksonTypeHandler.class, jdbcType = JdbcType.OTHER)
    private Object pages;

    private String status;

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;

    private Integer deleted;

    /** 本行 → 读面/审计用的页面列表（顺序 = 存进去的顺序；非数组/空值 ⇒ 空列表，不猜）。 */
    public List<String> toPages() {
        if (!(pages instanceof List<?> list)) {
            return List.of();
        }
        List<String> out = new ArrayList<>(list.size());
        for (Object item : list) {
            if (item != null) {
                out.add(String.valueOf(item));
            }
        }
        return out;
    }

    /**
     * 本行 → 审计用的键值映射（{@code {"pages": [...]}}）。
     *
     * <p>形态与请求体键**逐字同名** ⇒ 零映射；{@code tenant_param_audit} 的逐键 diff 才认得「改的是 pages」。</p>
     */
    public Map<String, Object> toConfigMap() {
        Map<String, Object> config = new LinkedHashMap<>();
        config.put("pages", toPages());
        return config;
    }
}
