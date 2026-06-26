// 重置库存 — 物理删除全部进货 + 出货记录
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()

async function clearCollection(collection) {
  const ids = []
  let skip = 0
  while (true) {
    const res = await db.collection(collection).skip(skip).limit(100).get()
    if (res.data.length === 0) break
    res.data.forEach(r => ids.push(r._id))
    skip += 100
  }
  console.log(`resetStock: ${collection} 共 ${ids.length} 条`)

  if (ids.length === 0) return { success: 0, fail: 0 }

  let ok = 0; let fail = 0
  for (const id of ids) {
    try {
      await db.collection(collection).doc(id).remove()
      ok++
    } catch (e) {
      fail++
      console.error(`resetStock: ${collection}/${id} 失败`, e.message)
    }
  }

  console.log(`resetStock: ${collection} 成功 ${ok}, 失败 ${fail}`)
  return { success: ok, fail }
}

exports.main = async () => {
  try {
    const p = await clearCollection('purchase')
    const s = await clearCollection('sales')
    return {
      ok: true,
      purchaseCount: p.success,
      salesCount: s.success,
      purchaseFail: p.fail,
      salesFail: s.fail
    }
  } catch (e) {
    console.error('resetStock error:', e)
    return { ok: false, message: e.message, purchaseCount: 0, salesCount: 0 }
  }
}
