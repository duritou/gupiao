// 云函数：获取游戏房间信息（含玩家净分数、公共池分数、流水记录，支持 walk_scoring / mahjong_scoring）
// 注：集合由 createRoom 首次创建时确保存在，本函数不再重复 ensureCollection
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()

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

    // 查询所有计分记录
    const recordsRes = await db.collection('score_records')
      .where({ roomId: roomCode })
      .orderBy('createTime', 'desc')
      .get()
    console.log('[getRoomInfo] 记录数:', recordsRes.data.length)

    const records = recordsRes.data
    const isMahjong = room.gameType === 'mahjong_scoring'

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

    // 计算公共池分数（仅 walk_scoring，麻将无公共池）
    let poolScore = 0
    if (!isMahjong) {
      for (const r of records) {
        if (r.type === 'up') { poolScore += r.score }
        else if (r.type === 'down') { poolScore -= r.score }
      }
    }

    // 底分默认值：打牌 100，麻将 0
    const DEFAULT_BASE_SCORE = isMahjong ? 0 : 100

    // 玩家列表附上净分数
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

    // 验证 math（仅 walk_scoring 做此校验）
    const totalNet = players.reduce((sum, p) => sum + p.netScore, 0)
    const totalBase = players.reduce((sum, p) => sum + p.baseScore, 0)
    const verify = isMahjong ? true : (totalNet + poolScore) === totalBase

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
