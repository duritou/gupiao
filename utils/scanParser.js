// 扫码解析 — 从扫码结果中提取轮胎规格信息
// 支持三种策略：JSON格式 → 分隔符文本 → 兜底备注

/**
 * 解析扫码结果，尝试提取轮胎信息
 * @param {string} codeResult - wx.scanCode 返回的码内容
 * @returns {{ size:string, pattern:string, ply:string, brand:string, price:string, note:string }}
 */
function parseScanCode(codeResult) {
  if (!codeResult || typeof codeResult !== 'string') {
    return _fallback(codeResult)
  }

  const trimmed = codeResult.trim()

  // URL 格式：客户端无法跨域 fetch HTML，返回空交给云函数处理
  if (/^https?:\/\//i.test(trimmed)) {
    return { size: '', pattern: '', ply: '', brand: '朝阳', price: '', note: 'URL需云函数解析' }
  }

  // 策略1: 尝试 JSON 格式
  try {
    const obj = JSON.parse(trimmed)
    if (obj && typeof obj === 'object') {
      return {
        size: obj.size || obj.spec || obj.guige || '',
        pattern: obj.pattern || obj.hua || obj.huawen || '',
        ply: obj.ply || obj.cengji || obj.load || '',
        brand: obj.brand || obj.pinpai || '朝阳',
        price: obj.price || obj.jiage || obj.unitPrice || '',
        note: ''
      }
    }
  } catch (_) { /* 不是 JSON，继续尝试 */ }

  // 策略1.5: URL 参数格式 (BRAND=xxx&SPEC=205/55R16&PATTERN=SA37&PLY=4PR&LOAD=91V)
  if (/[&=]/.test(trimmed) && !/\s/.test(trimmed)) {
    const params = parseUrlParams(trimmed)
    if (Object.keys(params).length > 0) {
      const brand = params.BRAND || params.PP || params.brand || ''
      const spec = params.SPEC || params.GG || params.spec || ''
      const pattern = params.PATTERN || params.HW || params.pattern || ''
      const ply = params.PLY || params.CJ || params.ply || ''
      const loadIndex = params.LOAD || params.FH || params.loadIndex || params.load || ''
      if (spec || pattern || brand) {
        return { size: spec, pattern, ply, brand: brand || '朝阳', price: '', note: '' }
      }
    }
  }

  // 策略2: 分隔符拆分 + 模式匹配
  // 匹配常见规格：如 12R22.5, 295/80R22.5, 11.00R20
  const sizePattern = /(\d{2,3}(?:\.\d{2})?[\/R]\d{2,3}(?:\.\d)?(?:R\d{2,3})?)/i
  const pricePattern = /(\d{3,4})(?:元|$)/

  const parts = trimmed.split(/[\s,，_、]+/).filter(Boolean)

  let size = '', pattern = '', brand = '朝阳', price = '', ply = ''

  // 遍历拆分片段进行匹配
  for (const part of parts) {
    if (!size && sizePattern.test(part)) {
      size = part.match(sizePattern)[0]
    } else if (!price && pricePattern.test(part)) {
      const pm = part.match(pricePattern)
      price = pm ? pm[1] : ''
    } else if (/^[一-龥]{2,4}$/.test(part) && brand === '朝阳') {
      // 可能是品牌名（2-4个汉字）
      brand = part
    } else if (/\d+PR/i.test(part) || /\d+层/.test(part)) {
      ply = part
    } else if (!pattern && !/^\d+$/.test(part) && part.length >= 2 && part.length <= 10) {
      // 剩余片段作为花纹
      pattern = part
    }
  }

  // 如果提取到了规格或花纹，认为解析成功
  if (size || pattern) {
    return { size, pattern, ply, brand, price, note: '' }
  }

  // 策略3: 兜底 — 整个码内容放入备注
  return _fallback(trimmed)
}

/**
 * 解析 URL 参数格式字符串（& 或换行分隔）
 * @param {string} str - 如 "BRAND=朝阳&SPEC=205/55R16&PATTERN=SA37"
 * @returns {object}
 */
function parseUrlParams(str) {
  const params = {}
  const pairs = str.split(/[&\n]+/)
  for (const pair of pairs) {
    const eqIdx = pair.indexOf('=')
    if (eqIdx === -1) continue
    const key = decodeURIComponent(pair.substring(0, eqIdx).trim())
    const val = decodeURIComponent(pair.substring(eqIdx + 1).trim())
    if (key && val) params[key] = val
  }
  return params
}

function _fallback(text) {
  return { size: '', pattern: '', ply: '', brand: '朝阳', price: '', note: text || '' }
}

module.exports = { parseScanCode, parseUrlParams }
