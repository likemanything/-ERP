"""单据编号生成：前缀 + yyMMdd + 4 位流水，例如 PO2610010001。"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.types import utcnow


def next_doc_no(db: Session, prefix: str, *, day: date | None = None, width: int = 4) -> str:
    from app.modules.system.models import Sequence

    day = day or utcnow().date()
    period = day.strftime("%y%m%d")
    for _ in range(5):
        seq = db.execute(
            select(Sequence).where(Sequence.prefix == prefix, Sequence.period == period).with_for_update()
        ).scalar_one_or_none()
        if seq is None:
            try:
                with db.begin_nested():
                    seq = Sequence(prefix=prefix, period=period, value=0)
                    db.add(seq)
                    db.flush()
            except IntegrityError:
                continue  # 并发创建，重试
        seq.value += 1
        db.flush()
        return f"{prefix}{period}{seq.value:0{width}d}"
    raise RuntimeError("生成单据编号失败，请重试")
