// 库存聚合查询 — 按 tireId 分组，实时计算库存 + 最近进货价
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()

/** 分页获取集合全部记录（突破默认100条限制） */
async function fetchAll(collection) {
  let all = []
  let skip = 0
  const PAGE_SIZE = 100
  while (true) {
    const res = await db.collection(collection).skip(skip).limit(PAGE_SIZE).get()
    if (res.data.length === 0) break
    all = all.concat(res.data)
    skip += PAGE_SIZE
  }
  console.log(`fetchAll(${collection}): ${all.length} 条`)
  return all
}

exports.main = async (event) => {
  const { supplierId } = event || {}

  try {
    // 分页获取全部轮胎 / 进货 / 出货（每集合可能超100条）
    const tires = await fetchAll('tires')
    const allPurchases = await fetchAll('purchase')
    const allSales = await fetchAll('sales')

    const result = tires.map(tire => {
      const purchases = allPurchases.filter(p => p.tireId === tire._id && !p.isDeleted)
      const sales = allSales.filter(s => s.tireId === tire._id && !s.isDeleted)

      const totalIn = purchases.reduce((s, p) => s + (p.qty || 0), 0)
      // 库存用 remainQuantity 求和（存量无此字段时回退用 qty）
      const stock = purchases.reduce((s, p) => s + (
        p.remainQuantity !== undefined ? p.remainQuantity : p.qty
      ) || 0, 0)
      const totalOut = totalIn - stock

      // 最近进货单价
      const sortedPurchases = purchases.sort((a, b) => (b.createdAt || 0) - (a.createdAt || 0))
      const lastPrice = sortedPurchases.length > 0 ? sortedPurchases[0].unitPrice : 0

      return {
        tireId: tire._id,
        size: tire.size,
        pattern: tire.pattern,
        ply: tire.ply || '',
        brand: tire.brand || '朝阳',
        stock,
        lastPrice,
        totalIn,
        totalOut
      }
    })

    // 如果有 supplierId 筛选
    let filtered = result
    if (supplierId) {
      const supplierTireIds = new Set()
      allPurchases.forEach(p => {
        if (p.supplierId === supplierId) supplierTireIds.add(p.tireId)
      })
      filtered = result.filter(r => supplierTireIds.has(r.tireId))
    }

    return { ok: true, list: filtered }
  } catch (e) {
    console.error('getStockList error:', e)
    return { ok: false, message: e.message, list: [] }
  }
}
