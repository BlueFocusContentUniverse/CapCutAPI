from fastapi import APIRouter, Depends

from util.cognito.cognito_auth import get_current_user_claims


def get_api_router() -> tuple[APIRouter, APIRouter]:
    """Get the main API router with all sub-routers included."""

    router = APIRouter(dependencies=[Depends(get_current_user_claims)])

    unprotected_router = APIRouter()

    from .audio import router as audio_router
    from .draft_archives import router as draft_archives_router, callback_router as draft_archives_callback_router
    from .draft_management_api import router as draft_management_router
    from .drafts import router as drafts_router
    from .effects import router as effects_router
    from .generate import router as generate_router
    from .health import router as health_router
    from .image import router as image_router
    from .metadata import router as metadata_router
    from .segments import router as segments_router
    from .sticker import router as sticker_router
    from .subtitle import router as subtitle_router
    from .tasks import router as tasks_router
    from .text import router as text_router
    from .tracks import router as tracks_router
    from .video import router as video_router
    from .video_task_status import router as video_task_status_router
    from .videos import router as videos_router

    # No prefix to preserve existing routes
    router.include_router(video_router)
    router.include_router(audio_router)
    router.include_router(image_router)
    router.include_router(text_router)
    router.include_router(subtitle_router)
    router.include_router(sticker_router)
    router.include_router(effects_router)
    router.include_router(drafts_router)
    router.include_router(metadata_router)
    # router.include_router(generate_router)
    router.include_router(tasks_router)
    router.include_router(draft_management_router)
    router.include_router(draft_archives_router)
    router.include_router(tracks_router)
    router.include_router(segments_router)
    router.include_router(videos_router)
    router.include_router(video_task_status_router)

    unprotected_router.include_router(health_router)
    unprotected_router.include_router(generate_router)
    # Callback router (no authentication required for Lambda callbacks)
    unprotected_router.include_router(draft_archives_callback_router)
    unprotected_router.include_router(draft_archives_router, prefix="/unprotected")
    unprotected_router.include_router(drafts_router, prefix="/unprotected")
    unprotected_router.include_router(draft_management_router, prefix="/unprotected")

    return router, unprotected_router
