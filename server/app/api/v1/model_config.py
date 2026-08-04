from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from server.app.core.permissions import AccessContext, require_permission
from server.app.db.session import get_db
from server.app.schemas.common import OkResponse
from server.app.schemas.model_config import (
    ConnectionTestRequest,
    ConnectionTestResponse,
    ModelConfigCreateRequest,
    ModelConfigListResponse,
    ModelConfigResponse,
    ModelConfigUpdateRequest,
    ModelProviderCreateRequest,
    ModelProviderListResponse,
    ModelProviderResponse,
    ModelProviderUpdateRequest,
)
from server.app.services.model_config_service import ModelConfigService

router = APIRouter(tags=["model-config"])


@router.get(
    "/model-providers",
    response_model=ModelProviderListResponse,
)
def list_model_providers(
    context: AccessContext = Depends(require_permission("MODEL_CONFIG_READ")),
    db: Session = Depends(get_db),
) -> dict:
    service = ModelConfigService(db)
    return {
        "data": [
            service.provider_to_dict(provider)
            for provider in service.list_providers(context)
        ]
    }


@router.post(
    "/model-providers",
    response_model=ModelProviderResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_model_provider(
    payload: ModelProviderCreateRequest,
    context: AccessContext = Depends(require_permission("MODEL_CONFIG_WRITE")),
    db: Session = Depends(get_db),
) -> dict:
    provider = ModelConfigService(db).create_provider(
        context,
        provider_type=payload.provider_type,
        name=payload.name,
        base_url=payload.base_url,
        api_key=payload.api_key,
        status=payload.status,
        config=payload.config,
    )
    return ModelConfigService.provider_to_dict(provider)


@router.patch(
    "/model-providers/{provider_id}",
    response_model=ModelProviderResponse,
)
def update_model_provider(
    provider_id: str,
    payload: ModelProviderUpdateRequest,
    context: AccessContext = Depends(require_permission("MODEL_CONFIG_WRITE")),
    db: Session = Depends(get_db),
) -> dict:
    provider = ModelConfigService(db).update_provider(
        context,
        provider_id,
        name=payload.name,
        base_url=payload.base_url,
        api_key=payload.api_key,
        status=payload.status,
        config=payload.config,
    )
    return ModelConfigService.provider_to_dict(provider)


@router.delete("/model-providers/{provider_id}", response_model=OkResponse)
def delete_model_provider(
    provider_id: str,
    context: AccessContext = Depends(require_permission("MODEL_CONFIG_WRITE")),
    db: Session = Depends(get_db),
) -> dict:
    ModelConfigService(db).delete_provider(context, provider_id)
    return {"ok": True}


@router.post(
    "/model-providers/{provider_id}/connection-tests",
    response_model=ConnectionTestResponse,
)
def test_model_provider_connection(
    provider_id: str,
    payload: ConnectionTestRequest | None = None,
    context: AccessContext = Depends(require_permission("MODEL_CONFIG_WRITE")),
    db: Session = Depends(get_db),
) -> dict:
    return ModelConfigService(db).test_provider_connection(
        context,
        provider_id,
        model_config_id=payload.model_config_id if payload else None,
    )


@router.get("/model-configs", response_model=ModelConfigListResponse)
def list_model_configs(
    capability: str | None = Query(default=None),
    context: AccessContext = Depends(require_permission("MODEL_CONFIG_READ")),
    db: Session = Depends(get_db),
) -> dict:
    service = ModelConfigService(db)
    return {
        "data": [
            service.model_config_to_dict(model_config)
            for model_config in service.list_model_configs(context, capability)
        ]
    }


@router.post(
    "/model-configs",
    response_model=ModelConfigResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_model_config(
    payload: ModelConfigCreateRequest,
    context: AccessContext = Depends(require_permission("MODEL_CONFIG_WRITE")),
    db: Session = Depends(get_db),
) -> dict:
    model_config = ModelConfigService(db).create_model_config(
        context,
        provider_id=payload.provider_id,
        capability=payload.capability,
        model_name=payload.model_name,
        embedding_dimension=payload.embedding_dimension,
        max_tokens=payload.max_tokens,
        timeout_ms=payload.timeout_ms,
        connect_timeout_ms=payload.connect_timeout_ms,
        write_timeout_ms=payload.write_timeout_ms,
        read_idle_timeout_ms=payload.read_idle_timeout_ms,
        overall_timeout_ms=payload.overall_timeout_ms,
        is_default=payload.is_default,
        status=payload.status,
        config=payload.config,
    )
    return ModelConfigService.model_config_to_dict(model_config)


@router.patch("/model-configs/{config_id}", response_model=ModelConfigResponse)
def update_model_config(
    config_id: str,
    payload: ModelConfigUpdateRequest,
    context: AccessContext = Depends(require_permission("MODEL_CONFIG_WRITE")),
    db: Session = Depends(get_db),
) -> dict:
    model_config = ModelConfigService(db).update_model_config(
        context,
        config_id,
        model_name=payload.model_name,
        embedding_dimension=payload.embedding_dimension,
        max_tokens=payload.max_tokens,
        timeout_ms=payload.timeout_ms,
        connect_timeout_ms=payload.connect_timeout_ms,
        write_timeout_ms=payload.write_timeout_ms,
        read_idle_timeout_ms=payload.read_idle_timeout_ms,
        overall_timeout_ms=payload.overall_timeout_ms,
        is_default=payload.is_default,
        status=payload.status,
        config=payload.config,
    )
    return ModelConfigService.model_config_to_dict(model_config)


@router.delete("/model-configs/{config_id}", response_model=OkResponse)
def delete_model_config(
    config_id: str,
    context: AccessContext = Depends(require_permission("MODEL_CONFIG_WRITE")),
    db: Session = Depends(get_db),
) -> dict:
    ModelConfigService(db).delete_model_config(context, config_id)
    return {"ok": True}


@router.patch(
    "/model-configs/{config_id}/default", response_model=ModelConfigResponse
)
def set_default_model_config(
    config_id: str,
    context: AccessContext = Depends(require_permission("MODEL_CONFIG_WRITE")),
    db: Session = Depends(get_db),
) -> dict:
    model_config = ModelConfigService(db).set_default_model(context, config_id)
    return ModelConfigService.model_config_to_dict(model_config)
