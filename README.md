# NetSpot - Sistema Inteligente de Monitoramento de Rede (NOC Lite)

![NetSpot Architecture](https://img.shields.io/badge/Architecture-Clean%20Architecture-blue)
![Python](https://img.shields.io/badge/Backend-FastAPI%20%7C%20Python%203.11%2F3.12-green)
![Docker](https://img.shields.io/badge/Container-Docker%20%26%20Docker%20Compose-blueviolet)
![Tests](https://img.shields.io/badge/Tests-86%2F86%20Passed%20(100%25)-brightgreen)
![Accessibility](https://img.shields.io/badge/Accessibility-WCAG%202.1%20AA%20Compliant-success)
![License](https://img.shields.io/badge/License-GPL--3.0-orange)

**NetSpot** é um sistema completo e moderno de **Network Operations Center (NOC Lite)** desenvolvido para monitoramento em tempo real de infraestruturas de TI, servidores, ativos de rede e conectividade em ambientes corporativos e educacionais.

O sistema combina monitoramento ativo e passivo (**ICMP Ping, Portas TCP, HTTP/HTTPS, DNS e SNMP Multivendor**), heurística especialista de inferência de **Causa Provável**, inteligência de autocura (**Self-Healing & Circuit Breaker**), cálculo estatístico contínuo de **Health Score**, **SLA** e **Jitter** (RFC 3550), além de gestão e despacho assíncrono de notificações via **RabbitMQ, n8n e Telegram**.

> 📄 **Documentação Completa**:
> - [`arquitetura.md`](arquitetura.md): Anatomia linha por linha de todos os arquivos, rotas, modelos e fluxos do sistema.
> - [`docs/funcionalidades.md`](docs/funcionalidades.md): Especificação técnica exaustiva de cada módulo e regra de negócio.
> - [`docs/kathara.md`](docs/kathara.md): Topologia e guia de execução nos laboratórios experimentais emulados Kathará (40 hosts e 126 hosts).

---

## 🏛️ Arquitetura do Sistema

O projeto foi concebido seguindo os princípios da **Clean Architecture**, **SOLID**, **Twelve-Factor App** e isolamento completo de serviços por microsserviços conteinerizados:

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

## ✨ Funcionalidades Principais

* **🛡️ Autocura e Resiliência Operacional (Self-Healing)**:
  * **Circuit Breaker Pattern**: Pausa progressiva e backoff exponencial em nós inoperantes para impedir sobrecarga de rede e *storm effects*.
  * **RabbitMQ Resiliente**: Conexão auto-regenerativa com reconexão em loop contínuo e encaminhamento para Dead Letter Queue (`netspot.dlq`) em caso de falha.
  * **Database Pool com Auto-Recovery**: Reconexão transparente do SQLAlchemy com `pool_pre_ping=True` e `wait_for_database()`.
  * **Limpeza e Retenção Contínua**: Expurgo automático de métricas e históricos legados com política parametrizável via `.env` (`NETSPOT_RETENTION_DAYS`).
  * **Proteção contra Subprocessos Zumbis**: Encerramento seguro de chamadas `ping` com timeout forçado `asyncio.wait_for` e `SIGKILL`.

* **🖥️ Monitoramento Multi-Protocolo**:
  * **ICMP Ping**: Latência precisa em milissegundos e cálculo de taxa de perda de pacotes.
  * **Portas TCP**: Varredura de integridade de portas de transporte (SSH, HTTP, HTTPS, Banco de Dados, etc.).
  * **HTTP / HTTPS**: Validação de código de status (200 OK), tempo de resposta e análise de tendências de degradação.
  * **DNS Resolver**: Checagem de resolução local e externa de nomes de domínio.

* **📊 Motor SNMP Multivendor (Linux, Windows, Cisco, Mikrotik, Huawei)**:
  * Leitura e normalização em tempo real de **Uso de CPU (%)**, **Memória RAM (%)**, **Uso de Disco (`/` e volumes `C:\`)** e **Tráfego de Rede (Download / Upload)**.
  * Resolução automática de tabelas MIB com salvaguarda estrita contra loops infinitos (teto de 500 iterações).
  * Community SNMP padrão parametrizável (`netspot`) com rejeição de credenciais padrão inseguras (`public`).

* **🧠 Heurística de Causa Provável (Probable Cause Engine)**:
  * Diagnóstico especialista imediato cruzando as camadas do modelo OSI:
    * Detecção de regras de firewall corporativo (ICMP bloqueado mas portas de aplicação ativas);
    * Sobrecarga de processador local (CPU > 90%);
    * Degradação por Jitter excessivo (> 80 ms);
    * Falha na resolução de nomes (DNS indisponível).

* **🎨 Frontend SPA de Alto Desempenho (Ergonomia & WCAG 2.1 AA)**:
  * **Flip Cards 3D (3 Faces por Host)**:
    * *Face 1*: Resumo de conectividade, Health Score, tendência de latência e Causa Provável;
    * *Face 2*: SLA individual por protocolo (Ping, TCP, HTTP), Jitter e portas ativas;
    * *Face 3*: Telemetria SNMP de hardware e gráficos em tempo real;
    * Indicador visual de face (`1/3`, `2/3`, `3/3`) e tooltips descritivos em cada botão de navegação.
  * **Acessibilidade Digital Inclusiva**:
    * Cores com taxa de contraste de **5.6:1** sobre fundos claros (excede o mínimo WCAG AA de 4.5:1);
    * Suporte integral à navegação por teclado com anel visual inteligente `:focus-visible`;
    * **Focus Trap** nos modais (aprisionamento e restauração de foco via <kbd>Tab</kbd> / <kbd>Esc</kbd>);
    * Rótulos acessíveis e atributos ARIA em todos os elementos interativos.
  * **Operação Offline-First**: Zero dependência de CDNs externos (fontes locais `.woff2` e Chart.js embutido), ideal para redes corporativas isoladas.
  * **Gestão Ergonômica de Hosts**:
    * Descoberta de rede automática com seleção/desmarcação em lote;
    * Lixeira de hosts com esvaziamento total protegido por modal de confirmação.

---

## 📁 Estrutura do Repositório

```text
NetSpot/
├── Backend/                    # Microsserviço FastAPI (Python 3.11/3.12)
│   ├── routes/                 # Endpoints RESTful (/api/hosts, /healthz, etc.)
│   ├── services/               # Circuit Breaker, Retenção, Notificações e Métricas
│   ├── snmp/                   # Motor SNMP Multivendor (Discovery, Cache, OID Resolvers)
│   ├── tests/                  # Suíte de Testes Automatizados (86 testes Pytest + smoke test)
│   ├── checker.py              # Sondagens assíncronas concorrentes (Ping, TCP, HTTP, DNS)
│   ├── database.py             # Configuração e pool resiliente do SQLAlchemy
│   ├── metrics.py              # Modelagem matemática de Health Score, SLA e Jitter
│   ├── models.py               # Modelos relacionais do banco de dados
│   ├── mq_manager.py           # Gestor assíncrono de mensageria AMQP (RabbitMQ)
│   ├── scheduler.py            # Orquestrador periódico de coleta e telemetria
│   └── security.py             # Criptografia, hashing bcrypt e autenticação JWT
├── Frontend/                   # Interface SPA servida por Nginx Alpine
│   ├── css/style.css           # Design System Vanilla CSS (Light & Dark Theme)
│   ├── js/app.js               # Gerenciador de estado, Cards 3D, Tabela NOC e renderização SPA
│   ├── js/incidents.js         # Lógica da tela de incidentes e filtragem
│   ├── fonts/                  # Fontes Open Sans e Roboto locais (Offline-First)
│   ├── dashboard.html          # Dashboard principal com Cards 3D e Tabela NOC
│   ├── incidents.html          # Painel histórico de alertas e incidentes
│   ├── login.html              # Tela de autenticação com suporte a troca de tema
│   └── nginx.conf              # Configuração Nginx com headers de segurança HTTP
├── Database/                   # Volume persistente do PostgreSQL
├── docs/                       # Documentação técnica (funcionalidades.md, kathara.md)
├── Escrita_TCC/                # Documentação Acadêmica e Monografia
│   └── Escrita_latex/          # Fonte LaTeX oficial do TCC (TCC - NetSpot.tex)
├── N8N/workflows/              # Workflows de orquestração de notificações (Telegram)
├── RabbitMQ/                   # Mensageria e filas de eventos
├── Teste - Kathará/            # Laboratórios de emulação de rede (40 hosts e Lab-126hosts)
├── scripts/snmp/               # Automação de setup de agentes SNMP (Linux e Windows)
├── arquitetura.md              # Documentação arquitetural linha por linha do repositório
├── docker-compose.yml          # Orquestração dos 5 containers do sistema
├── .env.example                # Template sanitizado de variáveis de ambiente
├── pyproject.toml              # Metadados e dependências do projeto Python
└── LICENSE                     # Licença GNU General Public License v3.0 (GPL-3.0)
```

---

## 🚀 Como Executar o Projeto

### Pré-requisitos

* **Docker** (versão 20.10 ou superior)
* **Docker Compose** (versão 2.0 ou superior)

### 1. Configurar o Arquivo de Ambiente (.env)

Crie o arquivo `.env` a partir do modelo seguro `.env.example`:

```bash
cp .env.example .env
```

Edite o `.env` definindo as credenciais desejadas:
* **Banco de Dados**: `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` e `DATABASE_URL`.
* **Segurança**: `NETSPOT_SECRET_KEY` (chave de assinatura JWT) e `NETSPOT_DEFAULT_ADMIN_PASSWORD`.
* **Mensageria**: `RABBITMQ_USER` e `RABBITMQ_PASSWORD`.
* **Automação N8N**: `N8N_BASIC_AUTH_USER` e `N8N_BASIC_AUTH_PASSWORD`.
* **Telegram**: `NETSPOT_TELEGRAM_BOT_TOKEN` e `NETSPOT_TELEGRAM_CHAT_ID`.
* **Parâmetros Operacionais**: `NETSPOT_PORT` (porta HTTP do Frontend, padrão `8080`), `NETSPOT_MONITOR_INTERVAL_SECONDS` (padrão `10`) e `NETSPOT_RETENTION_DAYS` (padrão `0`).

### 2. Inicializar o Ambiente em Containers

Execute o comando na raiz do projeto:

```bash
docker compose up -d --build
```

O Docker Compose iniciará automaticamente os 5 serviços interligados:
1. `netspot-db`: Banco relacional (PostgreSQL 15 em `localhost:5432`)
2. `netspot-backend`: API assíncrona (FastAPI em `localhost:8000`)
3. `netspot-frontend`: Interface web SPA (Nginx em `localhost:8080`)
4. `netspot-rabbitmq`: Painel de mensageria (RabbitMQ em `localhost:15672`)
5. `netspot-n8n`: Orquestrador de notificações (N8N em `localhost:5678`)

---

## 🌐 Endereços e Credenciais de Acesso

| Serviço | URL de Acesso | Credenciais |
| :--- | :--- | :--- |
| 🖥️ **Frontend Dashboard** | [http://localhost:8080](http://localhost:8080) | `admin` / (definida em `NETSPOT_DEFAULT_ADMIN_PASSWORD`) |
| 🔌 **Documentação da API (Swagger)** | [http://localhost:8000/docs](http://localhost:8000/docs) | — |
| 🏥 **Healthcheck Nativo** | [http://localhost:8000/healthz](http://localhost:8000/healthz) | — |
| 🐇 **RabbitMQ Management** | [http://localhost:15672](http://localhost:15672) | Conforme configurado no `.env` (`RABBITMQ_USER` / `RABBITMQ_PASSWORD`) |
| ⚡ **n8n Automation** | [http://localhost:5678](http://localhost:5678) | Conforme configurado no `.env` (`N8N_BASIC_AUTH_USER` / `N8N_BASIC_AUTH_PASSWORD`) |

---

## 🧪 Suíte de Testes Automatizados (Pytest)

A suíte de testes cobre integralmente checagens de rede, métricas de SLA, inferência de causa provável, expurgo de retenção, módulo SNMP multivendor, tolerância a falhas, segurança do Frontend e rotas autenticadas da API (**86/86 testes aprovados**).

Para executar os testes no container backend:

```bash
docker exec -it netspot-backend pytest Backend/tests -v
```

Ou localmente com o gerenciador `uv`:

```bash
uv run pytest Backend/tests
```

---

## 🔌 Configuração de Agentes SNMP nos Clientes

Para coletar **CPU, Memória RAM, Disco e Tráfego de Rede** em clientes da rede, utilize os scripts automatizados disponíveis em [`scripts/snmp/`](scripts/snmp/):

* **No Windows (PowerShell como Administrador)**:
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\scripts\snmp\setup_snmp_windows.ps1
  ```
* **No Linux (Debian, Ubuntu, Mint, Fedora, Arch)**:
  ```bash
  chmod +x ./scripts/snmp/setup_snmp_linux.sh
  sudo ./scripts/snmp/setup_snmp_linux.sh
  ```

---

## 📄 Licença

Este projeto é software livre licenciado sob a **GNU General Public License v3.0 (GPL-3.0)**. Consulte o arquivo [`LICENSE`](LICENSE) para mais detalhes sobre direitos de cópia, distribuição e modificação.