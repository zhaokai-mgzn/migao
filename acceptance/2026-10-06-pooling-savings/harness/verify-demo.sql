-- 2026-10-06 演示数据 · SQL 级核对 + 残留清理（tenant 25）
-- 前置：RDS 公网白名单需含本机出口 IP（本轮由 `aliyun rds ModifySecurityIps --DBInstanceIPArrayName dev_local` 追加）
-- 用法：psql -h $RDS_HOST -p 5432 -U $RDS_USER -d $RDS_DB -v ON_ERROR_STOP=1 -f verify-demo.sql

-- ① 事实核对（正式批次 814127；换成你那一批的 stamp 即可）
select '演示订单' t, count(*)::text v from orders
  where tenant_id=25 and deleted=0 and customer_name like 'SD07演示客814127%'
union all select '已生成加工单', count(*)::text from processing_orders po
  where po.tenant_id=25 and po.deleted=0
    and po.order_id in (select id from orders where tenant_id=25 and customer_name like 'SD07演示客814127%')
union all select '无加工单', count(*)::text from orders o
  where o.tenant_id=25 and o.deleted=0 and o.customer_name like 'SD07演示客814127%'
    and not exists (select 1 from processing_orders po where po.order_id=o.id)
union all select '批次消耗行', count(*)::text from stock_batch_consumptions where tenant_id=25
union all select '报工日志', count(*)::text from production_work_logs where tenant_id=25;

-- ② 加工单状态分布（应五种齐全）
select status, count(*) from processing_orders where tenant_id=25 and deleted=0 group by status order by 2 desc;

-- ③ 「无加工单」的成因切片（#6420：纱帘 × 特选项 100% 命中）
select count(*) as 无加工单,
       count(*) filter (where oi.processing_info->>'curtainType'='纱帘') as 其中纱帘,
       count(*) filter (where oi.processing_info->>'curtainType'='纱帘'
         and jsonb_array_length(coalesce(oi.processing_info->'specialOptions','[]'::jsonb))>0) as 纱帘带特选项
from orders o join order_items oi on oi.order_id=o.id
where o.tenant_id=25 and o.deleted=0 and o.customer_name like 'SD07演示客814127%'
  and not exists (select 1 from processing_orders po where po.order_id=o.id);

-- ④ 残留清理（按调试 stamp；顺序即安全顺序，FK 实测）。把 :'stamp' 换成要清的批次号。
--    本轮已执行：清掉 638866 / 723857 两个调试批次的 22 单 + 13 加工单 + 8 套探针商品/批次，
--    保留 814127 正式批次的 300 单 / 278 加工单 / 252 消耗行。
--    工人（users role=worker, worker_no like 'SD07演示W%'）**刻意保留**：24 个都已有报工记录（计件链路参与者）。
/*
begin;
create temp table _dord on commit drop as
  select id from orders where tenant_id=25 and customer_name like 'SD07演示客638866%';
create temp table _ditem on commit drop as select oi.id from order_items oi join _dord d on d.id=oi.order_id;
create temp table _dpo   on commit drop as select po.id from processing_orders po join _dord d on d.id=po.order_id;
create temp table _dsku  on commit drop as select id from product_skus where tenant_id=25 and sku_code like '%638866%';
create temp table _dbatch on commit drop as select id from stock_batches where tenant_id=25 and sku_code like '%638866%';
create temp table _dinb  on commit drop as select id from inbound_orders where tenant_id=25 and remark like 'SD07演示入库638866%';
delete from worker_report_audits where processing_order_id in (select id from _dpo);
delete from production_work_logs where processing_order_id in (select id from _dpo);
delete from production_instance_repricing_logs where processing_order_id in (select id from _dpo);
delete from processing_set_part_tokens where processing_order_id in (select id from _dpo);
delete from processing_order_sets where processing_order_id in (select id from _dpo);
delete from processing_position_operations where processing_order_id in (select id from _dpo);
delete from stock_batch_consumptions where order_item_id in (select id::text from _ditem);
delete from fabric_remnants where source_batch_id in (select id from _dbatch);
delete from processing_orders where order_id in (select id from _dord);
delete from order_logistics where order_id in (select id from _dord);
delete from stock_ledger_entries where ref_no in (select order_no from orders where id in (select id from _dord));
delete from order_items where order_id in (select id from _dord);
delete from orders where id in (select id from _dord);
delete from stock_ledger_entries where sku_id in (select id from _dsku);
delete from inbound_order_items where inbound_order_id in (select id from _dinb);
delete from stock_batches where id in (select id from _dbatch);
delete from inbound_orders where id in (select id from _dinb);
delete from product_skus where id in (select id from _dsku);
delete from products where tenant_id=25 and name like 'SD07演示布638866%';
delete from categories where tenant_id=25 and name like 'SD07演示类638866%';
commit;
*/
