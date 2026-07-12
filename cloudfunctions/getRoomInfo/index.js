// 云函数：获取游戏房间信息（含玩家净分数、公共池分数、流水记录，支持 walk_scoring / mahjong_scoring）
// 注：集合由 createRoom 首次创建时确保存在，本函数不再重复 ensureCollection
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()
const { calcPlayerDeltas, calcPoolScore, verifyConsistency, getDefaultBaseScore } = require('./common')

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
  const { roomCode } = event

  if (!roomCode) return { ok: false, message: '房间号不能为空' }

  console.log('[getRoomInfo] 入参 roomCode:', roomCode)

  try {
    // _id 即房间号，doc 查询无需索引
    const roomRes = await db.collection('rooms').doc(roomCode).get()
    console.log('[getRoomInfo] rooms.doc 结果:', !!roomRes.data)

    const room = roomRes.data
    if (!room || (room.gameType !== 'walk_scoring' && room.gameType !== 'mahjong_scoring')) {
      console.log('[getRoomInfo] 房间不存在或类型不匹配, gameType:', room && room.gameType)
      return { ok: false, message: '房间不存在' }
    }

    // 查询玩家列表
    const playersRes = await db.collection('room_players')
      .where({ roomId: roomCode })
      .orderBy('joinTime', 'asc')
      .get()
    console.log('[getRoomInfo] 玩家数:', playersRes.data.length)

    // 查询所有计分记录（分页全量拉取，避免 db.get() 默认 100 条上限漏数据）
    const records = await fetchAllScoreRecords(roomCode)
    console.log('[getRoomInfo] 记录数:', records.length)
    const gameType = room.gameType

    // 计分核心统一走 common 领域层（与重构前内联逻辑逐行等价，由 __tests__/calculator.test.js 守护）
    const deltas = calcPlayerDeltas(records, gameType)
    const poolScore = calcPoolScore(records, gameType)
    const defaultBase = getDefaultBaseScore(gameType)

    // 玩家列表附上净分数
    const players = playersRes.data.map(p => {
      const baseScore = p.baseScore !== undefined ? p.baseScore : defaultBase
      return {
        openId: p.openId,
        nickName: p.nickName,
        avatarUrl: p.avatarUrl,
        joinTime: p.joinTime,
        baseScore: baseScore,
        netScore: baseScore + (deltas[p.openId] || 0)
      }
    })

    // 守恒校验（仅 walk_scoring，麻将恒真）
    const verify = verifyConsistency(players, poolScore, gameType)

    console.log('[getRoomInfo] 返回成功, poolScore:', poolScore, 'verify:', verify, 'players:', players.length)
    return {
      ok: true,
      room: {
        _id: room._id,
        roomCode: room.roomCode,
        creatorOpenId: room.creatorOpenId,
        fractionMode: room.fractionMode || null,
        fractionAmount: room.fractionAmount || 0,
        fractionTakenBy: room.fractionTakenBy || [],
        playerCount: players.length,
        createTime: room.createTime,
        updateTime: room.updateTime
      },
      players: players,
      poolScore: poolScore,
      records: records,
      verify: verify
    }
  } catch (e) {
    console.error('[getRoomInfo] 异常:', e.message || e)
    return { ok: false, message: e.message || '获取房间信息失败' }
  }
}
