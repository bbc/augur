import logging
import pytest
import uuid
import sqlalchemy as s


from augur.util.repo_load_controller import RepoLoadController, ORG_REPOS_ENDPOINT, DEFAULT_REPO_GROUP_IDS, CLI_USER_ID

from augur.tasks.github.util.github_task_session import GithubTaskSession
from augur.application.db.session import DatabaseSession
from augur.tasks.github.util.github_paginator import GithubPaginator
from augur.application.db.models import Contributor, Issue, Config
from augur.tasks.github.util.github_paginator import hit_api
from augur.application.db.util import execute_session_query


logger = logging.getLogger(__name__)

VALID_ORG = {"org": "CDCgov", "repo_count": 241}


######## Helper Functions to Get Delete statements #################

def get_delete_statement(schema, table):

    return """DELETE FROM "{}"."{}";""".format(schema, table)

def get_repo_delete_statement():

    return get_delete_statement("augur_data", "repo")

def get_repo_group_delete_statement():

    return get_delete_statement("augur_data", "repo_groups")

def get_user_delete_statement():

    return get_delete_statement("augur_operations", "users")

def get_user_repo_delete_statement():

    return get_delete_statement("augur_operations", "user_repos")

def get_user_group_delete_statement():

    return get_delete_statement("augur_operations", "user_groups")

def get_config_delete_statement():

    return get_delete_statement("augur_operations", "config")

def get_repo_related_delete_statements(table_list):
    """Takes a list of tables related to the RepoLoadController class and generates a delete statement.

    Args:
        table_list: list of table names. Valid table names are 
        "user_repos" or "user_repo", "repo" or "repos", "repo_groups" or "repo_group:, "user" or "users", and "config"

    """

    query_list = []
    if "user_repos" in table_list or "user_repo" in table_list:
        query_list.append(get_user_repo_delete_statement())

    if "user_groups" in table_list or "user_group" in table_list:
        query_list.append(get_user_group_delete_statement())

    if "repos" in table_list or "repo" in table_list:
        query_list.append(get_repo_delete_statement())

    if "repo_groups" in table_list or "repo_group" in table_list:
        query_list.append(get_repo_group_delete_statement())

    if "users" in table_list or "user" in table_list:
        query_list.append(get_user_delete_statement())

    if "config" in table_list:
        query_list.append(get_config_delete_statement())

    return " ".join(query_list)

######## Helper Functions to add github api keys from prod db to test db #################
def add_keys_to_test_db(test_db_engine):

    row = None
    section_name = "Keys"
    setting_name = "github_api_key"
    with DatabaseSession(logger) as session:
        query = session.query(Config).filter(Config.section_name==section_name, Config.setting_name==setting_name)
        row = execute_session_query(query, 'one')

    with DatabaseSession(logger, test_db_engine) as test_session:
        new_row = Config(section_name=section_name, setting_name=setting_name, value=row.value, type="str")
        test_session.add(new_row)
        test_session.commit()


######## Helper Functions to get insert statements #################

def get_repo_insert_statement(repo_id, rg_id, repo_url="place holder url", repo_status="New"):

    return """INSERT INTO "augur_data"."repo" ("repo_id", "repo_group_id", "repo_git", "repo_path", "repo_name", "repo_added", "repo_status", "repo_type", "url", "owner_id", "description", "primary_language", "created_at", "forked_from", "updated_at", "repo_archived_date_collected", "repo_archived", "tool_source", "tool_version", "data_source", "data_collection_date") VALUES ({}, {}, '{}', NULL, NULL, '2022-08-15 21:08:07', '{}', '', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 'CLI', '1.0', 'Git', '2022-08-15 21:08:07');""".format(repo_id, rg_id, repo_url, repo_status)

def get_repo_group_insert_statement(rg_id):

    return """INSERT INTO "augur_data"."repo_groups" ("repo_group_id", "rg_name", "rg_description", "rg_website", "rg_recache", "rg_last_modified", "rg_type", "tool_source", "tool_version", "data_source", "data_collection_date") VALUES ({}, 'Default Repo Group', 'The default repo group created by the schema generation script', '', 0, '2019-06-03 15:55:20', 'GitHub Organization', 'load', 'one', 'git', '2019-06-05 13:36:25');""".format(rg_id)

def get_user_insert_statement(user_id):

    return """INSERT INTO "augur_operations"."users" ("user_id", "login_name", "login_hashword", "email", "first_name", "last_name", "admin") VALUES ({}, 'bil', 'pass', 'b@gmil.com', 'bill', 'bob', false);""".format(user_id)

def get_user_group_insert_statement(user_id, group_name, group_id=None):

    if group_id:
        return """INSERT INTO "augur_operations"."user_groups" ("group_id", "user_id", "name") VALUES ({}, {}, '{}');""".format(group_id, user_id, group_name)

    return """INSERT INTO "augur_operations"."user_groups" (user_id", "name") VALUES (1, 'default');""".format(user_id, group_name)


######## Helper Functions to get retrieve data from tables #################

def get_repos(connection, where_string=None):

    query_list = []
    query_list.append('SELECT * FROM "augur_data"."repo"')

    if where_string:
        if where_string.endswith(";"):
             query_list.append(where_string[:-1])

        query_list.append(where_string)

    query_list.append(";")

    query = s.text(" ".join(query_list))

    return connection.execute(query).fetchall()

def get_user_repos(connection):

    return connection.execute(s.text("""SELECT * FROM "augur_operations"."user_repos";""")).fetchall()


######## Helper Functions to get repos in an org #################

def get_org_repos(org_name, session):

    attempts = 0
    while attempts < 10:
        result = hit_api(session.oauths, ORG_REPOS_ENDPOINT.format(org_name), logger)

        # if result is None try again
        if not result:
            attempts += 1
            continue

        response = result.json()

        if response:
            return response

    return None

def get_org_repo_count(org_name, session):

    repos = get_org_repos(org_name, session)
    return len(repos)


def test_is_valid_repo():

    with GithubTaskSession(logger) as session:

        controller = RepoLoadController(session)

        assert controller.is_valid_repo("hello world") is False
        assert controller.is_valid_repo("https://github.com/chaoss/hello") is False
        assert controller.is_valid_repo("https://github.com/hello124/augur") is False
        assert controller.is_valid_repo("https://github.com//augur") is False
        assert controller.is_valid_repo("https://github.com/chaoss/") is False
        assert controller.is_valid_repo("https://github.com//") is False
        assert controller.is_valid_repo("https://github.com/chaoss/augur") is True
        assert controller.is_valid_repo("https://github.com/chaoss/augur/") is True
        assert controller.is_valid_repo("https://github.com/chaoss/augur.git") is True


def test_add_repo_row(test_db_engine):

    clear_tables = ["repo", "repo_groups"]
    clear_tables_statement = get_repo_related_delete_statements(clear_tables)

    try:
        data = {"rg_id": 1, "repo_id": 1, "tool_source": "Frontend",
                "repo_url": "https://github.com/chaoss/augur"}

        with test_db_engine.connect() as connection:

            query_statements = []
            query_statements.append(clear_tables_statement)
            query_statements.append(get_repo_group_insert_statement(data["rg_id"]))
            query = s.text("".join(query_statements))

            connection.execute(query)

        with DatabaseSession(logger, test_db_engine) as session:

            assert RepoLoadController(session).add_repo_row(data["repo_url"], data["rg_id"], data["tool_source"]) is not None

        with test_db_engine.connect() as connection:

            result = get_repos(connection, where_string=f"WHERE repo_git='{data['repo_url']}'")
            assert result is not None
            assert len(result) > 0

    finally:
        with test_db_engine.connect() as connection:
            connection.execute(clear_tables_statement)


def test_add_repo_row_with_updates(test_db_engine):

    clear_tables = ["user_repos", "repo", "repo_groups", "users"]
    clear_tables_statement = get_repo_related_delete_statements(clear_tables)

    try:
        data = {"old_rg_id": 1, "new_rg_id": 2, "repo_id": 1, "repo_id_2": 2, "tool_source": "Test",
                "repo_url": "https://github.com/chaoss/augur", "repo_url_2": "https://github.com/chaoss/grimoirelab-perceval-opnfv",  "repo_status": "Complete"}

        with test_db_engine.connect() as connection:

            query_statements = []
            query_statements.append(clear_tables_statement)
            query_statements.append(get_repo_group_insert_statement(data["old_rg_id"]))
            query_statements.append(get_repo_group_insert_statement(data["new_rg_id"]))
            query_statements.append(get_repo_insert_statement(data["repo_id"], data["old_rg_id"], repo_url=data["repo_url"], repo_status=data["repo_status"]))
            query = s.text("".join(query_statements))

            connection.execute(query)

        with DatabaseSession(logger, test_db_engine) as session:

            result =  RepoLoadController(session).add_repo_row(data["repo_url"], data["new_rg_id"], data["tool_source"]) is not None
            assert result == data["repo_id"]

        with test_db_engine.connect() as connection:

            result = get_repos(connection, where_string=f"WHERE repo_git='{data['repo_url']}'")
            assert result is not None
            assert len(result) == 1

            value = dict(result[0])
            assert value["repo_status"] == data["repo_status"]
            assert value["repo_group_id"] == data["new_rg_id"]

    finally:
        with test_db_engine.connect() as connection:
            connection.execute(clear_tables_statement)


def test_add_repo_to_user_group(test_db_engine):

    clear_tables = ["user_repos", "user_groups", "repo", "repo_groups", "users"]
    clear_tables_statement = get_repo_related_delete_statements(clear_tables)

    try:
        with test_db_engine.connect() as connection:

            data = {"repo_id": 1, "user_id": 2, "user_repo_group_id": 1, "user_group_id": 1, "user_group_name": "test_group"}

            query_statements = []
            query_statements.append(clear_tables_statement)
            query_statements.append(get_repo_group_insert_statement(data["user_repo_group_id"]))
            query_statements.append(get_repo_insert_statement(data["repo_id"], data["user_repo_group_id"]))
            query_statements.append(get_user_insert_statement(data["user_id"]))
            query_statements.append(get_user_group_insert_statement(data["user_id"], data["user_group_name"], data["user_group_id"]))
            query = s.text("".join(query_statements))

            connection.execute(query)

        with DatabaseSession(logger, test_db_engine) as session:

            RepoLoadController(session).add_repo_to_user_group(data["repo_id"], data["user_group_id"])

        with test_db_engine.connect() as connection:

            query = s.text("""SELECT * FROM "augur_operations"."user_repos" WHERE "group_id"=:user_group_id AND "repo_id"=:repo_id""")

            result = connection.execute(query, **data).fetchall()
            assert result is not None
            assert len(result) > 0

    finally:
        with test_db_engine.connect() as connection:
            connection.execute(clear_tables_statement)


def test_add_frontend_repos_with_duplicates(test_db_engine):

    clear_tables = ["user_repos", "user_groups", "repo", "repo_groups", "users", "config"]
    clear_tables_statement = get_repo_related_delete_statements(clear_tables)

    try:
        with test_db_engine.connect() as connection:

            url = "https://github.com/operate-first/operate-first-twitter"

            data = {"user_id": 2, "repo_group_id": DEFAULT_REPO_GROUP_IDS[0], "user_group_name": "test_group", "user_group_id": 1}

            query_statements = []
            query_statements.append(clear_tables_statement)
            query_statements.append(get_repo_group_insert_statement(data["repo_group_id"]))
            query_statements.append(get_user_insert_statement(data["user_id"]))
            query_statements.append(get_user_group_insert_statement(data["user_id"], data["user_group_name"], data["user_group_id"]))

            connection.execute("".join(query_statements))
        
        add_keys_to_test_db(test_db_engine)

        with GithubTaskSession(logger, test_db_engine) as session:

            controller = RepoLoadController(session)
            result = controller.add_frontend_repo(url, data["user_id"], data["user_group_name"])
            result2 = controller.add_frontend_repo(url, data["user_id"], data["user_group_name"])

            assert result["status"] == "Repo Added"
            assert result2["status"] == "Repo Added"

        with test_db_engine.connect() as connection:

            result = get_repos(connection)
            assert result is not None
            assert len(result) == 1
            assert dict(result[0])["repo_git"] == url

    finally:
        with test_db_engine.connect() as connection:
            connection.execute(clear_tables_statement)


def test_add_frontend_repos_with_invalid_repo(test_db_engine):

    clear_tables = ["user_repos", "user_groups", "repo", "repo_groups", "users", "config"]
    clear_tables_statement = get_repo_related_delete_statements(clear_tables)

    try:
        with test_db_engine.connect() as connection:

            url = "https://github.com/chaoss/whitepaper"

            data = {"user_id": 2, "repo_group_id": 5, "user_group_name": "test_group", "user_group_id": 1}

            query_statements = []
            query_statements.append(clear_tables_statement)
            query_statements.append(get_repo_group_insert_statement(data["repo_group_id"]))
            query_statements.append(get_user_insert_statement(data["user_id"]))
            query_statements.append(get_user_group_insert_statement(data["user_id"], data["user_group_name"], data["user_group_id"]))

            connection.execute("".join(query_statements))

        add_keys_to_test_db(test_db_engine)

        with GithubTaskSession(logger, test_db_engine) as session:

            result = RepoLoadController(session).add_frontend_repo(url, data["user_id"], data["user_group_name"])

            assert result["status"] == "Invalid repo"

        with test_db_engine.connect() as connection:

            result = get_repos(connection)
            assert result is not None
            assert len(result) == 0

    finally:
        with test_db_engine.connect() as connection:
            connection.execute(clear_tables_statement)


def test_add_frontend_org_with_invalid_org(test_db_engine):

    clear_tables = ["user_repos", "user_groups", "repo", "repo_groups", "users", "config"]
    clear_tables_statement = get_repo_related_delete_statements(clear_tables)

    try:

        data = {"user_id": 2, "repo_group_id": DEFAULT_REPO_GROUP_IDS[0], "org_name": "chaosssss", "user_group_name": "test_group", "user_group_id": 1}

        with test_db_engine.connect() as connection:

            query_statements = []
            query_statements.append(clear_tables_statement)
            query_statements.append(get_repo_group_insert_statement(data["repo_group_id"]))
            query_statements.append(get_user_insert_statement(data["user_id"]))
            query_statements.append(get_user_group_insert_statement(data["user_id"], data["user_group_name"], data["user_group_id"]))

            connection.execute("".join(query_statements))

        add_keys_to_test_db(test_db_engine)
        with GithubTaskSession(logger, test_db_engine) as session:

            url = f"https://github.com/{data['org_name']}/"
            result = RepoLoadController(session).add_frontend_org(url, data["user_id"], data["user_group_name"])
            assert result["status"] == "Invalid org"

        with test_db_engine.connect() as connection:

            result = get_repos(connection)
            assert result is not None
            assert len(result) == 0

    finally:
        with test_db_engine.connect() as connection:
            connection.execute(clear_tables_statement)


def test_add_frontend_org_with_valid_org(test_db_engine):

    clear_tables = ["user_repos", "user_groups", "repo", "repo_groups", "users", "config"]
    clear_tables_statement = get_repo_related_delete_statements(clear_tables)

    try:
        with test_db_engine.connect() as connection:

            data = {"user_id": 2, "repo_group_id": DEFAULT_REPO_GROUP_IDS[0], "org_name": VALID_ORG["org"], "user_group_name": "test_group", "user_group_id": 1}

            query_statements = []
            query_statements.append(clear_tables_statement)
            query_statements.append(get_repo_group_insert_statement(data["repo_group_id"]))
            query_statements.append(get_user_insert_statement(data["user_id"]))
            query_statements.append(get_user_group_insert_statement(data["user_id"], data["user_group_name"], data["user_group_id"]))

            connection.execute("".join(query_statements))

        add_keys_to_test_db(test_db_engine)

        with GithubTaskSession(logger, test_db_engine) as session:

            url = "https://github.com/{}/".format(data["org_name"])
            result = RepoLoadController(session).add_frontend_org(url, data["user_id"], data["user_group_name"])
            print(result)
            assert result["status"] == "Org repos added"

        with test_db_engine.connect() as connection:

            result = get_repos(connection)
            assert result is not None
            assert len(result) == VALID_ORG["repo_count"]

            user_repo_result = get_user_repos(connection)
            assert user_repo_result is not None
            assert len(user_repo_result) == VALID_ORG["repo_count"]
            
    finally:
        with test_db_engine.connect() as connection:
            connection.execute(clear_tables_statement)


def test_add_cli_org_with_valid_org(test_db_engine):

    clear_tables = ["user_repos", "user_groups", "repo", "repo_groups", "users", "config"]
    clear_tables_statement = get_repo_related_delete_statements(clear_tables)

    try:
        with test_db_engine.connect() as connection:

            data = {"user_id": CLI_USER_ID, "repo_group_id": 5, "org_name": VALID_ORG["org"]}

            query_statements = []
            query_statements.append(clear_tables_statement)
            query_statements.append(get_repo_group_insert_statement(data["repo_group_id"]))
            query_statements.append(get_user_insert_statement(data["user_id"]))


            connection.execute("".join(query_statements))

        repo_count = None

        add_keys_to_test_db(test_db_engine)

        with GithubTaskSession(logger, test_db_engine) as session:

            result = RepoLoadController(session).add_cli_org(data["org_name"])
            print(result)

        with test_db_engine.connect() as connection:

            result = get_repos(connection)
            assert result is not None
            assert len(result) == VALID_ORG["repo_count"]

            user_repo_result = get_user_repos(connection)
            assert user_repo_result is not None
            assert len(user_repo_result) == VALID_ORG["repo_count"]

    finally:
        with test_db_engine.connect() as connection:
            pass
            # connection.execute(clear_tables_statement)


def test_add_cli_repos_with_duplicates(test_db_engine):

    clear_tables = ["user_repos", "repo", "repo_groups", "users", "config"]
    clear_tables_statement = get_repo_related_delete_statements(clear_tables)

    try:
        with test_db_engine.connect() as connection:

            data = {"user_id": CLI_USER_ID, "repo_group_id": 5, "org_name": "operate-first", "repo_name": "operate-first-twitter"}
            url = f"https://github.com/{data['org_name']}/{data['repo_name']}"

            query_statements = []
            query_statements.append(clear_tables_statement)
            query_statements.append(get_repo_group_insert_statement(data["repo_group_id"]))
            query_statements.append(get_user_insert_statement(data["user_id"]))

            connection.execute("".join(query_statements))

        add_keys_to_test_db(test_db_engine)

        with GithubTaskSession(logger, test_db_engine) as session:

            repo_data = {"url": url, "repo_group_id": data["repo_group_id"]}

            controller = RepoLoadController(session)
            controller.add_cli_repo(repo_data)
            controller.add_cli_repo(repo_data)

        with test_db_engine.connect() as connection:

            result = get_repos(connection)

            assert result is not None
            assert len(result) == 1
            assert dict(result[0])["repo_git"] == url

    finally:
        with test_db_engine.connect() as connection:
            connection.execute(clear_tables_statement)



def test_convert_group_name_to_id(test_db_engine):

    clear_tables = ["user_repos", "repo", "repo_groups", "users"]
    clear_tables_statement = get_repo_related_delete_statements(clear_tables)

    try:
        with test_db_engine.connect() as connection:

            data = {"user_id": 1, "group_name": "test_group_name", "group_id": 1}
            url = f"https://github.com/{data['org_name']}/{data['repo_name']}"

            query_statements = []
            query_statements.append(clear_tables_statement)
            query_statements.append(get_user_insert_statement(data["user-id"]))
            query_statements.append(get_user_group_insert_statement(data["user_id"], data["group_name"], data["group_id"]))

            connection.execute("".join(query_statements))

        with GithubTaskSession(logger, test_db_engine) as session:

            repo_data = {"url": url, "repo_group_id": data["repo_group_id"]}

            controller = RepoLoadController(session)
            group_id = controller.convert_group_name_to_id(data["user_id"], data["group_name"])

            assert group_id is not None
            assert group_id == data["group_id"]

    finally:
        with test_db_engine.connect() as connection:
            connection.execute(clear_tables_statement)






