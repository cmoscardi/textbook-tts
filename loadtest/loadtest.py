#!/usr/bin/env python3
"""
Load test for textbook-tts.

Simulates concurrent users: sign up → upload PDF → wait for parse → play sentences.
Measures latency at each stage and reports summary statistics.

Usage:
    python loadtest.py run --rate 0.5 --users 10
    python loadtest.py cleanup [--dry-run]

Requires SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY env vars
(or pass via CLI flags).
"""

import argparse
import asyncio
import hashlib
import json
import os
import random
import statistics
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

import httpx

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

POLL_INTERVAL = 1.0  # seconds between parse-status polls
PREFETCH_AHEAD = 3   # sentences to prefetch (mirrors frontend)
DEFAULT_PARSE_TIMEOUT = 1200  # seconds
SYNTH_TIMEOUT = 60.0  # per-sentence synthesis timeout
# Cloudflare Turnstile always-pass test secret & token
TURNSTILE_TEST_SECRET = "1x0000000000000000000000000000000AA"
TURNSTILE_TEST_TOKEN = "10000000-aaaa-bbbb-cccc-000000000001"
MANAGEMENT_API = "https://api.supabase.com"


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# CAPTCHA swap via Supabase Management API
# ---------------------------------------------------------------------------

def _project_ref(supabase_url: str) -> str:
    """Extract project ref from https://<ref>.supabase.co"""
    from urllib.parse import urlparse
    host = urlparse(supabase_url).hostname or ""
    return host.split(".")[0]


async def _get_auth_config(http: httpx.AsyncClient, access_token: str,
                           ref: str) -> dict:
    resp = await http.get(
        f"{MANAGEMENT_API}/v1/projects/{ref}/config/auth",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    resp.raise_for_status()
    return resp.json()


async def _patch_auth_config(http: httpx.AsyncClient, access_token: str,
                             ref: str, patch: dict) -> None:
    resp = await http.patch(
        f"{MANAGEMENT_API}/v1/projects/{ref}/config/auth",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json=patch,
    )
    resp.raise_for_status()


async def swap_captcha_to_test(http: httpx.AsyncClient, access_token: str,
                               supabase_url: str,
                               prod_secret: str) -> str | None:
    """Swap CAPTCHA secret to the Turnstile test key.

    The Management API redacts secrets on GET, so we take the production
    secret from the environment (CAPTCHA_SECRET) to restore later.

    Returns the production secret to restore, or None if no swap needed.
    """
    ref = _project_ref(supabase_url)
    config = await _get_auth_config(http, access_token, ref)

    if not config.get("security_captcha_enabled"):
        log("CAPTCHA is not enabled — no swap needed")
        return None

    if not prod_secret:
        raise RuntimeError(
            "CAPTCHA is enabled but CAPTCHA_SECRET env var is not set. "
            "Needed to restore the secret after the test."
        )

    log("Swapping CAPTCHA secret to Turnstile test key...")
    await _patch_auth_config(http, access_token, ref, {
        "security_captcha_secret": TURNSTILE_TEST_SECRET,
    })
    # GoTrue takes a few seconds to pick up config changes
    log("Waiting for config to propagate...")
    await asyncio.sleep(10)
    log("CAPTCHA secret swapped to test key")
    return prod_secret


async def restore_captcha(http: httpx.AsyncClient, access_token: str,
                          supabase_url: str, prod_secret: str) -> None:
    """Restore the production CAPTCHA secret."""
    ref = _project_ref(supabase_url)
    log("Restoring production CAPTCHA secret...")
    await _patch_auth_config(http, access_token, ref, {
        "security_captcha_secret": prod_secret,
    })
    # Wait for propagation before exiting
    log("Waiting for config to propagate...")
    await asyncio.sleep(10)
    log("CAPTCHA secret restored")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class UserResult:
    user_index: int
    user_id: str
    email: str
    pdf_file: str
    started_at: float
    signup_duration: float = 0.0
    upload_duration: float = 0.0
    first_page_time: float = 0.0       # upload start → first page ready (our measurement)
    first_page_time_worker: float = 0.0 # worker's own time_to_first_page
    parse_total_time: float = 0.0
    parse_queue_time: float = 0.0
    parse_processing_time: float = 0.0
    first_synthesis_latency: float = 0.0
    total_buffering_time: float = 0.0
    interruptions: int = 0
    interruption_durations: list = field(default_factory=list)
    sentences_played: int = 0
    synthesis_latencies: list = field(default_factory=list)
    error: str | None = None
    phase_reached: str = "init"


# ---------------------------------------------------------------------------
# Supabase API helpers
# ---------------------------------------------------------------------------

class SupabaseClient:
    def __init__(self, base_url: str, anon_key: str, service_role_key: str,
                 http: httpx.AsyncClient, captcha_token: str):
        self.url = base_url.rstrip("/")
        self.anon_key = anon_key
        self.service_key = service_role_key
        self.http = http
        self.captcha_token = captcha_token

    def _admin_headers(self):
        return {
            "Authorization": f"Bearer {self.service_key}",
            "apikey": self.service_key,
            "Content-Type": "application/json",
        }

    def _user_headers(self, token: str):
        return {
            "Authorization": f"Bearer {token}",
            "apikey": self.anon_key,
            "Content-Type": "application/json",
        }

    # ---- Auth ----

    async def admin_create_user(self, email: str, password: str) -> str:
        resp = await self.http.post(
            f"{self.url}/auth/v1/admin/users",
            headers=self._admin_headers(),
            json={"email": email, "password": password, "email_confirm": True},
        )
        resp.raise_for_status()
        return resp.json()["id"]

    async def sign_in(self, email: str, password: str) -> str:
        resp = await self.http.post(
            f"{self.url}/auth/v1/token?grant_type=password",
            headers={"apikey": self.anon_key, "Content-Type": "application/json"},
            json={
                "email": email,
                "password": password,
                "gotrue_meta_security": {"captcha_token": self.captcha_token},
            },
        )
        if resp.status_code == 400 and "captcha" in resp.text.lower():
            raise RuntimeError(
                "CAPTCHA is blocking sign-in. Either:\n"
                "  1. Set Supabase CAPTCHA secret to the Turnstile test key "
                "(1x0000000000000000000000000000000AA), or\n"
                "  2. Disable CAPTCHA in Supabase dashboard "
                "(Authentication > Bot Protection), or\n"
                "  3. Pass a valid --captcha-token"
            )
        resp.raise_for_status()
        return resp.json()["access_token"]

    async def enable_user(self, user_id: str) -> None:
        resp = await self.http.patch(
            f"{self.url}/rest/v1/user_profiles?user_id=eq.{user_id}",
            headers={**self._admin_headers(), "Prefer": "return=minimal"},
            json={"enabled": True, "subscription_tier": "unlimited"},
        )
        resp.raise_for_status()

    # ---- Storage & Files ----

    async def upload_pdf(self, token: str, user_id: str,
                         filename: str, data: bytes) -> dict:
        checksum = hashlib.sha256(data).hexdigest()
        storage_path = f"{user_id}/{int(time.time() * 1000)}_{filename}"

        # Upload to storage
        resp = await self.http.post(
            f"{self.url}/storage/v1/object/files/{storage_path}",
            headers={
                "Authorization": f"Bearer {token}",
                "apikey": self.anon_key,
                "Content-Type": "application/pdf",
            },
            content=data,
        )
        resp.raise_for_status()

        # Insert file record
        resp = await self.http.post(
            f"{self.url}/rest/v1/files",
            headers={
                **self._user_headers(token),
                "Prefer": "return=representation",
            },
            json={
                "user_id": user_id,
                "file_name": filename,
                "file_path": storage_path,
                "file_size": len(data),
                "mime_type": "application/pdf",
                "checksum": checksum,
            },
        )
        resp.raise_for_status()
        rows = resp.json()
        return rows[0] if isinstance(rows, list) else rows

    # ---- Parse ----

    async def start_parse(self, token: str, file_id: str) -> str:
        resp = await self.http.post(
            f"{self.url}/functions/v1/parse-file",
            headers=self._user_headers(token),
            json={"file_id": file_id},
        )
        resp.raise_for_status()
        return resp.json()["id"]

    async def poll_parse_status(self, token: str, job_id: str) -> dict | None:
        resp = await self.http.get(
            f"{self.url}/rest/v1/file_parsings",
            headers=self._user_headers(token),
            params={"job_id": f"eq.{job_id}", "select": "*"},
        )
        resp.raise_for_status()
        rows = resp.json()
        return rows[0] if rows else None

    # ---- Sentences ----

    async def get_sentences(self, token: str, file_id: str) -> list[dict]:
        resp = await self.http.get(
            f"{self.url}/rest/v1/page_sentences",
            headers=self._user_headers(token),
            params={
                "file_id": f"eq.{file_id}",
                "select": "sentence_id,text,sequence_number",
                "order": "sequence_number",
            },
        )
        resp.raise_for_status()
        return resp.json()

    # ---- Synthesis ----

    async def synthesize(self, token: str, text: str,
                         file_id: str) -> tuple[float, float]:
        """Returns (http_latency_seconds, audio_duration_seconds)."""
        t0 = time.monotonic()
        resp = await self.http.post(
            f"{self.url}/functions/v1/play-sentence",
            headers=self._user_headers(token),
            json={"text": text, "file_id": file_id},
            timeout=SYNTH_TIMEOUT,
        )
        latency = time.monotonic() - t0
        resp.raise_for_status()
        duration = float(resp.headers.get("X-Audio-Duration", "0") or "0")
        if duration <= 0:
            # Fallback: estimate from MP3 size at 128kbps
            duration = max(len(resp.content) / 16000, 0.5)
        return latency, duration

    # ---- Cleanup ----

    async def list_users(self, page: int = 1, per_page: int = 50) -> list[dict]:
        resp = await self.http.get(
            f"{self.url}/auth/v1/admin/users",
            headers=self._admin_headers(),
            params={"page": page, "per_page": per_page},
        )
        resp.raise_for_status()
        return resp.json().get("users", [])

    async def delete_user_storage(self, user_id: str) -> None:
        # List objects in user's storage folder
        resp = await self.http.post(
            f"{self.url}/storage/v1/object/list/files",
            headers=self._admin_headers(),
            json={"prefix": f"{user_id}/", "limit": 1000},
        )
        if resp.status_code == 200:
            objects = resp.json()
            if objects:
                paths = [f"{user_id}/{obj['name']}" for obj in objects]
                # httpx delete doesn't support json=; use request()
                await self.http.request(
                    "DELETE",
                    f"{self.url}/storage/v1/object/files",
                    headers=self._admin_headers(),
                    json={"prefixes": paths},
                )

    async def admin_delete_user(self, user_id: str) -> None:
        resp = await self.http.delete(
            f"{self.url}/auth/v1/admin/users/{user_id}",
            headers=self._admin_headers(),
        )
        resp.raise_for_status()


# ---------------------------------------------------------------------------
# User simulation
# ---------------------------------------------------------------------------

async def run_user(idx: int, client: SupabaseClient, pdf_path: Path,
                   max_sentences: int, parse_timeout: int,
                   playback_speed: float = 1.0) -> UserResult:
    ts = int(time.time())
    email = f"loadtest+{idx}_{ts}@test.invalid"
    password = f"Lt{ts}{idx:04d}!xQ"
    result = UserResult(
        user_index=idx, user_id="", email=email,
        pdf_file=pdf_path.name, started_at=time.time(),
    )

    try:
        # ── 1. Sign up ──
        result.phase_reached = "signup"
        t0 = time.monotonic()
        user_id = await client.admin_create_user(email, password)
        result.user_id = user_id
        # Small delay for the DB trigger to create user_profiles row
        await asyncio.sleep(0.5)
        await client.enable_user(user_id)
        token = await client.sign_in(email, password)
        result.signup_duration = time.monotonic() - t0
        log(f"[User {idx}] Signed up in {result.signup_duration:.1f}s")

        # ── 2. Upload PDF ──
        result.phase_reached = "upload"
        t_upload_start = time.monotonic()
        pdf_data = pdf_path.read_bytes()
        file_record = await client.upload_pdf(
            token, user_id, pdf_path.name, pdf_data
        )
        file_id = file_record["file_id"]
        result.upload_duration = time.monotonic() - t_upload_start
        log(f"[User {idx}] Uploaded {pdf_path.name} in {result.upload_duration:.1f}s")

        # ── 3. Start parsing & poll until first page is ready ──
        result.phase_reached = "parse"
        job_id = await client.start_parse(token, file_id)
        log(f"[User {idx}] Parse started (job {job_id[:8]}...)")

        enqueue_time = time.monotonic()
        first_running_time = None
        first_page_ready = False

        while True:
            elapsed = time.monotonic() - enqueue_time
            if elapsed > parse_timeout:
                raise TimeoutError(
                    f"Parsing not ready after {parse_timeout}s"
                )

            row = await client.poll_parse_status(token, job_id)
            if row:
                status = row.get("status", "pending")
                completion = row.get("job_completion", 0)

                if status == "running" and first_running_time is None:
                    first_running_time = time.monotonic()

                if status == "failed":
                    raise RuntimeError(
                        f"Parsing failed: {row.get('error_message', 'unknown')}"
                    )

                # First page is ready when completion > 15 (mirrors frontend)
                # or parsing already completed entirely
                if completion > 15 or status == "completed":
                    result.first_page_time = time.monotonic() - t_upload_start
                    log(f"[User {idx}] First page ready in "
                        f"{result.first_page_time:.1f}s (completion={completion}%)")
                    first_page_ready = True
                    if status == "completed":
                        # Parse already done — record times now
                        now = time.monotonic()
                        result.parse_total_time = now - t_upload_start
                        if first_running_time:
                            result.parse_queue_time = (
                                first_running_time - enqueue_time
                            )
                            result.parse_processing_time = (
                                now - first_running_time
                            )
                        else:
                            result.parse_queue_time = now - enqueue_time
                            result.parse_processing_time = 0.0
                        result.first_page_time_worker = row.get(
                            "time_to_first_page", 0.0
                        ) or 0.0
                    break

            await asyncio.sleep(POLL_INTERVAL)

        # ── 4. Background: continue polling until full parse completes ──
        async def poll_until_complete():
            nonlocal first_running_time
            while True:
                await asyncio.sleep(POLL_INTERVAL)
                elapsed = time.monotonic() - enqueue_time
                if elapsed > parse_timeout:
                    result.error = (result.error or "") + \
                        f"; parse timed out after {parse_timeout}s"
                    return
                row = await client.poll_parse_status(token, job_id)
                if not row:
                    continue
                status = row.get("status", "pending")
                if status == "running" and first_running_time is None:
                    first_running_time = time.monotonic()
                if status == "completed":
                    now = time.monotonic()
                    result.parse_total_time = now - t_upload_start
                    if first_running_time:
                        result.parse_queue_time = (
                            first_running_time - enqueue_time
                        )
                        result.parse_processing_time = (
                            now - first_running_time
                        )
                    else:
                        result.parse_queue_time = now - enqueue_time
                        result.parse_processing_time = 0.0
                    result.first_page_time_worker = row.get(
                        "time_to_first_page", 0.0
                    ) or 0.0
                    log(
                        f"[User {idx}] Full parse done in "
                        f"{result.parse_total_time:.1f}s "
                        f"(queue ~{result.parse_queue_time:.1f}s, "
                        f"processing ~{result.parse_processing_time:.1f}s, "
                        f"worker first_page={result.first_page_time_worker:.1f}s)"
                    )
                    return
                if status == "failed":
                    result.error = (result.error or "") + \
                        f"; parse failed: {row.get('error_message', 'unknown')}"
                    return

        # Only spawn background poller if parse isn't already done
        parse_done = asyncio.Event()
        if result.parse_total_time > 0:
            parse_done.set()
        else:
            parse_bg_task = asyncio.create_task(poll_until_complete())

            # Wrap so we can signal parse_done when the poller returns
            async def _poll_wrapper():
                await parse_bg_task
                parse_done.set()
            asyncio.create_task(_poll_wrapper())

        # ── 5. Fetch first-page sentences & start playback ──
        # As parsing continues, new sentences appear. We re-fetch
        # periodically and grow the play queue, mirroring the frontend.
        result.phase_reached = "play"
        sentences: list[dict] = await client.get_sentences(token, file_id)
        if not sentences:
            result.error = "No sentences found after first page parsed"
            await parse_done.wait()
            return result
        log(f"[User {idx}] Got {len(sentences)} initial sentences")

        # Background task: periodically fetch new sentences while parsing
        sentences_lock = asyncio.Lock()

        async def sentence_refresher():
            """Re-fetch sentences every 3s until parse is done."""
            while not parse_done.is_set():
                await asyncio.sleep(3.0)
                try:
                    new = await client.get_sentences(token, file_id)
                    async with sentences_lock:
                        if len(new) > len(sentences):
                            sentences.extend(new[len(sentences):])
                except Exception:
                    pass
            # One final fetch after parse completes
            try:
                new = await client.get_sentences(token, file_id)
                async with sentences_lock:
                    if len(new) > len(sentences):
                        sentences.extend(new[len(sentences):])
            except Exception:
                pass

        refresh_task = asyncio.create_task(sentence_refresher())

        # ── 6. Simulate playback with prefetching ──
        synth_tasks: dict[int, asyncio.Task] = {}

        def fire_synth(si: int) -> None:
            if si < len(sentences) and si < max_sentences \
                    and si not in synth_tasks:
                synth_tasks[si] = asyncio.create_task(
                    client.synthesize(token, sentences[si]["text"], file_id)
                )

        # Initial prefetch: sentences 0..PREFETCH_AHEAD
        for j in range(min(PREFETCH_AHEAD + 1, len(sentences), max_sentences)):
            fire_synth(j)

        total_stall = 0.0
        i = 0

        while i < max_sentences:
            # Check if this sentence is available yet
            if i >= len(sentences):
                # No more sentences yet — wait for new ones or parse to finish
                if parse_done.is_set():
                    break  # parsing done, no more sentences coming
                log(f"[User {idx}] Sentence {i}: waiting for parse...")
                t_wait_start = time.monotonic()
                while i >= len(sentences) and not parse_done.is_set():
                    await asyncio.sleep(0.5)
                if i >= len(sentences):
                    break  # parse done, still no more
                wait = time.monotonic() - t_wait_start
                total_stall += wait
                result.interruptions += 1
                result.interruption_durations.append(round(wait, 3))
                log(f"[User {idx}] Sentence {i}: "
                    f"new sentences available (+{wait:.1f}s wait)")
                # Prefetch newly available sentences
                for j in range(i, min(i + PREFETCH_AHEAD + 1,
                                      len(sentences), max_sentences)):
                    fire_synth(j)

            # Ensure synthesis is started for this sentence
            fire_synth(i)

            # Wait for current sentence's audio
            t_wait_start = time.monotonic()
            try:
                latency, duration = await synth_tasks[i]
            except Exception as e:
                log(f"[User {idx}] Sentence {i}: synthesis FAILED ({e})")
                result.synthesis_latencies.append(-1.0)
                i += 1
                fire_synth(i + PREFETCH_AHEAD)
                continue

            t_now = time.monotonic()
            wait_time = t_now - t_wait_start

            # Stall: how long we had to wait past when we needed the audio.
            stall = wait_time if wait_time > 0.05 else 0.0

            if stall > 0:
                result.interruptions += 1
                result.interruption_durations.append(round(stall, 3))
                log(f"[User {idx}] Sentence {i}: "
                    f"buffering {stall:.1f}s")

            if i == 0:
                result.first_synthesis_latency = latency
            total_stall += stall
            result.synthesis_latencies.append(round(latency, 3))

            # Prefetch next sentences (may include newly parsed ones)
            for j in range(i + 1, min(i + PREFETCH_AHEAD + 2,
                                      len(sentences), max_sentences)):
                fire_synth(j)

            play_time = duration / playback_speed
            log(f"[User {idx}] Sentence {i}: playing "
                f"({duration:.1f}s audio @ {playback_speed}x = {play_time:.1f}s, "
                f"synth took {latency:.1f}s)")

            # Simulate playback — sleep for audio duration / speed
            await asyncio.sleep(play_time)
            i += 1

        result.sentences_played = i
        result.total_buffering_time = round(total_stall, 3)

        # Wait for background tasks to finish
        refresh_task.cancel()
        try:
            await refresh_task
        except asyncio.CancelledError:
            pass
        await parse_done.wait()

        log(
            f"[User {idx}] Done. Played {i}/{len(sentences)} sentences, "
            f"stall: {total_stall:.1f}s, "
            f"first audio: {result.first_synthesis_latency:.2f}s"
        )

    except Exception as e:
        result.error = str(e)
        log(f"[User {idx}] ERROR in {result.phase_reached}: {e}")

    return result


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------

def percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    k = (len(s) - 1) * p
    f = int(k)
    c = f + 1 if f + 1 < len(s) else f
    return s[f] + (k - f) * (s[c] - s[f])


def stats_for(values: list[float]) -> dict:
    if not values:
        return {"mean": 0, "p50": 0, "p95": 0, "p99": 0}
    return {
        "mean": round(statistics.mean(values), 2),
        "p50": round(percentile(values, 0.50), 2),
        "p95": round(percentile(values, 0.95), 2),
        "p99": round(percentile(values, 0.99), 2),
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

async def run_load_test(args: argparse.Namespace) -> None:
    url = args.supabase_url
    anon = args.anon_key
    srk = args.service_role_key
    access_token = args.access_token

    if not all([url, anon, srk]):
        log("Error: SUPABASE_URL, SUPABASE_ANON_KEY, and "
            "SUPABASE_SERVICE_ROLE_KEY are all required.")
        sys.exit(1)

    if not access_token:
        log("Error: SUPABASE_ACCESS_TOKEN is required "
            "(for CAPTCHA secret swap via Management API).")
        sys.exit(1)

    pdf_dir = Path(args.pdf_dir)
    pdfs = list(pdf_dir.glob("*.pdf"))
    if not pdfs:
        log(f"Error: No PDF files found in {pdf_dir}")
        sys.exit(1)
    log(f"Found {len(pdfs)} PDF(s) in {pdf_dir}")

    limits = httpx.Limits(
        max_connections=100, max_keepalive_connections=20
    )
    async with httpx.AsyncClient(
        limits=limits, timeout=httpx.Timeout(120.0)
    ) as http:
        # Swap CAPTCHA to test secret before running
        captcha_secret = os.environ.get("CAPTCHA_SECRET", "")
        original_captcha = await swap_captcha_to_test(
            http, access_token, url, captcha_secret
        )

        try:
            client = SupabaseClient(
                url, anon, srk, http, TURNSTILE_TEST_TOKEN
            )

            interval = 1.0 / args.rate
            tasks: list[asyncio.Task] = []
            start_time = time.monotonic()

            log(f"Spawning {args.users} users at {args.rate}/s "
                f"({interval:.1f}s apart), "
                f"max {args.max_sentences} sentences each, "
                f"{args.playback_speed}x speed")

            for i in range(args.users):
                pdf = random.choice(pdfs)
                task = asyncio.create_task(
                    run_user(
                        i, client, pdf,
                        args.max_sentences, args.parse_timeout,
                        args.playback_speed,
                    )
                )
                tasks.append(task)
                if i < args.users - 1:
                    await asyncio.sleep(interval)

            log(f"All {args.users} users spawned. "
                f"Waiting for completion...")
            results: list[UserResult] = await asyncio.gather(*tasks)
        finally:
            # Always restore the original CAPTCHA secret
            if original_captcha is not None:
                try:
                    await restore_captcha(
                        http, access_token, url, original_captcha
                    )
                except Exception as e:
                    log(f"WARNING: Failed to restore CAPTCHA secret: {e}")
                    log(f"Manually restore it in the Supabase dashboard!")

    total_duration = time.monotonic() - start_time

    # ── Build report ──
    succeeded = [r for r in results if r.error is None]
    failed = [r for r in results if r.error is not None]

    summary = {
        "users_completed": len(succeeded),
        "users_failed": len(failed),
        "first_page_time": stats_for(
            [r.first_page_time for r in succeeded if r.first_page_time > 0]
        ),
        "first_page_time_worker": stats_for(
            [r.first_page_time_worker for r in succeeded
             if r.first_page_time_worker > 0]
        ),
        "parse_total_time": stats_for([r.parse_total_time for r in succeeded]),
        "parse_queue_time": stats_for([r.parse_queue_time for r in succeeded]),
        "parse_processing_time": stats_for(
            [r.parse_processing_time for r in succeeded]
        ),
        "first_synthesis_latency": stats_for(
            [r.first_synthesis_latency for r in succeeded if r.sentences_played > 0]
        ),
        "synthesis_latency": stats_for(
            [l for r in succeeded for l in r.synthesis_latencies if l > 0]
        ),
        "total_buffering_time": stats_for(
            [r.total_buffering_time for r in succeeded if r.sentences_played > 0]
        ),
        "interruptions": stats_for(
            [float(r.interruptions) for r in succeeded if r.sentences_played > 0]
        ),
    }

    report = {
        "metadata": {
            "started_at": datetime.fromtimestamp(
                results[0].started_at, tz=timezone.utc
            ).isoformat() if results else None,
            "total_duration_seconds": round(total_duration, 1),
            "parameters": {
                "rate": args.rate,
                "users": args.users,
                "max_sentences": args.max_sentences,
                "pdf_dir": str(pdf_dir),
            },
        },
        "summary": summary,
        "users": [asdict(r) for r in results],
    }

    out_path = Path(args.output)
    out_path.write_text(json.dumps(report, indent=2))
    log(f"\nResults written to {out_path}")

    # ── Print summary ──
    log("\n" + "=" * 60)
    log("LOAD TEST SUMMARY")
    log("=" * 60)
    log(f"Users: {len(succeeded)} succeeded, {len(failed)} failed, "
        f"{total_duration:.0f}s total")

    for label, key in [
        ("First page ready", "first_page_time"),
        ("  (worker measured)", "first_page_time_worker"),
        ("Parse total", "parse_total_time"),
        ("  Queue time", "parse_queue_time"),
        ("  Processing", "parse_processing_time"),
        ("1st audio latency", "first_synthesis_latency"),
        ("Synthesis latency", "synthesis_latency"),
        ("Buffering time", "total_buffering_time"),
        ("Interruptions", "interruptions"),
    ]:
        s = summary[key]
        log(f"  {label:20s}  mean={s['mean']:6.1f}s  "
            f"p50={s['p50']:6.1f}s  p95={s['p95']:6.1f}s  p99={s['p99']:6.1f}s")

    if failed:
        log(f"\nFailed users:")
        for r in failed:
            log(f"  User {r.user_index}: {r.error} (reached: {r.phase_reached})")
    log("=" * 60)


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

async def run_cleanup(args: argparse.Namespace) -> None:
    url = args.supabase_url
    srk = args.service_role_key

    if not all([url, srk]):
        log("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required.")
        sys.exit(1)

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as http:
        client = SupabaseClient(url, "", srk, http, "")

        loadtest_users = []
        page = 1
        while True:
            users = await client.list_users(page=page, per_page=50)
            if not users:
                break
            for u in users:
                email = u.get("email", "")
                if email.startswith("loadtest+"):
                    loadtest_users.append(u)
            page += 1

        log(f"Found {len(loadtest_users)} loadtest user(s)")

        if not loadtest_users:
            return

        if args.dry_run:
            for u in loadtest_users:
                log(f"  [dry-run] Would delete: {u['email']} ({u['id']})")
            return

        for u in loadtest_users:
            uid = u["id"]
            email = u["email"]
            try:
                await client.delete_user_storage(uid)
                await client.admin_delete_user(uid)
                log(f"  Deleted {email}")
            except Exception as e:
                log(f"  Failed to delete {email}: {e}")

        log(f"Cleanup complete. Deleted {len(loadtest_users)} user(s).")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Load test for textbook-tts"
    )
    parser.add_argument(
        "--supabase-url",
        default=os.environ.get("SUPABASE_URL"),
    )
    parser.add_argument(
        "--anon-key",
        default=os.environ.get("SUPABASE_ANON_KEY"),
    )
    parser.add_argument(
        "--service-role-key",
        default=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
    )
    parser.add_argument(
        "--access-token",
        default=os.environ.get("SUPABASE_ACCESS_TOKEN"),
    )

    subs = parser.add_subparsers(dest="command")

    run_p = subs.add_parser("run", help="Run load test")
    run_p.add_argument("--rate", type=float, default=0.1,
                       help="New users per second (default: 0.1)")
    run_p.add_argument("--users", type=int, default=5,
                       help="Total users to spawn (default: 5)")
    run_p.add_argument("--pdf-dir", default="./test-pdfs",
                       help="Directory containing test PDFs")
    run_p.add_argument("--max-sentences", type=int, default=100,
                       help="Max sentences to play per user (default: 20)")
    run_p.add_argument("--parse-timeout", type=int,
                       default=DEFAULT_PARSE_TIMEOUT,
                       help="Parse timeout in seconds (default: 300)")
    run_p.add_argument("--output", default="output/loadtest-results.json",
                       help="Output JSON path (default: output/loadtest-results.json)")
    run_p.add_argument("--playback-speed", type=float, default=1.0,
                       help="Playback speed multiplier (default: 1.0)")

    cleanup_p = subs.add_parser("cleanup", help="Delete loadtest users")
    cleanup_p.add_argument("--dry-run", action="store_true",
                           help="List users without deleting")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "run":
        asyncio.run(run_load_test(args))
    elif args.command == "cleanup":
        asyncio.run(run_cleanup(args))


if __name__ == "__main__":
    main()
