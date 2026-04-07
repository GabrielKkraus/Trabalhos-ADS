#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════════════
 GERAÇÃO DE GRÁFICOS — RELATÓRIO CADEIA DE MARKOV
═══════════════════════════════════════════════════════════════════════════════

 Lê o CSV produzido pelo experimento e gera 5 gráficos prontos para relatório:

   Gráfico 1 — Evolução dos estados ao longo das épocas
   Gráfico 2 — Vazão configurada e vazão média por estado
   Gráfico 3 — Bytes transmitidos por época
   Gráfico 4 — Distribuição observada vs vetor estacionário (π)
   Gráfico 5 — Vazão acumulada vs vazão teórica

 Saída: pasta "graficos/" com arquivos .png em alta resolução (300 dpi).

 Uso:
   python3 graficos_markov.py
   python3 graficos_markov.py --csv outro_arquivo.csv
═══════════════════════════════════════════════════════════════════════════════
"""

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURAÇÕES — ajuste aqui se os parâmetros do experimento mudarem
# ═══════════════════════════════════════════════════════════════════════════════

# Matriz de transição (deve ser idêntica à usada no experimento)
P = np.array([
    [0.6, 0.3, 0.1],
    [0.2, 0.6, 0.2],
    [0.1, 0.3, 0.6],
])

TAXAS        = {0: 0, 1: 10, 2: 50}   # Mbps por estado
TEMPO_EPOCA  = 5                        # segundos por época
OUTDIR       = Path("graficos")         # pasta de saída dos PNGs

# Nomes descritivos dos estados para rótulos nos gráficos
NOMES_ESTADO = {0: "E0 — Ocioso (0 Mbps)",
                1: "E1 — Moderado (10 Mbps)",
                2: "E2 — Alto (50 Mbps)"}

# Paleta de cores por estado (acessível — evita vermelho/verde juntos)
CORES_ESTADO = {0: "#5B8DB8", 1: "#F4A261", 2: "#E76F51"}

# Estilo global dos gráficos (aparência limpa para relatório)
plt.rcParams.update({
    "figure.dpi":        150,
    "savefig.dpi":       300,       # alta resolução para impressão
    "font.family":       "DejaVu Sans",
    "font.size":         11,
    "axes.titlesize":    13,
    "axes.titleweight":  "bold",
    "axes.labelsize":    11,
    "axes.spines.top":   False,     # remove borda superior
    "axes.spines.right": False,     # remove borda direita
    "axes.grid":         True,
    "grid.alpha":        0.35,
    "grid.linestyle":    "--",
    "legend.framealpha": 0.8,
    "legend.fontsize":   10,
})

# ═══════════════════════════════════════════════════════════════════════════════
# FUNÇÕES AUXILIARES
# ═══════════════════════════════════════════════════════════════════════════════

def vetor_estacionario(P: np.ndarray) -> np.ndarray:
    """
    Calcula o vetor estacionário π tal que πP = π e sum(π) = 1.
    Usa resolução de sistema linear para estabilidade numérica.
    """
    n = P.shape[0]
    A = (P.T - np.eye(n)).T
    A[-1] = 1.0
    b = np.zeros(n)
    b[-1] = 1.0
    return np.linalg.solve(A, b)


def salvar(fig: plt.Figure, nome: str) -> None:
    """Salva a figura em PNG na pasta de saída e fecha a figura."""
    OUTDIR.mkdir(exist_ok=True)
    caminho = OUTDIR / nome
    fig.savefig(caminho, bbox_inches="tight")
    plt.close(fig)
    print(f"  Salvo: {caminho}")


def carregar_csv(caminho: Path) -> pd.DataFrame:
    """
    Lê o CSV do experimento e garante os tipos corretos.
    Colunas esperadas: Passo, Estado, Taxa Configurada (Mbps), Bytes Transmitidos
    """
    df = pd.read_csv(caminho)

    # Padroniza nomes de colunas (remove espaços extras)
    df.columns = df.columns.str.strip()

    # Garante tipos numéricos
    df["Passo"]   = df["Passo"].astype(int)
    df["Estado"]  = df["Estado"].astype(int)

    # Calcula vazão real por época a partir dos bytes (Mbps)
    # Fórmula: (bytes × 8 bits/byte) / (tempo_época_s × 1_000_000)
    df["Vazao_Mbps"] = (df["Bytes Transmitidos"] * 8) / (TEMPO_EPOCA * 1e6)

    # Vazão acumulada média até cada passo
    # Divide bytes acumulados pelo tempo total decorrido até aquele passo
    df["Bytes_Acum"]  = df["Bytes Transmitidos"].cumsum()
    df["Vazao_Acum"]  = (df["Bytes_Acum"] * 8) / (df["Passo"] * TEMPO_EPOCA * 1e6)

    return df


# ═══════════════════════════════════════════════════════════════════════════════
# GRÁFICO 1 — Evolução dos estados ao longo das épocas
# ───────────────────────────────────────────────────────────────────────────────
# Mostra como a cadeia de Markov transitou entre estados ao longo do tempo.
# Cada segmento colorido representa uma época no estado correspondente.
# ═══════════════════════════════════════════════════════════════════════════════

def grafico_estados(df: pd.DataFrame) -> None:
    """
    Gráfico de degraus coloridos mostrando a sequência de estados visitados.
    O estilo step (degrau) é o mais fiel à natureza discreta da cadeia.
    """
    fig, ax = plt.subplots(figsize=(12, 3.5))

    # Linha de degraus (representa bem o caráter discreto da DTMC)
    ax.step(df["Passo"], df["Estado"], where="post",
            color="#444", linewidth=1.2, alpha=0.6, zorder=2)

    # Faixas coloridas de fundo por estado (facilita leitura visual)
    for estado, cor in CORES_ESTADO.items():
        mask = df["Estado"] == estado
        for passo in df.loc[mask, "Passo"]:
            ax.axvspan(passo - 1, passo, alpha=0.25, color=cor, linewidth=0)

    # Pontos sobre cada época
    for estado, cor in CORES_ESTADO.items():
        mask = df["Estado"] == estado
        ax.scatter(df.loc[mask, "Passo"], df.loc[mask, "Estado"],
                   color=cor, s=30, zorder=3, label=NOMES_ESTADO[estado])

    ax.set_yticks([0, 1, 2])
    ax.set_yticklabels(["0\n(Ocioso)", "1\n(Moderado)", "2\n(Alto)"])
    ax.set_xlabel("Época (passo)")
    ax.set_ylabel("Estado")
    ax.set_title("Gráfico 1 — Evolução dos estados ao longo das épocas")
    ax.set_xlim(0.5, len(df) + 0.5)
    ax.set_ylim(-0.4, 2.4)
    ax.legend(loc="upper right", ncol=3)

    salvar(fig, "g1_evolucao_estados.png")


# ═══════════════════════════════════════════════════════════════════════════════
# GRÁFICO 2 — Vazão por época
# ───────────────────────────────────────────────────────────────────────────────
# Barras coloridas por estado mostram tanto o valor quanto o tipo de cada época.
# ═══════════════════════════════════════════════════════════════════════════════

def grafico_vazao_por_epoca(df: pd.DataFrame) -> None:
    """
    Barras verticais com a vazão medida em cada época.
    Cor de cada barra = estado daquela época.
    """
    fig, ax = plt.subplots(figsize=(12, 4))

    cores_barra = df["Estado"].map(CORES_ESTADO)
    ax.bar(df["Passo"], df["Vazao_Mbps"], color=cores_barra,
           edgecolor="white", linewidth=0.4, width=0.8)

    # Linhas horizontais de referência para cada taxa configurada
    for estado, taxa in TAXAS.items():
        if taxa > 0:
            ax.axhline(taxa, color=CORES_ESTADO[estado],
                       linestyle=":", linewidth=1.2, alpha=0.7,
                       label=f"Taxa E{estado} = {taxa} Mbps")

    # Legenda manual de cores dos estados
    from matplotlib.patches import Patch
    handles = [Patch(color=CORES_ESTADO[e], label=NOMES_ESTADO[e]) for e in range(3)]
    ax.legend(handles=handles, loc="upper right", ncol=1)

    ax.set_xlabel("Época (passo)")
    ax.set_ylabel("Vazão (Mbps)")
    ax.set_title("Gráfico 2 — Vazão medida por época")
    ax.set_xlim(0.5, len(df) + 0.5)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f"))

    salvar(fig, "g2_vazao_por_epoca.png")


# ═══════════════════════════════════════════════════════════════════════════════
# GRÁFICO 3 — Bytes transmitidos por época
# ───────────────────────────────────────────────────────────────────────────────
# Visualiza o volume bruto de dados por época — útil para tabela do relatório.
# ═══════════════════════════════════════════════════════════════════════════════

def grafico_bytes(df: pd.DataFrame) -> None:
    """
    Barras com o total de bytes transmitidos em cada época.
    Épocas ociosas (estado 0) aparecem naturalmente como barras nulas.
    """
    fig, ax = plt.subplots(figsize=(12, 4))

    cores_barra = df["Estado"].map(CORES_ESTADO)
    ax.bar(df["Passo"], df["Bytes Transmitidos"] / 1e6,
           color=cores_barra, edgecolor="white", linewidth=0.4, width=0.8)

    from matplotlib.patches import Patch
    handles = [Patch(color=CORES_ESTADO[e], label=NOMES_ESTADO[e]) for e in range(3)]
    ax.legend(handles=handles, loc="upper right")

    ax.set_xlabel("Época (passo)")
    ax.set_ylabel("Bytes transmitidos (MB)")
    ax.set_title("Gráfico 3 — Bytes transmitidos por época")
    ax.set_xlim(0.5, len(df) + 0.5)

    salvar(fig, "g3_bytes_por_epoca.png")


# ═══════════════════════════════════════════════════════════════════════════════
# GRÁFICO 4 — Distribuição observada vs vetor estacionário π
# ───────────────────────────────────────────────────────────────────────────────
# Comparação central do relatório: frequência real de cada estado vs π teórico.
# ═══════════════════════════════════════════════════════════════════════════════

def grafico_distribuicao(df: pd.DataFrame, pi: np.ndarray) -> None:
    """
    Barras agrupadas: frequência observada (experimental) vs π (teórico).
    Permite avaliar visualmente o quanto a cadeia convergiu ao regime estacionário.
    """
    fig, ax = plt.subplots(figsize=(7, 4.5))

    estados     = [0, 1, 2]
    n_estados   = len(estados)
    freq_obs    = [( df["Estado"] == e ).mean() for e in estados]  # proporção observada
    freq_teo    = list(pi)

    x      = np.arange(n_estados)
    largura = 0.35

    barras_obs = ax.bar(x - largura/2, freq_obs, largura,
                        color=[CORES_ESTADO[e] for e in estados],
                        label="Observado (experimental)", alpha=0.9)
    barras_teo = ax.bar(x + largura/2, freq_teo, largura,
                        color=[CORES_ESTADO[e] for e in estados],
                        label="Teórico (π estacionário)", alpha=0.45,
                        edgecolor=[CORES_ESTADO[e] for e in estados],
                        linewidth=1.5)

    # Rótulos com os valores acima de cada barra
    for barra in barras_obs:
        ax.text(barra.get_x() + barra.get_width()/2,
                barra.get_height() + 0.008,
                f"{barra.get_height():.3f}",
                ha="center", va="bottom", fontsize=9)
    for barra in barras_teo:
        ax.text(barra.get_x() + barra.get_width()/2,
                barra.get_height() + 0.008,
                f"{barra.get_height():.3f}",
                ha="center", va="bottom", fontsize=9, style="italic")

    ax.set_xticks(x)
    ax.set_xticklabels([f"Estado {e}" for e in estados])
    ax.set_ylabel("Proporção de tempo")
    ax.set_ylim(0, max(max(freq_obs), max(freq_teo)) + 0.12)
    ax.set_title("Gráfico 4 — Distribuição observada vs vetor estacionário π")
    ax.legend()

    salvar(fig, "g4_distribuicao_estados.png")


# ═══════════════════════════════════════════════════════════════════════════════
# GRÁFICO 5 — Convergência da vazão acumulada ao valor teórico
# ───────────────────────────────────────────────────────────────────────────────
# Mostra como a vazão média acumulada se aproxima de T_médio à medida que
# o número de épocas aumenta — ilustra a Lei dos Grandes Números na prática.
# ═══════════════════════════════════════════════════════════════════════════════

def grafico_convergencia(df: pd.DataFrame, pi: np.ndarray) -> None:
    """
    Linha da vazão média acumulada vs linha horizontal da vazão teórica.
    Quanto mais épocas, mais a linha experimental se aproxima da teórica.
    """
    fig, ax = plt.subplots(figsize=(10, 4))

    vazao_teorica = sum(pi[e] * TAXAS[e] for e in range(3))

    # Vazão acumulada observada a cada época
    ax.plot(df["Passo"], df["Vazao_Acum"],
            color="#E76F51", linewidth=2, label="Vazão acumulada observada")

    # Linha de referência teórica
    ax.axhline(vazao_teorica, color="#264653", linewidth=1.5,
               linestyle="--", label=f"Vazão teórica T_médio = {vazao_teorica:.2f} Mbps")

    # Faixa de ±10% em torno do valor teórico
    ax.fill_between(df["Passo"],
                    vazao_teorica * 0.90,
                    vazao_teorica * 1.10,
                    alpha=0.10, color="#264653", label="Faixa ±10%")

    # Anota o valor final observado
    val_final = df["Vazao_Acum"].iloc[-1]
    ax.annotate(f"{val_final:.2f} Mbps",
                xy=(df["Passo"].iloc[-1], val_final),
                xytext=(-40, 12), textcoords="offset points",
                fontsize=9, color="#E76F51",
                arrowprops=dict(arrowstyle="->", color="#E76F51", lw=1))

    ax.set_xlabel("Época (passo)")
    ax.set_ylabel("Vazão média acumulada (Mbps)")
    ax.set_title("Gráfico 5 — Convergência da vazão observada ao valor teórico")
    ax.set_xlim(1, len(df))
    ax.legend()

    salvar(fig, "g5_convergencia_vazao.png")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Gera gráficos do experimento Markov+iperf")
    parser.add_argument("--csv", default="resultados_markov/resultados.csv",
                        help="Caminho para o arquivo CSV (padrão: resultados_markov/resultados.csv)")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"Erro: arquivo '{csv_path}' não encontrado.")
        print("Execute primeiro o experimento (markov_traffic.py) ou informe o caminho com --csv.")
        return

    print(f"Lendo dados de: {csv_path}")
    df = carregar_csv(csv_path)
    pi = vetor_estacionario(P)

    print(f"  {len(df)} épocas carregadas.")
    print(f"  Vetor estacionário: π0={pi[0]:.4f}  π1={pi[1]:.4f}  π2={pi[2]:.4f}")
    print(f"  Vazão teórica: {sum(pi[e]*TAXAS[e] for e in range(3)):.2f} Mbps")
    print(f"  Vazão observada: {df['Vazao_Mbps'].mean():.2f} Mbps")
    print("\nGerando gráficos...")

    grafico_estados(df)
    grafico_vazao_por_epoca(df)
    grafico_bytes(df)
    grafico_distribuicao(df, pi)
    grafico_convergencia(df, pi)

    print(f"\nPronto! 5 gráficos salvos em '{OUTDIR}/'")


if __name__ == "__main__":
    main()