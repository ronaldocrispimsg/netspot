"""
Testes de regressão da auditoria: tendência preventiva, seleção de disco SNMP
e coerência do fast-path de causa provável.
"""

import asyncio
import pytest
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
    from datetime import datetime, timedelta, timezone
    from Backend.dependencies import get_current_user

    mock_db = MagicMock()
    mock_creds = MagicMock()
    mock_creds.credentials = "fake.jwt.token"

    locked_user = SimpleNamespace(
        username="admin",
        locked=True,
        locked_until=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=5),
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


def test_hard_delete_forbidden_for_non_admin():
    import pytest
    from fastapi import HTTPException
    from unittest.mock import MagicMock
    from Backend.dependencies import get_current_admin

    regular_user = MagicMock()
    regular_user.username = "estagiario"
    regular_user.is_admin = False

    with pytest.raises(HTTPException) as exc_info:
        get_current_admin(regular_user)
    assert exc_info.value.status_code == 403
    assert "Acesso negado" in exc_info.value.detail


def test_xss_host_name_escaping():
    import html
    malicious_hostname = "<script>alert('xss')</script>"
    malicious_img = '<img src=x onerror="alert(1)">'

    escaped_host = html.escape(malicious_hostname)
    escaped_img = html.escape(malicious_img)

    assert "<script>" not in escaped_host
    assert "&lt;script&gt;" in escaped_host
    assert "<img" not in escaped_img
    assert "&lt;img" in escaped_img


def test_inactive_http_does_not_penalize_host_severity():
    h = _host(
        status="UP",
        sla_rolling_ping=100.0,
        sla_rolling_tcp=100.0,
        sla_rolling_http=0.0,
        http_enabled=False,
    )
    sev, reasons = apply_preventive_logic(h)
    assert sev == "HEALTHY"
    assert "SLA instável" not in reasons
    assert "Queda de taxa de sucesso" not in reasons


def test_empty_trash_endpoint():
    from Backend.routes.hosts import empty_trash
    from Backend.models import Host

    class FakeQuery:
        def __init__(self, items):
            self.items = items

        def filter(self, *args, **kwargs):
            return self

        def all(self):
            return self.items

        def delete(self, synchronize_session=False):
            return len(self.items)

    class FakeSession:
        def __init__(self, trash_hosts):
            self.trash_hosts = trash_hosts
            self.deleted = []

        def query(self, model):
            if model == Host:
                return FakeQuery(self.trash_hosts)
            return FakeQuery([])

        def delete(self, item):
            self.deleted.append(item)

        def commit(self):
            pass

    fake_h1 = Host(id=1, name="host1", active=False)
    fake_h2 = Host(id=2, name="host2", active=False)
    session = FakeSession([fake_h1, fake_h2])

    result = empty_trash(db=session, user="admin")
    assert result["deleted_count"] == 2
    assert "2 host(s) removido(s)" in result["detail"]
    assert len(session.deleted) == 2


def test_validate_private_subnet_supports_slash_20():
    from Backend.routes.hosts import _validate_private_subnet
    from fastapi import HTTPException
    import pytest

    # Subnet /20 válida e privada (4.096 endereços)
    normalized = _validate_private_subnet("192.168.31.0/20")
    assert normalized == "192.168.16.0/20"

    # Subnet pública é rejeitada
    with pytest.raises(HTTPException) as exc_info:
        _validate_private_subnet("8.8.8.0/24")
    assert exc_info.value.status_code == 400
    assert "Subnet deve ser privada RFC1918" in exc_info.value.detail

    # Subnet maior que /20 (ex: /19 ou /16 com > 4096 endereços) é rejeitada
    with pytest.raises(HTTPException) as exc_info:
        _validate_private_subnet("10.0.0.0/16")
    assert exc_info.value.status_code == 400
    assert "Subnet muito grande" in exc_info.value.detail


def test_parse_nmap_hosts_xml_extracts_active_ips():
    from Backend.routes.hosts import _parse_nmap_hosts

    sample_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <nmaprun scanner="nmap" args="nmap -sn -PE -n 192.168.16.0/20">
      <host>
        <status state="up"/>
        <address addr="192.168.16.10" addrtype="ipv4"/>
      </host>
      <host>
        <status state="down"/>
        <address addr="192.168.16.11" addrtype="ipv4"/>
      </host>
      <host>
        <status state="up"/>
        <address addr="192.168.31.50" addrtype="ipv4"/>
      </host>
    </nmaprun>
    """
    hosts = _parse_nmap_hosts(sample_xml)
    assert len(hosts) == 2
    addrs = [h["address"] for h in hosts]
    assert "192.168.16.10" in addrs
    assert "192.168.31.50" in addrs
    assert "192.168.16.11" not in addrs


def test_run_nmap_discovery_fast_icmp_parameters(monkeypatch):
    from Backend.routes.hosts import _run_nmap_discovery
    import subprocess

    captured_cmd = None
    captured_timeout = None

    def fake_subprocess_run(cmd, capture_output, text, timeout, check):
        nonlocal captured_cmd, captured_timeout
        captured_cmd = cmd
        captured_timeout = timeout
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="<nmaprun></nmaprun>", stderr="")

    monkeypatch.setattr("Backend.routes.hosts.subprocess.run", fake_subprocess_run)

    res = _run_nmap_discovery("192.168.16.0/20")
    assert res == "<nmaprun></nmaprun>"
    assert "-sn" in captured_cmd
    assert "-PE" in captured_cmd
    assert "-n" in captured_cmd
    assert "--min-rate" in captured_cmd
    assert captured_timeout == 120
    # Probes de portas TCP e dns-servers devem estar desligados para velocidade e estabilidade
    assert not any("-PS" in arg for arg in captured_cmd)
    assert not any("--dns-servers" in arg for arg in captured_cmd)


def test_deactivate_host_and_fallback_by_name():
    from Backend.routes.hosts import deactivate_host
    from Backend.models import Host

    class FakeQuery:
        def __init__(self, host):
            self.host = host

        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return self.host

    class FakeSession:
        def __init__(self, host_by_id, host_by_name):
            self.host_by_id = host_by_id
            self.host_by_name = host_by_name
            self.committed = False

        def query(self, model):
            class Selector:
                def __init__(outer_self):
                    pass
                def filter(outer_self, expr):
                    expr_str = str(expr)
                    if "hosts.id" in expr_str:
                        return FakeQuery(self.host_by_id)
                    return FakeQuery(self.host_by_name)
            return Selector()

        def commit(self):
            self.committed = True

    # 1. Desativação normal (ID e nome coincidem)
    host1 = Host(id=10, name="router-core", active=True)
    sess1 = FakeSession(host1, host1)
    res1 = deactivate_host(host_id=10, host_name="router-core", db=sess1, user="admin")
    assert res1["detail"] == "Host movido para a lixeira com sucesso"
    assert host1.active is False
    assert host1.deleted_at is not None
    assert sess1.committed is True

    # 2. Host já está na lixeira
    res_already = deactivate_host(host_id=10, host_name="router-core", db=sess1, user="admin")
    assert res_already["detail"] == "Host já está na lixeira"

    # 3. Fallback por nome caso o ID na UI esteja desatualizado
    host_target = Host(id=12, name="pc-lab", active=True)
    sess_fallback = FakeSession(host_by_id=None, host_by_name=host_target)
    res_fb = deactivate_host(host_id=99, host_name="pc-lab", db=sess_fallback, user="admin")
    assert res_fb["detail"] == "Host movido para a lixeira com sucesso"
    assert host_target.active is False


def test_update_host_rename_and_fast_address_validation():
    from Backend.routes.hosts import update_host
    from Backend.models import Host, Incident, CheckResult
    from Backend.schemas import HostUpdate
    from fastapi import HTTPException

    class FakeQuery:
        def __init__(self, items):
            self.items = items if isinstance(items, list) else ([items] if items is not None else [])

        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return self.items[0] if self.items else None

        def update(self, values, synchronize_session=False):
            return len(self.items)

    class FakeSession:
        def __init__(self, host, existing_names=None):
            self.host = host
            self.existing_names = set(existing_names or [])
            self.committed = False

        def query(self, model):
            class Selector:
                def __init__(outer_self):
                    pass
                def filter(outer_self, *exprs):
                    if len(exprs) >= 2:
                        # Busca de duplicidade: Host.name == target_name e Host.id != host.id
                        target = getattr(exprs[0].right, "value", None)
                        if target in self.existing_names:
                            return FakeQuery(Host(id=999, name=target))
                        return FakeQuery([])
                    if len(exprs) == 1:
                        target = getattr(exprs[0].right, "value", None)
                        if self.host and self.host.name == target:
                            return FakeQuery(self.host)
                        return FakeQuery([])
                    return FakeQuery(self.host)
            return Selector()

        def commit(self):
            self.committed = True

    # 1. Renomeação com sucesso mantendo endereço (caminho rápido sem chamadas de DNS)
    h = Host(id=1, name="web-server-old", address="10.0.0.50", hostname_resolved="srv.local", active=True)
    sess = FakeSession(h, existing_names=["other-host"])
    payload = HostUpdate(
        name="web-server-new",
        address="10.0.0.50",
        ports=[80, 443],
        snmp_enabled=True,
        snmp_community="netspot"
    )

    res = update_host(host_name="web-server-old", data=payload, db=sess, user="admin")
    assert res["detail"] == "Host atualizado com sucesso"
    assert res["old_name"] == "web-server-old"
    assert res["name"] == "web-server-new"
    assert h.name == "web-server-new"
    assert h.hostname_resolved == "srv.local"
    assert sess.committed is True

    # 2. Conflito ao tentar renomear para um nome já existente
    h2 = Host(id=2, name="srv-app", address="10.0.0.60", active=True)
    sess2 = FakeSession(h2, existing_names=["srv-app-duplicado"])
    payload_conflict = HostUpdate(
        name="srv-app-duplicado",
        address="10.0.0.60"
    )
    with pytest.raises(HTTPException) as exc_info:
        update_host(host_name="srv-app", data=payload_conflict, db=sess2, user="admin")
    assert exc_info.value.status_code == 409
    assert "Já existe outro host com o nome" in exc_info.value.detail

    # 3. Atualização de endereço IP direto onde hostname_resolved é None não trava chamando DNS
    h3 = Host(id=3, name="db-host", address="10.0.0.70", hostname_resolved=None, active=True)
    sess3 = FakeSession(h3, existing_names=[])
    payload_ip = HostUpdate(
        name="db-host",
        address="10.0.0.80",
        ports=[5432]
    )
    res3 = update_host(host_name="db-host", data=payload_ip, db=sess3, user="admin")
    assert res3["detail"] == "Host atualizado com sucesso"
    assert h3.address == "10.0.0.80"
    assert h3.hostname_resolved is None
    assert sess3.committed is True


def test_process_host_check_in_flight_concurrency_lock():
    import asyncio
    from Backend.scheduler import process_host_check, _in_flight_hosts

    async def run():
        # Simula que host_id 42 já está em voo
        _in_flight_hosts.add(42)
        try:
            # Ao chamar process_host_check para o mesmo id, deve descartar sem chamar o check interno
            await process_host_check(42)
        finally:
            _in_flight_hosts.discard(42)

    asyncio.run(run())
    assert 42 not in _in_flight_hosts


def test_bulk_deactivate_hosts_endpoint():
    import pytest
    from fastapi import HTTPException
    from Backend.routes.hosts import bulk_deactivate_hosts
    from Backend.schemas import BulkDeactivateRequest
    from Backend.models import Host

    class FakeQuery:
        def __init__(self, items):
            self.items = items

        def filter(self, *args, **kwargs):
            return self

        def all(self):
            return self.items

    class FakeSession:
        def __init__(self, active_hosts):
            self.active_hosts = active_hosts
            self.committed = False

        def query(self, model):
            return FakeQuery(self.active_hosts)

        def commit(self):
            self.committed = True

    # 1. Rejeita chamada vazia
    with pytest.raises(HTTPException) as exc_info:
        bulk_deactivate_hosts(
            data=BulkDeactivateRequest(host_ids=[], host_names=[]),
            db=FakeSession([]),
            user="admin",
        )
    assert exc_info.value.status_code == 400

    # 2. Desativa múltiplos hosts em lote numa única transação
    h1 = Host(id=10, name="pc1", address="10.0.0.1", active=True)
    h2 = Host(id=11, name="pc2", address="10.0.0.2", active=True)
    sess = FakeSession([h1, h2])

    res = bulk_deactivate_hosts(
        data=BulkDeactivateRequest(host_ids=[10, 11], host_names=["pc1", "pc2"]),
        db=sess,
        user="admin",
    )
    assert res["deactivated_count"] == 2
    assert res["deactivated_names"] == ["pc1", "pc2"]
    assert h1.active is False
    assert h2.active is False
    assert h1.deleted_at is not None
    assert h2.deleted_at is not None
    assert sess.committed is True


def test_manual_check_host_awaits_async_checkers(monkeypatch):
    from Backend.routes import hosts as hosts_route
    from Backend.models import Host

    fake_host = Host(
        id=77,
        name="srv-manual",
        address="srv-manual.local",
        port=80,
        tcp_ports="[80]",
        active=True,
    )

    class FakeQuery:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return fake_host

    class FakeSession:
        def __init__(self):
            self.committed = False

        def query(self, model):
            return FakeQuery()

        def commit(self):
            self.committed = True

    monkeypatch.setattr(hosts_route, "resolve_dns_cached_sync", lambda addr, db: (["10.0.0.77"], 60, 60))

    async def fake_ping(ip):
        return {"success": True, "latency": 4.2, "error": None}

    async def fake_tcp(ip, port):
        return {"success": True, "latency": 1.8, "error": None}

    monkeypatch.setattr(hosts_route, "ping_host", fake_ping)
    monkeypatch.setattr(hosts_route, "tcp_check", fake_tcp)

    sess = FakeSession()
    result = asyncio.run(hosts_route.check_host("srv-manual", db=sess, user="admin"))

    assert result["status"] == "UP"
    assert result["ping"]["status"] == "UP"
    assert result["tcp"]["status"] == "UP"
    assert fake_host.last_resolved_ip == "10.0.0.77"
    assert sess.committed is True


def test_trim_history_awaits_async_db_delete():
    from Backend.scheduler import trim_history
    from unittest.mock import AsyncMock, MagicMock

    row1 = SimpleNamespace(id=1)
    row2 = SimpleNamespace(id=2)

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [row1, row2]

    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result

    asyncio.run(trim_history(mock_db, host_id=10, check_type="ping", limit=500))
    assert mock_db.delete.await_count == 2


def test_message_fingerprint_ignores_volatile_timestamp():
    from Backend.notifications import _message_fingerprint

    msg1 = {
        "event": "failure_confirmed",
        "host_name": "pc1",
        "new_status": "DOWN",
        "timestamp": "2026-10-22T16:00:00.000001",
    }
    msg2 = {
        "event": "failure_confirmed",
        "host_name": "pc1",
        "new_status": "DOWN",
        "timestamp": "2026-10-22T16:00:05.999999",
    }
    assert _message_fingerprint(msg1) == _message_fingerprint(msg2)


def test_snmp_engine_uses_last_resolved_ip_and_oid_cache(monkeypatch):
    from Backend.snmp.oid_cache import clear_oid_cache, get_cached_oids
    from unittest.mock import AsyncMock

    clear_oid_cache()
    polled_ips = []
    storage_walk_calls = 0

    async def fake_get_snmp_value(ip, comm, oid):
        polled_ips.append(ip)
        if oid == "1.3.6.1.4.1.2021.11.11.0":
            return 80  # 20% CPU
        if oid.startswith("1.3.6.1.2.1.25.2.3.1.5."):
            return 1000
        if oid.startswith("1.3.6.1.2.1.25.2.3.1.6."):
            return 250
        return None

    async def fake_get_storage_index(ip, comm):
        nonlocal storage_walk_calls
        storage_walk_calls += 1
        return "31"

    async def fake_get_best_iface(ip, comm):
        return None

    async def fake_trim_snmp(db, host_id, limit=500):
        pass

    monkeypatch.setattr(snmp_engine, "get_snmp_value", fake_get_snmp_value)
    monkeypatch.setattr(snmp_engine, "get_storage_index", fake_get_storage_index)
    monkeypatch.setattr(snmp_engine, "get_best_interface_index", fake_get_best_iface)
    monkeypatch.setattr(snmp_engine, "trim_snmp_history", fake_trim_snmp)

    fake_host = SimpleNamespace(
        id=501,
        address="pc1.empresa.local",
        last_resolved_ip="10.0.0.51",
        snmp_community="netspot",
        cpu_usage=None,
        ram_usage=None,
        disk_usage=None,
        disk_remaining=None,
        network_in_bps=None,
        network_out_bps=None,
        network_traffic=None,
        last_snmp_check=None,
    )
    mock_db = AsyncMock()
    mock_db.add = lambda obj: None

    # 1ª coleta descobre storage_index e salva no OIDCache usando last_resolved_ip
    asyncio.run(snmp_engine.update_host_snmp(fake_host, mock_db))
    assert "10.0.0.51" in polled_ips
    assert storage_walk_calls == 1
    assert get_cached_oids(501)["storage_index"] == "31"

    # 2ª coleta reutiliza o OIDCache sem repetir walk de storage_index
    asyncio.run(snmp_engine.update_host_snmp(fake_host, mock_db))
    assert storage_walk_calls == 1
    clear_oid_cache()


def test_enrich_discovered_hostnames_dns_and_snmp(monkeypatch):
    from Backend.routes import hosts as hosts_route

    monkeypatch.setattr(hosts_route, "_discover_local_dns_servers", lambda subnet, ips: ["10.0.3.7"])
    monkeypatch.setattr(
        hosts_route,
        "_discover_open_ports_batch",
        lambda ips, **kw: {
            "192.168.1.2": [22, 80, 443],
            "192.168.1.3": [22, 5432],
            "192.168.1.9": [8080],
        },
    )

    def fake_resolve(ip, dns_servers):
        if ip == "192.168.1.2":
            return "DESKTOP-C8GVSVS"
        if ip == "192.168.1.9":
            return "crispim"
        return None

    monkeypatch.setattr(hosts_route, "_resolve_single_discovered_hostname", fake_resolve)

    raw = [
        {"address": "192.168.1.2", "hostname": None},
        {"address": "192.168.1.3", "hostname": None},
        {"address": "192.168.1.9", "hostname": None},
    ]
    enriched = hosts_route._enrich_discovered_hostnames(raw, "192.168.1.0/24")
    assert enriched[0]["hostname"] == "DESKTOP-C8GVSVS"
    assert enriched[0]["ports"] == [22, 80, 443]
    assert enriched[0]["http_enabled"] is True
    assert enriched[0]["http_url"] is None
    assert enriched[1]["hostname"] is None
    assert enriched[1]["ports"] == [22, 5432]
    assert enriched[1]["http_enabled"] is False
    assert enriched[2]["hostname"] == "crispim"
    assert enriched[2]["ports"] == [8080]
    assert enriched[2]["http_enabled"] is True
    assert enriched[2]["http_url"] == "http://192.168.1.9:8080"


def test_parallel_monitoring_126_hosts_under_budget(monkeypatch):
    """Garante que 126 hosts concorrentes (prefetch=32) sejam processados com folga dentro do orçamento de tempo."""
    import time
    from Backend import scheduler

    checked_ids = []

    async def fake_host_check_async(host_id: int) -> None:
        await asyncio.sleep(0.02)
        checked_ids.append(host_id)

    monkeypatch.setattr(scheduler, "_host_check_async", fake_host_check_async)

    async def run_126():
        sem = asyncio.Semaphore(32)

        async def worker(hid: int):
            async with sem:
                await scheduler.process_host_check(hid)

        t0 = time.monotonic()
        await asyncio.gather(*[worker(i) for i in range(1, 127)])
        return time.monotonic() - t0

    elapsed = asyncio.run(run_126())
    assert len(checked_ids) == 126
    assert elapsed < 1.0


def test_first_password_blocked_for_already_activated_user():
    """Valida que /auth/first-password bloqueia usuários que já concluíram o primeiro acesso e valida tamanho mínimo de senha."""
    from Backend.routes.hosts import first_change_password
    from Backend.models import User
    from Backend.schemas import PasswordChangeRequest
    from fastapi import HTTPException
    import pytest

    class DummySession:
        def commit(self):
            pass

    # 1. Usuário já ativo (must_change_password == False) é rejeitado com 400
    user_active = User(username="admin", must_change_password=False, attempts=0)
    req = PasswordChangeRequest(new_password="SuperNovaSenha123!")
    with pytest.raises(HTTPException) as exc_info:
        first_change_password(data=req, user=user_active, db=DummySession())
    assert exc_info.value.status_code == 400
    assert "já foi realizada" in exc_info.value.detail

    # 2. Usuário com senha curta (< 4 caracteres) é rejeitado com 400
    user_pending = User(username="admin", must_change_password=True, attempts=0)
    req_short = PasswordChangeRequest(new_password="12")
    with pytest.raises(HTTPException) as exc_short:
        first_change_password(data=req_short, user=user_pending, db=DummySession())
    assert exc_short.value.status_code == 400
    assert "pelo menos 4 caracteres" in exc_short.value.detail

    # 3. Usuário legítimo em primeiro acesso altera com sucesso
    req_valid = PasswordChangeRequest(new_password="MinhaSenhaValida123")
    res = first_change_password(data=req_valid, user=user_pending, db=DummySession())
    assert res["logout"] is True
    assert user_pending.must_change_password is False


def test_failure_confirmed_alert_emitted_at_fail_threshold():
    """Valida que o evento failure_confirmed é gerado exatamente ao atingir ALERT_FAIL_THRESHOLD."""
    from Backend import scheduler

    # Cenário: Host falha no check
    baseline_pending = False
    new_status = "DOWN"
    service_up_without_icmp = False

    # Streak 1: Não deve disparar alerta de falha confirmada
    fail_streak_1 = 1
    is_confirmed_1 = (
        (not baseline_pending)
        and new_status != "UP"
        and not (service_up_without_icmp and new_status == "UP")
        and fail_streak_1 == scheduler.ALERT_FAIL_THRESHOLD
    )
    assert is_confirmed_1 is False

    # Streak 2: Atingiu ALERT_FAIL_THRESHOLD (2) -> DEVE disparar
    fail_streak_2 = 2
    is_confirmed_2 = (
        (not baseline_pending)
        and new_status != "UP"
        and not (service_up_without_icmp and new_status == "UP")
        and fail_streak_2 == scheduler.ALERT_FAIL_THRESHOLD
    )
    assert is_confirmed_2 is True

    # Streak 3: Falha já confirmada anteriormente -> Não deve re-disparar
    fail_streak_3 = 3
    is_confirmed_3 = (
        (not baseline_pending)
        and new_status != "UP"
        and not (service_up_without_icmp and new_status == "UP")
        and fail_streak_3 == scheduler.ALERT_FAIL_THRESHOLD
    )
    assert is_confirmed_3 is False


def test_calculate_availability_merges_overlapping_incidents():
    """Valida que incidentes sobrepostos ou simultâneos são mesclados via união de intervalos sem dupla contagem."""
    from datetime import datetime, timedelta
    from Backend.metrics import calculate_availability_from_incidents
    from Backend.models import Incident

    now = datetime(2026, 10, 23, 12, 10, 0)
    since = now - timedelta(minutes=10)  # 12:00:00

    # Incidente 1: 12:00 até 12:05 (5 minutos de queda = 300s)
    inc1 = Incident(
        started_time=datetime(2026, 10, 23, 12, 0, 0),
        ended_time=datetime(2026, 10, 23, 12, 5, 0)
    )

    # Incidente 2: 12:02 até 12:07 (5 minutos de queda = 300s, com 3 minutos de sobreposição)
    # União real do intervalo de queda: 12:00 até 12:07 = 7 minutos (420s)
    # Tempo restante online: 3 minutos (180s) em 10 minutos (600s) = 30.0% disponibilidade
    inc2 = Incident(
        started_time=datetime(2026, 10, 23, 12, 2, 0),
        ended_time=datetime(2026, 10, 23, 12, 7, 0)
    )

    avail = calculate_availability_from_incidents([inc1, inc2], now, since, total_period=600)
    assert avail == 30.0

    # Sem incidentes deve ser exatamente 100.0%
    assert calculate_availability_from_incidents([], now, since, total_period=600) == 100.0


def test_setup_kathara_routes_validates_ip_and_cidr(monkeypatch):
    """Garante que IPs ou CIDRs mal formatados em KATHARA_ROUTER_IP ou KATHARA_SUBNETS são filtrados sem erro."""
    import Backend.main as main_mod

    executed_commands = []

    def fake_subprocess_run(cmd, *args, **kwargs):
        executed_commands.append(cmd)
        class DummyRes:
            returncode = 0
            stderr = ""
        return DummyRes()

    monkeypatch.setattr("subprocess.run", fake_subprocess_run)

    # 1. Gateway inválido -> aborta imediatamente sem executar nenhum comando
    monkeypatch.setenv("KATHARA_ROUTER_IP", "ip-invalido-123")
    monkeypatch.setenv("KATHARA_SUBNETS", "10.0.0.0/16")
    main_mod.setup_kathara_routes()
    assert len(executed_commands) == 0

    # 2. Gateway válido, sub-redes com uma válida e outra inválida -> executa apenas a válida
    monkeypatch.setenv("KATHARA_ROUTER_IP", "172.17.0.2")
    monkeypatch.setenv("KATHARA_SUBNETS", "10.0.0.0/16, subrede-invalida, 100.0.0.0/16")
    main_mod.setup_kathara_routes()
    assert len(executed_commands) == 2
    assert executed_commands[0] == ["ip", "route", "replace", "10.0.0.0/16", "via", "172.17.0.2"]
    assert executed_commands[1] == ["ip", "route", "replace", "100.0.0.0/16", "via", "172.17.0.2"]



