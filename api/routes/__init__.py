"""Routes modulaires NormaCheck.

Chaque module contient un APIRouter pour un domaine fonctionnel.
"""

from api.routes.rh import router as rh_router
from api.routes.simulation import router as simulation_router
from api.routes.comptabilite import router as comptabilite_router

__all__ = [
    "rh_router",
    "simulation_router",
    "comptabilite_router",
]
