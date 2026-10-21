package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.Approval;
import org.apache.ibatis.annotations.Mapper;

/**
 * 审批 Mapper（issue #7374）：只继承 BaseMapper —— 状态流转与消费的**并发正确性**由服务层
 * 的条件更新（CAS）保证，不在 SQL 里各写一套。所有查询都由租户插件加 `tenant_id`。
 */
@Mapper
public interface ApprovalMapper extends BaseMapper<Approval> {
}
