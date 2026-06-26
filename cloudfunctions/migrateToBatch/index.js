// 一次性迁移：为存量 purchase 记录补充 remainQuantity 字段
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

exports.main = async () => {
  try {
    const purchases = await fetchAll('purchase')

    // 筛选出缺少 remainQuantity 字段的存量记录
    const toFix = purchases.filter(p => p.remainQuantity === undefined)
    console.log(`migrateToBatch: 共 ${purchases.length} 条进货，${toFix.length} 条需补充 remainQuantity`)

    if (toFix.length === 0) {
      return { ok: true, updated: 0, message: '所有记录已有 remainQuantity，无需迁移' }
    }

    let ok = 0
    let fail = 0

    // 逐条独立 try/catch — FAIL-10 铁则
    for (const p of toFix) {
      try {
        const qty = p.qty || 0
        console.log(`migrateToBatch: 更新 ${p._id} remainQuantity = ${qty}`)
        const res = await db.collection('purchase').doc(p._id).update({
          data: { remainQuantity: qty }
        })
        if (res.stats && res.stats.updated > 0) {
          ok++
        } else {
          // 降级：先读再 set
          console.warn(`migrateToBatch: ${p._id} update 返回 0，降级 set`)
          await db.collection('purchase').doc(p._id).set({
            data: Object.assign({}, p, { remainQuantity: qty })
          })
          ok++
        }
      } catch (e) {
        fail++
        console.error(`migrateToBatch: ${p._id} 失败`, e.message)
      }
    }

    console.log(`migrateToBatch: 成功 ${ok}, 失败 ${fail}`)
    return { ok: true, updated: ok, fail, total: toFix.length }
  } catch (e) {
    console.error('migrateToBatch error:', e)
    return { ok: false, message: e.message }
  }
}
