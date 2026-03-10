#!/usr/bin/env python3
"""
Automação do experimento no IMUNES.

Planejamento fatorial 2^2:

Fator A: algoritmo TCP
    - reno
    - cubic

Fator B: carga UDP de fundo
    - 800 Mbps
    - 900 Mbps

Cada tratamento é repetido várias vezes.

Medições coletadas:
    - vazão média TCP (iperf)
    - número de retransmissões TCP (tcpdump + tshark)

Saída:
    resultados_imunes/resultados.csv
"""

import csv
import subprocess
import re
from pathlib import Path
from datetime import datetime


# =========================================================
# CONFIGURAÇÕES DO EXPERIMENTO
# =========================================================

PC1 = "pc1"
PC2 = "pc2"

PC1_IP = "10.0.0.20"
PC2_IP = "10.0.2.20"

TCP_PORT = 5001

DURACAO_IPERF = 30

ALGS = ["reno", "cubic"]

UDP_BG = [800, 900]

REPS = 8

OUTDIR = Path("resultados_imunes")
OUTDIR.mkdir(exist_ok=True)

CSV_PATH = OUTDIR / "resultados.csv"


# =========================================================
# EXECUÇÃO DE COMANDOS
# =========================================================

def sh(cmd: str) -> str:
    """Executa comando no host."""
    print("$", cmd)

    p = subprocess.run(
        cmd,
        shell=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT
    )

    if p.returncode != 0:
        raise RuntimeError(p.stdout)

    return p.stdout


def himage(node: str, cmd: str) -> str:
    """Executa comando dentro de um nó IMUNES."""
    return sh(f"sudo himage {node} {cmd}")


# =========================================================
# CONFIGURAÇÃO TCP
# =========================================================

def set_tcp_alg(alg):
    """Define algoritmo TCP no pc1."""
    himage(PC1, f"sysctl -w net.ipv4.tcp_congestion_control={alg}")


# =========================================================
# SERVIDOR IPERF
# =========================================================

def start_iperf_server():

    himage(PC2, "pkill iperf || true")

    himage(PC2, "nohup iperf -s >/tmp/iperf.log 2>&1 &")


# =========================================================
# GERADOR DE TRÁFEGO UDP
# =========================================================

def start_udp_background(rate):

    himage(PC2, "pkill iperf || true")

    himage(
        PC2,
        f"nohup iperf -u -s -p 6001 >/tmp/iperf_udp.log 2>&1 &"
    )

    himage(
        PC1,
        f"nohup iperf -u -c {PC2_IP} -p 6001 -b {rate}M -t {DURACAO_IPERF} >/dev/null 2>&1 &"
    )


# =========================================================
# PARSE DA SAÍDA DO IPERF
# =========================================================

def parse_iperf(out):

    lines = [l for l in out.splitlines() if "Mbits/sec" in l]

    last = lines[-1]

    parts = last.split()

    for i, p in enumerate(parts):
        if p == "Mbits/sec":
            return float(parts[i - 1])

    raise RuntimeError("não achei taxa")


# =========================================================
# EXECUTA UMA REPETIÇÃO
# =========================================================

def run_one(alg, bg, rep):

    ts = datetime.now().isoformat()

    set_tcp_alg(alg)

    start_udp_background(bg)

    pcap = f"/tmp/cap_{alg}_{bg}_{rep}.pcap"

    himage(
        PC1,
        f"tcpdump -i any tcp and host {PC2_IP} -w {pcap} & echo $! >/tmp/tcpdump.pid"
    )

    out = himage(
        PC1,
        f"iperf -c {PC2_IP} -t {DURACAO_IPERF}"
    )

    vazao = parse_iperf(out)

    himage(
        PC1,
        "kill -INT $(cat /tmp/tcpdump.pid)"
    )

    local_pcap = OUTDIR / f"{alg}_{bg}_{rep}.pcap"

    sh(f"sudo hcp {PC1}:{pcap} {local_pcap}")

    total = int(sh(
        f'tshark -r "{local_pcap}" -Y "tcp.len>0" | wc -l'
    ))

    retrans = int(sh(
        f'tshark -r "{local_pcap}" -Y "tcp.analysis.retransmission" | wc -l'
    ))

    retrans_rate = retrans / total if total else 0

    local_pcap.unlink()

    return {
        "timestamp": ts,
        "rep": rep,
        "alg": alg,
        "bg_mbps": bg,
        "iperf_avg_mbps": vazao,
        "n_dados": total,
        "n_retrans": retrans,
        "retrans_rate": retrans_rate
    }


# =========================================================
# LOOP PRINCIPAL
# =========================================================

def main():

    start_iperf_server()

    write_header = not CSV_PATH.exists()

    with open(CSV_PATH, "a", newline="") as f:

        w = csv.DictWriter(
            f,
            fieldnames=[
                "timestamp",
                "rep",
                "alg",
                "bg_mbps",
                "iperf_avg_mbps",
                "n_dados",
                "n_retrans",
                "retrans_rate"
            ]
        )

        if write_header:
            w.writeheader()

        for alg in ALGS:
            for bg in UDP_BG:
                for rep in range(1, REPS + 1):

                    print(f"\nRUN {alg} bg={bg} rep={rep}")

                    row = run_one(alg, bg, rep)

                    w.writerow(row)

                    f.flush()

    print("CSV salvo em", CSV_PATH)


if __name__ == "__main__":
    main()