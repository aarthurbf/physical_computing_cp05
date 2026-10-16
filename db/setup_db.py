"""
setup_db.py - Script de criação e população do banco de dados SQLite
Smart Gym - CP02 | FIAP Physical Computing (IoT & IoB)
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "smart_gym.db")

def criar_banco():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS alunos (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            nome        TEXT    NOT NULL,
            uid_rfid    TEXT    NOT NULL UNIQUE,
            exercicio   TEXT    NOT NULL,
            repeticoes  INTEGER NOT NULL,
            criado_em   DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS log_acessos (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            aluno_id    INTEGER NOT NULL,
            uid_rfid    TEXT    NOT NULL,
            horario     DATETIME DEFAULT CURRENT_TIMESTAMP,
            reps_feitas INTEGER DEFAULT 0,
            concluido   INTEGER DEFAULT 0,
            FOREIGN KEY (aluno_id) REFERENCES alunos(id)
        )
    """)

    conn.commit()
    conn.close()
    print("[DB] Tabelas criadas com sucesso.")


def popular_alunos():
    """Insere alunos de exemplo. Ignorado se UID já existir."""
    alunos = [
        ("Lucas",    "00:A9:39:26", "Rosca Direta",       10),
        ("Maria",    "B3:22:A1:0C", "Agachamento",        12),
        ("Carlos",   "43:B6:49:05", "Desenvolvimento",    8),
        ("Ana",      "FF:12:34:56", "Supino Reto",        15),
        ("Convidado","GUEST:000000","Rosca Direta",        5),
    ]

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    for nome, uid, exercicio, reps in alunos:
        cursor.execute("""
            INSERT OR IGNORE INTO alunos (nome, uid_rfid, exercicio, repeticoes)
            VALUES (?, ?, ?, ?)
        """, (nome, uid, exercicio, reps))

    conn.commit()
    conn.close()
    print(f"[DB] {len(alunos)} alunos inseridos (duplicatas ignoradas).")


def listar_alunos():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, nome, uid_rfid, exercicio, repeticoes FROM alunos")
    rows = cursor.fetchall()
    conn.close()

    print("\n[DB] Alunos cadastrados:")
    print(f"{'ID':<4} {'Nome':<12} {'UID RFID':<20} {'Exercício':<20} {'Reps':<5}")
    print("-" * 65)
    for row in rows:
        print(f"{row[0]:<4} {row[1]:<12} {row[2]:<20} {row[3]:<20} {row[4]:<5}")


if __name__ == "__main__":
    criar_banco()
    popular_alunos()
    listar_alunos()
    print(f"\n[DB] Banco criado em: {DB_PATH}")
