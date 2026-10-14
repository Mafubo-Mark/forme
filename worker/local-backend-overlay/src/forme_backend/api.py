from __future__ import annotations

import hashlib
import hmac
import fcntl
import json
import math
import re
import sqlite3
import subprocess
import uuid
from pathlib import Path

from fastapi import BackgroundTasks, Cookie, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import Settings
from .cover_automation import prepare_task, task_status
from .concept_cover import CoverGateError, approve_registration, build_candidate
from .hunyuan_pro import archive as archive_hunyuan_result, poll as poll_hunyuan_job, submit as submit_hunyuan_job
from .production_flow import FlowError, digest, prepare_hunyuan_input, workflow_snapshot, write_json
from .store import Store
from .worker import validate_claimed
from .view_review import SLOTS, classify, prepare


class UploadInit(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str
    byte_size: int = Field(gt=0)


class CaptureDecision(BaseModel):
    approved: bool
    notes: str = Field(min_length=5, max_length=2000)


class SubmissionCreate(BaseModel):
    upload_id: str
    color: str
    material: str
    template_id: str = "01"
    inspiration: str = Field(default="", max_length=500)


class CustomerLogin(BaseModel):
    access_key: str = Field(min_length=1, max_length=256)


class ViewClassify(BaseModel):
    front_anchor: str | None = None


class ViewSelection(BaseModel):
    selections: dict[str, str]
    notes: str = Field(min_length=5, max_length=2000)


class CoverTaskCreate(BaseModel):
    template_id: str = Field(pattern=r"^[a-z0-9-]{1,40}$")


class RulerObservation(BaseModel):
    name: str = Field(pattern=r"^frame_[0-9]{4}\.jpg$")
    A: tuple[float, float]
    B: tuple[float, float]


class RulerCalibrationInput(BaseModel):
    images: list[RulerObservation] = Field(min_length=3, max_length=40)


class ConceptBuildInput(BaseModel):
    candidate_id: str = Field(pattern=r"^[a-z0-9_-]{1,40}$")
    proposal: dict


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    store = Store(settings.data_dir)
    app = FastAPI(title="Forme workflow API", version="0.1.0")
    operator_cookie = uuid.uuid4().hex

    def authorized(authorization: str | None = Header(default=None)) -> None:
        expected = f"Bearer {settings.dev_token}"
        if authorization is None or not hmac.compare_digest(authorization, expected):
            raise HTTPException(401, detail={"code": "UNAUTHORIZED"})

    def customer_session(forme_customer: str | None = Cookie(default=None)) -> str:
        if not forme_customer or not store.session_exists(forme_customer):
            raise HTTPException(401, detail={"code": "CUSTOMER_SESSION_REQUIRED"})
        return forme_customer

    def customer_or_admin(
        authorization: str | None = Header(default=None),
        forme_customer: str | None = Cookie(default=None),
    ) -> str | None:
        if authorization and hmac.compare_digest(authorization, f"Bearer {settings.dev_token}"):
            return None
        if forme_customer and store.session_exists(forme_customer):
            return forme_customer
        raise HTTPException(401, detail={"code": "UNAUTHORIZED"})

    def operator_media_auth(
        authorization: str | None = Header(default=None),
        forme_operator: str | None = Cookie(default=None),
    ) -> None:
        bearer_ok = authorization is not None and hmac.compare_digest(authorization, f"Bearer {settings.dev_token}")
        cookie_ok = forme_operator is not None and hmac.compare_digest(forme_operator, operator_cookie)
        if not bearer_ok and not cookie_ok:
            raise HTTPException(401, detail={"code": "UNAUTHORIZED"})

    def existing(upload_id: str, session_id: str | None = None) -> dict:
        upload = store.get_upload(upload_id)
        if upload is None:
            raise HTTPException(404, detail={"code": "UPLOAD_NOT_FOUND"})
        if session_id is not None and upload["session_id"] != session_id:
            raise HTTPException(404, detail={"code": "UPLOAD_NOT_FOUND"})
        return upload

    def existing_submission(submission_id: str, session_id: str | None = None) -> dict:
        submission = store.get_submission(submission_id)
        if submission is None or (session_id is not None and submission["session_id"] != session_id):
            raise HTTPException(404, detail={"code": "SUBMISSION_NOT_FOUND"})
        return submission

    def hunyuan_job(submission_id: str) -> dict | None:
        root = settings.data_dir / "cover_tasks" / submission_id / "hunyuan_inputs"
        record_path = root / "hunyuan_job.json"
        if not record_path.is_file():
            return None
        record = json.loads(record_path.read_text())
        worker_error_path = root / "hunyuan_worker_error.json"
        worker_error = json.loads(worker_error_path.read_text(encoding="utf-8")) if worker_error_path.is_file() else None
        preview = root / "hunyuan_result" / "preview_00.png"
        model = root / "hunyuan_result" / "result_00.glb"
        alignment_path = root.parent / "alignment" / "alignment_report.json"
        alignment = json.loads(alignment_path.read_text()) if alignment_path.is_file() else None
        preflight_path = root.parent / "template_physical_preflight.json"
        preflight = json.loads(preflight_path.read_text()) if preflight_path.is_file() else None
        ruler_path = root.parent / "ruler_only_assessment.json"
        ruler = json.loads(ruler_path.read_text()) if ruler_path.is_file() else None
        cloud_qa_path = root.parent / "pointcloud_qa.json"
        cloud_qa = json.loads(cloud_qa_path.read_text()) if cloud_qa_path.is_file() else None
        concept_root = root.parent / "ruler_only_template01_concept"
        concept_report_path = concept_root / "build_report.json"
        concept_report = json.loads(concept_report_path.read_text()) if concept_report_path.is_file() else None
        concept_glb = concept_root / "template01_ruler_visual.glb"
        hybrid_v2_root = root.parent / "workbuddy_hybrid_v2"
        hybrid_root = hybrid_v2_root if (hybrid_v2_root / "build_report.json").is_file() else root.parent / "workbuddy_hybrid_v1"
        hybrid_report_path = hybrid_root / "build_report.json"
        hybrid_report = json.loads(hybrid_report_path.read_text()) if hybrid_report_path.is_file() else None
        hybrid_is_v2 = hybrid_root == hybrid_v2_root
        hybrid_preview = hybrid_root / ("xiangyun_rim_fixed_v2_preview.glb" if hybrid_is_v2 else "xiangyun_hybrid_v1_preview.glb")
        print_root = root.parent / "print_prototype_v1"
        print_report_path = print_root / "build_report.json"
        print_report = json.loads(print_report_path.read_text()) if print_report_path.is_file() else None
        return {
            "status": record.get("status"), "jobId": record.get("jobId"),
            "model": record.get("model"), "region": record.get("region"),
            "submittedViews": record.get("submittedViews", []),
            "reviewOnlyViews": record.get("reviewOnlyViews", []),
            "submittedAt": record.get("submittedAt"), "lastQueryAt": record.get("lastQueryAt"),
            "workerError": worker_error.get("error") if worker_error else None,
            "previewUrl": f"/api/internal/submissions/{submission_id}/hunyuan/preview" if preview.is_file() else None,
            "modelUrl": f"/api/internal/submissions/{submission_id}/hunyuan/model" if model.is_file() else None,
            "geometryVerified": False, "scaleVerified": False, "coverFitVerified": False,
            "geometryReview": record.get("geometryReview"),
            "alignment": None if alignment is None else {
                "status": alignment["status"], "whiteMedianMm": alignment["best"]["whiteMedianMm"],
                "blackMedianMm": alignment["best"]["blackMedianMm"],
                "derivedShaftWidthMm": alignment["derivedShaftWidthMm"],
                "frontOverlayUrl": f"/api/internal/submissions/{submission_id}/hunyuan/alignment/front",
                "sideOverlayUrl": f"/api/internal/submissions/{submission_id}/hunyuan/alignment/side",
            },
            "templatePreflight": None if preflight is None else {
                "status": preflight["status"],
                "conditionalUpperWidthDeficitMm": None if ruler else preflight["conditionalWidthScreen"]["remainingDeficitMm"],
                "registrationVerified": preflight["registration"]["verified"],
            },
            "rulerOnlyAssessment": None if ruler is None else {
                "status": ruler["status"],
                "knownTargetLengthMm": ruler["calibration"]["knownTargetLengthMm"],
                "primaryMmPerColmapUnit": ruler["calibration"]["primaryMmPerColmapUnit"],
                "reconstructionScaleSpreadPercent": ruler["calibration"]["reconstructionScaleSpreadPercent"],
                "visibleAxialSpanMm": ruler["candidateGeometry"]["visibleAxialSpanMm"],
                "fitVerified": ruler["fitVerified"],
            },
            "pointcloudQa": None if cloud_qa is None else {
                "status": cloud_qa["status"],
                "provenanceVerified": cloud_qa["provenanceVerified"],
                "surfaceFitVerified": cloud_qa["surfaceFitVerified"],
                "fullyOccupiedSections": len(cloud_qa["sampling"]["fullyOccupiedSections"]),
                "totalSections": len(cloud_qa["sampling"]["sections"]),
                "sparseLowerSections": cloud_qa["sampling"]["sparseLowerSections"],
                "sparseUpperSections": cloud_qa["sampling"]["sparseUpperSections"],
                "imageConsistency": None if not cloud_qa.get("imageConsistency") else {
                    "status": cloud_qa["imageConsistency"]["status"],
                    "frameCount": cloud_qa["imageConsistency"]["frameCount"],
                    "uprightFrameCount": cloud_qa["imageConsistency"]["uprightFrameCount"],
                    "uprightMedianSilhouetteIoU": cloud_qa["imageConsistency"]["uprightMedianSilhouetteIoU"],
                    "topInteriorComplete": cloud_qa["imageConsistency"]["topInteriorComplete"],
                    "contactSheetUrl": f"/api/internal/submissions/{submission_id}/pointcloud-qa/contact-sheet",
                },
            },
            "visualConcept": None if concept_report is None or not concept_glb.is_file() else {
                "status": concept_report["status"],
                "templateId": concept_report["templateId"],
                "modelUrl": f"/api/internal/submissions/{submission_id}/cover-concept/model",
                "frontPreviewUrl": f"/api/internal/submissions/{submission_id}/cover-concept/front"
                if (concept_root / "review_front.png").is_file() else None,
                "threeQuarterPreviewUrl": f"/api/internal/submissions/{submission_id}/cover-concept/three_quarter"
                if (concept_root / "review_three_quarter.png").is_file() else None,
                "maxExteriorEnvelopeShortfallMm": concept_report["maxExteriorEnvelopeShortfallMm"],
                "registrationVerified": concept_report["registration"]["verified"],
                "fitVerified": concept_report["fitVerified"],
                "manufacturingApproved": concept_report["manufacturingApproved"],
            },
            "workbuddyHybrid": None if hybrid_report is None or not hybrid_preview.is_file() else {
                "status": hybrid_report["status"],
                "templateId": hybrid_report["templateId"],
                "version": 2 if hybrid_is_v2 else 1,
                "previewModelUrl": f"/api/internal/submissions/{submission_id}/workbuddy-hybrid/model",
                "frontPreviewUrl": f"/api/internal/submissions/{submission_id}/workbuddy-hybrid/front",
                "sidePreviewUrl": f"/api/internal/submissions/{submission_id}/workbuddy-hybrid/side",
                "topPreviewUrl": f"/api/internal/submissions/{submission_id}/workbuddy-hybrid/top",
                "overlayUrl": f"/api/internal/submissions/{submission_id}/workbuddy-hybrid/overlay",
                "fitVerified": hybrid_report["fitVerified"] if hybrid_is_v2 else hybrid_report["acceptance_flags"]["fit_verified"],
                "hunyuanGeometryFused": False,
                "trustedBandSilhouetteIoU": hybrid_report["trustedBandSilhouetteIoU"] if hybrid_is_v2 else hybrid_report["per_height_outer_contour_error"]["front_silhouette_iou_vs_cloud"]["trusted_band_90_280"],
            },
            "printPrototype": None if print_report is None else {
                "status": print_report["status"],
                "requiredBuildHeightMm": print_report["requiredBuildHeightMm"],
                "frontUrl": f"/api/internal/submissions/{submission_id}/print-prototype/front",
                "rearUrl": f"/api/internal/submissions/{submission_id}/print-prototype/rear",
                "packageUrl": f"/api/internal/submissions/{submission_id}/print-prototype/package",
                "fitVerified": False,
                "sideOpeningThinEdge": True,
            },
        }

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/api/customer/login")
    def login_customer(payload: CustomerLogin, response: Response) -> dict:
        if not settings.customer_access_key:
            raise HTTPException(503, detail={"code": "CUSTOMER_LOGIN_NOT_CONFIGURED"})
        if not hmac.compare_digest(payload.access_key, settings.customer_access_key):
            raise HTTPException(401, detail={"code": "INVALID_ACCESS_KEY"})
        session_id = str(uuid.uuid4())
        store.create_session(session_id)
        # Clear the earlier anonymous cookie, which was issued at the root path.
        response.delete_cookie("forme_customer", path="/")
        response.set_cookie("forme_customer", session_id, httponly=True, secure=settings.secure_customer_cookie,
                            samesite="strict", path="/api", max_age=7 * 24 * 3600)
        return {"status": "ready"}

    @app.get("/api/customer/session")
    def get_customer_session(session_id: str = Depends(customer_session)) -> dict:
        return {"status": "ready"}

    @app.get("/api/customer/templates")
    def customer_templates(session_id: str = Depends(customer_session)) -> dict:
        catalog_path = Path(__file__).resolve().parents[3] / "work-buddy-handoff" / "templates" / "catalog.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        return {"items": [{"id": item["id"], "name": item["name"]} for item in catalog["templates"]]}

    @app.post("/api/customer/logout")
    def logout_customer(response: Response, session_id: str = Depends(customer_session)) -> dict:
        store.revoke_session(session_id)
        response.delete_cookie("forme_customer", path="/api", secure=settings.secure_customer_cookie, samesite="strict")
        return {"status": "signed_out"}

    @app.post("/api/internal/connect", dependencies=[Depends(authorized)])
    def connect_operator(response: Response) -> dict:
        response.set_cookie("forme_operator", operator_cookie, httponly=True, samesite="strict", path="/api/internal", max_age=12 * 3600)
        return {"status": "connected"}

    @app.get("/api/internal/templates", dependencies=[Depends(authorized)])
    def list_cover_templates() -> dict:
        catalog_path = Path(__file__).resolve().parents[3] / "work-buddy-handoff" / "templates" / "catalog.json"
        if not catalog_path.is_file():
            return {"items": [], "unidentifiedCount": 0, "status": "catalog_not_registered"}
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        return {"items": [{"id": t["id"], "name": t["name"], "fixing": t["fixing"],
                           "hasEditableBlend": t["has_editable_blend"], "status": t["status"]}
                          for t in catalog["templates"]],
                "unidentifiedCount": len(catalog["unidentified_files"]),
                "status": "registered_unverified_fit"}

    @app.get("/api/internal/worker-status", dependencies=[Depends(authorized)])
    def worker_status() -> dict:
        def running(name: str) -> bool:
            path = settings.data_dir / f"{name}_worker.lock"
            if not path.is_file():
                return False
            with path.open("a+") as lock:
                try:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return True
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
                return False
        return {"media": running("media"), "colmap": running("model"),
                "hunyuan": running("hunyuan"), "hunyuanConfigured": bool(settings.hunyuan_key_file and settings.hunyuan_key_file.is_file()),
                "geometryConfigured": bool(settings.geometry_python and Path(settings.geometry_python).is_file())}

    @app.post("/api/uploads/init", status_code=201)
    def init_upload(payload: UploadInit, session_id: str | None = Depends(customer_or_admin)) -> dict:
        if payload.byte_size > settings.max_upload_bytes:
            raise HTTPException(413, detail={"code": "VIDEO_TOO_LARGE", "maxBytes": settings.max_upload_bytes})
        if payload.content_type not in {"video/mp4", "video/quicktime", "video/webm"}:
            raise HTTPException(422, detail={"code": "UNSUPPORTED_VIDEO_TYPE"})
        upload_id = str(uuid.uuid4())
        store.create_upload(upload_id, Path(payload.filename).name, payload.content_type, payload.byte_size, session_id)
        return {"uploadId": upload_id, "status": "initiated", "uploadUrl": f"/api/uploads/{upload_id}/content"}

    @app.get("/api/uploads", dependencies=[Depends(authorized)])
    def list_uploads() -> dict:
        return {"items": store.list_uploads()}

    @app.put("/api/uploads/{upload_id}/content")
    async def put_content(upload_id: str, request: Request, session_id: str | None = Depends(customer_or_admin)) -> dict:
        upload = existing(upload_id, session_id)
        if not store.transition(upload_id, "initiated", "uploading"):
            raise HTTPException(409, detail={"code": "UPLOAD_STATE_CONFLICT", "status": upload["status"]})
        upload_dir = settings.data_dir / "uploads" / upload_id
        upload_dir.mkdir(parents=True, exist_ok=True)
        partial = upload_dir / "source.video.part"
        final = upload_dir / "source.video"
        digest = hashlib.sha256()
        actual = 0
        try:
            with partial.open("wb") as stream:
                async for chunk in request.stream():
                    actual += len(chunk)
                    if actual > upload["expected_bytes"] or actual > settings.max_upload_bytes:
                        raise HTTPException(413, detail={"code": "UPLOAD_SIZE_MISMATCH"})
                    stream.write(chunk)
                    digest.update(chunk)
            if actual != upload["expected_bytes"]:
                raise HTTPException(422, detail={"code": "UPLOAD_SIZE_MISMATCH", "actualBytes": actual})
            partial.replace(final)
            store.transition(upload_id, "uploading", "uploaded", actual_bytes=actual, sha256=digest.hexdigest())
            return {"uploadId": upload_id, "status": "uploaded", "sha256": digest.hexdigest()}
        except BaseException:
            partial.unlink(missing_ok=True)
            final.unlink(missing_ok=True)
            store.transition(upload_id, "uploading", "initiated")
            raise

    @app.post("/api/uploads/{upload_id}/complete")
    def complete_upload(upload_id: str, session_id: str | None = Depends(customer_or_admin)) -> dict:
        upload = existing(upload_id, session_id)
        if upload["status"] not in {"uploaded", "validating", "needs_capture_review", "rejected", "validation_failed", "accepted", "needs_recapture"}:
            raise HTTPException(409, detail={"code": "UPLOAD_NOT_COMPLETE"})
        return {"uploadId": upload_id, "status": upload["status"], "pollUrl": f"/api/uploads/{upload_id}"}

    @app.get("/api/uploads/{upload_id}")
    def get_upload(upload_id: str, session_id: str | None = Depends(customer_or_admin)) -> dict:
        upload = existing(upload_id, session_id)
        return {
            "uploadId": upload_id,
            "status": upload["status"],
            "filename": upload["filename"],
            "byteSize": upload["actual_bytes"],
            "quality": upload["metadata"],
            "reasonCode": upload["reason_code"],
            "nextAction": upload["next_action"],
            "reviewNotes": upload["review_notes"],
            "createdAt": upload["created_at"],
            "updatedAt": upload["updated_at"],
        }

    @app.get("/api/uploads/{upload_id}/review-frames/{name}", dependencies=[Depends(authorized)])
    def review_frame(upload_id: str, name: str) -> FileResponse:
        upload = existing(upload_id)
        if upload["status"] not in {"needs_capture_review", "accepted", "needs_recapture"}:
            raise HTTPException(409, detail={"code": "REVIEW_FRAMES_NOT_READY"})
        if re.fullmatch(r"review_0[1-8]\.jpg", name) is None:
            raise HTTPException(404, detail={"code": "FRAME_NOT_FOUND"})
        path = settings.data_dir / "uploads" / upload_id / "review_frames" / name
        if not path.is_file():
            raise HTTPException(404, detail={"code": "FRAME_NOT_FOUND"})
        return FileResponse(path, media_type="image/jpeg")

    @app.post("/api/internal/uploads/{upload_id}/validate", dependencies=[Depends(authorized)], status_code=202)
    def validate_upload(upload_id: str, tasks: BackgroundTasks) -> dict:
        existing(upload_id)
        upload = store.claim_for_validation(upload_id)
        if upload is None:
            raise HTTPException(409, detail={"code": "UPLOAD_STATE_CONFLICT"})
        tasks.add_task(validate_claimed, store, settings, upload)
        return {"uploadId": upload_id, "status": "validating"}

    @app.post("/api/internal/uploads/{upload_id}/decision", dependencies=[Depends(authorized)])
    def capture_decision(upload_id: str, payload: CaptureDecision) -> dict:
        existing(upload_id)
        target = "accepted" if payload.approved else "needs_recapture"
        reason = "CAPTURE_REVIEW_APPROVED" if payload.approved else "CAPTURE_REVIEW_REJECTED"
        action = "拍摄复核通过，可启动 COLMAP 并确认多视角；毫米尺度和保护套仍需后续复核。" if payload.approved else payload.notes
        if not store.transition(upload_id, "needs_capture_review", target, reason_code=reason, next_action=action, review_notes=payload.notes):
            raise HTTPException(409, detail={"code": "UPLOAD_STATE_CONFLICT"})
        return {"uploadId": upload_id, "status": target}

    @app.post("/api/customer/submissions", status_code=201)
    def create_submission(payload: SubmissionCreate, tasks: BackgroundTasks, session_id: str = Depends(customer_session)) -> dict:
        if payload.color not in {"Satin Silver", "Deep Charcoal", "Soft Sand", "Ocean Blue"} and re.fullmatch(r"#[0-9a-fA-F]{6}", payload.color) is None:
            raise HTTPException(422, detail={"code": "INVALID_COLOR"})
        if payload.material not in {"PLA", "ABS", "Lightweight Polymer", "Durable Nylon", "Premium Resin"}:
            raise HTTPException(422, detail={"code": "INVALID_MATERIAL"})
        if payload.template_id not in {"01", "02", "03", "04", "05", "06", "05-magnetic"}:
            raise HTTPException(422, detail={"code": "INVALID_TEMPLATE"})
        upload = existing(payload.upload_id, session_id)
        if upload["status"] != "uploaded":
            raise HTTPException(409, detail={"code": "UPLOAD_NOT_READY", "status": upload["status"]})
        submission_id = str(uuid.uuid4())
        try:
            store.create_submission(submission_id, session_id, payload.upload_id, payload.color, payload.material, payload.inspiration, payload.template_id)
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, detail={"code": "UPLOAD_ALREADY_SUBMITTED"}) from exc
        claimed = store.claim_for_validation(payload.upload_id)
        if claimed is not None:
            tasks.add_task(validate_claimed, store, settings, claimed)
        return {"submissionId": submission_id, "status": "submitted", "detailUrl": f"/api/customer/submissions/{submission_id}"}

    @app.get("/api/customer/submissions")
    def customer_submissions(session_id: str = Depends(customer_session)) -> dict:
        items = store.list_submissions(session_id)
        for item in items:
            model = store.model_job_for_submission(item["id"])
            item["model"] = None if model is None else {"status": model["status"], "stage": model["stage"], "nextAction": model["next_action"]}
        return {"items": items}

    @app.get("/api/customer/submissions/{submission_id}")
    def customer_submission(submission_id: str, session_id: str = Depends(customer_session)) -> dict:
        submission = existing_submission(submission_id, session_id)
        progress = workflow_snapshot(store, settings.data_dir, submission_id)
        return {
            "submissionId": submission_id,
            "createdAt": submission["created_at"],
            "color": submission["color"],
            "material": submission["material"],
            "templateId": submission["template_id"],
            "inspiration": submission["inspiration"],
            "inspirationImageName": submission["inspiration_image_name"],
            "uploadId": submission["upload_id"],
            "status": submission["upload"]["status"],
            "nextAction": submission["upload"]["next_action"],
            "model": store.model_job_for_submission(submission_id),
            "productionProgress": {"nextStage": progress["nextStage"], "stages": progress["stages"],
                                   "manufacturingApproved": False},
        }

    @app.put("/api/customer/submissions/{submission_id}/inspiration-image")
    async def put_inspiration_image(submission_id: str, request: Request, session_id: str = Depends(customer_session)) -> dict:
        submission = existing_submission(submission_id, session_id)
        content_type = request.headers.get("content-type", "")
        if content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise HTTPException(422, detail={"code": "UNSUPPORTED_IMAGE_TYPE"})
        filename = request.headers.get("x-file-name", "inspiration-image")[:255]
        directory = settings.data_dir / "submissions" / submission_id
        directory.mkdir(parents=True, exist_ok=True)
        partial = directory / "inspiration.image.part"
        final = directory / "inspiration.image"
        size = 0
        try:
            with partial.open("wb") as stream:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > 10 * 1024 * 1024:
                        raise HTTPException(413, detail={"code": "IMAGE_TOO_LARGE"})
                    stream.write(chunk)
            if size == 0:
                raise HTTPException(422, detail={"code": "EMPTY_IMAGE"})
            signature = partial.open("rb").read(12)
            valid_image = (
                (content_type == "image/png" and signature.startswith(b"\x89PNG\r\n\x1a\n")) or
                (content_type == "image/jpeg" and signature.startswith(b"\xff\xd8\xff")) or
                (content_type == "image/webp" and signature[:4] == b"RIFF" and signature[8:12] == b"WEBP")
            )
            if not valid_image:
                raise HTTPException(422, detail={"code": "INVALID_IMAGE_CONTENT"})
            partial.replace(final)
            store.attach_inspiration(submission_id, Path(filename).name, content_type, size)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
        return {"submissionId": submission_id, "imageName": Path(filename).name, "byteSize": size}

    @app.get("/api/internal/submissions", dependencies=[Depends(authorized)])
    def internal_submissions() -> dict:
        return {"items": store.list_submissions()}

    @app.get("/api/internal/submissions/{submission_id}/cover-task", dependencies=[Depends(authorized)])
    def get_cover_task(submission_id: str) -> dict:
        existing_submission(submission_id)
        return task_status(store, settings.data_dir, submission_id)

    @app.get("/api/internal/submissions/{submission_id}/production-flow", dependencies=[Depends(authorized)])
    def get_production_flow(submission_id: str) -> dict:
        existing_submission(submission_id)
        return workflow_snapshot(store, settings.data_dir, submission_id)

    @app.get("/api/internal/submissions/{submission_id}/print-candidate/package", dependencies=[Depends(operator_media_auth)])
    def get_print_candidate(submission_id: str) -> FileResponse:
        existing_submission(submission_id)
        flow = workflow_snapshot(store, settings.data_dir, submission_id)
        candidate = flow["trialCandidate"]
        if not candidate:
            raise HTTPException(404, detail={"code": "PRINT_CANDIDATE_NOT_READY"})
        path = settings.data_dir / "cover_tasks" / submission_id / "candidate_print_trial" / candidate["candidateId"] / "cover_trial_mm.3mf"
        report = json.loads((path.parent / "build_report.json").read_text(encoding="utf-8"))
        if not path.is_file() or digest(path) != report["packageSha256"]:
            raise HTTPException(409, detail={"code": "PRINT_CANDIDATE_HASH_MISMATCH"})
        return FileResponse(path, media_type="model/3mf", filename=f"forme-{candidate['candidateId']}-trial.3mf")

    @app.get("/api/internal/submissions/{submission_id}/print-candidate/stl/{part}", dependencies=[Depends(operator_media_auth)])
    def get_print_candidate_stl(submission_id: str, part: str) -> FileResponse:
        existing_submission(submission_id)
        flow = workflow_snapshot(store, settings.data_dir, submission_id)
        candidate = flow["trialCandidate"]
        if not candidate:
            raise HTTPException(404, detail={"code": "PRINT_CANDIDATE_NOT_READY"})
        root = settings.data_dir / "cover_tasks" / submission_id / "candidate_print_trial" / candidate["candidateId"]
        report = json.loads((root / "build_report.json").read_text(encoding="utf-8"))
        if part == "combined":
            name, expected = report.get("combinedStl"), report.get("combinedStlSha256")
        elif part in ("front", "rear"):
            record = report["parts"][part]
            name, expected = record["file"], record["sha256"]
        else:
            raise HTTPException(404, detail={"code": "PRINT_STL_PART_NOT_FOUND"})
        if name not in {"cover_trial_mm.stl", "cover_front.stl", "cover_rear.stl"} or not expected:
            raise HTTPException(409, detail={"code": "PRINT_STL_REPORT_INVALID"})
        path = root / name
        if not path.is_file() or digest(path) != expected:
            raise HTTPException(409, detail={"code": "PRINT_STL_HASH_MISMATCH"})
        return FileResponse(path, media_type="model/stl", filename=f"forme-{candidate['candidateId']}-{part}.stl")

    @app.get("/api/internal/submissions/{submission_id}/ruler/frames", dependencies=[Depends(authorized)])
    def get_ruler_frames(submission_id: str) -> dict:
        existing_submission(submission_id)
        model = store.model_job_for_submission(submission_id)
        if not model or model["stage"] != "scale_review":
            raise HTTPException(409, detail={"code": "COLMAP_RECONSTRUCTION_REQUIRED"})
        folder = settings.data_dir / "model_jobs" / model["id"] / "frames"
        return {"items": [{"name": path.name, "url": f"/api/internal/submissions/{submission_id}/ruler/frames/{path.name}"}
                          for path in sorted(folder.glob("frame_[0-9][0-9][0-9][0-9].jpg"))]}

    @app.get("/api/internal/submissions/{submission_id}/ruler/frames/{name}", dependencies=[Depends(operator_media_auth)])
    def get_ruler_frame(submission_id: str, name: str) -> FileResponse:
        existing_submission(submission_id)
        if not re.fullmatch(r"frame_[0-9]{4}\.jpg", name):
            raise HTTPException(404, detail={"code": "FRAME_NOT_FOUND"})
        model = store.model_job_for_submission(submission_id)
        if not model:
            raise HTTPException(404, detail={"code": "FRAME_NOT_FOUND"})
        path = settings.data_dir / "model_jobs" / model["id"] / "frames" / name
        if not path.is_file():
            raise HTTPException(404, detail={"code": "FRAME_NOT_FOUND"})
        return FileResponse(path, media_type="image/jpeg")

    @app.get("/api/internal/submissions/{submission_id}/ruler/suggestions/{name}", dependencies=[Depends(authorized)])
    def suggest_ruler_marks(submission_id: str, name: str) -> dict:
        existing_submission(submission_id)
        if not re.fullmatch(r"frame_[0-9]{4}\.jpg", name):
            raise HTTPException(404, detail={"code": "FRAME_NOT_FOUND"})
        model = store.model_job_for_submission(submission_id)
        if not model or model["stage"] != "scale_review":
            raise HTTPException(409, detail={"code": "COLMAP_RECONSTRUCTION_REQUIRED"})
        frame = settings.data_dir / "model_jobs" / model["id"] / "frames" / name
        if not frame.is_file():
            raise HTTPException(404, detail={"code": "FRAME_NOT_FOUND"})
        if not settings.geometry_python or not Path(settings.geometry_python).is_file():
            raise HTTPException(409, detail={"code": "GEOMETRY_PYTHON_NOT_CONFIGURED"})
        script = Path(__file__).resolve().parents[2] / "scripts" / "suggest_ruler_marks.py"
        try:
            result = subprocess.run([settings.geometry_python, str(script), str(frame)],
                                    capture_output=True, text=True, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise HTTPException(409, detail={"code": "RULER_SUGGESTION_FAILED"}) from exc
        if result.returncode:
            raise HTTPException(409, detail={"code": "RULER_SUGGESTION_FAILED"})
        return json.loads(result.stdout)

    @app.post("/api/internal/submissions/{submission_id}/ruler/calibrate", dependencies=[Depends(authorized)])
    def calibrate_submission_ruler(submission_id: str, payload: RulerCalibrationInput) -> dict:
        submission = existing_submission(submission_id)
        model = store.model_job_for_submission(submission_id)
        if not model or model["stage"] != "scale_review":
            raise HTTPException(409, detail={"code": "COLMAP_RECONSTRUCTION_REQUIRED"})
        if not settings.geometry_python or not Path(settings.geometry_python).is_file():
            raise HTTPException(409, detail={"code": "GEOMETRY_PYTHON_NOT_CONFIGURED"})
        names = [item.name for item in payload.images]
        frame_dir = settings.data_dir / "model_jobs" / model["id"] / "frames"
        if len(set(names)) != len(names) or any(not (frame_dir / name).is_file() for name in names):
            raise HTTPException(422, detail={"code": "INVALID_RULER_FRAMES"})
        observations = payload.model_dump()
        if any(not math.isfinite(value) for item in observations["images"] for marker in ("A", "B") for value in item[marker]):
            raise HTTPException(422, detail={"code": "INVALID_RULER_PIXELS"})
        root = settings.data_dir / "cover_tasks" / submission_id
        canonical = json.dumps(observations, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        run_id = hashlib.sha256(canonical).hexdigest()[:16]
        folder = root / "ruler_calibrations" / run_id
        folder.mkdir(parents=True, exist_ok=True)
        observation_file = folder / "observations.json"
        if not observation_file.is_file():
            observation_file.write_bytes(canonical)
        output = folder / "calibration.json"
        if not output.is_file():
            model_dir = settings.data_dir / "model_jobs" / model["id"] / "sparse" / model["metrics"]["colmapModel"]
            video = settings.data_dir / "uploads" / submission["upload_id"] / "source.video"
            script = Path(__file__).resolve().parents[2] / "scripts" / "calibrate_ruler.py"
            try:
                result = subprocess.run([settings.geometry_python, str(script), "--model-dir", str(model_dir),
                                         "--observations", str(observation_file), "--source-video", str(video),
                                         "--output", str(output)], capture_output=True, text=True, timeout=180, check=False)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise HTTPException(409, detail={"code": "RULER_CALIBRATION_FAILED"}) from exc
            if result.returncode != 0:
                raise HTTPException(422, detail={"code": "RULER_CALIBRATION_REJECTED", "message": result.stderr[-400:]})
        calibration = json.loads(output.read_text(encoding="utf-8"))
        if calibration["sourceVideoSha256"] != submission["upload"]["sha256"]:
            raise HTTPException(409, detail={"code": "RULER_VIDEO_HASH_MISMATCH"})
        if any(not (Path(calibration["modelDirectory"]) / name).is_file() or
               digest(Path(calibration["modelDirectory"]) / name) != expected
               for name, expected in calibration["modelFilesSha256"].items()):
            raise HTTPException(409, detail={"code": "RULER_MODEL_HASH_MISMATCH"})
        latest = root / "ruler_calibration.json"
        write_json(latest, calibration)
        return {"status": calibration["status"], "runId": run_id,
                "mmPerColmapUnit": calibration["mmPerColmapUnit"], "quality": calibration["quality"],
                "physicalFitVerified": False}

    @app.post("/api/internal/submissions/{submission_id}/cover/registration", dependencies=[Depends(authorized)])
    def approve_cover_registration(submission_id: str, payload: dict) -> dict:
        submission = existing_submission(submission_id)
        views = store.get_view_review(submission_id)
        if submission["upload"]["status"] != "accepted" or not views or views["status"] != "reviewed":
            raise HTTPException(409, detail={"code": "CAPTURE_AND_VIEWS_REVIEW_REQUIRED"})
        model = store.model_job_for_submission(submission_id)
        if not model or model["stage"] != "scale_review":
            raise HTTPException(409, detail={"code": "COLMAP_RECONSTRUCTION_REQUIRED"})
        cloud = settings.data_dir / "model_jobs" / model["id"] / "dense" / "fused.ply"
        if not cloud.is_file():
            raise HTTPException(409, detail={"code": "COLMAP_CLOUD_REQUIRED"})
        try:
            return approve_registration(settings.data_dir / "cover_tasks" / submission_id,
                                        submission["upload"]["sha256"], cloud, payload)
        except (CoverGateError, ValueError, TypeError, OSError) as exc:
            raise HTTPException(409, detail={"code": str(exc)}) from exc

    @app.post("/api/internal/submissions/{submission_id}/cover/concept/build", dependencies=[Depends(authorized)])
    def build_cover_concept(submission_id: str, payload: ConceptBuildInput) -> dict:
        submission = existing_submission(submission_id)
        views = store.get_view_review(submission_id)
        if submission["upload"]["status"] != "accepted" or not views or views["status"] != "reviewed":
            raise HTTPException(409, detail={"code": "CAPTURE_AND_VIEWS_REVIEW_REQUIRED"})
        model = store.model_job_for_submission(submission_id)
        if not model or model["stage"] != "scale_review":
            raise HTTPException(409, detail={"code": "COLMAP_RECONSTRUCTION_REQUIRED"})
        if not settings.geometry_python or not Path(settings.geometry_python).is_file():
            raise HTTPException(409, detail={"code": "GEOMETRY_PYTHON_NOT_CONFIGURED"})
        cloud = settings.data_dir / "model_jobs" / model["id"] / "dense" / "fused.ply"
        if not cloud.is_file():
            raise HTTPException(409, detail={"code": "COLMAP_CLOUD_REQUIRED"})
        script = Path(__file__).resolve().parents[3] / "work-buddy-handoff" / "automation" / "fit_template.py"
        try:
            return build_candidate(settings.data_dir / "cover_tasks" / submission_id,
                                   submission["upload"]["sha256"], cloud, payload.candidate_id,
                                   payload.proposal, settings.geometry_python, script)
        except (CoverGateError, ValueError, TypeError, OSError, subprocess.TimeoutExpired) as exc:
            raise HTTPException(409, detail={"code": str(exc)}) from exc

    @app.post("/api/internal/submissions/{submission_id}/print-candidate/prepare", dependencies=[Depends(authorized)])
    def prepare_print_candidate(submission_id: str) -> dict:
        existing_submission(submission_id)
        flow = workflow_snapshot(store, settings.data_dir, submission_id)
        if flow["trialCandidate"]:
            return flow["trialCandidate"]
        review = task_status(store, settings.data_dir, submission_id)["candidateReview"]
        if not review or review["status"] != "CONCEPT_CANDIDATE_NOT_FIT_VERIFIED":
            raise HTTPException(409, detail={"code": "REVIEWED_CONCEPT_CANDIDATE_REQUIRED"})
        if not settings.geometry_python or not Path(settings.geometry_python).is_file():
            raise HTTPException(409, detail={"code": "GEOMETRY_PYTHON_NOT_CONFIGURED"})
        task_dir = settings.data_dir / "cover_tasks" / submission_id
        raw_review = json.loads((task_dir / "candidate_review.json").read_text(encoding="utf-8"))
        trial_dir = Path(raw_review["trialReport"]).parent
        script = Path(__file__).resolve().parents[2] / "scripts" / "package_cover_candidate.py"
        try:
            result = subprocess.run([settings.geometry_python, str(script), str(trial_dir), str(task_dir)],
                                    text=True, capture_output=True, timeout=1800, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise HTTPException(409, detail={"code": "PRINT_CANDIDATE_PACKAGING_FAILED"}) from exc
        if result.returncode != 0:
            raise HTTPException(409, detail={"code": "PRINT_CANDIDATE_PACKAGING_FAILED",
                                             "message": result.stderr[-500:]})
        return workflow_snapshot(store, settings.data_dir, submission_id)["trialCandidate"]

    @app.post("/api/internal/submissions/{submission_id}/hunyuan/prepare", dependencies=[Depends(authorized)])
    def prepare_hunyuan(submission_id: str) -> dict:
        existing_submission(submission_id)
        try:
            return prepare_hunyuan_input(store, settings.data_dir, submission_id)
        except FlowError as exc:
            raise HTTPException(409, detail={"code": str(exc)}) from exc

    def hunyuan_credentials() -> Path:
        if not settings.hunyuan_key_file or not settings.hunyuan_key_file.is_file():
            raise HTTPException(409, detail={"code": "HUNYUAN_CREDENTIALS_NOT_CONFIGURED"})
        return settings.hunyuan_key_file

    @app.post("/api/internal/submissions/{submission_id}/hunyuan/submit", dependencies=[Depends(authorized)])
    def submit_hunyuan(submission_id: str) -> dict:
        existing_submission(submission_id)
        manifest = settings.data_dir / "cover_tasks" / submission_id / "hunyuan_inputs" / "manifest.json"
        if not manifest.is_file():
            raise HTTPException(409, detail={"code": "HUNYUAN_INPUT_NOT_PREPARED"})
        try:
            record = submit_hunyuan_job(manifest, hunyuan_credentials(), settings.hunyuan_region)
        except (ValueError, RuntimeError, OSError) as exc:
            raise HTTPException(409, detail={"code": "HUNYUAN_SUBMIT_FAILED", "message": str(exc)[:300]}) from exc
        return {"status": record["status"], "jobId": record["jobId"]}

    @app.post("/api/internal/submissions/{submission_id}/hunyuan/poll", dependencies=[Depends(authorized)])
    def poll_hunyuan(submission_id: str) -> dict:
        existing_submission(submission_id)
        record_path = settings.data_dir / "cover_tasks" / submission_id / "hunyuan_inputs" / "hunyuan_job.json"
        if not record_path.is_file():
            raise HTTPException(409, detail={"code": "HUNYUAN_JOB_NOT_SUBMITTED"})
        try:
            record = poll_hunyuan_job(record_path, hunyuan_credentials())
        except (ValueError, RuntimeError, OSError) as exc:
            raise HTTPException(409, detail={"code": "HUNYUAN_POLL_FAILED", "message": str(exc)[:300]}) from exc
        return {"status": record["status"], "jobId": record["jobId"]}

    @app.post("/api/internal/submissions/{submission_id}/hunyuan/archive", dependencies=[Depends(authorized)])
    def archive_hunyuan(submission_id: str) -> dict:
        existing_submission(submission_id)
        record_path = settings.data_dir / "cover_tasks" / submission_id / "hunyuan_inputs" / "hunyuan_job.json"
        if not record_path.is_file():
            raise HTTPException(409, detail={"code": "HUNYUAN_JOB_NOT_SUBMITTED"})
        try:
            record = archive_hunyuan_result(record_path)
        except (ValueError, RuntimeError, OSError) as exc:
            raise HTTPException(409, detail={"code": "HUNYUAN_ARCHIVE_FAILED", "message": str(exc)[:300]}) from exc
        return {"status": record["status"], "jobId": record["jobId"], "artifactCount": len(record["artifacts"])}

    @app.post("/api/internal/submissions/{submission_id}/cover-task", dependencies=[Depends(authorized)])
    def create_cover_task(submission_id: str, payload: CoverTaskCreate) -> dict:
        existing_submission(submission_id)
        try:
            return prepare_task(store, settings.data_dir, submission_id, payload.template_id)
        except ValueError as exc:
            raise HTTPException(422, detail={"code": str(exc)}) from exc

    @app.get("/api/internal/submissions/{submission_id}", dependencies=[Depends(authorized)])
    def internal_submission(submission_id: str) -> dict:
        submission = existing_submission(submission_id)
        preview = settings.data_dir / "uploads" / submission["upload_id"] / "preview.mp4"
        progress = workflow_snapshot(store, settings.data_dir, submission_id)
        cover = task_status(store, settings.data_dir, submission_id)
        model_job = store.model_job_for_submission(submission_id)
        if model_job is not None:
            cloud = settings.data_dir / "model_jobs" / model_job["id"] / "dense" / "fused.ply"
            model_job["cloudUrl"] = f"/api/internal/submissions/{submission_id}/model-jobs/cloud" if cloud.is_file() else None
        return {
            "submissionId": submission_id,
            "createdAt": submission["created_at"],
            "choices": {"color": submission["color"], "material": submission["material"], "templateId": submission["template_id"], "inspiration": submission["inspiration"]},
            "resources": {
                "video": {"filename": submission["upload"]["filename"], "byteSize": submission["upload"]["actual_bytes"], "url": f"/api/internal/submissions/{submission_id}/video",
                          "previewUrl": f"/api/internal/submissions/{submission_id}/preview" if preview.is_file() else None},
                "inspirationImage": None if not submission["inspiration_image_name"] else {
                    "filename": submission["inspiration_image_name"],
                    "byteSize": submission["inspiration_image_bytes"],
                    "url": f"/api/internal/submissions/{submission_id}/inspiration-image",
                },
            },
            "uploadId": submission["upload_id"],
            "capture": {"status": submission["upload"]["status"], "quality": submission["upload"]["metadata"],
                        "reasonCode": submission["upload"]["reason_code"], "nextAction": submission["upload"]["next_action"],
                        "reviewNotes": submission["upload"]["review_notes"]},
            "workflow": {"referenceModel": "colmap_reconstruction" if model_job else "not_started",
                         "coverGeneration": "trial_candidate_review" if progress["trialCandidate"] else
                             "concept_candidate_review" if cover["candidateReview"] else
                             "registration_ready" if cover["conceptBuildAllowed"] else "awaiting_reference_and_registration"},
            "modelJob": model_job,
            "hunyuanJob": hunyuan_job(submission_id),
            "coverTask": cover,
            "productionFlow": progress,
            "hunyuanConfigured": bool(settings.hunyuan_key_file and settings.hunyuan_key_file.is_file()),
            "geometryConfigured": bool(settings.geometry_python and Path(settings.geometry_python).is_file()),
            "viewReview": store.get_view_review(submission_id),
            "visionConfigured": bool(settings.vision_model and settings.vision_api_key),
            "visionProvider": settings.vision_provider_label,
            "events": submission["events"],
        }

    @app.post("/api/internal/submissions/{submission_id}/views/prepare", dependencies=[Depends(authorized)], status_code=202)
    def prepare_views(submission_id: str, tasks: BackgroundTasks) -> dict:
        submission = existing_submission(submission_id)
        if (settings.data_dir / "cover_tasks" / submission_id / "hunyuan_inputs" / "manifest.json").is_file():
            raise HTTPException(409, detail={"code": "VIEWS_LOCKED_BY_HUNYUAN_PACKAGE"})
        if submission["upload"]["status"] not in {"needs_capture_review", "accepted"}:
            raise HTTPException(409, detail={"code": "CAPTURE_VALIDATION_REQUIRED"})
        review = store.get_view_review(submission_id)
        if review and review["status"] in {"preparing", "classifying"}:
            raise HTTPException(409, detail={"code": "VIEW_JOB_RUNNING"})
        store.set_view_review(submission_id, "preparing")
        tasks.add_task(prepare, store, settings, submission_id)
        return {"status": "preparing"}

    @app.get("/api/internal/submissions/{submission_id}/views", dependencies=[Depends(authorized)])
    def get_views(submission_id: str) -> dict:
        existing_submission(submission_id)
        review = store.get_view_review(submission_id)
        return review or {"status": "not_started", "data": {}}

    @app.get("/api/internal/submissions/{submission_id}/views/frames/{name}", dependencies=[Depends(operator_media_auth)])
    def get_view_frame(submission_id: str, name: str) -> FileResponse:
        existing_submission(submission_id)
        review = store.get_view_review(submission_id)
        if not review or name not in {frame["name"] for frame in review["data"].get("frames", [])}:
            raise HTTPException(404, detail={"code": "FRAME_NOT_FOUND"})
        path = settings.data_dir / "submissions" / submission_id / "view_frames" / name
        if not path.is_file():
            raise HTTPException(404, detail={"code": "FRAME_NOT_FOUND"})
        return FileResponse(path, media_type="image/jpeg")

    @app.post("/api/internal/submissions/{submission_id}/views/classify", dependencies=[Depends(authorized)], status_code=202)
    def classify_views(submission_id: str, payload: ViewClassify, tasks: BackgroundTasks) -> dict:
        existing_submission(submission_id)
        if (settings.data_dir / "cover_tasks" / submission_id / "hunyuan_inputs" / "manifest.json").is_file():
            raise HTTPException(409, detail={"code": "VIEWS_LOCKED_BY_HUNYUAN_PACKAGE"})
        if not settings.vision_model or not settings.vision_api_key:
            key_name = "FORME_DEEPSEEK_API_KEY" if settings.vision_provider == "deepseek" else "FORME_TOKENHUB_API_KEY"
            raise HTTPException(409, detail={"code": "VISION_API_NOT_CONFIGURED", "message": f"服务端尚未设置 {key_name}。"})
        review = store.get_view_review(submission_id)
        if not review or review["status"] not in {"ready", "classified", "reviewed", "incomplete", "partial", "failed"} or not review["data"].get("frames"):
            raise HTTPException(409, detail={"code": "VIEW_FRAMES_NOT_READY"})
        names = {frame["name"] for frame in review["data"]["frames"]}
        if payload.front_anchor is not None and payload.front_anchor not in names:
            raise HTTPException(422, detail={"code": "INVALID_FRONT_ANCHOR"})
        review["data"].pop("apiErrors", None)
        review["data"].pop("error", None)
        store.set_view_review(submission_id, "classifying", review["data"])
        tasks.add_task(classify, store, settings, submission_id, payload.front_anchor)
        return {"status": "classifying"}

    @app.post("/api/internal/submissions/{submission_id}/views/selection", dependencies=[Depends(authorized)])
    def select_views(submission_id: str, payload: ViewSelection) -> dict:
        existing_submission(submission_id)
        if (settings.data_dir / "cover_tasks" / submission_id / "hunyuan_inputs" / "manifest.json").is_file():
            raise HTTPException(409, detail={"code": "VIEWS_LOCKED_BY_HUNYUAN_PACKAGE"})
        review = store.get_view_review(submission_id)
        if not review or review["status"] not in {"ready", "classified", "reviewed", "incomplete", "partial", "failed"} or not review["data"].get("frames"):
            raise HTTPException(409, detail={"code": "VIEW_FRAMES_NOT_READY"})
        names = {frame["name"] for frame in review["data"].get("frames", [])}
        if set(payload.selections) - set(SLOTS) or any(name not in names for name in payload.selections.values()):
            raise HTTPException(422, detail={"code": "INVALID_VIEW_SELECTION"})
        geometry_names = [payload.selections[slot] for slot in ("front", "back", "left", "right", "top") if slot in payload.selections]
        if len(geometry_names) != len(set(geometry_names)):
            raise HTTPException(422, detail={"code": "DUPLICATE_GEOMETRY_VIEW"})
        data = review["data"]
        data["selections"] = payload.selections
        data["notes"] = payload.notes
        status = "reviewed" if set(payload.selections) == set(SLOTS) else "incomplete"
        store.set_view_review(submission_id, status, data)
        return {"status": status, "missing": [slot for slot in SLOTS if slot not in payload.selections]}

    @app.post("/api/internal/submissions/{submission_id}/model-jobs", dependencies=[Depends(authorized)], status_code=202)
    def start_model_job(submission_id: str) -> dict:
        submission = existing_submission(submission_id)
        if submission["upload"]["status"] != "accepted":
            raise HTTPException(409, detail={"code": "CAPTURE_NOT_ACCEPTED"})
        existing_job = store.model_job_for_submission(submission_id)
        if existing_job is not None:
            raise HTTPException(409, detail={"code": "MODEL_JOB_EXISTS", "jobId": existing_job["id"]})
        job = store.create_model_job(str(uuid.uuid4()), submission_id)
        return {"jobId": job["id"], "status": job["status"], "stage": job["stage"]}

    @app.get("/api/internal/submissions/{submission_id}/model-jobs", dependencies=[Depends(authorized)])
    def get_model_job(submission_id: str) -> dict:
        existing_submission(submission_id)
        job = store.model_job_for_submission(submission_id)
        if job is None:
            raise HTTPException(404, detail={"code": "MODEL_JOB_NOT_FOUND"})
        return job

    @app.get("/api/internal/submissions/{submission_id}/model-jobs/cloud", dependencies=[Depends(operator_media_auth)])
    def get_model_cloud(submission_id: str) -> FileResponse:
        existing_submission(submission_id)
        job = store.model_job_for_submission(submission_id)
        if job is None:
            raise HTTPException(404, detail={"code": "MODEL_JOB_NOT_FOUND"})
        path = settings.data_dir / "model_jobs" / job["id"] / "dense" / "fused.ply"
        if not path.is_file():
            raise HTTPException(404, detail={"code": "CLOUD_NOT_READY"})
        return FileResponse(path, media_type="application/octet-stream", filename="colmap-unscaled.ply")

    @app.get("/api/internal/submissions/{submission_id}/hunyuan/preview", dependencies=[Depends(operator_media_auth)])
    def get_hunyuan_preview(submission_id: str) -> FileResponse:
        existing_submission(submission_id)
        path = settings.data_dir / "cover_tasks" / submission_id / "hunyuan_inputs" / "hunyuan_result" / "preview_00.png"
        if not path.is_file():
            raise HTTPException(404, detail={"code": "HUNYUAN_PREVIEW_NOT_READY"})
        return FileResponse(path, media_type="image/png", content_disposition_type="inline")

    @app.get("/api/internal/submissions/{submission_id}/hunyuan/model", dependencies=[Depends(operator_media_auth)])
    def get_hunyuan_model(submission_id: str) -> FileResponse:
        existing_submission(submission_id)
        path = settings.data_dir / "cover_tasks" / submission_id / "hunyuan_inputs" / "hunyuan_result" / "result_00.glb"
        if not path.is_file():
            raise HTTPException(404, detail={"code": "HUNYUAN_MODEL_NOT_READY"})
        return FileResponse(path, media_type="model/gltf-binary", filename="hunyuan-geometry-candidate.glb")

    @app.get("/api/internal/submissions/{submission_id}/hunyuan/alignment/{view}", dependencies=[Depends(operator_media_auth)])
    def get_hunyuan_alignment(submission_id: str, view: str) -> FileResponse:
        existing_submission(submission_id)
        if view not in {"front", "side"}:
            raise HTTPException(404, detail={"code": "ALIGNMENT_VIEW_NOT_FOUND"})
        path = settings.data_dir / "cover_tasks" / submission_id / "alignment" / f"overlay_{view}.png"
        if not path.is_file():
            raise HTTPException(404, detail={"code": "ALIGNMENT_NOT_READY"})
        return FileResponse(path, media_type="image/png", content_disposition_type="inline")

    @app.get("/api/internal/submissions/{submission_id}/pointcloud-qa/contact-sheet", dependencies=[Depends(operator_media_auth)])
    def get_pointcloud_qa_contact_sheet(submission_id: str) -> FileResponse:
        existing_submission(submission_id)
        path = settings.data_dir / "cover_tasks" / submission_id / "pointcloud_image_validation" / "contact_sheet.jpg"
        if not path.is_file():
            raise HTTPException(404, detail={"code": "POINTCLOUD_IMAGE_VALIDATION_NOT_READY"})
        return FileResponse(path, media_type="image/jpeg", content_disposition_type="inline")

    @app.get("/api/internal/submissions/{submission_id}/cover-concept/{asset}", dependencies=[Depends(operator_media_auth)])
    def get_cover_concept_asset(submission_id: str, asset: str) -> FileResponse:
        existing_submission(submission_id)
        root = settings.data_dir / "cover_tasks" / submission_id / "ruler_only_template01_concept"
        if asset == "model":
            path = root / "template01_ruler_visual.glb"
            media_type = "model/gltf-binary"
        elif asset in {"front", "back", "side", "three_quarter"}:
            path = root / f"review_{asset}.png"
            media_type = "image/png"
        else:
            raise HTTPException(404, detail={"code": "CONCEPT_ASSET_NOT_FOUND"})
        if not path.is_file():
            raise HTTPException(404, detail={"code": "CONCEPT_ASSET_NOT_READY"})
        return FileResponse(path, media_type=media_type, content_disposition_type="inline")

    @app.get("/api/internal/submissions/{submission_id}/workbuddy-hybrid/{asset}", dependencies=[Depends(operator_media_auth)])
    def get_workbuddy_hybrid_asset(submission_id: str, asset: str) -> FileResponse:
        existing_submission(submission_id)
        v2_root = settings.data_dir / "cover_tasks" / submission_id / "workbuddy_hybrid_v2"
        is_v2 = (v2_root / "build_report.json").is_file()
        root = v2_root if is_v2 else settings.data_dir / "cover_tasks" / submission_id / "workbuddy_hybrid_v1"
        names = {
            "model": ("xiangyun_rim_fixed_v2_preview.glb" if is_v2 else "xiangyun_hybrid_v1_preview.glb", "model/gltf-binary"),
            "front": ("review_front.png", "image/png"),
            "side": ("review_side.png", "image/png"),
            "top": ("review_top.png", "image/png"),
            "overlay": ("review_overlay_front.png", "image/png"),
        }
        if asset not in names:
            raise HTTPException(404, detail={"code": "HYBRID_ASSET_NOT_FOUND"})
        filename, media_type = names[asset]
        path = root / filename
        if not path.is_file():
            raise HTTPException(404, detail={"code": "HYBRID_ASSET_NOT_READY"})
        return FileResponse(path, media_type=media_type, content_disposition_type="inline")

    @app.get("/api/internal/submissions/{submission_id}/print-prototype/{asset}", dependencies=[Depends(operator_media_auth)])
    def get_print_prototype_asset(submission_id: str, asset: str) -> FileResponse:
        existing_submission(submission_id)
        root = settings.data_dir / "cover_tasks" / submission_id / "print_prototype_v1"
        names = {
            "front": ("cover_front_print_test.stl", "model/stl"),
            "rear": ("cover_rear_print_test.stl", "model/stl"),
            "package": ("xiangyun_v2_print_trial_mm.3mf", "model/3mf"),
        }
        if asset not in names:
            raise HTTPException(404, detail={"code": "PRINT_ASSET_NOT_FOUND"})
        filename, media_type = names[asset]
        path = root / filename
        if not path.is_file():
            raise HTTPException(404, detail={"code": "PRINT_ASSET_NOT_READY"})
        return FileResponse(path, media_type=media_type, filename=filename)

    @app.get("/api/internal/submissions/{submission_id}/video", dependencies=[Depends(operator_media_auth)])
    def internal_video(submission_id: str) -> FileResponse:
        submission = existing_submission(submission_id)
        path = settings.data_dir / "uploads" / submission["upload_id"] / "source.video"
        if not path.is_file():
            raise HTTPException(404, detail={"code": "VIDEO_NOT_FOUND"})
        return FileResponse(path, media_type=submission["upload"]["content_type"], filename=submission["upload"]["filename"], content_disposition_type="inline")

    @app.get("/api/internal/submissions/{submission_id}/preview", dependencies=[Depends(operator_media_auth)])
    def internal_video_preview(submission_id: str) -> FileResponse:
        submission = existing_submission(submission_id)
        path = settings.data_dir / "uploads" / submission["upload_id"] / "preview.mp4"
        if not path.is_file():
            raise HTTPException(404, detail={"code": "PREVIEW_NOT_FOUND"})
        return FileResponse(path, media_type="video/mp4")

    @app.get("/api/internal/submissions/{submission_id}/inspiration-image", dependencies=[Depends(operator_media_auth)])
    def internal_inspiration_image(submission_id: str) -> FileResponse:
        submission = existing_submission(submission_id)
        if not submission["inspiration_image_name"]:
            raise HTTPException(404, detail={"code": "IMAGE_NOT_FOUND"})
        path = settings.data_dir / "submissions" / submission_id / "inspiration.image"
        if not path.is_file():
            raise HTTPException(404, detail={"code": "IMAGE_NOT_FOUND"})
        return FileResponse(path, media_type=submission["inspiration_image_type"])

    @app.post("/api/model/generate", dependencies=[Depends(authorized)])
    def model_generate() -> None:
        raise HTTPException(501, detail={
            "code": "MODEL_PIPELINE_NOT_CONNECTED",
            "message": "混元、COLMAP 定尺度与模型质量门禁尚未接入；没有生成模型。",
        })

    operator_dir = Path(__file__).resolve().parents[2] / "operator"
    if operator_dir.is_dir():
        app.mount("/operator", StaticFiles(directory=operator_dir, html=True), name="operator")
    web_dir = Path(__file__).resolve().parents[2] / "web"
    if web_dir.is_dir():
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")

    return app
