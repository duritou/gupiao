// 云函数：麻将计分 — 添加一局记录
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()

exports.main = async (event) => {
  const wxContext = cloud.getWXContext()
  const openId = wxContext.OPENID

  const {
    roomCode,
    roundNum,
    mode,          // 'dianpao' | 'zimo'
    winnerName,
    loserName,
    fanCount,
    baseScore,
    barScore,
    barPlayerName,
    taiBanEnabled,
    playerDeltas,  // [{ name: string, openId: string, delta: number }]
    snapshot       // 撤销用：本局之前各玩家总分 [{ openId: string, totalScore: number }]
  } = event

  if (!openId) return { ok: false, message: '未获取到用户身份' }
  if (!roomCode) return { ok: false, message: '房间号不能为空' }

  console.log('[mjAddRound] 入参:', { roomCode, roundNum, mode, winnerName, playerDeltas: playerDeltas && playerDeltas.length })

  try {
    const roomRes = await db.collection('rooms').doc(roomCode).get()
    const room = roomRes.data
    if (!room || room.gameType !== 'mahjong_scoring') {
      return { ok: false, message: '房间不存在或类型不匹配' }
    }

    // 所有玩家均可计分（点炮/自摸/转账）
    // 转账模式：校验发起人必须是玩家之一
    if (mode === 'transfer') {
      var isPlayer = room.players && room.players.indexOf(openId) >= 0
      if (!isPlayer) {
        return { ok: false, message: '你不在该房间中' }
      }
      // 校验转账发起人的 delta 为负（扣自己分转给他人）
      var deltas = playerDeltas || []
      var selfDelta = 0
      for (var di = 0; di < deltas.length; di++) {
        if (deltas[di].openId === openId) { selfDelta = deltas[di].delta; break }
      }
      if (selfDelta >= 0) {
        return { ok: false, message: '转账数据异常' }
      }
    }

    const now = Date.now()

    // 写入对局记录到 score_records（type='mj_round'）
    const addRes = await db.collection('score_records').add({
      data: {
        roomId: roomCode,
        roomCode: roomCode,
        openId: openId,
        type: 'mj_round',
        roundNum: roundNum,
        mode: mode,
        winnerName: winnerName,
        loserName: loserName || '',
        fanCount: fanCount || 0,
        baseScore: baseScore || 0,
        barScore: barScore || 0,
        barPlayerName: barPlayerName || '',
        taiBanEnabled: taiBanEnabled || false,
        playerDeltas: playerDeltas || [],
        snapshot: snapshot || [],
        createTime: now
      }
    })

    // 更新房间时间
    await db.collection('rooms').doc(roomCode).update({
      data: { updateTime: now }
    })

    return {
      ok: true,
      recordId: addRes._id
    }
  } catch (e) {
    console.error('[mjAddRound] 异常:', e.message || e)
    return { ok: false, message: e.message || '添加对局记录失败' }
  }
}
