// 一键清空出货记录
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()

exports.main = async () => {
  try {
    const ids = []
    let skip = 0
    while (true) {
      const res = await db.collection('sales').skip(skip).limit(100).get()
      if (res.data.length === 0) break
      res.data.forEach(r => ids.push(r._id))
      skip += 100
    }
    console.log(`clearSales: 共 ${ids.length} 条`)

    if (ids.length === 0) return { ok: true, deletedCount: 0, failCount: 0 }

    let ok = 0; let fail = 0
    for (const id of ids) {
      try {
        await db.collection('sales').doc(id).remove()
        ok++
      } catch (e) {
        fail++
        console.error(`clearSales: ${id} 失败`, e.message)
      }
    }

    console.log(`clearSales: 成功 ${ok}, 失败 ${fail}`)
    return { ok: true, deletedCount: ok, failCount: fail }
  } catch (e) {
    console.error('clearSales error:', e)
    return { ok: false, message: e.message }
  }
}
