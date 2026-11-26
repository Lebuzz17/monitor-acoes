# Política de Investimento do Fundo — RASCUNHO v0

> **Status: rascunho, NÃO vigente.** Todos os números abaixo são *propostas* para o dono aprovar ou
> alterar. Enquanto não houver aprovação registrada (data + versão no fim deste arquivo), o motor de
> execução não opera. Tudo é **paper/testnet**; dinheiro real só existe atrás de uma chave que só o
> dono liga, numa fase futura.

## 1. Objetivo e natureza

- Experimento pessoal de gestão de carteira de **longo prazo**, operado por agentes de IA, com o dono
  como único aprovador. Gestão de recursos próprios; não é oferta a terceiros.
- Objetivo: superar o benchmark ao longo de ciclos completos (3+ anos), com risco controlado e processo
  auditável. Aprender é um objetivo explícito (relatório traz a "aula da semana").

## 2. Capital e benchmark *(decisão do dono)*

- **Capital inicial simulado:** R$ 100.000 *(proposta; o dono define)*.
- **Benchmark proposto:** 50% Ibovespa · 25% S&P 500 (em BRL) · 15% CDI · 10% Bitcoin (em BRL).
  Alternativa mais simples: 70% Ibovespa / 30% CDI. *O dono escolhe.*
- Moeda-base: BRL. Caixa rende CDI no paper.

## 3. Universo

| Classe | Permitido | Observação |
|---|---|---|
| Ações Brasil (B3) | sim | só empresas com modelo `aprovado` |
| Ações EUA | sim | via paper; mesma regra |
| ETFs de índice líquidos | sim | principalmente no bolsão tático e para caixa estratégico |
| Cripto | BTC e ETH; satélites até 2% | testnet da Binance Spot |
| Derivativos, alavancagem, venda a descoberto | **não** | |

## 4. Limites *(propostas)*

| Item | Limite |
|---|---|
| Peso máximo por ativo | 10% |
| Peso máximo por setor | 25% |
| Exposição cambial (USD + cripto) | até 40% |
| Cripto total | até 10% |
| Reserva de caixa ("munição" para crise) | mínimo 10% |
| Giro anual máximo (livro de longo prazo) | 50% |
| Permanência mínima por posição | 90 dias (exceto critério de saída da tese) |
| Liquidez | posição zerável em até 5 dias a 20% do volume médio diário |
| **Expected Shortfall 97,5% (1 dia)** | alerta a 1,8% do patrimônio, limite 2,5% |
| Drawdown | −10% = revisão obrigatória pelo comitê; −15% = redução de risco |

## 5. Como se compra e vende (longo prazo, execução diária em código)

- Cada ativo só é operado se tiver **valuation `aprovado` pelo dono** (empresa + preço-alvo).
- O comitê (sexta) define **faixas de preço** a partir do alvo e do cenário bear:
  compra (≤ alvo base × (1 − margem de segurança)), reforço, redução e saída.
- Margem de segurança proposta: **20%**. Compras em **2 a 4 parcelas** ao longo de dias.
- Um motor em código executa quando o preço cruza a faixa. **Nenhuma IA decide no dia a dia.**
- Saída total só com critério de saída da tese atingido **e** confirmação do CIO.
- Mudança de alvo > 10% exige aprovação do dono. Sem alvo aprovado, o motor **não compra**.

## 6. Modo crise (tático) *(propostas)*

- **Gatilhos objetivos, em código** (basta um): circuit breaker B3 (Ibovespa −10%) ou EUA (S&P −7%,
  nível 1); queda de índice ≥ 5% em 1 pregão ou ≥ 12% em 3; VIX ≥ 40; BTC ≥ −15% em 24h.
  Limiares calibrados no histórico para disparar no máximo 1 a 3 vezes por ano.
- **Bolsão tático:** até 15% do fundo, com risco medido à parte, usando a reserva de caixa.
- Entrada em 3 parcelas (gatilho; mais X% de queda; após N pregões). Saída: realização em +Y% ou
  prazo máximo de ~20 pregões (depois, o CIO decide se migra para o longo prazo, desde que haja tese
  e modelo aprovado).
- O Agente Tático decide dentro do bolsão **sem aprovação prévia**; os limites rígidos e o *kill switch*
  continuam valendo. Aviso imediato no Telegram; revisão do CIO em até 24h; desliga sozinho após
  5 pregões ou quando a volatilidade normaliza.

## 7. Aprovação pelo dono

- Nível inicial **0**: o dono revisa empresa e preço-alvo (premissa por premissa), até domingo.
  Sem resposta, **nada acontece**. Níveis 1–3 liberam autonomia gradualmente, mudando em `config`.
- **Nunca desliga:** empresa de nível de dificuldade acima do já aprovado e mudança de alvo > 10%.
- Kill switch: o dono pode parar todas as operações a qualquer momento.

## 8. Governança e controle

- Separação de funções: quem propõe não aprova; quem aprova não executa.
- Toda premissa cita fonte e trecho; premissa sem fonte é recusada pelo código.
- Diário de decisões com probabilidade esperada; revisão trimestral de calibração (Brier).
- A IA nunca é testada no passado (viés de conhecimento); só o histórico do paper vale.
- Relatórios: semanal (≤ 2 páginas + mensagem de 5–8 linhas) e carta mensal (≤ 4 páginas).

## 9. Fora de escopo

- Operar dinheiro real, usar chaves de corretoras reais, ou receber recursos de terceiros.
- Recomendação de investimento: os agentes produzem análise; a decisão e a responsabilidade são do dono.

---

**Aprovação:** _(pendente)_ — versão v0, sem data.
