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
"""Data collection functions."""
import psycopg2
from flask import current_app

from namex_solr_importer import oracle_db


def _get_stringified_list_for_sql(config_value: str) -> str:
    """Return the values from the config in a format usable for the execute statement."""
    if items := current_app.config.get(config_value, []):
        return ",".join([f"'{x}'" for x in items]).replace(")", "")

    return ""


def collect_colin_data():
    """Collect data from COLIN."""
    current_app.logger.debug("Connecting to Oracle instance...")
    cursor = oracle_db.connection.cursor()
    current_app.logger.debug("Collecting COLIN data...")
    cursor.execute(f"""
        SELECT c.corp_num, c.recognition_dts as start_date,
            cn.corp_nme as name, j.can_jur_typ_cd as jurisdiction,
            CASE cos.op_state_typ_cd
                when 'ACT' then 'ACTIVE'
                when 'HIS' then 'HISTORICAL'
                else 'ACTIVE'
            END as state
        FROM corporation c
        join corp_state cs on cs.corp_num = c.corp_num
        join corp_op_state cos on cos.state_typ_cd = cs.state_typ_cd
        join corp_name cn on cn.corp_num = c.corp_num
        left join (select * from jurisdiction where end_event_id is null) j on j.corp_num = c.corp_num
        WHERE c.corp_typ_cd in ({_get_stringified_list_for_sql('CONFLICT_LEGAL_TYPES')})
            and c.corp_typ_cd not in ({_get_stringified_list_for_sql('MODERNIZED_LEGAL_TYPES')})
            and cs.end_event_id is null
            and cn.end_event_id is null
            and cn.corp_name_typ_cd in ('CO', 'NB')
            and cos.op_state_typ_cd in ('ACT','HLD')
        """)
    return cursor


def collect_lear_data():
    """Collect data from LEAR."""
    current_app.logger.debug("Connecting to LEAR Postgres instance...")
    conn = psycopg2.connect(host=current_app.config.get("LEAR_DB_HOST"),
                            port=current_app.config.get("LEAR_DB_PORT"),
                            database=current_app.config.get("LEAR_DB_NAME"),
                            user=current_app.config.get("LEAR_DB_USER"),
                            password=current_app.config.get("LEAR_DB_PASSWORD"))
    cur = conn.cursor()
    current_app.logger.debug("Collecting LEAR data...")
    cur.execute(f"""
        SELECT b.identifier as corp_num, b.legal_name as name,
            b.founding_date as start_date, b.state,
            CASE j.region
                when NULL then j.country
                when 'FEDERAL' then 'FD'
                else j.region
            END as jurisdiction
        FROM businesses b
        LEFT JOIN jurisdictions j on j.business_id = b.id
        WHERE legal_type in ({_get_stringified_list_for_sql('CONFLICT_LEGAL_TYPES')})
            and legal_type in ({_get_stringified_list_for_sql('MODERNIZED_LEGAL_TYPES')})
            and state in ('ACTIVE')
        """)
    return cur


def collect_namex_data():
    """Collect data from NameX."""
    current_app.logger.debug("Connecting to NameX Postgres instance...")
    conn = psycopg2.connect(host=current_app.config.get("DB_HOST"),
                            port=current_app.config.get("DB_PORT"),
                            database=current_app.config.get("DB_NAME"),
                            user=current_app.config.get("DB_USER"),
                            password=current_app.config.get("DB_PASSWORD"))
    cur = conn.cursor()
    current_app.logger.debug("Collecting NameX data...")
    cur.execute("""
        SELECT r.nr_num, r.corp_num, r.state_cd as state, r.xpro_jurisdiction as jurisdiction,
            r.submitted_date as start_date, r.submit_count,
            n.name, n.choice,
            CASE n.state
                when 'APPROVED' then 'A'
                when 'REJECTED' then 'R'
                when 'CONDITION' then 'C'
                else n.state
            END as name_state
        FROM requests r
            JOIN names n on n.nr_id = r.id
        """)
    return cur


def collect_synonyms_data():
    """Collect data from Synonyms."""
    current_app.logger.debug("Connecting to Synonym Postgres instance...")
    conn = psycopg2.connect(host=current_app.config.get("SYN_DB_HOST"),
                            port=current_app.config.get("SYN_DB_PORT"),
                            database=current_app.config.get("SYN_DB_NAME"),
                            user=current_app.config.get("SYN_DB_USER"),
                            password=current_app.config.get("SYN_DB_PASSWORD"))
    cur = conn.cursor()
    current_app.logger.debug("Collecting Synonym data...")
    # TODO: verify can just collect 'synonym' table / 'synonyms_text' column (there's also synonym_orig / stems_text)
    cur.execute("""
        SELECT synonyms_text
        FROM synonym
        WHERE enabled='t'
        """)
    return cur
