import logging
import os
import shutil
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Optional

from src.core.job_service import JobService
from src.scripts.ingest_slack import SlackIngestor


logger = logging.getLogger("slack_ingest_worker")
logging.basicConfig(
    level=os.getenv("WORKER_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(message)s",
)

POLL_INTERVAL_SECONDS = float(os.getenv("WORKER_POLL_INTERVAL", "5"))


def find_slack_json_folder(extracted_root: Path) -> Optional[Path]:
    """Locate the folder that contains Slack JSON export files."""
    extracted_root = Path(extracted_root)
    if any(p.suffix.lower() == ".json" for p in extracted_root.glob("*.json")):
        return extracted_root

    for child in extracted_root.iterdir():
        if child.is_dir() and any(p.suffix.lower() == ".json" for p in child.glob("*.json")):
            return child

    for json_path in extracted_root.rglob("*.json"):
        return json_path.parent
    return None


def process_slack_job(job_id: str, payload: dict) -> None:
    zip_path = Path(payload.get("zip_path", ""))
    channel_id = payload.get("channel_id")
    channel_name = payload.get("channel_name")
    workspace_domain = payload.get("workspace_domain", "kitabisa")

    if not zip_path.exists():
        raise FileNotFoundError(f"ZIP archive not found: {zip_path}")
    if not channel_id or not channel_name:
        raise ValueError("Missing channel metadata in job payload.")

    JobService.update_progress(job_id, {"stage": "preparing", "details": "Verifying archive"})

    with zipfile.ZipFile(zip_path, "r") as archive:
        test_members = archive.namelist()
        if not test_members:
            raise ValueError("ZIP archive is empty.")

    temp_dir = Path(tempfile.mkdtemp(prefix=f"slack_ingest_{job_id}_"))
    try:
        JobService.update_progress(job_id, {"stage": "extracting"})
        with zipfile.ZipFile(zip_path, "r") as archive:
            archive.extractall(temp_dir)

        slack_folder = find_slack_json_folder(temp_dir)
        if not slack_folder:
            raise ValueError("Slack JSON files not found in the provided ZIP.")

        JobService.update_progress(
            job_id,
            {
                "stage": "ingesting",
                "details": f"Processing {slack_folder.name}",
            },
        )

        def progress_callback(event: str, data: dict) -> None:
            JobService.update_progress(job_id, {"stage": event, "data": data})

        ingestor = SlackIngestor(
            source=slack_folder,
            channel_id=channel_id,
            channel_name=channel_name,
            workspace_domain=workspace_domain,
            skip_embedding=False,
            limit=None,
            progress_callback=progress_callback,
        )
        ingestor.run()

        JobService.mark_completed(
            job_id,
            {
                "stats": ingestor.stats,
                "run_id": str(ingestor.run_id),
                "channel_id": channel_id,
                "channel_name": channel_name,
                "workspace_domain": workspace_domain,
            },
        )
        JobService.update_progress(job_id, {"stage": "completed"})
        logger.info("Job %s completed", job_id)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def main() -> None:
    logger.info("Slack ingestion worker started. Poll interval: %ss", POLL_INTERVAL_SECONDS)

    while True:
        try:
            job = JobService.fetch_next_pending_job("slack_ingest")
            if not job:
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            job_id = job["id"]
            payload = job.get("payload") or {}
            logger.info("Picked job %s", job_id)

            try:
                process_slack_job(job_id, payload)
            except Exception as exc:
                logger.exception("Job %s failed: %s", job_id, exc)
                JobService.mark_failed(job_id, str(exc))
        except Exception as loop_exc:
            logger.exception("Worker loop error: %s", loop_exc)
            time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
