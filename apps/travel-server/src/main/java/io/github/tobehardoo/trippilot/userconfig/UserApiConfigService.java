package io.github.tobehardoo.trippilot.userconfig;

import java.time.Instant;
import java.util.List;
import java.util.UUID;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** 用户自建第三方 API 配置：读取(掩码)/保存/删除。 */
@Service
public class UserApiConfigService {

    private static final java.util.Set<String> PROVIDERS =
            java.util.Set.of("WEATHER", "AMAP", "KNOWLEDGE", "PLANNER");

    private final UserApiConfigMapper mapper;

    public UserApiConfigService(UserApiConfigMapper mapper) {
        this.mapper = mapper;
    }

    @Transactional(readOnly = true)
    public List<UserApiConfig> list(UUID userId) {
        return mapper.list(userId).stream()
                .map(row -> new UserApiConfig(row.provider(), maskKey(row.apiKey()),
                        row.apiBaseUrl(), row.model(), row.updatedAt()))
                .toList();
    }

    /** 保存（覆盖该用户所有 provider 配置）。 */
    @Transactional
    public void save(UUID userId, List<SaveItem> items) {
        Instant now = Instant.now();
        for (SaveItem item : items) {
            String provider = item.provider();
            if (provider == null || !PROVIDERS.contains(provider.trim())) {
                throw new IllegalArgumentException("unsupported api config provider: " + provider);
            }
            String key = blankToNull(item.apiKey());
            if (key == null) {
                // 传空 key 视为清除该 provider
                mapper.delete(userId, provider.trim());
                continue;
            }
            mapper.upsert(userId, provider.trim(), key,
                    blankToNull(item.apiBaseUrl()), blankToNull(item.model()), now);
        }
    }

    @Transactional
    public void delete(UUID userId, String provider) {
        if (provider == null || provider.isBlank()) {
            return;
        }
        mapper.delete(userId, provider.trim());
    }

    private static String maskKey(String key) {
        if (key == null || key.isEmpty()) {
            return null;
        }
        if (key.length() <= 8) {
            return "****";
        }
        return key.substring(0, 4) + "****" + key.substring(key.length() - 4);
    }

    private static String blankToNull(String value) {
        return value == null || value.isBlank() ? null : value.trim();
    }

    public record SaveItem(String provider, String apiKey, String apiBaseUrl, String model) {
    }
}