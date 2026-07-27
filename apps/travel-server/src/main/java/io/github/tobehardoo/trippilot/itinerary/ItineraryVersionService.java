package io.github.tobehardoo.trippilot.itinerary;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

import io.github.tobehardoo.trippilot.common.ApiException;
import io.github.tobehardoo.trippilot.planning.PlanningFactImpactMapper;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class ItineraryVersionService {

    private final ItineraryVersionMapper versionMapper;
    private final ItineraryMapper itineraryMapper;
    private final ItineraryVersionPersister versionPersister;
    private final ItineraryService itineraryService;
    private final PlanningFactImpactMapper factImpactMapper;

    public ItineraryVersionService(
            ItineraryVersionMapper versionMapper,
            ItineraryMapper itineraryMapper,
            ItineraryVersionPersister versionPersister,
            ItineraryService itineraryService,
            PlanningFactImpactMapper factImpactMapper
    ) {
        this.versionMapper = versionMapper;
        this.itineraryMapper = itineraryMapper;
        this.versionPersister = versionPersister;
        this.itineraryService = itineraryService;
        this.factImpactMapper = factImpactMapper;
    }

    @Transactional(readOnly = true)
    public List<VersionSummary> list(UUID ownerId, UUID tripId) {
        return versionMapper.findAllOwned(tripId, ownerId).stream()
                .map(version -> new VersionSummary(
                        version.id(), version.versionNumber(), version.parentVersionId(),
                        version.planningTaskId(), version.versionSource(), version.title(),
                        version.estimatedTotalCost(), version.provider(),
                        version.rollbackFromVersionId(), version.createdAt(), version.current()
                ))
                .toList();
    }

    @Transactional(readOnly = true)
    public VersionDiff diff(UUID ownerId, UUID tripId, UUID fromId, UUID toId) {
        VersionView from = readOwned(ownerId, tripId, fromId);
        VersionView to = readOwned(ownerId, tripId, toId);
        ActivityListDiff activityDiff = diffActivities(
                from.activities(), to.activities()
        );
        TransitListDiff transitDiff = diffTransit(
                from.transitLegs(), to.transitLegs()
        );
        Map<String, FactImpactView> beforeFacts =
                indexFactImpacts(from.factImpacts());
        Map<String, FactImpactView> afterFacts =
                indexFactImpacts(to.factImpacts());
        List<FactImpactView> addedFacts = afterFacts.entrySet().stream()
                .filter(entry -> !beforeFacts.containsKey(entry.getKey()))
                .map(Map.Entry::getValue).toList();
        List<FactImpactView> removedFacts = beforeFacts.entrySet().stream()
                .filter(entry -> !afterFacts.containsKey(entry.getKey()))
                .map(Map.Entry::getValue).toList();
        List<FactImpactChange> changedFacts = beforeFacts.keySet().stream()
                .filter(afterFacts::containsKey)
                .map(key -> factImpactChange(
                        beforeFacts.get(key), afterFacts.get(key)
                ))
                .filter(change -> !change.changes().isEmpty())
                .toList();
        return new VersionDiff(
                fromId, toId,
                activityDiff.added(), activityDiff.removed(), activityDiff.changed(),
                transitDiff.added(), transitDiff.removed(), transitDiff.changed(),
                addedFacts, removedFacts, changedFacts,
                from.totalCost(), to.totalCost(),
                to.totalCost().subtract(from.totalCost())
        );
    }

    @Transactional
    public ItineraryService.ItineraryResponse rollback(
            UUID ownerId,
            UUID tripId,
            UUID idempotencyKey,
            RollbackRequest request
    ) {
        ItineraryMapper.ItineraryState state = versionMapper
                .lockOwnedState(tripId, ownerId)
                .orElseThrow(this::notFound);
        ItineraryVersionMapper.RollbackResultRecord existing = versionMapper
                .findRollbackResult(state.id(), idempotencyKey)
                .orElse(null);
        if (existing != null) {
            if (request == null
                    || !existing.sourceVersionId().equals(request.sourceVersionId())
                    || !existing.expectedCurrentVersionId()
                            .equals(request.expectedCurrentVersionId())) {
                throw new ApiException(
                        HttpStatus.CONFLICT,
                        "IDEMPOTENCY_KEY_REUSED",
                        "The idempotency key was already used for another rollback"
                );
            }
            return itineraryService.getVersion(
                    ownerId, tripId, existing.resultVersionId()
            );
        }
        if (request == null || request.sourceVersionId() == null
                || request.expectedCurrentVersionId() == null
                || !request.expectedCurrentVersionId().equals(state.currentVersionId())) {
            throw new ApiException(
                    HttpStatus.CONFLICT,
                    "ITINERARY_VERSION_CONFLICT",
                    "The itinerary changed before rollback; reload and retry"
            );
        }
        ItineraryMapper.StoredVersion source = versionMapper
                .findOwnedVersion(tripId, request.sourceVersionId(), ownerId)
                .orElseThrow(this::notFound);
        UUID versionId = UUID.randomUUID();
        int versionNumber = state.currentVersionNumber() + 1;
        requireOne(versionMapper.insertRollbackVersion(
                new ItineraryVersionMapper.RollbackVersionWrite(
                        versionId, state.id(), versionNumber, state.currentVersionId(),
                        source.title(), source.estimatedTotalCost(), source.provider(),
                        source.constraintSnapshotJson(), source.id(), Instant.now()
                )
        ), "rollback version");
        copyVersion(source.id(), versionId);
        factImpactMapper.copyToVersion(source.id(), versionId);
        requireOne(itineraryMapper.updateCurrentVersion(state.id(), versionId), "current version");
        requireOne(versionMapper.insertRollback(
                new ItineraryVersionMapper.RollbackAuditWrite(
                        UUID.randomUUID(), state.id(), source.id(), versionId,
                        ownerId, idempotencyKey
                )
        ), "rollback audit");
        return itineraryService.getVersion(ownerId, tripId, versionId);
    }

    private void copyVersion(UUID sourceVersionId, UUID targetVersionId) {
        versionPersister.copyKnowledge(sourceVersionId, targetVersionId, "rollback knowledge");
        for (ItineraryMapper.StoredDay day : itineraryMapper.findDays(sourceVersionId)) {
            UUID dayId = UUID.randomUUID();
            requireOne(itineraryMapper.insertDay(new ItineraryMapper.DayWrite(
                    dayId, targetVersionId, day.date(), day.dayIndex()
            )), "rollback day");
            Map<UUID, UUID> activityIds = new HashMap<>();
            for (ItineraryMapper.StoredActivity activity
                    : itineraryMapper.findActivities(day.id())) {
                UUID activityId = UUID.randomUUID();
                activityIds.put(activity.id(), activityId);
                requireOne(itineraryMapper.insertActivity(
                        new ItineraryMapper.ActivityWrite(
                                activityId, dayId, activity.activityOrder(),
                                activity.title(), activity.startTime(), activity.endTime(),
                                activity.estimatedCost(), activity.source(),
                                activity.providerPoiId(), activity.longitude(),
                                activity.latitude(), activity.address(), activity.locked()
                        )
                ), "rollback activity");
            }
            for (ItineraryMapper.StoredTransitLeg leg
                    : itineraryMapper.findTransitLegs(day.id())) {
                requireOne(itineraryMapper.insertTransitLeg(
                        new ItineraryMapper.TransitLegWrite(
                                UUID.randomUUID(), dayId, leg.legOrder(),
                                activityIds.get(leg.fromActivityId()),
                                activityIds.get(leg.toActivityId()), leg.mode(),
                                leg.distanceMeters(), leg.durationSeconds(), leg.provider(),
                                leg.estimated(), leg.polylineJson(), leg.locked()
                        )
                ), "rollback transit leg");
            }
        }
    }

    private VersionView readOwned(UUID ownerId, UUID tripId, UUID versionId) {
        ItineraryMapper.StoredVersion version = versionMapper
                .findOwnedVersion(tripId, versionId, ownerId)
                .orElseThrow(this::notFound);
        List<ActivityView> activities = new ArrayList<>();
        List<TransitView> transitLegs = new ArrayList<>();
        for (ItineraryMapper.StoredDay day : itineraryMapper.findDays(versionId)) {
            List<ItineraryMapper.StoredActivity> storedActivities =
                    itineraryMapper.findActivities(day.id());
            Map<UUID, String> activityKeys = new HashMap<>();
            Map<UUID, String> activityTitles = new HashMap<>();
            for (ItineraryMapper.StoredActivity activity : storedActivities) {
                activityKeys.put(activity.id(), key(activity));
                activityTitles.put(activity.id(), activity.title());
                activities.add(new ActivityView(
                        key(activity), activity.title(), day.date(),
                        activity.activityOrder(), activity.startTime(), activity.endTime(),
                        activity.estimatedCost(), activity.locked()
                ));
            }
            for (ItineraryMapper.StoredTransitLeg leg
                    : itineraryMapper.findTransitLegs(day.id())) {
                String fromKey = activityKeys.get(leg.fromActivityId());
                String toKey = activityKeys.get(leg.toActivityId());
                if (fromKey == null || toKey == null) {
                    continue;
                }
                transitLegs.add(new TransitView(
                        day.date() + ":" + fromKey + "->" + toKey,
                        day.date(),
                        activityTitles.get(leg.fromActivityId()),
                        activityTitles.get(leg.toActivityId()),
                        leg.mode(),
                        leg.distanceMeters(),
                        leg.durationSeconds(),
                        leg.provider(),
                        leg.estimated(),
                        leg.locked()
                ));
            }
        }
        List<FactImpactView> factImpacts = factImpactMapper
                .findByVersion(versionId).stream()
                .map(impact -> new FactImpactView(
                        impact.factId(), impact.category(),
                        impact.applicableDate(), impact.effect(),
                        impact.targetPoiId(), impact.targetName(),
                        impact.reason(), impact.sourceName(),
                        impact.sourceType(), impact.sourceUrl(),
                        impact.reliabilityLevel(), impact.checkedAt(),
                        impact.evidence(), impact.stale(), impact.conflicted(),
                        impact.refreshFailed()
                ))
                .toList();
        return new VersionView(
                version.estimatedTotalCost(),
                activities,
                transitLegs,
                factImpacts
        );
    }

    private ActivityListDiff diffActivities(
            List<ActivityView> before,
            List<ActivityView> after
    ) {
        List<ActivityView> unmatchedBefore = new ArrayList<>(before);
        List<ActivityView> unmatchedAfter = new ArrayList<>(after);
        List<ActivityChange> changed = new ArrayList<>();
        matchActivities(unmatchedBefore, unmatchedAfter, true, changed);
        matchActivities(unmatchedBefore, unmatchedAfter, false, changed);
        return new ActivityListDiff(
                List.copyOf(unmatchedAfter),
                List.copyOf(unmatchedBefore),
                List.copyOf(changed)
        );
    }

    private void matchActivities(
            List<ActivityView> before,
            List<ActivityView> after,
            boolean sameOccurrenceOnly,
            List<ActivityChange> changed
    ) {
        for (int beforeIndex = before.size() - 1; beforeIndex >= 0; beforeIndex--) {
            ActivityView candidate = before.get(beforeIndex);
            int afterIndex = matchingActivityIndex(
                    candidate, after, sameOccurrenceOnly
            );
            if (afterIndex < 0) {
                continue;
            }
            ActivityChange change = change(candidate, after.remove(afterIndex));
            before.remove(beforeIndex);
            if (!change.changes().isEmpty()) {
                changed.add(change);
            }
        }
    }

    private int matchingActivityIndex(
            ActivityView before,
            List<ActivityView> candidates,
            boolean sameOccurrenceOnly
    ) {
        for (int index = 0; index < candidates.size(); index++) {
            ActivityView after = candidates.get(index);
            if (!before.key().equals(after.key())) {
                continue;
            }
            if (!sameOccurrenceOnly
                    || before.date().equals(after.date())
                    && before.startTime().equals(after.startTime())
                    && before.endTime().equals(after.endTime())) {
                return index;
            }
        }
        return -1;
    }

    private TransitListDiff diffTransit(
            List<TransitView> before,
            List<TransitView> after
    ) {
        List<TransitView> unmatchedBefore = new ArrayList<>(before);
        List<TransitView> unmatchedAfter = new ArrayList<>(after);
        List<TransitChange> changed = new ArrayList<>();
        for (int beforeIndex = unmatchedBefore.size() - 1;
                beforeIndex >= 0; beforeIndex--) {
            TransitView candidate = unmatchedBefore.get(beforeIndex);
            int afterIndex = matchingTransitIndex(candidate, unmatchedAfter);
            if (afterIndex < 0) {
                continue;
            }
            TransitChange change = transitChange(
                    candidate, unmatchedAfter.remove(afterIndex)
            );
            unmatchedBefore.remove(beforeIndex);
            if (!change.changes().isEmpty()) {
                changed.add(change);
            }
        }
        return new TransitListDiff(
                List.copyOf(unmatchedAfter),
                List.copyOf(unmatchedBefore),
                List.copyOf(changed)
        );
    }

    private int matchingTransitIndex(
            TransitView before,
            List<TransitView> candidates
    ) {
        for (int index = 0; index < candidates.size(); index++) {
            if (before.key().equals(candidates.get(index).key())) {
                return index;
            }
        }
        return -1;
    }

    private Map<String, FactImpactView> indexFactImpacts(
            List<FactImpactView> impacts
    ) {
        Map<String, FactImpactView> result = new LinkedHashMap<>();
        for (FactImpactView impact : impacts) {
            result.put(impact.key(), impact);
        }
        return result;
    }

    private String key(ItineraryMapper.StoredActivity activity) {
        return activity.providerPoiId() == null
                ? activity.title().strip().toLowerCase(java.util.Locale.ROOT)
                : activity.providerPoiId();
    }

    private ActivityChange change(ActivityView before, ActivityView after) {
        List<String> changes = new ArrayList<>();
        if (!before.date().equals(after.date()) || before.order() != after.order()) {
            changes.add("MOVED");
        }
        if (!before.startTime().equals(after.startTime())
                || !before.endTime().equals(after.endTime())) {
            changes.add("TIME_CHANGED");
        }
        if (before.locked() != after.locked()) {
            changes.add("LOCK_CHANGED");
        }
        return new ActivityChange(before, after, changes);
    }

    private TransitChange transitChange(TransitView before, TransitView after) {
        List<String> changes = new ArrayList<>();
        if (!before.mode().equals(after.mode())) {
            changes.add("MODE_CHANGED");
        }
        if (before.distanceMeters() != after.distanceMeters()
                || before.durationSeconds() != after.durationSeconds()) {
            changes.add("ROUTE_CHANGED");
        }
        if (before.locked() != after.locked()) {
            changes.add("LOCK_CHANGED");
        }
        return new TransitChange(before, after, changes);
    }

    private FactImpactChange factImpactChange(
            FactImpactView before,
            FactImpactView after
    ) {
        List<String> changes = new ArrayList<>();
        if (!Objects.equals(before.reason(), after.reason())) {
            changes.add("REASON_CHANGED");
        }
        if (!Objects.equals(
                before.reliabilityLevel(), after.reliabilityLevel()
        )) {
            changes.add("RELIABILITY_CHANGED");
        }
        if (before.stale() != after.stale()) {
            changes.add("FRESHNESS_CHANGED");
        }
        return new FactImpactChange(before, after, changes);
    }

    private ApiException notFound() {
        return new ApiException(
                HttpStatus.NOT_FOUND, "ITINERARY_VERSION_NOT_FOUND",
                "Itinerary version was not found"
        );
    }

    private void requireOne(int rows, String operation) {
        if (rows != 1) {
            throw new IllegalStateException("Could not persist " + operation);
        }
    }

    public record RollbackRequest(UUID sourceVersionId, UUID expectedCurrentVersionId) {
    }
    public record VersionSummary(
            UUID versionId, int versionNumber, UUID parentVersionId,
            UUID planningTaskId, String versionSource, String title,
            BigDecimal estimatedTotalCost, String provider,
            UUID rollbackFromVersionId, Instant createdAt, boolean current
    ) {
    }
    public record ActivityView(
            String key, String title, LocalDate date, int order,
            OffsetDateTime startTime, OffsetDateTime endTime,
            BigDecimal estimatedCost, boolean locked
    ) {
    }
    public record ActivityChange(
            ActivityView before, ActivityView after, List<String> changes
    ) {
    }
    public record TransitView(
            String key,
            LocalDate date,
            String fromTitle,
            String toTitle,
            String mode,
            int distanceMeters,
            int durationSeconds,
            String provider,
            boolean estimated,
            boolean locked
    ) {
    }
    public record TransitChange(
            TransitView before, TransitView after, List<String> changes
    ) {
    }
    public record FactImpactView(
            String factId,
            String category,
            LocalDate date,
            String effect,
            String targetPoiId,
            String targetName,
            String reason,
            String sourceName,
            String sourceType,
            String sourceUrl,
            String reliabilityLevel,
            Instant checkedAt,
            String evidence,
            boolean stale,
            boolean conflicted,
            boolean refreshFailed
    ) {
        String key() {
            return factId + ":" + category + ":" + effect + ":"
                    + Objects.toString(date, "") + ":"
                    + Objects.toString(targetPoiId, "");
        }
    }
    public record FactImpactChange(
            FactImpactView before,
            FactImpactView after,
            List<String> changes
    ) {
    }
    public record VersionDiff(
            UUID fromVersionId, UUID toVersionId,
            List<ActivityView> addedActivities,
            List<ActivityView> removedActivities,
            List<ActivityChange> changedActivities,
            List<TransitView> addedTransitLegs,
            List<TransitView> removedTransitLegs,
            List<TransitChange> changedTransitLegs,
            List<FactImpactView> addedFactImpacts,
            List<FactImpactView> removedFactImpacts,
            List<FactImpactChange> changedFactImpacts,
            BigDecimal fromTotalCost,
            BigDecimal toTotalCost,
            BigDecimal budgetChange
    ) {
    }
    private record VersionView(
            BigDecimal totalCost,
            List<ActivityView> activities,
            List<TransitView> transitLegs,
            List<FactImpactView> factImpacts
    ) {
    }
    private record ActivityListDiff(
            List<ActivityView> added,
            List<ActivityView> removed,
            List<ActivityChange> changed
    ) {
    }
    private record TransitListDiff(
            List<TransitView> added,
            List<TransitView> removed,
            List<TransitChange> changed
    ) {
    }
}
