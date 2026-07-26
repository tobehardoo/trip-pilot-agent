package io.github.tobehardoo.trippilot.cityintelligence;

import java.util.List;
import java.util.Set;
import java.util.UUID;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.tobehardoo.trippilot.common.ApiException;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class CitySourceService {

    private static final Set<String> REVIEW_STATUSES = Set.of("PENDING", "APPROVED", "REJECTED");

    private final CitySourceMapper citySourceMapper;
    private final ObjectMapper objectMapper;

    public CitySourceService(CitySourceMapper citySourceMapper, ObjectMapper objectMapper) {
        this.citySourceMapper = citySourceMapper;
        this.objectMapper = objectMapper;
    }

    @Transactional(readOnly = true)
    public List<CitySourceResponse> list(String cityCode, Boolean enabled, String reviewStatus) {
        validateReviewStatus(reviewStatus);
        return citySourceMapper.findAll(normalize(cityCode), enabled, normalize(reviewStatus))
                .stream()
                .map(this::response)
                .toList();
    }

    @Transactional
    public CitySourceResponse update(
            UUID reviewerId,
            UUID sourceId,
            CitySourceUpdateRequest request
    ) {
        validateReviewStatus(request.reviewStatus());
        if ("PENDING".equals(request.reviewStatus())) {
            throw new ApiException(
                    HttpStatus.BAD_REQUEST,
                    "CITY_SOURCE_REVIEW_INVALID",
                    "A reviewed source cannot be moved back to PENDING"
            );
        }
        CitySourceRecord existing = citySourceMapper.findById(sourceId)
                .orElseThrow(() -> new ApiException(
                        HttpStatus.NOT_FOUND,
                        "CITY_SOURCE_NOT_FOUND",
                        "City source was not found"
                ));
        int updated = citySourceMapper.updateReview(
                sourceId,
                request.enabled(),
                request.reviewStatus(),
                normalize(request.reviewNote()),
                reviewerId,
                request.expectedVersion()
        );
        if (updated == 0) {
            throw new ApiException(
                    HttpStatus.CONFLICT,
                    "CITY_SOURCE_VERSION_CONFLICT",
                    "City source changed after it was read"
            );
        }
        return citySourceMapper.findById(existing.id())
                .map(this::response)
                .orElseThrow();
    }

    private CitySourceResponse response(CitySourceRecord source) {
        try {
            return new CitySourceResponse(
                    source.id(),
                    source.cityCode(),
                    source.cityName(),
                    source.sourceName(),
                    source.sourceUrl(),
                    source.sourceType(),
                    source.reliabilityLevel(),
                    source.enabled(),
                    source.parserStrategy(),
                    objectMapper.readTree(source.refreshPolicyJson()),
                    source.reviewStatus(),
                    source.reviewNote(),
                    source.reviewedBy(),
                    source.reviewedAt(),
                    source.version(),
                    source.createdAt(),
                    source.updatedAt()
            );
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Stored city source refresh policy is invalid", exception);
        }
    }

    private void validateReviewStatus(String reviewStatus) {
        if (reviewStatus != null && !REVIEW_STATUSES.contains(reviewStatus)) {
            throw new ApiException(
                    HttpStatus.BAD_REQUEST,
                    "CITY_SOURCE_REVIEW_INVALID",
                    "Review status must be PENDING, APPROVED, or REJECTED"
            );
        }
    }

    private String normalize(String value) {
        if (value == null) {
            return null;
        }
        String normalized = value.trim();
        return normalized.isEmpty() ? null : normalized;
    }

    public record CitySourceResponse(
            UUID id,
            String cityCode,
            String cityName,
            String sourceName,
            String sourceUrl,
            String sourceType,
            String reliabilityLevel,
            boolean enabled,
            String parserStrategy,
            JsonNode refreshPolicy,
            String reviewStatus,
            String reviewNote,
            UUID reviewedBy,
            java.time.Instant reviewedAt,
            int version,
            java.time.Instant createdAt,
            java.time.Instant updatedAt
    ) {
    }
}
