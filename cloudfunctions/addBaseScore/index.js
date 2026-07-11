// 云函数：给玩家增加100底分
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()

exports.main = async (event) => {
  const wxContext = cloud.getWXContext()
  const openId = wxContext.OPENID

  const { roomCode, targetPlayerOpenId } = event

  if (!openId) return { ok: false, message: '未获取到用户身份' }
  if (!roomCode) return { ok: false, message: '房间号不能为空' }
  if (!targetPlayerOpenId) return { ok: false, message: '未指定目标玩家' }

  console.log('[addBaseScore] 入参:', { roomCode, targetPlayerOpenId, operatorOpenId: openId })

  try {
    // 验证房间存在
    const roomRes = await db.collection('rooms').doc(roomCode).get()
    const room = roomRes.data
    if (!room || room.gameType !== 'walk_scoring') {
      return { ok: false, message: '房间不存在' }
    }

    // 验证操作者在房间中
    const operatorRes = await db.collection('room_players')
      .where({ roomId: roomCode, openId: openId })
      .get()
    if (operatorRes.data.length === 0) {
      return { ok: false, message: '你不在该房间中' }
    }

    // 查找目标玩家
    const targetRes = await db.collection('room_players')
      .where({ roomId: roomCode, openId: targetPlayerOpenId })
      .get()
    if (targetRes.data.length === 0) {
      return { ok: false, message: '目标玩家不在该房间中' }
    }

    const player = targetRes.data[0]
    const currentBaseScore = player.baseScore || 100
    const newBaseScore = currentBaseScore + 100
    const now = Date.now()

    // 更新玩家底分
    await db.collection('room_players').doc(player._id).update({
      data: { baseScore: newBaseScore }
    })
    console.log('[addBaseScore] 底分更新:', currentBaseScore, '→', newBaseScore)

    // 写入计分记录（type=base，不影响公共池）
    const addRes = await db.collection('score_records').add({
      data: {
        roomId: roomCode,
        roomCode: roomCode,
        openId: openId,
        playerOpenId: targetPlayerOpenId,
        playerNickName: player.nickName,
        type: 'base',
        score: 100,
        createTime: now
      }
    })
    console.log('[addBaseScore] 记录写入 _id:', addRes._id)

    return {
      ok: true,
      newBaseScore: newBaseScore,
      targetPlayerName: player.nickName
    }
  } catch (e) {
    console.error('[addBaseScore] 异常:', e.message || e)
    return { ok: false, message: e.message || '增加底分失败' }
  }
}
