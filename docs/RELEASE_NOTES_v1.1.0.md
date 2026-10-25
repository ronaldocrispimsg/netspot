# NetSpot v1.1.0 — Versão Estável Consolidada e Hardening Completo (NOC Lite)

Lançamento oficial da versão **v1.1.0** do **NetSpot**, sistema de Network Operations Center (NOC Lite) desenvolvido como Trabalho de Conclusão de Curso (TCC) em Sistemas de Informação no Instituto Federal do Norte de Minas Gerais (IFNMG) — Campus Januária pelo desenvolvedor Ronaldo Crispim.

A versão **v1.1.0** representa o marco de consolidação, hardening defensivo, confiabilidade e auditoria completa do repositório, garantindo estabilidade operacional contínua, conformidade rigorosa com normas de segurança (OWASP), acessibilidade digital (WCAG 2.1 AA) e sincronização exaustiva entre código, infraestrutura e documentação acadêmica.

---

## Principais Novidades e Correções da Versão 1.1.0

### 1. Segurança Defensiva e Robustez no Backend
* **Proteção contra Sobrecarga no Bcrypt**: Validação estrita do limite de 72 bytes UTF-8 em `hash_password` e `verify_password` ([`Backend/security.py`](file:///home/crispim/Documentos/netspot/Backend/security.py)), prevenindo exceções não tratadas em tentativas com payloads volumosos.
* **Enforcement de Primeiro Acesso (`must_change_password`)**: A dependência [`Backend/dependencies.py`](file:///home/crispim/Documentos/netspot/Backend/dependencies.py) agora bloqueia requisições a rotas operacionais da API enquanto o operador não concluir a troca da senha inicial temporária.
* **Proteção de Força Bruta Resiliente**: Corrigido o bloqueio permanente em `/auth/change-password`; o sistema agora aplica bloqueio temporal dinâmico (`locked_until = now_utc + 1 min`) após a 5ª tentativa consecutiva incorreta, desbloqueando automaticamente após a expiração.
* **Controle de Acesso Baseado em Funções (RBAC)**: Exclusão de hosts (`DELETE /host/delete/{host_name}` e exclusão definitiva na lixeira) estritamente restrita a usuários administradores.
* **Resolução Reversa Assíncrona Segura**: Eliminada a mutação global concorrente de `socket.setdefaulttimeout` em [`Backend/utils.py`](file:///home/crispim/Documentos/netspot/Backend/utils.py), adotando instâncias isoladas e thread-safe de `dns.resolver.Resolver()` com timeout estrito de 0.8s.
* **Políticas de Isolamento PostgreSQL RLS**: Adicionadas políticas e ativação de `FORCE ROW LEVEL SECURITY` em [`Backend/security_rls_template.sql`](file:///home/crispim/Documentos/netspot/Backend/security_rls_template.sql) cobrindo todas as tabelas do sistema (`hosts`, `checks`, `alerts`, `incidents`, `snmp_metrics`).

### 2. Otimização de Performance, Concorrência e Métricas
* **Sondagens Concorrentes Intra-Host**: A rota de verificação manual imediata (`POST /host/check/{host_name}`) agora executa sondagens ICMP, todas as portas TCP configuradas e checagem Web HTTP em paralelo via `asyncio.gather`.
* **Fast-Path para Hosts Recém-Importados**: A função `infer_probable_cause` detecta antecipadamente hosts em estado `UNKNOWN` / `baseline_pending`, eliminando 504 consultas SQL repetitivas na listagem inicial.
* **Correção no Cálculo de Health Score Sub-Milissegundo**: A função `compute_health` em [`Backend/metrics.py`](file:///home/crispim/Documentos/netspot/Backend/metrics.py) trata latências `0.0 ms` usando verificação explícita `is not None`, eliminando penalidades falsas de -15 pontos de RTT.
* **Histerese Anti-Flapping com Isolamento de Eventos**: O supressor de rajadas em [`Backend/notifications.py`](file:///home/crispim/Documentos/netspot/Backend/notifications.py) rastreia o estado pela chave composta `host:event`, garantindo que tempestades de alertas de queda não suprimam notificações vitais de recuperação (`recovery`).
* **Sincronização de Estado Operacional**: A edição de host (`PUT /host/update/{host_name}`) agora reinicia o estado do `HostCircuitBreaker` e limpa o backoff exponencial SNMP, refletindo mudanças de configuração imediatamente.

### 3. Frontend SPA de Alta Densidade e Blindagem XSS
* **Proteção XSS em Atributos Inline**: Implementado o helper `escapeJsSingleQuotedAttr` em [`Frontend/js/app.js`](file:///home/crispim/Documentos/netspot/Frontend/js/app.js), sanitizando parâmetros interpolados em handlers `onclick` inline.
* **Transição Dinâmica da Face 3 SNMP no DOM**: Quando um host recebe sua primeira coleta SNMP, a interface atualiza cirurgicamente o card em voo (`updateHostCardInPlace`), renderizando KPIs de CPU, RAM, Disco e tráfego RX/TX sem exigir recarregamento da página (F5).
* **Eliminação de Requisições N+1 no Dashboard**: A função `loadLastResult` sintetiza os estados das portas TCP e HTTP diretamente do payload de `/hosts/list`, evitando centenas de requisições redundantes a cada ciclo de polling de 10 segundos.
* **Preservação de Ícones SVG em Botões**: Criados helpers `getButtonLabel`/`setButtonLabel` para preservar ícones vetoriais durante estados de carregamento em formulários e modais.
* **Operação 100% Offline-First**: Removidas todas as chamadas a CDNs externas do Google Fonts; tipografia local padronizada em fontes `Open Sans` e `Roboto` WOFF2 locais.
* **Compatibilidade Mobile**: Adicionados guards defensivos para navegadores iOS Safari e WebViews na API de notificações nativas.

### 4. Infraestrutura, Docker Compose e Automação N8N
* **Porta Parametrizada do Frontend**: Mapeamento do container Nginx flexibilizado para `"${NETSPOT_PORT:-8080}:80"`, permitindo alterar a porta externa via `.env`.
* **Healthchecks Nativos nos Microsserviços**: Containers `rabbitmq` (`rabbitmq-diagnostics -q ping`) e `n8n` (`/healthz`) agora contam com monitoramento de integridade e cláusula `depends_on: condition: service_healthy`.
* **Sanitização HTML no N8N (Telegram)**: Implementado helper `esc(v)` no nó `"Format HTML Message"` do fluxo n8n ([`N8N/workflows/netspot_notifications_workflow.json`](file:///home/crispim/Documentos/netspot/N8N/workflows/netspot_notifications_workflow.json)), impedindo erros de entrega por caracteres especiais (`<`, `>`, `&`) no Telegram (`parse_mode: "HTML"`).
* **Descoberta Dinâmica de Sessões de Chat**: Script [`scripts/backup_chat.py`](file:///home/crispim/Documentos/netspot/scripts/backup_chat.py) atualizado para localizar dinamicamente os logs da conversa principal ativa mais recente.

### 5. Laboratórios Kathará e Resolução DNS
* **Agentes SNMP Ativos em Roteadores**: O laboratório padrão de 40 hosts ([`Teste - Kathará/lab.conf`](file:///home/crispim/Documentos/netspot/Teste%20-%20Kathar%C3%A1/lab.conf)) agora inicializa automaticamente o daemon SNMP em `router_core`, `router_lab1`, `router_lab2` e `router_lab3`.
* **Zonas BIND9 Diretas e Reversas Completas**: Criadas e configuradas as zonas diretas (`db.lab.local`) e reversas (`db.10.0.1`, `db.10.0.2`, `db.10.0.3`) em `dns_server1` e `dns_server2`, garantindo 100% de resolução direta e reversa (PTR) para todos os dispositivos e roteadores emulados.

---

## Qualidade de Software e Cobertura de Testes

* **86 Testes Automatizados no Pytest (100% de Aprovação em ~7.5s)**:
  - `Backend/tests/test_audit_regressions.py` (42 testes de regressão de segurança, concorrência, infraestrutura e governança);
  - `Backend/tests/test_alert_logic.py` (7 cenários críticos de incidentes e histerese);
  - `Backend/tests/test_metrics.py` (cálculo de SLA, Jitter, Health Score e regressão linear);
  - `Backend/tests/test_self_healing.py` (Circuit Breaker e reconexão resiliente);
  - `Backend/tests/test_checker.py`, `test_snmp.py`, `test_retention.py`, `test_models_schemas.py` e `test_api_routes.py`.
* **Smoke Test Standalone**: Script [`Backend/tests/alert_logic_checklist.py`](file:///home/crispim/Documentos/netspot/Backend/tests/alert_logic_checklist.py) com 7/7 validações aprovadas.
* **Validação Estática Frontend**: Scripts validados com `node --check` e teste temático dos gráficos (`scripts/test_chart_theme.js`).

---

## Como Executar a Versão 1.1.0

```bash
# 1. Clone o repositório ou atualize para a tag v1.1.0
git clone https://github.com/ronaldocrispimsg/netspot.git
cd netspot

# 2. Configure as variáveis de ambiente a partir do exemplo seguro
cp .env.example .env

# 3. Inicialize os 5 containers integrados em segundo plano
docker compose up -d --build
```

### Portas e Endereços de Acesso:
* **Dashboard do Operador (NOC)**: [http://localhost:8080](http://localhost:8080)
* **Documentação Interativa da API (Swagger)**: [http://localhost:8000/docs](http://localhost:8000/docs)
* **Diagnóstico de Saúde da Aplicação**: [http://localhost:8000/healthz](http://localhost:8000/healthz)
* **Painel RabbitMQ Management**: [http://localhost:15672](http://localhost:15672)
* **Editor de Fluxos n8n**: [http://localhost:5678](http://localhost:5678)

---

## Licenciamento

O **NetSpot** é software livre distribuído sob os termos da licença **GNU General Public License v3.0 (GPL-3.0)**. Consulte o arquivo [`LICENSE`](file:///home/crispim/Documentos/netspot/LICENSE) para mais detalhes.

---

**Autor**: Ronaldo Crispim  
**Orientação / Instituição**: Sistemas de Informação — Instituto Federal do Norte de Minas Gerais (IFNMG — Campus Januária)  
**Ano**: 2026
