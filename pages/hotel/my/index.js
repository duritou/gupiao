// pages/my/index.js
import network from '../../../utils/hotel-network';
/*
 * @Author: yurui 
 * @Date: 2021-05-28
 */
Page({

  /**
   * 页面的初始数据
   */
  data: {
    tabActive: 4,
    avatarUrl: '',
    nickName: '',
    showUser: false,
    roomOrderNum: 0,
    foodOrderNum: 0,
  },
  getData() {
    const that = this;
    network.request({
      url: `order/statistics`,
      header: {
        'content-type': 'application/json'
      },
      success(res) {
        if (res.data.code == 100010) {
          that.setData({
            roomOrderNum: res.data.data.room,
            foodOrderNum: res.data.data.food,
          });
        }
      },
      fail(res) {
        wx.showToast({
          title: '数据请求失败',
          icon: 'error',
          duration: 2000
        });
      },
    });
  },
  onCloseUser() {
    this.setData({
      showUser: false
    });
  },

  // 替换废弃的 wx.getUserProfile：使用 chooseAvatar + nickname 填写能力
  onChooseAvatar(e) {
    const { avatarUrl } = e.detail;
    this.setData({ avatarUrl });
    const userInfo = wx.getStorageSync('userInfo') || {};
    userInfo.avatarUrl = avatarUrl;
    wx.setStorageSync('userInfo', userInfo);
  },

  onInputNickname(e) {
    const nickName = e.detail.value;
    this.setData({ nickName });
    const userInfo = wx.getStorageSync('userInfo') || {};
    userInfo.nickName = nickName;
    wx.setStorageSync('userInfo', userInfo);
  },
  goList(e) {
    wx.navigateTo({
      url: `/pages/hotel/order/index?active=${e.currentTarget.id}`
    });
  },
  goFood() {
    wx.navigateTo({
      url: `/pages/hotel/foodOrder/index?active=0`
    });
  },
  goEval() {
    wx.navigateTo({
      url: `/pages/hotel/foodMyEval/index`
    });
  },
  onLogin() {
    const userInfo = wx.getStorageSync('userInfo');
    if (userInfo && (userInfo.avatarUrl || userInfo.nickName)) {
      this.setData({
        avatarUrl: userInfo.avatarUrl || '',
        nickName: userInfo.nickName || ''
      });
    } else {
      // 未填写过头像昵称时展示编辑弹窗
      this.setData({ showUser: true });
    }
  },
  /**
   * 生命周期函数--监听页面加载
   */
  onLoad: function (options) {
    this.onLogin();
    this.getData();
  },

  /**
   * 生命周期函数--监听页面初次渲染完成
   */
  onReady: function () {

  },

  /**
   * 生命周期函数--监听页面显示
   */
  onShow: function () {

  },

  /**
   * 生命周期函数--监听页面隐藏
   */
  onHide: function () {

  },

  /**
   * 生命周期函数--监听页面卸载
   */
  onUnload: function () {

  },

  /**
   * 页面相关事件处理函数--监听用户下拉动作
   */
  onPullDownRefresh: function () {

  },

  /**
   * 页面上拉触底事件的处理函数
   */
  onReachBottom: function () {

  },

  /**
   * 用户点击右上角分享
   */
  onShareAppMessage: function () {

  }
})