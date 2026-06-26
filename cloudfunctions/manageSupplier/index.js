// 供应商增删改查
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()

exports.main = async (event) => {
  const { action, id, data } = event

  try {
    switch (action) {
      case 'list':
        const listRes = await db.collection('suppliers').orderBy('name', 'asc').get()
        return { ok: true, list: listRes.data }

      case 'add':
        if (!data || !data.name) return { ok: false, message: '缺少供应商名称' }
        // 检查重复
        const existRes = await db.collection('suppliers').where({ name: data.name }).get()
        if (existRes.data.length > 0) return { ok: false, message: '供应商已存在' }
        const addRes = await db.collection('suppliers').add({ data: { ...data, createdAt: Date.now() } })
        return { ok: true, _id: addRes._id }

      case 'update':
        if (!id) return { ok: false, message: '缺少 id' }
        await db.collection('suppliers').doc(id).update({ data: { ...data, updatedAt: Date.now() } })
        return { ok: true }

      case 'delete':
        if (!id) return { ok: false, message: '缺少 id' }
        await db.collection('suppliers').doc(id).remove()
        return { ok: true }

      default:
        return { ok: false, message: '未知操作: ' + action }
    }
  } catch (e) {
    return { ok: false, message: e.message }
  }
}
