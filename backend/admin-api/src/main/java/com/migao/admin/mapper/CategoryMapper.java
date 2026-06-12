package com.migao.admin.mapper;

import com.migao.admin.entity.Category;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/**
 * 商品分类 Mapper 接口
 */
@Mapper
public interface CategoryMapper extends BaseMapper<Category> {

    /**
     * 查询指定父分类下的子分类列表
     */
    @Select("SELECT * FROM categories WHERE parent_id = #{parentId} AND deleted = 0 ORDER BY sort_order ASC")
    List<Category> selectByParentId(@Param("parentId") String parentId);

    /**
     * 查询顶级分类列表（parent_id IS NULL）
     */
    @Select("SELECT * FROM categories WHERE parent_id IS NULL AND deleted = 0 ORDER BY sort_order ASC")
    List<Category> selectRootCategories();
}
