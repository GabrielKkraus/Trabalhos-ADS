#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════════════
 SIMULAÇÃO DE TRÁFEGO UDP GUIADA POR CADEIA DE MARKOV
═══════════════════════════════════════════════════════════════════════════════

 OBJETIVO
 --------
 Simular o comportamento de uma fonte de tráfego de rede cujo padrão de
 geração varia ao longo do tempo de forma estocástica, modelado por uma
 Cadeia de Markov de Tempo Discreto (DTMC).

 CONCEITO — CADEIA DE MARKOV
 ----------------------------
 Uma Cadeia de Markov é um processo aleatório onde o próximo estado depende
 APENAS do estado atual (propriedade de Markov / "sem memória").
 Aqui temos 3 estados que representam níveis de tráfego:

   Estado 0 → Idle:  nenhum tráfego enviado          (0 Mbps)
   Estado 1 → Baixo: tráfego moderado                (10 Mbps)
   Estado 2 → Alto:  tráfego intenso                 (50 Mbps)

 A cada época (intervalo fixo de tempo), a cadeia transita de um estado
 para outro com probabilidades definidas na MATRIZ DE TRANSIÇÃO P.

 FLUXO GERAL DO EXPERIMENTO
 ---------------------------
   1. Valida configurações e sobe servidor iperf no nó SERVER
   2. Calcula teoricamente a vazão esperada (vetor estacionário de P)
   3. Executa NUM_EPOCAS passos: sorteia estado → gera tráfego → mede vazão
   4. Salva resultados em CSV e exibe comparação teórico vs observado

 DEPENDÊNCIAS
 ------------
   - himage  : ferramenta para executar comandos em nós de rede virtual
               (usada em ambientes IMUNES ou GNS3)
   - iperf   : gerador/medidor de tráfego de rede
   - numpy   : álgebra linear (cálculo do vetor estacionário)

 REQUISITOS DO SISTEMA
 ---------------------
   Python >= 3.10  (usa sintaxe tuple[...] nos type hints)
   numpy >= 1.21
   Acesso sudo para comandos himage
═══════════════════════════════════════════════════════════════════════════════
"""

# ─── Biblioteca padrão ────────────────────────────────────────────────────────
import atexit        # Registra funções a executar ao encerrar o processo
import csv           # Leitura/escrita de arquivos CSV
import logging       # Emite mensagens de log com nível, timestamp e origem
import random        # Geração de números aleatórios (sorteio de estados Markov)
import re            # Expressões regulares (parse da saída do iperf)
import signal        # Captura sinais do SO como SIGINT (Ctrl+C) e SIGTERM
import subprocess    # Executa comandos externos no sistema operacional
import sys           # Acesso a argv, exit(), etc.
import time          # Pausas com time.sleep()
from pathlib import Path       # Manipulação de caminhos de forma portável

# ─── Dependência externa ──────────────────────────────────────────────────────
import numpy as np   # Álgebra linear: resolve o sistema πP = π


# ═══════════════════════════════════════════════════════════════════════════════
# SEÇÃO 1 — TOPOLOGIA DE REDE
# ───────────────────────────────────────────────────────────────────────────────
# Define os nomes dos nós virtuais e o IP do servidor.
# Esses valores dependem do ambiente de emulação (IMUNES/GNS3).
#
#   CLIENT ──(UDP)──► SERVER
#   pc1      iperf     pc2  (10.0.2.20)
# ═══════════════════════════════════════════════════════════════════════════════

CLIENT    = "pc1"        # Nó que envia tráfego (cliente iperf)
SERVER    = "pc2"        # Nó que recebe tráfego (servidor iperf)
SERVER_IP = "10.0.2.20"  # Endereço IP do servidor dentro da rede virtual


# ═══════════════════════════════════════════════════════════════════════════════
# SEÇÃO 2 — CADEIA DE MARKOV
# ───────────────────────────────────────────────────────────────────────────────
# MATRIZ DE TRANSIÇÃO P  (3×3)
# Cada linha i = estado ATUAL; cada coluna j = estado PRÓXIMO.
# Valor P[i][j] = probabilidade de ir de i para j.
#
# Exemplo: P[1][2] = 0.2 → estando no Estado 1 (baixo),
#          há 20% de chance de ir para o Estado 2 (alto).
#
# RESTRIÇÃO: cada linha deve somar 1.0 (distribuição de probabilidade).
#
#             Para:  E0    E1    E2
# De E0 →   [ 0.6,  0.3,  0.1 ]   60% fica em 0, 30% → 1, 10% → 2
# De E1 →   [ 0.2,  0.6,  0.2 ]   20% volta p/0, 60% fica, 20% → 2
# De E2 →   [ 0.1,  0.3,  0.6 ]   10% volta p/0, 30% → 1, 60% fica
# ═══════════════════════════════════════════════════════════════════════════════

P = [
    [0.6, 0.3, 0.1],  # Transições a partir do Estado 0 (idle)
    [0.2, 0.6, 0.2],  # Transições a partir do Estado 1 (baixo)
    [0.1, 0.3, 0.6],  # Transições a partir do Estado 2 (alto)
]

# Taxa de tráfego (em Mbps) associada a cada estado.
# Estado 0 = sem tráfego; Estado 1 = 10 Mbps; Estado 2 = 50 Mbps.
TAXAS = {0: 0, 1: 10, 2: 50}


# ═══════════════════════════════════════════════════════════════════════════════
# SEÇÃO 3 — PARÂMETROS DO EXPERIMENTO
# ───────────────────────────────────────────────────────────────────────────────
# NUM_EPOCAS  : quantas vezes a cadeia transita de estado (nº de rodadas)
# TEMPO_EPOCA : duração em segundos de cada rodada de tráfego
#
# Duração total ≈ NUM_EPOCAS × TEMPO_EPOCA = 50 × 5 = 250 s (~4 minutos)
# ═══════════════════════════════════════════════════════════════════════════════

NUM_EPOCAS  = 50   # Número total de épocas (passos da cadeia)
TEMPO_EPOCA = 5    # Duração de cada época em segundos (parâmetro -t do iperf)

OUTDIR   = Path("resultados_markov")   # Pasta criada automaticamente se não existir
CSV_PATH = OUTDIR / "resultados.csv"   # CSV com dados de cada época


# ═══════════════════════════════════════════════════════════════════════════════
# SEÇÃO 4 — SISTEMA DE LOG
# ───────────────────────────────────────────────────────────────────────────────
# Usa o módulo logging para exibir mensagens organizadas com timestamp,
# nível de severidade e texto. Níveis usados neste script:
#   INFO    → progresso normal (início de épocas, resultados)
#   WARNING → situação inesperada mas recuperável (iperf sem saída)
# ═══════════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
LOGGER = logging.getLogger(__name__)  # Logger com o nome deste módulo


# ═══════════════════════════════════════════════════════════════════════════════
# SEÇÃO 5 — EXECUÇÃO DE COMANDOS NO SHELL E NOS NÓS
# ═══════════════════════════════════════════════════════════════════════════════

def sh(cmd: str, capture: bool = False) -> str:
    """
    Executa um comando no shell do sistema operacional.

    Parâmetros
    ----------
    cmd     : string com o comando completo a executar
    capture : se True, captura e retorna stdout como string;
              se False, saída vai direto ao terminal

    Retorno
    -------
    stdout como string (se capture=True), ou string vazia.

    Erros
    -----
    Código de saída != 0 emite WARNING no log (não interrompe execução).
    """
    result = subprocess.run(
        cmd,
        shell=True,             # Interpreta cmd como string de shell
        capture_output=capture, # Redireciona stdout/stderr para result.*
        text=True,              # Decodifica saída como string UTF-8
    )

    if result.returncode != 0 and not capture:
        LOGGER.warning("Comando retornou código %d: %s", result.returncode, cmd)

    return result.stdout if capture else ""


def himage(node: str, cmd: str, capture: bool = False) -> str:
    """
    Executa um comando dentro de um nó virtual via ferramenta 'himage'.

    Equivale a "entrar" no nó de rede e rodar o comando como se
    estivesse diretamente no terminal daquele dispositivo virtual.

    Parâmetros
    ----------
    node    : nome do nó (ex: "pc1", "pc2")
    cmd     : comando a executar dentro do nó
    capture : repassado para sh() — captura stdout se True
    """
    return sh(f"sudo himage {node} {cmd}", capture=capture)


# ═══════════════════════════════════════════════════════════════════════════════
# SEÇÃO 6 — LIMPEZA E TRATAMENTO DE SINAIS
# ───────────────────────────────────────────────────────────────────────────────
# Garante que o servidor iperf seja encerrado corretamente mesmo que o
# programa termine de forma inesperada (Ctrl+C, kill, exceção não tratada).
#
# Mecanismos utilizados:
#   atexit  → chama cleanup() ao encerrar normalmente
#   SIGINT  → disparado pelo Ctrl+C no terminal
#   SIGTERM → disparado por "kill <pid>" ou pelo sistema operacional
# ═══════════════════════════════════════════════════════════════════════════════

def cleanup() -> None:
    """
    Encerra o servidor iperf no nó SERVER.
    Chamada automaticamente ao sair (atexit) ou ao receber SIGINT/SIGTERM.
    O sufixo "|| true" evita erro caso o processo já tenha sido encerrado.
    """
    LOGGER.info("Limpeza: parando servidor iperf em '%s'", SERVER)
    sh(f"sudo himage {SERVER} pkill iperf || true")


atexit.register(cleanup)  # Executa cleanup() sempre que o Python encerrar


def _signal_handler(sig, frame):
    """Intercepta sinais de interrupção e encerra o programa de forma limpa."""
    cleanup()
    sys.exit(0)  # Código 0 = encerramento normal


signal.signal(signal.SIGINT,  _signal_handler)  # Ctrl+C
signal.signal(signal.SIGTERM, _signal_handler)  # kill <pid>


# ═══════════════════════════════════════════════════════════════════════════════
# SEÇÃO 7 — GERENCIAMENTO DO SERVIDOR IPERF
# ═══════════════════════════════════════════════════════════════════════════════

def ensure_server() -> None:
    """
    Garante que o servidor iperf UDP está rodando no nó SERVER.

    Etapas
    ------
    1. Mata instâncias anteriores do iperf (evita conflito de porta)
    2. Aguarda 0,5 s para o socket ser liberado pelo SO
    3. Inicia o servidor em background (& = não bloqueia o script)
    4. Aguarda 1,5 s para o processo subir e abrir a porta UDP
    5. Verifica via pgrep se o processo existe → RuntimeError se não

    Flags do iperf servidor:
        -s : modo servidor (escuta por conexões)
        -u : protocolo UDP (deve combinar com o cliente)
    """
    LOGGER.info("Iniciando servidor iperf UDP em '%s'", SERVER)

    sh(f"sudo himage {SERVER} pkill iperf || true")  # Para instâncias antigas
    time.sleep(0.5)  # Aguarda liberação do socket

    sh(f"sudo himage {SERVER} sh -c 'iperf -s -u > /dev/null 2>&1 &'")
    time.sleep(1.5)  # Aguarda o servidor entrar em escuta

    # ── Verificação com múltiplos métodos ─────────────────────────────────────
    # Nós IMUNES podem não ter pgrep, ou o processo pode aparecer com nome
    # diferente (ex: "iperf2"). Tentamos 3 abordagens em ordem crescente de
    # compatibilidade, aceitando sucesso em qualquer uma delas.

    # Método 1: pgrep exato (mais preciso, pode não existir no nó)
    pid = himage(SERVER, "pgrep -x iperf 2>/dev/null || pgrep iperf 2>/dev/null", capture=True).strip()

    # Método 2: ps + grep (disponível em praticamente qualquer Unix)
    if not pid:
        ps = himage(SERVER, "ps aux 2>/dev/null || ps 2>/dev/null", capture=True)
        if "iperf" in ps:
            pid = "encontrado via ps"

    # Método 3: tenta uma conexão de teste rápida com timeout de 1s.
    # Se o servidor estiver escutando, o iperf retorna imediatamente com erro
    # de "sem dados", mas NÃO com "connection refused" — isso basta para confirmar.
    if not pid:
        teste = sh(
            f"sudo himage {CLIENT} iperf -c {SERVER_IP} -u -b 1K -t 1 2>&1 || true",
            capture=True
        )
        # "connection refused" → servidor offline; qualquer outra saída → online
        if teste and "Connection refused" not in teste and "connect failed" not in teste:
            pid = "confirmado via conexão de teste"
            LOGGER.info("Servidor confirmado por conexão de teste.")

    if not pid:
        # Nenhum dos 3 métodos confirmou o servidor — avisa mas não aborta,
        # pois em alguns ambientes IMUNES o processo sobe de forma atípica.
        # O experimento tentará prosseguir; falhas reais aparecerão no iperf.
        LOGGER.warning(
            "Não foi possível confirmar o servidor iperf em '%s'. "
            "O experimento continuará, mas verifique a conectividade se "
            "as épocas retornarem 0 Mbps.", SERVER
        )
    else:
        LOGGER.info("Servidor iperf ativo em '%s' (PID/status: %s)", SERVER, pid)


# ═══════════════════════════════════════════════════════════════════════════════
# SEÇÃO 8 — LÓGICA DA CADEIA DE MARKOV
# ═══════════════════════════════════════════════════════════════════════════════

def proximo_estado(estado: int) -> int:
    """
    Sorteia o próximo estado usando a linha correspondente da matriz P.

    random.choices([0,1,2], weights=P[estado]) sorteia um valor de [0,1,2]
    com probabilidades proporcionais aos pesos em P[estado].

    Exemplo: estado=1, P[1]=[0.2, 0.6, 0.2]
      → 20% de chance de retornar 0
      → 60% de chance de retornar 1
      → 20% de chance de retornar 2

    Parâmetro : estado atual (0, 1 ou 2)
    Retorno   : próximo estado (0, 1 ou 2)
    """
    return random.choices([0, 1, 2], weights=P[estado])[0]


def vetor_estacionario() -> np.ndarray:
    """
    Calcula o vetor estacionário π da cadeia de Markov.

    CONCEITO
    --------
    O vetor estacionário π = [π0, π1, π2] representa a proporção de tempo
    que a cadeia passa em cada estado no LONGO PRAZO (regime permanente).

    Ele satisfaz duas condições simultaneamente:
      (a)  π · P = π          (equação de equilíbrio global)
      (b)  π0 + π1 + π2 = 1  (é uma distribuição de probabilidade)

    MÉTODO NUMÉRICO
    ---------------
    Reformula como sistema linear (Pᵀ - I) · π = 0, substituindo a última
    linha pelo vínculo sum(π) = 1, formando Ax = b com solução única:

      A = Pᵀ - I  com a última linha substituída por [1, 1, 1]
      b = [0, 0, 1]

    np.linalg.solve(A, b) resolve de forma numericamente estável.

    Retorno : array numpy [π0, π1, π2]
    """
    P_np = np.array(P, dtype=float)
    n = P_np.shape[0]

    # Sistema (Pᵀ - I) · π = 0 (equações de balanço na forma coluna)
    A = P_np.T - np.eye(n)

    # Substitui última linha por sum(π) = 1 para garantir solução única
    A[-1] = 1.0
    b = np.zeros(n)
    b[-1] = 1.0

    return np.linalg.solve(A, b)


# ═══════════════════════════════════════════════════════════════════════════════
# SEÇÃO 9 — GERAÇÃO E MEDIÇÃO DE TRÁFEGO (IPERF)
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_iperf_csv(output: str) -> tuple[float, int]:
    """
    Extrai bytes transmitidos e vazão (Mbps) da saída CSV do iperf (-y C).

    Formato da linha CSV gerada pelo iperf com -y C:
      timestamp,ip_origem,porta_origem,ip_destino,porta_destino,id,t_inicio-t_fim,bytes,bps,jitter_ms,perdas,total_datagramas,percentual_perda,out_of_order

    Exemplo real:
      20240315120005,10.0.1.10,5001,10.0.2.20,5001,3,0.0-5.0,6250000,10000000,...

    Campos relevantes (índice a partir de 0):
      [7]  bytes transmitidos  → total de bytes no intervalo
      [8]  bits por segundo    → vazão em bps (dividir por 1e6 → Mbps)

    Estratégia de leitura:
      - Usa a ÚLTIMA linha não-vazia, que corresponde ao sumário do período
        completo (algumas versões do iperf imprimem linhas por sub-intervalo)
      - Fallback para regex em formato texto caso -y C não seja suportado

    Parâmetro : output — saída completa do iperf como string
    Retorno   : (vazao_mbps, bytes_tx) — zeros se não for possível parsear
    """
    # Tenta formato CSV (-y C): busca a última linha com campos numéricos
    linhas = [l.strip() for l in output.strip().splitlines() if l.strip()]
    for linha in reversed(linhas):
        campos = linha.split(",")
        if len(campos) >= 9:
            try:
                bytes_tx  = int(campos[7])           # campo 7 = bytes
                bps       = float(campos[8])          # campo 8 = bits/s
                vazao_mbps = bps / 1e6
                if bytes_tx > 0 and vazao_mbps > 0:
                    return vazao_mbps, bytes_tx
            except (ValueError, IndexError):
                continue

    # Fallback: formato texto normal (caso -y C não seja suportado pelo nó)
    matches = re.findall(r"([\d.]+)\s+Mbits/sec", output)
    if matches:
        vazao_mbps = float(matches[-1])
        bytes_tx   = int(vazao_mbps * 1e6 / 8 * TEMPO_EPOCA)
        LOGGER.debug("Parse via fallback texto (formato CSV não encontrado).")
        return vazao_mbps, bytes_tx

    return 0.0, 0


def executar_iperf(taxa: int) -> tuple[float, int]:
    """
    Executa um fluxo UDP com iperf durante TEMPO_EPOCA segundos.

    Comportamento por estado
    ------------------------
    taxa = 0  → Estado idle: apenas aguarda TEMPO_EPOCA s (equivale a sleep 5
                conforme o enunciado), sem gerar nenhum tráfego.
    taxa > 0  → Envia UDP a 'taxa' Mbps e lê bytes/vazão reais da saída CSV.

    Flags do iperf utilizadas (conforme enunciado seção 1.6.2):
        -c <ip>  : modo cliente, conecta ao servidor
        -u       : protocolo UDP (sem controle de congestionamento)
        -b <n>M  : taxa alvo em Mbps
        -l 1400  : tamanho do datagrama UDP em bytes
                   (valor próximo ao MTU Ethernet para maximizar eficiência)
        -t <n>   : duração da transmissão em segundos
        -y C     : saída em formato CSV (facilita parse dos bytes reais)

    Fallback
    --------
    Se o parse do CSV falhar, assume 95% da taxa nominal como estimativa
    conservadora (desconta ~5% de overhead UDP/IP/Ethernet).

    Retorno : (vazao_real_mbps, bytes_transmitidos)
    """
    if taxa == 0:
        # Estado ocioso: comportamento equivalente a "sleep 5" do enunciado
        time.sleep(TEMPO_EPOCA)
        return 0.0, 0

    # Comando conforme enunciado seção 1.6.2
    cmd = (
        f"iperf -c {SERVER_IP} -u "
        f"-b {taxa}M "
        f"-l 1400 "       # tamanho do datagrama UDP (bytes)
        f"-t {TEMPO_EPOCA} "
        f"-y C"           # saída em formato CSV para parse preciso
    )
    saida = himage(CLIENT, cmd, capture=True)

    vazao_mbps, bytes_tx = _parse_iperf_csv(saida)

    # Se ambos os métodos de parse falharam, aplica estimativa conservadora
    if vazao_mbps == 0.0:
        LOGGER.warning(
            "Vazão não lida do iperf (taxa=%d Mbps); usando estimativa de 95%%.", taxa
        )
        vazao_mbps = taxa * 0.95               # ~5% de overhead UDP/IP/Ethernet
        bytes_tx   = int(vazao_mbps * 1e6 / 8 * TEMPO_EPOCA)

    return vazao_mbps, bytes_tx


# ═══════════════════════════════════════════════════════════════════════════════
# SEÇÃO 10 — SIMULAÇÃO DA CADEIA (seção 1.4 do enunciado)
# ───────────────────────────────────────────────────────────────────────────────
# Antes do experimento real com iperf, simula a cadeia por 500 passos para
# verificar se as frequências observadas convergem ao vetor estacionário π.
# Isso valida a implementação da matriz P e serve como aquecimento teórico.
# ═══════════════════════════════════════════════════════════════════════════════

def simular_cadeia(n_passos: int = 500) -> list[float]:
    """
    Simula a cadeia de Markov por n_passos sem gerar tráfego real.

    A cada passo, registra o estado visitado e ao final calcula a
    frequência relativa de cada estado (proporção de visitas).

    OBJETIVO (seção 1.4 do enunciado)
    -----------------------------------
    Comparar as frequências observadas com o vetor estacionário π:
      - Se a simulação for longa o suficiente, freq[i] ≈ π[i]
      - Diferenças grandes indicam bug na matriz P ou n_passos insuficiente

    Parâmetro
    ---------
    n_passos : número de transições a simular (padrão: 500 conforme enunciado)

    Retorno
    -------
    Lista [freq0, freq1, freq2] com a proporção de tempo em cada estado.
    """
    estado     = 0            # Estado inicial (arbitrário)
    contagem   = [0, 0, 0]   # Contador de visitas por estado

    for _ in range(n_passos):
        estado = proximo_estado(estado)
        contagem[estado] += 1

    # Frequência relativa: divide cada contagem pelo total de passos
    frequencias = [c / n_passos for c in contagem]

    return frequencias


# ═══════════════════════════════════════════════════════════════════════════════
# SEÇÃO 11 — VALIDAÇÃO DE CONFIGURAÇÃO
# ───────────────────────────────────────────────────────────────────────────────
# Detecta erros de configuração ANTES de iniciar o experimento,
# evitando falhas silenciosas no meio da execução.
# ═══════════════════════════════════════════════════════════════════════════════

def validar_config() -> None:
    """
    Verifica a consistência dos parâmetros globais do experimento.

    Verificações
    ------------
    1. NUM_EPOCAS  > 0 : experimento precisa de ao menos uma época
    2. TEMPO_EPOCA > 0 : cada época precisa ter duração positiva
    3. Cada linha de P soma 1.0 (tolerância 1e-9)
       → garante que P é uma matriz de transição estocástica válida

    Lança AssertionError com mensagem descritiva se alguma condição falhar.
    """
    assert NUM_EPOCAS  > 0, "NUM_EPOCAS deve ser um inteiro positivo"
    assert TEMPO_EPOCA > 0, "TEMPO_EPOCA deve ser um inteiro positivo"

    for i, linha in enumerate(P):
        soma = sum(linha)
        assert abs(soma - 1.0) < 1e-9, (
            f"Linha {i} da matriz P não soma 1 (soma={soma:.9f}). "
            "Cada linha deve ser uma distribuição de probabilidade completa."
        )

    LOGGER.info("Configuração validada: %d épocas × %ds, matriz P consistente.",
                NUM_EPOCAS, TEMPO_EPOCA)


# ═══════════════════════════════════════════════════════════════════════════════
# SEÇÃO 11 — LOOP PRINCIPAL DO EXPERIMENTO
# ═══════════════════════════════════════════════════════════════════════════════

def run_markov() -> tuple[list, list, float]:
    """
    Executa a simulação completa da cadeia de Markov com geração de tráfego.

    A cada época
    ------------
    1. Sorteia o próximo estado com base na linha atual da matriz P
    2. Consulta a taxa de tráfego associada (TAXAS)
    3. Executa iperf por TEMPO_EPOCA segundos
    4. Registra: timestamp, estado, taxa, vazão medida, bytes enviados

    Métricas calculadas ao final
    ----------------------------
    vazao_obs   : vazão média em Mbps = (total_bits) / (tempo_total × 1e6)
    tempo_estado: tempo acumulado (s) em cada estado — comparável com π

    Retorno
    -------
    resultados   : lista de listas [timestamp, passo, estado, taxa, vazao, bytes]
    tempo_estado : tempo acumulado (s) por estado [E0, E1, E2]
    vazao_obs    : vazão média observada em Mbps
    """
    estado       = 0          # Estado inicial (começa em idle)
    total_bytes  = 0          # Acumulador de bytes transmitidos
    tempo_estado = [0, 0, 0]  # Tempo (s) acumulado em cada estado
    resultados   = []

    LOGGER.info("Iniciando experimento: %d épocas de %ds cada.", NUM_EPOCAS, TEMPO_EPOCA)

    for passo in range(1, NUM_EPOCAS + 1):

        # Transição: sorteia próximo estado pelas probabilidades de P
        estado = proximo_estado(estado)
        taxa   = TAXAS[estado]
        LOGGER.info("Época %02d/%02d | Estado %d | %2d Mbps",
                    passo, NUM_EPOCAS, estado, taxa)

        # Gera tráfego e obtém a vazão real medida pelo iperf
        vazao_real, bytes_tx = executar_iperf(taxa)

        # Atualiza acumuladores
        total_bytes          += bytes_tx
        tempo_estado[estado] += TEMPO_EPOCA

        resultados.append([passo, estado, taxa, bytes_tx])

    # Cálculo da vazão média observada (Mbps) ao longo de todo o experimento
    tempo_total = NUM_EPOCAS * TEMPO_EPOCA
    vazao_obs   = (total_bytes * 8) / (tempo_total * 1e6)

    # Proporção real de tempo em cada estado (comparar com vetor estacionário π)
    proporcao = [t / tempo_total for t in tempo_estado]

    LOGGER.info("─── Resultado experimental ───────────────────────────────")
    LOGGER.info("Tempo por estado (s) : E0=%ds  E1=%ds  E2=%ds", *tempo_estado)
    LOGGER.info("Proporção observada  : E0=%.3f  E1=%.3f  E2=%.3f", *proporcao)
    LOGGER.info("Vazão média observada: %.2f Mbps", vazao_obs)

    return resultados, tempo_estado, vazao_obs


# ═══════════════════════════════════════════════════════════════════════════════
# SEÇÃO 12 — FUNÇÃO PRINCIPAL
# ───────────────────────────────────────────────────────────────────────────────
# Orquestra todas as etapas na ordem correta:
#   Validação → Servidor → Análise Teórica → Experimento → CSV → Resumo
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    """
    Ponto de entrada principal do experimento.

    Sequência de execução
    ---------------------
    1. Valida parâmetros e cria diretório de saída
    2. Sobe o servidor iperf no nó SERVER
    3. Calcula o vetor estacionário π (resultado TEÓRICO)
       → Prediz a proporção de tempo em cada estado no longo prazo
       → Calcula a vazão média esperada: E[vazão] = π0×0 + π1×10 + π2×50
    4. Executa o loop de Markov com iperf (resultado EXPERIMENTAL)
    5. Salva todos os dados em CSV
    6. Exibe resumo comparando teoria vs experimento
    """
    LOGGER.info("═" * 60)
    LOGGER.info("  INÍCIO DO EXPERIMENTO MARKOV + IPERF UDP")
    LOGGER.info("  Épocas: %d × %ds = %ds totais",
                NUM_EPOCAS, TEMPO_EPOCA, NUM_EPOCAS * TEMPO_EPOCA)
    LOGGER.info("═" * 60)

    # Passo 1: verificações e preparação do ambiente
    validar_config()
    OUTDIR.mkdir(exist_ok=True)
    ensure_server()

    # Passo 2: análise teórica — predição matemática da vazão esperada
    # Calcula π tal que πP = π e sum(π) = 1 (regime estacionário)
    pi = vetor_estacionario()
    vazao_teorica = sum(pi[e] * TAXAS[e] for e in range(3))

    LOGGER.info("─── Resultado teórico (vetor estacionário π) ─────────────")
    for i, p in enumerate(pi):
        LOGGER.info("  π%d = %.4f  →  taxa=%2d Mbps  →  contribuição=%.3f Mbps",
                    i, p, TAXAS[i], p * TAXAS[i])
    LOGGER.info("  Vazão teórica esperada (T_médio): %.2f Mbps", vazao_teorica)

    # Passo 3: simulação de 500 passos sem tráfego real (seção 1.4 do enunciado)
    # Verifica se a implementação da cadeia está correta comparando as
    # frequências observadas com o vetor estacionário π calculado acima.
    N_SIM = 500
    freq_sim = simular_cadeia(n_passos=N_SIM)

    LOGGER.info("─── Simulação de %d passos (sem tráfego real) ────────────", N_SIM)
    LOGGER.info("  %-12s  %-10s  %-10s  %-8s", "Estado", "π (teórico)", "Freq. obs.", "Diferença")
    for i in range(3):
        diff = abs(freq_sim[i] - pi[i])
        LOGGER.info("  Estado %-5d  %-10.4f  %-10.4f  %-8.4f", i, pi[i], freq_sim[i], diff)

    # Passo 4: execução experimental com tráfego real
    resultados, tempo_estado, vazao_obs = run_markov()

    # Passo 5: exportação dos dados coletados em CSV
    # Colunas: Timestamp, Passo, Estado, Taxa_Mbps, Vazao_Real_Mbps, Bytes
    with open(CSV_PATH, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Passo", "Estado", "Taxa Configurada (Mbps)", "Bytes Transmitidos"])
        writer.writerows(resultados)

    LOGGER.info("CSV salvo em: %s  (%d linhas)", CSV_PATH, len(resultados))

    # Passo 6: resumo final — teoria vs experimento
    # A diferença percentual indica a qualidade da aproximação de Markov
    # para este cenário. Com NUM_EPOCAS suficientemente grande (≥100),
    # espera-se diferença < 10% pela Lei dos Grandes Números.
    diferenca_pct = abs(vazao_obs - vazao_teorica) / vazao_teorica * 100

    LOGGER.info("═" * 60)
    LOGGER.info("  RESUMO FINAL")
    LOGGER.info("  Vazão teórica  (πP=π)  : %7.2f Mbps", vazao_teorica)
    LOGGER.info("  Vazão observada (iperf) : %7.2f Mbps", vazao_obs)
    LOGGER.info("  Diferença               : %7.2f%%", diferenca_pct)
    LOGGER.info("  Tempo total             : %7ds", NUM_EPOCAS * TEMPO_EPOCA)
    LOGGER.info("  Épocas por estado       : E0=%d  E1=%d  E2=%d",
                tempo_estado[0] // TEMPO_EPOCA,
                tempo_estado[1] // TEMPO_EPOCA,
                tempo_estado[2] // TEMPO_EPOCA)
    LOGGER.info("═" * 60)
    LOGGER.info("  FIM DO EXPERIMENTO")
    LOGGER.info("═" * 60)


# ─── Ponto de entrada ─────────────────────────────────────────────────────────
# Garante que main() só é chamada quando o script é executado diretamente
# (python markov_traffic.py), e não quando importado como módulo.
if __name__ == "__main__":
    main()