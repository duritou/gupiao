// 数据库初始化云函数 — 创建集合 + 写入种子数据
// 部署后通过云开发控制台「云函数 → initDatabase → 测试」触发
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()

// 10 个集合名称
const COLLECTIONS = [
  'hotel_articles',      // 文章/横幅/新闻/关于我们
  'hotel_room_types',    // 房型定义
  'hotel_rooms',         // 房间实例
  'hotel_orders',        // 订房订单
  'hotel_week_prices',   // 周价格
  'hotel_day_prices',    // 特殊日期价格
  'hotel_foods',         // 菜品
  'hotel_food_types',    // 菜品分类
  'hotel_food_orders',   // 订餐订单
  'hotel_food_evals'     // 菜品评价
]

// 创建集合（已存在则跳过）
async function createCollections() {
  const results = []
  for (let i = 0; i < COLLECTIONS.length; i++) {
    try {
      await db.createCollection(COLLECTIONS[i])
      results.push({ name: COLLECTIONS[i], status: 'created' })
    } catch (e) {
      if (e.errCode === -502005 || e.errCode === -501001) {
        // 集合已存在，跳过
        results.push({ name: COLLECTIONS[i], status: 'exists' })
      } else {
        results.push({ name: COLLECTIONS[i], status: 'error', message: e.message })
      }
    }
  }
  return results
}

// ====================== 种子数据 ======================

// ================================================================
// 图片 fileID 配置（共 49 个云存储槽位，覆盖 56 张原始图片）
// ----------------------------------------------------------------
// 云存储上传步骤：
//   1. 微信开发者工具 → 云开发 → 存储 → 新建文件夹 hotel/
//   2. 在 hotel/ 下新建 rooms/ foods/ banners/ articles/ 四个子文件夹
//   3. 将 images/hotel/ 下对应图片上传到各子文件夹
//   4. 复制每张图片的 cloud:// fileID 填入下方对应槽位
//   5. 重新部署本云函数 + 触发初始化
// ----------------------------------------------------------------
// 槽位留空 → photo 为空字符串 → 前端自动展示 images/hotel/default-*.jpg
// ================================================================
const IMG = {
  // ---- 房型（5 种 × 2 张 = 10 槽位）-------------------------------
  rooms: {
    // 精致大床房 — images/hotel/room/standard-king.jpg + standard-king-2.jpg
    jingzhi_dachuang:       'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/rooms/standard-king.jpg',
    jingzhi_dachuang_2:     'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/rooms/standard-king-2.jpg',
    // 豪华双床房 — images/hotel/room/deluxe-twin.jpg + deluxe-twin-2.jpg
    haohua_shuangchuang:    'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/rooms/deluxe-twin.jpg',
    haohua_shuangchuang_2:  'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/rooms/deluxe-twin-2.jpg',
    // 行政套房 — images/hotel/room/executive-suite.jpg + executive-suite-2.jpg
    xingzheng_taofang:      'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/rooms/executive-suite.jpg',
    xingzheng_taofang_2:    'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/rooms/executive-suite-2.jpg',
    // 家庭套房 — images/hotel/room/family-suite.jpg + family-suite-2.jpg
    jiating_taofang:        'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/rooms/family-suite.jpg',
    jiating_taofang_2:      'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/rooms/family-suite-2.jpg',
    // 总统套房 — images/hotel/room/presidential-suite.jpg + presidential-suite-2.jpg
    zongtong_taofang:       'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/rooms/presidential-suite.jpg',
    zongtong_taofang_2:     'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/rooms/presidential-suite-2.jpg',
  },

  // ---- 首页横幅（6 张）— images/hotel/banner/banner-1~6.jpg -------
  banners: {
    banner_1: 'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/banners/banner-1.jpg',
    banner_2: 'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/banners/banner-2.jpg',
    banner_3: 'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/banners/banner-3.jpg',
    banner_4: 'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/banners/banner-4.jpg',
    banner_5: 'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/banners/banner-5.jpg',
    banner_6: 'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/banners/banner-6.jpg',
  },

  // ---- 菜品（30 道）— images/hotel/food/*.jpg --------------------
  foods: {
    // 中式热菜 14 道
    fuqifeipian:        'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/foods/fuqifeipian.jpg',
    gongbao_shrimp:     'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/foods/gongbao-shrimp.jpg',
    hongshao_ribs:      'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/foods/hongshao-ribs.jpg',
    huiguorou:          'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/foods/huiguorou.jpg',
    koushuiji:          'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/foods/koushuiji.jpg',
    laziji:             'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/foods/laziji.jpg',
    shuizhu_beef:       'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/foods/shuizhu-beef.jpg',
    steamed_fish:       'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/foods/steamed-fish.jpg',
    ganbian_beans:      'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/foods/ganbian-beans.jpg',
    cucumber:           'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/foods/cucumber.jpg',
    pidan_tofu:         'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/foods/pidan-tofu.jpg',
    wood_ear:           'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/foods/wood-ear.jpg',
    garlic_scallop:     'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/foods/garlic-scallop.jpg',
    hongyou_chaoshou:   'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/foods/hongyou-chaoshou.jpg',
    // 主食小吃 3 道
    rice:               'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/foods/rice.jpg',
    yangzhou_fried_rice:'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/foods/yangzhou-fried-rice.jpg',
    dandan_noodles:     'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/foods/dandan-noodles.jpg',
    // 汤品 4 道
    suanlatang:             'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/foods/suanlatang.jpg',
    tomato_egg_soup:        'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/foods/tomato-egg-soup.jpg',
    ribs_lotus_soup:        'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/foods/ribs-lotus-soup.jpg',
    mushroom_chicken_soup:  'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/foods/mushroom-chicken-soup.jpg',
    // 饮品 5 道
    coconut_juice:      'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/foods/coconut-juice.jpg',
    cola:               'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/foods/cola.jpg',
    orange_juice:       'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/foods/orange-juice.jpg',
    longjing_tea:       'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/foods/longjing-tea.jpg',
    tsingtao_beer:      'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/foods/tsingtau-beer.jpg',
    // 甜点/其他 4 道
    double_skin_milk:   'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/foods/double-skin-milk.jpg',
    mango_pudding:      'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/foods/mango-pudding.jpg',
    osmanthus_lotus:    'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/foods/osmanthus-lotus.jpg',
    fruit_platter:      'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/foods/fruit-platter.jpg',
  },

  // ---- 文章配图（复用默认占位图，后续可替换专用图）-----------
  articles: {
    news_hotel:   '', // 酒店最新动态 → 暂用默认图（seed 中实际已改用 banner）
    contact_us:   '', // 联系我们 → 暂用默认图
    about_us:     '', // 关于我们 → 暂用默认图
  },

  // ---- 默认占位图（5 张，已上传）--------------------------------
  defaults: {
    banner:     'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/default-banner.jpg',
    room:       'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/default-room.jpg',
    food:       'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/default-food.jpg',
    food_mini:  'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/default-food-mini.jpg',
    avatar:     'cloud://cloud1-d2gek3mad0a97e6a8.636c-cloud1-d2gek3mad0a97e6a8-1436450565/hotel/default-avatar.png',
  }
}

// 房型种子数据（5 种房型，匹配 images/hotel/room/ 下 5×2=10 张图片）
const ROOM_TYPES = [
  {
    name: '精致大床房', area: '25', window: 1, wifi: 1, floor: '2-5',
    people_num: 2, smoking: 0, bed_type: '大床 1.8m', meals: 0,
    photo: IMG.rooms.jingzhi_dachuang, photo_s: IMG.rooms.jingzhi_dachuang_2,
    support: '24小时热水,空调,电视',
    bathroom: '独立卫浴', food: '不包含早餐', media: '免费WiFi',
    landscape: '城景', facilities: '空调,电视,吹风机',
    instructions: '入住时间14:00，退房时间12:00\n请携带有效身份证件',
    cancel_rules: '入住前24小时可免费取消',
    isTop: 1, createdAt: new Date(), updatedAt: new Date()
  },
  {
    name: '豪华双床房', area: '35', window: 1, wifi: 1, floor: '3-6',
    people_num: 2, smoking: 0, bed_type: '双床 1.5m', meals: 1,
    photo: IMG.rooms.haohua_shuangchuang, photo_s: IMG.rooms.haohua_shuangchuang_2,
    support: '24小时热水,空调,电视,迷你吧',
    bathroom: '独立卫浴+浴缸', food: '含双早', media: '免费WiFi,智能电视',
    landscape: '城景/山景', facilities: '空调,电视,吹风机,迷你吧,保险箱',
    instructions: '入住时间14:00，退房时间12:00\n请携带有效身份证件\n含双人早餐券',
    cancel_rules: '入住前24小时可免费取消',
    isTop: 1, createdAt: new Date(), updatedAt: new Date()
  },
  {
    name: '行政套房', area: '50', window: 1, wifi: 1, floor: '7-8',
    people_num: 2, smoking: 0, bed_type: '大床 2.0m', meals: 1,
    photo: IMG.rooms.xingzheng_taofang, photo_s: IMG.rooms.xingzheng_taofang_2,
    support: '24小时热水,空调,电视,迷你吧,行政酒廊',
    bathroom: '独立卫浴+浴缸+双台盆', food: '含双早+行政酒廊',
    media: '免费WiFi,智能电视,音响', landscape: '全景',
    facilities: '空调,电视,吹风机,迷你吧,保险箱,熨斗,浴袍',
    instructions: '入住时间14:00，退房时间12:00\n请携带有效身份证件\n含行政酒廊权益',
    cancel_rules: '入住前48小时可免费取消',
    isTop: 1, createdAt: new Date(), updatedAt: new Date()
  },
  {
    name: '家庭套房', area: '55', window: 1, wifi: 1, floor: '5-7',
    people_num: 4, smoking: 0, bed_type: '大床 1.8m + 双层床', meals: 1,
    photo: IMG.rooms.jiating_taofang, photo_s: IMG.rooms.jiating_taofang_2,
    support: '24小时热水,空调,电视,迷你吧,儿童用品',
    bathroom: '独立卫浴+浴缸+儿童洗漱台', food: '含四早', media: '免费WiFi,智能电视,儿童频道',
    landscape: '城景', facilities: '空调,电视,吹风机,迷你吧,儿童拖鞋,婴儿床',
    instructions: '入住时间14:00，退房时间12:00\n请携带有效身份证件\n含四人早餐券\n提供儿童用品',
    cancel_rules: '入住前48小时可免费取消',
    isTop: 1, createdAt: new Date(), updatedAt: new Date()
  },
  {
    name: '总统套房', area: '120', window: 1, wifi: 1, floor: '8',
    people_num: 2, smoking: 0, bed_type: '大床 2.2m', meals: 1,
    photo: IMG.rooms.zongtong_taofang, photo_s: IMG.rooms.zongtong_taofang_2,
    support: '24小时热水,空调,电视,迷你吧,行政酒廊,管家服务',
    bathroom: '独立卫浴+按摩浴缸+桑拿房', food: '含双早+行政酒廊+迎宾水果',
    media: '免费WiFi,智能电视,音响,投影仪', landscape: '全景',
    facilities: '空调,电视,吹风机,迷你吧,保险箱,熨斗,浴袍,咖啡机,会客厅',
    instructions: '入住时间14:00，退房时间12:00\n请携带有效身份证件\n含专属管家服务\n含行政酒廊权益',
    cancel_rules: '入住前72小时可免费取消',
    isTop: 1, createdAt: new Date(), updatedAt: new Date()
  }
]

// 房间实例（每种房型创建 3 间）
async function seedRooms(roomTypeIds) {
  const rooms = []
  const roomNames = {
    '精致大床房': ['201', '202', '301', '302', '401'],
    '豪华双床房': ['305', '306', '405', '406', '505'],
    '行政套房':   ['701', '702', '801', '802'],
    '家庭套房':   ['501', '502', '601', '602'],
    '总统套房':   ['888']
  }
  for (let i = 0; i < roomTypeIds.length; i++) {
    const typeData = ROOM_TYPES[i]
    const names = roomNames[typeData.name] || ['101', '102', '103']
    for (let j = 0; j < Math.min(names.length, 3); j++) {
      rooms.push({
        name: names[j],
        room_type_id: roomTypeIds[i],
        status: 1,
        createdAt: new Date(),
        updatedAt: new Date()
      })
    }
  }
  // 并行写入房间
  await Promise.all(rooms.map(room => db.collection('hotel_rooms').add({ data: room })))
  return rooms.length
}

// 周价格（5 种房型 × 3 档 = 15 条）
async function seedWeekPrices(roomTypeIds) {
  const priceMap = [
    { weeks: '1,2,3,4', price: 298 }, { weeks: '5,6', price: 398 }, { weeks: '7', price: 358 },
    { weeks: '1,2,3,4', price: 398 }, { weeks: '5,6', price: 498 }, { weeks: '7', price: 458 },
    { weeks: '1,2,3,4', price: 598 }, { weeks: '5,6', price: 698 }, { weeks: '7', price: 658 },
    { weeks: '1,2,3,4', price: 528 }, { weeks: '5,6', price: 628 }, { weeks: '7', price: 588 },
    { weeks: '1,2,3,4', price: 1688 }, { weeks: '5,6', price: 1888 }, { weeks: '7', price: 1788 }
  ]
  // 并行写入周价格
  await Promise.all(priceMap.map((p, i) => {
    const typeIdx = Math.floor(i / 3)
    return db.collection('hotel_week_prices').add({
      data: { typeId: roomTypeIds[typeIdx], weeks: p.weeks, price: p.price, status: 1, createdAt: new Date(), updatedAt: new Date() }
    })
  }))
  return priceMap.length
}

// 文章/横幅（6 条 banner + 6 条促销 + 1 条联系我们 + 1 条关于我们）
async function seedArticles() {
  const articles = [
    // ---- 首页横幅轮播（6 张，匹配 images/hotel/banner/banner-1~6.jpg）----
    { title: '欢迎光临云上酒店',   desc: '享受舒适的住宿体验',   photo: IMG.banners.banner_1, type: 'banner', status: 1, createdAt: new Date(), updatedAt: new Date() },
    { title: '夏季特惠活动',       desc: '所有房型8.8折',       photo: IMG.banners.banner_2, type: 'banner', status: 1, createdAt: new Date(), updatedAt: new Date() },
    { title: '总统套房全新上线',   desc: '极致奢华体验',         photo: IMG.banners.banner_3, type: 'banner', status: 1, createdAt: new Date(), updatedAt: new Date() },
    { title: '家庭出行首选',       desc: '家庭套房温馨舒适',     photo: IMG.banners.banner_4, type: 'banner', status: 1, createdAt: new Date(), updatedAt: new Date() },
    { title: '订餐服务升级',       desc: '30道精选菜品等您品尝', photo: IMG.banners.banner_5, type: 'banner', status: 1, createdAt: new Date(), updatedAt: new Date() },
    { title: '会员专享礼遇',       desc: '注册即享专属折扣',     photo: IMG.banners.banner_6, type: 'banner', status: 1, createdAt: new Date(), updatedAt: new Date() },

    // ---- 促销活动文章（6 条，显示在"促销"页）----
    {
      title: '🔥 夏季特惠 · 全场房型8.8折',
      desc: '即日起至8月31日，所有房型享受8.8折优惠',
      content: '<p><strong>活动时间：</strong>即日起至8月31日</p><p><strong>活动内容：</strong>所有房型享受8.8折优惠，不限房晚数。</p><p>无论是商务出行还是家庭旅游，云上酒店为您提供最优惠的价格。</p>',
      photo: IMG.banners.banner_1,
      type: 'news', status: 1, createdAt: new Date(Date.now() - 5 * 86400000), updatedAt: new Date()
    },
    {
      title: '🎁 新客专享 · 首单立减50元',
      desc: '首次预订立减50元，注册即享会员权益',
      content: '<p><strong>适用对象：</strong>首次在云上酒店下单的用户</p><p><strong>优惠力度：</strong>首单立减50元</p><p>注册即享会员权益，积分可兑换免费房晚、餐饮折扣等丰富礼品。</p>',
      photo: IMG.banners.banner_2,
      type: 'news', status: 1, createdAt: new Date(Date.now() - 4 * 86400000), updatedAt: new Date()
    },
    {
      title: '👑 会员福利 · 积分兑换免费房晚',
      desc: '消费积分当钱花，最高可兑换3晚免费入住',
      content: '<p><strong>积分规则：</strong>每消费1元积1分</p><p><strong>兑换权益：</strong></p><p>· 500积分 → 精致大床房1晚</p><p>· 800积分 → 豪华双床房1晚</p><p>· 1500积分 → 行政套房1晚</p>',
      photo: IMG.banners.banner_3,
      type: 'news', status: 1, createdAt: new Date(Date.now() - 3 * 86400000), updatedAt: new Date()
    },
    {
      title: '💼 商务出行 · 行政套房限时特价',
      desc: '行政套房低至599元/晚，含双早+会议室使用权',
      content: '<p><strong>活动房型：</strong>行政套房</p><p><strong>特价：</strong>599元/晚（原价899元）</p><p>含双人自助早餐 + 2小时会议室免费使用权，商务出行的最佳选择。</p>',
      photo: IMG.banners.banner_4,
      type: 'news', status: 1, createdAt: new Date(Date.now() - 2 * 86400000), updatedAt: new Date()
    },
    {
      title: '👨‍👩‍👧‍👦 家庭出游 · 亲子房型推荐',
      desc: '家庭套房周末特惠，儿童免费加床+赠儿童套餐',
      content: '<p><strong>活动房型：</strong>家庭套房</p><p><strong>周末特惠：</strong>连住两晚享9折，儿童免费加床</p><p>赠送儿童套餐一份，让全家出行更轻松愉快。</p>',
      photo: IMG.banners.banner_5,
      type: 'news', status: 1, createdAt: new Date(Date.now() - 1 * 86400000), updatedAt: new Date()
    },
    {
      title: '酒店最新动态',
      desc: '了解更多酒店资讯',
      content: '<p>欢迎来到云上酒店，我们致力于为您提供最舒适的住宿体验。</p>',
      photo: IMG.banners.banner_6,
      type: 'news', status: 1, createdAt: new Date(), updatedAt: new Date()
    },

    // ---- 其他内容页 ----
    {
      title: '联系我们',
      desc: '酒店联系方式',
      content: '<p>地址：XX市XX区XX路100号</p><p>电话：400-XXX-XXXX</p><p>邮箱：info@yunshang-hotel.com</p>',
      photo: IMG.banners.banner_6,
      type: 'contact', status: 1, createdAt: new Date(), updatedAt: new Date()
    },
    {
      title: '关于我们',
      desc: '了解云上酒店',
      content: '<p>云上酒店创立于2020年，致力于打造高品质住宿服务。</p><p>我们拥有多种房型，满足商务、旅游、家庭出行等不同需求。</p>',
      photo: IMG.banners.banner_6,
      type: 'about', status: 1, createdAt: new Date(), updatedAt: new Date()
    }
  ]
  // 并行写入，避免 14 篇串行超时
  await Promise.all(articles.map(a => db.collection('hotel_articles').add({ data: a })))
  return articles.length
}

// 菜品分类（5 类，对应 images/hotel/food/ 下 30 道菜品）
async function seedFoodTypes() {
  const types = [
    { name: '中式热菜', orderNum: 1, createdAt: new Date() },
    { name: '主食小吃', orderNum: 2, createdAt: new Date() },
    { name: '汤品',     orderNum: 3, createdAt: new Date() },
    { name: '饮品',     orderNum: 4, createdAt: new Date() },
    { name: '甜点/其他', orderNum: 5, createdAt: new Date() }
  ]
  const results = await Promise.all(types.map(t => db.collection('hotel_food_types').add({ data: t })))
  return results.map(r => r._id)
}

// 菜品（30 道，匹配 images/hotel/food/ 下全部图片，并行写入避免超时）
async function seedFoods(typeIds) {
  // typeIds[0]=中式热菜 typeIds[1]=主食小吃 typeIds[2]=汤品 typeIds[3]=饮品 typeIds[4]=甜点/其他
  const foods = [
    // 中式热菜 14 道
    { title: '夫妻肺片',     type_id: typeIds[0], price: 28, photo: IMG.foods.fuqifeipian,     sales: 88,  createdAt: new Date() },
    { title: '宫保虾仁',     type_id: typeIds[0], price: 48, photo: IMG.foods.gongbao_shrimp,   sales: 95,  createdAt: new Date() },
    { title: '红烧排骨',     type_id: typeIds[0], price: 45, photo: IMG.foods.hongshao_ribs,    sales: 110, createdAt: new Date() },
    { title: '回锅肉',       type_id: typeIds[0], price: 32, photo: IMG.foods.huiguorou,        sales: 72,  createdAt: new Date() },
    { title: '口水鸡',       type_id: typeIds[0], price: 35, photo: IMG.foods.koushuiji,        sales: 80,  createdAt: new Date() },
    { title: '辣子鸡',       type_id: typeIds[0], price: 38, photo: IMG.foods.laziji,           sales: 65,  createdAt: new Date() },
    { title: '水煮牛肉',     type_id: typeIds[0], price: 52, photo: IMG.foods.shuizhu_beef,     sales: 78,  createdAt: new Date() },
    { title: '清蒸鱼',       type_id: typeIds[0], price: 48, photo: IMG.foods.steamed_fish,     sales: 55,  createdAt: new Date() },
    { title: '干煸四季豆',   type_id: typeIds[0], price: 22, photo: IMG.foods.ganbian_beans,    sales: 60,  createdAt: new Date() },
    { title: '凉拌黄瓜',     type_id: typeIds[0], price: 16, photo: IMG.foods.cucumber,         sales: 92,  createdAt: new Date() },
    { title: '皮蛋豆腐',     type_id: typeIds[0], price: 18, photo: IMG.foods.pidan_tofu,       sales: 70,  createdAt: new Date() },
    { title: '凉拌木耳',     type_id: typeIds[0], price: 18, photo: IMG.foods.wood_ear,         sales: 68,  createdAt: new Date() },
    { title: '蒜蓉扇贝',     type_id: typeIds[0], price: 42, photo: IMG.foods.garlic_scallop,   sales: 45,  createdAt: new Date() },
    { title: '红油抄手',     type_id: typeIds[0], price: 22, photo: IMG.foods.hongyou_chaoshou, sales: 85,  createdAt: new Date() },

    // 主食小吃 3 道
    { title: '米饭',         type_id: typeIds[1], price: 3,  photo: IMG.foods.rice,               sales: 200, createdAt: new Date() },
    { title: '扬州炒饭',     type_id: typeIds[1], price: 18, photo: IMG.foods.yangzhou_fried_rice, sales: 90,  createdAt: new Date() },
    { title: '担担面',       type_id: typeIds[1], price: 15, photo: IMG.foods.dandan_noodles,     sales: 75,  createdAt: new Date() },

    // 汤品 4 道
    { title: '酸辣汤',         type_id: typeIds[2], price: 18, photo: IMG.foods.suanlatang,            sales: 90, createdAt: new Date() },
    { title: '番茄蛋汤',       type_id: typeIds[2], price: 15, photo: IMG.foods.tomato_egg_soup,       sales: 100, createdAt: new Date() },
    { title: '排骨莲藕汤',     type_id: typeIds[2], price: 28, photo: IMG.foods.ribs_lotus_soup,       sales: 65, createdAt: new Date() },
    { title: '菌菇鸡汤',       type_id: typeIds[2], price: 35, photo: IMG.foods.mushroom_chicken_soup, sales: 55, createdAt: new Date() },

    // 饮品 5 道
    { title: '椰子汁',       type_id: typeIds[3], price: 12, photo: IMG.foods.coconut_juice, sales: 120, createdAt: new Date() },
    { title: '可乐',         type_id: typeIds[3], price: 8,  photo: IMG.foods.cola,         sales: 180, createdAt: new Date() },
    { title: '橙汁',         type_id: typeIds[3], price: 15, photo: IMG.foods.orange_juice, sales: 130, createdAt: new Date() },
    { title: '龙井茶',       type_id: typeIds[3], price: 28, photo: IMG.foods.longjing_tea, sales: 50,  createdAt: new Date() },
    { title: '青岛啤酒',     type_id: typeIds[3], price: 12, photo: IMG.foods.tsingtao_beer, sales: 75, createdAt: new Date() },

    // 甜点/其他 4 道
    { title: '双皮奶',       type_id: typeIds[4], price: 15, photo: IMG.foods.double_skin_milk, sales: 70, createdAt: new Date() },
    { title: '芒果布丁',     type_id: typeIds[4], price: 18, photo: IMG.foods.mango_pudding,    sales: 55, createdAt: new Date() },
    { title: '桂花莲藕',     type_id: typeIds[4], price: 20, photo: IMG.foods.osmanthus_lotus,  sales: 40, createdAt: new Date() },
    { title: '水果拼盘',     type_id: typeIds[4], price: 28, photo: IMG.foods.fruit_platter,    sales: 48, createdAt: new Date() }
  ]
  // 并行写入，避免 3 秒超时
  await Promise.all(foods.map(f => db.collection('hotel_foods').add({ data: f })))
  return foods.length
}

// ====================== 清空旧数据（防止重复） ======================
// 微信云数据库 where().remove() 批量删除（比逐条删快 100 倍）
async function clearCollection(name) {
  const _ = db.command
  let total = 0
  while (true) {
    try {
      const res = await db.collection(name).where({ _id: _.exists(true) }).remove()
      const removed = (res.stats && res.stats.removed) || 0
      total += removed
      if (removed === 0) break
    } catch (e) {
      // 集合不存在等异常，跳过
      console.log(`  ${name} 清空跳过: ${e.errMsg || e.message}`)
      break
    }
  }
  console.log(`  已清空 ${name}: ${total} 条`)
  return total
}

// 清空全部业务集合（并行，避免串行超时）
async function clearAll() {
  await Promise.all(COLLECTIONS.map(name => clearCollection(name)))
}

// ====================== 主入口 ======================
exports.main = async (event, context) => {
  console.log('=== 开始初始化数据库 ===')

  const forceClear = event.clear !== false // 默认 true，传 {clear: false} 可跳过清空

  // 0. 清空旧数据（防止重复记录）
  if (forceClear) {
    console.log('步骤 0/4: 清空已有数据')
    await clearAll()
    console.log('已有数据已清空')
  }

  // 1. 创建集合
  console.log('步骤 1/4: 创建集合')
  const collectionResults = await createCollections()
  console.log('集合创建结果:', JSON.stringify(collectionResults))

  // 2. 写入文章
  console.log('步骤 2/4: 写入种子文章')
  const articleIds = await seedArticles()
  console.log('文章写入完成:', articleIds.length, '篇')

  // 3. 写入房型 + 房间 + 价格
  console.log('步骤 3/4: 写入房型/房间/价格')
  const roomTypeResults = await Promise.all(ROOM_TYPES.map(rt => db.collection('hotel_room_types').add({ data: rt })))
  const roomTypeIds = roomTypeResults.map(r => r._id)
  console.log('房型写入完成:', roomTypeIds.length)
  const roomCount = await seedRooms(roomTypeIds)
  console.log('房间写入完成:', roomCount, '间')
  const weekPriceCount = await seedWeekPrices(roomTypeIds)
  console.log('周价格写入完成:', weekPriceCount, '条')
  // 特殊日期价格保持空（按需添加）

  // 4. 写入菜品
  console.log('步骤 4/4: 写入菜品分类和菜品')
  const foodTypeIds = await seedFoodTypes()
  console.log('菜品分类写入完成:', foodTypeIds.length)
  const foodCount = await seedFoods(foodTypeIds)
  console.log('菜品写入完成:', foodCount, '道')

  console.log('=== 数据库初始化完成 ===')
  return {
    code: 100010,
    data: {
      collections: collectionResults,
      articles: articleIds.length,
      roomTypes: roomTypeIds.length,
      rooms: roomCount,
      weekPrices: weekPriceCount,
      foodTypes: foodTypeIds.length,
      foods: foodCount
    },
    message: '数据库初始化成功'
  }
}
