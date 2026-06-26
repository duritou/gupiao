// 云函数：获取房间流水记录（分页）
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()

exports.main = async (event) => {
  const { roomCode, pageSize, cursor } = event

  if (!roomCode) return { ok: false, message: '房间号不能为空' }

  const limit = Math.min(pageSize || 20, 100)

  try {
    // _id 即房间号，doc 查询无需索引（同时校验 gameType）
    const roomRes = await db.collection('rooms').doc(roomCode).get()
    if (!roomRes.data || roomRes.data.gameType !== 'walk_scoring') {
      return { ok: false, message: '房间不存在' }
    }

    // 构建查询：按时间倒序
    let query = db.collection('score_records')
      .where({ roomId: roomCode })
      .orderBy('createTime', 'desc')
      .limit(limit + 1) // 多取一条判断是否有下一页

    if (cursor) {
      query = db.collection('score_records')
        .where({ roomId: roomCode, createTime: db.command.lt(cursor) })
        .orderBy('createTime', 'desc')
        .limit(limit + 1)
    }

    const res = await query.get()
    const hasMore = res.data.length > limit
    const records = hasMore ? res.data.slice(0, limit) : res.data
    const nextCursor = hasMore ? records[records.length - 1].createTime : null

    return {
      ok: true,
      records: records,
      hasMore: hasMore,
      nextCursor: nextCursor
    }
  } catch (e) {
    return { ok: false, message: e.message || '获取流水记录失败' }
  }
}
