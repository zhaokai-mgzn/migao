package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.RemnantItemSize;
import org.apache.ibatis.annotations.Mapper;

/**
 * 小件用料尺寸表 Mapper（V122，issue #5146）—— 纯 {@link BaseMapper}，不写额外 SQL。
 *
 * <p>有意**不加**任何自定义查询：尺寸表的读面就是「本租户的全部行」（一次
 * {@code selectList} 按 {@code item_key} 归成 Map），为它另写一条 SQL 只是把同一件事写两遍。
 * 匹配时的尺寸判定在 {@code RemnantItemSize#fits}（实体里，可被单测逐值判红）。</p>
 */
@Mapper
public interface RemnantItemSizeMapper extends BaseMapper<RemnantItemSize> {
}
