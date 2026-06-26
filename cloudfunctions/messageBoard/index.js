/**
 * messageBoard — 留言板云函数
 * 支持 action: add | list | delete
 * 所有留言存在 app_messages 集合，云函数拥有完整读写权限，避免客户端权限问题
 */
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()

/**
 * 确保集合存在，不存在则自动创建（云函数拥有完整权限，可建集合）
 * 创建成功或已存在均正常返回；其他错误抛出
 */
async function ensureCollection(name) {
  try {
    await db.createCollection(name)
    console.log('[messageBoard] 已创建集合:', name)
  } catch (e) {
    // -502001 / -501001 都表示集合已存在，忽略；其他错误抛出
    if (e.errCode !== -502001 && e.errCode !== -501001) {
      console.error('[messageBoard] 创建集合失败:', name, e)
      throw e
    }
  }
}

exports.main = async (event, context) => {
  // 每个请求先确保集合存在（首次调用自动建集合，后续调用无额外开销）
  await ensureCollection('app_messages')
  const wxContext = cloud.getWXContext()
  const openId = wxContext.OPENID
  const { action } = event

  if (!openId) {
    return { ok: false, message: '未获取到用户身份' }
  }

  try {
    switch (action) {

      // ========== 添加留言 ==========
      case 'add': {
        const { localId, nickName, avatarUrl, content } = event
        if (!content || !content.trim()) {
          return { ok: false, message: '留言内容不能为空' }
        }
        if (content.length > 500) {
          return { ok: false, message: '留言不能超过500字' }
        }
        const data = {
          localId: localId || '',        // 客户端生成的 ID，用于去重
          openId: openId,
          nickName: nickName || '匿名用户',
          avatarUrl: avatarUrl || '',
          content: content.trim(),
          createTime: new Date()
        }
        const res = await db.collection('app_messages').add({ data })
        return {
          ok: true,
          message: '留言成功',
          cloudId: res._id,
          localId: data.localId
        }
      }

      // ========== 拉取留言列表 ==========
      case 'list': {
        // 不用 orderBy（需要建索引才能用），拉取后 JS 排序取最近 100 条
        const res = await db.collection('app_messages')
          .limit(500)
          .get()
        // JS 侧按 createTime 倒序排列，取前 100 条
        var sorted = (res.data || []).sort(function (a, b) {
          var ta = a.createTime ? new Date(a.createTime).getTime() : 0
          var tb = b.createTime ? new Date(b.createTime).getTime() : 0
          return tb - ta
        })
        var recent = sorted.slice(0, 100)
        // 返回时带上 cloud _id 和 localId，客户端用 localId 去重
        const messages = recent.map(function (item) {
          return {
            cloudId: item._id,
            localId: item.localId || '',
            nickName: item.nickName || '匿名用户',
            avatarUrl: item.avatarUrl || '',
            content: item.content || '',
            createTime: item.createTime
          }
        })
        return { ok: true, messages }
      }

      // ========== 删除留言（仅创建者） ==========
      case 'delete': {
        const { localId } = event
        if (!localId) {
          return { ok: false, message: '缺少留言标识' }
        }
        // 查找该 localId 对应且属于当前用户的留言
        const res = await db.collection('app_messages')
          .where({ localId, openId })
          .get()
        if (res.data.length === 0) {
          return { ok: false, message: '留言不存在或无权删除' }
        }
        // 删除匹配的所有文档（理论上只有一条）
        const delPromises = res.data.map(doc =>
          db.collection('app_messages').doc(doc._id).remove()
        )
        await Promise.all(delPromises)
        return { ok: true, message: '已删除', deletedCount: delPromises.length }
      }

      default:
        return { ok: false, message: '未知操作: ' + action }
    }
  } catch (e) {
    console.error('[messageBoard] 操作失败:', action, e)
    return { ok: false, message: '服务异常: ' + (e.message || '未知错误') }
  }
}
