// 查询可用批次 — 返回有剩余库存的进货批次，用于出库页面选择
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
  const { keyword, brandFilter } = event || {}

  try {
    // 全量获取
    const purchases = await fetchAll('purchase')
    const tires = await fetchAll('tires')
    const suppliers = await fetchAll('suppliers')

    // 构建快速查找 Map
    const tireMap = {}
    tires.forEach(t => { tireMap[t._id] = t })
    const supplierMap = {}
    suppliers.forEach(s => { supplierMap[s._id] = s })

    // 组装可用批次列表
    const list = purchases
      .filter(p => !p.isDeleted)
      .map(p => {
        const tire = tireMap[p.tireId]
        const supplier = supplierMap[p.supplierId] || {}
        const effectiveRemain = p.remainQuantity !== undefined ? p.remainQuantity : p.qty

        return {
          purchaseId: p._id,
          supplierId: p.supplierId || '',
          supplierName: supplier.name || '未知供应商',
          tireId: p.tireId,
          size: tire ? tire.size : '?',
          pattern: tire ? tire.pattern : '?',
          ply: tire ? (tire.ply || '') : '',
          loadIndex: tire ? (tire.loadIndex || '') : '',
          brand: tire ? (tire.brand || '朝阳') : '?',
          remainQuantity: effectiveRemain,
          unitPrice: p.unitPrice || 0,
          date: p.date || ''
        }
      })
      .filter(r => r.remainQuantity > 0)
      // 关键字过滤：规格/花纹
      .filter(r => {
        if (!keyword || !keyword.trim()) return true
        const kw = keyword.trim().toLowerCase()
        return r.size.toLowerCase().includes(kw) ||
               r.pattern.toLowerCase().includes(kw)
      })
      // 品牌过滤
      .filter(r => {
        if (!brandFilter || brandFilter === '全部') return true
        return r.brand === brandFilter
      })

    // 排序：同轮胎按日期升序（先进先出），再按 remainQuantity 降序
    list.sort((a, b) => {
      const tireCompare = (a.size + a.pattern).localeCompare(b.size + b.pattern)
      if (tireCompare !== 0) return tireCompare
      const dateCompare = (a.date || '').localeCompare(b.date || '')
      if (dateCompare !== 0) return dateCompare
      return b.remainQuantity - a.remainQuantity
    })

    console.log(`getAvailableStock: 返回 ${list.length} 条可用批次`)
    return { ok: true, list }
  } catch (e) {
    console.error('getAvailableStock error:', e)
    return { ok: false, message: e.message, list: [] }
  }
}
