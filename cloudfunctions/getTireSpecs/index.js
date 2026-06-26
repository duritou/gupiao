// 查询轮胎规格 — 按品牌ID / 品牌名称 / 规格+花纹精确搜索
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()

exports.main = async (event) => {
  const { brandId, brand, action, size, pattern } = event

  try {
    // 精确搜索模式（手动输入规格+花纹时自动匹配）
    if (action === 'search') {
      if (!size || !pattern) return { ok: false, message: '缺少规格或花纹' }
      const res = await db.collection('tires').where({ size, pattern }).get()
      console.log(`getTireSpecs search: ${size} ${pattern}, found=${res.data.length}`)
      return { ok: true, tire: res.data.length > 0 ? res.data[0] : null }
    }

    // 按 brandId 或 brand 名称查询（brandId 优先，brand 作为兜底）
    const query = brandId ? { brandId } : brand ? { brand } : null
    if (!query) return { ok: false, message: '缺少 brandId 或 brand' }

    const res = await db.collection('tires')
      .where(query)
      .orderBy('pattern', 'asc')
      .get()
    console.log(`getTireSpecs: query=${JSON.stringify(query)}, count=${res.data.length}`)
    return { ok: true, list: res.data }
  } catch (e) {
    console.error('getTireSpecs error:', e)
    return { ok: false, message: e.message }
  }
}
