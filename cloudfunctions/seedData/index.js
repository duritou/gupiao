// 数据库种子数据 — 幂等插入品牌 + 轮胎规格 + 供应商
// 所有 10 个品牌各含至少 2 条规格，逐条去重可重复执行
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()

// 预置品牌（10个国内外主流轮胎品牌）
const SEED_BRANDS = [
  { name: '朝阳轮胎' },
  { name: '正新轮胎' },
  { name: '佳通轮胎' },
  { name: '玲珑轮胎' },
  { name: '米其林 Michelin' },
  { name: '普利司通 Bridgestone' },
  { name: '固特异 Goodyear' },
  { name: '马牌 Continental' },
  { name: '邓禄普 Dunlop' },
  { name: '倍耐力 Pirelli' }
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

// 供应商由用户自行添加，预置两个常用
const SEED_SUPPLIERS = [
  { name: '朝阳轮胎工厂', phone: '', note: '默认供应商' },
  { name: '本地轮胎批发', phone: '', note: '' }
]

exports.main = async () => {
  const result = {
    brandsInserted: 0, brandsSkipped: 0,
    tiresInserted: 0, tiresSkipped: 0,
    suppliersInserted: 0, suppliersSkipped: 0,
    errors: []
  }

  // ---- 插入品牌（去重 key: name） ----
  for (const b of SEED_BRANDS) {
    try {
      const exist = await db.collection('brands').where({ name: b.name }).count()
      if (exist.total > 0) { result.brandsSkipped++; continue }
      await db.collection('brands').add({ data: { ...b, createdAt: Date.now() } })
      result.brandsInserted++
    } catch (e) {
      result.errors.push(`brand ${b.name}: ${e.message}`)
    }
  }

  // 构建 brand name → _id 映射（通用化，不再硬编码单个品牌）
  const brandMap = {}
  for (const b of SEED_BRANDS) {
    try {
      const res = await db.collection('brands').where({ name: b.name }).get()
      if (res.data.length > 0) brandMap[b.name] = res.data[0]._id
    } catch (e) {
      result.errors.push(`获取品牌 ${b.name} ID 失败: ${e.message}`)
    }
  }
  // 确保朝阳轮胎 brandId 有效（核心品牌，不允许缺失）
  if (!brandMap['朝阳轮胎']) {
    try {
      const retry = await db.collection('brands').where({ name: '朝阳轮胎' }).get()
      if (retry.data.length > 0) {
        brandMap['朝阳轮胎'] = retry.data[0]._id
        console.log('seedData: 补充获取朝阳轮胎 brandId:', brandMap['朝阳轮胎'])
      } else {
        result.errors.push('朝阳轮胎品牌不存在于 brands 集合')
      }
    } catch (e) {
      result.errors.push('朝阳轮胎 brandId 重试失败: ' + e.message)
    }
  }

  // ---- 插入轮胎规格（去重 key: size + pattern） ----
  for (const t of SEED_TIRE_SPECS) {
    try {
      const exist = await db.collection('tires')
        .where({ size: t.size, pattern: t.pattern }).count()
      if (exist.total > 0) { result.tiresSkipped++; continue }
      await db.collection('tires').add({
        data: {
          size: t.size,
          pattern: t.pattern,
          ply: t.ply,
          loadIndex: t.loadIndex,
          brand: t.brand,
          brandId: brandMap[t.brand] || '',
          createdAt: Date.now()
        }
      })
      result.tiresInserted++
    } catch (e) {
      result.errors.push(`tire ${t.brand} ${t.size} ${t.pattern}: ${e.message}`)
    }
  }

  // ---- 修复朝阳轮胎 brandId 为空的存量记录（brandMap 失败导致的历史脏数据） ----
  if (brandMap['朝阳轮胎']) {
    try {
      const fixRes = await db.collection('tires')
        .where({ brand: '朝阳轮胎', brandId: '' })
        .update({ data: { brandId: brandMap['朝阳轮胎'] } })
      if (fixRes.stats.updated > 0) {
        console.log(`seedData: 修复朝阳轮胎 brandId 空值, 更新 ${fixRes.stats.updated} 条`)
        result._fixedBrandIds = fixRes.stats.updated
      }
    } catch (e) {
      result.errors.push(`修复朝阳轮胎 brandId 空值失败: ${e.message}`)
    }
  }

  // ---- 插入供应商 ----
  for (const s of SEED_SUPPLIERS) {
    try {
      const exist = await db.collection('suppliers').where({ name: s.name }).count()
      if (exist.total > 0) { result.suppliersSkipped++; continue }
      await db.collection('suppliers').add({ data: { ...s, createdAt: Date.now() } })
      result.suppliersInserted++
    } catch (e) {
      result.errors.push(`supplier ${s.name}: ${e.message}`)
    }
  }

  return {
    ok: true,
    message: `初始化完成：品牌 +${result.brandsInserted}(跳${result.brandsSkipped})，规格 +${result.tiresInserted}(跳${result.tiresSkipped})，供应商 +${result.suppliersInserted}(跳${result.suppliersSkipped})`,
    ...result
  }
}
