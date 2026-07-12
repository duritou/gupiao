// 领域类型定义（JSDoc，供 IDE 提示与未来 TS 迁移铺路）
// 纯类型声明文件，无运行时代码

/**
 * @typedef {Object} ScoreRecord 计分流水（score_records 集合）
 * @property {string} roomId       房间号（= rooms._id）
 * @property {string} roomCode     房间号冗余字段
 * @property {string} openId       操作者 openId
 * @property {string} playerOpenId 分数归属玩家 openId（base/up/down）
 * @property {string} playerNickName 归属玩家昵称
 * @property {string} type         base | up | down | mj_round
 * @property {number} score        分值（base/up/down 用）
 * @property {string} [fractionMode] 取分模式标记（takeFromPool 写入的 down 记录带 all/half/third）
 * @property {number} createTime   创建时间戳
 * @property {PlayerDelta[]} [playerDeltas] 麻将一局多人净变化（仅 mj_round）
 */

/**
 * @typedef {Object} PlayerDelta 麻将单局某玩家净变化
 * @property {string} openId
 * @property {number} delta
 */

/**
 * @typedef {Object} Player 房间玩家（room_players 集合原始字段）
 * @property {string} openId
 * @property {string} nickName
 * @property {string} avatarUrl
 * @property {number} [baseScore]
 * @property {number} joinTime
 */

/**
 * @typedef {Object} PlayerView 玩家视图（含计算字段，供前端展示）
 * @property {string} openId
 * @property {string} nickName
 * @property {string} avatarUrl
 * @property {number} joinTime
 * @property {number} baseScore 底分
 * @property {number} netScore  净分 = baseScore + 累计净变化
 */

/**
 * @typedef {Object} Room 房间（rooms 集合，_id = roomCode）
 * @property {string} creatorOpenId
 * @property {string} gameType        walk_scoring | mahjong_scoring
 * @property {string[]} [players]     成员 openId 列表
 * @property {string|null} [fractionMode] 当前平分锁定模式 all/half/third
 * @property {number} [fractionAmount] 锁定的单次取分金额
 * @property {string[]} [fractionTakenBy] 本轮已取分玩家 openId
 * @property {number} createTime
 * @property {number} updateTime
 */

module.exports = {}
