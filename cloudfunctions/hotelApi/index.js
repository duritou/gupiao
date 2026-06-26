// 酒店模块 API 云函数 — 替代原 Egg.js 后端的所有小程序接口
// 请求入口：event.action / event.method / event.payload
// 用户身份：cloud.getWXContext().OPENID（替代原 Redis sessionid 机制）
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()
const _ = db.command

// ====================== 工具函数 ======================

// 解析 action 字符串：'room?startTime=X&endTime=Y' → { path: 'room', query: { startTime: 'X', endTime: 'Y' } }
// 支持路径参数：'room/details/123' → { path: 'room/details/:id', params: { id: '123' } }
function parseAction(action) {
  if (!action) return { path: '', query: {}, params: {} }
  const questionIdx = action.indexOf('?')
  const pathWithQuery = questionIdx >= 0 ? action.substring(0, questionIdx) : action
  const queryStr = questionIdx >= 0 ? action.substring(questionIdx + 1) : ''
  // 解析 query string
  const query = {}
  if (queryStr) {
    queryStr.split('&').forEach(function (pair) {
      const eqIdx = pair.indexOf('=')
      if (eqIdx >= 0) {
        query[decodeURIComponent(pair.substring(0, eqIdx))] = decodeURIComponent(pair.substring(eqIdx + 1))
      }
    })
  }
  // 解析路径参数（如 /details/123、/:id）
  const pathParts = pathWithQuery.split('/')
  const params = {}
  // 尝试匹配已知的带参数路径模式
  if (pathParts.length >= 3) {
    // room/details/:id, order/details/:id, news/details/:id, food/details/:id, food/order/details/:id
    if ((pathParts[1] === 'details' || pathParts[pathParts.length - 2] === 'details') && pathParts[pathParts.length - 1]) {
      params.id = pathParts[pathParts.length - 1]
    }
  }
  return { path: pathWithQuery, query: query, params: params }
}

// 生成订单编号（16 位：时间戳后 10 位 + 6 位随机数）
function generateOrderId() {
  const ts = Date.now().toString()
  const rand = Math.floor(Math.random() * 1000000).toString().padStart(6, '0')
  return ts.substring(ts.length - 10) + rand
}

// 获取日期范围内所有日期（YYYY-MM-DD 数组）
function getDays(startDate, endDate) {
  const days = []
  const start = new Date(startDate)
  const end = new Date(endDate)
  while (start < end) {
    days.push(formatDate(start))
    start.setDate(start.getDate() + 1)
  }
  return days
}

function formatDate(date) {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return y + '-' + m + '-' + d
}

// 根据日期字符串获取星期几（中文）
function getDayOfWeekCN(dateStr) {
  const d = new Date(dateStr)
  const days = ['星期日', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六']
  return days[d.getDay()]
}

// 根据星期几获取数字（1-7，周一=1）
function getWeekNumber(dateStr) {
  const d = new Date(dateStr)
  return d.getDay() === 0 ? 7 : d.getDay()
}

// 获取某房型在某日期的价格（优先特殊日期价格，其次周价格）
async function getRoomPrice(dateStr, typeId) {
  // 先查特殊日期价格
  const dayRes = await db.collection('hotel_day_prices').where({
    typeId: typeId,
    startdate: _.lte(dateStr),
    enddate: _.gte(dateStr),
    status: 1
  }).limit(1).get()
  if (dayRes.data.length > 0) return Number(dayRes.data[0].price)

  // 再查周价格
  const weekNum = getWeekNumber(dateStr)
  const weekRes = await db.collection('hotel_week_prices').where({
    typeId: typeId,
    weeks: String(weekNum),
    status: 1
  }).limit(1).get()
  if (weekRes.data.length > 0) return Number(weekRes.data[0].price)

  return 0
}

// 计算平均价格
function getAverage(arr) {
  if (!arr || arr.length === 0) return 0
  let sum = 0
  for (let i = 0; i < arr.length; i++) sum += Number(arr[i])
  return Math.round(sum / arr.length)
}

// 统一返回格式
function ok(data, code) {
  return { code: code || 100010, data: data, message: '' }
}
function fail(message, code) {
  return { code: code || 0, data: null, message: message || '' }
}

// ====================== 登录 ======================
// 云开发模式下，登录只需返回 OPENID（已由 app.js 的 getOpenId 获取）
// 此接口保留兼容性，实际不再需要
async function handleLogin(event, ctx) {
  return ok(ctx.OPENID || 'success')
}

// ====================== 首页 ======================
async function handleHome(event, ctx) {
  try {
    // 获取 banner（articles 表中 type='banner' 的记录）
    const bannerRes = await db.collection('hotel_articles')
      .where({ type: 'banner' })
      .orderBy('createdAt', 'desc')
      .limit(6)
      .get()
    // 获取推荐房型列表
    const roomTypesRes = await db.collection('hotel_room_types')
      .orderBy('isTop', 'desc')
      .orderBy('createdAt', 'desc')
      .limit(10)
      .get()
    const rooms = []
    for (let i = 0; i < roomTypesRes.data.length; i++) {
      const rt = roomTypesRes.data[i]
      // 检查是否有空闲房间
      const freeRoomCount = await db.collection('hotel_rooms')
        .where({ room_type_id: rt._id, status: 1 })
        .count()
      if (freeRoomCount.total > 0) {
        // 获取一个默认价格（取第一条周价格或 0）
        const weekRes = await db.collection('hotel_week_prices')
          .where({ typeId: rt._id, status: 1 })
          .limit(1)
          .get()
        const price = weekRes.data.length > 0 ? Number(weekRes.data[0].price) : 0
        rooms.push({
          id: rt._id,
          name: rt.name,
          area: rt.area,
          window: rt.window,
          wifi: rt.wifi,
          floor: rt.floor,
          people_num: rt.people_num,
          smoking: rt.smoking,
          bed_type: rt.bed_type,
          meals: rt.meals,
          photo: rt.photo,
          photo_s: rt.photo_s,
          support: rt.support,
          bathroom: rt.bathroom,
          food: rt.food,
          media: rt.media,
          landscape: rt.landscape,
          facilities: rt.facilities,
          instructions: rt.instructions,
          cancel_rules: rt.cancel_rules,
          isTop: rt.isTop,
          createdAt: rt.createdAt
        })
      }
    }
    return ok({
      banner: bannerRes.data,
      rooms: rooms
    })
  } catch (e) {
    console.error('handleHome 错误:', e)
    return fail(e.message)
  }
}

// ====================== 房型 ======================
// GET room?startTime=X&endTime=Y
async function handleRoomList(event, ctx) {
  try {
    const query = parseAction(event.action).query
    const startTime = query.startTime
    const endTime = query.endTime
    const roomTypesRes = await db.collection('hotel_room_types')
      .orderBy('isTop', 'desc')
      .get()
    const result = []
    for (let i = 0; i < roomTypesRes.data.length; i++) {
      const rt = roomTypesRes.data[i]
      const freeRoomCount = await db.collection('hotel_rooms')
        .where({ room_type_id: rt._id, status: 1 })
        .count()
      if (freeRoomCount.total > 0) {
        // 计算时间段内每天的平均价格
        let price = 0
        if (startTime && endTime) {
          const days = getDays(startTime, endTime)
          const prices = []
          for (let d = 0; d < days.length; d++) {
            const p = await getRoomPrice(days[d], rt._id)
            if (p > 0) prices.push(p)
          }
          price = getAverage(prices)
        } else {
          const weekRes = await db.collection('hotel_week_prices')
            .where({ typeId: rt._id, status: 1 })
            .limit(1)
            .get()
          price = weekRes.data.length > 0 ? Number(weekRes.data[0].price) : 0
        }
        result.push({
          room: {
            id: rt._id, name: rt.name, area: rt.area, window: rt.window,
            wifi: rt.wifi, floor: rt.floor, people_num: rt.people_num,
            smoking: rt.smoking, bed_type: rt.bed_type, meals: rt.meals,
            photo: rt.photo, photo_s: rt.photo_s, support: rt.support,
            bathroom: rt.bathroom, food: rt.food, media: rt.media,
            landscape: rt.landscape, facilities: rt.facilities,
            instructions: rt.instructions, cancel_rules: rt.cancel_rules,
            isTop: rt.isTop, createdAt: rt.createdAt
          },
          price: price
        })
      }
    }
    return ok(result)
  } catch (e) {
    console.error('handleRoomList 错误:', e)
    return fail(e.message)
  }
}

// GET room/details/:id
async function handleRoomDetails(event, ctx) {
  try {
    const params = parseAction(event.action).params
    const id = params.id || event.payload.id
    if (!id) return fail('缺少房型 id')
    const res = await db.collection('hotel_room_types').doc(id).get()
    if (!res.data) return fail('房型不存在')
    const rt = res.data
    const freeRoomCount = await db.collection('hotel_rooms')
      .where({ room_type_id: id, status: 1 })
      .count()
    return ok({
      id: rt._id, name: rt.name, area: rt.area, window: rt.window,
      wifi: rt.wifi, floor: rt.floor, people_num: rt.people_num,
      smoking: rt.smoking, bed_type: rt.bed_type, meals: rt.meals,
      photo: rt.photo, photo_s: rt.photo_s, support: rt.support,
      bathroom: rt.bathroom, food: rt.food, media: rt.media,
      landscape: rt.landscape, facilities: rt.facilities,
      instructions: rt.instructions, cancel_rules: rt.cancel_rules,
      isTop: rt.isTop, freeCount: freeRoomCount.total
    })
  } catch (e) {
    console.error('handleRoomDetails 错误:', e)
    return fail(e.message)
  }
}

// GET order/buy?id=X&startTime=X&endTime=X
async function handleRoomOrderBuy(event, ctx) {
  try {
    const query = parseAction(event.action).query
    const typeId = query.id
    const startTime = query.startTime
    const endTime = query.endTime
    if (!typeId || !startTime || !endTime) return fail('缺少必要参数')
    // 检查是否有空闲房间
    const freeRoomCount = await db.collection('hotel_rooms')
      .where({ room_type_id: typeId, status: 1 })
      .count()
    if (freeRoomCount.total === 0) return fail('房间都被预定满了')
    // 获取房型信息
    const rtRes = await db.collection('hotel_room_types').doc(typeId).get()
    if (!rtRes.data) return fail('房型不存在')
    // 计算每天价格
    const days = getDays(startTime, endTime)
    const priceArr = []
    for (let i = 0; i < days.length; i++) {
      const p = await getRoomPrice(days[i], typeId)
      priceArr.push({ time: days[i], price: p })
    }
    return ok({
      room: {
        id: rtRes.data._id, name: rtRes.data.name, area: rtRes.data.area,
        window: rtRes.data.window, wifi: rtRes.data.wifi, floor: rtRes.data.floor,
        people_num: rtRes.data.people_num, smoking: rtRes.data.smoking,
        bed_type: rtRes.data.bed_type, meals: rtRes.data.meals,
        photo: rtRes.data.photo, photo_s: rtRes.data.photo_s,
        support: rtRes.data.support, bathroom: rtRes.data.bathroom,
        food: rtRes.data.food, media: rtRes.data.media,
        landscape: rtRes.data.landscape, facilities: rtRes.data.facilities,
        instructions: rtRes.data.instructions, cancel_rules: rtRes.data.cancel_rules
      },
      price: priceArr
    })
  } catch (e) {
    console.error('handleRoomOrderBuy 错误:', e)
    return fail(e.message)
  }
}

// ====================== 订单 ======================
// POST order/create
async function handleOrderCreate(event, ctx) {
  try {
    const query = event.payload
    const openId = ctx.OPENID
    if (!openId) return fail('未登录')
    if (!query.typeId || !query.start_time || !query.end_time) return fail('缺少必要参数')
    if (!query.people || !query.people_mobile) return fail('缺少预定人信息')
    // 校验入住时间不超过30天
    const now = new Date()
    const startDate = new Date(query.start_time + ' 18:00:00')
    const dayDiff = Math.floor((startDate - now) / (1000 * 60 * 60 * 24))
    if (dayDiff > 30) return fail('只能预定30天内的房间')
    // 查找一个空闲房间
    const freeRoomRes = await db.collection('hotel_rooms')
      .where({ room_type_id: query.typeId, status: 1 })
      .limit(1)
      .get()
    if (freeRoomRes.data.length === 0) return fail('该房型已满')
    const freeRoom = freeRoomRes.data[0]
    // 计算总价
    const days = getDays(query.start_time, query.end_time)
    let totalPrice = 0
    for (let i = 0; i < days.length; i++) {
      const p = await getRoomPrice(days[i], query.typeId)
      totalPrice += p
    }
    if (totalPrice === 0) return fail('价格计算失败')
    const orderId = generateOrderId()
    // 锁定房间
    await db.collection('hotel_rooms').doc(freeRoom._id).update({
      data: { status: 2, updatedAt: new Date() }
    })
    // 创建订单
    const orderData = {
      roomid: freeRoom._id,
      uid: openId,
      start_time: query.start_time,
      end_time: query.end_time,
      from_type: 3,
      order_id: orderId,
      price: totalPrice,
      people: query.people,
      people_mobile: query.people_mobile,
      mycome: query.mycome || '',
      content: query.content || '',
      deposit_price: query.deposit_price || 0,
      confirm_price: 0,
      status: 2,       // 待入住
      price_extras: 0,
      pay_status: 0,   // 未支付
      pay_id: '',
      pay_money: 0,
      refund_status: 0,
      eat_type: query.eat_type || 0,
      createdAt: new Date(),
      updatedAt: new Date()
    }
    const addRes = await db.collection('hotel_orders').add({ data: orderData })
    return ok({ ids: addRes._id + ',', succes: 1 }, 100020)
  } catch (e) {
    console.error('handleOrderCreate 错误:', e)
    return fail(e.message)
  }
}

// GET order/list?status=X&pay_status=X
async function handleOrderList(event, ctx) {
  try {
    const openId = ctx.OPENID
    if (!openId) return fail('未登录')
    const query = parseAction(event.action).query
    const where = { uid: openId }
    if (event.payload && event.payload.status) where.status = Number(event.payload.status)
    if (event.payload && event.payload.pay_status) where.pay_status = Number(event.payload.pay_status)
    if (query.status) where.status = Number(query.status)
    if (query.pay_status) where.pay_status = Number(query.pay_status)
    const res = await db.collection('hotel_orders')
      .where(where)
      .orderBy('createdAt', 'desc')
      .get()
    // 为每个订单附加房间和房型信息
    const result = []
    for (let i = 0; i < res.data.length; i++) {
      const order = res.data[i]
      let room = null
      try {
        const roomRes = await db.collection('hotel_rooms').doc(order.roomid).get()
        room = roomRes.data
      } catch (e) { /* 房间可能被删除 */ }
      let roomType = null
      if (room && room.room_type_id) {
        try {
          const typeRes = await db.collection('hotel_room_types').doc(room.room_type_id).get()
          roomType = typeRes.data
        } catch (e) { /* 房型可能被删除 */ }
      }
      const item = { ...order }
      if (room) item.room = { id: room._id, name: room.name, room_type_id: room.room_type_id, status: room.status }
      if (roomType) item.room.type = { id: roomType._id, name: roomType.name, photo: roomType.photo }
      // 计算剩余支付时间（30分钟）
      if (order.status === 2 && order.pay_status === 0) {
        const createdAt = new Date(order.createdAt).getTime()
        const expireTime = createdAt + 30 * 60 * 1000
        const remaining = Math.max(0, Math.floor((expireTime - Date.now()) / 1000))
        item.pay_time = remaining
      }
      result.push(item)
    }
    return ok(result)
  } catch (e) {
    console.error('handleOrderList 错误:', e)
    return fail(e.message)
  }
}

// POST order/cancel
async function handleOrderCancel(event, ctx) {
  try {
    const openId = ctx.OPENID
    if (!openId) return fail('未登录')
    const id = event.payload.id
    if (!id) return fail('缺少订单 id')
    const orderRes = await db.collection('hotel_orders').doc(id).get()
    if (!orderRes.data) return fail('订单不存在')
    const order = orderRes.data
    if (order.uid !== openId) return fail('无权操作')
    if (order.status !== 2) return fail('当前状态不可取消')
    // 距离入住时间18点小于24小时且已支付的订单不能取消
    if (order.pay_status === 1) {
      const now = new Date()
      const checkinTime = new Date(order.start_time + ' 18:00:00')
      const hours = Math.floor((checkinTime - now) / (1000 * 60 * 60))
      if (hours < 24) return fail('距离入住不足24小时，不可取消')
    }
    // 释放房间
    try {
      await db.collection('hotel_rooms').doc(order.roomid).update({
        data: { status: 1, updatedAt: new Date() }
      })
    } catch (e) { /* 房间可能已删除 */ }
    // 取消关联的订餐订单
    await db.collection('hotel_food_orders').where({
      room_order_id: order.order_id
    }).update({
      data: { status: 3, updatedAt: new Date() }
    })
    // 更新订单状态
    await db.collection('hotel_orders').doc(id).update({
      data: { status: 3, updatedAt: new Date() }
    })
    return ok(null, 100030)
  } catch (e) {
    console.error('handleOrderCancel 错误:', e)
    return fail(e.message, 100031)
  }
}

// GET order/details/:id
async function handleOrderDetails(event, ctx) {
  try {
    const openId = ctx.OPENID
    const params = parseAction(event.action).params
    const id = params.id || event.payload.id
    if (!id) return fail('缺少订单 id')
    const orderRes = await db.collection('hotel_orders').doc(id).get()
    if (!orderRes.data) return fail('订单不存在')
    const order = orderRes.data
    // 为订单附加房间和房型信息
    let room = null
    try {
      const roomRes = await db.collection('hotel_rooms').doc(order.roomid).get()
      room = roomRes.data
    } catch (e) { }
    let roomType = null
    if (room && room.room_type_id) {
      try {
        const typeRes = await db.collection('hotel_room_types').doc(room.room_type_id).get()
        roomType = typeRes.data
      } catch (e) { }
    }
    const result = { ...order }
    if (room) result.room = { id: room._id, name: room.name, room_type_id: room.room_type_id }
    if (roomType) {
      result.room.type = {
        id: roomType._id, name: roomType.name,
        instructions: roomType.instructions, cancel_rules: roomType.cancel_rules
      }
    }
    // 计算剩余支付时间
    if (order.status === 2 && order.pay_status === 0) {
      const createdAt = new Date(order.createdAt).getTime()
      const expireTime = createdAt + 30 * 60 * 1000
      result.pay_time = Math.max(0, Math.floor((expireTime - Date.now()) / 1000))
    }
    return ok(result)
  } catch (e) {
    console.error('handleOrderDetails 错误:', e)
    return fail(e.message)
  }
}

// POST order/more — 一次查询多个订单信息（用于支付页）
async function handleOrderMore(event, ctx) {
  try {
    const openId = ctx.OPENID
    const payload = event.payload || {}
    let ids = []
    // 支持逗号分隔的 id 列表或下划线分隔的 order_id 列表
    if (payload.ids) {
      ids = payload.ids.split(',').filter(Boolean)
    } else if (payload.orders) {
      ids = payload.orders.split('_').filter(Boolean)
    }
    if (ids.length === 0) return fail('缺少订单 id')
    let totalPrice = 0
    let orderInfo = {}
    const orderIds = []
    for (let i = 0; i < ids.length; i++) {
      let orderRes
      if (payload.ids) {
        orderRes = await db.collection('hotel_orders').doc(ids[i]).get()
      } else {
        const orderResList = await db.collection('hotel_orders').where({ order_id: ids[i] }).get()
        orderRes = { data: orderResList.data[0] }
      }
      if (!orderRes.data) continue
      const order = orderRes.data
      // 附加房间和房型信息
      let room = null, roomType = null
      try {
        const roomRes = await db.collection('hotel_rooms').doc(order.roomid).get()
        room = roomRes.data
      } catch (e) { }
      if (room && room.room_type_id) {
        try {
          const typeRes = await db.collection('hotel_room_types').doc(room.room_type_id).get()
          roomType = typeRes.data
        } catch (e) { }
      }
      orderInfo = {
        start_time: order.start_time,
        end_time: order.end_time,
        roomName: roomType ? roomType.name : '',
        instructions: roomType ? roomType.instructions : '',
        cancel_rules: roomType ? roomType.cancel_rules : ''
      }
      if (payload.ids) {
        orderIds.push(order.order_id)
      } else {
        orderIds.push(order._id)
      }
      totalPrice += Number(order.price)
    }
    if (totalPrice === 0) return fail('未找到有效订单')
    orderInfo.price = totalPrice
    orderInfo.order_id = orderIds.join('_')
    return ok(orderInfo)
  } catch (e) {
    console.error('handleOrderMore 错误:', e)
    return fail(e.message)
  }
}

// GET order/statistics
async function handleOrderStatistics(event, ctx) {
  try {
    const openId = ctx.OPENID
    if (!openId) return fail('未登录')
    const roomCount = await db.collection('hotel_orders').where({ uid: openId }).count()
    const foodCount = await db.collection('hotel_food_orders').where({ uid: openId }).count()
    return ok({ room: roomCount.total, food: foodCount.total })
  } catch (e) {
    console.error('handleOrderStatistics 错误:', e)
    return fail(e.message)
  }
}

// ====================== 支付 ======================
// POST pay/unifiedorder
// 简化实现：生成支付参数。完整的微信支付需要商户号、商户密钥等配置
async function handleUnifiedorder(event, ctx) {
  try {
    const openId = ctx.OPENID
    if (!openId) return fail('未登录')
    const payload = event.payload || {}
    const ids = payload.ids
    if (!ids) return fail('缺少订单 id')
    // 获取订单总价和合并信息
    const moreResult = await handleOrderMore({ payload: { ids: ids } }, ctx)
    if (moreResult.code !== 100010) return moreResult
    const orderData = moreResult.data
    // 微信支付统一下单（需要商户号配置才能完整实现）
    // 当前返回模拟参数，实际部署时替换为真实微信支付调用
    return ok({
      appId: '',       // 部署时填写小程序 appId
      timeStamp: Date.now().toString(),
      nonceStr: 'AGY5JX6KFQL',
      package: 'prepay_id=placeholder_' + orderData.order_id,
      signType: 'MD5',
      paySign: 'placeholder_sign'
    }, 100020)
  } catch (e) {
    console.error('handleUnifiedorder 错误:', e)
    return fail(e.message)
  }
}

// ====================== 餐饮 ======================
// GET food/list?type_id=X
async function handleFoodList(event, ctx) {
  try {
    const query = parseAction(event.action).query
    const where = {}
    if (query.type_id) where.type_id = query.type_id
    const res = await db.collection('hotel_foods').where(where).orderBy('sales', 'desc').limit(100).get()
    return ok({ rows: res.data, count: res.data.length })
  } catch (e) {
    console.error('handleFoodList 错误:', e)
    return fail(e.message)
  }
}

// GET food/types
async function handleFoodTypes(event, ctx) {
  try {
    const res = await db.collection('hotel_food_types').orderBy('orderNum', 'asc').limit(100).get()
    return ok({ rows: res.data, count: res.data.length })
  } catch (e) {
    console.error('handleFoodTypes 错误:', e)
    return fail(e.message)
  }
}

// GET food/details/:id
async function handleFoodDetails(event, ctx) {
  try {
    const params = parseAction(event.action).params
    const id = params.id || event.payload.id
    if (!id) return fail('缺少菜品 id')
    const foodRes = await db.collection('hotel_foods').doc(id).get()
    if (!foodRes.data) return fail('菜品不存在')
    // 获取评价列表
    const evalRes = await db.collection('hotel_food_evals')
      .where({ food_id: id })
      .orderBy('createdAt', 'desc')
      .get()
    return ok({ ...foodRes.data, eval: evalRes.data })
  } catch (e) {
    console.error('handleFoodDetails 错误:', e)
    return fail(e.message)
  }
}

// GET food/more?ids=X,Y,Z
async function handleFoodMore(event, ctx) {
  try {
    const query = parseAction(event.action).query
    const idStr = query.ids || ''
    const idArr = idStr.split(',').filter(Boolean)
    if (idArr.length === 0) return fail('缺少菜品 id')
    const res = await db.collection('hotel_foods')
      .where({ _id: _.in(idArr) })
      .get()
    return ok(res.data)
  } catch (e) {
    console.error('handleFoodMore 错误:', e)
    return fail(e.message)
  }
}

// POST food/create
async function handleFoodCreate(event, ctx) {
  try {
    const openId = ctx.OPENID
    if (!openId) return fail('未登录')
    const query = event.payload
    if (!query.ids || !query.room_order_id || !query.eat_time) return fail('缺少必要参数')
    // 校验房间订单是否有效
    const roomOrderRes = await db.collection('hotel_orders').where({ order_id: query.room_order_id, uid: openId }).get()
    if (roomOrderRes.data.length === 0) return fail('未找到有效的订房订单')
    const roomOrder = roomOrderRes.data[0]
    if (roomOrder.pay_status === 0 || roomOrder.status === 3 || roomOrder.status === 4) {
      return fail('房间订单状态异常')
    }
    // 校验就餐时间在入住时间范围内
    if (query.eat_time > roomOrder.end_time + ' 14:00' || query.eat_time < roomOrder.start_time + ' 9:00') {
      return fail('就餐时间不在入住范围内')
    }
    // 计算总价
    const foodIds = query.ids.split(',').filter(Boolean)
    const foodsRes = await db.collection('hotel_foods').where({ _id: _.in(foodIds) }).get()
    let totalPrice = 0
    for (let i = 0; i < foodIds.length; i++) {
      for (let j = 0; j < foodsRes.data.length; j++) {
        if (foodsRes.data[j]._id === foodIds[i]) {
          totalPrice += Number(foodsRes.data[j].price)
        }
      }
    }
    const foodOrderId = generateOrderId()
    // 创建订餐订单
    const foodOrderData = {
      order_id: foodOrderId,
      uid: openId,
      room_order_id: query.room_order_id,
      eat_time: query.eat_time,
      status: 0,       // 已订餐
      price: totalPrice,
      food_ids: query.ids,
      eva_status: 0,
      people: query.people || roomOrder.people,
      phone: query.phone || roomOrder.people_mobile,
      createdAt: new Date(),
      updatedAt: new Date()
    }
    const addRes = await db.collection('hotel_food_orders').add({ data: foodOrderData })
    // 更新房间订单的额外消费
    const newPriceExtras = Number(roomOrder.price_extras || 0) + totalPrice
    await db.collection('hotel_orders').doc(roomOrder._id).update({
      data: { price_extras: newPriceExtras, updatedAt: new Date() }
    })
    return ok({
      id: addRes._id,
      order_id: foodOrderId,
      eat_time: query.eat_time,
      price: totalPrice
    }, 100020)
  } catch (e) {
    console.error('handleFoodCreate 错误:', e)
    return fail(e.message)
  }
}

// GET food/orders?status=X
async function handleFoodOrders(event, ctx) {
  try {
    const openId = ctx.OPENID
    if (!openId) return fail('未登录')
    const query = parseAction(event.action).query
    const where = { uid: openId }
    if (event.payload && event.payload.status !== undefined) where.status = Number(event.payload.status)
    if (query.status) where.status = Number(query.status)
    const res = await db.collection('hotel_food_orders')
      .where(where)
      .orderBy('createdAt', 'desc')
      .get()
    // 为每个订单附加菜品信息
    const result = []
    for (let i = 0; i < res.data.length; i++) {
      const order = res.data[i]
      const item = { ...order }
      const foodIds = (order.food_ids || '').split(',').filter(Boolean)
      if (foodIds.length > 0) {
        try {
          const foodsRes = await db.collection('hotel_foods')
            .where({ _id: _.in(foodIds) })
            .field({ _id: true, title: true, price: true, photo: true })
            .get()
          item.foods = foodsRes.data
        } catch (e) { }
      }
      result.push(item)
    }
    return ok(result)
  } catch (e) {
    console.error('handleFoodOrders 错误:', e)
    return fail(e.message)
  }
}

// POST food/order/cancel
async function handleFoodOrderCancel(event, ctx) {
  try {
    const openId = ctx.OPENID
    if (!openId) return fail('未登录')
    const id = event.payload.id
    if (!id) return fail('缺少订单 id')
    const orderRes = await db.collection('hotel_food_orders').doc(id).get()
    if (!orderRes.data) return fail('订单不存在')
    const order = orderRes.data
    if (order.uid !== openId) return fail('无权操作')
    if (order.status !== 0) return fail('当前状态不可取消')
    // 更新房间订单的额外消费
    try {
      const roomOrderRes = await db.collection('hotel_orders').where({ order_id: order.room_order_id, uid: openId }).get()
      if (roomOrderRes.data.length > 0) {
        const roomOrder = roomOrderRes.data[0]
        const newPriceExtras = Math.max(0, Number(roomOrder.price_extras || 0) - Number(order.price))
        await db.collection('hotel_orders').doc(roomOrder._id).update({
          data: { price_extras: newPriceExtras, updatedAt: new Date() }
        })
      }
    } catch (e) { }
    // 更新订单状态为取消
    await db.collection('hotel_food_orders').doc(id).update({
      data: { status: 3, updatedAt: new Date() }
    })
    return ok(null, 100030)
  } catch (e) {
    console.error('handleFoodOrderCancel 错误:', e)
    return fail(e.message, 100031)
  }
}

// GET food/order/details/:id
async function handleFoodOrderDetails(event, ctx) {
  try {
    const openId = ctx.OPENID
    const params = parseAction(event.action).params
    const id = params.id || event.payload.id
    if (!id) return fail('缺少订单 id')
    const orderRes = await db.collection('hotel_food_orders').doc(id).get()
    if (!orderRes.data) return fail('订单不存在')
    const order = orderRes.data
    // 附加菜品信息
    const foodIds = (order.food_ids || '').split(',').filter(Boolean)
    let foods = []
    if (foodIds.length > 0) {
      try {
        const foodsRes = await db.collection('hotel_foods')
          .where({ _id: _.in(foodIds) })
          .field({ _id: true, title: true, price: true, photo: true })
          .get()
        foods = foodsRes.data
      } catch (e) { }
    }
    return ok({ ...order, foods: foods })
  } catch (e) {
    console.error('handleFoodOrderDetails 错误:', e)
    return fail(e.message)
  }
}

// POST food/eval/create
async function handleFoodEvalCreate(event, ctx) {
  try {
    const openId = ctx.OPENID
    if (!openId) return fail('未登录')
    const query = event.payload
    if (!query.orderId || !query.evals || query.evals.length === 0) return fail('缺少评价信息')
    // 校验订单状态
    const orderRes = await db.collection('hotel_food_orders').doc(query.orderId).get()
    if (!orderRes.data) return fail('订单不存在')
    const order = orderRes.data
    if (order.status !== 2) return fail('订单未完成，不可评价')
    if (order.eva_status === 1) return fail('已评价过')
    // 创建评价
    const evals = query.evals
    for (let i = 0; i < evals.length; i++) {
      await db.collection('hotel_food_evals').add({
        data: {
          food_id: evals[i].id,
          uid: openId,
          good: evals[i].good !== undefined ? evals[i].good : 1,
          name: evals[i].name || '',
          content: evals[i].content || '默认评价',
          createdAt: new Date(),
          createdBy: evals[i].name || ''
        }
      })
    }
    // 更新订单评价状态
    await db.collection('hotel_food_orders').doc(query.orderId).update({
      data: { eva_status: 1, updatedAt: new Date() }
    })
    return ok('评论成功', 100020)
  } catch (e) {
    console.error('handleFoodEvalCreate 错误:', e)
    return fail(e.message)
  }
}

// GET food/eval/my
async function handleFoodEvalMy(event, ctx) {
  try {
    const openId = ctx.OPENID
    if (!openId) return fail('未登录')
    const res = await db.collection('hotel_food_evals')
      .where({ uid: openId })
      .orderBy('createdAt', 'desc')
      .get()
    // 为每条评价附加菜品信息
    const result = []
    for (let i = 0; i < res.data.length; i++) {
      const evalItem = res.data[i]
      let food = null
      try {
        const foodRes = await db.collection('hotel_foods').doc(evalItem.food_id).get()
        if (foodRes.data) {
          food = { id: foodRes.data._id, title: foodRes.data.title, price: foodRes.data.price, photo: foodRes.data.photo }
        }
      } catch (e) { }
      result.push({ ...evalItem, food: food })
    }
    return ok(result)
  } catch (e) {
    console.error('handleFoodEvalMy 错误:', e)
    return fail(e.message)
  }
}

// ====================== 新闻 ======================
// GET news?pageNum=X&pageSize=X
async function handleNewsList(event, ctx) {
  try {
    const query = parseAction(event.action).query
    const pageNum = Number(query.pageNum) || 1
    const pageSize = Number(query.pageSize) || 10
    const res = await db.collection('hotel_articles')
      .where({ type: 'news' })
      .orderBy('createdAt', 'desc')
      .skip((pageNum - 1) * pageSize)
      .limit(pageSize)
      .get()
    const totalRes = await db.collection('hotel_articles').where({ type: 'news' }).count()
    return ok({ rows: res.data, count: totalRes.total })
  } catch (e) {
    console.error('handleNewsList 错误:', e)
    return fail(e.message)
  }
}

// GET news/details/:id
async function handleNewsDetails(event, ctx) {
  try {
    const params = parseAction(event.action).params
    const id = params.id || event.payload.id
    if (!id) return fail('缺少文章 id')
    const res = await db.collection('hotel_articles').doc(id).get()
    if (!res.data) return fail('文章不存在')
    return ok(res.data)
  } catch (e) {
    console.error('handleNewsDetails 错误:', e)
    return fail(e.message)
  }
}

// ====================== 关于我们 ======================
// GET about
async function handleAbout(event, ctx) {
  try {
    // 获取关于我们（id 可能不同，用 type 查找）
    const contactRes = await db.collection('hotel_articles')
      .where({ type: 'contact' })
      .orderBy('createdAt', 'desc')
      .limit(1)
      .get()
    const aboutRes = await db.collection('hotel_articles')
      .where({ type: 'about' })
      .orderBy('createdAt', 'desc')
      .limit(1)
      .get()
    return ok({
      contact: contactRes.data[0] || null,
      about: aboutRes.data[0] || null
    })
  } catch (e) {
    console.error('handleAbout 错误:', e)
    return fail(e.message)
  }
}

// ====================== 路由表 ======================
const routes = {
  'login':              { method: 'POST', handler: handleLogin },
  'home':               { method: 'GET',  handler: handleHome },
  'room':               { method: 'GET',  handler: handleRoomList },
  'room/details/:id':   { method: 'GET',  handler: handleRoomDetails },
  'order/buy':          { method: 'GET',  handler: handleRoomOrderBuy },
  'order/create':       { method: 'POST', handler: handleOrderCreate },
  'order/list':         { method: 'GET',  handler: handleOrderList },
  'order/cancel':       { method: 'POST', handler: handleOrderCancel },
  'order/details/:id':  { method: 'GET',  handler: handleOrderDetails },
  'order/more':         { method: 'POST', handler: handleOrderMore },
  'order/statistics':   { method: 'GET',  handler: handleOrderStatistics },
  'pay/unifiedorder':   { method: 'POST', handler: handleUnifiedorder },
  'food/list':          { method: 'GET',  handler: handleFoodList },
  'food/types':         { method: 'GET',  handler: handleFoodTypes },
  'food/details/:id':   { method: 'GET',  handler: handleFoodDetails },
  'food/more':          { method: 'GET',  handler: handleFoodMore },
  'food/create':        { method: 'POST', handler: handleFoodCreate },
  'food/orders':        { method: 'GET',  handler: handleFoodOrders },
  'food/order/cancel':  { method: 'POST', handler: handleFoodOrderCancel },
  'food/order/details/:id': { method: 'GET', handler: handleFoodOrderDetails },
  'food/eval/create':   { method: 'POST', handler: handleFoodEvalCreate },
  'food/eval/my':       { method: 'GET',  handler: handleFoodEvalMy },
  'news':               { method: 'GET',  handler: handleNewsList },
  'news/details/:id':   { method: 'GET',  handler: handleNewsDetails },
  'about':              { method: 'GET',  handler: handleAbout }
}

// ====================== 主入口 ======================
exports.main = async (event, context) => {
  const ctx = cloud.getWXContext()
  const action = event.action || ''
  const parsed = parseAction(action)
  const path = parsed.path

  // 匹配路由：先精确匹配，再尝试匹配带参数的路由模式
  let route = routes[path]
  if (!route) {
    // 尝试匹配带参数的路由模式（如 room/details/:id）
    for (const key in routes) {
      if (key.indexOf('/:id') >= 0 || key.indexOf('/details/') >= 0) {
        const keyPattern = key.replace(/\/:[^/]+/g, '/[^/]+')
        const regex = new RegExp('^' + keyPattern.replace(/\//g, '\\/') + '$')
        if (regex.test(path)) {
          route = routes[key]
          break
        }
      }
    }
  }

  if (!route) return fail('未知接口: ' + action)

  // 执行 handler
  return await route.handler(event, ctx)
}
