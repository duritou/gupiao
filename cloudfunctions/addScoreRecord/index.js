// 云函数：添加计分记录（上分/取分/麻将对局记录）
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()

// 确保集合存在（不存在则创建，已存在则跳过）
async function ensureCollection(name) {
  try {
    await db.createCollection(name)
  } catch (e) {
    // ResourceUnavailable.ResourceExist → 集合已存在，正常跳过
    // SDK 错误信息可能在 errMsg、message 或 errCode 中
    const msg = (e.errMsg || e.message || e.errCode || '')
    if (msg.indexOf('ResourceUnavailable.ResourceExist') > -1) {
      return
    }
    throw e
  }
}

exports.main = async (event) => {
  const wxContext = cloud.getWXContext()
  const openId = wxContext.OPENID

  const { roomCode, type, score, targetPlayerOpenId } = event

  if (!openId) return { ok: false, message: '未获取到用户身份' }
  if (!roomCode) return { ok: false, message: '房间号不能为空' }
  if (!type || (type !== 'up' && type !== 'down')) {
    return { ok: false, message: '操作类型无效，必须是 up（上分）或 down（取分）' }
  }
  if (!score || !Number.isInteger(score) || score <= 0) {
    return { ok: false, message: '分数必须为正整数' }
  }
  if (!targetPlayerOpenId) return { ok: false, message: '未指定目标玩家' }

  console.log('[addScoreRecord] 入参:', { roomCode, type, score, targetPlayerOpenId, operatorOpenId: openId })

  try {
    // 确保集合存在
    await ensureCollection('rooms')
    await ensureCollection('room_players')
    await ensureCollection('score_records')
    console.log('[addScoreRecord] 所有集合就绪')

    // _id 即房间号，doc 查询无需索引
    const roomRes = await db.collection('rooms').doc(roomCode).get()
    console.log('[addScoreRecord] rooms.doc 结果:', !!roomRes.data)

    const room = roomRes.data
    if (!room || (room.gameType !== 'walk_scoring' && room.gameType !== 'mahjong_scoring')) {
      console.log('[addScoreRecord] 房间不存在或类型不匹配:', room)
      return { ok: false, message: '房间不存在' }
    }

    // 验证操作者在房间中
    const operatorRes = await db.collection('room_players')
      .where({ roomId: roomCode, openId: openId })
      .get()
    console.log('[addScoreRecord] 操作者查询结果数:', operatorRes.data.length)

    if (operatorRes.data.length === 0) {
      // 额外日志：查看 room_players 中该房间有哪些玩家
      const allPlayers = await db.collection('room_players').where({ roomId: roomCode }).get()
      console.log('[addScoreRecord] 房间所有玩家:', allPlayers.data.map(p => ({ openId: p.openId, nickName: p.nickName })))
      return { ok: false, message: '你不在该房间中' }
    }

    // 验证目标玩家在房间中
    const targetRes = await db.collection('room_players')
      .where({ roomId: roomCode, openId: targetPlayerOpenId })
      .get()
    console.log('[addScoreRecord] 目标玩家查询结果数:', targetRes.data.length)

    if (targetRes.data.length === 0) {
      console.log('[addScoreRecord] 目标玩家不在房间中, 查找 openId:', targetPlayerOpenId)
      return { ok: false, message: '目标玩家不在该房间中' }
    }

    const targetPlayer = targetRes.data[0]

    // down 操作：校验公共池余额是否充足
    if (type === 'down') {
      const allRecords = await db.collection('score_records').where({ roomId: roomCode }).get()
      let poolScore = 0
      for (const r of allRecords.data) {
        if (r.type === 'up') poolScore += r.score
        else if (r.type === 'down') poolScore -= r.score
      }
      if (poolScore < score) {
        return { ok: false, message: `公共池仅剩${poolScore}分，不足以取出${score}分` }
      }
    }

    const now = Date.now()

    // 写入计分记录（记录的是目标玩家的分数变动）
    const addRes = await db.collection('score_records').add({
      data: {
        roomId: roomCode,
        roomCode: roomCode,
        openId: openId,           // 操作者 openId
        playerOpenId: targetPlayerOpenId, // 分数归属玩家
        playerNickName: targetPlayer.nickName,
        type: type,
        score: score,
        createTime: now
      }
    })
    console.log('[addScoreRecord] 写入记录 _id:', addRes._id)

    // 更新房间更新时间；上分时重置分数模式（公共池基数变化，旧锁定失效）
    const roomUpdate = { updateTime: now }
    if (type === 'up') {
      roomUpdate.fractionMode = null
      roomUpdate.fractionAmount = 0
      roomUpdate.fractionTakenBy = []
    }
    await db.collection('rooms').doc(roomCode).update({
      data: roomUpdate
    })

    // 重新计算目标玩家净分数和公共池分数
    const recordsRes = await db.collection('score_records')
      .where({ roomId: roomCode })
      .get()
    console.log('[addScoreRecord] 重新计算, 记录总数:', recordsRes.data.length)

    const DEFAULT_BASE_SCORE = 100
    const actualBaseScore = targetPlayer.baseScore !== undefined ? targetPlayer.baseScore : DEFAULT_BASE_SCORE
    const records = recordsRes.data
    let playerNetScore = 0
    let poolScore = 0

    for (const r of records) {
      if (r.type === 'base') continue // base 类型不计入净分，不影响公共池
      if (r.type === 'up') {
        poolScore += r.score
        if (r.playerOpenId === targetPlayerOpenId) {
          playerNetScore -= r.score
        }
      } else if (r.type === 'down') {
        poolScore -= r.score
        if (r.playerOpenId === targetPlayerOpenId) {
          playerNetScore += r.score
        }
      }
    }

    const displayScore = actualBaseScore + playerNetScore
    console.log('[addScoreRecord] 计算完成, displayScore:', displayScore, 'poolScore:', poolScore)
    return {
      ok: true,
      playerNetScore: displayScore,
      poolScore: poolScore,
      actionType: type,
      actionScore: score,
      targetPlayerName: targetPlayer.nickName
    }
  } catch (e) {
    console.error('[addScoreRecord] 异常:', e.message || e)
    return { ok: false, message: e.message || '添加记录失败' }
  }
}
