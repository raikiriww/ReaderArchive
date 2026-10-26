from pathlib import Path

from app.core.config import Settings


def test_qwen_defaults_and_explicit_old_model_remain_usable():
    qwen = Settings(_env_file=None, semantic_model_name="Qwen/Qwen3-Embedding-0.6B")
    assert qwen.semantic_model_dir == Path("/app/models/qwen")
    assert qwen.semantic_embedding_dimensions == 384
    assert qwen.semantic_text_version == "qwen-sentence-v1"
    legacy = Settings(_env_file=None, semantic_model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
    assert legacy.semantic_model_dir == Path("/app/data/models/fastembed")
    assert legacy.semantic_text_version == "token-body-v2"


def test_explicit_model_directory_and_version_are_never_overwritten():
    configured = Settings(_env_file=None, semantic_model_name="Qwen/Qwen3-Embedding-0.6B",
        semantic_model_dir="/custom/model", semantic_text_version="custom-v3")
    assert configured.semantic_model_dir == Path("/custom/model")
    assert configured.semantic_text_version == "custom-v3"


def test_minilm_is_downloaded_once_only_when_its_local_files_are_missing(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace

    from app.semantic import LocalEmbeddingProvider

    calls = []

    class TextEmbedding:
        def __init__(self, *, local_files_only, cache_dir, **options):
            calls.append(local_files_only)
            if local_files_only and not (tmp_path / "downloaded").exists():
                raise ValueError("Could not find model files locally")
            (tmp_path / "downloaded").write_text("")

    monkeypatch.setitem(sys.modules, "fastembed", SimpleNamespace(TextEmbedding=TextEmbedding))
    settings = Settings(_env_file=None, semantic_model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        semantic_model_dir=tmp_path / "models")
    LocalEmbeddingProvider(settings)._load_model()
    assert calls == [True, False]
    LocalEmbeddingProvider(settings)._load_model()
    assert calls == [True, False, True]
