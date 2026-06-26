// 数据导出 — 按条件生成 CSV，上传云存储，返回下载链接
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()

exports.main = async (event) => {
  const { type, dateFrom, dateTo } = event || {}

  try {
    let rows = []
    let header = ''

    if (!type || type === 'purchase') {
      const pRes = await db.collection('purchase').orderBy('date', 'asc').get()
      header = '﻿日期,轮胎ID,供应商ID,数量,单价,总价,备注\n'
      rows = pRes.data.filter(r => !r.isDeleted).map(r =>
        `${r.date},${r.tireId},${r.supplierId || ''},${r.qty},${r.unitPrice},${r.total},${(r.note || '').replace(/,/g, ' ')}`
      )
    }

    if (!type || type === 'sale') {
      const sRes = await db.collection('sales').orderBy('date', 'asc').get()
      if (!header) header = '﻿日期,轮胎ID,客户,数量,成本单价,销售单价,总价,出库类型,备注\n'
      rows = rows.concat(sRes.data.filter(r => !r.isDeleted).map(r =>
        `${r.date},${r.tireId},${r.customer},${r.qty},${r.unitCost},${r.unitPrice},${r.total},${r.outType},${(r.note || '').replace(/,/g, ' ')}`
      ))
    }

    const csv = header + rows.join('\n')

    // 上传到云存储
    const filename = `export_${type || 'all'}_${Date.now()}.csv`
    const uploadRes = await cloud.uploadFile({
      cloudPath: `exports/${filename}`,
      fileContent: Buffer.from(csv, 'utf-8')
    })

    return {
      ok: true,
      fileID: uploadRes.fileID,
      filename,
      totalRows: rows.length
    }
  } catch (e) {
    return { ok: false, message: e.message }
  }
}
