// 计分领域常量（纯数据，无运行时依赖）
// 与云函数历史硬编码保持一致，便于单一来源管理

// 游戏类型
const GAME_TYPES = {
  WALK_SCORING: 'walk_scoring',       // 打牌计分（公共池模式）
  MAHJONG_SCORING: 'mahjong_scoring'  // 麻将计分（对局结算模式）
}

// 计分记录类型（score_records.type）
const RECORD_TYPES = {
  BASE: 'base',       // 加底分（仅流水展示，不影响公共池 / 净变化）
  UP: 'up',           // 上分：玩家 → 公共池
  DOWN: 'down',       // 取分：公共池 → 玩家
  MJ_ROUND: 'mj_round' // 麻将一局（含多人 playerDeltas）
}

// 公共池取分模式（takeFromPool.mode）
const TAKE_MODES = {
  ALL: 'all',     // 取全部
  HALF: 'half',   // 取 1/2
  THIRD: 'third'  // 取 1/3
}

// 取分模式 → 除数映射（takeFromPool 内 divisor 推导）
const TAKE_DIVISORS = {
  [TAKE_MODES.ALL]: 1,
  [TAKE_MODES.HALF]: 2,
  [TAKE_MODES.THIRD]: 3
}

// 默认底分：打牌 100，麻将 0（对应 getRoomInfo:92 / joinRoom:89,142,177 / addBaseScore:43）
const DEFAULT_BASE_SCORE = {
  [GAME_TYPES.WALK_SCORING]: 100,
  [GAME_TYPES.MAHJONG_SCORING]: 0
}

// 每次加底分的固定增量（addBaseScore 每次加 100）
const BASE_SCORE_STEP = 100

module.exports = {
  GAME_TYPES,
  RECORD_TYPES,
  TAKE_MODES,
  TAKE_DIVISORS,
  DEFAULT_BASE_SCORE,
  BASE_SCORE_STEP
}
