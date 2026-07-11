// 云函数：添加计分记录（上分/取分/麻将对局记录）
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()

// 全量拉取房间计分记录
// 云函数 db.get() 默认上限 100 条，记录超过会静默截断导致求和漏数据，必须分页累加
async function fetchAllScoreRecords(roomCode) {
  const PAGE_SIZE = 100
  let all = []
  let skip = 0
  while (true) {
    const res = await db.collection('score_records')
      .where({ roomId: roomCode })
      .orderBy('createTime', 'desc')
      .skip(skip)
      .limit(PAGE_SIZE)
      .get()
    all = all.concat(res.data)
    if (res.data.length < PAGE_SIZE) break
    skip += PAGE_SIZE
  }
  return all
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

    // down 操作：校验公共池余额是否充足，并顺带算出 target 玩家写前净分（供末尾增量返回复用，省去二次全表拉取）
    let poolScoreBefore = 0   // 仅 down 路径赋值
    let targetNetBefore = 0   // target 玩家写前净分（不含 base）
    if (type === 'down') {
      const allRecords = await fetchAllScoreRecords(roomCode)
      for (const r of allRecords) {
        if (r.type === 'up') {
          poolScoreBefore += r.score
          if (r.playerOpenId === targetPlayerOpenId) targetNetBefore -= r.score
        } else if (r.type === 'down') {
          poolScoreBefore -= r.score
          if (r.playerOpenId === targetPlayerOpenId) targetNetBefore += r.score
        }
      }
      if (poolScoreBefore < score) {
        return { ok: false, message: `公共池仅剩${poolScoreBefore}分，不足以取出${score}分` }
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

    // 增量构造返回值（省去末尾二次全表拉取）：
    // - down 路径：写后 poolScore = 写前 poolScoreBefore - score；target 净分 = base + targetNetBefore + score
    // - up 路径：前端不读返回的分数字段（_backgroundSync 只看 ok），最终以 _loadRoomData 拉取为准
    const DEFAULT_BASE_SCORE = 100
    const actualBaseScore = targetPlayer.baseScore !== undefined ? targetPlayer.baseScore : DEFAULT_BASE_SCORE
    const result = {
      ok: true,
      actionType: type,
      actionScore: score,
      targetPlayerName: targetPlayer.nickName
    }
    if (type === 'down') {
      result.poolScore = poolScoreBefore - score
      result.playerNetScore = actualBaseScore + targetNetBefore + score
    }
    console.log('[addScoreRecord] 完成, type:', type, 'score:', score)
    return result
  } catch (e) {
    console.error('[addScoreRecord] 异常:', e.message || e)
    return { ok: false, message: e.message || '添加记录失败' }
  }
}
