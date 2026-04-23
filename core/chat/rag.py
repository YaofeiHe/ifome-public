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
    recent_days: int


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
    ) -> RAGChatResult:
        """Answer one user question from retrieved items and memory context."""

        query_analysis = self._analyze_query(query=query, recent_days=recent_days)
        documents = self._build_documents(
            states=states,
            profile=profile,
            career_state=career_state,
            item_id=item_id,
        )
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
                f"原文：{normalized.normalized_text}",
            ]
            if extracted is not None:
                if extracted.company:
                    parts.append(f"公司：{extracted.company}")
                if extracted.role:
                    parts.append(f"岗位：{extracted.role}")
                if extracted.city:
                    parts.append(f"地点：{extracted.city}")
                if extracted.summary_one_line:
                    parts.append(f"提取摘要：{extracted.summary_one_line}")

            documents.append(
                RAGDocument(
                    doc_id=f"item:{normalized.id}",
                    doc_type="item",
                    source_label=summary,
                    text="\n".join(parts),
                    snippet=(normalized.normalized_text or normalized.raw_content)[:240],
                    item_id=normalized.id,
                    created_at=card.updated_at if card and card.updated_at else normalized.created_at,
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

        career_bits = [
            f"今日重点：{', '.join(career_state.today_focus) or '未配置'}",
            f"当前优先级：{', '.join(career_state.active_priorities) or '未配置'}",
        ]
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

        query_vector = self.dependencies.embedding_gateway.embed_texts(
            route="dashscope:embedding",
            texts=[query],
        )[0]
        results = self.dependencies.vector_store.query_points(
            collection_name=self.settings.rag.collection_name,
            query_vector=query_vector,
            limit=self.settings.rag.query_limit,
        )

        contexts: list[RetrievedContext] = []
        for result in results:
            payload = result.get("payload", {})
            base_score = float(result.get("score") or 0.0)
            contexts.append(
                RetrievedContext(
                    doc_id=str(payload.get("doc_id") or result.get("id")),
                    doc_type=str(payload.get("doc_type") or "unknown"),
                    source_label=str(payload.get("source_label") or "引用"),
                    snippet=str(payload.get("snippet") or ""),
                    item_id=payload.get("item_id"),
                    score=base_score
                    + self._analysis_bonus(
                        category=str(payload.get("category") or ""),
                        source_label=str(payload.get("source_label") or ""),
                        snippet=str(payload.get("snippet") or ""),
                        created_at=self._parse_created_at(payload.get("created_at")),
                        query_analysis=query_analysis,
                    ),
                )
            )
        return contexts

    def _retrieve_local(
        self,
        *,
        query: str,
        documents: list[RAGDocument],
        query_analysis: QueryAnalysis,
    ) -> list[RetrievedContext]:
        scored: list[RetrievedContext] = []
        for document in documents:
            score = self._lexical_score(query, document.text) + self._analysis_bonus(
                category=document.category or "",
                source_label=document.source_label,
                snippet=document.snippet,
                created_at=document.created_at,
                query_analysis=query_analysis,
            )
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

    def _generate_answer(
        self,
        *,
        query: str,
        contexts: list[RetrievedContext],
        profile: ProfileMemory,
        career_state: CareerStateMemory,
    ) -> str:
        if not contexts:
            return "我还没从现有条目里检索到足够上下文，先补一条岗位、对话或画像信息会更稳。"

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
                        "profile_summary": {
                            "target_roles": profile.target_roles,
                            "priority_domains": profile.priority_domains,
                            "skills": profile.skills,
                            "summary": profile.summary,
                        },
                        "career_state_summary": {
                            "today_focus": career_state.today_focus,
                            "active_priorities": career_state.active_priorities,
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

        if "匹配" in query or "jd" in query.lower():
            return (
                f"从当前检索结果看，「{top.source_label}」最接近你的目标方向。"
                f"你的目标岗位包括 {', '.join(profile.target_roles) or '未配置'}，"
                f"核心技能包括 {', '.join(profile.skills) or '未配置'}。"
            )

        if "面试" in query and "问" in query:
            return (
                f"如果围绕「{top.source_label}」准备面试，"
                "建议优先准备项目经历、技术栈匹配点、以及为什么适合这个岗位。"
            )

        joined_labels = "、".join(context.source_label for context in contexts[:3])
        return f"我优先参考了这些上下文：{joined_labels}。当前最相关的是「{top.source_label}」。"

    def _analyze_query(self, *, query: str, recent_days: int) -> QueryAnalysis:
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
        if "今天" in query:
            recent_days = min(recent_days, 3)
        elif any(keyword in query for keyword in ("本周", "最近一周")):
            recent_days = min(recent_days, 7)
        elif any(keyword in query for keyword in ("本月", "最近一个月")):
            recent_days = min(recent_days, 30)

        return QueryAnalysis(
            categories=tuple(dict.fromkeys(categories)),
            keywords=tuple(dict.fromkeys(keywords[:8])),
            company=company,
            role=role,
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

    def _important_chars(self, text: str) -> set[str]:
        return {
            char
            for char in re.sub(r"\s+", "", text.lower())
            if char.isalnum() or "\u4e00" <= char <= "\u9fff"
        }
