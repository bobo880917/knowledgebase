import httpx

from app.core.config import get_settings
from app.schemas import ProviderHealth, SearchHit


class LLMProvider:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def health(self) -> ProviderHealth:
        if not self.settings.llm_base_url or not self.settings.llm_api_key:
            return ProviderHealth(configured=False, ok=False, message="LLM Provider 尚未配置")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    f"{self.settings.llm_base_url.rstrip('/')}/models",
                    headers=self._headers(),
                )
                response.raise_for_status()
            return ProviderHealth(configured=True, ok=True, message="LLM Provider 可访问")
        except Exception as exc:
            return ProviderHealth(configured=True, ok=False, message=f"LLM Provider 不可访问：{exc}")

    async def answer(self, query: str, hits: list[SearchHit]) -> str:
        context = self._build_context(hits)
        system_prompt = (
            "你是本地知识库问答助手。你只能使用下方「检索上下文」中的内容作答，禁止编造事实或使用上下文外的知识。"
            "若上下文不足以得出结论，必须明确回复「根据当前检索结果无法确定」，并简述缺失什么信息。"
            "回答要点须标注引用编号，格式为 [1][2] 对应上下文条目序号。"
            "引用编号只能来自检索上下文已给出的序号，不得虚构。"
        )
        user_prompt = f"用户问题：{query}\n\n检索上下文（条目序号即引用编号）：\n{context}"
        payload = {
            "model": self.settings.llm_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=self.settings.llm_timeout_seconds) as client:
            response = await client.post(
                f"{self.settings.llm_base_url.rstrip('/')}/chat/completions",
                headers=self._headers(),
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        return data["choices"][0]["message"]["content"]

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.llm_api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _build_context(hits: list[SearchHit]) -> str:
        lines = []
        for index, hit in enumerate(hits, start=1):
            source = f"[{index}] 文件：{hit.document_name}"
            if hit.section_title:
                source += f"；章节：{hit.section_title}"
            if hit.location_label:
                source += f"；位置：{hit.location_label}"
            lines.append(f"{source}\n{hit.text}")
        return "\n\n".join(lines)
