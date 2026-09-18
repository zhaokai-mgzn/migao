# 逐道工序列出（供人读 + 断言核对）
.data.positions[] | .position_name as $pos | .operations[]
| [$pos, (.seq|tostring), .operation, .unit, (.qty|tostring), .qty_source] | @tsv
