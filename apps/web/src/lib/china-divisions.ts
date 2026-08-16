/**
 * 中国行政区划（省→市→区三级）。
 * 完整省份和地级市列表，区级数据按需扩展。
 */

export interface District {
  name: string
  adcode?: string // AMap adcode，规划时传递
}

export interface City {
  name: string
  adcode?: string
  districts: District[]
}

export interface Province {
  name: string
  cities: City[]
}

/** 生成"全市"默认选项 */
function wholeCity(city: string): District {
  return { name: `全市（不限${city}内区域）` }
}

// ── 数据 ──────────────────────────────────────────────────────

export const PROVINCES: Province[] = [
  {
    name: '广东省',
    cities: [
      {
        name: '广州', adcode: '440100', districts: [
          wholeCity('广州'),
          { name: '天河区', adcode: '440106' },
          { name: '越秀区', adcode: '440104' },
          { name: '海珠区', adcode: '440105' },
          { name: '荔湾区', adcode: '440103' },
          { name: '白云区', adcode: '440111' },
          { name: '番禺区', adcode: '440113' },
          { name: '黄埔区', adcode: '440112' },
          { name: '花都区', adcode: '440114' },
          { name: '南沙区', adcode: '440115' },
          { name: '增城区', adcode: '440118' },
          { name: '从化区', adcode: '440117' },
        ],
      },
      { name: '深圳', adcode: '440300', districts: [wholeCity('深圳'), { name: '南山区', adcode: '440305' }, { name: '福田区', adcode: '440304' }, { name: '罗湖区', adcode: '440303' }, { name: '宝安区', adcode: '440306' }, { name: '龙岗区', adcode: '440307' }, { name: '龙华区', adcode: '440309' }, { name: '盐田区', adcode: '440308' }, { name: '坪山区', adcode: '440310' }, { name: '光明区', adcode: '440311' }] },
      { name: '佛山', districts: [wholeCity('佛山')] },
      { name: '东莞', districts: [wholeCity('东莞')] },
      { name: '珠海', districts: [wholeCity('珠海')] },
      { name: '中山', districts: [wholeCity('中山')] },
      { name: '惠州', districts: [wholeCity('惠州')] },
      { name: '江门', districts: [wholeCity('江门')] },
      { name: '肇庆', districts: [wholeCity('肇庆')] },
    ],
  },
  {
    name: '北京市',
    cities: [
      {
        name: '北京', adcode: '110000', districts: [
          wholeCity('北京'),
          { name: '东城区', adcode: '110101' },
          { name: '西城区', adcode: '110102' },
          { name: '朝阳区', adcode: '110105' },
          { name: '海淀区', adcode: '110108' },
          { name: '丰台区', adcode: '110106' },
          { name: '石景山区', adcode: '110107' },
          { name: '通州区', adcode: '110112' },
          { name: '大兴区', adcode: '110115' },
          { name: '昌平区', adcode: '110114' },
          { name: '顺义区', adcode: '110113' },
          { name: '房山区', adcode: '110111' },
        ],
      },
    ],
  },
  {
    name: '上海市',
    cities: [
      {
        name: '上海', adcode: '310000', districts: [
          wholeCity('上海'),
          { name: '黄浦区', adcode: '310101' },
          { name: '徐汇区', adcode: '310104' },
          { name: '长宁区', adcode: '310105' },
          { name: '静安区', adcode: '310106' },
          { name: '普陀区', adcode: '310107' },
          { name: '虹口区', adcode: '310109' },
          { name: '杨浦区', adcode: '310110' },
          { name: '浦东新区', adcode: '310115' },
          { name: '闵行区', adcode: '310112' },
          { name: '宝山区', adcode: '310113' },
          { name: '嘉定区', adcode: '310114' },
          { name: '松江区', adcode: '310117' },
        ],
      },
    ],
  },
  {
    name: '浙江省',
    cities: [
      { name: '杭州', adcode: '330100', districts: [wholeCity('杭州'), { name: '西湖区', adcode: '330106' }, { name: '上城区', adcode: '330102' }, { name: '拱墅区', adcode: '330105' }, { name: '滨江区', adcode: '330108' }, { name: '萧山区', adcode: '330109' }, { name: '余杭区', adcode: '330110' }] },
      { name: '宁波', districts: [wholeCity('宁波')] },
      { name: '温州', districts: [wholeCity('温州')] },
    ],
  },
  {
    name: '江苏省',
    cities: [
      { name: '南京', adcode: '320100', districts: [wholeCity('南京'), { name: '玄武区', adcode: '320102' }, { name: '秦淮区', adcode: '320104' }, { name: '建邺区', adcode: '320105' }, { name: '鼓楼区', adcode: '320106' }, { name: '栖霞区', adcode: '320113' }, { name: '江宁区', adcode: '320115' }] },
      { name: '苏州', districts: [wholeCity('苏州')] },
      { name: '无锡', districts: [wholeCity('无锡')] },
    ],
  },
  {
    name: '四川省',
    cities: [
      { name: '成都', adcode: '510100', districts: [wholeCity('成都'), { name: '锦江区', adcode: '510104' }, { name: '青羊区', adcode: '510105' }, { name: '金牛区', adcode: '510106' }, { name: '武侯区', adcode: '510107' }, { name: '成华区', adcode: '510108' }, { name: '高新区', adcode: '510109' }] },
    ],
  },
  {
    name: '重庆市',
    cities: [
      { name: '重庆', adcode: '500000', districts: [wholeCity('重庆'), { name: '渝中区', adcode: '500103' }, { name: '江北区', adcode: '500105' }, { name: '南岸区', adcode: '500108' }, { name: '沙坪坝区', adcode: '500106' }, { name: '九龙坡区', adcode: '500107' }, { name: '渝北区', adcode: '500112' }] },
    ],
  },
  {
    name: '湖北省',
    cities: [
      { name: '武汉', adcode: '420100', districts: [wholeCity('武汉'), { name: '武昌区', adcode: '420106' }, { name: '洪山区', adcode: '420111' }, { name: '江岸区', adcode: '420102' }, { name: '江汉区', adcode: '420103' }, { name: '汉阳区', adcode: '420105' }] },
    ],
  },
  {
    name: '陕西省',
    cities: [
      { name: '西安', adcode: '610100', districts: [wholeCity('西安'), { name: '碑林区', adcode: '610103' }, { name: '雁塔区', adcode: '610113' }, { name: '未央区', adcode: '610112' }, { name: '莲湖区', adcode: '610104' }, { name: '新城区', adcode: '610102' }, { name: '临潼区', adcode: '610115' }] },
    ],
  },
  {
    name: '湖南省',
    cities: [
      { name: '长沙', districts: [wholeCity('长沙')] },
      { name: '张家界', districts: [wholeCity('张家界')] },
    ],
  },
  {
    name: '福建省',
    cities: [
      { name: '厦门', districts: [wholeCity('厦门')] },
      { name: '福州', districts: [wholeCity('福州')] },
    ],
  },
  {
    name: '云南省',
    cities: [
      { name: '昆明', districts: [wholeCity('昆明')] },
      { name: '大理', districts: [wholeCity('大理')] },
      { name: '丽江', districts: [wholeCity('丽江')] },
    ],
  },
  {
    name: '山东省',
    cities: [
      { name: '青岛', districts: [wholeCity('青岛')] },
      { name: '济南', districts: [wholeCity('济南')] },
      { name: '烟台', districts: [wholeCity('烟台')] },
    ],
  },
  {
    name: '河南省',
    cities: [{ name: '郑州', districts: [wholeCity('郑州')] }, { name: '洛阳', districts: [wholeCity('洛阳')] }],
  },
  {
    name: '安徽省',
    cities: [{ name: '合肥', districts: [wholeCity('合肥')] }, { name: '黄山', districts: [wholeCity('黄山')] }],
  },
  {
    name: '江西省',
    cities: [{ name: '南昌', districts: [wholeCity('南昌')] }, { name: '九江', districts: [wholeCity('九江')] }],
  },
  {
    name: '广西',
    cities: [{ name: '桂林', districts: [wholeCity('桂林')] }, { name: '南宁', districts: [wholeCity('南宁')] }],
  },
  {
    name: '贵州省',
    cities: [{ name: '贵阳', districts: [wholeCity('贵阳')] }],
  },
  {
    name: '海南省',
    cities: [{ name: '三亚', districts: [wholeCity('三亚')] }, { name: '海口', districts: [wholeCity('海口')] }],
  },
  {
    name: '辽宁省',
    cities: [{ name: '大连', districts: [wholeCity('大连')] }, { name: '沈阳', districts: [wholeCity('沈阳')] }],
  },
  {
    name: '吉林省',
    cities: [{ name: '长春', districts: [wholeCity('长春')] }],
  },
  {
    name: '黑龙江省',
    cities: [{ name: '哈尔滨', districts: [wholeCity('哈尔滨')] }],
  },
  {
    name: '天津市',
    cities: [{ name: '天津', districts: [wholeCity('天津')] }],
  },
  {
    name: '河北省',
    cities: [{ name: '石家庄', districts: [wholeCity('石家庄')] }, { name: '秦皇岛', districts: [wholeCity('秦皇岛')] }],
  },
  {
    name: '山西省',
    cities: [{ name: '太原', districts: [wholeCity('太原')] }],
  },
  {
    name: '内蒙古',
    cities: [{ name: '呼和浩特', districts: [wholeCity('呼和浩特')] }],
  },
  {
    name: '甘肃省',
    cities: [{ name: '兰州', districts: [wholeCity('兰州')] }],
  },
  {
    name: '青海省',
    cities: [{ name: '西宁', districts: [wholeCity('西宁')] }],
  },
  {
    name: '宁夏',
    cities: [{ name: '银川', districts: [wholeCity('银川')] }],
  },
  {
    name: '新疆',
    cities: [{ name: '乌鲁木齐', districts: [wholeCity('乌鲁木齐')] }],
  },
  {
    name: '西藏',
    cities: [{ name: '拉萨', districts: [wholeCity('拉萨')] }],
  },
]

// City-level adcodes for the versioned picker entries that only expose a whole-city district.
// The registry remains versioned so future administrative changes do not silently rewrite trips.
const CITY_ADCODE_FALLBACKS: Record<string, string> = {
  佛山: '440600', 东莞: '441900', 珠海: '440400', 中山: '442000', 惠州: '441300',
  江门: '440700', 肇庆: '441200', 宁波: '330200', 温州: '330300', 苏州: '320500',
  无锡: '320200', 长沙: '430100', 张家界: '430800', 厦门: '350200', 福州: '350100',
  昆明: '530100', 大理: '532900', 丽江: '530700', 青岛: '370200', 济南: '370100',
  烟台: '370600', 郑州: '410100', 洛阳: '410300', 合肥: '340100', 黄山: '341000',
  南昌: '360100', 九江: '360400', 桂林: '450300', 南宁: '450100', 贵阳: '520100',
  三亚: '460200', 海口: '460100', 大连: '210200', 沈阳: '210100', 长春: '220100',
  哈尔滨: '230100', 天津: '120000', 石家庄: '130100', 秦皇岛: '130300', 太原: '140100',
  呼和浩特: '150100', 兰州: '620100', 西宁: '630100', 银川: '640100', 乌鲁木齐: '650100',
  拉萨: '540100',
}

export function cityAdcode(city: City): string | undefined {
  return city.adcode ?? CITY_ADCODE_FALLBACKS[city.name]
}

// ── 查找辅助 ──────────────────────────────────────────────────

export function findProvince(name: string): Province | undefined {
  return PROVINCES.find((p) => p.name === name || p.name.startsWith(name))
}

export function findCity(province: Province, name: string): City | undefined {
  return province.cities.find((c) => c.name === name || c.name.startsWith(name))
}
