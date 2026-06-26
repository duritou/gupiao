/**
 * mjClearHistory — 清除当前用户的所有麻将结算记录（云端）
 * 功能：从 mj_settlements 中删除当前用户参与过的所有结算文档
 * 权限：仅操作当前用户自己的记录
 */
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()

exports.main = async (event, context) => {
  const wxContext = cloud.getWXContext()
  const openId = wxContext.OPENID

  if (!openId) {
    return { ok: false, message: '未获取到用户身份' }
  }

  try {
    // 分页拉取当前用户参与的所有结算记录
    var allSettlements = []
    var offset = 0
    var PAGE_SIZE = 100
    while (true) {
      var batch = await db.collection('mj_settlements')
        .where({ memberOpenIds: openId })
        .skip(offset)
        .limit(PAGE_SIZE)
        .get()
      if (batch.data.length === 0) break
      allSettlements = allSettlements.concat(batch.data)
      if (batch.data.length < PAGE_SIZE) break
      offset += PAGE_SIZE
    }

    console.log('[mjClearHistory] 待删除结算记录数量:', allSettlements.length)

    if (allSettlements.length === 0) {
      return { ok: true, message: '无云端记录需清除', deletedCount: 0 }
    }

    // 逐条删除结算文档
    var deletePromises = allSettlements.map(function (doc) {
      return db.collection('mj_settlements').doc(doc._id).remove()
    })
    await Promise.all(deletePromises)

    console.log('[mjClearHistory] 已清除', allSettlements.length, '条结算记录, openId:', openId)
    return { ok: true, message: '云端记录已清除', deletedCount: allSettlements.length }
  } catch (e) {
    console.error('[mjClearHistory] 清除失败:', e)
    return { ok: false, message: '清除失败: ' + (e.message || '服务异常') }
  }
}
