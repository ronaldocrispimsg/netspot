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
