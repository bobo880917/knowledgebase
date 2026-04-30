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
            "你是一个本地知识库问答助手。只能基于用户提供的检索上下文回答。"
            "如果上下文不足，请明确说明没有找到足够依据。回答需要简洁，并在句末标注来源编号。"
        )
        user_prompt = f"问题：{query}\n\n检索上下文：\n{context}"
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
            lines.append(f"{source}\n{hit.text}")
        return "\n\n".join(lines)
