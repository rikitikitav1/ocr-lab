# the doors over the stand's two ways of removing artifacts
from mcp_tools import tool
from stages import cleanup as removal


@tool("delete_run", "DELETE /v1/runs/{id}",
      "Deletes a run the owner names with all its artifacts and files; if it was the book's result, the result "
      "moves to the next best finished run. Refused while the run has live jobs.")
def delete_run(id: int) -> dict:
    return removal.delete_run(id)


@tool("cleanup", "POST /v1/cleanup",
      "Lists (dry_run, the default) or removes the heavy intermediates (per-pass model dumps) of runs that are not "
      "their book's result; reports, profiles, measurements, model calls, bundles and the engines' book-level "
      "readings are never removed. Removed rows stay with removed_at set.")
def cleanup(dry_run: bool = True) -> dict:
    return removal.cleanup(dry_run)
