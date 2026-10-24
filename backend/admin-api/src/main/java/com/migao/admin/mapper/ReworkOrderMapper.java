package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ReworkOrder;
import org.apache.ibatis.annotations.Mapper;

/**
 * 返工单（issue #7377 段 2）：只继承 BaseMapper —— 「同一售后单只能一个未完结返工单」
 * 由部分唯一索引兜住，状态流转走服务层 CAS，不在 SQL 里各写一套。
 */
@Mapper
public interface ReworkOrderMapper extends BaseMapper<ReworkOrder> {
}
