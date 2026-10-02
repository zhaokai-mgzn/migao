"""
建议相关模块（issue #5951：主动「后续问题建议」通道已整体退役）

存活模块：
- `vague_guess.py`：模糊输入的「可点击猜测」投影（#4125 家族）

已退役（本单删除）：`follow_up.py`（后续问题建议生成器，生产零调用）、
`preference_tracker.py`（用户建议偏好读写 —— 写口 = 已删的 `/suggestion-feedback`，
读口 = 已删的 `_inject_user_preferences`；两侧同时归零 ⇒ 整条支链删除，
不留「永远命中空集」的活路径）。
"""