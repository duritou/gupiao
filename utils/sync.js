// 离线同步工具 — 本地存储队列 + 网络恢复自动同步
const PENDING_KEY = '__pending_queue__'

function saveLocal(key, data) {
  try {
    wx.setStorageSync(key, data)
  } catch (e) {
    console.error('saveLocal error:', e)
  }
}

function getLocal(key) {
  try {
    return wx.getStorageSync(key)
  } catch (e) {
    return null
  }
}

/** 加入待同步队列 */
function enqueue(action) {
  const queue = getLocal(PENDING_KEY) || []
  queue.push({ ...action, _ts: Date.now() })
  saveLocal(PENDING_KEY, queue)
}

/** 尝试同步所有待处理操作，成功后清除队列 */
async function syncPending() {
  const queue = getLocal(PENDING_KEY) || []
  if (!queue.length) return

  let successCount = 0
  for (let i = queue.length - 1; i >= 0; i--) {
    const item = queue[i]
    try {
      await wx.cloud.callFunction({ name: item.fn, data: item.data })
      queue.splice(i, 1)
      successCount++
    } catch (e) {
      // 保留在队列中，下次再试
      console.warn('syncPending retry:', item.fn, e.errMsg)
    }
  }
  saveLocal(PENDING_KEY, queue)
  return successCount
}

module.exports = { saveLocal, getLocal, enqueue, syncPending }
