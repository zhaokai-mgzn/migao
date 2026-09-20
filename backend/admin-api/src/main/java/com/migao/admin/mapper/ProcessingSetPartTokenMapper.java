package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProcessingSetPartToken;
import org.apache.ibatis.annotations.Mapper;

/**
 * 一部位一码 token Mapper（V92，切片 ⓪ / issue #4698）。
 * 本切片只读（扫码解析的**第一优先**形态：新 token → 套 × 部位）。
 */
@Mapper
public interface ProcessingSetPartTokenMapper extends BaseMapper<ProcessingSetPartToken> {
}
