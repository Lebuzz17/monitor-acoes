"""Cliente LLM agnostico de provedor, com controle de cota do plano gratis.

Responsabilidades:
  - respeitar tokens/minuto (janela deslizante) e tokens/dia por modelo;
  - registrar todo consumo em `llm_usage`;
  - cota diaria separada para o chat do CIO;
  - reserva diaria que SO o modo crise pode usar;
  - rodizio entre modelos grandes quando um estoura a cota.

O provedor e injetavel (`cliente`): o padrao e o Groq; para migrar para o
Claude depois, basta passar outro objeto com o mesmo metodo `completar`.
"""

import logging
import os
import time
from datetime import datetime
from typing import Callable, Protocol
from zoneinfo import ZoneInfo

from fundo import config, db

logger = logging.getLogger(__name__)

PRIORIDADES = ("normal", "chat", "crise")


class SemCota(Exception):
    """Nenhum modelo tem cota para esta chamada agora."""


class RespostaVazia(Exception):
    """O modelo consumiu tokens mas nao devolveu texto (ex.: raciocinio esgotou max_tokens)."""


class Resposta:
    def __init__(self, texto: str, modelo: str, tokens_in: int, tokens_out: int):
        self.texto = texto
        self.modelo = modelo
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out


class Cliente(Protocol):
    def completar(self, modelo: str, mensagens: list[dict], max_tokens: int,
                  temperatura: float) -> Resposta: ...


class ClienteGroq:
    """Adaptador fino do SDK do Groq (importado so quando usado)."""

    def __init__(self, api_key: str | None = None):
        from groq import Groq
        self._c = Groq(api_key=api_key or os.getenv("GROQ_API_KEY"))

    def completar(self, modelo, mensagens, max_tokens, temperatura):
        r = self._c.chat.completions.create(
            model=modelo, messages=mensagens, max_tokens=max_tokens, temperature=temperatura
        )
        u = r.usage
        return Resposta(r.choices[0].message.content or "", modelo,
                        getattr(u, "prompt_tokens", 0), getattr(u, "completion_tokens", 0))

    def listar_modelos(self) -> list[str]:
        return sorted(m.id for m in self._c.models.list().data)


def estimar_tokens(mensagens: list[dict]) -> int:
    """Estimativa grosseira (~3,5 caracteres por token em portugues)."""
    return int(sum(len(m.get("content") or "") for m in mensagens) / 3.5) + 8 * len(mensagens)


class LLM:
    def __init__(self, con=None, cliente: Cliente | None = None,
                 relogio: Callable[[], float] = time.time,
                 dormir: Callable[[float], None] = time.sleep):
        self.con = con or db.inicializar()
        self._cliente = cliente
        self._relogio = relogio
        self._dormir = dormir
        self._janela: dict[str, list[tuple[float, int]]] = {}  # modelo -> [(ts, tokens)]
        self._reqs: dict[str, list[float]] = {}                 # modelo -> [ts] (limite por minuto)

    @property
    def cliente(self) -> Cliente:
        if self._cliente is None:
            self._cliente = ClienteGroq()
        return self._cliente

    # ---- contabilidade ----------------------------------------------------
    def _dia(self) -> str:
        return datetime.fromtimestamp(self._relogio(), ZoneInfo(config.TIMEZONE)).strftime("%Y-%m-%d")

    def _usado_hoje(self, modelo: str | None = None, prioridade: str | None = None) -> int:
        q = "SELECT COALESCE(SUM(tokens_in + tokens_out), 0) FROM llm_usage WHERE dia = ? AND ok = 1"
        args: list = [self._dia()]
        if modelo:
            q += " AND modelo = ?"; args.append(modelo)
        if prioridade:
            q += " AND prioridade = ?"; args.append(prioridade)
        return self.con.execute(q, args).fetchone()[0]

    def _requisicoes_hoje(self, modelo: str) -> int:
        return self.con.execute(
            "SELECT COUNT(*) FROM llm_usage WHERE dia = ? AND modelo = ?", (self._dia(), modelo)
        ).fetchone()[0]

    def _limites(self, modelo: str) -> tuple[int, int, int]:
        tpm, rpd, tpd = config.LIMITES.get(modelo, config.LIMITE_PADRAO)
        m = config.MARGEM_SEGURANCA
        return int(tpm * m), int(rpd * m), int(tpd * m)

    def _tpm_usado(self, modelo: str) -> int:
        agora = self._relogio()
        j = [(t, n) for t, n in self._janela.get(modelo, []) if agora - t < 60]
        self._janela[modelo] = j
        return sum(n for _, n in j)

    def _tem_cota(self, modelo: str, tokens: int, prioridade: str) -> bool:
        tpm, rpd, tpd = self._limites(modelo)
        if self._requisicoes_hoje(modelo) >= rpd:
            return False
        reserva = 0 if prioridade == "crise" else config.RESERVA_CRISE_DIA
        if self._usado_hoje(modelo) + tokens > tpd - reserva:
            return False
        if prioridade == "chat" and self._usado_hoje(prioridade="chat") + tokens > config.COTA_CHAT_DIA:
            return False
        return True

    def cota_restante(self, modelo: str) -> int:
        return max(0, self._limites(modelo)[2] - self._usado_hoje(modelo))

    def _esperar_tpm(self, modelo: str, tokens: int) -> None:
        tpm = self._limites(modelo)[0]
        if tokens > tpm:
            raise SemCota(f"chamada de ~{tokens} tokens excede o limite por minuto ({tpm}) de {modelo}")
        rpm = int(config.RPM.get(modelo, config.RPM_PADRAO) * config.MARGEM_SEGURANCA)
        while True:
            agora = self._relogio()
            self._reqs[modelo] = [t for t in self._reqs.get(modelo, []) if agora - t < 60]
            if self._tpm_usado(modelo) + tokens <= tpm and len(self._reqs[modelo]) < rpm:
                break
            self._dormir(5)
        self._reqs[modelo].append(self._relogio())

    def _registrar(self, modelo, tarefa, prioridade, tin, tout, ok=1, erro=None):
        self.con.execute(
            "INSERT INTO llm_usage (dia, modelo, tarefa, prioridade, tokens_in, tokens_out, ok, erro) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (self._dia(), modelo, tarefa, prioridade, tin, tout, ok, erro),
        )
        self.con.commit()

    # ---- chamada ----------------------------------------------------------
    def chamar(self, tarefa: str, mensagens: list[dict], *, tamanho: str = "grande",
               prioridade: str = "normal", max_tokens: int = 800,
               temperatura: float = 0.2) -> Resposta:
        """`tamanho`: 'triagem' (8B) ou 'grande' (rodizio dos modelos grandes)."""
        if prioridade not in PRIORIDADES:
            raise ValueError(f"prioridade invalida: {prioridade}")
        entrada = estimar_tokens(mensagens)
        if entrada > config.MAX_TOKENS_ENTRADA:
            raise ValueError(f"entrada de ~{entrada} tokens passa do teto de {config.MAX_TOKENS_ENTRADA}; resuma antes")
        total = entrada + max_tokens
        candidatos = ([config.MODELOS["triagem"]] if tamanho == "triagem"
                      else list(config.MODELOS_GRANDES_RODIZIO))
        ultimo_erro: Exception | None = None
        for modelo in candidatos:
            if not self._tem_cota(modelo, total, prioridade):
                continue
            self._esperar_tpm(modelo, total)
            try:
                r = self.cliente.completar(modelo, mensagens, max_tokens, temperatura)
            except Exception as exc:  # limite do provedor, rede etc.
                logger.warning("LLM %s falhou (%s): %s", modelo, tarefa, exc)
                self._registrar(modelo, tarefa, prioridade, 0, 0, ok=0, erro=str(exc)[:300])
                ultimo_erro = exc
                continue
            self._janela.setdefault(modelo, []).append((self._relogio(), r.tokens_in + r.tokens_out))
            if not (r.texto or "").strip():
                # tokens foram gastos (conta na cota), mas nao ha resposta util
                self._registrar(modelo, tarefa, prioridade, r.tokens_in, r.tokens_out, ok=1,
                                erro="resposta vazia")
                raise RespostaVazia(f"{modelo} nao devolveu texto em '{tarefa}' (usou {r.tokens_out} "
                                    f"tokens de saida); aumente max_tokens ou reduza a tarefa")
            self._registrar(modelo, tarefa, prioridade, r.tokens_in, r.tokens_out)
            return r
        if ultimo_erro:
            raise SemCota(f"todos os modelos falharam para '{tarefa}': {ultimo_erro}")
        raise SemCota(f"sem cota para '{tarefa}' (prioridade {prioridade}) em {candidatos}")
