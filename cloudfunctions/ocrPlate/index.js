// cloudfunctions/ocrPlate/index.js
// 微信云开发 — 车牌 OCR 识别云函数
// 调用 cloud.openapi.ocr.printedText 通用印刷体识别 → 正则提取车牌号
// 兼容蓝牌、绿牌新能源、黄牌、粤Z 港澳牌

const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })

// 中文车牌正则：省份简称 + 城市字母 + 4~7 位号码
const PLATE_REGEX = /[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤川青藏琼宁][A-Z][A-HJ-NP-Z0-9]{4,7}/g

exports.main = async (event) => {
  const fileID = event.imgUrl || ''

  // ==================== 参数校验 ====================
  if (!fileID) {
    return { code: -1, msg: '缺少图片 fileID' }
  }
  console.log('ocrPlate 入参 fileID:', fileID)

  // ==================== cloud:// fileID → 临时 HTTP URL ====================
  let httpUrl
  try {
    const urlRes = await cloud.getTempFileURL({ fileList: [fileID] })
    const file = (urlRes.fileList && urlRes.fileList[0]) || {}
    if (file.status !== 0 || !file.tempFileURL) {
      console.error('ocrPlate getTempFileURL 失败:', file)
      return { code: -3, msg: '图片链接获取失败，请重试' }
    }
    httpUrl = file.tempFileURL
    console.log('ocrPlate 临时 URL 获取成功，长度:', httpUrl.length)
  } catch (err) {
    console.error('ocrPlate getTempFileURL 异常:', err)
    return { code: -3, msg: '图片链接获取失败，请重试' }
  }

  // ==================== 调用通用印刷体 OCR ====================
  // 注意：只用 imgUrl（HTTP URL），不加 type 参数避免干扰
  let ocrResult
  try {
    ocrResult = await cloud.openapi.ocr.printedText({
      imgUrl: httpUrl
    })
  } catch (err) {
    console.error('ocrPlate openapi 调用异常 errCode:', err.errCode, 'msg:', err.message)
    return handleOpenapiError(err)
  }

  console.log('ocrPlate 原始返回 errCode:', ocrResult.errCode)
  console.log('ocrPlate ocrResult 顶层 keys:', JSON.stringify(Object.keys(ocrResult)))
  console.log('ocrPlate ocrResult 完整:', JSON.stringify(ocrResult))

  // ==================== 业务结果判断 ====================
  if (ocrResult.errCode !== 0) {
    return handleBusinessError(ocrResult)
  }

  // ==================== 从识别文字中提取车牌号 ====================
  const result = (ocrResult.result && Object.keys(ocrResult.result).length)
    ? ocrResult.result
    : ocrResult

  console.log('ocrPlate 实际解析源 keys:', JSON.stringify(Object.keys(result)))

  // 兼容多种返回格式：items[] / text / TextDetections[] / words_result[] / words[]
  let fullText = ''

  if (Array.isArray(result.items) && result.items.length) {
    fullText = result.items.map(item => item.text || item.itemstring || '').join(' ')
  } else if (Array.isArray(result.TextDetections) && result.TextDetections.length) {
    fullText = result.TextDetections.map(t => t.DetectedText || '').join(' ')
  } else if (result.text && typeof result.text === 'string') {
    fullText = result.text
  } else if (Array.isArray(result.words_result) && result.words_result.length) {
    fullText = result.words_result.map(w => w.words || '').join(' ')
  } else if (Array.isArray(result.words) && result.words.length) {
    fullText = result.words.join(' ')
  }

  if (!fullText) {
    return { code: -4, msg: '未识别到文字，请确保图片清晰、光照充足' }
  }

  console.log('ocrPlate 识别到文字:', fullText)

  const matches = fullText.match(PLATE_REGEX)
  if (!matches || matches.length === 0) {
    return { code: -4, msg: '未识别到车牌号，请确保车牌清晰完整、光照充足' }
  }

  let plateNumber = matches[0].toUpperCase()
  plateNumber = plateNumber.replace(/O/g, '0').replace(/I/g, '1')

  const plateType = detectPlateType(plateNumber)
  console.log('ocrPlate 识别成功:', plateNumber, '类型:', plateType)

  return { code: 0, data: { plateNumber, plateType } }
}

// ==================== 异常分类处理（catch 分支） ====================

function handleOpenapiError(err) {
  const errCode = err.errCode
  const errMsg = err.message || ''

  if (errCode === -604100) {
    return { code: -2, msg: '印刷体 OCR API 未注册，请在微信云开发控制台开启 ocr.printedText 权限，并重新上传部署本云函数' }
  }
  if (errCode === -604101) {
    return { code: -2, msg: '印刷体 OCR 接口权限未开通，请在微信云开发控制台开启 ocr.printedText' }
  }
  if (errCode === 101003 || /quota/i.test(errMsg)) {
    return { code: -5, msg: 'OCR 调用额度不足，请在微信云开发控制台购买 ocr.printedText 调用次数' }
  }
  if (errCode === -609001 || /invalid|image|format|decode/i.test(errMsg)) {
    return { code: -3, msg: '图片无效或格式不支持，请使用 JPG/PNG 照片' }
  }
  return { code: -1, msg: errMsg || 'OCR 服务异常，请重试' }
}

// ==================== 正常返回但业务失败 ====================

function handleBusinessError(ocrResult) {
  const errCode = ocrResult.errCode
  const errMsg = ocrResult.errMsg || ''

  if (errCode === -604100) {
    return { code: -2, msg: '印刷体 OCR API 未注册，请在微信云开发控制台开启 ocr.printedText 权限' }
  }
  if (errCode === -604101) {
    return { code: -2, msg: '印刷体 OCR 接口权限未开通，请在微信云开发控制台开启 ocr.printedText' }
  }
  if (errCode === -609001) {
    return { code: -3, msg: '图片无效或格式不支持，请使用 JPG/PNG 照片' }
  }
  return { code: -1, msg: errMsg || '识别失败，请重试' }
}

// ==================== 车牌类型判断 ====================

function detectPlateType(plate) {
  if (!plate) return 'fuel'
  if (plate.length === 8) return 'newEnergy'
  if (plate.startsWith('粤Z')) return 'hkMacao'
  return 'fuel'
}
