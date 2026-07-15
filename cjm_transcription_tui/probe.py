"""Per-segment comparison probe: transcribe ONE VAD-cut segment across every
candidate (capability, MODEL) instance so the operator picks the run's
lightweight/accuracy pair on evidence instead of vibes (work item be4627c7).

Reuses the core pipeline's building blocks verbatim (convert -> VAD ->
boundaries -> cut -> one-segment composition over the candidate instance ids);
capability-side caches make repeat probes — and the eventual full run over the
same source — cheap. Comparison rows carry the transcript text plus the CR-7
empirical profile of each instance (duration mean / GPU + RSS peaks) once the
probe itself has seeded samples, so the "lightweight" judgment gets numbers.
"""

import time
from typing import Any, Dict, List

from cjm_transcription_core.boundaries import compute_segment_boundaries
from cjm_transcription_core.pipeline import (analyze_vad, build_segment_composition,
                                             convert_for_vad, cut_segments, probe_duration,
                                             records_from_composition)


class SegmentProbe:
    """One source's cut segments + cached per-segment comparison results.

    prepare() runs convert -> VAD -> boundaries -> cut ONCE per source (all
    cache-friendly); compare(i) fans the i-th raw segment out to every candidate
    instance as a one-segment composition and caches rows by segment index, so
    walking segments stays interactive and re-visiting one is free. The queue's
    manager reference supplies per-instance CR-7 empirical profiles for the rows.
    """

    def __init__(
        self,
        manager: Any,            # CapabilityManager (loaded instances; empirical profiles)
        queue: Any,              # Started JobQueue
        cfg: Any,                # PipelineConfig (vad/ffmpeg ids, rates, segment cap)
        source_path: str,        # The source to sample
        transcriber_ids: List[str],  # Candidate instance ids to fan out to
    ):
        self.manager = manager
        self.queue = queue
        self.cfg = cfg
        self.source_path = source_path
        self.transcriber_ids = list(transcriber_ids)
        self.raw_segments: List[Any] = []
        self.duration = 0.0
        self._rows: Dict[int, List[Dict[str, Any]]] = {}

    async def prepare(self) -> int:  # Segment count after cutting
        """Convert -> VAD -> boundaries -> cut the source once; return segment count."""
        vad_audio = await convert_for_vad(
            self.queue, self.cfg.ffmpeg_capability, self.source_path,
            sample_rate=self.cfg.sample_rate, channels=self.cfg.channels)
        chunks, duration = await analyze_vad(self.queue, self.cfg.vad_capability, vad_audio)
        if duration <= 0:
            duration = await probe_duration(self.queue, self.cfg.ffmpeg_capability,
                                            self.source_path)
        self.duration = duration
        boundaries = compute_segment_boundaries(chunks, self.cfg.max_segment_duration,
                                                duration)
        self.raw_segments, _ = await cut_segments(self.queue, self.cfg.ffmpeg_capability,
                                                  self.source_path, boundaries)
        return len(self.raw_segments)

    def profile(self, instance_id: str) -> Dict[str, Any]:
        """The instance's CR-7 empirical record fields worth showing (may be {})."""
        inst = self.manager.get_instance(instance_id)
        store = getattr(self.manager, "empirical_store", None)
        if inst is None or store is None or not getattr(inst, "config_hash", None):
            return {}
        try:
            rec = store.get_record(inst.instance_id, inst.config_hash)
        except Exception:
            return {}
        if rec is None:
            return {}
        return {"duration_s_mean": rec.duration_seconds_mean,
                "gpu_mb_peak": rec.gpu_memory_mb_peak_max,
                "rss_mb_peak": rec.memory_mb_peak_max,
                "samples": rec.sample_count}

    async def compare(self, index: int) -> List[Dict[str, Any]]:
        """Transcribe segment `index` across every candidate; one row per candidate."""
        if index in self._rows:
            return self._rows[index]
        seg = self.raw_segments[index]
        comp, metas = build_segment_composition(
            [seg], f"probe-{int(time.time())}", 0,
            self.cfg.ffmpeg_capability, self.transcriber_ids,
            sample_rate=self.cfg.sample_rate, channels=self.cfg.channels)
        comp_id = await self.queue.submit_composition(comp)
        crun = await self.queue.wait_for_composition(comp_id)
        records = records_from_composition(crun, metas)
        rec = records[0] if records else None
        rows: List[Dict[str, Any]] = []
        for tid in self.transcriber_ids:
            tr = (rec.transcripts.get(tid) if rec is not None else None) or {}
            text = tr.get("text") or ""
            rows.append({"instance_id": tid, "text": text, "chars": len(text),
                         "profile": self.profile(tid)})
        self._rows[index] = rows
        return rows
