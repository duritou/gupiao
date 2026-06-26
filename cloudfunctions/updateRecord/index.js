// 编辑进货/出库记录 — 库存自动重算
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()

exports.main = async (event) => {
  const { id, collection, data: updateData } = event

  if (!id || !collection || !updateData) {
    return { ok: false, message: '缺少参数' }
  }

  if (collection !== 'purchase' && collection !== 'sales') {
    return { ok: false, message: '集合名必须是 purchase 或 sales' }
  }

  try {
    // 如果是 purchase，重算 total
    if (collection === 'purchase' && updateData.qty && updateData.unitPrice) {
      updateData.total = +(updateData.qty * updateData.unitPrice).toFixed(2)
    }
    if (collection === 'sales' && updateData.qty && updateData.unitPrice) {
      updateData.total = +(updateData.qty * updateData.unitPrice).toFixed(2)
    }

    await db.collection(collection).doc(id).update({ data: { ...updateData, updatedAt: Date.now() } })
    return { ok: true }
  } catch (e) {
    return { ok: false, message: e.message }
  }
}
