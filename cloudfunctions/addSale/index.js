// 新增出库记录 — 含实时库存校验
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()

exports.main = async (event) => {
  const { tireId, customer, qty, unitCost, unitPrice, outType, date, note } = event

  if (!tireId || !qty) {
    return { ok: false, message: '缺少必填字段（tireId/qty）' }
  }

  const outQty = Number(qty)
  if (outQty <= 0) {
    return { ok: false, message: '出库数量必须大于0' }
  }

  try {
    // 实时计算库存：进货总数 - 出库总数
    const purchaseRes = await db.collection('purchase')
      .where({ tireId })
      .get()
    const totalIn = purchaseRes.data.filter(r => !r.isDeleted).reduce((sum, r) => sum + (r.qty || 0), 0)

    const saleRes = await db.collection('sales')
      .where({ tireId })
      .get()
    const totalOut = saleRes.data.filter(r => !r.isDeleted).reduce((sum, r) => sum + (r.qty || 0), 0)

    const currentStock = totalIn - totalOut

    if (outQty > currentStock) {
      return { ok: false, message: `库存不足，当前库存: ${currentStock}，出库数量: ${outQty}` }
    }

    const total = +(outQty * (unitPrice || 0)).toFixed(2)

    const record = {
      tireId,
      customer,
      qty: outQty,
      unitCost: Number(unitCost) || 0,
      unitPrice: Number(unitPrice) || 0,
      total,
      outType: outType || 'sales',
      date: date || new Date().toISOString().slice(0, 10),
      note: note || '',
      isDeleted: false,
      createdAt: Date.now()
    }

    const res = await db.collection('sales').add({ data: record })
    return { ok: true, _id: res._id, currentStock: currentStock - outQty }
  } catch (e) {
    return { ok: false, message: e.message }
  }
}
