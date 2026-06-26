// 流水统计 — 按时间范围聚合进货/出货数量和金额
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()
const _ = db.command

/** 分页获取集合全部记录（可选 where 过滤） */
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
  const { timeRange } = event
  const today = new Date().toISOString().slice(0, 10) // YYYY-MM-DD

  // 计算日期范围
  let whereClause = null

  if (timeRange === 'today') {
    // 今日：精确匹配 date === today
    whereClause = { date: today }
  } else if (timeRange === 'month') {
    // 近一月：30 天前至今
    const dateFrom = formatDate(addDays(new Date(), -30))
    whereClause = { date: _.gte(dateFrom) }
  } else if (timeRange === 'year') {
    // 近一年：365 天前至今
    const dateFrom = formatDate(addDays(new Date(), -365))
    whereClause = { date: _.gte(dateFrom) }
  } else if (timeRange === 'twoYears') {
    // 近两年：730 天前至今
    const dateFrom = formatDate(addDays(new Date(), -730))
    whereClause = { date: _.gte(dateFrom) }
  }
  // all 不传 whereClause → 全量

  try {
    // 分页获取数据
    const purchaseData = await fetchAll('purchase', whereClause)
    const saleData = await fetchAll('sales', whereClause)

    // 内存过滤 isDeleted + reduce 聚合
    const inQty = purchaseData
      .filter(r => !r.isDeleted)
      .reduce((s, r) => s + (r.qty || 0), 0)
    const inAmount = purchaseData
      .filter(r => !r.isDeleted)
      .reduce((s, r) => s + (r.total || 0), 0)
    const outQty = saleData
      .filter(r => !r.isDeleted)
      .reduce((s, r) => s + (r.qty || 0), 0)
    const outAmount = saleData
      .filter(r => !r.isDeleted)
      .reduce((s, r) => s + (r.total || 0), 0)

    console.log(`getStatistics timeRange=${timeRange}: 进货${purchaseData.length}条 出库${saleData.length}条 inQty=${inQty} inAmount=${inAmount} outQty=${outQty} outAmount=${outAmount}`)
    return {
      ok: true,
      inQty,
      inAmount: +inAmount.toFixed(2),
      outQty,
      outAmount: +outAmount.toFixed(2)
    }
  } catch (e) {
    console.error('getStatistics 异常:', e)
    return {
      ok: false,
      inQty: 0,
      inAmount: 0,
      outQty: 0,
      outAmount: 0,
      message: e.message
    }
  }
}

/** 日期加减天数，返回 Date 对象 */
function addDays(date, days) {
  const result = new Date(date)
  result.setDate(result.getDate() + days)
  return result
}

/** 格式化日期为 YYYY-MM-DD */
function formatDate(date) {
  return date.toISOString().slice(0, 10)
}
