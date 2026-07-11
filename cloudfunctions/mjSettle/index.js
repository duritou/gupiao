/**
 * mjSettle — 麻将计分结算云函数
 * 功能：保存结算快照、重置所有玩家分数
 * 权限：仅房间成员可调用
 *
 * 数据结构说明（重要）：
 * - rooms.players: [openId字符串] — 仅存成员 openId 列表
 * - room_players: 玩家详情（昵称、头像、baseScore）
 * - score_records: 计分流水（netScore = baseScore + 汇总 mj_round.deltas）
 * - 分数"重置" = 删除该房间所有 score_records（netScore 回到 baseScore=0）
 */
const cloud = require('wx-server-sdk')
cloud.init()
const db = cloud.database()

/** 确保集合存在（不存在则创建，已存在则跳过） */
async function ensureCollection(name) {
  try {
    await db.createCollection(name)
  } catch (e) {
    var msg = (e.errMsg || e.message || e.errCode || '')
    if (msg.indexOf('ResourceUnavailable.ResourceExist') > -1) return
    throw e
  }
}

/** 全量拉取房间计分记录（云函数 db.get() 默认上限 100 条，记录超过会静默截断导致求和漏数据，必须分页累加） */
async function fetchAllScoreRecords(roomCode) {
  var PAGE_SIZE = 100
  var all = []
  var skip = 0
  while (true) {
    var res = await db.collection('score_records')
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

exports.main = async (event, context) => {
  const { roomCode } = event
  const wxContext = cloud.getWXContext()
  const openId = wxContext.OPENID

  if (!roomCode) return { ok: false, message: '缺少房间号' }

  try {
    // 1. 获取房间基本信息（_id 即 roomCode，doc 查询无需索引）
    const roomRes = await db.collection('rooms').doc(roomCode).get()
    if (!roomRes.data) return { ok: false, message: '房间不存在' }
    const room = roomRes.data

    // 2. 权限校验：rooms.players 是 openId 字符串数组，不是对象数组
    const memberOpenIds = room.players || []
    if (!memberOpenIds.includes(openId)) {
      return { ok: false, message: '你不是该房间成员，无权结算' }
    }

    // 3. 查询 room_players 获取玩家详情（昵称、头像、baseScore）
    const playersRes = await db.collection('room_players')
      .where({ roomId: roomCode })
      .orderBy('joinTime', 'asc')
      .get()

    // 4. 查询 score_records，汇总每位玩家的净得分（分页全量拉取，避免漏数据）
    const records = await fetchAllScoreRecords(roomCode)
    const playerDeltas = {} // openId → 累计 delta
    for (const r of records) {
      if (r.type !== 'mj_round') continue
      const deltas = r.playerDeltas || []
      for (const d of deltas) {
        if (!playerDeltas[d.openId]) playerDeltas[d.openId] = 0
        playerDeltas[d.openId] += d.delta || 0
      }
    }

    // 5. 构建结算快照：包含每位玩家的昵称、头像、净得分
    const playersSnapshot = playersRes.data.map(p => {
      const baseScore = p.baseScore !== undefined ? p.baseScore : 0
      return {
        openId: p.openId,
        nickName: p.nickName || '',
        avatarUrl: p.avatarUrl || '',
        netScore: baseScore + (playerDeltas[p.openId] || 0)
      }
    })

    const settlement = {
      roomCode: roomCode,
      gameType: 'mahjong',
      startTime: room.createTime || 0,      // 房间创建时间
      settleTime: Date.now(),               // 结算时间
      players: playersSnapshot,             // 结算时各玩家分数快照
      memberOpenIds: memberOpenIds,         // 成员 openId 列表（权限查询用）
      creatorOpenId: room.creatorOpenId || ''
    }

    // 6. 确保 mj_settlements 集合存在，然后保存结算记录
    await ensureCollection('mj_settlements')
    await db.collection('mj_settlements').add({ data: settlement })

    // 7. 重置分数：删除该房间所有计分记录
    //    分数 = baseScore + 汇总(deltas)，删除后 netScore = baseScore（麻将=0）
    //    分页获取全部记录（云数据库 get() 默认上限 100，skip+limit 突破限制）
    var allRecords = []
    var offset = 0
    var PAGE_SIZE = 100
    while (true) {
      var batch = await db.collection('score_records')
        .where({ roomId: roomCode })
        .skip(offset)
        .limit(PAGE_SIZE)
        .get()
      if (batch.data.length === 0) break
      allRecords = allRecords.concat(batch.data)
      if (batch.data.length < PAGE_SIZE) break
      offset += PAGE_SIZE
    }

    console.log('[mjSettle] 待删除 score_records 数量:', allRecords.length)
    var deletePromises = allRecords.map(function (rec) {
      return db.collection('score_records').doc(rec._id).remove()
    })
    await Promise.all(deletePromises)

    // 8. 标记房间已结算（getRoomInfo 无需改动，因为分数已通过删除记录重置）
    await db.collection('rooms').doc(roomCode).update({
      data: { settledAt: Date.now() }
    })

    console.log('[mjSettle] 结算成功, roomCode:', roomCode, 'players:', playersSnapshot.length)
    return { ok: true, settlement: settlement }
  } catch (e) {
    console.error('[mjSettle] 结算失败:', e)
    return { ok: false, message: '结算失败: ' + (e.message || '服务异常') }
  }
}
