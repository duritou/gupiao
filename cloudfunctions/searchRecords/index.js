// 跨 collections 搜索 — purchases + sales 模糊匹配
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()
const _ = db.command

exports.main = async (event) => {
  const { keyword, type, dateFrom, dateTo, supplierId, customer } = event || {}

  // 构建查询条件
  const buildWhere = (baseWhere) => {
    const w = { ...baseWhere }
    if (dateFrom) w.date = _.gte(dateFrom)
    if (dateTo) w.date = w.date ? _.and(w.date, _.lte(dateTo)) : _.lte(dateTo)
    return w
  }

  let purchaseResults = []
  let saleResults = []

  try {
    // 搜索进货记录
    if (!type || type === 'purchase') {
      const pw = buildWhere({})
      if (supplierId) pw.supplierId = supplierId
      if (keyword) pw.note = db.RegExp({ regexp: keyword, options: 'i' })

      const pRes = await db.collection('purchase')
        .where(pw)
        .orderBy('date', 'desc')
        .limit(50)
        .get()
      purchaseResults = pRes.data.filter(r => !r.isDeleted).map(r => ({ ...r, recordType: 'purchase' }))
    }

    // 搜索出库记录
    if (!type || type === 'sale') {
      const sw = buildWhere({})
      if (customer) sw.customer = db.RegExp({ regexp: customer, options: 'i' })
      if (keyword) {
        sw.customer = db.RegExp({ regexp: keyword, options: 'i' })
      }

      const sRes = await db.collection('sales')
        .where(sw)
        .orderBy('date', 'desc')
        .limit(50)
        .get()
      saleResults = sRes.data.filter(r => !r.isDeleted).map(r => ({ ...r, recordType: 'sale' }))
    }

    // 合并并按日期降序排列
    const all = [...purchaseResults, ...saleResults]
      .sort((a, b) => (b.date || '').localeCompare(a.date || ''))

    return { ok: true, list: all, total: all.length }
  } catch (e) {
    return { ok: false, message: e.message, list: [] }
  }
}
