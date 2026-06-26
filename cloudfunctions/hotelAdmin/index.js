// 酒店图片管理云函数 — 管理员手机端管理房型/菜品/文章的图片
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()

// 允许管理的集合白名单
const ALLOWED_COLLECTIONS = {
  roomTypes: 'hotel_room_types',
  foods: 'hotel_foods',
  articles: 'hotel_articles'
}

// 各集合的显示字段映射
const DISPLAY_FIELDS = {
  hotel_room_types: { name: 'name', photo: 'photo', photo_s: 'photo_s' },
  hotel_foods: { name: 'title', photo: 'photo', photo_s: null },
  hotel_articles: { name: 'title', photo: 'photo', photo_s: null }
}

// 列出指定集合的所有记录（最多 50 条）
async function list(event) {
  const { collection } = event
  const colName = ALLOWED_COLLECTIONS[collection]
  if (!colName) {
    return { code: -1, message: '无效的集合名: ' + collection }
  }

  try {
    const MAX_LIMIT = 50
    const countResult = await db.collection(colName).count()
    const total = countResult.total
    const batchTimes = Math.ceil(total / MAX_LIMIT)

    // 分批获取（支持超过 20 条的集合）
    const tasks = []
    for (let i = 0; i < batchTimes; i++) {
      tasks.push(db.collection(colName).skip(i * MAX_LIMIT).limit(MAX_LIMIT).get())
    }
    const results = (await Promise.all(tasks)).reduce((acc, cur) => acc.concat(cur.data), [])

    return {
      code: 0,
      data: {
        collection: colName,
        fields: DISPLAY_FIELDS[colName],
        list: results,
        total: results.length
      }
    }
  } catch (e) {
    return { code: -1, message: '查询失败: ' + e.message }
  }
}

// 更新指定记录的照片字段
async function updatePhoto(event) {
  const { collection, docId, photo, photo_s } = event
  const colName = ALLOWED_COLLECTIONS[collection]
  if (!colName) {
    return { code: -1, message: '无效的集合名: ' + collection }
  }
  if (!docId) {
    return { code: -1, message: '缺少 docId' }
  }
  if (!photo) {
    return { code: -1, message: '缺少 photo fileID' }
  }

  try {
    const updateData = { photo: photo, updatedAt: new Date() }
    if (photo_s !== undefined && photo_s !== null) {
      updateData.photo_s = photo_s
    }

    await db.collection(colName).doc(docId).update({ data: updateData })

    return { code: 0, message: '更新成功' }
  } catch (e) {
    return { code: -1, message: '更新失败: ' + e.message }
  }
}

// ====================== 路由 ======================
const handlers = { list, updatePhoto }

exports.main = async (event, context) => {
  const action = event.action || ''
  const handler = handlers[action]
  if (!handler) {
    return { code: -1, message: '未知操作: ' + action }
  }
  return await handler(event)
}
