// 云函数：删除单条麻将对局记录
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()

exports.main = async (event) => {
  const { recordId, roomCode } = event

  if (!recordId) return { ok: false, message: '记录ID不能为空' }

  try {
    // 删除 score_records 中的记录
    const delRes = await db.collection('score_records').doc(recordId).remove()

    if (!delRes.stats || delRes.stats.removed === 0) {
      return { ok: false, message: '记录不存在或已删除' }
    }

    // 更新房间时间
    if (roomCode) {
      await db.collection('rooms').doc(roomCode).update({
        data: { updateTime: Date.now() }
      }).catch(function () { /* 非关键，忽略失败 */ })
    }

    return { ok: true, message: '已删除' }
  } catch (e) {
    console.error('[deleteMjRound] 异常:', e.message || e)
    return { ok: false, message: e.message || '删除失败' }
  }
}
