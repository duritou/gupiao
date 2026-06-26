// 按品牌查询库存 — 聚合 purchase 按 tireId 分组，返回有库存的轮胎规格
// 无参调用返回有库存的品牌名列表；传 brandId 返回该品牌下的分组库存
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()

/** 分页获取集合全部记录 */
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
  const { brandId } = event || {}

  try {
    const purchases = await fetchAll('purchase')
    const tires = await fetchAll('tires')

    // 构建轮胎 Map
    const tireMap = {}
    tires.forEach(t => { tireMap[t._id] = t })

    // 只取未删除且有剩余库存的进货记录
    const activePurchases = purchases.filter(p => {
      if (p.isDeleted) return false
      const remain = p.remainQuantity !== undefined ? p.remainQuantity : p.qty
      return remain > 0
    })

    // ---- 无 brandId：返回有库存的品牌列表 ----
    if (!brandId) {
      const brandStockMap = {}  // brandName → true
      for (const p of activePurchases) {
        const tire = tireMap[p.tireId]
        if (tire) {
          const brandName = tire.brand || '朝阳轮胎'
          brandStockMap[brandName] = true
        }
      }
      const brands = Object.keys(brandStockMap).sort((a, b) => a.localeCompare(b, 'zh'))
      console.log(`getStockByBrand: 有库存的品牌 ${brands.length} 个:`, brands)
      return { ok: true, brands }
    }

    // ---- 有 brandId：按 tireId 分组聚合 ----
    // 先筛选出该品牌的轮胎 ID 集合
    const brandTireIds = new Set()
    tires.forEach(t => {
      if (String(t.brandId) === String(brandId) || String(t.brand) === String(brandId)) {
        brandTireIds.add(t._id)
      }
    })
    // 也支持按品牌名称匹配
    if (brandTireIds.size === 0) {
      tires.forEach(t => {
        if (t.brand === brandId) {
          brandTireIds.add(t._id)
        }
      })
    }

    console.log(`getStockByBrand: brandId=${brandId} 匹配到 ${brandTireIds.size} 个轮胎规格`)

    // 按 tireId 分组聚合
    const groupMap = {}  // tireId → { purchases: [...], totalStock, lastPrice }
    for (const p of activePurchases) {
      if (!brandTireIds.has(p.tireId)) continue
      const remain = p.remainQuantity !== undefined ? p.remainQuantity : p.qty
      if (!groupMap[p.tireId]) {
        groupMap[p.tireId] = {
          purchases: [],
          totalStock: 0,
          lastDate: ''
        }
      }
      groupMap[p.tireId].purchases.push({
        purchaseId: p._id,
        remainQuantity: remain,
        unitPrice: p.unitPrice || 0,
        date: p.date || ''
      })
      groupMap[p.tireId].totalStock += remain
      if (p.date > groupMap[p.tireId].lastDate) {
        groupMap[p.tireId].lastDate = p.date
      }
    }

    // 组装输出列表
    const list = []
    for (const [tid, group] of Object.entries(groupMap)) {
      const tire = tireMap[tid]
      if (!tire) continue

      // 同轮胎按日期升序（FIFO）
      group.purchases.sort((a, b) => (a.date || '').localeCompare(b.date || ''))

      // 最近进价取最近一次进货的单价
      const lastPurchase = group.purchases.reduce((latest, p) =>
        (p.date > latest.date) ? p : latest
      , group.purchases[0])
      const lastPrice = lastPurchase ? lastPurchase.unitPrice : 0

      list.push({
        tireId: tid,
        size: tire.size || '',
        pattern: tire.pattern || '',
        ply: tire.ply || '',
        loadIndex: tire.loadIndex || '',
        brand: tire.brand || '朝阳轮胎',
        totalStock: group.totalStock,
        lastPrice,
        batches: group.purchases  // FIFO 排序后的批次列表，供 createSale 自动分配
      })
    }

    // 排序：按规格+花纹
    list.sort((a, b) => {
      const sizeCmp = (a.size || '').localeCompare(b.size || '')
      if (sizeCmp !== 0) return sizeCmp
      return (a.pattern || '').localeCompare(b.pattern || '')
    })

    console.log(`getStockByBrand: 返回 ${list.length} 个分组`)
    return { ok: true, list }

  } catch (e) {
    console.error('getStockByBrand error:', e)
    return { ok: false, message: e.message, brands: [], list: [] }
  }
}
