"""Stats > Workflow analysis: what the live workflow history (workflow_history.py) says needs attention. The
per-node findings are in workflow_analysis_nodes.py; models and pAIring steps are here.
"""

import statistics

from app.schemas.workflow_analysis import (
    Finding,
    FinishedReply,
    HistoryBucket,
    ModelRow,
    StepRow,
    WorkflowAnalysis,
)
from app.services.workflow_analysis_nodes import NodeFindings, count_text

_LEVELS = {"crit": 0, "warn": 1, "info": 2}


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


class WorkflowAnalyzer:
    NODE_ROWS = 20
    LOAD_GAP_SECONDS = 30.0

    def __init__(self, buckets: list[HistoryBucket], window_seconds: float) -> None:
        self._buckets = buckets
        self._window = window_seconds
        gaps = [(b.last_poll - b.first_poll) / (b.polls - 1) for b in buckets if b.polls > 1]
        self._poll_seconds = statistics.median(gaps) if gaps else 0.4  # time one poll stands for
        self._nodes = NodeFindings(buckets, self._poll_seconds)
        self._finished = [f for b in buckets for f in b.finished]
        self.findings: list[Finding] = []

    def report(self) -> WorkflowAnalysis:
        rows = self._nodes.rows()
        self.findings.extend(self._nodes.find(rows))
        models = self._models()
        steps = self._steps()
        self._reply_findings(models)
        self._step_findings(steps)
        self.findings.sort(key=lambda f: _LEVELS[f.level])
        return WorkflowAnalysis(
            window_seconds=self._window,
            covered_seconds=round(sum(b.last_poll - b.first_poll + self._poll_seconds for b in self._buckets), 1),
            polls=sum(b.polls for b in self._buckets),
            nodes_seen=len(self._nodes.nodes),
            replies_finished=len(self._finished),
            findings=self.findings,
            nodes=rows[: self.NODE_ROWS],
            nodes_more=max(len(rows) - self.NODE_ROWS, 0),
            models=models,
            steps=steps,
        )

    def _models(self) -> list[ModelRow]:
        groups: dict[str, list[FinishedReply]] = {}
        for f in self._finished:
            groups.setdefault(f.model, []).append(f)
        rows = []
        for model, replies in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            loads = [f for f in replies if f.load_seconds and f.load_seconds > 1]
            prompt = sum(f.prompt_tokens for f in replies)
            ttft = _median([f.first_token_seconds for f in replies if f.first_token_seconds is not None])
            tps = _median([f.tokens_per_second for f in replies if f.tokens_per_second])
            rows.append(ModelRow(
                model=model, replies=len(replies), waited=len(loads), loads=self._load_events(loads),
                load_seconds=round(sum(f.load_seconds for f in loads), 1),
                first_token_seconds=round(ttft, 2) if ttft is not None else None,
                tokens_per_second=round(tps, 2) if tps is not None else None,
                reuse_share=round(sum(f.reused_tokens for f in replies) / prompt, 3) if prompt else None,
            ))  # fmt: skip
        return rows

    @staticmethod
    def _load_events(waited: list[FinishedReply]) -> int:
        """Loads behind these waits: replies on one node starting within LOAD_GAP_SECONDS of each
        other waited for the same load (two chats sent together both wait for it)."""
        events, last = 0, {}
        for f in sorted(waited, key=lambda f: f.started_at):
            if f.started_at - last.get(f.host, float("-inf")) > WorkflowAnalyzer.LOAD_GAP_SECONDS:
                events += 1
            last[f.host] = f.started_at
        return events

    def _reply_findings(self, models: list[ModelRow]) -> None:
        for m in models:
            if m.loads:
                waited = f"{count_text(m.waited, 'reply', 'replies')} waited {m.load_seconds:.0f}s in total for it."
                if m.loads == 1:
                    note = " Normal for the first message after Matricxon starts, or after the model sat unused."
                    self._add("info", f"{m.model} was loaded once", waited + note, m.model)
                else:
                    note = " It was unloaded between messages: raise Max loaded models or Keep model loaded."
                    self._add("warn", f"{m.model} was loaded {m.loads} times", waited + note, m.model)
            if m.first_token_seconds and m.first_token_seconds > 10:
                detail = (
                    f"Median {m.first_token_seconds:.1f}s before the first word. "
                    "Long prompts or many knowledge-base passages make this slow on a CPU."
                )
                self._add("warn", f"Slow first token on {m.model}", detail, m.model)
            if m.reuse_share is not None and m.reuse_share < 0.2 and m.replies >= 3:
                detail = (
                    f"Only {m.reuse_share:.0%} of prompt tokens came from the cache: "
                    "chats are read again from the start. "
                    "The model may be unloaded between messages."
                )
                self._add("info", f"Little prompt-cache reuse on {m.model}", detail, m.model)

    def _steps(self) -> list[StepRow]:
        durations: dict[str, list[float]] = {}
        for bucket in self._buckets:
            for step, values in bucket.steps.items():
                durations.setdefault(step, []).extend(values)
        usual = self._buckets[-1].step_usual_ms if self._buckets else {}
        rows = []
        for step, values in durations.items():
            if not values:  # a step with no timed run (a history saved before this check)
                continue
            ordered = sorted(values)
            p90 = ordered[min(len(ordered) - 1, int(0.9 * len(ordered)))]
            rows.append(
                StepRow(
                    step=step,
                    runs=len(values),
                    median_ms=round(statistics.median(ordered), 1),
                    p90_ms=p90,
                    usual_ms=usual.get(step),
                )
            )
        return sorted(rows, key=lambda r: -r.p90_ms)

    def _step_findings(self, steps: list[StepRow]) -> None:
        for s in steps:
            if s.usual_ms and s.runs >= 3 and s.median_ms > s.usual_ms * 1.5:
                detail = (
                    f"Median {s.median_ms / 1000:.2f}s over {s.runs} chats, against a usual {s.usual_ms / 1000:.2f}s."
                )
                self._add("warn", f"pAIring step {s.step} is slower than usual", detail, s.step)

    def _add(self, level: str, title: str, detail: str, subject: str | None) -> None:
        self.findings.append(Finding(level=level, title=title, detail=detail, subject=subject))
