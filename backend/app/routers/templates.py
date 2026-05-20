"""CRUD for named work-day templates."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException

from sqlalchemy.orm import Session

from app.database import get_session
from app.models import Template
from app.schemas import TemplateBreakOut, TemplateIn, TemplateOut

router = APIRouter(prefix="/api/templates", tags=["templates"])


def _to_out(t: Template) -> TemplateOut:
    breaks = [TemplateBreakOut(**b) for b in json.loads(t.breaks)]
    return TemplateOut(id=t.id, name=t.name, start_time=t.start_time, end_time=t.end_time, breaks=breaks)


@router.get("", response_model=list[TemplateOut])
def list_templates(session: Session = Depends(get_session)) -> list[TemplateOut]:
    return [_to_out(t) for t in session.query(Template).order_by(Template.id).all()]


@router.post("", response_model=TemplateOut, status_code=201)
def create_template(body: TemplateIn, session: Session = Depends(get_session)) -> TemplateOut:
    t = Template(
        name=body.name,
        start_time=body.start_time,
        end_time=body.end_time,
        breaks=json.dumps([
            {"break_minutes": b.break_minutes, "start_time": b.start_time, "end_time": b.end_time}
            for b in body.breaks
        ]),
    )
    session.add(t)
    session.commit()
    session.refresh(t)
    return _to_out(t)


@router.delete("/{template_id}", status_code=204)
def delete_template(template_id: int, session: Session = Depends(get_session)) -> None:
    t = session.get(Template, template_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Template not found")
    session.delete(t)
    session.commit()
