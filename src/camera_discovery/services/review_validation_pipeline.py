from __future__ import annotations

from dataclasses import asdict
from zipfile import ZIP_DEFLATED, ZipFile

import httpx

from camera_discovery.core.models import (
    CameraCandidate,
    CandidateSet,
    OutputSummary,
    RunConfig,
    TargetContext,
    TrustPolicy,
    ValidationSummary,
)
from camera_discovery.utils.geojson_viewer import write_embedded_camera_map
from camera_discovery.utils.io import write_json, write_jsonl


class ReviewAndValidationPipeline:
    """Validate candidates and write final trusted/untrusted artifacts.

    LLM semantic review may have labeled candidates earlier, but this final stage
    uses deterministic/tool evidence only for stream validation and trusted output
    authorization. Multi-target runs are supported by carrying target_id metadata
    on each candidate and checking each candidate against its target's trust policy.
    """

    def __init__(self, config: RunConfig):
        self.config = config
        self.logs_dir = config.output_dir / "logs"
        self.candidates_dir = config.output_dir / "candidates"

    def run(self, target: TargetContext | list[TargetContext], candidates: CandidateSet):
        targets = target if isinstance(target, list) else [target]
        target_map = {t.target_id: t for t in targets}
        v = ValidationSummary(validation_enabled=self.config.validation_enabled, ffprobe_enabled=self.config.ffprobe_enabled)
        if self.config.validation_enabled and any(t.trust_policy == TrustPolicy.TRUSTED_ALLOWED for t in targets):
            self._validate(candidates, v)
        else:
            v.skipped = len(candidates.unique)
            for c in candidates.review:
                c.validation_status = "not_validated"
                c.trust_level = "untrusted"
        return v, self._write_outputs(targets, target_map, candidates, v)

    def _validate(self, candidates: CandidateSet, v: ValidationSummary) -> None:
        rows = candidates.in_scope or candidates.review
        for c in rows:
            v.attempted += 1
            status = self._validate_hls(c.stream_url)
            c.validation_status = status
            if status.startswith("active"):
                v.live += 1
                c.trust_level = "trusted" if c.scope_status == "in_scope" else "untrusted"
            elif status in {"dead_link", "offline_http", "restricted_http"}:
                v.dead += 1
                c.trust_level = "rejected"
            else:
                v.unknown += 1
                c.trust_level = "untrusted"

    def _validate_hls(self, url: str) -> str:
        try:
            with httpx.Client(timeout=self.config.http_timeout, headers={"User-Agent": self.config.user_agent}, follow_redirects=True) as client:
                r = client.get(url)
                if r.status_code in {401, 403}:
                    return "restricted_http"
                if r.status_code >= 400:
                    return "offline_http"
                return "active_live_unknown" if "#EXTM3U" in r.text[:4096] else "decode_failed"
        except Exception:
            return "dead_link"

    def _write_outputs(self, targets: list[TargetContext], target_map: dict[str, TargetContext], candidates: CandidateSet, v: ValidationSummary) -> OutputSummary:
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.candidates_dir.mkdir(parents=True, exist_ok=True)
        trusted_allowed = {t.target_id for t in targets if t.trust_policy == TrustPolicy.TRUSTED_ALLOWED and t.bbox_verified}
        trusted = [
            c for c in candidates.unique
            if c.trust_level == "trusted" and c.scope_status == "in_scope" and c.has_coordinates and c.target_id in trusted_allowed
        ]
        review = [
            c for c in candidates.unique
            if c.has_coordinates
            and c not in trusted
            and c.trust_level != "rejected"
            and c.scope_status != "out_of_scope"
        ]
        out = OutputSummary()
        if trusted:
            out.trusted_geojson_created = True
            out.trusted_geojson_features_written = len(trusted)
            self._write_geojson(self.config.output_dir / "camera.geojson", trusted, trusted=True, target_map=target_map)
            write_jsonl(self.config.output_dir / "camera_inventory.jsonl", [asdict(c) for c in trusted])
            self._write_cameras_md(trusted)
        elif (self.config.output_dir / "camera.geojson").exists():
            (self.config.output_dir / "camera.geojson").unlink()
        if review and self.config.allow_untrusted_review_output:
            out.untrusted_geojson_created = True
            out.untrusted_geojson_features_written = len(review)
            self._write_geojson(self.config.output_dir / "untrusted_camera_candidates.geojson", review, trusted=False, target_map=target_map)
            write_jsonl(self.candidates_dir / "untrusted_camera_candidates_source_rows.jsonl", [asdict(c) for c in review])
        write_jsonl(self.logs_dir / "validation_results.jsonl", [asdict(c) for c in candidates.unique])
        write_json(self.logs_dir / "validation_summary.json", asdict(v))
        write_json(self.logs_dir / "output_summary.json", asdict(out))
        out.map_html = str(self._write_map())
        out.review_artifacts_zip = str(self._package_review_artifacts())
        return out

    def _write_geojson(self, path, rows: list[CameraCandidate], *, trusted: bool, target_map: dict[str, TargetContext]) -> None:
        feats = []
        for c in rows:
            if not c.has_coordinates:
                continue
            target = target_map.get(c.target_id or "")
            props = asdict(c)
            props.update(
                {
                    "trust_level": "trusted" if trusted else "untrusted",
                    "output_policy": "trusted" if trusted else "review_only",
                    "review_required": not trusted,
                    "trusted_inventory_candidate": trusted,
                    "trusted_geojson_candidate": trusted,
                    "target_bbox_trusted": bool(target and target.bbox_verified),
                    "target_id": c.target_id,
                    "target_label": c.target_label,
                    "target_index": c.target_index,
                }
            )
            feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [c.lon, c.lat]}, "properties": props})
        write_json(path, {"type": "FeatureCollection", "features": feats})
        write_json(
            self.logs_dir / ("trusted_camera_geojson_status.json" if trusted else "untrusted_camera_candidates_geojson_status.json"),
            {"created": bool(feats), "features": len(feats), "path": str(path)},
        )

    def _write_cameras_md(self, rows: list[CameraCandidate]) -> None:
        (self.config.output_dir / "cameras.md").write_text(
            "# Trusted Camera Inventory\n\n" + "\n".join(f"- `{r.stream_url}` — {r.target_label or r.target_id}" for r in rows) + "\n",
            encoding="utf-8",
        )

    def _write_map(self):
        return write_embedded_camera_map(self.config.output_dir, output_name="map.html")

    def _package_review_artifacts(self):
        zpath = self.config.output_dir / "review_artifacts.zip"
        with ZipFile(zpath, "w", ZIP_DEFLATED) as z:
            for rel in ["camera.geojson", "untrusted_camera_candidates.geojson", "camera_inventory.jsonl", "cameras.md", "map.html"]:
                p = self.config.output_dir / rel
                if p.exists():
                    z.write(p, rel)
            for sub in ["logs", "candidates"]:
                folder = self.config.output_dir / sub
                if folder.exists():
                    for p in folder.rglob("*"):
                        if p.is_file():
                            z.write(p, str(p.relative_to(self.config.output_dir)))
        return zpath
