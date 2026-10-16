/**
 * Smart_Gym_RFID_CP05.ino — Smart Gym | CP05
 * Disciplina: Physical Computing (IoT & IoB) — FIAP
 *
 * Novidades CP05:
 *   - Recebe comandos de status via Serial vindo do Python:
 *       "STATUS:ocupada\n"  → acende LED vermelho
 *       "STATUS:livre\n"    → apaga LED vermelho
 *   - LED verde pisca ao enviar UID com sucesso (mantido do CP04)
 *   - LED vermelho permanece aceso enquanto estação estiver ocupada
 *
 * Hardware necessário:
 *   - Arduino Uno / Nano
 *   - Módulo RFID RC522
 *   - LED verde (pino 7) e LED vermelho (pino 8)
 *   - Buzzer (pino 6)
 *
 * Conexões RC522 → Arduino Uno:
 *   SDA  → D10
 *   SCK  → D13
 *   MOSI → D11
 *   MISO → D12
 *   GND  → GND
 *   RST  → D9
 *   3.3V → 3.3V
 *
 * Protocolo Serial (saída → Python):
 *   Baud: 9600
 *   "UID: XX:XX:XX:XX"
 *
 * Protocolo Serial (entrada ← Python):
 *   "STATUS:ocupada"  → LED vermelho acende
 *   "STATUS:livre"    → LED vermelho apaga
 *
 * Bibliotecas necessárias (Library Manager):
 *   - MFRC522 by GithubCommunity
 *   - SPI (nativa)
 */

#include <SPI.h>
#include <MFRC522.h>

// ── Pinos ────────────────────────────────────────────────────────────────────
#define SS_PIN    10
#define RST_PIN    9
#define LED_VERDE  7
#define LED_VERM   8
#define BUZZER     6

// ── Objetos ──────────────────────────────────────────────────────────────────
MFRC522 rfid(SS_PIN, RST_PIN);

// ── Estado ───────────────────────────────────────────────────────────────────
bool   estacaoOcupada = false;
String serialBuffer   = "";

// ── Debounce RFID ────────────────────────────────────────────────────────────
String        ultimoUID = "";
unsigned long tUlt      = 0;
const unsigned long DEBOUNCE_MS = 2000;

// ─────────────────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(9600);
  SPI.begin();
  rfid.PCD_Init();

  pinMode(LED_VERDE, OUTPUT);
  pinMode(LED_VERM,  OUTPUT);
  pinMode(BUZZER,    OUTPUT);

  // Pisca LEDs para indicar boot
  for (int i = 0; i < 3; i++) {
    digitalWrite(LED_VERDE, HIGH);
    delay(100);
    digitalWrite(LED_VERDE, LOW);
    delay(100);
  }

  Serial.println("Smart Gym RFID CP05 Pronto.");
  Serial.println("Aguardando cartao...");
}

// ─────────────────────────────────────────────────────────────────────────────
void loop() {
  // ── 1. Lê comandos de status vindos do Python ─────────────────────────────
  lerComandoSerial();

  // ── 2. Lê cartão RFID ─────────────────────────────────────────────────────
  if (!rfid.PICC_IsNewCardPresent() || !rfid.PICC_ReadCardSerial()) {
    return;
  }

  // Monta string do UID no formato XX:XX:XX:XX
  String uid = "";
  for (byte i = 0; i < rfid.uid.size; i++) {
    if (rfid.uid.uidByte[i] < 0x10) uid += "0";
    uid += String(rfid.uid.uidByte[i], HEX);
    if (i < rfid.uid.size - 1) uid += ":";
  }
  uid.toUpperCase();

  // Debounce — ignora leitura do mesmo cartão em menos de 2 s
  unsigned long agora = millis();
  if (uid == ultimoUID && (agora - tUlt) < DEBOUNCE_MS) {
    rfid.PICC_HaltA();
    rfid.PCD_StopCrypto1();
    return;
  }

  ultimoUID = uid;
  tUlt      = agora;

  // Envia para o Python no formato esperado: "UID: XX:XX:XX:XX"
  Serial.print("UID: ");
  Serial.println(uid);

  // Feedback: bipe + pisca LED verde (independente do estado da estação)
  beep(1, 100);
  digitalWrite(LED_VERDE, HIGH);
  delay(300);
  digitalWrite(LED_VERDE, LOW);

  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();
}

// ─────────────────────────────────────────────────────────────────────────────
/**
 * Lê bytes disponíveis na Serial e acumula no buffer até '\n'.
 * Ao receber linha completa, parseia comandos de status.
 */
void lerComandoSerial() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\n') {
      processarComando(serialBuffer);
      serialBuffer = "";
    } else if (c != '\r') {
      serialBuffer += c;
    }
  }
}

void processarComando(String cmd) {
  cmd.trim();
  if (cmd.startsWith("STATUS:")) {
    String valor = cmd.substring(7);
    valor.trim();
    if (valor.equalsIgnoreCase("ocupada")) {
      estacaoOcupada = true;
      digitalWrite(LED_VERM, HIGH);
    } else if (valor.equalsIgnoreCase("livre")) {
      estacaoOcupada = false;
      digitalWrite(LED_VERM, LOW);
    }
  }
}

// ─────────────────────────────────────────────────────────────────────────────
void beep(int vezes, int duracao_ms) {
  for (int i = 0; i < vezes; i++) {
    digitalWrite(BUZZER, HIGH);
    delay(duracao_ms);
    digitalWrite(BUZZER, LOW);
    if (i < vezes - 1) delay(100);
  }
}
