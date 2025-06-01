# Copyright © 2025 Province of British Columbia
#
# Licensed under the BSD 3 Clause License, (the "License");
# you may not use this file except in compliance with the License.
# The template for the license can be found here
#    https://opensource.org/license/bsd-3-clause/
#
# Redistribution and use in source and binary forms,
# with or without modification, are permitted provided that the
# following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice,
#    this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# 3. Neither the name of the copyright holder nor the names of its contributors
#    may be used to endorse or promote products derived from this software
#    without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS “AS IS”
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO,
# THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
"""The Search solr data import service."""
import sys
from dataclasses import asdict

from flask import current_app
from psycopg2._psycopg import cursor

from namex_solr_api.exceptions import SolrException
from namex_solr_importer import create_app
from namex_solr_importer.utils import (
    collect_colin_data,
    collect_lear_data,
    collect_namex_data,
    collect_synonyms_data,
    import_conflicts,
    parse_conflict,
    parse_synonyms,
    reindex_post,
    reindex_prep,
    reindex_recovery,
    resync,
    update_synonyms,
)


def _load_synonyms():
    """Update namex search with the synonyms from the solr admin app."""
    current_app.logger.debug("---------- Collecting/Updating Synonyms ----------")
    syn_data_cur = collect_synonyms_data()
    syn_data = syn_data_cur.fetchall()
    synonym_payload = parse_synonyms(syn_data)
    update_synonyms(synonym_payload)
    current_app.logger.debug("---------- Synonym update completed ----------.")


def _load_conflicts(data_cur: cursor, data_name: str, type: str):
    """Update namex search with the given conflicts."""
    current_app.logger.debug("Fetching data...")
    # NOTE: for the colin connection the data_cur is not a 'cursor' type, but they overlap for the used methods
    data = data_cur.fetchall()
    namex_descs = [desc[0].lower() for desc in data_cur.description]
    nr_data: dict[str, dict] = {}
    possible_conflicts = []
    current_app.logger.debug("Parsing data...")
    for item in data:
        item_dict = dict(zip(namex_descs, item, strict=False))
        if type == "CORP":
            # corps can be added to possible_conflicts right away
            possible_conflicts.append(asdict(parse_conflict(item_dict, type)))
        elif type == "NR":
            # each nr name will have its own record, so we have to put them together
            name_dict = {
                "name": item_dict["name"],
                "name_state": item_dict["name_state"],
                "submit_count": item_dict["submit_count"],
                "choice": item_dict["choice"],
            }

            if (nr_num := item_dict["nr_num"]) in nr_data:
                # add name to nr
                nr_data[nr_num]["names"].append(name_dict)
            else:
                # add 'names' field with this name (others under the same NR will be added to this)
                item_dict["names"] = [name_dict]
                # add nr to dict
                nr_data[nr_num] = item_dict

    for nr_conflict in nr_data.values():
        # parse all the nrs (the names will be grouped underneath them now)
        possible_conflicts.append(asdict(parse_conflict(nr_conflict, type)))

    current_app.logger.debug("Importing data...")
    final_record = [possible_conflicts[-1]], data_name
    return import_conflicts(possible_conflicts, data_name), final_record


def _load_nrs():
    """Load namex search with the nr possible conflicts."""
    current_app.logger.debug("---------- Collecting/Importing NRs ----------")
    namex_data_cur = collect_namex_data()
    count, final_record = _load_conflicts(namex_data_cur, "NameX NR", "NR")
    current_app.logger.debug("---------- NR import completed ----------.")
    return count, final_record


def _load_colin_corps():
    """Load namex search with the colin corp possible conflicts."""
    current_app.logger.debug("---------- Collecting/Importing COLIN Corps ----------")
    colin_data_cur = collect_colin_data()
    count, final_record = _load_conflicts(colin_data_cur, "COLIN Corps", "CORP")
    current_app.logger.debug("---------- COLIN Corp import completed ----------.")
    return count, final_record


def _load_lear_corps():
    """Load namex search with the lear corp possible conflicts."""
    current_app.logger.debug("---------- Collecting/Importing LEAR Corps ----------")
    lear_data_cur = collect_lear_data()
    count, final_record = _load_conflicts(lear_data_cur, "LEAR Corps", "CORP")
    current_app.logger.debug("---------- LEAR Corp import completed ----------.")
    return count, final_record


def load_conflicts_core():  # noqa: PLR0915
    """Load data from Synonyms, NameX, LEAR and COLIN into the conflicts core."""
    try:
        is_reindex = current_app.config.get("REINDEX_CORE")
        include_synonym_load = current_app.config.get("INCLUDE_SYNONYM_LOAD")
        include_namex_load = current_app.config.get("INCLUDE_NAMEX_LOAD")
        include_colin_load = current_app.config.get("INCLUDE_COLIN_LOAD")
        include_lear_load = current_app.config.get("INCLUDE_LEAR_LOAD")
        final_record = None

        if is_reindex and current_app.config.get("IS_PARTIAL_IMPORT"):
            current_app.logger.error("Attempted reindex on partial data set.")
            current_app.logger.debug("Setting reindex to False to prevent potential data loss.")
            is_reindex = False

        if is_reindex:
            current_app.logger.debug("---------- Pre Reindex Actions ----------")
            reindex_prep()

        try:
            if include_synonym_load:
                _load_synonyms()

            nr_count = 0
            if include_namex_load:
                nr_count, final_record = _load_nrs()
                current_app.logger.debug(f"Total NR records imported: {nr_count}")

            colin_count = 0
            if include_colin_load:
                colin_count, final_record = _load_colin_corps()
                current_app.logger.debug(f"Total COLIN Corp records imported: {colin_count}")

            lear_count = 0
            if include_lear_load:
                lear_count, final_record = _load_lear_corps()
                current_app.logger.debug(f"Total LEAR Corp records imported: {lear_count}")

            current_app.logger.debug(f"Total possible conflicts imported: {nr_count + colin_count + lear_count}")

        except Exception as err:
            if is_reindex:
                reindex_recovery()
            raise err  # pass along

        try:
            current_app.logger.debug("---------- Resync ----------")
            resync()
        except Exception as error:
            current_app.logger.debug(error.with_traceback(None))
            current_app.logger.error("Resync failed.")

        try:
            current_app.logger.debug("---------- Final Commit ----------")
            current_app.logger.debug("Triggering final commit on leader to make changes visible to searching on leader...")
            import_conflicts(final_record[0], final_record[1])
            current_app.logger.debug("Final commit complete.")

        except Exception as error:
            current_app.logger.debug(error.with_traceback(None))
            current_app.logger.error("Final commit failed. (This will only effect DEV).")

        if is_reindex:
            current_app.logger.debug("---------- Post Reindex Actions ----------")
            reindex_post()

        current_app.logger.debug("SOLR import finished successfully.")

    except SolrException as err:
        current_app.logger.debug(f"SOLR gave status code: {err.status_code}")
        current_app.logger.error(err.error)
        current_app.logger.debug("SOLR import failed.")
        sys.exit(1)


if __name__ == "__main__":
    print("Starting data importer...")  # noqa: T201
    app = create_app()
    with app.app_context():
        load_conflicts_core()
        sys.exit(0)
