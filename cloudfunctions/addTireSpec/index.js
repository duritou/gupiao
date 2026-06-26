// 新增轮胎规格 — 写入 tires 集合，自动去重
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()

exports.main = async (event) => {
  const { size, pattern, ply, loadIndex, brand, brandId } = event

  if (!size || !pattern) return { ok: false, message: '缺少规格(size)或花纹(pattern)' }

  try {
    // 去重：同规格+花纹视为重复
    const dup = await db.collection('tires').where({ size, pattern }).get()
    if (dup.data.length > 0) {
      console.log(`addTireSpec: ${pattern} ${size} 已存在, _id=${dup.data[0]._id}`)
      return { ok: true, _id: dup.data[0]._id, existed: true }
    }

    const res = await db.collection('tires').add({
      data: {
        size,
        pattern,
        ply: ply || '',
        loadIndex: loadIndex || '',
        brand: brand || '',
        brandId: brandId || '',
        createdAt: Date.now()
      }
    })
    console.log(`addTireSpec: ${pattern} ${size} 新增成功, _id=${res._id}`)
    return { ok: true, _id: res._id, existed: false }
  } catch (e) {
    console.error('addTireSpec error:', e)
    return { ok: false, message: e.message }
  }
}
