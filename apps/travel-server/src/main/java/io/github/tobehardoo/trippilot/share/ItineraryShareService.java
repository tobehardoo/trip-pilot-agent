package io.github.tobehardoo.trippilot.share;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.Base64;
import java.util.List;
import java.util.UUID;

import io.github.tobehardoo.trippilot.common.ApiException;
import io.github.tobehardoo.trippilot.itinerary.ItineraryService;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class ItineraryShareService {

    private static final SecureRandom TOKEN_RANDOM = new SecureRandom();

    private final ItineraryShareMapper shareMapper;
    private final ItineraryService itineraryService;
    private final PublicShareRateLimiter rateLimiter;
    private final Clock clock;

    public ItineraryShareService(
            ItineraryShareMapper shareMapper,
            ItineraryService itineraryService,
            PublicShareRateLimiter rateLimiter,
            Clock clock
    ) {
        this.shareMapper = shareMapper;
        this.itineraryService = itineraryService;
        this.rateLimiter = rateLimiter;
        this.clock = clock;
    }

    @Transactional
    public CreatedShare create(UUID ownerId, UUID tripId, UUID versionId, Instant expiresAt) {
        if (versionId == null) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "SHARE_VERSION_REQUIRED",
                    "An itinerary version is required for sharing");
        }
        Instant now = clock.instant();
        if (expiresAt != null && !expiresAt.isAfter(now)) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "SHARE_EXPIRY_INVALID",
                    "A share expiry must be in the future");
        }
        shareMapper.findOwnedVersion(tripId, versionId, ownerId)
                .orElseThrow(this::shareNotFound);
        shareMapper.revokeExpiredOwnedVersion(tripId, versionId, ownerId, now);
        if (shareMapper.findActiveOwnedVersion(tripId, versionId, ownerId, now).isPresent()) {
            throw new ApiException(HttpStatus.CONFLICT, "SHARE_ACTIVE",
                    "This itinerary version already has an active share link");
        }
        String token = newToken();
        ItineraryShareMapper.ShareWrite share = new ItineraryShareMapper.ShareWrite(
                UUID.randomUUID(), versionId, tripId, ownerId, tokenHash(token), expiresAt
        );
        shareMapper.insert(share);
        return new CreatedShare(share.id(), share.itineraryVersionId(), token, share.expiresAt(), now);
    }

    @Transactional(readOnly = true)
    public List<ShareStatus> list(UUID ownerId, UUID tripId) {
        return shareMapper.findOwned(tripId, ownerId).stream().map(this::toStatus).toList();
    }

    @Transactional
    public void revoke(UUID ownerId, UUID tripId, UUID shareId) {
        if (shareMapper.findOwnedById(shareId, tripId, ownerId).isEmpty()) {
            throw shareNotFound();
        }
        shareMapper.revoke(shareId, tripId, ownerId, clock.instant());
    }

    @Transactional(readOnly = true)
    public PublicItinerary resolvePublic(String token, String clientAddress) {
        rateLimiter.check(clientAddress);
        if (token == null || token.length() < 32) {
            throw shareNotFound();
        }
        UUID versionId = shareMapper.findActiveVersionByTokenHash(tokenHash(token), clock.instant())
                .orElseThrow(this::shareNotFound);
        return redact(itineraryService.getVersionForAuthorizedShare(versionId));
    }

    private ShareStatus toStatus(ItineraryShareMapper.ShareRecord share) {
        return new ShareStatus(
                share.id(), share.itineraryVersionId(), share.expiresAt(), share.revokedAt(), share.createdAt()
        );
    }

    private PublicItinerary redact(ItineraryService.ItineraryResponse itinerary) {
        List<PublicDay> days = itinerary.days().stream().map(day -> new PublicDay(
                day.date(),
                day.activities().stream().map(activity -> new PublicActivity(
                        activity.title(), activity.startTime(), activity.endTime(),
                        activity.estimatedCost(), activity.address(),
                        activity.costSource()
                )).toList(),
                day.transitLegs().stream().map(leg -> new PublicTransitLeg(
                        leg.mode(), leg.modeLabel(), leg.distanceMeters(), leg.durationSeconds(),
                        leg.routeDurationSeconds(), leg.waitSeconds(), leg.displayCost(),
                        leg.costSource(), leg.costMeaning(), leg.provider(), leg.estimated(), leg.stale()
                )).toList()
        )).toList();
        List<PublicSource> sources = itinerary.knowledge() == null ? List.of()
                : itinerary.knowledge().citations().stream().map(citation -> new PublicSource(
                        citation.title(), citation.sourceName(), citation.sourceUrl(), citation.reliabilityLevel()
                )).toList();
        return new PublicItinerary(
                itinerary.title(), itinerary.estimatedTotalCost(), itinerary.provider(),
                days, sources, itinerary.createdAt()
        );
    }

    private String newToken() {
        byte[] bytes = new byte[32];
        TOKEN_RANDOM.nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    private String tokenHash(String token) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256")
                    .digest(token.getBytes(StandardCharsets.UTF_8));
            StringBuilder result = new StringBuilder(digest.length * 2);
            for (byte value : digest) {
                result.append(String.format("%02x", value));
            }
            return result.toString();
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 is unavailable", exception);
        }
    }

    private ApiException shareNotFound() {
        return new ApiException(HttpStatus.NOT_FOUND, "SHARE_NOT_FOUND", "Shared itinerary was not found");
    }

    public record CreatedShare(
            UUID id,
            UUID versionId,
            String shareToken,
            Instant expiresAt,
            Instant createdAt
    ) {
    }

    public record ShareStatus(
            UUID id,
            UUID versionId,
            Instant expiresAt,
            Instant revokedAt,
            Instant createdAt
    ) {
    }

    public record PublicItinerary(
            String title,
            BigDecimal estimatedTotalCost,
            String provider,
            List<PublicDay> days,
            List<PublicSource> sources,
            Instant generatedAt
    ) {
    }

    public record PublicDay(
            LocalDate date,
            List<PublicActivity> activities,
            List<PublicTransitLeg> transitLegs
    ) {
    }

    public record PublicActivity(
            String title,
            OffsetDateTime startTime,
            OffsetDateTime endTime,
            BigDecimal estimatedCost,
            String address,
            String costSource
    ) {
    }

    public record PublicTransitLeg(
            String mode,
            String modeLabel,
            int distanceMeters,
            int durationSeconds,
            int routeDurationSeconds,
            int waitSeconds,
            BigDecimal estimatedCost,
            String costSource,
            String costMeaning,
            String provider,
            boolean estimated,
            boolean stale
    ) {
    }

    public record PublicSource(
            String title,
            String sourceName,
            String sourceUrl,
            String reliabilityLevel
    ) {
    }
}
