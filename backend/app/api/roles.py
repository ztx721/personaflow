from fastapi import APIRouter

from ..config_loader import load_personas
from ..schemas import RoleSummary

router = APIRouter(prefix="/api", tags=["roles"])


@router.get("/roles", response_model=list[RoleSummary])
def list_roles():
    return [
        RoleSummary(
            role_id=p.role_id,
            display_name=p.display_name,
            description=p.description,
            avatar=p.avatar,
        )
        for p in load_personas().values()
    ]
