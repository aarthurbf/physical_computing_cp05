# CP05 — Smart Gym: Conectividade IoT e Telemetria em Nuvem

## Visão Geral

O CP05 transforma a estação de treino num dispositivo IoT conectado via **MQTT**.
O objetivo é publicar eventos do ciclo de treino num broker MQTT público
(HiveMQ Cloud free ou broker.hivemq.com) e exibir os dados em tempo real num
**Dashboard Web** (HTML + JS puro, servido por um mini servidor Python embutido)
que qualquer navegador pode abrir localmente.

### Escopo

| O que muda | Descrição |
|---|---|
| Novo módulo Python: `MqttClient` | Publica status da máquina, nome e volume de reps |
| Script Python principal: `smart_gym_cp05.py` | Fork do cp04, integra MqttClient |
| Novo Arduino sketch: `Smart_Gym_RFID_CP05.ino` | RFID continua serial; opcionalmente publica via MQTT se ESP32 |
| Novo arquivo: `dashboard/index.html` | Dashboard Web que assina os tópicos MQTT via WebSocket |
| Atualização: `db/setup_db.py` | Sem alteração |
| Atualização: `README.md` | Documentação do CP05 |

### Tópicos MQTT definidos

```
smartgym/maquina/status      → "livre" | "ocupada"
smartgym/sessao/aluno        → JSON { "nome": "...", "exercicio": "...", "uid": "..." }
smartgym/sessao/reps         → JSON { "nome": "...", "reps": N, "meta": N, "concluido": true/false }
```

### Arquitetura

```
Arduino (RFID serial)
        │ Serial
        ▼
smart_gym_cp05.py  ──── MQTT publish ──► broker.hivemq.com:1883
        │                                       │
        │ HTTP (threading)                       │ MQTT over WS :8884
        ▼                                       ▼
dashboard/index.html  ◄──── subscribe ──── MQTT.js (CDN)
```

---

## Sub-tarefa 1 — Módulo `MqttClient` e integração no app principal

**Status:** [ ] pending

### Intent
Criar um wrapper `MqttClient` (usando `paho-mqtt`) que publica nos três tópicos
definidos, e integrá-lo no `SmartGymApp` existente sem quebrar nenhuma
funcionalidade já existente do CP04.

### Expected Outcomes
- `src/smart_gym_cp05.py` funciona como substituto direto do `cp04`
- Ao login RFID: publica `smartgym/maquina/status = "ocupada"` e dados do aluno
- A cada nova rep concluída: publica `smartgym/sessao/reps` com o estado atual
- Ao concluir/resetar: publica `smartgym/sessao/reps` com `concluido=true` e
  depois `smartgym/maquina/status = "livre"`
- Se paho-mqtt não instalado, o sistema roda sem MQTT (fallback silencioso)

### Todo List
1. Copiar `src/smart_gym_cp04.py` → `src/smart_gym_cp05.py`
2. Adicionar bloco `try/import paho.mqtt.client` com flag `_MQTT_DISPONIVEL`
3. Criar classe `MqttClient` com métodos:
   - `__init__(broker, port, client_id)` — configura e conecta em background thread
   - `publicar(topico, payload_dict)` — serializa JSON e publica com retain=True
   - `desconectar()`
4. Instanciar `MqttClient` dentro de `SmartGymApp.__init__`
5. Em `_ativar_treino`: publicar status "ocupada" + dados do aluno
6. Em `_atualizar_reps` (quando nova_rep == True): publicar reps atual
7. Em `_concluir_treino`: publicar reps final com `concluido: true` + status "livre"
8. Em `_resetar`: publicar status "livre"
9. Em `_sair`: chamar `mqtt.desconectar()`
10. Alterar título da janela para "Smart Gym — CP05 | MQTT + YOLO + MediaPipe"

### Relevant Context
- Arquivo base: `src/smart_gym_cp04.py`
- Pontos de integração: `_ativar_treino()`, `_loop_camera()` (nova_rep), `_concluir_treino()`, `_resetar()`, `_sair()`
- Broker público gratuito: `broker.hivemq.com`, porta `1883` (TCP), porta `8884` (WSS)
- Biblioteca: `paho-mqtt` (pip install paho-mqtt)
- O `MqttClient` deve rodar num daemon thread para não bloquear o loop Tkinter

---

## Sub-tarefa 2 — Dashboard Web

**Status:** [ ] pending

### Intent
Criar um Dashboard Web (`dashboard/index.html`) que se conecta ao mesmo broker
MQTT via WebSocket e exibe em tempo real:
- Cor da máquina (Verde = livre, Vermelho = ocupada)
- Nome do aluno logado e exercício
- Contador de repetições e progresso da meta
- Histórico das últimas sessões concluídas na mesma execução

### Expected Outcomes
- Abrir `dashboard/index.html` em qualquer browser mostra o dashboard
- Status muda de cor em ≤ 2 s após login/logout no app Python
- Nome do aluno e reps atualizam em tempo real
- Ao concluir treino: badge "Concluído ✓" aparece com nome e total de reps
- Visual consistente com a identidade do projeto (dark theme, cores da UI Python)

### Todo List
1. Criar pasta `dashboard/`
2. Criar `dashboard/index.html` com:
   - Layout: header com logo, card de status da máquina, card do aluno ativo,
     card de progresso de reps, tabela de histórico da sessão
   - Incluir MQTT.js via CDN (unpkg): `mqtt.connect("wss://broker.hivemq.com:8884/mqtt")`
   - Subscribe em `smartgym/maquina/status`, `smartgym/sessao/aluno`, `smartgym/sessao/reps`
   - Handler `onMessage`: atualizar os cards conforme tópico recebido
   - Status card muda background para verde (#00e676) quando "livre", vermelho (#f44336) quando "ocupada"
   - Histórico: ao receber `concluido: true`, adicionar linha na tabela
3. Estilização dark theme inline (sem dependência externa além do MQTT.js CDN):
   - Fundo: #0d0d0d, painel: #1a1a1a, destaque: #e91e8c — mesmas cores do Python

### Relevant Context
- MQTT.js CDN: `https://unpkg.com/mqtt/dist/mqtt.min.js`
- Broker WS: `wss://broker.hivemq.com:8884/mqtt`
- Tópicos: `smartgym/maquina/status`, `smartgym/sessao/aluno`, `smartgym/sessao/reps`
- Nenhuma dependência de servidor — arquivo HTML puro abrível direto no browser

---

## Sub-tarefa 3 — Arduino sketch atualizado (CP05)

**Status:** [ ] pending

### Intent
Atualizar o sketch Arduino para adicionar feedback visual diferenciado:
- LED Verde piscando quando UID é enviado com sucesso
- LED Vermelho para indicar que a estação está ocupada (recebe comando serial do Python)
- Manter o protocolo serial `"UID: XX:XX:XX:XX"` intacto

O sketch continua usando comunicação serial (Arduino Uno não tem Wi-Fi).
A nota sobre ESP32 é mantida no README.

### Expected Outcomes
- `arduino/Smart_Gym_RFID_CP05.ino` compila sem erros na Arduino IDE
- O protocolo serial de saída permanece idêntico ao CP04
- Novo protocolo de entrada serial: o Python pode enviar `"STATUS:ocupada\n"` ou
  `"STATUS:livre\n"` e o Arduino acende LED vermelho (ocupada) ou verde (livre)

### Todo List
1. Copiar `arduino/Smart_Gym_RFID.ino` → `arduino/Smart_Gym_RFID_CP05.ino`
2. Adicionar variável `bool estacaoOcupada = false`
3. No `loop()`: ler `Serial.available()` e parsear linhas `"STATUS:ocupada"` / `"STATUS:livre"`
4. Atualizar LED verde/vermelho conforme `estacaoOcupada`
5. Manter toda lógica RFID existente intacta

### Relevant Context
- Arquivo base: `arduino/Smart_Gym_RFID.ino`
- LED_VERDE = pino 7, LED_VERM = pino 8, BUZZER = pino 6
- O Python deve enviar `"STATUS:ocupada\n"` via `ser.write()` quando treino ativar
- O Python deve enviar `"STATUS:livre\n"` via `ser.write()` quando resetar/concluir

---

## Sub-tarefa 4 — README atualizado (CP05)

**Status:** [ ] pending

### Intent
Atualizar o `README.md` para documentar todas as novidades do CP05: tópicos MQTT,
dashboard web, novas dependências e fluxo IoT completo.

### Expected Outcomes
- README reflete fielmente a arquitetura CP05
- Seção de setup inclui `pip install paho-mqtt`
- Instruções de como abrir o dashboard
- Diagrama do fluxo IoT atualizado

### Todo List
1. Renomear título para "CP05"
2. Adicionar seção "O que há de novo no CP05" com tabela de features MQTT/Dashboard
3. Atualizar diagrama de fluxo para incluir MQTT e Dashboard
4. Adicionar seção "Tópicos MQTT" com tabela dos três tópicos
5. Adicionar `paho-mqtt` na tabela de bibliotecas Python
6. Adicionar instruções para abrir o dashboard
7. Atualizar seção de estrutura do repositório

---

## Dependências entre sub-tarefas

```
Sub-tarefa 1 (MqttClient Python)
        │
        ├──► Sub-tarefa 2 (Dashboard)     ← independente, pode ser feita em paralelo
        │
        └──► Sub-tarefa 3 (Arduino)       ← depende do protocolo serial definido na 1
                    │
                    └──► Sub-tarefa 4 (README) ← deve ser feita por último
```

## Notas de Implementação

- **Broker:** usar `broker.hivemq.com` (gratuito, sem cadastro, sem TLS obrigatório)
- **Client ID único:** usar `f"smartgym-{os.getpid()}"` para evitar conflito de conexões
- **Retain flag:** publicar todos os tópicos com `retain=True` para que o Dashboard
  receba o estado atual imediatamente ao conectar, sem esperar o próximo evento
- **Thread safety:** o `paho-mqtt` roda o loop de rede num thread próprio;
  as publicações do Tkinter thread são thread-safe (paho garante isso internamente)
- **Payload JSON:** `json.dumps(dict, ensure_ascii=False)` com encoding UTF-8
- **Arquivo principal**: o arquivo de entrada do CP05 será `src/smart_gym_cp05.py`
  (o cp04 é preservado intacto como histórico)
