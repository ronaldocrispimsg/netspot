# Documentação Completa de Funcionalidades e Arquitetura - NetSpot (NOC Lite)

Este documento descreve detalhadamente todas as funcionalidades, mecanismos de resiliência, inteligência estatística, arquitetura de software e recursos de interface do sistema **NetSpot**.

---

## Sumário
1. [Visão Geral e Arquitetura](#1-visão-geral-e-arquitetura)
2. [Mecanismos de Autocura e Resiliência (Self-Healing)](#2-mecanismos-de-autocura-e-resiliência-self-healing)
3. [As Funcionalidades Avançadas de Engenharia](#3-as-funcionalidades-avançadas-de-engenharia)
4. [Protocolos de Monitoramento e Motor SNMP Multivendor](#4-protocolos-de-monitoramento-e-motor-snmp-multivendor)
5. [Motor Heurístico de Causa Provável (Probable Cause Engine)](#5-motor-heurístico-de-causa-provável-probable-cause-engine)
6. [Descoberta Automática de Rede e Gestão de Hosts](#6-descoberta-automática-de-rede-e-gestão-de-hosts)
7. [Métricas NOC, SLA, Jitter e Score de Saúde](#7-métricas-noc-sla-jitter-e-score-de-saúde)
8. [Política de Retenção e Limpeza Contínua de Dados](#8-política-de-retenção-e-limpeza-contínua-de-dados)
9. [Gestão de Alertas, Incidentes e Barramento AMQP (RabbitMQ + n8n)](#9-gestão-de-alertas-incidentes-e-barramento-amqp-rabbitmq--n8n)
10. [Interface Frontend SPA (UX, Ergonomia e Acessibilidade WCAG 2.1 AA)](#10-interface-frontend-spa-ux-ergonomia-e-acessibilidade-wcag-21-aa)
11. [Ambiente de Laboratório Kathará (40+ Nós)](#11-ambiente-de-laboratório-kathará-40-nós)
12. [Suíte de Testes Automatizados (Pytest)](#12-suíte-de-testes-automatizados-pytest)
13. [Licenciamento](#13-licenciamento)

---

## 1. Visão Geral e Arquitetura

O **NetSpot** é uma plataforma moderna de **Network Operations Center (NOC Lite)** projetada para monitorar em tempo real a saúde, latência, disponibilidade de protocolos e consumo de recursos de ativos de infraestrutura de TI.

### Princípios de Engenharia e Design:
- **Clean Architecture & SOLID**: Separação estrita de responsabilidades entre entidades de domínio (`Backend/models.py`), contratos e esquemas (`Backend/schemas.py`), adaptadores de entrada (`Backend/routes/`), serviços de regras de negócio (`Backend/services/`), orquestração assíncrona (`Backend/scheduler.py` e `Backend/checker.py`) e subsistema SNMP (`Backend/snmp/`).
- **Concorrência Assíncrona Não-Bloqueante**: Construído sobre FastAPI, Starlette e AsyncIO, permitindo que centenas de sondagens de rede I/O-bound executem simultaneamente sem travar o event loop principal.
- **Containerização Total**: Isolamento em 5 microsserviços orquestrados via Docker Compose (FastAPI, PostgreSQL 15, RabbitMQ 3 Management, n8n Automation e Nginx Alpine).

```text
                                 +-------------------------+
                                 |   Navegador Web / NOC   |
                                 |  (SPA HTML5 / Vanilla)  |
                                 +------------+------------+
                                              | :8080 (Nginx Alpine)
                                              v
+------------------+             +-------------------------+             +------------------+
|  Base de Dados   |  SQLAlchemy  |     Backend FastAPI     |   PySNMP    | Agentes Nativos  |
|  PostgreSQL 15   |<----------->|   (Python 3.11 / 3.12)  |<----------->| (Windows/Linux/  |
+------------------+  AsyncPG    +------------+------------+  UDP :161   | Cisco/Mikrotik)  |
                                              | AMQP                     +------------------+
                                              v
                                 +-------------------------+
                                 |   RabbitMQ Message Bus  |
                                 |   (Filas, DLX & DLQ)    |
                                 +------------+------------+
                                              | Webhook
                                              v
                                 +-------------------------+             +------------------+
                                 |     n8n Automation      |------------>| Alertas Telegram |
                                 +-------------------------+             +------------------+
```

---

## 2. Mecanismos de Autocura e Resiliência (Self-Healing)

O NetSpot possui um núcleo auto-regenerativo projetado para tolerar falhas temporárias de infraestrutura sem interromper o serviço FastAPI:

### A) Autocura do PostgreSQL (`Backend/database.py`)
- **Pool Auto-Regenerativo**: Configurado no SQLAlchemy com `pool_pre_ping=True` (testa a integridade de cada conexão antes de utilizá-la) e `pool_recycle=1800` (recicla conexões TCP ociosas a cada 30 minutos).
- **Dimensionamento Seguro do Pool**: `pool_size=20`, `max_overflow=10`, `pool_timeout=30`.
- **Loop de Reconexão a Frio (`wait_for_database`)**: Na inicialização do Docker Compose, se o PostgreSQL estiver em processo de boot, o FastAPI tenta reconectar por até 15 vezes com backoff exponencial sem abortar a aplicação.

### B) Autocura do RabbitMQ (`Backend/mq_manager.py`)
- **Conexão Resiliente**: Conexão estabelecida via `aio_pika.connect_robust()`, que restabelece o canal TCP automaticamente em caso de oscilações de rede.
- **Monitor de Segundo Plano (`_monitor_connection_loop`)**: Loop assíncrono que verifica a saúde do broker periodicamente. Em caso de queda, reconecta de forma transparente e reinscreve todos os consumidores automaticamente.

---

## 3. As Funcionalidades Avançadas de Engenharia

### 1. Diagnóstico de Saúde Nativo (`/healthz` + Docker Healthcheck)
- Endpoint `/healthz` que executa testes em sub-milissegundos no PostgreSQL (`SELECT 1`) e nos canais do RabbitMQ.
- Integrado ao `docker-compose.yml` via `healthcheck`, permitindo que o Docker monitore o estado do container e o reinicie caso fique inativo.

### 2. Pattern Circuit Breaker (Disjuntor de Polling)
- Implementado em `Backend/services/circuit_breaker.py`.
- Se um dispositivo acumular 5 falhas consecutivas de resposta (`failure_threshold`), o circuito transita de `CLOSED` para `OPEN`.
- Durante o período em `OPEN`, o NetSpot suspende o envio de novos pings e sondagens SNMP para o host, impedindo tempestades de pacotes (*storm effect*) e saturação desnecessária de sockets.
- Após o período de resfriamento, o disjuntor entra em `HALF-OPEN` para emitir uma sondagem de teste. Havendo sucesso, o circuito fecha novamente (`CLOSED`).

### 3. Dead Letter Queue (DLQ) no RabbitMQ (`netspot.dlq`)
- Declaração automática da *Dead Letter Exchange* (`netspot.dlx`) e *Dead Letter Queue* (`netspot.dlq`).
- Mensagens que falham no processamento de notificações ou tarefas são encaminhadas para a DLQ, assegurando retenção integral de eventos para auditoria sem perda de dados.

### 4. Anti-Fadiga de Alertas e Supressão de Flapping
- Função `is_flapping_suppressed()` em `Backend/notifications.py`.
- Detecta oscilações rápidas e repetitivas de estado (`UP` <-> `DOWN` frequentes em janelas curtas).
- Suprime disparos repetitivos para o Telegram, protegendo os operadores de rede contra a fadiga de alertas (*Alert Fatigue*).

### 5. Desligamento Gracioso (Graceful Shutdown com SIGTERM)
- Interceptação e tratamento seguro dos sinais de sistema `SIGTERM` e `SIGINT` em `Backend/main.py`.
- Ao executar `docker stop`, o sistema suspende o agendador de coletas, aguarda a conclusão das tarefas em andamento e libera os pools do SQLAlchemy (`engine.dispose()`) e canais de mensageria.

### 6. Prevenção de Subprocessos Zumbis
- No módulo `Backend/checker.py`, a execução de comandos `ping` utiliza `asyncio.wait_for` com timeout forçado e encerramento com `SIGKILL` em caso de timeout, impedindo acúmulo de processos órfãos na tabela de processos do sistema operacional.

---

## 4. Protocolos de Monitoramento e Motor SNMP Multivendor

### Protocolos Suportados:
- **ICMP Ping**: Medição de latência precisa em milissegundos e cálculo de taxa de perda de pacotes.
- **Portas TCP**: Varredura de sockets em portas de aplicação (ex.: 22/SSH, 80/HTTP, 443/HTTPS, 3306/MySQL, 5432/PostgreSQL).
- **HTTP / HTTPS**: Validação de código de retorno (200 OK), tempo de resposta e análise de tendências de degradação.
- **DNS Resolver**: Validação de resolução de nomes de domínio (registros A).

### Agente SNMP Multivendor (`Backend/snmp/`):
- **Linux (UCD-SNMP-MIB)**: Leitura de CPU (`ssCpuIdle`), Memória RAM (`memTotalReal`, `memAvailReal`), Disco (`/`) e Contadores de Tráfego de Interfaces.
- **Windows (HOST-RESOURCES-MIB)**: Leitura de CPU (`hrProcessorLoad`), RAM (`hrStorageSize`, `hrStorageUsed` para `Virtual/Physical Memory`), Disco (`C:\` e pontos de montagem) e Interfaces de Rede.
- **Dispositivos de Rede (Cisco, Mikrotik, Huawei, Fortinet)**: Coleta de tráfego de interface em 32 bits e 64 bits (`ifHCInOctets`/`ifHCOutOctets`) e telemetria de hardware específica por fabricante.
- **Segurança Operacional**: Utilização da community padrão customizada `netspot` com rejeição de credenciais vulneráveis legadas (`public`).
- **Salvaguarda contra Loops MIB**: Teto estrito de 500 iterações em caminhamentos `walk_snmp` para proteger o coletor contra nós mal configurados.

---

## 5. Motor Heurístico de Causa Provável (Probable Cause Engine)

Implementado em `Backend/routes/hosts.py` (`infer_probable_cause`), o algoritmo analisa as métricas coletadas em conformidade com o modelo OSI:
- **Bloqueio por Firewall Corporativo**: Quando o ping ICMP falha (100% de perda), mas as portas TCP ou serviços HTTP respondem com sucesso, o sistema infere *"Firewall bloqueando ICMP (serviço ativo)"*.
- **Sobrecarga de Processador**: Quando a utilização de CPU via SNMP ultrapassa 90%, infere *"Sobrecarga de processador (CPU > 90%)"*.
- **Saturação de Armazenamento**: Quando a ocupação do disco principal excede 90%, infere *"Espaço em disco crítico (> 90%)"*.
- **Instabilidade de Rede por Jitter**: Quando há variação estatística excessiva entre tempos de resposta consecutivos, infere *"Degradação por Jitter elevado (> 80ms)"*.
- **Falha de Resolução de Nomes**: Quando a consulta DNS não obtém resposta, infere *"Falha na resolução de nomes (DNS indisponível)"*.

A heurística opera por caminhos rápidos determinísticos (*Fast-Path*), garantindo diagnósticos auditáveis, explicáveis e sem alucinações.

---

## 6. Descoberta Automática de Rede e Gestão de Hosts

- **Varredura de Sub-rede**: Rota `/network/discover` realiza varredura com controle de concorrência em faixas CIDR (suportando até `/20` com 4.096 IPs), identificando nós ativos via ICMP com alta velocidade sem sobrecarga de portas TCP ou travamentos de DNS reverso.
- **Seleção e Importação em Lote**: Interface com botão interativo para "Selecionar todos / Desmarcar todos", permitindo importar múltiplos hosts simultaneamente.
- **Lixeira de Hosts com Proteção**: Exclusão de dispositivos direcionada para lixeira lógica, permitindo restauração individual ou esvaziamento em massa protegido por modal de confirmação de segurança.

---

## 7. Métricas NOC, SLA, Jitter e Score de Saúde

- **Health Score Composto (0 a 100%)**: Avaliação calculada pela função `calculate_health_score` em `Backend/metrics.py`, normalizando pesos proporcionais para conectividade física, transporte, aplicação e hardware.
- **SLA Contínuo (Rolling SLA %)**: Cálculo percentual de disponibilidade em janelas deslizantes de tempo (10 min, 1 hora, 24 horas e 30 dias).
- **Jitter Estatístico (RFC 3550)**: Média das diferenças absolutas entre tempos de resposta consecutivos, essencial para avaliar a qualidade da rede para tráfego sensível a tempo real (VoIP, streaming e replicação).
- **Tendência de Latência**: Análise de inclinação matemática (*slope*) classificando a tendência da aplicação em `Estável`, `Degradação` ou `Crítico`.

---

## 8. Política de Retenção e Limpeza Contínua de Dados

- **Configuração Declarativa via `.env`**: Parâmetro `NETSPOT_RETENTION_DAYS` define o tempo de retenção do histórico (padrão: 7 dias).
- **Desativação Flexível**: Definir `NETSPOT_RETENTION_DAYS=0` desativa a rotina de purga, preservando as séries históricas indefinidamente.
- **Execução Automática em Background**: Rotina periódica gerenciada por `Backend/services/retention_service.py` que remove registros legados de checagens, métricas SNMP e histórico de incidentes em lotes, preservando a performance do PostgreSQL.

---

## 9. Gestão de Alertas, Incidentes e Barramento AMQP (RabbitMQ + n8n)

- **Ciclo de Vida de Incidentes**: Abertura automática de incidente quando um host transita para `DOWN` ou `DEGRADED`, com registro de causa provável e encerramento com cômputo do tempo total de indisponibilidade quando o serviço se recupera.
- **Barramento Assíncrono AMQP**: Despacho de envelopes JSON duráveis para o RabbitMQ, desacoplando o coletor local de eventuais lentidões em links externos de internet.
- **Orquestração com n8n e Telegram**: Workflow visual que consome mensagens da fila, aplica formatação e despacha alertas em tempo real para grupos de suporte técnico.

---

## 10. Interface Frontend SPA (UX, Ergonomia e Acessibilidade WCAG 2.1 AA)

- **Design System Vanilla Dual**: Folha de estilos centralizada em `Frontend/css/style.css` com suporte a tema claro e escuro, dispensando etapas de compilação ou dependências de Node.js em runtime.
- **Flip Cards 3D com 3 Faces por Host**:
  - *Face 1*: Resumo de conectividade, Health Score, tendência de latência e Causa Provável;
  - *Face 2*: SLA por protocolo (Ping, TCP, HTTP), Jitter e portas abertas;
  - *Face 3*: Telemetria SNMP de hardware e gráficos de consumo;
  - Indicadores dinâmicos de face (`1/3`, `2/3`, `3/3`) e tooltips descritivos nas ações de navegação.
- **Acessibilidade Digital (WCAG 2.1 AA)**:
  - Contraste de cores de **5.6:1** em textos secundários, superando a norma de 4.5:1;
  - Navegação universal por teclado com anel visual `:focus-visible`;
  * **Focus Trap** nos modais (aprisionamento de foco com <kbd>Tab</kbd> e restauração ao fechar com <kbd>Esc</kbd>);
  * Rótulos semânticos e atributos ARIA em diálogos e campos de formulário.
- **Operação Offline-First**: Fontes Open Sans e biblioteca Chart.js UMD distribuídas localmente no container Nginx, permitindo operação perfeita em redes sem acesso externo à internet.

---

## 11. Ambiente de Laboratório Kathará (40+ Nós)

- Detalhado em [`kathara.md`](kathara.md).
- **Topologia Roteada em Larga Escala**: Emulação de 40 dispositivos virtuais distribuídos em 4 sub-redes corporativas:
  - 30 estações de trabalho (`pc1` a `pc30`);
  - 10 servidores dedicados (Web, DNS BIND9, Banco de Dados e Aplicações);
  - 4 roteadores Linux interligados.
- **Injeção Controlada de Falhas**: Simulação de queda de interfaces, perda de pacotes e variação de latência via `tc` (Traffic Control) e sobrecarga de CPU com `stress-ng`.

---

## 12. Suíte de Testes Automatizados (Pytest)

A suíte de testes reside em `Backend/tests/` e conta com **61 testes automatizados (100% aprovados)**:
- `test_alert_logic.py`: Máquina de estados de incidentes, supressão de alarmes falsos de firewall e cooldown anti-spam.
- `test_checker.py`: Checadores assíncronos de Ping, TCP, HTTP e DNS.
- `test_metrics.py`: Algoritmos de Health Score, SLA contínuo, Jitter e tendências de degradação.
- `test_retention.py`: Regras da política de retenção de dados e expurgo.
- `test_snmp.py`: Parsers e conversores SNMP multivendor.
- `test_api_routes.py`: Endpoints RESTful da API e integração de rotas.
- `test_models_schemas.py`: Validação de contratos Pydantic e entidades SQLAlchemy.
- `test_self_healing.py`: Autocura de conexões, Circuit Breaker, DLQ e anti-flapping.
- `test_audit_regressions.py`: Testes de regressão cobrindo esvaziamento seguro da lixeira, causa provável e rotas administrativas.

Comandos para execução:
```bash
# Execução no container Docker
docker exec -it netspot-backend pytest Backend/tests -v

# Execução local com uv
uv run pytest Backend/tests
```

---

## 13. Licenciamento

O **NetSpot** é software livre disponibilizado sob os termos da licença **GNU General Public License v3.0 (GPL-3.0)**. Consulte o arquivo [`LICENSE`](LICENSE) para mais informações.
