// 统一错误码（前端按 code 判断，不再 includes 中文 message）
// M1 阶段策略：云函数返回 { ok, code, message }，message 保留向后兼容（前端暂不改），M2 再切前端 code 判断

// 错误码常量
const ERR = {
  // 通用 / 身份 / 参数
  ERR_UNAUTHORIZED: 'ERR_UNAUTHORIZED',     // 未获取到用户身份
  ERR_PARAM_INVALID: 'ERR_PARAM_INVALID',   // 参数非法（roomCode 缺失等）

  // 房间 / 玩家
  ERR_ROOM_NOT_FOUND: 'ERR_ROOM_NOT_FOUND',         // 房间不存在
  ERR_ROOM_TYPE_MISMATCH: 'ERR_ROOM_TYPE_MISMATCH', // 房间类型不匹配
  ERR_NOT_IN_ROOM: 'ERR_NOT_IN_ROOM',               // 操作者不在房间
  ERR_INVALID_PLAYER: 'ERR_INVALID_PLAYER',         // 目标玩家不在房间

  // 计分业务
  ERR_SCORE_INVALID: 'ERR_SCORE_INVALID',     // 分数必须为正整数
  ERR_TYPE_INVALID: 'ERR_TYPE_INVALID',       // 操作类型非法（非 up/down）
  ERR_MODE_INVALID: 'ERR_MODE_INVALID',       // 取分模式非法（非 all/half/third）
  ERR_POOL_NOT_ENOUGH: 'ERR_POOL_NOT_ENOUGH', // 公共池余额不足
  ERR_POOL_EMPTY: 'ERR_POOL_EMPTY',           // 公共池无可取分数
  ERR_FRACTION_LOCKED: 'ERR_FRACTION_LOCKED', // 平分模式已锁定，不可切换
  ERR_VERIFY_FAILED: 'ERR_VERIFY_FAILED',     // 守恒校验失败

  // M2 预留（幂等 / CAS）
  ERR_DUPLICATE_REQUEST: 'ERR_DUPLICATE_REQUEST', // 幂等：重复请求
  ERR_VERSION_CONFLICT: 'ERR_VERSION_CONFLICT'    // CAS：版本冲突
}

// 错误码默认文案（云函数可传自定义 message 覆盖）
const DEFAULT_MESSAGES = {
  [ERR.ERR_UNAUTHORIZED]: '未获取到用户身份',
  [ERR.ERR_PARAM_INVALID]: '参数非法',
  [ERR.ERR_ROOM_NOT_FOUND]: '房间不存在',
  [ERR.ERR_ROOM_TYPE_MISMATCH]: '房间类型不匹配',
  [ERR.ERR_NOT_IN_ROOM]: '你不在该房间中',
  [ERR.ERR_INVALID_PLAYER]: '目标玩家不在该房间中',
  [ERR.ERR_SCORE_INVALID]: '分数必须为正整数',
  [ERR.ERR_TYPE_INVALID]: '操作类型无效，必须是 up（上分）或 down（取分）',
  [ERR.ERR_MODE_INVALID]: '取分模式无效，必须是 all/half/third',
  [ERR.ERR_POOL_NOT_ENOUGH]: '公共池余额不足',
  [ERR.ERR_POOL_EMPTY]: '公共池没有可取的分数',
  [ERR.ERR_FRACTION_LOCKED]: '当前分数模式已锁定，不可切换',
  [ERR.ERR_VERIFY_FAILED]: '数据守恒校验失败',
  [ERR.ERR_DUPLICATE_REQUEST]: '重复请求',
  [ERR.ERR_VERSION_CONFLICT]: '数据版本冲突，请重试'
}

// 标准化错误返回体
// 用法：return makeError(ERR.ERR_POOL_NOT_ENOUGH)                       → 用默认文案
//      return makeError(ERR.ERR_POOL_NOT_ENOUGH, `公共池仅剩${x}分`)    → 覆盖文案
function makeError(code, message, extra) {
  const body = { ok: false, code, message: message || DEFAULT_MESSAGES[code] || code }
  if (extra) body.extra = extra
  return body
}

module.exports = { ERR, DEFAULT_MESSAGES, makeError }
