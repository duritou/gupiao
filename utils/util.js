const formatTime = date => {
  const year = date.getFullYear()
  const month = date.getMonth() + 1
  const day = date.getDate()
  const hour = date.getHours()
  const minute = date.getMinutes()
  const second = date.getSeconds()
  return `${[year, month, day].map(formatNumber).join('/')} ${[hour, minute, second].map(formatNumber).join(':')}`
}

const formatNumber = n => {
  n = n.toString()
  return n[1] ? n : `0${n}`
}

// ---- 常量 ----
const MAX_SEATS = 10
const ROOM_ID_LENGTH = 6
const MAX_LOG_ENTRIES = 200
const BLINDS = { small: 0, big: 0 }
const GAME_PHASES = ['第1轮 · 翻牌前', '第2轮 · 翻牌', '第3轮 · 转牌', '第4轮 · 河牌', '摊牌']
const IDENTITY_POLL_MAX = 15
const IDENTITY_POLL_INTERVAL = 300

// ---- 游戏类型 ----
const GAME_TYPES = {
  WALK_SCORING: 'walk_scoring',
  MAHJONG_SCORING: 'mahjong_scoring'
}

// ---- 游戏元数据（首页展示） ----
const GAME_META = {
  [GAME_TYPES.WALK_SCORING]: {
    name: '打牌计分', icon: '🃏', minPlayers: 2, maxPlayers: 20,
    category: 'party', desc: '线下计分·公共池模式·随意加入'
  },
  [GAME_TYPES.MAHJONG_SCORING]: {
    name: '麻将计分', icon: '🀄', minPlayers: 4, maxPlayers: 4,
    category: 'party', desc: '线下麻将计分·4人局·番数计算'
  }
}

// ---- 游戏类型 → 页面路径映射 ----
const GAME_PAGE_MAP = {
  [GAME_TYPES.WALK_SCORING]: '/pages/walk_scoring/walk_scoring',
  [GAME_TYPES.MAHJONG_SCORING]: '/pages/mahjong_scoring/mahjong_scoring'
}

function getPagePath(gameType) {
  return GAME_PAGE_MAP[gameType] || GAME_PAGE_MAP[GAME_TYPES.WALK_SCORING]
}

function gameTypeFromPagePath(path) {
  for (const [type, pagePath] of Object.entries(GAME_PAGE_MAP)) {
    if (path.indexOf(pagePath.replace(/^\//, '')) !== -1) return type
  }
  return GAME_TYPES.WALK_SCORING
}

// ---- 房间 ID ----
const generateRoomId = () => {
  return String(Math.floor(100000 + Math.random() * 900000))
}

// ---- 深拷贝（结构化方式，避免 JSON 的性能和类型丢失问题）----
const deepClone = obj => {
  if (obj === null || typeof obj !== 'object') return obj
  if (Array.isArray(obj)) return obj.map(deepClone)
  const cloned = {}
  for (const key of Object.keys(obj)) {
    cloned[key] = deepClone(obj[key])
  }
  return cloned
}

// ---- 创建空白玩家 ----
const createPlayer = (name, chip, openId) => ({
  name,
  chip,
  openId: openId || '',
  isFolded: false,
  roundBet: 0,
  isSitOut: false
})

// ---- 创建空白游戏状态 ----
const blankGame = () => ({
  isStart: false,
  phase: -1,
  settings: { peopleNum: 6, initChip: 1000, smallBlind: BLINDS.small, bigBlind: BLINDS.big },
  players: [],
  curIdx: 0,
  dealerIdx: 0,
  pot: 0,
  curBet: 0,
  history: [],
  actedMask: 0,
  deck: [],
  communityCards: [],
  sidePots: [],
  showdownResult: null
})

module.exports = {
  formatTime,
  generateRoomId,
  deepClone,
  createPlayer,
  blankGame,
  BLINDS,
  GAME_PHASES,
  MAX_SEATS,
  ROOM_ID_LENGTH,
  MAX_LOG_ENTRIES,
  IDENTITY_POLL_MAX,
  IDENTITY_POLL_INTERVAL,
  GAME_TYPES,
  GAME_META,
  GAME_PAGE_MAP,
  getPagePath,
  gameTypeFromPagePath
}
