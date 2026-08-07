package io.github.tobehardoo.trippilot.trip;

import java.util.List;
import java.util.Map;

/**
 * Static administrative region catalog (province -> city -> district) used to
 * validate structured trip destinations. Codes are AMap adcodes; the data
 * is a compact subset of the web's china-divisions.ts. A structured destination
 * must reference codes that exist here with matching names.
 */
public final class RegionCatalog {

    private RegionCatalog() {
    }

    private static final Map<String, String> PROVINCES = Map.ofEntries(
            Map.entry("110000", "北京市"),
            Map.entry("120000", "天津市"),
            Map.entry("130000", "河北省"),
            Map.entry("140000", "山西省"),
            Map.entry("150000", "内蒙古"),
            Map.entry("210000", "辽宁省"),
            Map.entry("220000", "吉林省"),
            Map.entry("230000", "黑龙江省"),
            Map.entry("310000", "上海市"),
            Map.entry("320000", "江苏省"),
            Map.entry("330000", "浙江省"),
            Map.entry("340000", "安徽省"),
            Map.entry("350000", "福建省"),
            Map.entry("360000", "江西省"),
            Map.entry("370000", "山东省"),
            Map.entry("410000", "河南省"),
            Map.entry("420000", "湖北省"),
            Map.entry("430000", "湖南省"),
            Map.entry("440000", "广东省"),
            Map.entry("450000", "广西"),
            Map.entry("460000", "海南省"),
            Map.entry("500000", "重庆市"),
            Map.entry("510000", "四川省"),
            Map.entry("520000", "贵州省"),
            Map.entry("530000", "云南省"),
            Map.entry("540000", "西藏"),
            Map.entry("610000", "陕西省"),
            Map.entry("620000", "甘肃省"),
            Map.entry("630000", "青海省"),
            Map.entry("640000", "宁夏"),
            Map.entry("650000", "新疆")
    );

    private static final Map<String, List<String>> PROVINCE_CITIES = Map.ofEntries(
            Map.entry("110000", List.of("北京")),
            Map.entry("120000", List.of()),
            Map.entry("130000", List.of()),
            Map.entry("140000", List.of()),
            Map.entry("150000", List.of()),
            Map.entry("210000", List.of()),
            Map.entry("220000", List.of()),
            Map.entry("230000", List.of()),
            Map.entry("310000", List.of("上海")),
            Map.entry("320000", List.of("南京")),
            Map.entry("330000", List.of("杭州")),
            Map.entry("340000", List.of()),
            Map.entry("350000", List.of()),
            Map.entry("360000", List.of()),
            Map.entry("370000", List.of()),
            Map.entry("410000", List.of()),
            Map.entry("420000", List.of("武汉")),
            Map.entry("430000", List.of()),
            Map.entry("440000", List.of("广州", "深圳")),
            Map.entry("450000", List.of()),
            Map.entry("460000", List.of()),
            Map.entry("500000", List.of()),
            Map.entry("510000", List.of("成都")),
            Map.entry("520000", List.of()),
            Map.entry("530000", List.of()),
            Map.entry("540000", List.of()),
            Map.entry("610000", List.of("西安")),
            Map.entry("620000", List.of()),
            Map.entry("630000", List.of()),
            Map.entry("640000", List.of()),
            Map.entry("650000", List.of())
    );

    private static final Map<String, String> CITY_CODES = Map.ofEntries(
            Map.entry("110000", "北京"),
            Map.entry("310000", "上海"),
            Map.entry("320100", "南京"),
            Map.entry("330100", "杭州"),
            Map.entry("420100", "武汉"),
            Map.entry("440100", "广州"),
            Map.entry("440300", "深圳"),
            Map.entry("510100", "成都"),
            Map.entry("610100", "西安")
    );

    private static final Map<String, String> CITY_PROVINCE = Map.ofEntries(
            Map.entry("110000", "110000"),
            Map.entry("310000", "310000"),
            Map.entry("320100", "320000"),
            Map.entry("330100", "330000"),
            Map.entry("420100", "420000"),
            Map.entry("440100", "440000"),
            Map.entry("440300", "440000"),
            Map.entry("510100", "510000"),
            Map.entry("610100", "610000")
    );

    private static final Map<String, List<String>> CITY_DISTRICTS = Map.ofEntries(
            Map.entry("110000", List.of("东城区", "西城区", "朝阳区", "海淀区", "丰台区", "石景山区", "通州区", "大兴区", "昌平区", "顺义区", "房山区")),
            Map.entry("310000", List.of("黄浦区", "徐汇区", "长宁区", "静安区", "普陀区", "虹口区", "杨浦区", "浦东新区", "闵行区", "宝山区", "嘉定区", "松江区")),
            Map.entry("320100", List.of("玄武区", "秦淮区", "建邺区", "鼓楼区", "栖霞区", "江宁区")),
            Map.entry("330100", List.of("西湖区", "上城区", "拱墅区", "滨江区", "萧山区", "余杭区")),
            Map.entry("420100", List.of("武昌区", "洪山区", "江岸区", "江汉区", "汉阳区")),
            Map.entry("440100", List.of("天河区", "越秀区", "海珠区", "荔湾区", "白云区", "番禺区", "黄埔区", "花都区", "南沙区", "增城区", "从化区")),
            Map.entry("440300", List.of("南山区", "福田区", "罗湖区", "宝安区", "龙岗区", "龙华区", "盐田区", "坪山区", "光明区")),
            Map.entry("510100", List.of("锦江区", "青羊区", "金牛区", "武侯区", "成华区")),
            Map.entry("610100", List.of("碑林区", "雁塔区", "未央区", "莲湖区", "新城区", "临潼区"))
    );

    private static final Map<String, String> DISTRICT_CODES = Map.ofEntries(
            Map.entry("110101", "东城区"),
            Map.entry("110102", "西城区"),
            Map.entry("110105", "朝阳区"),
            Map.entry("110106", "丰台区"),
            Map.entry("110107", "石景山区"),
            Map.entry("110108", "海淀区"),
            Map.entry("110111", "房山区"),
            Map.entry("110112", "通州区"),
            Map.entry("110113", "顺义区"),
            Map.entry("110114", "昌平区"),
            Map.entry("110115", "大兴区"),
            Map.entry("310101", "黄浦区"),
            Map.entry("310104", "徐汇区"),
            Map.entry("310105", "长宁区"),
            Map.entry("310106", "静安区"),
            Map.entry("310107", "普陀区"),
            Map.entry("310109", "虹口区"),
            Map.entry("310110", "杨浦区"),
            Map.entry("310112", "闵行区"),
            Map.entry("310113", "宝山区"),
            Map.entry("310114", "嘉定区"),
            Map.entry("310115", "浦东新区"),
            Map.entry("310117", "松江区"),
            Map.entry("320102", "玄武区"),
            Map.entry("320104", "秦淮区"),
            Map.entry("320105", "建邺区"),
            Map.entry("320106", "鼓楼区"),
            Map.entry("320113", "栖霞区"),
            Map.entry("320115", "江宁区"),
            Map.entry("330102", "上城区"),
            Map.entry("330105", "拱墅区"),
            Map.entry("330106", "西湖区"),
            Map.entry("330108", "滨江区"),
            Map.entry("330109", "萧山区"),
            Map.entry("330110", "余杭区"),
            Map.entry("420102", "江岸区"),
            Map.entry("420103", "江汉区"),
            Map.entry("420105", "汉阳区"),
            Map.entry("420106", "武昌区"),
            Map.entry("420111", "洪山区"),
            Map.entry("440103", "荔湾区"),
            Map.entry("440104", "越秀区"),
            Map.entry("440105", "海珠区"),
            Map.entry("440106", "天河区"),
            Map.entry("440111", "白云区"),
            Map.entry("440112", "黄埔区"),
            Map.entry("440113", "番禺区"),
            Map.entry("440114", "花都区"),
            Map.entry("440115", "南沙区"),
            Map.entry("440117", "从化区"),
            Map.entry("440118", "增城区"),
            Map.entry("440303", "罗湖区"),
            Map.entry("440304", "福田区"),
            Map.entry("440305", "南山区"),
            Map.entry("440306", "宝安区"),
            Map.entry("440307", "龙岗区"),
            Map.entry("440308", "盐田区"),
            Map.entry("440309", "龙华区"),
            Map.entry("440310", "坪山区"),
            Map.entry("440311", "光明区"),
            Map.entry("510104", "锦江区"),
            Map.entry("510105", "青羊区"),
            Map.entry("510106", "金牛区"),
            Map.entry("510107", "武侯区"),
            Map.entry("510108", "成华区"),
            Map.entry("610102", "新城区"),
            Map.entry("610103", "碑林区"),
            Map.entry("610104", "莲湖区"),
            Map.entry("610112", "未央区"),
            Map.entry("610113", "雁塔区"),
            Map.entry("610115", "临潼区")
    );

    private static final Map<String, String> DISTRICT_CITY = Map.ofEntries(
            Map.entry("110101", "110000"),
            Map.entry("110102", "110000"),
            Map.entry("110105", "110000"),
            Map.entry("110106", "110000"),
            Map.entry("110107", "110000"),
            Map.entry("110108", "110000"),
            Map.entry("110111", "110000"),
            Map.entry("110112", "110000"),
            Map.entry("110113", "110000"),
            Map.entry("110114", "110000"),
            Map.entry("110115", "110000"),
            Map.entry("310101", "310000"),
            Map.entry("310104", "310000"),
            Map.entry("310105", "310000"),
            Map.entry("310106", "310000"),
            Map.entry("310107", "310000"),
            Map.entry("310109", "310000"),
            Map.entry("310110", "310000"),
            Map.entry("310112", "310000"),
            Map.entry("310113", "310000"),
            Map.entry("310114", "310000"),
            Map.entry("310115", "310000"),
            Map.entry("310117", "310000"),
            Map.entry("320102", "320100"),
            Map.entry("320104", "320100"),
            Map.entry("320105", "320100"),
            Map.entry("320106", "320100"),
            Map.entry("320113", "320100"),
            Map.entry("320115", "320100"),
            Map.entry("330102", "330100"),
            Map.entry("330105", "330100"),
            Map.entry("330106", "330100"),
            Map.entry("330108", "330100"),
            Map.entry("330109", "330100"),
            Map.entry("330110", "330100"),
            Map.entry("420102", "420100"),
            Map.entry("420103", "420100"),
            Map.entry("420105", "420100"),
            Map.entry("420106", "420100"),
            Map.entry("420111", "420100"),
            Map.entry("440103", "440100"),
            Map.entry("440104", "440100"),
            Map.entry("440105", "440100"),
            Map.entry("440106", "440100"),
            Map.entry("440111", "440100"),
            Map.entry("440112", "440100"),
            Map.entry("440113", "440100"),
            Map.entry("440114", "440100"),
            Map.entry("440115", "440100"),
            Map.entry("440117", "440100"),
            Map.entry("440118", "440100"),
            Map.entry("440303", "440300"),
            Map.entry("440304", "440300"),
            Map.entry("440305", "440300"),
            Map.entry("440306", "440300"),
            Map.entry("440307", "440300"),
            Map.entry("440308", "440300"),
            Map.entry("440309", "440300"),
            Map.entry("440310", "440300"),
            Map.entry("440311", "440300"),
            Map.entry("510104", "510100"),
            Map.entry("510105", "510100"),
            Map.entry("510106", "510100"),
            Map.entry("510107", "510100"),
            Map.entry("510108", "510100"),
            Map.entry("610102", "610100"),
            Map.entry("610103", "610100"),
            Map.entry("610104", "610100"),
            Map.entry("610112", "610100"),
            Map.entry("610113", "610100"),
            Map.entry("610115", "610100")
    );

    public static boolean hasProvince(String code) { return PROVINCES.containsKey(code); }
    public static boolean hasCity(String code) { return CITY_CODES.containsKey(code); }
    public static boolean hasDistrict(String code) { return DISTRICT_CODES.containsKey(code); }
    public static String provinceName(String code) { return PROVINCES.get(code); }
    public static String cityName(String code) { return CITY_CODES.get(code); }
    public static String districtName(String code) { return DISTRICT_CODES.get(code); }
    public static String provinceOfCity(String cityCode) { return CITY_PROVINCE.get(cityCode); }
    public static String cityOfDistrict(String districtCode) { return DISTRICT_CITY.get(districtCode); }
    public static List<String> citiesOfProvince(String provinceCode) { return PROVINCE_CITIES.getOrDefault(provinceCode, List.of()); }
    public static List<String> districtsOfCity(String cityCode) { return CITY_DISTRICTS.getOrDefault(cityCode, List.of()); }
}