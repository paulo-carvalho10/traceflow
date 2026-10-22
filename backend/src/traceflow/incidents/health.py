"""A saúde de cada nó ao longo do tempo: histerese e linha de base.

- **Histerese:** o estado de um nó só muda depois de 3 retratos seguidos pedindo a mudança.
  Um segundo ruim não abre incidente, e um segundo bom no meio de uma falha não fecha. Sem
  isso, o mapa piscaria e a linha do tempo ficaria cheia de "adoeceu, recuperou, adoeceu".
- **Linha de base:** o "normal" do p95 de cada nó, uma média móvel exponencial. Ela só
  aprende enquanto o nó está saudável: se aprendesse durante a falha, a lentidão viraria o
  novo normal e a regra relativa pararia de disparar no meio do incidente.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from traceflow.incidents.rules import HEALTHY, State, Verdict

HYSTERESIS = 3  # retratos seguidos (1 por segundo) para mudar de estado
# A média móvel pesa cada segundo novo em 1/120: o "normal" reflete uns 2 minutos recentes.
BASELINE_ALPHA = 1 / 120
BASELINE_MIN_SAMPLES = 30  # antes de 30 s de observação saudável, a linha de base não vale
BASELINE_MIN_REQUESTS = 20  # um p95 de 3 requisições não ensina o normal


@dataclass
class Baseline:
    value: float | None = None
    samples: int = 0

    def learn(self, observed: float) -> None:
        self.value = observed if self.value is None else self.value + BASELINE_ALPHA * (observed - self.value)
        self.samples += 1

    @property
    def ready(self) -> float | None:
        return self.value if self.samples >= BASELINE_MIN_SAMPLES else None


@dataclass
class NodeHealth:
    verdict: Verdict = HEALTHY  # o estado em vigor, e a regra que o colocou nele
    since: float = 0.0
    streak: int = 0  # retratos seguidos pedindo um estado diferente do atual
    baseline: Baseline = field(default_factory=Baseline)

    @property
    def state(self) -> State:
        return self.verdict.state

    def observe(self, raw: Verdict, now: float, p95_ms: float | None, requests: int) -> bool:
        """Registra a avaliação deste segundo. Devolve True se o estado em vigor mudou.

        Conta os retratos seguidos DIFERENTES do estado atual, seja qual for o estado pedido:
        com o erro oscilando em volta de 25%, a avaliação alterna entre degradado e falhando, e
        contar só pedidos iguais deixaria o nó "saudável" para sempre. Ao mudar, vale o último.
        """
        changed = False
        if raw.state == self.verdict.state:
            self.streak = 0
            self.verdict = raw  # o mesmo estado, com o motivo e o valor de agora
        else:
            self.streak += 1
            if self.streak >= HYSTERESIS:
                self.verdict, self.since, self.streak, changed = raw, now, 0, True
        # Aprende só com o nó saudável E com o segundo saudável: durante os 3 s da histerese o
        # estado em vigor ainda é "saudável", e os valores ruins já entrariam no "normal"
        if (
            self.state == "healthy"
            and raw.state == "healthy"
            and p95_ms is not None
            and requests >= BASELINE_MIN_REQUESTS
        ):
            self.baseline.learn(p95_ms)
        return changed
