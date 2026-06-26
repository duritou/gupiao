// parseTireCode 云函数 — 扫码解析轮胎信息
// v3: 策略0 改为 API 逆向直调 news.zcckj.com 产品接口，无需 HTML 解析
// 策略1-4 不变，向后兼容非 URL 条码
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()
const axios = require('axios')

// ===== 常量 =====
const URL_PATTERN = /^https?:\/\//i
const BRAND_FIXED = '朝阳轮胎'
const WX_UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.38'

// 策略4 正则（旧条码兼容）
const SIZE_RE_OLD = /(\d{2,3}(?:\.\d{2})?[\/R]\d{2,3}(?:\.\d)?(?:R\d{2,3})?)/i
const PLY_RE = /(\d{1,2})\s*PR/i

// ============================== 主入口 ==============================

exports.main = async (event) => {
  const input = event.url || event.code || ''
  if (!input || typeof input !== 'string' || !input.trim()) {
    return { code: -1, msg: '扫码内容为空' }
  }
  const trimmed = input.trim()
  console.log('parseTireCode 输入:', trimmed.substring(0, 200))

  // ===== 策略0: URL → API 逆向直调 =====
  if (URL_PATTERN.test(trimmed)) {
    return await strategy0_apiReverse(trimmed)
  }

  // ===== 策略1: JSON 解析 =====
  try {
    const obj = JSON.parse(trimmed)
    if (obj && typeof obj === 'object') {
      const result = {
        brand: obj.brand || obj.pinpai || obj.BRAND || '',
        spec: obj.spec || obj.size || obj.guige || obj.SPEC || '',
        pattern: obj.pattern || obj.hua || obj.huawen || obj.PATTERN || '',
        ply: obj.ply || obj.cengji || obj.PLY || '',
        loadIndex: obj.loadIndex || obj.load || obj.LOAD || ''
      }
      if (result.spec || result.pattern || result.brand) {
        console.log('策略1 JSON解析成功:', JSON.stringify(result))
        return {
          code: 0,
          data: { brand: result.brand, size: result.spec, pattern: result.pattern, ply: result.ply, loadSpeed: result.loadIndex }
        }
      }
    }
  } catch (_) { /* 不是 JSON */ }

  // ===== 策略2: URL 参数格式 =====
  if (/[&=]/.test(trimmed) && !/\s/.test(trimmed)) {
    try {
      const params = parseUrlParams(trimmed)
      const result = {
        brand: params.BRAND || params.PP || params.brand || '',
        spec: params.SPEC || params.GG || params.spec || '',
        pattern: params.PATTERN || params.HW || params.pattern || '',
        ply: params.PLY || params.CJ || params.ply || '',
        loadIndex: params.LOAD || params.FH || params.loadIndex || params.load || ''
      }
      if (result.spec || result.pattern || result.brand) {
        console.log('策略2 URL参数解析成功:', JSON.stringify(result))
        return {
          code: 0,
          data: { brand: result.brand, size: result.spec, pattern: result.pattern, ply: result.ply, loadSpeed: result.loadIndex }
        }
      }
    } catch (e) { console.log('策略2 异常:', e.message) }
  }

  // ===== 策略3: 纯数字条码 → 查 barcode_map =====
  if (/^\d{8,}$/.test(trimmed)) {
    try {
      const mapRes = await db.collection('barcode_map').where({ code: trimmed }).get()
      if (mapRes.data && mapRes.data.length > 0) {
        const record = mapRes.data[0]
        console.log('策略3 barcode_map 命中:', trimmed, '→', JSON.stringify(record))
        return {
          code: 0,
          data: { brand: record.brand || '', size: record.spec || '', pattern: record.pattern || '', ply: record.ply || '', loadSpeed: record.loadIndex || '' }
        }
      }
    } catch (e) { console.log('策略3 异常:', e.message) }
  }

  // ===== 策略4: 正则兜底 =====
  const result = regexParse(trimmed)
  if (result.spec || result.pattern || result.brand) {
    console.log('策略4 正则兜底成功:', JSON.stringify(result))
    return {
      code: 0,
      data: { brand: result.brand, size: result.spec, pattern: result.pattern, ply: result.ply, loadSpeed: result.loadIndex }
    }
  }

  console.log('全部策略失败:', trimmed.substring(0, 100))
  return { code: -1, msg: '无法识别轮胎信息，请手动输入' }
}

// ============================================================
// 策略0: API 逆向直调 — news.zcckj.com 产品接口
// ============================================================

/**
 * 两步走：
 * ① GET 页面 → 获取阿里云WAF的 acw_tc cookie
 * ② GET /api/tire/scan/product/detail?barcode={serial} → 解析 JSON 轮胎数据
 */
async function strategy0_apiReverse(url) {
  console.log('策略0 API逆向 输入URL:', url)

  // 提取序列号
  const serial = extractSerialFromURL(url)
  if (!serial) {
    return { code: -1, msg: '无法从URL提取序列号' }
  }
  console.log('策略0 序列号:', serial)

  // Step 1: 获取 WAF cookie
  let acwTc = ''
  try {
    const pageResp = await axios.get('http://news.zcckj.com/h5/tires/goods', {
      params: { barcode: serial },
      headers: {
        'User-Agent': WX_UA,
        'Accept': 'text/html,application/xhtml+xml',
        'Referer': 'http://weixin.d.zcckj.com/'
      },
      timeout: 15000,
      maxRedirects: 0,
      validateStatus: function (status) { return status < 500 }  // 接受 2xx/3xx/4xx
    })
    acwTc = extractCookie(pageResp.headers, 'acw_tc')
    if (acwTc) console.log('策略0 WAF cookie获取成功')
  } catch (e) {
    // 即使请求失败，也可能有 Set-Cookie
    if (e.response) acwTc = extractCookie(e.response.headers, 'acw_tc')
    if (!acwTc) console.log('策略0 获取WAF cookie时出错:', e.message)
  }

  if (!acwTc) {
    console.log('策略0 未获取到WAF cookie，尝试无cookie直调')
  }

  // Step 2: 调用产品详情 API
  try {
    const apiHeaders = {
      'User-Agent': WX_UA,
      'Accept': 'application/json, text/plain, */*',
      'Referer': 'http://news.zcckj.com/h5/tires/goods?barcode=' + serial
    }
    if (acwTc) {
      apiHeaders['Cookie'] = 'acw_tc=' + acwTc
    }

    const apiResp = await axios.get('http://news.zcckj.com/api/tire/scan/product/detail', {
      params: { barcode: serial },
      headers: apiHeaders,
      timeout: 15000
    })

    const body = apiResp.data
    console.log('策略0 API响应 code:', body.code, 'success:', body.success)

    if (!body.success || !body.data) {
      return { code: -1, msg: '产品信息查询失败: ' + (body.message || '服务端返回空数据') }
    }

    // Step 3: 提取并标准化轮胎数据
    const result = normalizeFromApi(body.data, serial)
    if (result.size || result.pattern) {
      console.log('策略0 API逆向成功:', JSON.stringify(result))
      return { code: 0, data: result }
    }

    console.log('策略0 数据为空，title:', body.data.title)
    return { code: -1, msg: '无法从该轮胎提取信息' }
  } catch (e) {
    if (e.code === 'ECONNABORTED') {
      return { code: -3, msg: '请求超时，请重试' }
    }
    if (e.response) {
      return { code: -2, msg: 'HTTP错误: ' + e.response.status }
    }
    console.error('策略0 API调用异常:', e.message || e)
    return { code: -2, msg: '请求失败: ' + (e.message || String(e)) }
  }
}

/**
 * 从 API 响应 JSON 中提取标准化轮胎数据
 * 优先用 attrList 结构化字段，缺失时用 title 正则降级
 */
function normalizeFromApi(data, serial) {
  const result = {
    brand: data.brandName || BRAND_FIXED,
    size: '',
    pattern: '',
    ply: '',
    loadSpeed: '',
    price: data.marketPrice || 0,
    serialNo: serial
  }

  // 从 attrList 提取结构化属性
  if (data.attrList && Array.isArray(data.attrList)) {
    let loadIndex = '', speedLevel = ''
    for (const attr of data.attrList) {
      if (!attr.value) continue
      switch (attr.name) {
        case '规格': result.size = attr.value; break
        case '花纹': result.pattern = attr.value; break
        case '层级': result.ply = attr.value; break
        case '负荷指数': loadIndex = attr.value; break
        case '速度级别': speedLevel = attr.value; break
      }
    }
    if (loadIndex && speedLevel) {
      result.loadSpeed = loadIndex + speedLevel
    } else if (loadIndex) {
      result.loadSpeed = loadIndex
    }
  }

  // 降级：从 title 正则提取缺失字段
  const title = data.title || ''
  if (title) {
    if (!result.size) {
      const sizeMatch = title.match(/(\d{2,3}\/\d{2}R\d{2})/i)
      if (sizeMatch) result.size = sizeMatch[0]
    }
    if (!result.pattern) {
      let p = title
        .replace(/朝阳CHAOYANG/gi, '').replace(/朝阳轮胎/gi, '')
        .replace(/朝阳/gi, '').replace(/CHAOYANG/gi, '')
      if (result.size) p = p.replace(result.size, '')
      p = p.replace(/\b\d{2}[A-Z]\b/, '')
        .replace(/\s+/g, ' ').trim()
      result.pattern = p
    }
    if (!result.loadSpeed) {
      const lsMatch = title.match(/\b(\d{2}[A-Z])\b/)
      if (lsMatch) result.loadSpeed = lsMatch[0]
    }
  }

  return result
}

/**
 * 从 HTTP 响应头中提取指定 cookie 值
 */
function extractCookie(headers, name) {
  const setCookie = headers['set-cookie']
  if (!setCookie) return ''
  const cookies = Array.isArray(setCookie) ? setCookie : [setCookie]
  for (const c of cookies) {
    const m = c.match(new RegExp(name + '=([^;]+)'))
    if (m) return m[1]
  }
  return ''
}

/**
 * 从 URL 提取序列号
 * 支持: /qr/{serial} | ?barcode={serial} | ?code={serial}
 */
function extractSerialFromURL(url) {
  // /qr/{serial}
  let m = url.match(/\/qr\/([A-Z0-9]{6,30})/i)
  if (m) return m[1]
  // barcode={serial}
  m = url.match(/[?&]barcode=([A-Z0-9]{6,30})/i)
  if (m) return m[1]
  // code={serial}
  m = url.match(/[?&]code=([A-Z0-9]{6,30})/i)
  if (m) return m[1]
  return null
}

// ============================================================
// 策略1-4 辅助函数
// ============================================================

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

function regexParse(str) {
  const parts = str.split(/[\s,，_、]+/).filter(Boolean)
  let spec = '', brand = '', ply = '', pattern = '', loadIndex = ''
  for (const part of parts) {
    if (!spec && SIZE_RE_OLD.test(part)) {
      spec = part.match(SIZE_RE_OLD)[0]
    } else if (!ply && PLY_RE.test(part)) {
      ply = part.match(PLY_RE)[0].toUpperCase()
    } else if (/^\d{2,3}(\/\d{2,3})?[A-Z]?$/.test(part) && part.length <= 7) {
      loadIndex = part
    } else if (/^[一-龥]{2,4}$/.test(part)) {
      brand = part
    } else if (part.length >= 2 && part.length <= 10 && !/^\d+$/.test(part)) {
      pattern = part
    }
  }
  return { brand, spec, pattern, ply, loadIndex }
}
