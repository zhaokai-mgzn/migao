package com.migao.admin.dto;

import lombok.Data;

import java.util.List;

/**
 * 通用分页响应 DTO
 */
@Data
public class PageResponse<T> {

    /**
     * 总记录数
     */
    private Long total;

    /**
     * 当前页码
     */
    private Long page;

    /**
     * 每页大小
     */
    private Long size;

    /**
     * 数据列表
     */
    private List<T> items;

    /**
     * 创建分页响应
     */
    public static <T> PageResponse<T> of(Long total, Long page, Long size, List<T> items) {
        PageResponse<T> response = new PageResponse<>();
        response.setTotal(total);
        response.setPage(page);
        response.setSize(size);
        response.setItems(items);
        return response;
    }

    /**
     * 创建分页响应（从 MyBatis-Plus Page 转换）
     */
    public static <T> PageResponse<T> of(com.baomidou.mybatisplus.extension.plugins.pagination.Page<T> page) {
        PageResponse<T> response = new PageResponse<>();
        response.setTotal(page.getTotal());
        response.setPage(page.getCurrent());
        response.setSize(page.getSize());
        response.setItems(page.getRecords());
        return response;
    }
}
