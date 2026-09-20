\pset pager off
-- 忠实模拟 variantNameOf：先查 VARIANT_NAMES[logical][position]，再裸名兜底（catalog 按 name 索引）
\echo '===== 分区（按 scope）+ 一列价聚合 ====='
with cell as (
  select p.logical_name, p.position, p.unit_price, p.applicable,
         -- 裸名兜底：catalog.containsKey(logicalName) ? logicalName : null
         (select o.scope from production_operations o
           where o.tenant_id=p.tenant_id and o.deleted=0 and o.status='active'
             and o.name = p.logical_name limit 1) as scope
    from production_operation_positions p where p.tenant_id=1 and p.deleted=0)
select case when scope='set' then 'delivery  ' else 'operations' end||' | '
       ||logical_name||'×'||position||' scope='||coalesce(scope,'null')
  from cell order by (scope='set') desc, logical_name, position;

\echo ''
\echo '===== 打包 一列价（4 格是否都进 delivery）====='
with cell as (
  select p.logical_name, p.position, p.unit_price, p.applicable,
         (select o.scope from production_operations o
           where o.tenant_id=p.tenant_id and o.deleted=0 and o.status='active'
             and o.name = p.logical_name limit 1) as scope
    from production_operation_positions p where p.tenant_id=1 and p.deleted=0)
select '打包 delivery 格数='||count(*) filter (where scope='set')
       ||' / 该工序总格数='||count(*) from cell where logical_name='打包';

\echo ''
\echo '===== 各 scope=set 工序的一列价 ====='
with cell as (
  select p.logical_name, p.position, p.unit_price, p.applicable,
         (select o.scope from production_operations o
           where o.tenant_id=p.tenant_id and o.deleted=0 and o.status='active'
             and o.name = p.logical_name limit 1) as scope
    from production_operation_positions p where p.tenant_id=1 and p.deleted=0),
agg as (
  select logical_name, count(*) n_cells,
         count(*) filter (where applicable) n_app,
         count(*) filter (where applicable and unit_price is null) n_null,
         count(distinct unit_price) filter (where applicable and unit_price is not null) n_dist,
         min(unit_price) filter (where applicable and unit_price is not null) the_price
    from cell where scope='set' group by logical_name)
select logical_name||' (cells='||n_cells||', applicable='||n_app||') → '||
  case when n_app=0 then 'no_applicable_position'
       when n_null>0 then 'unpriced price=null'
       when n_dist=1 then 'priced price='||the_price
       else 'multiple_prices different_price_count='||n_dist end
  from agg order by logical_name;

\echo ''
\echo '===== 非 set 工序（应全部落 operations，且不受交付一列价影响）====='
with cell as (
  select p.logical_name, p.position,
         (select o.scope from production_operations o
           where o.tenant_id=p.tenant_id and o.deleted=0 and o.status='active'
             and o.name = p.logical_name limit 1) as scope
    from production_operation_positions p where p.tenant_id=1 and p.deleted=0)
select 'operations 段行数='||count(*) filter (where scope is distinct from 'set')
       ||' | delivery 段工序数='||count(distinct logical_name) filter (where scope='set')
  from cell;
