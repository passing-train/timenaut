import logging
from typing import List, Tuple

import PySide2.QtSql as QtSql

from timewire.core.models.process_heartbeat import ProcessHeartbeat
from timewire.core.models.process import Process
from timewire.core.models.window import Window
from timewire.util.database_error import DatabaseError
from timewire.util.util import get_data_file_location


def connect() -> None:
    db = QtSql.QSqlDatabase.addDatabase("QSQLITE")
    db.setDatabaseName(get_data_file_location())

    if not db.open():
        raise DatabaseError("Could not open database!")

    logging.info(f"Connected to database {get_data_file_location()}")
    try:
        create_tables()
    except DatabaseError as e:
        logging.error(e)
        raise DatabaseError("Error creating tables")


def create_tables() -> None:
    query = QtSql.QSqlQuery()
    if not query.exec_("PRAGMA foreign_keys = ON;"):
        raise DatabaseError(query.lastError())

    if not query.exec_("CREATE TABLE IF NOT EXISTS processes("
                       "id INTEGER PRIMARY KEY, "
                       "path TEXT);"):  # text may be NULL because of Wayland sloppy support
        raise DatabaseError(query.lastError())

    if not query.exec_("CREATE TABLE IF NOT EXISTS windows("
                       "id INTEGER PRIMARY KEY, "
                       "process_id INTEGER NOT NULL, "
                       "title TEXT NOT NULL,"
                       "FOREIGN KEY (process_id) REFERENCES processes(id));"):
        raise DatabaseError(query.lastError())

    if not query.exec_("CREATE TABLE IF NOT EXISTS heartbeats("
                       "process_id INTEGER NOT NULL,"
                       "window_id INTEGER NOT NULL,"
                       "start_time INTEGER NOT NULL,"
                       "end_time INTEGER NOT NULL,"
                       "FOREIGN KEY (process_id) REFERENCES processes(id), "
                       "FOREIGN KEY (window_id) REFERENCES windows(id));"):
        raise DatabaseError(query.lastError())
    logging.info("Created database tables")


def add_process(process: Process) -> int:
    query = QtSql.QSqlQuery()

    # Check if the process already exists in the database
    query.prepare("SELECT * FROM processes WHERE path = :path")
    query.bindValue(":path", process.path)
    if not query.exec_():
        raise DatabaseError(query.lastError())
    else:
        # If the process already exists
        if query.next():
            return query.value(0)

    query.prepare("INSERT INTO processes (path) VALUES (:path)")
    query.bindValue(":path", process.path)
    if not query.exec_():
        raise DatabaseError(query.lastError())
    else:
        return query.lastInsertId()


def add_window(window: Window, process_id: int) -> int:
    query = QtSql.QSqlQuery()

    # Check if the window already exists in the database
    query.prepare("SELECT * FROM windows WHERE title = :title")
    query.bindValue(":title", window.title)
    if not query.exec_():
        raise DatabaseError(query.lastError())
    else:
        # If the window already exists
        if query.next():
            return query.value(0)

    query.prepare("INSERT INTO windows (title, process_id) VALUES (:title, :process_id)")
    query.bindValue(":title", window.title)
    query.bindValue(":process_id", process_id)
    if not query.exec_():
        raise DatabaseError(query.lastError())
    else:
        return query.lastInsertId()


# TODO: put into class?
last_process_id = None
last_window_id = None
last_start_time = None


def add_heartbeat(heartbeat: ProcessHeartbeat) -> None:
    global last_process_id
    global last_window_id
    global last_start_time

    if not heartbeat.is_valid():
        return

    process_id = add_process(heartbeat.process)
    window_id = add_window(heartbeat.window, process_id)

    if process_id == last_process_id and window_id == last_window_id:
        query = QtSql.QSqlQuery()
        query.prepare(
            "UPDATE heartbeats "
            "SET end_time=:end_time "
            "WHERE start_time=:last_start_time")
        query.bindValue(":last_start_time", last_start_time)
        query.bindValue(":end_time", int(heartbeat.time))
        if not query.exec_():
            raise DatabaseError(query.lastError())
    else:
        query = QtSql.QSqlQuery()
        query.prepare(
            "INSERT INTO heartbeats (process_id, window_id, start_time, end_time) "
            "VALUES (:process_id, :window_id, :datetime, :datetime)")
        query.bindValue(":process_id", process_id)
        query.bindValue(":window_id", window_id)
        query.bindValue(":datetime", int(heartbeat.time))
        if not query.exec_():
            raise DatabaseError(query.lastError())

        last_process_id = process_id
        last_window_id = window_id
        last_start_time = int(heartbeat.time)


def get_window_data() -> List[Tuple[Process, Window, int]]:
    query = QtSql.QSqlQuery()

    query.prepare(
        """
        SELECT path, title, SUM(difference)
        FROM heartbeats
        JOIN 
            (SELECT start_time, end_time - start_time AS difference FROM heartbeats) d 
        ON d.start_time=heartbeats.start_time
        JOIN processes p on heartbeats.process_id = p.id
        JOIN windows w on heartbeats.window_id = w.id
        GROUP BY heartbeats.process_id, window_id
        ORDER BY SUM(difference) DESC
        """
    )

    results = []

    if not query.exec_():
        raise DatabaseError(query.lastError())
    else:
        while query.next():
            path = Process(query.value(0))
            title = Window(query.value(1))
            count = query.value(2)
            results.append((path, title, count))

    return results


def get_process_data() -> List[Tuple[Process, int]]:
    query = QtSql.QSqlQuery()

    query.prepare(
        """
        SELECT path, SUM(difference)
        FROM heartbeats
        JOIN 
            (SELECT start_time, end_time - start_time AS difference FROM heartbeats) d 
        ON d.start_time=heartbeats.start_time
        JOIN processes p on heartbeats.process_id = p.id
        GROUP BY process_id
        ORDER BY SUM(difference) DESC
        """
    )

    results = []

    if not query.exec_():
        raise DatabaseError(query.lastError())
    else:
        while query.next():
            path = Process(query.value(0))
            count = query.value(1)
            results.append((path, count))

    return results
