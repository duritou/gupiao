// 客户端数据库初始化 — 当云函数未部署时，直接写库插入种子数据
// 仅在 app.js onLaunch 中调用一次（通过 storage 标记防重复）
// 逐条去重，与 cloudfunctions/seedData/index.js 行为一致
const STORAGE_KEY = '__db_init_v7__'

// 种子数据（与 cloudfunctions/seedData/index.js 保持一致）
const SEED_BRANDS = [
  { name: '朝阳轮胎' }, { name: '正新轮胎' }, { name: '佳通轮胎' },
  { name: '玲珑轮胎' }, { name: '米其林 Michelin' }, { name: '普利司通 Bridgestone' },
  { name: '固特异 Goodyear' }, { name: '马牌 Continental' },
  { name: '邓禄普 Dunlop' }, { name: '倍耐力 Pirelli' }
]

// 预置规格 — 每条带 brand 字段，确保与品牌正确关联
const SEED_TIRE_SPECS = [
  // 朝阳轮胎（10条 — FAIL-8 精确指定）
  { brand:'朝阳轮胎', size:'205/55R16',   pattern:'SA37',  ply:'4PR',  loadIndex:'91V' },
  { brand:'朝阳轮胎', size:'215/55R17',   pattern:'SA37',  ply:'4PR',  loadIndex:'94V' },
  { brand:'朝阳轮胎', size:'195/65R15',   pattern:'RP18',  ply:'6PR',  loadIndex:'95H' },
  { brand:'朝阳轮胎', size:'205/55R16',   pattern:'RP18',  ply:'6PR',  loadIndex:'91H' },
  { brand:'朝阳轮胎', size:'185/60R14',   pattern:'RP26',  ply:'4PR',  loadIndex:'82H' },
  { brand:'朝阳轮胎', size:'195/60R15',   pattern:'RP26',  ply:'4PR',  loadIndex:'88H' },
  { brand:'朝阳轮胎', size:'225/45R18',   pattern:'SA57',  ply:'8PR',  loadIndex:'95W' },
  { brand:'朝阳轮胎', size:'235/40R19',   pattern:'SA57',  ply:'8PR',  loadIndex:'96Y' },
  { brand:'朝阳轮胎', size:'215/55R17',   pattern:'RP36',  ply:'6PR',  loadIndex:'98W' },
  { brand:'朝阳轮胎', size:'205/55R16',   pattern:'SA07',  ply:'4PR',  loadIndex:'91V' },
  // 正新轮胎（2条）
  { brand:'正新轮胎', size:'205/55R16',   pattern:'MA202',        ply:'4PR',  loadIndex:'91V' },
  { brand:'正新轮胎', size:'195/65R15',   pattern:'MD308',        ply:'6PR',  loadIndex:'95H' },
  // 佳通轮胎（2条）
  { brand:'佳通轮胎', size:'205/55R16',   pattern:'Comfort220',   ply:'4PR',  loadIndex:'91V' },
  { brand:'佳通轮胎', size:'225/65R17',   pattern:'SUV520',       ply:'6PR',  loadIndex:'102H' },
  // 玲珑轮胎（2条）
  { brand:'玲珑轮胎', size:'205/55R16',   pattern:'GreenMax',     ply:'4PR',  loadIndex:'91V' },
  { brand:'玲珑轮胎', size:'215/55R17',   pattern:'CrossWind',    ply:'6PR',  loadIndex:'98W' },
  // 米其林（2条）
  { brand:'米其林 Michelin', size:'205/55R16', pattern:'Primacy4',    ply:'4PR', loadIndex:'91W' },
  { brand:'米其林 Michelin', size:'225/45R17', pattern:'PilotSport4', ply:'6PR', loadIndex:'94Y' },
  // 普利司通（2条）
  { brand:'普利司通 Bridgestone', size:'205/55R16', pattern:'TuranzaT005',  ply:'4PR', loadIndex:'91V' },
  { brand:'普利司通 Bridgestone', size:'225/45R17', pattern:'PotenzaRE004', ply:'6PR', loadIndex:'94W' },
  // 固特异（2条）
  { brand:'固特异 Goodyear', size:'205/55R16', pattern:'EfficientGrip', ply:'4PR', loadIndex:'91V' },
  { brand:'固特异 Goodyear', size:'225/45R17', pattern:'EagleF1',      ply:'6PR', loadIndex:'94Y' },
  // 马牌（2条）
  { brand:'马牌 Continental', size:'205/55R16', pattern:'UltraContact',  ply:'4PR', loadIndex:'91V' },
  { brand:'马牌 Continental', size:'225/45R17', pattern:'SportContact7', ply:'6PR', loadIndex:'94Y' },
  // 邓禄普（2条）
  { brand:'邓禄普 Dunlop', size:'205/55R16', pattern:'SP2040',       ply:'4PR', loadIndex:'91V' },
  { brand:'邓禄普 Dunlop', size:'225/45R17', pattern:'DirezzaDZ102', ply:'6PR', loadIndex:'94W' },
  // 倍耐力（2条）
  { brand:'倍耐力 Pirelli', size:'205/55R16', pattern:'CinturatoP7', ply:'4PR', loadIndex:'91V' },
  { brand:'倍耐力 Pirelli', size:'225/45R17', pattern:'PZero',       ply:'6PR', loadIndex:'94Y' }
]

const SEED_SUPPLIERS = [
  { name: '朝阳轮胎工厂', phone: '', note: '默认供应商' },
  { name: '本地轮胎批发', phone: '', note: '' }
]

/**
 * 检查并初始化数据库种子数据
 * 优先尝试云函数 seedData，失败则直接写库
 * 逐条去重：已有品牌/规格/供应商不会重复插入
 * @param {{ force?: boolean }} opts - force=true 时忽略 storage 标记强制重跑
 */
async function initDatabase(opts = {}) {
  // 已初始化过则跳过（force 模式除外）
  if (!opts.force) {
    const done = wx.getStorageSync(STORAGE_KEY)
    if (done) return { skipped: true, message: '已初始化', _ts: done }
  }

  if (!wx.cloud) {
    console.warn('initData: 云开发未就绪，跳过数据库初始化')
    return { skipped: true, message: '云开发未就绪' }
  }

  // 先尝试云函数（已部署时走云函数）
  try {
    const cfRes = await wx.cloud.callFunction({ name: 'seedData' })
    if (cfRes.result && cfRes.result.ok) {
      wx.setStorageSync(STORAGE_KEY, Date.now())
      console.log('initData: 云函数 seedData 完成 —', cfRes.result.message)
      return cfRes.result
    }
  } catch (_) {
    console.log('initData: seedData 云函数未部署，改用直接写库')
  }

  // === 兜底：直接写库（逐条去重） ===
  const db = wx.cloud.database()
  const result = {
    brandsInserted: 0, brandsSkipped: 0,
    tiresInserted: 0, tiresSkipped: 0,
    suppliersInserted: 0, suppliersSkipped: 0,
    errors: []
  }

  try {
    // —— 品牌：逐条检查 name 是否已存在 ——
    for (const b of SEED_BRANDS) {
      try {
        const exist = await db.collection('brands').where({ name: b.name }).count()
        if (exist.total > 0) { result.brandsSkipped++; continue }
        await db.collection('brands').add({ data: { ...b, createdAt: Date.now() } })
        result.brandsInserted++
      } catch (e) { result.errors.push('brand ' + b.name + ': ' + e.message) }
    }

    // 构建 brand name → _id 映射（通用化，不再硬编码朝阳）
    const brandMap = {}
    for (const b of SEED_BRANDS) {
      try {
        const res = await db.collection('brands').where({ name: b.name }).get()
        if (res.data.length > 0) brandMap[b.name] = res.data[0]._id
      } catch (e) {
        result.errors.push('查询品牌 ' + b.name + ' ID失败: ' + e.message)
      }
    }
    // 确保朝阳轮胎 brandId 有效（核心品牌，不允许缺失）
    if (!brandMap['朝阳轮胎']) {
      try {
        const retry = await db.collection('brands').where({ name: '朝阳轮胎' }).get()
        if (retry.data.length > 0) {
          brandMap['朝阳轮胎'] = retry.data[0]._id
          console.log('initData: 补充获取朝阳轮胎 brandId:', brandMap['朝阳轮胎'])
        } else {
          result.errors.push('朝阳轮胎品牌不存在于 brands 集合')
        }
      } catch (e) {
        result.errors.push('朝阳轮胎 brandId 重试失败: ' + e.message)
      }
    }

    // —— 轮胎规格：逐条检查 size+pattern 是否已存在 ——
    for (const t of SEED_TIRE_SPECS) {
      try {
        const exist = await db.collection('tires').where({ size: t.size, pattern: t.pattern }).count()
        if (exist.total > 0) { result.tiresSkipped++; continue }
        await db.collection('tires').add({
          data: {
            size: t.size, pattern: t.pattern,
            ply: t.ply, loadIndex: t.loadIndex,
            brand: t.brand,
            brandId: brandMap[t.brand] || '',
            createdAt: Date.now()
          }
        })
        result.tiresInserted++
      } catch (e) { result.errors.push('tire ' + t.brand + ' ' + t.size + ' ' + t.pattern + ': ' + e.message) }
    }

    // —— 修复朝阳轮胎 brandId 为空的存量记录（brandMap 失败导致的历史脏数据） ——
    if (brandMap['朝阳轮胎']) {
      try {
        const fixRes = await db.collection('tires')
          .where({ brand: '朝阳轮胎', brandId: '' })
          .update({ data: { brandId: brandMap['朝阳轮胎'] } })
        if (fixRes.stats.updated > 0) {
          console.log('initData: 修复朝阳轮胎 brandId 空值, 更新 ' + fixRes.stats.updated + ' 条')
          result._fixedBrandIds = fixRes.stats.updated
        }
      } catch (e) {
        result.errors.push('修复朝阳轮胎 brandId 空值失败: ' + e.message)
      }
    }

    // —— 供应商：逐条检查 name 是否已存在 ——
    for (const s of SEED_SUPPLIERS) {
      try {
        const exist = await db.collection('suppliers').where({ name: s.name }).count()
        if (exist.total > 0) { result.suppliersSkipped++; continue }
        await db.collection('suppliers').add({ data: { ...s, createdAt: Date.now() } })
        result.suppliersInserted++
      } catch (e) { result.errors.push('supplier ' + s.name + ': ' + e.message) }
    }

    wx.setStorageSync(STORAGE_KEY, Date.now())
    console.log('initData: 直接写库完成 —', JSON.stringify(result))
  } catch (e) {
    console.error('initData: 直接写库失败 —', e)
    result.errors.push('初始化异常: ' + (e.message || JSON.stringify(e)))
  }

  return { ok: result.errors.length === 0, ...result }
}

module.exports = { initDatabase, STORAGE_KEY }
