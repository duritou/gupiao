// 云函数：从公共池取分给玩家（取全部 / 取1/2 / 取1/3）
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()

// 全量拉取房间计分记录
// 云函数 db.get() 默认上限 100 条，记录超过会静默截断导致求和漏数据，必须分页累加
async function fetchAllScoreRecords(roomCode) {
  const PAGE_SIZE = 100
  let all = []
  let skip = 0
  while (true) {
    const res = await db.collection('score_records')
      .where({ roomId: roomCode })
      .orderBy('createTime', 'desc')
      .skip(skip)
      .limit(PAGE_SIZE)
      .get()
    all = all.concat(res.data)
    if (res.data.length < PAGE_SIZE) break
    skip += PAGE_SIZE
  }
  return all
}

exports.main = async (event) => {
  const wxContext = cloud.getWXContext()
  const openId = wxContext.OPENID

  const { roomCode, targetPlayerOpenId, mode } = event

  if (!openId) return { ok: false, message: '未获取到用户身份' }
  if (!roomCode) return { ok: false, message: '房间号不能为空' }
  if (!targetPlayerOpenId) return { ok: false, message: '未指定目标玩家' }
  if (!mode || (mode !== 'all' && mode !== 'half' && mode !== 'third')) {
    return { ok: false, message: '取分模式无效，必须是 all/half/third' }
  }

  console.log('[takeFromPool] 入参:', { roomCode, mode, targetPlayerOpenId, operatorOpenId: openId })

  try {
    // 验证房间存在
    const roomRes = await db.collection('rooms').doc(roomCode).get()
    const room = roomRes.data
    if (!room || room.gameType !== 'walk_scoring') {
      return { ok: false, message: '房间不存在' }
    }

    // 验证操作者在房间中
    const operatorRes = await db.collection('room_players')
      .where({ roomId: roomCode, openId: openId })
      .get()
    if (operatorRes.data.length === 0) {
      return { ok: false, message: '你不在该房间中' }
    }

    // 验证目标玩家在房间中
    const targetRes = await db.collection('room_players')
      .where({ roomId: roomCode, openId: targetPlayerOpenId })
      .get()
    if (targetRes.data.length === 0) {
      return { ok: false, message: '目标玩家不在该房间中' }
    }

    const targetPlayer = targetRes.data[0]

    // 计算当前公共池分数（从所有计分记录推算，分页全量拉取避免漏数据）
    const records = await fetchAllScoreRecords(roomCode)
    let poolScore = 0
    for (const r of records) {
      if (r.type === 'up') poolScore += r.score
      else if (r.type === 'down') poolScore -= r.score
      // base 类型不影响公共池
    }

    console.log('[takeFromPool] 当前公共池分数:', poolScore)

    if (poolScore <= 0) {
      return { ok: false, message: '公共池没有可取的分数' }
    }

    const now = Date.now()
    let takeAmount = 0
    let newFractionMode = room.fractionMode || null
    let newFractionAmount = room.fractionAmount || 0
    let takenBy = room.fractionTakenBy || []  // 已取分的玩家 openId 列表

    if (mode === 'all') {
      // 取全部：清空公共池，重置分数模式
      takeAmount = poolScore
      newFractionMode = null
      newFractionAmount = 0
      takenBy = []
    } else {
      // 取 1/2 或 1/3
      const currentFractionMode = room.fractionMode || null
      const currentFractionAmount = room.fractionAmount || 0
      const divisor = mode === 'half' ? 2 : 3

      if (currentFractionMode && currentFractionMode !== mode) {
        return {
          ok: false,
          message: `当前已是${currentFractionMode === 'half' ? '1/2' : '1/3'}模式，无法切换为${mode === 'half' ? '1/2' : '1/3'}模式。请先取全部清空公共池`
        }
      }

      if (currentFractionMode === mode) {
        // 分数模式已锁定，使用已锁定的金额
        takeAmount = currentFractionAmount
        console.log('[takeFromPool] 使用已锁定金额:', takeAmount)
      } else {
        // 首次触发：计算并锁定分数
        takeAmount = Math.floor(poolScore / divisor)
        console.log('[takeFromPool] 首次触发, poolScore:', poolScore, 'divisor:', divisor, 'takeAmount:', takeAmount)

        if (takeAmount <= 0) {
          return { ok: false, message: `公共池${poolScore}分不足以${mode === 'half' ? '对半' : '三等'}分配` }
        }

        newFractionMode = mode
        newFractionAmount = takeAmount
        takenBy = []  // 新的一轮，清空已取列表
      }

      // 校验公共池足够支付
      if (poolScore < takeAmount) {
        return { ok: false, message: `公共池仅剩${poolScore}分，不足以取出${takeAmount}分` }
      }

      // 记录取分玩家（去重）
      if (!takenBy.includes(targetPlayerOpenId)) {
        takenBy = takenBy.concat(targetPlayerOpenId)
      }

      // 取满人数 → 自动重置
      if (takenBy.length >= divisor) {
        console.log('[takeFromPool] 已满' + divisor + '人取分，自动重置模式')
        newFractionMode = null
        newFractionAmount = 0
        takenBy = []
        // 注意：takeAmount 仍使用已锁定的金额，最后一次取分有效
      }
    }

    // 写入计分记录
    const addRes = await db.collection('score_records').add({
      data: {
        roomId: roomCode,
        roomCode: roomCode,
        openId: openId,
        playerOpenId: targetPlayerOpenId,
        playerNickName: targetPlayer.nickName,
        type: 'down',
        score: takeAmount,
        fractionMode: mode,  // 记录取分模式，方便追溯
        createTime: now
      }
    })
    console.log('[takeFromPool] 写入记录 _id:', addRes._id, 'takeAmount:', takeAmount)

    // 更新房间状态
    await db.collection('rooms').doc(roomCode).update({
      data: {
        updateTime: now,
        fractionMode: newFractionMode,
        fractionAmount: newFractionAmount,
        fractionTakenBy: takenBy
      }
    })
    console.log('[takeFromPool] 房间分数模式更新:', {
      fractionMode: newFractionMode,
      fractionAmount: newFractionAmount,
      takenByCount: takenBy.length
    })

    const updatedPoolScore = poolScore - takeAmount

    return {
      ok: true,
      takeAmount: takeAmount,
      poolScore: updatedPoolScore,
      fractionMode: newFractionMode,
      fractionAmount: newFractionAmount,
      targetPlayerName: targetPlayer.nickName,
      remainder: newFractionMode ? (updatedPoolScore % newFractionAmount) : 0,
      takenBy: takenBy,
      takenCount: takenBy.length,
      // 前端可用此信息提示进度
      totalSlots: mode === 'all' ? 1 : (mode === 'half' ? 2 : 3)
    }
  } catch (e) {
    console.error('[takeFromPool] 异常:', e.message || e)
    return { ok: false, message: e.message || '取分失败' }
  }
}
