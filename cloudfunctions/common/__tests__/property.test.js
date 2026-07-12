// 性质测试（Property Testing）：用大量随机输入钉死计分守恒不变量
// 与 calculator.test.js 的 case-based 回归互补——后者钉"旧==新"，这里钉"不变量恒成立"
// 适合纯函数：未来 M2/M3 重构 Calculator，这层守恒契约必须始终成立
const { calcPoolScore, calcPlayerDeltas, calcPlayerNetScore, verifyConsistency } = require('..')

// 确定性伪随机（mulberry32）——固定种子，任何失败都可复现
function mulberry32(seed) {
  let a = seed >>> 0
  return function () {
    a = (a + 0x6D2B79F5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}
const rand = mulberry32(20260712)
const ri = (max) => Math.floor(rand() * max)        // [0, max)
const pick = (arr) => arr[ri(arr.length)]

const PLAYER_IDS = ['P0', 'P1', 'P2', 'P3', 'P4', 'P5']
const WALK_TYPES = ['up', 'down', 'base']

// 生成 0~count 条随机 walk 记录（type/playerOpenId/score 全随机）
function genWalkRecords(count) {
  const records = []
  for (let i = 0; i < count; i++) {
    records.push({
      type: pick(WALK_TYPES),
      playerOpenId: pick(PLAYER_IDS),
      score: ri(500) + 1
    })
  }
  return records
}

// 生成 0~count 条随机麻将轮次（每轮 2~4 人分摊 delta，Σdelta 可不为 0）
function genMjRecords(count) {
  const records = []
  for (let i = 0; i < count; i++) {
    const n = ri(3) + 2
    const deltas = []
    for (let k = 0; k < n; k++) {
      deltas.push({ openId: pick(PLAYER_IDS), delta: ri(401) - 200 })
    }
    records.push({ type: 'mj_round', playerDeltas: deltas })
  }
  return records
}

describe('性质测试：walk_scoring 守恒不变量（10000 组随机）', () => {
  const N = 10000

  test('Σ(delta) + poolScore === 0 恒成立', () => {
    // 守恒核心：pool = Σup−Σdown，Σdelta = Σdown−Σup ⇒ 二者互为相反数
    // 若未来重构改了 pool 或 delta 任一方的符号/项，此式立刻破裂
    for (let i = 0; i < N; i++) {
      const records = genWalkRecords(ri(60))
      const pool = calcPoolScore(records, 'walk_scoring')
      const deltas = calcPlayerDeltas(records, 'walk_scoring')
      const sumDelta = Object.values(deltas).reduce((s, d) => s + d, 0)
      expect(sumDelta + pool).toBe(0)
    }
  })

  test('verifyConsistency 恒为 true（随机底分 + 随机记录）', () => {
    for (let i = 0; i < N; i++) {
      const records = genWalkRecords(ri(60))
      const pool = calcPoolScore(records, 'walk_scoring')
      const deltas = calcPlayerDeltas(records, 'walk_scoring')
      const players = PLAYER_IDS.map(id => {
        const base = ri(500)
        return { baseScore: base, netScore: base + (deltas[id] || 0) }
      })
      expect(verifyConsistency(players, pool, 'walk_scoring')).toBe(true)
    }
  })
})

describe('性质测试：mahjong_scoring 不变量（10000 组随机）', () => {
  const N = 10000

  test('poolScore 恒为 0（即便混入 up/down 记录）', () => {
    for (let i = 0; i < N; i++) {
      const records = genMjRecords(ri(30))
      // 偶尔混入 walk 记录，麻将模式必须仍忽略
      if (ri(2)) records.push({ type: 'up', playerOpenId: pick(PLAYER_IDS), score: ri(500) })
      expect(calcPoolScore(records, 'mahjong_scoring')).toBe(0)
    }
  })

  test('verifyConsistency 恒为 true（无公共池约束）', () => {
    for (let i = 0; i < N; i++) {
      const records = genMjRecords(ri(30))
      const deltas = calcPlayerDeltas(records, 'mahjong_scoring')
      const players = PLAYER_IDS.map(id => ({ baseScore: 0, netScore: deltas[id] || 0 }))
      expect(verifyConsistency(players, 0, 'mahjong_scoring')).toBe(true)
    }
  })
})

describe('性质测试：单玩家 vs 多玩家 API 一致（10000 组随机）', () => {
  const N = 10000

  test('calcPlayerNetScore === base + calcPlayerDeltas[id]', () => {
    for (let i = 0; i < N; i++) {
      const records = genWalkRecords(ri(60))
      const base = ri(500)
      const id = pick(PLAYER_IDS)
      const net = calcPlayerNetScore(base, records, id, 'walk_scoring')
      const deltas = calcPlayerDeltas(records, 'walk_scoring')
      expect(net).toBe(base + (deltas[id] || 0))
    }
  })
})
