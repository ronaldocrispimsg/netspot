"""
Testes de regressão da auditoria: tendência preventiva, seleção de disco SNMP
e coerência do fast-path de causa provável.
"""

import asyncio
from types import SimpleNamespace

from Backend import snmp_engine
from Backend.metrics import apply_preventive_logic


def _host(**overrides):
    base = dict(
        status="UP",
        sla_rolling_ping=100,
        sla_rolling_tcp=None,
        sla_rolling_http=None,
        jitter_ms_ping=5,
        jitter_ms_tcp=None,
        jitter_ms_http=None,
        trend="STABLE",
        trend_http="STABLE",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_preventive_trend_ping_degrading_triggers_warning():
    sev, reasons = apply_preventive_logic(_host(trend="DEGRADING"))
    assert sev == "WARNING"
    assert "Tendência de piora no ping" in reasons


def test_preventive_trend_http_critical_triggers_warning():
    sev, reasons = apply_preventive_logic(_host(trend_http="CRITICAL"))
    assert sev == "WARNING"
    assert "Tendência de piora no HTTP" in reasons


def test_preventive_trend_stable_stays_healthy():
    sev, reasons = apply_preventive_logic(_host())
    assert sev == "HEALTHY"
    assert reasons == []


def test_storage_index_prefers_root_over_other_mounts(monkeypatch):
    async def fake_walk(ip, community, oid):
        return [
            ("1.3.6.1.2.1.25.2.3.1.3.10", '"/run"'),
            ("1.3.6.1.2.1.25.2.3.1.3.11", '"/dev/shm"'),
            ("1.3.6.1.2.1.25.2.3.1.3.31", '"/"'),
        ]

    monkeypatch.setattr(snmp_engine, "walk_snmp", fake_walk)
    idx = asyncio.run(snmp_engine.get_storage_index("127.0.0.1", "netspot"))
    assert idx == "31"


def test_storage_index_windows_drive_prefix(monkeypatch):
    async def fake_walk(ip, community, oid):
        return [
            ("1.3.6.1.2.1.25.2.3.1.3.1", '"Physical Memory"'),
            ("1.3.6.1.2.1.25.2.3.1.3.2", '"C:\\ Label:Sistema  Serial Number 1234"'),
        ]

    monkeypatch.setattr(snmp_engine, "walk_snmp", fake_walk)
    idx = asyncio.run(snmp_engine.get_storage_index("127.0.0.1", "netspot"))
    assert idx == "2"


def _fake_db_with_rows(rows):
    from unittest.mock import MagicMock
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = rows
    return db


def test_sla_requires_minimum_samples():
    from Backend.metrics import calc_sla_rolling_ping, MIN_SLA_SAMPLES

    few = [SimpleNamespace(success=False)] * (MIN_SLA_SAMPLES - 1)
    assert calc_sla_rolling_ping(_fake_db_with_rows(few), 1) is None

    enough = [SimpleNamespace(success=True)] * MIN_SLA_SAMPLES
    assert calc_sla_rolling_ping(_fake_db_with_rows(enough), 1) == 100.0


def test_calculate_availability_from_incidents():
    from datetime import datetime, timedelta, timezone
    from Backend.metrics import calculate_availability_from_incidents

    now = datetime(2026, 10, 20, 12, 0, 0)
    since = now - timedelta(minutes=10)

    # Sem incidentes: 100% de disponibilidade
    assert calculate_availability_from_incidents([], now, since) == 100.0

    # Incidente de 3 minutos (180s) em 600s = 70% de disponibilidade
    inc = SimpleNamespace(
        started_time=now - timedelta(minutes=5),
        ended_time=now - timedelta(minutes=2),
    )
    assert calculate_availability_from_incidents([inc], now, since) == 70.0


def test_infer_probable_cause_healthy_fast_path_avoids_db():
    from unittest.mock import MagicMock
    from Backend.routes.hosts import infer_probable_cause

    db = MagicMock()
    healthy_host = SimpleNamespace(
        id=1,
        status="UP",
        status_ping="UP",
        severity="HEALTHY",
        cpu_usage=15.0,
        ram_usage=40.0,
        disk_usage=55.0,
        jitter_ms_ping=10.0,
    )
    result = infer_probable_cause(db, healthy_host)
    assert result == "Operação normal"
    # Nenhuma query executada no banco para host saudável com status_ping UP
    assert db.query.call_count == 0


def test_circuit_breaker_blocks_polling_when_open():
    from Backend.services.circuit_breaker import HostCircuitBreaker

    cb = HostCircuitBreaker(failure_threshold=3, recovery_timeout=60.0)
    host_id = 42

    assert cb.is_allowed(host_id) is True

    # 3 falhas consecutivas disparam OPEN
    cb.record_failure(host_id)
    cb.record_failure(host_id)
    cb.record_failure(host_id)

    assert cb.state[host_id] == "OPEN"
    assert cb.is_allowed(host_id) is False

    # Sucesso fecha imediatamente
    cb.record_success(host_id)
    assert cb.state[host_id] == "CLOSED"
    assert cb.is_allowed(host_id) is True


def test_locked_user_denied_access():
    import pytest
    from fastapi import HTTPException
    from unittest.mock import MagicMock
    from datetime import datetime, timedelta
    from Backend.dependencies import get_current_user

    mock_db = MagicMock()
    mock_creds = MagicMock()
    mock_creds.credentials = "fake.jwt.token"

    locked_user = SimpleNamespace(
        username="admin",
        locked=True,
        locked_until=datetime.now() + timedelta(minutes=5),
        attempts=5,
    )
    mock_db.query.return_value.filter.return_value.first.return_value = locked_user

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("Backend.dependencies.decode_token", lambda token: {"sub": "admin"})
        with pytest.raises(HTTPException) as exc_info:
            get_current_user(mock_creds, mock_db)
        assert exc_info.value.status_code == 403
        assert "bloqueada" in exc_info.value.detail.lower()


def test_tcp_check_timeout_handling(monkeypatch):
    from Backend.checker import tcp_check

    async def fake_open_connection(ip, port):
        await asyncio.sleep(10)

    monkeypatch.setattr(asyncio, "open_connection", fake_open_connection)
    result = asyncio.run(tcp_check("192.168.1.1", 80, timeout=0.05))

    assert result["success"] is False
    assert result["error"] == "timeout"
    assert result["latency"] is None


def test_models_utcnow_naive_default():
    from Backend.models import CheckResult, Incident, Alert, SNMPMetric, _utcnow_naive
    from datetime import datetime

    ts = _utcnow_naive()
    assert isinstance(ts, datetime)
    assert ts.tzinfo is None  # naive para integridade com SQLite/Postgres

    assert CheckResult.timestamp.default.arg.__name__ == "_utcnow_naive"
    assert Incident.started_time.default.arg.__name__ == "_utcnow_naive"
    assert Alert.timestamp.default.arg.__name__ == "_utcnow_naive"
    assert SNMPMetric.timestamp.default.arg.__name__ == "_utcnow_naive"

    # Garantir que a invocação do default do SQLAlchemy retorna datetime válido
    eval_ts = CheckResult.timestamp.default.arg(None)
    assert isinstance(eval_ts, datetime)
    assert eval_ts.tzinfo is None


def test_healthz_handles_db_timeout(monkeypatch):
    from fastapi import Response
    from Backend.routes.health import health_check

    class HangingSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        async def execute(self, stmt):
            await asyncio.sleep(10)

    monkeypatch.setattr("Backend.routes.health.AsyncSessionLocal", lambda: HangingSession())

    class FakeMQ:
        connection = type("Conn", (), {"is_closed": False})()
        channel = type("Chan", (), {"is_closed": False})()

    monkeypatch.setattr("Backend.routes.health.mq_manager", FakeMQ())

    resp = Response()
    with monkeypatch.context() as m:
        async def mock_wait_for(fut, timeout):
            if hasattr(fut, "close"):
                fut.close()
            raise asyncio.TimeoutError()

        m.setattr(asyncio, "wait_for", mock_wait_for)
        result = asyncio.run(health_check(resp))

    assert result["status"] == "UNHEALTHY"
    assert result["database"] == "DOWN"
    assert resp.status_code == 503







