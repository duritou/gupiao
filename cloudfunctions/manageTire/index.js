// 轮胎品类增删改查 — 自动去重 size+pattern，支持品牌级联 + 负荷指数
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()

exports.main = async (event) => {
  const { action, id, data, brandId } = event

  try {
    switch (action) {
      case 'list':
        const listRes = await db.collection('tires')
          .orderBy('_id', 'desc')
          .limit(20)
          .get()
        return { ok: true, list: listRes.data }

      case 'getByBrand':
        // 按品牌ID过滤规格列表
        if (!brandId) return { ok: false, message: '缺少 brandId' }
        const brandRes = await db.collection('tires')
          .where({ brandId })
          .orderBy('pattern', 'asc')
          .get()
        return { ok: true, list: brandRes.data }

      case 'search':
        const { size, pattern } = event
        const searchRes = await db.collection('tires')
          .where({ size: size || '', pattern: pattern || '' })
          .get()
        return { ok: true, tire: searchRes.data.length > 0 ? searchRes.data[0] : null }

      case 'add':
        if (!data || !data.size || !data.pattern) {
          return { ok: false, message: '缺少规格或花纹' }
        }
        const dupRes = await db.collection('tires')
          .where({ size: data.size, pattern: data.pattern })
          .get()
        if (dupRes.data.length > 0) {
          return { ok: true, _id: dupRes.data[0]._id, existed: true }
        }
        const addRes = await db.collection('tires').add({
          data: {
            size: data.size,
            pattern: data.pattern,
            ply: data.ply || '',
            loadIndex: data.loadIndex || '',
            brand: data.brand || '朝阳',
            brandId: data.brandId || '',
            createdAt: Date.now()
          }
        })
        return { ok: true, _id: addRes._id, existed: false }

      case 'update':
        if (!id) return { ok: false, message: '缺少 id' }
        await db.collection('tires').doc(id).update({ data: { ...data, updatedAt: Date.now() } })
        return { ok: true }

      case 'delete':
        if (!id) return { ok: false, message: '缺少 id' }
        const pRes = await db.collection('purchase').where({ tireId: id }).get()
        const pCount = pRes.data.filter(r => !r.isDeleted).length
        const sRes = await db.collection('sales').where({ tireId: id }).get()
        const sCount = sRes.data.filter(r => !r.isDeleted).length
        if (pCount > 0 || sCount > 0) {
          return { ok: false, message: `该轮胎有 ${pCount} 条进货记录和 ${sCount} 条出库记录，无法删除` }
        }
        await db.collection('tires').doc(id).remove()
        return { ok: true }

      default:
        return { ok: false, message: '未知操作: ' + action }
    }
  } catch (e) {
    return { ok: false, message: e.message }
  }
}
