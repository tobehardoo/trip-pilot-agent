"""Controlled acquisition boundaries for official knowledge sources."""

from trip_agent.acquisition.dns import HostResolver, SystemHostResolver
from trip_agent.acquisition.extraction import (
    ArticleExtractionPassed,
    ArticleExtractionRejected,
    ArticleExtractionResult,
    ExtractedArticle,
    ExtractionQualityIssue,
    GuangzhouGovernmentArticleExtractor,
)
from trip_agent.acquisition.extraction_service import (
    ExtractionPersisted,
    ExtractionVersionConflict,
    PendingSnapshot,
    SnapshotExtractionProcessed,
    SnapshotExtractionRecord,
    SnapshotExtractionService,
)
from trip_agent.acquisition.fetch_models import (
    AcquisitionFetchError,
    FetchResult,
    FetchValidators,
    ResourceFetched,
    ResourceNotModified,
)
from trip_agent.acquisition.fetching import HttpResourceFetcher
from trip_agent.acquisition.models import DiscoveredResource, KnowledgeSource
from trip_agent.acquisition.recording import (
    AcquisitionExecutionRecorder,
    AcquisitionPersisted,
    AcquisitionRecord,
    AcquisitionRecordRepository,
    CandidateSnapshot,
    ConditionalResourceState,
    FetchRunRecord,
    KnowledgeResourceRecord,
)
from trip_agent.acquisition.registry import SourceCatalog
from trip_agent.acquisition.repository import PsycopgAcquisitionRepository
from trip_agent.acquisition.scheduling import (
    AcquisitionScheduler,
    FetchAttempt,
    FetchAttemptFailed,
    FetchAttemptSucceeded,
    FetchExecution,
    FetchExecutionFailed,
    FetchExecutionSucceeded,
    RetryPolicy,
)
from trip_agent.acquisition.workflow import (
    AcquisitionExecutionScheduler,
    AcquisitionWorkflow,
    AcquisitionWorkflowResult,
)

__all__ = [
    "AcquisitionFetchError",
    "AcquisitionExecutionRecorder",
    "AcquisitionExecutionScheduler",
    "AcquisitionPersisted",
    "AcquisitionRecord",
    "AcquisitionRecordRepository",
    "AcquisitionScheduler",
    "AcquisitionWorkflow",
    "AcquisitionWorkflowResult",
    "ArticleExtractionPassed",
    "ArticleExtractionRejected",
    "ArticleExtractionResult",
    "CandidateSnapshot",
    "ConditionalResourceState",
    "DiscoveredResource",
    "ExtractedArticle",
    "ExtractionQualityIssue",
    "ExtractionPersisted",
    "ExtractionVersionConflict",
    "FetchResult",
    "FetchRunRecord",
    "FetchAttempt",
    "FetchAttemptFailed",
    "FetchAttemptSucceeded",
    "FetchExecution",
    "FetchExecutionFailed",
    "FetchExecutionSucceeded",
    "FetchValidators",
    "HttpResourceFetcher",
    "HostResolver",
    "GuangzhouGovernmentArticleExtractor",
    "KnowledgeSource",
    "KnowledgeResourceRecord",
    "PsycopgAcquisitionRepository",
    "PendingSnapshot",
    "ResourceFetched",
    "ResourceNotModified",
    "RetryPolicy",
    "SourceCatalog",
    "SnapshotExtractionProcessed",
    "SnapshotExtractionRecord",
    "SnapshotExtractionService",
    "SystemHostResolver",
]
