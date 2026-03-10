#!/usr/bin/env python3
"""
Script de análise dos resultados do planejamento fatorial 2^2.

Entrada:
    resultados_imunes/resultados.csv

Saídas:
    sumários estatísticos
    gráficos com IC95
"""

from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.stats import t


CSV_PATH = Path("resultados_imunes/resultados.csv")

OUT_DIR = Path("resultados_imunes")

FIG_DIR = OUT_DIR / "figuras"

FIG_DIR.mkdir(parents=True, exist_ok=True)


# =========================================================
# SUMÁRIO DE UMA VARIÁVEL
# =========================================================

def summarize_response(df, y):

    g = df.groupby(["alg", "bg_mbps"])[y]

    n = g.count()
    mean = g.mean()
    sd = g.std(ddof=1)

    se = sd / np.sqrt(n)

    tcrit = t.ppf(0.975, n - 1)

    ci = tcrit * se

    out = pd.DataFrame({

        "alg": mean.index.get_level_values(0),

        "bg_mbps": mean.index.get_level_values(1),

        "n": n.values,

        "mean": mean.values,

        "sd": sd.values,

        "ci95_half": ci.values,

        "ci95_low": (mean - ci).values,

        "ci95_high": (mean + ci).values,

    })

    return out


# =========================================================
# EFEITOS DO PLANEJAMENTO
# =========================================================

def factorial_effects(df, y):

    cell = df.groupby(["alg", "bg_mbps"])[y].mean().reset_index()

    cell["xA"] = cell["alg"].map({"reno": -1, "cubic": 1})

    cell["xB"] = cell["bg_mbps"].map({800: -1, 900: 1})

    cell["xAB"] = cell["xA"] * cell["xB"]

    b0 = cell[y].mean()

    bA = (cell["xA"] * cell[y]).sum() / 4

    bB = (cell["xB"] * cell[y]).sum() / 4

    bAB = (cell["xAB"] * cell[y]).sum() / 4

    return {

        "effect_A": 2 * bA,

        "effect_B": 2 * bB,

        "effect_AB": 2 * bAB

    }


# =========================================================
# GRÁFICOS
# =========================================================

def plot_means(summary, y_label, title, file):

    algs = sorted(summary.alg.unique())

    loads = sorted(summary.bg_mbps.unique())

    x = np.arange(len(loads))

    fig, ax = plt.subplots()

    for alg in algs:

        sub = summary[summary.alg == alg].sort_values("bg_mbps")

        ax.errorbar(

            x,

            sub.mean,

            yerr=sub.ci95_half,

            marker="o",

            label=alg

        )

    ax.set_xticks(x)

    ax.set_xticklabels([f"{l} Mbps" for l in loads])

    ax.set_xlabel("Carga UDP de fundo")

    ax.set_ylabel(y_label)

    ax.set_title(title)

    ax.legend()

    fig.savefig(file, dpi=200)

    plt.close()


# =========================================================
# MAIN
# =========================================================

def main():

    df = pd.read_csv(CSV_PATH)

    sum_thr = summarize_response(df, "iperf_avg_mbps")

    sum_ret = summarize_response(df, "retrans_rate")

    plot_means(

        sum_thr,

        "Vazão média (Mbps)",

        "Throughput TCP",

        FIG_DIR / "throughput.png"

    )

    plot_means(

        sum_ret,

        "Taxa de retransmissão",

        "Retransmissões TCP",

        FIG_DIR / "retrans.png"

    )

    sum_thr.to_csv(OUT_DIR / "sumario_throughput.csv", index=False)

    sum_ret.to_csv(OUT_DIR / "sumario_retrans.csv", index=False)

    eff_thr = factorial_effects(df, "iperf_avg_mbps")

    eff_ret = factorial_effects(df, "retrans_rate")

    pd.DataFrame([

        {"y": "throughput", **eff_thr},

        {"y": "retrans", **eff_ret}

    ]).to_csv(OUT_DIR / "efeitos.csv", index=False)

    print("Análise concluída.")


if __name__ == "__main__":
    main()