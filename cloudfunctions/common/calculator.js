// 计分计算器（纯函数）
// 从 getRoomInfo / joinRoom / addScoreRecord / takeFromPool 四处重复逻辑收敛而来
// 行为必须与原逻辑逐行等价 —— 由 __tests__/calculator.test.js 守护契约
// 零 wx-server-sdk 依赖，可跨端复用（云函数 / 云托管 / Node）

const { GAME_TYPES, RECORD_TYPES } = require('./constants')

const isMahjong = gameType => gameType === GAME_TYPES.MAHJONG_SCORING

/**
 * 计算公共池分数（仅 walk_scoring；麻将无公共池，返回 0）
 * poolScore = Σ(up.score) - Σ(down.score)，base 记录不影响
 * 等价：getRoomInfo:83-89 / joinRoom:80-86 / takeFromPool:69-74 / addScoreRecord:87-91
 * @param {ScoreRecord[]} records
 * @param {string} gameType
 * @returns {number}
 */
function calcPoolScore(records, gameType) {
  if (isMahjong(gameType)) return 0
  let poolScore = 0
  for (const r of records) {
    if (r.type === RECORD_TYPES.UP) poolScore += r.score
    else if (r.type === RECORD_TYPES.DOWN) poolScore -= r.score
  }
  return poolScore
}

/**
 * 汇总每位玩家的累计净变化（不含底分）
 * - 麻将：累加 mj_round.playerDeltas[].delta
 * - 打牌：down 加、up 减，base 跳过
 * 等价：getRoomInfo:59-80 / joinRoom:56-77（playerScores）/ addScoreRecord:86-93（targetNetBefore 单玩家视角）
 * @param {ScoreRecord[]} records
 * @param {string} gameType
 * @returns {Object<string, number>} { [openId]: 净变化 }
 */
function calcPlayerDeltas(records, gameType) {
  const deltas = {}
  if (isMahjong(gameType)) {
    for (const r of records) {
      if (r.type !== RECORD_TYPES.MJ_ROUND) continue
      const list = r.playerDeltas || []
      for (const d of list) {
        deltas[d.openId] = (deltas[d.openId] || 0) + (d.delta || 0)
      }
    }
  } else {
    for (const r of records) {
      if (r.type === RECORD_TYPES.BASE) continue
      const id = r.playerOpenId
      if (r.type === RECORD_TYPES.DOWN) deltas[id] = (deltas[id] || 0) + r.score
      else if (r.type === RECORD_TYPES.UP) deltas[id] = (deltas[id] || 0) - r.score
    }
  }
  return deltas
}

/**
 * 计算单玩家净分 = baseScore + 累计净变化
 * 等价：getRoomInfo:103 / joinRoom:99（netScore = baseScore + (playerScores[openId]||0)）
 * @param {number} baseScore 该玩家底分
 * @param {ScoreRecord[]} records
 * @param {string} openId
 * @param {string} gameType
 * @returns {number}
 */
function calcPlayerNetScore(baseScore, records, openId, gameType) {
  const deltas = calcPlayerDeltas(records, gameType)
  return baseScore + (deltas[openId] || 0)
}

/**
 * 守恒校验
 * - 麻将：恒真（无公共池约束）
 * - 打牌：Σ(netScore) + poolScore === Σ(baseScore)
 * 等价：getRoomInfo:108-110
 * @param {Array<{baseScore:number, netScore:number}>} players
 * @param {number} poolScore
 * @param {string} gameType
 * @returns {boolean}
 */
function verifyConsistency(players, poolScore, gameType) {
  if (isMahjong(gameType)) return true
  const totalNet = players.reduce((sum, p) => sum + p.netScore, 0)
  const totalBase = players.reduce((sum, p) => sum + p.baseScore, 0)
  return (totalNet + poolScore) === totalBase
}

module.exports = {
  calcPoolScore,
  calcPlayerDeltas,
  calcPlayerNetScore,
  verifyConsistency
}
