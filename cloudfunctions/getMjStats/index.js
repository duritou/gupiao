/**
 * getMjStats — 麻将个人数据统计
 * 功能：汇总当前用户所有已结算对局，计算 6 项个人指标
 * 数据源：mj_settlements（需要复合索引 memberOpenIds + settleTime desc）
 */
const cloud = require('wx-server-sdk')
cloud.init()
const db = cloud.database()

/** 确保集合存在 */
async function ensureCollection(name) {
  try {
    await db.createCollection(name)
  } catch (e) {
    var msg = (e.errMsg || e.message || e.errCode || '')
    if (msg.indexOf('ResourceUnavailable.ResourceExist') > -1) return
    throw e
  }
}

exports.main = async (event, context) => {
  const wxContext = cloud.getWXContext()
  const openId = wxContext.OPENID

  try {
    await ensureCollection('mj_settlements')

    // 分页拉取当前用户所有结算记录
    var allSettlements = []
    var offset = 0
    var PAGE_SIZE = 100
    while (true) {
      var batch = await db.collection('mj_settlements')
        .where({ memberOpenIds: openId })
        .orderBy('settleTime', 'desc')
        .skip(offset)
        .limit(PAGE_SIZE)
        .get()
      if (batch.data.length === 0) break
      allSettlements = allSettlements.concat(batch.data)
      if (batch.data.length < PAGE_SIZE) break
      offset += PAGE_SIZE
    }

    // 无记录 → 返回零值
    if (allSettlements.length === 0) {
      return {
        ok: true,
        totalGames: 0,
        totalScore: 0,
        avgScore: 0,
        winRate: 0,
        bestScore: 0,
        worstScore: 0,
        lastGameTime: null,
        history: []
      }
    }

    // 遍历所有结算记录，提取当前用户的 netScore
    var userScores = []
    for (var i = 0; i < allSettlements.length; i++) {
      var s = allSettlements[i]
      var players = s.players || []
      var found = null
      for (var j = 0; j < players.length; j++) {
        if (players[j].openId === openId) {
          found = players[j]
          break
        }
      }
      if (found) {
        userScores.push({
          netScore: found.netScore || 0,
          settlement: s
        })
      } else {
        console.warn('[getMjStats] 结算 ' + s.roomCode + ' 中未找到用户 ' + openId)
      }
    }

    var totalGames = userScores.length
    var totalScore = 0
    var bestScore = -Infinity
    var worstScore = Infinity
    var wins = 0

    for (var k = 0; k < userScores.length; k++) {
      var ns = userScores[k].netScore
      totalScore += ns
      if (ns > bestScore) bestScore = ns
      if (ns < worstScore) worstScore = ns
      if (ns > 0) wins++
    }

    // 构建返回数据
    var avgScore = parseFloat((totalScore / totalGames).toFixed(2))
    var winRate = parseFloat(((wins / totalGames) * 100).toFixed(1))
    var lastGameTime = allSettlements[0].settleTime

    // 构建历史列表（最多 50 条，预提取 myScore）
    var history = []
    var histLen = Math.min(userScores.length, 50)
    for (var h = 0; h < histLen; h++) {
      var item = userScores[h]
      history.push({
        roomCode: item.settlement.roomCode,
        startTime: item.settlement.startTime || 0,
        settleTime: item.settlement.settleTime || 0,
        gameType: item.settlement.gameType || 'mahjong',
        myScore: item.netScore,
        players: (item.settlement.players || []).map(function (p) {
          return {
            openId: p.openId,
            nickName: p.nickName || '',
            avatarUrl: p.avatarUrl || '',
            netScore: p.netScore || 0
          }
        })
      })
    }

    return {
      ok: true,
      totalGames: totalGames,
      totalScore: totalScore,
      avgScore: avgScore,
      winRate: winRate,
      bestScore: bestScore === -Infinity ? 0 : bestScore,
      worstScore: worstScore === Infinity ? 0 : worstScore,
      lastGameTime: lastGameTime,
      history: history
    }
  } catch (e) {
    console.error('[getMjStats] 统计失败:', e)
    return {
      ok: false,
      message: '统计失败: ' + (e.message || '服务异常'),
      totalGames: 0,
      totalScore: 0,
      avgScore: 0,
      winRate: 0,
      bestScore: 0,
      worstScore: 0,
      lastGameTime: null,
      history: []
    }
  }
}
