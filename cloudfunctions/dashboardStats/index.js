// 仪表盘统计 — 今日进货总额 + 今日出库数量
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()
const _ = db.command

/** 分页获取集合全部记录（突破默认100条限制） */
async function fetchAll(collection, whereClause) {
  let all = []
  let skip = 0
  const PAGE_SIZE = 100
  while (true) {
    let query = db.collection(collection).skip(skip).limit(PAGE_SIZE)
    if (whereClause) query = query.where(whereClause)
    const res = await query.get()
    if (res.data.length === 0) break
    all = all.concat(res.data)
    skip += PAGE_SIZE
  }
  return all
}

exports.main = async (event) => {
  const today = event.date || new Date().toISOString().slice(0, 10) // YYYY-MM-DD

  try {
    // 分页获取今日全部进货记录（可能超100条）
    const purchaseData = await fetchAll('purchase', { date: today })
    const purchaseTotal = purchaseData
      .filter(r => !r.isDeleted)
      .reduce((sum, r) => sum + (r.total || 0), 0)

    // 分页获取今日全部出库记录
    const saleData = await fetchAll('sales', { date: today })
    const saleTotalQty = saleData
      .filter(r => !r.isDeleted)
      .reduce((sum, r) => sum + (r.qty || 0), 0)

    console.log(`dashboardStats: ${today} 进货${purchaseData.length}条(有效${purchaseTotal}) 出库${saleData.length}条(有效${saleTotalQty})`)
    return { ok: true, purchaseTotal: purchaseTotal.toFixed(2), saleTotalQty }
  } catch (e) {
    console.error('dashboardStats 异常:', e)
    return { ok: false, purchaseTotal: '0.00', saleTotalQty: 0, message: e.message }
  }
}
