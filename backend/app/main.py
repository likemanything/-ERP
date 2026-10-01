import logging
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import app.models  # noqa: F401  确保全部模型已注册
from app.core.config import settings
from app.core.errors import register_exception_handlers

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _api_router() -> APIRouter:
    from app.modules.ads.router import router as ads_router
    from app.modules.distribution.portal import router as portal_router
    from app.modules.distribution.router import router as distribution_router
    from app.modules.fba.router import router as fba_router
    from app.modules.finance.router import router as finance_router
    from app.modules.integration.router import router as integration_router
    from app.modules.logistics.router import router as logistics_router
    from app.modules.order.router import router as order_router
    from app.modules.product.router import router as product_router
    from app.modules.purchase.router import router as purchase_router
    from app.modules.replenishment.router import router as replenishment_router
    from app.modules.report.router import router as report_router
    from app.modules.shop.router import router as shop_router
    from app.modules.supplier.router import router as supplier_router
    from app.modules.system.router import auth_router
    from app.modules.system.router import router as system_router
    from app.modules.warehouse.router import router as warehouse_router

    api = APIRouter(prefix="/api/v1")
    for r in (
        auth_router,
        system_router,
        shop_router,
        product_router,
        supplier_router,
        warehouse_router,
        purchase_router,
        logistics_router,
        order_router,
        fba_router,
        replenishment_router,
        finance_router,
        ads_router,
        report_router,
        integration_router,
        distribution_router,
        portal_router,
    ):
        api.include_router(r)
    return api


DEFAULT_SECRET = "change-me-in-production-please-use-a-long-random-string"


def create_app() -> FastAPI:
    if settings.env == "prod" and (settings.secret_key == DEFAULT_SECRET or len(settings.secret_key) < 32):
        raise RuntimeError("生产环境必须设置 ERP_SECRET_KEY（至少 32 位随机字符串）")
    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="面向跨境电商中小卖家的一体化 ERP：多平台店铺、产品、采购、仓储、FBA、订单、补货、财务利润、广告。",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(application)
    application.include_router(_api_router())

    @application.get("/api/health", tags=["系统"])
    def health():
        return {"status": "ok", "app": settings.app_name}

    dist = Path(settings.frontend_dist) if settings.frontend_dist else None
    if dist and dist.is_dir():
        application.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @application.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str):
            if full_path.startswith("api/"):
                from fastapi import HTTPException

                raise HTTPException(status_code=404, detail="Not Found")
            target = (dist / full_path).resolve()
            if not str(target).startswith(str(dist.resolve())):
                return FileResponse(dist / "index.html")
            if full_path and target.is_file():
                return FileResponse(target)
            return FileResponse(dist / "index.html")

    return application


app = create_app()
