package io.github.tobehardoo.trippilot.knowledge;

import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/**
 * 知识库两轴自动归类：
 * <ul>
 *   <li>地区 region：省/市/区三级。城市已给时按常见城市→省反查；区县尽量从正文线索取。</li>
 *   <li>板块 contentType：按分块正文的关键词加权归入 景点/酒店/餐饮/交通/行程/人文/贴士。</li>
 * </ul>
 * 用户显式提供时以用户为准（手动覆盖）。
 */
public final class KnowledgeClassifier {

    public static final String ATTRACTION = "attraction";
    public static final String HOTEL = "hotel";
    public static final String RESTAURANT = "restaurant";
    public static final String TRANSPORT = "transport";
    public static final String ITINERARY = "itinerary";
    public static final String CULTURE = "culture";
    public static final String TIP = "tip";

    private static final Map<String, String> CITY_PROVINCE = Map.ofEntries(
            Map.entry("广州", "广东省"), Map.entry("深圳", "广东省"), Map.entry("珠海", "广东省"),
            Map.entry("佛山", "广东省"), Map.entry("东莞", "广东省"), Map.entry("中山", "广东省"),
            Map.entry("北京", "北京市"), Map.entry("上海", "上海市"), Map.entry("天津", "天津市"),
            Map.entry("重庆", "重庆市"), Map.entry("杭州", "浙江省"), Map.entry("宁波", "浙江省"),
            Map.entry("南京", "江苏省"), Map.entry("苏州", "江苏省"), Map.entry("成都", "四川省"),
            Map.entry("武汉", "湖北省"), Map.entry("长沙", "湖南省"), Map.entry("西安", "陕西省"),
            Map.entry("厦门", "福建省"), Map.entry("福州", "福建省"),
            Map.entry("青岛", "山东省"), Map.entry("济南", "山东省")
    );

    /** 区县线索 → 直接作为 region_district（若正文出现这些词）。 */
    private static final Set<String> KNOWN_DISTRICTS = Set.of(
            "越秀", "天河", "海珠", "荔湾", "白云", "番禺", "黄埔", "花都", "南沙",
            "朝阳", "海淀", "东城", "西城", "徐汇", "静安", "浦东", "西湖", "上城",
            "秦淮", "鼓楼", "武侯", "锦江", "武昌", "江汉", "岳麓", "天心", "思明", "市南"
    );

    private KnowledgeClassifier() {
    }

    /** 计算板块；若用户已给 contentType 则原样返回（手动覆盖）。 */
    public static String classifyType(String chunkText, String overrideType) {
        if (overrideType != null && !overrideType.isBlank()) {
            return overrideType.trim();
        }
        return classify(chunkText);
    }

    /** 由城市推导缺失的省；正文线索推导区县。 */
    public static ResolvedRegion resolveRegion(
            String province, String city, String district, String content
    ) {
        String c = blankToNull(city);
        String p = blankToNull(province);
        String d = blankToNull(district);
        if (p == null && c != null) {
            p = CITY_PROVINCE.get(c.trim());
        }
        if (d == null && content != null) {
            d = detectDistrict(content);
        }
        return new ResolvedRegion(p, c, d);
    }

    static String classify(String text) {
        String s = text == null ? "" : text.toLowerCase(Locale.ROOT);
        int[] score = new int[7];
        score[6] = count(s, "酒店", "民宿", "旅馆", "住宿", "入住", "客栈", "公寓", "青旅");
        score[2] = count(s, "餐厅", "饭店", "饭馆", "美食", "老字号", "小吃", "早餐",
                "午饭", "晚饭", "夜宵", "食堂", "招牌菜", "人均", "好吃", "吃");
        score[0] = count(s, "景点", "公园", "博物馆", "古刹", "塔", "广场", "步行街",
                "门票", "参观", "游览", "第1站", "第2站", "第3站", "驿站");
        score[3] = count(s, "地铁", "公交", "交通", "打车", "高铁", "机场", "车站", "导航", "走路", "大巴");
        score[4] = count(s, "行程", "第一天", "第二天", "day", "路线", "攻略", "安排", "顺路", "逛");
        score[5] = count(s, "文化", "历史", "人文", "非遗", "民俗", "传统", "老建筑");
        score[1] = count(s, "注意", "建议", "贴士", "预约", "必带", "省钱", "提醒", "避坑");

        int max = 0;
        int typeIndex = 4; // 默认 itinerary
        for (int i = 0; i < score.length; i++) {
            if (score[i] > max) {
                max = score[i];
                typeIndex = i;
            }
        }
        return switch (typeIndex) {
            case 0 -> ATTRACTION;
            case 1 -> TIP;
            case 2 -> RESTAURANT;
            case 3 -> TRANSPORT;
            case 5 -> CULTURE;
            case 6 -> HOTEL;
            default -> ITINERARY;
        };
    }

    private static int count(String text, String... keywords) {
        int n = 0;
        for (String k : keywords) {
            int idx = text.indexOf(k);
            while (idx != -1) {
                n++;
                idx = text.indexOf(k, idx + k.length());
            }
        }
        return n;
    }

    private static String detectDistrict(String content) {
        for (String district : KNOWN_DISTRICTS) {
            if (content.contains(district + "区") || content.contains(district)) {
                return district + "区";
            }
        }
        return null;
    }

    private static String blankToNull(String value) {
        return value == null || value.isBlank() ? null : value.trim();
    }

    public record ResolvedRegion(String province, String city, String district) {
    }
}