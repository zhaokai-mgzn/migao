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
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 裁高（定高）<b>租户级配置</b>（V140，母单 #5161；设计单
 * {@code docs/design/cutting-height-config-and-terminal.md}）。对应表：{@code cutting_height_configs}。
 *
 * <p><b>它回答什么</b>：这台机器这一刀该多高 ——
 * {@code 裁剪高度(部位) = 成品高 + Σ(命中的增量项)}，增量项集合与取值由本租户配置。</p>
 *
 * <p><b>缺行 = 用默认种子</b>（读面 {@code source='default'}）：默认种子只在 Java 一处
 * （{@code CuttingHeightConfigService.DEFAULT_ITEMS}，逐字 = 壁达现场弹窗那 7 项）；
 * 库里再种一份 = <b>第二份会漂的默认值</b>（同族先例：{@code craft_calc_configs} 的
 * 「不做开租播种」，理由一字相同）。</p>
 *
 * <p><b>为什么用 JSONB</b>：两列都是整份替换的配置（PUT 全量替换），没有按项查询 / 按项外键的需求
 * ⇒ 子表只带来 join 与「半份配置」的中间态。</p>
 */
@Data
@Builder(toBuilder = true)
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "cutting_height_configs", autoResultMap = true)
public class CuttingHeightConfig {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    /** 增量项档案：{@code [{key,name,value,direction,height_join,hit,hit_expr,enabled,order}]}；{@code value=null} = **有项无值** */
    @TableField(typeHandler = JacksonTypeHandler.class, jdbcType = JdbcType.OTHER)
    private Object items;

    /** 取整规则：{@code {mode: half_up|down|up, digits: 0..3}}；默认保留三位小数（= mm 精度） */
    @TableField(typeHandler = JacksonTypeHandler.class, jdbcType = JdbcType.OTHER)
    private Object rounding;

    private String status;

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;

    private Integer deleted;

    /** 本行 → 读面/审计用的配置对象（键 = 请求体键，逐字同名 ⇒ 零映射）。 */
    public Map<String, Object> toConfigMap() {
        Map<String, Object> config = new LinkedHashMap<>();
        config.put("items", items);
        config.put("rounding", rounding);
        return config;
    }
}
