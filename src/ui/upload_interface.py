"""
Upload interface for knowledge base management.
"""
import os
import shutil
import tempfile
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import streamlit as st

from src.utils.file_processor import FileProcessor
from src.core.knowledge_service import KnowledgeService
from src.core.job_service import JobService
from src.utils.slack_helper import (
    export_and_ingest_slack_channel,
    validate_slack_token,
    validate_channel_id,
)


class UploadInterface:
    """File upload interface for the QA Assistant."""
    
    def __init__(self):
        self.file_processor = FileProcessor()
        self.knowledge_service = KnowledgeService()
        self.job_service = JobService()
    
    def render(self) -> None:
        """Render the upload interface."""
        st.title("Upload Knowledge Base")
        st.write(
            "Upload documents (PDF, TXT, MD, DOCX, CSV) or a Slack channel export in `.zip` format. "
            "Slack ZIP uploads will be unpacked, JSON messages parsed, and embeddings generated automatically."
        )
        
        tab1, tab2, tab3 = st.tabs(["File Upload", "Bulk ZIP Upload", "Slack Import"])
        
        with tab1:
            self._render_file_uploader()
        
        with tab2:
            self._render_bulk_zip_uploader()
        
        with tab3:
            self._render_slack_import()
        
        self._render_knowledge_stats()
    
    def _render_file_uploader(self) -> None:
        """Render standard file upload controls."""
        st.subheader("Upload Files or Slack ZIP")
        
        uploaded_files = st.file_uploader(
            "Choose files",
            accept_multiple_files=True,
            type=["pdf", "txt", "docx", "csv", "zip"],
        )
        
        source_link = st.text_input(
            "Source Link (Optional)",
            placeholder="https://docs.example.com/guide",
            help="Enter the URL where this document can be found online.",
        )
        
        treat_zip_as_slack = st.checkbox(
            "Treat uploaded .zip files as Slack channel exports",
            value=False,
        )
        
        slack_channel_id = slack_channel_name = workspace_domain = ""
        if treat_zip_as_slack:
            st.info("Provide Slack channel metadata for proper tagging.")
            slack_channel_id = st.text_input("Slack Channel ID", placeholder="C6MNKM087")
            slack_channel_name = st.text_input("Slack Channel Name", placeholder="dev-bugs")
            workspace_domain = st.text_input("Slack Workspace Domain", value="kitabisa")
        
        if uploaded_files:
            st.write("### Selected Files:")
            for file in uploaded_files:
                file_info = self.file_processor.get_file_info(file)
                st.write(f"{file_info['name']} ({file_info['size_mb']} MB)")
        
        if st.button("Process and Add to Knowledge Base", type="primary"):
            if uploaded_files:
                if source_link and not source_link.strip().startswith(("http://", "https://")):
                    st.error("Source link must start with http:// or https://")
                else:
                    self._process_files(
                        uploaded_files,
                        treat_zip_as_slack=treat_zip_as_slack,
                        slack_channel_id=slack_channel_id.strip(),
                        slack_channel_name=slack_channel_name.strip(),
                        workspace_domain=(workspace_domain or "kitabisa").strip(),
                        source_link=source_link.strip() if source_link else None,
                    )
            else:
                st.warning("Please upload at least one file.")
    
    def _render_bulk_zip_uploader(self) -> None:
        """Render bulk ZIP upload interface with no size limit."""
        st.subheader("Bulk ZIP Upload (No Size Limit)")
        st.write(
            "Upload a ZIP file containing documents (PDF, TXT, MD, DOCX, CSV). "
            "The folder structure will be preserved in metadata. "
            "Perfect for Notion exports or document folders."
        )
        
        uploaded_zip = st.file_uploader(
            "Choose a ZIP file",
            accept_multiple_files=False,
            type=["zip"],
            key="bulk_zip_uploader",
        )
        
        source_prefix = st.text_input(
            "Source Prefix (Optional)",
            placeholder="Notion/Engineering",
            help="Add a prefix to source names, e.g., 'Notion/Engineering/filename.md'",
            key="bulk_source_prefix",
        )
        
        if uploaded_zip:
            size_mb = uploaded_zip.size / (1024 * 1024)
            st.info(f"📦 **{uploaded_zip.name}** ({size_mb:.2f} MB)")
        
        if st.button("Extract and Process ZIP", type="primary", key="bulk_zip_btn"):
            if not uploaded_zip:
                st.warning("Please upload a ZIP file first.")
                return
            
            self._process_bulk_zip(uploaded_zip, source_prefix.strip() if source_prefix else "")
    
    def _process_bulk_zip(self, uploaded_zip, source_prefix: str = "") -> None:
        """Process a bulk ZIP file and add all documents to knowledge base."""
        import mimetypes
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        tmpdir = tempfile.mkdtemp(prefix="bulk_zip_")
        
        try:
            status_text.text("Extracting ZIP file...")
            uploaded_zip.seek(0)
            
            with zipfile.ZipFile(uploaded_zip) as zf:
                zf.extractall(tmpdir)
            
            # Find all supported files
            supported_exts = {".pdf", ".txt", ".md", ".docx", ".csv"}
            all_files = []
            
            for root, _, files in os.walk(tmpdir):
                for f in files:
                    ext = Path(f).suffix.lower()
                    if ext in supported_exts:
                        full_path = Path(os.path.join(root, f))
                        rel_path = full_path.relative_to(tmpdir)
                        all_files.append((full_path, str(rel_path)))
            
            if not all_files:
                st.warning("No supported documents found in the ZIP file.")
                shutil.rmtree(tmpdir, ignore_errors=True)
                return
            
            st.info(f"Found **{len(all_files)}** documents to process.")
            
            total_chunks = 0
            processed_files = 0
            failed_files = []
            
            for idx, (file_path, rel_path) in enumerate(all_files):
                progress = (idx + 1) / len(all_files)
                progress_bar.progress(progress)
                status_text.text(f"Processing ({idx + 1}/{len(all_files)}): {rel_path}")
                
                try:
                    # Build source name with prefix and folder structure
                    if source_prefix:
                        source_name = f"{source_prefix}/{rel_path}"
                    else:
                        source_name = rel_path
                    
                    # Read and process file
                    ext = file_path.suffix.lower()
                    mime_map = {
                        ".pdf": "application/pdf",
                        ".txt": "text/plain",
                        ".md": "text/markdown",
                        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        ".csv": "text/csv",
                    }
                    content_type = mime_map.get(ext, "text/plain")
                    
                    local_file = self.file_processor.create_uploaded_from_path(str(file_path))
                    local_file.type = content_type  # Override MIME type
                    
                    text = self.file_processor.process_uploaded_file(local_file)
                    local_file.close()
                    
                    if text and text.strip():
                        chunks_added = self.knowledge_service.add_to_knowledge_base(
                            text,
                            source_name,
                            source_link=None,
                        )
                        if chunks_added > 0:
                            total_chunks += chunks_added
                            processed_files += 1
                        else:
                            failed_files.append(rel_path)
                    else:
                        failed_files.append(rel_path)
                        
                except Exception as e:
                    failed_files.append(f"{rel_path} ({str(e)[:50]})")
                    continue
            
            progress_bar.progress(1.0)
            status_text.text("Processing complete!")
            
            st.success(f"✅ Processed **{processed_files}/{len(all_files)}** files, added **{total_chunks}** chunks.")
            
            if failed_files:
                with st.expander(f"⚠️ {len(failed_files)} files failed"):
                    for f in failed_files[:20]:
                        st.write(f"- {f}")
                    if len(failed_files) > 20:
                        st.write(f"... and {len(failed_files) - 20} more")
            
            st.balloons()
            
        except zipfile.BadZipFile:
            st.error("Invalid ZIP file. Please check and try again.")
        except Exception as e:
            st.error(f"Error processing ZIP: {str(e)}")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    
    def _render_slack_import(self) -> None:
        """Render Slack direct import interface."""
        st.subheader("Direct Slack Channel Import")
        st.write(
            "Export chat history langsung dari Slack API dan ingest ke knowledge base secara otomatis."
        )
        
        slack_token = st.text_input(
            "Slack User Token",
            type="password",
            placeholder="xoxp-...",
        )
        
        channel_id = st.text_input(
            "Channel ID",
            placeholder="C6MNKM087 atau GDDFBV5B2",
        )
        
        workspace_domain = st.text_input(
            "Workspace Domain",
            value="kitabisa",
        )
        
        col1, col2 = st.columns(2)
        with col1:
            oldest_date = st.date_input(
                "Tanggal Mulai (Oldest)",
                value=datetime(2024, 1, 1),
            )
        with col2:
            latest_date = st.date_input(
                "Tanggal Akhir (Latest)",
                value=None,
            )
        
        validation_ok = True
        if slack_token and not validate_slack_token(slack_token):
            st.warning("Token format tidak valid. User token harus dimulai dengan `xoxp-`")
            validation_ok = False
        
        if channel_id and not validate_channel_id(channel_id):
            st.warning("Channel ID format tidak valid.")
            validation_ok = False
        
        if st.button("Export & Ingest to Knowledge Base", type="primary", disabled=not validation_ok):
            if not slack_token or not channel_id:
                st.error("Token dan Channel ID wajib diisi!")
                return
            
            oldest_str = oldest_date.strftime("%Y-%m-%d") if oldest_date else None
            latest_str = latest_date.strftime("%Y-%m-%d") if latest_date else None
            
            with st.spinner(f"Exporting dari channel {channel_id}..."):
                try:
                    result = export_and_ingest_slack_channel(
                        token=slack_token,
                        channel_id=channel_id,
                        oldest=oldest_str,
                        latest=latest_str,
                        include_threads=True,
                        knowledge_service=self.knowledge_service,
                        file_processor=self.file_processor,
                        workspace_domain=workspace_domain or "kitabisa",
                    )
                    
                    if result.get("debug_logs"):
                        with st.expander("Debug Logs", expanded=True):
                            for log in result["debug_logs"]:
                                st.text(log)
                    
                    if result["status"] == "success":
                        st.success(
                            f"Berhasil export dan ingest {result['message_count']} pesan! "
                            f"Total {result['ingested_chunks']} chunks ditambahkan."
                        )
                        st.balloons()
                    elif result["status"] == "warning":
                        st.warning(f"{result['errors'][0] if result['errors'] else 'No messages found'}")
                    else:
                        st.error(f"Error: {'; '.join(result['errors'])}")
                        
                except Exception as e:
                    st.error(f"Unexpected error: {str(e)}")
        
        with st.expander("Panduan Slack Import"):
            st.markdown("""
            ### Cara mendapatkan Slack User Token:
            1. Buka https://api.slack.com/apps
            2. Pilih app Anda atau buat app baru
            3. Di sidebar, pilih **OAuth & Permissions**
            4. Tambahkan scopes: `channels:history`, `groups:history`
            5. Install app ke workspace
            6. Copy **User OAuth Token** (dimulai dengan `xoxp-`)
            
            ### Cara mendapatkan Channel ID:
            - **Dari Web**: Buka channel, lihat URL: `.../archives/C6MNKM087`
            - **Dari App**: Klik channel name → View channel details → scroll bawah
            """)
    
    def _process_files(
        self,
        uploaded_files: List,
        treat_zip_as_slack: bool = False,
        slack_channel_id: str = "",
        slack_channel_name: str = "",
        workspace_domain: str = "kitabisa",
        source_link: Optional[str] = None,
    ) -> None:
        """Process uploaded files and add to knowledge base."""
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        total_files = len(uploaded_files)
        processed_files = 0
        total_chunks = 0
        
        for i, uploaded_file in enumerate(uploaded_files):
            status_text.text(f"Processing {uploaded_file.name}...")
            filename_lower = uploaded_file.name.lower()
            
            if filename_lower.endswith(".zip"):
                uploaded_file.seek(0)
                
                if treat_zip_as_slack:
                    if not slack_channel_id:
                        st.warning("Slack Channel ID is required for Slack exports.")
                        continue
                    
                    try:
                        with zipfile.ZipFile(uploaded_file, "r") as archive:
                            has_json = any(m.lower().endswith(".json") for m in archive.namelist())
                    except zipfile.BadZipFile:
                        st.error(f"{uploaded_file.name} is not a valid zip archive.")
                        continue
                    finally:
                        uploaded_file.seek(0)
                    
                    if not has_json:
                        st.error("ZIP does not contain Slack JSON files.")
                        continue
                    
                    jobs_dir = Path("uploads/slack_jobs")
                    jobs_dir.mkdir(parents=True, exist_ok=True)
                    job_id = str(uuid.uuid4())
                    destination = jobs_dir / f"{job_id}.zip"
                    
                    try:
                        with destination.open("wb") as dest_file:
                            dest_file.write(uploaded_file.getbuffer())
                        
                        self.job_service.enqueue_slack_job(
                            job_id=job_id,
                            zip_path=str(destination.resolve()),
                            channel_id=slack_channel_id,
                            channel_name=slack_channel_name or slack_channel_id,
                            workspace_domain=workspace_domain,
                            original_filename=uploaded_file.name,
                            requested_by=os.getenv("USER") or os.getenv("STREAMLIT_USER"),
                        )
                        processed_files += 1
                        st.success(f"Slack export queued (Job ID: `{job_id}`)")
                    except Exception as exc:
                        destination.unlink(missing_ok=True)
                        st.error(f"Failed to create job: {exc}")
                    continue
                
                chunks_from_zip = self._process_regular_zip(
                    uploaded_file,
                    source_link,
                    status_text,
                )
                if chunks_from_zip > 0:
                    processed_files += 1
                    total_chunks += chunks_from_zip
            else:
                validation_errors = self.file_processor.validate_file(uploaded_file)
                if validation_errors:
                    for error in validation_errors:
                        st.error(f"{uploaded_file.name}: {error}")
                    continue
                
                try:
                    text = self.file_processor.process_uploaded_file(uploaded_file)
                    
                    if text:
                        chunks_added = self.knowledge_service.add_to_knowledge_base(
                            text,
                            uploaded_file.name,
                            source_link=source_link,
                        )
                        if chunks_added > 0:
                            processed_files += 1
                            total_chunks += chunks_added
                            st.success(f"{uploaded_file.name}: Added {chunks_added} chunks")
                        else:
                            st.error(f"{uploaded_file.name}: Failed to add chunks")
                    else:
                        st.error(f"{uploaded_file.name}: Failed to extract text")
                except Exception as e:
                    st.error(f"{uploaded_file.name}: Error - {str(e)}")
            
            progress_bar.progress((i + 1) / total_files)
        
        status_text.text("Processing complete!")
        
        if processed_files > 0:
            st.success(f"Processed {processed_files}/{total_files} files!")
            st.info(f"Total chunks added: {total_chunks}")
        else:
            st.error("No files were successfully processed.")
    
    def _process_regular_zip(
        self,
        uploaded_file,
        source_link: Optional[str],
        status_text,
    ) -> int:
        """Process a regular ZIP file (not Slack export)."""
        total_chunks = 0
        tmpdir = tempfile.mkdtemp(prefix="upload_zip_")
        
        try:
            with zipfile.ZipFile(uploaded_file) as zf:
                zf.extractall(tmpdir)
        except zipfile.BadZipFile:
            st.error(f"{uploaded_file.name} is not a valid zip archive.")
            shutil.rmtree(tmpdir, ignore_errors=True)
            return 0
        except Exception as exc:
            st.error(f"Error unpacking {uploaded_file.name}: {exc}")
            shutil.rmtree(tmpdir, ignore_errors=True)
            return 0
        
        supported_exts = {".pdf", ".txt", ".docx", ".csv"}
        extracted_files = [
            Path(os.path.join(root, f))
            for root, _, files in os.walk(tmpdir)
            for f in files
            if Path(f).suffix.lower() in supported_exts
        ]
        
        if not extracted_files:
            json_detected = any(
                Path(f).suffix.lower() == ".json"
                for _, _, files in os.walk(tmpdir)
                for f in files
            )
            if json_detected:
                st.warning(
                    f"{uploaded_file.name} appears to contain Slack JSON. "
                    "Enable the Slack export option to process it."
                )
            else:
                st.info(f"No supported documents found in {uploaded_file.name}.")
        else:
            for ef in extracted_files:
                status_text.text(f"Processing {ef.name}...")
                try:
                    local_file = self.file_processor.create_uploaded_from_path(str(ef))
                    validation_errors = self.file_processor.validate_file(local_file)
                    if validation_errors:
                        for error in validation_errors:
                            st.error(f"{ef.name}: {error}")
                        local_file.close()
                        continue
                    
                    local_file.seek(0)
                    text = self.file_processor.process_uploaded_file(local_file)
                    local_file.close()
                except Exception as exc:
                    st.error(f"{ef.name}: Failed to process ({exc})")
                    continue
                
                if text:
                    try:
                        chunks_added = self.knowledge_service.add_to_knowledge_base(
                            text,
                            ef.name,
                            source_link=source_link,
                        )
                        if chunks_added > 0:
                            total_chunks += chunks_added
                            st.success(f"{ef.name}: Added {chunks_added} chunks")
                        else:
                            st.error(f"{ef.name}: Failed to add chunks")
                    except Exception as e:
                        st.error(f"{ef.name}: Error - {str(e)}")
                else:
                    st.error(f"{ef.name}: Failed to extract text")
        
        shutil.rmtree(tmpdir, ignore_errors=True)
        return total_chunks
    
    def _render_knowledge_stats(self) -> None:
        """Display knowledge base statistics."""
        st.write("---")
        st.write("### Knowledge Base")
        
        stats = self.knowledge_service.get_knowledge_stats()
        st.metric("Total Documents", stats["total_files"])
        
        col1, col2 = st.columns([3, 1])
        with col1:
            search_query = st.text_input("Search documents", placeholder="Enter keywords...")
        with col2:
            search_button = st.button("Search", type="primary")
        
        if search_query and (search_button or search_query):
            st.write(f"#### Search Results for: '{search_query}'")
            results = self._search_documents(search_query)
            if results:
                for doc in results:
                    with st.expander(f"{doc.get('metadata', {}).get('source', 'Unknown')}"):
                        st.write(doc["content"][:300] + "...")
            else:
                st.info("No documents found matching your search.")
        else:
            if stats["top_sources"]:
                st.write("#### All Documents:")
                for source, count in stats["top_sources"]:
                    display_name = source if len(source) <= 60 else source[:57] + "..."
                    st.write(f"**{display_name}**")
            else:
                st.info("No documents uploaded yet.")
        
        self._render_job_queue()
    
    def _search_documents(self, query: str) -> List:
        """Search documents using embedding similarity."""
        try:
            from src.core.embedding_service import EmbeddingService
            embedding_service = EmbeddingService()
            
            query_embedding = embedding_service.embed_text(query)
            if not query_embedding:
                return []
            
            return self.knowledge_service.retrieve_similar_docs(query_embedding, top_k=5)
        except Exception as e:
            st.error(f"Search error: {e}")
            return []
    
    def _render_job_queue(self) -> None:
        """Display recent Slack ingestion jobs."""
        st.write("#### Slack Ingestion Jobs (recent)")
        jobs = self.job_service.list_recent_jobs(limit=8, job_type="slack_ingest")
        
        if not jobs:
            st.info("Tidak ada job Slack yang menunggu.")
            return
        
        status_labels = {
            "pending": "Pending",
            "running": "Running",
            "completed": "Completed",
            "failed": "Failed",
        }
        
        for job in jobs:
            status_label = status_labels.get(job["status"], job["status"])
            created_at = job.get("created_at")
            created_str = created_at.strftime("%Y-%m-%d %H:%M") if created_at else "-"
            payload = job.get("payload") or {}
            
            st.markdown(f"**{status_label}** | `{job['id']}` | {created_str}")
            st.caption(
                f"Channel: {payload.get('channel_name', '-')} ({payload.get('channel_id', '-')}) | "
                f"Workspace: {payload.get('workspace_domain', '-')}"
            )
            
            progress = job.get("progress") or {}
            if progress:
                stage = progress.get("stage")
                if stage:
                    st.write(f"Progress: `{stage}`")
                
                data = progress.get("data")
                if isinstance(data, dict) and data:
                    st.caption(f"File {data.get('index', 0)}/{data.get('total', 0)} {data.get('filename', '')}")
            
            result = job.get("result") or {}
            if job["status"] == "completed" and isinstance(result.get("stats"), dict):
                stats = result["stats"]
                st.write(f"Messages: {stats.get('messages_processed', 0)} | Threads: {stats.get('threads_embedded', 0)}")
            
            if job["status"] == "failed":
                error = result.get("error") or "Unknown error"
                st.error(error)
        
        st.write("---")
