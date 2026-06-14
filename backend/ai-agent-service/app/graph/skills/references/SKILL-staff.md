---
name: staff
domain: hr
display_name: 人事管理
version: 1.0.0
description: >
  员工账号、角色与权限管理。
  支持员工信息管理、角色创建/编辑、权限分配。
tools:
  - employee_manage
  - role_manage
  - validate_input
triggers:
  - 员工管理 / 添加员工 / 编辑员工
  - 角色管理 / 权限设置
  - 分配权限 / 角色列表
constraints:
  - 写操作前调 validate_input 校验
  - 权限变更需展示影响范围
  - 禁止降级或删除自己的管理员权限
  - 密码等敏感字段不展示不记录
---

# Staff Skill

人事管理技能，覆盖员工账号和角色权限管理。

## 执行原则

1. **校验先行**：写操作前调 validate_input
2. **权限透明**：权限变更说明影响的操作范围
3. **安全底线**：不操作自身权限，敏感字段不记录
