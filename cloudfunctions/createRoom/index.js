// 云函数：创建游戏房间（支持打牌计分 / 麻将计分）
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()

// 确保集合存在（不存在则创建，已存在则跳过）
async function ensureCollection(name) {
  try {
    await db.createCollection(name)
  } catch (e) {
    // ResourceUnavailable.ResourceExist → 集合已存在，正常跳过
    // SDK 错误信息可能在 errMsg、message 或 errCode 中
    const msg = (e.errMsg || e.message || e.errCode || '')
    if (msg.indexOf('ResourceUnavailable.ResourceExist') > -1) {
      return
    }
    throw e
  }
}

// 生成6位不重复房间号（_id 即房间号，用 doc(code).get() 避免复合索引要求）
async function generateRoomCode() {
  const MAX_RETRY = 10
  for (let i = 0; i < MAX_RETRY; i++) {
    const code = String(Math.floor(100000 + Math.random() * 900000))
    try {
      await db.collection('rooms').doc(code).get()
      // 文档存在说明房间号已被占用，继续尝试
    } catch (e) {
      // doc 不存在 → 房间号可用
      return code
    }
  }
  throw new Error('生成房间号失败，请重试')
}

exports.main = async (event) => {
  const wxContext = cloud.getWXContext()
  const openId = wxContext.OPENID

  const { nickName, avatarUrl, gameType } = event
  const effectiveGameType = gameType || 'walk_scoring'

  if (!openId) return { ok: false, message: '未获取到用户身份' }
  if (!nickName) return { ok: false, message: '昵称不能为空' }

  try {
    const roomCode = await generateRoomCode()
    const now = Date.now()

    // 确保集合存在（云开发不会自动建集合，需显式检查创建）
    await ensureCollection('rooms')
    await ensureCollection('room_players')
    await ensureCollection('score_records')

    // 以 _id = roomCode 写入房间文档（与现有 Texas 模式一致，doc 查询无需索引）
    await db.collection('rooms').doc(roomCode).set({
      data: {
        gameType: effectiveGameType,
        creatorOpenId: openId,
        players: [openId],
        fractionMode: null,
        fractionAmount: 0,
        fractionTakenBy: [],
        createTime: now,
        updateTime: now
      }
    })

    // 写入玩家信息（roomId 就是 roomCode，baseScore：打牌 100，麻将 0）
    await db.collection('room_players').add({
      data: {
        roomId: roomCode,
        roomCode: roomCode,
        openId: openId,
        nickName: nickName,
        avatarUrl: avatarUrl || '',
        baseScore: effectiveGameType === 'mahjong_scoring' ? 0 : 100,
        joinTime: now
      }
    })

    return {
      ok: true,
      roomId: roomCode,
      roomCode: roomCode
    }
  } catch (e) {
    return { ok: false, message: e.message || '创建房间失败' }
  }
}
