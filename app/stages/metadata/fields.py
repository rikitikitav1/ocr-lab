# a metadata field as every reader shows it: the value, where it came from and how sure that source was
from orm.catalogue import MetadataField
from sqlalchemy import select


def view(f: MetadataField) -> dict:
    return {"value": f.value, "source": f.source, "confidence": f.confidence}


def of_version(session, version_id: int | None) -> dict[str, dict]:
    rows = session.scalars(select(MetadataField).where(MetadataField.metadata_version_id == version_id)
                           .order_by(MetadataField.name))
    return {f.name: view(f) for f in rows}
