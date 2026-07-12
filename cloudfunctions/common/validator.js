// 输入校验器（纯函数，不依赖 db）
// db 相关校验（房间存在、操作者/目标玩家在房间）仍由云函数负责，M2 统一入口时再收口
// 此处仅校验不依赖数据库的纯逻辑：操作类型、分值正整数、取分模式合法性

const { ERR, makeError } = require('./errors')
const { RECORD_TYPES, TAKE_MODES, DEFAULT_BASE_SCORE, GAME_TYPES } = require('./constants')

/**
 * 校验上分/取分输入（type + score）
 * 等价：addScoreRecord:34-39（type 必须是 up/down，score 必须是正整数）
 * @param {{type?:string, score?:number}} input
 * @returns {{ok:true}|{ok:false,code:string,message:string}}
 */
function validateScoreInput({ type, score } = {}) {
  if (!type || (type !== RECORD_TYPES.UP && type !== RECORD_TYPES.DOWN)) {
    return makeError(ERR.ERR_TYPE_INVALID)
  }
  if (!score || !Number.isInteger(score) || score <= 0) {
    return makeError(ERR.ERR_SCORE_INVALID)
  }
  return { ok: true }
}

/**
 * 校验取分模式（mode 必须是 all/half/third）
 * 等价：takeFromPool:35-37
 * @param {string} mode
 * @returns {{ok:true}|{ok:false,code:string,message:string}}
 */
function validateTakeMode(mode) {
  if (!mode || ![TAKE_MODES.ALL, TAKE_MODES.HALF, TAKE_MODES.THIRD].includes(mode)) {
    return makeError(ERR.ERR_MODE_INVALID)
  }
  return { ok: true }
}

/**
 * 取游戏类型对应的默认底分（打牌 100，麻将 0）
 * 等价：getRoomInfo:92 / joinRoom:89,142,177（isMahjong ? 0 : 100）
 * @param {string} gameType
 * @returns {number}
 */
function getDefaultBaseScore(gameType) {
  return DEFAULT_BASE_SCORE[gameType] !== undefined
    ? DEFAULT_BASE_SCORE[gameType]
    : DEFAULT_BASE_SCORE[GAME_TYPES.WALK_SCORING]
}

module.exports = {
  validateScoreInput,
  validateTakeMode,
  getDefaultBaseScore
}
