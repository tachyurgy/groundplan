from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response

from groundplan.api.deps import Ctx, owned
from groundplan.api.problems import Problem
from groundplan.api.schemas import DismissIn, ResolveIn
from groundplan.config import get_settings
from groundplan.db import models as m
from groundplan.services import ingest
from groundplan.services import portfolio as svc
from groundplan.services import workspace as ws
from groundplan.services.pipeline_adapter import PipelineUnavailable, load_processor

router = APIRouter(tags=["documents & findings"])


def _dump(x):
    return x.model_dump(mode="json") if hasattr(x, "model_dump") else x


@router.post("/households/{household_id}/documents", status_code=201,
             summary="Upload a PDF; runs the pipeline in-process. File bytes are never persisted.")
async def upload_document(household_id: str, file: UploadFile = File(...), c: Ctx = Depends()):
    h = c.household(household_id)
    cap = get_settings().max_documents_per_workspace
    if ws.counts(c.s, c.aid)[1] >= cap:
        raise Problem(429, "Document limit reached", f"a workspace holds at most {cap} documents; delete some or reset the "
                      "workspace", "https://groundplan.dev/problems/document-limit")
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    await file.close()
    if len(data) > limit:
        raise Problem(413, "Upload too large", f"max {get_settings().max_upload_mb} MB",
                      "https://groundplan.dev/problems/upload-too-large")
    sha = hashlib.sha256(data).hexdigest()
    filename = file.filename or "upload.pdf"
    try:
        process = load_processor()
    except PipelineUnavailable as e:
        size = len(data)
        del data  # nothing is retained; GP_RETAIN_UPLOADS_SECONDS is 0 and there is no code path that stores bytes
        raise Problem(501, "Document pipeline not installed", f"Upload accepted and hashed, but {e}. Install the gp_pipeline "
                      "package into the backend environment (uv pip install -e ../pipeline) to extract fields.",
                      "https://groundplan.dev/problems/pipeline-not-installed", sha256=sha, filename=filename, size_bytes=size,
                      bytes_retained=False) from e
    try:
        result = _dump(process(data, filename, {"household_id": h.id, "state": h.state, "tax_year_latest": h.tax_year_latest,
                                                "property_keys": [p.property_key for p in h.properties if p.property_key]}))
    finally:
        del data
    doc_out = dict(_dump(result.get("document")) or {})
    doc_out.update({"sha256": sha, "filename": doc_out.get("filename") or filename})
    stats: dict = {}
    if result.get("reconciled"):
        ingest.import_reconciled(c.s, h, result["reconciled"])
    keymap = ingest.persist_documents(c.s, h, [doc_out], [_dump(f) for f in result.get("extracted_fields", [])], stats)
    findings = ingest.upsert_findings(c.s, h, [_dump(f) for f in result.get("findings", [])], {}, keymap, stats)
    c.s.commit()
    doc = next(d for d in h.documents if d.sha256 == sha)
    touched = sorted({p.id for p in h.properties if p.property_key in {f.property_key for f in doc.fields}})
    return {"document": svc.document_dict(doc), "extracted_fields": [svc.field_dict(f) for f in doc.fields],
            "findings": [svc.finding_dict(f) for f in findings], "properties_touched": touched}


@router.get("/households/{household_id}/documents")
def list_documents(household_id: str, c: Ctx = Depends()):
    h = c.household(household_id)
    q = m.scoped(m.Document, c.aid).where(m.Document.household_id == h.id).order_by(m.Document.tax_year, m.Document.filename)
    return [svc.document_dict(d) | {"field_count": len(d.fields)} for d in c.s.execute(q).scalars()]


@router.get("/documents/{document_id}")
def get_document(document_id: str, c: Ctx = Depends()):
    d = owned(c.s, m.Document, document_id, c.aid, "Document")
    return {"document": svc.document_dict(d), "fields": [svc.field_dict(f) for f in sorted(d.fields, key=lambda f: (f.page, f.field))]}


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: str, c: Ctx = Depends()):
    c.s.delete(owned(c.s, m.Document, document_id, c.aid, "Document"))
    c.s.commit()
    return Response(status_code=204)


@router.post("/findings/{finding_id}/resolve", summary="Resolve with a chosen value; the value is written back to the data")
def resolve_finding(finding_id: str, body: ResolveIn, c: Ctx = Depends()):
    f = owned(c.s, m.Finding, finding_id, c.aid, "Finding")
    ingest.resolve(c.s, f, body.value, body.note, body.who, "resolved")
    c.s.commit()
    return svc.finding_dict(f)


@router.post("/findings/{finding_id}/dismiss")
def dismiss_finding(finding_id: str, body: DismissIn | None = None, c: Ctx = Depends()):
    f = owned(c.s, m.Finding, finding_id, c.aid, "Finding")
    body = body or DismissIn()
    ingest.resolve(c.s, f, None, body.note, body.who, "dismissed")
    c.s.commit()
    return svc.finding_dict(f)
