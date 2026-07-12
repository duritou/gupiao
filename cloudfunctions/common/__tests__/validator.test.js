// validator 回归测试：钉死纯逻辑校验与 addScoreRecord/takeFromPool 内联校验等价
const { validateScoreInput, validateTakeMode, getDefaultBaseScore, ERR, makeError } = require('..')

describe('validateScoreInput', () => {
  test('up + 正整数 → ok', () => {
    expect(validateScoreInput({ type: 'up', score: 100 })).toEqual({ ok: true })
  })
  test('down + 正整数 → ok', () => {
    expect(validateScoreInput({ type: 'down', score: 50 })).toEqual({ ok: true })
  })
  test('type 缺失 → ERR_TYPE_INVALID', () => {
    const r = validateScoreInput({ score: 100 })
    expect(r.ok).toBe(false)
    expect(r.code).toBe(ERR.ERR_TYPE_INVALID)
  })
  test('type=base（非法）→ ERR_TYPE_INVALID', () => {
    expect(validateScoreInput({ type: 'base', score: 100 }).code).toBe(ERR.ERR_TYPE_INVALID)
  })
  test('score=0 → ERR_SCORE_INVALID', () => {
    expect(validateScoreInput({ type: 'up', score: 0 }).code).toBe(ERR.ERR_SCORE_INVALID)
  })
  test('score 负数 → ERR_SCORE_INVALID', () => {
    expect(validateScoreInput({ type: 'up', score: -10 }).code).toBe(ERR.ERR_SCORE_INVALID)
  })
  test('score 非整数 → ERR_SCORE_INVALID', () => {
    expect(validateScoreInput({ type: 'up', score: 1.5 }).code).toBe(ERR.ERR_SCORE_INVALID)
  })
  test('score 缺失 → ERR_SCORE_INVALID', () => {
    expect(validateScoreInput({ type: 'up' }).code).toBe(ERR.ERR_SCORE_INVALID)
  })
  test('入参整体缺省 → ERR_TYPE_INVALID（不抛错）', () => {
    expect(validateScoreInput().code).toBe(ERR.ERR_TYPE_INVALID)
  })
  test('错误返回体结构含 ok/code/message', () => {
    const r = validateScoreInput({ type: 'x' })
    expect(r).toHaveProperty('ok', false)
    expect(r).toHaveProperty('code')
    expect(r).toHaveProperty('message')
  })
})

describe('validateTakeMode', () => {
  test('all/half/third → ok', () => {
    expect(validateTakeMode('all')).toEqual({ ok: true })
    expect(validateTakeMode('half')).toEqual({ ok: true })
    expect(validateTakeMode('third')).toEqual({ ok: true })
  })
  test('非法值 → ERR_MODE_INVALID', () => {
    expect(validateTakeMode('quarter').code).toBe(ERR.ERR_MODE_INVALID)
  })
  test('缺失 → ERR_MODE_INVALID', () => {
    expect(validateTakeMode().code).toBe(ERR.ERR_MODE_INVALID)
  })
})

describe('getDefaultBaseScore', () => {
  test('打牌 → 100', () => expect(getDefaultBaseScore('walk_scoring')).toBe(100))
  test('麻将 → 0', () => expect(getDefaultBaseScore('mahjong_scoring')).toBe(0))
  test('未知 gameType → 兜底 100', () => expect(getDefaultBaseScore('xxx')).toBe(100))
  test('undefined → 兜底 100', () => expect(getDefaultBaseScore(undefined)).toBe(100))
})

describe('makeError', () => {
  test('默认文案', () => {
    expect(makeError(ERR.ERR_POOL_NOT_ENOUGH)).toEqual({
      ok: false,
      code: 'ERR_POOL_NOT_ENOUGH',
      message: '公共池余额不足'
    })
  })
  test('自定义文案覆盖默认', () => {
    const e = makeError(ERR.ERR_POOL_NOT_ENOUGH, '公共池仅剩5分')
    expect(e.ok).toBe(false)
    expect(e.code).toBe('ERR_POOL_NOT_ENOUGH')
    expect(e.message).toBe('公共池仅剩5分')
  })
  test('带 extra 附加字段', () => {
    const e = makeError(ERR.ERR_VERIFY_FAILED, null, { poolScore: -5 })
    expect(e.extra).toEqual({ poolScore: -5 })
  })
})
