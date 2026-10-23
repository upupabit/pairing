"""Stats > Workflow analysis, per Matricxon node (workflow_analysis.py builds the rest of the report).

Every finding compares a node with itself (its usual speed, how often it was reachable) or with the other nodes
running the same model, so a weaker computer is reported once as weaker, not as slow all the time. When one long
prompt read, or an overloaded node, explains a queue and slow replies, that cause is reported, not its symptoms.
An overloaded node is judged on absolute signs (minutes without a first word, writing below 1 tok/s), since a node
that just started has no usual speed yet.
"""

import re
import statistics

from app.schemas.workflow_analysis import Finding, HistoryBucket, NodeBucket, NodeRow
from app.services.workflow_history import CRAWL_TPS

_SUMMED = (
    "polls", "down", "running", "queued", "decode", "slow", "ratio_sum",
    "long_read", "held_polls", "queued_in_read", "slow_in_read", "crawl", "long_wait",
)  # fmt: skip


def node_name(host: str) -> str:
    """ "http://node-2:8420" -> "node-2", like the live view (Matricxon's default port dropped)."""
    return re.sub(r":8420$", "", re.sub(r"^https?://", "", host))


def count_text(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


class NodeFindings:
    MIN_POLLS = 5  # a node needs this many polls before it is judged
    WEAKER = 0.6  # a node below this share of the other nodes' speed on the same model is "weaker"
    EXPLAINED = 0.6  # a symptom is left out when at least this share of it happened during a long read
    HELD_CRIT_SECONDS = 30.0
    STRESS_WAIT_SECONDS = 30.0  # total time replies sat LONG_WAIT_SECONDS or more without a first word
    STRESS_CRAWL_SHARE = 0.3

    def __init__(self, buckets: list[HistoryBucket], poll_seconds: float) -> None:
        self._poll_seconds = poll_seconds
        self.nodes = self._merge(buckets)
        self.findings: list[Finding] = []

    @staticmethod
    def _merge(buckets: list[HistoryBucket]) -> dict[str, NodeBucket]:
        merged: dict[str, NodeBucket] = {}
        for bucket in buckets:
            for host, n in bucket.nodes.items():
                m = merged.setdefault(host, NodeBucket())
                for field in _SUMMED:
                    setattr(m, field, getattr(m, field) + getattr(n, field))
                m.reason = n.reason or m.reason
                m.max_wait = max(m.max_wait, n.max_wait)
                if n.min_tps is not None:
                    m.min_tps = min(m.min_tps or n.min_tps, n.min_tps)
                if n.read_tokens > m.read_tokens:
                    m.read_tokens, m.read_reused, m.read_model = n.read_tokens, n.read_reused, n.read_model
                for model, (total, count) in n.tps_by_model.items():
                    t = m.tps_by_model.setdefault(model, [0.0, 0])
                    t[0], t[1] = t[0] + total, t[1] + count
        return merged

    def rows(self) -> list[NodeRow]:
        """Every node, the ones worth a look first."""
        return sorted((self._row(h, n) for h, n in self.nodes.items()), key=self._attention, reverse=True)

    def _row(self, host: str, n: NodeBucket) -> NodeRow:
        polls = max(n.polls, 1)
        total, count = (sum(v[i] for v in n.tps_by_model.values()) for i in (0, 1))
        return NodeRow(
            host=host,
            seen_seconds=round(n.polls * self._poll_seconds, 1),
            down_share=round(n.down / polls, 3),
            running=round(n.running / polls, 2),
            queued_share=round(n.queued / max(n.running, 1), 3),
            tokens_per_second=round(total / count, 2) if count else None,
            slow_share=round(n.slow / n.decode, 3) if n.decode else 0.0,
            slowness=round(n.ratio_sum / n.decode, 2) if n.decode else None,
        )

    def _attention(self, row: NodeRow) -> tuple[float, float]:
        held = self.nodes[row.host].held_polls / max(self.nodes[row.host].polls, 1)
        return (row.down_share * 3 + held * 3 + row.slow_share * 2 + row.queued_share, row.running)

    def find(self, rows: list[NodeRow]) -> list[Finding]:
        for row in rows:
            n = self.nodes[row.host]
            if n.polls < self.MIN_POLLS:
                continue
            self._reachability(row, n)
            self._long_read(row, n)
            stressed = self._stress(row, n)
            if stressed:
                continue  # its queue and slow replies are what "overloaded" means
            if row.slow_share >= 0.3 and row.slowness and n.slow_in_read < n.slow * self.EXPLAINED:
                level = "crit" if row.slowness >= 2.5 else "warn"
                detail = (
                    f"Writing {row.slowness:.1f}x slower than it usually does, {row.slow_share:.0%} of the time. "
                    "Overloaded, hot, or other programs running."
                )
                self._add(level, f"{node_name(row.host)} is slower than usual", detail, row.host)
            if row.queued_share >= 0.2 and n.queued_in_read < n.queued * self.EXPLAINED:
                detail = (
                    f"{row.queued_share:.0%} of its replies waited for a free model slot. "
                    "Raise Concurrent replies per model, or add a node."
                )
                self._add("warn", f"Replies queue on {node_name(row.host)}", detail, row.host)
        self._weaker_nodes({f.subject for f in self.findings if f.title.endswith("slower than usual")})
        return self.findings

    def _reachability(self, row: NodeRow, n: NodeBucket) -> None:
        down_seconds = round(n.down * self._poll_seconds)
        if row.down_share >= 0.5:
            reason = (n.reason or "no answer").removeprefix(f"{row.host}: ")
            detail = f"Didn't answer for about {down_seconds}s ({row.down_share:.0%} of checks): {reason}"
            self._add("crit", f"{node_name(row.host)} is unreachable", detail, row.host)
        elif row.down_share > 0:
            detail = (
                f"Didn't answer for about {down_seconds}s ({row.down_share:.0%} of checks). "
                "Often a restart; if it repeats, check the node and its network."
            )
            self._add("warn", f"{node_name(row.host)} drops out", detail, row.host)

    def _stress(self, row: NodeRow, n: NodeBucket) -> bool:
        """Matricxon can't keep up on this node: replies sit for a minute or more before their first
        word, or write at a crawl. Reported red whatever the node's usual speed (it may have none)."""
        waited = n.long_wait * self._poll_seconds >= self.STRESS_WAIT_SECONDS
        crawling = n.decode >= self.MIN_POLLS and n.crawl / n.decode >= self.STRESS_CRAWL_SHARE
        if not (waited or crawling):
            return False
        signs = []
        if waited:
            signs.append(f"replies waited up to {self._duration(n.max_wait)} before their first word")
        if crawling:
            signs.append(
                f"{n.crawl / n.decode:.0%} of the time they wrote below {CRAWL_TPS:.0f} tok/s "
                f"(slowest {n.min_tps:.2f} tok/s)"
            )
        signs[0] = signs[0][0].upper() + signs[0][1:]
        detail = (
            f"{' and '.join(signs)}. Users see long lags or replies that seem stuck. Check the "
            "computer: a hot, throttled CPU, too little memory (swapping), or other programs using the CPU. "
            "Fewer replies at once, a smaller model, or another node helps."
        )
        self._add("crit", f"Matricxon on {node_name(row.host)} is overloaded", detail, row.host)
        return True

    @staticmethod
    def _duration(seconds: float) -> str:
        return f"{seconds:.0f}s" if seconds < 120 else f"{seconds // 60:.0f}m {seconds % 60:02.0f}s"

    def _long_read(self, row: NodeRow, n: NodeBucket) -> None:
        """A reply reading a long chat from the start while the node's other replies waited or crawled."""
        if not n.held_polls:
            return
        held_seconds = n.held_polls * self._poll_seconds
        read_seconds = n.long_read * self._poll_seconds
        total = n.read_tokens + n.read_reused
        cached = f"only {n.read_reused:,} of {total:,} came from the cache" if n.read_reused else "none from the cache"
        effects = []
        if n.queued_in_read:
            effects.append("other replies waited for a free model slot")
        if n.slow_in_read:
            effects.append("other replies wrote slower than usual")
        detail = (
            f"A reply read {n.read_tokens:,} prompt tokens of {n.read_model} from the start ({cached}), for about "
            f"{read_seconds:.0f}s. For {held_seconds:.0f}s of it {' and '.join(effects)}. "
            "A chat read from the start has usually lost its cache (a restart, or the model was unloaded): keep "
            "Save to disk every on and Max loaded models high enough. To keep other chats answering meanwhile, "
            "raise Concurrent replies per model, or send long chats to a faster node."
        )
        level = "crit" if held_seconds >= self.HELD_CRIT_SECONDS else "warn"
        self._add(level, f"A long prompt read held up other replies on {node_name(row.host)}", detail, row.host)

    def _weaker_nodes(self, flagged: set[str]) -> None:
        """Nodes slower than the others on the same model, leaving out those already flagged as slow right now."""
        by_model: dict[str, dict[str, float]] = {}
        for host, n in self.nodes.items():
            for model, (total, count) in n.tps_by_model.items():
                if count >= self.MIN_POLLS:
                    by_model.setdefault(model, {})[host] = total / count
        for model, speeds in by_model.items():
            if len(speeds) < 3:
                continue
            typical = statistics.median(speeds.values())
            weaker = sorted(node_name(h) for h, s in speeds.items() if s < typical * self.WEAKER and h not in flagged)
            if weaker:
                names = ", ".join(weaker[:5]) + (f" and {len(weaker) - 5} more" if len(weaker) > 5 else "")
                detail = (
                    f"Below {self.WEAKER:.0%} of the other nodes' {typical:.1f} tok/s on {model}: {names}. "
                    "Fine if they are smaller computers; otherwise check them."
                )
                title = f"{count_text(len(weaker), 'node', 'nodes')} consistently slower on {model}"
                self._add("info", title, detail, model)

    def _add(self, level: str, title: str, detail: str, subject: str | None) -> None:
        self.findings.append(Finding(level=level, title=title, detail=detail, subject=subject))
