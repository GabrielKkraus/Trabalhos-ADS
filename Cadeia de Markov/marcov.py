#!/usr/bin/env python3
# Indica que o script deve ser executado com Python 3 no sistema

import atexit      # Executa funções automaticamente ao encerrar o programa
import csv         # Manipulação de arquivos CSV
import logging     # Sistema de logs (mensagens organizadas no terminal)
import random      # Geração de números aleatórios
import signal      # Captura sinais do sistema (ex: CTRL+C)
import subprocess  # Executar comandos do sistema
import sys         # Interação com o sistema (ex: sair do programa)
import time        # Controle de tempo (sleep)
from pathlib import Path  # Manipulação moderna de caminhos de arquivos

# =========================
# TOPOLOGIA
# =========================

CLIENT = "pc1"        # Nome do nó cliente no ambiente (ex: Mininet/himage)
SERVER = "pc2"        # Nome do nó servidor
SERVER_IP = "10.0.2.20"  # IP do servidor

# =========================
# MARKOV
# =========================

# Matriz de transição da cadeia de Markov
# Cada linha representa o estado atual
# Cada coluna representa a probabilidade de ir para outro estado
P = [
    [0.6, 0.3, 0.1],  # Estado 0 → (0,1,2)
    [0.2, 0.6, 0.2],  # Estado 1 → (0,1,2)
    [0.1, 0.3, 0.6]   # Estado 2 → (0,1,2)
]

# =========================
# PARÂMETROS
# =========================

NUM_EPOCAS = 50     # Quantidade de passos (iterações)
TEMPO_EPOCA = 5     # Tempo de cada passo (segundos)

# Diretório onde os resultados serão salvos
OUTDIR = Path("resultados_markov")
OUTDIR.mkdir(exist_ok=True)  # Cria a pasta se não existir

# Caminho do arquivo CSV
CSV_PATH = OUTDIR / "resultados.csv"

# =========================
# LOGGING
# =========================

# Configuração do sistema de logs
logging.basicConfig(
    level=logging.INFO,  # Mostra mensagens INFO ou superiores
    format="%(asctime)s | %(levelname)s | %(message)s"
)

LOGGER = logging.getLogger()  # Cria o logger principal

# =========================
# EXECUÇÃO DE COMANDOS
# =========================

def sh(cmd):
    """
    Executa um comando no shell do sistema
    """
    subprocess.run(cmd, shell=True)
    return ""

def himage(node, cmd):
    """
    Executa um comando dentro de um nó (ex: pc1, pc2)
    usando o comando 'himage'
    """
    return sh(f"sudo himage {node} {cmd}")

# =========================
# LIMPEZA
# =========================

def cleanup():
    """
    Função chamada ao encerrar o programa
    """
    LOGGER.info("Limpeza final")

# Garante que cleanup será chamado ao sair
atexit.register(cleanup)

def signal_handler(sig, frame):
    """
    Captura CTRL+C e finaliza corretamente
    """
    cleanup()
    sys.exit(0)

# Associa o handler ao sinal SIGINT (CTRL+C)
signal.signal(signal.SIGINT, signal_handler)

# =========================
# MARKOV
# =========================

def proximo_estado(estado):
    """
    Escolhe o próximo estado baseado na matriz de transição P
    """
    return random.choices([0,1,2], weights=P[estado])[0]

# =========================
# IPERF (GERAÇÃO DE TRÁFEGO)
# =========================

def executar_iperf(taxa):
    """
    Executa tráfego UDP com iperf baseado na taxa (Mbps)
    """

    # Se taxa = 0 → não gera tráfego
    if taxa == 0:
        time.sleep(TEMPO_EPOCA)
        return 0

    # Comando iperf
    cmd = f"iperf -c {SERVER_IP} -u -b {taxa}M -t {TEMPO_EPOCA}"

    # Executa no cliente
    himage(CLIENT, cmd)

    # Estimativa de bytes transmitidos:
    # taxa (Mbps) → bits/s → bytes/s → multiplicado pelo tempo
    bytes_tx = taxa * 1_000_000 / 8 * TEMPO_EPOCA

    return int(bytes_tx)

# =========================
# SERVIDOR IPERF
# =========================

def ensure_server():
    """
    Garante que o servidor iperf está rodando
    """

    LOGGER.info("Subindo servidor iperf UDP")

    # Mata instâncias antigas do iperf
    sh(f"sudo himage {SERVER} pkill iperf || true")

    # Inicia servidor em background
    sh(f"sudo himage {SERVER} sh -c 'iperf -s -u > /dev/null 2>&1 &'")

    # Aguarda inicialização
    time.sleep(1)

    LOGGER.info("Servidor iniciado com sucesso")

# =========================
# VETOR ESTACIONÁRIO
# =========================

import numpy as np

def vetor_estacionario():
    """
    Calcula o vetor estacionário da cadeia de Markov
    (π tal que πP = π)
    """

    P_np = np.array(P)

    # Autovalores e autovetores da matriz transposta
    eigvals, eigvecs = np.linalg.eig(P_np.T)

    # Seleciona o autovetor associado ao autovalor 1
    idx = np.argmin(abs(eigvals - 1))

    pi = eigvecs[:, idx].real

    # Normaliza para somar 1
    pi = pi / sum(pi)

    return pi

# =========================
# EXPERIMENTO
# =========================

def run_markov():
    """
    Executa a simulação da cadeia de Markov com geração de tráfego
    """

    estado = 0  # Estado inicial

    total_bytes = 0              # Total transmitido
    tempo_estado = [0,0,0]       # Tempo em cada estado

    resultados = []              # Armazena dados para CSV

    # Loop principal
    for passo in range(1, NUM_EPOCAS+1):

        # Transição de estado
        estado = proximo_estado(estado)

        # Define taxa conforme estado
        if estado == 0:
            taxa = 0
        elif estado == 1:
            taxa = 10
        else:
            taxa = 50

        LOGGER.info(f"Passo {passo} | Estado {estado} | {taxa} Mbps")

        # Executa tráfego
        bytes_tx = executar_iperf(taxa)

        # Atualiza métricas
        total_bytes += bytes_tx
        tempo_estado[estado] += TEMPO_EPOCA

        # Salva resultado
        resultados.append([passo, estado, taxa, bytes_tx])

    # Tempo total do experimento
    tempo_total = NUM_EPOCAS * TEMPO_EPOCA

    # Vazão média observada (Mbps)
    vazao_obs = (total_bytes * 8) / (tempo_total * 1e6)

    LOGGER.info("=== RESULTADO EXPERIMENTAL ===")
    LOGGER.info(f"Tempo por estado: {tempo_estado}")
    LOGGER.info(f"Vazão média observada: {vazao_obs:.2f} Mbps")

    return resultados, tempo_estado, vazao_obs

# =========================
# MAIN
# =========================

def main():
    """
    Função principal
    """

    LOGGER.info("===== INÍCIO =====")

    # Garante servidor ativo
    ensure_server()

    # ===== PARTE TEÓRICA =====
    pi = vetor_estacionario()

    LOGGER.info("=== TEÓRICO ===")
    LOGGER.info(f"π0 = {pi[0]:.4f}")
    LOGGER.info(f"π1 = {pi[1]:.4f}")
    LOGGER.info(f"π2 = {pi[2]:.4f}")

    # Vazão teórica baseada no vetor estacionário
    vazao_teorica = pi[1]*10 + pi[2]*50
    LOGGER.info(f"Vazão teórica: {vazao_teorica:.2f} Mbps")

    # ===== PARTE EXPERIMENTAL =====
    resultados, tempo_estado, vazao_obs = run_markov()

    # ===== SALVAR CSV =====
    with open(CSV_PATH, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Passo", "Estado", "Taxa", "Bytes"])
        writer.writerows(resultados)

    LOGGER.info(f"CSV salvo em {CSV_PATH}")
    LOGGER.info("===== FIM =====")

# Executa o programa
if __name__ == "__main__":
    main()