"""Master Agent / Orchestrator.

Responsibilities (§4): understand the request, classify intent, resolve the
project, route to the right action, manage memory, record tasks/decisions and
return a final answer.

The agent never imports an HTTP client of a specific LLM — it talks to the
LLMProvider interface only.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from app import approvals, repositories as repo
from app.approvals import risk as risk_mod
from app.llm import LLMMessage, get_provider
from app.llm.base import LLMProvider
from app.logging_config import get_logger, log_event
from app.master.prompts import INTENT_SYSTEM, build_master_prompt

log = get_logger("master")


@dataclass
class IncomingMessage:
    user_id: int
    chat_id: int
    text: str
    username: str | None = None
    first_name: str | None = None


class MasterAgent:
    def __init__(self, provider: LLMProvider | None = None) -> None:
        self.llm = provider or get_provider()

    # ── Public entry point ─────────────────────────────────────────────────
    def handle(self, msg: IncomingMessage) -> str:
        user = repo.upsert_user(msg.user_id, msg.username, msg.first_name)
        convo = repo.get_or_create_conversation(user["id"], msg.chat_id)
        repo.add_message(conversation_id=convo["id"], role="user", content=msg.text)
        repo.record_event(
            "user_message", user_id=user["id"],
            payload={"text": msg.text, "chat_id": msg.chat_id},
        )

        try:
            route = self._classify_intent(msg.text)
            log_event(log, "intent_classified", user_id=user["id"],
                      project_slug=route.get("project_slug"),
                      payload={"intent": route.get("intent"), "confidence": route.get("confidence")})

            answer = self._route(route, msg, user["id"], convo["id"])
        except Exception as exc:  # noqa: BLE001 — never crash the webhook
            log.exception("master.error", extra={"extra_fields": {"error": str(exc)}})
            answer = (
                "⚠️ در پردازش درخواست خطایی رخ داد. جزئیات در لاگ ثبت شد.\n"
                f"خطا: {type(exc).__name__}"
            )

        repo.add_message(conversation_id=convo["id"], role="assistant", content=answer)
        return answer

    # ── Intent classification ──────────────────────────────────────────────
    def _classify_intent(self, text: str) -> dict:
        # Cheap deterministic shortcuts keep common commands fast + cheap (§45).
        low = text.strip().lower()
        if low in ("/start", "شروع", "start"):
            return {"intent": "help", "confidence": 0.99, "project_slug": None}
        if low in ("/tasks", "کارها", "تسک‌ها", "tasks"):
            return {"intent": "list_tasks", "confidence": 0.95, "project_slug": None}
        if low in ("/approvals", "تأییدها", "تاییدها", "approvals", "صف تأیید"):
            return {"intent": "list_approvals", "confidence": 0.99, "project_slug": None}
        if low.startswith("/dossier") or low.startswith("پرونده"):
            rest = text.strip().split(maxsplit=1)
            return {
                "intent": "project_dossier",
                "confidence": 0.99,
                "project_slug": rest[1].strip() if len(rest) > 1 else None,
            }

        messages = [
            LLMMessage(role="system", content=INTENT_SYSTEM),
            LLMMessage(role="user", content=text),
        ]
        try:
            result = self.llm.structured_output(messages, temperature=0.0, max_tokens=400)
        except Exception as exc:  # noqa: BLE001
            log.warning("intent.fallback", extra={"extra_fields": {"error": str(exc)}})
            result = {"intent": "chat", "confidence": 0.3}
        # Normalise
        result.setdefault("intent", "chat")
        result.setdefault("confidence", 0.5)
        return result

    # ── Routing ────────────────────────────────────────────────────────────
    def _route(self, route: dict, msg: IncomingMessage, user_id: int, convo_id: int) -> str:
        intent = route.get("intent", "chat")
        project = None
        if route.get("project_slug"):
            project = repo.get_project(route["project_slug"])

        if intent == "create_task":
            return self._action_create_task(route, project, user_id, msg.chat_id)
        if intent == "list_approvals":
            return self._action_list_approvals(user_id)
        if intent == "project_dossier":
            if not project:
                return "کدوم پروژه؟ مثلاً: «پرونده گیاهکده» یا `/dossier giahkade`."
            return self._action_project_dossier(project)
        if intent == "list_tasks":
            return self._action_list_tasks(project)
        if intent == "project_status":
            if not project:
                return "کدوم پروژه رو می‌خوای؟ نام پروژه رو بگو (مثلاً گیاهکده، امداد سرویس قم، CropExport)."
            return self._action_project_status(project)
        if intent == "last_decision":
            return self._action_last_decision(project)
        if intent == "help":
            return self._help_text()

        # Default: chat via Master with full context
        return self._action_chat(msg, convo_id, project)

    # ── Actions ────────────────────────────────────────────────────────────
    def _action_create_task(self, route: dict, project, user_id: int,
                            chat_id: int | None = None) -> str:
        title = route.get("task_title") or "Task جدید"
        desc = route.get("task_description")
        priority = route.get("priority") or "normal"
        amount = route.get("amount")
        due_hint = route.get("due_hint")

        # Every write goes through the Approval gateway (§19). task.create is
        # 🟢 so it executes immediately — but it is still recorded and audited.
        n = int(amount) if isinstance(amount, int) and amount > 0 else 1
        n = max(1, min(n, 20))
        results = []
        for i in range(n):
            t_title = title if n == 1 else f"{title} ({i+1} از {n})"
            results.append(approvals.request_action(
                action_type="task.create",
                title=f"ثبت Task: {t_title}",
                summary=desc,
                payload={
                    "title": t_title,
                    "project_id": project["id"] if project else None,
                    "description": desc,
                    "priority": priority,
                    "source": "telegram",
                },
                requested_by=user_id,
                project_id=project["id"] if project else None,
                chat_id=chat_id,
                agent="master",
            ))

        created = [r for r in results if r.executed]
        failed = [r for r in results if not r.executed]

        repo.record_event(
            "tasks_created", user_id=user_id,
            project_id=project["id"] if project else None,
            payload={"count": len(created), "uids": [r.action_uid for r in created]},
        )

        proj_name = project["name"] if project else "بدون پروژه"
        lines = [f"✅ {len(created)} Task ثبت شد.", f"📂 پروژه: {proj_name}"]
        for r in created:
            lines.append(f"  • [{priority}] {r.result}")
        for r in failed:
            lines.append(f"  ⚠️ {r.message}")
        if due_hint:
            lines.append(f"🕒 مهلت اشاره‌شده: {due_hint} (برای ثبت دقیق deadline بگو تا زمان را قطعی کنم).")
        lines.append("\nمی‌تونی وضعیتش رو با «کارها» ببینی.")
        return "\n".join(lines)

    # ── Approval queue (§19) ───────────────────────────────────────────────
    def _action_list_approvals(self, user_id: int) -> str:
        repo.expire_stale_actions()
        user = repo.get_user(user_id)
        items = repo.list_pending_actions(
            requested_by=user["id"] if user else None, limit=15
        )
        if not items:
            return "✅ صف تأیید خالی است — هیچ اقدامی منتظر تصمیم تو نیست."
        lines = [f"⏳ {len(items)} اقدام در انتظار تأیید:"]
        for a in items:
            emoji = risk_mod.EMOJI.get(a["risk"], "🟡")
            proj = f"[{a['project_name']}] " if a["project_name"] else ""
            step = ""
            if a["status"] == "confirming":
                step = f" (تأیید {a['approvals_count']}/{a['approvals_required']})"
            lines.append(f"{emoji} {proj}{a['title']}{step}\n     `{a['action_uid']}`")
        lines.append("\nروی دکمه‌های همان کارت در چت [✅ تأیید] یا [❌ لغو] را بزن.")
        return "\n".join(lines)

    # ── Full project dossier (§2) ──────────────────────────────────────────
    def _action_project_dossier(self, project) -> str:
        d = repo.project_dossier(project)
        p = d["project"]
        lines = [f"📁 *پرونده کامل پروژه: {p['name']}*"]
        ident = []
        if p.get("domain"):
            ident.append(f"🌐 {p['domain']}")
        if p.get("industry"):
            ident.append(f"🏷 {p['industry']}")
        ident.append(f"وضعیت: {p.get('status')}")
        lines.append(" | ".join(ident))
        if p.get("notes"):
            lines.append(f"\n📝 {p['notes']}")

        kpis = d["kpis"]
        lines.append(f"\n📊 *KPIها* ({len(kpis)})")
        if kpis:
            for k in kpis:
                cur_v = k["current_value"]
                tgt = k["target_value"]
                unit = k["unit"] or ""
                progress = ""
                if cur_v is not None and tgt:
                    if k["direction"] == "up":
                        pct = cur_v / tgt * 100
                    else:
                        pct = (tgt / cur_v * 100) if cur_v else 0
                    progress = f" — {pct:.0f}٪ هدف"
                lines.append(f"   • {k['name']}: {cur_v if cur_v is not None else '—'}"
                             f" / {tgt if tgt is not None else '—'} {unit}{progress}")
        else:
            lines.append("   (هنوز KPI ثبت نشده)")

        budget = d["budget"]
        lines.append(f"\n💰 *بودجه* ({len(budget)} ردیف)")
        if budget:
            for cur_code, tot in d["budget_totals"].items():
                lines.append(f"   • {cur_code}: برنامه {tot['planned']:,.0f} | "
                             f"هزینه‌شده {tot['spent']:,.0f} | درآمد {tot['income']:,.0f}")
            for b in budget[:6]:
                lines.append(f"     - {b['label']}: {float(b['amount'] or 0):,.0f} {b['currency']}")
        else:
            lines.append("   (بودجه‌ای ثبت نشده)")

        people = d["people"]
        lines.append(f"\n👥 *افراد* ({len(people)})")
        if people:
            for person in people:
                tag = "داخلی" if person["is_internal"] else "خارجی"
                extra = f" | {person['responsibility']}" if person["responsibility"] else ""
                lines.append(f"   • {person['name']} — {person['role'] or '—'} ({tag}){extra}")
        else:
            lines.append("   (فردی ثبت نشده)")

        tasks = d["open_tasks"]
        lines.append(f"\n📋 *Taskهای باز* ({len(tasks)})")
        for t in tasks[:6]:
            lines.append(f"   • {t['title']} ({t['priority']}/{t['status']})")
        if len(tasks) > 6:
            lines.append(f"   … و {len(tasks)-6} مورد دیگر")

        if d["decisions"]:
            lines.append("\n🧭 *آخرین تصمیم‌ها*")
            for dec in d["decisions"]:
                lines.append(f"   • {dec['problem']} → {dec['decision'] or 'ثبت شده'}")

        if d["memories"]:
            lines.append("\n🧠 *حافظه پروژه*")
            for m in d["memories"][:6]:
                lines.append(f"   • {m['content']}")

        if d["pending_actions"]:
            lines.append(f"\n⏳ *در انتظار تأیید* ({len(d['pending_actions'])})")
            for a in d["pending_actions"]:
                lines.append(f"   {risk_mod.EMOJI.get(a['risk'], '🟡')} {a['title']}")

        lines.append("\n_برای افزودن KPI/بودجه/فرد فقط بگو؛ موارد پرخطر با دکمه تأیید می‌شوند._")
        return "\n".join(lines)

    def _action_list_tasks(self, project) -> str:
        tasks = repo.list_tasks(project_id=project["id"] if project else None, limit=15)
        if not tasks:
            base = f"برای پروژه {project['name']} " if project else ""
            return f"📭 {base}هیچ Task بازی نیست. عالی به نظر می‌رسه!"
        title = f"📋 Taskهای باز ({'همه پروژه‌ها' if not project else project['name']}):\n"
        lines = []
        for t in tasks:
            pname = f"[{t['project_name']}] " if not project and t["project_name"] else ""
            lines.append(f"• {pname}{t['title']} — {t['priority']} / {t['status']}")
        return title + "\n".join(lines)

    def _action_project_status(self, project) -> str:
        import json as _json
        meta = {}
        try:
            meta = _json.loads(project["metadata_json"] or "{}")
        except Exception:  # noqa: BLE001
            pass

        open_tasks = repo.list_tasks(project_id=project["id"], limit=50)
        decisions = repo.list_decisions(project_id=project["id"], limit=3)

        lines = [f"📊 وضعیت پروژه: {project['name']}"]
        if project["domain"]:
            lines.append(f"🌐 {project['domain']}")
        if project["industry"]:
            lines.append(f"🏷 {project['industry']}")
        if project["notes"]:
            lines.append(f"\n📝 {project['notes']}")

        lines.append(f"\n🔸 Taskهای باز: {len(open_tasks)}")
        for t in open_tasks[:5]:
            lines.append(f"   • {t['title']} ({t['priority']}/{t['status']})")
        if len(open_tasks) > 5:
            lines.append(f"   … و {len(open_tasks)-5} مورد دیگر")

        if decisions:
            lines.append("\n🔹 آخرین تصمیم‌ها:")
            for d in decisions:
                lines.append(f"   • {d['problem']} → {d['decision'] or 'ثبت شده'}")

        # Project-specific quick hints
        if project["slug"] == "giahkade":
            existing = meta.get("existing_articles", [])
            lines.append("\n💡 یادآوری: قبل از موضوع جدید، Content Index بررسی شود تا Cannibalization نشود.")
            if existing:
                lines.append("   مقالات موجود نمونه: " + "؛ ".join(existing))
        elif project["slug"] == "esqom":
            cwv = meta.get("core_web_vitals", {})
            lines.append(f"\n⚠️ Core Web Vitals: Failed (LCP~{cwv.get('lcp_ms')}ms, INP~{cwv.get('inp_ms')}ms).")
            lines.append("   تمرکز: SEO Recovery، CTR و Lead.")

        return "\n".join(lines)

    def _action_last_decision(self, project) -> str:
        decisions = repo.list_decisions(project_id=project["id"] if project else None, limit=5)
        if not decisions:
            return "📭 هنوز تصمیمی ثبت نشده."
        lines = ["🧭 آخرین تصمیم‌ها:"]
        for d in decisions:
            proj = f"[{d['project_name']}] " if d["project_name"] else ""
            lines.append(f"• {proj}{d['problem']}")
            if d["decision"]:
                lines.append(f"    ↳ تصمیم: {d['decision']}")
            if d["reason"]:
                lines.append(f"    ↳ دلیل: {d['reason']}")
        return "\n".join(lines)

    # ── Chat with full context ─────────────────────────────────────────────
    def _action_chat(self, msg: IncomingMessage, convo_id: int, project) -> str:
        projects = repo.list_projects(active_only=True)
        projects_block = "\n".join(
            f"- {p['name']} (slug: {p['slug']})" + (f" — {p['domain']}" if p["domain"] else "")
            for p in projects
        )
        memories = repo.search_memory(scope="user", limit=10)
        memory_block = "\n".join(f"- {m['content']}" for m in memories) or "- (بدون حافظه ثبت‌شده)"

        system_prompt = build_master_prompt(projects_block, memory_block)

        history = repo.recent_messages(convo_id, limit=8)
        messages: list[LLMMessage] = [LLMMessage(role="system", content=system_prompt)]
        if project:
            import json as _json
            try:
                _meta = _json.loads(project["metadata_json"] or "{}")
            except Exception:  # noqa: BLE001
                _meta = {}
            project_block = (
                f"پروژه مرتبط: {project['name']} (slug={project['slug']})\n"
                f"دامنه: {project['domain'] or '—'}\n"
                f"صنعت: {project['industry'] or '—'}\n"
                f"وضعیت: {project['status']}\n"
                f"یادداشت‌ها و اطلاعات قطعی:\n{project['notes'] or '—'}\n"
                f"متادیتا:\n{_json.dumps(_meta, ensure_ascii=False, indent=2)}"
            )
            messages.append(LLMMessage(role="system", content=project_block))
        for m in history:
            if m["role"] in ("user", "assistant"):
                messages.append(LLMMessage(role=m["role"], content=m["content"]))

        resp = self.llm.chat(messages, temperature=0.4, max_tokens=900)
        # store token usage for cost awareness (§45)
        last_user = repo.recent_messages(convo_id, limit=1)
        if last_user:
            repo.db.execute(
                "UPDATE messages SET tokens_in=?, tokens_out=? WHERE id=?",
                (resp.prompt_tokens, resp.completion_tokens, last_user[0]["id"]),
            )
        return resp.content or "پاسخی دریافت نشد؛ دوباره امتحان کن."

    # ── Help ───────────────────────────────────────────────────────────────
    def _help_text(self) -> str:
        return (
            "سلام علی 👋 من Ali OS هستم، Chief of Staff هوش مصنوعی تو.\n\n"
            "کارهایی که الان می‌تونم انجام بدم:\n"
            "• گفتگو و تحلیل با حافظه‌ی پروژه‌ها\n"
            "• ثبت خودکار Task از حرفات (مثلاً: «برای گیاهکده ۳ مقاله این هفته آماده کن»)\n"
            "• دیدن Taskها: «کارها» یا «تسک‌های امداد سرویس قم»\n"
            "• وضعیت پروژه: «وضعیت گیاهکده رو بگو»\n"
            "• آخرین تصمیم‌ها: «آخرین تصمیم درباره CropExport چی بود؟»\n"
            "• پرونده کامل پروژه: «پرونده گیاهکده» یا /dossier giahkade\n"
            "• صف تأیید: /approvals — اقدامات 🟡/🔴 با دکمه [✅ تأیید] [❌ لغو] در همین چت\n\n"
            "🔐 سیستم تأیید سه‌سطحی فعال است: 🟢 مستقیم اجرا می‌شود، "
            "🟡 یک تأیید و 🔴 دو تأیید از تو می‌گیرد.\n\n"
            "پروژه‌های فعلی: Net Nova، گیاهکده، E-Ferdowsi، امداد سرویس قم، CropExport، آبادگران، Sir-Siah.\n\n"
            "فقط کافیه طبیعی حرف بزنی؛ Intent رو خودم تشخیص می‌دم."
        )
