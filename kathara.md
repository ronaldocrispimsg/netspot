# Planejamento e Execução do Laboratório Experimental com Kathará no NetSpot

Este documento apresenta a arquitetura da topologia, a análise de viabilidade computacional e a metodologia experimental para a simulação de uma rede corporativa e acadêmica em larga escala (40+ dispositivos) utilizando a ferramenta **Kathará**, validando o protótipo **NetSpot (NOC Lite)** no âmbito do Trabalho de Conclusão de Curso (TCC) em Sistemas de Informação no IFNMG — Campus Januária.

---

## 1. Análise de Viabilidade Técnica e Desempenho

O **Kathará** é uma plataforma de emulação de redes baseada em containers leves, compartilhando o kernel do sistema operacional hospedeiro. Isso viabiliza a execução simultânea de dezenas de nós virtuais com consumo reduzido de memória quando comparado a hipervisores tradicionais de virtualização completa (KVM/QEMU, GNS3 ou EVE-NG).

### Estimativa de Carga Computacional:

* **Consumo por Nó Kathará (Debian/Alpine com SNMPD e ferramentas de rede)**: $\approx 15\text{ MB a } 25\text{ MB de RAM}$ por nó ocioso.
* **Carga de 40 Nós Kathará**:
  $$\text{RAM dos 40 Nós Simulados} \approx 40 \times 20\text{ MB} = 800\text{ MB de RAM}$$
* **Carga da Infraestrutura NetSpot (5 Containers Docker)**:
  * PostgreSQL 15: $\approx 150\text{ MB}$
  * RabbitMQ Broker: $\approx 180\text{ MB}$
  * Backend FastAPI (Python 3.11 / 3.12): $\approx 120\text{ MB}$
  * n8n Automation: $\approx 350\text{ MB}$
  * Frontend Nginx Alpine: $\approx 20\text{ MB}$
  * **Total NetSpot**: $\approx 820\text{ MB a } 1.2\text{ GB}$
* **Consumo Global Estimado do Laboratório Completo**: **~2.0 GB a 3.0 GB de RAM Total**.

> **Conclusão de Viabilidade**: O experimento completo com 40 computadores e 4 roteadores executa com estabilidade em computadores pessoais equipados com 8 GB ou 16 GB de memória RAM.

---

## 2. Arquitetura da Topologia de Rede Simulada

A topologia emulada reproduz uma infraestrutura corporativa/acadêmica dividida em **4 Sub-redes Roteadas**:

```text
                               +-----------------------------+
                               |     NetSpot Server (NOC)    |
                               | (192.168.100.2 / Backend)   |
                               +--------------+--------------+
                                              |
                                      +-------+-------+
                                      | Roteador Core |
                                      | (router_core) |
                                      +---+---+---+---+
                                          |   |   |
         +--------------------------------+   |   +--------------------------------+
         |                                    |                                    |
+--------+--------+                  +--------+--------+                  +--------+--------+
| Roteador Lab 1  |                  | Roteador Lab 2  |                  | Roteador Servid. |
|  (10.0.1.1/24)  |                  |  (10.0.2.1/24)  |                  |  (10.0.3.1/24)  |
+--------+--------+                  +--------+--------+                  +--------+--------+
         |                                    |                                    |
   (15 Clientes)                        (15 Clientes)                        (10 Servidores)
   - pc1 a pc15                         - pc16 a pc30                        - Web, DNS, DB
   - Agente SNMP (netspot)              - Agente SNMP (netspot)              - Agente SNMP (netspot)
```

### Mapeamento dos 40 Nós Monitorados no `lab.conf`:
- **Sub-rede Laboratório 1 (`10.0.1.0/24`)**: 15 estações clientes (`pc1` a `pc15`).
- **Sub-rede Laboratório 2 (`10.0.2.0/24`)**: 15 estações clientes (`pc16` a `pc30`).
- **Sub-rede Servidores de Aplicação (`10.0.3.0/24`)**: 10 servidores dedicados:
  - 3 Servidores Web (`web_server1`, `web_server2`, `web_server3`);
  - 3 Servidores de Banco de Dados (`db_server1`, `db_server2`, `db_server3`);
  - 2 Servidores DNS BIND9 (`dns_server1`, `dns_server2`);
  - 2 Servidores de Aplicação (`app_server1`, `app_server2`).
- **Roteadores e Infraestrutura de Enlace**:
  - `router_core`: Interconexão com o container `netspot-backend` na sub-rede `192.168.100.0/24`.
  - `router_lab1`, `router_lab2`, `router_lab3`: Roteadores de borda configurados via diretivas `[exec]` no `lab.conf`.

---

## 3. Configuração dos Agentes SNMP nos Nós

Todos os nós do laboratório Kathará executam o daemon `snmpd` configurado com a community somente-leitura customizada **`netspot`**, conforme a diretriz de segurança do projeto (mitigando o uso da credencial genérica `public`).

O script de inicialização do SNMP (`setup_snmp_linux.sh`) presente nos nós aplica a configuração:

```bash
# Community restrita ao NetSpot
rocommunity netspot 192.168.100.0/24
rocommunity netspot 10.0.0.0/16
```

---

## 4. Cenários de Testes Práticos e Injeção de Falhas

Com o Kathará, é possível aplicar perturbações controladas de tráfego para avaliar o tempo de reação, o algoritmo de Causa Provável e a resiliência do NetSpot:

### Cenário A: Queda Abrupta de Dispositivo (Estado DOWN)
* **Ação**: Interrupção do container ou encerramento de interface:
  ```bash
  kathara vclean -n pc12
  ```
* **Métrica Aferida**: Tempo até a detecção pelo coletor, abertura do incidente no PostgreSQL e notificação via Telegram.
* **Resultado Esperado**: Detecção rápida ($\text{MTTD} < 30\text{ s}$), ativação do Circuit Breaker e transição visual do card para status crítico.

### Cenário B: Degradação por Latência e Variação de Tráfego (Estado DEGRADED)
* **Ação**: Injeção de latência e perda de pacotes via `tc` (Traffic Control) na interface do nó:
  ```bash
  tc qdisc add dev eth0 root netem delay 250ms loss 12%
  ```
* **Métrica Aferida**: Reclassificação do **Health Score (0 a 100%)**, elevação do **Jitter estatístico (ms)** e acionamento da heurística de causa provável (*Degradação por Jitter elevado*).

### Cenário C: Sobrecarga de Recursos Físicos (Telemetria SNMP)
* **Ação**: Execução do utilitário `stress-ng` dentro de um nó Kathará para forçar sobrecarga de CPU:
  ```bash
  stress-ng --cpu 4 --timeout 60s
  ```
* **Métrica Aferida**: Coleta da telemetria de processamento via SNMP, exibição do pico de carga na Face 3 do card do host e diagnóstico preditivo de *"Sobrecarga de processador (CPU > 90%)"*.

---

## 5. Estratégia Metodológica para a Defesa do TCC

A validação experimental do NetSpot combina duas abordagens complementares:
1. **Emulação em Larga Escala (Kathará)**:
   - Validação da capacidade do motor assíncrono frente a 40+ ativos distribuídos em múltiplas sub-redes roteadas;
   - Avaliação do consumo computacional do servidor de monitoramento sob cenários de estresse.
2. **Ambiente Físico Real (IFNMG Campus Januária)**:
   - Validação com computadores e equipamentos de rede reais no ambiente acadêmico;
   - Avaliação da usabilidade prática e experiência do operador na sala de controle.

---

## 6. Como Executar o Laboratório Kathará

1. **Instalar o Kathará no Linux (Ubuntu / Debian)**:
   ```bash
   sudo apt-get install kathara
   ```
2. **Navegar até a pasta do laboratório e iniciar a topologia**:
   ```bash
   cd "Teste - Kathará"
   kathara lstart
   ```
3. **Integrar a rede do Kathará com o NetSpot**:
   Se os containers do NetSpot já estiverem rodando, execute o script de interconexão:
   ```bash
   chmod +x ./scripts/setup_kathara_network.sh
   ./scripts/setup_kathara_network.sh
   ```
4. **Abrir o Dashboard do NetSpot**:
   Acesse [http://localhost:8080](http://localhost:8080) e inicie a descoberta automática da rede para cadastrar os nós monitorados.
