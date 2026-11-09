"""Local web application for receipt intake and evidence preservation."""

from __future__ import annotations

import json
import logging
import os
from importlib.util import find_spec

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.ai_intelligence.provider import AIProvider, ReplitAIProvider
from app.ai_intelligence.routing import QuestionRejected, parse_question
from app.ai_intelligence.service import ask_history
from app.config import STATIC_DIR, Settings, load_settings, size_limit_message
from app.corrections.repository import init_corrections_db
from app.corrections.service import (
    CorrectionNotFound,
    CorrectionRejected,
    corrections_for_extraction,
    corrections_for_pattern,
    record_correction,
    suggestions_for_extraction,
)
from app.muse_ai.repository import init_muse_ai_db, read_audit
from app.muse_ai.service import (
    ingest_muse_extraction,
    queue_receipt,
    queue_status,
)
from app.muse_ai.validation import MusePayloadError
from app.pantry.repository import init_pantry_db
from app.pantry.service import (
    PantryNotFound,
    PantryRejected,
    add_from_purchase,
    add_manual_item,
    read_item_with_history,
    read_pantry,
    set_status,
)
from app.product_images.service import lookup_image
from app.purchase_analytics.service import build_analytics
from app.purchase_confirmation.confidence import assess_extraction
from app.purchase_memory.errors import MemoryNotFound, MemoryRejected, PurchaseNotFound
from app.purchase_memory.repository import init_memory_db
from app.purchase_memory.service import (
    correct_classification,
    read_memory,
    read_memory_list,
    remember_from_request,
    remember_purchase,
)
from app.purchase_confirmation.errors import AlreadyConfirmed, ConfirmationRejected, ExtractionNotFound
from app.purchase_confirmation.repository import get_purchase_for_extraction, init_confirmed_db
from app.purchase_confirmation.service import confirm_purchase, read_purchase
from app.receipt_extraction.errors import EvidenceNotFound
from app.receipt_extraction.models import ExtractionRecord
from app.receipt_extraction.repository import init_extraction_db
from app.receipt_extraction.service import extract_preserved_receipt, read_extraction
from app.receipt_intake.errors import IntakeRejected
from app.receipt_intake.models import parse_evidence_id
from app.receipt_intake.repository import get_evidence, init_db
from app.receipt_intake.service import preserve_upload
from app.receipt_intake.validation import declared_body_too_large, read_limited_upload
from app.visual_recall.repository import init_visual_db
from app.visual_recall.service import build_visual_recall, default_provider, read_enrichment_image

logger = logging.getLogger("purchase_intelligence.receipt_intake")
extraction_logger = logging.getLogger("purchase_intelligence.receipt_extraction")
confirmation_logger = logging.getLogger("purchase_intelligence.confirmation")
memory_logger = logging.getLogger("purchase_intelligence.memory")
analytics_logger = logging.getLogger("purchase_intelligence.analytics")
visual_logger = logging.getLogger("purchase_intelligence.visual_recall")

_GENERIC_FAILURE = "The upload could not be processed."


def create_app(
    settings: Settings | None = None, image_provider: object | None = None,
    ai_provider: AIProvider | None = None,
) -> FastAPI:
    settings = settings or load_settings()
    provider = default_provider() if image_provider is None else image_provider
    intelligence_provider = ai_provider if ai_provider is not None else ReplitAIProvider()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.files_dir.mkdir(parents=True, exist_ok=True)
    init_db(settings.db_path)
    init_extraction_db(settings)
    init_confirmed_db(settings)
    init_memory_db(settings)
    init_visual_db(settings)
    init_pantry_db(settings)
    init_corrections_db(settings)
    init_muse_ai_db(settings)
    muse_ai_logger = logging.getLogger("purchase_intelligence.muse_ai")

    app = FastAPI(
        title="Purchase Intelligence",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        if not settings.allow_preview_embedding:
            response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        frame_policy = (
            "'self' https://replit.com https://*.replit.com https://*.replit.dev"
            if settings.allow_preview_embedding else "'none'"
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self'; script-src 'self'; "
            f"img-src 'self' data:; frame-ancestors {frame_policy}; base-uri 'none'"
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def reject_malformed_request(request: Request, exc: RequestValidationError):
        return _rejected(
            "The upload could not be processed. Choose a receipt image and try again."
        )

    def page(filename: str, active: str) -> str:
        """Reuse one navigation fragment without a template/build dependency."""
        navigation = (STATIC_DIR / "nav.html").read_text(encoding="utf-8")
        for section in ("overview", "memory", "analytics", "food", "ask", "intake"):
            navigation = navigation.replace(
                f"__ACTIVE_{section.upper()}__",
                'aria-current="page"' if section == active else "",
            )
        template = (STATIC_DIR / filename).read_text(encoding="utf-8")
        return template.replace("__NAV__", navigation).replace(
            "__MAX_MB__", str(settings.max_upload_megabytes),
        )

    @app.get("/", response_class=HTMLResponse)
    def overview() -> str:
        return page("overview.html", "overview")

    @app.get("/intake", response_class=HTMLResponse)
    def receipt_intake_page() -> str:
        return page("index.html", "intake")

    @app.get("/api/ai-status")
    def ai_capability_status() -> JSONResponse:
        # Configuration only: no model request, key exposure or health promise.
        configured = (
            bool(os.environ.get("AI_INTEGRATIONS_OPENAI_BASE_URL"))
            and bool(os.environ.get("AI_INTEGRATIONS_OPENAI_API_KEY"))
            and find_spec("openai") is not None
        )
        return JSONResponse(content={
            "status": "configured" if configured else "unavailable",
            "provider": intelligence_provider.name,
            "model": intelligence_provider.model,
            "health_verified": False,
        })

    @app.post("/api/receipts")
    async def intake_receipt(
        request: Request,
        file: UploadFile | None = File(default=None),
    ) -> JSONResponse:
        if declared_body_too_large(request.headers.get("content-length"), settings.max_upload_bytes):
            logger.info("receipt rejected reason=declared_size")
            return _rejected(size_limit_message(settings.max_upload_bytes))
        if file is None:
            logger.info("receipt rejected reason=missing_file")
            return _rejected("No file was provided.")
        try:
            content = await read_limited_upload(file, settings.max_upload_bytes)
            record = preserve_upload(content, file.filename, settings)
        except IntakeRejected as exc:
            logger.info("receipt rejected reason=%s", exc.reason)
            return _rejected(exc.reason)
        except Exception:
            logger.exception("receipt intake failed")
            return _rejected(_GENERIC_FAILURE, status_code=500)

        logger.info(
            "receipt accepted evidence_id=%s mime_type=%s byte_size=%s",
            record.evidence_id,
            record.mime_type,
            record.byte_size,
        )
        return JSONResponse(status_code=201, content=record.to_public_dict())

    @app.post("/api/receipts/{evidence_id}/extraction")
    async def extract_receipt(evidence_id: str) -> JSONResponse:
        try:
            record = await extract_preserved_receipt(settings, evidence_id)
        except EvidenceNotFound:
            extraction_logger.info("extraction rejected reason=evidence_not_found")
            return _not_found()
        except Exception:
            extraction_logger.exception("extraction failed")
            return JSONResponse(
                status_code=500,
                content={"status": "failed", "reason": "The receipt could not be read."},
            )
        extraction_logger.info(
            "extraction finished evidence_id=%s status=%s line_count=%s",
            record.evidence_id,
            record.extraction_status,
            len(record.lines),
        )
        status_code = 422 if record.extraction_status == "failed" else 200
        return JSONResponse(status_code=status_code, content=_reviewed_extraction(settings, record))

    @app.get("/api/receipts/{evidence_id}/extraction")
    def read_saved_extraction(evidence_id: str) -> JSONResponse:
        try:
            record = read_extraction(settings, evidence_id)
        except EvidenceNotFound:
            return _not_found()
        if record is None:
            return JSONResponse(
                status_code=404,
                content={"status": "not_found", "reason": "No extraction exists for this receipt."},
            )
        return JSONResponse(status_code=200, content=_reviewed_extraction(settings, record))

    @app.post("/api/receipts/{evidence_id}/muse-ai")
    def queue_muse_ai(evidence_id: str) -> JSONResponse:
        """Queue a receipt for Muse to read. Tim polls the queue over SSH."""
        try:
            record = queue_receipt(settings, evidence_id)
        except EvidenceNotFound:
            return _not_found()
        muse_ai_logger.info("muse-ai queued evidence_id=%s", evidence_id)
        return JSONResponse(status_code=202, content=record.to_public_dict())

    @app.get("/api/receipts/{evidence_id}/muse-ai")
    def read_muse_ai_status(evidence_id: str) -> JSONResponse:
        record = queue_status(settings, evidence_id)
        if record is None:
            return JSONResponse(
                status_code=404,
                content={"status": "not_found", "reason": "This receipt is not queued for Muse AI."},
            )
        payload = record.to_public_dict()
        if record.extraction_id:
            audit = read_audit(settings, record.extraction_id)
            if audit is not None:
                payload["totals_reconciled"] = audit.totals_reconciled
                payload["total_mismatch"] = audit.total_mismatch
                payload["lines_sum"] = audit.lines_sum
        return JSONResponse(status_code=200, content=payload)

    @app.post("/api/receipts/{evidence_id}/muse-ai/ingest")
    async def ingest_muse_ai(evidence_id: str, request: Request) -> JSONResponse:
        """Store a Muse extraction as the receipt's unconfirmed candidate."""
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return JSONResponse(
                status_code=400,
                content={"status": "rejected", "reason": "The extraction could not be read."},
            )
        try:
            record, audit = ingest_muse_extraction(settings, evidence_id, payload)
        except EvidenceNotFound:
            return _not_found()
        except MusePayloadError as exc:
            muse_ai_logger.info("muse-ai ingest rejected evidence_id=%s reason=%s", evidence_id, exc)
            return JSONResponse(
                status_code=422,
                content={"status": "rejected", "reason": str(exc)},
            )
        muse_ai_logger.info(
            "muse-ai ingested evidence_id=%s extraction_id=%s lines=%s reconciled=%s",
            evidence_id,
            record.extraction_id,
            len(record.lines),
            audit.totals_reconciled,
        )
        content = _reviewed_extraction(settings, record)
        content["muse_ai"] = {
            "source": "muse_ai",
            "totals_reconciled": audit.totals_reconciled,
            "total_mismatch": audit.total_mismatch,
            "lines_sum": audit.lines_sum,
        }
        return JSONResponse(status_code=200, content=content)

    @app.post("/api/purchases")
    async def confirm_reviewed_purchase(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return _confirmation_rejected("The confirmation could not be read.")
        try:
            purchase = confirm_purchase(settings, payload)
        except EvidenceNotFound:
            confirmation_logger.info("confirmation rejected reason=evidence_not_found")
            return _not_found()
        except ExtractionNotFound:
            confirmation_logger.info("confirmation rejected reason=extraction_not_found")
            return JSONResponse(
                status_code=404,
                content={"status": "not_found", "reason": "The extraction was not found."},
            )
        except AlreadyConfirmed as exc:
            confirmation_logger.info("confirmation rejected reason=already_confirmed")
            return JSONResponse(
                status_code=409,
                content={
                    "status": "rejected",
                    "reason": "This extraction is already confirmed.",
                    "purchase_id": exc.purchase_id,
                },
            )
        except ConfirmationRejected as exc:
            confirmation_logger.info("confirmation rejected")
            return _confirmation_rejected(exc.reason)
        except Exception:
            confirmation_logger.exception("confirmation failed")
            return _confirmation_rejected("The purchase could not be confirmed.", status_code=500)
        confirmation_logger.info(
            "purchase confirmed purchase_id=%s evidence_id=%s item_count=%s",
            purchase.purchase_id,
            purchase.evidence_id,
            len(purchase.items),
        )
        try:
            memory, _created = remember_purchase(settings, purchase.purchase_id)
        except Exception:
            confirmation_logger.exception("purchase history was not saved")
            return _confirmation_rejected(
                "The purchase was confirmed, but purchase history could not be saved.",
                status_code=500,
            )
        try:
            pantry_items = add_from_purchase(settings, purchase)
        except Exception:
            confirmation_logger.exception("pantry update failed")
            return _confirmation_rejected(
                "The purchase was confirmed, but the pantry could not be updated.",
                status_code=500,
            )
        payload = purchase.to_public_dict()
        payload["memory_id"] = memory.memory_id
        payload["pantry_items"] = [item.to_public_dict() for item in pantry_items]
        payload["applied_corrections"] = [
            correction.to_public_dict()
            for correction in corrections_for_extraction(settings, purchase.extraction_id)
        ]
        return JSONResponse(status_code=201, content=payload)

    @app.get("/api/purchases/{purchase_id}")
    def read_confirmed_purchase(purchase_id: str) -> JSONResponse:
        purchase = read_purchase(settings, purchase_id)
        if purchase is None:
            return JSONResponse(
                status_code=404,
                content={"status": "not_found", "reason": "The confirmed purchase was not found."},
            )
        payload = purchase.to_public_dict()
        payload["applied_corrections"] = [
            correction.to_public_dict()
            for correction in corrections_for_extraction(settings, purchase.extraction_id)
        ]
        order = {item.purchase_item_id: index for index, item in enumerate(purchase.items)}
        payload["pantry_items"] = [
            item.to_public_dict()
            for item in sorted(
                (item for item in read_pantry(settings, None) if item.purchase_id == purchase_id),
                key=lambda item: order.get(item.purchase_item_id, 0),
            )
        ]
        return JSONResponse(status_code=200, content=payload)

    # Locked API aliases (Nov 4, 2026 spec). Same handlers, no new logic.
    @app.post("/api/receipts/{evidence_id}/extract")
    async def extract_receipt_alias(evidence_id: str) -> JSONResponse:
        return await extract_receipt(evidence_id)

    @app.get("/api/extractions/{extraction_id}")
    def read_extraction_by_id(extraction_id: str) -> JSONResponse:
        from app.receipt_extraction.repository import get_extraction_by_id

        record = get_extraction_by_id(settings, extraction_id)
        if record is None:
            return JSONResponse(
                status_code=404,
                content={"status": "not_found", "reason": "The extraction was not found."},
            )
        return JSONResponse(status_code=200, content=_reviewed_extraction(settings, record))

    @app.post("/api/purchases/confirm")
    async def confirm_purchase_alias(request: Request) -> JSONResponse:
        return await confirm_reviewed_purchase(request)

    @app.get("/api/analytics/weekly")
    def read_weekly_analytics() -> JSONResponse:
        from collections import defaultdict
        from datetime import date as _date
        from decimal import Decimal, InvalidOperation

        from app.purchase_memory.repository import list_memories

        weekly: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for entry in list_memories(settings, None):
            day = entry.purchase_date
            try:
                parsed = _date.fromisoformat(day) if day else None
            except ValueError:
                parsed = None
            if parsed is None:
                continue
            iso_year, iso_week, _ = parsed.isocalendar()
            for item in entry.items:
                try:
                    weekly[f"{iso_year}-W{iso_week:02d}"] += Decimal(str(item.line_total or 0))
                except (TypeError, ValueError, InvalidOperation):
                    continue
        return JSONResponse(
            status_code=200,
            content={
                "status": "ok",
                "weekly_spending": {key: float(value) for key, value in sorted(weekly.items())},
            },
        )

    @app.get("/api/analytics/most-bought")
    def read_most_bought_analytics() -> JSONResponse:
        report = build_analytics(settings)
        items = [
            {
                "item_name": item["item_name"],
                "occurrence_count": item["occurrence_count"],
                "first_purchase_date": item["first_purchase_date"],
                "latest_purchase_date": item["latest_purchase_date"],
            }
            for item in report.get("repeat_items", [])
        ]
        return JSONResponse(status_code=200, content={"status": "ok", "most_bought": items})

    # Product photos: seeded mapping first, then Open Beauty Facts /
    # Open Food Facts by UPC, then by name. No photo found is a plain
    # "not_found" — the display shows a placeholder, never a wrong photo.
    @app.get("/api/products/image")
    def read_product_image(upc: str | None = None, name: str | None = None) -> JSONResponse:
        return JSONResponse(status_code=200, content=lookup_image(upc=upc, name=name))

    # Pantry: What's in the house. Single user, no auth, no deletion.
    @app.get("/api/pantry")
    def list_pantry(status: str | None = None) -> JSONResponse:
        try:
            items = read_pantry(settings, status)
        except PantryRejected as exc:
            return JSONResponse(status_code=400, content={"status": "rejected", "reason": exc.reason})
        return JSONResponse(
            status_code=200,
            content={"status": "ok", "items": [item.to_public_dict() for item in items]},
        )

    @app.post("/api/pantry")
    async def add_pantry_item(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return JSONResponse(status_code=400, content={"status": "rejected", "reason": "The item could not be read."})
        try:
            item = add_manual_item(settings, payload)
        except PantryRejected as exc:
            return JSONResponse(status_code=400, content={"status": "rejected", "reason": exc.reason})
        return JSONResponse(status_code=201, content=item.to_public_dict())

    @app.get("/api/pantry/{pantry_item_id}")
    def read_pantry_item(pantry_item_id: str) -> JSONResponse:
        payload = read_item_with_history(settings, pantry_item_id)
        if payload is None:
            return JSONResponse(status_code=404, content={"status": "not_found", "reason": "The pantry item was not found."})
        return JSONResponse(status_code=200, content=payload)

    @app.post("/api/pantry/{pantry_item_id}/status")
    async def update_pantry_status(pantry_item_id: str, request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return JSONResponse(status_code=400, content={"status": "rejected", "reason": "The status could not be read."})
        try:
            item = set_status(settings, pantry_item_id, payload)
        except PantryNotFound:
            return JSONResponse(status_code=404, content={"status": "not_found", "reason": "The pantry item was not found."})
        except PantryRejected as exc:
            return JSONResponse(status_code=400, content={"status": "rejected", "reason": exc.reason})
        return JSONResponse(status_code=200, content=item.to_public_dict())

    # Correction log: record only. Never modifies the extraction.
    @app.post("/api/extractions/{extraction_id}/correct")
    async def correct_extraction(extraction_id: str, request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return JSONResponse(status_code=400, content={"status": "rejected", "reason": "The correction could not be read."})
        try:
            correction = record_correction(settings, extraction_id, payload)
        except CorrectionNotFound:
            return JSONResponse(status_code=404, content={"status": "not_found", "reason": "The extraction was not found."})
        except CorrectionRejected as exc:
            return JSONResponse(status_code=400, content={"status": "rejected", "reason": exc.reason})
        return JSONResponse(status_code=201, content=correction.to_public_dict())

    @app.get("/api/corrections")
    def list_corrections(pattern: str | None = None) -> JSONResponse:
        corrections = corrections_for_pattern(settings, pattern) if pattern else []
        if pattern is None:
            from app.corrections.repository import list_corrections as _list_all

            corrections = _list_all(settings)
        return JSONResponse(
            status_code=200,
            content={"status": "ok", "corrections": [c.to_public_dict() for c in corrections]},
        )

    @app.get("/memory", response_class=HTMLResponse)
    def purchase_history() -> str:
        return page("memory.html", "memory")

    @app.get("/ask", response_class=HTMLResponse)
    def ask_page() -> str:
        return page("ask.html", "ask")

    @app.post("/api/ask")
    async def ask_purchase_history(request: Request) -> JSONResponse:
        if request.query_params or request.headers.get("content-type", "").split(";")[0] != "application/json":
            return _rejected("Submit only a JSON question.")
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 4096:
                return _rejected("The question request is too large.")
        try:
            question = parse_question(json.loads(raw))
        except (json.JSONDecodeError, UnicodeError):
            return _rejected("The question could not be read.")
        except QuestionRejected as exc:
            return _rejected(str(exc))
        try:
            result = await ask_history(settings, question, intelligence_provider)
        except Exception:
            # Preserve existing capabilities and avoid leaking questions/data/paths.
            logging.getLogger("purchase_intelligence.ai").error("ai context unavailable")
            return JSONResponse(status_code=503, content={
                "status": "rejected", "reason": "Purchase history could not be read. Try again later.",
            })
        return JSONResponse(status_code=200, content=result.to_public_dict())

    @app.get("/analytics", response_class=HTMLResponse)
    def purchase_patterns() -> str:
        return page("analytics.html", "analytics")

    @app.get("/api/analytics")
    def read_purchase_analytics(request: Request) -> JSONResponse:
        if request.query_params:
            return _analytics_rejected("That analytics request is not supported.")
        report = build_analytics(settings)
        summary = report["summary"]
        analytics_logger.info(
            "analytics calculated purchases=%s items=%s",
            summary["remembered_purchases"],
            summary["remembered_items"],
        )
        return JSONResponse(status_code=200, content=report)

    @app.get("/food-recall", response_class=HTMLResponse)
    def food_recall() -> str:
        return page("food-recall.html", "food")

    @app.get("/api/visual-recall")
    def read_visual_recall(view: str | None = None) -> JSONResponse:
        try:
            report = build_visual_recall(settings, provider, view)
        except ValueError:
            return _visual_rejected("That food recall view is not supported.")
        except Exception:
            visual_logger.exception("visual recall failed")
            return _visual_rejected("Food recall could not be loaded.", status_code=500)
        visual_logger.info("visual recall items=%s", len(report["items"]))
        return JSONResponse(status_code=200, content=report)

    @app.get("/api/visual-recall/enrichments/{enrichment_id}/image")
    def read_visual_image(enrichment_id: str) -> Response:
        content = read_enrichment_image(settings, provider, enrichment_id)
        if content is None:
            return JSONResponse(
                status_code=404,
                content={"status": "not_found", "reason": "The food image was not found."},
            )
        return Response(content=content, media_type="image/svg+xml")

    @app.post("/api/memory")
    async def remember_confirmed_purchase(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return _memory_rejected("The memory request could not be read.")
        try:
            memory, created = remember_from_request(settings, payload)
        except PurchaseNotFound:
            memory_logger.info("memory rejected reason=purchase_not_found")
            return JSONResponse(
                status_code=404,
                content={"status": "not_found", "reason": "The confirmed purchase was not found."},
            )
        except MemoryRejected as exc:
            memory_logger.info("memory rejected")
            return _memory_rejected(exc.reason)
        except Exception:
            memory_logger.exception("memory creation failed")
            return _memory_rejected("The purchase could not be remembered.", status_code=500)
        memory_logger.info(
            "memory %s memory_id=%s purchase_id=%s item_count=%s",
            "created" if created else "reused",
            memory.memory_id,
            memory.purchase_id,
            len(memory.items),
        )
        return JSONResponse(status_code=201 if created else 200, content=memory.to_public_dict())

    @app.get("/api/memory")
    def list_purchase_history(filter: str | None = None) -> JSONResponse:
        try:
            entries = read_memory_list(settings, filter)
        except MemoryRejected as exc:
            return _memory_rejected(exc.reason)
        return JSONResponse(
            status_code=200,
            content={"status": "ok", "purchases": [entry.to_summary_dict() for entry in entries]},
        )

    @app.get("/api/memory/{memory_id}")
    def read_remembered_purchase(memory_id: str) -> JSONResponse:
        memory = read_memory(settings, memory_id)
        if memory is None:
            return JSONResponse(
                status_code=404,
                content={"status": "not_found", "reason": "The remembered purchase was not found."},
            )
        return JSONResponse(status_code=200, content=memory.to_public_dict())

    @app.patch("/api/memory/{memory_id}/items/{memory_item_id}")
    async def correct_item_classification(
        memory_id: str,
        memory_item_id: str,
        request: Request,
    ) -> JSONResponse:
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return _memory_rejected("The classification could not be read.")
        try:
            memory = correct_classification(settings, memory_id, memory_item_id, payload)
        except MemoryNotFound:
            memory_logger.info("classification rejected reason=memory_not_found")
            return JSONResponse(
                status_code=404,
                content={"status": "not_found", "reason": "The remembered purchase was not found."},
            )
        except MemoryRejected as exc:
            memory_logger.info("classification rejected")
            return _memory_rejected(exc.reason)
        except Exception:
            memory_logger.exception("classification update failed")
            return _memory_rejected("The classification could not be saved.", status_code=500)
        return JSONResponse(status_code=200, content=memory.to_public_dict())

    @app.get("/api/receipts/{evidence_id}")
    def read_receipt(evidence_id: str) -> JSONResponse:
        canonical = parse_evidence_id(evidence_id)
        if canonical is None:
            return _not_found()
        record = get_evidence(settings, canonical)
        if record is None:
            return _not_found()
        return JSONResponse(status_code=200, content=record.to_public_dict())

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


def _reviewed_extraction(settings: Settings, record: ExtractionRecord) -> dict[str, object]:
    payload = record.to_public_dict()
    payload["suggestions"] = suggestions_for_extraction(settings, record)
    payload["corrections"] = [
        correction.to_public_dict() for correction in corrections_for_extraction(settings, record.extraction_id)
    ]
    payload["confidence"] = assess_extraction(record)
    existing = get_purchase_for_extraction(settings, record.extraction_id)
    payload["confirmation_state"] = "confirmed" if existing else "unconfirmed"
    payload["purchase_id"] = existing.purchase_id if existing else None
    return payload


def _visual_rejected(reason: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"status": "rejected", "reason": reason})


def _analytics_rejected(reason: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"status": "rejected", "reason": reason})


def _memory_rejected(reason: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"status": "rejected", "reason": reason})


def _confirmation_rejected(reason: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"status": "rejected", "reason": reason})


def _rejected(reason: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"status": "rejected", "reason": reason})


def _not_found() -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"status": "not_found", "reason": "Receipt evidence was not found."},
    )


app = create_app()
