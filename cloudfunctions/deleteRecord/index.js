// 单条记录软删除 — 批次级库存恢复/校验
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()
const _ = db.command

exports.main = async (event) => {
  const { id, collection } = event

  if (!id || !collection) {
    return { ok: false, message: '缺少参数' }
  }

  if (collection !== 'purchase' && collection !== 'sales') {
    return { ok: false, message: '集合名必须是 purchase 或 sales' }
  }

  try {
    // 获取记录
    const recRes = await db.collection(collection).doc(id).get()
    const record = recRes.data
    if (!record) return { ok: false, message: '记录不存在' }
    if (record.isDeleted) return { ok: false, message: '记录已删除' }

    const tireId = record.tireId

    // ---- 删除进货记录：用 remainQuantity 校验是否已有出库 ----
    if (collection === 'purchase') {
      const effectiveRemain = record.remainQuantity !== undefined ? record.remainQuantity : record.qty
      const originalQty = record.qty || 0
      const soldQty = originalQty - effectiveRemain

      if (soldQty > 0) {
        return {
          ok: false,
          message: `该进货单已出库 ${soldQty} 条，无法删除。原进货 ${originalQty} 条，剩余 ${effectiveRemain} 条。请先删除对应出库单`
        }
      }
      console.log(`deleteRecord: 进货 ${id} 全部未出库，允许删除`)
    }

    // ---- 删除出库记录：恢复 remainQuantity ----
    if (collection === 'sales') {
      if (record.batches && record.batches.length > 0) {
        // 新格式：逐批次恢复
        console.log(`deleteRecord: 恢复 ${record.batches.length} 个批次的 remainQuantity`)
        for (const batch of record.batches) {
          try {
            console.log(`deleteRecord: 恢复 ${batch.purchaseId} remainQuantity += ${batch.qty}`)
            const updRes = await db.collection('purchase').doc(batch.purchaseId).update({
              data: { remainQuantity: _.inc(batch.qty) }
            })
            if (!updRes.stats || updRes.stats.updated === 0) {
              // 降级 set
              console.warn(`deleteRecord: ${batch.purchaseId} inc 未生效，降级 set`)
              const cur = await db.collection('purchase').doc(batch.purchaseId).get()
              const curRemain = cur.data.remainQuantity !== undefined ? cur.data.remainQuantity : cur.data.qty
              await db.collection('purchase').doc(batch.purchaseId).update({
                data: { remainQuantity: curRemain + Number(batch.qty) }
              })
            }
            console.log(`deleteRecord: ${batch.purchaseId} 恢复成功`)
          } catch (e) {
            console.error(`deleteRecord: 恢复 ${batch.purchaseId} 失败`, e.message)
            return { ok: false, message: `恢复批次 ${batch.purchaseId} 库存失败: ${e.message}` }
          }
        }
      } else if (record.purchaseId) {
        // 兼容单批次无 batches 数组的旧格式
        try {
          console.log(`deleteRecord: 旧格式恢复 ${record.purchaseId} remainQuantity += ${record.qty}`)
          const updRes = await db.collection('purchase').doc(record.purchaseId).update({
            data: { remainQuantity: _.inc(record.qty || 0) }
          })
          if (!updRes.stats || updRes.stats.updated === 0) {
            console.warn(`deleteRecord: ${record.purchaseId} inc 未生效（旧格式），降级 set`)
            const cur = await db.collection('purchase').doc(record.purchaseId).get()
            const curRemain = cur.data.remainQuantity !== undefined ? cur.data.remainQuantity : cur.data.qty
            await db.collection('purchase').doc(record.purchaseId).update({
              data: { remainQuantity: curRemain + Number(record.qty || 0) }
            })
          }
          console.log(`deleteRecord: ${record.purchaseId} 旧格式恢复成功`)
        } catch (e) {
          console.error(`deleteRecord: 旧格式恢复 ${record.purchaseId} 失败`, e.message)
        }
      }
      // 存量 sales 无 purchaseId 也无 batches 的情况：不做批次恢复（库存通过总减法已正确，无批次可恢复）
    }

    // 执行软删除
    const updateRes = await db.collection(collection).doc(id).update({
      data: { isDeleted: true }
    })

    // 校验 update 是否实际生效（FAIL-10）
    if (!updateRes.stats || updateRes.stats.updated === 0) {
      console.warn(`deleteRecord: update ${collection}/${id} 返回 updated:0，降级为 remove`)
      const removeRes = await db.collection(collection).doc(id).remove()
      if (!removeRes.stats || removeRes.stats.removed === 0) {
        return { ok: false, message: '删除失败，记录可能已被删除或不存在' }
      }
      console.log(`deleteRecord: ${collection}/${id} 已物理删除（降级）`)
      return { ok: true, message: '已删除' }
    }

    console.log(`deleteRecord: ${collection}/${id} 已软删除`)
    return { ok: true, message: '已删除' }
  } catch (e) {
    console.error('deleteRecord error:', e)
    return { ok: false, message: e.message }
  }
}
