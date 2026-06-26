// 原子出库 — 批次级别库存扣减，补偿模式回滚
// 支持两种模式：
//   A) 显式批次：前端传 batches[{purchaseId, qty}] → 直接使用
//   B) 自动FIFO：前端只传 tireId+qty → 后端按入库日期升序自动分配批次
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()
const _ = db.command

/** 分页获取集合全部记录 */
async function fetchAll(collection) {
  let all = []
  let skip = 0
  const PAGE_SIZE = 100
  while (true) {
    const res = await db.collection(collection).skip(skip).limit(PAGE_SIZE).get()
    if (res.data.length === 0) break
    all = all.concat(res.data)
    skip += PAGE_SIZE
  }
  return all
}

/** 回滚已扣批次 */
async function rollbackDeducted(deducted) {
  console.log(`createSale: 开始回滚 ${deducted.length} 个已扣批次`)
  for (const rb of deducted) {
    try {
      const rbDelta = Number(rb.qty)
      console.log(`createSale: 回滚 ${rb.purchaseId} remainQuantity += ${rbDelta}`)
      const rbRes = await db.collection('purchase').doc(rb.purchaseId).update({
        data: { remainQuantity: _.inc(rbDelta) }
      })
      if (!rbRes.stats || rbRes.stats.updated === 0) {
        const cur = await db.collection('purchase').doc(rb.purchaseId).get()
        const curRemain = cur.data.remainQuantity !== undefined ? cur.data.remainQuantity : cur.data.qty
        await db.collection('purchase').doc(rb.purchaseId).update({
          data: { remainQuantity: curRemain + rbDelta }
        })
      }
      console.log(`createSale: ${rb.purchaseId} 回滚成功`)
    } catch (rbErr) {
      console.error(`createSale: 回滚 ${rb.purchaseId} 失败!!!`, rbErr.message)
    }
  }
}

exports.main = async (event) => {
  let { tireId, customer, plate, qty, unitCost, unitPrice, outType, date, note, batches } = event

  // ---- Step 1: 参数校验 ----
  if (!tireId || !qty) {
    return { ok: false, message: '缺少必填字段（tireId/qty）' }
  }

  const outQty = Number(qty)
  if (outQty <= 0) {
    return { ok: false, message: '出库数量必须大于0' }
  }

  // ---- Step 1.5: 自动 FIFO 分配（当前端未传 batches 时）----
  if (!batches || !batches.length) {
    console.log(`createSale: 未传 batches，自动 FIFO 分配 tireId=${tireId} qty=${outQty}`)

    // 分页获取该轮胎所有未删除进货，按日期升序
    const allPurchases = await fetchAll('purchase')
    const candidates = allPurchases
      .filter(p => p.tireId === tireId && !p.isDeleted)
      .map(p => ({
        purchaseId: p._id,
        remainQuantity: p.remainQuantity !== undefined ? p.remainQuantity : (p.qty || 0),
        date: p.date || ''
      }))
      .filter(p => p.remainQuantity > 0)
      .sort((a, b) => (a.date || '').localeCompare(b.date || ''))

    console.log(`createSale: FIFO 候选批次 ${candidates.length} 个`)

    if (candidates.length === 0) {
      return { ok: false, message: '该轮胎无可用库存' }
    }

    // 计算总可用库存
    const totalAvailable = candidates.reduce((s, c) => s + c.remainQuantity, 0)
    if (outQty > totalAvailable) {
      return { ok: false, message: `库存不足，可用 ${totalAvailable} 条，需要 ${outQty} 条` }
    }

    // 贪心分配（FIFO 按日期升序）
    batches = []
    let remaining = outQty
    for (const c of candidates) {
      if (remaining <= 0) break
      const take = Math.min(c.remainQuantity, remaining)
      batches.push({ purchaseId: c.purchaseId, qty: take })
      remaining -= take
    }

    console.log(`createSale: FIFO 分配结果 ${JSON.stringify(batches)}`)
  }

  // ---- Step 1.6: 校验批次数量之和 ----
  const batchSum = batches.reduce((s, b) => s + Number(b.qty), 0)
  if (batchSum !== outQty) {
    return { ok: false, message: `批次分配数量(${batchSum})与出库总数(${outQty})不一致` }
  }

  // 去重：同一批次不能出现多次
  const batchIds = batches.map(b => b.purchaseId)
  if (new Set(batchIds).size !== batchIds.length) {
    return { ok: false, message: '存在重复的批次分配' }
  }

  // ---- Step 2: 逐条校验每个批次库存（独立 try/catch）----
  console.log(`createSale: 开始校验 ${batches.length} 个批次库存`)
  for (const batch of batches) {
    try {
      const pRes = await db.collection('purchase').doc(batch.purchaseId).get()
      const p = pRes.data
      if (!p) {
        return { ok: false, message: `批次 ${batch.purchaseId} 不存在` }
      }
      if (p.isDeleted) {
        return { ok: false, message: `批次 ${batch.purchaseId} 已被删除` }
      }
      if (p.tireId !== tireId) {
        return { ok: false, message: `批次 ${batch.purchaseId} 轮胎不匹配` }
      }
      const effectiveRemain = p.remainQuantity !== undefined ? p.remainQuantity : p.qty
      if (effectiveRemain < Number(batch.qty)) {
        return { ok: false, message: `批次库存不足: ${batch.purchaseId} 剩余 ${effectiveRemain}，需要 ${batch.qty}` }
      }
      console.log(`createSale: ${batch.purchaseId} 库存校验通过 remain=${effectiveRemain} 扣减=${batch.qty}`)
    } catch (e) {
      console.error(`createSale: 校验 ${batch.purchaseId} 失败`, e.message)
      return { ok: false, message: `校验批次 ${batch.purchaseId} 失败: ${e.message}` }
    }
  }

  // ---- Step 3: 逐条扣减 remainQuantity（补偿模式）----
  console.log(`createSale: 开始扣减 ${batches.length} 个批次`)
  const deducted = []

  for (const batch of batches) {
    try {
      const delta = -Number(batch.qty)
      console.log(`createSale: 扣减 ${batch.purchaseId} remainQuantity += ${delta}`)

      const updRes = await db.collection('purchase').doc(batch.purchaseId).update({
        data: { remainQuantity: _.inc(delta) }
      })

      // FAIL-10: 验证 update 是否生效
      if (!updRes.stats || updRes.stats.updated === 0) {
        console.warn(`createSale: ${batch.purchaseId} inc 未生效，降级为显式 set`)
        const cur = await db.collection('purchase').doc(batch.purchaseId).get()
        const curRemain = cur.data.remainQuantity !== undefined ? cur.data.remainQuantity : cur.data.qty
        const newRemain = curRemain - Number(batch.qty)
        await db.collection('purchase').doc(batch.purchaseId).update({
          data: { remainQuantity: newRemain }
        })
      }

      deducted.push(batch)
      console.log(`createSale: ${batch.purchaseId} 扣减成功`)
    } catch (e) {
      console.error(`createSale: ${batch.purchaseId} 扣减失败`, e.message)
      await rollbackDeducted(deducted)
      return { ok: false, message: `扣减批次 ${batch.purchaseId} 失败，已回滚: ${e.message}` }
    }
  }

  // ---- Step 4: 创建 sales 记录 ----
  console.log(`createSale: 所有批次扣减完成，创建 sales 记录`)
  const total = +(outQty * (unitPrice || 0)).toFixed(2)

  const record = {
    tireId,
    customer,
    plate: plate || '',
    qty: outQty,
    unitCost: Number(unitCost) || 0,
    unitPrice: Number(unitPrice) || 0,
    total,
    outType: outType || 'sales',
    date: date || new Date().toISOString().slice(0, 10),
    note: note || '',
    purchaseId: batches[0].purchaseId,  // 主批次ID
    batches: batches.map(b => ({ purchaseId: b.purchaseId, qty: Number(b.qty) })),
    purchaseIds: batches.map(b => b.purchaseId),  // FAIL-11: 被扣减的进货单 ID 列表
    isDeleted: false,
    createdAt: Date.now()
  }

  try {
    const addRes = await db.collection('sales').add({ data: record })
    console.log(`createSale: sales 记录创建成功 ${addRes._id}`)
    return { ok: true, _id: addRes._id, deducted }
  } catch (e) {
    console.error(`createSale: 创建 sales 记录失败`, e.message)
    await rollbackDeducted(deducted)
    return { ok: false, message: `创建出库记录失败，已回滚库存: ${e.message}` }
  }
}
