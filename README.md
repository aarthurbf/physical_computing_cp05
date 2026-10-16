# 🏋️ Smart Gym — Checkpoint 05
### Physical Computing (IoT & IoB) | FIAP — Engenharia de Software

---

## 👥 Equipe

| Nome | RM |
|---|---|
| *Arthur Bobadilla Franchi* | RM 555056 |
| *Luan Orlandelli Ramos* | RM 554747 |
| *Jorge Luiz* | RM 554418 |

---

## 📌 Sobre o Projeto

Evolução do CP04: a estação de treino agora é um **dispositivo IoT conectado**.
O sistema implementa o protocolo **MQTT (Publish/Subscribe)** para transmitir
eventos em tempo real para um **Dashboard Web** de monitoramento, transformando
o Smart Gym numa solução de telemetria em nuvem.

### O que há de novo no CP05

| Funcionalidade | Detalhes |
|---|---|
| **Protocolo MQTT** | Publicação de eventos via `paho-mqtt` para `broker.hivemq.com` |
| **Tópico de status da máquina** | `smartgym/maquina/status` → `"livre"` / `"ocupada"` |
| **Tópico de aluno** | `smartgym/sessao/aluno` → JSON com nome, exercício e UID |
| **Tópico de repetições** | `smartgym/sessao/reps` → JSON com reps, meta e flag de conclusão |
| **Dashboard Web** | `dashboard/index.html` — subscriber em tempo real via WebSocket |
| **Status visual no Dashboard** | Verde (livre) ↔ Vermelho (ocupada) em ≤ 2 s |
| **Histórico de sessões** | Tabela acumulada das séries concluídas na sessão |
| **Feedback LED no Arduino** | LED vermelho acende ao receber `STATUS:ocupada` do Python |
| **Badge MQTT no app** | Indicador do estado da conexão MQTT na UI Python |

### Fluxo completo CP05

```
Aproximação do cartão RFID
         ↓
Consulta no banco SQLite
         ↓
Publica: status="ocupada" + dados do aluno → MQTT broker
         ↓
Arduino recebe STATUS:ocupada → LED vermelho acende
         ↓
Treino ativo — câmera ligada
         ↓
YOLO detecta celular na cena?
   ├── NÃO → badge "Aguardando Equipamento" + contagem pausada
   └── SIM → badge "Equipamento Detectado ✓"
         ↓
MediaPipe identifica ângulo do braço
         ↓
Máquina de estados: IDLE → EXTENSAO → FLEXAO → EXTENSAO
         ↓ (ciclo completo + equipamento presente)
rep++ → Publica reps atuais → MQTT broker → Dashboard atualiza
         ↓ (meta atingida)
Publica: reps finais (concluido=true) + status="livre" → MQTT broker
         ↓
Log registrado no SQLite + reset automático em 8 s
         ↓
Arduino recebe STATUS:livre → LED vermelho apaga
```

---

## 🌐 Arquitetura IoT

```
Arduino (RFID serial)
        │  Serial 9600 baud
        ▼
smart_gym_cp05.py  ──── MQTT publish ──► broker.hivemq.com:1883
        │                (paho-mqtt)              │
        │ STATUS:ocupada/livre                    │ MQTT over WSS :8884
        ▼                                         ▼
Arduino (LED feedback)       dashboard/index.html (MQTT.js)
                                        │
                              Navegador qualquer
```

---

## 📡 Tópicos MQTT

| Tópico | Payload | Evento |
|---|---|---|
| `smartgym/maquina/status` | `"livre"` ou `"ocupada"` | Login / conclusão / reset / saída |
| `smartgym/sessao/aluno` | `{"nome":"...","exercicio":"...","uid":"..."}` | Login RFID |
| `smartgym/sessao/reps` | `{"nome":"...","reps":N,"meta":N,"concluido":bool}` | A cada rep + conclusão |

> Todos os tópicos são publicados com **retain=True** — o Dashboard recebe o
> estado atual imediatamente ao conectar, sem esperar o próximo evento.

---

## 🖥️ Dashboard Web

Arquivo: `dashboard/index.html`

| Painel | Descrição |
|---|---|
| **Status da Estação** | Círculo verde (livre) ou vermelho (ocupada), atualiza em tempo real |
| **Aluno Ativo** | Nome, exercício e UID do aluno logado |
| **Repetições** | Contador em tempo real + barra de progresso |
| **Série Concluída** | Badge destacado ao atingir a meta |
| **Histórico** | Tabela de todas as séries concluídas na sessão |
| **Badge MQTT** | Indicador de conexão com o broker (verde = conectado) |

**Como abrir:** basta abrir `dashboard/index.html` em qualquer navegador.
Não é necessário servidor — o MQTT.js conecta diretamente ao broker via WebSocket.

---

## 🧠 Lógica de Detecção (mantida do CP04)

### YOLO — Equipamento
- Modelo: **YOLOv8n** (nano)
- Classe: `cell phone` (COCO id 67)
- Confiança mínima: `0.40`

### MediaPipe — Ângulo do Braço
- Landmarks: ombro (11/12), cotovelo (13/14), pulso (15/16)
- Seleciona automaticamente o braço com maior visibilidade

### Máquina de Estados

```
IDLE ──► EXTENSAO (ângulo ≥ 145°) ──► FLEXAO (ângulo ≤ 55°)
              ▲                              │
              │         rep++ aqui           │
              └──────────────────────────────┘
```

---

## 🗄️ Banco de Dados (SQLite)

Arquivo: `db/smart_gym.db`

### Tabela `alunos`
| Coluna | Tipo | Descrição |
|---|---|---|
| `id` | INTEGER PK | Identificador único |
| `nome` | TEXT | Nome do aluno |
| `uid_rfid` | TEXT UNIQUE | UID do cartão RFID |
| `exercicio` | TEXT | Exercício programado |
| `repeticoes` | INTEGER | Meta de repetições |
| `criado_em` | DATETIME | Data de cadastro |

### Tabela `log_acessos`
| Coluna | Tipo | Descrição |
|---|---|---|
| `id` | INTEGER PK | ID do log |
| `aluno_id` | INTEGER FK | Referência ao aluno |
| `uid_rfid` | TEXT | UID lido no acesso |
| `horario` | DATETIME | Timestamp automático |
| `reps_feitas` | INTEGER | Repetições realizadas |
| `concluido` | INTEGER | 1 = meta atingida, 0 = parcial |

---

## 🔩 Hardware & Componentes

| Componente | Qtd | Observação |
|---|---|---|
| Arduino Uno / Nano | 1 | Comunicação serial com Python |
| Módulo RFID RC522 | 1 | Comunicação SPI |
| Cartões/tags RFID (Mifare 1K) | 2+ | UID cadastrado no banco |
| LED Verde | 1 | Pisca ao ler cartão (D7) |
| LED Vermelho | 1 | Acende quando estação ocupada (D8) |
| Buzzer passivo | 1 | Feedback sonoro (D6) |
| Resistores 220Ω | 2 | Para os LEDs |
| Webcam USB | 1 | Monitoramento de pose + YOLO |
| Celular (qualquer) | 1 | "Equipamento" detectado pelo YOLO |
| Cabo USB | 1 | Comunicação Serial + alimentação |

---

## 📚 Bibliotecas

### Python
| Biblioteca | Uso |
|---|---|
| `opencv-python` | Captura e processamento de imagem |
| `mediapipe` | Detecção de pose (PoseLandmarker) |
| `ultralytics` | YOLOv8 — detecção de objetos COCO |
| `numpy` | Cálculo de ângulos |
| `pyserial` | Comunicação serial com Arduino |
| `Pillow` | Exibição de frames no Tkinter |
| `paho-mqtt` | **[NOVO CP05]** Protocolo MQTT Publish/Subscribe |
| `sqlite3` | Banco de dados (nativa) |
| `tkinter` | Interface gráfica (nativa) |

### Arduino
| Biblioteca | Uso |
|---|---|
| `MFRC522` | Comunicação com módulo RFID RC522 |
| `SPI` | Barramento SPI (nativa) |

---

## 🔌 Diagrama de Conexões (RC522 → Arduino Uno)

```
RC522          Arduino Uno
─────────────────────────
SDA    ──────→  D10
SCK    ──────→  D13
MOSI   ──────→  D11
MISO   ──────→  D12
IRQ    ──────→  (não usado)
GND    ──────→  GND
RST    ──────→  D9
3.3V   ──────→  3.3V

LED Verde  ──── 220Ω ──── D7 ──── GND
LED Verm   ──── 220Ω ──── D8 ──── GND
Buzzer     ──────────────  D6 ──── GND
```

> **Atenção:** RC522 opera em 3.3V. Não conecte ao 5V.

---

## ⚙️ Setup e Execução

### 1. Instalar dependências Python
```bash
pip install opencv-python mediapipe ultralytics numpy pyserial Pillow paho-mqtt
```

### 2. Criar e popular o banco de dados
```bash
python db/setup_db.py
```

### 3. Configurar porta serial (se usar Arduino)
Em `src/smart_gym_cp05.py`:
```python
SERIAL_PORT = "COM5"   # Windows: COM3, COM4... / Linux: /dev/ttyUSB0
```

### 4. Upload do sketch Arduino (CP05)
- Abra `arduino/Smart_Gym_RFID_CP05.ino` na Arduino IDE
- Instale a biblioteca **MFRC522** (Library Manager)
- Selecione a placa e porta corretas → Upload

### 5. Executar o sistema
```bash
python src/smart_gym_cp05.py
```

### 6. Abrir o Dashboard Web
Abra `dashboard/index.html` diretamente no navegador.
O dashboard conecta automaticamente ao broker `broker.hivemq.com` via WebSocket.

### Atalhos da interface
| Tecla | Ação |
|---|---|
| `S` | Entrar como Convidado (sem RFID) |
| `R` | Resetar a estação |
| `Q` | Sair do sistema |

---

## 📁 Estrutura do Repositório

```
physical_computing_cp05/
├── arduino/
│   ├── Smart_Gym_RFID.ino          # Sketch CP04 (mantido como histórico)
│   └── Smart_Gym_RFID_CP05.ino     # Sketch CP05 — feedback LED por STATUS serial
├── dashboard/
│   └── index.html                  # Dashboard Web IoT (MQTT.js + WebSocket)
├── db/
│   ├── setup_db.py                 # Cria e popula o banco SQLite
│   └── smart_gym.db                # Banco de dados gerado
├── src/
│   ├── smart_gym_cp04.py           # Versão anterior (CP04) — mantida como histórico
│   └── smart_gym_cp05.py           # Aplicação principal CP05 (MQTT + YOLO + MediaPipe)
├── pose_landmarker_full.task       # Modelo MediaPipe
├── efficientdet_lite0.tflite       # Modelo EfficientDet (detector de equipamento)
├── cp05-plan.md                    # Plano de implementação do CP05
└── README.md
```

---

## 📝 Notas Técnicas

- **Broker público:** `broker.hivemq.com` — gratuito, sem cadastro, sem TLS obrigatório.
  Porta TCP `1883` (Python) e WSS `8884` (Dashboard).
- **retain=True:** todos os tópicos publicados com flag retain — o Dashboard recebe
  o estado imediatamente ao conectar, sem esperar o próximo evento.
- **Thread safety:** `paho-mqtt` roda o loop de rede num daemon thread interno;
  as publicações do Tkinter thread são thread-safe (paho garante internamente).
- **Fallback MQTT:** se `paho-mqtt` não estiver instalado, o app roda normalmente
  sem publicação — uma mensagem de aviso aparece no terminal.
- **YOLO roda no thread da câmera** junto com MediaPipe (frame a frame via `root.after()`).
- **cp04 preservado intacto** como referência histórica; o CP05 é um arquivo separado.

---

## 🎬 Vídeo Demonstrativo

> 🔗 []

---

*CP05 — Smart Gym | Physical Computing (IoT & IoB) — FIAP 2026*
