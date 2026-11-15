"""CRUD for named work-day templates."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import Template
from app.schemas import OrderIn, TemplateBreakOut, TemplateIn, TemplateOut
from app.services import chains

router = APIRouter(prefix="/api/templates", tags=["templates"])


def _to_out(t: Template) -> TemplateOut:
    breaks = [TemplateBreakOut(**b) for b in json.loads(t.breaks)]
    return TemplateOut(
        id=t.id,
        name=t.name,
        start_time=t.start_time,
        end_time=t.end_time,
        breaks=breaks,
        position=t.position,
    )


@router.get("", response_model=list[TemplateOut])
def list_templates(session: Session = Depends(get_session)) -> list[TemplateOut]:
    """In the order the user set; a new one goes last."""
    rows = session.query(Template).order_by(Template.position, Template.id).all()
    return [_to_out(t) for t in rows]


# Declared before "/{template_id}" so that "order" is not read as an id.
@router.put("/order", response_model=list[TemplateOut])
def set_template_order(body: OrderIn, session: Session = Depends(get_session)) -> list[TemplateOut]:
    chains.set_order(session, Template, body.ids)
    session.commit()
    return list_templates(session)


@router.post("", response_model=TemplateOut, status_code=201)
def create_template(body: TemplateIn, session: Session = Depends(get_session)) -> TemplateOut:
    t = Template(
        name=body.name,
        start_time=body.start_time,
        end_time=body.end_time,
        breaks=json.dumps(
            [
                {
                    "break_minutes": b.break_minutes,
                    "start_time": b.start_time,
                    "end_time": b.end_time,
                }
                for b in body.breaks
            ]
        ),
        position=chains.next_position(session, Template),
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
