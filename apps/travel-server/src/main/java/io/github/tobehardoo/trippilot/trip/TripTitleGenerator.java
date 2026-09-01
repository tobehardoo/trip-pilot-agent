package io.github.tobehardoo.trippilot.trip;

import java.time.LocalDate;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.Locale;

/**
 * B13-C: deterministic default trip-title generation.
 *
 * Pure function over the destination city and the two trip boundaries; the
 * date semantics are fixed to Asia/Shanghai and the format is stable so the
 * Web preview and the server-side fallback always agree.
 */
public final class TripTitleGenerator {

    static final ZoneId CHINA_ZONE = ZoneId.of("Asia/Shanghai");

    private static final DateTimeFormatter FULL_DATE =
            DateTimeFormatter.ofPattern("yyyy年MM月dd日", Locale.CHINA);
    private static final DateTimeFormatter MONTH_DAY =
            DateTimeFormatter.ofPattern("MM月dd日", Locale.CHINA);

    private TripTitleGenerator() {
    }

    /**
     * e.g. {@code 2026年08月20日—08月21日 广州市旅行规划}.  Same-year ranges
     * drop the leading year from the second date; different-year ranges keep
     * both years.
     */
    public static String generate(String city, LocalDate startDate, LocalDate endDate) {
        String base = normalizeCity(city);
        String start = startDate.atStartOfDay(CHINA_ZONE).format(FULL_DATE);
        String end = startDate.getYear() == endDate.getYear()
                ? endDate.atStartOfDay(CHINA_ZONE).format(MONTH_DAY)
                : endDate.atStartOfDay(CHINA_ZONE).format(FULL_DATE);
        return start + "—" + end + " " + base + "旅行规划";
    }

    /** The city is the title subject; append 市 when the name lacks a suffix. */
    private static String normalizeCity(String city) {
        String trimmed = city == null ? "" : city.trim();
        if (trimmed.isEmpty()) {
            return "";
        }
        for (String suffix : new String[]{"市", "自治州", "地区", "盟", "特别行政区"}) {
            if (trimmed.endsWith(suffix)) {
                return trimmed;
            }
        }
        return trimmed + "市";
    }
}
