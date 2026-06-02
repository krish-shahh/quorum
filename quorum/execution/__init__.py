"""Execution layer: paper broker, safety, analytics, trade logging."""

from .db import close_db, get_db, migrate, query_trades
from .executor import ExecutionEngine
from .schemas import (
    AccountInfo,
    DiscoveredTicker,
    DiscoveryStatus,
    ExecutionRecord,
    OrderRequest,
    OrderResult,
    OrderStatus,
    PoliticianSignal,
    PoliticianTrade,
    Position,
    Quote,
)
from .stop_loss import StopLossMonitor
from .confidence import compute_confidence_score, adjust_position_size
from .learning import LearningEngine
from .analytics import generate_performance_summary
