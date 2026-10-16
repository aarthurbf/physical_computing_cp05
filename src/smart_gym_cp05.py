"""
smart_gym_cp05.py — Smart Gym | Checkpoint 05
Disciplina: Physical Computing (IoT & IoB) — FIAP

Novas funcionalidades (CP05):
  • Protocolo MQTT (paho-mqtt) — Publish/Subscribe
    – Publica status da máquina: smartgym/maquina/status
    – Publica dados do aluno: smartgym/sessao/aluno
    – Publica reps em tempo real: smartgym/sessao/reps
  • Feedback LED no Arduino via serial inversa (STATUS:ocupada / STATUS:livre)
  • Dashboard Web (dashboard/index.html) assina os tópicos em tempo real
  • Fallback silencioso: se paho-mqtt não instalado, app roda sem MQTT
"""

import os
import json
import time
import sqlite3
import tkinter as tk
from datetime import datetime

import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision
from PIL import Image, ImageTk

# ─── Ultralytics (YOLOv8) — opcional ─────────────────────────────────────────
try:
    from ultralytics import YOLO as _YOLO
    _YOLO_DISPONIVEL = True
    print("[YOLO] ultralytics disponível — modo YOLO ativo como primário.")
except ImportError:
    _YOLO_DISPONIVEL = False
    print("[YOLO] ultralytics não encontrado.")

# ─── paho-mqtt — opcional ─────────────────────────────────────────────────────
try:
    import paho.mqtt.client as mqtt_client
    _MQTT_DISPONIVEL = True
    print("[MQTT] paho-mqtt disponível — modo IoT ativo.")
except ImportError:
    _MQTT_DISPONIVEL = False
    print("[MQTT] paho-mqtt não encontrado — rodando sem telemetria MQTT.")

# ─── Caminhos e constantes ───────────────────────────────────────────────────
DB_PATH        = os.path.join(os.path.dirname(__file__), "..", "db", "smart_gym.db")
MODEL_PATH     = os.path.join(os.path.dirname(__file__), "..", "pose_landmarker_full.task")
OBJ_MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "efficientdet_lite0.tflite")

SERIAL_PORT = "COM5"   # ajuste conforme porta do Arduino
BAUD_RATE   = 9600

# ─── Configuração MQTT ────────────────────────────────────────────────────────
MQTT_BROKER   = "broker.hivemq.com"
MQTT_PORT     = 1883
MQTT_CLIENT_ID = f"smartgym-{os.getpid()}"

TOPICO_STATUS = "smartgym/maquina/status"
TOPICO_ALUNO  = "smartgym/sessao/aluno"
TOPICO_REPS   = "smartgym/sessao/reps"

# ─── Detector de equipamento — configuração ──────────────────────────────────
OBJ_CATEGORIAS_EQUIP = {"cell phone", "remote"}
OBJ_CONF_THRESHOLD   = 0.35

YOLO_EQUIPMENT_IDS  = {67}    # cell phone
YOLO_CONF_THRESHOLD = 0.40

# ─── Fallback HSV ─────────────────────────────────────────────────────────────
HSV_DARK_LOW      = np.array([  0,   0,   0], dtype=np.uint8)
HSV_DARK_HIGH     = np.array([180,  90, 100], dtype=np.uint8)
HSV_MIN_AREA_FRAC = 0.012
HSV_DEBOUNCE_FRAMES = 15

# ─── Estados ─────────────────────────────────────────────────────────────────
ESTADO_AGUARDANDO = "AGUARDANDO_LOGIN"
ESTADO_TREINO     = "TREINO_ATIVO"
ESTADO_CONCLUIDO  = "TREINO_CONCLUIDO"

ESTAGIO_IDLE     = "idle"
ESTAGIO_EXTENSAO = "extensao"
ESTAGIO_FLEXAO   = "flexao"

ANGULO_EXTENSAO = 145
ANGULO_FLEXAO   = 55
POSE_VIS_MIN    = 0.50

# ─── Paleta de cores ─────────────────────────────────────────────────────────
COR_BG       = "#0d0d0d"
COR_PAINEL   = "#1a1a1a"
COR_DESTAQUE = "#e91e8c"
COR_VERDE    = "#00e676"
COR_AMARELO  = "#ffd740"
COR_TEXTO    = "#ffffff"
COR_CINZA    = "#888888"
COR_AZUL     = "#00e5ff"
COR_LARANJA  = "#ff9800"
COR_VERMELHO = "#f44336"


# ═══════════════════════════════════════════════════════════════════════════════
#  MQTT CLIENT
# ═══════════════════════════════════════════════════════════════════════════════
class MqttClient:
    """
    Wrapper sobre paho-mqtt.
    Conecta ao broker em background thread (loop_start).
    Publica payloads JSON com retain=True para que o Dashboard receba
    o estado atual imediatamente ao conectar.
    """

    def __init__(self, broker: str, port: int, client_id: str):
        self._ativo = False
        if not _MQTT_DISPONIVEL:
            return

        self._client = mqtt_client.Client(client_id=client_id, clean_session=True)
        self._client.on_connect    = self._on_connect
        self._client.on_disconnect = self._on_disconnect

        try:
            self._client.connect_async(broker, port, keepalive=60)
            self._client.loop_start()
            self._ativo = True
            print(f"[MQTT] Conectando a {broker}:{port} (client_id={client_id})")
        except Exception as e:
            print(f"[MQTT] Falha na conexão: {e}")

    # ── Callbacks internos ────────────────────────────────────────────────────
    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print("[MQTT] Broker conectado com sucesso.")
        else:
            print(f"[MQTT] Falha na conexão, código: {rc}")

    def _on_disconnect(self, client, userdata, rc):
        if rc != 0:
            print(f"[MQTT] Desconectado inesperadamente (rc={rc}). Reconectando...")

    # ── API pública ───────────────────────────────────────────────────────────
    @property
    def ativo(self) -> bool:
        return self._ativo

    def publicar(self, topico: str, payload: dict | str):
        """Serializa dict como JSON e publica com retain=True."""
        if not self._ativo:
            return
        try:
            if isinstance(payload, dict):
                mensagem = json.dumps(payload, ensure_ascii=False)
            else:
                mensagem = str(payload)
            self._client.publish(topico, mensagem, qos=1, retain=True)
            print(f"[MQTT] Publicado → {topico}: {mensagem}")
        except Exception as e:
            print(f"[MQTT] Erro ao publicar: {e}")

    def desconectar(self):
        if self._ativo:
            self._client.loop_stop()
            self._client.disconnect()
            self._ativo = False
            print("[MQTT] Desconectado.")


# ═══════════════════════════════════════════════════════════════════════════════
#  BANCO DE DADOS
# ═══════════════════════════════════════════════════════════════════════════════
class BancoDados:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def _conn(self):
        return sqlite3.connect(self.db_path)

    def buscar_aluno_por_uid(self, uid: str):
        conn = self._conn()
        cur  = conn.cursor()
        cur.execute(
            "SELECT id, nome, exercicio, repeticoes FROM alunos WHERE uid_rfid = ?",
            (uid,)
        )
        row = cur.fetchone()
        conn.close()
        if row:
            return {"id": row[0], "nome": row[1], "exercicio": row[2], "repeticoes": row[3]}
        return None

    def registrar_acesso(self, aluno_id: int, uid: str) -> int:
        conn = self._conn()
        cur  = conn.cursor()
        cur.execute(
            "INSERT INTO log_acessos (aluno_id, uid_rfid) VALUES (?, ?)",
            (aluno_id, uid)
        )
        log_id = cur.lastrowid
        conn.commit()
        conn.close()
        return log_id

    def finalizar_acesso(self, log_id: int, reps_feitas: int, concluido: bool):
        conn = self._conn()
        cur  = conn.cursor()
        cur.execute(
            "UPDATE log_acessos SET reps_feitas=?, concluido=? WHERE id=?",
            (reps_feitas, int(concluido), log_id)
        )
        conn.commit()
        conn.close()

    def contar_treinos(self, aluno_id: int) -> int:
        conn = self._conn()
        cur  = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM log_acessos WHERE aluno_id=? AND concluido=1",
            (aluno_id,)
        )
        total = cur.fetchone()[0]
        conn.close()
        return total


# ═══════════════════════════════════════════════════════════════════════════════
#  LEITOR RFID (serial Arduino)
# ═══════════════════════════════════════════════════════════════════════════════
class LeitorRFID:
    def __init__(self, porta: str, baud: int):
        self.porta = porta
        self.baud  = baud
        self.ser   = None
        self.ativo = False

    def conectar(self) -> bool:
        try:
            import serial
            self.ser   = serial.Serial(self.porta, self.baud, timeout=0.1)
            self.ativo = True
            print(f"[RFID] Arduino conectado em {self.porta}")
            return True
        except Exception as e:
            print(f"[RFID] Sem conexão ({e}) — modo teclado ativo")
            return False

    def ler_uid(self) -> str | None:
        if not self.ativo or not self.ser:
            return None
        try:
            if self.ser.in_waiting > 0:
                linha = self.ser.readline().decode("utf-8", errors="ignore").strip()
                if "UID:" in linha:
                    return linha.split("UID:")[1].strip().upper()
        except Exception:
            pass
        return None

    def enviar_status(self, status: str):
        """Envia STATUS:ocupada ou STATUS:livre para o Arduino."""
        if not self.ativo or not self.ser:
            return
        try:
            self.ser.write(f"STATUS:{status}\n".encode("utf-8"))
        except Exception as e:
            print(f"[RFID] Erro ao enviar status: {e}")

    def fechar(self):
        if self.ser:
            self.ser.close()


# ═══════════════════════════════════════════════════════════════════════════════
#  DETECTOR DE EQUIPAMENTO
# ═══════════════════════════════════════════════════════════════════════════════
class DetectorEquipamento:
    """
    Prioridade automática:
      1. MediaPipe EfficientDet (efficientdet_lite0.tflite)
      2. YOLO YOLOv8n (se ultralytics instalado)
      3. HSV OpenCV (último recurso)
    """

    _MODO_EFFDET = "EfficientDet (MediaPipe)"
    _MODO_YOLO   = "YOLO (YOLOv8n)"
    _MODO_HSV    = "HSV (OpenCV)"

    def __init__(self):
        self._modo           = None
        self._detector_mp    = None
        self._modelo_yolo    = None
        self._frames_ausente = 0
        self._ultimo_estado  = False
        self._carregar()

    def _carregar(self):
        if os.path.exists(OBJ_MODEL_PATH):
            try:
                base = mp_python.BaseOptions(model_asset_path=OBJ_MODEL_PATH)
                opts = mp_vision.ObjectDetectorOptions(
                    base_options=base,
                    running_mode=mp_vision.RunningMode.VIDEO,
                    score_threshold=OBJ_CONF_THRESHOLD,
                    max_results=10,
                )
                self._detector_mp = mp_vision.ObjectDetector.create_from_options(opts)
                self._modo = self._MODO_EFFDET
                print(f"[DETECTOR] {self._modo} ativo.")
                return
            except Exception as e:
                print(f"[DETECTOR] EfficientDet falhou ({e}).")

        if _YOLO_DISPONIVEL:
            try:
                self._modelo_yolo = _YOLO("yolov8n.pt")
                self._modo = self._MODO_YOLO
                print(f"[DETECTOR] {self._modo} ativo.")
                return
            except Exception as e:
                print(f"[DETECTOR] YOLO falhou ({e}).")

        self._modo = self._MODO_HSV
        print(f"[DETECTOR] {self._modo} ativo (fallback).")

    @property
    def nome_modo(self) -> str:
        return self._modo or self._MODO_HSV

    def detectar(self, frame_bgr, timestamp_ms: int = 0):
        if self._modo == self._MODO_EFFDET:
            presente, frame_bgr, info = self._detectar_effdet(frame_bgr, timestamp_ms)
        elif self._modo == self._MODO_YOLO:
            presente, frame_bgr, info = self._detectar_yolo(frame_bgr)
        else:
            presente, frame_bgr, info = self._detectar_hsv(frame_bgr)

        if presente:
            self._frames_ausente = 0
            self._ultimo_estado  = True
        else:
            self._frames_ausente += 1
            if self._frames_ausente < HSV_DEBOUNCE_FRAMES:
                presente = self._ultimo_estado
            else:
                self._ultimo_estado = False

        return presente, frame_bgr, info

    def _detectar_effdet(self, frame_bgr, timestamp_ms: int):
        rgb    = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = self._detector_mp.detect_for_video(mp_img, timestamp_ms)

        equip_presente = False
        info           = []

        for det in result.detections:
            cat   = det.categories[0]
            label = cat.category_name
            conf  = cat.score
            bb    = det.bounding_box
            x1, y1 = bb.origin_x, bb.origin_y
            x2, y2 = x1 + bb.width, y1 + bb.height
            info.append((x1, y1, x2, y2, conf, label))

            is_equip = label.lower() in OBJ_CATEGORIAS_EQUIP
            if is_equip:
                equip_presente = True
                cv2.rectangle(frame_bgr, (x1, y1), (x2, y2), (200, 0, 220), 2)
                cv2.rectangle(frame_bgr, (x1, max(y1 - 26, 0)), (x2, y1), (200, 0, 220), -1)
                cv2.putText(frame_bgr,
                            f"{label} {conf:.0%}",
                            (x1 + 4, max(y1 - 6, 12)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
            else:
                cv2.rectangle(frame_bgr, (x1, y1), (x2, y2), (80, 80, 80), 1)
                cv2.putText(frame_bgr, label,
                            (x1 + 2, y1 - 4),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.40, (120, 120, 120), 1)

        return equip_presente, frame_bgr, info

    def _detectar_yolo(self, frame_bgr):
        resultados     = self._modelo_yolo(frame_bgr, verbose=False, conf=YOLO_CONF_THRESHOLD)
        equip_presente = False
        boxes_info     = []

        for r in resultados:
            for box in r.boxes:
                cls_id = int(box.cls[0])
                conf   = float(box.conf[0])
                label  = self._modelo_yolo.names[cls_id]
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                boxes_info.append((x1, y1, x2, y2, conf, label))

                if cls_id in YOLO_EQUIPMENT_IDS:
                    equip_presente = True
                    cv2.rectangle(frame_bgr, (x1, y1), (x2, y2), (200, 0, 220), 2)
                    cv2.rectangle(frame_bgr, (x1, y1 - 26), (x2, y1), (200, 0, 220), -1)
                    cv2.putText(frame_bgr, f"{label} {conf:.0%}",
                                (x1 + 4, y1 - 6),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
                else:
                    cv2.rectangle(frame_bgr, (x1, y1), (x2, y2), (80, 80, 80), 1)

        return equip_presente, frame_bgr, boxes_info

    def _detectar_hsv(self, frame_bgr):
        h, w       = frame_bgr.shape[:2]
        min_area   = h * w * HSV_MIN_AREA_FRAC

        hsv  = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, HSV_DARK_LOW, HSV_DARK_HIGH)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
        mask   = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        mask   = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  kernel)

        contornos, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        equip_presente = False
        info           = []

        for cnt in contornos:
            if cv2.contourArea(cnt) < min_area:
                continue
            x, y, cw, ch = cv2.boundingRect(cnt)
            info.append((x, y, cw, ch))
            ratio = max(ch / max(cw, 1), cw / max(ch, 1))
            if ratio < 1.2:
                continue
            equip_presente = True
            cv2.rectangle(frame_bgr, (x, y), (x + cw, y + ch), (0, 220, 220), 2)
            cv2.rectangle(frame_bgr, (x, max(y - 22, 0)), (x + cw, y), (0, 220, 220), -1)
            cv2.putText(frame_bgr, "equipamento (HSV)",
                        (x + 4, max(y - 5, 12)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 0, 0), 1)

        return equip_presente, frame_bgr, info


# ═══════════════════════════════════════════════════════════════════════════════
#  MOTOR DE POSE (MediaPipe)
# ═══════════════════════════════════════════════════════════════════════════════
class MotorPose:
    def __init__(self, model_path: str):
        self.detector   = None
        self.disponivel = False
        self._carregar(model_path)

    def _carregar(self, model_path):
        if not os.path.exists(model_path):
            print(f"[POSE] Modelo não encontrado: {model_path}")
            return
        try:
            base_options = mp_python.BaseOptions(model_asset_path=model_path)
            options      = mp_vision.PoseLandmarkerOptions(
                base_options=base_options,
                running_mode=mp_vision.RunningMode.VIDEO
            )
            self.detector   = mp_vision.PoseLandmarker.create_from_options(options)
            self.disponivel = True
            print("[POSE] MediaPipe carregado.")
        except Exception as e:
            print(f"[POSE] Erro ao carregar MediaPipe: {e}")

    def processar_frame(self, frame_bgr, timestamp_ms: int):
        if not self.disponivel:
            return None, frame_bgr

        rgb    = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = self.detector.detect_for_video(mp_img, timestamp_ms)

        h, w   = frame_bgr.shape[:2]
        angulo = None

        if result.pose_landmarks:
            m = result.pose_landmarks[0]

            BRACOS = [
                (11, 13, 15),
                (12, 14, 16),
            ]

            melhor_vis = -1.0
            escolha    = None

            for ids in BRACOS:
                pts_vis = [m[i].visibility for i in ids]
                vis_min = min(pts_vis)
                if vis_min >= POSE_VIS_MIN and vis_min > melhor_vis:
                    melhor_vis = vis_min
                    escolha    = ids

            if escolha:
                oi, ci, pi = escolha
                ombro  = (int(m[oi].x * w), int(m[oi].y * h))
                cotove = (int(m[ci].x * w), int(m[ci].y * h))
                pulso  = (int(m[pi].x * w), int(m[pi].y * h))

                angulo = _calcular_angulo(ombro, cotove, pulso)

                cv2.line(frame_bgr, ombro, cotove, (255, 255, 255), 2)
                cv2.line(frame_bgr, cotove, pulso,  (255, 255, 255), 2)
                for pt in [ombro, cotove, pulso]:
                    cv2.circle(frame_bgr, pt, 10, (0, 0, 255), -1)

                cv2.putText(frame_bgr, f"{int(angulo)}\xb0",
                            (cotove[0] + 15, cotove[1] - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 0), 2)

        return angulo, frame_bgr


def _calcular_angulo(a, b, c) -> float:
    a, b, c = np.array(a), np.array(b), np.array(c)
    rad = np.arctan2(c[1] - b[1], c[0] - b[0]) - np.arctan2(a[1] - b[1], a[0] - b[0])
    ang = abs(rad * 180.0 / np.pi)
    if ang > 180:
        ang = 360 - ang
    return ang


# ═══════════════════════════════════════════════════════════════════════════════
#  CONTADORA DE REPETIÇÕES (máquina de estados)
# ═══════════════════════════════════════════════════════════════════════════════
class ContadorReps:
    def __init__(self):
        self.reps    = 0
        self.estagio = ESTAGIO_IDLE

    def resetar(self):
        self.reps    = 0
        self.estagio = ESTAGIO_IDLE

    def processar(self, angulo: float | None, equipamento_presente: bool) -> bool:
        if angulo is None or not equipamento_presente:
            return False

        nova_rep = False

        if self.estagio == ESTAGIO_IDLE:
            if angulo >= ANGULO_EXTENSAO:
                self.estagio = ESTAGIO_EXTENSAO

        elif self.estagio == ESTAGIO_EXTENSAO:
            if angulo <= ANGULO_FLEXAO:
                self.estagio = ESTAGIO_FLEXAO

        elif self.estagio == ESTAGIO_FLEXAO:
            if angulo >= ANGULO_EXTENSAO:
                self.estagio = ESTAGIO_EXTENSAO
                self.reps   += 1
                nova_rep     = True

        return nova_rep

    @property
    def descricao_estagio(self) -> str:
        return {
            ESTAGIO_IDLE:     "Aguardando posição inicial",
            ESTAGIO_EXTENSAO: "Braço estendido — execute a flexão",
            ESTAGIO_FLEXAO:   "Braço flexionado — estenda para contar",
        }.get(self.estagio, "")


# ═══════════════════════════════════════════════════════════════════════════════
#  INTERFACE (Tkinter)
# ═══════════════════════════════════════════════════════════════════════════════
class SmartGymApp:
    def __init__(self, root: tk.Tk):
        self.root  = root
        self.root.title("Smart Gym — CP05 | MQTT + YOLO + MediaPipe")
        self.root.configure(bg=COR_BG)
        self.root.geometry("1200x720")
        self.root.resizable(False, False)

        # ── Módulos ──────────────────────────────────────────────────────────
        self.db       = BancoDados(DB_PATH)
        self.rfid     = LeitorRFID(SERIAL_PORT, BAUD_RATE)
        self.pose     = MotorPose(MODEL_PATH)
        self.yolo     = DetectorEquipamento()
        self.contador = ContadorReps()
        self.cap      = None

        # ── MQTT ─────────────────────────────────────────────────────────────
        self.mqtt = MqttClient(MQTT_BROKER, MQTT_PORT, MQTT_CLIENT_ID)

        # ── Estado ───────────────────────────────────────────────────────────
        self.estado            = ESTADO_AGUARDANDO
        self.perfil_ativo      = None
        self.log_id            = None
        self.total_treinos     = 0
        self._ts_inicio        = 0
        self._equip_presente   = False

        self.rfid.conectar()
        self._build_ui()
        self._iniciar_camera()
        self._loop_rfid()
        self._loop_camera()

        # Publica estado inicial: máquina livre
        self._mqtt_publicar_status("livre")

    # ──────────────────────────────────────────────────────────────────────────
    #  MQTT — helpers de publicação
    # ──────────────────────────────────────────────────────────────────────────
    def _mqtt_publicar_status(self, status: str):
        """status: 'livre' ou 'ocupada'"""
        self.mqtt.publicar(TOPICO_STATUS, status)
        self.rfid.enviar_status(status)
        # Atualiza badge MQTT na UI
        cor   = COR_VERDE if status == "livre" else COR_VERMELHO
        texto = f"MQTT: máquina {status.upper()}"
        self.lbl_mqtt_status.configure(text=texto, fg=cor)

    def _mqtt_publicar_aluno(self, aluno: dict, uid: str):
        self.mqtt.publicar(TOPICO_ALUNO, {
            "nome":      aluno["nome"],
            "exercicio": aluno["exercicio"],
            "uid":       uid,
        })

    def _mqtt_publicar_reps(self, reps: int, meta: int, concluido: bool = False):
        nome = self.perfil_ativo["nome"] if self.perfil_ativo else "—"
        self.mqtt.publicar(TOPICO_REPS, {
            "nome":      nome,
            "reps":      reps,
            "meta":      meta,
            "concluido": concluido,
        })

    # ──────────────────────────────────────────────────────────────────────────
    #  BUILD UI
    # ──────────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        # ── Header ────────────────────────────────────────────────────────────
        header = tk.Frame(self.root, bg=COR_DESTAQUE, height=60)
        header.pack(fill=tk.X)
        tk.Label(header, text="⚡ SMART GYM  —  CP05",
                 font=("Helvetica", 22, "bold"),
                 bg=COR_DESTAQUE, fg=COR_TEXTO).pack(side=tk.LEFT, padx=20)

        # Badge MQTT no header
        self.lbl_mqtt_status = tk.Label(
            header,
            text="MQTT: conectando...",
            font=("Helvetica", 11, "bold"),
            bg=COR_DESTAQUE, fg=COR_AMARELO
        )
        self.lbl_mqtt_status.pack(side=tk.RIGHT, padx=20)

        self.lbl_hora = tk.Label(header, text="",
                                  font=("Helvetica", 13),
                                  bg=COR_DESTAQUE, fg=COR_TEXTO)
        self.lbl_hora.pack(side=tk.RIGHT, padx=10)
        self._atualizar_hora()

        # ── Corpo ─────────────────────────────────────────────────────────────
        corpo = tk.Frame(self.root, bg=COR_BG)
        corpo.pack(fill=tk.BOTH, expand=True, padx=15, pady=10)

        painel_esq = tk.Frame(corpo, bg=COR_PAINEL, width=340, bd=0,
                               highlightthickness=1, highlightbackground=COR_DESTAQUE)
        painel_esq.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 12))
        painel_esq.pack_propagate(False)
        self._build_painel_info(painel_esq)

        painel_cam = tk.Frame(corpo, bg=COR_PAINEL, bd=0,
                               highlightthickness=1, highlightbackground="#333333")
        painel_cam.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._build_painel_camera(painel_cam)

        # ── Rodapé ────────────────────────────────────────────────────────────
        rodape = tk.Frame(self.root, bg="#111111", height=30)
        rodape.pack(fill=tk.X)
        tk.Label(rodape,
                 text="[S] Entrar como Convidado    [Q] Sair    [R] Resetar",
                 font=("Courier", 10), bg="#111111", fg=COR_CINZA).pack()

        self.root.bind("<KeyPress-s>", lambda e: self._login_convidado())
        self.root.bind("<KeyPress-S>", lambda e: self._login_convidado())
        self.root.bind("<KeyPress-q>", lambda e: self._sair())
        self.root.bind("<KeyPress-Q>", lambda e: self._sair())
        self.root.bind("<KeyPress-r>", lambda e: self._resetar())
        self.root.bind("<KeyPress-R>", lambda e: self._resetar())

    def _build_painel_info(self, parent):
        pad = dict(padx=18, pady=5)

        # ── Status da estação ─────────────────────────────────────────────────
        tk.Label(parent, text="STATUS DA ESTAÇÃO",
                 font=("Helvetica", 9, "bold"),
                 bg=COR_PAINEL, fg=COR_CINZA).pack(anchor="w", **pad)

        frm_status = tk.Frame(parent, bg=COR_PAINEL)
        frm_status.pack(fill=tk.X, padx=18, pady=3)
        self.canvas_status = tk.Canvas(frm_status, width=12, height=12,
                                        bg=COR_PAINEL, highlightthickness=0)
        self.canvas_status.pack(side=tk.LEFT)
        self._dot_status = self.canvas_status.create_oval(1, 1, 11, 11, fill=COR_CINZA)
        self.lbl_status = tk.Label(frm_status, text="Aguardando Login",
                                    font=("Helvetica", 12, "bold"),
                                    bg=COR_PAINEL, fg=COR_CINZA)
        self.lbl_status.pack(side=tk.LEFT, padx=8)

        self._sep(parent)

        # ── Badge equipamento ─────────────────────────────────────────────────
        tk.Label(parent, text="EQUIPAMENTO",
                 font=("Helvetica", 9, "bold"),
                 bg=COR_PAINEL, fg=COR_CINZA).pack(anchor="w", **pad)

        frm_equip = tk.Frame(parent, bg=COR_PAINEL)
        frm_equip.pack(fill=tk.X, padx=18, pady=3)
        self.canvas_equip = tk.Canvas(frm_equip, width=12, height=12,
                                       bg=COR_PAINEL, highlightthickness=0)
        self.canvas_equip.pack(side=tk.LEFT)
        self._dot_equip = self.canvas_equip.create_oval(1, 1, 11, 11, fill=COR_CINZA)
        self.lbl_equip = tk.Label(frm_equip, text="Aguardando Equipamento",
                                   font=("Helvetica", 11, "bold"),
                                   bg=COR_PAINEL, fg=COR_CINZA)
        self.lbl_equip.pack(side=tk.LEFT, padx=8)

        self._sep(parent)

        # ── Avatar / aluno ────────────────────────────────────────────────────
        self.lbl_avatar = tk.Label(parent, text="👤",
                                    font=("Helvetica", 46),
                                    bg=COR_PAINEL, fg=COR_CINZA)
        self.lbl_avatar.pack(pady=(10, 0))
        self.lbl_boas_vindas = tk.Label(parent,
                                         text="Aproxime o cartão\nou pressione [S]",
                                         font=("Helvetica", 14),
                                         bg=COR_PAINEL, fg=COR_CINZA,
                                         justify=tk.CENTER)
        self.lbl_boas_vindas.pack(pady=4)

        self._sep(parent)

        # ── Exercício ─────────────────────────────────────────────────────────
        tk.Label(parent, text="EXERCÍCIO",
                 font=("Helvetica", 9, "bold"),
                 bg=COR_PAINEL, fg=COR_CINZA).pack(anchor="w", **pad)
        self.lbl_exercicio = tk.Label(parent, text="—",
                                       font=("Helvetica", 16, "bold"),
                                       bg=COR_PAINEL, fg=COR_AZUL)
        self.lbl_exercicio.pack(anchor="w", padx=18)

        self._sep(parent)

        # ── Contadores ───────────────────────────────────────────────────────
        frm_reps = tk.Frame(parent, bg=COR_PAINEL)
        frm_reps.pack(fill=tk.X, padx=18, pady=6)
        frm_l = tk.Frame(frm_reps, bg=COR_PAINEL)
        frm_l.pack(side=tk.LEFT, expand=True)
        tk.Label(frm_l, text="REPS", font=("Helvetica", 9, "bold"),
                 bg=COR_PAINEL, fg=COR_CINZA).pack()
        self.lbl_reps = tk.Label(frm_l, text="0",
                                  font=("Helvetica", 44, "bold"),
                                  bg=COR_PAINEL, fg=COR_VERDE)
        self.lbl_reps.pack()

        frm_r = tk.Frame(frm_reps, bg=COR_PAINEL)
        frm_r.pack(side=tk.LEFT, expand=True)
        tk.Label(frm_r, text="META", font=("Helvetica", 9, "bold"),
                 bg=COR_PAINEL, fg=COR_CINZA).pack()
        self.lbl_meta = tk.Label(frm_r, text="—",
                                  font=("Helvetica", 44, "bold"),
                                  bg=COR_PAINEL, fg=COR_CINZA)
        self.lbl_meta.pack()

        self._sep(parent)

        # ── Barra de progresso ────────────────────────────────────────────────
        tk.Label(parent, text="PROGRESSO",
                 font=("Helvetica", 9, "bold"),
                 bg=COR_PAINEL, fg=COR_CINZA).pack(anchor="w", **pad)
        self.progress_bg = tk.Canvas(parent, height=18, bg="#333333",
                                      highlightthickness=0)
        self.progress_bg.pack(fill=tk.X, padx=18, pady=(0, 6))
        self.progress_fill = self.progress_bg.create_rectangle(
            0, 0, 0, 18, fill=COR_DESTAQUE, outline=""
        )

        self._sep(parent)

        # ── Estágio do ciclo ──────────────────────────────────────────────────
        tk.Label(parent, text="FASE DO MOVIMENTO",
                 font=("Helvetica", 9, "bold"),
                 bg=COR_PAINEL, fg=COR_CINZA).pack(anchor="w", **pad)
        self.lbl_fase = tk.Label(parent, text="—",
                                  font=("Helvetica", 10, "italic"),
                                  bg=COR_PAINEL, fg=COR_AMARELO,
                                  wraplength=300, justify=tk.CENTER)
        self.lbl_fase.pack(padx=18, pady=(2, 6))

        self._sep(parent)

        # ── Treinos concluídos ────────────────────────────────────────────────
        tk.Label(parent, text="TREINOS CONCLUÍDOS",
                 font=("Helvetica", 9, "bold"),
                 bg=COR_PAINEL, fg=COR_CINZA).pack(anchor="w", **pad)
        self.lbl_total = tk.Label(parent, text="—",
                                   font=("Helvetica", 22, "bold"),
                                   bg=COR_PAINEL, fg=COR_AMARELO)
        self.lbl_total.pack(anchor="w", padx=18)

        # ── Feedback ─────────────────────────────────────────────────────────
        self.lbl_feedback = tk.Label(parent, text="",
                                      font=("Helvetica", 11, "italic"),
                                      bg=COR_PAINEL, fg=COR_AMARELO,
                                      wraplength=300, justify=tk.CENTER)
        self.lbl_feedback.pack(pady=6, padx=12)

    def _build_painel_camera(self, parent):
        modo = self.yolo.nome_modo
        tk.Label(parent,
                 text=f"MONITORAMENTO — {modo.upper()} + MEDIAPIPE",
                 font=("Helvetica", 9, "bold"),
                 bg=COR_PAINEL, fg=COR_CINZA).pack(anchor="nw", padx=12, pady=(8, 4))
        self.lbl_cam = tk.Label(parent, bg="#000000")
        self.lbl_cam.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

    def _sep(self, parent):
        tk.Frame(parent, bg="#333333", height=1).pack(fill=tk.X, padx=12, pady=3)

    # ──────────────────────────────────────────────────────────────────────────
    #  CÂMERA — loop principal de visão computacional
    # ──────────────────────────────────────────────────────────────────────────
    def _iniciar_camera(self):
        self.cap = cv2.VideoCapture(0)
        if not self.cap.isOpened():
            print("[CAM] Câmera não disponível.")

    def _loop_camera(self):
        if self.cap and self.cap.isOpened():
            ret, frame = self.cap.read()
            if ret:
                frame = cv2.flip(frame, 1)

                if self.estado == ESTADO_TREINO:
                    ts_ms = int((time.time() - self._ts_inicio) * 1000)

                    # 1. Detecta equipamento
                    equip, frame, _ = self.yolo.detectar(frame, timestamp_ms=ts_ms)
                    self._equip_presente = equip
                    self._atualizar_badge_equip(equip)

                    # 2. MediaPipe — detecta pose e calcula ângulo
                    angulo, frame = self.pose.processar_frame(frame, ts_ms)

                    # 3. Contagem de reps
                    nova_rep = self.contador.processar(angulo, equip)
                    if nova_rep:
                        self._atualizar_reps(self.contador.reps)
                        meta = self.perfil_ativo["repeticoes"]
                        # Publica rep via MQTT
                        self._mqtt_publicar_reps(self.contador.reps, meta)
                        if self.contador.reps >= meta:
                            self._concluir_treino()

                    # Fase do movimento na UI
                    self.lbl_fase.configure(text=self.contador.descricao_estagio)

                    # Overlay de aviso se equipamento ausente
                    if not equip:
                        h, w = frame.shape[:2]
                        overlay = frame.copy()
                        cv2.rectangle(overlay, (0, h - 48), (w, h), (0, 0, 0), -1)
                        cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)
                        cv2.putText(frame,
                                    "Aguardando Equipamento — contagem pausada",
                                    (14, h - 16),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                                    (0, 200, 255), 1)

                elif self.estado == ESTADO_AGUARDANDO:
                    h, w = frame.shape[:2]
                    cv2.putText(frame, "APROXIME O CARTAO",
                                (w // 2 - 160, h // 2 - 15),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2)
                    cv2.putText(frame, "ou pressione [S]",
                                (w // 2 - 120, h // 2 + 25),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 1)

                # Exibe frame no Tkinter
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                frame_rgb = cv2.resize(frame_rgb, (820, 570))
                img = ImageTk.PhotoImage(Image.fromarray(frame_rgb))
                self.lbl_cam.configure(image=img)
                self.lbl_cam.image = img

        self.root.after(33, self._loop_camera)

    # ──────────────────────────────────────────────────────────────────────────
    #  RFID
    # ──────────────────────────────────────────────────────────────────────────
    def _loop_rfid(self):
        if self.estado == ESTADO_AGUARDANDO:
            uid = self.rfid.ler_uid()
            if uid:
                self._processar_uid(uid)
        self.root.after(200, self._loop_rfid)

    def _processar_uid(self, uid: str):
        aluno = self.db.buscar_aluno_por_uid(uid)
        if aluno:
            self._ativar_treino(aluno, uid)
        else:
            self._set_feedback(f"UID não cadastrado:\n{uid}", COR_AMARELO)

    # ──────────────────────────────────────────────────────────────────────────
    #  TREINO
    # ──────────────────────────────────────────────────────────────────────────
    def _ativar_treino(self, aluno: dict, uid: str):
        self.perfil_ativo    = aluno
        self.log_id          = self.db.registrar_acesso(aluno["id"], uid)
        self.total_treinos   = self.db.contar_treinos(aluno["id"])
        self.estado          = ESTADO_TREINO
        self._ts_inicio      = time.time()
        self._equip_presente = False
        self.contador.resetar()

        self.lbl_avatar.configure(text="🏋️", fg=COR_DESTAQUE)
        self.lbl_boas_vindas.configure(
            text=f"Bem-vindo,\n{aluno['nome']}!", fg=COR_TEXTO)
        self.lbl_exercicio.configure(text=aluno["exercicio"])
        self.lbl_meta.configure(text=str(aluno["repeticoes"]), fg=COR_TEXTO)
        self.lbl_total.configure(text=str(self.total_treinos))
        self._set_status("Treino Ativo", COR_VERDE)
        self._set_feedback("Posicione-se e segure o celular!", COR_VERDE)
        self._atualizar_reps(0)
        self._atualizar_badge_equip(False)
        self.lbl_fase.configure(text=self.contador.descricao_estagio)

        # ── Publicações MQTT ─────────────────────────────────────────────────
        self._mqtt_publicar_status("ocupada")
        self._mqtt_publicar_aluno(aluno, uid)
        # Publica reps zeradas para limpar estado anterior no dashboard
        self._mqtt_publicar_reps(0, aluno["repeticoes"])

        print(f"[GYM] Login: {aluno['nome']} | {aluno['exercicio']} x{aluno['repeticoes']}")

    def _concluir_treino(self):
        self.estado = ESTADO_CONCLUIDO
        self.db.finalizar_acesso(self.log_id, self.contador.reps, concluido=True)
        self.total_treinos += 1
        self.lbl_total.configure(text=str(self.total_treinos))
        self._set_status("Treino Concluído ✓", COR_VERDE)
        self._set_feedback("🎉 Parabéns! Meta atingida!\nDescanse 60–90 segundos.", COR_VERDE)
        self.lbl_avatar.configure(text="🏆", fg=COR_VERDE)

        # ── Publicações MQTT ─────────────────────────────────────────────────
        meta = self.perfil_ativo["repeticoes"]
        self._mqtt_publicar_reps(self.contador.reps, meta, concluido=True)
        self._mqtt_publicar_status("livre")

        print(f"[GYM] Concluído: {self.perfil_ativo['nome']} | "
              f"{self.contador.reps} reps | log_id={self.log_id}")
        self.root.after(8000, self._resetar)

    def _resetar(self):
        if self.log_id and self.estado != ESTADO_CONCLUIDO:
            self.db.finalizar_acesso(self.log_id, self.contador.reps, concluido=False)

        self.estado          = ESTADO_AGUARDANDO
        self.perfil_ativo    = None
        self.log_id          = None
        self._equip_presente = False
        self.contador.resetar()

        self.lbl_avatar.configure(text="👤", fg=COR_CINZA)
        self.lbl_boas_vindas.configure(
            text="Aproxime o cartão\nou pressione [S]", fg=COR_CINZA)
        self.lbl_exercicio.configure(text="—")
        self.lbl_reps.configure(text="0", fg=COR_VERDE)
        self.lbl_meta.configure(text="—", fg=COR_CINZA)
        self.lbl_total.configure(text="—")
        self.lbl_fase.configure(text="—")
        self._set_status("Aguardando Login", COR_CINZA)
        self._set_feedback("", COR_CINZA)
        self._atualizar_barra(0, 1)
        self._atualizar_badge_equip(False)

        # ── Publicação MQTT ──────────────────────────────────────────────────
        self._mqtt_publicar_status("livre")

        print("[GYM] Estação resetada.")

    def _login_convidado(self):
        if self.estado == ESTADO_AGUARDANDO:
            aluno = self.db.buscar_aluno_por_uid("GUEST:000000")
            if aluno:
                self._ativar_treino(aluno, "GUEST:000000")

    # ──────────────────────────────────────────────────────────────────────────
    #  HELPERS DE UI
    # ──────────────────────────────────────────────────────────────────────────
    def _atualizar_badge_equip(self, presente: bool):
        if presente:
            self.canvas_equip.itemconfig(self._dot_equip, fill=COR_VERDE)
            self.lbl_equip.configure(text="Equipamento Detectado ✓", fg=COR_VERDE)
        else:
            self.canvas_equip.itemconfig(self._dot_equip, fill=COR_LARANJA)
            self.lbl_equip.configure(text="Aguardando Equipamento", fg=COR_LARANJA)

    def _atualizar_reps(self, reps: int):
        meta = self.perfil_ativo["repeticoes"] if self.perfil_ativo else 1
        self.lbl_reps.configure(text=str(reps))
        cor = COR_VERDE if reps < meta else COR_DESTAQUE
        self.lbl_reps.configure(fg=cor)
        self._atualizar_barra(reps, meta)

    def _atualizar_barra(self, atual: int, total: int):
        self.progress_bg.update_idletasks()
        largura = self.progress_bg.winfo_width()
        pct     = min(atual / total, 1.0) if total > 0 else 0
        self.progress_bg.coords(self.progress_fill, 0, 0, int(largura * pct), 18)

    def _set_status(self, texto: str, cor: str):
        self.lbl_status.configure(text=texto, fg=cor)
        self.canvas_status.itemconfig(self._dot_status, fill=cor)

    def _set_feedback(self, texto: str, cor: str):
        self.lbl_feedback.configure(text=texto, fg=cor)

    def _atualizar_hora(self):
        agora = datetime.now().strftime("%H:%M:%S  |  %d/%m/%Y")
        self.lbl_hora.configure(text=agora)
        self.root.after(1000, self._atualizar_hora)

    def _sair(self):
        self._mqtt_publicar_status("livre")
        self.mqtt.desconectar()
        if self.cap:
            self.cap.release()
        self.rfid.fechar()
        self.root.destroy()


# ═══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    if not os.path.exists(DB_PATH):
        print("[BOOT] Banco não encontrado — execute db/setup_db.py primeiro.")
    else:
        root = tk.Tk()
        app  = SmartGymApp(root)
        root.protocol("WM_DELETE_WINDOW", app._sair)
        root.mainloop()
