package io.github.tobehardoo.trippilot.export;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

import io.github.tobehardoo.trippilot.itinerary.ItineraryService;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class ItineraryExportService {

    private static final DateTimeFormatter ICS_TIMESTAMP = DateTimeFormatter.ofPattern("yyyyMMdd'T'HHmmss'Z'");

    private final ItineraryService itineraryService;
    private final Clock clock;

    public ItineraryExportService(ItineraryService itineraryService, Clock clock) {
        this.itineraryService = itineraryService;
        this.clock = clock;
    }

    @Transactional(readOnly = true)
    public ExportedItinerary calendar(UUID ownerId, UUID tripId, UUID versionId) {
        ItineraryService.ItineraryResponse itinerary = version(ownerId, tripId, versionId);
        StringBuilder calendar = new StringBuilder();
        line(calendar, "BEGIN:VCALENDAR");
        line(calendar, "VERSION:2.0");
        line(calendar, "PRODID:-//TripPilot//Itinerary//EN");
        line(calendar, "CALSCALE:GREGORIAN");
        line(calendar, "METHOD:PUBLISH");
        for (ItineraryService.DayResponse day : itinerary.days()) {
            for (ItineraryService.ActivityResponse activity : day.activities()) {
                line(calendar, "BEGIN:VEVENT");
                line(calendar, "UID:" + activity.id() + "@trippilot");
                line(calendar, "DTSTAMP:" + formatIcs(clock.instant()));
                line(calendar, "DTSTART:" + formatIcs(activity.startTime()));
                line(calendar, "DTEND:" + formatIcs(activity.endTime()));
                line(calendar, "SUMMARY:" + escapeIcs(activity.title()));
                if (activity.address() != null && !activity.address().isBlank()) {
                    line(calendar, "LOCATION:" + escapeIcs(activity.address()));
                }
                line(calendar, "DESCRIPTION:" + escapeIcs(
                        "TripPilot itinerary; estimated cost: " + amount(activity.estimatedCost())
                ));
                line(calendar, "END:VEVENT");
            }
        }
        line(calendar, "END:VCALENDAR");
        return new ExportedItinerary(itinerary.versionNumber(), calendar.toString().getBytes(StandardCharsets.UTF_8));
    }

    @Transactional(readOnly = true)
    public ExportedItinerary pdf(UUID ownerId, UUID tripId, UUID versionId) {
        ItineraryService.ItineraryResponse itinerary = version(ownerId, tripId, versionId);
        List<String> lines = new ArrayList<>();
        lines.add(itinerary.title());
        lines.add("Estimated total cost: " + amount(itinerary.estimatedTotalCost()));
        lines.add("Provider: " + itinerary.provider());
        lines.add("Generated: " + clock.instant());
        for (ItineraryService.DayResponse day : itinerary.days()) {
            lines.add("");
            lines.add("Day " + day.date());
            for (ItineraryService.ActivityResponse activity : day.activities()) {
                lines.add(formatActivity(activity));
            }
            for (ItineraryService.TransitLegResponse leg : day.transitLegs()) {
                String cost = leg.displayCost() == null ? "" : ", 费用 " + amount(leg.displayCost());
                String wait = leg.waitSeconds() == 0
                        ? "" : ", 含候车 " + Math.round(leg.waitSeconds() / 60.0) + " 分钟";
                String estimate = leg.estimated() ? "（估算）" : "";
                lines.add("交通 " + leg.modeLabel() + "：" + leg.distanceMeters() + " 米，"
                        + Math.round(leg.routeDurationSeconds() / 60.0) + " 分钟"
                        + wait + cost + estimate);
            }
        }
        if (itinerary.knowledge() != null && !itinerary.knowledge().citations().isEmpty()) {
            lines.add("");
            lines.add("Sources");
            itinerary.knowledge().citations().forEach(citation -> lines.add(
                    citation.sourceName() + ": " + citation.title()
            ));
        }
        return new ExportedItinerary(itinerary.versionNumber(), renderPdf(lines));
    }

    private ItineraryService.ItineraryResponse version(UUID ownerId, UUID tripId, UUID versionId) {
        return versionId == null
                ? itineraryService.getCurrent(ownerId, tripId)
                : itineraryService.getVersion(ownerId, tripId, versionId);
    }

    private String formatActivity(ItineraryService.ActivityResponse activity) {
        String start = activity.startTime().toLocalTime().toString();
        String end = activity.endTime().toLocalTime().toString();
        String location = activity.address() == null || activity.address().isBlank() ? "" : " @ " + activity.address();
        return start + "-" + end + " " + activity.title() + location + " (" + amount(activity.estimatedCost()) + ")";
    }

    private byte[] renderPdf(List<String> rawLines) {
        List<String> lines = rawLines.stream().flatMap(line -> wrap(line, 42).stream()).toList();
        List<List<String>> pages = new ArrayList<>();
        for (int offset = 0; offset < lines.size(); offset += 44) {
            pages.add(lines.subList(offset, Math.min(offset + 44, lines.size())));
        }
        if (pages.isEmpty()) {
            pages.add(List.of("TripPilot itinerary"));
        }
        try (ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            List<byte[]> objects = new ArrayList<>();
            objects.add(ascii("<< /Type /Catalog /Pages 2 0 R >>"));
            StringBuilder kids = new StringBuilder("<< /Type /Pages /Kids [");
            for (int index = 0; index < pages.size(); index++) {
                kids.append(4 + index * 2).append(" 0 R ");
            }
            kids.append("] /Count ").append(pages.size()).append(" >>");
            objects.add(ascii(kids.toString()));
            // Adobe's predefined CJK font and CMap keep Chinese text portable without a host font mount.
            objects.add(ascii("""
                    << /Type /Font /Subtype /Type0 /BaseFont /STSong-Light
                    /Encoding /UniGB-UCS2-H /DescendantFonts [ 4 0 R ] >>
                    """.replace("4 0 R", (4 + pages.size() * 2) + " 0 R")));
            for (int index = 0; index < pages.size(); index++) {
                int pageObject = 4 + index * 2;
                int contentObject = pageObject + 1;
                objects.add(ascii("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                        + "/Resources << /Font << /F1 3 0 R >> >> /Contents " + contentObject + " 0 R >>"));
                byte[] content = pageContent(pages.get(index));
                objects.add(concat(
                        ascii("<< /Length " + content.length + " >>\nstream\n"),
                        content,
                        ascii("\nendstream")
                ));
            }
            int cidFontObject = 4 + pages.size() * 2;
            objects.add(ascii("""
                    << /Type /Font /Subtype /CIDFontType0 /BaseFont /STSong-Light
                    /CIDSystemInfo << /Registry (Adobe) /Ordering (GB1) /Supplement 5 >> /DW 1000
                    /FontDescriptor %d 0 R >>
                    """.formatted(cidFontObject + 1)));
            objects.add(ascii("""
                    << /Type /FontDescriptor /FontName /STSong-Light /Flags 4
                    /FontBBox [-25 -254 1000 880] /ItalicAngle 0 /Ascent 880 /Descent -120
                    /CapHeight 880 /StemV 80 >>
                    """));

            output.write(ascii("%PDF-1.7\n%\u00e2\u00e3\u00cf\u00d3\n"));
            List<Integer> offsets = new ArrayList<>();
            offsets.add(0);
            for (int index = 0; index < objects.size(); index++) {
                offsets.add(output.size());
                output.write(ascii((index + 1) + " 0 obj\n"));
                output.write(objects.get(index));
                output.write(ascii("\nendobj\n"));
            }
            int xref = output.size();
            output.write(ascii("xref\n0 " + (objects.size() + 1) + "\n0000000000 65535 f \n"));
            for (int index = 1; index < offsets.size(); index++) {
                output.write(ascii("%010d 00000 n \n".formatted(offsets.get(index))));
            }
            output.write(ascii("trailer\n<< /Size " + (objects.size() + 1)
                    + " /Root 1 0 R >>\nstartxref\n" + xref + "\n%%EOF\n"));
            return output.toByteArray();
        } catch (IOException exception) {
            throw new IllegalStateException("Could not render itinerary PDF", exception);
        }
    }

    private byte[] pageContent(List<String> lines) {
        StringBuilder content = new StringBuilder("BT\n/F1 11 Tf\n50 790 Td\n");
        for (String line : lines) {
            content.append('<').append("FEFF").append(utf16Hex(line)).append("> Tj\n0 -16 Td\n");
        }
        return ascii(content.append("ET").toString());
    }

    private List<String> wrap(String text, int maxCodePoints) {
        if (text == null || text.isEmpty()) {
            return List.of("");
        }
        List<String> lines = new ArrayList<>();
        int offset = 0;
        while (offset < text.length()) {
            int end = text.offsetByCodePoints(offset, Math.min(maxCodePoints, text.codePointCount(offset, text.length())));
            lines.add(text.substring(offset, end));
            offset = end;
        }
        return lines;
    }

    private String utf16Hex(String value) {
        StringBuilder hex = new StringBuilder();
        for (byte character : value.getBytes(StandardCharsets.UTF_16BE)) {
            hex.append("%02X".formatted(Byte.toUnsignedInt(character)));
        }
        return hex.toString();
    }

    private byte[] concat(byte[]... values) {
        try (ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            for (byte[] value : values) {
                output.write(value);
            }
            return output.toByteArray();
        } catch (IOException exception) {
            throw new IllegalStateException("Could not compose PDF stream", exception);
        }
    }

    private byte[] ascii(String value) {
        return value.getBytes(StandardCharsets.ISO_8859_1);
    }

    private String formatIcs(Instant instant) {
        return ICS_TIMESTAMP.withZone(ZoneOffset.UTC).format(instant);
    }

    private String formatIcs(OffsetDateTime time) {
        return formatIcs(time.toInstant());
    }

    private String escapeIcs(String value) {
        return value.replace("\\", "\\\\").replace(";", "\\;")
                .replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n");
    }

    private void line(StringBuilder value, String line) {
        int lineBytes = 0;
        for (int offset = 0; offset < line.length();) {
            int codePoint = line.codePointAt(offset);
            int codePointBytes = new String(Character.toChars(codePoint))
                    .getBytes(StandardCharsets.UTF_8).length;
            if (lineBytes + codePointBytes > 75) {
                value.append("\r\n ");
                lineBytes = 1;
            }
            value.appendCodePoint(codePoint);
            lineBytes += codePointBytes;
            offset += Character.charCount(codePoint);
        }
        value.append("\r\n");
    }

    private String amount(BigDecimal amount) {
        return amount == null ? "0" : amount.stripTrailingZeros().toPlainString();
    }

    public record ExportedItinerary(int versionNumber, byte[] content) {
    }
}
