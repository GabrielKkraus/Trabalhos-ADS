#!/usr/bin/env python3
"""
Script responsável por executar automaticamente o experimento no IMUNES.

O objetivo é medir o comportamento do TCP sob diferentes condições
de congestionamento utilizando planejamento fatorial 2².

Fatores do experimento:

A → Algoritmo TCP
    - reno
    - cubic

B → Tráfego UDP de fundo
    - 800 Mbps
    - 900 Mbps

Número de repetições:
    8

Fluxos utilizados no experimento:

Fluxo principal (medição):
    pc1 → pc2  (TCP)

Tráfego de fundo:
    pc3 → pc4  (UDP)

Ambos compartilham o link entre os roteadores,
gerando competição por largura de banda.
"""

import subprocess
import time
import csv
import os
from datetime import datetime

# ===============================
# CONFIGURAÇÕES DO EXPERIMENTO
# ===============================

REPETICOES = 8
DURACAO_IPERF = 20

TCP_ALGS = ["reno", "cubic"]
BG_TRAFFIC = [800, 900]

# Nós da topologia IMUNES
PC1 = "pc1"
PC2 = "pc2"
PC3 = "pc3"
PC4 = "pc4"

# IPs usados
PC2_IP = "10.0.2.10"
PC4_IP = "10.0.2.30"

RESULT_DIR = "resultados_imunes"
CSV_FILE = os.path.join(RESULT_DIR, "resultados.csv")

os.makedirs(RESULT_DIR, exist_ok=True)


# ===============================
# EXECUTAR COMANDO
# ===============================

def run(cmd):
    """Executa um comando no shell e retorna a saída."""
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout


# ===============================
# EXECUTAR COMANDO NO NÓ DO IMUNES
# ===============================

def himage(node, command):
    """
    Executa um comando dentro de um nó da topologia IMUNES.

    Exemplo:
        himage("pc1", "iperf ...")
    """
    return run(f"sudo himage {node} {command}")


# ===============================
# CONFIGURAR ALGORITMO TCP
# ===============================

def set_tcp_alg(alg):
    """
    Configura o algoritmo TCP usado no pc1.

    Isso altera como o TCP reage a congestionamento.
    """
    print(f"\nConfigurando algoritmo TCP: {alg}")

    run(f"sudo sysctl -w net.ipv4.tcp_congestion_control={alg}")


# ===============================
# INICIAR SERVIDOR TCP
# ===============================

def start_tcp_server():
    """
    Inicia o servidor iperf TCP no pc2.
    """
    himage(PC2, "pkill iperf || true")
    himage(PC2, "nohup iperf -s -p 5001 >/tmp/iperf_tcp.log 2>&1 &")


# ===============================
# TRÁFEGO UDP DE FUNDO
# ===============================

def start_udp_background(rate):
    """
    Gera tráfego UDP de fundo entre pc3 e pc4.

    Isso cria congestionamento no link entre os roteadores.
    """

    print(f"Gerando tráfego UDP de fundo: {rate} Mbps")

    # servidor UDP
    himage(PC4, "pkill iperf || true")
    himage(PC4, "nohup iperf -u -s -p 6001 >/tmp/iperf_udp.log 2>&1 &")

    # cliente UDP
    himage(
        PC3,
        f"nohup iperf -u -c {PC4_IP} -p 6001 -b {rate}M -t {DURACAO_IPERF} >/dev/null 2>&1 &"
    )


# ===============================
# EXECUTAR TESTE TCP
# ===============================

def run_tcp_test():
    """
    Executa o iperf TCP entre pc1 e pc2.

    Retorna a vazão média medida.
    """

    output = himage(
        PC1,
        f"iperf -c {PC2_IP} -p 5001 -t {DURACAO_IPERF}"
    )

    for line in output.splitlines():
        if "Mbits/sec" in line and "sec" in line:
            try:
                return float(line.split()[-2])
            except:
                pass

    return 0


# ===============================
# SALVAR RESULTADOS
# ===============================

def salvar_csv(linha):
    """
    Salva uma linha de resultado no arquivo CSV.
    """

    header = [
        "timestamp",
        "rep",
        "alg",
        "bg_mbps",
        "iperf_avg_mbps"
    ]

    file_exists = os.path.isfile(CSV_FILE)

    with open(CSV_FILE, "a", newline="") as f:
        writer = csv.writer(f)

        if not file_exists:
            writer.writerow(header)

        writer.writerow(linha)


# ===============================
# LOOP PRINCIPAL DO EXPERIMENTO
# ===============================

def main():

    print("\n===== INICIANDO EXPERIMENTO =====")

    for alg in TCP_ALGS:

        set_tcp_alg(alg)

        for bg in BG_TRAFFIC:

            for rep in range(1, REPETICOES + 1):

                print(f"\nRUN alg={alg} bg_udp={bg} Mbps rep={rep}")

                start_tcp_server()

                start_udp_background(bg)

                time.sleep(2)

                throughput = run_tcp_test()

                salvar_csv([
                    datetime.now().isoformat(),
                    rep,
                    alg,
                    bg,
                    throughput
                ])

                time.sleep(2)

    print("\nExperimento finalizado.")


if __name__ == "__main__":
    main()