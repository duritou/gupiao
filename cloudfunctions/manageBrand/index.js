// 品牌管理 — 增删改查
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()

exports.main = async (event) => {
  const { action, id, data } = event

  try {
    switch (action) {
      case 'list':
        const listRes = await db.collection('brands').orderBy('name', 'asc').get()
        return { ok: true, list: listRes.data }

      case 'add':
        if (!data || !data.name) return { ok: false, message: '缺少品牌名称' }
        // 去重检查
        const exist = await db.collection('brands').where({ name: data.name }).get()
        if (exist.data.length > 0) return { ok: false, message: '品牌已存在' }
        const addRes = await db.collection('brands').add({ data: { name: data.name, createdAt: Date.now() } })
        return { ok: true, _id: addRes._id }

      case 'update':
        if (!id) return { ok: false, message: '缺少 id' }
        await db.collection('brands').doc(id).update({ data: { ...data, updatedAt: Date.now() } })
        return { ok: true }

      case 'delete':
        if (!id) return { ok: false, message: '缺少 id' }
        // 检查是否有关联规格
        const tireCount = await db.collection('tires').where({ brandId: id }).count()
        if (tireCount.total > 0) {
          return { ok: false, message: `该品牌下有 ${tireCount.total} 条规格，无法删除` }
        }
        await db.collection('brands').doc(id).remove()
        return { ok: true }

      default:
        return { ok: false, message: '未知操作: ' + action }
    }
  } catch (e) {
    return { ok: false, message: e.message }
  }
}
