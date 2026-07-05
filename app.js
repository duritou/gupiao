App({
  onLaunch() {
    // ========== 云开发初始化（轮胎/扑克 模块共用）==========
    if (!wx.cloud) {
      console.error('请使用 2.2.3 或以上的基础库以使用云能力')
    } else {
      wx.cloud.init({ env: 'cloud1-d2gek3mad0a97e6a8' })
    }

    // 从本地缓存恢复用户身份（openId 每人固定不变，本地缓存实现瞬时启动）
    const idCache = wx.getStorageSync('__my_identity__') || {}
    if (idCache.openId) this.globalData.openId = idCache.openId
    if (idCache.nickName) this.globalData.nickName = idCache.nickName
    if (idCache.avatarUrl) this.globalData.avatarUrl = idCache.avatarUrl || ''

    // ========== 统一登录（获取云开发 openId）==========
    // 异步获取 openId，更新 globalData 并持久化
    wx.cloud.callFunction({ name: 'getOpenId' }).then(res => {
      if (res.result && res.result.openId) {
        this.globalData.openId = res.result.openId
        const id = wx.getStorageSync('__my_identity__') || {}
        id.openId = res.result.openId
        wx.setStorageSync('__my_identity__', id)
      }
    }).catch(err => {
      console.error('getOpenId 调用失败:', err)
    })

    // 冷启动：执行版本更新检测
    checkMiniProgramUpdate.call(this)
  },

  onShow() {
    // 热启动（后台切前台）：执行版本更新检测
    checkMiniProgramUpdate.call(this)
  },

  globalData: {
    openId: '',
    nickName: '',
    avatarUrl: '',
    hasCheckedUpdate: false      // 单次生命周期内是否已检测过更新
  },

  setNickName(name) {
    this.globalData.nickName = name
    // 合并写入，避免覆盖已有的 avatarUrl
    var id = wx.getStorageSync('__my_identity__') || {}
    id.nickName = name
    wx.setStorageSync('__my_identity__', id)
  }
})

/**
 * 检测微信小程序版本更新
 * 兼容冷启动（onLaunch）和热启动（onShow）两种场景
 * 单次生命周期内只执行一次，通过 globalData.hasCheckedUpdate 控制
 */
function checkMiniProgramUpdate() {
  // 单次生命周期只检测一次，避免反复弹窗打扰用户
  if (this.globalData.hasCheckedUpdate) return
  this.globalData.hasCheckedUpdate = true

  // 低版本微信不支持 UpdateManager → 提示升级微信客户端
  if (!wx.canIUse('getUpdateManager') || typeof wx.getUpdateManager !== 'function') {
    wx.showModal({
      title: '版本过低',
      content: '当前微信版本过低，无法获取小程序更新。请升级微信客户端后再使用。',
      showCancel: false,           // 无取消按钮，引导用户必须升级
      confirmText: '我知道了'
    })
    return
  }

  const updateManager = wx.getUpdateManager()

  // 监听版本更新结果（有新版本时触发）
  updateManager.onCheckForUpdate(res => {
    // res.hasUpdate === true 表示有新版本
    if (!res.hasUpdate) return

    // 监听新版包下载完成
    updateManager.onUpdateReady(() => {
      wx.showModal({
        title: '版本更新',
        content: '新版本已上线，体验更多功能',
        showCancel: true,
        cancelText: '稍后再说',     // 用户可选择继续使用旧版
        confirmText: '立即更新',
        success: modalRes => {
          if (modalRes.confirm) {
            // 用户确认 → 重启应用新版本
            updateManager.applyUpdate()
          }
          // 用户点取消 → 不做处理，下次进入仍会弹窗
        }
      })
    })

    // 监听新版包下载失败
    updateManager.onUpdateFailed(() => {
      wx.showModal({
        title: '更新失败',
        content: '新版本下载失败，请删除小程序后重新搜索进入。',
        showCancel: false,           // 无取消按钮，引导用户手动重装
        confirmText: '我知道了'
      })
    })
  })
}
