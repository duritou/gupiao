/**
 * getMjHistory — 获取麻将计分结算历史
 * 权限：仅返回当前用户参与过的房间的结算记录（memberOpenIds 包含查询）
 *
 * 【重要】需要在微信云开发控制台为 mj_settlements 集合创建复合索引：
 *   索引字段：memberOpenIds(升序) + settleTime(降序)
 *   否则 .where({ memberOpenIds }).orderBy('settleTime', 'desc') 会报错
 *   云函数报错时会自动降级到本地 storage 缓存
 */
const cloud = require('wx-server-sdk')
cloud.init()
const db = cloud.database()

/** 确保集合存在（不存在则创建，已存在则跳过） */
async function ensureCollection(name) {
  try {
    await db.createCollection(name)
  } catch (e) {
    var msg = (e.errMsg || e.message || e.errCode || '')
    if (msg.indexOf('ResourceUnavailable.ResourceExist') > -1) return
    throw e
  }
}

exports.main = async (event, context) => {
  const wxContext = cloud.getWXContext()
  const openId = wxContext.OPENID

  try {
    // 确保集合存在
    await ensureCollection('mj_settlements')

    // 查询 memberOpenIds 数组包含当前用户的结算记录
    // 按结算时间倒序，最多返回 50 条
    // 需要复合索引：(memberOpenIds, settleTime desc)
    const res = await db.collection('mj_settlements')
      .where({
        memberOpenIds: openId
      })
      .orderBy('settleTime', 'desc')
      .limit(50)
      .get()

    return {
      ok: true,
      history: res.data
    }
  } catch (e) {
    console.error('[getMjHistory] 查询失败:', e)
    return { ok: false, message: '查询失败: ' + (e.message || '服务异常'), history: [] }
  }
}
