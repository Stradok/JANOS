"""Learned routing: when to follow the LLM's triage and when to override it.

For every request the LLM suggests which agent should start and whether to plan
first (10 possible actions). This module learns, from rewards, where that
suggestion is wrong.

It is a small deep Q-network for a one-step decision (a contextual bandit):

  features   hashed words and word pairs of the request, the task type, and
             which action the LLM suggested. No vocabulary file, no embedding
             model, numpy only.
  Q-network  522 → 64 (tanh) → 10. Predicts the reward of each action.
  choice     argmax of Q plus a fixed trust bonus on the LLM's suggestion, so an
             untrained network follows the LLM, and overrides it only once it
             predicts a gain larger than the bonus.
  optimism   every action starts predicted at the best reward (PRIOR = 1). An
             untried action is never ranked below a tried one just for lack of
             data; alternatives are tried only once the LLM's choice scores below
             1 - TRUST on that kind of task. Starting at zero made it stop looking
             after one mediocre result; starting at a "typical" 0.7 made every
             action that had scored well look better than untried ones everywhere.
  learning   every outcome goes into a replay buffer; each update trains on a
             minibatch drawn from it (Adam, squared error on the taken action).
  exploring  with probability epsilon a random allowed action is tried. Callers
             pick epsilon: low while a person is waiting, higher in autonomous
             mode, where a wrong try costs nobody anything.

REINFORCE was tried first and rejected: with a strong prior on the suggestion it
rarely tried the alternatives, and learned the right override on only some
random seeds. Q-learning with replay learns off-policy from every outcome.
"""

from __future__ import annotations

import fcntl
import os
import re
import tempfile
import zlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np

AGENTS = ("researcher", "analyst", "operator", "engineer", "scribe")
MODES = ("simple", "complex")
ACTIONS = [(a, m) for a in AGENTS for m in MODES]
N_HASH = 512
N_ACT = len(ACTIONS)
DIM = N_HASH + N_ACT
HIDDEN = 64
TRUST = 0.15          # predicted reward gain needed before overriding the LLM
PRIOR = 1.0           # untried actions start at the best reward (optimism under uncertainty)
REPLAY = 2000         # most recent outcomes kept for training
BATCH, STEPS = 32, 4  # minibatch size and gradient steps per new outcome


@dataclass
class Decision:
    features: np.ndarray
    action: int
    prob: float       # probability of this action under the exploring policy
    suggested: int
    agent: str
    mode: str


def reward(score: float, seconds: float) -> float:
    """Answer quality minus a small, capped latency cost.

    The cap (0.1, reached at 50 s) keeps slowness alone from outweighing the
    TRUST margin: uncapped, a correct 60 s plan scored below a mediocre 5 s
    guess, and the policy learned to skip planning on the tasks that need it.
    """
    return float(np.clip(score - min(0.1, 0.002 * seconds), -1.0, 1.0))


class Policy:
    def __init__(self, path: Path, *, lr: float = 0.01, seed: int | None = None):
        self.path = Path(path)
        self.lr = lr
        self.rng = np.random.default_rng(seed)
        self.params = {
            "W1": self.rng.normal(0, 1 / np.sqrt(DIM), (HIDDEN, DIM)),
            "b1": np.zeros(HIDDEN),
            "W2": self.rng.normal(0, 0.01, (N_ACT, HIDDEN)),   # Q ≈ PRIOR everywhere: the LLM leads at first
            "b2": np.full(N_ACT, PRIOR),
        }
        self._m = {k: np.zeros_like(v) for k, v in self.params.items()}
        self._v = {k: np.zeros_like(v) for k, v in self.params.items()}
        self._t = 0
        self.X = np.zeros((0, DIM), np.float32)
        self.A = np.zeros(0, np.int64)
        self.R = np.zeros(0, np.float32)
        self.K = np.zeros(0, "U32")          # episode id per sample, so a rating can relabel it
        self.updates = self.overrides = 0
        self._mtime = 0.0
        self._sync()

    def _sync(self) -> None:
        """Reload if another process (server, voice, autonomous run) saved since we last looked."""
        try:
            mtime = self.path.stat().st_mtime
        except FileNotFoundError:
            return
        if mtime == self._mtime:
            return
        with np.load(self.path) as d:
            for k in self.params:
                self.params[k] = d[k]
                if f"m_{k}" in d:
                    self._m[k], self._v[k] = d[f"m_{k}"], d[f"v_{k}"]
            self.X, self.A, self.R = d["X"], d["A"], d["R"]
            self.K = d["K"] if "K" in d else np.full(len(self.R), "", "U32")
            self.updates, self.overrides = int(d["updates"]), int(d["overrides"])
            self._t = int(d["t"]) if "t" in d else 0
        self._mtime = mtime

    def _locked(self):
        """An exclusive lock on a sidecar file, held across reload → train → save."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path.with_suffix(".lock"), "w")
        fcntl.flock(fh, fcntl.LOCK_EX)
        return fh

    # ------------------------------------------------------------ inference

    @staticmethod
    def _suggested(agent: str, mode: str) -> int:
        agent = agent if agent in AGENTS else "researcher"
        mode = mode if mode in MODES else "simple"
        return ACTIONS.index((agent, mode))

    def features(self, task: str, task_type: str, suggested_agent: str,
                 suggested_mode: str) -> np.ndarray:
        words = re.findall(r"\w+", task.lower())
        toks = words + [f"{a} {b}" for a, b in zip(words, words[1:])] + ["type=" + task_type]
        h = np.zeros(N_HASH)
        for t in toks:                                  # crc32: stable across runs, unlike hash()
            h[zlib.crc32(t.encode()) % N_HASH] += 1.0
        h /= np.linalg.norm(h) or 1.0
        onehot = np.zeros(N_ACT)
        onehot[self._suggested(suggested_agent, suggested_mode)] = 1.0
        return np.concatenate([h, onehot]).astype(np.float32)

    def q(self, x: np.ndarray) -> np.ndarray:
        p = self.params
        return p["W2"] @ np.tanh(p["W1"] @ x.astype(np.float64) + p["b1"]) + p["b2"]

    def choose(self, task: str, task_type: str, suggested_agent: str, suggested_mode: str,
               *, allowed: set[str] | None = None, explore: float = 0.0) -> Decision:
        self._sync()
        x = self.features(task, task_type, suggested_agent, suggested_mode)
        sug = self._suggested(suggested_agent, suggested_mode)
        ok = np.array([a in allowed for a, _ in ACTIONS]) if allowed else np.ones(N_ACT, bool)
        if not ok.any():
            ok[:] = True
        score = self.q(x)
        score[sug] += TRUST
        score[~ok] = -np.inf
        greedy = int(np.argmax(score))
        n_ok = int(ok.sum())
        a = int(self.rng.choice(np.flatnonzero(ok))) if self.rng.random() < explore else greedy
        prob = (1 - explore) * (a == greedy) + explore / n_ok
        return Decision(x, a, float(prob), sug, *ACTIONS[a])

    # -------------------------------------------------------------- learning

    def learn(self, decision: Decision, reward: float, key: str = "") -> None:
        """Record one outcome and train on it. Saves, under a lock, when the policy has a file."""
        with self._locked():
            self._sync()
            self.X = np.vstack([self.X, decision.features[None]])[-REPLAY:]
            self.A = np.append(self.A, decision.action)[-REPLAY:]
            self.R = np.append(self.R, np.float32(reward))[-REPLAY:]
            self.K = np.append(self.K, key[:32])[-REPLAY:]
            self._train(len(self.R) - 1)
            self.updates += 1
            self.overrides += int(decision.action != decision.suggested)
            self._save()

    def relabel(self, key: str, reward: float) -> bool:
        """Replace the reward of an earlier outcome, e.g. when a human rates it.

        Appending a second sample instead left two contradicting rewards for
        one decision, and every repeat click added another.
        """
        if not key:
            return False
        with self._locked():
            self._sync()
            hits = np.flatnonzero(self.K == key[:32])
            if not len(hits):
                return False
            self.R[hits] = np.float32(reward)
            self._train(int(hits[-1]))
            self._save()
        return True

    def _train(self, newest: int) -> None:
        n = len(self.R)
        for _ in range(STEPS):
            idx = self.rng.choice(n, size=min(BATCH, n), replace=False)
            idx[0] = newest                             # always include the sample that just changed
            self._step(self.X[idx].astype(np.float64), self.A[idx], self.R[idx].astype(np.float64))

    def _step(self, X: np.ndarray, A: np.ndarray, R: np.ndarray) -> None:
        p = self.params
        H = np.tanh(X @ p["W1"].T + p["b1"])            # (B, HIDDEN)
        Q = H @ p["W2"].T + p["b2"]                     # (B, N_ACT)
        rows = np.arange(len(A))
        gQ = np.zeros_like(Q)
        gQ[rows, A] = (Q[rows, A] - R) / len(A)         # d(mean squared error)/dQ, taken action only
        gH = (gQ @ p["W2"]) * (1 - H * H)
        grads = {"W2": gQ.T @ H, "b2": gQ.sum(0), "W1": gH.T @ X, "b1": gH.sum(0)}
        self._t += 1
        for k, g in grads.items():                      # Adam
            self._m[k] = 0.9 * self._m[k] + 0.1 * g
            self._v[k] = 0.999 * self._v[k] + 0.001 * g * g
            mh = self._m[k] / (1 - 0.9 ** self._t)
            vh = self._v[k] / (1 - 0.999 ** self._t)
            p[k] -= self.lr * mh / (np.sqrt(vh) + 1e-8)

    # ----------------------------------------------------------- persistence

    def save(self) -> None:
        with self._locked():
            self._save()

    def _save(self) -> None:
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        with os.fdopen(fd, "wb") as f:
            np.savez(f, **self.params, X=self.X, A=self.A, R=self.R, K=self.K,
                     updates=self.updates, overrides=self.overrides, t=self._t,
                     **{f"m_{k}": v for k, v in self._m.items()},
                     **{f"v_{k}": v for k, v in self._v.items()})
        os.replace(tmp, self.path)
        self._mtime = self.path.stat().st_mtime

    def stats(self) -> dict:
        n = max(self.updates, 1)
        recent = self.R[-100:]
        return {"updates": self.updates, "replay": int(len(self.R)),
                "recent_reward": float(recent.mean()) if len(recent) else 0.0,
                "override_rate": round(self.overrides / n, 3)}
