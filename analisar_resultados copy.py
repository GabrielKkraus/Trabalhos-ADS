#!/usr/bin/env python3
"""
Script responsável por analisar os resultados gerados no CSV.

Ele realiza:

1) Leitura dos resultados
2) Cálculo da média
3) Desvio padrão
4) Intervalo de confiança (95%)
5) Geração de gráficos
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy import stats

CSV_PATH = "resultados_imunes/resultados.csv"


# ===============================
# INTERVALO DE CONFIANÇA
# ===============================

def ic95(data):
    """
    Calcula intervalo de confiança de 95%.
    """

    n = len(data)
    mean = np.mean(data)
    sd = np.std(data, ddof=1)

    t = stats.t.ppf(0.975, n - 1)

    ic = t * sd / np.sqrt(n)

    return mean, ic


# ===============================
# ANÁLISE PRINCIPAL
# ===============================

def main():

    df = pd.read_csv(CSV_PATH)

    resultados = []

    for alg in df.alg.unique():
        for bg in df.bg_mbps.unique():

            subset = df[(df.alg == alg) & (df.bg_mbps == bg)]

            mean, ic = ic95(subset.iperf_avg_mbps)

            resultados.append({
                "alg": alg,
                "bg": bg,
                "mean": mean,
                "ic": ic
            })

    res = pd.DataFrame(resultados)

    print("\nResultados:")
    print(res)

    # ============================
    # GRÁFICO
    # ============================

    plt.figure()

    for alg in res.alg.unique():

        sub = res[res.alg == alg]

        plt.errorbar(
            sub.bg,
            sub.mean,
            yerr=sub.ic,
            marker='o',
            label=alg
        )

    plt.xlabel("Tráfego UDP de fundo (Mbps)")
    plt.ylabel("Throughput TCP (Mbps)")
    plt.title("Impacto do congestionamento no TCP")

    plt.legend()

    plt.grid(True)

    plt.savefig("grafico_throughput.png")

    plt.show()


if __name__ == "__main__":
    main()