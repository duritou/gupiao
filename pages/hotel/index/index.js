// index.js
// 获取应用实例
const app = getApp();
import {
  moment
} from '../../../utils/hotel-util';
import network from '../../../utils/hotel-network';
/*
 * @Author: yurui
 * @Date: 2021-05-28
 */
import {
  domain
} from '../../../utils/hotel-config';

Page({
  data: {
    tabActive: 0,
    startTime: moment().format('MM月DD日'),
    endTime: moment().add(1, 'days').format('MM月DD日'),
    startWeek: moment().format('dddd'),
    endWeek: moment().add(1, 'days').format('dddd'),
    totalTime: '1',
    autoplay: true,
    show: false,
    banner: [],
    rooms: [],
    domain,
    allStartTime: moment().format('YYYY-MM-DD'),
    allEndTime: moment().add(1, 'days').format('YYYY-MM-DD'),
  },
  // 事件处理函数
  onDisplay() {
    this.setData({
      show: true
    });
  },
  onClose() {
    this.setData({
      show: false
    });
  },
  onConfirm(event) {
    const [start, end] = event.detail;
    this.setData({
      show: false,
      allStartTime: moment(start).format('YYYY-MM-DD'),
      allEndTime: moment(end).format('YYYY-MM-DD'),
      startTime: moment(start).format('MM月DD日'),
      endTime: moment(end).format('MM月DD日'),
      startWeek: moment(start).format('dddd'),
      endWeek: moment(end).format('dddd'),
      totalTime: moment(end).diff(moment(start), 'days'),
    });
  },
  getData() {
    const that = this;
    network.request({
      url: `home`,
      header: {
        'content-type': 'application/json'
      },
      success(res) {
        if (res.data.code == 100010) {
          that.setData({
            banner: res.data.data.banner,
            rooms: res.data.data.rooms,
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
  onLoad() {
    // 等待登录完成后再请求数据，避免未登录时发起鉴权请求
    if (app.hotelLoginReady) {
      app.hotelLoginReady.then(() => {
        this.getData();
      });
    } else {
      this.getData();
    }
  },
  goYuding() {
    wx.navigateTo({
      url: `/pages/hotel/room/index?startTime=${this.data.allStartTime}&endTime=${this.data.allEndTime}`
    });
  },
  goRoomDetails(e) {
    wx.navigateTo({
      url: `/pages/hotel/roomDetails/index?id=${e.currentTarget.id}`
    });
  },
  // 分享首页给好友
  onShareAppMessage() {
    return {
      title: '酒店预订 - 品质之选',
      path: '/pages/hotel/index/index',
      imageUrl: this.data.banner.length ? domain + this.data.banner[0].photo : '',
    };
  }
})