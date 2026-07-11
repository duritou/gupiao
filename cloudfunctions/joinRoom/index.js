// 云函数：加入游戏房间（支持 walk_scoring / mahjong_scoring）
// 优化：加入成功后直接返回房间完整数据（玩家列表 + 对局记录），前端无需再调 getRoomInfo
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

/** 查询房间完整数据（玩家列表 + 计分记录），供加入成功后返回 */
async function fetchRoomData(roomCode, gameType) {
  // 查询玩家列表
  const playersRes = await db.collection('room_players')
    .where({ roomId: roomCode })
    .orderBy('joinTime', 'asc')
    .get()

  // 查询计分记录（分页全量拉取，避免 db.get() 默认 100 条上限漏数据）
  const records = await fetchAllScoreRecords(roomCode)
  const isMahjong = gameType === 'mahjong_scoring'

  // 计算每位玩家的净分数
  const playerScores = {}
  if (isMahjong) {
    // 麻将：从 mj_round 记录的 playerDeltas 汇总每位玩家的净分变化
    for (const r of records) {
      if (r.type !== 'mj_round') continue
      const deltas = r.playerDeltas || []
      for (const d of deltas) {
        if (!playerScores[d.openId]) playerScores[d.openId] = 0
        playerScores[d.openId] += d.delta || 0
      }
    }
  } else {
    // 打牌：取分总和 - 上分总和，不包含 base 类型
    for (const r of records) {
      if (r.type === 'base') continue
      if (!playerScores[r.playerOpenId]) playerScores[r.playerOpenId] = 0
      if (r.type === 'down') {
        playerScores[r.playerOpenId] += r.score
      } else if (r.type === 'up') {
        playerScores[r.playerOpenId] -= r.score
      }
    }
  }

  // 公共池分数（仅 walk_scoring）
  let poolScore = 0
  if (!isMahjong) {
    for (const r of records) {
      if (r.type === 'up') { poolScore += r.score }
      else if (r.type === 'down') { poolScore -= r.score }
    }
  }

  // 底分默认值：打牌 100，麻将 0
  const DEFAULT_BASE_SCORE = isMahjong ? 0 : 100

  const players = playersRes.data.map(p => {
    const baseScore = p.baseScore !== undefined ? p.baseScore : DEFAULT_BASE_SCORE
    return {
      openId: p.openId,
      nickName: p.nickName,
      avatarUrl: p.avatarUrl,
      joinTime: p.joinTime,
      baseScore: baseScore,
      netScore: baseScore + (playerScores[p.openId] || 0)
    }
  })

  return { players, records, poolScore }
}

exports.main = async (event) => {
  // 确保集合存在后进行操作
  await ensureCollection('rooms')
  await ensureCollection('room_players')
  const wxContext = cloud.getWXContext()
  const openId = wxContext.OPENID

  const { roomCode, nickName, avatarUrl } = event

  if (!openId) return { ok: false, message: '未获取到用户身份' }
  if (!roomCode) return { ok: false, message: '房间号不能为空' }
  if (!nickName) return { ok: false, message: '昵称不能为空' }

  try {
    // _id 即房间号，doc 查询无需索引
    const roomRes = await db.collection('rooms').doc(roomCode).get()

    const room = roomRes.data
    if (!room || (room.gameType !== 'walk_scoring' && room.gameType !== 'mahjong_scoring')) {
      return { ok: false, message: '房间不存在' }
    }

    // 检查是否已在房间中
    const existRes = await db.collection('room_players')
      .where({ roomId: roomCode, openId: openId })
      .get()

    if (existRes.data.length > 0) {
      // 已在房间中，更新昵称和头像（不覆盖 baseScore）
      const existingBaseScore = existRes.data[0].baseScore
      const updateData = {
        nickName: nickName,
        avatarUrl: avatarUrl || ''
      }
      // 如果旧记录没有 baseScore 字段，补上默认值（打牌 100，麻将 0）
      if (existingBaseScore === undefined) {
        updateData.baseScore = room.gameType === 'mahjong_scoring' ? 0 : 100
      }
      await db.collection('room_players').doc(existRes.data[0]._id).update({
        data: updateData
      })

      // 返回房间完整数据，前端无需再调 getRoomInfo
      const roomData = await fetchRoomData(roomCode, room.gameType)

      return {
        ok: true,
        roomId: roomCode,
        roomCode: roomCode,
        rejoined: true,
        room: {
          creatorOpenId: room.creatorOpenId,
          gameType: room.gameType,
          createTime: room.createTime,
          updateTime: room.updateTime
        },
        players: roomData.players,
        poolScore: roomData.poolScore,
        records: roomData.records
      }
    }

    // 加入房间（baseScore：打牌 100，麻将 0）
    const now = Date.now()
    await db.collection('room_players').add({
      data: {
        roomId: roomCode,
        roomCode: roomCode,
        openId: openId,
        nickName: nickName,
        avatarUrl: avatarUrl || '',
        baseScore: room.gameType === 'mahjong_scoring' ? 0 : 100,
        joinTime: now
      }
    })

    // 更新 rooms.players 数组
    await db.collection('rooms').doc(roomCode).update({
      data: {
        players: db.command.addToSet(openId),
        updateTime: now
      }
    })

    // 返回房间完整数据，前端无需再调 getRoomInfo
    const roomData = await fetchRoomData(roomCode, room.gameType)

    return {
      ok: true,
      roomId: roomCode,
      roomCode: roomCode,
      rejoined: false,
      room: {
        creatorOpenId: room.creatorOpenId,
        gameType: room.gameType,
        createTime: room.createTime,
        updateTime: now
      },
      players: roomData.players,
      poolScore: roomData.poolScore,
      records: roomData.records
    }
  } catch (e) {
    return { ok: false, message: e.message || '加入房间失败' }
  }
}
