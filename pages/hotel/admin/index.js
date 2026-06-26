// 酒店图片管理页 — 手机端上传房型/菜品/文章图片
const app = getApp()
const domain = '' // 云存储模式，domain 置空

Page({
  data: {
    activeTab: 'roomTypes',
    list: [],
    loading: false,
    uploading: false,

    // 分类配置
    tabs: [
      { key: 'roomTypes', label: '房型' },
      { key: 'foods', label: '菜品' },
      { key: 'articles', label: '文章' }
    ]
  },

  onLoad() {
    this.fetchList()
  },

  // 切换分类
  switchTab(e) {
    const tab = e.currentTarget.dataset.tab
    if (tab === this.data.activeTab) return
    this.setData({ activeTab: tab, list: [] })
    this.fetchList()
  },

  // 获取列表
  async fetchList() {
    this.setData({ loading: true })
    try {
      const res = await wx.cloud.callFunction({
        name: 'hotelAdmin',
        data: { action: 'list', collection: this.data.activeTab }
      })
      const result = res.result
      if (result.code === 0 && result.data) {
        const { fields, list } = result.data
        // 格式化显示字段
        const formatted = list.map(item => ({
          ...item,
          displayName: item[fields.name] || '(未命名)',
          displayPhoto: item.photo || ''
        }))
        this.setData({ list: formatted })
        // 缓存字段信息用于更新判断
        this._fields = fields
      } else {
        wx.showToast({ title: result.message || '加载失败', icon: 'none' })
      }
    } catch (e) {
      console.error('fetchList error:', e)
      wx.showToast({ title: '网络错误', icon: 'none' })
    } finally {
      this.setData({ loading: false })
    }
  },

  // 更换照片
  onChangePhoto(e) {
    const docId = e.currentTarget.dataset.id
    const name = e.currentTarget.dataset.name

    // 选择图片
    wx.chooseImage({
      count: 1,
      sizeType: ['compressed'],
      sourceType: ['album', 'camera'],
      success: async (chooseRes) => {
        const filePath = chooseRes.tempFilePaths[0]
        await this.uploadAndUpdate(docId, filePath, name)
      }
    })
  },

  // 上传图片到云存储并更新数据库
  async uploadAndUpdate(docId, filePath, name) {
    this.setData({ uploading: true })

    try {
      // 生成云存储路径（带时间戳防重名）
      const timestamp = Date.now()
      const ext = filePath.split('.').pop() || 'jpg'
      const cloudPath = `hotel/${this.data.activeTab}/${timestamp}.${ext}`

      // 上传到云存储
      const uploadRes = await wx.cloud.uploadFile({
        cloudPath: cloudPath,
        filePath: filePath
      })

      if (!uploadRes.fileID) {
        throw new Error('上传失败：未获取到 fileID')
      }

      // 更新数据库
      const updateRes = await wx.cloud.callFunction({
        name: 'hotelAdmin',
        data: {
          action: 'updatePhoto',
          collection: this.data.activeTab,
          docId: docId,
          photo: uploadRes.fileID
        }
      })

      if (updateRes.result.code === 0) {
        wx.showToast({ title: '更新成功', icon: 'success' })
        // 刷新列表
        this.fetchList()
      } else {
        wx.showToast({ title: updateRes.result.message || '更新失败', icon: 'none' })
      }
    } catch (e) {
      console.error('uploadAndUpdate error:', e)
      wx.showToast({ title: '上传失败: ' + (e.message || '未知错误'), icon: 'none' })
    } finally {
      this.setData({ uploading: false })
    }
  }
})
