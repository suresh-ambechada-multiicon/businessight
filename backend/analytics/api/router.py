from ninja import NinjaAPI

from analytics.api import config, query, history, prompts
from analytics.services.logger import get_logger

logger = get_logger("api")

api = NinjaAPI()

api.add_router("models", config.router, tags=["config"])
api.add_router("", query.router, tags=["query"])
api.add_router("", history.router, tags=["history"])
api.add_router("", prompts.router, tags=["prompts"])