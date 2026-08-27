"""Built-in executors for Phase 2 action types.

Each function receives the validated payload and a context dict, performs the
real work and returns a short, human-readable result string (it is echoed back
into the approval card in Telegram).
"""
from __future__ import annotations

from app import repositories as repo
from app.approvals.registry import executor


# ── Tasks ───────────────────────────────────────────────────────────────────

@executor("task.create")
def _task_create(payload: dict, ctx: dict) -> str:
    task = repo.create_task(
        title=payload.get("title") or "Task جدید",
        project_id=payload.get("project_id") or ctx.get("project_id"),
        description=payload.get("description"),
        priority=payload.get("priority", "normal"),
        status=payload.get("status", "inbox"),
        assignee=payload.get("assignee", "Ali"),
        source=payload.get("source", "approval"),
        expected_result=payload.get("expected_result"),
        due_at=payload.get("due_at"),
    )
    return f"Task ثبت شد: {task['task_uid']}"


@executor("task.update_status")
def _task_update_status(payload: dict, ctx: dict) -> str:
    uid = payload.get("task_uid")
    status = payload.get("status")
    if not uid:
        raise ValueError("task_uid لازم است")
    if status not in repo.VALID_TASK_STATUSES:
        raise ValueError(f"status نامعتبر: {status}")
    cur = repo.db.execute(
        "UPDATE tasks SET status=?, updated_at=? WHERE task_uid=?",
        (status, repo.db.now(), uid),
    )
    if getattr(cur, "rowcount", 1) == 0:
        raise ValueError(f"Task یافت نشد: {uid}")
    return f"وضعیت {uid} → {status}"


@executor("task.delete")
def _task_delete(payload: dict, ctx: dict) -> str:
    uid = payload.get("task_uid")
    if not uid:
        raise ValueError("task_uid لازم است")
    repo.db.execute(
        "UPDATE tasks SET status='cancelled', updated_at=? WHERE task_uid=?",
        (repo.db.now(), uid),
    )
    return f"Task {uid} لغو شد"


# ── Memory & decisions ──────────────────────────────────────────────────────

@executor("memory.add")
def _memory_add(payload: dict, ctx: dict) -> str:
    content = (payload.get("content") or "").strip()
    if not content:
        raise ValueError("content لازم است")
    repo.add_memory(
        memory_type=payload.get("memory_type", "fact"),
        scope=payload.get("scope", "user"),
        content=content,
        project_id=payload.get("project_id") or ctx.get("project_id"),
        confidence=float(payload.get("confidence", 0.8)),
        source=payload.get("source", "telegram"),
    )
    return "به حافظه اضافه شد"


@executor("decision.record")
def _decision_record(payload: dict, ctx: dict) -> str:
    problem = (payload.get("problem") or "").strip()
    if not problem:
        raise ValueError("problem لازم است")
    row = repo.record_decision(
        project_id=payload.get("project_id") or ctx.get("project_id"),
        problem=problem,
        evidence=payload.get("evidence"),
        options=payload.get("options"),
        decision=payload.get("decision"),
        reason=payload.get("reason"),
        impact=payload.get("impact"),
    )
    return f"تصمیم #{row['id']} ثبت شد"


# ── Project dossier ─────────────────────────────────────────────────────────

@executor("kpi.add")
def _kpi_add(payload: dict, ctx: dict) -> str:
    project_id = payload.get("project_id") or ctx.get("project_id")
    if not project_id:
        raise ValueError("project_id لازم است")
    kpi = repo.add_kpi(
        project_id=project_id,
        name=payload.get("name") or "KPI",
        target_value=payload.get("target_value"),
        current_value=payload.get("current_value"),
        unit=payload.get("unit"),
        period=payload.get("period", "monthly"),
        direction=payload.get("direction", "up"),
        notes=payload.get("notes"),
    )
    return f"KPI «{kpi['name']}» ثبت شد"


@executor("person.add")
def _person_add(payload: dict, ctx: dict) -> str:
    project_id = payload.get("project_id") or ctx.get("project_id")
    if not project_id:
        raise ValueError("project_id لازم است")
    person = repo.add_person(
        project_id=project_id,
        name=payload.get("name") or "بدون نام",
        role=payload.get("role"),
        contact=payload.get("contact"),
        responsibility=payload.get("responsibility"),
        is_internal=bool(payload.get("is_internal", True)),
        notes=payload.get("notes"),
    )
    return f"{person['name']} به تیم پروژه اضافه شد"


@executor("budget.add_line")
def _budget_add(payload: dict, ctx: dict) -> str:
    project_id = payload.get("project_id") or ctx.get("project_id")
    if not project_id:
        raise ValueError("project_id لازم است")
    line = repo.add_budget_line(
        project_id=project_id,
        label=payload.get("label") or "ردیف بودجه",
        amount=float(payload.get("amount") or 0),
        category=payload.get("category"),
        currency=payload.get("currency", "IRT"),
        kind=payload.get("kind", "expense"),
        period=payload.get("period"),
        spent=float(payload.get("spent") or 0),
        notes=payload.get("notes"),
    )
    return f"ردیف بودجه «{line['label']}» ثبت شد"


@executor("project.update")
def _project_update(payload: dict, ctx: dict) -> str:
    project_id = payload.get("project_id") or ctx.get("project_id")
    if not project_id:
        raise ValueError("project_id لازم است")
    allowed = ("name", "domain", "industry", "status", "notes")
    sets, params = [], []
    for field in allowed:
        if field in payload:
            sets.append(f"{field}=?")
            params.append(payload[field])
    if not sets:
        raise ValueError("هیچ فیلد قابل تغییری داده نشد")
    params.extend([repo.db.now(), project_id])
    repo.db.execute(
        f"UPDATE projects SET {', '.join(sets)}, updated_at=? WHERE id=?", tuple(params)
    )
    return "پروژه به‌روزرسانی شد"


# ── Notifications (§18) ─────────────────────────────────────────────────────

@executor("notification.send")
def _notification_send(payload: dict, ctx: dict) -> str:
    from app.telegram import send_message

    chat_id = payload.get("chat_id") or ctx.get("chat_id")
    text = (payload.get("text") or "").strip()
    if not chat_id or not text:
        raise ValueError("chat_id و text لازم است")
    send_message(chat_id=int(chat_id), text=text)
    return "پیام ارسال شد"


@executor("notification.create")
def _notification_create(payload: dict, ctx: dict) -> str:
    from app.notifications.service import create_notification
    title = (payload.get("title") or "").strip()
    if not title:
        raise ValueError("title لازم است")
    create_notification(
        user_id=payload.get("user_id") or ctx.get("requested_by"),
        type=payload.get("type", "custom"),
        title=title,
        body=payload.get("body"),
        related_type=payload.get("related_type"),
        related_id=payload.get("related_id"),
    )
    return f"اعلان ثبت شد: {title}"


# ── CRM (§14) ─────────────────────────────────────────────────────────────────

@executor("crm.create_contact")
def _crm_create_contact(payload: dict, ctx: dict) -> str:
    from app.crm.repository import create_contact
    name = (payload.get("name") or "").strip()
    if not name:
        raise ValueError("نام مخاطب لازم است")
    contact = create_contact(
        name=name,
        project_id=payload.get("project_id") or ctx.get("project_id"),
        company=payload.get("company"),
        role=payload.get("role"),
        phone=payload.get("phone"),
        email=payload.get("email"),
        telegram=payload.get("telegram"),
        status=payload.get("status", "lead"),
        tags=payload.get("tags"),
        notes=payload.get("notes"),
        source=payload.get("source"),
        owner=payload.get("owner", "Ali"),
        created_by=payload.get("created_by") or ctx.get("requested_by"),
    )
    return f"مخاطب ثبت شد: {contact['contact_uid']} — {name}"


@executor("crm.update_contact")
def _crm_update_contact(payload: dict, ctx: dict) -> str:
    from app.crm.repository import update_contact
    uid = payload.get("contact_uid")
    if not uid:
        raise ValueError("contact_uid لازم است")
    # Remove uid from fields
    fields = {k: v for k, v in payload.items() if k != "contact_uid"}
    if not fields:
        raise ValueError("هیچ فیلدی برای به‌روزرسانی داده نشد")
    row = update_contact(uid, **fields)
    if not row:
        raise ValueError(f"مخاطب یافت نشد: {uid}")
    return f"مخاطب به‌روزرسانی شد: {uid}"


@executor("crm.delete_contact")
def _crm_delete_contact(payload: dict, ctx: dict) -> str:
    from app.crm.repository import delete_contact
    uid = payload.get("contact_uid")
    if not uid:
        raise ValueError("contact_uid لازم است")
    ok = delete_contact(uid)
    if not ok:
        raise ValueError(f"مخاطب یافت نشد: {uid}")
    return f"مخاطب حذف شد: {uid}"


@executor("crm.add_interaction")
def _crm_add_interaction(payload: dict, ctx: dict) -> str:
    from app.crm.repository import add_interaction, get_contact
    contact_uid = payload.get("contact_uid")
    contact_id = payload.get("contact_id")
    if contact_uid and not contact_id:
        c = get_contact(contact_uid)
        if not c:
            raise ValueError(f"مخاطب یافت نشد: {contact_uid}")
        contact_id = c["id"]
    if not contact_id:
        raise ValueError("contact_id یا contact_uid لازم است")
    summary = (payload.get("summary") or "").strip()
    if not summary:
        raise ValueError("خلاصه تعامل لازم است")
    row = add_interaction(
        contact_id=contact_id,
        summary=summary,
        project_id=payload.get("project_id") or ctx.get("project_id"),
        type=payload.get("type", "note"),
        content=payload.get("content"),
        outcome=payload.get("outcome"),
        next_action=payload.get("next_action"),
        next_follow_up_at=payload.get("next_follow_up_at"),
        created_by=payload.get("created_by") or ctx.get("requested_by"),
    )
    return f"تعامل ثبت شد: {row['interaction_uid']}"


@executor("crm.create_deal")
def _crm_create_deal(payload: dict, ctx: dict) -> str:
    from app.crm.repository import create_deal, get_contact
    title = (payload.get("title") or "").strip()
    if not title:
        raise ValueError("عنوان معامله لازم است")
    contact_id = payload.get("contact_id")
    if payload.get("contact_uid") and not contact_id:
        c = get_contact(payload["contact_uid"])
        if c:
            contact_id = c["id"]
    deal = create_deal(
        title=title,
        contact_id=contact_id,
        project_id=payload.get("project_id") or ctx.get("project_id"),
        amount=float(payload.get("amount") or 0),
        currency=payload.get("currency", "IRT"),
        stage=payload.get("stage", "lead"),
        probability=int(payload.get("probability", 50)),
        expected_close_at=payload.get("expected_close_at"),
        notes=payload.get("notes"),
        created_by=payload.get("created_by") or ctx.get("requested_by"),
    )
    return f"معامله ثبت شد: {deal['deal_uid']} — {title}"


@executor("crm.update_deal")
def _crm_update_deal(payload: dict, ctx: dict) -> str:
    from app.crm.repository import update_deal
    uid = payload.get("deal_uid")
    if not uid:
        raise ValueError("deal_uid لازم است")
    fields = {k: v for k, v in payload.items() if k != "deal_uid"}
    if not fields:
        raise ValueError("هیچ فیلدی برای به‌روزرسانی داده نشد")
    row = update_deal(uid, **fields)
    if not row:
        raise ValueError(f"معامله یافت نشد: {uid}")
    return f"معامله به‌روزرسانی شد: {uid}"


@executor("crm.update_deal_stage")
def _crm_update_deal_stage(payload: dict, ctx: dict) -> str:
    from app.crm.repository import update_deal
    uid = payload.get("deal_uid")
    stage = payload.get("stage")
    if not uid or not stage:
        raise ValueError("deal_uid و stage لازم است")
    row = update_deal(uid, stage=stage, probability=payload.get("probability"))
    if not row:
        raise ValueError(f"معامله یافت نشد: {uid}")
    return f"مرحله معامله {uid} → {stage}"


@executor("crm.delete_deal")
def _crm_delete_deal(payload: dict, ctx: dict) -> str:
    from app.crm.repository import delete_deal
    uid = payload.get("deal_uid")
    if not uid:
        raise ValueError("deal_uid لازم است")
    ok = delete_deal(uid)
    if not ok:
        raise ValueError(f"معامله یافت نشد: {uid}")
    return f"معامله حذف شد: {uid}"

