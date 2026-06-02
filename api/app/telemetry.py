"""Application Insights via OpenTelemetry - emet 3 custom metrics RL."""
import logging
from .config import settings

logger = logging.getLogger("rl-api"); logger.setLevel(logging.INFO)
_meter = None
_episode_counter = None
_reward_histogram = None
_sharpe_histogram = None
_latency_histogram = None
_error_counter = None
_total_requests = 0
_total_errors = 0
_latency_sum = 0.0


def init_telemetry():
    global _meter, _episode_counter, _reward_histogram, _sharpe_histogram, _latency_histogram, _error_counter
    if not settings.applicationinsights_connection_string:
        logger.warning("APPLICATIONINSIGHTS_CONNECTION_STRING not set - telemetry disabled")
        return
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
        from opentelemetry import metrics
    except ImportError as exc:
        logger.warning("Azure SDK not installed: %s", exc); return
    configure_azure_monitor(connection_string=settings.applicationinsights_connection_string,
                            logger_name="rl-api")
    _meter = metrics.get_meter("rl-api")
    _episode_counter  = _meter.create_counter("episode_count")
    _reward_histogram = _meter.create_histogram("episode_reward")
    _sharpe_histogram = _meter.create_histogram("episode_sharpe")
    _latency_histogram = _meter.create_histogram("inference_latency_ms", unit="ms")
    _error_counter    = _meter.create_counter("api_error_count")
    logger.info("Telemetry initialized")


def record_episode(reward, sharpe, duration_ms, n_steps, n_buy, n_hold, n_sell):
    global _total_requests, _latency_sum
    _total_requests += 1; _latency_sum += duration_ms
    tags = {"agent_version": settings.model_version, "algo": settings.algo}
    if _episode_counter:  _episode_counter.add(1, tags)
    if _reward_histogram: _reward_histogram.record(reward, tags)
    if _sharpe_histogram: _sharpe_histogram.record(sharpe, tags)
    if _latency_histogram: _latency_histogram.record(duration_ms, tags)
    logger.info("EpisodeCompleted reward=%.4f sharpe=%.2f steps=%d ms=%.1f",
                reward, sharpe, n_steps, duration_ms)


def record_error(error_type):
    global _total_errors
    _total_errors += 1
    if _error_counter: _error_counter.add(1, {"error_type": error_type})
    logger.error("api_error: %s", error_type)


def get_summary():
    avg = _latency_sum / _total_requests if _total_requests else 0.0
    return {"total_requests": _total_requests, "errors": _total_errors,
            "avg_latency_ms": round(avg, 2)}
