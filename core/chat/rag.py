"""RAG-style chat service for grounded follow-up questions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
import re
from uuid import NAMESPACE_URL, uuid5

from core.schemas import AgentState, CareerStateMemory, ContentCategory, ProfileMemory
from core.tools import (
    EmbeddingGatewayError,
    LLMGatewayError,
    PromptLoader,
    VectorStoreError,
)


@dataclass(frozen=True)
class RAGDocument:
    """One retrievable context document derived from items or memory."""

    doc_id: str
    doc_type: str
    source_label: str
    text: str
    snippet: str
    item_id: str | None = None
    created_at: datetime | None = None
    category: str | None = None


@dataclass(frozen=True)
class RetrievedContext:
    """One retrieval result returned by the chat engine."""

    doc_id: str
    doc_type: str
    source_label: str
    snippet: str
    item_id: str | None
    score: float


@dataclass(frozen=True)
class RAGChatResult:
    """Grounded answer plus citations for API serialization."""

    answer: str
    supporting_item_ids: list[str]
    citations: list[RetrievedContext]
    retrieval_mode: str


@dataclass(frozen=True)
class QueryAnalysis:
    """Parsed retrieval preferences inferred from one chat query."""

    categories: tuple[ContentCategory, ...]
    keywords: tuple[str, ...]
    company: str | None
    role: str | None
    intent: str
    search_hints: tuple[str, ...]
    profile_update_hints: tuple[str, ...]
    career_update_hints: tuple[str, ...]
    should_update_memory: bool
    needs_resume: bool
    recent_days: int
    rewritten_query: str | None = None
    retrieval_queries: tuple[str, ...] = ()
    web_search_queries: tuple[str, ...] = ()


class RAGChatService:
    """Build documents, retrieve context, rerank candidates, and answer with citations."""

    def __init__(self, *, dependencies, settings) -> None:
        self.dependencies = dependencies
        self.settings = settings

    def answer(
        self,
        *,
        query: str,
        states: list[AgentState],
        profile: ProfileMemory,
        career_state: CareerStateMemory,
        item_id: str | None = None,
        recent_days: int = 30,
        extra_documents: list[RAGDocument] | None = None,
        query_analysis: QueryAnalysis | None = None,
    ) -> RAGChatResult:
        """Answer one user question from retrieved items and memory context."""

        query_analysis = query_analysis or self._analyze_query(
            query=query,
            recent_days=recent_days,
        )
        documents = self._build_documents(
            states=states,
            profile=profile,
            career_state=career_state,
            item_id=item_id,
        )
        if extra_documents:
            documents.extend(extra_documents)
        if not documents:
            return RAGChatResult(
                answer="当前还没有可检索的条目，先提交一条文本、链接、截图或 Boss 直聘输入。",
                supporting_item_ids=[],
                citations=[],
                retrieval_mode="empty",
            )

        retrieved, retrieval_mode = self._retrieve(
            query=query,
            documents=documents,
            item_id=item_id,
            query_analysis=query_analysis,
        )
        reranked = self._rerank(query=query, contexts=retrieved, query_analysis=query_analysis)
        answer = self._generate_answer(
            query=query,
            contexts=reranked,
            profile=profile,
            career_state=career_state,
            query_analysis=query_analysis,
        )
        supporting_item_ids = [
            context.item_id
            for context in reranked
            if context.item_id is not None
        ]
        return RAGChatResult(
            answer=answer,
            supporting_item_ids=list(dict.fromkeys(supporting_item_ids)),
            citations=reranked,
            retrieval_mode=retrieval_mode,
        )

    def analyze_query(self, *, query: str, recent_days: int = 30) -> QueryAnalysis:
        """Expose query analysis so callers can reuse one shared planning result."""

        return self._analyze_query(query=query, recent_days=recent_days)

    def _build_documents(
        self,
        *,
        states: list[AgentState],
        profile: ProfileMemory,
        career_state: CareerStateMemory,
        item_id: str | None,
    ) -> list[RAGDocument]:
        documents: list[RAGDocument] = []

        for state in states:
            if state.normalized_item is None:
                continue
            if item_id and state.normalized_item.id != item_id:
                continue

            normalized = state.normalized_item
            card = state.render_card
            extracted = state.extracted_signal
            original_source_ref = str(
                normalized.source_metadata.get("original_source_ref") or normalized.source_ref or ""
            ).strip() or None
            if card and card.summary_one_line:
                summary = card.summary_one_line
            elif extracted and extracted.summary_one_line:
                summary = extracted.summary_one_line
            else:
                summary = normalized.source_title or normalized.id
            parts = [
                f"条目摘要：{summary}",
                f"来源类型：{normalized.source_type.value}",
                f"工作流状态：{state.status.value}",
                f"分类：{(extracted.category.value if extracted else state.classified_category.value if state.classified_category else 'unknown')}",
                f"源引用：{original_source_ref or '无'}",
                f"原文：{normalized.normalized_text}",
            ]
            if extracted is not None:
                if extracted.company:
                    parts.append(f"公司：{extracted.company}")
                if extracted.role:
                    parts.append(f"岗位：{extracted.role}")
                if extracted.city:
                    parts.append(f"地点：{extracted.city}")
                if extracted.ddl:
                    parts.append(f"截止时间：{extracted.ddl.isoformat()}")
                if extracted.interview_time:
                    parts.append(f"面试时间：{extracted.interview_time.isoformat()}")
                if extracted.event_time:
                    parts.append(f"事件时间：{extracted.event_time.isoformat()}")
                if extracted.summary_one_line:
                    parts.append(f"提取摘要：{extracted.summary_one_line}")
                if extracted.apply_url:
                    parts.append(f"投递链接：{extracted.apply_url}")
                if extracted.source_url:
                    parts.append(f"来源网页：{extracted.source_url}")

            documents.append(
                RAGDocument(
                    doc_id=f"item:{normalized.id}",
                    doc_type="item",
                    source_label=summary,
                    text="\n".join(parts),
                    snippet=(
                        "；".join(
                            part
                            for part in [
                                f"源引用：{normalized.source_ref}" if normalized.source_ref else "",
                                f"原始来源：{original_source_ref}" if original_source_ref else "",
                                f"投递链接：{extracted.apply_url}" if extracted and extracted.apply_url else "",
                                f"公司：{extracted.company}" if extracted and extracted.company else "",
                                f"岗位：{extracted.role}" if extracted and extracted.role else "",
                                f"摘要：{summary}",
                            ]
                            if part
                        )
                    )[:240]
                    or (normalized.normalized_text or normalized.raw_content)[:240],
                    item_id=normalized.id,
                    created_at=card.updated_at if card and card.updated_at else normalized.created_at,
                    category=(
                        extracted.category.value
                        if extracted is not None
                        else state.classified_category.value if state.classified_category else None
                    ),
                )
            )

            if original_source_ref or (extracted is not None and extracted.apply_url):
                link_parts = [
                    f"条目摘要：{summary}",
                    f"源引用：{original_source_ref or '无'}",
                    f"投递链接：{extracted.apply_url if extracted and extracted.apply_url else original_source_ref or '无'}",
                ]
                if extracted is not None:
                    if extracted.company:
                        link_parts.append(f"公司：{extracted.company}")
                    if extracted.role:
                        link_parts.append(f"岗位：{extracted.role}")
                documents.append(
                    RAGDocument(
                        doc_id=f"job_link:{normalized.id}",
                        doc_type="job_link",
                        source_label=f"名称与链接 - {summary}",
                        text="\n".join(link_parts),
                        snippet="；".join(link_parts)[:240],
                        item_id=normalized.id,
                        created_at=card.updated_at if card and card.updated_at else normalized.created_at,
                        category=(
                            extracted.category.value
                            if extracted is not None
                            else state.classified_category.value if state.classified_category else None
                        ),
                    )
                )

            schedule_lines = []
            if extracted is not None:
                if extracted.ddl:
                    schedule_lines.append(f"DDL：{extracted.ddl.isoformat()}")
                if extracted.interview_time:
                    schedule_lines.append(f"面试：{extracted.interview_time.isoformat()}")
                if extracted.event_time:
                    schedule_lines.append(f"活动：{extracted.event_time.isoformat()}")
            if schedule_lines:
                documents.append(
                    RAGDocument(
                        doc_id=f"schedule:{normalized.id}",
                        doc_type="schedule",
                        source_label=f"时间节点 - {summary}",
                        text="\n".join(
                            [
                                f"关联条目：{summary}",
                                *schedule_lines,
                                f"分类：{(extracted.category.value if extracted else state.classified_category.value if state.classified_category else 'unknown')}",
                            ]
                        ),
                        snippet="；".join(schedule_lines)[:240],
                        item_id=normalized.id,
                        created_at=card.updated_at if card and card.updated_at else normalized.created_at,
                        category=(
                            extracted.category.value
                            if extracted is not None
                            else state.classified_category.value if state.classified_category else None
                        ),
                    )
                )

            for reminder in state.reminder_tasks:
                documents.append(
                    RAGDocument(
                        doc_id=f"reminder:{reminder.id}",
                        doc_type="reminder",
                        source_label=f"提醒 - {reminder.title}",
                        text="\n".join(
                            [
                                f"提醒标题：{reminder.title}",
                                f"触发时间：{reminder.trigger_time.isoformat()}",
                                f"优先级：{reminder.priority.value}",
                                f"来源条目：{summary}",
                            ]
                        ),
                        snippet=(
                            f"{reminder.title}；触发时间 {reminder.trigger_time.isoformat()}；"
                            f"优先级 {reminder.priority.value}"
                        )[:240],
                        item_id=normalized.id,
                        created_at=reminder.trigger_time,
                        category=(
                            extracted.category.value
                            if extracted is not None
                            else state.classified_category.value if state.classified_category else None
                        ),
                    )
                )

        profile_bits = [
            f"目标岗位：{', '.join(profile.target_roles) or '未配置'}",
            f"优先领域：{', '.join(profile.priority_domains) or '未配置'}",
            f"核心技能：{', '.join(profile.skills) or '未配置'}",
        ]
        if profile.persona_keywords:
            profile_bits.append(f"自我描述关键词：{', '.join(profile.persona_keywords)}")
        if profile.summary:
            profile_bits.append(f"画像摘要：{profile.summary}")
        documents.append(
            RAGDocument(
                doc_id=f"profile:{profile.user_id}:{profile.workspace_id or 'default'}",
                doc_type="profile",
                source_label="长期画像",
                text="\n".join(profile_bits),
                snippet="；".join(profile_bits)[:240],
                created_at=profile.updated_at,
            )
        )

        for index, project in enumerate(profile.projects):
            project_bits = [
                f"项目名称：{project.name}",
                f"项目摘要：{project.summary}",
            ]
            if project.role:
                project_bits.append(f"角色：{project.role}")
            if project.tech_stack:
                project_bits.append(f"技术栈：{', '.join(project.tech_stack)}")
            if project.highlight_points:
                project_bits.append(f"亮点：{'；'.join(project.highlight_points)}")
            documents.append(
                RAGDocument(
                    doc_id=f"project:{profile.user_id}:{index}:{project.name}",
                    doc_type="project",
                    source_label=f"项目经历 - {project.name}",
                    text="\n".join(project_bits),
                    snippet=project.summary[:240],
                    created_at=profile.updated_at,
                )
            )

        if profile.resume_snapshot is not None:
            resume_bits = [
                f"文件名：{profile.resume_snapshot.file_name or '未命名简历'}",
                f"简历摘要：{profile.resume_snapshot.summary or '未生成摘要'}",
                f"简历原文：{profile.resume_snapshot.text}",
            ]
            documents.append(
                RAGDocument(
                    doc_id=f"resume:{profile.user_id}:{profile.workspace_id or 'default'}",
                    doc_type="resume",
                    source_label="简历原文",
                    text="\n".join(resume_bits),
                    snippet=(profile.resume_snapshot.summary or profile.resume_snapshot.text)[:240],
                    created_at=profile.resume_snapshot.updated_at,
                )
            )

        career_bits = [
            f"今日重点：{', '.join(career_state.today_focus) or '未配置'}",
            f"当前优先级：{', '.join(career_state.active_priorities) or '未配置'}",
        ]
        if career_state.watched_companies:
            career_bits.append(f"重点关注公司：{', '.join(career_state.watched_companies)}")
        if career_state.notes:
            career_bits.append(f"当前备注：{career_state.notes}")
        documents.append(
            RAGDocument(
                doc_id=f"career:{career_state.user_id}:{career_state.workspace_id or 'default'}",
                doc_type="career_state",
                source_label="动态求职状态",
                text="\n".join(career_bits),
                snippet="；".join(career_bits)[:240],
                created_at=career_state.updated_at,
            )
        )

        for index, deadline in enumerate(career_state.upcoming_deadlines):
            documents.append(
                RAGDocument(
                    doc_id=f"deadline:{career_state.user_id}:{index}:{deadline.title}",
                    doc_type="deadline",
                    source_label=f"近期DDL - {deadline.title}",
                    text="\n".join(
                        [
                            f"标题：{deadline.title}",
                            f"截止时间：{deadline.due_at.isoformat()}",
                            f"建议动作：{deadline.recommended_action.value if deadline.recommended_action else '未配置'}",
                        ]
                    ),
                    snippet=(
                        f"{deadline.title}；截止时间 {deadline.due_at.isoformat()}；"
                        f"建议动作 {deadline.recommended_action.value if deadline.recommended_action else '未配置'}"
                    )[:240],
                    item_id=deadline.source_item_id,
                    created_at=deadline.due_at,
                )
            )

        for index, interview in enumerate(career_state.active_interviews):
            documents.append(
                RAGDocument(
                    doc_id=f"active_interview:{career_state.user_id}:{index}:{interview.company}",
                    doc_type="active_interview",
                    source_label=f"进行中面试 - {interview.company} {interview.role}",
                    text="\n".join(
                        [
                            f"公司：{interview.company}",
                            f"岗位：{interview.role}",
                            f"阶段：{interview.stage}",
                            f"时间：{interview.scheduled_at.isoformat() if interview.scheduled_at else '待定'}",
                            f"地点：{interview.location or '未配置'}",
                        ]
                    ),
                    snippet=(
                        f"{interview.company} {interview.role}；阶段 {interview.stage}；"
                        f"时间 {interview.scheduled_at.isoformat() if interview.scheduled_at else '待定'}"
                    )[:240],
                    item_id=interview.source_item_id,
                    created_at=interview.scheduled_at or career_state.updated_at,
                )
            )

        return documents

    def _retrieve(
        self,
        *,
        query: str,
        documents: list[RAGDocument],
        item_id: str | None,
        query_analysis: QueryAnalysis,
    ) -> tuple[list[RetrievedContext], str]:
        if (
            item_id is None
            and self.settings.rag.enable_live_rag
            and self.dependencies.embedding_gateway.is_available("dashscope:embedding")
            and self.dependencies.vector_store.is_available()
        ):
            try:
                return (
                    self._retrieve_live(
                        query=query,
                        documents=documents,
                        query_analysis=query_analysis,
                    ),
                    "live_qdrant_hybrid",
                )
            except (EmbeddingGatewayError, VectorStoreError):
                pass
        return (
            self._retrieve_local(
                query=query,
                documents=documents,
                query_analysis=query_analysis,
            ),
            "local_hybrid",
        )

    def _retrieve_live(
        self,
        *,
        query: str,
        documents: list[RAGDocument],
        query_analysis: QueryAnalysis,
    ) -> list[RetrievedContext]:
        query_variants = self._query_variants(query, query_analysis=query_analysis)
        embeddings = self.dependencies.embedding_gateway.embed_texts(
            route="dashscope:embedding",
            texts=[document.text for document in documents],
        )
        if not embeddings:
            return []

        self.dependencies.vector_store.ensure_collection(
            name=self.settings.rag.collection_name,
            vector_size=len(embeddings[0]),
        )
        self.dependencies.vector_store.upsert_points(
            collection_name=self.settings.rag.collection_name,
            points=[
                {
                    "id": str(uuid5(NAMESPACE_URL, document.doc_id)),
                    "vector": vector,
                    "payload": {
                        "doc_id": document.doc_id,
                        "doc_type": document.doc_type,
                        "source_label": document.source_label,
                        "snippet": document.snippet,
                        "item_id": document.item_id,
                        "created_at": document.created_at.isoformat()
                        if document.created_at
                        else None,
                        "category": document.category,
                    },
                }
                for document, vector in zip(documents, embeddings, strict=False)
            ],
        )

        query_vectors = self.dependencies.embedding_gateway.embed_texts(
            route="dashscope:embedding",
            texts=query_variants,
        )

        merged: dict[str, RetrievedContext] = {}
        for variant_index, query_vector in enumerate(query_vectors):
            results = self.dependencies.vector_store.query_points(
                collection_name=self.settings.rag.collection_name,
                query_vector=query_vector,
                limit=self.settings.rag.query_limit,
            )
            for rank, result in enumerate(results, start=1):
                payload = result.get("payload", {})
                doc_id = str(payload.get("doc_id") or result.get("id"))
                base_score = float(result.get("score") or 0.0)
                fused_score = (
                    base_score
                    + (1.0 / (20 + rank))
                    + self._analysis_bonus(
                        category=str(payload.get("category") or ""),
                        source_label=str(payload.get("source_label") or ""),
                        snippet=str(payload.get("snippet") or ""),
                        created_at=self._parse_created_at(payload.get("created_at")),
                        query_analysis=query_analysis,
                    )
                    + (0.015 * variant_index if variant_index == 0 else 0.0)
                )
                existing = merged.get(doc_id)
                if existing is None or fused_score > existing.score:
                    merged[doc_id] = RetrievedContext(
                        doc_id=doc_id,
                        doc_type=str(payload.get("doc_type") or "unknown"),
                        source_label=str(payload.get("source_label") or "引用"),
                        snippet=str(payload.get("snippet") or ""),
                        item_id=payload.get("item_id"),
                        score=fused_score,
                    )

        contexts = sorted(merged.values(), key=lambda item: item.score, reverse=True)
        return contexts[: self.settings.rag.query_limit]

    def _retrieve_local(
        self,
        *,
        query: str,
        documents: list[RAGDocument],
        query_analysis: QueryAnalysis,
    ) -> list[RetrievedContext]:
        query_variants = self._query_variants(query, query_analysis=query_analysis)
        scored: list[RetrievedContext] = []
        for document in documents:
            per_variant_scores: list[float] = []
            for variant_index, variant in enumerate(query_variants):
                variant_score = self._lexical_score(variant, document.text) + self._analysis_bonus(
                    category=document.category or "",
                    source_label=document.source_label,
                    snippet=document.snippet,
                    created_at=document.created_at,
                    query_analysis=query_analysis,
                )
                variant_score += self._keyword_overlap_score(
                    query_tokens=self._important_tokens(variant, query_analysis=query_analysis),
                    text=document.text,
                )
                if variant_index == 0:
                    variant_score += 0.015
                per_variant_scores.append(variant_score)
            score = max(per_variant_scores, default=0.0)
            if len([value for value in per_variant_scores if value > 0]) > 1:
                score += 0.03
            if score <= 0:
                continue
            scored.append(
                RetrievedContext(
                    doc_id=document.doc_id,
                    doc_type=document.doc_type,
                    source_label=document.source_label,
                    snippet=document.snippet,
                    item_id=document.item_id,
                    score=score,
                )
            )
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[: self.settings.rag.query_limit]

    def _rerank(
        self,
        *,
        query: str,
        contexts: list[RetrievedContext],
        query_analysis: QueryAnalysis,
    ) -> list[RetrievedContext]:
        reranked = []
        query_chars = self._important_chars(query)
        for context in contexts:
            source_chars = self._important_chars(context.source_label + context.snippet)
            overlap = len(query_chars & source_chars)
            rerank_score = context.score + overlap * 0.03
            if context.doc_type == "item":
                rerank_score += 0.05
            if any(keyword in (context.source_label + context.snippet) for keyword in query_analysis.keywords):
                rerank_score += 0.08
            reranked.append(
                RetrievedContext(
                    doc_id=context.doc_id,
                    doc_type=context.doc_type,
                    source_label=context.source_label,
                    snippet=context.snippet,
                    item_id=context.item_id,
                    score=rerank_score,
                )
            )
        reranked.sort(key=lambda item: item.score, reverse=True)
        return reranked[: self.settings.rag.rerank_limit]

    def _query_variants(self, query: str, *, query_analysis: QueryAnalysis) -> tuple[str, ...]:
        variants = [
            query.strip(),
            (query_analysis.rewritten_query or "").strip(),
            *[value.strip() for value in query_analysis.retrieval_queries],
        ]
        unique: list[str] = []
        seen: set[str] = set()
        for value in variants:
            normalized = re.sub(r"\s+", " ", value).strip()
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            unique.append(normalized)
        return tuple(unique[:5] or [query.strip()])

    def _generate_answer(
        self,
        *,
        query: str,
        contexts: list[RetrievedContext],
        profile: ProfileMemory,
        career_state: CareerStateMemory,
        query_analysis: QueryAnalysis,
    ) -> str:
        if not contexts:
            if query_analysis.needs_resume and profile.resume_snapshot is None:
                return "当前缺少简历上下文，先上传简历或补充项目经历，再给你更个性化的建议。"
            return "我还没从现有条目里检索到足够上下文，先补一条岗位、对话、简历或画像信息会更稳。"

        route = self.dependencies.model_router.select("chat", "medium")
        if self.dependencies.llm_gateway.is_available(route):
            try:
                prompt = self.dependencies.prompt_loader.load("chat_rag")
                response = self.dependencies.llm_gateway.complete_json(
                    route=route,
                    task_name="chat_rag_answer",
                    system_prompt=prompt,
                    user_payload={
                        "query": query,
                        "query_plan": {
                            "intent": query_analysis.intent,
                            "search_hints": list(query_analysis.search_hints),
                            "rewritten_query": query_analysis.rewritten_query,
                            "retrieval_queries": list(query_analysis.retrieval_queries),
                            "web_search_queries": list(query_analysis.web_search_queries),
                            "profile_update_hints": list(query_analysis.profile_update_hints),
                            "career_update_hints": list(query_analysis.career_update_hints),
                            "needs_resume": query_analysis.needs_resume,
                        },
                        "contexts": [
                            {
                                "doc_id": context.doc_id,
                                "doc_type": context.doc_type,
                                "source_label": context.source_label,
                                "snippet": context.snippet,
                                "score": round(context.score, 4),
                            }
                            for context in contexts
                        ],
                        "attachment_summaries": [
                            {
                                "source_label": context.source_label,
                                "snippet": context.snippet,
                            }
                            for context in contexts
                            if context.doc_type in {"resume", "document"}
                        ],
                        "profile_summary": {
                            "target_roles": profile.target_roles,
                            "priority_domains": profile.priority_domains,
                            "skills": profile.skills,
                            "persona_keywords": profile.persona_keywords,
                            "summary": profile.summary,
                            "resume_summary": (
                                profile.resume_snapshot.summary
                                if profile.resume_snapshot is not None
                                else None
                            ),
                        },
                        "career_state_summary": {
                            "today_focus": career_state.today_focus,
                            "active_priorities": career_state.active_priorities,
                            "watched_companies": career_state.watched_companies,
                            "notes": career_state.notes,
                        },
                    },
                )
                answer = str(response.get("answer", "")).strip()
                if answer:
                    return answer
            except (LLMGatewayError, FileNotFoundError, KeyError, TypeError, ValueError):
                pass

        top = contexts[0]
        if "今天" in query and "投" in query:
            return (
                f"今天建议先处理「{top.source_label}」。"
                f"它和你当前画像、求职状态的重合度最高；"
                f"同时也建议围绕 {', '.join(career_state.today_focus) or '当前重点任务'} 安排动作。"
            )

        if any(keyword in query.lower() for keyword in ("ddl", "deadline", "截止", "本周")):
            labels = "、".join(context.source_label for context in contexts[:3])
            return f"我优先检索到这些时间相关上下文：{labels}。建议先按最靠前的时间节点逐个确认投递、面试和提醒。"

        if any(keyword in query for keyword in ("名称", "链接", "网址", "投递链接")):
            lines: list[str] = []
            seen_labels: set[str] = set()
            for context in contexts:
                urls = re.findall(r"https?://[^\s；，]+", context.snippet)
                if not urls:
                    continue
                label = re.sub(r"^(名称与链接 - |投递链接 - )", "", context.source_label).strip()
                if not label or label in seen_labels:
                    continue
                seen_labels.add(label)
                lines.append(f"- {label}：{urls[0]}")
                if len(lines) >= 8:
                    break
            if lines:
                return "我先按当前检索结果整理出这些名称与链接：\n" + "\n".join(lines)
            return "我检索到了相关岗位卡片，但当前上下文里没有稳定抽到链接字段，建议点开对应卡片详情或源链接继续确认。"

        if "匹配" in query or "jd" in query.lower():
            return (
                f"从当前检索结果看，「{top.source_label}」最接近你的目标方向。"
                f"你的目标岗位包括 {', '.join(profile.target_roles) or '未配置'}，"
                f"核心技能包括 {', '.join(profile.skills) or '未配置'}。"
            )

        if any(keyword in query for keyword in ("简历", "自我介绍", "润色")):
            return (
                f"我优先参考了「{top.source_label}」以及你的画像信息。"
                "如果要继续做个性化简历润色，最好同时提供简历原文和目标岗位 JD。"
            )

        if "面试" in query and "问" in query:
            return (
                f"如果围绕「{top.source_label}」准备面试，"
                "建议优先准备项目经历、技术栈匹配点、以及为什么适合这个岗位。"
            )

        if any(keyword in query for keyword in ("hr", "微信", "boss", "直聘", "回复", "沟通")):
            return (
                f"我优先参考了「{top.source_label}」。"
                "这类沟通建议最好结合岗位、你的简历和当前流程阶段来写，给我目标岗位或简历后会更准。"
            )

        joined_labels = "、".join(context.source_label for context in contexts[:3])
        return f"我优先参考了这些上下文：{joined_labels}。当前最相关的是「{top.source_label}」。"

    def _analyze_query(self, *, query: str, recent_days: int) -> QueryAnalysis:
        heuristic = self._heuristic_query_analysis(query=query, recent_days=recent_days)

        route = self.dependencies.model_router.select("chat", "medium")
        if self.dependencies.llm_gateway.is_available(route):
            try:
                prompt = self.dependencies.prompt_loader.load("chat_preprocess")
                response = self.dependencies.llm_gateway.complete_json(
                    route=route,
                    task_name="chat_preprocess",
                    system_prompt=prompt,
                    user_payload={
                        "query": query,
                        "fallback_intent": heuristic.intent,
                        "fallback_search_hints": list(heuristic.search_hints),
                        "fallback_profile_update_hints": list(heuristic.profile_update_hints),
                        "fallback_career_update_hints": list(heuristic.career_update_hints),
                        "fallback_recent_days": heuristic.recent_days,
                    },
                )
                return QueryAnalysis(
                    categories=heuristic.categories,
                    keywords=heuristic.keywords,
                    company=heuristic.company,
                    role=heuristic.role,
                    intent=str(response.get("intent") or heuristic.intent).strip()
                    or heuristic.intent,
                    search_hints=tuple(
                        dict.fromkeys(
                            [
                                *heuristic.search_hints,
                                *[
                                    str(value).strip()
                                    for value in response.get("search_hints", [])
                                    if str(value).strip()
                                ],
                            ]
                        )
                    )[:8],
                    profile_update_hints=tuple(
                        dict.fromkeys(
                            [
                                *heuristic.profile_update_hints,
                                *[
                                    str(value).strip()
                                    for value in response.get("profile_update_hints", [])
                                    if str(value).strip()
                                ],
                            ]
                        )
                    )[:6],
                    career_update_hints=tuple(
                        dict.fromkeys(
                            [
                                *heuristic.career_update_hints,
                                *[
                                    str(value).strip()
                                    for value in response.get("career_update_hints", [])
                                    if str(value).strip()
                                ],
                            ]
                        )
                    )[:6],
                    should_update_memory=bool(
                        response.get("should_update_memory", heuristic.should_update_memory)
                    ),
                    needs_resume=bool(response.get("needs_resume", heuristic.needs_resume)),
                    recent_days=max(
                        1,
                        int(response.get("recent_days", heuristic.recent_days)),
                    ),
                )
            except (LLMGatewayError, FileNotFoundError, KeyError, TypeError, ValueError):
                pass

        return heuristic

    def _heuristic_query_analysis(self, *, query: str, recent_days: int) -> QueryAnalysis:
        categories: list[ContentCategory] = []
        if any(keyword in query for keyword in ("投", "岗位", "jd", "匹配")):
            categories.append(ContentCategory.JOB_POSTING)
        if "面试" in query:
            categories.append(ContentCategory.INTERVIEW_NOTICE)
        if any(keyword in query for keyword in ("行情", "市场", "赛道", "趋势")):
            categories.append(ContentCategory.GENERAL_UPDATE)
        if any(keyword in query for keyword in ("宣讲", "活动")):
            categories.append(ContentCategory.TALK_EVENT)

        keywords = [
            token
            for token in re.findall(r"[A-Za-z0-9_+-]+|[\u4e00-\u9fff]{2,6}", query.lower())
            if token not in {"今天", "最近", "什么", "怎么", "这个", "那个"}
        ]
        search_hints = list(dict.fromkeys(keywords[:8]))
        role = next(
            (token for token in keywords if "工程师" in token or "经理" in token or "分析师" in token),
            None,
        )
        company = next(
            (
                token
                for token in keywords
                if token.endswith(("公司", "集团", "科技", "网络", "智能", "汽车"))
            ),
            None,
        )
        intent = "general_grounded_chat"
        profile_update_hints: list[str] = []
        career_update_hints: list[str] = []
        lowered = query.lower()
        if any(keyword in lowered for keyword in ("ddl", "deadline", "截止", "本周", "本月")):
            intent = "deadline_planning"
            career_update_hints.extend(["active_priorities"])
        elif any(keyword in lowered for keyword in ("简历", "resume", "cv", "润色", "自我介绍")):
            intent = "resume_polish"
            profile_update_hints.extend(["resume_snapshot", "skills", "projects"])
            career_update_hints.extend(["active_priorities"])
        elif any(keyword in lowered for keyword in ("面试", "八股", "问题", "自我陈述")):
            intent = "interview_prep"
            profile_update_hints.extend(["projects", "skills"])
            career_update_hints.extend(["active_priorities"])
        elif any(keyword in lowered for keyword in ("hr", "boss", "直聘", "微信", "回复", "沟通")):
            intent = "hr_reply"
            profile_update_hints.extend(["resume_snapshot", "summary"])
            career_update_hints.extend(["watched_companies", "active_priorities"])
        elif any(keyword in lowered for keyword in ("画像", "我现在", "我目前", "目标岗位", "我想找", "不考虑")):
            intent = "profile_update"
            profile_update_hints.extend(
                ["target_roles", "skills", "location_preferences", "persona_keywords"]
            )
        elif any(
            keyword in lowered
            for keyword in ("今天该投什么", "投什么", "匹配", "岗位建议", "待投递", "名称与链接", "所有岗位")
        ):
            intent = "job_targeting"
            profile_update_hints.extend(["target_roles", "skills", "location_preferences"])
            career_update_hints.extend(["watched_companies", "active_priorities"])
        if "今天" in query:
            recent_days = min(recent_days, 3)
        elif any(keyword in query for keyword in ("本周", "最近一周")):
            recent_days = min(recent_days, 7)
        elif any(keyword in query for keyword in ("本月", "最近一个月")):
            recent_days = min(recent_days, 30)
        elif "所有" in query and any(keyword in query for keyword in ("岗位", "投递", "链接")):
            recent_days = max(recent_days, 180)

        return QueryAnalysis(
            categories=tuple(dict.fromkeys(categories)),
            keywords=tuple(dict.fromkeys(keywords[:8])),
            company=company,
            role=role,
            intent=intent,
            search_hints=tuple(search_hints),
            profile_update_hints=tuple(dict.fromkeys(profile_update_hints)),
            career_update_hints=tuple(dict.fromkeys(career_update_hints)),
            should_update_memory=bool(
                profile_update_hints
                or career_update_hints
                or any(marker in query for marker in ("我现在", "我目前", "我想", "我不考虑"))
            ),
            needs_resume=intent in {"resume_polish", "interview_prep", "hr_reply"},
            recent_days=max(1, recent_days),
        )

    def _analysis_bonus(
        self,
        *,
        category: str,
        source_label: str,
        snippet: str,
        created_at: datetime | None,
        query_analysis: QueryAnalysis,
    ) -> float:
        bonus = 0.0
        if query_analysis.categories and category:
            if any(expected.value == category for expected in query_analysis.categories):
                bonus += 0.16
        text = f"{source_label} {snippet}".lower()
        if query_analysis.company and query_analysis.company.lower() in text:
            bonus += 0.1
        if query_analysis.role and query_analysis.role.lower() in text:
            bonus += 0.1
        keyword_hits = sum(1 for keyword in query_analysis.keywords if keyword and keyword in text)
        bonus += min(keyword_hits, 4) * 0.03
        if created_at is not None:
            age_days = max(0.0, (datetime.now(created_at.tzinfo) - created_at).total_seconds() / 86400.0)
            bonus += max(0.0, 0.16 - min(age_days, query_analysis.recent_days) * 0.01)
        return bonus

    def _parse_created_at(self, value) -> datetime | None:
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            return None

    def _lexical_score(self, query: str, text: str) -> float:
        query_chars = self._important_chars(query)
        text_chars = self._important_chars(text)
        if not query_chars or not text_chars:
            return 0.0
        overlap = len(query_chars & text_chars)
        denominator = math.sqrt(len(query_chars) * len(text_chars))
        return overlap / denominator if denominator else 0.0

    def _keyword_overlap_score(self, *, query_tokens: tuple[str, ...], text: str) -> float:
        if not query_tokens:
            return 0.0
        lowered = text.lower()
        hits = sum(1 for token in query_tokens if token and token in lowered)
        return min(hits, 5) * 0.06

    def _important_chars(self, text: str) -> set[str]:
        return {
            char
            for char in re.sub(r"\s+", "", text.lower())
            if char.isalnum() or "\u4e00" <= char <= "\u9fff"
        }

    def _important_tokens(self, text: str, *, query_analysis: QueryAnalysis) -> tuple[str, ...]:
        tokens = [
            token
            for token in re.findall(r"[A-Za-z0-9_+.#-]+|[\u4e00-\u9fff]{2,10}", text.lower())
            if token not in {"今天", "最近", "什么", "怎么", "这个", "那个"}
        ]
        return tuple(dict.fromkeys([*query_analysis.search_hints, *tokens]))[:12]
