// calculator 回归测试：钉死抽取后的纯函数与原 4 处内联逻辑逐行等价（旧=新）
const { calcPoolScore, calcPlayerDeltas, calcPlayerNetScore, verifyConsistency } = require('..')

// ===== 真实结构样例（贴近 score_records 实际字段）=====
const walkRecords = [
  { type: 'base', playerOpenId: 'A', score: 100 },
  { type: 'base', playerOpenId: 'B', score: 100 },
  { type: 'up',   playerOpenId: 'A', score: 100 },
  { type: 'up',   playerOpenId: 'B', score: 50 },
  { type: 'down', playerOpenId: 'A', score: 30 },
  { type: 'down', playerOpenId: 'C', score: 120 }
]

const mjRecords = [
  { type: 'mj_round', playerDeltas: [{ openId: 'A', delta: 80 }, { openId: 'B', delta: -30 }, { openId: 'C', delta: -50 }] },
  { type: 'mj_round', playerDeltas: [{ openId: 'A', delta: -20 }, { openId: 'B', delta: 20 }] },
  { type: 'up', playerOpenId: 'A', score: 999 } // 麻将模式下应被忽略
]

describe('calcPoolScore', () => {
  test('打牌：Σ(up) - Σ(down)，base 不影响', () => {
    expect(calcPoolScore(walkRecords, 'walk_scoring')).toBe(0) // 100+50-30-120
  })
  test('空记录 → 0', () => {
    expect(calcPoolScore([], 'walk_scoring')).toBe(0)
  })
  test('只有 up → Σup', () => {
    expect(calcPoolScore([{ type: 'up', playerOpenId: 'A', score: 80 }], 'walk_scoring')).toBe(80)
  })
  test('down 大于 up → 负值（照实计算，合法性由上层校验）', () => {
    expect(calcPoolScore([{ type: 'up', score: 10 }, { type: 'down', score: 30 }], 'walk_scoring')).toBe(-20)
  })
  test('麻将：恒 0（即便含 up/down 记录）', () => {
    expect(calcPoolScore(mjRecords, 'mahjong_scoring')).toBe(0)
  })
})

describe('calcPlayerDeltas', () => {
  test('打牌：down 加、up 减、base 跳过', () => {
    expect(calcPlayerDeltas(walkRecords, 'walk_scoring')).toEqual({ A: -70, B: -50, C: 120 })
  })
  test('打牌：base 记录完全不参与', () => {
    const onlyBase = [{ type: 'base', playerOpenId: 'A', score: 100 }, { type: 'base', playerOpenId: 'A', score: 100 }]
    expect(calcPlayerDeltas(onlyBase, 'walk_scoring')).toEqual({})
  })
  test('打牌：空记录 → {}', () => {
    expect(calcPlayerDeltas([], 'walk_scoring')).toEqual({})
  })
  test('麻将：累加 mj_round.playerDeltas[].delta，忽略 up/down/base', () => {
    expect(calcPlayerDeltas(mjRecords, 'mahjong_scoring')).toEqual({ A: 60, B: -10, C: -50 })
  })
  test('麻将：delta 缺省按 0', () => {
    expect(calcPlayerDeltas([{ type: 'mj_round', playerDeltas: [{ openId: 'A' }, { openId: 'B', delta: 5 }] }], 'mahjong_scoring')).toEqual({ A: 0, B: 5 })
  })
})

describe('calcPlayerNetScore', () => {
  test('= baseScore + 累计变化', () => {
    expect(calcPlayerNetScore(100, walkRecords, 'A', 'walk_scoring')).toBe(30) // 100 + (-70)
  })
  test('无记录玩家 → baseScore', () => {
    expect(calcPlayerNetScore(100, walkRecords, 'NEW', 'walk_scoring')).toBe(100)
  })
  test('麻将玩家净分', () => {
    expect(calcPlayerNetScore(0, mjRecords, 'A', 'mahjong_scoring')).toBe(60)
  })
})

describe('verifyConsistency', () => {
  test('打牌守恒成立 → true', () => {
    // A:base100 net30, B:base100 net50, C:base0 net120 ; totalNet=200 totalBase=200 pool=0
    const players = [
      { baseScore: 100, netScore: 30 },
      { baseScore: 100, netScore: 50 },
      { baseScore: 0, netScore: 120 }
    ]
    expect(verifyConsistency(players, 0, 'walk_scoring')).toBe(true)
  })
  test('打牌不守恒 → false', () => {
    expect(verifyConsistency([{ baseScore: 100, netScore: 30 }], 999, 'walk_scoring')).toBe(false) // 30+999≠100
  })
  test('麻将：恒 true', () => {
    expect(verifyConsistency([{ baseScore: 0, netScore: 9999 }], 0, 'mahjong_scoring')).toBe(true)
  })
})

// ===== 回归守护：与 getRoomInfo / joinRoom 旧内联逻辑逐行等价 =====
// legacyCalcScores 为重构前云函数内联实现的忠实复刻（getRoomInfo:59-89）
function legacyCalcScores(records, gameType) {
  const isMahjong = gameType === 'mahjong_scoring'
  const playerScores = {}
  if (isMahjong) {
    for (const r of records) {
      if (r.type !== 'mj_round') continue
      const deltas = r.playerDeltas || []
      for (const d of deltas) {
        if (!playerScores[d.openId]) playerScores[d.openId] = 0
        playerScores[d.openId] += d.delta || 0
      }
    }
  } else {
    for (const r of records) {
      if (r.type === 'base') continue
      if (!playerScores[r.playerOpenId]) playerScores[r.playerOpenId] = 0
      if (r.type === 'down') playerScores[r.playerOpenId] += r.score
      else if (r.type === 'up') playerScores[r.playerOpenId] -= r.score
    }
  }
  let poolScore = 0
  if (!isMahjong) {
    for (const r of records) {
      if (r.type === 'up') poolScore += r.score
      else if (r.type === 'down') poolScore -= r.score
    }
  }
  return { playerScores, poolScore }
}

describe('与旧逻辑等价（回归守护）', () => {
  const cases = [
    { name: 'walk 打牌样例', records: walkRecords, gameType: 'walk_scoring' },
    { name: 'mahjong 麻将样例', records: mjRecords, gameType: 'mahjong_scoring' },
    { name: '空记录', records: [], gameType: 'walk_scoring' },
    { name: '全 base', records: [{ type: 'base', playerOpenId: 'A', score: 100 }], gameType: 'walk_scoring' },
    { name: '全 up', records: [{ type: 'up', playerOpenId: 'A', score: 10 }, { type: 'up', playerOpenId: 'B', score: 20 }], gameType: 'walk_scoring' },
    { name: 'down>up 负池', records: [{ type: 'up', score: 10 }, { type: 'down', score: 30 }], gameType: 'walk_scoring' },
    { name: '单条 mj_round', records: [{ type: 'mj_round', playerDeltas: [{ openId: 'A', delta: 5 }] }], gameType: 'mahjong_scoring' }
  ]
  for (const { name, records, gameType } of cases) {
    test(`calcPoolScore 等价：${name}`, () => {
      expect(calcPoolScore(records, gameType)).toBe(legacyCalcScores(records, gameType).poolScore)
    })
    test(`calcPlayerDeltas 等价：${name}`, () => {
      expect(calcPlayerDeltas(records, gameType)).toEqual(legacyCalcScores(records, gameType).playerScores)
    })
  }
})
