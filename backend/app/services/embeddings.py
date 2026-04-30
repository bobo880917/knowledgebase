import hashlib
import json
import math
from functools import cached_property

from app.core.config import get_settings
from app.schemas import EmbeddingHealth


class EmbeddingService:
    def __init__(self) -> None:
        self.settings = get_settings()

    @cached_property
    def model(self):
        if self.settings.embedding_provider != "sentence_transformers":
            return None
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "使用 sentence_transformers 需要安装 embedding 依赖："
                "uv sync --extra embedding 或 uv pip install -e '.[embedding]'"
            ) from exc
        return SentenceTransformer(self.settings.embedding_model)

    def embed(self, text: str) -> list[float]:
        if self.model is not None:
            vector = self.model.encode(text, normalize_embeddings=True)
            return [float(value) for value in vector]
        return self._hash_embedding(text)

    def health(self) -> EmbeddingHealth:
        provider = self.settings.embedding_provider
        model_name = self.settings.embedding_model
        dimension = self.settings.embedding_dimension

        if provider == "hash":
            return EmbeddingHealth(
                provider=provider,
                model=model_name,
                dimension=dimension,
                semantic_enabled=False,
                ok=True,
                message="当前使用 hash fallback，仅适合开发验证；建议启用 sentence_transformers 语义模型。",
            )

        if provider != "sentence_transformers":
            return EmbeddingHealth(
                provider=provider,
                model=model_name,
                dimension=dimension,
                semantic_enabled=False,
                ok=False,
                message=f"暂不支持的 embedding provider：{provider}",
            )

        try:
            model = self.model
            if hasattr(model, "get_embedding_dimension"):
                model_dimension = model.get_embedding_dimension()
            else:
                model_dimension = model.get_sentence_embedding_dimension()
        except RuntimeError as exc:
            return EmbeddingHealth(
                provider=provider,
                model=model_name,
                dimension=dimension,
                semantic_enabled=True,
                ok=False,
                message=str(exc),
            )
        except Exception as exc:
            return EmbeddingHealth(
                provider=provider,
                model=model_name,
                dimension=dimension,
                semantic_enabled=True,
                ok=False,
                message=f"Embedding 模型加载失败：{exc}",
            )

        return EmbeddingHealth(
            provider=provider,
            model=model_name,
            dimension=int(model_dimension or dimension),
            semantic_enabled=True,
            ok=True,
            message="语义 embedding 模型可用。",
        )

    def _hash_embedding(self, text: str) -> list[float]:
        dimension = self.settings.embedding_dimension
        vector = [0.0] * dimension
        tokens = [token for token in _tokenize(text) if token]
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    @staticmethod
    def dumps(vector: list[float]) -> str:
        return json.dumps(vector, ensure_ascii=False)

    @staticmethod
    def loads(raw: str) -> list[float]:
        return [float(value) for value in json.loads(raw)]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    size = min(len(left), len(right))
    dot = sum(left[index] * right[index] for index in range(size))
    left_norm = math.sqrt(sum(value * value for value in left[:size]))
    right_norm = math.sqrt(sum(value * value for value in right[:size]))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _tokenize(text: str) -> list[str]:
    lowered = text.lower()
    ascii_tokens = []
    current = []
    for char in lowered:
        if char.isalnum() and ord(char) < 128:
            current.append(char)
        else:
            if current:
                ascii_tokens.append("".join(current))
                current = []
            if "\u4e00" <= char <= "\u9fff":
                ascii_tokens.append(char)
    if current:
        ascii_tokens.append("".join(current))
    return ascii_tokens
