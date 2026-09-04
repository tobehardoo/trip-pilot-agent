package io.github.tobehardoo.trippilot.knowledge;

import java.math.BigInteger;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 确定性特征哈希嵌入，与 agent-service 的 HashEmbeddingProvider 同构，
 * 保证 travel-server 写入/检索的向量与已有库（demo 模式）可比对。
 */
public final class DemoEmbedding {

    public static final String MODEL_NAME = "demo-hash-v1";
    public static final int DIMENSIONS = 1024;

    private static final Pattern TOKEN = Pattern.compile("[\\u3400-\\u9fff]|[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*");

    private DemoEmbedding() {
    }

    /** 对文本做 L2 归一化的特征哈希向量（返回维度为 DIMENSIONS 的 double 列表）。 */
    public static List<Double> embed(String text) {
        String folded = text.toLowerCase(Locale.ROOT);
        double[] values = new double[DIMENSIONS];
        byte[] digest = digest(text);
        Matcher matcher = TOKEN.matcher(folded);
        while (matcher.find()) {
            int index = mod(toUnsignedLong(matcher.group().getBytes(StandardCharsets.UTF_8), 8), DIMENSIONS);
            byte flag = digest(matcher.group())[8];
            values[index] += (flag & 1) == 0 ? 1.0 : -1.0;
        }
        double norm = norm(values);
        if (norm == 0.0) {
            values[mod(toUnsignedLong(digest, 8), DIMENSIONS)] = 1.0;
            norm = 1.0;
        }
        List<Double> result = new ArrayList<>(DIMENSIONS);
        for (double value : values) {
            result.add(value / norm);
        }
        return result;
    }

    /** 把向量格式化为 pgvector 数组字面量：{0.1,0.2,...}。 */
    public static String toVectorLiteral(List<Double> vector) {
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < vector.size(); i++) {
            if (i > 0) {
                sb.append(',');
            }
            sb.append(vector.get(i));
        }
        return sb.append(']').toString();
    }

    public static int tokenCount(String text) {
        int count = 0;
        Matcher matcher = TOKEN.matcher(text.toLowerCase(Locale.ROOT));
        while (matcher.find()) {
            count++;
        }
        return count;
    }

    public static String sha256Hex(String text) {
        byte[] digest = digest(text);
        StringBuilder sb = new StringBuilder(digest.length * 2);
        for (byte b : digest) {
            sb.append(Character.forDigit((b >> 4) & 0xF, 16)).append(Character.forDigit(b & 0xF, 16));
        }
        return sb.toString();
    }

    private static byte[] digest(String text) {
        try {
            return MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8));
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException("SHA-256 unavailable", impossible);
        }
    }

    /** first {@code length} bytes of {@code bytes} as an unsigned 64-bit BigInteger. */
    private static BigInteger toUnsignedLong(byte[] bytes, int length) {
        byte[] head = java.util.Arrays.copyOf(bytes, length);
        return new BigInteger(1, head);
    }

    private static int mod(BigInteger value, int modulus) {
        return value.mod(BigInteger.valueOf(modulus)).intValue();
    }

    private static double norm(double[] values) {
        double sum = 0.0;
        for (double v : values) {
            sum += v * v;
        }
        return Math.sqrt(sum);
    }
}