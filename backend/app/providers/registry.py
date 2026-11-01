"""Pick a provider per capability from env vars."""
from .. import config as C

def llm(kind: str = "writer"):
    which = C.CRITIC_PROVIDER if kind == "critic" else C.LLM_PROVIDER
    if which == "meta":
        from .meta import meta_llm; return meta_llm()
    if which == "baseten":
        from .baseten import baseten_llm; return baseten_llm(C.BASETEN_WRITER_REASONING if kind == "writer" else C.BASETEN_REASONING)
    from .mock import MockLLM; return MockLLM()

def image():
    if C.IMAGE_PROVIDER == "meta":
        from .meta import MetaImage; return MetaImage()
    if C.IMAGE_PROVIDER == "modal":
        from .modal_open import ModalImage; return ModalImage()
    from .mock import MockImage; return MockImage()

def segmenter():
    if C.SEG_PROVIDER == "meta":
        from .meta import MetaSAM; return MetaSAM()
    if C.SEG_PROVIDER == "modal":
        from .modal_open import ModalSAM; return ModalSAM()
    from .mock import MockSAM; return MockSAM()

def asr():
    if C.ASR_PROVIDER == "meta":
        from .meta import MetaTranscribe; return MetaTranscribe()
    if C.ASR_PROVIDER == "whisper":
        try:
            import faster_whisper  # noqa
            from .whisper_asr import WhisperASR; return WhisperASR()
        except ImportError:
            pass
    from .mock import NoASR; return NoASR()
