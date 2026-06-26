// 单轮胎详情 — 基本信息 + 库存 + 全部流水 + 历史进价
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()

exports.main = async (event) => {
  const { tireId } = event
  if (!tireId) return { ok: false, message: '缺少 tireId' }

  try {
    // 轮胎基本信息
    const tireRes = await db.collection('tires').doc(tireId).get()
    const tire = tireRes.data

    if (!tire) return { ok: false, message: '轮胎不存在' }

    // 进货记录
    const purchasesRes = await db.collection('purchase')
      .where({ tireId })
      .orderBy('date', 'desc')
      .get()
    const purchases = purchasesRes.data

    // 出库记录
    const salesRes = await db.collection('sales')
      .where({ tireId })
      .orderBy('date', 'desc')
      .get()
    const sales = salesRes.data

    // 过滤已删除记录
    const activePurchases = purchases.filter(r => !r.isDeleted)
    const activeSales = sales.filter(r => !r.isDeleted)

    // 当前库存（用 remainQuantity 求和，存量无此字段时回退用 qty）
    const totalIn = activePurchases.reduce((s, p) => s + (p.qty || 0), 0)
    const stock = activePurchases.reduce((s, p) => s + (
      p.remainQuantity !== undefined ? p.remainQuantity : p.qty
    ) || 0, 0)

    // 最近进货单价
    const sortedPurchases = [...activePurchases].sort((a, b) => (b.createdAt || 0) - (a.createdAt || 0))
    const lastPrice = sortedPurchases.length > 0 ? sortedPurchases[0].unitPrice : 0

    // 历史进价列表（按日期升序，用于趋势图）
    const priceHistory = [...activePurchases]
      .sort((a, b) => (a.date || '').localeCompare(b.date || ''))
      .map(p => ({ date: p.date, unitPrice: p.unitPrice, qty: p.qty }))

    return {
      ok: true,
      tire,
      stock,
      lastPrice,
      purchase: activePurchases,
      sales: activeSales,
      priceHistory
    }
  } catch (e) {
    return { ok: false, message: e.message }
  }
}
