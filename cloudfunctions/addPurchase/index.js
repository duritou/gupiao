// 新增进货记录
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()

exports.main = async (event) => {
  const { supplierId, tireId, qty, unitPrice, date, note, imageList } = event

  if (!tireId || !qty || !unitPrice) {
    return { ok: false, message: '缺少必填字段' }
  }

  const total = +(qty * unitPrice).toFixed(2)

  const record = {
    supplierId: supplierId || '',
    tireId,
    qty: Number(qty),
    remainQuantity: Number(qty),
    unitPrice: Number(unitPrice),
    total,
    date: date || new Date().toISOString().slice(0, 10),
    note: note || '',
    imageList: imageList || [],
    photo: (imageList && imageList.length > 0) ? imageList[0] : '',  // 冗余字段：首张照片 fileID
    isDeleted: false,
    createdAt: Date.now()
  }

  try {
    const res = await db.collection('purchase').add({ data: record })
    return { ok: true, _id: res._id, total }
  } catch (e) {
    return { ok: false, message: e.message }
  }
}
