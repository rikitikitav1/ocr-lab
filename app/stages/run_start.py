# a run made for a book on its current structure and metadata, its book_run job queued; the doors and a chain share it
import artifacts
import book_knobs
import job_queue
import job_specs
import profiles
from orm.catalogue import Book, MetadataVersion, Profile, Run, StructureVersion
from orm.db import Session

from stages import run_pieces as units_of_run
from stages import versions


def startable(session, id: int, format: str, profile_id: int | None) -> tuple[StructureVersion, int]:
    if format != "markdown":
        raise job_specs.Refused(f"format {format!r} is not built; built: markdown")
    if session.get(Book, id) is None:
        raise LookupError(f"no book {id}")
    structure = versions.current(session, StructureVersion, id)
    if structure is None:
        raise job_specs.Refused(f"book {id} has no structure yet; recollect structure first")
    if profile_id is None:
        return structure, profiles.resolve(session, id).id
    if (given := session.get(Profile, profile_id)) is None or given.book_id != id:
        raise job_specs.Refused(f"profile {profile_id} is not a profile of book {id}")
    return structure, profile_id


def start(session, id: int, format: str, structure: StructureVersion, profile_id: int,
           parent_id: int | None = None) -> tuple[Run, int]:
    meta = versions.current(session, MetadataVersion, id)
    run = Run(book_id=id, profile_id=profile_id, structure_version_id=structure.id, format=format,
              metadata_version_id=meta.id if meta is not None else None, dir="", status="queued",
              reading_level=units_of_run.level_for(book_knobs.of(id)["structure.reading_level"],
                                                  units_of_run.rows(session, structure.id)))
    session.add(run)
    session.flush()
    run.dir = str(artifacts.run_dir(id, run.id))
    return run, job_queue.enqueue("book_run", {"run_id": run.id}, run_id=run.id, book_id=id, session=session,
                                  parent_id=parent_id)


# a run started by a chain (a submission asking for one) rather than a door
def start_one(book_id: int) -> int:
    with Session() as session:
        structure, profile_id = startable(session, book_id, "markdown", None)
        run, _ = start(session, book_id, "markdown", structure, profile_id)
        session.commit()
        return run.id
