// 领域核心统一出口（Domain Core）
// 纯函数 + 常量 + 类型，零 wx-server-sdk 依赖，可跨端复用（云函数 / 云托管 / Node）
// 云函数引入：const { calcPoolScore, ERR, validateScoreInput } = require('common')

const constants = require('./constants')
const errors = require('./errors')
const calculator = require('./calculator')
const validator = require('./validator')

module.exports = {
  ...constants,
  ...calculator,
  ...validator,
  ERR: errors.ERR,
  DEFAULT_MESSAGES: errors.DEFAULT_MESSAGES,
  makeError: errors.makeError
}
