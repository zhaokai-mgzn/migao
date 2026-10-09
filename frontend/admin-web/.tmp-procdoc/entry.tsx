import React from 'react'
import { createRoot } from 'react-dom/client'
import ProcessingDoc from '../src/components/orders/ProcessingDoc'
const order: any = {
  id: 'o1', orderNo: 'YK20261006001', createdAt: '2026-10-06T10:00:00+08:00',
  customerName: 'SD07演示客814127-134', customerPhone: '13310000134',
  customerAddress: 'SD07演示地址392号', requiredDeliveryDate: '2026-10-13',
  logisticsType: 'express', logisticsCompany: '顺丰速运', createdByName: '米高测试', remark: '',
  items: [{ id: 'it1', productCode: 'FY-2026-0012', quantity: 3.4, width: 2.3, height: 2, specification: '',
    processingInfo: { curtainType: '布帘', craft: '打孔', craftType: '定高实宽', fabricWidth: 2.8, foldRatio: 1.5, fabricMeters: 3.4, componentRole: '主布', colorName: '雾霾蓝' } }],
}
const processingOrder: any = { processingOrderNo: 'JG-20261006-8445', expectedDeliveryDate: '2026-10-13', items: [{ itemId: 'it1', batchNo: 'PC-20261006-0009' }] }
createRoot(document.querySelector('.print-preview-doc') as HTMLElement).render(
  React.createElement(ProcessingDoc, { order, processingOrder, qrValue: 'JG-20261006-8445', inline: true })
)
