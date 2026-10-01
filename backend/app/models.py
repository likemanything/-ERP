"""导入全部 ORM 模型，确保 Base.metadata 完整（供 Alembic 与建表使用）。"""

from app.modules.ads import models as ads_models  # noqa: F401
from app.modules.approval import models as approval_models  # noqa: F401
from app.modules.assembly import models as assembly_models  # noqa: F401
from app.modules.distribution import models as distribution_models  # noqa: F401
from app.modules.fba import models as fba_models  # noqa: F401
from app.modules.finance import models as finance_models  # noqa: F401
from app.modules.fulfillment import models as fulfillment_models  # noqa: F401
from app.modules.integration import models as integration_models  # noqa: F401
from app.modules.logistics import models as logistics_models  # noqa: F401
from app.modules.order import models as order_models  # noqa: F401
from app.modules.product import models as product_models  # noqa: F401
from app.modules.purchase import models as purchase_models  # noqa: F401
from app.modules.replenishment import models as replenishment_models  # noqa: F401
from app.modules.shop import models as shop_models  # noqa: F401
from app.modules.supplier import models as supplier_models  # noqa: F401
from app.modules.system import models as system_models  # noqa: F401
from app.modules.warehouse import models as warehouse_models  # noqa: F401
